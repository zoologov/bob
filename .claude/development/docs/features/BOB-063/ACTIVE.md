<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-063 — «Гигиена репозитория» (Фаза 1)

> **Created:** 2026-07-02
> **Parent:** `bob-x9c` · ветка `chore/BOB-063-hygiene`

---

## Фокус
dev `.1` (чистка) → review `.2`.

## Беады
| Беад | Роль | Статус |
|------|------|--------|
| `bob-x9c.1` | dev: rm/mv/gitignore + прун | ⏳ in_progress |
| `bob-x9c.2` | review: ничего важного не снесли | ○ blocked (.1) |

## Решения
- archive-бинарники (tar.gz+2 PNG) — УБРАТЬ (owner подтвердил, история в git).
- .DS_Store — no-op (уже gitignored). data/*.bak — локальный прун.
