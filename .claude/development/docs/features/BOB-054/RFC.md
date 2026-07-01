<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-054 — «Прочитать ссылку» (`read_url`)

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD:** `.claude/development/docs/features/BOB-054/PRD.md`
> **Решения (под утв.):** навык за capability-швом (зеркалит `web_search`) · читатель на `aiohttp` +
> извлечение текста **stdlib `html.parser`** (без новых зависимостей) · 🔴 SSRF-защита (только http/https,
> блок приватных/loopback/link-local, ре-валидация редиректов, лимиты) · `permission="safe"`, привилегия
> по отправителю (authz/BOB-052) · сбой/блок/логин-волл → честный отказ без выдумки.

---

## Идея решения

Новый навык **`read_url`** за существующим capability-швом (BOB-002), близнец `web_search` (BOB-053): GUPPI
через `ToolLoop` сам выбирает его, когда в разговоре появляется ссылка, которую надо прочитать. Навык
делает **один** вызов к порту `UrlReader` (infra: `aiohttp` GET → 🔴 SSRF-guard → извлечь читаемый текст +
заголовок) и возвращает компактную проекцию в tool-loop; финальную реплику Боб **синтезирует своим голосом
по содержимому**. Привилегия — по отправителю (owner/allowlist сразу; чужой → BOB-052). Реюз паттернов
`web_search`: структура навыка, `call_with_retry` (BOB-049), честный-нотис на сбое.

## Доменная модель (порт + значения)

В `domain/ports.py` (рядом с `WebSearchProvider`, тем же стилем frozen+slots / runtime_checkable):

```python
@frozen(slots=True)
class WebPage:
    url: str                 # финальный URL (после разрешённых редиректов)
    title: str               # заголовок страницы ("" если нет)
    text: str                # извлечённый читаемый текст (обрезан до лимита)

@runtime_checkable
class UrlReader(Protocol):
    async def read(self, url: str) -> WebPage: ...
```

Порт провайдер-агностичен: v1 — `HttpUrlReader`; завтра платный X-плагин/headless-рендер — за тем же
портом, без смены навыка.

## Навык (application capability)

`application/capabilities/read_url.py` — `make_read_url_capability(reader: UrlReader) -> Capability`
(зеркалит `web_search.py`):

- `name = "read_url"`.
- `description` — модели: «открыть и прочитать КОНКРЕТНУЮ веб-страницу по URL (статья/пост/док) и ответить
  по её содержимому; использовать, когда в разговоре есть ссылка, которую нужно прочитать». Отличать от
  `web_search` (тот ищет по теме, этот читает данный URL). Держать tight, чтобы не дёргался без ссылки.
- `input_schema` — `{ "url": {"type":"string"} }`, required `url`.
- `permission = "safe"` — read-only; 🔴 привилегия НЕ здесь: tool-loop только для авторизованного
  отправителя (authz/BOB-051/052).
- `execute(args)` — валидировать `url` (непустая строка); `call_with_retry(reader.read(url))`
  (essential-политика BOB-049, инъектируемый sleep); вернуть компактную проекцию `{url, title, excerpt}`
  (текст обрезан для синтеза, НЕ сырой дамп). 🔴 На сбое/блоке/пустом — как `web_search`: честный
  «не смог открыть/прочитать эту ссылку» нотис с анти-конфабуляцией (никогда — выдуманное содержимое).

Регистрация в `app.py` `_build_registry` под флагом `read_url.enabled` (зеркалит `search.enabled`;
default True, привилегия по отправителю).

## Читатель страниц (infrastructure) + 🔴 SSRF

`infrastructure/web/http_url_reader.py` — `HttpUrlReader` реализует `UrlReader` (на `aiohttp`, как
`web_search_qwen`). Порядок:

1. **Схема:** принять ТОЛЬКО `http`/`https`; иначе — raise (блок `file://`, `ftp://`, `gopher://`, и т.п.).
2. **🔴 SSRF-guard (до соединения):** резолвить хост → проверить, что ВСЕ разрешённые IP **публичные**
   (`ipaddress`: reject `is_private` / `is_loopback` / `is_link_local` / `is_reserved` / `is_multicast` /
   `is_unspecified`). Это режет `127.0.0.1`, `10/8`, `172.16/12`, `192.168/16`, `169.254.169.254`
   (облачные метаданные!), IPv6 `::1` / `fc00::/7` / `fe80::/10`. Если любой резолв — приватный → raise.
3. **Редиректы — вручную, с ре-валидацией:** `allow_redirects=False`; на каждый `3xx` `Location` повторить
   SSRF-guard для нового URL; лимит числа хопов (`read_url.max_redirects`). (Закрывает redirect-to-internal
   и снижает DNS-rebinding-окно.)
