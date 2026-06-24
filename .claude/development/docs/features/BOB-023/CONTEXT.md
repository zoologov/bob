<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-023 — «Адресность»

> **Status:** Approved
> **Created:** 2026-06-23
> **Feature:** BOB-023 (Tier-1-капстоун человечности + BobNet-фундамент)

---

## Состояние

Боб различает собеседников (BOB-019), реагирует/молчит-частично (BOB-018 REACT_ONLY, BOB-014 .2a DECLINE),
но **не знает адресности** (кому сообщение) — встревает в чужой разговор; событие не несёт reply-to/@mention.
PRD/RFC утверждены. main `9bfae99`. Боб запущен на проде.

## Ключевые решения (из RFC)

- **Пламбинг:** `MessageReceived` += `reply_to_sender_id` + `mentions_bob`; multibot извлекает из aiogram
  (reply_to/entities) против id/username бота Боба (`BotRegistry`/`get_me`).
- **Детектор** `domain/personality/addressivity.py` (чистый): DIRECTED_TO_BOB / DIRECTED_TO_OTHER / AMBIENT.
- **Политика** (поверх аппетита .2a + perception): к Бобу→всегда ответ; к другому→по умолчанию SILENT, но
  **интересная тема втягивает** (высокий порог); ambient→молча/лайк, втягивает легче. Новый исход **SILENT**.
- **Guardrails:** прямое обращение всегда отвечается; 1:1 owner↔Bob ambient→вступает; не перехватывает
  чужой диалог; гост-инвариант BOB-019 цел.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, Ollama, Telegram (aiogram). DDD/Clean: домен чист ←
  application ← infrastructure; композиция в `app.py`. Инъекция Clock/RNG/портов.
- **ТЕСТЫ через `.venv/bin/pytest -p no:cacheprovider`** (NOT `uv run` — висит), `pkill -9 -f pytest` перед,
  один прогон за раз. cov ≥80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы — рус.

## Зависимости и границы

- **Вне BOB-023:** реальный bot-to-bot транспорт (только основа turn-taking); смена authz/гост-инварианта;
  полный диалог-менеджмент.
- Опираемся: BOB-019 (Interlocutor/sender/гость), BOB-018 (REACT_ONLY/ExpressionPlan), BOB-014 .2a
  (engagement appetite/interest), gateway multibot.
