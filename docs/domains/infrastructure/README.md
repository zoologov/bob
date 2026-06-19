<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Слой infrastructure — адаптеры портов

Реализации портов домена наружу: Telegram-транспорт, OpenAI-совместимый
LLM-провайдер, SQLite-хранилище с FTS5, файловый `SoulStore` и загрузчик
конфигурации. Инфраструктура реализует контракты `bob.domain.ports`; связывание с
приложением происходит только в `app.py`.

## Спецификация

### Модули

- **telegram/gateway.py** — `TelegramGateway` на aiogram: long-polling приём с
  единым гейтом авторизации + нативный draft-стриминг и Rich Messages (только
  транспорт); структурные протоколы `BotLike`, `UpdateLike`, `MessageLike`,
  `AuthorizerLike`.
- **telegram/rich.py** — `MarkdownToRichMessage` (markdown → типизированное дерево
  aiogram `RichMessage`/`RichBlock`/`RichText`) и `RichMessageSerializer` (дерево →
  rich-message markdown для отправки).
- **llm/openai_compat.py** — `OpenAICompatProvider`, OpenAI-совместимые
  completions поверх aiohttp (non-stream, SSE-стриминг и tool-calling).
- **llm/factory.py** — `build_tier_providers()`, сборка провайдеров Tier 0/1 из
  конфигурации.
- **persistence/sqlite_repo.py** — `SqliteMemoryRepo`, единственный дом SQL.
- **persistence/fts_recall.py** — `Fts5MemoryRecall`, keyword-recall через FTS5.
- **persistence/allowlist_store.py** — `KvAllowlistStore`, долговечный
  authz-allowlist поверх таблицы `kv`.
- **persistence/soul_store.py** — `SoulStore`, файловые артефакты `data/soul/`.
- **persistence/schema.sql** — схема SQLite (таблицы + FTS5 + триггеры).
- **config/loader.py** — `ConfigLoader`, слоистая конфигурация.

### Telegram-gateway (aiogram)

`TelegramGateway` — граница между Telegram и приложением; делает только
транспортные задачи и **не** содержит логики Higher Mind / LLM / памяти. Адаптер
переписан на **aiogram** (Bot API 10.1): нативные draft-стриминг и Rich Messages
заменили прежний хак на `editMessageText`-loop из PTB.

**Приём + единый гейт авторизации.** `poll_once()` long-polls `get_updates`,
`intake()` дедуплицирует по `update_id` (Telegram может переслать), затем проходит
**единый гейт** `_passes_gate`: при подключённом `AuthorizerLike` сообщение из
неразрешённого чата или от неавторизованного пользователя **молча отбрасывается**
(ни `MessageReceived`, ни ответа) — это единственная точка проверки, без обхода и
fail-closed. Owner-команды `/authorize <user_id>` и `/deauthorize <user_id>`
потребляются прямо здесь (не публикуются) и доступны только owner; для остальных
их текст проходит как обычное сообщение. Прошедший гейт текстовый апдейт
нормализуется в `MessageReceived` и публикуется в `EventBus`. Без подключённого
авторизатора гейт открыт (обратная совместимость).

**Стриминг ответа.** `stream_reply` шлёт частичный текст нативными draft'ами
(`send_message_draft`), батчит по числу токенов и троттлит не чаще одной за
интервал, при `TelegramRetryAfter` делает backoff и повтор, по завершении
коммитит готовый ответ как реальное сообщение (`send_message`).

**Rich Messages + thinking.** `reply` конвертирует markdown-ответ Боба в
типизированное дерево `RichMessage` (опционально с ведущим сворачиваемым блоком
`RichBlockThinking`, когда задан `thinking`), сериализует его в rich-message
markdown и шлёт через `send_rich_message`. `stream_reply_rich` стримит rich-драфты
(`send_rich_message_draft`) и коммитит готовый rich-ответ. При **любой** ошибке
rich происходит тихая деградация на обычный `send_message` — пользователь всегда
получает текст, никогда ошибку; plain-fallback дробит длину по лимиту
`PLAIN_TEXT_LIMIT` (4096).

Время и sleep инъецируются для детерминизма; бот инъецируется за минимальным
протоколом `BotLike`, поэтому тесты идут без сети. Реальная сборка aiogram `Bot`
и адаптер `UpdateLike` живут в `app.py`.

### Markdown → Rich Message

