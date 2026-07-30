<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль capabilities — «инструменты Боба»

Способность «инструменты Боба» как единая вертикаль: стабильный контракт
`Capability` и его порты (tool-calling-провайдер + web / diagram / introspection
сеймы) в `ports.py`, чистые value-object'ы `diagrams` / `introspection`, половина
`usecases/` (шов `CapabilityRegistry` + `ToolLoop` и сами навыки — recall/search
памяти, read code/url, навигация по репозиторию (list_dir / find_file), web-поиск,
render diagram, inspect architecture, list work, code rationale, progress announcer) и половина `adapters/` (aiohttp url-reader за
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
  ports.py            # layer=domain          — 18 портов-протоколов + value-object'ы шва
  __init__.py         # layer=domain          — фасад (re-export стабильных портов)
  diagrams/           # layer=domain            (чистый разбор inline-mermaid, BOB-037)
    mermaid_blocks.py #                        — extract / strip / normalize fenced ```mermaid
  introspection/      # layer=domain            (чистые инварианты самоинтроспекции)
    privacy_guard.py  #                        — PrivacyGuard: приват-инвариант полного-репо доступа (BOB-017→BOB-067); чистое ядро _allows_path/_sanitize/_resolve вынесено на уровень модуля (mutation-testable)
    code_history.py   #                        — чистые парсеры git↔беады↔фича-доки (BOB-038)
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
    list_work.py      #                        — свой трекер через RepoIntrospector (bd ready/show)
    code_rationale.py #                        — код↔«почему»: git↔беады↔фича-доки↔граф (BOB-038)
    web_search.py     #                        — заземлённый веб-поиск (BOB-053)
    read_url.py       #                        — чтение одной ссылки за SSRF-щитом (BOB-054)
    render_diagram.py #                        — mermaid→PNG в чат + CollectingDiagramSink (BOB-035)
    diagram_sender.py #                        — DiagramSender: авто-рендер inline-mermaid + drain sink → отправка (коллаборатор handle_message, BOB-062.6b)
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
аргументов (`input_schema`), декларирует `permission` (`"safe"` идёт насквозь;
`"confirm"` — сейм под будущий approval-гейт) и `execute`'ится над декодированными
аргументами. Новые навыки регистрируются под этим контрактом; потребители не меняются.
Это именно **шов**, не плагин-машинерия (sandboxing / discovery / self-creation —
позже за тем же контрактом).

`CapabilityRegistry` (`usecases/registry.py`) — упорядоченный, name-unique индекс
того, что GUPPI может рекламировать и запускать: `register` (уникальное имя),
`manifest` (рендер зарегистрированных навыков как OpenAI `tools`-определений для
модели), `dispatch` (запуск навыка по имени — **исполняет GUPPI**), `describe`
(короткий prose-манифест для системного промпта Боба). Чистая application-политика:
держит capability-объекты, транспорта не касается. `SafeCapabilityDispatcher` —
allowlist-ограниченный вид над реестром: жёсткая граница автономного тика
(BOB-015), пропускает ТОЛЬКО пересечение реестра и явного safe-allowlist
(`goals.safe_capabilities`); навык вне allowlist недостижим по конструкции. Пустой
allowlist = автономно ничего не запускается (консервативный дефолт).

`ToolLoop` (`usecases/tool_loop.py`) — акт-сторона шва: гонит раунд-трип
`модель ↔ инструменты` до финального текста. Просит `ToolCallingProvider` завершить
ход, предлагая манифест как `tools`; если модель запросила tool_calls —
**диспетчеризует** каждый через реестр (исполняет GUPPI), дописывает ассистент-ход
и `tool`-результаты, переспрашивает; capает число ходов (`_DEFAULT_MAX_TURNS = 6`),
чтобы зациклившаяся модель не убежала. Неизвестный tool не фатален — ошибка
скармливается обратно как tool-результат, чтобы модель восстановилась. Перед
**медленным** навыком опционально зовёт `ProgressAnnouncer` (interim-строка); любая
ошибка анонсера глотается — декоративная строка не может задержать/сломать dispatch.

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
  из `goals.safe_capabilities`; introspection/web-навыки туда НЕ добавлены — только
  разговор, автономный тик их не запустит. Пустой allowlist = автономно ничего.

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

Модуль `src/bob/capabilities/ports.py` (порты-протоколы + value-object'ы шва, 18
публичных символов):
- `Capability` (Protocol) — стабильный контракт навыка: `name`, `description`,
  `input_schema`, `permission`, `async execute(args)`.
- `ToolCallingProvider` (Protocol) — `async complete_with_tools(messages, *, tools)`
  → `ToolCallResult`. Реализация — инфра OpenAI-совместимый провайдер.
- `WebSearchProvider` (Protocol) — `async search(query)` → `WebSearchResult` (raise
  на сбое). Реализация — `QwenWebSearchProvider`.
- `UrlReader` (Protocol) — `async read(url)` → `WebPage` (raise/`SsrfBlockedError` на
  блоке). Реализация — `HttpUrlReader`.
- `RepoIntrospector` (Protocol) — read-only самоинтроспекция и навигация:
  `architecture_context`, `search_code`, `read_file(path, *, max_lines)`,
  `list_dir(path)` (записи одной директории, не рекурсивно), `find_file(pattern)`
  (пути по glob по всему дереву, `.git`-skip + кап), `list_tasks`, `code_history`.
  Реализация — `SubprocessRepoIntrospector`.
- `DiagramRenderer` (Protocol) — `async render(mermaid_source)` → `bytes`
  (`DiagramRenderError` на сбое). Реализация — `SubprocessMmdcRenderer`.
- `DiagramSink` (Protocol) — `push` / `pending` / `drain`. Реализация —
  `CollectingDiagramSink` (🔴 один инстанс на процесс).
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
  `web_search.make_web_search_capability`, `read_url.make_read_url_capability`,
  `render_diagram.make_render_diagram_capability` (+ `CollectingDiagramSink`).
- Чистый домен: `diagrams.mermaid_blocks` (`extract_mermaid_blocks`,
  `strip_mermaid_blocks`, `normalize_mermaid`), `introspection.privacy_guard`
  (`PrivacyGuard` + module-level `_allows_path` / `_sanitize` / `_resolve`,
  `ALLOWED_ROOTS`), `introspection.code_history`
  (`parse_bead_refs`, `commits_mentioning`, `feature_doc_dir`).
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
  `test_code_rationale_acceptance.py`).
