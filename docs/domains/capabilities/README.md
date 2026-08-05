<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль capabilities — «инструменты Боба»

Способность «инструменты Боба» как единая вертикаль: стабильный контракт
`Capability` и его порты (tool-calling-провайдер + web / diagram / introspection
сеймы) в `ports.py`, чистые value-object'ы `diagrams` / `introspection`, половина
`usecases/` (шов `CapabilityRegistry` + `ToolLoop` и сами навыки — recall/search
памяти, read code/url, навигация по репозиторию (list_dir / find_file), web-поиск,
render diagram, inspect architecture, list work, code rationale, progress announcer,
отправка в указанный чат) и половина `adapters/` (aiohttp url-reader за
SSRF-щитом, локальный mermaid-рендерер, beadloom/bd/git-интроспектор, Qwen web-search
транспорт). GUPPI — исполнитель шва: модель просит инструмент, GUPPI его запускает.

Это четвёртый и крупнейший **вертикальный** модуль domain-first раскладки
(BOB-062.4, срез 4/8 эпика BOB-062): весь capability-шов собран в одном месте
`src/bob/capabilities/`, а не размазан по слоям `domain/ports/capabilities.py` +
`domain/{diagrams,introspection}/` + `application/capabilities/**` +
`infrastructure/{web,diagrams,introspection}/` + `infrastructure/llm/web_search_qwen.py`.
Модуль охватывает три слоя **внутри** одного bounded-context, поэтому в графе он
несёт не-слойный тег `module-vertical` (правило `architecture-layers` его рёбра
пропускает), а внутреннюю и внешнюю дисциплину держат explicit-path
`forbid_import`-правила в `.beadloom/_graph/rules.yml`, сгенерированные
`scripts/gen_boundary_rules.py`.

## 🔴 Ключевые решения по границам и принадлежности

1. **`CollectingDiagramSink` — один разделяемый инстанс на процесс.** PNG,
   отрендеренный навыком `render_diagram` глубоко в tool-loop (где нет `chat_id`),
   должен дойти до текущего чата. Навык не шлёт фото сам — он `push`ит структурный
   `DiagramResult` в per-turn `DiagramSink`, а reply-путь (у которого есть `chat_id`
   и gateway) после tool-loop `drain`ит sink и отправляет фото. Критично: `HandleMessage`
   и `render_diagram` держат **один и тот же** инстанс `CollectingDiagramSink` (иначе
   inline-mermaid авто-рендер не сможет дедуплицировать диаграмму, которую tool уже
   отрендерил этот ход, — дедуп по `DiagramResult.source`). Раздваивать sink при
   композиции нельзя.
2. **`InterimLineGenerator` — кандидат на извлечение в `conversation` (.6).** Порт
   живой interim-строки («секунду, гляну…») сейчас живёт в
   `usecases/progress_announcer.py` вместе с политикой анонса. Помечен в коде
   (`# BOB-062.6 candidate`) как кандидат на переезд в conversation-срез — сейчас НЕ
   разделяем, чтобы не тащить лишний шов в этот переезд.
3. **`capabilities → memory` через порт `MemoryRecall`.** Навыки `recall_memory` /
   `search_memory` держат ТОЛЬКО инжектированный порт `MemoryRecall` (публичная
   поверхность memory), без своего I/O. Ребро наружу, чисто, через фасад, циклов нет
   — помечено в правилах границ как легализованное.
4. **`web_search_qwen` вынесен из `llm`.** Транспорт `QwenWebSearchProvider` переехал
   из `infrastructure/llm/` в `capabilities/adapters/` (это web-навык шва, а не
   базовый LLM-провайдер). Ребро `llm.factory → capabilities.adapters` (RUNTIME
   cross-infra) — новое, помечено legalized.
5. **kernel персистентности не трогаем** (вариант C, до среза .7): capabilities не
   держит долговечных сторов, зависимость на SQLite-kernel отсутствует.

## Спецификация

### Раскладка модуля

```
src/bob/capabilities/
  ports.py            # layer=domain          — 19 портов-протоколов + value-object'ы шва
  __init__.py         # layer=domain          — фасад (re-export стабильных портов)
  diagrams/           # layer=domain            (чистый разбор inline-mermaid, BOB-037)
    mermaid_blocks.py #                        — extract / strip / normalize fenced ```mermaid
  introspection/      # layer=domain            (чистые инварианты самоинтроспекции)
    privacy_guard.py  #                        — PrivacyGuard: приват-инвариант полного-репо доступа (BOB-017→BOB-067); чистое ядро _allows_path/_sanitize/_resolve вынесено на уровень модуля (mutation-testable)
    code_history.py   #                        — чистые парсеры git↔беады↔фича-доки (BOB-038)
    dev_query.py      #                        — чистая валидация dev-интроспекции: clamp_commit_count/validate_bead_id(инъекция-гард)/normalize_status/is_bead_id/sanitize_search_term (BOB-081, BOB-090.A, mutation-ядро)
    tracker_intent.py #                        — TrackerPlan/plan_tracker_query/find_bead_key: какой read по трекеру отвечает на вопрос (ready/list/show/search), BOB-090.A
    tracker_digest.py #                        — digest_search_results/MAX_DIGEST_ITEMS: длинная выдача bd search → сводка + важное + «Скрыто: N», BOB-090.A
    graph_form.py     #                        — GraphForm/plan_graph_form/validate_graph_ref/clamp_graph_depth/diagram_carries_nodes: какая из ТРЁХ разрешённых форм `beadloom graph` отвечает на просьбу нарисовать + валидация слотов argv (BOB-091.1, mutation-ядро)
    impact_digest.py  #                        — digest_impact/MAX_IMPACT_ITEMS/MAX_SUBJECT_CHARS: `beadloom why` (197 строк Rich-рамок и ASCII-дерева) → узел + «Зависит от» + «Влияет на» + честный счёт транзитивных (BOB-091.1, mutation-ядро)
    health_form.py    #                        — HealthForm/plan_health_form/normalize_check/validate_git_ref: КАКОЙ из шести read-only отчётов beadloom (status/prime/doctor/sync-check/lint/diff) просят + его фиксированный argv; 🔴 `lint` планируется как `--no-reindex --strict` (плоский lint ПЕРЕиндексирует, то есть пишет) (BOB-091.2, mutation-ядро)
    health_digest.py  #                        — digest_health/MAX_LISTED_ITEMS/MAX_REPORT_LINES/MAX_DOMAIN_CHARS: сжатие отчёта по его виду (585 строк пар → счёт + только stale; porcelain-кортежи lint → читаемые строки, включая ОБЕ реальные формы — с файлом и с ПУСТЫМИ файлом/строкой у правил про узел и ребро, BOB-091.4; 39 КБ prime → шапка + домены + счёт правил; diff хранит последнюю строку сводки) (BOB-091.2, mutation-ядро)
  usecases/           # layer=application
    registry.py       #                        — CapabilityRegistry + SafeCapabilityDispatcher
    tool_loop.py      #                        — ToolLoop: model↔tools раунд-трип до финала
    progress_announcer.py — GatewayProgressAnnouncer + InterimLineGenerator (🔴 → .6)
    recall_memory.py  #                        — авто-recall над MemoryRecall (тонкий)
    search_memory.py  #                        — агентный поиск памяти над MemoryRecall
    read_code.py      #                        — чтение любого файла репо (путь → read_file, иначе search)
    list_dir.py       #                        — перечень записей директории репо (BOB-067, read-only, не рекурсивно)
    find_file.py      #                        — поиск файлов по имени/glob по всему дереву (BOB-067, .git-skip, кап)
    inspect_architecture.py — граф-контекст через RepoIntrospector (beadloom ctx/graph/why)
    list_work.py      #                        — свой трекер через RepoIntrospector (bd ready/show/list/search; план чтения — tracker_intent, BOB-090.A)
    code_rationale.py #                        — код↔«почему»: git↔беады↔фича-доки↔граф (BOB-038)
    recent_commits.py #                        — git log -n N repo-wide (BOB-081, read-only, за флагом dev_tools)
    list_tasks.py     #                        — bd list по статусу (BOB-081, read-only)
    show_task.py      #                        — bd show <id> детали (BOB-081, read-only)
    task_comments.py  #                        — bd comments <id> (BOB-081, read-only)
    draw_architecture.py —                     — схема архитектуры: mermaid-ИСТОЧНИК модели для слов + САМ ставит отрендеренную картинку в общий DiagramSink (beadloom graph: обзор / узел с --depth / C4-компоненты в --scope) (BOB-091.1/.6, за флагом architecture_tools)
    architecture_impact.py —                   — «что сломается, если тронуть X» (beadloom why, сжато) (BOB-091.1, за флагом architecture_tools)
    project_health.py #                        — «как дела у проекта»: ОДИН инструмент над закрытым перечнем шести read-only отчётов beadloom (BOB-091.2, за тем же флагом architecture_tools)
    web_search.py     #                        — заземлённый веб-поиск (BOB-053)
    read_url.py       #                        — чтение одной ссылки за SSRF-щитом (BOB-054)
    render_diagram.py #                        — mermaid→PNG в чат + CollectingDiagramSink (BOB-035)
    diagram_attachment.py —                    — DiagramAttachment: ОДИН шов «отрендерить и поставить картинку в очередь хода» (общий для render_diagram и draw_architecture; дедуп по источнику) (BOB-091.6)
    diagram_sender.py #                        — DiagramSender: авто-рендер inline-mermaid + drain sink → отправка (коллаборатор handle_message, BOB-062.6b)
    send_to_chat.py   #                        — отправка в УКАЗАННЫЙ чат/топик по просьбе owner'а: адрес (destination) + гейт переноса приватного (disclosure) + заземление упоминаний (mention); за флагом social.delivery, default OFF (BOB-090.B1)
    delivery_scope.py #                        — DeliveryScope + armed_delivery_scope/current_delivery_scope: обстоятельства ХОДА (кто просит, откуда, из какого материала) через ContextVar — нет хода, нет отправки (BOB-090.B1)
    turn_material.py  #                        — TurnMaterial/MaterialOrigin/MaterialTrailRecall: единый СЛЕД материала хода (метки «дверь + видимость», без содержимого), по которому считается перенос приватного (BOB-090.B-fix2)
  adapters/           # layer=infrastructure
    web/
      http_url_reader.py — HttpUrlReader: aiohttp GET за 🔴 SSRF-щитом + html.parser-извлечение
      factory.py      #                        — build_url_reader (конфиг read_url.*)
    diagrams/
      mmdc_renderer.py — SubprocessMmdcRenderer: mermaid→PNG локально через mmdc (не shell)
    introspection/
      subprocess_introspector.py — SubprocessRepoIntrospector: read-only beadloom/bd/git log
    web_search_qwen.py — QwenWebSearchProvider: web_search через Qwen Responses API (streamed)
