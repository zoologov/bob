<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-013 — Глубина личности

> **Status:** Approved
> **Created:** 2026-06-21
> **Epic:** bob-m6d

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

Эпик `bob-m6d` уже существует с двумя dev-фичами; добивает test/review/tech-writer.

| Беад | Роль | Описание | Зависит от |
|------|------|----------|-----------|
| `bob-m6d.1` | **dev** (Ф1) | Negotiation-врезка: `TasteEngine.conviction_for` + порт `ZoneClassifier` (дефолт-эвристика) + `decide()` в `handle_message._decide` + `Stance`→директива в `_SYSTEM_PROMPT`. Тесты на фейках. | — |
| `bob-m6d.2` | **dev** (Ф2) | Само-эволюция: `domain/personality/taste_evolution.py` (`reinforce`, затухание) + `SOUL.with_taste/with_baseline` (+`experience_count++`) + use-case `ApplyReflection` + врезка в `ReflectTick` + персист. Guardrails + тесты (границы/анти-runaway/идемпотентность). | — |
| `bob-m6d.3` | **test** | Покрытие обеих фаз ≥80%; приёмка US-1..US-3; интеграция (стойка в промпте; эволюция персистится; двойной тик идемпотентен); регрессии (реактив/проактив/память не сломаны). | .1, .2 |
| `bob-m6d.4` | **review** | Корректность + DDD-границы + guardrails реально жёсткие + Negotiation не делает грубым + приватность/тиринг целы. Read-only. | .3 |
| `bob-m6d.5` | **tech-writer** | `architecture.md` (рус): Negotiation-врезка, `ZoneClassifier`, `taste_evolution`, `ApplyReflection`, эволюция SOUL. Gate зелёный. | .4 |

## Волны

```
W1 {bob-m6d.1 Ф1 Negotiation}  ∥  W2 {bob-m6d.2 Ф2 Само-эволюция}
        → bob-m6d.3 (test) → bob-m6d.4 (review) → bob-m6d.5 (tech-writer)
```

- **Ф1 и Ф2 параллельны** (минимальный overlap: Ф1 — `handle_message`/`taste`/`negotiation`; Ф2 —
  `taste_evolution`(new)/`soul`/`heartbeat`/новый use-case). Merge-slot сериализует коммиты.
- Затем общий test → review → tech-writer.
- Одна ветка `features/BOB-013`, один PR (#13) в main.

## Критерии готовности эпика

- [ ] Negotiation влияет на ответ (стойка в промпте); Taste/baseline эволюционируют и персистятся.
- [ ] Guardrails само-эволюции проверены (границы, анти-runaway, идемпотентность).
- [ ] Реактив/проактив/память/тиринг/authz не сломаны; cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
