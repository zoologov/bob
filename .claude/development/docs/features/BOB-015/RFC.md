<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-015 — «Автономность: Goal Engine + Planner + самонаправленность»

> **Status:** Approved
> **Created:** 2026-06-24

---

## Обзор

Боб получает **подложку целей** и умение **действовать к ним сам**, строго в рамках governance.
Три части: **Goal Engine** (чистый граф целей + персист в SQLite: состояния/приоритеты/зависимости/
критерии), **Planner** (LLM-декомпозиция цели → задачи, через capability/ToolCalling-порт, с
апрув-флоу) и **самонаправленный heartbeat-тик** (`PursueGoalsTick`), который продвигает
**утверждённые** цели через **ту же** `Governance`/`ProactiveDecider` (BOB-010), исполняя только
**безопасные** (chat/память/рефлексия/bookkeeping) шаги. Внешняя агентность (стадия C) не
исполняется автономно — только помечается «нужен гейт». Owner у руля: approve/pause/cancel/
kill-switch. Всё «как характер»: Боб преследует свои цели, оставаясь собой (Тир 1).

## Технический контекст

### Ограничения
- Python 3.12+, DDD/Clean: **граф целей и решения — чистый домен** (без I/O, детерминированно;
  стохастика — seeded); персист за портом; LLM/исполнение за портами; композиция в `app.py`;
  инъекция Clock/RNG/портов. **TDD на фейках через `.venv/bin/pytest`** (uv run висит),
  `mypy --strict`, `ruff`, cov >=80%.
- Не ломать: реактив, проактив-чат (стадия A), Тир 1 (настроение/вкус/память/отношения/адресность/
  краткость), governance, capability-шов + GUPPI, authz/гость-инвариант.

### Реюз существующей машинерии
- `domain/proactivity/`: `Governance` (quiet-hours/owner-mute/cooldown/per-window ceiling),
  `ProactiveDecider.should_speak`, `ProactivityStore`. **Самонаправленный тик идёт через них же.**
- `application/usecases/heartbeat.py` + `runtime/{heartbeat,agent}.py`: тики — one-shot корутины,
  супервизятся agent'ом; `ReflectTick` с опциональными узкими seam-Protocol'ами — **образец** для
  `PursueGoalsTick`.
- Capability-шов (`domain/ports.py:Capability`, `CapabilityRegistry`, `ToolLoop`, `ToolCallingProvider`)
  — безопасный путь исполнения и LLM-декомпозиции.
- Persistence-паттерн `XxxStore(Protocol)` (`load/save`) + Sqlite-impl (как `ProactivityStore`/
  `RelationshipStore`).

### Затрагиваемые области
`domain/goals/` (new — граф/состояния/решения), `domain/ports.py` (+`GoalStore`, +`Planner`),
`infrastructure/persistence/` (+`SqliteGoalStore`), `application/usecases/` (+`plan_goal`,
`+pursue_goals`, +owner-команды `manage_goals`), `application/runtime/` (wire `PursueGoalsTick`),
`infrastructure/telegram/guppi.py` (owner-команды целей), `app.py`, `config`.

---

## Предлагаемое решение

### (1) Goal Engine — чистый домен (`domain/goals/`)
- **`Goal`** (immutable): `id`, `title`, `description`, `priority`, `criteria` (критерий завершения,
  текст/проверяемый), `state: GoalState`, `created_at`, опц. `deadline`, `origin` (OWNER | BOB_PROPOSED).
- **`GoalState`** (Enum, машина состояний): `PROPOSED` → `APPROVED` → `ACTIVE` → (`BLOCKED` ↔) →
  `DONE` | `CANCELLED` | `PAUSED`. **Переход PROPOSED→APPROVED — ТОЛЬКО по апруву owner.**
- **`Task`** (immutable, единица работы цели): `id`, `goal_id`, `summary`, `deps: tuple[task_id]`,
  `state`, **`needs_external_agency: bool`** (требует ли стадии-C — код/внешние инструменты/ФС/API).
- **`GoalGraph`** + чистые функции: `ready_tasks(graph)` (топосорт по deps, только APPROVED/ACTIVE
  цели, исключая `needs_external_agency`), `next_safe_task(graph, *, priority)` (что продвинуть
  следующим), `is_goal_complete(goal, tasks, criteria)` (проверка критерия), `blocked_reason`.
  Детерминированно, без I/O.

### (2) Planner — декомпозиция цели → задачи (порт + LLM)
- **`Planner(Protocol)`** (`domain/ports.py`): `async decompose(goal: Goal) -> Sequence[Task]` —
  разбивает цель на исполнимые задачи с зависимостями и **классифицирует `needs_external_agency`**.
- **Impl** (`infrastructure` или `application`): через `ToolCallingProvider`/LLM (tier-1), строгий
  JSON-выход (как memory-extraction). Промпт просит: атомарные задачи, зависимости, и пометить
  внешне-агентные. Тестируется фейк-планнером (детерминизм).
- **`plan_goal` use-case** (`application/usecases/plan_goal.py`): берёт APPROVED-цель без плана →
  `Planner.decompose` → сохраняет задачи (state NEW) → **показывает план owner** (одно сообщение)
  → цель ACTIVE по апруву плана. (Двойной апрув: цель, затем план — консервативно для стадии B.)

