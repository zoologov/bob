<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-052 — «Разрешение на привилегированное»

> **Created:** 2026-06-30

## Фокус

Не-авторизованный просит привилегированное -> Боб спрашивает owner (pending) -> approve исполнить/durable /
deny отказ. Только owner решает. Координатор, автономно. Dev ПОСЛЕДОВАТЕЛЬНО (гонка app.py/handle_message).

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-jko.1` | dev — домен + PrivilegeJudge + store | in_progress | — |
| `bob-jko.2` | dev — флоу детект+нотис+решение | blocked | .1 |
| `bob-jko.3` | dev — исполнение approve/deny+durable | blocked | .1,.2 |
| `bob-jko.4` | test — US-1..6 + инвариант + декоративность | blocked | .1-.3 |
| `bob-jko.5` | review — SECURITY | blocked | .4 |
| `bob-jko.6` | tech-writer | blocked | .5 |

## Критический путь

```
.1 домен+швы → .2 детект+нотис+решение → .3 исполнение → .4 test → .5 review → .6 tech-writer
```

## Инварианты (держать в голове)

- 🔴 ТОЛЬКО owner approve/deny/authorize; не-owner не разрешает даже себе.
- 🔴 Привилегия только для одобренного запроса (per-request) или явный durable; без owner — ничего не
  раскрывается (безопасный дефолт = отказ). Внутрянка/приват без approve не раскрыта; BOB-051 не ослаблена.
- 🔴 Сбой флоу -> тихо опускается, обычный ответ Боба цел, НЕ GUPPI-нотис.
- Миграция идемпотентна; 🔴 бэкап data/bob.db перед живым рестартом.
- .venv/bin/pytest; >=80%; ruff/mypy --strict/beadloom ci зелёные.

## Прогресс

- 2026-06-30 — PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; старт координатора.