`MarkdownToRichMessage` — чистая детерминированная трансформация (без I/O, сети и
часов): подмножество markdown ответа Боба → типизированное дерево aiogram
`RichMessage`. Блоки: заголовки `#..######` → `RichBlockSectionHeading`, fenced
код → `RichBlockPreformatted`, цитаты `>` → `RichBlockBlockQuotation`, списки
`-`/`1.` → `RichBlockList`, `---`/`***` → `RichBlockDivider`, остальное —
`RichBlockParagraph`. Инлайн-спаны: `**bold**`, `*italic*`, `` `code` ``,
`~~strike~~`, `||spoiler||`, `$math$`. `RichMessageSerializer` рендерит дерево
обратно в rich-message markdown, который aiogram `InputRichMessage(markdown=...)`
принимает на отправку (на send-стороне дерево не передаётся). Обе операции чисты
и тестируемы в изоляции.

### LLM-провайдер

`OpenAICompatProvider` реализует `LLMProvider` против любого эндпоинта формата
OpenAI `/chat/completions` — один адаптер служит и Tier 0 (локальный mlx-lm, без
auth), и Tier 1 (Qwen API, bearer-auth). Два режима: non-stream (POST
`stream=False`, вернуть content) и stream (POST `stream=True`, yield дельта-токенов
из SSE-тела). API-ключ не инлайнится: подаётся фабрикой из конфигурации/env, а
при отсутствии (Tier 0) заголовок `Authorization` не отправляется.
`build_tier_providers()` читает секцию `llm` и строит по одному провайдеру на тир.

Под reasoning-модели провайдер настраивается: `timeout_seconds` (по умолчанию
`180`) не даёт медленному reasoning-ответу ложно упасть в таймаут, а
`disable_thinking` (по умолчанию `true` в `DEFAULT_CONFIG`) шлёт директиву
«no thinking» сразу в двух формах (`extra_body` и `chat_template_kwargs`) — ответам
chain-of-thought не нужен, без него быстрее и дешевле. Разбор содержимого терпим:
структурные ошибки (нет `choices`/`message`) поднимаются, но отсутствующий, `null`
или нестроковый `content` деградирует в пустую строку, не вызывая ложного отката.

**Tool-calling** реализует порт `ToolCallingProvider`: `complete_with_tools`
отправляет манифест навыков как нативные OpenAI `tools` и разбирает ответ в
`ToolCallResult`. Предпочитается нативный массив `tool_calls`; если его нет —
включается **prompt-fallback**: из текста ответа терпимо извлекается
prompt-протокольный JSON-объект `{"tool_call": {"name": ..., "arguments": {...}}}`
(терпя reasoning-обёртку: преамбулу-рассуждение и markdown-фенсы), сканированием
первого сбалансированного `{...}`. Если ни того, ни другого — ход финальный и
`text` есть ответ. Аргументы вызова (JSON-строка) декодируются терпимо: битый или
не-объектный payload даёт `{}`, а не ошибку, чтобы сбойная модель не уронила
диспатч.

### Хранилище (SQLite + FTS5)

`SqliteMemoryRepo` реализует `MemoryRepo` и является единственным домом SQL.
Схема (`schema.sql`) применяется идемпотентно на `initialize()`, соединение
работает в режиме WAL, каждый оператор параметризован (`?`) — никаких f-strings.
Доменные сущности (`EpisodicEvent`, `SemanticFact`) маппятся в строки и обратно
здесь, чтобы домен оставался без I/O.

`Fts5MemoryRecall` реализует `MemoryRecall` через FTS5 `MATCH` с ранжированием
BM25. Recall охватывает оба индекса — распознанные факты (`semantic_fts`) и весь
архив переписки (`episodic_fts`): даже не извлечённый в факт ход остаётся
доступным, так что Боб вспоминает сказанное много ходов назад. Совпадения из обоих
индексов сливаются, дедуплицируются по содержимому, ранжируются по BM25 и
обрезаются до `k` лучших; каждый элемент несёт тег источника (`semantic` /
`episodic`). Порт — шов для будущего вектора: домен видит только
`recall(query, k) → [Recalled]` и не знает про keyword. Сырой пользовательский
текст санитизируется в безопасное FTS5-выражение (OR кавыченных терминов), так
что операторные символы не вызывают синтаксической ошибки и не инжектятся.

Индекс `episodic_fts` синхронизируется триггерами, а `SqliteMemoryRepo.initialize()`
ещё и идемпотентно его перестраивает (команда FTS5 `rebuild`), подхватывая ходы,
записанные до появления индекса.

