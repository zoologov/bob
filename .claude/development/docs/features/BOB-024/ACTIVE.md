<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-024 — «Краткость по запросу»

> **Last updated:** 2026-06-24
> **Phase:** Development (автономный прогон до PR-merge + перезапуска Боба)
> **Feature:** bob-09y · branch `features/BOB-024`

---

## Текущий беад

**Беад:** `bob-09y.2` — dev: байес краткости + интеграция (следующий).

## Прогресс

- [x] `.1` домен brevity — зелёный (1333 passed; classify_answer_demand + decide_verbosity + BrevityThresholds)
- [ ] `.2` байес: voice.brevity_directive + few-shot + handle_message + опц. страж + конфиг
- [ ] `.3` test · `.4` review · `.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-09y.1 | dev домен | — | done |
| bob-09y.2 | dev байес+интеграция | .1 | in_progress |
| bob-09y.3 | test | .1,.2 | blocked |
| bob-09y.4 | review | .3 | blocked |
| bob-09y.5 | tech-writer | .4 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба (утверждён owner'ом, как BOB-023).
- Гейт каждой волны проверяет КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; песочница
  агентов нестабильна — при обрыве доводит инлайн).
- Связь: BOB-023 решает *отвечать ли*, BOB-024 — *насколько коротко*. Главный рычаг — few-shot
  (примеры бьют verbosity-prior Qwen). Источник: PRD/RFC/CONTEXT.
