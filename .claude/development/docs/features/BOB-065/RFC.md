<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-065 — «Фундамент: split `ports.py` + детальный граф + AaC-правила»

> **Status:** Approved
> **Created:** 2026-07-02
> **Type:** feature · Фаза 2 аудита · BOB-Issues #7 + #8 (+ подтягивает #1/#2)
> **PRD:** `./PRD.md` (Approved)

---

## Обзор

Три связанные части, одна цель — поставить **архитектурный каркас с зубами** до того, как
Фаза 3 начнёт физически двигать код:

- **A. Split `ports.py`** — 51 контракт из God-файла → per-module + shared kernel; ~140
  импортёров не трогаем (re-export-шим).
- **B. Детальный граф beadloom** — узлы по слоям + подмодулям с точными `source`-аннотациями
  и `tags`. Это энейблер: без узлов правилам нечего проверять, а `docs generate` нечего
  генерировать (корень монолита доков).
- **C. Максимальный AaC-ruleset** — на реальных примитивах rule-движка (проверено по коду
  beadloom): направление слоёв, границы импортов, циклы, покрытие, размерные лимиты.

**Ключевой факт (проверен):** beadloom строит рёбра `depends_on` из **реальных импортов**
(tree-sitter), поэтому `forbid_import`/`deny`/`layers` ловят фактические нарушения кода, а не
только рассинхрон декларации. Каркас будет живой.

---

## Часть A — Split `domain/ports.py`

### Приём: файл → пакет (шим бесплатно)

`domain/ports.py` (файл) → `domain/ports/` (пакет). `domain/ports/__init__.py` реэкспортирует
все 51 символ (сохраняя `__all__`) — поэтому `from bob.domain.ports import X` работает для всех
~140 импортёров **без единого изменения**. Реальные определения переезжают в подмодули:

| Подмодуль `domain/ports/` | Контракты (кол-во) |
|---|---|
| `kernel.py` | `Clock`, `EventBus`, `DomainEvent`, `EventHandler`, `LLMProvider`, `LLMMessage`, `JsonValue` (7) |
| `capabilities.py` | `Capability`, `Permission`, `ToolCall`, `ToolCallResult`, `ToolDefinition`, `ToolCallingProvider`, `WebSearchProvider`, `WebSearchResult`, `WebSource`, `UrlReader`, `UrlReadError`, `SsrfBlockedError`, `WebPage`, `DiagramRenderer`, `DiagramRenderError`, `DiagramResult`, `DiagramSink`, `RepoIntrospector` (18) |
| `memory.py` | `MemoryRepo`, `MemoryRecall`, `Recalled`, `Embedder`, `Reranker` (5) |
| `personality.py` | `FascinationStore`, `FirstImpressionStore`, `RelationshipStore`, `NotableReactionStore`, `SulkStore`, `MessageReactor`, `ReflectionReader`, `ZoneClassifier` (8) |
| `conversation.py` | `ConversationFloorStore`, `CloserLog` (2) |
| `social.py` | `AllowlistStore`, `SoulStore` (2) |
| `proactivity.py` | `ProactivityStore`, `GoalStore`, `Planner`, `SelfImprovementStore`, `PatternDetector` (5) |
| `coding.py` | `ClaudeCodeRunner`, `Worktree`, `CodingSessionStore`, `PullRequestOpener` (4) |

**Спорные размещения (решено):** `ToolCallingProvider` → capabilities (единственный потребитель —
tool-loop; тянет `LLMMessage` из kernel — межмодульное ребро допустимо). `MessageReactor`,
`ReflectionReader` → personality (выражение/внутренняя жизнь). `CloserLog` → conversation
(анти-тик). Straddler self-improvement (`SelfImprovementStore`/`PatternDetector`) → proactivity,
хотя типы берёт из `personality.self_improvement` (TYPE_CHECKING — ок).

