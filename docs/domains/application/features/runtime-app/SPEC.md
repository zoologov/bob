<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# runtime-app — рантайм приложения (asyncio-примитивы)

Асинхронные примитивы рантайма GUPPI: жизненный цикл процесса, in-process шина
событий и устойчивые heartbeat-тики (retry/backoff). Сами события интейка
(`MessageReceived`, `BobMessageReaction`) живут в shared kernel — `src/bob/kernel/events.py`
(BOB-113). Узел
`runtime-app` (`part_of` слоя `bob-application`, source `src/bob/application/runtime/`).

🔴 Отличать от `runtime` (composition root в `src/bob/runtime/` — проводка всех слоёв):
это разные узлы, они никогда не резолвятся друг в друга. `runtime-app` — доменно-чистые
async-примитивы приложения, а не корень сборки процесса.

## Спецификация

### Модули

- **agent.py** — `AgentRuntime`, жизненный цикл процесса GUPPI поверх одного
  asyncio-цикла: `start` / `stop` / `run_until_stopped`, супервизия фоновых задач,
  `state` / `is_running`; `RuntimeState` — перечисление состояний жизненного цикла.
- **event_bus.py** — `AsyncEventBus`, asyncio fan-out: доставить каждое событие всем
  обработчикам его имени (`subscribe` / `publish`) с изоляцией ошибок обработчиков.
- **heartbeat.py** — `periodic(...)`, обёртка тик-корутины в супервизируемый
  повторяющийся фоновый цикл (sleep инъецируется для детерминизма); `RetryPolicy` —
  политика ограниченного backoff для ретрая транзиентных сбоев тика.
  `health_gated(tick, *, reader, provider_id, probe=False, gate_id=None)` (BOB-116 D5, F2) —
  гейт дорожки по здоровью LLM-провайдера, от которого она зависит. Дорожка закрыта, пока
  `reader.is_degraded(gate_id or provider_id)`; сборка передаёт `gate_id=TIER0_EFFECTIVE`
  («Tier-0 целиком»), а зонд, его расписание, счёт отказов и строка лога остаются за
  `provider_id` (`tier0-primary`). При открытом гейте тик — тот же тик: исключение уходит
  без изменений. При закрытом:
  - дорожка с `probe=False` пропускает тик — ни вызова, ни строки лога (монитор уже сказал
    владельцу, а стек на каждый тик похоронил бы лог);
  - дорожка с `probe=True` выполняет тик, только когда `reader.probe_due(provider_id)`: тик и
    есть зонд, его успех доходит до монитора обычным докладом и снимает деградацию;
    проваленный зонд — одна строка `INFO` без стека, незаложенный зонд пропускается молча.

  Отказ зонда отличается от прочей ошибки по СОСТОЯНИЮ, а не по форме исключения: вырос ли
  `consecutive_failures` провайдера в снимке читателя за время тика. Роутер и обёртки
  записывают отказ до того, как исключение дойдёт до дорожки, поэтому отказ провайдера виден
  как рост счётчика. Всё остальное — ошибка БД до вызова модели или после зонда, на который
  модель ответила, — счётчик не двигает и поднимается в `periodic`, который логирует его со
  стеком, как раньше. Пределы названы в докстринге: параллельный отказ того же провайдера у
  другого вызывающего во время зонда сделает не-LLM ошибку тика похожей на проваленный зонд;
  тик, проглотивший свою LLM-ошибку и упавший дальше, тоже уйдёт строкой `INFO`; дорожку,
  которая частью ходит в Tier-1 (переоценка в `reflect`), гейт держит только целиком.
  `periodic` и `RetryPolicy` не изменились: проваленный зонд не поднимается и не
  ретраится, не-LLM ошибка ретраится как раньше и снова проходит через гейт.
- **retry.py** — `retry_with_backoff(...)`, ограниченный экспоненциальный backoff на
  *транзиентных* сбоях; `is_transient(...)` классифицирует транзиент/перманент.
- **delayed_turn.py** — `DelayedTurn`, человеческий пол под скоростью прилёта ответа:
  сгенерированный ответ никогда не приходит быстрее своего человеческого floor'а (BOB-066 2.3).
- **share_of_voice_gate.py** — `ShareOfVoiceGate`, потолок ambient-барджа одним решением:
  масштабирует вероятность барджа per-chat share-of-voice-потолком (`admits_barge`, BOB-066 2.3).
- **catch_up_reentry.py** — `CatchUpReentry`, re-entry-тик над осевшей пачкой per-chat
  воркера (`select`, флаг по умолчанию OFF, BOB-066 Срез W.3); `CatchUpSelection`.
- **staleness_reassessor.py** — `StalenessReassessor`, переоценка черновика ответа против
  того, что прилетело за время генерации, одним решением (`reassess`, BOB-066 Срез 3.1).
  С BOB-116 D13 судья устаревания может не ответить (`StalenessJudge.assess` → `None`, когда
  провайдер недоступен — `LLMRouter.run_optional`), и тогда черновик отправляется, а не
  теряется.
