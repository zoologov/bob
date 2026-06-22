<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-020 — «Эмоциональная глубина и уязвимость» (T1.2)

> **Last updated:** 2026-06-22
> **Phase:** Development
> **Feature:** bob-36q · branch `features/BOB-020`

---

## Текущий беад

**Беад:** `bob-36q.1` — dev: off-day тон + mood→taste модуляция (в работе).

## Прогресс

- [ ] `.1` off-day тон (voice.tone_directive) + mood→taste модуляция (mood_taste.py) + врезка
- [ ] `.2` увлечение (Fascination + FascinationStore + grounded-эволюция + проявление)
- [ ] `.3` эволюция фантомов (SOUL.with_phantoms + phantom_evolution + reflect-тик + персист)
- [ ] `.4` test · `.5` review · `.6` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-36q.1 | dev off-day+mood→taste | — | in_progress |
| bob-36q.2 | dev увлечение | .1 | blocked |
| bob-36q.3 | dev эволюция фантомов | .1 | blocked |
| bob-36q.4 | test | .1,.2,.3 | blocked |
| bob-36q.5 | review | .4 | blocked |
| bob-36q.6 | tech-writer | .5 | blocked |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Главный принцип: «как характер, не конфиг»; guardrails (границы/плавность/идемпотентность/seeded-RNG).
- Off-day = mood-driven, **не** реляционная обида (BOB-014). Оси taste при модуляции НЕ мутируют.
- Источник: PRD/RFC/CONTEXT.