**Внутренние связки** (переезжают вместе, все within-bucket): `EventBus`→`DomainEvent`/`EventHandler`;
`ToolCallResult`→`ToolCall`; `WebSearchProvider`→`WebSearchResult`→`WebSource`; `UrlReader`→`WebPage`;
`SsrfBlockedError`⊂`UrlReadError`; `Diagram*`; `MemoryRecall`/`Reranker`→`Recalled`. Межмодульные
только два, оба в kernel: `ToolCallingProvider`→`LLMMessage`, `SoulStore`→`JsonValue`.

### Kernel: где живёт

Целевое место общего ядра — `runtime/` (Фаза 3, когда `app.py`→runtime). Сейчас `runtime/` нет,
поэтому промежуточно kernel-контракты живут в `domain/ports/kernel.py` (не тянут ничего наружу,
инфраструктурно-нейтральны — легально в domain). В Фазе 3 `domain/ports/kernel.py` → `runtime/ports.py`
одним ходом; шим страхует.

### Порядок и безопасность

Split — **поведение-сохраняющий** (чистый move + реэкспорт, рантайм-логику не трогаем). Так как шим
держит импорты, split можно делать одним dev-беадом; проверка — `pytest`+`mypy --strict` зелёные
(mypy ловит любую промашку в реэкспорте). Тесты, использующие `bob.domain.ports`, не меняются.

> 🔴 Инвариант: `__all__` в `__init__.py` = точное объединение прежнего `__all__` (51 символ). Ни
> одного «тихо пропавшего» имени — иначе импортёр упадёт в рантайме. mypy + тест-импорт всех символов.

---

## Часть B — Детальный граф beadloom

### Проблема сейчас

Граф = сервис `bob` + узлы-слои `bob-domain/application/infrastructure` с `depends_on`-рёбрами, НО
**все 186 файлов мапятся на узел `bob`** (blanket `# beadloom:domain=bob`). Значит: (1) правилам не
за что зацепиться на уровне файлов, (2) `docs generate` (node-driven) эмитить нечего → монолит доков.

### Целевой граф Фазы 2 (текущая слоистая структура, честно и детально)

Иерархия `service → layer → submodule`. Слой задаётся **тегом на узле** (не маркером в коде — так
устроен движок). Узлы указывают `source:` на реальные каталоги:

**Слои (kind: domain-узлы beadloom, тег слоя):**
- `bob` (kind: service, root)
- `layer-domain` node group → `src/bob/domain/`, tag `[layer-domain]`
- `layer-application` → `src/bob/application/`, tag `[layer-application]`
- `layer-infrastructure` → `src/bob/infrastructure/`, tag `[layer-infra]`
- `runtime` (kind: service) → `src/bob/app.py`, tag `[layer-runtime]` (composition root)

**Подмодули (kind: feature под слоем, `part_of` слой):**
- под domain: `personality`, `memory`, `goals`, `coding-domain`, `diagrams-domain`,
  `introspection-domain`, `permission`, `proactivity-domain` (`src/bob/domain/<X>/`)
- под application: `usecases`, `authz`, `capabilities-app`, `router`, `runtime-app`,
  `proactivity-app` (`src/bob/application/<X>/`)
- под infrastructure (kind: component): `llm`, `web`, `telegram`, `persistence`, `config`,
  `coding-infra`, `diagrams-infra`, `introspection-infra` (`src/bob/infrastructure/<X>/`)

**Аннотации:** большинство файлов привязываются автоматически по `source`-префиксу узла — массово
переаннотировать 186 файлов НЕ нужно. Точечные `# beadloom:feature=`/`component=` ставим лишь там,
где файл логически принадлежит иному модулю, чем его каталог (редкие случаи). Blanket
`# beadloom:domain=bob` в шапках заменяется/снимается там, где мешает.

