<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Слой infrastructure — адаптеры портов

Реализации портов домена наружу: Telegram-транспорт, OpenAI-совместимый
LLM-провайдер, SQLite-хранилище с FTS5, файловый `SoulStore` и загрузчик
конфигурации. Инфраструктура реализует контракты `bob.domain.ports`; связывание с
приложением происходит только в `app.py`.

## Спецификация

### Модули

- **telegram/gateway.py** — `TelegramGateway`, long-polling приём и стриминг
  ответа (только транспорт); структурные протоколы `BotLike`, `UpdateLike`,
  `MessageLike`.
- **llm/openai_compat.py** — `OpenAICompatProvider`, OpenAI-совместимые
  completions поверх aiohttp (non-stream и SSE-стриминг).
- **llm/factory.py** — `build_tier_providers()`, сборка провайдеров Tier 0/1 из
  конфигурации.
- **persistence/sqlite_repo.py** — `SqliteMemoryRepo`, единственный дом SQL.
- **persistence/fts_recall.py** — `Fts5MemoryRecall`, keyword-recall через FTS5.
- **persistence/soul_store.py** — `SoulStore`, файловые артефакты `data/soul/`.
- **persistence/schema.sql** — схема SQLite (таблицы + FTS5 + триггеры).
- **config/loader.py** — `ConfigLoader`, слоистая конфигурация.

### Telegram-gateway

`TelegramGateway` — граница между Telegram и приложением; делает две транспортные
задачи и **не** содержит логики Higher Mind / LLM / памяти. **Приём:**
long-polls `get_updates`, дедуплицирует по `update_id` (Telegram может
переслать), нормализует текстовый апдейт в `MessageReceived` и публикует его в
`EventBus`. **Стриминг ответа:** шлёт одно placeholder-сообщение и прогрессивно
правит его (`editMessageText`), батчит правки по числу токенов и троттлит не
чаще одной за интервал; при rate-limit `RetryAfter` делает backoff и повтор.
Время и sleep инъецируются для детерминизма; бот инъецируется за минимальным
протоколом `BotLike`, поэтому тесты идут без сети.

### LLM-провайдер

`OpenAICompatProvider` реализует `LLMProvider` против любого эндпоинта формата
OpenAI `/chat/completions` — один адаптер служит и Tier 0 (локальный mlx-lm, без
auth), и Tier 1 (Qwen API, bearer-auth). Два режима: non-stream (POST
`stream=False`, вернуть content) и stream (POST `stream=True`, yield дельта-токенов
из SSE-тела). API-ключ не инлайнится: подаётся фабрикой из конфигурации/env, а
при отсутствии (Tier 0) заголовок `Authorization` не отправляется.
`build_tier_providers()` читает секцию `llm` и строит по одному провайдеру на тир.

### Хранилище (SQLite + FTS5)

`SqliteMemoryRepo` реализует `MemoryRepo` и является единственным домом SQL.
Схема (`schema.sql`) применяется идемпотентно на `initialize()`, соединение
работает в режиме WAL, каждый оператор параметризован (`?`) — никаких f-strings.
Доменные сущности (`EpisodicEvent`, `SemanticFact`) маппятся в строки и обратно
здесь, чтобы домен оставался без I/O.

`Fts5MemoryRecall` реализует `MemoryRecall` через FTS5 `MATCH` с ранжированием
BM25. Порт — шов для будущего вектора: домен видит только
`recall(query, k) → [Recalled]` и не знает про keyword. Сырой пользовательский
текст санитизируется в безопасное FTS5-выражение (OR кавыченных терминов), так
что операторные символы не вызывают синтаксической ошибки и не инжектятся.

`SoulStore` — файловый reader/writer артефактов `data/soul/`: `SOUL.md`,
JSON-профили (`taste_profile`, `mood`, `phantom_prefs`) и append-only
`genesis_log.md`. Каталог создаётся по требованию.

### Конфигурация

`ConfigLoader` строит эффективную конфигурацию слоями: встроенные
`DEFAULT_CONFIG` → опциональный YAML (`yaml.safe_load`) → переменные окружения
(префикс `BOB_`, `__` для вложенности, например `BOB_LLM__TIER1_MODEL` →
`config["llm"]["tier1_model"]`). Поздние слои deep-merge поверх ранних.

## Инварианты

- Адаптеры реализуют порты `bob.domain.ports`; связывание — только в `app.py`.
- Весь SQL живёт в `SqliteMemoryRepo` и параметризован (`?`).
- Пользовательский текст для FTS5 санитизируется (без инъекций/синтаксических ошибок).
- API-ключ и токен берутся из конфигурации/env и не инлайнятся; на Tier 0 нет
  заголовка `Authorization`.
- Везде `yaml.safe_load` и `pathlib`.
- Gateway не содержит логики Higher Mind / LLM / памяти.

## API

Модуль `src/bob/infrastructure/telegram/gateway.py`:
- `TelegramGateway(*, bot, bus, poll_timeout, batch_tokens, throttle_interval, clock, sleep)` —
  `async poll_once()`, `async intake(update)`, `async stream_reply(*, chat_id, tokens)`.
- `BotLike`, `UpdateLike`, `MessageLike`.

Модуль `src/bob/infrastructure/llm/openai_compat.py`:
- `OpenAICompatProvider(*, base_url, model, api_key, timeout_seconds=60.0)` —
  `async complete(messages, *, stream=False)`.

Модуль `src/bob/infrastructure/llm/factory.py`:
- `build_tier_providers(config)` → `dict[int, LLMProvider]`.

Модуль `src/bob/infrastructure/persistence/sqlite_repo.py`:
- `SqliteMemoryRepo(db_path)` — `initialize()`, `close()`, `save_episode()`,
  `load_episodes(*, limit)`, `save_fact()`, `set_mood(state, *, at)`,
  `get_mood()`, `set_taste_axis(...)`, `set_relationship()`, `kv_set()/kv_get()`.

Модуль `src/bob/infrastructure/persistence/fts_recall.py`:
- `Fts5MemoryRecall(repo)` — `async recall(query, *, k)` → `Sequence[Recalled]`.

Модуль `src/bob/infrastructure/persistence/soul_store.py`:
- `SoulStore(soul_dir)` — `soul_exists()`, `read_soul()`, `write_soul()`,
  `read_json()/write_json()`, `append_genesis_log()/read_genesis_log()`.

Модуль `src/bob/infrastructure/config/loader.py`:
- `ConfigLoader(*, yaml_path, env=None)` — `load()` → `Config`; `DEFAULT_CONFIG`.

## Тесты

Тесты: `tests/infrastructure/telegram/test_gateway.py`,
`tests/infrastructure/llm/test_openai_compat.py`,
`tests/infrastructure/llm/test_openai_compat_parsers.py`,
`tests/infrastructure/llm/test_factory.py`,
`tests/infrastructure/persistence/test_sqlite_repo.py`,
`tests/infrastructure/persistence/test_fts_recall.py`,
`tests/infrastructure/persistence/test_soul_store.py`,
`tests/infrastructure/config/test_loader.py`.
