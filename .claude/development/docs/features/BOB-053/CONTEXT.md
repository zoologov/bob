<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-053 — «Веб-поиск» (`web_search`)

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Навык `web_search` за существующим capability-швом (BOB-002): GUPPI/tool-loop сам выбирает его на запрос
про свежее/внешнее → один вызов Qwen MaaS (`qwen3.7-plus`, `enable_search`+`enable_source`, нативный
DashScope) → ответ + источники (title/url) → Боб синтезирует своим голосом со ссылками. Гейт привилегии —
по отправителю (authz/BOB-052), tool-loop не запускается для не-авторизованных. Сбой/пусто → честный
GUPPI-нотис/оговорка, без галлюцинации «найденного».

## Ключевые решения (утв. в PRD/RFC)

1. **Провайдер:** Qwen MaaS нативно (`qwen3.7-plus`, `enable_search`+`enable_source`) — тот же ключ,
   бесплатно, с источниками. Tavily — позже, за тем же портом.
2. **Привилегия:** `permission="safe"` + гейт по отправителю (authz/BOB-052), без отдельного `confirm`.
3. **Сбой/пусто:** essential → честный GUPPI-нотис/оговорка, БЕЗ ответа-из-обучения под видом поиска.
4. **Объём v1:** атомарный один проход; `web_research` (многошаг) — отдельно, ROADMAP T2.3.

## Архитектура (где что лежит)

- **domain:** `domain/ports.py` — `WebSource`/`WebSearchResult` (frozen+slots) + порт `WebSearchProvider`
  (`search(query)→WebSearchResult`).
- **application:** `application/capabilities/web_search.py` — `make_web_search_capability(provider)` →
  `Capability` (`name="web_search"`, `permission="safe"`, `input_schema={query}`, валидация → делегирование
  → компактная проекция); регистрация в `app.py`/`CapabilityRegistry`.
- **infrastructure:** `infrastructure/llm/web_search_qwen.py` — `QwenWebSearchProvider` (клиент
  **Responses API** `/compatible-mode/v1/responses`, тот же workspace-хост+ключ; `tools:[web_search]`;
  `httpx`; парсинг `output[]`: `web_search_call.action.sources[].url` + `message.content[].output_text`);
  сборка в `infrastructure/llm/factory.py`; конфиг `search.*`.

## 🔴 Инварианты (НЕ нарушать)

- **Привилегия по отправителю:** навык доступен только авторизованным (owner/allowlist); не-авторизованный
  → флоу разрешения owner (BOB-052). Навык `permission="safe"`, но tool-loop для чужих не запускается.
  BOB-051 (память публична) / BOB-052 (разрешение) не ослабляются.
- **Нет конфабуляции «найденного»:** при сбое/пустом результате Боб НЕ выдаёт ответ из обучения под видом
  поиска — честный GUPPI-нотис/оговорка/«не нашёл».
- **Синтез, не дамп:** навык отдаёт структурированную проекцию (ответ+источники), финальную реплику
  синтезирует модель в голосе Боба.
- **Шов не ломаем:** +1 capability за стабильным контрактом `Capability`; потребители (tool-loop/GUPPI/
  registry) не переписываются. Domain чист (без I/O); ключ/endpoint — через factory/конфиг, не хардкод.
- **DDD:** domain ← application ← infrastructure; композиция только в `app.py`.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; **DDD + Clean Architecture** (`domain`/`application`/`infrastructure`).
- `ruff` (lint+format), `mypy --strict`; frozen+slots, StrEnum, без `Any`/`# type: ignore` без причины.
- TDD: тест прежде кода; pytest; покрытие модулей ≥ 80%.
- Без `print`/`breakpoint`, без bare `except`, без `import *`, без mutable-default.
- Русские литералы в src/тестах → per-file-ignore RUF001/002/003 в `pyproject.toml` (как в BOB-052).
- Сообщения Бобу/нотисы — на русском, в голосе Боба.

## Verify (РАЗРЕШЁНО ✅, 2026-07-01)

Живые вызовы подтвердили: **источники доступны на текущем workspace-ключе через Responses API**
(`/compatible-mode/v1/responses` + `tools:[{type:web_search}]`, `qwen3.7-plus`). chat/completions и
legacy-native text-generation источников НЕ отдают (проверено). Глобальный/отдельный DashScope-ключ
**не нужен**. Источники = URL (`web_search_call.action.sources[].url`); title опционален. NB: поиск через
Responses API медленнее (несколько сек) → таймаут с запасом. HTTP2-обрывы при verify были из-за
нестабильного интернета, не эндпоинта.

## Связи

BOB-002 (capability-шов) · BOB-019/051/052 (authz + разрешение) · BOB-049 (синтез/нотис) · ROADMAP #10
(полный Боб/нотис) · фундамент `web_research` (T2.3).