### (3) Самонаправленный тик (`PursueGoalsTick` + `pursue_goals` use-case)
- Новый heartbeat-тик (супервизится agent'ом, кадэнс из конфига), идёт через **те же ворота**:
  - **Governance-гейт:** `Governance.permits(...)` (quiet-hours / owner-mute / cooldown / per-window
    ceiling) + **kill-switch** (см. (4)). Не прошёл → тик ничего не делает.
  - **Выбор задачи:** `next_safe_task` по утверждённым целям (приоритет + готовность по deps),
    исключая `needs_external_agency`.
  - **Исполнение безопасного шага:** через **capability-шов** — только из **safe-allowlist**
    capability (recall/search памяти, заметка, рефлексия, подготовка, отправка прогресс-сообщения).
    Внешне-агентные capability в автономном пути **недоступны**.
  - **Обновление состояния + прозрачность:** задача → DONE/BLOCKED; проверка критерия цели → DONE;
    эпизод в память; **прогресс-сообщение owner** («занялся X, сделал Y» — кратко, по BOB-024).
- Внешне-агентная задача (`needs_external_agency`) → НЕ исполняется; **выносится как предложение**
  owner («для этого нужен код/инструмент — запустить? (стадия C, отдельный гейт)»).

### (4) Контроль owner + предложение целей
- **Owner-команды** (через GUPPI, как `/quiet`/`/wake`): `/goals` (список+состояния), `/goal approve
  <id>`, `/goal plan-approve <id>`, `/goal pause|resume|cancel <id>`, **`/goals stop`** (kill-switch
  — персист-флаг, мгновенно глушит `PursueGoalsTick`), `/goals go` (снять). Плюс естественный язык
  («стоп, не занимайся этим») → та же остановка. Только **owner** (authz), не гость.
- **Предложение целей Бобом:** из паттернов диалога/памяти Боб может создать цель `origin=BOB_PROPOSED,
  state=PROPOSED` и предложить её — но `PursueGoalsTick` **никогда** не трогает PROPOSED.

### (5) Persistence + конфиг
- **`SqliteGoalStore`** (порт `GoalStore`): таблицы `goal` / `task` / `task_dep` (+ kill-switch флаг
  в proactivity/owner-state). `load(persona_id)->GoalGraph`, `save(...)`, атомарные апдейты состояний.
- **Конфиг `goals.*`:** кадэнс тика, max задач/окно (rate-limit поверх governance), tier планнера,
  **safe-capability allowlist**, kill-switch default (выкл = Боб может преследовать; но цели всё
  равно нужны APPROVED).

### Композиция / безопасность (инварианты)
```
owner: цель → APPROVED → Planner.decompose → план → APPROVED →
  PursueGoalsTick (governance + kill-switch + safe-allowlist) → безопасный шаг → прогресс owner
внешне-агентная задача → НЕ авто; предложение owner (стадия-C гейт)
```
Гость-инвариант (BOB-019) цел; authz: команды целей только owner. Стадия C не пересекается.

## Guardrails (под тестами)
- **Authz-before-autonomy:** `PursueGoalsTick` трогает ТОЛЬКО APPROVED/ACTIVE цели; PROPOSED и
  BOB_PROPOSED-неутверждённые — никогда. Переход в APPROVED — только owner-апрув.
- **Граница стадии C:** задача `needs_external_agency` НИКОГДА не исполняется автономно (только
  предложение). Автономный путь видит только safe-allowlist capability.
- **Governance:** quiet-hours / rate-limit / cooldown соблюдены; **kill-switch** мгновенно
  останавливает; не спамит (per-window ceiling).
- **Прозрачность:** каждое автономное действие → эпизод + прогресс-сообщение owner.
- **Owner-контроль:** pause/cancel/resume/list/kill-switch работают; гость не может управлять целями.
- Домен (граф/состояния/готовность) чист и детерминирован; тик seeded.

## Рассмотренные альтернативы
- **Сразу полная агентность (стадия C в этом эпике)** — отвергнуто: нарушает authz-before-autonomy;
  внешнее исполнение — отдельный гейт (Тир 3).
- **Без апрува плана (только апрув цели)** — отвергнуто для стадии B: двойной гейт (цель+план)
  консервативен на старте автономии; ослабить можно позже конфигом.
- **Свой scheduler вместо heartbeat/governance** — отвергнуто: реюз proactivity-governance (единые
  quiet-hours/rate-limit/kill-switch), без дублирования машинерии.
- **Goal-граф через Beads** — отвергнуто: Beads — это dev-трекинг репозитория; цели Боба — его
  рантайм-состояние (SQLite, как память/проактивность), отдельный слой.

## Риски
| Риск | Вер. | Влияние | Митигация |
|---|---|---|---|
| Боб действует по неутверждённой цели | Low | **High** | Машина состояний: тик трогает только APPROVED/ACTIVE; тест-инвариант |
| Автономный выход во внешнюю агентность | Low | **High** | `needs_external_agency`→только предложение; safe-allowlist в авто-пути; тесты |
| Спам самонаправленными сообщениями | Med | Med | Governance (quiet-hours/ceiling/cooldown) + max задач/окно; kill-switch |
| Боб «застревает»/зацикливается на задаче | Med | Med | BLOCKED-состояние + blocked_reason + cap попыток; видно owner |
| Планнер плодит мусорные задачи | Med | Low | Апрув плана owner перед ACTIVE; правка/отмена |

## Открытые вопросы
| # | Вопрос | Предложение |
|---|--------|-------------|
| Q1 | Что считается «безопасным» capability в авто-пути | Явный allowlist в конфиге (recall/search/заметка/рефлексия/прогресс-сообщение); всё остальное — нет |
| Q2 | Критерий завершения цели | Текстовый + при возможности проверяемый предикат; иначе owner закрывает вручную |
| Q3 | Двойной апрув (цель + план) | Да на стадии B; конфиг `goals.require_plan_approval` (default true) |
| Q4 | Kill-switch хранение | Персист-флаг рядом с owner-mute (proactivity/owner-state); естественный язык → тот же флаг |
| Q5 | Кадэнс PursueGoalsTick | Из конфига, редкий (порядок проактивного heartbeat), под governance-ceiling |
