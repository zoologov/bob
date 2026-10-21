<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# kernel — общее ядро контрактов

Shared Kernel Боба — инфра-нейтральные контракты и общий словарь, на которые опирается
каждый вертикальный модуль. В нём лежат:

- рантайм-швы: `Clock`, `EventBus`, `EventHandler`, `DomainEvent`, `LLMProvider`,
  `UnderstudyBackedProvider`;
- общие value-типы обмена с моделью: `LLMMessage`, `ToolLoopMessage`, `JsonValue`;
- общий словарь эпизодического лога: `WORK_EVENT_TYPE`, `Recalled`;
- события интейка: `MessageReceived`, `BobMessageReaction`;
- порты памяти и ответа: `EpisodeReader`, `MemoryRecall`, `ReplyGateway`, `BobUserIdSource`;
- словарь tool-calling'а: `ToolDefinition`, `ToolCall`, `ToolCallResult`,
  `ToolCallingProvider`;
- модуляторы самоулучшения: `RuleModulators`;
- социальный словарь — кто говорит с Бобом и как он к нему относится: `Interlocutor`,
  `InterlocutorKind`, `Trust`, `Gender`, `Relationship`, `RosterMember`, `SulkState`;
- небольшие чистые правила, о которых спрашивают несколько модулей: `visibility`,
  `config_paths`, `poll_backoff`, `poll_outage`;
- здоровье LLM-провайдеров (BOB-116): правило `provider_health`, порты `HealthView`,
  `HealthObserver`, `HealthReader`, `OwnerAlertSink`, `SelfReportingProvider`, время для
  человека `local_time` и русские слова о простое `ru_text`.

В BOB-113 сюда переехали `Recalled`, события интейка, порты памяти и ответа, словарь
tool-calling'а, `RuleModulators` и социальный словарь. Их читают модули, стоящие ниже
прежнего владельца по runtime-порядку вертикалей, и объявление у владельца тянуло
сигнатуры потребителей ребром вверх (порядок и правило размещения — в
[`docs/architecture.md`](../../../../architecture.md), раздел «Порядок вертикалей»).

