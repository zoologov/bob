<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-059 — «Устойчивый старт при флапе сети»

> **Created:** 2026-07-01
> **Parent:** `bob-49u` · ветка `features/BOB-059`

---

## Текущий фокус
Wave 1 — dev `.1` (retry get_me + грациозная деградация на TelegramNetworkError).

## Беады
| Беад | Роль | Статус |
|------|------|--------|
| `bob-49u.1` | dev: retry + деградация | ⏳ in_progress |
| `bob-49u.2` | test | ○ blocked (.1) |
| `bob-49u.3` | review | ○ blocked (.2) |
| `bob-49u.4` | tech-writer + Gate | ○ blocked (.3) |

## Заметки
- Причина: except в resolve_bot_identities не ловит TelegramNetworkError → блип на старте роняет запуск.
- Фикс совпадает с заложенным замыслом «не блокировать старт».
