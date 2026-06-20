<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Слой domain — чистое ядро Боба

Чистая логика и модели Боба: личность (Higher Mind) и память. Без I/O, без LLM,
без Telegram. Домен не импортирует ничего наружу — он общается с транспортом,
LLM, хранилищем и временем исключительно через порты-протоколы.

## Спецификация

### Модули

- **ports.py** — порты-протоколы (структурные `typing.Protocol`, только
  интерфейсы): `LLMProvider`, `ToolCallingProvider`, `MemoryRepo`, `MemoryRecall`,
  `Embedder`, `Reranker`, `SoulStore`, `AllowlistStore`, `EventBus`, `Clock`,
  `Capability`, `DomainEvent`. Здесь же общие value-объекты: `LLMMessage`,
  `Recalled`, `JsonValue`, `EventHandler`, `ToolCall`, `ToolCallResult`,
  `ToolDefinition`, `Permission`. Адаптеры в `bob.infrastructure` реализуют эти
  порты, `app.py` связывает конкретные адаптеры с ними.
- **personality/mood.py** — `Mood` (пять осей в `[-1, 1]`), `MoodDelta` и
  деривация тона.
- **personality/taste.py** — `TasteEngine`, `TasteAxis`, перечисление `Verdict`.
- **personality/negotiation.py** — `Negotiation`, зоны `NegotiationZone`, позиции
  `Stance`.
- **personality/soul.py** — `SOUL`, неизменяемый снапшот загруженной личности.
- **memory/entities.py** — `EpisodicEvent` и `SemanticFact`, неизменяемые
  value-объекты памяти.
- **proactivity/urge.py** — `UrgeModel`, чистая формула «порыва заговорить» из
  настроения, тоски, салиентности и циркадного ритма.
- **proactivity/social_energy.py** — `SocialEnergy`, ограниченный `[0, 1]`
  резервуар порыва (копится/тратится/восполняется).
- **proactivity/governance.py** — `Governance`, чистые потолки-вето над проактивом;
  `GovernanceConfig`, `ProactiveHistory`.
- **proactivity/decision.py** — `ProactiveDecider` (`urge` → вероятность →
  seeded-розыгрыш под вето); `urge_to_probability`.
- **proactivity/state.py** — `ProactivityState`, per-persona состояние,
  персистируемое между тиками.

### Личность (Higher Mind)

**Mood** — аффективное состояние из пяти осей (`valence`, `arousal`, `openness`,
`social`, `stability`). `update(delta)` применяет `MoodDelta` с клампом к
границам; `drift_toward(baseline, rate)` моделирует эмоциональный гомеостаз
(настроение между стимулами дрейфует к resting-baseline на долю `rate ∈ [0, 1]`);
`tone()` детерминированно выводит тон-дескриптор из знака valence и полосы
arousal (например `excited`, `cheerful`, `glum`, `neutral`).

**TasteEngine** детерминированно отображает тему в `Verdict` по осям вкусов.
Знак значения оси выбирает like/dislike, а conviction гейтит экстремумы: достичь
`LOVE`/`HATE` можно лишь при сильном значении и достаточном conviction, иначе
вердикт смягчается на шаг внутрь. Неизвестная тема — `NEUTRAL`. LLM лишь
*вербализует* вердикт в другом слое, но никогда его не *решает*.

**Negotiation** решает текстовую позицию Боба. Три зоны разделяют, кому
принадлежит вопрос: `BOB_PERSONAL`, `SHARED`, `USER_DOMAIN`. В домене
пользователя Боб всегда уступает (`CONCEDE`); в своей и общей зоне ниже порога
conviction соглашается (`AGREE`), на пороге и выше предлагает альтернативу
(`PROPOSE_ALTERNATIVE`). В P0 действует только на текст.

**SOUL** — неизменяемый снапшот загруженной личности: идентичность, текущее
настроение и baseline, движок вкусов, фантомные предпочтения. Собирается
вызывающей стороной из артефактов `SoulStore` (домен не трогает файловую
систему); `with_mood(mood)` даёт обновлённый снапшот без мутации оригинала.