```

### Capability-шов (стабильный контракт)

`Capability` (`ports.py`) — единственное, что GUPPI умеет делать для Боба:
объект называет себя (`name`), описывает себя (`description`), объявляет JSON-Schema
аргументов (`input_schema`), декларирует `permission` и `execute`'ится над декодированными
аргументами. 🔴 `permission` — РАБОТАЮЩЕЕ заявление (BOB-090.B-fix), а не задел на будущее:
`"safe"` значит «можно исполнять без человека», `"confirm"` — «действие видно людям или
необратимо, санкционировать должен человек», и автономная граница
(`SafeCapabilityDispatcher`) второе не исполняет. Раньше поле было декоративным, поэтому
ошибка в `goals.safe_capabilities` делала автономной даже необратимую отправку.
Новые навыки регистрируются под этим контрактом; потребители не меняются.
Это именно **шов**, не плагин-машинерия (sandboxing / discovery / self-creation —
позже за тем же контрактом).

`CapabilityRegistry` (`usecases/registry.py`) — упорядоченный, name-unique индекс
того, что GUPPI может рекламировать и запускать: `register` (уникальное имя),
`manifest` (рендер зарегистрированных навыков как OpenAI `tools`-определений для
модели), `dispatch` (запуск навыка по имени — **исполняет GUPPI**), `describe`
(короткий prose-манифест для системного промпта Боба) и `permission_of` (что навык
заявляет о необходимости человеческой санкции; незарегистрированное имя не заявляет
ничего — `None`). Чистая application-политика: держит capability-объекты, транспорта не
касается. `SafeCapabilityDispatcher` — allowlist-ограниченный вид над реестром: жёсткая
граница автономного тика (BOB-015), пропускает ТОЛЬКО то, что и внесено в явный
safe-allowlist (`goals.safe_capabilities`), И само объявляет себя `"safe"`; навык вне
allowlist недостижим по конструкции, навык с `permission="confirm"` — тоже. Пустой
allowlist = автономно ничего не запускается (консервативный дефолт); неизвестное имя не
допускается никогда (сомнение отказывает).

`ToolLoop` (`usecases/tool_loop.py`) — акт-сторона шва: гонит раунд-трип
`модель ↔ инструменты` до финального текста. Просит `ToolCallingProvider` завершить
ход, предлагая манифест как `tools`; если модель запросила tool_calls —
**диспетчеризует** каждый через реестр (исполняет GUPPI), дописывает ассистент-ход
и `tool`-результаты, переспрашивает; capает число ходов (`_DEFAULT_MAX_TURNS = 6`),
чтобы зациклившаяся модель не убежала. Неизвестный tool не фатален — ошибка
скармливается обратно как tool-результат, чтобы модель восстановилась. Перед
**медленным** навыком опционально зовёт `ProgressAnnouncer` (interim-строка); любая
ошибка анонсера глотается — декоративная строка не может задержать/сломать dispatch.

🔴 **Анти-нарратив backstop (BOB-074, recall-poisoning).** Прошлые реплики, где Боб
описывал намерение GUPPI («GUPPI пошёл… заглянет… ищет… ждём отчёт») вместо реального
результата, оседали в истории и учили Qwen мимикрировать этот нарратив — модель отвечала
рассказом о намерении, а не вызывала инструмент. Backstop: ход БЕЗ `tool_calls`, чей
текст распознан как нарратив о намерении GUPPI, — не настоящий ответ. Тогда петля ОДИН раз
переспрашивает с жёстким системным нюджем «вызови нужный инструмент СЕЙЧАС и верни реальный
результат» (`_NARRATION_NUDGE`). Ретрай **ограничен**: флаг `retried` на весь `run`, поэтому
упорный нарратив не может зациклиться, и **никогда** на последнем ходу (это опустило бы ниже
до-backstop поведения). Если переспрос всё равно нарративит или отвечает обычным текстом — этот
текст возвращается, то есть backstop не хуже прежнего.

Предикат `_looks_like_tool_narration(text)` — чистая функция, намеренно **консервативная**
(GUPPI-заякоренная): срабатывает ТОЛЬКО когда текст содержит И GUPPI-токен (`guppi`/`гаппи`/
`гуппи`), И маркер намерения в настоящем времени (`пошёл`/`заглян`/`ищет`/`ждём отчёт`…).
Обычная реплика без GUPPI, легитимное упоминание GUPPI с реальным результатом и мгновенный
`tool_call` предикат не трогают. Промах стоит лишь до-BOB-074 поведения, ложное срабатывание —
одного лишнего вызова Qwen, поэтому сигнатура держится узкой. Правило-близнец в промпте
(анти-few-shot преамбула манифеста, personality `_CAPABILITY_PREFACE`) давит нарратив ещё на
входе; backstop — страховка на выходе.

🔴 **Структурный ассистент-ход, без утечки `[tool_calls]` (BOB-069).** `_assistant_turn`
собирает интент модели в НАТИВНЫЙ массив `tool_calls` схемы OpenAI, а не в текстовую строку
`[tool_calls] …`, засунутую в `content`. Каждый вызов становится
`{"id","type":"function","function":{"name","arguments"}}`, где `arguments` — JSON-СТРОКА (как
ждёт OpenAI), а `id` совпадает с `tool_call_id`, который `_run_tool` кладёт на результат — так
модель связывает каждый `tool`-результат со своим вызовом и доходит до финального текста.
Прежняя строковая форма оставляла переспрос кривым (ассистент-ход без `tool_calls`,
`tool`-результат ссылается на `id`, которого нет в истории), из-за чего Qwen эхом возвращал
строку и она текла в чат. Реплики петли типизированы `ToolLoopMessage` (значение может быть
массивом `tool_calls`, см. `kernel/ports.py`); инвариант «reply с `[tool_calls] ` НИКОГДА не
течёт в чат» держит инфра-парсер `infrastructure/llm/openai_compat.py` (распознаёт hermes
`<tool_call>{…}` и эхо-форму).

### Навыки (application)

- **Память.** `recall_memory` — тонкий авто-recall (GUPPI молча заземляет ответ) над
  портом `MemoryRecall`. `search_memory` — первый **агентный** навык: Боб сам решает
  искать в своём архиве, гоняет гибридный recall, модель может тюнить `k`
  (бессмысленные значения клампятся к безопасному дефолту). Оба держат только порт
  `MemoryRecall`, своего I/O нет.
- **Самоинтроспекция и навигация по репозиторию (BOB-017/038/067).**
  `inspect_architecture` (граф-контекст через `RepoIntrospector.architecture_context`),
  `read_code` (один `query`: путь → `read_file` теперь по ЛЮБОМУ файлу репо, иначе →
  `search_code`), `list_work` (`RepoIntrospector.list_tasks` — `bd show`/`bd ready`),
  `code_rationale` (код↔«почему»: `code_history` → `parse_bead_refs` → фича-доки
  PRD/RFC/BRIEF + bracketing-коммиты + граф в один компактный ответ; при отсутствии
  decision-ключа — честное «история не зафиксирована», не выдумка). BOB-067 добавил два
  навигационных навыка: `list_dir` (`RepoIntrospector.list_dir` — перечень записей одной
  директории репо: имя + вид `file`/`dir` + размер, не рекурсивно) и `find_file`
  (`RepoIntrospector.find_file` — поиск файлов по имени/glob по всему дереву, `.git`
  пропускается, результат капается). Оба императивно требуют от Боба ВЫЗВАТЬ инструмент и
  доложить РЕАЛЬНЫЙ листинг/совпадения (INV-N1), а на пустом выводе дают честное
  «не нашёл», а не выдумку. Все шесть — фабрики `make_*_capability(introspector)`,
  `permission="safe"`, только-разговор (не в автономном allowlist). Приват-инвариант
  живёт ВНУТРИ порта, не у вызывателя.
- **Dev-интроспекция: git-история + трекер (BOB-081, read-only).** Живой баг: Боб упирался
  в стену на «глянь последние коммиты / посмотри закрытые задачи / историю git» — не мог
  заземлить разговор о работе. Четыре разговорных навыка над тем же `RepoIntrospector`:
  `recent_commits` (`git log --oneline -n N`, repo-wide — раньше `git log` требовал `--grep`/
  `-- path`), `list_tasks` (`bd list --status <enum>` — задачи по статусу; сосед `list_work` —
  свободный запрос/ready-очередь), `show_task` (`bd show <id>` — детали), `task_comments`
  (`bd comments <id>` — комментарии/чекпоинты, новая read-подкоманда). 🔴 **Строго read-only:**
  git-allowlist остаётся `{log}` (fixed-forms; `show`/`diff`/`commit`/`push` невыразимы),
  bd-allowlist — `{ready,show,list,comments,search}` (`search` добавлен в BOB-090.A); все
  мутирующие подкоманды (`bd create/update/
  close`, singular `bd comment`, `git commit/push/checkout`) отклоняются. Валидация значений —
  чистое ядро `capabilities/introspection/dev_query.py` (`clamp_commit_count` [1,50];
  `validate_bead_id` — только форма bead-key, инъекция-гард против `--flag`/`;`/`../`;
  `normalize_status` — allowlist + RU-синонимы; `sanitize_search_term` — свободное слово
  поиска: управляющие символы становятся разделителями, флагоподобные токены
  выбрасываются, длина капается `MAX_SEARCH_TERM_CHARS`, а от строки, состоящей из одних
  флагов, остаётся `None` — «поиск не запускать», а не угаданный запрос; `is_bead_id` —
  предикат формы ключа). subprocess — `exec` (не shell); санитайз
  секретов наследуется от `_run` (INV-3); авторизация — существующий `is_guest`-гейт (гость
  инструментов не получает). За под-флагом `introspection.dev_tools` (default OFF → навыки не
  регистрируются). Пусто/битый id → честный ответ, не выдумка/не краш.
- **Схема архитектуры и влияние (BOB-091.1, read-only).** `graph` и `why` лежали в
  allowlist адаптера с самого начала, но были МЁРТВЫМИ записями — до них не доходил ни один
  метод порта, поэтому Боб не мог ни нарисовать схему, ни ответить «что сломается, если
  тронуть memory». Два навыка над тем же `RepoIntrospector`: `draw_architecture`
  (`architecture_diagram` → `ArchitectureDiagram(mermaid, form, requested)`) и
  `architecture_impact` (`impact` → сжатый `beadloom why`). 🔴 **Решение owner'а:**
  `draw_architecture` отдаёт модели **mermaid-ИСТОЧНИК** (Боб объясняет схему словами) и
  **сам** ставит отрендеренную картинку в тот же per-turn `DiagramSink`, что и
  `render_diagram` — то есть owner получает и объяснение, и изображение, а молчаливый PNG
  по-прежнему невыразим (текст ответа всегда пишет модель).
  🔴 **BOB-091.6 — почему связка стала СТРУКТУРНОЙ.** Сначала связка «объясни словами И
  вызови `render_diagram`» жила ТОЛЬКО в описании инструмента, то есть в уговоре с
  моделью, — и живой смоук показал ровно её отказ: Боб вызвал `draw_architecture`, получил
  5 КБ настоящего mermaid, грамотно разобрал схему словами и картинки не прислал (второго
  вызова не сделал). Ни результат вызова, ни цикл инструментов к рендеру не толкали.
  Теперь рендер — часть рисования: общий
  [`DiagramAttachment`](../../../src/bob/capabilities/usecases/diagram_attachment.py)
  (тот же локальный рендерер + тот же синк) рендерит ОДИН раз, дедуплицирует по источнику
  (два инструмента на одну схему = одна фотография) и НЕ бросает наружу — сбой рендера
  возвращается как честная строка `picture`, а не как исключение хода. Слова гарантированы,
  картинка — best-effort. Пустой граф и отказанный ref не рендерятся вовсе.
  🔴 **Урок про тесты (§0.3 п.4/п.10):** прежние юниты и BDD доказывали, что в ОПИСАНИИ
  инструмента есть слово `render_diagram`, — ассерт про текст обещания, а не про поведение.
  Связка закрыта тестом ЧЕРЕЗ ГРАНИЦУ (вызов → картинка в синке И mermaid модели) плюс
  сквозным прогоном на НАСТОЯЩЕМ `mmdc` и НАСТОЯЩЕМ `beadloom graph` этого репозитория,
  в том числе через боевую сборку `_build_registry`
  (`tests/infrastructure/diagrams/test_real_architecture_render.py`). Формы argv — ФИКСИРОВАННЫЕ (как
  `_BD_LIST_ARG_FORMS`): обзор (без аргументов), `<ref> [--depth <N>]` (N клампится в
  [1,5]), и C4-внутренности одного контейнера
  (`--format c4 --level component --scope <ref>`); membership-check выполняется ДО запуска,
  поэтому `--project` (ЧУЖОЙ репозиторий!), `--json`, другой формат и любая write-подкоманда
  (`reindex`/`docs`/`link`/`setup-*`/`active-sync`/`sync-update`) невыразимы никаким
  аргументом. `beadloom why` принимает РОВНО один валидированный ref. Честные деградации:
  `--scope` на ЛИСТЕ графа печатает один заголовок `C4Container` (живой факт), поэтому форма
  сходит к схеме связей узла и `form != requested` — модель получает поправку «внутренностей
  нет, это связи», а не подмену вида; пустой граф → честное «не нашёл», а не пустая
  картинка. За под-флагом `introspection.architecture_tools` (default OFF → навыки не
  регистрируются).
- **Состояние проекта (BOB-091.2, read-only).** Остальной READ-ONLY beadloom одним
  навыком `project_health` (`project_health` → `ProjectHealth(check, report)`): `status`
  (числа индекса), `prime` (компактный контекст), `doctor` (целостность графа),
  `sync-check` (свежесть доков), `lint` (границы), `diff --since <git-ref>` (что изменилось
  в графе). 🔴 **Один инструмент, а не шесть:** манифест и без того большой, и шесть
  почти-одинаковых инструментов ухудшили бы выбор модели; аргумент — значение из ЗАКРЫТОГО
  перечня, и это же его форма безопасности — модель не называет подкоманду beadloom, поэтому
  write-команды того же CLI невыразимы даже опечаткой (отказ при этом ПЕРЕЧИСЛЯЕТ допустимые
  отчёты, иначе модель повторит ту же ошибку). Формы argv фиксированные, membership-check ДО
  запуска: `status`/`prime`/`doctor`/`sync-check` — БЕЗ аргументов (поэтому `prime --update`,
  который ПЕРЕПИСЫВАЕТ `AGENTS.md`, и `--project <чужой репозиторий>` невыразимы),
  `lint --no-reindex --strict`, `diff --since <git-ref>` со строгой валидацией слота (флаг,
  путь, диапазон `a..b`, reflog-синтаксис, метасимвол — отказ ДО запуска).
  🔴 **Две находки живого прогона, которых фейк не дал бы.** (1) ПЛОСКИЙ `beadloom lint`
  сам делает reindex, то есть ПИШЕТ в индекс (замерено по sha256 `.beadloom/beadloom.db`),
  поэтому `--no-reindex` — часть read-only инварианта, а не вкусовщина; цена названа честно:
  вердикт читается по СОХРАНЁННОМУ индексу, и дайджест это говорит вслух (по стоячему
  правилу §0.3 п.1 lint на несвежем индексе врёт). А `--strict` обязателен потому, что
  плоский `lint` отдаёт rc=0 даже при error-нарушении. (2) При нарушении lint печатает в пайп
  МАШИННЫЙ porcelain (`rule:kind:severity:file:line:from:to`) и строки «0 violations» в этом
  случае НЕТ вовсе — дайджест переводит кортежи в человеческие строки.
  🔴 **И у этого porcelain ДВЕ реальные формы, а не одна (BOB-091.4, Critical-1).** Правило
  про ФАЙЛ заполняет `file`+`line`; правило про УЗЕЛ или РЕБРО (бюджет символов, цикл,
  `require`, слой) оставляет оба поля ПУСТЫМИ и заполняет `from`/`to`. Срез 2 снял фикстуру с
  одного живого образца (`forbid_import` — единственный вид, у которого файл есть), поэтому
  вердикт НЕ ВИДЕЛ узловых нарушений: на смешанном входе он говорил «Нарушений: 1», ЦИКЛ
  исчезал молча (ровно тот класс дефекта, из-за которого написано правило §0.3 п.1), а
  собеседник получал сырую машинную строку вместо ответа. Теперь разбор позиционный и
  терпимый к пустым слотам, локация печатается той, какая есть (`файл:строка` / узел /
  `from → to`), а **любая** машинная строка, которую дайджест не смог прочитать, ВСЁ РАВНО
  попадает в счёт и называется вслух как неразобранная — сырой porcelain не выходит наружу ни
  в одной ветке. Оговорки `lint` и `sync-check` приклеивает сам ДИСПЕТЧЕР дайджеста (после
  капа), поэтому «всегда» из докстринга — структура, а не обещание: ветка честной деградации
  их потерять не может.
  🔴 **Ненулевой код возврата — РЕЗУЛЬТАТ, а не сбой:** `lint` отдаёт 1 при нарушении,
  `sync-check` — 2 при устаревшей паре, `diff` — 1 при изменениях. Это структурно безопасно:
  раннер возвращает stdout и НИКОГДА не смотрит `returncode`, поэтому Боб отвечает «доки
  отстали», а не «не смог посмотреть»; проверено на РЕАЛЬНОМ beadloom (живой `diff` с rc=1) и
  на настоящем подпроцессе с `exit(2)`. Отдельно проверено, что `sync-check` (он трогает файл
  индекса) НЕ прячет staleness при повторном прогоне — сигнал для человеческого гейта не
  стирается. Сжатие честное: 48 КБ / 585 строк пар → счёт + только устаревшие пары (+ оговорка,
  что пары строятся не для всех узлов, §0.3 п.2), 39 КБ `prime` → шапка + домены + СЧЁТ правил
  (agent-instruction секции выброшены — это инструкции тулчейну, не факты о проекте).
  🔴 **Сжатие идёт ДО капа вывода** (`_run(..., condense=...)`) — и это тоже находка живого
  прогона, а не вкус: интроспектор режет сырой вывод на 20 000 символах, поэтому дайджест,
  применённый ПОСЛЕ капа, считал только влезшее и уверенно отвечал «274 пары» вместо 585, а у
  `prime` кап съедал самое ценное — секции про домены, устаревшие доки и нарушения (они в конце
  отчёта, после списка правил). Неверное число, сказанное уверенно, хуже дампа. `beadloom why`
  (срез 1) переведён на тот же порядок — 14 КБ живого вывода в одном графе от капа.
  Вне scope сознательно (BRIEF): `tui`/`ui`/`watch`/`mcp-serve` (интерактивные),
  `export`/`snapshot compare`/`config-check` (инертные для Боба) — их невыразимость
  ассертится тестом, а не документируется. За тем же под-флагом
  `introspection.architecture_tools` (default OFF): весь read-only beadloom — одна
  отгружаемая часть, один переключатель.
- **Трекер отвечает вместо «пусто» (BOB-090.A).** На «расскажи про BOB-087» и «какие
  задачи открыты» Боб честно отвечал «такой задачи не существует» / «пусто»: `bd show`
  понимает только точный id, а ключ эпика живёт в ЗАГОЛОВКАХ задач. Теперь `list_work`
  сперва планирует чтение чистым ядром `tracker_intent.plan_tracker_query(query)` →
  `TrackerPlan` (`ready` / `list` / `show` / `search`), `find_bead_key` вынимает ключ из
  фразы («расскажи про нашу задачу BOB-087» → `BOB-087`). Деградации честные: id, который
  `bd show` не резолвит, повторяется поиском по заголовку, а поиск без совпадений сходит к
  обычному листингу, а не к молчанию. Поиск идёт фиксированной формой
  `bd search <term> --status all` — без `--status all` закрытый эпик не нашёлся бы вовсе, а
  никакой другой флаг поиска невыразим. Длинная выдача сжимается чистым
  `tracker_digest.digest_search_results` — сводка по статусам, сам эпик и незакрытые
  задачи, затем честная строка «Скрыто: N», — вместо простыни на 39 строк. Описания
  навыков, которые видит модель, переписаны на язык проекта и прямо говорят, что ключ
  эпика подойдёт и что можно спросить «какие открыты».
- **Web (BOB-053/054).** `web_search` — заземлённый веб-поиск над `WebSearchProvider`:
  проецирует `answer` + `sources` компактно в tool-loop, Боб синтезирует финал своим
  голосом со ссылками. `read_url` — близнец: открывает ОДНУ конкретную ссылку через
  `UrlReader` (SSRF-guarded), проецирует `url` + `title` + excerpt. Оба
  `permission="safe"`, read-only; привилегия — по отправителю (authz/BOB-052), не
  здесь. 🔴 Отказоустойчивость (BOB-049): оба **essential** — раз модель решила
  искать/читать, transient-сбой RETRIED ограниченно с backoff
  (`application.reliability.call_with_retry`, инжектированный sleep-сейм); при полном
  провале — честный «couldn't search/open» нотис с анти-конфабуляционным `guidance`,
  НИКОГДА выдуманный контент. `SsrfBlockedError` детерминирован → surface немедленно,
  без трат retry-бюджета.
- **Диаграммы (BOB-035/037).** `render_diagram` — mermaid→PNG ЛОКАЛЬНО через
  `DiagramRenderer`, `push` результата в per-turn `CollectingDiagramSink`, возврат
  короткого TEXT-подтверждения (модель байты не видит). Рендерит ТОЛЬКО свой INPUT
  (личных данных не читает). На сбое рендера — честное «renderer unavailable», ход не
  падает.
- **Отправка диаграмм хода (BOB-062.6b, #9).** `DiagramSender` (`usecases/diagram_sender.py`)
  — коллаборатор `handle_message`, собираемый в `HandleMessage.__init__`. После генерации
  ответа `autorender_inline_mermaid` рендерит ` ```mermaid `-блоки, что модель написала
  ТЕКСТОМ (дедуп против sink, стрип обработанных блоков из видимого текста), а `send_pending`
  `drain`-ит per-turn `DiagramSink` и постит каждый PNG как фото/документ через транспортный
  шов `DiagramGateway` в `chat_id` хода, перед текстом. 🔴 Общий инстанс `diagram_sink`
  инъектируется И в `DiagramSender`, И в registry-навык `render_diagram` — push/drain на одном
  объекте.