В ядре только значения и контракты: структурные `typing.Protocol`, frozen-датаклассы,
Enum'ы, константы и чистые правила без I/O. Поведение остаётся у модуля-владельца. Значение
может проверять собственный инвариант при конструировании (`Relationship`), но не несёт
логики своего контекста. Классический DDD shared kernel: любой модуль (`capabilities` /
`social` / `memory` / …) импортирует **отсюда**, а сам kernel не импортирует ни один модуль
Боба, поэтому циклов через него не возникает.

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
  - BOB-113 (переехали сюда без изменения сигнатур):
    - `EpisodeReader` (Protocol) — чтение недавней истории разговора (`recent_episodes`,
      `recent_episodes_for`); был в `application/usecases/handle_message.py`.
    - `MemoryRecall` (runtime-checkable Protocol) — relevance-retrieval
      (`recall(query, *, k, surface_old=False)` → `Sequence[Recalled]`); был в `memory/ports.py`.
    - `ReplyGateway` (Protocol) — исходящий канал (`typing_indicator`, `reply`,
      `send_photo`, `send_document`); был в `handle_message.py`.
    - `BobUserIdSource` (Protocol) — ленивый источник собственного `user_id` Боба; был в
      `handle_message.py`.
    - Словарь tool-calling'а: `ToolDefinition` (алиас OpenAI-описания инструмента),
      `ToolCall` / `ToolCallResult` (frozen value-объекты), `ToolCallingProvider`
      (runtime-checkable Protocol, `complete_with_tools`); были в `capabilities/ports.py`.
  - BOB-116, здоровье LLM-провайдеров. Порты в ядре, потому что докладывают и читают их обе
    стороны линии слоёв: роутер (`application`) и дублёр-обёртка с докладывающей обёрткой
    Tier-1 (`infrastructure`), а `application-no-infra` запрещает прямой импорт.
    - `HealthView` (frozen dataclass) — снимок одного провайдера: `state`,
      `consecutive_failures`, `failure_class`, `failing_since` (timezone-aware начало серии
      отказов), `stood_down_reason` (почему провайдер снят при старте, D11; `None` у
      провайдера в строю).
    - `HealthObserver` (runtime-checkable) — `async record_success(provider_id)` /
      `async record_failure(provider_id, failure_class)`; реализация глотает свои ошибки
      доставки, доклад исхода никогда не валит сам вызов.
    - `HealthReader` (runtime-checkable) — `snapshot()`, `is_degraded(provider_id)`,
      `probe_due(provider_id)`. Контракт id записан в докстринге порта (G1): читатель
      отвечает за `tier0-primary`, `tier0-understudy`, `tier1` и за `TIER0_EFFECTIVE`
      («Tier-0 целиком», не провайдер, в снимке его нет); незнакомый id — здоров, поэтому
      читатель, поданный в гейт дорожек, ОБЯЗАН отвечать за `TIER0_EFFECTIVE`, иначе гейт не
      закроется никогда. `probe_due` спрашивают о провайдерах, а не о `TIER0_EFFECTIVE`.
    - `OwnerAlertSink` (runtime-checkable) — `async notify_owner(text)`: личное сообщение
      владельцу мимо LLM. Отдельный порт, а не `RestartNotifier`: другая семантика, и путь
      обязан работать ровно тогда, когда сломан модельный стек.
    - `SelfReportingProvider` (runtime-checkable, F1) — свойство `reported_id`: маркер
      провайдера, который докладывает свои вызовы сам. По нему роутер решает не докладывать
      вызов повторно.
    `ports.py` импортирует `HealthState` из `provider_health.py` в рантайме: `get_type_hints`
    на `HealthView` должен его разрешить. Это импорт внутри ядра.
- **episode_types.py** — общий словарь `event_type` эпизодического лога: термины, которые
  пишет один контекст, а читают другие.
  - `WORK_EVENT_TYPE` (`"work"`) — дистиллированная первого-лица операторская вспоминка
    dev-сессии (BOB-087.B1). `memory` её минтит (`work_episode_event`) и ключует на ней
    register-aware recall, `conversation` вычищает её из проигранной нити (BOB-087.C8),
    `personality` озвучивает её провенанс. Слово общее — поэтому оно тут: пока термин жил
    в `memory`, `conversation` вынужден был импортировать соседний домен, и это замыкало
    цикл `conversation → memory → runtime-app → conversation` (bob-abk.32).
    `bob.memory.work_journal` ре-экспортирует термин ради совместимости импортов.
  - `Recalled` (`Mapping[str, object]`) — один recalled-элемент памяти (контент + score).
    Возвращает его `memory`, читают `conversation` и `personality` — ниже `memory`, поэтому
    тип здесь (BOB-113; был в `memory/ports.py`).
- **events.py** — события интейка на шине (переехали из `application/runtime/` в BOB-113:
  их читают `conversation` и `personality`, стоящие ниже рантайма): `MessageReceived` (сообщение
  пользователя из Telegram, нормализованное для приложения) и `BobMessageReaction`
  (реакция, добавленная/снятая на одно из собственных сообщений Боба, BOB-050); у обоих
  стабильное свойство `name` для маршрутизации. Поля `MessageReceived` — координаты хода
  (`update_id`, `chat_id`, `message_id`, `text`), отправитель (`sender_id`, `sender_name`),
  сигналы адресности (`reply_to_sender_id`, `mentions_bob`, BOB-023), канальный сигнал
  `is_group` (BOB-082.1) и два поля BOB-090:
  - `topic_id` (`message_thread_id` форум-топика) — ТОЧНЫЙ адрес рядом с `chat_id`:
    `is_group` отвечает только «личка или комната», а чтобы позже написать туда, где
    разговор действительно шёл, нужен и топик. Гейтвей знал этот сигнал всегда (он и так
    привязывает ответы Боба к треду), но до приложения его не доводил. `None` = топика нет
    (личка либо группа без форумов), и это не догадка и не замена неизвестному чату.
  - `sender_username` — Telegram-ник БЕЗ «собаки», рядом с человеческим `sender_name`. Он
    приезжал в каждом апдейте и терялся на этой границе, поэтому не существовал нигде — и
    Боб писал «@Норман» вместо `@NormanGri`. `None` = ника нет, нормальное состояние в
    Telegram, ведущее к обращению по ИМЕНИ, а не к составленному тегу.

  Оба поля имеют умолчание, поэтому событие обратно совместимо; заполняет их
  `TelegramGateway` из входящего апдейта.
