<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-001 — Личность Боба в Telegram

> **Last updated:** 2026-06-18
> **Phase:** Development
> **Epic:** bob-d1p

---

## Текущий беад

**Беад:** — (между беадами; W2 в работе параллельно)

## Прогресс

- [x] BEAD-01 (bob-d1p.1) — DONE: DDD-скелет src/bob/{domain,application,infrastructure}+app.py.
      ports.py (5 Protocol-портов), AsyncEventBus, AgentRuntime (lifecycle), ConfigLoader
      (defaults→YAML→env), app.py (composition root + стабы портов). 42 теста, ruff/mypy зелёные, cov 91%.
      Граф/доки beadloom отложены на BEAD-10.
- [x] BEAD-03 (bob-d1p.3) — DONE: LLM-слой + router. `OpenAICompatProvider` (aiohttp, non-stream JSON +
      SSE-стриминг, optional Bearer) реализует порт `LLMProvider`; `build_tier_providers(config)`→{0,1}
      (Tier0 локально без ключа, Tier1 = ключ из конфига/env). `LLMRouter`: `TaskType`→Tier
      (REPLY_TO_USER/GENESIS→Tier1, SENTIMENT/INNER_MONOLOGUE/REFLECT→Tier0), **редакция** personal_context
      перед Tier1, fallback Tier1→Tier0. Приватность протестирована (captured fake: сырьё не уходит в Tier1).
      15 новых тестов (in-process aiohttp loopback, без сети). ruff/mypy --strict (src+tests)/100 тестов зелёные.

## Статусы беадов

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-d1p.1 | dev: GUPPI core | — | open (ready) |
| bob-d1p.2 | dev: Persistence (SQLite+FTS5+SoulStore) | .1 | blocked |
| bob-d1p.3 | dev: LLM layer + router + редакция | .1 | blocked |
| bob-d1p.4 | dev: Telegram Gateway | .1 | blocked |
| bob-d1p.5 | dev: Higher Mind domain | .3 | blocked |
| bob-d1p.6 | dev: bob-soul + Genesis | .2, .3, .5 | blocked |
| bob-d1p.7 | dev: HandleMessage e2e + ticks | .2, .3, .4, .5, .6 | blocked |
| bob-d1p.8 | test: покрытие ≥80% | .7 | blocked |
| bob-d1p.9 | review | .8 | blocked |
| bob-d1p.10 | tech-writer: доки + узлы | .9 | blocked |

**Волны:** W1 {.1} → W2 {.2, .3, .4} ∥ → W3 {.5} → W4 {.6} → W5 {.7} → .8 → .9 → .10.

## Заметки

- Решения зафиксированы в CONTEXT.md (Q2: ответ = Tier1+редакция/fallback Tier0; Q3: long-polling).
- Доки на русском (project-override §3). Шаблоны адаптировать под Бобов стек (Python 3.12+, DDD).
- Старт разработки — через `/coordinator` (волнами, гейты по зависимостям беадов).
