<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль coding — «Боб пишет код»

Гейтованный автономный кодинг: по команде owner'а Боб гоняет локальный `claude` CLI
над собственным репозиторием, собирает план, после явного апрува исполняет его в
изолированном worktree и открывает PR. Мержа в машине нет — Боб останавливается на
открытом PR, интеграцию в `main` делает owner вручную вне Боба. Второй путь —
интерактивный терминал в личке owner'а (BOB-083): живой двусторонний сеанс `claude`,
которым owner правит репликами, в том числе в долгоживущем рабочем месте, копящем работу
между сеансами (BOB-087.D). У этого пути PR-открывашки нет вовсе.

Это первый **вертикальный** модуль domain-first раскладки (BOB-062.1, срез 1/8 эпика
BOB-062): вся способность собрана в одном месте `src/bob/coding/`, а не размазана по
слоям `domain/` + `application/usecases/` + `infrastructure/`. Модуль охватывает три
слоя **внутри** одного bounded-context, поэтому в графе он несёт не-слойный тег
`module-vertical` (правило `architecture-layers` его рёбра пропускает), а внутреннюю
и внешнюю дисциплину держат path-glob `forbid_import`-правила в
`.beadloom/_graph/rules.yml`.

## Спецификация

### Раскладка модуля

```
src/bob/coding/
  ports.py            # layer=domain   — порты-протоколы способности
  __init__.py         # layer=domain   — фасад (CodingSession, предикаты, narrate, worktree_branch)
  state.py            # layer=domain   — машина состояний + чистые предикаты переходов
  entities.py         # layer=domain   — CodingSession (immutable value-object; claude_session_id для --resume, BOB-087.D1)
  naming.py           # layer=domain   — worktree_branch: эфемерная bob/<slug> + workspace_branch: долгоживущая bob/epic-<slug> (кириллица транслитерируется, BOB-087.D1/D5b)
  argv_policy.py      # layer=domain   — build_interactive_argv / extract_session_id: чем параметризуется живой claude и что берётся из init-кадра (BOB-087.D1/D4b)
  sandbox_policy.py   # layer=domain   — allowed_modes/is_allowed_mode/extra_dir_argv/is_safe_argv_value: политика owner-ослаблений изоляции (BOB-087.D2)
  resume_policy.py    # layer=domain   — select_resumable/is_confirmation_fresh: можно ли поднять приостановленную работу и какую (BOB-087.D3)
  narrate.py          # layer=domain   — stream-json событие Claude Code → нарратив-строка / None (сжато, для группы)
  stream_render.py    # layer=domain   — render_stream_event(verbose): событие→строка; verbose=интерактив (полный текст+rich+chunk_for_telegram) vs груп (краткий кэп). BOB-082/085
  intent.py           # layer=domain   — is_approval / is_stop (чистые предикаты NL-команд)
  interactive_intent.py # layer=domain — четыре чистых распознавателя DM-команд: parse_interactive_entry (/code -i), parse_interactive_workspace (/workspace), parse_interactive_resume (/resume), is_interactive_exit + is_confirmation/is_rejection (BOB-083, BOB-087.D3/D5b)
  session_voice.py    # layer=domain   — детерминированные шаблоны реплик в персоне Боба-оператора (человечные реакции взялся/готово-PR/провал/стоп, BOB-087.B2; + workspace/resume-реплики, BOB-087.D)
  work_facts.py       # layer=domain   — WorkFactsAccumulator/SessionKeyFacts/WorkOutcome: сворачивает поток stream-json в ОГРАНИЧЕННЫЙ снимок ключевых фактов (BOB-087.B1)
  usecases/           # layer=application
    coding_assistant.py       — CodingAssistant (оркестратор гейтед-сессии)
    distill_work_journal.py   — WorkJournalDistiller (порт) + Tier0-адаптер + parse_work_episodes: факты сессии → 1-3 операторских эпизода (BOB-087.B1)
    work_journal_recorder.py  — Distilling/NoOp рекордеры рабочего журнала (флаг memory.work_journal, BOB-087.B1)
    coding_context.py         — make_coding_context (арх-преамбула в claude-промпт)
    classify_coding_intent.py — ClassifyCodingIntent (Tier-0 классификатор «это dev-запрос?»)
    coding_intent_router.py   — CodingIntentRouter (NL-маршрутизация к гейтед-сессии)
    interactive_session.py    — InteractiveSessionManager (менеджер живой интерактив-сессии, БЕЗ PR-opener, BOB-083; + open_workspace/propose_resume/resolve_pending_resume/resume, BOB-087.D)
    interactive_intake.py     — InteractiveIntakeRouter (вход/steer→stdin/выход в личке, owner+DM, BOB-083; опциональный resume-seam, BOB-087.D3)
    recover_interactive_sessions.py — RecoverInteractiveSessions (свип осиротевших INTERACTIVE-строк на старте процесса, BOB-087.D5b)
  adapters/           # layer=infrastructure
    claude_runner.py    — SubprocessClaudeRunner (headless claude через subprocess, без shell; one-shot)
    interactive_runner.py — InteractiveClaudeRunner (персистентный claude с ОТКРЫТЫМ stdin, двусторонний, BOB-083; argv собирает argv_policy)
    git_worktree.py     — GitWorktree (изолированный worktree только на трекнутых файлах; ensure — идемпотентный долгоживущий workspace, BOB-087.D1)
    gh_pr.py            — GhPullRequestOpener (gh pr create; НИКОГДА merge)
    session_store.py    — SqliteCodingSessionStore (персист сессий через рестарт; by_branch — чтение всех сессий ветки, BOB-087.D3)
    indicator.py        — TypingKeepalive + StatusPanel (индикаторы работы в топике Боба)
    owner_notifier.py   — _CodingOwnerNotifier (нотификатор owner'а; переехал из app.py, BOB-062.7a)
    live_stream.py      — _DmLiveStreamer (полный лайв-стрим сырых событий в личку owner'а, BOB-082; firehose ботом GUPPI при coder.stream_via_guppi, BOB-087.A)
    _branch.py, _exec.py — внутренние shell-free хелперы адаптеров
```

