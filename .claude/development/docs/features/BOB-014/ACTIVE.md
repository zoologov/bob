<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-014 — «Отношения (multi-party) + обида/охлаждение» (T1.5)

> **Last updated:** 2026-06-23
> **Phase:** Development (финал Тира 1)
> **Epic:** bob-8id · branch `features/BOB-014`

---

## Текущий беад

**Беад:** `bob-8id.2` — dev .2a: «Аппетит к разговору» (engagement appetite) — реализован,
ждёт прогона тестов на гейте (sandbox в этой сессии блокирует pytest/ruff/mypy).

## Прогресс

- [x] `.1` RelationshipTracker (per-sender) + влияние на тон/уступчивость
- [x] `.2a` Аппетит к разговору: EngagementLevel (FULL/PLAYFUL/TERSE/DECLINE) ×
      mood/topic-interest/fatigue/relationship + feedback (mood↑, fatigue↑/↓)
- [ ] `.2b` (bob-8id.6) Обида/Sulk + guest-disengage + восприятие мата
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
