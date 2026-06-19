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
  `SoulStore`, `AllowlistStore`, `EventBus`, `Clock`, `Capability`, `DomainEvent`.
  Здесь же общие value-объекты: `LLMMessage`, `Recalled`, `JsonValue`,
  `EventHandler`, `ToolCall`, `ToolCallResult`, `ToolDefinition`, `Permission`.
  Адаптеры в `bob.infrastructure` реализуют эти порты, `app.py` связывает
  конкретные адаптеры с ними.
- **personality/mood.py** — `Mood` (пять осей в `[-1, 1]`), `MoodDelta` и
  деривация тона.
- **personality/taste.py** — `TasteEngine`, `TasteAxis`, перечисление `Verdict`.
- **personality/negotiation.py** — `Negotiation`, зоны `NegotiationZone`, позиции
  `Stance`.
- **personality/soul.py** — `SOUL`, неизменяемый снапшот загруженной личности.
- **memory/entities.py** — `EpisodicEvent` и `SemanticFact`, неизменяемые
  value-объекты памяти.

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

## Тесты

Тесты: `tests/domain/test_ports.py`, `tests/domain/personality/test_mood.py`,
`tests/domain/personality/test_taste.py`,
`tests/domain/personality/test_negotiation.py`,
`tests/domain/personality/test_soul.py`, `tests/domain/memory/test_entities.py`.
