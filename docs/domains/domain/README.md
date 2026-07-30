<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Слой domain — чистое ядро Боба

Обзор domain-слоя как **концепции**, а не отдельного пакета. Чистая логика и модели
Боба: без I/O, без LLM, без Telegram. Домен не импортирует ничего наружу — он
общается с транспортом, LLM, хранилищем и временем исключительно через
порты-протоколы, которые реализуют адаптеры инфраструктуры.

> **BOB-062 (domain-first реорг, завершена).** Прежний layer-first пакет
> `src/bob/domain/` **удалён**: чистое ядро больше не живёт в одной папке. Оно
> разъехалось по **domain-слоям семи вертикальных модулей** (root-файлы + `ports.py`
> каждого модуля), а инфра-нейтральные **кросс-модульные контракты** собраны в
> shared kernel `src/bob/kernel/`. Этот документ — навигационная карта: где теперь
> искать чистую доменную логику.

## Где живёт чистое ядро

### Shared kernel — `src/bob/kernel/ports.py`

Инфра-нейтральные контракты, которые нужны нескольким модулям сразу:

- `LLMProvider` — `async complete(messages, *, stream)` → `str | AsyncIterator[str]`.
- `LLMMessage`, `JsonValue` — общие value-типы обмена с моделью. `LLMMessage`
  (`Mapping[str, str]`) — обычная чат-реплика role+content. `ToolLoopMessage`
  (`Mapping[str, object]`, BOB-069) — реплика петли инструментов: как `LLMMessage`,
  но значение может быть структурным массивом `tool_calls` (нативный tool-call-ход
  ассистента — список объектов `{"id","type","function":{…}}`), поэтому значения
  типизированы `object`, а не `str`. Более широкий тип несёт ТОЛЬКО переспрос петли
  инструментов; обычное завершение остаётся строковым.
- `Clock` — `now()` → `datetime` (инъекция времени; запрет `datetime.now()` в домене).
- `EventBus` — `publish(event)`, `subscribe(event_name, handler)`; `EventHandler`.
- `DomainEvent` — маркер с `name` для маршрутизации на шине.

kernel — чистый inward-safe leaf: только stdlib/typing, любой модуль может его
импортить, kernel не импортит модули (правила `kernel-no-*` в
`.beadloom/_graph/rules.yml`).

### Domain-слои вертикальных модулей

Каждый модуль держит свою чистую логику и свои порты в собственном domain-слое
(root-файлы + `ports.py`). Полные спецификации — в SPEC модуля:

| Модуль | Чистое ядро (примеры) | SPEC |
|---|---|---|
| **personality** | `Mood`, `MoodDelta`, `TasteEngine`/`Verdict`, `Negotiation`/`Stance`, `SOUL`, `voice`, семейство `reaction` | [`../personality/README.md`](../personality/README.md) |
| **memory** | `EpisodicEvent`, `SemanticFact`; порты `MemoryRepo`/`MemoryRecall`/`Embedder`/`Reranker` | [`../memory/README.md`](../memory/README.md) |
| **conversation** | адресность, conversational floor, brevity, engagement, судьи отклика; порты `ConversationFloorStore`/`CloserLog`/`ZoneClassifier` | [`../conversation/README.md`](../conversation/README.md) |
| **social** | идентичность собеседника, первое впечатление, отношения, permission; порты `AllowlistStore`/`SoulStore`/… | [`../social/README.md`](../social/README.md) |
| **proactivity** | `UrgeModel`, `SocialEnergy`, `Governance`, `ProactiveDecider`, `ProactivityState` | [`../proactivity/README.md`](../proactivity/README.md) |
| **capabilities** | `Capability`-контракт + value-объекты вызова инструментов (`ToolCall`/`ToolCallResult`/`ToolDefinition`), чистые diagrams/introspection | [`../capabilities/README.md`](../capabilities/README.md) |
| **coding** | доменное состояние сессии кодинга, переходы, narrate; порты `ClaudeCodeRunner`/`Worktree`/… | [`../coding/README.md`](../coding/README.md) |

## Инварианты (общие для domain-слоя)

- Домен не выполняет I/O и не импортирует `application` или `infrastructure`
  (проверяется `forbid_import`-правилами границ модулей + `tests/application/test_layering.py`).
- Порты — только контракты (структурные `typing.Protocol`): реализаций в domain-слое нет.
- Числовые инварианты домена ограничены и проверяются при конструировании
  (оси `Mood` / значения вкусов — `[-1, 1]`; conviction / confidence — `[0, 1]`;
  порыв / социальная энергия — `[0, 1]`); нарушение границы — `ValueError`.
- Метки времени памяти обязаны быть timezone-aware.
- Вердикты `TasteEngine`, позиции `Negotiation` и проактивные решения
  детерминированны и тестируемы без LLM; час суток и стохастика приходят из
  инъецированных `Clock` и seeded RNG (в домене нет `datetime.now()` / `random`).
- kernel — чистый leaf: не импортит ни модули, ни `application`/`infrastructure`.

## Тесты

Тесты чистого ядра лежат под `tests/domain/` (mood/taste/negotiation/soul,
memory-entities, proactivity urge/governance/decision) и в per-module наборах
каждого модуля. Полные списки — в соответствующих SPEC.
