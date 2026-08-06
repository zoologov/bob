<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль coding — «Боб пишет код»

Гейтованный автономный кодинг: по команде owner'а Боб гоняет локальный `claude` CLI
над собственным репозиторием, собирает план, после явного апрува исполняет его в
изолированном worktree и открывает PR. Мержа в машине нет — Боб останавливается на
открытом PR, интеграцию в `main` делает owner вручную вне Боба.

🔴 С BOB-089 у последнего шага есть ВТОРАЯ форма (под флагом): когда рабочее место — клон
ПРИВАТНОГО форка Боба, открыть PR он не может вовсе (installation-токен скоупится на одну
установку), поэтому он честно говорит, что работа лежит в его форке, и отдаёт ссылку на
создание PR — жмёт owner. Ни в одной из форм Боб не мержит.

🔴 **Второй путь — живой интерактивный терминал — с BOB-087.E живёт в собственном модуле**
[`interactive`](../interactive/README.md) («Боб держит живой терминал»): долгоживущий
сеанс `claude` с открытым stdin в личке owner'а, долгоживущее рабочее место, возобновление.
Он ОПИРАЕТСЯ на общую поверхность этого модуля (порты, `CodingSession`/`CodingOutcome`,
машина состояний, имена веток, политика песочницы, push-барьер, разбор stream-json), но
говорит на своём языке и держит свои инварианты; `coding` о нём не знает ничего
(ребро одностороннее). Здесь остаётся ГЕЙТЕД кодер и эта общая поверхность.

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
  sandbox_policy.py   # layer=domain   — allowed_modes/is_allowed_mode/extra_dir_argv/is_safe_argv_value: политика owner-ослаблений изоляции + ClaudeRunError (BOB-087.D2/E)
  push_guard.py       # layer=domain   — guarded_spawn_env: ЕДИНСТВЕННЫЙ шов окружения спавна — барьер сетевого push (BOB-087.E, bob-5ao) + изоляция от кредов owner'а (BOB-089.C, решения в bob.identity.spawn_isolation)
  clone_plan.py       # layer=domain   — clone_argv/checkout_argv/origin_argv/identity_argv/workspace_verdict/is_credential_free_url: план рабочего места-КЛОНА (файловый транспорт вместо хардлинков, подпись bob[ai] ЛОКАЛЬНО в клоне, вердикт переиспользования, запрет кредов в argv; BOB-089.A/D)
  untrusted_repo.py   # layer=domain   — hardened_git_argv/unsafe_local_config/LOCAL_CONFIG_QUERY: как Боб зовёт git в каталоге, за содержимое которого отвечает МОДЕЛЬ (хуки/fsmonitor/подпись коммита не исполняются в его процессе, незнакомый ключ локального конфига останавливает интеграцию; bob-a6b.14)
  pr_link.py          # layer=domain   — repo_slug/compare_url: «ветка в форке Боба → предзаполненная форма создания PR» (PR открывает owner: cross-repo PR из приватного форка installation-токену недоступен, BOB-089.D)
  stream_json.py      # layer=domain   — parse_event / STREAM_LIMIT: как читается ОДНА строка NDJSON-потока claude (общий примитив обоих транспортов, BOB-087.E)
  narrate.py          # layer=domain   — stream-json событие Claude Code → нарратив-строка / None (сжато, для группы)
  stream_render.py    # layer=domain   — render_stream_event(verbose): событие→строка; verbose=интерактив (полный текст+rich+chunk_for_telegram) vs груп (краткий кэп). BOB-082/085
  intent.py           # layer=domain   — is_approval / is_stop (чистые предикаты NL-команд)
  session_voice.py    # layer=domain   — детерминированные шаблоны реплик гейтед-сессии в персоне Боба-оператора (взялся/готово-PR/готово-но-PR-за-owner'ом/провал/стоп, BOB-087.B2 + BOB-089.D; реплики живого терминала — в bob/interactive/voice.py)
  speaker.py          # layer=domain   — speaker_for(MessageKind) → Speaker: КТО озвучивает сообщение (механика — GUPPI, живое и адресованное людям — Боб; запрос разрешения — Боб) + channel_for: единственный перевод «говорящий → канал». Канон Денниса Тейлора, BOB-090.D/B-fix
  work_facts.py       # layer=domain   — WorkFactsAccumulator/SessionKeyFacts/WorkOutcome: сворачивает поток stream-json в ОГРАНИЧЕННЫЙ снимок ключевых фактов (BOB-087.B1)
  usecases/           # layer=application
    coding_assistant.py       — CodingAssistant (оркестратор гейтед-сессии)
    distill_work_journal.py   — WorkJournalDistiller (порт) + Tier0-адаптер + parse_work_episodes: факты сессии → 1-3 операторских эпизода (BOB-087.B1)
    work_journal_recorder.py  — Distilling/NoOp рекордеры рабочего журнала (флаг memory.work_journal, BOB-087.B1)
    coding_context.py         — make_coding_context (арх-преамбула в claude-промпт)
    classify_coding_intent.py — ClassifyCodingIntent (Tier-0 классификатор «это dev-запрос?»)
    coding_intent_router.py   — CodingIntentRouter (NL-маршрутизация к гейтед-сессии)
  adapters/           # layer=infrastructure
    claude_runner.py    — SubprocessClaudeRunner (headless claude через subprocess, без shell; one-shot)
    git_worktree.py     — GitWorktree (изолированный worktree только на трекнутых файлах; ensure — идемпотентный долгоживущий workspace, BOB-087.D1)
    git_clone.py        — GitClone (то же рабочее место как ОТДЕЛЬНЫЙ КЛОН со своим .git; под теми же портами, подмена в композиции по флагу coder.isolated_clone, BOB-089.A)
    gh_pr.py            — GhPullRequestOpener (gh pr create; НИКОГДА merge)
    fork_link.py        — ForkCompareLink (тот же порт, но НИЧЕГО не исполняет: отдаёт owner'у форму создания PR из форка Боба; подмена в композиции, BOB-089.D)
    session_store.py    — SqliteCodingSessionStore (персист сессий через рестарт; by_branch — чтение всех сессий ветки, BOB-087.D3)
    indicator.py        — TypingKeepalive + StatusPanel (индикаторы работы в топике Боба)
    owner_notifier.py   — _CodingOwnerNotifier (нотификатор owner'а; переехал из app.py, BOB-062.7a)
    live_stream.py      — _DmLiveStreamer (полный лайв-стрим сырых событий в личку owner'а, BOB-082; firehose ботом GUPPI при coder.stream_via_guppi, BOB-087.A)
    _branch.py, _exec.py — внутренние shell-free хелперы адаптеров
    _integrate.py       — commit_and_push_branch: ЕДИНСТВЕННОЕ место, где строится push ветки Боба (общее для worktree и клона, BOB-089.A; закалённая форма + push ПО ЗНАЧЕНИЮ адреса, bob-a6b.14)
    _paths.py           — is_strict_child: проверка вложенности пути перед разрушающей операцией (общая для обоих рабочих мест)
```

Живой терминал (`InteractiveSessionManager`, `InteractiveIntakeRouter`,
`RecoverInteractiveSessions`, `InteractiveClaudeRunner`, распознаватели команд режима,
политики resume/argv и голос режима) переехал в `src/bob/interactive/` — см. README
модуля [`interactive`](../interactive/README.md).

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

🔴 **Живой интерактивный терминал (BOB-083 / BOB-087.D) — в модуле
[`interactive`](../interactive/README.md).** Двусторонний сеанс, долгоживущее рабочее
место и возобновление описаны там же. Отсюда он берёт общую поверхность (порты,
`CodingSession`/`CodingOutcome`, `state`, `naming`, `sandbox_policy`, `push_guard`,
`stream_json`, две общие реплики `session_voice`) и НИЧЕГО из `usecases/`/`adapters/` —
это запрещено правилами границ. 🔴 Состояние `INTERACTIVE` живёт в общей машине состояний
здесь и имеет пустой `_PROGRESS`: живой сеанс никогда не доходит до `EXECUTING`, а его
менеджер структурно без PR-открывашки — мерж/пуш в `main` невозможен.

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

🔴 **GUPPI-канал: firehose исполнителя (BOB-087.A, флаг `coder.stream_via_guppi`).** В
загрузчике флаг по-прежнему `false`, и OFF-путь остаётся байт-в-байт; BOB-090.D включил его в
ЖИВОМ `config/bob.yaml` (файл git-ignored, поэтому в репозитории его состояние не видно).
По канону Денниса Тейлора GUPPI — **несознательный интерфейс**: исполняет буквально,
без личности, мнения и инициативы. При флаге ON механический **firehose** (per-event narrate +
`_DmLiveStreamer` live-stream + технический итог прогона) уходит **ботом GUPPI**, а голос Боба (гейты
`session_voice` «берусь/готово/провал», `dev_pointer`, `narration_capped`, typing/панель) — **всегда
ботом Боба** (`stream_notifier`-порт в `CodingAssistant`). OFF (default в загрузчике) → всё ботом Боба,
байт-в-байт. Отделяет механический поток от голоса Боба (канон + анти-recall-яд: firehose вне истории
бота Боба).

🔴 **Кто говорит — чистое ядро (BOB-090.D1/D2).** Раньше расклад «эта строка — Бобу, та — GUPPI» был
размазан по местам отправки, и каждая новая реплика решала за себя. Теперь он ОДИН и лежит в
`speaker.py`: `speaker_for(MessageKind)` делит сообщения по их **виду** — механика (сырой вывод
инструмента, пошаговый нарратив прогона, технический статус/итог, «не найдено», техническое
подтверждение) → `Speaker.GUPPI`; живое (реплики гейтов сессии, вход/выход режима, реакции, маркер
присутствия, всё адресованное людям) → `Speaker.BOB`. 🔴 **Запрос разрешения — это Боб**, а не GUPPI:
это социальный акт (Боб защищает приватность owner'а и просит решения у человека), а не механика.
Оркестратор шлёт ВСЁ через одну дверь `CodingAssistant._say(kind, text)` → `notifier_for(kind, …)`, так
что ветки «мимо канона» не остаётся; при выключенном флаге оба канала — один нотификатор, и поведение
байт-в-байт прежнее.

🔴 **Канон и канал связаны, а не совпадают (BOB-090.B-fix).** Пока канал выбирался отдельной
строкой, которая лишь СОВПАДАЛА с вердиктом ядра, подмена канона не двигала ни одного канала —
то есть ядро ничего не решало. Теперь перевод «говорящий → канал» ровно один:
`channel_for[Channel](kind, *, bob, guppi)` рядом со `speaker_for`. `notifier_for` делегирует
ему, а композиционный корень выбирает им бота для запроса разрешения. Ядро параметрично по типу
канала — ему безразлично, бот это или нотификатор, — а `bob` и `guppi`, оказавшиеся одним
объектом (OFF-путь), дают тот же объект на любой вид. Привязка проверяется тестом, который
подменяет канон и требует, чтобы бот ПЕРЕЕХАЛ.

🔴 **Один шов остался вне канона — интерактивный терминал.** В `runtime/wiring/coding.py`
сырой поток строится над `stream_bot` структурно, по флагу, а не через `channel_for`.
Ограничение названо прямо: подмена канона этот канал не сдвинет.

🔴 **Реплики GUPPI не попадают в память как голос Боба.** Голос Боба воспроизводится по recall
(BOB-022/074/078), поэтому машинные строки исполнителя обязаны остаться транспортом. В память с
coding-сессии осаждаются только его СОБСТВЕННЫЕ следы: поступок от первого лица (`self_action`,
BOB-079) и операторская вспоминка (`work`, BOB-087.B1). Доказано тестом на настоящей SQLite
(`tests/application/usecases/test_coding_guppi_not_in_memory.py`): ни одна отправленная каналом GUPPI
строка не встречается ни в одном эпизоде.

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
owner-флагом `coder.allow_bypass` (BOB-087.D2). Строку NDJSON-потока оба транспорта — этот и
персистентный раннер живого терминала — читают одним общим примитивом `stream_json`
(`parse_event`, буфер `STREAM_LIMIT` = 16 МиБ: 64-килобайтный дефолт asyncio ронял чтение на
длинной строке, BOB-084). `GitWorktree` создаёт worktree на новой ветке фиксированной
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

🔴 **Рабочее место как ОТДЕЛЬНЫЙ КЛОН (BOB-089, срез A; флаг `coder.isolated_clone`, default
OFF).** У linked worktree есть предел, который никакой конфиг не сдвинет: он делит `.git` с
основным репозиторием — те же объекты, те же **refs**, те же remotes и те же credentials.
Проверено на настоящем git (bob-5ao): `git update-ref refs/heads/main <sha>` из такого дерева
двигает main owner'а без сети, без кредов и мимо любого push-барьера. `GitClone` — тот же
контракт под теми же портами (`create` / `ensure` / `commit_and_push` / `remove`), но рабочее
место становится КЛОНОМ со своим `.git`; подмена происходит в композиции
(`_build_workspace`), поэтому use-case'ы не знают, во что приземляются, а OFF-путь остаётся
прежним и доказывается РАВЕНСТВОМ сборки (тип адаптера и его аргументы), а не «похожестью».
Решения вынесены в чистое ядро `clone_plan`: клонирование идёт через `file://` (голый
локальный путь заставил бы git ХАРДЛИНКОВАТЬ файлы объектов — то есть склад объектов остался
бы общим с репозиторием owner'а); `origin` переписывается на `coder.fork_url`, а при пустом
значении remote удаляется ЦЕЛИКОМ (рабочая копия owner'а не остаётся адресом для push,
апстрим не прописан ни при каком значении); долгоживущее место переиспользуется по вердикту
`workspace_verdict`, а посторонний непустой каталог получает громкий отказ; URL со
встроенными кредами (`https://x-access-token:<токен>@host/…`) отвергается на сборке, потому
что argv виден в `ps`. Приватность клона ДОКАЗАНА на настоящем git, а не предположена (у
`git clone` иные правила, чем у `worktree add`): тест перечисляет содержимое клона целиком и
сверяет его с трекнутыми файлами, отдельно проверяя отсутствие хардлинков/alternates и то,
что `update-ref refs/heads/main` внутри клона main owner'а не двигает
(`tests/infrastructure/coding/test_git_clone_real_git.py`); на НАСТОЯЩЕМ репозитории owner'а
то же самое проверяет opt-in смоук сравнением sha `refs/heads/main` до и после
(`test_upstream_refusal_live_smoke.py`). Цена (замер на этом
репозитории, `.git` 602 МБ): 3.8 с и 142 МБ на рабочее место; `--depth 1` (1.3 с, 63 МБ)
отвергнут — без истории Боб теряет `git log`/`blame`, а `--shared`/`--reference` ставят клон
в зависимость от объектов owner'а.

🔴 **Вторая половина того же флага — изоляция от кредов owner'а (BOB-089, срез C).** Клон
закрывает ЛОКАЛЬНУЮ дорогу к стволу (свой `.git`), но сам по себе оставляет сетевую: пока
окружение спавна наследует credential helper owner'а, `git push` в апстрим уходит его
кредами. Поэтому тот же `coder.isolated_clone` включает и изоляцию окружения: `claude`
спавнится с подменным global-конфигом git, отключённым системным, СБРОШЕННЫМ списком
credential-хелперов, `GIT_TERMINAL_PROMPT=0`, askpass'ом в никуда, собственным пустым
`GH_CONFIG_DIR`, контролируемым `GIT_SSH_COMMAND` (bob-a6b.10 — см. ниже) и без амбиентных
`GH_TOKEN`/`GITHUB_TOKEN`/`SSH_AUTH_SOCK`/`GIT_CONFIG_PARAMETERS`. Механизм —
РАСШИРЕННЫЙ `push_guard.guarded_spawn_env` (второго механизма нет: обе меры выражаются одним
блоком `GIT_CONFIG_*`), решения — в чистом ядре
[`bob.identity.spawn_isolation`](../identity/README.md), файлы — в его адаптере. Барьер
`pushInsteadOf` остаётся вторым слоем: сам он снимается изнутри, но без кредов обход
бессмыслен. 🔴 ЧЕСТНАЯ РАМКА, проверенная вживую против настоящего GitHub: отказ теперь
приходит ПО ПРАВАМ (`Repository not found` рабочему принципалу, `Write access to repository
not granted` + 403 предлагающему), а легитимный пуш ветки в форк тем же токеном проходит.
Структурны ровно два свойства — отдельный `.git` и отсутствие права записи у токена; само
окружение границей НЕ является (тот же UID владеет своим окружением), но его обход даёт лишь
процесс БЕЗ кредов. И внутри клона модель по-прежнему делает с рабочим деревом что угодно —
правами это не закрывается вообще.

🔴 **Поправка по факту (bob-a6b.10): «отказ по правам» относился только к https.** Абзац
выше в первой редакции читался как «сетевая дорога к апстриму закрыта». Ревьюер проверил из
ровно прод-окружения спавна: `ssh -T git@github.com` → `Hi <owner>! You've successfully
authenticated`, `git ls-remote` апстрима по ssh → `rc=0`. Изоляция **не касалась ssh
вовсе**, а по ssh Боб предъявлял не свой токен, а ключ owner'а — то есть «нет права записи»
к этой дороге не относилось. Теперь git по ssh ходит контролируемой командой
(`GIT_SSH_COMMAND` + `core.sshCommand` в подменном конфиге; каждая опция проверена на
настоящем ssh — детали и почему `IdentitiesOnly` в одиночку не работает, в
[доке `identity`](../identity/README.md)), и апстрим по ssh отвечает
`Permission denied (publickey)`. **Не закрыт прямой вызов `ssh`** из спавна: ключ owner'а
на диске под тем же UID, а `~` OpenSSH раскрывает по записи в passwd, не по `HOME` —
окружением это не закрывается, только раздельным UID (BOB-093). Ограничение зафиксировано
исполняемо (честная рамка в `test_ssh_road_live_smoke.py`), а `coder.fork_url` в примере
конфига переведён на **https**, чтобы штатная настройка не вела по транспорту, на котором
изоляции нет.

**Подпись работы Боба (BOB-089.D, вместе с клоном).** В клоне выставляются
`user.name = bob[ai]` и ботовский адрес
`<coder.app_user_id>+bob-ai-work[bot]@users.noreply.github.com` — форма
`identity_argv` из того же чистого ядра, и она несёт `--local` и `-C <клон>` ЯВНО:
🔴 глобальная настройка переподписала бы коммиты owner'а в его собственном репозитории как
`bob[ai]` — ровно та путаница идентичностей, от которой уходит эпик. Имя ставится всегда, а
числовой `app_user_id` (публичная величина, не секрет) — лишь префикс адреса: не подписать
вовсе было бы ХУЖЕ, потому что тогда git взял бы идентичность owner'а и работа Боба стала бы
неотличима от его собственной. Локальность доказана на настоящем git: значения `--global` и
`--local` в репозитории owner'а сверяются до и после, и его собственный коммит после
появления рабочего места Боба по-прежнему подписан им
(`tests/infrastructure/coding/test_git_clone_real_git.py`).

**Как работа доезжает до owner'а — две развилки одного порта.** `GhPullRequestOpener` строит
единственную форму `gh pr create --base main --head <branch>` (discrete argv, без shell) —
merge-метода в порте нет. `ForkCompareLink` (BOB-089.D) реализует ТОТ ЖЕ порт, но не
исполняет ничего вовсе (в модуле нет даже командного шва — это инвариант под тестом): он
возвращает предзаполненную форму
`https://github.com/<github.propose_repo>/compare/main...<форк>:<ветка>?expand=1`, собранную
чистым `pr_link.compare_url`, а слаг форка берётся из ТОГО ЖЕ `coder.fork_url`, куда уходит
push (иначе ссылка однажды указала бы не туда, где лежит работа). 🔴 ОДИН факт — ОДИН ключ
(bob-a6b.9): апстрим читается только из `github.propose_repo` — секции, которая одна держит
репозиторную идентичность (прежний дубль `coder.upstream_repo` убран: два ключа на один факт
однажды разъезжаются, и Боб отдал бы ссылку на один репозиторий, а читал бы другой). По той
же причине `coder.fork_url` (транспортный адрес) сверяется на сборке ссылки с
`github.work_repo` (слаг той же установки): расхождение — громкий отказ с именами обоих
ключей, а не тихий уход на gh-путь; пустой `work_repo` расхождением не считается (сверять не
с чем, пока принципалы не настроены). 🔴 Почему так: cross-repo
PR из ПРИВАТНОГО форка installation-токену недоступен — токен скоупится на одну установку
(проверены три способа, обход — не-цель PRD), поэтому «Create pull request» жмёт owner.
Развилка ПАРНАЯ: `_build_pr_integration` отдаёт адаптер и флаг `opens_pr` одним решением, и
голос идёт за фактом — `session_voice.pr` («вот PR») против `session_voice.ready_for_pr`
(«работа в моём форке, открыть PR сам не могу, вот форма»). Заявить открытый PR там, где
отдана лишь ссылка, — неправда, которую owner проверит первым же нажатием. Неполный набор
(нет клона / нет форка на GitHub / неизвестен апстрим) → прежний gh-путь, байт-в-байт. `SqliteCodingSessionStore` round-trip'ит `CodingSession` (двойной гейт
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
- **Изоляция клона (BOB-089.A, под флагом):** та же приватность (только трекнутые файлы,
  доказано перечислением на настоящем git) плюс СВОЙ `.git` — общих refs с основным
  репозиторием нет, поэтому локальный `update-ref refs/heads/main` до main owner'а не
  достаёт; единственный remote — форк (или ни одного); `remove` требует и containment, и
  того, чтобы каталог был клоном. 🔴 Креды этим НЕ изолируются — отдельный срез.
- **Идентичность ЛОКАЛЬНА (BOB-089.D):** подпись `bob[ai]` живёт в конфиге клона; формы
  `identity_argv` несут `--local` и `-C <клон>` явно, и глобальная область ими невыразима —
  коммиты owner'а в его репозитории не переподписываются (доказано сравнением значений
  `--global`/`--local` до и после + его собственным коммитом после создания клона).
- **Боб не притворяется, что открыл PR (BOB-089.D):** на форк-пути у него нет даже
  поверхности, чтобы что-то сделать в апстриме (`ForkCompareLink` не имеет командного шва), и
  реплика идёт ЗА фактом — «работа в моём форке, вот форма», а не «вот PR». Адаптер и флаг
  `opens_pr` приезжают из ОДНОГО решения композиции, поэтому разойтись не могут.
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

🔴 **Бюджет размера узла: рекалибровка СНЯТА (BOB-087.E, беада `bob-6u2`).** В срезе D у `coding`
был заведён отдельный бюджет `no-monster-modules-coding` (220 символов при общем потолке 200) с
явной пометкой «это отсрочка: настоящий фикс — разбить сам УЗЕЛ». Долг взят: живой терминал уехал в
модуль [`interactive`](../interactive/README.md), и оба узла снова проходят ОБЩЕЕ правило
`no-monster-modules` (≤ 200) без единого исключения — `coding` 172, `interactive` 48. Ни `exclude`,
ни персонального бюджета в `rules.yml` больше нет. Оговорка на будущее: дробление ФАЙЛОВ внутри
модуля счётчик узла не снижает (символы остаются в том же узле) — снижает только честная граница
bounded context'а, и подпапка внутри `src/bob/coding/` тоже не помогла бы: размер считается по
префиксу `source`, поэтому вложенный узел учитывался бы дважды. Следующий кандидат на разбор, если
узел снова начнёт расти, — `usecases/coding_assistant.py` (955 строк, 30 символов: оркестратор
гейтед-сессии вместе с четырьмя своими сеймами).

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
- `sandbox_policy.py`: `allowed_modes(*, allow_bypass)` → `frozenset[str]`;
  `is_allowed_mode(mode, *, allow_bypass)` → `bool`; `extra_dir_argv(dirs, *, max_dirs=MAX_EXTRA_DIRS)`
  → `list[str]`; `is_safe_argv_value(candidate)` → `bool`; исключение `ClaudeRunError` (отказ до
  старта процесса — живёт у политики, которая отказывает; ре-экспортируется адаптером
  `adapters/claude_runner.py`, BOB-087.E). Константы `BASE_PERMISSION_MODES`
  (`{plan, acceptEdits}`), `BYPASS_PERMISSION_MODE`, `MAX_EXTRA_DIRS = 8`.
- `push_guard.py`: `guarded_spawn_env(env, *, active, isolation=None)` → окружение спавна:
  барьер сетевого push (BOB-087.E, bob-5ao) и/или изоляция от кредов owner'а (BOB-089.C,
  решения — в `bob.identity.spawn_isolation`). Обе выключены → `None`, спавн без `env=`.
- `clone_plan.py`: `clone_argv(git_bin, *, source, dest)`, `checkout_argv(git_bin, *, dest,
  branch, on_origin)`, `origin_argv(git_bin, *, dest, fork_url)` → `list[str]`;
  `identity_argv(git_bin, *, dest, app_user_id)` → `list[list[str]]` (две `config --local`-формы
  подписи `bob[ai]`, BOB-089.D);
  `workspace_verdict(*, dest_exists, is_repo)` → `WorkspaceVerdict` (`CLONE`/`REUSE`/`REFUSE`);
  `is_credential_free_url(url)` → `bool` (BOB-089.A).
- `untrusted_repo.py`: `hardened_git_argv(git_bin, *, path=None)` → `list[str]` — префикс
  каждого git-вызова Боба в каталоге, которым распоряжается модель (`-c core.hooksPath=/dev/null`,
  `-c core.fsmonitor=false`, `-c commit.gpgSign=false`, затем `-C <path>`);
  `unsafe_local_config(listing)` → `tuple[str, ...]` — ALLOW-список: имена ключей локального
  конфига клона, которых наша последовательность заведения там не оставляла (пусто → идти можно);
  `LOCAL_CONFIG_QUERY` — форма опроса (`config --local --list -z`). 🔴 Состав выбран ПОПЫТКАМИ на
  настоящем git: без пар в процессе Боба исполнялись подложенные моделью `pre-commit`/
  `post-commit`/`pre-push`, `core.fsmonitor` и `gpg.program`; ALLOW-список (а не перечень опасных
  ключей) — потому что `include.path` и `extensions.worktreeConfig` ПРЯЧУТ свои ключи от
  `--local`. Границы меры — в докстроке модуля (bob-a6b.14, ревью MAJOR-7).
- `pr_link.py`: `repo_slug(url)` → `str` (`owner/repo` форка или `""`),
  `compare_url(*, upstream, fork, branch, base)` → `str` — предзаполненная форма создания PR,
  которую отдаёт Боб вместо открытия PR (BOB-089.D).
- `stream_json.py`: `parse_event(line)` → `Mapping[str, object] | None`; константа
  `STREAM_LIMIT` = 16 МиБ — общий примитив чтения потока для обоих транспортов (BOB-087.E).
- `narrate.py`: `narrate(event)` → `str | None`.
- `intent.py`: `is_approval(text)`, `is_stop(text)` → `bool`.
- `session_voice.py`: гейт-реплики сессии (`accepted`/`plan`/`pr`/`ready_for_pr`/`no_changes`/
  `failed`/`stopped`/`narration_capped`/`dev_pointer`, панель-строки — включая
  `panel_ready_for_pr`, `busy`/`cannot_approve`/`no_session`/`status_*`).
  Две из них — `stopped()` и `no_session()` — общие: их ре-экспортирует голос живого терминала
  (`bob.interactive.voice`), потому что они про управление сессией, а не про режим.
- `speaker.py`: `speaker_for(kind)` → `Speaker` (`BOB` / `GUPPI`), `is_mechanical(kind)` → `bool`;
  перечисление `MessageKind` (`TOOL_OUTPUT`/`RUN_EVENT`/`RUN_STATUS`/`NOTHING_FOUND`/`TECHNICAL_ACK`
  — механика; `SESSION_GATE`/`MODE_NOTICE`/`REACTION`/`PRESENCE_MARK`/`PERMISSION_REQUEST`/
  `ADDRESSED_TO_PERSON` — живое); `channel_for[Channel](kind, *, bob, guppi)` → `Channel` —
  единственный перевод вердикта в канал. Чисто, без транспорта:
  `usecases/coding_assistant.notifier_for` и бот запроса разрешения в композиционном корне
  берут канал отсюда.
- `usecases/coding_assistant.py`: `CodingAssistant` — `start`/`approve_plan`/`stop`/`status`.
- `usecases/coding_intent_router.py`: `CodingIntentRouter.route(text, sender, is_owner)`.
- `usecases/classify_coding_intent.py`: `ClassifyCodingIntent.is_coding_request(text)`.
- `usecases/coding_context.py`: `make_coding_context(...)` — bounded, privacy-safe преамбула;
  собственный узкий `_is_safe_doc_path` (сегмент-префикс `src`/`tests`/`docs`/`.claude/dev-docs`/
  `.claude/development/docs`) НЕ пускает personal-data доки (SOUL/`bob.db`/`.env`/`config`) во
  внешнюю coder-преамбулу, хотя расширенный full-repo `PrivacyGuard` (BOB-067) в чате их читает.
- `adapters/`: `SubprocessClaudeRunner`, `GitWorktree`
  (`create`/`ensure`/`commit_and_push`/`remove`), `GitClone` (те же порты + `app_user_id` —
  подпись `bob[ai]` локально в клоне), `GhPullRequestOpener`, `ForkCompareLink`
  (`upstream`/`fork` → форма создания PR; PR не открывает),
  `SqliteCodingSessionStore` (`save`/`get`/`active`/`by_branch`), `TypingKeepalive`, `StatusPanel`.

Owner-команды гейтед-сессии — `/code`, `/code approve`, `/code stop`, `/code status` (команды
живого терминала — в README модуля [`interactive`](../interactive/README.md)). Сборка — в
`runtime/wiring/coding.py` (`_build_coding_assistant` / `_build_coding_router` при
`coder.enabled`; там же собирается и живой терминал: `_build_interactive_session` /
`_build_interactive_intake` при `coder.interactive`, `_build_interactive_recovery` — безусловно)
и GUPPI (`infrastructure/telegram/guppi.py`). Композиционный корень — единственный слой, которому
позволено собирать оба модуля разом.

## Тесты

Тесты покрывают коды-инварианты и поведение (identical после переезда): машина
состояний и гейт плана, never-merge (отсутствие опасных токенов в `gh_pr`),
worktree-изоляция и containment, allowlist режимов раннера, консервативность
классификатора намерения и предикатов апрува/стопа, автономный guard (coding вне
`goals.safe_capabilities`). См. `tests/` (переехавшие coding-тесты, включая строковые
литералы путей в `test_coding_never_merge_and_autonomy_guard.py`, обновлены под
`src/bob/coding/`). Резилентность `active()` — `tests/infrastructure/persistence/test_coding_session_store.py`
(битая строка пропускается, список не падает, BOB-078 D).

Чистые ядра общей поверхности — `tests/domain/coding/test_state.py`, `test_entities.py`,
`test_naming.py`, `test_sandbox_policy.py`, `test_push_guard.py`, `test_intent.py`,
`test_narrate.py`, `test_session_voice.py`, `test_stream_render*.py`, `test_work_facts.py`,
`test_untrusted_repo.py`. То, что подложенный моделью код НЕ исполняется в процессе Боба,
доказано на РЕАЛЬНОМ git парами «контроль → защита»:
`tests/infrastructure/coding/test_untrusted_repo_real_git.py` (хуки всех трёх видов,
`core.hooksPath` из конфига модели, `fsmonitor`, `gpg.program`, `remote.origin.pushurl`,
`url.*.pushInsteadOf`, `filter.*.clean`, `include.path`, `extensions.worktreeConfig` — и то, что
легитимная работа всё равно доезжает до форка).
Персистентное дерево проверяется на РЕАЛЬНОМ git
(`tests/infrastructure/coding/test_git_worktree_persistent_real_git.py` — фейк этот контракт не
воспроизводил), а спавн-окружение — `test_claude_spawn_env.py` / `test_push_guard_real_git.py` /
`test_spawn_isolation_real_git.py` (изоляция от кредов owner'а И ssh-дорога: каждая дорога
проверяется парой «контроль → изоляция» вердиктом самого git) /
`test_upstream_refusal_live_smoke.py`
(🔴 opt-in негативный смоук против НАСТОЯЩЕГО GitHub: отказ по правам с проверкой текста,
легитимный пуш в форк работает). ssh-половина живёт в узле `identity`:
`tests/infrastructure/identity/test_ssh_isolation_real_ssh.py` (разбор конфигурации САМИМ
ssh, без сети) и `test_ssh_road_live_smoke.py` (🔴 opt-in: отказ настоящего GitHub по ключу
+ честная рамка про прямой `ssh`). Плюс `tests/runtime/wiring/test_coding_spawn_isolation.py`
(доезжает ли изоляция до границы процесса в ОБОИХ рантаймах; OFF → `None` и ни одного файла).
Тесты живого терминала (юниты, адаптер на реальном процессе и приёмочный BDD) переехали вместе
с модулем — см. раздел «Тесты» README [`interactive`](../interactive/README.md).
