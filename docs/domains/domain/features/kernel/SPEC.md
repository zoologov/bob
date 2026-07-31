<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# kernel — общее ядро контрактов

Инфра-нейтральные контракты, на которые опирается каждый вертикальный модуль:
рантайм-сеймы (`Clock`, `EventBus`, `EventHandler`, `DomainEvent`, `LLMProvider`) и
общие value-объекты (`LLMMessage`, `ToolLoopMessage`, `JsonValue`). Это *только
интерфейсы* — структурные `typing.Protocol` без реализаций. Классический DDD shared
kernel: любой модуль (`capabilities` / `social` / `memory` / …) импортирует **отсюда**,
но сам kernel не импортирует ни один модуль, поэтому циклов не возникает.

Узел `kernel` (`part_of` слоя `bob-domain`) физически живёт в `src/bob/kernel/`. До
BOB-062.8 эти контракты лежали в снятом слое-first каталоге `src/bob/domain/ports/`;
срез .8 перенёс семь контрактов сюда и удалил последний re-export shim.

## Спецификация

### Модули

- **ports.py** — определения контрактов:
  - `DomainEvent` (Protocol) — маркер всего, что публикуется на `EventBus`; несёт
    стабильное свойство `name` для маршрутизации подписок.
  - `EventHandler` — тип async-подписчика: `Callable[[DomainEvent], Awaitable[None]]`.
  - `Clock` (runtime-checkable Protocol) — источник времени с методом `now() -> datetime`;
    инъецируется, чтобы домен никогда не звал `datetime.now()` напрямую (детерминизм тестов).
  - `EventBus` (runtime-checkable Protocol) — asyncio publish/subscribe: `publish(event)` и
    `subscribe(event_name, handler)`.
  - `LLMProvider` (runtime-checkable Protocol) — OpenAI-совместимый провайдер завершений
    (Tier 0 локальный / Tier 1 API): `complete(messages, *, stream=False)`.
  - `LLMMessage` — чат-сообщение для провайдера (`Mapping[str, str]`, роль + контент).
  - `ToolLoopMessage` — сообщение tool-loop'а: как `LLMMessage`, но значение может быть
    структурным массивом `tool_calls` (нативный tool-call ход ассистента), поэтому значения
    типизированы как `object`, а не `str` (BOB-069). Богаче-типизирован только re-ask
    tool-loop'а; обычное завершение остаётся string-only, и широкий тип не течёт всюду.
  - `JsonValue` — JSON-декодируемое значение soul-артефакта (объект/массив/скаляр),
    переносимое `SoulStore`.
- **__init__.py** — фасад пакета, реэкспортирующий контракты как shared kernel.

## Инварианты

- Kernel не импортирует ни один вертикальный модуль (никаких циклов; граница-проверка
  в `.beadloom/_graph/rules.yml`).
- Только Protocol/type-определения: ни I/O, ни LLM-вызовов, ни транспорта.
- `Clock`/`EventBus`/`LLMProvider` помечены `@runtime_checkable` для structural-проверок в тестах.

## API

Модуль `src/bob/kernel/ports.py`:
- `Clock.now()` → `datetime` — текущее timezone-aware время.
- `EventBus.publish(event)` / `EventBus.subscribe(event_name, handler)` — доставка и подписка.
- `LLMProvider.complete(messages, *, stream=False)` → `str | AsyncIterator[str]` — завершение
  чат-хода; при `stream=True` отдаёт токены.
- `DomainEvent.name` → `str` — стабильное имя типа события.
- Типы-алиасы: `LLMMessage`, `ToolLoopMessage`, `JsonValue`, `EventHandler`.

## Тестирование

Контракты покрываются косвенно — через тесты реализаций сеймов (например
`tests/application/runtime/test_event_bus.py` для `EventBus`, `tests/infrastructure/llm/`
для `LLMProvider`) и structural-проверки инъекции в use-case-тестах.

<!-- beadloom:track=src/bob/kernel/ports.py -->
