<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-015 — «Автономность: Goal Engine + Planner + самонаправленность»

> **Last updated:** 2026-06-24
> **Phase:** Development (автономный прогон до PR-merge + перезапуска Боба)
> **Feature:** bob-xnz · branch `features/BOB-015`

---

## Текущий беад

**Беад:** `bob-xnz.2` — dev: Planner + двойной апрув + контроль owner (следующий).

## Прогресс

- [x] `.1` Goal Engine + persist — зелёный (1424 passed; машина переходов + граф + SqliteGoalStore; authz/стадия-C закодированы в домене)
- [ ] `.2` Planner + двойной апрув + контроль owner
- [ ] `.3` самонаправленный тик PursueGoalsTick
- [ ] `.4` test · `.5` review · `.6` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-xnz.1 | dev Goal Engine | — | done |
| bob-xnz.2 | dev Planner+контроль | .1 | in_progress |
| bob-xnz.3 | dev самонаправленный тик | .1,.2 | blocked |
| bob-xnz.4 | test | .1,.2,.3 | blocked |
| bob-xnz.5 | review | .4 | blocked |
| bob-xnz.6 | tech-writer | .5 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба (утверждён owner'ом).
- **🔴 Safety-ядро (под тестами .4, ревью .5):** authz-before-autonomy (тик только APPROVED/ACTIVE),
  граница стадии C (`needs_external_agency` никогда не авто; safe-allowlist), kill-switch, governance,
  гость-инвариант. Реюз proactivity-governance + capability-шов.
- Гейт каждой волны проверяет КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; при обрыве агента —
  инлайн). Источник: PRD/RFC/CONTEXT.
