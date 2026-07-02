<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-065 — «Фундамент: split ports + граф + AaC»

> **Status:** In Progress
> **Updated:** 2026-07-02
> **Branch:** `features/BOB-065` · **Parent bead:** `bob-r3z`

---

## Беады

| Беад | Роль | Статус |
|------|------|--------|
| `bob-r3z.1` | dev — split ports.py → пакет + шим | ○ ready (Волна 0) |
| `bob-r3z.2` | dev — детальный граф beadloom | ○ ready (Волна 0) |
| `bob-r3z.3` | dev — docs generate скелеты | ● blocked (.2) |
| `bob-r3z.4` | dev — AaC rules.yml | ● blocked (.2) |
| `bob-r3z.5` | test | ● blocked (.1,.3,.4) |
| `bob-r3z.6` | review | ● blocked (.5) |
| `bob-r3z.7` | tech-writer | ● blocked (.6) |

## Волны

- **Волна 0 (сейчас):** `.1 ∥ .2` (разные файлы: `src/bob/domain/ports*` vs `.beadloom/`).
- **Волна 1:** `.3 ∥ .4` (после .2).
- **Волна 2:** `.5` → **Волна 3:** `.6` → **Волна 4:** `.7`.

## Прогресс

- 2026-07-02: docs (PRD/RFC/CONTEXT/PLAN) Approved; беады созданы; ветка создана. Старт Волны 0.

## Инварианты (🔴)

- `.1`: `__all__` = 51 символ точно; тест-импорт всех + mypy --strict.
- `.4`: error-правила зелёные на текущем коде; ложные → триаж (не замазывать). `no-monster` = warn.
- reindex после каждого изменения графа; не аннотировать 186 файлов вручную.
