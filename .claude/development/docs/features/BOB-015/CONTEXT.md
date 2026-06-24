<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-015 — «Автономность: Goal Engine + Planner + самонаправленность»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-015 (Тир 2, автономность-стадия B) · эпик `bob-xnz`

---

## Состояние

Тир 1 закрыт (личность в диалоге). Боб реактивен + проактивен в чате (стадия A: heartbeat +
governance), но **без своих целей**. Этот эпик даёт автономность-стадию B: Goal Engine + Planner +
самонаправленное исполнение **утверждённых** целей под governance, со строгими guardrails
(authz-before-autonomy; без внешней агентности стадии C). PRD/RFC утверждены (двойной апрув:
цель + план). Ветка `features/BOB-015` от main `a3980ec`.

## Ключевые решения (из RFC)

- **Goal Engine** — чистый домен `domain/goals/`: `Goal`/`Task`/`GoalState`-машина/`GoalGraph` +
  чистые `ready_tasks`/`next_safe_task`/`is_goal_complete`; персист `SqliteGoalStore` (порт `GoalStore`).
- **Planner** — порт `Planner.decompose(goal)→задачи` (LLM/ToolCalling), классифицирует
  `needs_external_agency`; `plan_goal` use-case + двойной апрув.
- **Самонаправленный тик** `PursueGoalsTick` — через **ту же** `Governance`/`ProactiveDecider`
  (BOB-010) + kill-switch; только APPROVED/ACTIVE цели; только **safe-allowlist** capability;
  внешне-агентная задача → предложение (не авто). Прозрачность: эпизод + прогресс owner.
- **Контроль owner** — GUPPI-команды (`/goals`, approve/plan-approve/pause/resume/cancel, `/goals
  stop` kill-switch) + естественный язык; только owner. Боб может **предложить** цель (PROPOSED).
- **Граница стадии C** не пересекается; гость-инвариант BOB-019 цел.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5, Ollama (Qwen), Telegram (aiogram). DDD/Clean: граф целей и
  решения — чистый домен (без I/O, детерминированно, стохастика seeded) ← application ←
  infrastructure; персист/LLM/исполнение за портами; композиция в `app.py`; инъекция Clock/RNG/портов.
- **ТЕСТЫ через `.venv/bin/pytest -p no:cacheprovider`** (NOT `uv run` — висит), `pkill -9 -f pytest`
  перед, один прогон за раз. cov >=80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы
  — рус, без символа `x`-кириллицы в формулах (латиница).

## Зависимости и границы

- **Реюз:** `domain/proactivity/` (`Governance`/`ProactiveDecider`/`ProactivityStore`), heartbeat-тики
  + `runtime/{heartbeat,agent}` (образец `ReflectTick`), capability-шов (`Capability`/`CapabilityRegistry`/
  `ToolLoop`/`ToolCallingProvider`), persistence-паттерн `XxxStore`, личность Тир 1 (Боб преследует
  цели «как характер»).
- **Вне BOB-015:** внешняя агентность (код/Claude Code/инструменты/ФС/внешние API — стадия C, Тир 3);
  Self-Improvement правилами (вторая половина T2.2, отложена); permission-tiers / зрелость
  capability-машинерии (T2.3).
