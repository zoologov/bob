<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-021 — «Консолидация памяти» (BOB-011 Ф2 · T1.3)

> **Last updated:** 2026-06-23
> **Phase:** Done (dev .1–.3 + test + review + tech-writer завершены)
> **Feature:** bob-0xz · branch `features/BOB-021`

---

## Текущий беад

**Беад:** все закрыты. Фича готова к PR в `main`.

## Прогресс

- [x] `.1` дайджесты: миграция consolidated + digest-тип + ConsolidateMemory (тик) + врезка
- [x] `.2` дедуп фактов: superseded_by + DedupFacts (косинус) + recall исключает superseded
- [x] `.3` всплытие старого: surface_old опт-ин + колбэк BOB-018
- [x] `.4` test: cov 99% (новые модули 100%), US-1..3 + guardrails/приватность
- [x] `.5` review (+приватность)
- [x] `.6` tech-writer: architecture.md (схема/ConsolidateMemory/DedupFacts/surface_old + reflect-тик + конфиг)

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-0xz.1 | dev дайджесты+схема | — | closed |
| bob-0xz.2 | dev дедуп фактов | .1 | closed |
| bob-0xz.3 | dev всплытие старого | .1 | closed |
| bob-0xz.4 | test | .1,.2,.3 | closed |
| bob-0xz.5 | review (+приватность) | .4 | closed |
| bob-0xz.6 | tech-writer | .5 | closed |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Локально/приватно (фейки в CI) · не деструктивно (только пометки) · идемпотентно · drop-in MemoryRecall.
- Консолидация — на reflect-тике (как BOB-020 эволюции). Источник: PRD/RFC/CONTEXT.
