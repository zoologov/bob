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
| `bob-r3z.1` | dev — split ports.py → пакет + шим | ✓ done (pytest 3269 ✓, mypy ✓) |
| `bob-r3z.2` | dev — детальный граф beadloom | ✓ done (4→27 узлов, lint ✓) |
| `bob-r3z.3` | dev — docs generate скелеты | ✓ done (15 скелетов) |
| `bob-r3z.4` | dev — AaC rules.yml | ✓ done (11 правил, lint exit 0) |
| `bob-r3z.8` | dev — сверка граф↔правила↔доки | ✓ done (ports-узел, 28 узлов, coverage 68%) |
| `bob-r3z.5` | test | ✓ done (pytest 3269, coverage 100%) |
| `bob-r3z.6` | review | ✓ done (OK, 0 critical/major) |
| `bob-r3z.7` | tech-writer | ✓ done (architecture.md рефреш, #7/#8 закрыты) |
| `bob-r3z.9` | dev (Gate-fix) | ✓ done (112 аннотаций #1, скелеты отвязаны в Ф3) |

## Gate

`beadloom ci` **EXIT 0** — reindex/lint/sync-check/docs-audit/config-check/doctor PASS.
Решение owner: контент SPEC-доков отложен в Фазу 3 (скелеты отвязаны, Gate требует наполнения).
Остаток — не-блокирующий warn `no-monster-modules: usecases 217>200` (ожидаемо, #9).

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
