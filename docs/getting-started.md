<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Первый запуск Боба

Пошаговый разворот Боба с нуля: предпосылки, установка, конфигурация, запуск.
Обзор архитектуры — в [`architecture.md`](architecture.md); подробности по каждому
модулю — в per-module SPEC (`domains/<module>/README.md`, `services/runtime.md`).

## Предпосылки

- **[uv](https://github.com/astral-sh/uv)** — менеджер зависимостей и виртуального
  окружения (Python 3.12+ подтягивается им же).
- **[Ollama](https://ollama.com)** с локальными моделями Qwen — для семантической
  памяти (эмбеддер, опц. реранкер) и локального Tier 0.
- **Telegram-бот-токен** (на самом деле два — для Боба и для GUPPI, см. ниже).
- Опц. ключ Qwen MaaS для Tier 1 (качественные ответы) и `claude` CLI (навык
  «Боб пишет код»).

## Установка

```bash
uv sync                                        # зависимости + venv
cp config/bob.example.yaml config/bob.yaml     # рабочая конфигурация
```

`config/bob.example.yaml` — размеченный шаблон со всеми секциями и дефолтами;
скопируйте его в `config/bob.yaml` и заполните non-secret значения (модели, owner,
chat). Секреты (токены ботов, `llm.tier1_api_key`) в YAML **не** кладут — они
приходят через переменные окружения.

### Локальный стек памяти (Ollama)

Гибридной памяти нужен локальный Ollama с эмбеддером и (опционально) реранкером.
Ставится одним скриптом:

```bash
bash scripts/setup-ollama.sh
```

Скрипт качает **standalone Ollama** (не `brew install ollama` — Homebrew-формула
тянет `python@3.14` и может сломать toolchain проекта) в `~/.local/ollama`,
поднимает `ollama serve` и делает `pull` эмбеддера (`bge-m3`) и реранкера
(`bge-reranker-v2-m3`). Модели/каталог переопределяются через env: `EMBED_MODEL`,
`RERANK_MODEL`, `OLLAMA_DIR`. На Linux — `https://ollama.com/install.sh`, дальше
с шага `pull`.

Боб **стартует и при выключенном Ollama**: сборка эмбеддера сеть не трогает, а
первый недоступный `embed()` мягко деградирует recall на keyword-only — память не
теряется, лишь её семантическая половина.

## Конфигурация

`ConfigLoader` собирает эффективную конфигурацию слоями:
**встроенные дефолты → `config/bob.yaml` → переменные окружения** (префикс `BOB_`,
`__` для вложенности, напр. `BOB_LLM__TIER1_API_KEY`). env выигрывает всегда.

### Переменные окружения (секреты)

Положите в `.env` (загружается лаунчером `./bob`):

```
BOB_TELEGRAM__TOKEN=…       # токен бота Боба
GUPPI_TELEGRAM__TOKEN=…     # токен бота GUPPI (нестандартный префикс GUPPI_)
BOB_TELEGRAM__OWNER_ID=…    # ваш Telegram user-id (owner-команды)
BOB_LLM__TIER1_API_KEY=…    # ключ Qwen MaaS для Tier 1 (опц.)
```

🔴 **Два токена в env — обязательны для боевого запуска.** Оба бота должны быть
**админами группы**: иначе Telegram privacy mode скроет от них групповые сообщения
(решается правами админа либо `/setprivacy disable` у BotFather). Именно потому,
что оба админа видят одно сообщение, gateway дедуплицирует кросс-бот по
`(chat_id, message_id)`.

### Ключевые non-secret параметры (`config/bob.yaml`)

- `telegram.chat_id` — id supergroup; `telegram.bob.topic_id` — форум-топик Боба;
  `telegram.owner_id`; `telegram.allowed_chat_ids` — список разрешённых чатов.
  General — тред без `message_thread_id` (служебный, под GUPPI).
- `llm.tier0_*` / `llm.tier1_*` — endpoints и модели тиров; `timeout_seconds`
  (180); `disable_thinking` (true); `tier0_temperature`/`tier1_temperature`.
- `llm.tier0_fallback` (пусто = выключено) — аварийный локальный дублёр Tier 0 на
  случай, когда облачный endpoint пропадает из сети. Режим включает значение `ollama` —
  единственное поддерживаемое (`BOB_LLM__TIER0_FALLBACK=ollama` либо строка в
  `config/bob.yaml`: у всех трёх ключей есть встроенные дефолты, в шаблоне
  `bob.example.yaml` их нет). `llm.tier0_fallback_base_url`
  (`http://localhost:11434/v1`) и `llm.tier0_fallback_model` (`qwen2.5:0.5b`) задают
  дублёра. Подробности и границы режима — в
  [`domains/infrastructure/features/llm/SPEC.md`](domains/infrastructure/features/llm/SPEC.md).
- `runtime.language` (`ru`) — язык персоны для само-генерируемого текста.
- `embeddings.*` / `reranker.*` — локальный стек памяти (base_url `localhost:11434`).
- `goals.*` — автономность (по умолчанию `pursuit_enabled: false` → рантайм
  ровно прежний); `emotion.*` / `personality.evolution.*` — тюнинг эмоциональной
  глубины и темпа само-эволюции.

🔴 **Аварийный фолбэк Tier 0 выключен намеренно, и включать его пока не следует.**
Нулевой тир обслуживает не только служебные ходы: короткие разговорные реплики идут
через него же. Поэтому при включённом `llm.tier0_fallback` и отвале облака ответ в чат
сгенерирует локальная модель (по умолчанию `qwen2.5:0.5b`) — и ляжет в память как
обычный голос Боба, продолжая влиять на тон уже после того, как облако вернулось.
Решение по этому поведению владелец ещё не принял. Отдельно: дублёр наследует общий
`timeout_seconds` (180 с), так что на отказе вида «облако молчит» ход может стоить два
ожидания подряд.

Полный список секций с комментариями — в `config/bob.example.yaml`.

## Запуск

Боб управляется единым лаунчером `./bob`:

```bash
./bob start      # старт в фоне (грузит .env, начинает Telegram-поллинг)
./bob status     # 🟢/🔴 + жив ли поллинг
./bob logs       # хвост живого лога
./bob restart    # stop + start
./bob stop       # мягкая остановка
```

На первом старте один раз отрабатывает Genesis (загрузка `bob-soul/`), после чего
composition root (`src/bob/runtime/`) поднимает один poll-таск (гонит обоих ботов
через `MultiBotGateway`) и четыре heartbeat-тика (inner-monologue, mood-drift,
reflect, проактивный `ProactiveTick`). Подробности сборки и запуска — в
[`services/runtime.md`](services/runtime.md).

## Проверка

```bash
uv run pytest                    # тесты
uv run ruff check src/ tests/    # линт
uv run mypy src/                 # типы (strict)
```
