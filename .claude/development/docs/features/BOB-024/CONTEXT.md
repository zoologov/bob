<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-024 — «Краткость по запросу»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-024 (капстоун человечности: осмысленная длина ответа)

---

## Состояние

Боб различает адресность (BOB-023), имеет аппетит/интерес (.2a), настроение/off-days (BOB-020),
мягкий `FormHint` длины (BOB-018) — но **всегда многословит**: мягкий хинт не перебивает
verbosity-prior Qwen, и нет сигнала «сколько требует сам вопрос». PRD/RFC утверждены. Ветка
`features/BOB-024` от main `5cfb737` (BOB-023 смержен, Боб перезапущен).

## Ключевые решения (из RFC)

- **answer-demand** (чистый домен `brevity.py`): `AnswerDemand {LOW/MEDIUM/HIGH}` лексической
  эвристикой над текстом.
- **verbosity** (чистый домен): `Verbosity {TERSE/NORMAL/EXPANSIVE}` = demand x интерес x
  настроение/аппетит; `form_hint` BOB-018 — мягкий вход; анти-обрубок для HIGH-demand owner.
- **байес**: `voice.brevity_directive` (сильная инструкция) + `voice.brevity_few_shot` (примеры
  «простой вопрос → короткий ответ», как anti-bait few-shot) — главный рычаг против verbosity.
- **опц. страж длины** (выкл/консервативен по умолчанию). Конфиг `brevity.*`.
- Композируется поверх BOB-023 (решает длину *выбранного* ответа); SILENT/гость-инвариант целы.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5, Ollama (Qwen), Telegram (aiogram). DDD/Clean: домен чист
  (детектор/решение — без I/O, детерминированно; стохастика — seeded-RNG) ← application ←
  infrastructure; композиция в `app.py`; инъекция Clock/RNG/портов.
- **ТЕСТЫ через `.venv/bin/pytest -p no:cacheprovider`** (NOT `uv run` — висит), `pkill -9 -f
  pytest` перед, один прогон за раз. cov >=80%, `ruff`, `mypy --strict` (src+tests), `beadloom
  ci`. Документы — рус. Без символа `x`-кириллица: в комментах/докстрингах брать латиницей.

## Зависимости и границы

- **Опираемся:** BOB-018 (`ExpressionPlan`/`FormHint`/voice-директивы + anti-bait few-shot),
  BOB-014 .2a (interest/engagement), BOB-020 (mood/valence/off-days), BOB-023 (addressivity/ENGAGE).
- **Вне BOB-024:** смена/дообучение модели; жёсткий token-limit как единственный механизм;
  перегенерация длинных ответов; конфиг как основной путь управления длиной.
