&lt;!-- beadloom:badge-start -->
> 📘 **reference** — overview/guide, not tied to a code symbol
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
&lt;!-- beadloom:badge-end -->

&lt;!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Слой infrastructure — адаптеры портов

Реализации портов домена наружу: Telegram-транспорт, OpenAI-совместимый
LLM-провайдер, SQLite-хранилище с FTS5, файловый `SoulStore` и загрузчик
конфигурации. Инфраструктура реализует порты своих модулей (`bob.<module>.ports`) и
kernel-контракты (`bob.kernel.ports`); связывание с приложением происходит только в
composition root `src/bob/runtime/` (`app.py` — тонкий shim над ним).

## Спецификация

### Модули

- **telegram/multibot.py** — `MultiBotGateway`: `BotRegistry` (Боб + GUPPI), один
  поллинг обоих ботов с изоляцией, кросс-бот дедуп по `(chat_id, message_id)` и
  центральный роутер по identity+scope; `BotIdentity`, `BotScope`,
  `BotRegistration`.
- **telegram/guppi.py** — `GuppiHandler`: видимый reject `GUPPI_REJECT_TEXT` в
  топике Боба + owner-команды `/authorize`/`/deauthorize`/`/status` в General
  поверх общего `Authorizer`, плюс `/quiet`/`/wake` управления проактивностью.
- **telegram/gateway.py** — `TelegramGateway` на aiogram: long-polling приём с
  единым гейтом авторизации + typing-индикатор во время генерации и один rich-финал
  (Вариант A, BOB-008), приколачивание ответа к топику через `reply_thread_id`
  (только транспорт); структурные протоколы `BotLike`, `UpdateLike`, `MessageLike`,
  `AuthorizerLike`.
- **telegram/rich.py** — `MarkdownToRichMessage` (markdown → типизированное дерево
  aiogram `RichMessage`/`RichBlock`/`RichText`) и `RichMessageSerializer` (дерево →
  rich-message markdown для отправки).
- **llm/openai_compat.py** — `OpenAICompatProvider`, OpenAI-совместимые
  completions поверх aiohttp (non-stream, SSE-стриминг и tool-calling).
- **llm/factory.py** — `build_tier_providers()`, сборка провайдеров Tier 0/1 из
  конфигурации.
- **llm/ollama_embedder.py** — `OllamaEmbedder`, локальные dense-эмбеддинги
  (BGE-M3, 1024-dim) поверх локального Ollama; реализует порт `Embedder`.
- **llm/embedder_factory.py** — `build_embedder()`, сборка `OllamaEmbedder` из
  секции `embeddings`.
- **llm/ollama_reranker.py** — `OllamaReranker`, локальный реранкер как
  Ollama-scorer (top-K → top-N); реализует порт `Reranker`, аддитивно и с мягкой
  деградацией.
- **llm/reranker_factory.py** — `build_reranker()`, сборка `OllamaReranker` из
  секции `reranker` (или `None`, когда реранк выключен).
- **persistence/connection.py** — `SqliteConnection`, connection/schema-kernel: чистое
  I/O (open/WAL/foreign_keys, загрузка sqlite-vec, идемпотентный
  `executescript(schema.sql)`, общий kv-стор, `.connection`-шов). Кормит все 13
  долговечных сторов всех модулей + memory-репозиторий (BOB-062.7b).
- **persistence/schema.sql** — единая схема SQLite (таблицы + FTS5-триггеры +
  `memory_vec` vec0), применяется одним `executescript`.
- **persistence/__init__.py** — фасад, экспортит **только** `SqliteConnection`;
  прежние god-facade re-export'ы убраны (сторы импортятся из своих модулей).
- **config/loader.py** — `ConfigLoader`, слоистая конфигурация.

Долговечные сторы **переехали в свои bounded-context'ы**: memory-репозиторий и
вектор-/recall-адаптеры → `bob.memory.adapters` (`SqliteMemoryRepo`,
`MemoryVectorStore`, `Fts5MemoryRecall`, `HybridMemoryRecall`; BOB-062.7b/.2);
proactivity-/goal-/self-improvement-сторы → `bob.proactivity.adapters` (.3);
personality-/social-/conversation-/coding-сторы → соответствующие `adapters`-пакеты
(.4-.6). Каждый читает connection-kernel через инъецированный `.connection`-шов, а
`KvAllowlistStore`/`SoulStore` — authz/soul-адаптеры соответствующих модулей.

