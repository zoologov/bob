<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Слой application — GUPPI (рантайм, use-cases, роутер)

Оркестрация Боба: жизненный цикл процесса, шина событий, use-cases и политика
LLM-роутера. Зависит от домена через порты-протоколы и **не** импортирует
инфраструктуру (граница проверяется `tests/application/test_layering.py`).

## Спецификация

### Модули

- **runtime/agent.py** — `AgentRuntime`, жизненный цикл GUPPI поверх одного
  asyncio-цикла: start/stop и супервизия фоновых задач.
- **runtime/event_bus.py** — `AsyncEventBus`, in-process publish/subscribe с
  конкурентным fan-out и изоляцией ошибок обработчиков.
- **runtime/events.py** — `MessageReceived`, нормализованное событие сообщения
  (принадлежит приложению, не транспорту), и константа имени `MESSAGE_RECEIVED`.
- **runtime/heartbeat.py** — `periodic()`, обёртка одноразового тика в
  супервизируемый повторяющийся фоновый цикл (sleep инъецируется для
  детерминизма); `RetryPolicy` — политика backoff для ретрая транзиентных сбоев тика.
- **runtime/retry.py** — `retry_with_backoff()`, ограниченный экспоненциальный
  backoff на транзиентных сбоях; `is_transient()` классифицирует транзиент/перманент.
- **authz/authorizer.py** — `Authorizer`, чистая политика доступа
  owner/allowlist/chat-scope поверх порта `AllowlistStore`.
- **capabilities/registry.py** — `CapabilityRegistry`, индекс навыков GUPPI
  (`register`/`manifest`/`dispatch`/`describe`); `UnknownCapabilityError`.
- **capabilities/tool_loop.py** — `ToolLoop`, петля «модель ↔ инструменты» до
  финального текста (turn-cap, GUPPI исполняет вызовы).
- **capabilities/recall_memory.py** — `make_recall_memory_capability()`, первый
  реальный навык `recall_memory` — тонкая обёртка над `MemoryRecall`.
- **router/llm_router.py** — `LLMRouter`, классификация задачи, селективная
  редакция приватности и fallback тиров; `LLMRequest` (с двумя каналами
  контекста — `shareable_context` и `private_context`), `TaskType`.
- **usecases/handle_message.py** — `HandleMessage`, полный поток
  сообщение → ответ → персист → запоминание; `PersonalityState`,
  `EpisodeReader` (шов чтения недавней истории).
- **usecases/update_mood_from_text.py** — `UpdateMoodFromText`, шаг perceive:
  сигналы текста → `MoodDelta`.
- **usecases/extract_facts.py** — `ExtractFacts`, шаг remember на Tier 0: дистилляция
  устойчивых фактов о пользователе в `semantic_memory` (best-effort).
- **usecases/run_genesis.py** — `RunGenesis`, первое пробуждение Боба.
- **usecases/heartbeat.py** — `InnerMonologueTick`, `MoodDriftTick`, `ReflectTick`.

### Рантайм (GUPPI)

`AgentRuntime` владеет start/stop и супервизирует фоновые задачи (heartbeat,
polling). Он транспорт- и провайдер-агностичен: коллабораторы приходят
callable-фабриками корутин, так что рантайм прогоняется на фейках. `start()` и
`stop()` идемпотентны; `stop()` корректно отменяет задачи;
`run_until_stopped()` блокирует до остановки (точка входа main-loop процесса).

`AsyncEventBus` развязывает производителей событий (Telegram-gateway) и
потребителей (use-cases): обработчики одного события исполняются конкурентно, а
упавший обработчик логируется и изолируется, чтобы не «заморить» соседей и не
уронить публикатора.

### Роутер LLM и селективная редакция приватности

`LLMRouter` — политика приложения поверх портов `LLMProvider` (Tier 0 локальный /
Tier 1 API). Для каждого запроса он: **классифицирует** задачу (`TaskType`) в
предпочтительный тир (`REPLY_TO_USER` и `GENESIS` → Tier 1; `SENTIMENT`,
`INNER_MONOLOGUE`, `REFLECT`, `EXTRACT_FACTS` → Tier 0); **селективно
редактирует** перед любым вызовом Tier 1; **откатывается** Tier 1 → Tier 0 при
сбое предпочтительного тира.

Селективная редакция (Вариант 2) делит контекст запроса на два канала по
политике назначения. `shareable_context` — история диалога, вспомненная память,
настроение, идентичность и вкус: этот материал формирует ответ Боба и
возвращается тому же пользователю, поэтому он **разрешён** на Tier 1.
`private_context` — сугубо внутренний материал (только Tier 0), который
**никогда** не прикрепляется к payload, идущему на Tier 1 (в P0.1 канал пуст, но
шов сохранён). Запрос на Tier 0 получает оба канала; запрос на Tier 1 — только
`shareable_context`. Payload собирается один раз, поэтому при откате
Tier 1 → Tier 0 уходит ровно тот же payload (с уже вырезанным
`private_context`) — инвариант держится и на пути fallback. Прежняя
over-aggressive редакция (когда на Tier 1 не доходила вообще никакая память)
делала Боба stateless; Вариант 2 это исправляет, не раскрывая внутренний
материал.

