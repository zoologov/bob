<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-025 — «Адресность по непрерывности диалога (conversational floor)»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-025 (поверх BOB-023) · эпик `bob-v0k`

---

## Состояние

Тир 1 закрыт; адресность поштучна (BOB-023); повторения починены (BOB-026). Боб теряет адресата,
едва пропадает метка «Боб,…» — при госте в топике его безметочные реплики уходят в «ambient при
других» и Боб молчит. Нужен слой **непрерывности**: трекер «разговорной реплики» (conversational
floor) поверх BOB-023. PRD/RFC утверждены (дефолты: floor приклеивает прямое обращение И ответ
Боба; тайм-аут ~5 мин; сброс после 2 чужих реплик подряд; гость-инвариант по правам цел). Ветка
`features/BOB-025` синхронизирована с main (`21b023d`, BOB-026 включён).

## Ключевые решения (из RFC)

- **Трекер floor** — чистый домен `conversation_floor.py`: `FloorHolder {BOB/OTHER/IDLE}`,
  `ConversationFloor` (holder/holder_id/since/idle_streak); чистые `advance_floor(...)` (переход по
  ходу) + `resolve_addressivity(per_message, floor, now, config)` (поднимает AMBIENT→DIRECTED_TO_BOB,
  пока floor=БОБ и не истёк).
- **Персист** — порт `ConversationFloorStore` (load/save на (chat_id, thread_id)) + Sqlite-impl.
- **Интеграция в `handle_message`** поверх BOB-023: per-message classify → load floor → resolve →
  политика на эффективной адресности → (ENGAGE и Боб ответил) → advance_floor(bob_replied) → save.
- **Дефолты** `addressivity.floor.*`: enabled, timeout_seconds=300, reset_after_silent=2.
- Гость-инвариант BOB-019 по правам не трогаем; прямое обращение всегда к Бобу; SILENT для чужого.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5, Ollama (Qwen), Telegram (aiogram). DDD/Clean: трекер floor —
  чистый домен (без I/O, детерминированно по инъектированному `now`, без рандома); персист за портом;
  композиция в `app.py`; инъекция Clock/портов.
- **ТЕСТЫ через `.venv/bin/pytest -p no:cacheprovider`** (NOT `uv run` — висит), `pkill -9 -f pytest`
  перед, один прогон за раз. cov >=80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы
  — рус, без символа `x`-кириллицы в формулах (латиница).

## Зависимости и границы

- **Опираемся:** BOB-023 (`classify_addressivity`/`decide_response`/SILENT), BOB-019 (Interlocutor/
  owner/гость), BOB-014 .2a (аппетит), BOB-018 (REACT_ONLY), persistence-паттерн `XxxStore`.
- **Вне BOB-025:** реальный BobNet bot-to-bot транспорт (только фундамент turn-taking); смена
  authz/гость-инварианта по правам; полный диалог-менеджмент / семантический topic-tracking (LLM
  на каждый ход).
