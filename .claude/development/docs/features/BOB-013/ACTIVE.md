<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-013 — Глубина личности

> **Last updated:** 2026-06-21
> **Phase:** Development
> **Epic:** bob-m6d · branch `features/BOB-013`

---

## Текущий беад

**Беад:** `bob-m6d.1` — dev Ф1 Negotiation-врезка (в работе). Следом `bob-m6d.2` (dev Ф2 Само-эволюция).

## Прогресс

- [ ] W1: `bob-m6d.1` — Negotiation-врезка (conviction_for + ZoneClassifier + decide→директива)
- [ ] W2: `bob-m6d.2` — Само-эволюция (reinforce + with_taste + ApplyReflection + guardrails)
- [ ] `bob-m6d.3` test · `bob-m6d.4` review · `bob-m6d.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-m6d.1 | dev Ф1 Negotiation-врезка | — | in_progress |
| bob-m6d.2 | dev Ф2 Само-эволюция | — | ready |
| bob-m6d.3 | test | .1,.2 | blocked |
| bob-m6d.4 | review | .3 | blocked |
| bob-m6d.5 | tech-writer | .4 | blocked |

## Заметки

- Ведём dev-беады **последовательно** на одной ветке (фоновые агенты, общий рабочий tree).
- Guardrails само-эволюции — жёстко: границы [0,1]/[-1,1], затухание (1−conviction), идемпотентность.
- Источник дизайна: `.claude/dev-docs/PERSONALITY-DEPTH-AUDIT.md` + RFC.md.