4. **Лимиты:** таймаут (`read_url.timeout_seconds`); Content-Type только `text/html`/`text/plain` (иначе —
   честный отказ, не тянем бинарь); **потоковое чтение с обрывом при превышении** `read_url.max_bytes`
   (защита от гигантских/бесконечных тел); фиксированный `User-Agent`; без auth-заголовков.
5. **Извлечение текста — stdlib `html.parser`** (без новых зависимостей): выкинуть `<script>/<style>/
   <head>/<noscript>`, собрать видимый текст, схлопнуть пробелы, вытащить `<title>`; обрезать до
   `read_url.max_chars` для подачи модели. (Не идеальная «readability», но достаточно — синтез делает
   модель; boilerplate она игнорирует.)

Сетевые/HTTP-ошибки, SSRF-блок, не тот Content-Type, пустой текст → **поднять исключение** (caller решает) —
паттерн `web_search_qwen` raise-on-failure. Сборка — `infrastructure/web/factory.py` (или существующий
factory-шов) из конфига `read_url.*`; в `app.py` прокидывается в `make_read_url_capability`.

## 🔴 Отказоустойчивость («полный Боб или честный GUPPI-нотис»)

`read_url` — **essential**, когда модель решила открыть ссылку (не декор). Сбой/недоступно/логин-волл (в т.ч.
X)/SSRF-блок → ограниченный ретрай (`call_with_retry`, только сетевые/временные; SSRF-блок ретраить
бессмысленно — сразу честный отказ) → **честный** «не смог открыть/прочитать эту ссылку» без выдумки
содержимого. 🔴 Боб НЕ сочиняет, что «написано» на недоступной странице. Сбой не ломает обычный диалог.

## Слои (DDD)

- **domain:** `WebPage`, порт `UrlReader` (чистые, без I/O).
- **application:** `read_url.py` (`make_read_url_capability`) — валидация + делегирование + компактная
  проекция + честный-нотис; регистрация; гейт по отправителю — существующий (authz/BOB-052).
- **infrastructure:** `HttpUrlReader` (aiohttp + SSRF-guard + извлечение), factory, конфиг `read_url.*`.
  Новый пакет `infrastructure/web/` (читатель — не LLM; отдельно от `infrastructure/llm/`).

## Риски и митигации

- **🔴 SSRF** (главный риск: мы сами ходим по присланному URL) → guard до соединения + ре-валидация
  редиректов + только http/https + блок приватных/loopback/link-local/метаданных; тест-инвариант на каждый
  класс адресов. DNS-rebinding-окно сужено ручными редиректами (полное закрытие — connect-by-resolved-IP —
  как опция, если понадобится; для личного инструмента v1 guard+revalidate достаточно).
- **Конфабуляция содержимого** при недоступности → essential честный-нотис; выдумка «что на странице»
  запрещена (тест-инвариант).
- **Гипер-вызов** (Боб читает где не надо) → точная `description` (только когда есть ссылка для чтения);
  tool-loop решает.
- **Огромные/злые тела / медленные хосты** → max_bytes (потоковый обрыв) + timeout + max_redirects +
  content-type allowlist.
- **Логин-воллы / JS-SPA / X** → v1 читает статичный HTML; на нечитаемом — честный отказ (не выдумка).
  X — вне объёма (платный плагин позже).
- **Качество извлечения** (stdlib грубее readability-либ) → приемлемо для синтеза; upgrade на
  trafilatura/readability — позже за тем же портом, если качество будет мешать.
- **Регрессии шва** → +1 capability за стабильным контрактом; потребители (tool-loop/GUPPI) не меняются.

## Открытые решения (под утверждение)

1. **Извлечение текста:** stdlib `html.parser` (без новых зависимостей) — **рекомендую** для v1; upgrade на
   readability-либу позже за портом при нужде.
2. **SSRF-защита:** guard (scheme + публичный IP) + ручные редиректы с ре-валидацией + лимиты — **рекомендую**
   (connect-by-IP против DNS-rebinding — опция на будущее, для личного инструмента избыточно в v1).
3. **Привилегия:** `permission="safe"` + гейт по отправителю (authz/BOB-052) — **рекомендую** (как
   `web_search`).
4. **Сбой/блок:** essential → честный отказ БЕЗ выдумки содержимого; SSRF-блок не ретраим — **рекомендую**.
5. **Объём v1:** обычные HTML-страницы; X/твиты, JS-рендер, PDF — вне (ROADMAP) — **рекомендую**.
