<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-013 — Глубина личности

> **Last updated:** 2026-06-21
> **Phase:** Done (все волны закрыты)
> **Epic:** bob-m6d · branch `features/BOB-013`

---

## Текущий беад

Все беады BOB-013 завершены. Ветка `features/BOB-013` готова к PR в `main`.

## Прогресс

- [x] W1: `bob-m6d.1` — Negotiation-врезка (conviction_for + ZoneClassifier + decide→директива)
- [x] W2: `bob-m6d.2` — Само-эволюция (reinforce + with_taste + ApplyReflection + guardrails)
- [x] `bob-m6d.3` test · `bob-m6d.4` review · `bob-m6d.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-m6d.1 | dev Ф1 Negotiation-врезка | — | done |
| bob-m6d.2 | dev Ф2 Само-эволюция | — | done |
| bob-m6d.3 | test | .1,.2 | done |
| bob-m6d.4 | review | .3 | done |
| bob-m6d.5 | tech-writer | .4 | done |

## Заметки

- Ведём dev-беады **последовательно** на одной ветке (фоновые агенты, общий рабочий tree).
- Guardrails само-эволюции — жёстко: границы [0,1]/[-1,1], затухание (1−conviction), идемпотентность.
- Источник дизайна: `.claude/dev-docs/PERSONALITY-DEPTH-AUDIT.md` + RFC.md.
- Tech-writer (`bob-m6d.5`): `docs/architecture.md` обновлён под BOB-013 — Negotiation-врезка
  (зона→стойка→директива, `ZoneClassifier`/`TasteZoneClassifier`), само-эволюция
  (`taste_evolution.reinforce` + guardrails, `ApplyReflection`/`HeuristicReflectionParser`,
  эволюция в `ReflectTick` + персист round-trip), иммутабельные `SOUL.with_taste/with_baseline`.
  `beadloom sync-check` зелёный (56/56 ok), `lint --strict` — 0 нарушений.
