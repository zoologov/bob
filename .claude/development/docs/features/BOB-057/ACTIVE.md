<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-057 — «Боб знает, чего не знает» (эпистемическая проверка)

> **Created:** 2026-07-01
> **Parent:** `bob-2mh` · ветка `features/BOB-057`

---

## Текущий фокус

Wave 1 — dev `.1` (судья волатильности, Tier-0).

## Беады

| Беад | Роль | Статус |
|------|------|--------|
| `bob-2mh.1` | dev: судья волатильности (Tier-0) | ⏳ in_progress |
| `bob-2mh.2` | dev: verify-шаг в reply-пути | ○ blocked (.1) |
| `bob-2mh.3` | dev: живая интерим-реплика (US-3b) | ○ blocked (.2) |
| `bob-2mh.4` | test | ○ blocked (.1–.3) |
| `bob-2mh.5` | review (🔴 authz + не-зануда) | ○ blocked (.4) |
| `bob-2mh.6` | tech-writer + Gate | ○ blocked (.5) |

## Прогресс

- 2026-07-01: PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; координатор запущен (dev `.1`).

## Решения/заметки

- v1 на Qwen web_search; Tavily (быстрый) — апгрейд латентности потом (ROADMAP).
- 🔴 Инварианты: не зануда (консервативный судья) · не 5 мин · не привилегия BOB-052 (прямой internal-verify) · честный хедж · декоративность.
- Живая адресная интерим-реплика (US-3b) — апгрейд анонсера BOB-055.
