<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-001 — Личность Боба в Telegram

> **Last updated:** 2026-06-18
> **Phase:** Development
> **Epic:** bob-d1p

---

## Текущий беад

**Беад:** bob-d1p.1 — dev: GUPPI core (runtime, EventBus, config, ports, app.py)
**Цель:** walking skeleton — процесс стартует/останавливается graceful, есть event loop, шина, конфиг,
порты-протоколы и composition root.
**Done when:** `AgentRuntime` (asyncio) + `EventBus` (pub/sub) + `ConfigLoader` (defaults→YAML→env) +
`domain/ports.py` + `app.py` (заглушки), тесты зелёные.

## Прогресс

- [x] BEAD-01 (bob-d1p.1) — DONE: DDD-скелет src/bob/{domain,application,infrastructure}+app.py.
      ports.py (5 Protocol-портов), AsyncEventBus, AgentRuntime (lifecycle), ConfigLoader
      (defaults→YAML→env), app.py (composition root + стабы портов). 42 теста, ruff/mypy зелёные, cov 91%.
      Граф/доки beadloom отложены на BEAD-10.

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