### Память

`EpisodicEvent` — одно событие на ленте (сообщение, тик, действие) со снапшотом
настроения и тегами. `SemanticFact` — распознанный факт с `confidence ∈ [0, 1]`
и категорией. Оба неизменяемы (`frozen`, `slots`), а инварианты проверяются в
`__post_init__` при конструировании: метки времени обязаны быть timezone-aware,
`confidence` — в единичном интервале. Невалидная запись не может существовать в
памяти. Адаптер хранилища переводит эти сущности в строки SQLite и обратно —
домен не видит базу.

### Порты памяти: recall, эмбеддинги, реранкинг (BOB-011)

`MemoryRecall` — единственный контракт извлечения для домена и приложения:
`recall(query, *, k)` → `Sequence[Recalled]`. За ним свободно меняется реализация
(keyword-only FTS5 или гибрид с вектором) — потребители не знают, что стоит позади.
Гибридный recall эпика «Память» (BOB-011) встаёт за этот же порт как drop-in замена.

`Embedder` — шов семантической памяти: `embed(texts)` → один dense-вектор на текст
(порядок сохраняется, пустой вход даёт пустой список). Порт намеренно
**провайдер-агностичен**: первая реализация — Ollama-адаптер на BGE-M3 (dense,
1024-dim, мультиязычный/русский), но контракт обещает лишь «текст на входе — вектор
на выходе», поэтому другой локальный эмбеддер (например Qwen3-Embedding) свопается
без правки потребителей. Размерность фиксируется выбранной моделью. Эмбеддинги
считаются **локально** — контент памяти не уходит наружу.

`Reranker` — аддитивный буст качества **поверх** `MemoryRecall`: `rerank(query,
candidates)` → переупорядоченные (и подрезанные до top-N) кандидаты. Гибрид-recall
поднимает широкий top-K (RRF над keyword + vector), а реранкер переоценивает пул
более резким суждением о релевантности. Контракт строго **аддитивный**: реализация
обязана деградировать мягко — при недоступности (реранк выключен, модель/эндпоинт
недоступны, скор не разобрался) она возвращает вход **без изменений** и **никогда
не бросает** в вызывающего, поэтому реранк никогда не ухудшает recall. Порт тоже
провайдер-агностичен (первая реализация — Ollama-как-scorer, нативного rerank-API
у Ollama нет), и, как эмбеддинги, работает локально.

### Capability-шов (контракт навыков)

`Capability` — стабильный контракт одного навыка, который GUPPI умеет исполнять
для Боба. Это именно **контракт**, а не машинерия плагинов (sandbox, авто-дискавери,
self-creation придут позже за тем же швом). Навык называет себя (`name`),
описывает себя (`description`), объявляет JSON-схему аргументов (`input_schema`),
несёт уровень доступа `permission` (`safe` исполняется напрямую; `confirm` —
задел под будущий approval-гейт) и `async execute(args)`. Новый навык — это
регистрация объекта под этот контракт; потребители не меняются.

Вокруг контракта лежат value-объекты вызова инструментов в форме OpenAI:
`ToolCall` (один запрошенный моделью вызов: `id`, `name`, `arguments`),
`ToolCallResult` (финальный текст плюс кортеж `tool_calls`; пустой кортеж = ход
финальный) и `ToolDefinition` (определение функции-инструмента, которое реестр
отдаёт модели как `tools`). `ToolCallingProvider` — tool-aware двойник
`LLMProvider`: `async complete_with_tools(messages, *, tools)` → `ToolCallResult`.

`AllowlistStore` — порт долговечного хранилища рантайм-allowlist (множество
`user_id`): `load()`, `add()`, `remove()`. На нём держится `Authorizer`, чтобы
команда `/authorize` пережила рестарт; SQLite-адаптер живёт в инфраструктуре.

