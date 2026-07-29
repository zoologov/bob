<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Архитектура Боба

> **Навигационный обзор.** Этот документ — карта системы: слои, доменные модули,
> граф зависимостей и сквозной поток обработки сообщения. Подробности по каждому
> модулю живут в отдельных SPEC (`domains/<module>/README.md`,
> `services/runtime.md`) — ссылки в таблице ниже. Первый запуск —
> [`getting-started.md`](getting-started.md).

Боб — это единый Python-процесс, который держит **два aiogram-бота** (Боб и
GUPPI), локальный и облачный LLM за провайдер-агностичным роутером, память на
SQLite и ядро личности (Higher Mind). Пользователь пишет в приватную
Telegram-supergroup: Боб живёт в своём форум-топике и отвечает «печатает…»-
индикатором и форматированным rich-сообщением — с учётом настроения, вкусов и
памяти — а GUPPI работает привратником и админом в General. Оба бота — админы
группы, поэтому групповое сообщение может прийти на обоих; их поллит один
`MultiBotGateway`, дедуплицируя по `(chat_id, message_id)`. Система переживает
рестарты процесса и машины. Доступ закрыт авторизацией (owner + allowlist + scope
по чату), отказ неавторизованному **виден**, петля устойчива к транзиентным
сетевым сбоям, а навыки Боба исполняются через стабильный Capability-шов. На
каждый входящий Боб **понимает сообщение в контексте** и выбирает — как человек —
ответить словами, поставить эмодзи-реакцию или промолчать (семантическое
суждение, BOB-049). А если связь с моделью рвётся на существенном шаге — это
**полный Боб или честный GUPPI-нотис**, а не деградированный полуответ. Боб не
только реактивен: проактивный drive-движок (BOB-010) иногда пишет первым по
«порыву» из внутреннего состояния, под governance-потолками и owner-командами
`/quiet`/`/wake`.

## Слои (DDD + гексагональная архитектура)

Зависимости направлены только внутрь: `runtime → infrastructure → application →
domain`. Домен не импортирует ничего наружу; приложение зависит от домена через
порты-протоколы и не импортирует инфраструктуру; композиция живёт только в пакете
`src/bob/runtime/` (composition root; `app.py` — тонкий re-export shim над ним).

```
src/bob/
  kernel/            # 🔴 SHARED KERNEL (BOB-062.8): инфра-нейтральные кросс-модульные
                     #   контракты — Clock, DomainEvent, EventBus, EventHandler,
                     #   JsonValue, LLMMessage, LLMProvider. Чистый inward-safe leaf
                     #   (только stdlib/typing); любой модуль может импортить,
                     #   kernel НЕ импортит модули (правила kernel-no-*).
  <module>/          # 7 ВЕРТИКАЛЬНЫХ бизнес-модулей (domain-first, BOB-062): coding,
                     #   memory, proactivity, capabilities, social, personality,
                     #   conversation. Каждый собирает СВОИ три слоя внутри одного
                     #   bounded-context — ports.py + логика (layer=domain), usecases/
                     #   (layer=application), adapters/ (layer=infrastructure) — и несёт
                     #   не-слойный тег module-vertical. Границы держат explicit-path
                     #   forbid_import-правила, СГЕНЕРИРОВАННЫЕ scripts/gen_boundary_rules.py.
  application/       # Тонкий слой кросс-доменных оркестраторов (нужны несколько
                     #   bounded-context'ов): usecases/ (HandleMessage-оркестратор +
                     #   EssentialRunner/PreComposeGate/privileged_fulfiller/perceive_reaction),
                     #   router/ (LLMRouter: задача → Tier + правило редакции),
                     #   runtime/ (async-примитивы: AgentRuntime, AsyncEventBus, periodic, retry +
                     #   intake/ — concurrency-шов между поллером и Бобом: ChatDispatcher/
                     #   ChatInbox/TurnScope, BOB-066).
  infrastructure/    # Адаптеры общих компонентов: telegram/ (MultiBotGateway + GUPPI +
                     #   aiogram), llm/ (OpenAICompatProvider + фабрика),
                     #   persistence/ (connection-kernel SqliteConnection + schema.sql),
                     #   config/ (ConfigLoader).
  runtime/           # composition root + entrypoint (единственный слой, зовущий все
                     #   слои и все модули; модули НЕ импортят runtime). Отличать от
                     #   application/runtime/ (async-примитивы, НЕ composition root).
  app.py             # тонкий re-export shim над runtime (launcher ./bob + тесты держатся)
```

