<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-018 — «Выражение» (BOB-010 Ф2 · T1.1)

> **Last updated:** 2026-06-21
> **Phase:** Development
> **Feature:** bob-c4w · branch `features/BOB-018`

---

## Текущий беад

**Беад:** `bob-c4w.1` — dev: ExpressionPlan + переменная форма (в работе).

## Прогресс

- [ ] `.1` ядро: ExpressionPlan (decide_expression) + form_hint + voice.py + врезка в handle_message
- [ ] `.2` реакции: MessageReactor + set_message_reaction + REACT_ONLY
- [ ] `.3` grounded-добавки: внутренняя жизнь + колбэки (no-op без материала)
- [ ] `.4` test · `.5` review · `.6` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-c4w.1 | dev ядро+форма | — | in_progress |
| bob-c4w.2 | dev реакции | .1 | blocked |
| bob-c4w.3 | dev grounded-добавки | .1 | blocked |
| bob-c4w.4 | test | .1,.2,.3 | blocked |
| bob-c4w.5 | review | .4 | blocked |
| bob-c4w.6 | tech-writer | .5 | blocked |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Главный принцип: grounded + «как характер, не конфиг»; анти-тик (редко/по состоянию, seeded-RNG).
- Источник: PRD/RFC/CONTEXT.