- **modulators.py** — `RuleModulators` (BOB-028 .3; переехал из
  `proactivity/self_improvement.py` в BOB-113): замороженный набор мягких наклонов
  (`voice_adjustments`, `length_step`, `proactivity_bias`, `addressivity_bias`, `has_any()`).
  Собирает его `proactivity` (`build_modulators`), применяют `conversation` и `personality`.
- **interlocutor.py / relationship.py / roster.py / sulk.py** — социальный словарь
  (BOB-113, RFC D; переехал из одноимённых модулей `social/`): `Interlocutor` +
  `InterlocutorKind` + `Trust` + `Gender` (Enum), `Relationship` (4 оси в
  `[MIN_AXIS, MAX_AXIS]`, валидация в `__post_init__`), `RosterMember`, `SulkState`
  (`intensity` в `[MIN_INTENSITY, MAX_INTENSITY]`). Это только ЗНАЧЕНИЯ: их читают
  `conversation` и `personality` — ниже `social` по runtime-порядку. Поведение
  (`classify`, `detect_self_gender`/`GenderRead`, `apply_interaction`, `build_roster`,
  `observe_relationship`/`recover`) остаётся в `social` и импортирует значения отсюда;
  ре-экспортов по старым путям нет.
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
- **config_paths.py** — общее правило «как понимать ПУТЬ, заданный в конфиге» (bob-a6b.15).
  - `under_root(value, *, root)` — АБСОЛЮТНОЕ значение возвращается как есть, значение с
    `~` раскрывается по домашнему каталогу, ОТНОСИТЕЛЬНОЕ привязывается к `root` (корню
    проекта), а не к текущему каталогу процесса. Файловую систему правило не трогает и о
    существовании пути не судит.
  - Правило живёт в ядре, потому что его спрашивают и домен (`identity.credentials` —
    путь к приватному ключу принципала), и композиция (`runtime.wiring.coding` —
    `coder.clone_root`); домен не имеет права импортировать композицию, а вторая копия
    правила разъехалась бы молча — «путь не тот» видно только в проде. Тот же довод, что и
    у `strictest_visibility`.
  - 🔴 Зачем: приклеенный к абсолютному значению корень репозитория
    (`<repo>//Users/o/.config/bob/secrets/key.pem`) убивал подпись App-JWT — то есть
    ЕДИНСТВЕННАЯ безопасная конфигурация (ключи вне дерева репозитория) была невыразима, а
    прежние смоуки проходили ровно потому, что путь был относительным и небезопасным.
- **poll_backoff.py** — правило ПАУЗЫ между подряд идущими сбоями опроса Telegram (BOB-103).
  - `next_backoff(consecutive_failures)` — `0` сбоев → `0.0 с`, иначе экспонента
    `base * 2**(n-1)` с потолком `≤30 с`. Чистая детерминированная развилка; ничего не
    спит и не смотрит в окружение — async-оркестрация паузы живёт в
    `infrastructure.telegram.multibot`.
  - 🔴 Зачем: поллинг крутится `periodic(poll, interval_seconds=0.0)`; на обрыве сети
    `get_updates` бросает МГНОВЕННО, и без паузы цикл бил снова сразу → хот-луп (~30 тыс.
    строк «poll failed» в сутки на бота). Первый УСПЕШНЫЙ опрос сбрасывает счётчик, поэтому
    после возврата сети доставка не ждёт максимальную паузу (лечение не хуже болезни).
  - Живёт в ядре, потому что его спрашивает `infrastructure` (`multibot`), а
    `infrastructure` не заводится целиком в mutation-scope — ядро под мутацией отдельно.
