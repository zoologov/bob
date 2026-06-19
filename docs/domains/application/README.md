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
  детерминизма).
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

### Use-cases (поток, память и Genesis)

`HandleMessage` (подписан на `MessageReceived`) проводит один ход
perceive → decide → act → persist → remember: обновляет настроение через
`UpdateMoodFromText`, воспроизводит недавнюю историю диалога
(`recent_episodes(k)` через шов `EpisodeReader`), делает recall памяти
(`MemoryRecall`, FTS5) и собирает `shareable_context` (история, память,
настроение, идентичность, вкус), получает ответ от роутера (`REPLY_TO_USER`,
Tier 1 + селективная редакция / fallback Tier 0), стримит его через gateway,
сохраняет эпизод и снапшот настроения. Именно прикрепление `shareable_context`
к вызову Tier 1 даёт Бобу память — он помнит имя, названное ход назад.

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

## Инварианты

- `application` не импортирует `bob.infrastructure` (включая `TYPE_CHECKING`).
- Payload LLM-запроса собирается один раз; `private_context` никогда не доходит до
  Tier 1, в том числе на пути fallback Tier 1 → Tier 0; `shareable_context`
  (история/память/настроение/идентичность/вкус) на Tier 1 разрешён.
- Шаг remember (`ExtractFacts`) best-effort: ошибка извлечения фактов не роняет
  уже отправленный ответ.
- Время берётся только из инъецированного `Clock`.
- Ошибка одного heartbeat-тика изолируется и не роняет остальные.
- Genesis идемпотентен по on-disk флагу `SOUL.md`.

## API

Модуль `src/bob/application/router/llm_router.py`:
- `LLMRouter(*, providers: Mapping[int, LLMProvider])` — `async run(request)` → `str`.
- `LLMRequest` — поля `shareable_context` / `private_context` (два канала контекста);
  `TaskType` (значения `REPLY_TO_USER`, `GENESIS`, `SENTIMENT`, `INNER_MONOLOGUE`,
  `REFLECT`, `EXTRACT_FACTS`).

Модуль `src/bob/application/runtime/agent.py`:
- `AgentRuntime(*, background_tasks=None)` — `start()`, `stop()`,
  `run_until_stopped()`, `state`, `is_running`.

Модуль `src/bob/application/runtime/event_bus.py`:
- `AsyncEventBus` — `subscribe(event_name, handler)`, `async publish(event)`.

Модуль `src/bob/application/runtime/events.py`:
- `MessageReceived`, `MESSAGE_RECEIVED`.

Модуль `src/bob/application/runtime/heartbeat.py`:
- `periodic(tick, *, interval_seconds, sleep=None)` → фабрика фоновой задачи.

Модуль `src/bob/application/usecases/handle_message.py`:
- `HandleMessage` — `async handle(event)`; `PersonalityState`, `EpisodeReader`.

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
`tests/application/usecases/test_handle_message.py`,
`tests/application/usecases/test_extract_facts.py`,
`tests/application/usecases/test_update_mood_from_text.py`,
`tests/application/usecases/test_run_genesis.py`,
`tests/application/usecases/test_run_genesis_hardening.py`,
`tests/application/usecases/test_heartbeat.py`,
`tests/application/test_layering.py`.
