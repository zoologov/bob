<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-028 — «T2.2 Self-Improvement: метакогнитивное обучение на паттернах»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-028 (Тир 2, T2.2) · эпик `bob-7xn`

---

## Состояние

Тир 1 закрыт; автономность-стадия B (Goal Engine) отгружена-дремлет (BOB-015). Боб эволюционирует
эстетически (вкус/fascination/phantom/память), но **не учится на своей истории общения** — не
замечает поведенческих паттернов за собой. Этот эпик даёт **метакогнитивный слой**: детектор
паттернов → правило-стратегия → предложение owner → мягкое обратимое применение. Вариант A
(предложил→апрув), полный набор сигналов, жёсткие границы безопасности. PRD/RFC утверждены. Ветка
`features/BOB-028` от main (`0452890`, BOB-027 в main).

## Ключевые решения (из RFC)

- **Модель правила** — чистый домен `self_improvement.py`: `Lever` (жёсткий allowlist
  TONE/LENGTH/PROACTIVITY/ADDRESSIVITY_BIAS/HUMOR — и только); `RuleState`-машина (в APPROVED только
  owner-апрув); `ImprovementRule` (observation/adjustment/lever/ограниченная magnitude/evidence) +
  `active_rules`. Порт `SelfImprovementStore` + Sqlite.
- **Детектор** — порт `PatternDetector` + LLM-impl; `detect_patterns` use-case из ReflectTick-seam:
  сигналы (самоповторы/адресность/verbosity/отношения/застревание-настроения/поправки/что-зашло) →
  кандидаты PROPOSED → дедуп → персист. Только предлагает.
- **Предложил→апрув** — реюз паттерна Goal Engine; GUPPI owner-команды `/rules`, `/rule approve|
  reject|pause|resume|remove`.
- **Мягкое применение** — `active_rules` → модуляторы по рычагу в свою точку (voice-директива /
  verbosity-байес / urge-байес / адресность-байес); наклон, не перехват; читает только allowlist.
- **Безопасность по конструкции** — `Lever` не содержит authz/гостя/SOUL/safety → правило их не
  представит (defense-in-depth: домен + применение). Мастер-выключатель `self_improvement.enabled` OFF.

## Стандарты кода (CLAUDE.md §0.1)

- Python 3.12+ (asyncio), SQLite+FTS5, Ollama (Qwen), Telegram (aiogram). DDD/Clean: модель правила/
  машина/выбор — чистый домен (без I/O, детерминированно; стохастика seeded) ← application ←
  infrastructure; детектор/LLM/persist за портами; композиция в `app.py`; инъекция Clock/RNG/портов.
- **ТЕСТЫ через `.venv/bin/pytest -p no:cacheprovider`** (NOT `uv run` — висит), `pkill -9 -f pytest`
  перед, один прогон за раз. cov >=80%, `ruff`, `mypy --strict` (src+tests), `beadloom ci`. Документы
  — рус, без символа `x`-кириллицы в формулах (латиница).

## Зависимости и границы

- **Реюз:** ReflectTick (BOB-026, драйвер детектора через опц. seam), апрув-паттерн Goal Engine
  (BOB-015), voice-директивы / verbosity (BOB-024) / urge-governance (BOB-010) / адресность-пороги
  (BOB-023/025) как точки применения, persistence-паттерн `XxxStore`, личность Тир 1 как то, что шлифуется.
- **Вне BOB-028:** авто-применение без апрува (позже); правила, трогающие authz/safety/ядро SOUL;
  Боб переписывает свой код (Тир 3); self-improvement самих целей (BOB-015); RL/онлайн-дообучение.