### Отправка в другой чат (`send_to_chat`, BOB-090.B1, флаг `social.delivery`, default OFF)

Недостающая половина адресации: до этого среза исходящего адреса не существовало как
понятия — ответ всегда уходил в `chat_id` текущего хода, поэтому просьба из лички
«расскажи Норману в нашей группе» была невыполнима. Заведён именно ИНСТРУМЕНТ, а не
перенаправление готового ответа: реплика, сочинённая для owner'а в личке, комнате не
адресована, поэтому аргументом `text` модель пишет то, что должно появиться ИМЕННО ТАМ.

Своей политики у навыка нет — он собирает чужие чистые ядра в фиксированном порядке:
`resolve_destination` (адрес или «переспроси»), `transfer_needs_consent` (нужно ли
согласие owner'а на вынос приватного) и `ground_mentions` (заземление упоминаний на
ростер) — все три из `social`. Вердикты «переспроси» / «нужно согласие» возвращаются
МОДЕЛИ подсказкой, и Боб переспрашивает своими словами: ни одной скриптованной реплики.
Транспорт — порт `OutboundMessenger` (реализация `TelegramOutboundMessenger` поверх
существующего rich-шва, нового транспорта эпик не заводил).

🔴 **Никакой автономии (урок BOB-076).** Обстоятельства хода приходят из `DeliveryScope`
через `ContextVar`, а не из общего мутабельного холдера: реестр capability общий и живёт
весь процесс, ходы живут в разных задачах, и общий атрибут означал бы, что признак «просит
owner» одного хода достанется другому. Нет армированного хода — нет отправки. Навык
объявляет `permission="confirm"`, поэтому автономная граница его не исполняет даже при
ошибочной записи в `goals.safe_capabilities`.

