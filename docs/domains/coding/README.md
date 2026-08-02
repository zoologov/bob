<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль coding — «Боб пишет код»

Гейтованный автономный кодинг: по команде owner'а Боб гоняет локальный `claude` CLI
над собственным репозиторием, собирает план, после явного апрува исполняет его в
изолированном worktree и открывает PR. Мержа в машине нет — Боб останавливается на
открытом PR, интеграцию в `main` делает owner вручную вне Боба.

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
  entities.py         # layer=domain   — CodingSession (immutable value-object)
  naming.py           # layer=domain   — worktree_branch: безопасное имя ветки bob/<slug>
  narrate.py          # layer=domain   — stream-json событие Claude Code → нарратив-строка / None (сжато, для группы)
  stream_render.py    # layer=domain   — render_stream_event(verbose): событие→строка; verbose=интерактив (полный текст+rich+chunk_for_telegram) vs груп (краткий кэп). BOB-082/085
  intent.py           # layer=domain   — is_approval / is_stop (чистые предикаты NL-команд)
  interactive_intent.py # layer=domain — parse_interactive_entry (/code -i)/is_interactive_exit (BOB-083, чистые предикаты)
  session_voice.py    # layer=domain   — детерминированные шаблоны реплик в персоне Боба-оператора (человечные реакции взялся/готово-PR/провал/стоп, BOB-087.B2)
  work_facts.py       # layer=domain   — WorkFactsAccumulator/SessionKeyFacts/WorkOutcome: сворачивает поток stream-json в ОГРАНИЧЕННЫЙ снимок ключевых фактов (BOB-087.B1)
  usecases/           # layer=application
    coding_assistant.py       — CodingAssistant (оркестратор гейтед-сессии)
    distill_work_journal.py   — WorkJournalDistiller (порт) + Tier0-адаптер + parse_work_episodes: факты сессии → 1-3 операторских эпизода (BOB-087.B1)
    work_journal_recorder.py  — Distilling/NoOp рекордеры рабочего журнала (флаг memory.work_journal, BOB-087.B1)
    coding_context.py         — make_coding_context (арх-преамбула в claude-промпт)
    classify_coding_intent.py — ClassifyCodingIntent (Tier-0 классификатор «это dev-запрос?»)
    coding_intent_router.py   — CodingIntentRouter (NL-маршрутизация к гейтед-сессии)
    interactive_session.py    — InteractiveSession (менеджер живой интерактив-сессии, БЕЗ PR-opener, BOB-083)
    interactive_intake.py     — InteractiveIntakeRouter (вход/steer→stdin/выход в личке, owner+DM, BOB-083)
  adapters/           # layer=infrastructure
    claude_runner.py    — SubprocessClaudeRunner (headless claude через subprocess, без shell; one-shot)
    interactive_runner.py — InteractiveClaudeRunner (персистентный claude с ОТКРЫТЫМ stdin, двусторонний, BOB-083)
    git_worktree.py     — GitWorktree (изолированный worktree только на трекнутых файлах)
    gh_pr.py            — GhPullRequestOpener (gh pr create; НИКОГДА merge)
    session_store.py    — SqliteCodingSessionStore (персист сессий через рестарт)
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
`with_worktree`/`with_pr_url` (каждый возвращает новый объект).

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
`InteractiveSession` (`usecases/interactive_session.py`) — менеджер живой сессии: `open` (worktree +
спавн + вывод в `_DmLiveStreamer`), `feed→stdin`, `stop→ПРЯМОЙ kill` + cleanup; **одна сессия за раз**.
Вход `/code -i`/выход `stop` + steer-consume-гейт (`interactive_intake.py` → `handle_message`) —
**owner-only, DM-only, за флагом**; режим не залипает (feed только пока сессия активна). 🔴 **Безопасность:**
новое состояние `INTERACTIVE` имеет пустой `_PROGRESS` (никогда не доходит до `EXECUTING`); менеджер
**структурно без PR-opener** — мерж/пуш в main НЕВОЗМОЖЕН; правки — в изолированном worktree `bob/<slug>`,
в main только через существующий PR-гейт owner'а. Осознанное ослабление двойного гейта — ТОЛЬКО для
правок-в-worktree под управлением owner'а.

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
(никогда не shell), с фиксированным allowlist режимов `{plan, acceptEdits}` и лимитами
(таймаут/события/байты). `GitWorktree` создаёт worktree на новой ветке фиксированной
формы `bob/<slug>` — свежий worktree содержит **только трекнутые файлы**, поэтому
приватные данные Боба (`data/soul/`, `bob.db*`, `.env*`, `config/*` — все gitignored)
в нём физически отсутствуют. `GhPullRequestOpener` строит единственную форму
`gh pr create --base main --head <branch>` (discrete argv, без shell) — merge-метода в
порте нет. `SqliteCodingSessionStore` round-trip'ит `CodingSession` (двойной гейт
честен и через границу процесса). 🔴 **Резилентность `active()` (BOB-078 D):**
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
  флаге assistant не подключён и шов инертен.
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

