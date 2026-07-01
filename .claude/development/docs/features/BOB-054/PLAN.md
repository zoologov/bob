<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-054 — «Прочитать ссылку» (`read_url`)

> **Status:** Approved
> **Created:** 2026-07-01
> **CONTEXT:** `./CONTEXT.md`

---

## Беады (DAG)

Родитель: **`bob-054`** [feature] — «[BOB-054] Прочитать ссылку (read_url)».

| Беад | Роль | Описание | Зависит от |
|------|------|----------|-----------|
| `.1` | dev | **Читатель страниц + порт + 🔴 SSRF.** Domain: `WebPage` + порт `UrlReader`. Infra (новый пакет `infrastructure/web/`): `HttpUrlReader` (aiohttp GET; 🔴 SSRF-guard — только http/https, резолв→все IP публичные, ручные редиректы с ре-валидацией, лимиты timeout/max_bytes/content-type/max_redirects, фикс UA; извлечение текста stdlib `html.parser`; raise-on-failure) + factory + конфиг `read_url.*`. | — |
| `.2` | dev | **Навык `read_url` + регистрация.** `application/capabilities/read_url.py` (`make_read_url_capability(reader)` → `Capability`, `permission="safe"`, `{url}`, валидация → `call_with_retry` → компактная проекция; сбой→честный «не смог открыть» с анти-конфабуляцией). Регистрация в `app.py` `_build_registry` под `read_url.enabled`. Зеркалить `web_search.py`. | `.1` |
| `.3` | test | **Тесты.** domain; навык (валидация/проекция/сбой→честный-нотис/🔴 нет-конфабуляции); читатель (извлечение текста, content-type, лимиты, raise); **🔴 SSRF-инвариант на каждый класс: loopback/private/link-local(метаданные 169.254.169.254)/IPv6 ::1,fc00::,fe80::/не-http(s)/redirect-to-internal**. Мок DNS+HTTP, без сети. ≥ 80%. | `.1`,`.2` |
| `.4` | review | **Ревью (read-only) — акцент на 🔴 SSRF.** Полнота SSRF-guard (все классы адресов, ре-валидация редиректов, лимиты), нет конфабуляции, гейт по отправителю/BOB-052 цел, BOB-051 не ослаблен, DDD-границы, без новых зависимостей. Findings → bd-комменты. | `.3` |
| `.5` | tech-writer | **Доки.** `docs/architecture.md` (RU): навык `read_url`, порт `UrlReader`, `HttpUrlReader` + SSRF, гейт authz, отказоустойчивость; связь BOB-053/002/052. Beadloom Gate зелёный. | `.4` |

## Волны (coordinator)

1. **Wave 1 (dev, последовательно):** `.1` → `.2` (ветка `features/BOB-054`, коммит per-беад). `.1` первым (слои).
2. **Wave 2 (test):** `.3` после dev — акцент на 🔴 SSRF-инварианты.
3. **Wave 3 (review):** `.4` после `.3` — акцент на 🔴 SSRF.
4. **Wave 4 (tech-writer):** `.5` после `.4`.
5. Финал: закрыть `bob-054`, полный pytest, `beadloom ci`, PR → main, мерж, рестарт Боба, живая проверка
   (кинуть Бобу ссылку на статью → читает и комментирует; SSRF — заблокированный адрес → честный отказ).

## Критический путь

`.1 → .2 → .3 → .4 → .5` (линейный; dev последовательно, т.к. слои зависят).

## Критерии приёмки (из PRD)

- Присланный URL (обычная страница) → Боб читает и отвечает по существу своим голосом.
- Боб **сам** выбирает навык, когда в разговоре есть релевантная ссылка (tool-loop).
- Гейт authz: owner/allowlist — сразу; не-авторизованный → BOB-052.
- 🔴 Недоступно/не читается → честный отказ без выдумки содержимого; диалог не ломается.
- 🔴 SSRF: приватные/loopback/link-local/не-http(s)/redirect-to-internal — заблокированы.

## Риски

- 🔴 SSRF — главный; полнота guard + ре-валидация редиректов проверяется тест-инвариантами в `.3` и ревью `.4`.
- Конфабуляция при недоступности → тест-инвариант в `.3`.
- Гипер-вызов навыка → точная `description`; тюнинг.
- Качество извлечения (stdlib) → приемлемо; upgrade позже за портом.
