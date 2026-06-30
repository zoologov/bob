<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-050 — «Восприятие реакций на сообщения Боба»

> **Status:** Approved
> **Created:** 2026-06-30

---

## Состояние

Зеркало BOB-049: Боб воспринимает реакции (постановка/снятие) на СВОИ сообщения, понимает их СМЫСЛ
(Tier-0 `ReactionJudge`) и это меняет настроение/отношения/память + ощущение «меня услышали». Декоративно
(сбой тихо опускается). Транспорт: `message_reaction` (gateway `get_updates`/`set_message_reaction` есть;
ответ шлётся `send_message`/`send_rich_message`).

## Ключевые решения (утверждены)

- **Транспорт:** `message_reaction`(+count) в allowed_updates → событие `BobMessageReaction` на шину; фильтр
  «только сообщения Боба»; 🔴 verify вживую + defensive (anon → «кто-то» без «кто»).
- **Связь:** колонка `bob_message_id` в `episodic_log` (+ идемпотентная PRAGMA-миграция, как BOB-045);
  фиксировать message_id исходящего ответа Боба.
- **Шов** `ReactionJudge` (Tier-0, как `ResponseJudge`): `ReactionContext` → `ReactionMeaning` (смысл +
  mood-эффект ИЗ СМЫСЛА + warmth-нудж + «вслух?»); снятие → лёгкий негатив.
- **Эффекты** `PerceiveReaction`: настроение (BOB-033), отношения (BOB-014), память (BOB-045), пометка-вслух.
- **«Вслух»** = низкочастотная подсказка в compose (Боб вплетает сам), не отдельное сообщение.
- **🔴 Декоративно/опционально:** сбой восприятия → тихо опускается, НИКОГДА не GUPPI-нотис, не ломает ответы.
- **🔴 Authz (BOB-019):** гость реагирует — Боб чувствует, owner-приват не утекает; per-person память.

## Стандарты (из CLAUDE.md §0.1)

- Python 3.12+, asyncio · DDD/Clean (domain← application← infrastructure) · frozen+slots, StrEnum
- pytest · ruff · mypy --strict · `.venv/bin/pytest` (uv run висит) · ≥80% · beadloom ci зелёный
- Документы — на русском. Код/докстринги — на английском.

## 🔴 Инварианты (держать в голове)

- Смысл реакции — семантически, НЕ emoji→таблица; эффекты bounded (без качелей, полоса BOB-030).
- Восприятие реакции декоративно: сбой тихо опускается (принцип «полный Боб»). Не essential.
- Authz BOB-019 не ослаблен; owner-приват не утекает гостю; память per-person.
- Миграция `bob_message_id` идемпотентна/не деструктивна; 🔴 бэкап БД перед живым рестартом.
- `.venv/bin/pytest`; ≥80%; ruff/mypy --strict/beadloom ci зелёные.

## Точки интеграции

- `src/bob/infrastructure/telegram/gateway.py` / `multibot.py` / `app.py` — allowed_updates + маршрутизация
  `MessageReactionUpdated`; фиксация message_id исходящего ответа.
- `src/bob/infrastructure/persistence/sqlite_repo.py` / `schema.sql` — колонка `bob_message_id` + миграция.
- `src/bob/domain/personality/` — `BobMessageReaction`, `ReactionContext`/`ReactionMeaning`, `ReactionJudge`
  порт, промпт/парсер.
- `src/bob/application/usecases/` — `perceive_reaction.py` (эффекты); подписка на шину; запись bob_message_id;
  низкочастотная подсказка-вслух в `handle_message` compose.
- `src/bob/infrastructure/llm/` — `LlmReactionJudge` (Tier-0). Реюз BOB-033 (mood), BOB-014 (отношения),
  BOB-045 (память), BOB-049 (шов-паттерн).
