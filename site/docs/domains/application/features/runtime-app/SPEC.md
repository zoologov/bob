<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T07:27:18.171078+00:00 · coverage 100% (`runtime-app`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

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
- `TurnScope.rng` — единственный источник seeded-случайности хода (детерминизм под intake).

## API

Модуль `src/bob/application/runtime/`:
- `AgentRuntime.start()` / `.stop()` / `.run_until_stopped()` — жизненный цикл процесса.
- `AsyncEventBus.subscribe(name, handler)` / `.publish(event)` — шина событий.
- `periodic(...)` → супервизируемый повторяющийся тик; `RetryPolicy` — backoff.
- `retry_with_backoff(...)` / `is_transient(...)` — ретрай транзиентных сбоев.
- `ChatDispatcher.submit(...)` / `.wait_for_idle()` / `.aclose()` — intake-развязка.
- `new_turn_scope(...)` → `TurnScope` — изолированный per-turn контекст.

## Тестирование

Тесты: `tests/application/runtime/test_agent.py`, `test_event_bus.py`, `test_retry.py`,
`test_heartbeat_scheduler.py`, `test_delayed_turn.py`, `test_share_of_voice_gate.py`,
`test_catch_up_reentry.py`, `test_staleness_reassessor.py`,
`test_bob_message_reaction_event.py`, и `tests/application/runtime/intake/` (dispatcher,
inbox, focus, scope, room_stream_reader).

<!-- beadloom:track=src/bob/application/runtime/agent.py -->
<!-- beadloom:track=src/bob/application/runtime/event_bus.py -->
<!-- beadloom:track=src/bob/application/runtime/heartbeat.py -->
<!-- beadloom:track=src/bob/application/runtime/retry.py -->
<!-- beadloom:track=src/bob/application/runtime/delayed_turn.py -->
<!-- beadloom:track=src/bob/application/runtime/share_of_voice_gate.py -->
<!-- beadloom:track=src/bob/application/runtime/catch_up_reentry.py -->
<!-- beadloom:track=src/bob/application/runtime/staleness_reassessor.py -->
