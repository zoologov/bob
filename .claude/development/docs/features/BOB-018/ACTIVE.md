<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-018 — «Выражение» (BOB-010 Ф2 · T1.1)

> **Last updated:** 2026-06-22
> **Phase:** Done
> **Feature:** bob-c4w · branch `features/BOB-018`

---

## Текущий беад

**Беад:** `bob-c4w.6` — tech-writer: architecture.md + Gate (завершается).

## Прогресс

- [x] `.1` ядро: ExpressionPlan (decide_expression) + form_hint + voice.py + врезка в handle_message
- [x] `.2` реакции: MessageReactor + set_message_reaction + REACT_ONLY
- [x] `.3` grounded-добавки: внутренняя жизнь (ReflectionReader) + колбэки (MemoryRecall, no-op без материала)
- [x] `.4` test · [x] `.5` review · [x] `.6` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-c4w.1 | dev ядро+форма | — | done |
| bob-c4w.2 | dev реакции | .1 | done |
| bob-c4w.3 | dev grounded-добавки | .1 | done |
| bob-c4w.4 | test | .1,.2,.3 | done |
| bob-c4w.5 | review | .4 | done |
| bob-c4w.6 | tech-writer | .5 | done |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Главный принцип: grounded + «как характер, не конфиг»; анти-тик (редко/по состоянию, seeded-RNG).
- Источник: PRD/RFC/CONTEXT.
