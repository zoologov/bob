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

### Shared kernel — `src/bob/kernel/`

Инфра-нейтральные контракты и общий словарь, которые нужны нескольким модулям сразу.

#### Контракты — `ports.py`

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

#### Общий словарь — `episode_types.py`

Термины эпизодического лога (`event_type`), о которых договорились НЕСКОЛЬКО контекстов:

- `WORK_EVENT_TYPE` (`"work"`) — дистиллированная операторская вспоминка dev-сессии
  (BOB-087.B1). `memory` её пишет (`work_episode_event`) и ключует на ней
  register-aware recall, `conversation` вычищает её из проигранной нити (C8),
  `personality` озвучивает её провенанс. Слово общее → живёт в ядре;
  `bob.memory.work_journal` ре-экспортирует его ради совместимости импортов.
  Значения ПЕРСИСТЯТСЯ в эпизодическом логе — менять их значит переписывать историю.

#### Ось приватности — `visibility.py`

Метки-разрешения воспоминания и правило, по которому их наследует ПРОИЗВОДНАЯ запись
(bob-g7t):

- `VISIBILITY_PUBLIC` / `VISIBILITY_OWNER_PRIVATE` — два слова оси; `NULL` в базе
  читается как публично (осознанный fail-open метки-разрешения, BOB-066 2.6).
- `is_owner_private(visibility)` — единственное определение «приватного»: ровно
  `owner_private` без учёта регистра/пробелов; `None` и неизвестный тег — публично.
- `strictest_visibility(labels)` — самая строгая метка среди источников. Хоть один
  `owner_private` — производная (дайджест консолидации) приватна; пустой набор
  источников тоже приватен, потому что публичность нечем подкрепить.

Слово общее (`memory` мнёт производные записи, `social` судит такт разглашения) →
живёт в ядре: прямой импорт `memory → social` замыкал бы цикл узлов, ровно как было с
`WORK_EVENT_TYPE`. Значения ПЕРСИСТЯТСЯ в `episodic_log.visibility` /
`semantic_memory.visibility`.

#### Путь из конфига — `config_paths.py`

Одно правило на весь проект, «как понимать ПУТЬ, заданный в конфиге» (bob-a6b.15):

- `under_root(value, *, root)` — АБСОЛЮТНОЕ значение как есть, значение с `~` по
  домашнему каталогу, ОТНОСИТЕЛЬНОЕ от `root` (корня проекта), а не от текущего
  каталога процесса. Файловую систему не трогает, о существовании пути не судит.

Правило общее (`identity.credentials` читает им путь к приватному ключу принципала,
`runtime.wiring.coding` — `coder.clone_root`) → живёт в ядре: домен не имеет права
импортировать композицию, а вторая копия разъехалась бы молча. 🔴 Приклеенный к
абсолютному значению корень репозитория (`<repo>//Users/o/.config/bob/secrets/key.pem`)
убивал подпись App-JWT: ключи ЖИВУТ вне дерева репозитория (bob-zmp), то есть
единственная безопасная конфигурация была невыразима.

#### Пауза между сбойными опросами — `poll_backoff.py`

Одно правило «сколько ждать после подряд идущих сбоев опроса Telegram» (BOB-103):

- `next_backoff(consecutive_failures)` — `0` сбоев → `0.0 с`, иначе экспонента
  `base * 2**(n-1)` с потолком `≤30 с`. Чистая детерминированная развилка, ничего
  не спит и не смотрит в окружение.

Корень: поллинг крутится `periodic(poll, interval_seconds=0.0)` — при живой сети это
правильно (long-poll сам держит темп), но на обрыве сети `get_updates` бросает
МГНОВЕННО, и цикл без паузы бил снова сразу → хот-луп (~30 тыс. строк «poll failed» в
сутки на бота). 🔴 Лечение не хуже болезни: первый УСПЕШНЫЙ опрос сбрасывает счётчик,
поэтому после возврата сети доставка не ждёт максимальную паузу. Живёт в ядре, потому
что спрашивает его `infrastructure.telegram.multibot` (пауза + схлопывание лога), а
`infrastructure` не заводится целиком в mutation-scope — ядро под мутацией отдельно.

#### Сигнал «я оглох» — `poll_outage.py`

Одно правило «пора ли объявить диагноз» поверх того же счётчика подряд идущих сбоев
(BOB-094 срез 2):

- `outage_state(consecutive_failures, threshold)` — `True`, когда сбоев набралось
  `≥ порога`. Чистая детерминированная развилка границы, ничего не логирует и не
  смотрит в окружение. 🔴 Порог обязан быть `> 1` (`< 2` отвергается): единичный блип
  — рутинный обрыв long-poll, НЕ «оглох», иначе наблюдатель захлебнулся бы ложными
  тревогами.

Разделение с `poll_backoff`: backoff отвечает «сколько ждать» (гасит хот-луп), а это
ядро — «пора ли объявить диагноз». Оркестрация в `infrastructure.telegram.multibot`
держит per-bot латч, чтобы WARNING-диагноз при переходе в «оглох» и INFO-снятие при
первом успехе логировались РОВНО раз, а не на каждый сбой/успех. Порог из конфига
`telegram.outage_threshold`.

🔴 Ограничение, названное честно: сигнал — вход для НАБЛЮДАТЕЛЯ (строка в логе +
`./bob status`), а НЕ Telegram-алерт. Оглохший Боб сам о себе в Telegram не напишет —
его канал и есть то, что легло; полноценный алерт требует ВНЕШНЕГО канала и делается
отдельной работой. Ядро сознательно не притворяется алертом.

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
