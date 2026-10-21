<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T08:49:35.850635+00:00 · coverage 100% (`bob-domain`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

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
- Порты, которые читают модули НИЖЕ их прежнего владельца (переехали в BOB-113, сигнатуры
  не менялись): `EpisodeReader` и `MemoryRecall` (чтение памяти), `ReplyGateway`
  (исходящий канал), `BobUserIdSource` (собственный id Боба) и словарь tool-calling'а
  `ToolDefinition` / `ToolCall` / `ToolCallResult` / `ToolCallingProvider` (рядом с
  `ToolLoopMessage`).

#### События интейка — `events.py`

`MessageReceived` и `BobMessageReaction` (+ константы имён) — события, которые гейтвей
публикует на шину. Переехали из `application/runtime/` (BOB-113): их читают
`conversation` и `personality`, стоящие ниже рантайма.

#### Модуляторы самоулучшения — `modulators.py`

`RuleModulators` — замороженный набор мягких наклонов из одобренных правил BOB-028.
Собирает `proactivity` (`build_modulators`), применяют `conversation` и `personality`
(ниже `proactivity`) → значение в ядре (BOB-113). Предикат `has_any()` — «есть ли что
применять» — делегирует функции модульного уровня `_has_any_lever`: метод `@dataclass`
mutmut не мутирует, а так предикат под мутационным гейтом (bob-etb.8).

#### Социальный словарь — `interlocutor.py`, `relationship.py`, `roster.py`, `sulk.py`

Значения «кто говорит с Бобом и как он к нему относится» (BOB-113, RFC D):
`Interlocutor` + `InterlocutorKind` + `Trust` + `Gender` (Enum) — в `interlocutor.py`,
`Relationship` (4 оси, `MIN_AXIS`/`MAX_AXIS`) — в `relationship.py`, `RosterMember` — в
`roster.py`, `SulkState` (`MIN_INTENSITY`/`MAX_INTENSITY`) — в `sulk.py`. Их читают
`conversation` и `personality` — ниже `social`, поэтому значения в ядре; поведение
(`classify`, `detect_self_gender`, `apply_interaction`, `build_roster`,
`observe_relationship`/`recover`) осталось в `social`. Инвариант значения `Relationship`
(каждая ось в `[MIN_AXIS, MAX_AXIS]`, границы включительно) проверяют функции модульного
уровня (`_require_axes_within_bounds` → `_require_within_bounds` по одной на ось), которые
зовёт `__post_init__` — по той же причине, что и у модуляторов. Границы `MIN_AXIS`/`MAX_AXIS`
— единственный источник: `personality.reaction_effect` клампит теплоту ими же, своей копии
нет (bob-etb.8).

#### Общий словарь — `episode_types.py`

Термины эпизодического лога (`event_type`), о которых договорились НЕСКОЛЬКО контекстов:

- `WORK_EVENT_TYPE` (`"work"`) — дистиллированная операторская вспоминка dev-сессии
  (BOB-087.B1). `memory` её пишет (`work_episode_event`) и ключует на ней
  register-aware recall, `conversation` вычищает её из проигранной нити (C8),
  `personality` озвучивает её провенанс. Слово общее → живёт в ядре;
  `bob.memory.work_journal` ре-экспортирует его ради совместимости импортов.
  Значения ПЕРСИСТЯТСЯ в эпизодическом логе — менять их значит переписывать историю.
- `Recalled` (`Mapping[str, object]`) — один recalled-элемент памяти; читают `conversation`
  и `personality`, поэтому тип в ядре (BOB-113, был в `memory/ports.py`).

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
импортить, kernel не импортит модули. Это держат правила `kernel-no-*` в
`.beadloom/_graph/rules.yml`, тест изоляции `tests/domain/kernel/test_kernel_isolation.py`
и гард `tests/test_no_runtime_import_cycles.py`. Правило `no-dependency-cycles` рёбер ИЗ
ядра не видит: узлы `kernel` и `bob-domain` делят один `source` (наблюдение O1 ревью
BOB-113). Кто из модулей читает каждое семейство контрактов и почему оно не у владельца —
таблица «Кто читает ядро снизу» в [`features/kernel/SPEC.md`](features/kernel/SPEC.md).

### Domain-слои вертикальных модулей

Каждый модуль держит свою чистую логику и свои порты в собственном domain-слое
(root-файлы + `ports.py`). Полные спецификации — в SPEC модуля:

| Модуль | Чистое ядро (примеры) | SPEC |
|---|---|---|
| **personality** | `Mood`, `MoodDelta`, `TasteEngine`/`Verdict`, `Negotiation`/`Stance`, `SOUL`, `voice`, семейство `reaction` | [`../personality/README.md`](../personality/README.md) |
| **memory** | `EpisodicEvent`, `SemanticFact`; порты `MemoryRepo`/`Embedder`/`Reranker` (`MemoryRecall` — в kernel, BOB-113) | [`../memory/README.md`](../memory/README.md) |
| **conversation** | адресность, conversational floor, brevity, engagement, судьи отклика; порты `ConversationFloorStore`/`CloserLog`/`ZoneClassifier` | [`../conversation/README.md`](../conversation/README.md) |
| **social** | поведение над социальным словарём ядра (`classify`, род по само-презентации, накопление отношений, ростер, обида), первое впечатление, permission; порты `AllowlistStore`/`SoulStore`/… | [`../social/README.md`](../social/README.md) |
| **proactivity** | `UrgeModel`, `SocialEnergy`, `Governance`, `ProactiveDecider`, `ProactivityState` | [`../proactivity/README.md`](../proactivity/README.md) |
| **capabilities** | `Capability`-контракт (словарь вызова инструментов `ToolCall`/`ToolCallResult`/`ToolDefinition` — в kernel, BOB-113), чистые diagrams/introspection | [`../capabilities/README.md`](../capabilities/README.md) |
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
