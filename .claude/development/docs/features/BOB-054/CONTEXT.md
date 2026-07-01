<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-054 — «Прочитать ссылку» (`read_url`)

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Навык `read_url` за capability-швом (BOB-002), близнец `web_search` (BOB-053): GUPPI/tool-loop сам выбирает
его на присланную ссылку → один вызов порта `UrlReader` (infra: `aiohttp` GET → 🔴 SSRF-guard → извлечь
читаемый текст+заголовок stdlib `html.parser`) → компактная проекция → Боб отвечает своим голосом по
содержимому. Гейт привилегии — по отправителю (authz/BOB-052). Сбой/блок/логин-волл → честный отказ без
выдумки содержимого.

## Ключевые решения (утв. в PRD/RFC)

1. **Извлечение текста:** stdlib `html.parser` (без новых зависимостей). Upgrade на readability-либу — позже
   за портом.
2. **🔴 SSRF-защита:** только http/https + резолв→все IP публичные (`ipaddress`) + ручные редиректы с
   ре-валидацией + лимиты (timeout/max_bytes/content-type/max_redirects). connect-by-IP — опция на будущее.
3. **Привилегия:** `permission="safe"` + гейт по отправителю (authz/BOB-052), без отдельного `confirm`.
4. **Сбой/блок:** essential → честный отказ БЕЗ выдумки содержимого; SSRF-блок не ретраим.
5. **Объём v1:** обычные HTML-страницы; X/твиты, JS-рендер, PDF — вне (ROADMAP).

## Архитектура (где что лежит)

- **domain:** `domain/ports.py` — `WebPage{url,title,text}` (frozen+slots) + порт `UrlReader`
  (`read(url)→WebPage`). Рядом с `WebSearchProvider`.
- **application:** `application/capabilities/read_url.py` — `make_read_url_capability(reader)` → `Capability`
  (`name="read_url"`, `permission="safe"`, `input_schema={url}`, валидация → `call_with_retry` →
  компактная проекция; честный-нотис на сбое). Зеркалит `web_search.py`. Регистрация в `app.py`
  `_build_registry` под `read_url.enabled`.
- **infrastructure:** новый пакет `infrastructure/web/` — `http_url_reader.py` (`HttpUrlReader`: aiohttp +
  SSRF-guard + извлечение), factory; конфиг `read_url.*`.

## 🔴 Инварианты (НЕ нарушать)

- **SSRF-защита (главное):** только http/https; все резолвнутые IP публичные (блок private/loopback/
  link-local/reserved/multicast/unspecified — режет `127.0.0.1`, `10/8`, `192.168`, `169.254.169.254`
  метаданные, IPv6 `::1`/`fc00::`/`fe80::`); редиректы вручную с ре-валидацией каждого хопа + лимит;
  max_bytes (потоковый обрыв), timeout, content-type allowlist (`text/html`/`text/plain`), фикс UA, без
  auth-заголовков. Тест-инвариант на каждый класс заблокированных адресов.
- **Нет конфабуляции содержимого:** сбой/недоступно/логин-волл/SSRF-блок → честный «не смог прочитать», Боб
  НЕ сочиняет, что на странице. BOB-051/052 не ослабляются.
- **Привилегия по отправителю:** навык только авторизованным (owner/allowlist); чужой → BOB-052.
  `permission="safe"`, но tool-loop для чужих не запускается.
- **Синтез, не дамп:** компактная проекция (url+title+excerpt), финал синтезирует модель в голосе Боба.
- **Шов не ломаем:** +1 capability за стабильным контрактом `Capability`; потребители (tool-loop/GUPPI/
  registry) не переписываются. Domain чист (без I/O); конфиг/лимиты — через factory/конфиг.
- **DDD:** domain ← application ← infrastructure; композиция только в `app.py`.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; **DDD + Clean Architecture** (`domain`/`application`/`infrastructure`).
- `ruff` (lint+format), `mypy --strict`; frozen+slots, StrEnum, без `Any`/`# type: ignore` без причины.
- TDD: тест прежде кода; pytest; покрытие модулей ≥ 80%.
- Без `print`/`breakpoint`, без bare `except`, без `import *`, без mutable-default.
- Русские литералы в src/тестах → per-file-ignore RUF001/002/003 в `pyproject.toml` (как в BOB-053).
- Сообщения Бобу/нотисы — на русском, в голосе Боба.
- **Без новых зависимостей** (stdlib `html.parser` + существующий `aiohttp`).

## Реюз из BOB-053 (близнец)

`web_search.py` — образец структуры навыка (`call_with_retry`, честный-нотис, компактная проекция,
инъектируемый sleep); `web_search_qwen.py` — образец aiohttp-клиента (raise-on-failure); регистрация в
`app.py` `_build_registry` под флагом; конфиг-секция в `loader.py`. Зеркалить, не изобретать.

## Связи

BOB-053 (`web_search`, близнец) · BOB-002 (capability-шов) · BOB-019/051/052 (authz + разрешение) ·
BOB-049 (`call_with_retry`, синтез/нотис) · ROADMAP #10 (полный Боб/нотис) · фундамент `web_research` (T2.3).
