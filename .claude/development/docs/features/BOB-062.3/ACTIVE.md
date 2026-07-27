<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.3 — «Срез proactivity → src/bob/proactivity/»

> **Status:** In Progress
> **Updated:** 2026-07-23
> **Branch:** `features/BOB-062.3` · **Родитель:** `bob-8r4.3` (эпик `bob-8r4`)

---

## Беады (последовательно)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.3.1` | dev — переезд proactivity (~25ф) | ✅ done (pytest 3270✓ mypy✓ ruff✓ reindex✓) |
| `bob-8r4.3.2` | dev — AaC правила + оценка генератора | ● blocked (.1) |
| `bob-8r4.3.3` | test — pytest + proactivity-инварианты | ● blocked (.1,.2) |
| `bob-8r4.3.4` | review — переезд + вердикт генератора | ● blocked (.3) |
| `bob-8r4.3.5` | tech-writer — SPEC/DOC + #13 + Gate | ● blocked (.4) |

Критпуть: `.1 → .2 → .3 → .4 → .5`.

## Решения по принадлежности (утв. owner)

1. `self_improvement.py` → **забираем** из personality (метакогниция; чистый лист) + 2 теста.
2. `run_genesis.py` → **вне** proactivity (genesis SOUL → .5/.6).
3. goals → единый `feature=proactivity` (подпапка `goals/`).
4. kernel (вариант C) — 4 стора через seam, schema остаётся.

## Заметки

- Крупнейший срез (~25 файлов). Blast radius: app.py, guppi, multibot, handle_message, re-export.
- Стыки помечаются: personality→self_improvement, guppi→домен, proactivity→memory.entities.
- 🔴 .2/.4 оценивают: не пора ли генератор правил границ (globs [adim]*→[adimp]*).

## Прогресс

- 2026-07-23: BRIEF Approved; роль-беады созданы; ветка `features/BOB-062.3`. Старт Волны 0.
- 2026-07-23: `.1` ГОТОВ. 25 файлов git mv → `src/bob/proactivity/` (ports/decision/governance/social_energy/state/urge/self_improvement + goals/ + usecases/ + adapters/). self_improvement забран из personality (tag personality→proactivity); goals единый feature=proactivity; 5 usecase tag usecases→proactivity. Внешние правки: app.py, domain/ports/__init__ (шим), persistence/__init__ (−4 стора), handle_message, guppi, multibot, conversation/voice (докстринги), pyproject (ruff per-file-ignores пути), 24 теста. Создан `proactivity/adapters/__init__.py` (фасад 4 сторов). Граф: узлы proactivity-domain+proactivity-app+goals → один `proactivity` (module-vertical, source src/bob/proactivity/). heartbeat.py НЕ тронут (2 докстринг-кросс-рефа оставлены осознанно). run_genesis/kernel НЕ тронуты. Всё зелёно (lint --strict 0 violations). Детали стыков → bd comment для .2.
