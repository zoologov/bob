<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-026 — «Повторения»

> **Last updated:** 2026-06-24
> **Phase:** Development (автономный прогон до PR-merge + перезапуска Боба)
> **Feature:** bob-629 · branch `features/BOB-026`

---

## Текущий беад

**Беад:** `bob-629.5` — tech-writer (следующий).

## Прогресс

- [x] `.1` окно анти-повтора ответа — зелёный (1531 passed; кейс пользователя чинится)
- [x] `.2` reflect-тик грундинг + дедуп — зелёный (1542 passed; (C) двойной записи НЕТ)
- [x] `.3` test — зелёный (1559 passed; ~100% изменённого кода)
- [x] `.4` review — **APPROVE** без блокеров (минор: дедуп-окно укреплено over-fetch ×6 координатором)
- [ ] `.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-629.1 | dev окно анти-повтора | — | done |
| bob-629.2 | dev reflect грундинг+дедуп | .1 | done |
| bob-629.3 | test | .1,.2 | done |
| bob-629.4 | review | .3 | done |
| bob-629.5 | tech-writer | .4 | in_progress |
| bob-629.3 | test | .1,.2 | blocked |
| bob-629.4 | review | .3 | blocked |
| bob-629.5 | tech-writer | .4 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба.
- Корень (A): `_guard_against_verbatim_repeat` (handle_message.py:1381) сравнивает только с
  `_last_bob_reply` → повтор «через ход» проскальзывает (user-пример). Фикс — окно последних N.
- Корень (B): анти-повтор не покрывает reflect-тик; генерик-промпт + низкая темп → 740 рефлексий,
  565 уникальных.
- После BOB-026 — вернуться к **BOB-025** (ветка `features/BOB-025`, PRD+RFC уже на ней).
- Гейт каждой волны проверяет КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; при обрыве — инлайн).
