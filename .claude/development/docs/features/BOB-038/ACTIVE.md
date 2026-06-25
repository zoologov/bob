<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-038 — T3.A⁺ «Архитектурный контекст»

> **Feature:** BOB-038 · родитель `bob-4be` · ветка `features/BOB-038`
> **Обновлено:** 2026-06-26

---

## Фокус

Read-only навык `code_rationale`: код ↔ почему (git→беады→фича-доки→граф). Идея самого Боба (T3.A⁺).

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-4be.1` | dev — порт code_history + git фикс-формы + домен-парсер | ready | — |
| `bob-4be.2` | dev — навык code_rationale + провязка + конфиг | blocked | .1 |
| `bob-4be.3` | test — US-1..5 + приват + git-формы + регрессии | blocked | .1,.2 |
| `bob-4be.4` | review | blocked | .3 |
| `bob-4be.5` | tech-writer | blocked | .4 |

## Критический путь

```
.1 порт+git-формы+парсер → .2 навык+провязка → .3 test → .4 review → .5 tech-writer
```

## Прогресс

- 2026-06-26 — PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; запуск координатора.

## Инварианты

- 🔴 Приват-инвариант: навык не читает SOUL/`bob.db`/`.env`/`config`; git — только read-log фикс-формы (без shell/инъекций/`git show`).
- Только чтение; навык НЕ в автономном `goals.safe_capabilities` (диалоговый).
- Честное «история решения не зафиксирована» при отсутствии связки.
- `.venv/bin/pytest` (uv run висит); ≥80%; ruff/mypy --strict/beadloom ci зелёные.
