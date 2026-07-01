<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-053 — «Веб-поиск» (`web_search`)

> **Status:** Approved
> **Created:** 2026-07-01
> **CONTEXT:** `./CONTEXT.md`

---

## Беады (DAG)

Родитель: **`bob-053`** [feature] — «[BOB-053] Веб-поиск (web_search)».

| Беад | Роль | Описание | Зависит от |
|------|------|----------|-----------|
| `.1` | dev | **Провайдер поиска (Qwen Responses API) + порт.** Domain: `WebSource`/`WebSearchResult` + порт `WebSearchProvider`. Infra: `QwenWebSearchProvider` (Responses API `/compatible-mode/v1/responses`, тот же ключ; `tools:[web_search]`; парсинг `output[]`: `web_search_call.action.sources[].url` + `message.content[].output_text`; raise-on-failure; таймаут с запасом) + сборка в `factory.py` + конфиг `search.*`. **✅ verify РАЗРЕШЁН** (источники на текущем ключе через Responses API). | — |
| `.2` | dev | **Навык `web_search` + регистрация.** `application/capabilities/web_search.py` (`make_web_search_capability(provider)` → `Capability`, `permission="safe"`, валидация `query` → делегирование → компактная проекция ответ+источники; честное «не нашёл» на пусто). Регистрация в `app.py`/`CapabilityRegistry`. | `.1` |
| `.3` | dev | **Отказоустойчивость + синтез.** Провязка essential-пути: сбой провайдера → ретрай → честный GUPPI-нотис/оговорка (без ответа-из-обучения под видом поиска); проекция способствует синтезу в голосе Боба, не сырому дампу. | `.2` |
| `.4` | test | **Тесты.** domain (значения/порт), навык (валидация, проекция, пусто→«не нашёл», 🔴 инвариант «нет конфабуляции при сбое»), провайдер (парсинг `search_info`, raise-on-failure; мок HTTP), регистрация. Покрытие ≥ 80%. | `.1`,`.2`,`.3` |
| `.5` | review | **Ревью (read-only).** Корректность, DDD-границы, безопасность (гейт по отправителю/BOB-052 цел, BOB-051 не ослаблен, нет конфабуляции, ключ не в коде), отказоустойчивость. Findings → bd-комменты. | `.4` |
| `.6` | tech-writer | **Доки.** `docs/architecture.md` (RU): навык `web_search`, порт `WebSearchProvider`, `QwenWebSearchProvider`, гейт authz, отказоустойчивость; связь BOB-002/052. Beadloom Gate зелёный. | `.5` |

## Волны (coordinator)

1. **Wave 1 (dev, последовательно):** `.1` → `.2` → `.3` (каждый на ветке `features/BOB-053`, коммит per-беад). `.1` первым из-за 🔴 verify.
2. **Wave 2 (test):** `.4` после всех dev.
3. **Wave 3 (review):** `.5` после `.4`.
4. **Wave 4 (tech-writer):** `.6` после `.5`.
5. Финал: закрыть `bob-053`, полный pytest, `beadloom ci`, PR → main, мерж, рестарт Боба, живая проверка.

## Критический путь

`.1 → .2 → .3 → .4 → .5 → .6` (линейный; dev последовательно, т.к. слои зависят).

## Критерии приёмки (из PRD)

- Запрос про свежее/внешнее → один веб-поиск → ответ своим голосом **с источниками** (title+url).
- Боб **сам** выбирает навык (tool-loop), не только по команде.
- Гейт authz: owner/allowlist — сразу; не-авторизованный → BOB-052.
- 🔴 Сбой/пусто → честный нотис/оговорка, без галлюцинации «найденного»; диалог не ломается.

## Риски

- ✅ ~~Эндпоинт/токен~~ — verify .1 разрешён: источники на текущем ключе через Responses API (новый ключ не нужен).
- Гипер-вызов навыка → точная `description`; тюнинг.
- Конфабуляция при сбое → тест-инвариант в `.4`.
