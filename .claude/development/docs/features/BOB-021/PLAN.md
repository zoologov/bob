<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-021 — «Консолидация памяти» (BOB-011 Ф2 · T1.3)

> **Status:** Approved
> **Created:** 2026-06-22
> **Feature:** BOB-021 (Тир 1 / T1.3)

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (дайджесты) | Миграция `episodic_log.consolidated` + дайджест-тип (`event_type='digest'`, эмбеддится) + `ConsolidateMemory` (тик, Tier-0 суммаризация старых не-consolidated пачкой → дайджест + пометить источники; не деструктивно, идемпотентно) + врезка в reflect-тик. Тесты на фейках. | — |
| `.2` | **dev** (дедуп фактов) | Миграция `semantic_memory.superseded_by` + `DedupFacts` (тик, near-duplicate по косинусу эмбеддингов, консервативный порог, канонич.=новейший/полнейший, остальные superseded + provenance; несхожие не сливать; идемпотентно) + recall исключает superseded. | `.1` |
| `.3` | **dev** (всплытие старого) | `surface_old` опт-ин в `HybridMemoryRecall` (дефолт recall не меняется → drop-in) + использование через колбэк-шов BOB-018 (редко, grounded). | `.1` |
| `.4` | **test** | ≥80% + US-1..3 + guardrails (не деструктивно, идемпотентность, дедуп без ложных слияний, drop-in recall) + локальность (фейки) + регрессии (recall Ф1/выражение/эмоции/проактив). | `.1,.2,.3` |
| `.5` | **review** (+приватность) | DDD-чистота, не деструктивно, идемпотентность, дедуп консервативен, drop-in контракт цел, ноль сети с контентом памяти. Read-only. | `.4` |
| `.6` | **tech-writer** | `architecture.md` (рус): схема (consolidated/digest/superseded), ConsolidateMemory, DedupFacts, surface_old, конфиг `memory.*`. Gate. | `.5` |

## Волны (последовательно на одной ветке)

```
.1 (дайджесты+схема) → .2 (дедуп) → .3 (всплытие) → .4 test → .5 review → .6 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-021`, один PR.

## Критерии готовности

- [ ] 3 механизма работают локально/приватно, не деструктивно, идемпотентно, под guardrails.
- [ ] `MemoryRecall` drop-in; дайджесты ищутся наравне; дедуп без ложных слияний.
- [ ] Реактив/проактив/recall Ф1/выражение/эмоции/тиринг/authz не сломаны.
- [ ] cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