🔴 **След материала хода — `TurnMaterial` (B-fix2).** Гейт переноса обещает считать перенос
«по материалу», но читал ОДНУ дверь — авто-recall, снятый до генерации. Материал приходит
ещё как минимум тремя: выдачей `search_memory` / `recall_memory` в том же tool-loop,
grounded-addon callback'ом и реплеем нити, — и живой вызов показал, что приватное уезжало в
комнату без вопроса. Лечение — не четвёртая проверка, а ОДИН след: набор меток «дверь +
видимость» **без содержимого** (в `ContextVar` не оседает переписка), армируемый на ВЕСЬ
ход в `HandleMessage.handle`.

Три механизма против «тихой двери»:

1. **Дверь к памяти ровно одна.** Порт `MemoryRecall` собирается в единственном месте
   (композиционный корень) и обёрнут декоратором `MaterialTrailRecall`, поэтому все
   нынешние и будущие потребители попадают в след по построению, без строчки учёта у себя.
   Архитектурный тест держит, что источник порта конструируется только там.
2. **Дверь НЕ к памяти обязана назвать себя** новым значением `MaterialOrigin`, а политика
   перечисляет ИСКЛЮЧЕНИЯ (`_NOT_A_TRANSFER`) — незнакомая дверь считается переносимым
   материалом по умолчанию (fail-closed).
