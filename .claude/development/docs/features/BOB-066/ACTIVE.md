<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-066 — «Человеческое групповое присутствие»

> **Status:** In Progress
> **Updated:** 2026-07-29
> **Эпик-беад:** `bob-vol` · **Ветка:** `features/BOB-066`

---

## Беады (эпик `bob-vol`)

| Срез | Беад | Тема | Статус |
|------|------|------|--------|
| **0** | `bob-vol.1` | Инструментарий качества (pytest-bdd + mutmut + scaffold) | ○ ready (роли .1.1–.1.4) |
| 1.1 | `bob-vol.2` | Reply-to на выходе | ● blocked (S0) |
| 1.2 | `bob-vol.3` | Floor-по-говорящему | ● blocked (S0) |
| 2.1 | `bob-vol.4` | Intake-развязка + TurnScope | ● blocked (S0) |
| 2.2 | `bob-vol.5` | Рефлексивный read-the-room + split + INV-1 + web-лаз | ● blocked (S0,1.1,1.2,2.1) |
| 2.3 | `bob-vol.6` | Ритм-слой presence/ + доля эфира | ● blocked (S0,2.1) |
| 2.4 | `bob-vol.7` | RoomMood-в-тоне + салиенс/бюджет | ● blocked (2.2,2.3) |
| 2.5 | `bob-vol.8` | Per-person обида/охлаждение | ● blocked (S0) |
| 2.6 | `bob-vol.9` | Такт разглашения + кредит доверия | ● blocked (S0) |
| 3.1 | `bob-vol.10` | Staleness/merge-gate | ● blocked (2.1,2.3) |
| 3.2 | `bob-vol.11` | Backlog catch-up + бэкпрешер | ● blocked (2.1,2.2,3.1) |

**Критический путь:** `S0 → 1.2 → 2.1 → 2.2 → 2.4 → 3.2`.

## Срез 0 — роль-беады (текущий фокус)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-vol.1.1` | dev — harness (pytest-bdd+mutmut+scaffold) | ○ ready |
| `bob-vol.1.2` | test — harness зелёный + порог | ● blocked (.1.1) |
| `bob-vol.1.3` | review — метод BDD+mutation | ● blocked (.1.2) |
| `bob-vol.1.4` | tech-writer — dev-доки | ● blocked (.1.3) |

## Пирамида качества (CONTEXT §Парадигмы)

BDD acceptance (pytest-bdd+Gherkin) · Mutation (mutmut, прицельно domain, ≥85%) · TDD unit · DDD +
Cohesion. 🔴 DoD: full-reindex + full-mypy + `beadloom ci`.

## Прогресс
- 2026-07-29: PRD/RFC/CONTEXT/PLAN Approved; методология DDD/TDD/BDD/Cohesion/Mutation зафиксирована
  стоячей (CLAUDE.md §0.2 + 4 роль-агента); эпик `bob-vol` + 11 срезов + Срез-0 роли созданы, DAG
  связан. Старт Среза 0.
