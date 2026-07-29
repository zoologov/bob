<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-066 — между срезами

## Последний завершённый срез
**W.3-dev (bob-vol.12.3) — ЗАКРЫТ.** staleness врезка (`presence.staleness.enabled`) + catch-up
re-entry tick (`presence.catchup.enabled`), оба OFF=byte-identical. 🔴🔴 INV-1 reconcile:
`decide_staleness` проверяет new_direct_question ПЕРВЫМ → свежий прямой вопрос никогда не роняется
в лайк. NEW: presence/staleness_judgment.py + adapters/staleness_judge.py (TaskType.STALENESS_JUDGE
Tier-0); application/runtime/catch_up_reentry.py; runtime/wiring/{staleness,catchup}.py.
3875 тестов зелёные, cov 99%, mypy FULL 0, ruff 0, lint --strict EXIT 0 (починен runtime-app→usecases
цикл inline-проекцией). mutation: decide_staleness 1/1, is_reentry 6/6 (100%). architecture.md
doc-stale → tech-writer волна.

## Следующий фокус
**W.4-dev (bob-vol.12.4)** — EQ live-врезка (endorsement + tactful_withhold) — разблокирован.

## Инварианты-напоминание
INV-1 фокус минует любой потолок/бюджет (never dropped). Флаги OFF = byte-identical.
