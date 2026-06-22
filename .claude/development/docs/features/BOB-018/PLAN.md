<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-018 — «Выражение» (BOB-010 Ф2 · T1.1)

> **Status:** Approved
> **Created:** 2026-06-21
> **Feature:** BOB-018 (Тир 1 / T1.1)

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (ядро + форма) | `domain/personality/expression.py` (`decide_expression`/`ExpressionPlan`, heuristic+seeded-RNG) + врезка плана в `handle_message` (REPLY-путь) + **переменная форма** (`form_hint` + директива в `voice.py`). Тесты на фейках. | — |
| `.2` | **dev** (реакции) | Порт `MessageReactor` + telegram-реализация `set_message_reaction` (mood→emoji, стандартный set) + путь `REACT_ONLY` (реакция вместо ответа, без LLM) + best-effort фоллбэк. | `.1` |
| `.3` | **dev** (grounded добавки) | **Внутренняя жизнь** (свежая реальная рефлексия → промпт) + **колбэк** (гибрид `MemoryRecall` → реальный момент в промпт); оба no-op при отсутствии материала (анти-конфабуляция). | `.1` |
| `.4` | **test** | Покрытие ≥80% + US-1..4 + grounded (нет материала → no-op) + анти-тик (редко/по состоянию, seeded-RNG) + регрессии (voice/язык/Negotiation/проактив/память). | `.1,.2,.3` |
| `.5` | **review** | DDD-чистота, grounded без конфабуляции, анти-тик реально держит, не ломает voice/anti-bait/язык, реакции best-effort. Read-only. | `.4` |
| `.6` | **tech-writer** | `architecture.md` (рус): `ExpressionPlan`, `MessageReactor`/реакции, leak/callback grounded, form_hint в voice. Gate. | `.5` |

## Волны (последовательно на одной ветке)

```
.1 (ядро+форма) → .2 (реакции) → .3 (grounded добавки) → .4 test → .5 review → .6 tech-writer
```

- Dev-беады ведём **последовательно** (фоновые агенты, общий рабочий tree). Ветка `features/BOB-018`, один PR.
- `.2` и `.3` оба на `.1`; идут друг за другом (без параллельного дерева).

## Критерии готовности

- [ ] 4 элемента работают grounded + «как характер, не конфиг»; анти-тик держит.
- [ ] Реактив/проактив/память/язык/Negotiation/voice/тиринг/authz не сломаны.
- [ ] cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