## API

<!-- beadloom:track=src/bob/coding/ports.py -->

Модуль `src/bob/coding/ports.py` (порты-протоколы, только интерфейсы):
- `ClaudeCodeRunner` — шов headless-раннера Claude Code.
- `Worktree` — шов изолированного git-worktree.
- `CodingSessionStore` — шов долговечного хранилища сессий.
- `PullRequestOpener` — шов открытия PR (merge-метода намеренно нет).

Фасад `src/bob/coding/__init__.py` re-export'ит: `CodingSession`, `CodingSessionState`,
`can_transition`, `can_start`, `can_approve_plan`, `can_stop`, `is_terminal`, `narrate`,
`worktree_branch`. Канонический импорт портов — `from bob.coding.ports import
ClaudeCodeRunner`; транзитный ports-шим `bob.domain.ports` удалён (BOB-062.8).

Ключевые точки входа:
- `state.py`: `can_transition(frm, to)`, `can_approve_plan(state)`, `can_stop(state)`,
  `is_terminal(state)` → `bool`.
- `naming.py`: `worktree_branch(task)` → `str` (безопасное `bob/<slug>`).
- `narrate.py`: `narrate(event)` → `str | None`.
- `intent.py`: `is_approval(text)`, `is_stop(text)` → `bool`.
- `usecases/coding_assistant.py`: `CodingAssistant` — `start`/`approve_plan`/`stop`/`status`.
- `usecases/coding_intent_router.py`: `CodingIntentRouter.route(text, sender, is_owner)`.
- `usecases/classify_coding_intent.py`: `ClassifyCodingIntent.is_coding_request(text)`.
- `usecases/coding_context.py`: `make_coding_context(...)` — bounded, privacy-safe преамбула;
  собственный узкий `_is_safe_doc_path` (сегмент-префикс `src`/`tests`/`docs`/`.claude/dev-docs`/
  `.claude/development/docs`) НЕ пускает personal-data доки (SOUL/`bob.db`/`.env`/`config`) во
  внешнюю coder-преамбулу, хотя расширенный full-repo `PrivacyGuard` (BOB-067) в чате их читает.
- `adapters/`: `SubprocessClaudeRunner`, `GitWorktree`, `GhPullRequestOpener`,
  `SqliteCodingSessionStore`, `TypingKeepalive`, `StatusPanel`.

Композиция и owner-команды (`/code`, `/code approve`, `/code stop`, `/code status`) —
в композиционном корне `app.py` (`_build_coding_assistant` / `_build_coding_router`,
только при `coder.enabled`) и GUPPI (`infrastructure/telegram/guppi.py`). Подробный
разбор потока, голоса Боба на гейтах и индикаторов работы — в `docs/architecture.md`
(раздел «Боб запускает Claude Code: гейтед coding-сессия»).

## Тесты

Тесты покрывают коды-инварианты и поведение (identical после переезда): машина
состояний и гейт плана, never-merge (отсутствие опасных токенов в `gh_pr`),
worktree-изоляция и containment, allowlist режимов раннера, консервативность
классификатора намерения и предикатов апрува/стопа, автономный guard (coding вне
`goals.safe_capabilities`). См. `tests/` (переехавшие coding-тесты, включая строковые
литералы путей в `test_coding_never_merge_and_autonomy_guard.py`, обновлены под
`src/bob/coding/`). Резилентность `active()` — `tests/infrastructure/persistence/test_coding_session_store.py`
(битая строка пропускается, список не падает, BOB-078 D).