### Машина состояний (чистый домен)

`CodingSessionState` (`state.py`) — строковый `StrEnum` (значение совпадает с
TEXT-колонкой SQLite). Жизненный цикл:

```
PROPOSED → PLANNING → PLAN_READY → EXECUTING → PR_OPEN  (успешный терминал)
                          │ (ГЕЙТ ПЛАНА)
CANCELLED / FAILED ← из любого нетерминального
```

`EXECUTING` достижимо **только** из `PLAN_READY` (непробиваемый гейт плана). Чистые
предикаты: `can_transition`, `can_start`, `can_approve_plan`, `can_stop` (kill-switch
из любого нетерминального), `is_terminal` (`PR_OPEN`/`DONE`/`CANCELLED`/`FAILED`).
`CodingSession` (`entities.py`) — immutable `frozen, slots` value-object без I/O и
часов: момент времени инжектится параметром `at` в мутаторы `with_state`/`with_plan`/
`with_worktree`/`with_pr_url`/`with_claude_session_id` (каждый возвращает новый объект).

### Оркестратор (application)

`CodingAssistant` (`usecases/coding_assistant.py`) — чисто-оркестрационный use-case
над чистым доменом и инжектированными портами (раннер, worktree, стор, PR-открывашка,
нотификатор owner, authz, часы, фабрика id) плюс опциональные сеймы индикаторов и
арх-контекста. Четыре owner-only метода: `start(task, sender)` (worktree + план без
правок → `PLAN_READY`, останавливается), `approve_plan(sender)` (гейт: только из
`PLAN_READY` → исполнение → PR → `PR_OPEN`), `stop(sender)` (kill-switch → `CANCELLED`
+ уборка worktree), `status(sender)`. Естественный язык (постановка задачи Бобу его
словами в топике) маршрутизируется `CodingIntentRouter` поверх Tier-0
`ClassifyCodingIntent`; NL-путь **не обходит ни одного гейта** — лишь выбирает, *когда*
звать `start`/`approve_plan`/`stop`.

🔴 **Dev-канал: лайв-стрим в личку (BOB-082, T3.C, за флагом `coder.dev_dm`).** По умолчанию
поток claude сжимается `narrate` в ~12 строк и льётся в **групповой топик** (кап
`_MAX_NARRATION`, чтобы не флудить группу, BOB-076). При `coder.dev_dm` ON поток вместо этого
идёт **полным лайв-стримом** в **личку** owner'а: `render_stream_event` (сырые события, не
lossy `narrate`) → `_DmLiveStreamer` (адаптер в DM `chat_id`, progressive `edit_message_text`
через `StatusPanel`, **без капа** — флуд в приватной личке уместен); группа получает лишь
короткий указатель `session_voice.dev_pointer()`. Маршрутизация — на **wiring** (порт
`LiveRunStreamer` держит use-case transport-free); стрим **односторонний** (без stdin —
двойной гейт и worktree-изоляция не ослаблены); OFF → поведение байт-в-байт как раньше.

🔴 **Интерактивный терминал: двусторонний (BOB-083, T3.C⁺, за флагом `coder.interactive`).**
Надстройка над односторонним стримом: owner не только видит поток, но и **направляет claude в
реальном времени**. `InteractiveClaudeRunner` (`adapters/interactive_runner.py`) держит
**персистентный** процесс `claude -p --input-format stream-json --output-format stream-json` с
**открытым stdin** (`open`/`feed`/`events`/`close`; kill — `terminate→grace→kill→reap`, идемпотентно);
`encode_user_message` (чистое ядро) кодирует реплику owner'а в stream-json user-фрейм.
`InteractiveSessionManager` (`usecases/interactive_session.py`) — менеджер живой сессии: `open` (worktree +
спавн + вывод в `_DmLiveStreamer`), `feed→stdin`, `stop→ПРЯМОЙ kill` + cleanup; **одна сессия за раз**.
Вход `/code -i`/выход `stop` + steer-consume-гейт (`interactive_intake.py` → `handle_message`) —
**owner-only, DM-only, за флагом**; режим не залипает (feed только пока сессия активна). 🔴 **Безопасность:**
новое состояние `INTERACTIVE` имеет пустой `_PROGRESS` (никогда не доходит до `EXECUTING`); менеджер
**структурно без PR-opener** — мерж/пуш в main НЕВОЗМОЖЕН; правки — в изолированном worktree `bob/<slug>`,
в main только через существующий PR-гейт owner'а. Осознанное ослабление двойного гейта — ТОЛЬКО для
правок-в-worktree под управлением owner'а.

🔴 **Интерактив-2: долгоживущее рабочее место и возобновление (BOB-087.D, флаг `coder.resume`, default
OFF).** Эфемерный интерактив BOB-083 удалял worktree на «стоп», поэтому накапливать работу между
сеансами было негде. Срез D добавляет второй, ДОЛГОЖИВУЩИЙ путь: owner заводит именованное рабочее
место, работает в нём, останавливается — и позже поднимает ту же сессию `claude` с телефона.

