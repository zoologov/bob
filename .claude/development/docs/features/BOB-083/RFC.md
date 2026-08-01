> **Status:** Approved
> **Type:** feature (Тир-3 T3.C⁺)
> **Created:** 2026-08-01
> **Issue:** BOB-083

# RFC — Интерактивный терминал Claude Code в личке (двусторонний)

## Резюме решения

Четыре потока: (0) **входящий owner-DM доходит до Боба** (multibot сейчас дропает DM — фундамент, чинит
и BOB-082 `/code`-из-лички); (1) **персистентный интерактивный runner** (`claude -p --input-format
stream-json --output-format stream-json` с ОТКРЫТЫМ stdin — сейчас one-shot без stdin); (2)
**интерактивная сессия** (новое состояние + держит живой процесс + прямой kill); (3) **интейк-режим**
(реплики owner'а из лички → stdin; команды входа/выхода). Вывод реюзит `_DmLiveStreamer`/
`render_stream_event` BOB-082. Всё owner-only, DM-only, за флагом `coder.interactive`; main
неприкосновенен (worktree + PR-гейт).

## Разведанные seam-точки (авторитетно)

- **Runner (one-shot, без stdin):** `claude_runner.py:87-122` argv `claude -p <prompt> --output-format
  stream-json …`; спавн `_ExecStreamRunner.__call__:139-172` (`create_subprocess_exec`, **stdin не
  передан**, `proc` — выброшенный локал, read-loop `stdout.readline()`); порт `ClaudeCodeRunner`
  (`coding/ports.py:29-49`, нет write). Валидные режимы `_ALLOWED_MODES={plan,acceptEdits}`
  (`claude_runner.py:42`).
- **Сессия:** `state.py:42-60` (`CodingSessionState`, `EXECUTING` только из `PLAN_READY`; `can_stop`
  любой non-terminal `:130`), `entities.py:32-70` (нет proc-handle/типа сессии), `coding_assistant.py`
  (start:270 / approve_plan:315 / stop:344 / `_run`-эфемерен в `aclosing`; kill кооперативный
  «break loop» через `_cancelled:352→proc.kill` в `finally`). Стор `session_store.py:50-106`
  (новое состояние round-trip'ит как TEXT).
- **🔴 Интейк-роут (DM дропается):** `multibot.py:532-566 _route_by_content` — `bob_scope.matches` только
  супергруппа; owner-DM → `UNROUTABLE`, дроп. Per-chat воркер `intake/dispatcher.py:126-173`. In-turn
  consume-гейт `handle_message.py:1373` (`maybe_route_coding`→return) / `precompose_gate.py:97-128`
  (сейчас без `is_group`/`chat_id`). Сигнал `is_group` — `events.py:65-73` (BOB-082).
- **Команды:** `guppi.py:303-322` (owner-gate + `chat_id==general`), `_dispatch_coding:469-490`,
  `_run_code:492-507` (approve/stop/status/start). NL — `coding_intent_router.py:87-135`, `intent.py`
  (is_stop:109/is_approval:119).
- **Стрим (реюз):** `live_stream.py:65-94` `_DmLiveStreamer` (output-only, `render_stream_event`);
  `stream_render.py:48-158` (по `event["type"]`; нет handler'а вопроса/permission); порт
  `LiveRunStreamer` (`coding_assistant.py:164-186`); wiring `wiring/coding.py:161-184`
  (`_build_dm_live_streamer`, `dev_dm`/`dev_dm_chat_id`).
- **Config/kill:** `runtime/config.py` (`_flag`/`_int`/`_str`; нет `interactive`); `bob.yaml:76-81` coder;
  `composition.py:505-517/833` coder-wiring; `git_worktree.py:63-141` (create/remove --force),
  `coding_assistant.py:582-589 _cleanup`.

## Поток 0 — Входящий owner-DM доходит (фундамент)

- **multibot route:** в `_route_by_content` добавить ветку: сообщение в **личке owner'а**
  (`chat_id == owner_dm_chat_id`, `is_group=False`/`chat.type==private`, sender==owner) → публикуется в
  пайплайн Боба (как `bob_scope.matches`-ветка). `owner_dm_chat_id` прокинуть в `MultiBotGateway`.
- **🔴 Reply в личку:** inner-gateway reply thread-locked на групповой топик (`_reply_thread_id`). Для
  DM-хода ответ должен идти в DM (`chat_id=owner_dm`, thread=None). Предпочтительно — **вторая
  scope-регистрация** бота Боба на DM-scope (`BotScope(chat_id=owner_dm, topic_id=None)`) → DM-ход
  роутится в DM-gateway, чей reply уходит в личку (реюз per-scope модели); fallback — chat-aware reply
  через `RichMarkdownSender.send(chat_id, message_thread_id=None)`. dev выбирает чище.
- Итог: owner пишет в личку → доходит → авторизуется owner-DM (BOB-082) → Боб отвечает В ЛИЧКУ. Чинит и
  BOB-082 `/code`-из-лички (S0). Гость/чужой DM по-прежнему дропается (только owner-DM).

## Поток 1 — Персистентный интерактивный runner

- Новый адаптер `InteractiveClaudeRunner` (рядом с `SubprocessClaudeRunner`, НЕ ломая one-shot) + порт:
  спавн `claude -p --input-format stream-json --output-format stream-json --verbose --permission-mode
  <mode>` c `stdin=PIPE, stdout=PIPE`; **держит `proc`-handle**; `feed(user_message)` — JSON-фрейм
  user-сообщения → `proc.stdin.write + drain`; `events()` — async-итератор `stdout.readline()`; `close()`
  — `proc.terminate()`/`kill` + drain. Чистое ядро: `encode_user_message(text) -> str` (stream-json
  user-фрейм) — mutation-цель. subprocess — `exec` (не shell), как сейчас.
- Тайм-аут/bounds наследуем; но интерактив живёт до `stop`/idle-таймаута (backstop).

## Поток 2 — Интерактивная сессия (state + lifecycle + kill)

- Новое состояние `INTERACTIVE` в `CodingSessionState` (+ рёбра `_PROGRESS`; `can_stop` уже покрывает).
  Тип сессии — новое поле/дискриминатор в `entities.py` (или отдельный менеджер).
- **Менеджер интерактив-сессии** (owner-only): `open(task, sender)` — worktree (реюз `git_worktree`) +
  спавн `InteractiveClaudeRunner`, держит живой `proc`-handle + подписку вывода на `_DmLiveStreamer`
  (реюз BOB-082); `feed(text)` — в stdin; `stop(sender)` — **прямой** `runner.close()` (terminate) +
  `_cleanup(worktree)` + состояние терминальное. 🔴 Kill прямой (не кооперативный break — живого read-loop
  для выхода недостаточно). Одна сессия за раз (гвард).
- worktree-изоляция + «никогда main» + PR-гейт BOB-039 — НЕ трогаем; правки owner'а в ветке → PR по
  существующему гейту (S4/INV-2).

## Поток 3 — Интейк-режим (реплики→stdin + команды)

- **Вход:** `/code -i <task>` (новая суб-верба в `_run_code`, owner-only; или NL «открой интерактив»
  предикатом в `intent.py`); только в личке + флаг `coder.interactive`. Открывает сессию (поток 2).
- **Steer (S2):** пока интерактив активен в личке — in-turn consume-гейт (по образцу
  `maybe_route_coding`, `handle_message.py:1373`): owner-plain-text (не команда `stop`) → `session.feed`
  → **consume хода** (не обычный Боб-ответ). Прокинуть `is_group`/`chat_id` в гейт (сейчас нет).
- **Выход/kill (S4):** `stop` → `session.stop` (прямой kill). Личка возвращается к обычному Бобу
  (INV-5). Явный режим: Боб в личке сообщает вход/выход интерактива.
- **Вопрос claude (S3):** claude пишет вопрос обычным assistant-событием (`render_stream_event`
  показывает) → owner отвечает репликой → `feed` в stdin. `permission_mode: acceptEdits` → правки без
  спросов (worktree), т.е. спец-suspend не нужен; при необходимости — handler события вопроса.

## Флаг / безопасность

`coder.interactive` (bool, default OFF; читать как `dev_dm`). OFF → интерактив недоступен (нет входа,
режим не активируется). owner-only (гейт `is_owner` + owner-DM authz), DM-only (is_group=False),
worktree-изоляция, main через PR-гейт (не трогаем), прямой kill-switch, idle/hard-таймаут backstop, одна
сессия. Осознанное ослабление гейта — ТОЛЬКО для правок-в-worktree под управлением owner'а, НЕ для main.

## Инварианты → реализация

- INV-0 → поток 0 (multibot DM-route + reply-в-личку).
- INV-1 → поток 1 (open-stdin runner) + поток 3 (реплики→feed).
- INV-2 → worktree + PR-гейт BOB-039 не трогаем (main неприкосновенен).
- INV-3 → owner-only + DM-only + флаг.
- INV-4 → прямой `proc.terminate()` на stop + worktree cleanup + таймаут.
- INV-5 → consume-гейт активен только в интерактив-режиме; явный вход/выход.

## Риски и меры

- **Живой subprocess течёт/зомби** → `proc`-handle держим, `stop`/таймаут/idle гарантируют terminate+drain;
  тест на kill (процесс убит, worktree снят). Одна сессия (гвард от накопления).
- **DM-reply уходит в группу** (поток 0) → тест: DM-ход отвечает В ЛИЧКУ, не в топик.
- **Гость/чужой DM** → только owner-DM роутится; остальное дропается (тест).
- **Режим залипает** (реплики уходят в stdin после смерти сессии) → consume-гейт строго по активной сессии;
  выход/kill сбрасывает; тест на возврат к обычному Бобу.
- **main задет** → worktree-изоляция + PR-гейт не трогаем; ревью проверяет невозможность мержа/пуша main.
- **Ослабление гейта** → осознанно, owner-only/DM-only/флаг/worktree; security-ревью отдельно.

## Тест-стратегия

- **Unit/TDD:** `encode_user_message` (stream-json user-фрейм); multibot DM-route (owner-DM→Bob, гость/
  чужой→drop); reply-в-личку; интерактив-сессия lifecycle (open/feed/stop, прямой kill, одна-сессия);
  consume-гейт (активна→feed, неактивна→обычный Боб); команды `/code -i`/exit owner-only. **mutation ≥85%**
  на `encode_user_message` + любых чистых предикатах режима.
- **BDD `.feature`** (через границу, fake runner/gateway): S0 DM доходит+ответ-в-личку, S1 открыть
  интерактив, S2 реплика→stdin, S4 stop→kill+возврат, S5 owner-only/DM-only/флаг-OFF.
- **Живой смоук (после активации флага):** 🔴 сперва feasibility — Боб шлёт owner'у в личку отчёт (тест
  DM-выхода); затем `/code -i` из лички → живой стрим + steer репликой + `stop`. Негатив: гость/группа не
  открывают интерактив; main недостижим.
