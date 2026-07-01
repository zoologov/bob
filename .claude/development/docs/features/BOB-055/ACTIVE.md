<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-055 — «Надёжный web_search: стриминг + реплика "ищу…"»

> **Created:** 2026-07-01
> **Parent:** `bob-b1u` · ветка `features/BOB-055`

---

## Текущий фокус

Wave 1 — dev `.1` (стриминг `QwenWebSearchProvider`).

## Беады

| Беад | Роль | Статус |
|------|------|--------|
| `bob-b1u.1` | dev: стриминг провайдера | ⏳ in_progress |
| `bob-b1u.2` | dev: реплика «ищу…» (ProgressAnnouncer + tool-loop) | ○ ready (независим) |
| `bob-b1u.3` | test: стриминг+анонс+инвариант | ○ blocked (.1,.2) |
| `bob-b1u.4` | review | ○ blocked (.3) |
| `bob-b1u.5` | tech-writer + Gate | ○ blocked (.4) |

## Прогресс

- 2026-07-01: PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; координатор запущен (dev `.1`).

## Решения/заметки

- Диагностика: не-стрим рвётся на ~31с (таймаут длинного ответа); стрим живёт 90–120с.
- Анонс декоративен; инвариант BOB-053 (честный нотис без выдумки) цел.
- dev `.1`/`.2` независимы (разные слои), но запускаем последовательно (гонки по ветке).
