<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.3 — «Срез proactivity → src/bob/proactivity/» (Фаза 3, срез 3/8)

> **Status:** Approved
> **Created:** 2026-07-23
> **Type:** feature · срез эпика BOB-062 · BOB-Issues #13
> **Родитель:** `bob-8r4.3` (эпик `bob-8r4`) · Контекст: эпик `RFC/CONTEXT` + прецеденты .1 coding / .2 memory

---

## Проблема

Способность «фоновая жизнь Боба» (drive/проактивность + свои цели + самоулучшение) размазана:
`domain/proactivity/` + `domain/goals/` + `domain/personality/self_improvement.py` +
`application/proactivity/` + `usecases/{plan_goal,pursue_goals,detect_patterns,announce_rules,
self_improvement_sources}` + 4 стора в `persistence/` + `ports/proactivity`. Собираем в
`src/bob/proactivity/` по валидированной схеме (module-vertical).

## Решение (атомарный переезд, behavior-preserving) — самый крупный срез (~25 файлов)

Целевая структура (схема CONTEXT + подпапка `goals/` для когезивной подобласти):
```
src/bob/proactivity/
  ports.py            # layer=domain  ← domain/ports/proactivity.py (5 Protocol)
  __init__.py         # layer=domain  (фасад)
  decision.py · governance.py · social_energy.py · state.py · urge.py     # layer=domain (drive-core)
  self_improvement.py # layer=domain  ← 🔴 из domain/personality/self_improvement.py
  goals/              # layer=domain  ← domain/goals/{entities,graph,state}.py (когезивная подобласть)
  usecases/           # layer=application ← application/proactivity/{engine,tick,record_owner_activity}
                      #   + usecases/{plan_goal,pursue_goals,detect_patterns,announce_rules,self_improvement_sources}
  adapters/           # layer=infrastructure ← persistence/{proactivity_store,proactivity_sources,goal_store,self_improvement_store}
```

### 🔴 Три решения по принадлежности (по данным разведки — отмечены для видимости owner)
1. **`self_improvement.py` → забираем в proactivity** (из `domain/personality/`). Это метакогниция над
   поведением (BOB-028), не черта личности; **чистый лист** (0 импортов из `bob.*`) → цикла нет. Тянет
   2 теста (`tests/domain/personality/test_self_improvement*.py`) + смену тега `feature=personality→proactivity`.
2. **`run_genesis.py` → ОСТАЁТСЯ вне proactivity** (не переносим). По зависимостям это first-boot генезис
   SOUL (тянет `SoulStore`/social + router), не drive/goals. Уедет в срез social(.5) или personality(.6).
3. **goals → единый `feature=proactivity`** (подпапка `goals/` структурно), как один feature на модуль в
   эталоне coding/memory.

### 🔴 Kernel (вариант C — подтверждён разведкой)
4 стора (`proactivity_store/goal_store/self_improvement_store/proactivity_sources`) получают connection
через `SqliteMemoryRepo.connection()` seam (как 13 других). После переезда в `adapters/` — зависят от
kernel наружу (proactivity→infra kernel, норм). Обратной kernel→proactivity зависимости НЕТ (sqlite_repo
не импортит сторы). `schema.sql` (таблицы proactivity_state/goal/task/improvement_rule) ОСТАЁТСЯ в kernel.

### Внешние прод-правки (шире среднего — proactivity пронизывает фоновую жизнь)
- `app.py` — ~14 import-строк + wiring (конструкторы Sqlite*-сторов, engine/tick/genesis).
- `domain/ports/__init__.py` — re-export 5 портов из `proactivity.ports` (шим).
- `application/usecases/__init__.py` — реэкспорт (GenesisResult/RunGenesis остаются; убрать proactivity-usecases).
- `infrastructure/persistence/__init__.py` — убрать 4 стора.
- **`handle_message.py`** (:124,:165) — `self_improvement` (RuleModulators/build_modulators) на новый путь; 🔴 стык personality-flow→proactivity.self_improvement (read-модуляторы) — пометить allow.
- **`guppi.py`** (:38-51) — тянет `goals.state/graph`, `self_improvement`, `plan_goal`, `proactivity.state` (UI-рендер прямо в домен) → переписать пути + пометить (adapter читает proactivity-домен).
- **`multibot.py`** (:80) — `plan_goal.PlanGoal` (TYPE).
- Тесты (~24) — импорты; строковых литералов путей НЕ найдено (плюс). `heartbeat.py` — правок не требует (Protocol-seam'ы, только docstring).

## Беады (роль-суб-беады под `bob-8r4.3`)

- **`.1` dev** — переезд proactivity (структура + `git mv` ~25 файлов вкл. self_improvement из personality; kernel/sqlite_repo/schema НЕ трогать; run_genesis НЕ трогать; переписать импорты app.py/ports/__init__/handle_message/guppi/multibot/re-export пакеты + ~24 теста; `# beadloom:feature=proactivity`+`layer=`; узел module-vertical + reindex). pytest/ruff/mypy зелёные.
- **`.2` dev** — AaC правила границ proactivity (как memory/coding; расширить char-class globs `[adim]*→[adimp]*`); пометить allow: personality→proactivity.self_improvement, guppi→proactivity-домен, proactivity→memory.entities; kernel→proactivity нет (проверить). 🔴 **Оценить: не пора ли генератор правил границ** (сигнал review .1/.2) — если ручное расширение globs становится громоздким, предложить/сделать. `beadloom lint --strict` зелёный.
- **`.3` test** — полный `pytest` (поведение идентично) + proactivity-инварианты (drive urge-монотонность, 6 governance-вето, seeded-RNG детерминизм, goal-state-переходы, self-improvement gate двойной-апрув, quiet-hours/kill-switch) + механика правил + `beadloom ci`.
- **`.4` review** — корректность переезда, границы (self_improvement-перенос чист, kernel-отсрочка, guppi-стык), поведение неизменно; вердикт по генератору правил.
- **`.5` tech-writer** — SPEC/DOC модуля proactivity; закрыть #13; Gate (`sync-update bob` + `setup-rules --refresh`).

## Критерии приёмки

- `src/bob/proactivity/` собран (вкл. self_improvement + goals/); run_genesis и kernel не тронуты.
- `pytest` зелёный (поведение идентично); proactivity-инварианты целы; `ruff`/`mypy --strict` зелёные.
- `beadloom ci` зелёный; стыки (personality→self_improvement, guppi→домен, proactivity→memory) помечены.
- BOB-Issues #13 закрыт.

## Связи

Эпик BOB-062, срез 3/8 (крупнейший). Прецеденты .1 coding / .2 memory. 🔴 kernel-split → .7; genesis → .5/.6.
Следующий: `.4 capabilities` (`bob-8r4.4`, blocked до мержа).