### Проактивность (drive-модель порыва)

Чистое ядро проактивности (BOB-010 Ф1): поведение Боба «писать первым» рождается из
состояния, а не из таймера. `UrgeModel.urge` складывает четыре именованных,
настраиваемых тяги в порыв `[0, 1]`: настроение (среднее по осям
`arousal`/`openness`/`social` из `Mood`), тоску по тишине (растёт с секундами
молчания и насыщается за ~6 ч), салиентность свежей рефлексии и циркадную базу по
**локальному** часу (утренний и вечерний пики, дневной провал, низ ночью); плюс
текущий уровень социальной энергии. Функция чистая: тот же вход — тот же порыв,
час суток приходит уже выведенным из `Clock`.

`SocialEnergy` — ограниченный `[0, 1]` резервуар: `recover(elapsed_seconds)`
копит его в тишине, `spend()` тратит фиксированную долю на реплику, а
`replenish_from_reply()` частично восполняет на ответ owner — естественный cooldown
без таймера. Все переходы чисты (прошедшее время передаёт вызывающая сторона).

`ProactiveDecider` — шов решения на тике: берёт «сейчас» из инъецированного `Clock`,
считает `urge`, переводит его в вероятность `p(speak)` монотонной логистической
кривой (`urge_to_probability`) и делает **один** розыгрыш из инъецированного seeded
`Random`. `Governance` проверяется первой и только **блокирует**, никогда не поднимает
порыв: пять чистых вето — quiet hours (жёсткий пол по локальному времени),
owner-mute, анти-спам (потолок в окне), мин-гэп и owner-cooldown; пороги вынесены в
`GovernanceConfig`, а недавняя история — в `ProactiveHistory`. `ProactivityState` —
plain value-объект, который порт `ProactivityStore` round-trip'ит в хранилище:
резервуар, маркеры `last_spoke_at`/`last_user_msg_at` и флаг `proactivity_enabled`
(`/quiet`/`/wake`). Всё per-persona — реплики Bobiverse наследуют код, но держат своё.

## Инварианты

- Домен не выполняет I/O и не импортирует `application` или `infrastructure`.
- Все оси Mood и значения вкусов ограничены `[-1, 1]`, conviction и confidence —
  `[0, 1]`; нарушение границы — `ValueError` при конструировании.
- Метки времени памяти обязаны быть timezone-aware.
- Вердикты `TasteEngine` и позиции `Negotiation` детерминированны и тестируемы
  без LLM.
- Порты — только контракты: в этом модуле нет реализаций.
- `Capability`-шов forward-compatible: новый навык регистрируется как объект под
  контракт, потребители (реестр, tool-loop) не меняются.
- Проактивность чистая и детерминированная: `urge`, вероятность и governance-вето
  тестируемы без LLM; час суток и стохастика приходят из инъецированных `Clock` и
  seeded RNG, в домене нет `datetime.now()`/`random`.
- Социальная энергия и порыв ограничены `[0, 1]`; выход за границу — `ValueError`.
- Governance только блокирует и никогда не поднимает порыв; всё состояние
  проактивности — per-persona.

## API

<!-- beadloom:track=src/bob/domain/ports.py -->

Модуль `src/bob/domain/ports.py`:
- `LLMProvider` — `async complete(messages, *, stream)` → `str | AsyncIterator[str]`.
- `ToolCallingProvider` — `async complete_with_tools(messages, *, tools)` → `ToolCallResult`.
- `Capability` — свойства `name`, `description`, `input_schema`, `permission`
  (`"safe" | "confirm"`) и `async execute(args)` → `object`.
- `MemoryRepo` — `save_episode()`, `save_fact()`, `load_episodes(*, limit)`,
  `recent_episodes(k)` (последние `k` эпизодов в хронологическом порядке — для
  воспроизведения недавней истории диалога в промпт ответа).
- `MemoryRecall` — `recall(query, *, k)` → `Sequence[Recalled]`.
- `Embedder` — `async embed(texts)` → `list[list[float]]` (один dense-вектор на
  текст, порядок сохраняется; локально, провайдер-агностично).
