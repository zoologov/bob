<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-065 — «Фундамент: split ports + граф + AaC»

> **Status:** Approved
> **Created:** 2026-07-02
> **CONTEXT:** `./CONTEXT.md`

---

## Беады (DAG)

Родитель: **`BOB-065`** [feature] — «Фундамент: split ports.py + детальный граф + AaC-правила».

| Беад | Роль | Что делает | Зависит от | BOB-Issues |
|------|------|-----------|-----------|-----------|
| **.1** | dev | Split `domain/ports.py` → пакет `domain/ports/`: `kernel/capabilities/memory/personality/conversation/social/proactivity/coding` + `__init__.py` реэкспорт-шим (`__all__` = 51). Перенести внутренние связки. | — | #7 |
| **.2** | dev | Граф: узлы-слои (domain/application/infrastructure + runtime=app.py, теги) + подмодульные узлы (feature/component) на реальных путях + `part_of`/`depends_on` рёбра + точечные `# beadloom:`-аннотации. `beadloom reindex` чистый. | — | #1/#2 (частично) |
| **.3** | dev | `docs generate` скелеты для новых узлов (чтобы `module_coverage` был зелёным); БЕЗ наполнения содержимым. | .2 | #3 (частично) |
| **.4** | dev | `.beadloom/_graph/rules.yml` (v3): `layers` + `forbid_import` ×3 + `forbid_cycles` + `deny` + `module_coverage` + `check`. Триаж срабатываний, severity-ratchet. `beadloom lint --strict` зелёный. | .2 | #8 |
| **.5** | test | Тест-импорт всех 51 символа из `bob.domain.ports`; регресс `pytest`; проверка `beadloom reindex`/`lint --strict`/`sync-check` зелёные. | .1, .3, .4 | — |
| **.6** | review | Корректность split (шим полон, mypy), граф честен путям, правила используют реальные примитивы и осмысленны, severity-стратегия обоснована, поведение не изменилось. Read-only. | .5 | — |
| **.7** | tech-writer | Обновить доки: `architecture.md`/`docs/` отражают новый граф+правила; закрыть #7/#8 и отметить #1/#2 частично в BOB-Issues.md. | .6 | — |

## Волны координатора

- **Волна 0 (parallel):** `.1` (ports split) ∥ `.2` (граф) — разные файлы (`src/bob/domain/ports*` vs `.beadloom/`), конфликтов нет.
- **Волна 1 (parallel, после .2):** `.3` (docs-скелеты) ∥ `.4` (rules.yml) — оба нуждаются в узлах графа.
- **Волна 2:** `.5` (test) — после всех dev.
- **Волна 3:** `.6` (review) — после test.
- **Волна 4:** `.7` (tech-writer) — после review.

Критический путь: `.2 → .4 → .5 → .6 → .7`.

## Риски / особые указания

- 🔴 `.1`: `__all__` пакета = точное объединение 51 символа; тест-импорт всех имён + `mypy --strict`.
- 🔴 `.4`: если `error`-правило краснеет на текущем коде — триаж (чинить/понижать с TODO), не замазывать.
  Ожидаемо загорится `no-monster-modules` (warn) на handle_message/app.py/gateway — это ок (#9/#10/#25).
- `.2`/`.3`/`.4`: `beadloom reindex` после каждого изменения графа; не аннотировать 186 файлов вручную
  (опора на `source`-префикс).
- Merge-slot не критичен (файловые домены беадов почти не пересекаются); один PR на всю фичу.

## Порядок создания беадов

Родитель `BOB-065` [feature] → `.1`..`.7` [task] → зависимости по таблице. Создаются ПОСЛЕ утверждения
PLAN.