Предпочтительный тир задачи — это **умолчание**: вызывающий может задать
`LLMRequest.tier_override`, чтобы направить конкретный запрос на другой тир
(если такой провайдер подан; неизвестный override игнорируется и запрос идёт на
умолчание задачи). **Важно:** редакция привязана к политике **задачи**, а не к
выбранному тиру, поэтому ответ, опущенный override'ом на Tier 0, по-прежнему
никогда не несёт `private_context`.

### Гибридный тиринг ответа пользователю (BOB-006)

Живой ответ на reasoning-модели Tier 1 (`qwen3.7-plus`) может занимать минуты —
слишком медленно для чата. `select_reply_tier`
(`router/reply_tier_selector.py`) — чистая детерминированная эвристика по тексту
пользователя (без отдельного LLM-round-trip): casual/короткая реплика отвечается
на быстрый Tier 0 (`qwen3.6-flash`), а на качественный Tier 1 (`qwen3.7-plus`)
эскалируется только сложный ход. Эскалация — когда ход требует инструментов
(`needs_tools`) **или** сообщение выглядит сложным: длиннее 240 символов, более
одного знака вопроса, содержит блок кода или несёт ключевое слово глубины
(`объясни`, `проанализируй`, `сравни`, `напиши`, …; целыми словами,
регистронезависимо). `HandleMessage` зовёт селектор и передаёт результат роутеру
как `LLMRequest.tier_override`.

### Use-cases (поток, память и Genesis)

`HandleMessage` (подписан на `MessageReceived`) проводит один ход
perceive → decide → act → persist → remember: обновляет настроение через
`UpdateMoodFromText`, воспроизводит недавнюю историю диалога
(`recent_episodes(k)` через шов `EpisodeReader`), делает recall памяти
(`MemoryRecall`, FTS5) и собирает `shareable_context` (история, память,
настроение, идентичность, вкус), получает ответ от роутера (`REPLY_TO_USER` +
селективная редакция / fallback Tier 0; тир ответа выбирается гибридно через
`select_reply_tier` и передаётся как `tier_override`), стримит его через gateway,
сохраняет эпизод и снапшот настроения. Именно прикрепление `shareable_context`
к вызову даёт Бобу память — он помнит имя, названное ход назад.

После ответа отрабатывает шаг **remember**: `ExtractFacts` (Tier 0,
`EXTRACT_FACTS`) дистиллирует устойчивые факты о пользователе (имя,
предпочтения, важные люди, решения) в `semantic_memory` (FTS5), чтобы recall на
следующих ходах поднял их обратно в контекст. Разбор устойчив к reasoning-обёртке:
парсер пробует по очереди сырой текст, тело markdown-блока и первый
сбалансированный JSON-массив `[...]` (терпя преамбулу-рассуждение и текст после
массива); невалидный JSON или записи без `content` дают ноль фактов. Шаг
best-effort: он никогда не бросает исключение, так что сбойная локальная модель не
ломает уже отправленный ответ. Память переживает рестарт.

`UpdateMoodFromText` — шаг perceive: читает сентимент (классификация на Tier 0),
частоту сообщений, время суток (из `Clock`) и присутствие, превращая их в
`MoodDelta`, который применяет чистый `Mood`.

`RunGenesis` генерирует и персистит идентичность Боба один раз: при отсутствии
`SOUL.md` загружает шаблоны `bob-soul/`, генерирует личность через Tier 1
(`GENESIS`), валидирует JSON (`GenesisError` при невалиде) и пишет артефакты
через `SoulStore`. Повторный запуск — no-op.

### Heartbeat-тики

`InnerMonologueTick` (Боб думает на Tier 0, сентимент мысли нудит настроение),
`MoodDriftTick` (дрейф к baseline, гомеостаз), `ReflectTick` (рефлексия на
Tier 0, сохраняемая как эпизод). Все читают и пишут общий `PersonalityState`.
Внутренняя жизнь не эскалирует на удалённый API.

### Авторизация (owner + allowlist + chat-scope)