> **Граница с Фазой 3.** Этот граф честно описывает *текущую* слоистую структуру. Фаза 3 (BOB-062)
> физически двигает код в domain-first вертикали и **перецеливает `source:` узлов** на новые пути
> (напр. `personality` → `src/bob/personality/`). Узлы-слои и все правила (Часть C) — структурно-
> инвариантны и переживают реорг. Тем самым #1/#2 частично выполняются здесь (граф-каркас), а Фаза 3
> занимается переездом кода + наполнением доков.

### Побочная победа

Как только узлы появились, `beadloom docs generate` начинает эмитить per-node скелеты (SPEC/DOC) —
это снимает корень монолита доков. Наполнение содержимым доков оставляем Фазе 3; здесь достаточно
скелетов, чтобы `module_coverage` был зелёным.

---

## Часть C — Максимальный AaC-ruleset

Пишем `.beadloom/_graph/rules.yml` (version 3) по образцу самого beadloom, адаптированный под
Clean Architecture Боба. Все примитивы — реально существующие (проверено по `graph/rules/`).

### Направление зависимостей (Clean Architecture)

Импорты указывают **внутрь**: `runtime → infrastructure → application → domain`. `domain` чист
(ни на кого не смотрит). Порядок в `layers` top→bottom = «самый зависимый … самый независимый»:

```yaml
version: 3

tags:                       # справочно; теги реально живут на узлах графового YAML
  layer-runtime:        [runtime]
  layer-infra:          [layer-infrastructure]
  layer-application:    [layer-application]
  layer-domain:         [layer-domain]

rules:
  # --- структурная целостность ---
  - name: domain-needs-parent
    description: "Каждый domain-узел — part_of сервиса bob"
    require: { for: {kind: domain}, has_edge_to: {ref_id: bob}, edge_kind: part_of }

  - name: feature-needs-parent
    description: "Каждая feature — part_of своего слоя/домена"
    require: { for: {kind: feature}, has_edge_to: {kind: domain}, edge_kind: part_of }

  - name: no-dependency-cycles
    description: "Никаких циклов depends_on"
    severity: error
    forbid_cycles: { edge_kind: depends_on }

  # --- НАПРАВЛЕНИЕ СЛОЁВ (главные зубы) ---
  - name: architecture-layers
    description: "runtime → infrastructure → application → domain; не обратно"
    severity: error
    layers:
      - {name: runtime,        tag: layer-runtime}
      - {name: infrastructure, tag: layer-infra}
      - {name: application,    tag: layer-application}
      - {name: domain,         tag: layer-domain}
    enforce: top-down
    allow_skip: true            # infra→domain (реализация портов) и runtime→domain легальны
    edge_kind: depends_on

  # --- ЖЁСТКИЕ ГРАНИЦЫ ИМПОРТОВ (сканируют реальные import'ы) ---
  - name: domain-imports-nothing-outward
    description: "Домен не импортит application"
    severity: error
    forbid_import: { from: "src/bob/domain/**", to: "src/bob/application/**" }

  - name: domain-no-infra
    description: "Домен не импортит infrastructure"
    severity: error
    forbid_import: { from: "src/bob/domain/**", to: "src/bob/infrastructure/**" }

  - name: application-no-infra
    description: "Application не импортит infrastructure (только через порты домена)"
    severity: error
    forbid_import: { from: "src/bob/application/**", to: "src/bob/infrastructure/**" }

  # --- страховка на уровне рёбер графа ---
  - name: no-domain-depends-on-outer
    description: "Домен не зависит от app/infra/runtime (кроме part_of)"
    deny:
      from: {kind: domain}
      to:   {kind: service}
      unless_edge: [part_of]

  # --- покрытие: новые файлы обязаны иметь узел ---
  - name: module-coverage
    description: "Каждый src-модуль — трекнутый узел или явный exempt"
    severity: error
    module_coverage:
      source_root: src/bob/
      min_symbols: 1
      exempt: ["**/__init__.py", "**/__main__.py", "**/py.typed"]

  # --- анти-монстры (ratchet: warn сейчас, error после декомпозиции) ---
  - name: no-monster-modules
    description: "Модуль не должен пухнуть (handle_message/app.py/gateway — известные, #9/#10/#25)"
    severity: warn
    check: { for: {kind: feature}, max_symbols: 200 }
```

