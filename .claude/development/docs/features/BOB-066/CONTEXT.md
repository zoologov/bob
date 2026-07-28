<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-066 — «Человеческое групповое присутствие»

> **Status:** Approved
> **Created:** 2026-07-29
> **Type:** epic
> **PRD/RFC:** оба Approved (см. соседние файлы)

---

## Цель и блокер (не забывать при каждом срезе)

Боб — **живой равный участник** мультипати-диалога (Владимир + Норман + Лёша), а не скриптованный
бот. 🔴 **Блокер:** owner НЕ добавит команду в группу, пока эпик не сделан ЦЕЛИКОМ и на максимум
качества. Финальный критерий — человеческий: owner субъективно подтверждает «Боб ощущается живым».

## Ключевые решения (из RFC — единый источник правды)

Четыре ортогональных пласта, всё **аддитивно** (деградирует в текущее поведение при выключенных
порогах):
1. **Реактивный split** (conversation) — фокус/периферия в `TurnGate.gate()`; прямое обращение →
   детерминированный ответ (INV-1); ambient → рефлексия.
2. **Рефлексивное ядро «read the room»** (conversation, НОВЫЙ Tier-1 компонент рядом с судьёй
   BOB-049) — `RoomReading{room_mood, intent, addressee_id, salience, wants_web…}`; чистый
   `decide_from_reading` держит вердикт. Web-лаз (C11) = `wants_web` → форсит существующий
   `VerifyStep`.
3. **Ритм-слой `presence/`** (НОВЫЙ чистый domain) + intake-развязка (`application/runtime/intake/`)
   — per-chat буфер/сериализация, доля эфира, естественная задержка, бюджет реакций, staleness,
   догоняющий.
4. **EQ-слой** (social + personality) — per-person обида (`person_sulk`), RoomMood-в-тоне (по
   значению), такт разглашения (`visibility`-провенанс), кредит доверия.

**Сквозной принцип:** *LLM вербализует → чистое ядро решает вердикт → application оркестрирует →
infra реализует порт* (детерминизм ядра при живости; ПРИНЦИП-1 «живость > экономия»).

**Форсайт BobNet:** архитектура участник-агностична (ключ `sender_id`) → Боб-к-Бобу ложится на то
же ядро. Loop-breaker/replica-kind/authenticity — ОТЛОЖЕНЫ (будущий эпик). Не хардкодить
«участник = человек».

## 9 инвариантов-хранителей (чек-лист test-волны КАЖДОГО среза)

INV-1 фокусная гарантия (ответ ИЛИ GUPPI-нотис, никогда молчание; минуя RNG/ceiling/батч-дроп) ·
INV-2 полный Боб/честный нотис · INV-3 анти-скрипт = нудж не правило · INV-4 turn-local не течёт
(`TurnScope.rng`) · INV-5 порядок/сериализация треда · INV-6 анти-Exodus/достоинство (обида
порог+sustain+time-decay, per-person) · INV-7 приватность скоупа (`may_surface`) · INV-8
скоуп-fail-safe (сомнение → как 1:1) · INV-9 живой тайминг.

## Стандарты кода (из CLAUDE.md §0.1)

- **Стек:** Python **3.12+** (asyncio), Telegram (`python-telegram-bot`), Ollama (Qwen 2.5 7B/0.5B),
  SQLite + FTS5 (**без RAG/эмбеддингов в P0**).
- **Архитектура:** DDD + Clean Architecture; бизнес-модули (coding/memory/proactivity/capabilities/
  social/personality/conversation + **presence** новый) + технические (application/infrastructure/
  runtime/kernel). Границы — AaC-правила (генератор `scripts/gen_boundary_rules.py`).
- **TDD обязателен** (тест до кода). AAA, edge-cases, coverage ≥ 80%.
- **Инструменты:** ruff (lint+format), **mypy --strict** (без `Any`/`# type: ignore` без причины),
  pytest.
- **Запреты:** `print()`/`breakpoint()`, bare `except:`, `import *`, mutable-default-args.
- **Документы эпика — на русском** (project decision).

## Парадигмы качества (DDD · TDD · BDD · Cohesion · Mutation)

Путь эпика (решение owner): **максимальное качество, честность, контроль, стиль, поддерживаемость,
расширяемость, стабильность.** Пирамида:

```
   BDD acceptance (снаружи-внутрь) — pytest-bdd + Gherkin .feature
   Mutation gate (на чистых ядрах) — mutmut, измеряет СИЛУ тестов
   TDD unit (изнутри-наружу)       — чистые доменные ядра, детерминизм без LLM
   DDD границы · Cohesion компоненты
```

