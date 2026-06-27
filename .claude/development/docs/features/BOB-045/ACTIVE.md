<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-045 — «Память диалога по персоне + длинные паузы»

> **Created:** 2026-06-26

## Фокус

Per-person память диалога (атрибуция `sender_id` → per-person replay + scoped recall) + длинные паузы.
Координатор, автономный прогон (owner утвердил все шаги).

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-1i0.1` | dev — атрибуция/миграция/read-шов/бэкафилл | in_progress | — |
| `bob-1i0.2` | dev — per-person history + scoped recall | blocked | .1 |
| `bob-1i0.3` | dev — длинные паузы (absence-hint) | blocked | .1,.2 |
| `bob-1i0.4` | test — US-1..5 + приват-инвариант + миграция | blocked | .1,.2,.3 |
| `bob-1i0.5` | review — SECURITY приват/authz/миграция | blocked | .4 |
| `bob-1i0.6` | tech-writer — architecture.md | blocked | .5 |

## Критический путь

```
.1 атрибуция → .2 per-person wiring → .3 паузы → .4 test → .5 review → .6 tech-writer
```

## Инварианты (держать в голове)

- 🔴 Приват: non-owner видит только свою нить; recall non-owner пост-фильтр по `sender_id`; authz BOB-019
  не ослаблен; гостевой ход не в owner-факты.
- Миграция идемпотентна/не деструктивна; 🔴 бэкап `data/bob.db` перед живым рестартом.
- Окна развязаны (`dialogue.recent_turns` ≠ `repeat.*`).
- `.venv/bin/pytest`; ≥80%; ruff/mypy --strict/beadloom ci зелёные.

## Прогресс

- 2026-06-26 — PRD/RFC/CONTEXT/PLAN утверждены (owner: автономный прогон); беады созданы; старт координатора.
