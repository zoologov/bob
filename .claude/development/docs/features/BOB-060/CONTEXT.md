<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-060 — «Голос Боба при поиске»

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Унифицировать оба пути анонса поиска на **живую Tier-0-генерацию** и **вырезать зашитое**: удалить
`WEB_SEARCH_PROGRESS_PHRASES` + seeded-fallback; `GatewayProgressAnnouncer` говорит только через
`InterimLineGenerator` (реюз BOB-057), сбой/пусто → **тишина** (не шаблон). tool-loop передаёт запрос как
topic → живой контекстный интерим и там. + лёгкий register-nudge: находка/хедж — в голосе Боба, не «отчёт
агента».

## Ключевые решения (утв. в PRD/RFC)

1. Удалить `WEB_SEARCH_PROGRESS_PHRASES`/`DEFAULT_PROGRESS_PHRASES`/`phrases`/seeded-fallback **полностью**;
   сбой генерации → **тишина**.
2. Унификация: оба пути через `_announce_live(topic)`; tool-loop передаёт `call.arguments`(query) как topic.
3. Register-nudge находки/хеджа — мягкий промпт-nudge (grounded/hedge-заметка + манифест), семантические
   тесты (не по подстроке).
4. Реюз `InterimLineGenerator` (BOB-057) — контракт неизменен.

## Архитектура (где что менять)

- **application `progress_announcer.py`:** убрать зашитое; `GatewayProgressAnnouncer` ctor
  (`chat_id`/`gateway`/`line_generator`/`sender_name`; без `rng`/`phrases`); единый `_announce_live(topic)`
  (генератор → strip → пусто/сбой → тишина); `announce_verify(topic)` и `announce(name, query)` → оба через
  него.
- **application `tool_loop.py`:** `announce(call.name, call.arguments)` (передать query); try/except-обёртка
  (декоративность на шве) сохранена.
- **application `handle_message.py`:** оба per-turn анонсера (`_reply_with_tools`, `_send_verify_interim`)
  строятся с `line_generator`+`sender_name`; register-nudge grounded/hedge-заметки.
- **domain/infra `interim_line.py`:** контракт `generate(topic, sender_name)` неизменен; промпт при нужде
  чуть обобщить (поиск-по-запросу + сверка-факта).

## 🔴 Инварианты (НЕ нарушать)

- **US-2 ноль скриптованности:** ни одной зашитой фразы в коде; сбой/пусто → **тишина**, не шаблон.
- **Декоративность:** интерим никогда не блокирует поиск/не ломает ход (сбой → тишина, глотается).
- **US-3 голос Боба:** находка/хедж читаются как Боб, не «отчёт агента»; GUPPI-нотис по канону, но живой.
- **Латентность:** живой интерим — лёгкая Tier-0 (+1–2с, тонет в поиске).
- **Инвариант BOB-053:** честный хедж при реальном сбое цел (звучит живее, не робо).
- **Не трогаем:** BOB-057 verify-триггер (VolatilityJudge), BOB-053/055 стриминг/механизм поиска.
- **DDD:** application-центрично; seeded-RNG больше не нужен в анонсере; композиция как есть.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; DDD/Clean; `ruff`, `mypy --strict`; TDD, покрытие ≥80% (`mypy src tests`).
- Без `print`/`breakpoint`, bare `except` (кроме осознанной декоративной обёртки с логом), `import *`,
  mutable-default. Русские литералы → per-file-ignore RUF001/002/003. Реплики/интерим — русский, голос Боба.

## Реюз / прецеденты

- `InterimLineGenerator`/`LlmInterimLineGenerator` (BOB-057, `interim_line.py`) — живой генератор, реюз.
- `GatewayProgressAnnouncer.announce_verify`/`_live_verify_line` (BOB-057) — база; убрать seeded-fallback.
- `_safe_addon`/декоративность (BOB-050); `_send_verify_interim`/`_reply_with_tools` (handle_message) —
  точки провязки; grounded/hedge-заметка (BOB-057) — register-nudge.

## Связи

BOB-055 (зашитый интерим — вырезаем) · BOB-057 (живой интерим — распространяем) · BOB-053 (честный хедж) ·
BOB-050 (декоративность) · север `bob-personality-simulation-philosophy` (не программно) · `bob-telegram-
pivot` (канон GUPPI/Боб) · перед BOB-061 (анти-тик).
