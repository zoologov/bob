<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-014 — «Отношения (multi-party) + обида/охлаждение» (T1.5)

> **Last updated:** 2026-06-23
> **Phase:** Development (финал Тира 1)
> **Epic:** bob-8id · branch `features/BOB-014`

---

## Текущий беад

**Беад:** `bob-8id.1` — dev: RelationshipTracker + влияние (в работе).

## Прогресс

- [ ] `.1` RelationshipTracker (per-sender) + влияние на тон/уступчивость
- [ ] `.2` Обида/Sulk (governance-veto + холодный тон + GUPPI + восстановление, anti-Exodus)
- [ ] `.3` test · `.4` review · `.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-8id.1 | dev RelationshipTracker | — | in_progress |
| bob-8id.2 | dev Обида/Sulk | .1 | blocked |
| bob-8id.3 | test | .1,.2 | blocked |
| bob-8id.4 | review | .3 | blocked |
| bob-8id.5 | tech-writer | .4 | blocked |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Guardrails: отношения в [-1,1]+дрейф; обида не по мелочи + **гарантированный выход** (intensity→0 по
  времени) + идемпотентность; **память цела (anti-Exodus, без reset)**. Как характер.
- Sulk v1 — на owner-отношении. Источник: PRD/RFC/CONTEXT. **Закрывает Тир 1.**
