<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-019 — «Свои и чужие» (соц. идентичность · T1.4)

> **Status:** Approved
> **Created:** 2026-06-23
> **Epic:** bob-apv (Тир 1 / T1.4)

---

## Состояние

Боб не обыгрывает, что видит, от кого сообщение; неавторизованный → GUPPI hard-reject. Даём соц. слой
(восприятие отправителя + человечная реакция на незнакомца) поверх неизменного authz. PRD/RFC утверждены.
main `a4ebe58`. `MessageReceived` уже несёт `sender_id`/`sender_name`; `Authorizer` даёт is_owner/is_authorized/
authorize.

## Ключевые решения (из RFC)

- **`Interlocutor`** (owner/known/guest/bot + trust), чистая классификация из Authorizer+sender; люди и боты.
- **Гость** (неавториз. + в разрешённом чате/топике Боба) → **Боб-соц-путь** вместо GUPPI hard-reject:
  компоновка **без tool-loop**, **без recall приватной памяти owner**, + `voice.stranger_directive()`.
- **First-impression** — лёгкий per-sender стор (основа под BOB-014).
- **🔴 Инвариант безопасности:** гость = ноль capability + ноль owner-памяти; chat-scope/owner-доступ без
  изменений; промоушен только `/authorize`; редакция по аудитории.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, Ollama, Telegram (aiogram). DDD/Clean: домен чист ←
  application ← infrastructure; композиция в `app.py`. Инъекция Clock/портов.
- TDD на фейках (без сети), cov ≥80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы — рус.

## Зависимости и границы

- **Вне BOB-019:** полный RelationshipTracker/обида → **BOB-014**; реальный bot-to-bot транспорт (только
  абстракция «собеседник»); ЛС с ботами; изменение модели доступа к возможностям.
- Опираемся: authz (BOB-002/003), gateway/GUPPI (multibot), память (BOB-011/021), личность (mood/voice/
  выражение/эмоции). Готовит фундамент multi-party BOB-014.
