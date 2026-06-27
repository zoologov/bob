<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-045 — «Память диалога по персоне + длинные паузы»

> **Status:** Approved
> **Created:** 2026-06-26

---

## Состояние

Ядро: per-person память диалога поверх BOB-019 (`Interlocutor.sender_id`), BOB-044 (окно/реплей), recall.
Сейчас гость получает ZERO памяти (`recalled=[]`, `history=[]` при `is_guest`); owner — глобальное окно.
Фича: атрибуция эпизодов `sender_id` → per-person replay + person-scoped recall, гость authz-safe.

## Ключевые решения (утверждены)

- **Атрибуция:** структурная колонка `sender_id` в `episodic_log` (+ идемпотентная миграция `ALTER ADD
  COLUMN`, индекс, best-effort бэкафилл по имени-префиксу). НЕ парсинг имени в рантайме.
- **Replay:** per-person для ЛЮБОГО собеседника (owner тоже — симметрично), окно `dialogue.recent_turns`.
- **Recall:** owner — глобальный; non-owner — пост-фильтр по `sender_id` (🔴 не утекает owner-приватное).
- **Длинные паузы:** per-person свежесть + recall; опц. лёгкий маркер «давно не виделись»
  (`dialogue.absence_hint_hours`, ~8ч).
- **🔴 Приват-инвариант:** non-owner НИКОГДА не видит чужой/owner-приватной памяти — defense-in-depth
  (фильтр в запросе истории + пост-фильтр recall). Прочие гостевые ограничения (capabilities/owner
  inner-life/owner-факты) сохраняются.

## Стандарты (из CLAUDE.md §0.1)

- Python 3.12+, asyncio · DDD/Clean (domain← application← infrastructure) · frozen+slots, StrEnum
- pytest · ruff · mypy --strict · `.venv/bin/pytest` (uv run висит) · ≥80% · beadloom ci зелёный
- Документы — на русском. Код/докстринги — на английском.

## Инварианты (держать в голове)

- 🔴 Приватность: гость видит только свою нить (свои эпизоды + ответы Боба ему); recall non-owner
  пост-фильтрован по `sender_id`; authz BOB-019 не ослаблен; гостевой ход не пишется в owner-факты.
- Миграция идемпотентна + не деструктивна; бэкап БД перед живым прогоном; бэкафилл best-effort.
- Окна развязаны: `dialogue.recent_turns` (нить) ≠ `repeat.*` (anti-repeat/tic).
- `.venv/bin/pytest`; ruff/mypy --strict/beadloom ci зелёные.

## Точки интеграции

- `src/bob/infrastructure/persistence/sqlite_repo.py` — миграция, `recent_episodes_for`, `sender_id` в
  recalled-проекции, бэкафилл; `schema.sql`.
- `src/bob/application/usecases/handle_message.py` — per-person history + scoped recall (~1006-1021),
  `_persist` пишет `sender_id` (~2170), `EpisodeReader` шов (~343), опц. absence-hint в контекст.
- `src/bob/domain/personality/interlocutor.py` — `Interlocutor.sender_id` (ключ персоны).
- `src/bob/infrastructure/config/loader.py` — `dialogue.absence_hint_hours` (опц.).
