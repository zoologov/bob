<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T08:49:35.850635+00:00 · coverage 100% (`bob-application`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

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
- **runtime/heartbeat.py** — `periodic()`, обёртка одноразового тика в
  супервизируемый повторяющийся фоновый цикл (sleep инъецируется для
  детерминизма); `RetryPolicy` — политика backoff для ретрая транзиентных сбоев тика.
- **runtime/retry.py** — `retry_with_backoff()`, ограниченный экспоненциальный
  backoff на транзиентных сбоях; `is_transient()` классифицирует транзиент/перманент.
- **runtime/intake/** — concurrency-развязка между поллером и Бобом (BOB-066 Срез 2.1):
  `ChatDispatcher` (быстрый неблокирующий `submit` + по воркеру на `chat_id`),
  `ChatInbox` (per-chat буфер + debounce, фокус минует окно), `TurnScope` (per-turn
  rng-изоляция) и `make_focus_predicate`. `RoomStreamReader` + `AmbientBatchReader`
  (`runtime/intake/room_stream_reader.py`, BOB-072) — холистическое чтение осевшей
  ambient-пачки одним batch-read'ом за флагом `presence.stream_read`. Подробнее — раздел
  «Intake-развязка» ниже.
- **authz/authorizer.py** — `Authorizer`, чистая политика доступа
  owner/allowlist/chat-scope поверх порта `AllowlistStore`.
- **capabilities/registry.py** — `CapabilityRegistry`, индекс навыков GUPPI
  (`register`/`manifest`/`dispatch`/`describe`); `UnknownCapabilityError`.
- **capabilities/tool_loop.py** — `ToolLoop`, петля «модель ↔ инструменты» до
  финального текста (turn-cap, GUPPI исполняет вызовы).
- **capabilities/recall_memory.py** — `make_recall_memory_capability()`, тонкий
  *авто*-recall `recall_memory` — обёртка над `MemoryRecall`.
- **capabilities/search_memory.py** — `make_search_memory_capability()`, агентный
  навык `search_memory`: Боб сам ищет по всему архиву через гибрид-recall (BOB-011).
- **router/llm_router.py** — `LLMRouter`, классификация задачи, селективная
  редакция приватности и fallback тиров (Tier1 → Tier0 — только на аварии связи,
  вердикт берётся из общего `fallback_policy`, bob-41o); `LLMRequest` (с двумя каналами
  контекста — `shareable_context` и `private_context`), `TaskType`. Опциональный
  Tier-1 rate-cap `tier1_max_concurrency` (BOB-072): семафор на число ОДНОВРЕМЕННЫХ
  Tier-1-вызовов; `None`/`<= 0` (по умолчанию) → без гейта, байт-в-байт.
- **reliability.py** — `call_with_retry`, ограниченный async-ретрай ЛЮБОГО сбоя
  essential-шага (с инъектируемым sleep) для принципа «полный Боб или честный
  GUPPI-нотис» (BOB-049 .3). Отличается от `runtime/retry.retry_with_backoff`
  (тот ретраит только transient): для пользовательского хода любой сбой
  суждения/генерации → ретрай, затем честный GUPPI-нотис, а не деградированный
  полу-ответ.
  <!-- beadloom:track=src/bob/application/reliability.py -->
- **router/fallback_policy.py** — `should_fall_back(error)`, чистое ядро вердикта «это
  авария канала (уходим на более слабую модель) или наш дефект (показываем)» (BOB-087.E1),
  общее для обоих этажей тиринга (bob-41o). Подробности — в SPEC узла `router`.
- **usecases/decide_response.py** — `DecideResponse`, тонкий use-case над швом
  семантического суждения (BOB-049): собирает `ResponseContext` из частей хода и
  делегирует решение REPLY/REACT/IGNORE инъецированному `ResponseJudge`.
- **usecases/handle_message.py** — `HandleMessage`, **тонкий оркестратор** хода
  сообщение → ответ → персист → запоминание (BOB-062.6b, #9): `handle(event, scope=None)`
  проводит фазы perceive → who → gate → compose+guard → post-effects, делегируя ~14 когезивным
  коллабораторам, разложенным по вертикалям (personality/conversation/social/capabilities). Под
  intake-развязкой (BOB-066) воркер зовёт его с per-turn `TurnScope`, чей `rng` прокидывается во
  все seeded-draw хода (INV-4); без scope — откат на per-boot rng (legacy идентично). Двое
  живут в этом слое — `EssentialRunner` и `PreComposeGate` (ниже). `__init__` — композиционный
  корень, собирающий коллабораторов из инъектированных швов (`PersonalityState`, `EpisodeReader`
  — шов чтения недавней истории); проводка мигрирует в runtime в срезе .7.
- **usecases/essential_runner.py** — `EssentialRunner`, ретрай существенных LLM-шагов
  (суждение/генерация) с ограниченным backoff, затем честный GUPPI-outage-нотис вместо
  деградированного ответа (`run`/`handle_failure`/`notify_outage`, BOB-049 .3); persist —
  инъектированный колбэк.
- **usecases/precompose_gate.py** — `PreComposeGate`, cross-domain гейты перед обычной
  компоновкой, что могут ЗАБРАТЬ ход: `maybe_route_coding` (NL-coding-intent для owner, BOB-041)
  и `maybe_permission` (privilege-flow, BOB-052).
- **usecases/update_mood_from_text.py** — `UpdateMoodFromText`, шаг perceive:
  сигналы текста → `MoodDelta`.
- **usecases/extract_facts.py** — `ExtractFacts`, шаг remember на Tier 0: дистилляция
  устойчивых фактов о пользователе в `semantic_memory` (best-effort).
- **usecases/run_genesis.py** — `RunGenesis`, первое пробуждение Боба.
- **usecases/heartbeat.py** — `InnerMonologueTick`, `MoodDriftTick`, `ReflectTick`.
- **proactivity/engine.py** — `ProactivityEngine`, drive-модель → проактивное
  сообщение (решить дёшево, говорить и платить редко); протоколы-швы
  `ProactivityStoreLike`, `ReflectionSalienceSource`, `ProactiveWindowCounter`.
- **proactivity/tick.py** — `ProactiveTick`, heartbeat-обёртка движка;
  `ProactiveRunner`.
- **proactivity/record_owner_activity.py** — `RecordOwnerActivity`, сворачивает
  сообщение owner в проактивное состояние.

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

### Intake-развязка: поллер ⇄ Боб (BOB-066 Срез 2.1)

Раньше поллер Telegram `await`-ил всю генерацию ответа прямо в цикле, поэтому следующий
`get_updates` не срабатывал, пока Боб «думал». Пакет `runtime/intake/` разрывает шов,
оставляя `AsyncEventBus` / gateway / `poll_once` нетронутыми — быстрым стал только
обработчик за швом. Подписчик `MESSAGE_RECEIVED` — теперь `ChatDispatcher.submit`
(нормализовать → буфер → вернуться); за швом один воркер-таск на `chat_id` дренирует
`ChatInbox` этого чата и зовёт `HandleMessage.handle` последовательно.

- **`ChatDispatcher`** — быстрый `submit` (буфер + гарантия воркера, мгновенный возврат) +
  по воркеру на `chat_id`. Каждое сообщение обрабатывается под свежим `TurnScope`; ошибка
  обработчика ловится (воркер не умирает посреди потока). `aclose` закрывает все инбоксы и
  дожидается воркеров.
- **`ChatInbox`** — per-chat буфер с debounce-окном «пусть допишут». `drain_batch` ждёт окно
  тишины и отдаёт осевший всплеск; снапшот+очистка синхронны, поэтому конкурентный `offer` не
  теряется. Фокусное сообщение или закрытие замыкают окно в ноль.
- **`TurnScope`** — изолированный per-turn контекст: `Random`, засеянный
  `(base_seed, chat_id, message_id)`, прокинутый во все seeded-draw хода.
- **`make_focus_predicate`** — «фокус» = `classify_addressivity` → `DIRECTED_TO_BOB`
  (переиспользует детектор адресности, DRY); `bob_user_id` резолвится лениво на старте.

Проводка: `runtime/composition.py` меняет подписчика `_as_handler(handle_message)` →
`_as_dispatch_handler(intake_dispatcher)`; `Application.intake_dispatcher` дренируется в
`Application.shutdown` ПЕРЕД закрытием соединения (`runtime.stop()` → `aclose()` →
`connection.close()`), поэтому корректная остановка досдаёт буферизованные ответы. Окно —
`dialogue.intake_debounce_ms` (по умолчанию 0, latency-free). При `presence.stream_read`
(BOB-072) окно активируется (коалесинг вспышки в один холистический read); фокус минует окно
всегда (INV-1).

#### Холистический stream-read вспышки (BOB-072, за `presence.stream_read`, OFF)

Вместо скриптованного top-k (один Tier-1 read на КАЖДОЕ ambient-сообщение) осевшую вспышку
воркер читает по-человечески — целиком и разом. `ChatDispatcher._handle_stream_read`
SPLIT'ит батч на focal и ambient:

- **focal** (прямое обращение, `is_focused`) отвечается детерминированно как сейчас, НАД и
  ВНЕ batch-read (никакая batch-читка не штампуется → срабатывает focal-короткое замыкание
  гейта), INV-1;
- весь **ambient**-остаток идёт в ОДИН `RoomStreamReader.read` (порт `AmbientBatchReader`,
  `room_stream_reader.py`): вспышка сворачивается в `BatchRoomReadingContext`, инъектированный
  `BatchRoomReader` зовётся один раз и возвращает по одному `RoomReading` на сообщение В
  ПОРЯДКЕ прибытия. Каждое читаемое per-message `ambient_reading` едет на `TurnScope`, и
  `TurnGate` применяет предвычисленный вердикт (минуя per-message read) — reply/react/persist
  + floor для ВСЕХ ambient-сообщений, включая молчаливый IGNORE (INV-S2, тред цел).

🔴 Читалка НИКОГДА не бросает: сбой деградирует в безопасный all-IGNORE-план нужной длины
(`SILENT_IGNORE_READING`), поэтому воркер всё равно персистит каждое ambient-сообщение —
Боб не действует по угаданному read'у.

Перед чтением `_coalesce_mask` прореживает ambient очередным стейл-коалесингом (`presence`,
`coalesce_stale`, за тем же флагом + `stale_coalesce_enabled`): переформулировку того же
опознанного отправителя в следующем слоте выкидывает из read'а (штампуя `SILENT_IGNORE_READING`),
но всё равно персистит (INV-S2/INV-S3). OFF → каждое ambient-сообщение читается, байт-в-байт.

### Роутер LLM и селективная редакция приватности

`LLMRouter` — политика приложения поверх портов `LLMProvider` (Tier 0 локальный /
Tier 1 API). Для каждого запроса он: **классифицирует** задачу (`TaskType`) в
предпочтительный тир (`REPLY_TO_USER` и `GENESIS` → Tier 1; `SENTIMENT`,
`INNER_MONOLOGUE`, `REFLECT`, `EXTRACT_FACTS` → Tier 0); **селективно
редактирует** перед любым вызовом Tier 1; **откатывается** Tier 1 → Tier 0 при
сбое предпочтительного тира.

🔴 **Tier-1 rate-cap (BOB-072).** Опциональный `tier1_max_concurrency` вешает потолок
на число ОДНОВРЕМЕННЫХ Tier-1-вызовов (`asyncio.Semaphore`) — незаметная страховка от
429/деградации, когда вспышки по чатам (включая batch `ROOM_READ`) бьют в Tier 1 разом.
Он только СЕРИАЛИЗУЕТ вызовы: не трогает решение о маршрутизации и payload. Fallback
Tier 1 → Tier 0 выполняется ВНЕ гейта, поэтому упавший Tier-1-вызов не держит слот, пока
доигрывает локальный откат. `None`/`<= 0` (по умолчанию) → гейта нет → байт-в-байт.
Конфиг — `llm.tier1_max_concurrency`.

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

`HandleMessage` (за швом `ChatDispatcher`, который подписан на `MessageReceived`)
проводит один ход
perceive → decide → act → persist → remember: обновляет настроение через
`UpdateMoodFromText`, воспроизводит недавнюю историю диалога
(`recent_episodes(k)` через шов `EpisodeReader`), делает recall памяти
(`MemoryRecall`, FTS5) и собирает `shareable_context` (история, память,
настроение, идентичность, вкус), получает ответ от роутера (`REPLY_TO_USER` +
селективная редакция / fallback Tier 0; тир ответа выбирается гибридно через
`select_reply_tier` и передаётся как `tier_override`). Медленная генерация идёт
внутри `typing_indicator(chat_id)` шва `ReplyGateway` (keepalive «Bob печатает…»),
затем готовый ответ коммитится **одним** `reply()` (rich, plain fallback); далее
сохраняются эпизод и снапшот настроения. Именно прикрепление `shareable_context`
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

### Проактивность: drive-движок (BOB-010 Ф1)

`ProactivityEngine` превращает чистую drive-модель в реальное проактивное
сообщение — поведение рождается из состояния (mood/тишина/рефлексия/циркада), не из
расписания. Движок дёшев по построению: решение «заговорить» чистое (без LLM),
поэтому подавляющее большинство тиков завершается с **нулём** обращений к модели.
На каждом тике, cheapest-first: загрузить per-persona `ProactivityState` через
`ProactivityStore`; снять лапснувший тайм-мьют (`/quiet 2h` — durably вернуть флаг и
очистить `mute_until` один раз, постоянный `/quiet` держится до `/wake`);
восстановить энергию за тишину; решить через `ProactiveDecider` (`urge` →
`p(speak)` → seeded-розыгрыш под governance-вето, **по умолчанию молчать**); только
при срабатывании — дешёвый Tier-0-гейт (`SAY: <seed>` говорит, `SKIP`/пустой/битый
ответ молчит); на не-skip — компоновка через `LLMRouter` с гибридным
`select_reply_tier` и постинг в топик Боба через `typing_indicator` + `reply`;
наконец потратить энергию и проставить `last_spoke_at`. Всё инъектируется (store,
decider, router, gateway, личность, `Clock`, seeded RNG, read-seams), движок не
держит ни глобалов, ни конфигурации, ни знания о транспорте.

`ProactiveTick` — тонкая обёртка, которую рантайм планирует на heartbeat-каденсе
рядом с тремя другими тиками и под той же `RetryPolicy`. `RecordOwnerActivity`
вызывается из `HandleMessage` после каждого сообщения owner: проставляет
`last_user_msg_at` (взводит owner-cooldown) и частично восполняет резервуар энергии
(«ты вернулся»), сохраняя мьют и `last_spoke_at`. Движок читает два дешёвых сигнала
через швы `ReflectionSalienceSource` (салиентность свежей рефлексии) и
`ProactiveWindowCounter` (счётчик проактивов в окне для анти-спама) — реализованы
инфраструктурой над `episodic_log`.

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
- `recall_memory` (`make_recall_memory_capability(recall)`) — тонкий *авто*-recall:
  обёртка над `MemoryRecall`, `permission` `safe`. GUPPI тихо подмешивает память в
  ответ; навык обкатал петлю e2e без нового I/O.
- `search_memory` (`make_search_memory_capability(recall)`, BOB-011) — первая
  содержательная **агентная** capability: то, что Боб *решает* вызвать сам через
  tool-loop. Он ищет по всему долгому архиву реальным запросом (гибрид
  семантика+keyword за тем же портом `MemoryRecall`) и использует результат.
  `permission` `safe`; JSON-схема — обязательный `query` плюс опциональный `k`
  (модель тюнит число воспоминаний; мусорный/нулевой/огромный `k` клампится в
  безопасное окно `[1, 50]`, по умолчанию 8, чтобы небрежная модель не затопила и
  не оголила свой контекст). Возвращает компактный список `content` найденных
  воспоминаний.

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
- Intake-развязка (BOB-066): подписчик `MESSAGE_RECEIVED` неблокирующий (`submit`
  возвращается сразу — поллер не ждёт генерацию). **INV-5**: один воркер на `chat_id` →
  сообщения чата обрабатываются в порядке прихода; параллелизм только между чатами, без
  глобального лока (deadlock-free). **INV-4**: свежий `TurnScope.rng` на сообщение засеян
  `(base, chat_id, message_id)` → конкурентные чаты не делят поток розыгрышей, ход
  воспроизводим. **INV-1/10**: фокусное сообщение минует debounce (флаш на уровне батча,
  никогда не теряется). `shutdown` дренирует диспетчер до закрытия соединения.
- Genesis идемпотентен по on-disk флагу `SOUL.md`.
- Доступ закрыт по политике owner/allowlist/chat-scope (fail-closed): chat-scope
  связывает даже owner; решение читает динамический allowlist на каждом вызове.
- Capability-шов forward-compatible: новый навык — регистрация объекта, потребители
  (реестр, tool-loop, `HandleMessage`) не меняются; tool-loop ограничен turn-cap.
- Проактивный тик дёшев по умолчанию: решение чистое (без LLM), поэтому вето или
  непрошедший розыгрыш завершают тик с нулём LLM-вызовов; гейт Tier 0 платится
  только при срабатывании, компоновка — только на не-skip seed.
- Проактив управляется состоянием, не расписанием; всё проактивное состояние
  per-persona; время и стохастика — из инъецированных `Clock` и seeded RNG.

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

Модуль `src/bob/application/runtime/heartbeat.py`:
- `periodic(tick, *, interval_seconds, sleep=None, retry=None)` → фабрика фоновой задачи.
- `RetryPolicy(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=30.0)`.

Модуль `src/bob/application/runtime/retry.py`:
- `retry_with_backoff(operation, *, max_attempts, base_delay_seconds, max_delay_seconds, sleep)` → `T`.
- `is_transient(error)` → `bool`.

Пакет `src/bob/application/runtime/intake/` (BOB-066 Срез 2.1):
- `ChatDispatcher(*, handle, base_seed, is_focused, quiet_window=0.0, sleep=asyncio.sleep)` —
  `submit(message)` (быстро, неблокирующе), `async wait_for_idle()`, `async aclose()`.
- `ChatInbox(*, quiet_window, is_focused, sleep=asyncio.sleep)` — `offer(message)`,
  `async drain_batch()` → `list[MessageReceived]`, `close()`, `peek_since(after_update_id)`,
  свойства `empty` / `closing`.
- `TurnScope(chat_id, message_id, rng)` (frozen); `new_turn_scope(*, base_seed, chat_id,
  message_id)` → `TurnScope`.
- `make_focus_predicate(bob_user_id_source)` → `Callable[[MessageReceived], bool]`;
  `message_is_focused(message, *, bob_user_id)` → `bool`.
- `decisions.should_debounce(*, closing, has_focus)` / `batch_grew(*, before, after)` /
  `derive_turn_seed(*, base_seed, chat_id, message_id)` — чистое детерминированное ядро.

Модуль `src/bob/application/reliability.py` (BOB-049 .3):
- `call_with_retry(operation, *, attempts, backoff_seconds, sleep)` → `T` — ограниченный
  ретрай ЛЮБОГО сбоя essential-шага (не только transient), затем повторный raise.
- `Sleep` — тип инъектируемого backoff-сна.

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

Модуль `src/bob/application/capabilities/search_memory.py`:
- `make_search_memory_capability(recall)` → `Capability` (агентный навык
  `search_memory`: `query` + опциональный `k`, клампится в `[1, 50]`).

Модуль `src/bob/application/usecases/handle_message.py`:
- `HandleMessage` — `async handle(event, scope: TurnScope | None = None)` (тонкий оркестратор,
  BOB-062.6b; `scope.rng` прокидывается во все seeded-draw хода, BOB-066 INV-4; без scope —
  откат на per-boot rng); `PersonalityState`,
  `EpisodeReader`, опциональные `registry` и `tool_provider` (включают capability tool-loop).
  `__init__` собирает ~14 коллабораторов из инъектированных швов.
- Отказоустойчивость (BOB-049 .3): essential-шаги (суждение + генерация ответа)
  обёрнуты `call_with_retry`; при стойком сбое — `OutageNotifier.notify_outage()`
  (GUPPI-нотис в топик Боба), ход пользователя персистится, деградированный ответ
  НЕ отправляется. Швы: `outage_notifier`, `retry_sleep`, `essential_attempts`,
  `essential_backoff_seconds`.

Модуль `src/bob/application/usecases/essential_runner.py`:
- `EssentialRunner` — `async run(operation, *, step)` (ограниченный ретрай существенного шага),
  `async handle_failure(event, soul, exc)` (персист хода + GUPPI-нотис), `notify_outage`. Порт
  `OutageNotifier`; исключение `_EssentialStepError`.

Модуль `src/bob/application/usecases/precompose_gate.py`:
- `PreComposeGate` — `async maybe_route_coding(event, interlocutor)` / `async
  maybe_permission(event, interlocutor)` → `bool` (съел ли ход). Швы `NaturalCodingRouter`,
  `PermissionFlowLike`.

Модуль `src/bob/application/usecases/update_mood_from_text.py`:
- `UpdateMoodFromText` — `async run(mood, signals)` → `Mood`; `TextSignals`.

Модуль `src/bob/application/usecases/extract_facts.py`:
- `ExtractFacts` — `async run(*, user_message, reply=None)` (best-effort); `FactWriter`.

Модуль `src/bob/application/usecases/run_genesis.py`:
- `RunGenesis` — `async run()` → `GenesisResult`; `GenesisError`.

Модуль `src/bob/application/usecases/heartbeat.py`:
- `InnerMonologueTick`, `MoodDriftTick`, `ReflectTick` — каждый `async run()`.

Модуль `src/bob/application/proactivity/engine.py`:
- `ProactivityEngine(*, persona_id, chat_id, store, decider, router, gateway,
  personality, reflection, window, clock, rng)` — `async tick()` → `bool` (говорил ли).
- `ProactivityStoreLike`, `ReflectionSalienceSource`, `ProactiveWindowCounter` — швы-протоколы.

Модуль `src/bob/application/proactivity/tick.py`:
- `ProactiveTick(*, engine)` — `async run()`; `ProactiveRunner`.

Модуль `src/bob/application/proactivity/record_owner_activity.py`:
- `RecordOwnerActivity(*, store, clock, persona_id="bob")` — `async run()`.

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
`tests/application/test_search_memory_capability.py`,
`tests/application/usecases/test_handle_message.py`,
`tests/application/usecases/test_extract_facts.py`,
`tests/application/usecases/test_update_mood_from_text.py`,
`tests/application/usecases/test_run_genesis.py`,
`tests/application/usecases/test_run_genesis_hardening.py`,
`tests/application/usecases/test_heartbeat.py`,
`tests/application/proactivity/test_engine.py`,
`tests/application/proactivity/test_tick.py`,
`tests/application/proactivity/test_record_owner_activity.py`,
`tests/application/test_layering.py`.
