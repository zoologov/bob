<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-001 — Личность Боба в Telegram (текстовый MVP)

> **Status:** Approved
> **Created:** 2026-06-18

---

## Обзор

Строим **единый Python-процесс (GUPPI)**, который держит Telegram-бота, локальный/облачный LLM через
провайдер-агностичный router, память на SQLite и ядро личности (Higher Mind). Пользователь пишет в
приватную supergroup → Боб отвечает со стримингом, с учётом настроения/вкусов/памяти, переживает
рестарты. Архитектура — **DDD + Clean Architecture**: чистый домен личности в центре, адаптеры
(Telegram, LLM, SQLite) — снаружи.

## Мотивация

### Проблема
Нужен первый живой срез личности (см. PRD). Технически: связать Telegram-транспорт, LLM-слой и
персистентную личность так, чтобы (а) личность была отделена от транспорта и провайдера (переносимость),
(б) состояние переживало рестарт, (в) всё уместилось в один процесс на Mac mini 24 ГБ.

### Решение
Гексагональная схема: **домен** (личность, память — чистая логика) не знает про Telegram/Qwen/SQLite;
**приложение** (GUPPI: рантайм, use-cases, router-политика) оркеструет; **инфраструктура** (адаптеры)
реализует порты. Замена «локально ↔ API» и «keyword ↔ vector» — это смена адаптера за портом, не
переписывание ядра.

## Технический контекст

### Ограничения
- Python 3.12+, asyncio, единый процесс. Сборка `uv`. `mypy --strict`, `ruff`, покрытие ≥80%, TDD.
- SQLite (WAL), FTS5 для recall. Без RAG/эмбеддингов в P0 (порт `MemoryRecall` для будущей замены).
- Mac mini M4 Pro 24 ГБ: Tier 0 — лёгкая локальная MLX-модель (~1.5–3 ГБ); тяжёлый reasoning — Qwen API
  (не ест локальную RAM). См. VISION §7.1.
- LLM-доступ только через OpenAI-совместимый клиент (`base_url + model + key`).
- Приватность: личность/память по умолчанию → Tier 0; эскалация в Tier 1 только с редакцией контекста.

### Затрагиваемые области
Гринфилд: `src/bob/` сейчас пуст (только `__init__.py`, граф beadloom = 1 узел `bob`). Весь код P0 —
новый. Внешние данные: `bob-soul/` (шаблоны личности, новый каталог) и `data/` (рантайм-состояние,
вне git).

## Предлагаемое решение

### Слои (DDD + Clean Architecture)

```
src/bob/
  domain/                 # ЧИСТО: без I/O, без LLM, без Telegram. Только логика и модели.
    personality/          # Mood, Taste, Negotiation, SOUL, phantom prefs (value objects + доменные сервисы)
    memory/               # EpisodicEvent, SemanticFact, доменные правила консолидации
    ports.py              # протоколы (интерфейсы): LLMProvider, MemoryRepo, MemoryRecall, Clock, EventBus
  application/            # GUPPI: use-cases + оркестрация. Зависит от domain (через порты), не от infra.
    runtime/              # AgentRuntime (event loop), EventBus-импл (asyncio), lifecycle
    router/               # LLMRouter: классификация задачи → выбор Tier + правило редакции
    usecases/             # HandleMessage, RunGenesis, InnerMonologueTick, ReflectTick, UpdateMoodFromText
  infrastructure/         # Адаптеры портов (наружу).
    telegram/             # TelegramGateway (python-telegram-bot): приём, дедуп, стриминг editMessageText
    llm/                  # OpenAICompatProvider (Tier 0 mlx-lm server / Tier 1 Qwen API), фабрика по конфигу
    persistence/          # SqliteMemoryRepo + FTS5 recall, схема, миграции, SoulStore
    config/               # ConfigLoader (defaults → YAML → env)
  app.py                  # composition root: собирает порты+адаптеры, запускает AgentRuntime
```

Правило слоёв (lint beadloom): `infrastructure → application → domain`; `domain` не импортирует ничего
наружу; композиция — только в `app.py`. Никакой «CLI → Core → Storage» (это не CLI-тула).

### Поток обработки сообщения (упрощённый perceive→decide→act)

1. **Telegram update** → `TelegramGateway` дедупит, публикует `MessageReceived` в EventBus.
2. **`UpdateMoodFromText`** (Tier 0): сентимент + сигналы (частота, время суток, presence) → обновляет
   Mood (доменная логика).
3. **`HandleMessage`**: recall релевантной памяти (`MemoryRecall`, FTS5) + текущее состояние личности
   (Mood/Taste/SOUL) → собирает контекст.
4. **LLMRouter**: классифицирует задачу → выбирает Tier (ответ пользователю → Tier 1 по умолчанию,
   с **редакцией** личного контекста; дешёвое/чувствительное → Tier 0). Зовёт `LLMProvider`.
5. **Стриминг**: токены → `TelegramGateway` батчит правки `editMessageText` (с троттлингом).
6. **Персист**: эпизод в `episodic_log`, новые факты в `semantic_memory` (FTS5), снапшот настроения.