3. **Отсутствие следа спрашивает согласие.** Неармированный ход даёт `TurnMaterial.unknown()`
   — «материал мог быть приватным», — а не молчаливый пропуск.

🔴 **Карве-аут назван, а не забыт.** Живая нить помечается дверью `LIVE_THREAD` с видимостью
самого разговора и переносом НЕ считается: иначе гейт горел бы на каждой отправке из лички
и Боб снова отказывал бы owner'у в прямом распоряжении. Остаточный риск (в нити есть
собственные прошлые реплики Боба, а в них — сказанное третьим человеком) записан прямо в
`_NOT_A_TRANSFER`. Гейт этого не удержит, и по решению owner'а удерживать не нужно.

Честно о силе: след — НАДМНОЖЕСТВО того, что доехало до промпта (порт отмечается тем, что
подняла память, ещё до фильтрации под аудиторию и подреза по `k`), поэтому гейт может
спросить лишний раз. Сторона ошибки выбрана осознанно: лишний вопрос владелец видит, тихий
пропуск — нет.

### Адаптеры (infrastructure)

`HttpUrlReader` (`adapters/web/http_url_reader.py`) реализует `UrlReader`: один
`aiohttp` GET за 🔴 **SSRF-щитом** (guard прогоняется ДО открытия сокета и на каждом
redirect-хопе), схема только `http`/`https`, redirect'ы вручную и ре-валидируются,
content-type allowlist `text/html`/`text/plain`, стриминг тела с обрывом по
`max_bytes`, извлечение через stdlib `html.parser`. `SubprocessMmdcRenderer`
(`adapters/diagrams/mmdc_renderer.py`) реализует `DiagramRenderer`: локальный `mmdc`
через `create_subprocess_exec` (не shell), таймаут, temp-dir убирается всегда, на
сбое — `DiagramRenderError`. `SubprocessRepoIntrospector`
(`adapters/introspection/subprocess_introspector.py`) реализует `RepoIntrospector`:
`beadloom`/`bd`/`git log` через `create_subprocess_exec` против ФИКС-allowlist
read-only подкоманд (не shell); `read_file` спрашивает `PrivacyGuard` ДО открытия.
`QwenWebSearchProvider` (`adapters/web_search_qwen.py`) реализует `WebSearchProvider`
над Qwen MaaS **Responses API** (`/responses`, не `/chat/completions`), **стримингом**
(`stream: true`, переживает 1-2-минутный поиск), парсит терминальный
`response.completed` → `output[]` (`web_search_call` → `sources`, `message` → answer).
Все адаптеры инжектируют subprocess/opener-сейм, поэтому тесты не спавнят процессы и
не ходят в сеть.

