<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-014 — «Отношения (multi-party) + обида/охлаждение» (T1.5)

> **Status:** Approved
> **Created:** 2026-06-23
> **Epic:** bob-8id (Тир 1 / T1.5 — финал Тира 1)

---

## Состояние

Финал Тира 1. Боб различает собеседников (BOB-019), имеет мнение/растёт (BOB-013), эмоц. глубок (BOB-020),
помнит (BOB-011/021), проактивен под governance (BOB-010), GUPPI шлёт системные сообщения. Качество
отношений не моделируется; обиды нет. PRD/RFC утверждены. main `e59a7fd`.

## Ключевые решения (из RFC)

- **RelationshipTracker** (per-sender): `relationship.py` (trust/respect/warmth/compatibility ∈ [-1,1]) +
  `apply_interaction(stance, mood, sentiment)` (малые дельты + дрейф к нейтрали) + `RelationshipStore`
  (как first_impression). Влияет на тон + порог уступчивости Negotiation; апдейт после хода.
- **Обида (Sulk)**: `sulk.py` (`SulkState`) — вход при устойчивом критическом падении owner-отношения;
  эффекты: sulk-veto в `governance` (проактив подавлен), холодный реактив (`voice.sulk_directive`),
  **GUPPI announce one-shot**; восстановление на reflect-тике (затухание времени + отогрев). **Память цела.**
- **Guardrails:** порог+устойчивость (не по мелочи); **гарантированный выход** (intensity→0 по времени);
  идемпотентность; границы; announce один раз. Anti-Exodus (без reset).

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, Ollama, Telegram (aiogram). DDD/Clean: домен чист ←
  application ← infrastructure; композиция в `app.py`. Инъекция Clock/RNG/портов.
- TDD на фейках (без сети), cov ≥80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы — рус.

## Зависимости и границы

- **Вне BOB-014:** реальный bot-to-bot; смена authz; медиа; per-person обида (v1 — owner); полная модель
  эмоций сверх Mood+relationship.
- Опираемся: BOB-013 (Negotiation/само-эволюция), BOB-019 (per-sender стор/Interlocutor), Mood, проактив
  governance (BOB-010), GUPPI, reflect-тик. **Закрывает Тир 1.**