- **Команды owner'а в личке.** `/workspace <name> [task]` (синоним `/code -w <name> [task]`) — завести
  сеанс сразу в долгоживущем workspace; имя — первый токен, задача опущена → задачей становится само имя.
  `/resume <workspace>` (синоним `/code -r <workspace>`) — попросить поднять прошлую сессию. Ответ на
  вопрос-подтверждение — «да» либо «нет» ЦЕЛЫМ сообщением (`is_confirmation` / `is_rejection`, множества
  не пересекаются: «да, но сначала покажи дифф» подтверждением не считается). 🔴 Распознаётся ТОЛЬКО
  явная слэш-команда: свободный естественный язык здесь не разбирается и разбираться не будет —
  однажды дешёвая Tier-0 мис-классификация болтовни уже запустила runaway-кодер (BOB-076).
- **Двухшаговое подтверждение с TTL.** `/resume` сам по себе не поднимает ничего: `propose_resume`
  находит кандидата и задаёт вопрос голосом Боба, называя workspace и время той сессии (метка с зоной,
  чтобы owner с телефона не подтвердил не ту). `resolve_pending_resume` разрешает вопрос следующим ходом:
  «да» в окне `CONFIRMATION_TTL` (5 минут; окно двустороннее — часы, ушедшие назад, считаются
  протухшими) → `resume`; «нет» → отмена; любая другая реплика, ответ не того отправителя или истёкший
  TTL → вопрос СНИМАЕТСЯ, а ход идёт обычным разговорным путём. Вопрос не залипает, поэтому «да»,
  сказанное совсем по другому поводу, сессию не поднимет.
- **Поднять можно только остановленную сессию.** Кандидата выбирает чистая политика `select_resumable`:
  та же ветка, непустой `claude_session_id` и ТЕРМИНАЛЬНОЕ состояние (`state.is_terminal` — тот же
  единственный источник правды, что и у стора); из подходящих берётся самая свежая по `updated_at`.
  🔴 Live-attach невозможен структурно: живая `INTERACTIVE`-сессия кандидатом не является, а при живом
  сеансе весь resume-путь отказывает (одна сессия за раз) — два водителя за одним процессом `claude`
  встретиться не могут.
- **Дерево переживает «стоп».** `open_workspace` и `resume` работают в персистентном worktree
  (`PersistentWorkspace.ensure` на ветке `workspace_branch(name)` = `bob/epic-<slug>` — отдельное
  пространство имён, с эфемерной `bob/<slug>` не пересекается). `stop` такое дерево НЕ удаляет, как не
  удаляет его и провал спавна: в нём накоплена работа, ради которой сессию и поднимали. Маркер
  персистентности (`_LiveSession.persistent`) живёт в памяти рядом с живым сеансом — по имени ветки его
  выводить нельзя (эфемерная задача, названная «epic …», дала бы ту же форму), а колонки в БД он не
  требует.
- **Session-id claude.** `extract_session_id` берёт id из первого `init`-кадра потока, а `_capture_id`
  (проходной трансформер между раннером и стримером; событие уходит в личку НЕИЗМЕНЁННЫМ, рендер
  байт-в-байт прежний) сразу пишет его в `coding_session.claude_session_id`. Раньше id сохранялся только
  на «стоп», и краш посреди сеанса терял его навсегда; теперь `stop` — лишь бэкстоп.
- **Свип на старте процесса.** `RecoverInteractiveSessions` (вызывается из `Application.startup`)
  переводит осиротевшие `INTERACTIVE`-строки в `CANCELLED`. Живой сеанс существует ровно столько,
  сколько живёт держащий его процесс, поэтому увиденная на старте `INTERACTIVE`-строка по определению
  осиротела: процесс, который мог бы её закрыть, уже мёртв (деплой, краш, kill). Пока строка
  нетерминальна, `active()` отдаёт её как in-flight и гейтед-кодер на любую новую задачу отвечает «я уже
  в работе», а `select_resumable` её пропускает и поднимает более старую нить разговора. Свип нарочно
  узкий — только `INTERACTIVE`; гейтед стадии (`PLANNING` / `PLAN_READY` / `EXECUTING`) рестарт
  переживают намеренно (owner может одобрить план и назавтра). Свип идемпотентен и best-effort: уронить
  старт он права не имеет. Собирается безусловно — строка могла остаться от прежнего запуска с
  включённым интерактивом, а при отсутствии таких строк свип не пишет ничего.
- **Голос.** `workspace_opened` честно предупреждает, что дерево долгоживущее; `stopped_persistent`
  (парная к `stopped`) на остановке такой сессии не говорит ни слова про уборку — её не было;
  `interactive_setup_failed` отвечает на провал ПОДГОТОВКИ дерева («ничего не тронул» — в отличие от
  `interactive_failed`, где копия создавалась и убрана); `resume_confirm` / `resume_nothing` /
  `resume_cancelled` / `resumed` / `resume_failed` ведут двухшаговый путь. Реплика всегда идёт за
  реальной судьбой файлов — Боб не докладывает об уборке того, что осталось на месте.
- **Ни один сбой не уходит в молчание (BOB-087.D5b B2 + D5c N2).** Приёмный гейт глотает любое
  исключение роутера и уводит ход обычным chat-путём, поэтому падение внутри интерактива выглядело
  бы как «owner сказал «да», а Боб просто поболтал». Правило: подготовка дерева (`create` / `ensure`),
  поиск кандидата (`by_branch`) и персист — все под `try`, и любой сбой ПОСЛЕ спавна не только отвечает
  owner'у честной репликой, но и закрывает раннер, чтобы не остался неостановимый процесс без живой
  сессии (`_go_live` возвращает признак успеха, `_resumable_or_refusal` различает «сбой стора» и
  «нечего поднимать», `_persist_terminal` не теряет прощание).