`Authorizer` — чистая политика доступа поверх порта `AllowlistStore`, без
транспорта и SQL. Боб приватен: общаться могут только **owner** и
**авторизованные** пользователи и только внутри **разрешённых чатов**.
`is_authorized(user_id, chat_id)` сперва проверяет chat-scope (сообщение из чата
вне `allowed_chat_ids` отвергается для всех, включая owner — утёкший токен в
чужом чате мёртв), затем внутри разрешённого чата пропускает owner всегда, а
любого другого — только если он в персистентном allowlist. `owner_id` и
`allowed_chat_ids` неизменны на процесс; динамический allowlist читается из
хранилища на каждом решении, так что грант на одном процессе виден везде.
`authorize`/`deauthorize` мутируют allowlist и персистят его через
`AllowlistStore`, поэтому `/authorize` переживает рестарт. Единый гейт-применение
живёт в gateway (инфраструктура) — без обхода.

### Резилентность тиков (retry/backoff + изоляция)

`retry_with_backoff(operation, *, max_attempts, base_delay_seconds, max_delay_seconds, sleep)`
повторяет операцию на **транзиентных** сбоях с ограниченным экспоненциальным
backoff. `is_transient(error)` классифицирует, что стоит ретраить: сетевые сбои
соединения aiohttp (включая `Server disconnected`), таймауты и ответы 5xx;
перманентная ошибка (4xx, баг, структурная) пробрасывается сразу, чтобы backoff
не маскировал дефект. `sleep` инъецируется (по умолчанию `asyncio.sleep`), так
что расписание backoff проверяется тестами без реальных ожиданий.

Резилентность слоёная (изнутри наружу): `periodic(...)` оборачивает тик в
`retry_with_backoff` (когда задана `RetryPolicy`), затем изолирует то, что тик
**в итоге** бросил, логируя и продолжая цикл — так одна сбойная итерация не валит
heartbeat и не глушит соседние тики; отмена (на остановке рантайма)
пробрасывается чисто.

### Capability-шов (реестр + tool-loop + первый навык)

Стабильный шов навыков, на котором поедут «Память» и «Автономность» — фундамент,
не полная плагин-машинерия (sandbox/дискавери/self-creation — позже за тем же
контрактом `Capability`). По канону GUPPI — **исполнитель** навыков.

- `CapabilityRegistry` — индекс того, что Боб умеет: `register(capability)`
  (имя уникально), `manifest()` (рендер навыков в OpenAI-определения `tools` для
  модели), `dispatch(name, args)` (исполнить навык = **GUPPI исполняет**;
  неизвестный навык → `UnknownCapabilityError`), `describe()` (короткий
  прозаический перечень для системного промпта, чтобы Боб **знал, что умеет**).
- `ToolLoop` — act-сторона шва: даёт модели манифест как `tools` через
  `ToolCallingProvider.complete_with_tools`; если модель вернула `tool_calls` —
  диспатчит каждый через реестр, дописывает ход ассистента и `tool`-результат и
  повторяет, пока не финальный текст. Число ходов ограничено `max_turns` (по
  умолчанию 6), чтобы не зациклиться; неизвестный навык не фатален — ошибка
  возвращается как результат, чтобы модель восстановилась.
- `recall_memory` (`make_recall_memory_capability(recall)`) — первый реальный
  навык: тонкая обёртка над `MemoryRecall` (архивный keyword-recall), `permission`
  `safe`. Обкатывает петлю e2e без нового I/O; агентный `search_memory` с
  векторами — отдельный эпик «Память».

`HandleMessage` подхватывает шов опционально: tool-loop включается, только когда
зарегистрированы навыки **и** подан `ToolCallingProvider` (в P0-сборке — провайдер
Tier 1); иначе ход идёт прежним plain-путём роутера. Манифест навыков попадает в
системный промпт (преамбула о GUPPI как исполнителе).

## Инварианты

- `application` не импортирует `bob.infrastructure` (включая `TYPE_CHECKING`).
- Payload LLM-запроса собирается один раз; `private_context` никогда не доходит до
  Tier 1, в том числе на пути fallback Tier 1 → Tier 0; `shareable_context`
  (история/память/настроение/идентичность/вкус) на Tier 1 разрешён.
- Редакция приватного контекста привязана к политике задачи, а не к выбранному
  тиру: `tier_override`, опускающий ответ на Tier 0, не раскрывает `private_context`.
- Шаг remember (`ExtractFacts`) best-effort: ошибка извлечения фактов не роняет
  уже отправленный ответ.
- Время берётся только из инъецированного `Clock`.
- Ошибка одного heartbeat-тика изолируется и не роняет остальные; транзиентный
  сбой ретраится с backoff, перманентный пробрасывается сразу.
- Genesis идемпотентен по on-disk флагу `SOUL.md`.
- Доступ закрыт по политике owner/allowlist/chat-scope (fail-closed): chat-scope
  связывает даже owner; решение читает динамический allowlist на каждом вызове.
- Capability-шов forward-compatible: новый навык — регистрация объекта, потребители
  (реестр, tool-loop, `HandleMessage`) не меняются; tool-loop ограничен turn-cap.