`KvAllowlistStore` реализует порт `AllowlistStore`, персистя множество
allowlisted `user_id` как JSON-массив под единым ключом `authz.allowlist` в
существующей таблице `kv` (`kv_get`/`kv_set` репозитория). Весь SQL остаётся в
`SqliteMemoryRepo` (параметризован), а `/authorize` переживает рестарт: свежий
процесс читает тот же ключ и видит те же гранты. Декодирование защищено по форме
(не-список или не-int элементы игнорируются).

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
- Единый гейт авторизации в gateway fail-closed: при подключённом авторизаторе
  неразрешённый чат/пользователь молча отброшены, без обхода.
- Rich-отправка деградирует на plain при любой ошибке — пользователь не видит
  ошибку транспорта.
- `MarkdownToRichMessage` и `RichMessageSerializer` — чистые и детерминированные
  (без I/O, сети, часов).
- Allowlist персистится в таблице `kv` (параметризованный SQL) и переживает рестарт.

## API

Модуль `src/bob/infrastructure/telegram/gateway.py`:
- `TelegramGateway(*, bot, bus, poll_timeout, batch_tokens, throttle_interval, clock, sleep, authorizer=None)` —
  `async poll_once()`, `async intake(update)`, `async stream_reply(*, chat_id, tokens)`,
  `async reply(*, chat_id, markdown, thinking=None)`,
  `async stream_reply_rich(*, chat_id, tokens, thinking=None)`.
- `BotLike`, `UpdateLike`, `MessageLike`, `AuthorizerLike`, `PLAIN_TEXT_LIMIT`.

Модуль `src/bob/infrastructure/telegram/rich.py`:
- `MarkdownToRichMessage` — `convert(markdown, *, thinking=None)` → `RichMessage`.
- `RichMessageSerializer` — `to_markdown(message)` → `str`.

Модуль `src/bob/infrastructure/llm/openai_compat.py`:
- `OpenAICompatProvider(*, base_url, model, api_key, timeout_seconds=180.0, disable_thinking=False)` —
  `async complete(messages, *, stream=False)`,
  `async complete_with_tools(messages, *, tools)` → `ToolCallResult`.

Модуль `src/bob/infrastructure/llm/factory.py`:
- `build_tier_providers(config)` → `dict[int, LLMProvider]`.

Модуль `src/bob/infrastructure/persistence/sqlite_repo.py`:
- `SqliteMemoryRepo(db_path)` — `initialize()`, `close()`, `save_episode()`,
  `load_episodes(*, limit)`, `save_fact()`, `set_mood(state, *, at)`,
  `get_mood()`, `set_taste_axis(...)`, `set_relationship()`, `kv_set()/kv_get()`.

Модуль `src/bob/infrastructure/persistence/fts_recall.py`:
- `Fts5MemoryRecall(repo)` — `async recall(query, *, k)` → `Sequence[Recalled]`
  (поиск по `semantic_fts` + `episodic_fts`, слияние, дедуп, ранжирование BM25).

Модуль `src/bob/infrastructure/persistence/allowlist_store.py`:
- `KvAllowlistStore(kv)` — `async load()` → `set[int]`, `async add(user_id)`,
  `async remove(user_id)`.

Модуль `src/bob/infrastructure/persistence/soul_store.py`:
- `SoulStore(soul_dir)` — `soul_exists()`, `read_soul()`, `write_soul()`,
  `read_json()/write_json()`, `append_genesis_log()/read_genesis_log()`.

Модуль `src/bob/infrastructure/config/loader.py`:
- `ConfigLoader(*, yaml_path, env=None)` — `load()` → `Config`; `DEFAULT_CONFIG`.

## Тесты

Тесты: `tests/infrastructure/telegram/test_gateway.py`,
`tests/infrastructure/telegram/test_gateway_authz.py`,
`tests/infrastructure/telegram/test_gateway_hardening.py`,
`tests/infrastructure/telegram/test_rich.py`,
`tests/infrastructure/telegram/test_rich_hardening.py`,
`tests/infrastructure/llm/test_openai_compat.py`,
`tests/infrastructure/llm/test_openai_compat_parsers.py`,
`tests/infrastructure/llm/test_factory.py`,
`tests/infrastructure/persistence/test_sqlite_repo.py`,
`tests/infrastructure/persistence/test_fts_recall.py`,
`tests/infrastructure/persistence/test_allowlist_store.py`,
`tests/infrastructure/persistence/test_soul_store.py`,
`tests/infrastructure/config/test_loader.py`.