- **poll_outage.py** — правило СИГНАЛА «оглох» поверх того же счётчика сбоев (BOB-094 срез 2).
  - `outage_state(consecutive_failures, threshold)` — `True`, когда сбоев `≥ порога`.
    Чистая детерминированная развилка границы; ничего не логирует. 🔴 Порог `> 1`
    (`< 2` отвергается): единичный блип — рутинный обрыв long-poll, НЕ «оглох».
  - 🔴 Зачем отдельно от `poll_backoff`: backoff отвечает «сколько ждать», а это ядро —
    «пора ли объявить диагноз». Латч «уже оглох?» держит async-оркестрация в `multibot`,
    чтобы WARNING-диагноз при переходе и INFO-снятие при первом успехе логировались
    РОВНО раз, а не на каждый сбой/успех. Порог из `telegram.outage_threshold`.
  - 🔴 Ограничение: сигнал — вход для НАБЛЮДАТЕЛЯ (лог + `./bob status`), НЕ Telegram-алерт.
    Оглохший Боб сам о себе в Telegram не напишет; полноценный алерт (внешний канал) —
    отдельная работа. Ядро не притворяется алертом.
- **provider_health.py** — правило здоровья LLM-провайдера по исходам вызовов (BOB-116 D1).
  - `HealthPolicy` (frozen) — `failures_threshold=5`, `duration_threshold_s=180.0`,
    `reminders_s=(600, 3600, 21600, 86400)`, `probe_s=(60, 120, 300)`; негодная политика
    отвергается при создании (`failures_threshold < 2` — одиночный отказ не диагноз, как у
    `poll_outage`; длительность `≤ 0`; пустое расписание или шаг `≤ 0`).
  - `ProviderHealth` (frozen) — `state`, `consecutive_failures`, `failing_since`,
    `failure_class`, `alerts_sent`, `last_alert_at`, `last_probe_at`, `failed_probes` (индекс
    расписания зонда). `HealthState` (`HEALTHY` / `DEGRADED`), `Transition` (`NONE` /
    `DEGRADED` / `REMINDER` / `RECOVERED`).
  - Правила: `DEGRADED` — отказов подряд `≥ failures_threshold` или с первого отказа серии
    прошло `≥ duration_threshold_s`, переход отдаётся один раз; `REMINDER` — отказ в
    `DEGRADED`, когда с прошлого сигнала прошло очередное `reminders_s` (потолок — последний
    шаг); `RECOVERED` — только первый успех из `DEGRADED`, успех после допороговых отказов —
    тихий сброс. Зонд: в `HEALTHY` вызов разрешён всегда, в `DEGRADED` — не раньше
    `probe_s[min(failed_probes, len - 1)]` от последней попытки.
  - 🔴 Ограничение, названное в модуле: ядро не различает зонд и обычный вызов — отказ ответа
    человеку в `DEGRADED` тоже сдвигает расписание зонда.
  - Идентификаторы: `TIER0_PRIMARY`, `TIER0_UNDERSTUDY`, `TIER1` (ревью M3 — один дом вместо
    литералов в трёх модулях) и `TIER0_EFFECTIVE = "tier0"` (Tier-0 целиком; переехал сюда из
    монитора в G1).
  - Логика — в функциях модульного уровня, `__post_init__` политики только зовёт
    `_check_policy`: тела методов декорированных классов mutmut не мутирует.