### Telegram-gateway (aiogram)

`TelegramGateway` — граница между Telegram и приложением; делает только
транспортные задачи и **не** содержит логики Higher Mind / LLM / памяти. Адаптер
построен на **aiogram** (Bot API 10.1): typing-индикатор во время генерации и
нативные Rich Messages для финального ответа.

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

**Ответ в группе (typing-индикатор во время генерации + rich-финал, BOB-009).**
Нативный токен-стрим в групповом топике Telegram невозможен: драфты работают только
в ЛС (Threaded Mode = темы в личке, не в группе), а `editMessageText` в группе
медленный и флуд-опасный. Боб доступен **только** через групповой топик (ЛС закрыта
authz), поэтому стримить негде — гейтвей **не стримит** (`stream_reply`/`_iter_tokens`
удалены, псевдо-стрим из готового текста больше не используется).

*Во время генерации — `sendChatAction("typing")`.* Медленная генерация (`router.run`)
оборачивается в async-контекст `typing_indicator(chat_id)`: на входе сразу шлётся
`sendChatAction("typing")` в тред Боба (`message_thread_id` через `reply_thread_id`),
затем фоновый таск **повторяет** его каждые `typing_interval` секунд (Telegram сам
гасит индикатор через несколько секунд), пока модель думает — пользователь видит «Bob
печатает…» всё ожидание. На выходе из контекста keepalive-таск **отменяется** (без
утечки). Каденс задаётся инъецированным `sleep`, поэтому детерминирован в тестах. Сбой
typing-действия логируется и проглатывается, ход не ломается.

*Готовый ответ — один `send_rich_message`.* Когда поток закончился, собранный ответ
коммитится **одним** rich-сообщением через `reply()` (`send_rich_message`: rich-блоки
+ ведущий блок `RichBlockThinking`, когда задан `thinking`), привязанным к треду
Боба. При **любой** ошибке rich — тихая деградация на обычный `send_message`, так что
ответ **никогда не теряется**; plain-fallback дробит длину по лимиту
`PLAIN_TEXT_LIMIT` (4096). Одиночный (не-драфт) `send_rich_message` в групповом
топике работает. Поскольку финал — единственное rich-сообщение, прежний баг
«edit-стрим ломает rich» больше не возникает.

*Стриминг удалён.* Прежняя машинерия стрима — edit-стриминг (`editMessageText`-loop),
draft-стриминг (`send_rich_message_draft`) и **3.0с-троттл** флуд-контроля BOB-006 —
**выпилена**: в группе не стримим, ЛС закрыта. Гейтвей упростился до
typing → rich-финал → plain-fallback.

**Rich Messages + thinking.** `reply` конвертирует markdown-ответ Боба в
типизированное дерево `RichMessage` (опционально с ведущим сворачиваемым блоком
`RichBlockThinking`, когда задан `thinking`), сериализует его в rich-message
markdown и шлёт через `send_rich_message`, деградируя на plain при любой ошибке rich.

Время и sleep инъецируются для детерминизма; бот инъецируется за минимальным
протоколом `BotLike`, поэтому тесты идут без сети. Реальная сборка aiogram `Bot`
и адаптер `UpdateLike` живут в `app.py`.

### Мульти-бот gateway и GUPPI (BOB-003)

Один процесс держит два бота — Боба и GUPPI — за `MultiBotGateway`, который чисто
транспортный шов поверх внутренних `TelegramGateway` (по одному на бота).

**`BotRegistry`** регистрирует бота как `{identity, bot, scope}` (`BotRegistration`,
`BotIdentity` BOB/GUPPI, `BotScope` с `chat_id` и опциональным `topic_id`). Боб
получает scope своего топика, GUPPI — General (`topic_id = None`). Добавление
реплики — один вызов `register` (forward-compatible под Bobiverse).