- **OFF (default).** При выключенном `coder.resume` узкие порты `lookup` / `workspace` не инъектируются,
  а роутер вообще не держит resume-seam: ни `/workspace …`, ни `/resume …` не являются командами,
  персистентное дерево не создаётся, поведение байт-в-байт как в BOB-083.

🔴 **Owner-ослабления песочницы (BOB-087.D2, флаги `coder.allow_bypass` и `coder.extra_dirs`, оба
default OFF).** Оба решения принимает чистое ядро `sandbox_policy`, и оба по умолчанию инертны — argv
обоих раннеров остаётся байт-в-байт прежним.

- `allow_bypass` добавляет в allowlist `--permission-mode` РОВНО один режим — `bypassPermissions`
  (claude перестаёт спрашивать перед каждой правкой). База без флага — `{plan, acceptEdits}`; флаг
  расширяет её на один режим, а не открывает allowlist целиком. Совпадение точное: ни другой регистр, ни
  хвост (`plan; rm -rf /`), ни пустая строка не проходят.
- `extra_dirs` передаёт claude пути ВНЕ worktree парами `--add-dir`. Вход санитайзится: обрезка пробелов,
  отброс пустых, флагоподобных (ведущий `-` — иначе строка вида `--dangerously-skip-permissions`, стоящая
  в слоте значения, была бы прочитана парсером опций как отдельный ФЛАГ) и содержащих NUL, дедуп с
  сохранением порядка, кэп `MAX_EXTRA_DIRS = 8` на число оставленных директорий. Тот же примитив
  `is_safe_argv_value` санитайзит `resume_session_id` перед `--resume`: id приходит из колонки БД, а слот
  argv у него ровно тот же; негодный id читается как «сессии нет» — спавн проваливается в `--continue`
  или во фреш.

🔴 **Чего на самом деле стоит `allow_bypass: true`.** В самом Бобе интерактивный шов по-прежнему не
содержит ни push, ни merge, ни открытия PR — это остаётся правдой. Но `bypassPermissions` даёт claude
НЕПОДНАДЗОРНОЕ выполнение внутри linked worktree, а linked worktree делит с основным репозиторием
`.git`: те же объекты, те же **refs**, те же remotes и те же credentials. Оттуда выразимы
и `git push --force origin HEAD:main`, и `git branch -f main …`, и `gh pr merge`. Поэтому при флаге
неприкосновенность `main` (INV-2) перестаёт быть СТРУКТУРНОЙ гарантией и держится на суждении owner'а.
Выключенный флаг — состояние по умолчанию — оставляет пер-действенный гейт на каждую запись claude, и
именно этот гейт реально защищает ствол. Формулировка синхронизирована с секцией `coder` в
`infrastructure/config/loader.py` и докстрингами `runtime/wiring/coding.py`; смягчать её не следует.

🔴 **GUPPI-канал: firehose исполнителя (BOB-087.A, флаг `coder.stream_via_guppi`).** По канону GUPPI —
детерминированный **исполнитель**, Боб — разум. При флаге ON механический **firehose** (per-event narrate +
`_DmLiveStreamer` live-stream) уходит **ботом GUPPI**, а голос Боба (гейты `session_voice` «берусь/готово/
провал», `dev_pointer`, `narration_capped`, typing/панель) — **всегда ботом Боба** (`stream_notifier`-порт в
`CodingAssistant`). OFF (default) → всё ботом Боба, байт-в-байт. Отделяет механический поток от голоса Боба
(канон + анти-recall-яд: firehose вне истории бота Боба).

