<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-013 — Глубина личности

> **Status:** Approved
> **Created:** 2026-06-21
> **Epic:** bob-m6d

---

## Состояние

Замыкаем два разомкнутых контура личности (аудит `.claude/dev-docs/PERSONALITY-DEPTH-AUDIT.md`):
**Negotiation** (построен, 0 потребителей) подключаем к ответу; **Reflection→Taste** (рефлексия лог-only)
замыкаем в само-эволюцию с guardrails. PRD/RFC утверждены. BOB-012 (язык/grounding/persist проактива) — в
проде (main `dab3bab`). Боб сейчас запущен на проде (тест BOB-012 идёт параллельно).

## Ключевые решения (из RFC)

- **Negotiation-врезка:** геттер `TasteEngine.conviction_for` + порт `ZoneClassifier` (дефолт —
  детерминированная эвристика; Tier-0 LLM свопаем позже) → `Negotiation.decide` → `Stance` → **директива в
  системный промпт** (дополняет «warmly», не делает грубым).
- **Само-эволюция:** чистый `taste_evolution.reinforce` с затуханием `(1−conviction)` (анти-runaway) →
  `SOUL.with_taste/with_baseline` (+`experience_count++`) → use-case `ApplyReflection` в `ReflectTick` →
  персист `SoulStore.write_json` (round-trip готов).
- **Guardrails (жёстко):** границы [0,1]/[-1,1], малые α=0.15/β=0.10 (в конфиг), идемпотентность (маркер +
  тест двойного прогона), гейт релевантности (нет сигнала → no-op).
- Q1 парс рефлексии — Tier 0 + эвристик-фоллбэк за портом-функцией. Q3 baseline-эволюция — минимально/позже.

## Стандарты кода (из CLAUDE.md §0.1)

- **Стек:** Python 3.12+ (asyncio), SQLite + FTS5 + sqlite-vec, Ollama (локально), Telegram (aiogram).
- **Архитектура:** DDD + Clean — `domain/` (чист, без I/O, иммутабельный SOUL) ← `application/` ←
  `infrastructure/`; композиция только в `app.py`. Инъекция `Clock`/портов.
- **Качество:** TDD на фейках (без сети в CI), cov ≥80%, `ruff`, `mypy --strict` (src + tests), `beadloom ci`.
- **Не ломать:** реактив, проактив (BOB-010), память (BOB-011), тиринг, authz, язык персоны (BOB-012).
- **Документы — на русском** (проектное правило §3).

## Зависимости и границы

- **Вне эпика:** RelationshipTracker/Exodus → BOB-014 (`bob-8id`, зависит от 013); Goal/Planner/
  Self-Improvement → BOB-015 (`bob-xnz`); визуальные taste-категории — заморожены пивотом.
- Negotiation-исходы (Ф1) позже питают RelationshipTracker (BOB-014).