- **local_time.py** — в каком поясе Боб называет время человеку (BOB-116 D11):
  `in_local_zone(moment, tz=None)` — тот же момент в поясе `tz`, по умолчанию в поясе
  процесса, наивный — как есть; `utc_offset_label(moment)` — `+03:00` / `-09:30`, у наивного —
  пусто. Один пояс на сообщения владельцу, GUPPI `/status`, эпизод «я молчал» и строки лога
  монитора; до модуля три места говорили в двух поясах, и только одно подписывало.
- **ru_text.py** — единственный дом русских форм о простое провайдера (BOB-116 F3, ревью M3;
  формулировки дня и часов уточнены в G2): `plural(count, forms)`, `duration(seconds)`
  (винительный падеж: «минуту», «32 минуты»; ровно сутки — «сутки»), `period(since, until)`
  («1 октября с 06:10 до 06:42 +03:00» в пределах дня, «с 1 октября 06:10 по 10 октября 06:42
  +03:00» между датами, предлог «со» только перед днём «2»), `Speaker` / `provider_speaker`
  («облако», «дублёр», «основная модель», незнакомый — «провайдер <id>»), `failure_now` /
  `failure_then` / `failure_report` — одна таблица причин по классу отказа в трёх регистрах
  (владельцу с кодом, память от первого лица, безличная строка `/status`). Незнакомый класс
  называется как есть в скобках. Потребители — `application/router/health_messages`,
  `memory/self_action`, `infrastructure/telegram/health_status`; своих копий у них нет.
- **__init__.py** — докстринг-карта групп контрактов и правило «только stdlib и `typing`».
  Пакет ничего не ре-экспортирует: каждое имя импортируется из своего модуля
  (`from bob.kernel.events import MessageReceived`), у имени один путь.

### Кто читает ядро снизу

Одна строка на семейство: где имя жило до BOB-113, кто его производит и какие модули ниже
прежнего дома его читают (именно они не дают вернуть имя владельцу). Строки сверены по
импортам в `src/`, включая блоки `TYPE_CHECKING`.

| Семейство | Модуль ядра | Прежний дом | Кто производит | Читают ниже прежнего дома |
|---|---|---|---|---|
| `MessageReceived`, `BobMessageReaction` | `events.py` | `runtime-app` | гейтвей `infrastructure.telegram` | `conversation`, `personality` |
| `Recalled` | `episode_types.py` | `memory` | recall-адаптеры `memory` | `conversation`, `personality` |
| `EpisodeReader` | `ports.py` | `application.usecases` | `SqliteMemoryRepo` (`memory`) | `conversation` |
| `MemoryRecall` | `ports.py` | `memory` | FTS5- и гибридный recall (`memory`) | `personality` |
| `ReplyGateway` | `ports.py` | `application.usecases` | `infrastructure.telegram` | `proactivity` |
| `BobUserIdSource` | `ports.py` | `application.usecases` | `MultiBotGateway.bob_user_id` (`infrastructure.telegram`) | `conversation`, `runtime-app` |
| Tool-calling | `ports.py` | `capabilities` | `infrastructure.llm` | `personality` (`VoiceComposer`) |
| `RuleModulators` | `modulators.py` | `proactivity` | `build_modulators` (`proactivity`) | `conversation` (`TurnGate`, `AntiRepeatGuard`), `personality` (`VoiceComposer`) |
| Социальный словарь | `interlocutor.py`, `relationship.py`, `roster.py`, `sulk.py` | `social` | поведение `social` (`classify`, `apply_interaction`, `build_roster`, `observe_relationship`) | `conversation`, `personality` |
| Здоровье LLM (BOB-116, сразу в ядре — прежнего дома нет) | `ports.py`, `provider_health.py` | — | монитор `application/router/health_monitor.py`; докладывают роутер, `infrastructure.llm` (дублёр-обёртка, обёртка Tier-1) | `application` (роутер, монитор, `heartbeat.health_gated`), `infrastructure` (`llm`, `telegram`), `memory` (`self_action`), `runtime` (`wiring`) |
| Время и слова для человека (BOB-116) | `local_time.py`, `ru_text.py` | — | — | `application/router`, `memory` (`self_action`), `infrastructure/telegram` (`health_status`), `runtime` (`wiring/self_action`) |