**UX терминала: курированный полный вывод + rich (BOB-085).** `render_stream_event(event, verbose=)`
двухрежимный: **интерактив-DM** (`verbose=True`, `_DmLiveStreamer(verbose=True)`) — ответы claude
**целиком** (не 200-символьный огрызок), markdown claude как markdown (`send_rich_message` рендерит
заголовки/списки/`код`), вызовы инструментов компактными rich-строками, tool-результаты щедро капнуты
(`_MAX_RESULT`) в код-блоке; длинный вывод чанкится `chunk_for_telegram` (≤4096, не рвёт ``` — закрывает/
переоткрывает fence на стыке). **Груп-нарратив** (BOB-082, `verbose=False`) сохраняет краткий кэп
байт-в-байт. Закрывает BOB-Issues #35 (форматирование) + #36 (обрезка).

🔴 **Дистиллированная рабочая память (BOB-087.B1, флаг `memory.work_journal`, default OFF).**
Чтобы Боб ПОМНИЛ, что делал в dev-сессии (первого-лица «операторские» воспоминания), но НЕ
захлебнулся сырым логом (урок BOB-076 флуд), поток чистится в два шага — накопление ключевых
фактов по ходу и дистилляция на конце.

- **Накопление (чистое ядро).** `WorkFactsAccumulator` (`work_facts.py`, I/O-free,
  детерминированно) сворачивает тот же поток stream-json событий, что уже порождает сессия, в
  маленький **ОГРАНИЧЕННЫЙ** снимок `SessionKeyFacts`: тронутые файлы (базовые имена, дедуп, кэп
  `_MAX_FILES=24`), прошли/упали ли тесты и короткие выжимки «что сломалось» (дедуп, обрезка,
  кэп `_MAX_ERRORS=8`). Это ДИСТИЛЛЯТ существа сессии, а НЕ firehose: system-init, чистая проза
  ассистента и неизвестные события — шум, игнорируются. `WorkOutcome` (`FINISHED`/`FAILED`/
  `ABORTED`) задаёт рамку исхода. Границы намеренны — неограниченное накопление вернуло бы флуд.
- **Дистилляция (Tier-0).** `WorkJournalDistiller` (порт, `usecases/distill_work_journal.py`) +
  `Tier0WorkJournalDistiller` (адаптер) сводят факты + исход в **1-3 ДЕТАЛЬНЫХ первого-лица
  операторских эпизода** («я попросил GUPPI починить краш стрима в `interactive_runner.py`; тесты
  падали на >64 КБ; подняли лимит буфера — позеленело»): один дешёвый Tier-0 вызов
  (`TaskType.WORK_JOURNAL`, локально — приватность dev-работы), зеркалит `ClassifyCodingIntent`.
  Чистый строитель промпта + чистый парсер `parse_work_episodes` (mutation-цель, кэп
  `_MAX_EPISODES=3`, снимает list-маркеры). Best-effort: сбой модели → ноль эпизодов, никогда не
  бросает в сессию.
- **Запись (веха, за флагом).** `DistillingWorkJournalRecorder` (`usecases/work_journal_recorder.py`)
  связывает снимок → дистиллятор → стор: на **конце** сессии (НЕ per-event) сводит факты в эпизоды
  и осаждает их через `work_episode_event` (эпизоды `work`, visibility owner-приватно). Любой сбой
  дистилляции/записи проглатывается и логируется — рабочий журнал НИКОГДА не роняет coding/
  interactive-сессию (урок Part D BOB-078); пустой снимок пропускается. `NoOpWorkJournalRecorder` —
  реализация для выключенного флага `memory.work_journal`: ноль записей, память байт-в-байт.
- **Шов в оркестраторе.** `CodingAssistant` держит узкий порт `WorkJournalRecorder` (default —
  внутренний null-объект `_NullWorkJournalRecorder`, композиционный корень подставляет реальный
  рекордер лишь при флаге ON). По ходу прогона сырой поток **tee**-ится через `_observe_facts` в
  `WorkFactsAccumulator` ПЕРВЫМ (только ключевые факты, сырое не хранится; tee не меняет прогон), а
  на терминале сессии (`FINISHED`/`FAILED`) вызывается `_journal` → `record_session`.

🔴 **Голос оператора (BOB-087.B2).** `session_voice.py` — ЧИСТЫЕ детерминированные шаблоны реплик
на гейтах сессии (`accepted`/`plan`/`pr`/`failed`/`no_changes`/`stopped` + панель-строки) в персоне
**Боба-оператора**: Боб дирижирует от первого лица, GUPPI — сухой исполнитель, на которого Боб
ссылается. Никакого LLM-вызова на сообщение (латентность/стоимость). Реплики — короткие живые
человечные реакции («взялся», «готово — вот PR», «чёрт, сломалось»), не журнал. Парная директива
персоны — `personality/voice.py::operator_stance()` (см. README домена personality).

### Адаптеры (infrastructure)

`SubprocessClaudeRunner` гоняет `claude` headless через `create_subprocess_exec`
(никогда не shell), с лимитами (таймаут/события/байты); режим валидируется allowlist-политикой
чистого ядра `sandbox_policy` — `{plan, acceptEdits}`, плюс `bypassPermissions` только под
owner-флагом `coder.allow_bypass` (BOB-087.D2). Argv интерактивного раннера собирает не адаптер,
а чистая политика `argv_policy.build_interactive_argv`; адаптер лишь доносит её вердикт до границы
процесса. `GitWorktree` создаёт worktree на новой ветке фиксированной
формы `bob/<slug>` — свежий worktree содержит **только трекнутые файлы**, поэтому
приватные данные Боба (`data/soul/`, `bob.db*`, `.env*`, `config/*` — все gitignored)
в нём физически отсутствуют. Его `ensure` (BOB-087.D1) обслуживает ДОЛГОЖИВУЩЕЕ дерево и
идемпотентен по-настоящему: зарегистрированные пути из `git worktree list --porcelain` сравниваются
с целевым по `Path.resolve()` с обеих сторон (porcelain печатает абсолютные пути, а
`coder.worktree_root` по умолчанию относительный `.worktrees`), а уже существующая ветка
ЧЕКАУТИТСЯ (`worktree add <path> <branch>`), а не пересоздаётся через `-b`. Без обеих половин
второй подъём того же workspace падал на `fatal: a branch named … already exists`, и обещание
«работа копится между сеансами» ломалось со второго сеанса (BOB-087.D5b, находка B1).
Третья половина — САМОИСЦЕЛЕНИЕ мёртвой регистрации (BOB-087.D5c, находка N1): если каталог
дерева исчез (`rm -rf .worktrees`, уборочный `git clean -xdff` — `.worktrees/` gitignored), git
всё равно продолжает печатать станзу, помечая её `prunable`, и вдобавок ОТКАЗЫВАЕТ в повторном
`add` («fatal: <branch> is already used by worktree at <мёртвый путь>»). Поэтому `ensure` зовёт
фиксированный `git worktree prune` ПЕРЕД листингом (чистит только бухгалтерию исчезнувших
деревьев — ни живое дерево, ни ветку, ни main), парсер отбрасывает `prunable`-станзы, а реюз
дополнительно требует, чтобы путь реально лежал на диске. Иначе owner получал бы мёртвый cwd
и лечил бы это только шеллом — которого у него с телефона нет.
`GhPullRequestOpener` строит единственную форму
`gh pr create --base main --head <branch>` (discrete argv, без shell) — merge-метода в
порте нет. `SqliteCodingSessionStore` round-trip'ит `CodingSession` (двойной гейт
честен и через границу процесса), включая колонку `claude_session_id`, и отдаёт `by_branch(branch)`
— все записанные сессии ветки, в любом состоянии (какую из них можно поднять, решает чистая
политика, поэтому стор не может разойтись с правилом «только остановленную»). Саму колонку
`coding_session.claude_session_id` заводит guarded ALTER-миграция
`_migrate_coding_session_claude_session_id` в ядре persistence (`CREATE TABLE IF NOT EXISTS` уже
существующую таблицу не меняет): она добавляется только когда её нет, легаси-строка получает `NULL` —
возобновлять по ней нечего, поведение прежнее.
🔴 **Резилентность `active()` (BOB-078 D):**
`active()` дёргается coding-router'ом на КАЖДОМ входящем сообщении, поэтому ОДНА битая строка
(`state` вне `CodingSessionState` → `ValueError`, битая дата) не должна ронять весь список —
иначе роутер бросает на каждом сообщении и Боб глохнет. `_try_row_to_session` оборачивает
`_row_to_session`: неразбираемую строку логирует и ПРОПУСКАЕТ (`ValueError`/`TypeError`),
валидные сессии возвращаются как обычно.

## Инварианты

- **Never-merge:** в порте `PullRequestOpener` и в модуле физически **нет** merge-пути
  и git-записи в защищённую ветку. Боб открывает PR и останавливается (`PR_OPEN` —
  успешный терминал).
- **PR ≠ merge:** `is_terminal(PR_OPEN)` истинно — завершённая сессия не блокирует
  новую, но нового пути в `EXECUTING` это не создаёт.
- **Двойной гейт плана:** `EXECUTING` достижимо только из `PLAN_READY`; на уровне
  домена (таблица переходов) и повторно на уровне use-case'а (`can_approve_plan`).
- **Worktree-изоляция:** приватные gitignored-данные отсутствуют в свежем worktree —
  Claude Code их не видит; `remove` проверяет containment (symlink-resolved потомок
  `worktree_root`).
- **Sender-is-bob / owner-гейт (defense-in-depth):** тройная owner-проверка —
  `_maybe_route_coding` пускает только `InterlocutorKind.OWNER`, роутер перепроверяет
  `is_owner`, use-case проверяет `OwnerCheck.is_owner` на каждом методе. Отправитель
  сообщений сессии — **бот Боба** (BOB-046), нарратив атрибутирован GUPPI (`GUPPI: …`).
- **NL-safe:** естественно-языковой путь не обходит гейтов; классификатор намерения
  консервативен (ложноположительное лишь предложит план за гейтом).
- **Off-by-default:** мастер-switch `coder.enabled` по умолчанию `false`; при выключенном
  флаге assistant не подключён и шов инертен. Так же выключены и все флаги среза D —
  `coder.resume`, `coder.allow_bypass`, `coder.extra_dirs`: при них ни `/workspace`, ни `/resume` не
  команды, allowlist режимов равен `{plan, acceptEdits}`, ни одного `--add-dir` в argv нет.
- **Никакого live-attach (BOB-087.D3):** возобновить можно ТОЛЬКО остановленную сессию —
  `select_resumable` требует терминального состояния (тот же `state.is_terminal`, что и у стора), а при
  живом сеансе resume-путь отказывает целиком. Двух водителей за одним процессом `claude` получить
  нечем.
- **Подтверждение обязательно (BOB-087.D3):** команда `/resume` только задаёт вопрос; сессию поднимает
  исключительно явное «да» того же owner'а в окне `CONFIRMATION_TTL` (5 минут). Всё прочее — иную
  реплику, чужой ответ, истёкший TTL — вопрос снимает, ничего не поднимая.
- **Персистентный workspace не удаляется (BOB-087.D):** ни `stop`, ни провал спавна не трогают дерево
  долгоживущего рабочего места, а реплика Боба идёт за реальной судьбой файлов (`stopped_persistent` —
  ни слова про уборку, которой не было). Эфемерный посессионный worktree убирается, как и раньше.
- **Argv-значения санитайзятся (BOB-087.D2/D5b):** всё, что попадает в argv из внешнего источника —
  `--add-dir` из конфига и `--resume` из колонки БД — проходит `is_safe_argv_value` (не пустое, без
  ведущего `-`, без NUL), поэтому строка вида `--dangerously-skip-permissions` не может встать в слот
  значения отдельным флагом.
- **🔴 INV-2 при `allow_bypass: true` держится не на структуре:** у Боба нет push/merge/PR-пути, но
  linked worktree делит с основным репозиторием `.git`, refs, remotes и credentials, а
  `bypassPermissions` даёт claude неподнадзорное выполнение. При включённом флаге неприкосновенность
  `main` — это суждение owner'а, а не гарантия кода. При выключенном (default) каждую запись claude
  по-прежнему пропускает пер-действенный гейт.
- **Shell-free:** все внешние вызовы (`claude`, `git`, `gh`) идут через
  `create_subprocess_exec` дискретными argv, без интерполяции метасимволов.
- **Резилентность приёма (BOB-078 D):** `active()` пропускает битую строку `coding_session`
  (`_try_row_to_session` глотает `ValueError`/`TypeError` и логирует), а не роняет весь список —
  одна порченая сессия не оглушает Боба на каждом входящем сообщении. Парный гейт на стороне
  application (`PreComposeGate.maybe_route_coding`) глотает любую ошибку роутера → chat-путь
  продолжается.

### Границы модуля (AaC)

Дисциплина держится path-glob `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ vertical modules):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/`;
- снаружи к `coding` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`).

Три cross-boundary ссылки узаконены по дизайну (не нарушения): `classify_coding_intent
→ application/router/llm_router` (общий shared-router вне модулей), `coding_context →
capabilities/introspection/privacy_guard` (TYPE_CHECKING-only; `PrivacyGuard` переехал
в вертикальный модуль `capabilities`, BOB-062.4) и `adapters/indicator →
infrastructure/telegram/gateway` (TYPE_CHECKING-only). Если любая станет runtime-импортом
— всплывёт в скане и подлежит переоценке.

🔴 **Бюджет размера узла (BOB-087.D3).** Общее правило `no-monster-modules` (потолок 200 символов на
feature-узел) теперь исключает `coding`, а для него заведён отдельный явный бюджет
`no-monster-modules-coding` — 220 символов. Это осознанная рекалибровка, а не маскировка: `coding` —
полная вертикаль способности (порты, чистые политики, use-cases, адаптеры claude/git/gh/Telegram),
честно разложенная по 35 файлам, крупнейший из которых несёт 34 символа. Срез D довёл узел до 213.
Общий потолок 200 остаётся зубастым для всех прочих узлов (следующий по величине — `conversation`,
178), а запас в 7 символов означает, что правило снова упадёт и потребует настоящего фикса. Настоящий
фикс — разбить сам УЗЕЛ (выделить интерактивный терминал в собственный feature-узел): дробление файлов
внутри домена счётчик не снижает. Долг заведён беадой `bob-6u2`.

## API

<!-- beadloom:track=src/bob/coding/ports.py -->

Модуль `src/bob/coding/ports.py` (порты-протоколы, только интерфейсы):
- `ClaudeCodeRunner` — шов headless-раннера Claude Code.
- `InteractiveRunner` — шов персистентного двустороннего раннера: `open(workdir, *, mode,
  resume_session_id=None, continue_session=False)` / `feed` / `events` / `close` + property
  `session_id`. Опции возобновления живут на порту с BOB-087.D3 (менеджер видит только порт, а
  поднимать сессию по сохранённому id должен именно он); дефолты сохраняют свежий спавн BOB-083.
- `Worktree` — шов изолированного git-worktree (`create` / `commit_and_push` / `remove`).
- `CodingSessionStore` — шов долговечного хранилища сессий.
- `ResumableSessionLookup` — узкий read-шов `by_branch(branch)` → все записанные сессии ветки
  (BOB-087.D3; отдельный порт, чтобы фейки `CodingSessionStore` остались валидны).
- `PersistentWorkspace` — узкий шов `ensure(branch)` → путь долгоживущего worktree
  (BOB-087.D3; отдельный порт, поэтому use-case, которому нужно только «обеспечить», не может
  выразить удаление).
- `PullRequestOpener` — шов открытия PR (merge-метода намеренно нет).

Фасад `src/bob/coding/__init__.py` re-export'ит: `CodingSession`, `CodingSessionState`,
`can_transition`, `can_start`, `can_approve_plan`, `can_stop`, `is_terminal`, `narrate`,
`worktree_branch`. Канонический импорт портов — `from bob.coding.ports import
ClaudeCodeRunner`; транзитный ports-шим `bob.domain.ports` удалён (BOB-062.8).

Ключевые точки входа:
- `state.py`: `can_transition(frm, to)`, `can_approve_plan(state)`, `can_stop(state)`,
  `is_terminal(state)` → `bool`.
- `entities.py`: `CodingSession` — поле `claude_session_id: str | None` и мутатор
  `with_claude_session_id(claude_session_id, *, at)` → `CodingSession` (BOB-087.D1).
- `naming.py`: `worktree_branch(task)` → `str` (безопасное `bob/<slug>`);
  `workspace_branch(name)` → `str` (долгоживущее `bob/epic-<slug>`). Обе транслитерируют кириллицу:
  раньше она просто отбрасывалась, и любое русское имя схлопывалось в один и тот же fallback-slug
  (`«эпик»`, `«проект»`, `«релиз»` — все три `bob/epic-task`), то есть `/resume проект` поднимал бы
  чужую работу. Имя вовсе без букв и цифр (`..`, `----`) по-прежнему даёт fallback `task`.
- `argv_policy.py`: `build_interactive_argv(claude_bin, *, mode, resume_session_id=None,
  continue_session=False, extra_dirs=())` → `list[str]` (приоритет `--resume` > `--continue` > фреш;
  `--add-dir` — всегда суффикс); `extract_session_id(event)` → `str | None` (только настоящий
  `init`-кадр с непустым строковым `session_id`).
- `sandbox_policy.py`: `allowed_modes(*, allow_bypass)` → `frozenset[str]`;
  `is_allowed_mode(mode, *, allow_bypass)` → `bool`; `extra_dir_argv(dirs, *, max_dirs=MAX_EXTRA_DIRS)`
  → `list[str]`; `is_safe_argv_value(candidate)` → `bool`. Константы `BASE_PERMISSION_MODES`
  (`{plan, acceptEdits}`), `BYPASS_PERMISSION_MODE`, `MAX_EXTRA_DIRS = 8`.
- `resume_policy.py`: `select_resumable(sessions, *, branch)` → `CodingSession | None`;
  `is_confirmation_fresh(*, requested_at, now, ttl=CONFIRMATION_TTL)` → `bool`; константа
  `CONFIRMATION_TTL` = 5 минут.
- `narrate.py`: `narrate(event)` → `str | None`.
- `intent.py`: `is_approval(text)`, `is_stop(text)` → `bool`.
- `interactive_intent.py`: `parse_interactive_entry(text)` → `str | None`;
  `parse_interactive_workspace(text)` → `tuple[str, str] | None` (workspace, задача);
  `parse_interactive_resume(text)` → `str | None`; `is_interactive_exit(text)`,
  `is_confirmation(text)`, `is_rejection(text)` → `bool`. Все четыре глагола попарно не пересекаются.
- `session_voice.py`: помимо гейт-реплик — `workspace_opened(workspace)`, `stopped_persistent()`,
  `interactive_setup_failed()`, `resume_confirm(*, workspace, when)`, `resume_nothing(workspace)`,
  `resume_cancelled()`, `resumed(workspace)`, `resume_failed()` → `str`.
- `usecases/coding_assistant.py`: `CodingAssistant` — `start`/`approve_plan`/`stop`/`status`.
- `usecases/interactive_session.py`: `InteractiveSessionManager` — `open`/`feed`/`stop`/`active` плюс
  путь долгоживущего рабочего места `open_workspace(name, task, sender)`,
  `propose_resume(name, sender)`, `resolve_pending_resume(text, sender)` → `CodingOutcome | None`
  (`None` = ход резюме не касается) и `resume(name, sender)`.
- `usecases/recover_interactive_sessions.py`: `RecoverInteractiveSessions.run()` → `int` (сколько
  осиротевших `INTERACTIVE`-строк закрыто).
- `usecases/coding_intent_router.py`: `CodingIntentRouter.route(text, sender, is_owner)`.
- `usecases/classify_coding_intent.py`: `ClassifyCodingIntent.is_coding_request(text)`.
- `usecases/coding_context.py`: `make_coding_context(...)` — bounded, privacy-safe преамбула;
  собственный узкий `_is_safe_doc_path` (сегмент-префикс `src`/`tests`/`docs`/`.claude/dev-docs`/
  `.claude/development/docs`) НЕ пускает personal-data доки (SOUL/`bob.db`/`.env`/`config`) во
  внешнюю coder-преамбулу, хотя расширенный full-repo `PrivacyGuard` (BOB-067) в чате их читает.
- `adapters/`: `SubprocessClaudeRunner`, `InteractiveClaudeRunner`, `GitWorktree`
  (`create`/`ensure`/`commit_and_push`/`remove`), `GhPullRequestOpener`,
  `SqliteCodingSessionStore` (`save`/`get`/`active`/`by_branch`), `TypingKeepalive`, `StatusPanel`.

Owner-команды гейтед-сессии — `/code`, `/code approve`, `/code stop`, `/code status`; команды живого
терминала в личке — `/code -i <task>` (`/interactive <task>`), `/workspace <name> [task]`
(`/code -w`), `/resume <workspace>` (`/code -r`), выход — `stop` / `стоп` / `/stop` / `/code stop`
целым сообщением. Сборка — в `runtime/wiring/coding.py` (`_build_coding_assistant` /
`_build_coding_router` при `coder.enabled`; `_build_interactive_session` и
`_build_interactive_intake` при `coder.interactive`, с resume-швами только при `coder.resume`;
`_build_interactive_recovery` — безусловно) и GUPPI (`infrastructure/telegram/guppi.py`).

## Тесты

Тесты покрывают коды-инварианты и поведение (identical после переезда): машина
состояний и гейт плана, never-merge (отсутствие опасных токенов в `gh_pr`),
worktree-изоляция и containment, allowlist режимов раннера, консервативность
классификатора намерения и предикатов апрува/стопа, автономный guard (coding вне
`goals.safe_capabilities`). См. `tests/` (переехавшие coding-тесты, включая строковые
литералы путей в `test_coding_never_merge_and_autonomy_guard.py`, обновлены под
`src/bob/coding/`). Резилентность `active()` — `tests/infrastructure/persistence/test_coding_session_store.py`
(битая строка пропускается, список не падает, BOB-078 D).

Интерактив-2 (BOB-087.D) покрыт на трёх уровнях:
- **Чистые ядра** — `tests/domain/coding/test_argv_policy.py`, `test_sandbox_policy.py`,
  `test_resume_policy.py`, `test_interactive_intent.py`, `test_naming.py`, `test_session_voice.py`.
  Первые пять модулей — mutation-цели (`./scripts/mutation.sh coding.argv_policy` и так далее). Ради
  постоянного гейта `build_interactive_argv` и `extract_session_id` и переехали из адаптера в
  доменный `argv_policy.py`: конвенция mutmut исключает `*/adapters/*`, поэтому в адаптере штатный
  прогон давал ноль мутантов.
- **Use-case и адаптеры** — `tests/application/usecases/test_interactive_resume.py`,
  `test_recover_interactive_sessions.py`, `tests/infrastructure/coding/test_git_worktree.py` и
  `test_git_worktree_persistent_real_git.py` (реюз персистентного дерева проверяется на РЕАЛЬНОМ git в
  одноразовом репозитории, с относительным `worktree_root` — фейк этот контракт не воспроизводил),
  `tests/runtime/wiring/test_coding_resume_wiring.py`, `test_coding_sandbox_relaxations.py`,
  `test_interactive_recovery_wiring.py`.
- **Приёмочный BDD** — `tests/acceptance/features/interactive_resume.feature` (сценарии R1–R10,
  русскоязычный Gherkin) поверх харнесса `tests/acceptance/interactive_resume_harness.py`, который
  поднимает настоящий стек (`InteractiveClaudeRunner` над фейковым процессом → менеджер → интейк) и
  наблюдает только через границу: argv и cwd, отданные спавнеру, судьбу рабочего дерева, что ушло в
  личку и в stdin claude, и что список выполненных push пуст. Это живая документация поведения —
  подъём именно прошлой сессии, накопление работы между сеансами, обязательное подтверждение,
  невозможность live-attach, отсутствие push/merge/PR и байт-в-байт равенство argv базлайну BOB-083
  при выключенных флагах.
