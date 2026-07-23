<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062 — «Domain-first реорганизация + доки» (эпик)

> **Status:** Scaffolded — на паузе перед стартом среза .1
> **Updated:** 2026-07-02
> **Epic bead:** `bob-8r4` · **Docs:** PRD/RFC/CONTEXT/PLAN — все Approved

---

## Срезы (последовательно, PR за PR)

| Срез | Bead | Модуль | риск | Статус |
|------|------|--------|------|--------|
| .1 | `bob-8r4.1` | coding | 🟢 | ○ **ready — СЛЕДУЮЩИЙ** (контрольный) |
| .2 | `bob-8r4.2` | memory | 🟢 | ● blocked (.1) |
| .3 | `bob-8r4.3` | proactivity | 🟡 | ● blocked (.2) |
| .4 | `bob-8r4.4` | capabilities | 🟡 | ● blocked (.3) |
| .5 | `bob-8r4.5` | social | 🟡 | ● blocked (.4) |
| .6 | `bob-8r4.6` | personality+conversation (+handle_message #9) | 🔴 | ● blocked (.5) |
| .7 | `bob-8r4.7` | application+runtime (+app.py→runtime #10) | 🔴 | ● blocked (.6) |
| .8 | `bob-8r4.8` | доки + закрытие каркаса | 🟡 | ● blocked (.7) |

## RESUME POINT (после паузы)

1. `bd ready` → `bob-8r4.1` (coding). Стартовать **task-init среза .1** (feature: CONTEXT+PLAN или BRIEF),
   затем координатор-волны (dev→test→review→tech-writer) → PR → owner «мержи».
2. Срез .1 **контрольный**: валидирует структуру модуля (`ports.py`/логика/`usecases/`/`adapters/` +
   `# beadloom:layer=`), правила границ, доки-в-срезе. Если схема неудобна — правим RFC/CONTEXT ДО .2.
3. Прогонять чек-лист инвариантов (CONTEXT) в test-волне каждого среза.

## Прогресс

- 2026-07-02: эпик BOB-062 отскаффолжен (PRD/RFC/CONTEXT/PLAN Approved; беады `bob-8r4` + `.1..8`
  цепочкой созданы). **Пауза** перед стартом среза .1. Рельсы Фазы 2 (граф+правила+аннотации) на main.
