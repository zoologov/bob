<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-028 — «T2.2 Self-Improvement»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-028 · родитель `bob-7xn`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (модель правила + persist) | `domain/personality/self_improvement.py`: `Lever` (жёсткий allowlist TONE/LENGTH/PROACTIVITY/ADDRESSIVITY_BIAS/HUMOR — и ТОЛЬКО), `RuleState`-машина (PROPOSED→APPROVED→PAUSED↔→REMOVED; PROPOSED→REJECTED; в APPROVED только через owner-апрув на уровне use-case), `ImprovementRule` (frozen: id/observation/adjustment/lever/magnitude/state/origin/created_at/evidence), чистые `active_rules`/`can_transition`/`clamp_magnitude`. Порт `SelfImprovementStore` + `SqliteSelfImprovementStore` (таблица improvement_rule). Юнит-тесты на машину + active_rules + клампы. | — |
| `.2` | **dev** (детектор паттернов) | Порт `PatternDetector.detect(signals)->правила` + impl через ToolCalling/LLM (строгий JSON, выбор рычага из `Lever`); `ImprovementSignals` (самоповторы/исходы адресности/verbosity-промахи/дельты отношений/застревание настроения из mood_history/поправки owner'а/что зашло); `detect_patterns` use-case из ReflectTick-seam (опц. Protocol, unwired→как раньше): собрать сигналы → detect → дедуп против существующих (lever+близость observation) → сохранить PROPOSED. Фейк-детектор. Без применения. | `.1` |
| `.3` | **dev** (апрув-флоу + мягкое применение) | Боб проговаривает свежее правило owner'у (реюз проактивного канала / при случае); owner-команды GUPPI `/rules`, `/rule approve\|reject\|pause\|resume\|remove <id>` (owner-only, как /goals). Мягкое применение: `active_rules`→модуляторы по рычагу в свою точку (voice-директива тон/юмор; verbosity-байес BOB-024; urge-байес BOB-010; адресность-байес BOB-023/025) — наклон, не перехват, читает ТОЛЬКО allowlist, magnitude клампится. Конфиг `self_improvement.{enabled OFF, detect_cadence, max_magnitude, max_active_rules, detector_tier}`. Провязка в app.py. | `.1,.2` |
| `.4` | **test** | ≥80% + US-1..6 + guardrails (детектор только PROPOSED; в APPROVED только owner; `Lever` не содержит authz/гостя/SOUL/safety и применение читает только allowlist — граница по конструкции; magnitude клампится, наклон не перехват; max_active_rules; pause/remove обратимы; гость не управляет; OFF по умолчанию→как до BOB-028) + регрессии (Тир 1/эстетическая эволюция/governance/BOB-015/authz целы). Через `.venv/bin/pytest`. | `.1,.2,.3` |
| `.5` | **review** | Граница безопасности по конструкции (нет рычага для authz/гостя/SOUL/safety; defense-in-depth домен+применение); authz-before-autonomy (без апрува ничего не применяется); ограниченность/обратимость; owner-only команды; чистота DDD/детерминизм; без регрессий. Read-only. | `.4` |
| `.6` | **tech-writer** | `docs/architecture.md` (рус): метакогнитивный слой — модель правила/рычаги, детектор, апрув-флоу, мягкое применение, границы безопасности, место в ReflectTick/рантайме. Gate. | `.5` |

## Волны (последовательно на одной ветке)

```
.1 модель+persist → .2 детектор → .3 апрув-флоу+применение → .4 test → .5 review → .6 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-028`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит), один прогон за раз. Гейт каждой волны — КООРДИНАТОР
  через `.venv/bin/*`.

## Критерии готовности

- [ ] Боб замечает поведенческие паттерны за собой, формулирует человечно, **предлагает** owner;
      по апруву правило **мягко модулирует** поведение (тон/длина/проактивность/адресность/юмор).
- [ ] **Безопасность по конструкции:** правило не представит и не тронет authz/гостя/SOUL/safety
      (нет рычага); без owner-апрува ничего не применяется; magnitude клампится; OFF по умолчанию.
- [ ] Owner-контроль (`/rules` list/approve/reject/pause/resume/remove) работает; гость не управляет;
      всё обратимо/прозрачно.
- [ ] Тир 1/эстетическая эволюция/governance/BOB-015/authz/гость-инвариант не сломаны; cov ≥80%;
      `ruff`/`mypy --strict`/`beadloom ci` зелёные.
