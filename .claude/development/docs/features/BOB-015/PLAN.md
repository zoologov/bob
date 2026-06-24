<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-015 — «Автономность: Goal Engine + Planner + самонаправленность»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-015 · родитель `bob-xnz`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (Goal Engine + persist) | `domain/goals/`: `Goal`, `Task` (+`needs_external_agency`), `GoalState`-машина (PROPOSED→APPROVED→ACTIVE→BLOCKED/DONE/CANCELLED/PAUSED; переход в APPROVED только через явный owner-апрув на уровне use-case), `GoalGraph` + чистые `ready_tasks`/`next_safe_task`/`is_goal_complete`/`blocked_reason` (топосорт по deps, только APPROVED/ACTIVE, исключая внешне-агентные). Порт `GoalStore` + `SqliteGoalStore` (таблицы goal/task/task_dep). Юнит-тесты на машину состояний + граф. | — |
| `.2` | **dev** (Planner + апрув + контроль owner) | Порт `Planner.decompose(goal)->задачи` + impl через `ToolCallingProvider` (строгий JSON, классификация `needs_external_agency`); `plan_goal` use-case (декомпозиция → показать план owner) с **двойным апрувом** (цель, затем план; конфиг `goals.require_plan_approval=true`); owner-команды через GUPPI (`/goals`, `/goal approve\|plan-approve\|pause\|resume\|cancel <id>`, **`/goals stop`** kill-switch персист-флаг + `/goals go`) — только owner (authz), естественный язык «стоп» → тот же флаг; конфиг `goals.*`. Фейк-планнер для детерминизма. | `.1` |
| `.3` | **dev** (самонаправленный тик) | `pursue_goals` use-case + `PursueGoalsTick` (супервизится agent'ом, кадэнс из конфига): governance-гейт (`Governance`/`ProactiveDecider` + kill-switch) → `next_safe_task` по APPROVED/ACTIVE → исполнение **только safe-allowlist** capability (recall/search/заметка/рефлексия/прогресс) → обновление состояния + проверка критерия + **прогресс-сообщение owner** (кратко, BOB-024). Внешне-агентная задача → НЕ авто, предложение owner. Боб может **предложить** цель (`BOB_PROPOSED`/PROPOSED). Провязка тика в `runtime`/`app.py`. | `.1,.2` |
| `.4` | **test** | ≥80% + US-1..6 + guardrails (тик трогает ТОЛЬКО APPROVED/ACTIVE; `needs_external_agency` НИКОГДА не авто; governance/rate-limit/kill-switch соблюдены; прозрачность эпизод+прогресс; гость не управляет целями; двойной апрув) + регрессии (проактив-чат/Тир 1/governance/capability/authz целы). Через `.venv/bin/pytest`. | `.1,.2,.3` |
| `.5` | **review** | Authz-before-autonomy железно (неутверждённые цели недостижимы тиком); граница стадии C непересекаема (safe-allowlist + needs_external_agency); kill-switch/governance работают; gость/authz целы; чистота DDD/детерминизм; без регрессий. Read-only. | `.4` |
| `.6` | **tech-writer** | `docs/architecture.md` (рус): Goal Engine, Planner+апрув, PursueGoalsTick+governance+safe-allowlist, контроль owner, границы стадии B/C, место в рантайме. Gate. | `.5` |

## Волны (последовательно на одной ветке)

```
.1 Goal Engine+persist → .2 Planner+апрув+контроль → .3 самонаправленный тик → .4 test → .5 review → .6 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-015`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит), один прогон за раз. Гейт каждой волны проверяет
  КООРДИНАТОР через `.venv/bin/*`.

## Критерии готовности

- [ ] Боб удерживает цели между сессиями (SQLite), декомпозирует (Planner), сам продвигает
      безопасные задачи под governance, сообщает прогресс.
- [ ] **Authz-before-autonomy:** тик никогда не действует по неутверждённой цели; `needs_external_agency`
      никогда не авто (только предложение, стадия C — гейт); двойной апрув; kill-switch мгновенен.
- [ ] Owner-контроль (list/approve/plan-approve/pause/resume/cancel/kill-switch) работает; гость не
      управляет; governance/quiet-hours/rate-limit/ceiling соблюдены (не спамит).
- [ ] Проактив-чат/Тир 1/governance/capability/authz/гость-инвариант не сломаны; cov ≥80%;
      `ruff`/`mypy --strict`/`beadloom ci` зелёные.
