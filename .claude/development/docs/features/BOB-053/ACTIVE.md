<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-053 — «Веб-поиск» (`web_search`)

> **Created:** 2026-07-01
> **Parent:** `bob-l90` · ветка `features/BOB-053`

---

## Текущий фокус

Wave 1 — dev `.1` (провайдер Qwen-native + порт + 🔴 verify живым вызовом).

## Беады

| Беад | Роль | Статус |
|------|------|--------|
| `bob-l90.1` | dev: провайдер + порт (+verify) | ⏳ in_progress |
| `bob-l90.2` | dev: навык web_search + регистрация | ○ blocked (.1) |
| `bob-l90.3` | dev: отказоустойчивость + синтез | ○ blocked (.2) |
| `bob-l90.4` | test | ○ blocked (.1–.3) |
| `bob-l90.5` | review | ○ blocked (.4) |
| `bob-l90.6` | tech-writer + Gate | ○ blocked (.5) |

## Прогресс

- 2026-07-01: PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; координатор запущен (dev `.1`).

## Решения/заметки

- Провайдер: Qwen MaaS нативно (qwen3.7-plus, enable_search+enable_source) — источники есть.
- 🔴 verify нативного эндпоинта/токена в `.1` перед реализацией.
- web_research (многошаг) — ВНЕ объёма, ROADMAP T2.3.
