<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-024 — «Краткость по запросу»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-024 · родитель `bob-09y`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (домен) | `domain/personality/brevity.py`: `AnswerDemand {LOW/MEDIUM/HIGH}` + чистая `classify_answer_demand(text)` (лексическая эвристика рус+eng); `Verbosity {TERSE/NORMAL/EXPANSIVE}` + чистая `decide_verbosity(demand, interest, mood_valence, engagement, form_hint, roll, thresholds)` (демэнд-база; интерес↑ редко/seeded; настроение/аппетит↓; анти-обрубок HIGH-demand owner ≥NORMAL); `BrevityThresholds`. Юнит-тесты на все ветки. | — |
| `.2` | **dev** (байес + интеграция) | `voice.brevity_directive(verbosity)` (сильная директива) + `voice.brevity_few_shot(verbosity)` (примеры «простой→короткий», как anti-bait few-shot); в `handle_message` после addressivity/ENGAGE вычислить demand+verbosity (из уже считаемых mood/interest/engagement/form_hint) и подмешать в `_system_prompt_for` (заменить мягкий form_hint-путь); опц. **страж длины** (demand LOW + длинно → лёгкое ужатие, выкл по умолчанию). Конфиг `brevity.*` в `DEFAULT_CONFIG`/loader + провязка в `app.py`. | `.1` |
| `.3` | **test** | ≥80% + US-1..5 + guardrails (простой→TERSE+few-shot; открытый→EXPANSIVE; настроение/аппетит↓ но HIGH-demand owner ≥NORMAL; интерес↑ редко; анти-обрубок owner) + регрессии (BOB-018/014.2a/020/023 целы; SILENT/гость-инвариант не затронуты). Через `.venv/bin/pytest`. | `.1,.2` |
| `.4` | **review** | Не рубит развёрнутый ответ; few-shot не ломает тон/язык; одна финальная директива длины (нет двойных с form_hint); анти-обрубок owner; SILENT/гость целы; без регрессий. Read-only. | `.3` |
| `.5` | **tech-writer** | `docs/architecture.md` (рус): answer-demand, verbosity, директива+few-shot, опц. страж, место в потоке хода (после BOB-023). Gate. | `.4` |

## Волны (последовательно на одной ветке)

```
.1 (домен) → .2 (байес+интеграция) → .3 test → .4 review → .5 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-024`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит), один прогон за раз. Гейт каждой волны проверяет
  КООРДИНАТОР через `.venv/bin/*`.

## Критерии готовности

- [ ] Простой/закрытый вопрос → короткий ответ (TERSE-директива + few-shot); открытый/глубокий →
      развёрнутый; настроение/аппетит урезают; интерес изредка разворачивает; анти-обрубок owner.
- [ ] Длина коррелирует с answer-demand x интерес x настроение; короткие ответы не обрублены.
- [ ] BOB-018/014.2a/020/023, память/проактив/тиринг не сломаны; SILENT/гость-инвариант целы;
      cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
