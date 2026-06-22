<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-020 — «Эмоциональная глубина и уязвимость» (T1.2)

> **Status:** Approved
> **Created:** 2026-06-22
> **Feature:** BOB-020 (Тир 1 / T1.2)

---

## Состояние

Боб выразителен (BOB-018), с мнением/растущими вкусами (BOB-013), но эмоционально ровный и однобоко-
позитивный. Даём 4 элемента эмоциональной глубины. PRD/RFC утверждены. main `14795db` (после BOB-018).
Опираемся на: Mood (deep), Taste+само-эволюция (BOB-013), voice/anti-bait (BOB-016), ExpressionPlan
(BOB-018), проактив (BOB-010).

## Ключевые решения (из RFC)

- **Off-days:** `voice.tone_directive(mood)` — тон зависит от настроения (низкое → уязвимее/«не знаю»),
  заменяет безусловный «warmly» (`handle_message:121`). Off-day = производное от mood (без нового состояния).
- **Увлечение:** `Fascination` (+`FascinationStore`); редкий grounded-шаг эволюции (Tier-0, Q1/Q2);
  проявляется редко, no-op без увлечения.
- **Mood→Taste:** чистый `mood_taste.modulate` (сдвиг ≤1 шаг, **временно**, оси не мутируют) + `experiment_bias`.
- **Фантомы:** `SOUL.with_phantoms` + `phantom_evolution.evolve` (медленно/идемпотентно/seeded-RNG) + персист.
- **Guardrails (как BOB-013):** границы, плавность, идемпотентность, не-runaway, seeded-RNG + Clock.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, Ollama, Telegram (aiogram). DDD/Clean: домен чист/
  иммутабелен ← application ← infrastructure; композиция в `app.py`. Инъекция Clock/RNG/портов.
- TDD на фейках (без сети), cov ≥80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы — рус.

## Зависимости и границы

- **Вне BOB-020:** реляционная обида/отношения → **BOB-014**; соц. идентичность → **BOB-019**; медиа → Тир 4.
- Off-day (mood-driven) ≠ обида (реляционная, BOB-014). Mood остаётся ядром аффекта (вторую систему не плодим).
- Не ломать: voice (BOB-016), язык (BOB-012), Negotiation (BOB-013), выражение (BOB-018), проактив, память.
