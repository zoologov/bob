<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-017 Phase A — «Боб знает свой мир»

> **Feature:** BOB-017 Phase A · родитель `bob-9eh` · ветка `features/BOB-017`
> **Обновлено:** 2026-06-25

---

## Фокус

Read-only навыки самоинтроспекции за capability-швом. Волна последовательная, один PR.

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-9eh.1` | dev — PrivacyGuard + RepoIntrospector + SubprocessRepoIntrospector | ready | — |
| `bob-9eh.2` | dev — навыки + провязка в app.py + конфиг | blocked | .1 |
| `bob-9eh.3` | test — US-1..6 + приват-инвариант + регрессии | blocked | .1,.2 |
| `bob-9eh.4` | review — read-only/приват/границы/DDD | blocked | .3 |
| `bob-9eh.5` | tech-writer — architecture.md | blocked | .4 |

## Критический путь

```
.1 приват+порт+инфра → .2 навыки+провязка+конфиг → .3 test → .4 review → .5 tech-writer
```

## Прогресс

- 2026-06-25 — PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; запуск координатора.

## Инварианты (держать в голове)

- 🔴 Приват-инвариант: SOUL/`bob.db`/`.env`/`config` недоступны навыкам, не обходится промптом.
- Только чтение; subprocess `exec` без shell + фикс-allowlist read-подкоманд.
- Навыки НЕ в автономном `goals.safe_capabilities` (диалоговые, не самонаправленные).
- `.venv/bin/pytest` (uv run висит); ≥80%; ruff/mypy --strict/beadloom ci зелёные.
