<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-055 — «Надёжный web_search: стриминг + реплика "ищу…"»

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Фикс BOB-053, две части за существующими швами: **(A)** `QwenWebSearchProvider` → стриминг Responses API
(`stream:true`, копить SSE до `response.completed`, переиспользовать текущий парсер) — обходит ~30с-таймаут,
поиск доживает; **(B)** реплика «ищу…»: tool-loop через `ProgressAnnouncer` (per-turn, chat-bound) шлёт
живую разную фразу в голосе Боба сразу перед долгим навыком. Декоративно; инвариант BOB-053 (честный нотис
без выдумки) цел.

## Ключевые решения (утв. в PRD/RFC)

1. **Стриминг парсинг:** копить SSE до `response.completed`, переиспользовать текущий парсер `output[]`. Тот
   же контракт `WebSearchResult`.
2. **Механизм анонса:** `ProgressAnnouncer` в tool-loop, решение по имени навыка (контракт `Capability` НЕ
   трогаем).
3. **Вариативность фразы:** ~5–8 живых вариантов + seeded-RNG (не Tier-0-генерация в v1).
4. **Декоративность:** сбой анонса тихо опускается; инвариант BOB-053 честного нотиса цел.
5. **Объём:** анонс только в обычном reply-пути (не `privileged_fulfiller`) в v1.

## Архитектура (где что лежит)

- **infrastructure:** `infrastructure/llm/web_search_qwen.py` — `QwenWebSearchProvider.search()` на
  стриминге (SSE-чтение построчно `response.content`, парс `data:` JSON, финал `response.completed` →
  текущий парсер `output[]`: `web_search_call.action.sources[].url` dedup + `message.content[].output_text`).
- **application:** `ProgressAnnouncer` порт (`announce(capability_name)`) + `GatewayProgressAnnouncer`
  (per-turn: chat_id + gateway `reply` + seeded-RNG + карта имя→фразы, пока `web_search`); `ToolLoop` +opt
  `announcer` (зов ПЕРЕД `registry.dispatch`); провязка в `HandleMessage` (per-turn сборка там, где строится
  `ToolLoop`, ~стр. 2763).
- **domain:** без изменений.

## 🔴 Инварианты (НЕ нарушать)

- **Инвариант BOB-053 цел:** реальный сбой поиска (даже со стримингом) → `call_with_retry` → честный нотис
  «не смог найти» БЕЗ конфабуляции. Стриминг убирает только ЛОЖНЫЕ нотисы (таймаут).
- **Анонс декоративен:** сбой `announce`/gateway → тихо опускается (`_safe_addon`-стиль), обычный ход/ответ
  не ломается и не блокируется.
- **Контракт `Capability` не трогаем:** решение об анонсе — по имени в анонсере; потребители (registry/
  tool-loop сигнатура `run`) не переписываются сверх +optional параметра.
- **Естественность (US-4):** фраза «ищу…» — живая и РАЗНАЯ (набор вариантов, seeded-выбор), в голосе Боба;
  не робо-«Loading…».
- **Тот же контракт `WebSearchResult`** — стриминг меняет только транспорт чтения, не результат.
- **DDD:** domain ← application ← infrastructure; композиция только в `app.py`; seeded-RNG инъектируется
  (детерминизм тестов).

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; **DDD + Clean Architecture** (`domain`/`application`/`infrastructure`).
- `ruff` (lint+format), `mypy --strict`; frozen+slots, StrEnum, без `Any`/`# type: ignore` без причины.
- TDD: тест прежде кода; pytest; покрытие модулей ≥ 80% (`mypy src tests`).
- Без `print`/`breakpoint`, без bare `except`, без `import *`, без mutable-default.
- Русские литералы в src/тестах → per-file-ignore RUF001/002/003 в `pyproject.toml`.
- Реплики Боба (фразы «ищу…») — на русском, в голосе Боба, живые и разные.
- Без новых зависимостей (aiohttp SSE читаем сами; stdlib).

## Реюз / прецеденты

- `web_search_qwen.py` — текущий не-стрим клиент + парсер `output[]` (переиспользовать парс).
- `render_diagram` / `_diagram_sink` (BOB-035) — прецедент out-of-band отправки из tool-loop (но там
  drain-after-loop; нам нужен eager-анонс перед dispatch).
- `_safe_addon` (BOB-050) — паттерн декоративного тихого опускания.
- `call_with_retry` (BOB-049) — essential-ретрай в capability (остаётся).
- seeded-RNG — уже инъектируется в проекте (детерминизм); переиспользовать шов.

## Связи

BOB-053 (`web_search`, фиксим) · BOB-002 (capability-шов/tool-loop) · BOB-049 (retry/честный нотис) ·
BOB-050 (`_safe_addon`) · BOB-035 (out-of-band из tool-loop) · BOB-054 (`read_url`, родственный) ·
ROADMAP #10 (полный Боб/нотис) · север `bob-personality-simulation-philosophy` (не выглядеть программно).
