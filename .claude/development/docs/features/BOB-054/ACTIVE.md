<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-054 — «Прочитать ссылку» (`read_url`)

> **Created:** 2026-07-01
> **Parent:** `bob-76p` · ветка `features/BOB-054`

---

## Текущий фокус

Wave 1 — dev `.1` (читатель страниц + порт `UrlReader` + 🔴 SSRF-guard).

## Беады

| Беад | Роль | Статус |
|------|------|--------|
| `bob-76p.1` | dev: читатель + порт + 🔴 SSRF | ⏳ in_progress |
| `bob-76p.2` | dev: навык read_url + регистрация | ○ blocked (.1) |
| `bob-76p.3` | test: + 🔴 SSRF-инварианты | ○ blocked (.1,.2) |
| `bob-76p.4` | review (акцент 🔴 SSRF) | ○ blocked (.3) |
| `bob-76p.5` | tech-writer + Gate | ○ blocked (.4) |

## Прогресс

- 2026-07-01: PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; координатор запущен (dev `.1`).

## Решения/заметки

- Близнец BOB-053 `web_search` — зеркалить структуру навыка/клиента.
- 🔴 SSRF — главный риск; stdlib `html.parser` (без новых зависимостей).
- X/твиты, JS-рендер, PDF — вне v1 (ROADMAP).