## Инварианты

- Kernel импортирует только стандартную библиотеку и `typing`. Импорты `bob.*` есть только
  внутри самого ядра: `bob.kernel.episode_types` из `kernel/ports.py` под `TYPE_CHECKING`,
  `bob.kernel.provider_health` из `kernel/ports.py` в рантайме (BOB-116) и
  `bob.kernel.local_time` с `bob.kernel.provider_health` из `kernel/ru_text.py`.
- Kernel не импортирует ни один модуль Боба. Это держат три независимые проверки:
  правила `kernel-no-*` в `.beadloom/_graph/rules.yml` (13 штук, `severity: error`);
  `tests/domain/kernel/test_kernel_isolation.py`, где импорт каждого модуля ядра в
  изолированном интерпретаторе не загружает ни одного `bob.*` вне `bob.kernel`;
  `tests/test_no_runtime_import_cycles.py`, для которого любое ребро ИЗ ядра направлено
  вверх. 🔴 Правило `no-dependency-cycles` beadloom это направление не видит: узлы `kernel`
  и `bob-domain` делят `source: src/bob/kernel/`, входящие импорты резолвятся в
  `bob-domain`, и ребро из ядра не порождает ни одного derived-ребра (наблюдение O1 ревью
  BOB-113, доказано саботажем `kernel → memory`). Поэтому направление охраняют именно три
  проверки выше, а не правило циклов.
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
- Типы-алиасы: `LLMMessage`, `ToolLoopMessage`, `ToolDefinition`, `JsonValue`, `EventHandler`.
- `UnderstudyBackedProvider.without_understudy()` → `LLMProvider` — основной провайдер без
  аварийного дублёра (BOB-087.E).
- `EpisodeReader.recent_episodes(k)` / `recent_episodes_for(sender_id, k)` →
  `Sequence[Mapping[str, object]]` (BOB-113).
- `MemoryRecall.recall(query, *, k, surface_old=False)` → `Sequence[Recalled]` (BOB-113).
- `ReplyGateway.typing_indicator(*, chat_id)` / `reply(*, chat_id, markdown, thinking=None,
  reply_to_message_id=None)` → `int | None` / `send_photo(...)` / `send_document(...)`
  (BOB-113).
- `BobUserIdSource()` → `int | None` — `None`, пока идентичность бота не разрешена (BOB-113).
- `ToolCall` (`id`, `name`, `arguments`), `ToolCallResult` (`text`, `tool_calls`),
  `ToolCallingProvider.complete_with_tools(messages, *, tools)` → `ToolCallResult` (BOB-113).
- `HealthView(state, consecutive_failures=0, failure_class=None, failing_since=None,
  stood_down_reason=None)` (BOB-116).
- `HealthObserver.record_success(provider_id)` / `.record_failure(provider_id,
  failure_class)` — async, → `None` (BOB-116).
- `HealthReader.snapshot()` → `Mapping[str, HealthView]`; `.is_degraded(provider_id)` →
  `bool`; `.probe_due(provider_id)` → `bool` (BOB-116).
- `OwnerAlertSink.notify_owner(text)` — async, → `None` (BOB-116).
- `SelfReportingProvider.reported_id` → `str` (BOB-116 F1).

Модуль `src/bob/kernel/provider_health.py`:
- `on_failure(h, *, now, failure_class, policy)` → `tuple[ProviderHealth, Transition]`.
- `on_success(h, *, now)` → `tuple[ProviderHealth, Transition]`.
- `probe_due(h, *, now, policy)` → `bool`; `next_probe_interval(h, policy)` → `float`;
  `outage_duration(h, *, now)` → `float`.
