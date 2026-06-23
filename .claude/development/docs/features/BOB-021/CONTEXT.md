<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-021 — «Консолидация памяти» (BOB-011 Ф2 · T1.3)

> **Status:** Approved
> **Created:** 2026-06-22
> **Feature:** BOB-021 (Тир 1 / T1.3)

---

## Состояние

Память Ф1 (гибрид FTS5+vector+RRF, BGE-M3/Ollama, sqlite-vec, search_memory) растёт безгранично и не
взрослеет. Даём 3 механизма консолидации. PRD/RFC утверждены. main `2c757df` (после BOB-020). Reflect-тик
уже несёт редкие фоновые шаги (ApplyReflection/EvolveFascination/EvolvePhantoms) — туда же консолидация.

## Ключевые решения (из RFC)

- **Схема:** `episodic_log.consolidated`; дайджест = строка `episodic_log` (`event_type='digest'`,
  эмбеддится → recall наравне); `semantic_memory.superseded_by`. Миграции идемпотентны.
- **Дайджесты:** `ConsolidateMemory` (тик, Tier-0, не деструктивно, идемпотентно).
- **Дедуп:** `DedupFacts` (тик, косинус эмбеддингов ~0.92+, канонич.=новейший, остальные superseded; несхожие не сливаем).
- **Всплытие старого:** `surface_old` опт-ин в `HybridMemoryRecall` (дефолт не меняется → drop-in) + колбэк BOB-018.
- Всё локально/приватно (фейки в CI), под guardrails (консервативные пороги, без runaway), конфиг `memory.*`.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, Ollama, Telegram (aiogram). DDD/Clean: домен чист ←
  application ← infrastructure; композиция в `app.py`. Инъекция Clock/портов.
- TDD на фейках (эмбеддер/LLM за портами, без сети), cov ≥80%, `ruff`, `mypy --strict` (src+tests),
  `beadloom ci`. Документы — рус.

## Зависимости и границы

- **Вне BOB-021:** внешний RAG (доки/веб) → P3; мультимодальная/облачная память; смена эмбеддера;
  деструктивное удаление (только пометки).
- `MemoryRecall` остаётся **drop-in** (потребители не меняются). Не ломать: recall Ф1, проактив, выражение
  (BOB-018), эмоции (BOB-020), тиринг, authz.