> **BOB-062 (domain-first реорг, завершена).** Прежний layer-first пакет
> `src/bob/domain/` **удалён**: чистая логика разъехалась по domain-слоям семи
> вертикальных модулей, а инфра-нейтральные кросс-модульные контракты собраны в
> `src/bob/kernel/`. Транзитный ports-шим (`domain/ports/`) удалён; импорты
> ходят на канон — `bob.<module>.ports` (модульные порты) и `bob.kernel.ports`
> (kernel-контракты).

Граница слоёв — не только соглашение: `tests/application/test_layering.py`
сканирует каждый файл слоя `application` и падает на любом импорте
`bob.infrastructure`. Границы вертикальных модулей держат `forbid_import`-правила
в `.beadloom/_graph/rules.yml`; их **генерирует** `scripts/gen_boundary_rules.py`
из `module-vertical`-узлов графа (explicit paths, не char-class'ы), режим
`--check` — CI-gate идемпотентности. На каждый модуль генерируются
`usecases-no-adapters`, `internals-no-usecases`, `internals-no-adapters`,
`usecases-no-infra`, `no-composition-root` + inward-границы от чужих модулей;
координационные слои (`application` / `infrastructure` / `runtime`) из
inward-модели исключены намеренно — они по определению собирают и зовут
usecases/adapters модулей.

## Доменные модули и сервисы

Каждый модуль — bounded-context со своим SPEC. За полными инвариантами, API и
тестами — переходите по ссылке.

| Модуль | Слой / вид | Что делает | SPEC |
|---|---|---|---|
| **coding** | вертикальный (business) | «Боб пишет код» — гейтованный автономный кодинг через `claude` CLI, план→апрув→worktree→PR | [`domains/coding/README.md`](domains/coding/README.md) |
| **memory** | вертикальный (business) | «Боб помнит» — эпизоды + семантические факты, гибридный recall (FTS5 + sqlite-vec → RRF) | [`domains/memory/README.md`](domains/memory/README.md) |
| **personality** | вертикальный (business) | «кто Боб есть» — mood/disposition/taste/negotiation/voice/reflection/soul | [`domains/personality/README.md`](domains/personality/README.md) |
| **conversation** | вертикальный (business) | «как ведётся ход» — адресность, conversational floor, brevity, engagement, судьи отклика | [`domains/conversation/README.md`](domains/conversation/README.md) |
| **social** | вертикальный (business) | «Боб различает людей» — идентичность, первое впечатление, отношения, авторизация, permission, genesis | [`domains/social/README.md`](domains/social/README.md) |
| **proactivity** | вертикальный (business) | «фоновая жизнь Боба» — drive-движок, свои цели (Goal Engine), само-улучшение | [`domains/proactivity/README.md`](domains/proactivity/README.md) |
| **capabilities** | вертикальный (business) | «инструменты Боба» — registry + tool-loop + навыки (recall, web_search, read_url, диаграммы, интроспекция) | [`domains/capabilities/README.md`](domains/capabilities/README.md) |
| **application** | координационный слой | тонкие кросс-доменные оркестраторы (HandleMessage), LLM-роутер, async-примитивы рантайма | [`domains/application/README.md`](domains/application/README.md) |
| **infrastructure** | координационный слой | адаптеры: Telegram (aiogram + мульти-бот), LLM-провайдеры, SQLite-connection-kernel, конфигурация | [`domains/infrastructure/README.md`](domains/infrastructure/README.md) |
| **domain (layer)** | чистое ядро | обзор чистого ядра — kernel-контракты + domain-слои вертикальных модулей | [`domains/domain/README.md`](domains/domain/README.md) |
| **runtime** | сервис | composition root + entrypoint — сборка адаптеров, подписки, poll-таск, heartbeat-тики, Genesis | [`services/runtime.md`](services/runtime.md) |

## Граф зависимостей

Диаграмма — модули (feature/component-узлы) сгруппированы по слоям, `runtime` —
composition root над всеми. Источник — `beadloom graph` (`.beadloom/_graph/`);
здесь курированный срез без служебных `part_of`/`touches_code`-рёбер.

```mermaid
graph TD
    subgraph business["Вертикальные бизнес-модули (domain)"]
        personality["personality"]
        conversation["conversation"]
        memory["memory"]
        social["social"]
        proactivity["proactivity"]
        capabilities["capabilities"]
        coding["coding"]
    end
    subgraph app["application (координация)"]
        usecases["usecases"]
        router["router"]
        runtime_app["runtime-app<br/>(async-примитивы)"]
    end
    subgraph infra["infrastructure (адаптеры)"]
        llm["llm"]
        telegram["telegram"]
        persistence["persistence"]
        config["config"]
    end
    kernel["kernel<br/>(shared kernel)"]
    runtime["runtime<br/>(composition root)"]

    conversation --> personality
    social --> personality
    proactivity --> personality
    proactivity --> conversation
    proactivity --> memory
    memory --> persistence
    coding --> router
    coding --> telegram
    social --> telegram
    llm --> capabilities
    usecases --> capabilities
    usecases --> conversation
    business --> router
    business -.->|контракты| kernel
    app -.->|контракты| kernel
    runtime --> business
    runtime --> app
    runtime --> infra
```

## Сквозной поток: обработка сообщения (perceive → decide → act → persist)

Когда пользователь пишет в Telegram, Боб проживает один ход. Поток собирается в
`HandleMessage` (`application/usecases/handle_message.py`). Подписчик `MessageReceived` в
`AsyncEventBus` — уже не сам `HandleMessage`, а быстрый `ChatDispatcher.submit`
(intake-развязка, BOB-066 Срез 2.1, см. ниже); per-`chat_id` воркер зовёт
`HandleMessage.handle(event, scope)` с per-turn `TurnScope`.

`handle_message.py` — **тонкий оркестратор, а не God-use-case** (BOB-062.6b, #9):
`HandleMessage.handle(event, scope=None)` проводит ход по фазам **perceive → who → gate →
compose+guard → post-effects**, делегируя каждую ~14 когезивным коллабораторам,
разложенным по чистым модулям. `HandleMessage.__init__` остаётся композиционным
корнем (собирает коллабораторов из инъектированных швов). Карта
коллаборатор → модуль:

| Коллаборатор | Модуль | Роль |
|---|---|---|
| `MoodPerceiver` | `personality/usecases/mood_perceiver.py` | обновить настроение из входящего + план выражения (BOB-018) |
| `GroundedAddons` | `personality/usecases/grounded_addons.py` | заземлённые добавки (рефлексия/колбэк/фасцинация), decorative |
| `VoiceComposer` | `personality/usecases/voice_composer.py` | голос + генерация ответа |
| `SocialContext` | `social/usecases/social_context.py` | per-person чтение: отправитель, первое впечатление, отношение, обида, стойка, тон |
| `AddressivityPerceiver` | `conversation/usecases/addressivity_perceiver.py` | восприятие адресности + брать ли ход |
| `EngagementModel` | `conversation/usecases/engagement_model.py` | аппетит + verbosity + after-turn feedback |
| `RecallAssembler` | `conversation/usecases/recall_assembler.py` | воспроизведение треда + absence/acknowledgment |
| `FloorManager` | `conversation/usecases/floor_manager.py` | resolve + advance разговорной реплики (floor) |
| `VerifyStep` | `conversation/usecases/verify_step.py` | предответная эпистемическая проверка → per-turn note |
| `TurnGate` | `conversation/usecases/turn_gate.py` | гейт хода: reply/react/silent (тонкий координатор) |
| `AntiRepeatGuard` | `conversation/usecases/anti_repeat_guard.py` | анти-повтор/тик + кольцо закрывающих |
| `EssentialRunner` | `application/usecases/essential_runner.py` | ретрай существенных LLM-шагов + честный GUPPI-нотис |
| `PreComposeGate` | `application/usecases/precompose_gate.py` | coding-intent + permission гейты, что могут забрать ход |
| `DiagramSender` | `capabilities/usecases/diagram_sender.py` | авто-рендер inline-mermaid + отправка диаграмм |

🔴 **Цикл compose↔guard замкнут колбэком по значению, а не импортом.**
`AntiRepeatGuard` (conversation) принимает `VoiceComposer.compose` (personality)
как callback, так что регенерация повтора вызывает композицию БЕЗ импорта
`conversation → personality`. 🔴 **Turn-local state — через аргументы, никогда не
атрибут** коллаборатора (класс — shared singleton): `verify_note`, `closer_nudge`,
`recalled`, `is_guest`, `reply`, `chat_id`, announcer прокидываются параметрами и
через тот же callback, поэтому не протекают между ходами и пользователями. 🔴 Сюда же
относится **seeded-rng хода**: `handle(event, scope)` берёт `scope.rng` (per-turn поток,
засеянный координатами `(base, chat_id, message_id)`) и прокидывает его во ВСЕ
seeded-draw-сайты хода (plan → engagement → verbosity → addressivity → surface/ack →
compose/guard), так что конкурентные чаты никогда не делят поток розыгрышей (INV-4). При
прямом вызове без scope — откат на инъектированный per-boot rng (legacy-поведение
идентично).

Фазы хода:

1. **Приём (мульти-бот роутер + единый гейт авторизации).** `MultiBotGateway`
   (infrastructure/telegram) одним проходом поллит обоих ботов, дедуплицирует
   кросс-бот по `(chat_id, message_id)`, затем центральный роутер проверяет
   topic-scope Боба и **единый гейт** `Authorizer` (social). Апдейт вне топика или
   из неразрешённого чата в пайплайн не попадает. В топике Боба ход публикуется и
   для авторизованного, и для гостя (BOB-019, ограниченный гостевой режим);
   owner-команда в General уходит GUPPI. Текстовый апдейт нормализуется в
   `MessageReceived` и публикуется в `AsyncEventBus`. **Подписчик события — быстрый,
   неблокирующий `ChatDispatcher.submit`** (intake-развязка, BOB-066 Срез 2.1): он
   буферизует сообщение и мгновенно возвращается, поэтому поллер Telegram больше НЕ ждёт
   генерацию Боба; per-`chat_id` воркер за швом дренирует буфер и зовёт `HandleMessage`
   последовательно (см. «Intake-развязка» ниже). → см.
   [social](domains/social/README.md), [infrastructure](domains/infrastructure/README.md).
2. **Perceive (обновление настроения, Tier 0).** `UpdateMoodFromText`
   (personality) читает сигналы — сентимент (Tier 0, локально), частоту, время
   суток, присутствие — и собирает `MoodDelta`. Шаг сентимент→валентность
   асимметричен (диспозиция, BOB-033), а позитивный входящий сначала тянет
   настроение к baseline — главный анти-депрессант. → см.
   [personality](domains/personality/README.md).
3. **Гейт хода: семантическое решение об отклике (BOB-049).** `_gate_turn` решает,
   **берёт ли Боб ход и как** (`REPLY`/`REACT`/`IGNORE`): `DecideResponse`
   (conversation) взвешивает по смыслу контекст хода — текст, отправитель (social),
   общий недавний тред топика (BOB-058), структурные подсказки (mentions/reply-to/
   адресность/floor), тон настроения. Без судьи — легаси-лестница адресности
   (BOB-023, BOB-025). → см. [conversation](domains/conversation/README.md).
4. **Decide (план выражения + recall + история + личность).** `REPLY` идёт в
   компоновку (ветки `REACT`/`IGNORE` завершаются внутри `TurnGate`, обе персистят
   ход, BOB-045). План выражения (BOB-018, seeded-RNG) выбирает grounded-добавки;
   воспроизводится общий тред топика (BOB-058), извлекаются факты (`MemoryRecall`,
   FTS5, единый recall на группу, BOB-051), собирается контекст ответа (идентичность,
   тон, вердикт `TasteEngine`, фантомы, факты). Negotiation-врезка (BOB-013) даёт
   директиву стойки; краткость (BOB-024) выбирает `Verbosity`. → см.
   [memory](domains/memory/README.md), [personality](domains/personality/README.md),
   [conversation](domains/conversation/README.md).
5. **Act (ответ, гибридный тиринг + селективная редакция).** `LLMRouter`
   (application/router) обрабатывает `REPLY_TO_USER`. Тир выбирается гибридно
   (BOB-006): casual → быстрый **Tier 0**, сложное/длинное/с инструментами →
   качественный **Tier 1**. `shareable_context` сопровождает вызов (память Боба);
   `private_context` **редактируется** перед любым Tier 1 (привязка к политике
   задачи, не к тиру). При сбое Tier 1 — локальный откат на Tier 0; генерация —
   существенный шаг (ретрай → честный GUPPI-нотис при провале). → см.
   [application](domains/application/README.md).
6. **Ответ (typing-индикатор + rich-финал, BOB-009).** Стрима нет (групповой
   топик). Медленная генерация идёт внутри `typing_indicator(chat_id)` (keepalive
   каждые `typing_interval` с), готовый ответ коммитится одним `reply()` — Rich
   Message'ом, привязанным к `message_thread_id`; при любой ошибке rich — деградация
   на plain. → см. [infrastructure](domains/infrastructure/README.md).
7. **Persist.** Ход сохраняется как эпизод в `episodic_log` (атрибутирован
   `sender_id`, BOB-045), снапшот настроения — в `mood_state`/`mood_history`.
   Персист идёт во **всех** ветках (`REPLY`/`REACT`/`IGNORE`/сбой). Извлечение
   фактов (`extract_facts`) — для любого участника закрытой группы (BOB-051). → см.
   [memory](domains/memory/README.md).

Параллельно идёт лёгкий **heartbeat** — фоновые asyncio-задачи рантайма, каждая
изолирована: ошибка в одном тике не роняет остальные, транзиентный сбой ретраится
с backoff. Подробнее о сборке и запуске — [`services/runtime.md`](services/runtime.md).

## Intake-развязка: поллер ⇄ Боб (BOB-066 Срез 2.1)

Раньше поллер Telegram `await`-ил всю генерацию ответа прямо в своём цикле, поэтому
следующий `get_updates` не срабатывал, пока Боб «думал». Пакет
`application/runtime/intake/` разрывает этот шов, оставляя `AsyncEventBus`, gateway и
`poll_once` нетронутыми — быстрым стал только обработчик за швом. Подписчик
`MESSAGE_RECEIVED` теперь `ChatDispatcher.submit` (нормализовать → буфер → вернуться); за
ним один воркер на `chat_id` дренирует буфер чата и зовёт `HandleMessage.handle`
последовательно.

Модули пакета:

- **decisions.py** — чистое детерминированное ядро решений: `should_debounce`
  (замкнуть окно тишины в ноль при фокусе/закрытии), `batch_grew` (продолжать ли ждать
  всплеск), `derive_turn_seed` (сид турна из `(base, chat_id, message_id)`). Mutation-tested.
- **scope.py** — `TurnScope` (frozen-dataclass: `chat_id` / `message_id` / собственный
  `Random`) + фабрика `new_turn_scope`; изолированный per-turn контекст, прокинутый через ход.
- **inbox.py** — `ChatInbox`: per-`chat_id` буфер с debounce-окном. `offer` неблокирующий
  (append + wake); `drain_batch` ждёт короткое окно тишины «пусть допишут» и отдаёт
  осевший всплеск; снапшот+очистка синхронны (без `await` внутри), поэтому конкурентный
  `offer` не теряется. `peek_since` — недренажный снапшот для будущего catch-up (Фаза 3).
- **dispatcher.py** — `ChatDispatcher`: быстрый `submit` + по одному воркер-таску на
  `chat_id`. Каждое сообщение обрабатывается под свежим `TurnScope`; `wait_for_idle` — шов
  синхронизации для тестов (прод не зовёт); `aclose` — graceful-дренаж.
- **focus.py** — `make_focus_predicate` / `message_is_focused`: переиспользует ТОТ ЖЕ
  чистый детектор `classify_addressivity` (`DIRECTED_TO_BOB`), что и гейт адресности (DRY),
  так что «фокус» = @mention Боба / reply-на-Боба / «Боб, …». `bob_user_id` резолвится лениво.

Композиционный корень (`runtime/composition.py`) меняет подписчика с
`_as_handler(handle_message)` на `_as_dispatch_handler(intake_dispatcher)`; `Application`
получает поле `intake_dispatcher`, а `Application.shutdown` дренирует его дренажом
(`runtime.stop()` → `intake_dispatcher.aclose()` → `connection.close()`), поэтому корректная
остановка досдаёт буферизованные ответы и никогда не пишет сквозь закрытое соединение.
Окно debounce конфигурируется в `dialogue.intake_debounce_ms` (по умолчанию 0 — одиночные
ходы без задержки; богатое окно «пусть допишут» — opt-in для Фазы 3).

Инварианты развязки:

- 🔴 **INV-5 (сериализация/порядок).** Один воркер владеет инбоксом чата, поэтому сообщения
  чата обрабатываются строго в порядке прихода (floor / mood / отношения продвигаются по
  порядку). Параллелизм — только МЕЖДУ чатами (разные воркеры); глобального лока нет, поэтому
  воркер может ждать только свой инбокс и не может задедлочить другой.
- 🔴 **INV-4 (turn-local изоляция).** Каждое сообщение обрабатывается под свежим `TurnScope`,
  чей `rng` засеян `(base, chat_id, message_id)` и прокинут в КАЖДЫЙ seeded-draw хода
  (включая регенерацию anti-repeat), поэтому конкурентные чаты не делят поток розыгрышей, а
  ход воспроизводим независимо от порядка диспетчеризации.
- 🔴 **INV-1/10 (фокус минует debounce).** Сообщение, прямо адресованное Бобу, замыкает
  окно тишины в ноль и флашится на уровне ВСЕГО батча (фокусное сообщение флашит растущий
  ambient-всплеск разом), поэтому фокус-сигнал никогда не теряется и не задерживается
  батчингом.

## Конфигурация, запуск и тесты

- **Первый запуск, конфигурация, env-переменные, лаунчер `./bob`** —
  [`getting-started.md`](getting-started.md).
- **Сборка приложения (composition root, порядок boot, heartbeat-тики)** —
  [`services/runtime.md`](services/runtime.md).
- **Тесты** лежат под `tests/`, повторяя структуру слоёв и модулей
  (`tests/domain/`, `tests/application/`, `tests/infrastructure/` + per-module
  наборы). Граница слоёв проверяется `tests/application/test_layering.py`,
  границы модулей — `beadloom lint --strict`; e2e — `tests/test_e2e_flow.py`,
  `tests/test_e2e_integration.py`. Инварианты и тестовые наборы каждого модуля —
  в его SPEC.
- **Пирамида качества.** Поверх модульных наборов — два верхних уровня.
  Приёмочные BDD-сценарии живут под `tests/acceptance/` (pytest-bdd,
  русскоязычный Gherkin): `.feature`-файлы описывают наблюдаемое поведение, а
  шаги проверяют его строго через границу `FakeGateway` (отправленные реплики,
  реакции, typing-индикаторы), не касаясь приватного состояния. Мутационное
  тестирование запускается адресно, по срезу, через `scripts/mutation.sh
  <module>` (mutmut мутирует только чистые доменные пакеты — технические слои
  и adapters/ports/`__init__` исключены; конвенция — ≥85% убитых мутантов на
  чистом домене с явной разметкой эквивалентных мутантов). Мутация в хуки и CI
  **не** входит — это осознанный ручной шаг. Порядок запуска, конфигурация и
  политика порога — в `.claude/dev-docs/MUTATION.md`.
