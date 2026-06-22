<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-020 — «Эмоциональная глубина и уязвимость» (T1.2)

> **Status:** Approved
> **Created:** 2026-06-22
> **Feature:** BOB-020 (Тир 1 / T1.2)

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (off-day + mood→taste) | `voice.tone_directive(mood)` (уязвимость/«не знаю», заменяет безусловный warm) + `domain/personality/mood_taste.py` (`modulate`/`experiment_bias`, сдвиг ≤1, временно) + врезка в `handle_message`. Тесты. | — |
| `.2` | **dev** (увлечение) | `domain/personality/fascination.py` + `FascinationStore` (персист per-persona) + grounded-шаг эволюции (Tier-0, на reflect-тике, идемпотентно) + проявление редко в compose/проактив (no-op без увлечения). | `.1` |
| `.3` | **dev** (эволюция фантомов) | `SOUL.with_phantoms` + `domain/personality/phantom_evolution.py` (`evolve`, медленно/идемпотентно/seeded-RNG, границы) + шаг на reflect-тике + персист `SoulStore`. | `.1` |
| `.4` | **test** | ≥80% + US-1..4 + guardrails (сдвиг ≤1, идемпотентность, границы, off-day не грубит) + grounded + регрессии (voice/язык/Negotiation/выражение/проактив). | `.1,.2,.3` |
| `.5` | **review** | DDD-чистота, guardrails держат, off-day ≠ грубость/обида, оси taste не мутируют, не ломает voice/выражение. Read-only. | `.4` |
| `.6` | **tech-writer** | `architecture.md` (рус): tone_directive, mood_taste, fascination, phantom_evolution, with_phantoms. Gate. | `.5` |

## Волны (последовательно на одной ветке)

```
.1 (off-day + mood→taste) → .2 (увлечение) → .3 (фантомы) → .4 test → .5 review → .6 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-020`, один PR.

## Критерии готовности

- [ ] 4 элемента работают «как характер, не конфиг», под guardrails; «вечный позитив» снят; off-day ≠ обида.
- [ ] Реактив/проактив/память/язык/Negotiation/выражение/voice/тиринг/authz не сломаны.
- [ ] cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