- Web: `tests/application/capabilities/test_web_search.py`, `test_read_url.py`;
  `tests/test_app_web_search.py`, `test_app_read_url.py`,
  `tests/test_integration_web_search_streaming.py`, `tests/test_read_url_config.py`.
- Диаграммы: `tests/application/capabilities/test_render_diagram.py`,
  `tests/test_app_diagrams.py`.
- Чистый домен: `tests/domain/diagrams/test_mermaid_blocks.py`,
  `tests/domain/introspection/test_code_history.py`, `test_privacy_guard.py`.
- Адаптеры: `tests/infrastructure/web/` (`test_http_url_reader.py`,
  `test_url_reader_factory.py`), `tests/infrastructure/diagrams/`
  (`test_mmdc_renderer.py`, `test_mmdc_exec_runner.py`),
  `tests/infrastructure/introspection/` (`test_subprocess_introspector.py`,
  `test_subprocess_introspector_integration.py`, `test_git_history.py`),
  `tests/infrastructure/llm/` (`test_web_search_qwen.py`, `test_web_search_factory.py`).
- Конфиг: `tests/test_introspection_config.py`.
- Layer-guard модуля: `tests/capabilities/test_layering.py` (usecases не тянут
  adapters, домен не тянет usecases; 🔴 c/c-изоляция coding↔capabilities реально ловится).