- **DDD:** bounded contexts (`presence/` — сознательно отдельный, не в proactivity), ports/adapters,
  чистота домена, ubiquitous language (floor/salience/RoomMood/sulk/share-of-voice), cycle-safety.
- **TDD:** тест-до-кода; вердикты тестируются детерминированно (принцип «LLM вербализует → ядро
  решает» существует ради этого).
- **BDD (acceptance-слой):** `pytest-bdd` + Gherkin `.feature` (dev-dependency). Сценарии PRD
  A/B/C/D + инварианты INV-1…9 — как поведенческие контракты, через fake-gateway. Живут в
  `tests/acceptance/features/*.feature` + steps в `tests/acceptance/steps/`. **Living documentation**
  для блокера — owner читает «как Боб живёт» на почти-естественном языке.
- **Mutation testing (`mutmut`, прицельно):** ТОЛЬКО чистые доменные ядра (`presence/` domain,
  conversation `decide_from_reading`/room-reading-логика, social sulk/relationship/endorsement,
  personality room_tone/voice-директивы). НЕ адаптеры/LLM/async/gateway. Порог **mutation-score
  ≥85%** (или «0 выживших в core-verdict»), эквивалентные мутанты — явный триаж-игнор (не подгонять
  цифру). Гоняется **per-срез на затронутом domain-модуле**, НЕ в pre-commit/pre-push (дорого).
- **🔴 Cohesion-guard (урок review .5 BOB-062):** `handle_message.py` уже 1634 строки — новые
  wiring-концерны BOB-066 (`OutgoingTarget`, извлечение room-mood, staleness-шаг, recall-фильтр
  такта) **выносить в коллабораторы, а НЕ толстить `handle()`**. Каждый срез проверяет: добавил
  когезивный компонент, не раздул монстра.

## 🔴 DoD каждого dev/test-беада (уроки BOB-062)

- `uv run pytest` зелёный.
- `uv run mypy` **ПОЛНЫЙ** (src+tests, без пути) — 0 (урок .6b: `mypy src/` пропускает стейл
  тест-импорты).
- `uv run ruff check src/ tests/`.
- `beadloom reindex --full && beadloom lint --strict` EXIT 0 (🔴 урок #142: инкрементальный reindex
  НЕ обновляет import-рёбра → маскирует циклы; всегда `--full`).
- `beadloom ci` зелёный.
- **BDD:** каждый срез добавляет `.feature`-сценарии для своих PRD-сценариев (acceptance, через
  fake-gateway).
- **Mutation (domain-беады):** `mutmut run` на затронутом domain-модуле → score ≥85% (триаж
  эквивалентных). НЕ для адаптеров/оркестрации.

## 🔴 Безопасность циклов (Bob строг к межмодульным import-циклам)

- personality ↔ conversation: RoomMood в conversation; влияние на personality — по ЗНАЧЕНИЮ
  (float/str через application), НЕ импортом.
- personality ↔ social: директивы argument-shaped; `voice` берёт `kind.value`/`trust.value`
  строками.
- conversation → social/application: через `TYPE_CHECKING` (прецедент `response_choice.py`).
- `presence/` — чистый domain (no I/O, `now`/rng инъектятся), порты в `presence/ports.py`.
- Новый модуль `presence/` → прогнать `python scripts/gen_boundary_rules.py` (граф-узел
  `module-vertical` + explicit-path правила границ), аннотации `# beadloom:feature=presence`+`layer=`.

## Метод среза (отработан на BOB-062)

BRIEF/task-init → координатор (волны: dev-impl → [dev-AaC-правила, если новый модуль] → test
инварианты → review → tech-writer) → PR → owner «мержи». Схема нового модуля: `ports.py` + логика в
корне + `usecases/` + `adapters/`. tech-writer ОБЯЗАН закрыть Gate (`sync-update` + `setup-rules
--refresh`). Мерж-затык: `git restore --staged --worktree .beads/` перед switch main. main
branch-protected → интеграция через PR.

## Миграции (все guarded/аддитивные — не ломать BOB-051 и 13 сторов)

`conversation_floor`+`participants` (nullable, пусто=legacy) · `person_sulk` (новая, нет строки=not-
sulking) · `episodic_log`+`semantic_memory`+`visibility` (NULL=public). Эталоны:
`_migrate_pursuit_stopped`, `_migrate_episodic_sender_id`.