### Стратегия строгости (severity ratchet)

- **error сразу** — там, где код уже чист: направление слоёв, `domain-no-*`, `application-no-infra`,
  циклы, coverage. Ожидаем зелёный (Clean Arch в Бобе соблюдается — аудит подтвердил: домен реально
  импортит порты лишь в 2 местах, оба TYPE_CHECKING).
- **warn сначала** — `no-monster-modules` (сразу загорится на `handle_message.py`/`app.py`/`gateway.py` —
  это ожидаемо, они уже трекаются #9/#10/#25). Флип в error — по мере декомпозиции в Фазе 3.
- Если какая-то error-проверка неожиданно краснеет на текущем коде — RFC-инвариант: либо это
  настоящее нарушение (чиним в рамках беада), либо ложное (документируем и понижаем до warn с TODO).

### Верификация правил

`beadloom lint --strict` (exit 1 при error-нарушениях) в pre-push + `beadloom ci`. Добавляем прогон в
DoD беадов. Формат `github`/`porcelain` — для CI-аннотаций.

---

## Scope: что в Фазе 2, что в Фазе 3

**В BOB-065 (Фаза 2):**
- Split `ports.py` → пакет + kernel + шим (#7).
- Граф: слои + подмодульные узлы текущей структуры + точечные аннотации (энейблер; часть #1/#2).
- Полный AaC-ruleset + severity-ratchet (#8).
- `docs generate` скелеты (чтобы coverage зелёный) — без наполнения содержимым.

**НЕ здесь (остаётся Фазе 3 / BOB-062):**
- Физический переезд кода в domain-first вертикали + перецеливание `source:` узлов.
- Наполнение SPEC/DOC содержимым, ужатие `architecture.md` (#3–#5).
- Декомпозиция `handle_message.py`/`app.py` (#9/#10) — тогда же флип `no-monster-modules` в error.
- Удаление ports-шима (#18).

> **Почему так (рекомендация):** сначала ставим каркас (граф+правила) как **guard-rails**, потом
> Фаза 3 двигает код *внутри* этих рельс — правила ловят ошибки переезда в реальном времени. Обратный
> порядок (двигать код без правил) — это резать вслепую.

---

## Риски и инварианты

- 🔴 **Полнота `__all__`** после split (тест-импорт всех 51 символа + mypy).
- 🔴 **Ложные срабатывания** новых error-правил на текущем коде → триаж в рамках беада (чинить/понижать
  с TODO), не «замазывать».
- **Аннотации:** не переаннотировать 186 файлов вручную; опираться на `source`-префикс узла, точечно
  переопределять. `beadloom reindex` после каждого изменения графа/аннотаций.
- **Поведение рантайма не меняется** нигде (Часть A — чистый move; B/C — только метаданные/конфиг).
  DoD: `pytest`, `ruff`, `mypy --strict`, `beadloom lint --strict`, `beadloom sync-check` — зелёные.
- **Совместимость с Фазой 3:** узлы-слои и правила структурно-инвариантны; подмодульные узлы
  перецеливаются (дёшево). Шим удаляется только в #18.

## Открытые вопросы (к CONTEXT/PLAN)

- Дробить ли `capabilities.py` портов сразу на web/diagrams/introspection/tool-core, или монолитным
  подмодулем до Фазы 3? (Рекомендация: один `capabilities.py` сейчас, дробление — с вертикалью #16.)
- `docs generate` скелеты — в этом же feature или отдельным беадом внутри него? (Рекомендация: беад
  внутри, после графа.)
- Порог `max_symbols` для `no-monster-modules` (200 — как beadloom-ish? калибруем по реальным цифрам).