**`poll_once()`** поллит каждого зарегистрированного бота по очереди и
**изолированно** (`_poll_bot` на бота): сбой `get_updates` одного бота логируется
и пропускается, не роняя остальных. Набор изолируемых ошибок включает
`aiogram.exceptions.TelegramNetworkError` (обёртка над `ServerDisconnectedError`
на рутинном обрыве long-poll) наравне с `OSError`/`RuntimeError`/`TimeoutError` —
такой обрыв даёт `return 0` и ретрай на следующем тике, не роняя таск. Под каждого
бота заведён внутренний `TelegramGateway` для приёма/нормализации и ответа
(typing-индикатор + rich-финал); у Боба он приколочен к его топику через
`reply_thread_id`.

**Надёжность приёма — offset после обработки (BOB-070).** Внутри `_poll_bot`
offset апдейта (`self._offsets[identity]`) сдвигается **только после успешного
`route()`**, а не до обработки. Если `route()` бросает исключение, offset не
двигается и батч **останавливается на упавшем апдейте**: Telegram переприсылает
всё, что ≥ offset, на следующем тике, поэтому обрабатывать последующие апдейты
батча нельзя (иначе offset уехал бы за непринятый и сообщение потерялось бы
навсегда). Это даёт at-least-once с сохранением порядка. От зацикливания на
«ядовитом» апдейте, стабильно падающем в `route()`, защищает **poison-cap**:
неудачи считаются per-`(identity, update_id)` в `self._route_failures`; после
`_MAX_ROUTE_ATTEMPTS` (=3) попыток апдейт **громко логируется (`logger.error`) и
пропускается** (offset двигается за него, счётчик сбрасывается). Успешная
обработка тоже сбрасывает счётчик, поэтому транзиентные сбои не накапливаются до
cap.

**Кросс-бот дедуп.** Оба бота-админа видят одно групповое сообщение, поэтому оно
приходит на два потока апдейтов. `route` дедуплицирует по `(chat_id, message_id)` и
обрабатывает сообщение один раз — это отдельный ключ от per-бот дедупа по
`update_id` внутри `TelegramGateway`.

**Центральный роутер `route(update, identity)`.** После дедупа: авторизованный в
топике Боба → публикация `MessageReceived` (пайплайн Боба, ответ ботом-Бобом в его
тред); неавторизованный в топике Боба → видимый reject GUPPI (пайплайн Боба не
запускается); owner-команда в General → GUPPI; всё прочее (другой топик, чужой чат,
DM незнакомца, не-owner команда) — молча игнорируется. GUPPI-привратник строится
только когда GUPPI зарегистрирован и подан `Authorizer`; иначе GUPPI-хуки
деградируют в молчаливые дропы (обратная совместимость).

**`GuppiHandler`** владеет только поведением GUPPI и шлёт ответы своим ботом (не
Боба): `reject(chat_id, thread_id)` отправляет `GUPPI_REJECT_TEXT` в тред Боба (его
вызывает роутер только для разрешённой группы, поэтому DM незнакомца reject не
триггерит); `handle_general_command(text, user_id, chat_id)` обрабатывает
`/authorize`/`/deauthorize` (мутируют allowlist через общий `Authorizer`),
`/status` и команды проактивности `/quiet`/`/wake`, возвращая `True` только когда
команда от owner в General — иначе молча `False`. Невалидный `<user_id>` даёт
подсказку, а не грант.

**Owner-команды проактивности (BOB-010 Ф1).** `/quiet` заглушает проактив (сбрасывает
персист-флаг `proactivity_enabled` через `ProactivityStoreLike`); опциональная
длительность `/quiet 2h` / `/quiet 30m` дополнительно выставляет тайм-мьют
`mute_until` (по истечении движок сам разбудит проактив). `/wake` снимает мьют и
чистит `mute_until`. Невалидный аргумент `/quiet` даёт подсказку по использованию, а
не молчаливый мьют. Команды подключены, только когда в сборку подан
proactivity-store; иначе они деградируют в no-op (обратная совместимость).

`reply_gateway(identity)` отдаёт `ReplyGateway`-шов нужного бота; ответы Боба
приколочены к его треду, а контракт (`typing_indicator(chat_id)` +
`reply(chat_id, markdown, thinking)`) для `HandleMessage` не меняется.

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

