> **Status:** Approved
> **Type:** feature (Тир-3 T3.C⁺)
> **Created:** 2026-08-01
> **Issue:** BOB-083

# PLAN — BOB-083 (DAG + seam-точки)

## Seam-точки (авторитетно, из разведки)

- Runner: `coding/adapters/claude_runner.py:87-122` (argv) / `:139-172` (спавн, stdin НЕ передан) / порт
  `coding/ports.py:29-49`; режимы `_ALLOWED_MODES:42`.
- Сессия: `coding/state.py:42-60/79-84/130`, `coding/entities.py:32-70`, `coding/usecases/coding_assistant.py`
  (start:270/approve:315/stop:344/_run эфемерен/kill кооперативный `_cancelled:352→proc.kill finally`),
  стор `session_store.py:50-106`.
- Интейк: `multibot.py:532-566` (`_route_by_content`, DM→UNROUTABLE дроп), `intake/dispatcher.py:126-173`,
  consume-гейт `handle_message.py:1373` / `precompose_gate.py:97-128` (без is_group/chat_id), сигнал
  `events.py:65-73` (is_group).
- Команды: `guppi.py:303-322/469-490/492-507`, `coding_intent_router.py:87-135`, `intent.py:109/119`.
- Стрим (реюз): `coding/adapters/live_stream.py:65-94`, `coding/stream_render.py:48-158`, порт
  `coding_assistant.py:164-186`, wiring `runtime/wiring/coding.py:161-184`.
- Config/kill: `runtime/config.py` (`_flag`, нет interactive), `config/bob.yaml:76-81`,
  `composition.py:505-517/833`, `git_worktree.py:63-141`, `coding_assistant.py:582-589`.

## Беады

```
BOB-083 [feature] — интерактивный терминал Claude Code в личке (двусторонний)
├── .1 [dev] — ФУНДАМЕНТ: входящий owner-DM доходит до Боба (multibot route-ветка owner-DM→пайплайн) +
│              reply в личку (2-я scope-регистрация DM ИЛИ chat-aware reply). Гость/чужой DM → drop.
│              Чинит и BOB-082 /code-из-лички. Прокинуть owner_dm_chat_id в MultiBotGateway.
├── .2 [dev] — RUNNER: InteractiveClaudeRunner (рядом с one-shot, НЕ ломая): claude -p --input-format
│              stream-json --output-format stream-json, stdin=PIPE, держит proc-handle; feed(msg)/events()/
│              close()(terminate+drain). Чистое ядро encode_user_message(text)->stream-json user-фрейм. exec. deps .1
├── .3 [dev] — СЕССИЯ: состояние INTERACTIVE (+рёбра _PROGRESS/can_stop) + менеджер (owner-only): open(task)
│              worktree+спавн runner+подписка вывода на _DmLiveStreamer(реюз); feed(text)→stdin; stop→ПРЯМОЙ
│              runner.close()+_cleanup+терминал. Одна сессия. worktree/PR-гейт BOB-039 НЕ трогать. deps .2
├── .4 [dev] — ИНТЕЙК-РЕЖИМ: /code -i вход (owner-only, DM-only, флаг coder.interactive) + exit; consume-гейт
│              (образец maybe_route_coding, handle_message:1373): интерактив активен в личке → owner-plain-text
│              →session.feed→consume; прокинуть is_group/chat_id. Явный вход/выход (INV-5). deps .3
├── .5 [test] — unit (encode_user_message; multibot DM-route+reply-в-личку; сессия lifecycle/прямой-kill/одна;
│              consume-гейт активна/неактивна; команды owner-only) + BDD (S0 DM-доходит+ответ-в-личку / S1
│              открыть / S2 реплика→stdin / S4 stop→kill+возврат / S5 owner-only/DM-only/флаг-OFF) + mutation
│              ≥85% (encode_user_message + чистые предикаты режима). deps .4
├── .6 [review] — 🔴 SECURITY: main неприкосновенен (worktree+PR, мерж/пуш main невозможен); ослабление гейта
│              строго owner-only/DM-only/флаг; kill гарантирован (нет зомби); DM-route только owner (гость/
│              чужой drop); reply-в-личку не течёт в группу; режим не залипает; DDD. deps .5
└── .7 [tech-writer] — docs (coding интерактив-сессия/runner/стрим; social/transport DM-route; флаг
                     coder.interactive; ROADMAP T3.C⁺ отметка). deps .6
```

## Волны / критерии

Dev последовательно (.1→.4 — общие касания multibot/coding/intake; урок BOB-066). Test → review → tw → PR
→ self-merge → рестарт → активация → живой смоук + 🔴 **Боб шлёт owner'у в личку краткий отчёт** (тест DM-выхода).

🔴 **Живой смоук:** Боб пишет в личку отчёт (DM-выход работает?); затем `/code -i` из лички → живой стрим +
steer репликой + `stop`→kill+возврат к обычному Бобу; негатив: гость/группа не открывают, main недостижим.
Ядра mutation ≥85%.

## Риски (из RFC)

Живой subprocess зомби → proc-handle+stop+таймаут+одна-сессия; DM-reply в группу → тест; режим залипает →
consume строго по активной сессии; main задет → worktree+PR не трогаем; ослабление гейта → security-ревью.