- `HealthPolicy`, `ProviderHealth`, `HealthState`, `Transition`; константы `TIER0_PRIMARY`,
  `TIER0_UNDERSTUDY`, `TIER1`, `TIER0_EFFECTIVE`.

Модуль `src/bob/kernel/local_time.py`:
- `in_local_zone(moment, tz=None)` → `datetime`; `utc_offset_label(moment)` → `str`.

Модуль `src/bob/kernel/ru_text.py`:
- `plural(count, forms)`, `duration(seconds)`, `period(since, until)` → `str`.
- `Speaker`, `provider_speaker(provider_id)` → `Speaker`.
- `failure_now(failure_class, speaker)`, `failure_then(failure_class, speaker)`,
  `failure_report(failure_class)` → `str`.

Модуль `src/bob/kernel/events.py`:
- `MessageReceived`, `BobMessageReaction` (frozen dataclass'ы, свойство `name`);
  константы имён `MESSAGE_RECEIVED`, `BOB_MESSAGE_REACTION`.

Модуль `src/bob/kernel/modulators.py`:
- `RuleModulators` (frozen dataclass) — `has_any()` → `bool`.

Модуль `src/bob/kernel/interlocutor.py`:
- `Interlocutor` (frozen dataclass: `sender_id`, `display_name`, `kind`, `trust`,
  `gender=Gender.UNKNOWN`, `username=None`); Enum'ы `InterlocutorKind`, `Trust`, `Gender`.

Модуль `src/bob/kernel/relationship.py`:
- `Relationship` (frozen dataclass: `sender_id`, `trust`/`respect`/`warmth`/`compatibility`,
  каждая ось в `[MIN_AXIS, MAX_AXIS]`, иначе `ValueError`); константы `MIN_AXIS`, `MAX_AXIS`.

Модуль `src/bob/kernel/roster.py`:
- `RosterMember` (frozen dataclass: `sender_id`, `name`, `first_seen_at`, `is_newcomer`).

Модуль `src/bob/kernel/sulk.py`:
- `SulkState` (frozen dataclass: `active`, `intensity`, `low_streak`, `since`, `announced`);
  константы `MIN_INTENSITY`, `MAX_INTENSITY`.

Модуль `src/bob/kernel/episode_types.py`:
- `WORK_EVENT_TYPE` → `str` — `event_type` дистиллированного рабочего эпизода (`"work"`).
- `Recalled` — type-алиас `Mapping[str, object]`.

Модуль `src/bob/kernel/config_paths.py`:
- `under_root(value: str | Path, *, root: Path)` → `Path` — путь из конфига: абсолютный и
  домашний как есть, относительный от корня проекта.

Модуль `src/bob/kernel/poll_backoff.py`:
- `next_backoff(consecutive_failures: int)` → `float` — пауза в секундах после N подряд
  идущих сбоев опроса: `0` → `0.0`, иначе экспонента с потолком `≤30 с`.

Модуль `src/bob/kernel/poll_outage.py`:
- `outage_state(consecutive_failures: int, *, threshold: int)` → `bool` — «оглох ли»:
  `True`, когда сбоев `≥ threshold`; `threshold < 2` отвергается (единичный блип ≠ оглох).

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
оно под мутационным гейтом (`scripts/mutation.sh kernel.visibility`). Правило чтения пути из
конфига — `tests/domain/kernel/test_config_paths.py` (все три ветви, включая «относительный
путь НЕ следует за cwd»), а его стык с настоящим инструментом —
`tests/infrastructure/identity/test_key_path_forms_real_openssl.py`: путь к ключу в каждой
форме проходит через разбор конфига в НАСТОЯЩИЙ `openssl` и подпись проверяется
`openssl dgst -verify` (дефект дожил до живого прогона именно потому, что стык между
разбором конфига и подписью не проверял никто). Правило паузы опроса —
`tests/domain/kernel/test_poll_backoff.py` (ноль сбоев → 0.0, экспонента, потолок,
монотонность, отказ на отрицательном), под мутационным гейтом
(`scripts/mutation.sh poll_backoff` — 17 мутантов, 100 % убито); его стык с реальным
poll-циклом — `tests/infrastructure/telegram/test_multibot_poll_backoff.py` (хот-луп на
обрыве сети падает в частоте, восстановление быстрое, лог схлопывается). Правило сигнала
«оглох» — `tests/domain/kernel/test_poll_outage.py` (граница `≥`, единичный блип ≠ оглох,
отказ на пороге `≤ 1` и отрицательном счётчике), под мутационным гейтом
(`mutmut run "*outage_state*"` — 8 мутантов, 100 % убито); его стык с поллингом —
`tests/infrastructure/telegram/test_multibot_poll_outage.py` (диагноз при переходе РОВНО
раз, снятие при первом успехе РОВНО раз, блип молчит). Инвариант значения `Relationship`
(каждая из четырёх осей в `[MIN_AXIS, MAX_AXIS]`, обе границы включительно, ось названа в
ошибке) — `tests/domain/kernel/test_relationship_value.py`; предикат `RuleModulators.has_any`
(нейтральное значение — «нечего применять», любой ОДИН рычаг — «есть») —
`tests/domain/kernel/test_rule_modulators.py`. Оба под мутационным гейтом с BOB-113
(`scripts/mutation.sh kernel.relationship` — 28 мутантов, `kernel.modulators` — 4, 100 %
убито). 🔴 Проверка и предикат живут в функциях модульного уровня, а метод `@dataclass`
лишь вызывает их: mutmut не мутирует методы декорированных классов вообще, и оставленные в
теле класса они давали 0 мутантов (`.claude/dev-docs/MUTATION.md` «Порог и честность»).
Какие оси и какие рычаги входят в правило, mutmut не меряет (выпадение операнда — не его
мутант): это держат юниты на каждую ось и каждый рычаг, кусачесть доказана саботажем.

Здоровье LLM-провайдера (BOB-116) — `tests/domain/kernel/test_provider_health.py` (пороги по
числу и по длительности, напоминания по расписанию, тихий сброс, рост интервала зонда,
отказ негодной политики, дефолты, совпадающие с утверждёнными; структурные фейки
удовлетворяют портам здоровья). Время для человека — `tests/domain/kernel/test_local_time.py`,
русские слова — `tests/domain/kernel/test_ru_text.py`. Все три под мутационным гейтом,
прогоны `scripts/mutation.sh` строго по одному (каталог `mutants/` общий): `kernel.provider_health`
— 144 мутанта, 144 убито; `kernel.local_time` — 19 из 19; `kernel.ru_text` — 151 из 151 (перемер
координатора после G2). Слепые зоны названы в беадах: возвраты `Enum` и дефолты полей
`dataclass` мутантов не дают и держатся содержательными тестами и саботажами.

Изоляция ядра — `tests/domain/kernel/test_kernel_isolation.py`: первый тест находит все
модули пакета через `pkgutil` и импортирует их в подпроцессе `python -I`, проверяя, что
не загрузилось ни одного `bob.*` вне `bob.kernel`; второй требует, чтобы дома, заведённые
в BOB-113, действительно загрузились (пустой импорт не проходит).

<!-- beadloom:track=src/bob/kernel/ports.py -->
<!-- beadloom:track=src/bob/kernel/events.py -->
<!-- beadloom:track=src/bob/kernel/modulators.py -->
<!-- beadloom:track=src/bob/kernel/interlocutor.py -->
<!-- beadloom:track=src/bob/kernel/relationship.py -->
<!-- beadloom:track=src/bob/kernel/roster.py -->
<!-- beadloom:track=src/bob/kernel/sulk.py -->
<!-- beadloom:track=src/bob/kernel/provider_health.py -->
<!-- beadloom:track=src/bob/kernel/local_time.py -->
<!-- beadloom:track=src/bob/kernel/ru_text.py -->