- `Reranker` — `async rerank(query, candidates)` → `list[Recalled]`
  (переупорядоченные/подрезанные кандидаты; аддитивно, при недоступности возвращает
  вход без изменений).
- `SoulStore` — `soul_exists()`, `read_soul()`, `write_soul()`, `write_json()`,
  `append_genesis_log()`.
- `AllowlistStore` — `load()` → `set[int]`, `add(user_id)`, `remove(user_id)`.
- `EventBus` — `publish(event)`, `subscribe(event_name, handler)`.
- `Clock` — `now()` → `datetime` (инъекция времени; запрет `datetime.now()` в домене).
- `DomainEvent` — маркер с `name` для маршрутизации на шине.
- `ToolCall`, `ToolCallResult` — value-объекты OpenAI-формата вызова инструментов;
  `Permission` (`"safe" | "confirm"`), `ToolDefinition` — определение функции-инструмента.

Модуль `src/bob/domain/personality/mood.py`:
- `Mood` — `update(delta)`, `drift_toward(baseline, *, rate)`, `tone()`.
- `MoodDelta` — знаковый сдвиг по каждой оси.

Модуль `src/bob/domain/personality/taste.py`:
- `TasteEngine` — `score(topic)` → `Verdict`.
- `TasteAxis`, `Verdict`.

Модуль `src/bob/domain/personality/negotiation.py`:
- `Negotiation` — `decide(zone, *, conviction)` → `Stance`.
- `NegotiationZone`, `Stance`.

Модуль `src/bob/domain/personality/soul.py`:
- `SOUL` — `with_mood(mood)` → `SOUL`.

Модуль `src/bob/domain/memory/entities.py`:
- `EpisodicEvent`, `SemanticFact`.

Модуль `src/bob/domain/proactivity/urge.py`:
- `UrgeModel` — `urge(*, mood, silence_seconds, salience, time_of_day_local, social_energy)` → `float[0..1]`.

Модуль `src/bob/domain/proactivity/social_energy.py`:
- `SocialEnergy(level)` — `recover(*, elapsed_seconds)`, `spend()`, `replenish_from_reply()` → `SocialEnergy`.

Модуль `src/bob/domain/proactivity/governance.py`:
- `Governance(config=GovernanceConfig())` — `allows(*, now, history)` → `bool`.
- `GovernanceConfig(quiet_start_hour, quiet_end_hour, max_per_window, min_gap, owner_cooldown)`,
  `ProactiveHistory(last_spoke_at, last_user_msg_at, sent_in_window, muted)`.

Модуль `src/bob/domain/proactivity/decision.py`:
- `ProactiveDecider(clock, governance, urge_model=UrgeModel())` —
  `should_speak(*, mood, silence_seconds, salience, social_energy, history, rng)` → `bool`.
- `urge_to_probability(urge)` → `float`.

Модуль `src/bob/domain/proactivity/state.py`:
- `ProactivityState(social_energy, last_spoke_at, last_user_msg_at, proactivity_enabled)`.

Модуль `src/bob/domain/ports.py` (проактивность):
- `ProactivityStore` — `async load(persona_id)` → `ProactivityState`,
  `async save(persona_id, state)`.

## Тесты

Тесты: `tests/domain/test_ports.py`, `tests/domain/personality/test_mood.py`,
`tests/domain/personality/test_taste.py`,
`tests/domain/personality/test_negotiation.py`,
`tests/domain/personality/test_soul.py`, `tests/domain/memory/test_entities.py`,
`tests/domain/proactivity/test_urge.py`,
`tests/domain/proactivity/test_urge_monotonicity.py`,
`tests/domain/proactivity/test_social_energy.py`,
`tests/domain/proactivity/test_governance.py`,
`tests/domain/proactivity/test_decision.py`,
`tests/domain/proactivity/test_store_port.py`.
