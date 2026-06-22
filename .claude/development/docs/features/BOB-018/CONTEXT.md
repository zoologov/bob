<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-018 — «Выражение» (BOB-010 Ф2 · T1.1)

> **Status:** Approved
> **Created:** 2026-06-21
> **Feature:** BOB-018 (Тир 1 / T1.1)

---

## Состояние

Боб отзывчив, но однообразен по форме. Даём спонтанную выразительность через 4 grounded-элемента под
единым `ExpressionPlan`. PRD/RFC утверждены. main `c2b43ea` (после roadmap-правок BOB-019). Опираемся на
готовое: память (BOB-011), grounding/язык (BOB-012), мнение (BOB-013), voice/anti-bait (BOB-016),
проактив (BOB-010).

## Ключевые решения (из RFC)

- **`ExpressionPlan`** — чистая `decide_expression(mood, signals, rng, freqs)` (heuristic + seeded-RNG, не
  LLM): режим `REACT_ONLY`/`REPLY` + флаги `leak_inner_life`/`callback` + `form_hint`.
- **Реакции** через порт `MessageReactor` → `set_message_reaction` (mood→emoji, стандартный set).
- **Внутренняя жизнь** = реальная свежая рефлексия (BOB-012); **колбэк** = гибрид `MemoryRecall` (BOB-011);
  оба **grounded**, нет материала → no-op (анти-конфабуляция).
- **Переменная форма** = `form_hint` + директива в `voice.py` (дополняет anti-bait).
- Всё **редко и по состоянию** (анти-тик), детерминированно (seeded-RNG + Clock). Частоты — в конфиг (Q3).

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, Ollama, Telegram (aiogram). DDD/Clean: домен чист/
  иммутабелен ← application ← infrastructure; композиция в `app.py`. Инъекция Clock/RNG/портов.
- TDD на фейках (без сети в CI), cov ≥80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`.
- Документы — на русском.

## Зависимости и границы

- **Вне BOB-018:** эмоции/уязвимость/увлечение → **T1.2**; соц. идентичность/незнакомцы → **BOB-019**;
  отношения → **BOB-014**; картинки-реакции → **Тир 4** (тут только текст + нативные emoji-реакции).
- Не ломать: voice (BOB-016), язык (BOB-012), Negotiation (BOB-013), проактив (BOB-010), память (BOB-011).