### Локальные эмбеддинги и реранкер (BOB-011)

`OllamaEmbedder` реализует порт `Embedder` против эмбеддинг-API локального Ollama,
модель по умолчанию `bge-m3` (dense, 1024-dim, мультиязычный/русский). Эмбеддинги
считаются **на машине** — контент памяти не уходит наружу (приватность). `embed`
пробует два формата запроса по очереди: батч (`POST /api/embed` с
`{"model", "input": [...]}`, один round-trip на все тексты), а при 404 — legacy
per-text (`POST /api/embeddings` с `{"prompt": ...}`) для старого Ollama без батча.
Транзиентные сбои (обрывы соединения, таймауты, 5xx) ретраятся с ограниченным
экспоненциальным backoff (повторно используется `retry_with_backoff` BOB-002);
перманентные (4xx, битое тело, несовпадение размерности) поднимаются сразу.
`build_embedder` читает секцию `embeddings` (`base_url`/`model`/`dim`) — провайдер
свопается конфигом.

`OllamaReranker` реализует порт `Reranker` как **Ollama-as-scorer**: нативного
rerank-эндпоинта у Ollama нет (открытый Q1), поэтому адаптер оценивает каждую пару
`(query, candidate)`, спрашивая у локальной модели одно число релевантности
`[0, 1]` через OpenAI-совместимый `/v1/chat/completions`, сортирует кандидаты по
убыванию скора и оставляет top-N. Скор парсится терпимо (первое число в ответе,
кламп в `[0, 1]`). **Аддитивный контракт — реранк никогда не роняет recall:** при
недоступности эндпоинта, исчерпании ретраев или непарсящемся скоре адаптер
возвращает вход **без изменений** (гибридный порядок) и логирует одну строку — Боб
не теряет извлечение из-за того, что реранк был недоступен. `build_reranker` читает
секцию `reranker`; реранк выключен по умолчанию (`enabled` false) — тогда фабрика
возвращает `None`, и пайплайн просто пропускает реранкинг.

### Вектор-стор (sqlite-vec)

`MemoryVectorStore` держит vec0-таблицу `memory_vec` (загружаемое расширение
`sqlite-vec`, `float[1024]`) в синхроне с архивом памяти. Расширение грузится на
(aiosqlite) соединение **до** применения схемы, потому что vec0-таблица — часть
`schema.sql`. Вектора кладутся с привязкой к исходной строке по `(source, src_id)`,
где `source` — `semantic` или `episodic`. Два пути записи питают стор: идемпотентный
**бэкфилл** существующих фактов/эпизодов (`backfill`, батчами по 64, на каждом
старте — как FTS-бэкфилл, без дублей) и **on-write** эмбеддинг свежесохранённой
строки (`embed_row`, идемпотентно). Оба пути **best-effort**: недоступный в рантайме
эмбеддер (Ollama выключен) пропускается и логируется, а не роняет запись или старт —
recall просто деградирует на keyword-only до следующего доступного эмбеддера.
`knn(vector, k)` обслуживает чтение: sqlite-vec KNN по каждой партиции-источнику,
JOIN к контенту исходной строки, слияние и top-`k` по возрастанию дистанции. Без
поданного эмбеддера стор инертен — таблица существует, но пустая (keyword-only).
Внутренние имена таблиц/колонок — фиксированные литералы (не пользовательский ввод),
а вектор, ключ партиции и `k` параметризованы.

### Гибридный recall (FTS5 + sqlite-vec → RRF)

`HybridMemoryRecall` реализует порт `MemoryRecall` как **drop-in** замену
keyword-only `Fts5MemoryRecall`: потребители (`handle_message`, `recall_memory`,
`search_memory`) по-прежнему зовут `recall(query, k) → [Recalled]` и не знают, что
извлечение отрастило семантическую половину. Внутри он гоняет два поиска по одному
архиву и сливает их **Reciprocal Rank Fusion** (RRF-скор = сумма по спискам
`1 / (k0 + rank)`, **k0 = 60** — значение из оригинальной статьи Cormack и де-факто
дефолт):

- **семантика** — эмбеддит запрос через инъецированный `Embedder` и гоняет
  sqlite-vec KNN по `memory_vec` (находит по смыслу даже без общих слов);