- **serial_queue.py** — `SerialQueue[T]`, очередь с одним фоновым воркером (BOB-126, ревью
  M1): `submit` синхронный и возвращается сразу, элементы обрабатываются строго по одному в
  порядке поступления, отказ обработчика логируется и воркер не останавливает. Сборка ставит
  её между шиной и `PerceiveReaction`: подписчик `BOB_MESSAGE_REACTION` вызывается из цикла
  поллинга Telegram, а судья реакции — вызов Tier-0, который с дублёром может думать до 180 с.
  Элемент живёт в памяти процесса (at-most-once, как сообщение в `ChatDispatcher`); `aclose`
  не ждёт медленный обработчик — отменяет текущий элемент, сбрасывает очередь и пишет в лог,
  сколько брошено.
- **intake/** — concurrency-развязка между поллером и Бобом (BOB-066 Срез 2.1):
  - `dispatcher.py` — `ChatDispatcher`, быстрый неблокирующий `submit` + по воркеру на
    `chat_id`, сериализующий каждый чат (`wait_for_idle`, `aclose`).
  - `inbox.py` — `ChatInbox`, per-chat буфер: неблокирующий `offer` + debounced `drain_batch`
    (`peek_since`, `empty`, `closing`, `close`).
  - `decisions.py` — чистое ядро решений intake: `should_debounce`, `batch_grew`,
    `derive_turn_seed`.
  - `focus.py` — предикат фокуса: `message_is_focused`, `make_focus_predicate` (прямой
    сигнал минует debounce-окно).
  - `scope.py` — `TurnScope`, изолированный per-turn контекст (координаты хода + собственный
    seeded rng, INV-4); `new_turn_scope`.
  - `room_stream_reader.py` — `RoomStreamReader` + `AmbientBatchReader`: осевший ambient-burst
    → одно per-message-чтение (BOB-072). Опциональный шов `perceive_kind` (BOB-078 B) размечает
    каждое сообщение соц-`InterlocutorKind` автора, чтобы read взвесил тёплый ответ гостя/новичка
    как салиентный; без шва `kind=None` (baseline байт-идентичен).

## Инварианты

- `runtime-app` — доменно-чистый: зависит от домена через порты (kernel `EventBus`/`Clock`),
  инфраструктуру не импортирует.
- `retry_with_backoff` ретраит **только** транзиентные сбои (перманентные пробрасывает).
- `AsyncEventBus` изолирует ошибку одного обработчика — она не роняет доставку остальным.
- `ChatDispatcher` сериализует ходы в пределах одного `chat_id`; разные чаты идут конкурентно.
- `SerialQueue` обрабатывает элементы по одному и по порядку; вызывающий её не ждёт.
- `TurnScope.rng` — единственный источник seeded-случайности хода (детерминизм под intake).

## API

Модуль `src/bob/application/runtime/`:
- `AgentRuntime.start()` / `.stop()` / `.run_until_stopped()` — жизненный цикл процесса.
- `AsyncEventBus.subscribe(name, handler)` / `.publish(event)` — шина событий.
- `periodic(...)` → супервизируемый повторяющийся тик; `RetryPolicy` — backoff.
- `health_gated(tick, *, reader: HealthReader, provider_id: str, probe: bool = False,
  gate_id: str | None = None)` → `Tick` — тик под гейтом здоровья LLM (BOB-116).
- `retry_with_backoff(...)` / `is_transient(...)` — ретрай транзиентных сбоев.
- `ChatDispatcher.submit(...)` / `.wait_for_idle()` / `.aclose()` — intake-развязка.
- `SerialQueue(handle, *, name)`; `.submit(item)` / `.wait_for_idle()` / `.aclose()` — работа
  вне пути вызывающего, по одному элементу.
- `new_turn_scope(...)` → `TurnScope` — изолированный per-turn контекст.

## Тестирование

Тесты: `tests/application/runtime/test_agent.py`, `test_event_bus.py`, `test_retry.py`,
`test_heartbeat_scheduler.py`, `test_delayed_turn.py`, `test_share_of_voice_gate.py`,
`test_catch_up_reentry.py`, `test_staleness_reassessor.py`,
`test_bob_message_reaction_event.py`, `test_serial_queue.py`, и
`tests/application/runtime/intake/` (dispatcher,
inbox, focus, scope, room_stream_reader). Гейт здоровья (BOB-116):
`tests/application/runtime/test_heartbeat_health_gated.py` (фейковый читатель: пропуск,
зонд, `INFO` без стека, ошибка БД в деградации логируется со стеком через настоящий
`periodic`, успешный зонд возвращает ритм) и `test_heartbeat_health_gated_real_monitor.py`
(то же на настоящем `ProviderHealthMonitor`). Живая документация —
`tests/acceptance/features/llm_health.feature` S6–S8 (режим зонда, одна строка лога на
переход, возврат ритма).

<!-- beadloom:track=src/bob/application/runtime/agent.py -->
<!-- beadloom:track=src/bob/application/runtime/event_bus.py -->
<!-- beadloom:track=src/bob/application/runtime/heartbeat.py -->
<!-- beadloom:track=src/bob/application/runtime/retry.py -->
<!-- beadloom:track=src/bob/application/runtime/delayed_turn.py -->
<!-- beadloom:track=src/bob/application/runtime/share_of_voice_gate.py -->
<!-- beadloom:track=src/bob/application/runtime/catch_up_reentry.py -->
<!-- beadloom:track=src/bob/application/runtime/staleness_reassessor.py -->