## Инварианты

- **🔴 SSRF-guard (`read_url`).** `HttpUrlReader` отклоняет ЛЮБОЙ resolved IP из
  private / loopback / link-local / reserved / multicast / unspecified (loopback
  `127/8` / `::1`, приватные `10/8` / `172.16/12` / `192.168/16`, cloud-metadata
  на link-local `169.254/16`, IPv6 `fc00::/7` / `fe80::/10`); guard прогоняется до
  коннекта И на каждом redirect. Блок → `SsrfBlockedError` (отдельный тип: не
  retry'ится, честно отказывается).
- **🔴 PrivacyGuard — полный доступ ко всему репозиторию (BOB-067).** Осознанный выбор
  владельца: Боб — равный инженер, работающий по ВСЕМУ репо, а не по узкому whitelist'у.
  `allows_path` РАЗРЕШАЕТ любой путь, который резолвится ПОД корнем репо (всё рабочее
  дерево: `src`, `tests`, `docs`, `.beadloom/`, `config/`, `data/`, сам корень, любой
  исходник/тест/документ). Отказ ТОЛЬКО на ВЫХОД за границу репо: путь, который уходит
  вверх через `..` за корень, либо абсолютный путь вне репо (симлинк наружу тоже) —
  `relative_to` бросает, чтение отклоняется по конструкции. `ALLOWED_ROOTS=(".",)` —
  единственная граница есть сам корень репо, адаптер сверяет по ней симлинк-контейнмент.
  Guard — чистый доменный объект (без I/O/LLM/промпта), его нельзя обойти тем, что скажет
  модель; путь резолвится (`..` схлопывается, без обращения к диску) до проверки
  контейнмента. Чистое ядро вынесено на уровень модуля (`_allows_path` / `_sanitize` /
  `_resolve`), методы делегируют — так security-инвариант остаётся mutation-testable,
  а публичный API `PrivacyGuard` неизменен.
- **🔴 `sanitize` — секрет-backstop (INV-N4).** Полный доступ на ЧТЕНИЕ не означает утечку
  литеральных секретов: `sanitize` сохранён как defence-in-depth и вычищает
  секрет-подобные значения → `[REDACTED]` из любого возвращаемого текста, даже с
  разрешённого пути или из CLI. Литеральная строка секрета не покидает машину. BOB-067.6
  (hotfix INV-N4-дыры, пойманной живым smoke): паттерны усилены под РЕАЛЬНЫЙ формат `.env`,
  который отдаёт `read_file` — (1) присваивание секрет-ИМЕНОВАННОМУ ключу (имя СОДЕРЖИТ
  `token|key|secret|password|api|credential|auth`, без `\b`, так что `__TOKEN`/`_API_KEY`
  ловятся, с любым отступом) маскирует значение справа от `:`/`=`, ключ читаем
  (`FOO_TOKEN=[REDACTED]`); (2) `sk-`-шейп С ТОЧКАМИ/подчёркиваниями (Qwen-ключ
  `sk-xx.yyyy.zzzz`); (3) telegram-бот-токен `<цифры>:<длинный-base64>` по ШЕЙПУ значения.
  Over-redaction ограничен: обычный код, лишь упоминающий `key`/`token` без присваивания
  секрет-значения, не трогается (баланс security-first — недо-маскировка утекает живой
  ключ во внешний LLM, пере-маскировка редкой строки кода косметична).
- **🔴 Узкий doc-фильтр coder-преамбулы (`coding_context`).** Расширенный full-repo guard
  НЕ протекает во внешнюю coder-преамбулу: `coding/usecases/coding_context._is_safe_doc_path`
  — своя, НАМЕРЕННО более узкая политика курации (сегмент-префикс по `src` / `tests` /
  `docs` / `.claude/dev-docs` / `.claude/development/docs`). Personal-data документ
  (SOUL / `bob.db` / `.env` / `config` / настройки `.claude`) не проходит и не попадёт во
  внешний coder-контекст, хотя в чате его прочитать теперь можно.
- **tool-loop.** Порядок tool_calls сохраняется; неизвестный/упавший навык не валит
  ход (ошибка → tool-результат); число ходов capается (`max_turns`).
- **🔴 Анти-нарратив backstop, ровно один ретрай (BOB-074).** Ход без `tool_calls`, чей
  текст распознан консервативным `_looks_like_tool_narration` как нарратив о намерении
  GUPPI (нужны И GUPPI-токен, И present-tense маркер намерения), переспрашивается ОДИН раз
  с жёстким нюджем на реальный tool call. Ретрай ограничен флагом `retried` на весь `run`
  (упорный нарратив не зацикливается) и не делается на последнем ходу; легит-ответ,
  GUPPI-упоминание с реальным результатом и мгновенный tool_call не трогаются; после
  переспроса текст возвращается как есть (никогда не хуже до-backstop поведения).
- **🔴 Петля инструментов смыкается в текст, `[tool_calls]` не течёт в чат (BOB-069).**
  Ассистент-ход собирается как СТРУКТУРНЫЙ `tool_calls`-массив OpenAI (`id`==`tool_call_id`,
  `arguments` — JSON-строка), а не текстовая строка `[tool_calls] …` в `content` — переспрос
  корректен, модель доходит до финального текста, а не эхо-строки. Инфра-парсер держит инвариант
  «reply с `[tool_calls] ` НИКОГДА не попадает в чат» (распознаёт hermes `<tool_call>{…}` и
  эхо-форму).
- **announce live-only (BOB-060).** Interim-строка генерируется ЖИВО на Tier-0
  `InterimLineGenerator`; при сбое/пустой строке/без генератора анонсер **молчит** —
  НИКОГДА не скриптовая фраза. Говорит только для `web_search` (по имени навыка),
  полностью декоративен (свои ошибки глотает).
- **web_search streaming.** Вызов стримингом (`stream: true`) — буферизованный POST
  дропается gateway'ем через ~30s, а живой поиск идёт 1-2 мин; читаем SSE построчно
  до `response.completed`. Любой сбой/оборванный стрим/malformed поле → **raise**
  (отказоустойчивость на стороне вызывателя, Боб не конфабулирует); пустой `sources`
  на успехе валиден.
- **safe-allowlist автономии.** `SafeCapabilityDispatcher` пропускает ТОЛЬКО навыки
  из `goals.safe_capabilities`, И только те, что сами объявляют `permission="safe"`
  (BOB-090.B-fix); introspection/web-навыки в allowlist НЕ добавлены — только разговор,
  автономный тик их не запустит. Пустой allowlist = автономно ничего.
- **🔴 Отправка вовне — только по просьбе owner'а, только в известный адрес
  (BOB-090.B1).** `send_to_chat` не существует, пока `social.delivery` выключен (не
  зарегистрирована → её нет в манифесте → модель не может её вызвать), и не регистрируется
  вовсе, если ни один адрес не настроен. При включённом флаге отправка требует
  армированного хода (`DeliveryScope`), а внутри хода — owner'а: отказ не-owner'у стоит
  первой проверкой ядра адреса. Адреса — закрытый список из конфига; `chat_id` модель
  передать не может.
- **🔴 След материала fail-closed (BOB-090.B-fix2).** Перенос считается по единому следу
  хода: неизвестная дверь считается переносимым материалом, отсутствие следа означает
  «материал мог быть приватным» и спрашивает согласие. Единственное исключение — живая
  нить разговора, и оно перечислено явным списком, а не подразумевается.

### Границы модуля (AaC) + 🔴 генератор правил

Дисциплина держится explicit-path `forbid_import`-правилами
(`.beadloom/_graph/rules.yml`), которые **генерирует** `scripts/gen_boundary_rules.py`
(BOB-062.4, этап A). Причина перехода на генератор: движок beadloom берёт в
`forbid_import` только одиночный glob, а прежняя схема изолировала модуль char-class'ом
(`src/bob/[adimp]*`) — но `capabilities` начинается на `c`, ровно как `coding`, и
fnmatch по первому символу их физически не различает (коллизия c/c). Генератор:

- читает `module-vertical`-узлы из `services.yml` и эмитит per-module правила на
  **explicit paths** (`src/bob/<module>/…`) в marker-регион
  `# BEGIN/END generated boundary rules`; рукописные rationale-блоки вне маркеров не
  трогает;
- рендер детерминирован (модули + источники отсортированы) → запись идемпотентна,
  режим `--check` — CI-gate, проверяющий синхронность региона;
- на каждый модуль эмитит `usecases-no-adapters`, `internals-no-usecases`,
  **`internals-no-adapters`** (закрывает дыру каркаса из test .3),
  `usecases-no-infra`, `no-composition-root` + inward-boundary правила от чужих
  бизнес-модулей;
- в модель inward-границы включён ТОЛЬКО `domain` (`INWARD_LAYER_SOURCES`):
  координационные слои (`application` / `infrastructure` / `runtime` / композиционный
  корень) исключены намеренно — они по определению собирают и зовут usecases/adapters
  модулей (`handle_message`, `privileged_fulfiller`, инфра-фабрики).

Намеренно разрешённые кросс-рёбра (все — на публичную поверхность):
`llm.factory → capabilities.adapters` (`QwenWebSearchProvider`, RUNTIME cross-infra,
legalized), `coding.usecases → capabilities` (`PrivacyGuard`, TC, перенос
существующего ref), `capabilities → memory` (`MemoryRecall`),
`handle_message` / `privileged_fulfiller → capabilities.usecases` (координация).

## API

<!-- beadloom:track=src/bob/capabilities/ports.py -->

Модуль `src/bob/capabilities/ports.py` (порты-протоколы + value-object'ы шва, 19
публичных символов):
- `Capability` (Protocol) — стабильный контракт навыка: `name`, `description`,
  `input_schema`, `permission`, `async execute(args)`.
- `ToolCallingProvider` (Protocol) — `async complete_with_tools(messages, *, tools)`
  → `ToolCallResult`; `messages` — `Sequence[ToolLoopMessage]` (BOB-069: реплика может нести
  структурный `tool_calls`-массив ассистента, см. `kernel/ports.py`). Реализация — инфра
  OpenAI-совместимый провайдер.
- `WebSearchProvider` (Protocol) — `async search(query)` → `WebSearchResult` (raise
  на сбое). Реализация — `QwenWebSearchProvider`.
- `UrlReader` (Protocol) — `async read(url)` → `WebPage` (raise/`SsrfBlockedError` на
  блоке). Реализация — `HttpUrlReader`.
- `RepoIntrospector` (Protocol) — read-only самоинтроспекция и навигация:
  `architecture_context`, `search_code`, `read_file(path, *, max_lines)`,
  `list_dir(path)` (записи одной директории, не рекурсивно), `find_file(pattern)`
  (пути по glob по всему дереву, `.git`-skip + кап), `list_tasks(query)` (состояние
  трекера: ready-очередь / листинг по статусу / одна задача / поиск по заголовку,
  включающий закрытые, — длинная выдача возвращается сжатой), `code_history`.
  Реализация — `SubprocessRepoIntrospector`.
- `DiagramRenderer` (Protocol) — `async render(mermaid_source)` → `bytes`
  (`DiagramRenderError` на сбое). Реализация — `SubprocessMmdcRenderer`.
- `DiagramSink` (Protocol) — `push` / `pending` / `drain`. Реализация —
  `CollectingDiagramSink` (🔴 один инстанс на процесс).
- `OutboundMessenger` (Protocol, BOB-090.B1) — `async send(*, chat_id, topic_id, markdown)`:
  отправка по ЯВНОМУ адресу. Реализация —
  `infrastructure.telegram.outbound_messenger.TelegramOutboundMessenger`.
- Value-object'ы: `ToolCall`, `ToolCallResult`, `WebSource`, `WebSearchResult`,
  `WebPage`, `DiagramResult` (все frozen); исключения `UrlReadError`,
  `SsrfBlockedError` (подтип), `DiagramRenderError`; type-алиасы `ToolDefinition`,
  `Permission` (`Literal["safe", "confirm"]`).

Фасад `src/bob/capabilities/__init__.py` re-export'ит стабильные порты + value-объекты.
Канонический импорт портов — `from bob.capabilities.ports import Capability`; транзитный
ports-шим `bob.domain.ports` удалён (BOB-062.8), все импортёры переведены на канон.

Ключевые точки входа:
- Шов: `usecases.registry` (`CapabilityRegistry`, `SafeCapabilityDispatcher`,
  `UnknownCapabilityError`, `CapabilityNotAllowedError`), `usecases.tool_loop.ToolLoop`,
  `usecases.progress_announcer` (`GatewayProgressAnnouncer`, `ProgressAnnouncer`,
  `InterimLineGenerator` — 🔴 → .6).
- Навыки-фабрики: `usecases.recall_memory.make_recall_memory_capability`,
  `search_memory.make_search_memory_capability`,
  `read_code.make_read_code_capability`,
  `list_dir.make_list_dir_capability`, `find_file.make_find_file_capability`,
  `inspect_architecture.make_inspect_architecture_capability`,
  `list_work.make_list_work_capability`,
  `code_rationale.make_code_rationale_capability`,
  `draw_architecture.make_draw_architecture_capability`,
  `architecture_impact.make_architecture_impact_capability` (BOB-091.1),
  `project_health.make_project_health_capability` (BOB-091.2) — три последних только за
  флагом `introspection.architecture_tools`,
  `web_search.make_web_search_capability`, `read_url.make_read_url_capability`,
  `render_diagram.make_render_diagram_capability` (+ `CollectingDiagramSink`),
  `diagram_attachment.DiagramAttachment` (общий шов «рендер → очередь картинок хода»:
  `render_diagram` строит его внутри, `draw_architecture` принимает готовый, BOB-091.6),
  `send_to_chat.make_send_to_chat_capability` (BOB-090.B1, регистрируется только за
  флагом `social.delivery`).
- Обстоятельства и материал хода: `usecases.delivery_scope` (`DeliveryScope`,
  `armed_delivery_scope`, `current_delivery_scope`), `usecases.turn_material`
  (`TurnMaterial`, `MaterialOrigin`, `MaterialTrailRecall`, `armed_turn_material`,
  `current_turn_material`).
- Чистый домен: `diagrams.mermaid_blocks` (`extract_mermaid_blocks`,
  `strip_mermaid_blocks`, `normalize_mermaid`), `introspection.privacy_guard`
  (`PrivacyGuard` + module-level `_allows_path` / `_sanitize` / `_resolve`,
  `ALLOWED_ROOTS`), `introspection.code_history`
  (`parse_bead_refs`, `commits_mentioning`, `feature_doc_dir`),
  `introspection.dev_query` (`clamp_commit_count`, `validate_bead_id`, `is_bead_id`,
  `normalize_status`, `sanitize_search_term`, `MAX_SEARCH_TERM_CHARS`),
  `introspection.tracker_intent` (`TrackerPlan`, `plan_tracker_query`, `find_bead_key`),
  `introspection.tracker_digest` (`digest_search_results`, `MAX_DIGEST_ITEMS`),
  `introspection.graph_form` (`GraphForm`, `plan_graph_form`, `validate_graph_ref`,
  `clamp_graph_depth`, `diagram_carries_nodes`, `MAX_GRAPH_DEPTH`),
  `introspection.impact_digest` (`digest_impact`, `MAX_IMPACT_ITEMS`, `MAX_SUBJECT_CHARS`),
  `introspection.drawing_reply` (`drawn_reply`, `not_found_reply`, `refused_reply`,
  `PictureStatus`, `NOT_FOUND`, `FALLBACK_NOTE`, `REFUSED_REF`, `PICTURE_SENT`,
  `PICTURE_UNAVAILABLE` — чистое ядро ответа про рисование: что модели сказано про
  ИСТОЧНИК, про вид схемы и про КАРТИНКУ, BOB-091.6),
  `introspection.health_form` (`HealthForm`, `plan_health_form`, `normalize_check`,
  `validate_git_ref`, `is_git_ref`, `HEALTH_CHECKS`, `DEFAULT_DIFF_REF` + типизированные
  отказы `HealthRequestError` / `UnknownCheckError` / `InvalidGitRefError` — капабилити
  выбирает подсказку модели по ТИПУ, а не по тексту сообщения, BOB-091.4),
  `introspection.health_digest` (`digest_health`, `MAX_LISTED_ITEMS`, `MAX_REPORT_LINES`,
  `MAX_DOMAIN_CHARS`).
- Адаптеры: `adapters.web` (`HttpUrlReader`, `build_url_reader`),
  `adapters.diagrams.mmdc_renderer.SubprocessMmdcRenderer`,
  `adapters.introspection.subprocess_introspector.SubprocessRepoIntrospector`,
  `adapters.web_search_qwen.QwenWebSearchProvider`.

Композиция (сборка реестра, навыков, tool-loop, анонсера + один разделяемый
`CollectingDiagramSink`) — в композиционном корне `app.py`.

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Шов: `tests/application/test_capability_registry.py`,
  `tests/application/capabilities/test_progress_announcer.py`.
- Навыки памяти: `tests/application/test_recall_memory_capability.py`,
  `test_search_memory_capability.py`.
- Самоинтроспекция и навигация: `tests/application/capabilities/`
  (`test_inspect_architecture.py`, `test_read_code.py`, `test_list_dir.py`,
  `test_find_file.py`, `test_list_work.py`, `test_code_rationale.py`,
  `test_code_rationale_acceptance.py`, `test_draw_architecture.py`,
  `test_architecture_impact.py`, `test_project_health.py`); BDD —
  `tests/acceptance/features/architecture_drawing.feature` (BOB-091.1: схема источником,
  влияние сжато, гейт флага; BOB-091.6 заменил ассерт про ОПИСАНИЕ на S1b/S1c — картинка
  реально встала в очередь отправки хода, а при сбое рендера очередь пуста и модели ушла
  честная строка «не удалось») и
  `tests/acceptance/features/project_health.feature` (BOB-091.2: 585 строк пар счётом,
  устаревшие доки и нарушение границ как ОТВЕТ, а не сбой, `--no-reindex` в argv, отказ на
  write-отчёт, гейт флага; BOB-091.4 добавил S3b — нарушения уровня УЗЛА и ЦИКЛ в счёте, ни
  одной сырой машинной строки в ответе) — второй сценарный набор идёт через НАСТОЯЩИЙ адаптер, у которого
  сценирован только подпроцесс, потому что сжимается именно сырой вывод beadloom.
- Web: `tests/application/capabilities/test_web_search.py`, `test_read_url.py`;
  `tests/test_app_web_search.py`, `test_app_read_url.py`,
  `tests/test_integration_web_search_streaming.py`, `tests/test_read_url_config.py`.
- Диаграммы: `tests/application/capabilities/test_render_diagram.py`,
  `tests/test_app_diagrams.py`; 🔴 `tests/infrastructure/diagrams/test_real_architecture_render.py`
  — сквозной прогон на НАСТОЯЩИХ инструментах (настоящий `beadloom graph` этого репозитория →
  настоящий `mmdc` → PNG в синке), в том числе через БОЕВУЮ сборку `_build_registry`; фейковый
  рендерер доказывает контракт фейка, а дефект BOB-091.6 был именно неработающей сквозной
  фичей при зелёных юнитах.
- Чистый домен: `tests/domain/diagrams/test_mermaid_blocks.py`,
  `tests/domain/introspection/test_code_history.py`, `test_privacy_guard.py`,
  `test_graph_form.py`, `test_impact_digest.py` (оба — mutation-ядра BOB-091.1),
  `test_health_form.py`, `test_health_digest.py` (оба — mutation-ядра BOB-091.2; фикстуры —
  ДОСЛОВНЫЙ вывод живого beadloom, включая ОБЕ формы машинного porcelain `lint`: с файлом и
  строкой — и с ПУСТЫМИ файлом/строкой у правил про узел и ребро, BOB-091.4). 🔴 Там же —
  юниты на ЗНАЧЕНИЯ модульных констант (закрытый перечень отчётов, кортежи форм argv, таблица
  алиасов, оба ref-регекса, границы капов): mutmut мутирует только тела функций, поэтому
  100%-ный score про эти строки не говорит ничего — а именно в такой константе и жил
  Critical-1 (ревью Major-1).
- Адаптеры: `tests/infrastructure/web/` (`test_http_url_reader.py`,
  `test_url_reader_factory.py`), `tests/infrastructure/diagrams/`
  (`test_mmdc_renderer.py`, `test_mmdc_exec_runner.py`),
  `tests/infrastructure/introspection/` (`test_subprocess_introspector.py`,
  `test_subprocess_introspector_integration.py` — в т.ч. РЕАЛЬНЫЙ `beadloom graph`/`why`
  этого репозитория и все шесть read-only отчётов на живом CLI: сжатие многокилобайтного `sync-check`,
  `diff` с НЕнулевым кодом возврата, неизменность sha256 индекса после `lint`, стабильность
  вердикта `sync-check` между прогонами; `test_git_history.py`,
  `test_architecture_reads.py` — в т.ч. невыразимость write- и вне-scope-подкоманд,
  `test_health_reads.py`),
  `tests/infrastructure/llm/` (`test_web_search_qwen.py`, `test_web_search_factory.py`).
- Отправка в другой чат и след материала (BOB-090.B): `tests/capabilities/test_send_to_chat.py`
  (последовательность гейтов: нет хода → пусто → адрес → согласие → заземление → отправка),
  `tests/capabilities/test_turn_material.py` (fail-closed на незнакомой двери и на
  неармированном ходе + архитектурный гард «порт памяти собирается в одном месте и
  обёрнут следом»); BDD — `tests/acceptance/features/chat_addressing.feature`.
- Конфиг: `tests/test_introspection_config.py`.
- Layer-guard модуля: `tests/capabilities/test_layering.py` (usecases не тянут
  adapters, домен не тянет usecases; 🔴 c/c-изоляция coding↔capabilities реально ловится).