## API

Модуль `src/bob/application/router/llm_router.py`:
- `LLMRouter(*, providers: Mapping[int, LLMProvider])` — `async run(request)` → `str`.
- `LLMRequest` — поля `shareable_context` / `private_context` (два канала контекста)
  и `tier_override: int | None` (направить запрос на конкретный тир в обход умолчания
  задачи); `TaskType` (значения `REPLY_TO_USER`, `GENESIS`, `SENTIMENT`,
  `INNER_MONOLOGUE`, `REFLECT`, `EXTRACT_FACTS`).

Модуль `src/bob/application/router/reply_tier_selector.py`:
- `select_reply_tier(message: str, *, needs_tools: bool = False)` → `int` — чистая
  эвристика выбора тира ответа: `0` (быстрый flash) для casual/короткого хода, `1`
  (качественный plus) при `needs_tools` или сложном сообщении (длина, мульти-вопрос,
  код, ключевое слово глубины). Детерминирована.

Модуль `src/bob/application/runtime/agent.py`:
- `AgentRuntime(*, background_tasks=None)` — `start()`, `stop()`,
  `run_until_stopped()`, `state`, `is_running`.

Модуль `src/bob/application/runtime/event_bus.py`:
- `AsyncEventBus` — `subscribe(event_name, handler)`, `async publish(event)`.

Модуль `src/bob/application/runtime/events.py`:
- `MessageReceived`, `MESSAGE_RECEIVED`.

Модуль `src/bob/application/runtime/heartbeat.py`:
- `periodic(tick, *, interval_seconds, sleep=None, retry=None)` → фабрика фоновой задачи.
- `RetryPolicy(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=30.0)`.

Модуль `src/bob/application/runtime/retry.py`:
- `retry_with_backoff(operation, *, max_attempts, base_delay_seconds, max_delay_seconds, sleep)` → `T`.
- `is_transient(error)` → `bool`.

Модуль `src/bob/application/authz/authorizer.py`:
- `Authorizer(*, owner_id, allowed_chat_ids, store)` — `is_owner(user_id)`,
  `async is_authorized(*, user_id, chat_id)`, `async authorize(user_id)`,
  `async deauthorize(user_id)`.

Модуль `src/bob/application/capabilities/registry.py`:
- `CapabilityRegistry` — `register(capability)`, `manifest()` → `list[ToolDefinition]`,
  `async dispatch(name, args)`, `describe()`, свойство `is_empty`; `UnknownCapabilityError`.

Модуль `src/bob/application/capabilities/tool_loop.py`:
- `ToolLoop(*, provider, registry, max_turns=6)` — `async run(messages)` → `str`.

Модуль `src/bob/application/capabilities/recall_memory.py`:
- `make_recall_memory_capability(recall)` → `Capability` (навык `recall_memory`).

Модуль `src/bob/application/usecases/handle_message.py`:
- `HandleMessage` — `async handle(event)`; `PersonalityState`, `EpisodeReader`,
  опциональные `registry` и `tool_provider` (включают capability tool-loop).

Модуль `src/bob/application/usecases/update_mood_from_text.py`:
- `UpdateMoodFromText` — `async run(mood, signals)` → `Mood`; `TextSignals`.

Модуль `src/bob/application/usecases/extract_facts.py`:
- `ExtractFacts` — `async run(*, user_message, reply=None)` (best-effort); `FactWriter`.

Модуль `src/bob/application/usecases/run_genesis.py`:
- `RunGenesis` — `async run()` → `GenesisResult`; `GenesisError`.

Модуль `src/bob/application/usecases/heartbeat.py`:
- `InnerMonologueTick`, `MoodDriftTick`, `ReflectTick` — каждый `async run()`.

## Тесты

Тесты: `tests/application/router/test_llm_router.py`,
`tests/application/router/test_llm_router_hardening.py`,
`tests/application/runtime/test_agent.py`,
`tests/application/runtime/test_event_bus.py`,
`tests/application/runtime/test_heartbeat_scheduler.py`,
`tests/application/runtime/test_retry.py`,
`tests/application/authz/test_authorizer.py`,
`tests/application/test_capability_registry.py`,
`tests/application/test_tool_loop.py`,
`tests/application/test_tool_loop_hardening.py`,
`tests/application/test_recall_memory_capability.py`,
`tests/application/usecases/test_handle_message.py`,
`tests/application/usecases/test_extract_facts.py`,
`tests/application/usecases/test_update_mood_from_text.py`,
`tests/application/usecases/test_run_genesis.py`,
`tests/application/usecases/test_run_genesis_hardening.py`,
`tests/application/usecases/test_heartbeat.py`,
`tests/application/test_layering.py`.
