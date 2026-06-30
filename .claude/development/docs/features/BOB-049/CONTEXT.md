<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-049 — «Семантическое решение об отклике»

> **Status:** Approved
> **Created:** 2026-06-30

---

## Состояние

Заменить лестницу эвристик (addressivity BOB-023/025 + expression BOB-018) **одним семантическим суждением**
`ResponseJudge` (Tier-0): на каждое входящее Боб понимает смысл и решает `reply|react|ignore` + эмодзи. +
персист хода во всех ветках. + 🔴 отказоустойчивость «полный Боб или GUPPI-нотис».

## Ключевые решения (утверждены)

- **Шов суждения** `ResponseJudge` (порт + Tier-0 `LlmResponseJudge`); вход `ResponseContext` (текст,
  отправитель-как-контекст, per-person нить BOB-045, структурные подсказки @mention/reply/floor,
  настроение/отношения); выход `ResponseChoice{intent, emoji, reason}`. ВСЕГДА семантика.
- **Замена decide_response/decide_expression** одним решением; структурные сигналы — входы, не правила.
- **Эмодзи по смыслу** (intent=react), валидируется против Telegram-набора + фолбэк.
- **Персист хода при react/ignore** (память по нити).
- **🔴 Отказоустойчивость:** essential-сбой (суждение/генерация) → ретрай → GUPPI «⚠️ проблемы со связью»
  (Боб не отвечает деградированно); опциональные флейворы при сбое тихо опускаются; REACT/IGNORE как
  выбор ≠ сбой. Общий принцип проекта (в ROADMAP).
- **🔴 Authz ортогонально (BOB-019):** REPLY гостю — гостевым путём (без owner-памяти/capabilities); семантика
  решает соц-отклик, не доступ.
- **Детерминизм:** шов суждения инъектируемый (фейк в тестах).

## Стандарты (из CLAUDE.md §0.1)

- Python 3.12+, asyncio · DDD/Clean (domain← application← infrastructure) · frozen+slots, StrEnum
- pytest · ruff · mypy --strict · `.venv/bin/pytest` (uv run висит) · ≥80% · beadloom ci зелёный
- Документы — на русском. Код/докстринги — на английском.

## 🔴 Инварианты (держать в голове)

- Решение по СМЫСЛУ, для любого собеседника (не is_owner); структурные сигналы — входы.
- Authz BOB-019 не ослаблен (гость — гостевой путь). Память: ход персистится при react/ignore.
- Полный Боб или честный GUPPI-нотис — никаких полу-ответов. REACT/IGNORE-выбор ≠ сбой.
- `.venv/bin/pytest`; ≥80%; ruff/mypy --strict/beadloom ci зелёные.

## Точки интеграции

- `src/bob/domain/personality/` — `ResponseIntent`/`ResponseChoice` (новый), промпт-строитель+парсер,
  валидация эмодзи, `ResponseJudge` порт; addressivity/expression/reaction — поставщики сигналов.
- `src/bob/application/usecases/` — `decide_response.py` (новый use-case `DecideResponse`);
  `handle_message.py` (замена блока решения ~1006-1024, ветвление+персист, отказоустойчивость).
- `src/bob/infrastructure/llm/` — `LlmResponseJudge` (Tier-0 через router); `app.py` — провязка.
- `src/bob/infrastructure/telegram/` — GUPPI-нотис «проблемы со связью» (системный голос в топик Боба);
  reactor (BOB-018) ставит эмодзи по смыслу.
