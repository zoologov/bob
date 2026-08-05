<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# kernel — общее ядро контрактов

Инфра-нейтральные контракты, на которые опирается каждый вертикальный модуль:
рантайм-сеймы (`Clock`, `EventBus`, `EventHandler`, `DomainEvent`, `LLMProvider`),
общие value-объекты (`LLMMessage`, `ToolLoopMessage`, `JsonValue`) и общий словарь
терминов эпизодического лога (`WORK_EVENT_TYPE`). Это *только контракты и слова* —
структурные `typing.Protocol` и константы, без реализаций. Классический DDD shared
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
- **episode_types.py** — общий словарь `event_type` эпизодического лога: термины, которые
  пишет один контекст, а читают другие.
  - `WORK_EVENT_TYPE` (`"work"`) — дистиллированная первого-лица операторская вспоминка
    dev-сессии (BOB-087.B1). `memory` её минтит (`work_episode_event`) и ключует на ней
    register-aware recall, `conversation` вычищает её из проигранной нити (BOB-087.C8),
    `personality` озвучивает её провенанс. Слово общее — поэтому оно тут: пока термин жил
    в `memory`, `conversation` вынужден был импортировать соседний домен, и это замыкало
    цикл `conversation → memory → runtime-app → conversation` (bob-abk.32).
    `bob.memory.work_journal` ре-экспортирует термин ради совместимости импортов.
- **visibility.py** — общий словарь оси ПРИВАТНОСТИ и правило наследования метки
  производной записью (bob-g7t).
  - `VISIBILITY_PUBLIC` (`"public"`) / `VISIBILITY_OWNER_PRIVATE` (`"owner_private"`) —
    два разрешения, которые несёт воспоминание; хранятся в nullable-колонке, и `NULL`
    читается как публично (осознанный fail-open метки-разрешения, BOB-066 2.6).
  - `is_owner_private(visibility)` — единственное определение «приватного»: ровно
    `owner_private` без учёта регистра и пробелов; `None` и любое неизвестное слово —
    публично (незнакомому слову не позволено молча прятать публичную память).
  - `strictest_visibility(labels)` — метка ПРОИЗВОДНОЙ записи (сегодня — дайджест
    консолидации): самая строгая среди меток источников. Хоть один `owner_private` —
    вся производная приватна; пустой набор источников тоже приватен (публичность нечем
    подкрепить). Правило живёт в ядре, потому что нужно `memory`, а прямой импорт
    `memory → social` замыкает цикл узлов — тот же случай, что и с `WORK_EVENT_TYPE`.
- **__init__.py** — фасад пакета, реэкспортирующий контракты как shared kernel.

## Инварианты

- Kernel не импортирует ни один вертикальный модуль (никаких циклов; граница-проверка
  в `.beadloom/_graph/rules.yml`).
- Только Protocol/type-определения и общий словарь: ни I/O, ни LLM-вызовов, ни транспорта.
- Термины `episode_types` ПЕРСИСТЯТСЯ в эпизодическом логе — их значения стабильны
  (смена значения = переписывание уже записанной истории).
- `Clock`/`EventBus`/`LLMProvider` помечены `@runtime_checkable` для structural-проверок в тестах.

## API

Модуль `src/bob/kernel/ports.py`:
- `Clock.now()` → `datetime` — текущее timezone-aware время.
- `EventBus.publish(event)` / `EventBus.subscribe(event_name, handler)` — доставка и подписка.
- `LLMProvider.complete(messages, *, stream=False)` → `str | AsyncIterator[str]` — завершение
  чат-хода; при `stream=True` отдаёт токены.
- `DomainEvent.name` → `str` — стабильное имя типа события.
- Типы-алиасы: `LLMMessage`, `ToolLoopMessage`, `JsonValue`, `EventHandler`.

Модуль `src/bob/kernel/episode_types.py`:
- `WORK_EVENT_TYPE` → `str` — `event_type` дистиллированного рабочего эпизода (`"work"`).

Модуль `src/bob/kernel/visibility.py`:
- `VISIBILITY_PUBLIC` / `VISIBILITY_OWNER_PRIVATE` → `str` — две метки оси приватности.
- `is_owner_private(visibility: str | None)` → `bool` — приватна ли запись с такой меткой.
- `strictest_visibility(labels: Iterable[str | None])` → `str` — самая строгая метка среди
  источников (метка производной записи).

## Тестирование

Контракты покрываются косвенно — через тесты реализаций сеймов (например
`tests/application/runtime/test_event_bus.py` для `EventBus`, `tests/infrastructure/llm/`
для `LLMProvider`) и structural-проверки инъекции в use-case-тестах. Общий словарь
покрыт напрямую: `tests/domain/kernel/test_episode_types.py` (стабильность термина `work`
и его отличие от `self_action`) плюс проверка ре-экспорта в
`tests/domain/memory/test_work_journal.py`. Правило наследования метки приватности —
`tests/domain/kernel/test_visibility.py` (строгость против «большинства» и «последней»,
пустой набор, неизвестный тег, drift-guard против копий литералов в `social.disclosure`);
оно под мутационным гейтом (`scripts/mutation.sh kernel.visibility`).

<!-- beadloom:track=src/bob/kernel/ports.py -->