Параллельно — лёгкий **heartbeat-тик** (background asyncio task): `InnerMonologueTick` (Tier 0, питает
Mood), дрейф mood-baseline, периодический `ReflectTick`.

### Genesis (первый запуск)

`RunGenesis` срабатывает, если нет `data/soul/SOUL.md`: читает шаблоны `bob-soul/` (архетип, пул черт,
оси вкусов, mood-baselines, фантомные предпочтения), Tier 1 генерирует конкретную личность, пишет
`data/soul/` (SOUL.md, taste_profile.json, mood.json, phantom_prefs.json, genesis_log.md) +
проигрывает «пробуждение» в чат. Флаг персистентности → повторно не запускается.

### Ключевые порты (контракты)

- `LLMProvider`: `async complete(messages, *, stream) -> str | AsyncIterator[str]` (OpenAI-совместимо).
  Реализации: `OpenAICompatProvider(base_url, model, api_key)` для Tier 0 (mlx-lm) и Tier 1 (Qwen).
- `MemoryRepo`: запись/чтение эпизодов, фактов, состояния (SQLite).
- `MemoryRecall`: `recall(query, k) -> list[Recalled]` — в P0 FTS5-keyword; шов для vector в P1.5+.
- `EventBus`: `publish(event)` / `subscribe(type, handler)` (asyncio pub/sub).
- `Clock`: инъекция времени (детерминизм тестов; в репо запрещён `datetime.now()` без инъекции).

### Изменения (новые модули — основные)

| Модуль | Назначение |
|---|---|
| `infrastructure/telegram/gateway.py` | приём апдейтов, дедуп, стриминг-ответы |
| `infrastructure/llm/openai_compat.py` | провайдер OpenAI-совместимый (Tier 0/1) + фабрика по конфигу |
| `infrastructure/persistence/sqlite_repo.py` + `schema.sql` | хранилище + FTS5 recall + миграции |
| `application/router/llm_router.py` | классификация задачи → Tier + правило редакции |
| `application/runtime/agent.py` + `event_bus.py` | event loop, lifecycle, шина |
| `domain/personality/{mood,taste,negotiation,soul}.py` | ядро личности (чистая логика) |
| `application/usecases/{handle_message,genesis,monologue,reflect}.py` | use-cases |
| `app.py` | composition root |
| `bob-soul/` | шаблоны личности (архетип, черты, вкусы, фантомные предпочтения) |

### Схема данных (SQLite, эскиз)

`episodic_log(ts, type, content, mood_snapshot, tags)` · `semantic_memory(category, content, …)` +
FTS5 виртуальная таблица над content · `mood_state` / `mood_history` · `taste_axes(axis, value,
conviction, experience_count)` · `relationship(trust, …)` · `kv(genesis_done, …)`.

## Рассмотренные альтернативы

- **Без слоёв, «всё в хендлерах Telegram»** — отвергнуто: личность привязалась бы к транспорту, тесты
  и переносимость пострадали; противоречит цели «личность платформонезависима».
- **Локальная модель для тяжёлого reasoning (Tier 1 локально)** — отвергнуто для P0: 24 ГБ конфликтуют
  с будущим dev-тулчейном; Qwen API сильнее и не ест RAM (VISION §7.1). Порт оставляет дверь открытой.
- **Сразу векторная память (FAISS)** — отвергнуто: на масштабе MVP FTS5 достаточно; эмбеддинги едят
  RAM и усложняют. Введём за портом при промахах (P1.5+).
- **Webhook вместо long-polling** — отложено: long-polling проще (нет публичного эндпоинта); webhook —
  оптимизация позже.

## Риски

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Латентность/обрыв Qwen API на ответе пользователю | Med | Med | Fallback на Tier 0 локально; таймауты; стриминг скрывает часть латентности |
| Троттлинг Telegram при стриминге `editMessageText` | Med | Low | Батчить правки (N токенов / интервал), backoff |
| Утечка личного контекста в Tier 1 | Low | High | Правило редакции в router; тесты на минимизацию; чувствительное — на Tier 0 |
| Качество Genesis зависит от шаблонов `bob-soul` | Med | Med | Тщательно проработать шаблоны; Genesis через Tier 1; ретраи |
| 24 ГБ RAM при работе Tier 0 + процесса | Low | Med | Tier 0 ~1.5–3 ГБ; тяжёлое в API; мониторинг |

## Открытые вопросы

| # | Вопрос | Решение |
|---|--------|---------|
| Q1 | Точная локальная Tier 0 модель (Qwen3-1.7B vs 4B на MLX) | Pending — бенч на этапе реализации |
| Q2 | Дефолтный Tier для **ответа пользователю** | **Decided:** Tier 1 (Qwen) + редакция личного контекста, fallback Tier 0 при недоступности |
| Q3 | Long-polling в P0? | **Decided:** да, long-polling; webhook позже |
| Q4 | Сколько `bob-soul` авторить руками сейчас vs генерить | Pending — минимально-достаточный шаблон в P0 |
