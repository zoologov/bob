<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-060 — «Голос Боба при поиске»

> **Created:** 2026-07-01
> **Parent:** `bob-68s` · ветка `features/BOB-060`

---

## Текущий фокус
Wave 1 — dev `.1` (вырезать зашитое + унификация на живой генератор).

## Беады
| Беад | Роль | Статус |
|------|------|--------|
| `bob-68s.1` | dev: вырезать зашитое + унификация | ⏳ in_progress |
| `bob-68s.2` | dev: register-nudge голос находки/хеджа | ○ blocked (.1) |
| `bob-68s.3` | test: ноль скриптованности + живые пути | ○ blocked (.1,.2) |
| `bob-68s.4` | review | ○ blocked (.3) |
| `bob-68s.5` | tech-writer + Gate | ○ blocked (.4) |

## Заметки
- Решение owner: зашитые WEB_SEARCH_PROGRESS_PHRASES убрать ПОЛНОСТЬЮ; сбой→тишина, не шаблон.
- Реюз InterimLineGenerator (BOB-057); унифицировать tool-loop + verify пути.
