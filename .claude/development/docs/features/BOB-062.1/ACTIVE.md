<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.1 — «Срез coding → src/bob/coding/»

> **Status:** In Progress
> **Updated:** 2026-07-23
> **Branch:** `features/BOB-062.1` · **Родитель:** `bob-8r4.1` (эпик `bob-8r4`)

---

## Беады (последовательно)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.1.1` | dev — переезд coding | ○ ready (Волна 0) |
| `bob-8r4.1.2` | dev — AaC правила границ + 3 cross-boundary | ● blocked (.1) |
| `bob-8r4.1.3` | test — pytest + coding-инварианты + beadloom ci | ● blocked (.1,.2) |
| `bob-8r4.1.4` | review — переезд + вердикт «схема удобна?» | ● blocked (.3) |
| `bob-8r4.1.5` | tech-writer — SPEC/DOC + закрыть #11 | ● blocked (.4) |

Критпуть: `.1 → .2 → .3 → .4 → .5` (один PR на срез).

## Прогресс

- 2026-07-23: BRIEF Approved; роль-беады созданы; ветка `features/BOB-062.1`. Старт Волны 0 (.1 dev).

## Заметки для среза

- 🔑 Контрольный: review (.4) выносит вердикт по схеме модуля → влияет на .2–.8 эпика.
- 🔴 Ловушка: `test_coding_never_merge_and_autonomy_guard.py` — строковые литералы путей.
- Прод-импорты править только в `app.py` + `domain/ports/__init__.py`.
- Инварианты coding: never-merge / plan-gate / PR≠merge / worktree-изоляция / NL-approve-stop.