- **keyword** — FTS5 BM25 по семантическому + эпизодическому индексам (переиспользует
  `Fts5MemoryRecall`).

Из каждой половины берётся широкий пул кандидатов (по 20), пул сливается RRF и
дедуплицируется по содержимому; элемент, попавший в **оба** списка, копит больший
слитый скор — в этом и смысл рангового фьюжна. **Мягкий фоллбэк:** если эмбеддер
отсутствует или бросил (Ollama выключен), recall деградирует на чистый FTS5
keyword — Боб «не теряет память», теряет лишь семантическую половину; сбой логируется,
а не пробрасывается. **Реранкер (аддитивно):** опциональный `Reranker`-коллаборатор
переоценивает широкий слитый top-K и подрезает до тесного top-N; без поданного
реранкера (или при выключенном/недоступном) гибридный порядок возвращается как есть —
реранк никогда не ухудшает извлечение.

### Connection-kernel (SQLite + FTS5)

`SqliteConnection` (`persistence/connection.py`) — общий connection/schema-kernel
персистентности (BOB-062.7b). Это чистое I/O, не композиция: `initialize()`
открывает соединение в режиме WAL, включает `foreign_keys`, грузит расширение
sqlite-vec **до** применения схемы (vec0-таблица `memory_vec` — часть `schema.sql`)
и один раз идемпотентно применяет **единую** `schema.sql` через `executescript`
(таблицы + FTS5-триггеры + `memory_vec` связаны одним ordering'ом). Kernel владеет
generic key/value-стором (`kv_set`/`kv_get`) и выставляет живое соединение через
**`.connection`-шов** (`@property`), которым кормятся все 13 долговечных сторов всех
модулей + memory-репозиторий. Как schema/migration-owner kernel держит и
proactivity-специфичную миграцию `_migrate_pursuit_stopped` (помечена
`# BOB-062: proactivity-specific, future relocation` — оставлена в kernel'е, потому
что он применяет весь `schema.sql`; будущий срез может унести её в proactivity). Рядом
живёт guarded-миграция `_migrate_conversation_floor_participants` (BOB-066 .1):
`CREATE TABLE IF NOT EXISTS` не трогает уже существующую таблицу, поэтому база,
записанная до появления столбца `conversation_floor.participants`, получает его
одноразовым `ALTER TABLE ... ADD COLUMN participants TEXT` под стражей `PRAGMA
table_info` (идемпотентный no-op, когда столбец уже есть). Аддитивно и без потери
данных: legacy-строка берёт `NULL`, который стор читает как пустой `()` = legacy-режим
floor (любой участник продолжает нить, ровно поведение до BOB-066 — бэкфилл не нужен).

Модульно-специфичный SQL живёт **в самих сторах** (каждый параметризован, `?`, без
f-strings): memory-репозиторий (`bob.memory.adapters.SqliteMemoryRepo`) маппит
`EpisodicEvent`/`SemanticFact` в строки, держит memory-миграции и FTS5-бэкфилл; его
recall-/вектор-адаптеры (`Fts5MemoryRecall`, `HybridMemoryRecall`,
`MemoryVectorStore`) — тоже в модуле `memory` (см. `domains/memory/README.md`).
Kernel сам по себе не зависит ни от одного бизнес-контекста.

`KvAllowlistStore` (`bob.social.adapters`) реализует порт `AllowlistStore`, персистя
множество allowlisted `user_id` как JSON-массив под единым ключом `authz.allowlist` в
таблице `kv` connection-kernel'а (через его `kv_get`/`kv_set`). SQL параметризован, а
`/authorize` переживает рестарт: свежий процесс читает тот же ключ и видит те же
гранты. Декодирование защищено по форме (не-список или не-int элементы игнорируются).

`SoulStore` (`bob.social.adapters`) — файловый reader/writer артефактов `data/soul/`:
`SOUL.md`, JSON-профили (`taste_profile`, `mood`, `phantom_prefs`) и append-only
`genesis_log.md`. Каталог создаётся по требованию.

Проактивные сторы (`SqliteProactivityStore` над `proactivity_state`,
`RepoProactivitySources` над `episodic_log`) переехали в `bob.proactivity.adapters`
(BOB-062.3) и описаны в `domains/proactivity/README.md`; они, как и все прочие сторы,
читают connection-kernel через его `.connection`-шов.

### Конфигурация

`ConfigLoader` строит эффективную конфигурацию слоями: встроенные
`DEFAULT_CONFIG` → опциональный YAML (`yaml.safe_load`) → переменные окружения
(префикс `BOB_`, `__` для вложенности, например `BOB_LLM__TIER1_MODEL` →
`config["llm"]["tier1_model"]`). Поздние слои deep-merge поверх ранних.

**Два токена ботов (BOB-003)** не выражаются generic-правилом вложенности, поэтому
special-cased в `_TOKEN_ENV_MAPPING`: env `BOB_TELEGRAM__TOKEN` →
`telegram.bob.token` (иначе попал бы в `telegram.token`), env `GUPPI_TELEGRAM__TOKEN`
→ `telegram.guppi.token` (нестандартный префикс `GUPPI_`, который `BOB_`-механизм не
видит). Маппинг применяется после generic-env-слоя, поэтому env по-прежнему
выигрывает. Токены — единственные секреты в `telegram` (только из env); остальное
(`chat_id`, `bob.topic_id`, `owner_id`, `poll_timeout`, `allowed_chat_ids`) —
non-secret и может прийти из YAML.

**Память (BOB-011).** Секция `embeddings` (`base_url`, `model` по умолчанию
`bge-m3`, `dim` 1024) настраивает локальный эмбеддер; секция `reranker`
(`enabled` по умолчанию `false`, `base_url`, `model`, `top_n`) — опциональный
реранкер. Целочисленные значения (`dim`, `top_n`) терпят строковую форму из env, а
`reranker.enabled` — строковые `true`/`false`. По умолчанию обе секции указывают на
локальный Ollama (`http://localhost:11434`) — приватно, контент памяти не уходит
наружу.

## Инварианты

- Адаптеры реализуют порты `bob.<module>.ports` / `bob.kernel.ports`; связывание —
  только в composition root `src/bob/runtime/`.
- Один процесс поллит обоих ботов; кросс-бот дедуп по `(chat_id, message_id)` —
  групповое сообщение обрабатывается ровно один раз.
- Изоляция ботов: сбой поллинга одного бота не роняет другого.
- GUPPI шлёт ответы только своим ботом; reject виден только в разрешённой группе
  (DM незнакомца его не триггерит); owner-команды — только для owner в General.
- Connection-kernel (`SqliteConnection`) — единственный владелец соединения/схемы:
  один WAL-коннекшн, единая `schema.sql` одним `executescript`, общий `.connection`-шов
  и kv-стор кормят все сторы; сам kernel не зависит ни от одного бизнес-контекста.
- Весь SQL параметризован (`?`, без f-strings) и живёт в сторе-владельце данных.
- Пользовательский текст для FTS5 санитизируется (без инъекций/синтаксических ошибок).
- Контент памяти не уходит наружу: эмбеддинги и реранкинг считаются локально
  (Ollama на машине), вектора — в той же локальной SQLite (`memory_vec`).
- Гибрид-recall (`HybridMemoryRecall`) — drop-in за `MemoryRecall`; при недоступном
  эмбеддере мягко деградирует на чистый FTS5 keyword (память не теряется).
- Эмбеддинг строк best-effort: недоступный в рантайме эмбеддер пропускается и
  логируется, не роняя запись или старт (recall становится keyword-only).
- Реранкер аддитивен: при отсутствии/выключении/недоступности возвращает вход без
  изменений — реранк никогда не ухудшает извлечение.
- API-ключ и токен берутся из конфигурации/env и не инлайнятся; на Tier 0 нет
  заголовка `Authorization`.
- Везде `yaml.safe_load` и `pathlib`.
- Gateway не содержит логики Higher Mind / LLM / памяти.
- Единый гейт авторизации в gateway fail-closed: при подключённом авторизаторе
  неразрешённый чат/пользователь молча отброшены, без обхода.
- Rich-отправка деградирует на plain при любой ошибке — пользователь не видит
  ошибку транспорта, ответ никогда не теряется.
- Приём at-least-once (BOB-070): offset апдейта сдвигается только после успешного
  `route()`; при сбое offset не двигается и батч встаёт на упавшем апдейте, а
  Telegram переприсылает всё ≥ offset на следующем тике (потери нет, порядок цел).
- Poison-cap (BOB-070): апдейт, стабильно падающий в `route()`, после
  `_MAX_ROUTE_ATTEMPTS` (=3) попыток громко логируется и пропускается — приём не
  зацикливается; успех сбрасывает per-`(identity, update_id)` счётчик неудач.
- Сетевой обрыв long-poll изолирован (BOB-070): `TelegramNetworkError` из
  `get_updates` ловится наравне с `OSError`/`RuntimeError`/`TimeoutError` — `return
  0` и ретрай, тик и poll-таск живы, другие боты не задеты.
- В группе стриминга нет (Вариант A, BOB-008): во время генерации — повторяемый
  `sendChatAction("typing")` в тред Боба, готовый ответ — **один**
  `send_rich_message` с plain-fallback.
- Edit-стриминг, draft-стриминг и 3.0с-троттл флуд-контроля удалены — гейтвей
  упрощён до typing → rich-финал → plain-fallback.
- `MarkdownToRichMessage` и `RichMessageSerializer` — чистые и детерминированные
  (без I/O, сети, часов).
- Allowlist персистится в таблице `kv` (параметризованный SQL) и переживает рестарт.
- Проактивное состояние per-persona персистится в `proactivity_state`; `save` не
  трогает `mute_until`, поэтому запись состояния не сбрасывает срочный мьют.
- `/quiet`/`/wake` доступны только owner в General; без поданного proactivity-store
  деградируют в no-op.

## API

Модуль `src/bob/infrastructure/telegram/multibot.py`:
- `MultiBotGateway(*, registry, bus, poll_timeout, authorizer=None,
  reply_typing_interval=4.0, reply_clock=time.monotonic, reply_sleep=asyncio.sleep)`
  — `async poll_once()` → `int`, `async route(update, identity)` → `bool`,
  `reply_gateway(identity)` → `ReplyGateway` (`typing_indicator(chat_id)` +
  `reply(chat_id, markdown, thinking)`); свойство `registry`. Реплеи-параметры
  по умолчанию живые (реальные часы/sleep + каденс typing ~4с); тесты
  инъецируют детерминированные заглушки.
- `BotRegistry` — `register(*, identity, bot, scope)`, `get(identity)`, `all()`,
  `scope_of(identity)`.
- `BotIdentity` (`BOB`/`GUPPI`), `BotScope(chat_id, topic_id)` с
  `matches(*, chat_id, message_thread_id)`, `BotRegistration`.

Модуль `src/bob/infrastructure/telegram/guppi.py`:
- `GuppiHandler(*, bot, authorizer, general_chat_id, proactivity_store=None,
  clock=None, persona_id="bob")` — `async reject(*, chat_id, thread_id)`,
  `async handle_general_command(*, text, user_id, chat_id)` → `bool` (включая
  `/quiet`/`/wake`, когда подан proactivity-store).
- `GUPPI_REJECT_TEXT`, `ProactivityStoreLike`.

Модуль `src/bob/infrastructure/telegram/gateway.py`:
- `TelegramGateway(*, bot, bus, poll_timeout, typing_interval, clock, sleep, authorizer=None, reply_thread_id=None)` —
  `async poll_once()`, `async intake(update)`,
  `typing_indicator(*, chat_id)` → async-контекст (keepalive `sendChatAction("typing")`
  каждые `typing_interval`, отменяется на выходе),
  `async reply(*, chat_id, markdown, thinking=None)`.
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

Модуль `src/bob/infrastructure/persistence/connection.py`:
- `SqliteConnection(db_path)` — `async initialize()` (open+WAL+foreign_keys, загрузка
  sqlite-vec, `executescript(schema.sql)`, миграции), `async close()`,
  `async journal_mode()`, `async kv_set(key, value)/kv_get(key)`, свойства
  `db_path` и `connection` (`.connection`-шов — живое `aiosqlite`-соединение,
  которым кормятся все сторы).

Memory-репозиторий (`SqliteMemoryRepo`), вектор-стор (`MemoryVectorStore`) и
recall-адаптеры (`Fts5MemoryRecall`, `HybridMemoryRecall`) уехали в
`bob.memory.adapters` — их API см. в `domains/memory/README.md`.

Модуль `src/bob/infrastructure/llm/ollama_embedder.py`:
- `OllamaEmbedder(*, base_url, model, dim, timeout_seconds=120.0, sleep=None)` —
  `async embed(texts)` → `list[list[float]]`.

Модуль `src/bob/infrastructure/llm/embedder_factory.py`:
- `build_embedder(config)` → `OllamaEmbedder` (из секции `embeddings`).

Модуль `src/bob/infrastructure/llm/ollama_reranker.py`:
- `OllamaReranker(*, base_url, model, top_n, timeout_seconds=30.0, max_attempts=2,
  sleep=None)` — `async rerank(query, candidates)` → `list[Recalled]`.

Модуль `src/bob/infrastructure/llm/reranker_factory.py`:
- `build_reranker(config)` → `OllamaReranker | None` (из секции `reranker`;
  `None`, когда реранк выключен/отсутствует).

Модуль `src/bob/social/adapters/allowlist_store.py`:
- `KvAllowlistStore(kv)` — `async load()` → `set[int]`, `async add(user_id)`,
  `async remove(user_id)` (kv-стор connection-kernel'а).

Модуль `src/bob/social/adapters/soul_store.py`:
- `SoulStore(soul_dir)` — `soul_exists()`, `read_soul()`, `write_soul()`,
  `read_json()/write_json()`, `append_genesis_log()/read_genesis_log()`.

Проактивные сторы (`SqliteProactivityStore`, `RepoProactivitySources`) — в
`bob.proactivity.adapters`, их API см. в `domains/proactivity/README.md`.

Модуль `src/bob/infrastructure/config/loader.py`:
- `ConfigLoader(*, yaml_path, env=None)` — `load()` → `Config`; `DEFAULT_CONFIG`
  (включая секции `embeddings.*` и `reranker.*`).

## Тесты

Тесты: `tests/infrastructure/telegram/test_gateway.py`,
`tests/infrastructure/telegram/test_gateway_authz.py`,
`tests/infrastructure/telegram/test_gateway_hardening.py`,
`tests/infrastructure/telegram/test_multibot.py`,
`tests/infrastructure/telegram/test_multibot_hardening.py`,
`tests/infrastructure/telegram/test_guppi.py`,
`tests/infrastructure/telegram/test_multibot_guppi.py`,
`tests/infrastructure/telegram/test_e2e_two_bot.py`,
`tests/infrastructure/telegram/test_rich.py`,
`tests/infrastructure/telegram/test_rich_hardening.py`,
`tests/infrastructure/llm/test_openai_compat.py`,
`tests/infrastructure/llm/test_openai_compat_parsers.py`,
`tests/infrastructure/llm/test_factory.py`,
`tests/infrastructure/llm/test_ollama_embedder.py`,
`tests/infrastructure/llm/test_ollama_embedder_hardening.py`,
`tests/infrastructure/llm/test_embedder_factory.py`,
`tests/infrastructure/llm/test_ollama_reranker.py`,
`tests/infrastructure/llm/test_ollama_reranker_hardening.py`,
`tests/infrastructure/llm/test_reranker_factory.py`,
`tests/infrastructure/persistence/test_connection.py`,
`tests/infrastructure/persistence/test_sqlite_repo.py`,
`tests/infrastructure/persistence/test_fts_recall.py`,
`tests/infrastructure/persistence/test_vector_store.py`,
`tests/infrastructure/persistence/test_vector_store_hardening.py`,
`tests/infrastructure/persistence/test_hybrid_recall.py`,
`tests/infrastructure/persistence/test_allowlist_store.py`,
`tests/infrastructure/persistence/test_soul_store.py`,
`tests/infrastructure/persistence/test_proactivity_store.py`,
`tests/infrastructure/persistence/test_proactivity_sources.py`,
`tests/infrastructure/telegram/test_guppi_proactivity.py`,
`tests/infrastructure/config/test_loader.py`.
