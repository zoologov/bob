<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль social — «Боб различает людей»

Социальная идентичность Боба как единая вертикаль: он *воспринимает*, кто на другом
конце хода (owner, известный друг, гость, другой бот), формирует лёгкое первое
впечатление на каждого нового, ведёт отношение по каждому человеку, умеет по-настоящему
обидеться на **конкретного** человека (обида как характер, а не книжный Exodus-reset;
охлаждение к одному участнику не студит тон к остальным), гейтит привилегии через
двойной permission-flow с решением owner'а, авторизует по allowlist в рамках
разрешённых чатов и один раз при рождении генерирует уникальную личность (genesis
SOUL). Всё это живёт *над* неизменной политикой доступа: identity ≠ authz — Боб
узнаёт человека, но кто именно допущен, решает отдельный `Authorizer`.

Это пятый **вертикальный** модуль domain-first раскладки (BOB-062.5, срез 5/8 эпика
BOB-062): «Боб различает людей» собрана в одном месте `src/bob/social/`, а не размазана
по слоям `domain/permission/` + `domain/personality/{interlocutor,first_impression,
relationship,sulk}` + `application/authz/` + `application/usecases/{permission_*,
*_sources,run_genesis}` + persistence-сторы + `infrastructure/llm/privilege_judge` +
`domain/ports/social`. Модуль охватывает три слоя **внутри** одного bounded-context,
поэтому в графе он несёт не-слойный тег `module-vertical` (правило `architecture-layers`
его рёбра пропускает), а внутреннюю и внешнюю дисциплину держат explicit-path
`forbid_import`-правила в `.beadloom/_graph/rules.yml` (§ social VERTICAL module),
сгенерированные `scripts/gen_boundary_rules.py`.

## 🔴 Ключевые решения по границам и принадлежности

1. **`interlocutor.py` — владелец `social`, разрыв цикла `personality↔social`.**
   Идентичность «кто этот человек» концептуально — ядро social, поэтому `interlocutor`
   переехал из `domain/personality/` в `social` (вариант B, утв. owner). Одно runtime-ребро
   разорвано behavior-preserving: `domain/personality/voice.py` больше НЕ импортит
   `InterlocutorKind` — `sulk_directive`/тон читают уже-вычисленное **значение** kind
   (`interlocutor.kind.value`, keyed по строковому лейблу), а классификацию делает
   вызывающий upstream. Итог: цикл `personality↔social` разорван, social владеет
   identity целиком.
2. **`social → personality` однонаправленно (`relationship → negotiation.Stance`).**
   `apply_interaction` окрашивает отношение стилем торга (уступчивый CONCEDE/AGREE
   греет иначе, чем удержание позиции `PROPOSE_ALTERNATIVE`) и настроением `Mood`.
   Это единственная зависимость наружу в personality — публичная domain-поверхность,
   легализованная в правилах границ. Обратного ребра нет.
3. **`privileged_fulfiller` ОСТАЁТСЯ в `application/usecases/`.** Это cross-domain
   оркестратор (тянет `capabilities.usecases.tool_loop` — RUNTIME), а значит
   application-оркестрация, как `handle_message`, а не social-домен. Держим его вне
   vertical'а, чтобы не заводить первый vertical↔vertical runtime-стык; social лишь
   инжектит его как порт `PrivilegedFulfiller` в `PermissionExecutor`.
4. **Долговечные сторы читают connection-kernel.** social-сторы (first_impression /
   relationship / sulk / permission_request) пишут через `.connection`-шов общего
   `SqliteConnection` (`infrastructure/persistence/connection.py`); allowlist — через
   его `kv`-таблицу; soul_store — файловый (`data/soul/`). Обратного ребра
   `kernel → social` нет. schema-таблицы (`first_impression`, `person_relationship`,
   `sulk_state`, `person_sulk`, `permission_request`, `kv`) живут в единой `schema.sql`
   kernel'а.
   С расщеплением kernel'а в BOB-062.7b долг варианта C закрыт (connection-kernel ↔
   memory-репозиторий разведены; сторы читают чистый `.connection`-шов).
5. **Порты живут в `social/ports.py`** (Allowlist / Soul / First / Relationship / Sulk /
   PrivilegeJudge); канонический импорт — `from bob.social.ports import AllowlistStore`
   (транзитный ports-шим `bob.domain.ports` удалён, BOB-062.8).

## 🔴 Мультиперсональность: cross-sender контекст здоров

Это модуль идентичности за многолюдный диалог: `interlocutor` покрывает и людей, и ботов
(готов к будущему BobNet bot-to-bot без транспорта в домене), first_impression /
relationship / sulk-сторы ключуются по `sender_id` / `persona_id` — Боб держит отдельный
read на каждого. При этом (аудит команды 2026-07-28) **cross-sender контекст здоров**:
после BOB-058 групповой тред — **общий** (Боб видит разговор целиком), а recall памяти
**не фильтруется по автору** — реплики разных участников остаются одним контекстом хода.
То есть per-person атрибуция (кто сказал, с кем какое отношение) сосуществует с цельным
общим тредом, а не рвёт групповой диалог на изолированные диалоги «Боб ↔ каждый».

## Спецификация

### Раскладка модуля

```
src/bob/social/
  ports.py            # layer=domain          — social-порты (Allowlist/Soul/First/Relationship/Sulk/PrivilegeJudge)
  __init__.py         # layer=domain          — фасад модуля
  interlocutor.py     # layer=domain          — Interlocutor + classify (owner/known/guest/bot + trust), BOB-019
  first_impression.py # layer=domain          — FirstImpression + impression_note_for (лёгкая заметка на нового), BOB-019
  relationship.py     # layer=domain          — Relationship (4 оси) + apply_interaction (шаг за ход), BOB-014
  sulk.py             # layer=domain          — SulkState + observe_relationship/recover (обида на person, person-agnostic, анти-Exodus), BOB-014.2b/BOB-066.2.5
  permission/         # layer=domain
    entities.py       #                        — PermissionRequest (immutable pending-запрос), BOB-052.1
    intent.py         #                        — is_deny/is_grant/is_authorize (NL-предикаты решения owner'а)
    privilege.py      #                        — PrivilegeNeed/PrivilegeContext/PrivilegeJudge (шов оценки привилегии)
    state.py          #                        — PermissionState StrEnum (PENDING/APPROVED/DENIED/EXPIRED)
  usecases/           # layer=application
    authorizer.py     #                        — Authorizer: is_authorized/authorize/deauthorize (allowlist + chat-scope)
    sender_perception.py  —                    — SenderPerception: MessageReceived → Interlocutor, BOB-019
    reactor_perception.py —                    — ReactorPerception: реактор → Interlocutor, BOB-050
    permission_flow.py    —                    — PermissionFlow: обнаружить привилегию, спросить owner, записать решение (WHEN/WHO)
    permission_execution.py —                  — PermissionExecutor: исполнить решение owner'а (HOW: grant/authorize/deny)
    first_impression_sources.py —              — FirstImpressionTracker: live-шов первого впечатления
    relationship_sources.py —                  — RelationshipTracker: live-шов отношения (current/record_interaction)
    sulk_sources.py       —                    — SulkTracker: per-person live-шов обиды (current_for/observe(sender_id)/active_targets/recover) + GroupSilentAnnouncer (scope-aware announce), BOB-066.2.5
    social_context.py     —                    — SocialContext: per-person чтение хода (собеседник/впечатление/отношение/обида/стойка/тон), коллаборатор handle_message (BOB-062.6b)
    run_genesis.py        —                    — RunGenesis: первое пробуждение, генерация уникальной личности
  adapters/           # layer=infrastructure
    allowlist_store.py     —                   — KvAllowlistStore (allowlist в kv-таблице)
    soul_store.py          —                   — SoulStore (файловый reader/writer data/soul/)
    first_impression_store.py —                — SqliteFirstImpressionStore (INSERT … ON CONFLICT DO NOTHING)
    relationship_store.py  —                   — SqliteRelationshipStore (UPSERT в person_relationship)
    sulk_store.py          —                   — SqliteSulkStore (legacy per-persona sulk_state — источник owner-backfill)
    person_sulk_store.py   —                   — SqlitePersonSulkStore (per-(persona,sender) UPSERT в person_sulk + backfill_owner), BOB-066.2.5
    permission_request_store.py —              — SqlitePermissionRequestStore (pending-запросы)
    privilege_judge.py     —                   — LlmPrivilegeJudge (Tier-0 реализация PrivilegeJudge)
    permission_channels.py —                   — транспортные края гейта привилегий (BOB-052): _PermissionRequesterChannel / _PermissionNotifier + _SafeDefaultPrivilegeJudge (safe-default обёртка судьи)
    soul_loader.py         —                   — _load_soul/_default_soul: сборка in-memory SOUL из персиста data/soul/ (переехало из app.py, BOB-062.7a)
```

**Connection-kernel (общий):** конкретная запись social-сторов идёт через
`.connection`-шов `SqliteConnection` (`infrastructure/persistence/connection.py`);
schema-таблицы (`first_impression`, `person_relationship`, `sulk_state`, `person_sulk`,
`permission_request`, `kv`) живут в единой `schema.sql` kernel'а. Таблица `person_sulk`
(PK `(persona_id, sender_id)`) добавлена в BOB-066.2.5 как guarded-миграция
(`CREATE TABLE IF NOT EXISTS` — не трогает существующую базу); legacy `sulk_state`
остаётся источником одноразового owner-backfill.

**ОСТАЁТСЯ вне social:** `privileged_fulfiller.py` (application-оркестратор, решение 3);
`ports/personality.py` (MessageReactor / ReflectionReader / Fascination / ZoneClassifier
— реакция/рефлексия ≠ social); `reaction_judge.py` / `perceive_reaction.py` (personality).

### Идентичность и восприятие (чистый домен)

`Interlocutor` (`interlocutor.py`) — frozen value-object: id + display-name собеседника,
`InterlocutorKind` (OWNER / KNOWN / GUEST / BOT) и `Trust` (TRUSTED / GUEST). `classify` —
чистая функция: выводит идентичность из уже известных за ход authz-фактов (`is_owner` /
`is_authorized`) и Telegram-флага `is_bot`. Транспорта не касается, покрывает и людей, и
ботов; сам по себе НЕ меняет доступ — это восприятие поверх неизменной политики.

`FirstImpression` (`first_impression.py`) — лёгкая заметка на человека: WHO (`sender_id`),
WHEN (`first_seen_at`), одна строка `note`. `impression_note_for` — дешёвая чистая
эвристика от воспринятого `Interlocutor` (kind + имя); ничего не выдумывает — это *vibe*,
не досье. Минимальный фундамент под полный `RelationshipTracker`, не сам движок.

`Relationship` (`relationship.py`) — качество отношения Боба с одним человеком на четырёх
осях в `[-1, 1]`, стартуя с `0` (нейтрально): **trust**, **respect**, **warmth** (сильнее
всего красит тон), **compatibility**. `apply_interaction` — единственный детерминированный
шаг обновления от сигналов ОДНОГО хода (`stance`, `Mood`, `sentiment`) малыми bounded-
дельтами; сначала применяется мягкий дрейф к нейтральному `0`, так что отношение без
поддержки расслабляется обратно и никогда не убегает в закреплённый экстремум.

`SulkState` (`sulk.py`) — обида/охлаждение, дно оси вовлечённости. Вход требует ПОРОГА И
поддержания: одно плохое сообщение или бытовой мат не заводят обиду — только устойчиво
критически низкое warmth **этого человека** ИЛИ устойчивая DIRECTED-враждебность за прогон
`sustain_count` наблюдений (`observe_relationship`); здоровый ход между сбрасывает
streak. Домен теперь **person-agnostic** (BOB-066.2.5): `observe_relationship` берёт
`person_warmth` вместо `owner_warmth`, тот же порог/поддержание/затухание обслуживает и
owner'а, и любого гостя — обида ключуется по `(persona, sender)` уровнем выше. Обида несёт
затухающую `intensity`, тон становится тише и суше (не reset личности), и НЕ трогает ни
память, ни soul — Боб «отходит», а не «уходит». `recover` — ГАРАНТИРОВАННЫЙ выход одним
лишь временем (даже при нулевом warmth блокировки навсегда нет; тёплые ходы ускоряют
выздоровление).

### Permission-домен (BOB-052.1)

`PermissionRequest` (`permission/entities.py`) — immutable pending-запрос привилегии: кто
(не-owner), что (`what` + `kind`), исходный `request_text` (нужен, чтобы исполнить на
approve), состояние (`PermissionState`) и время; `with_state` возвращает новый объект.
`PermissionState` (`permission/state.py`) — StrEnum жизненного цикла
(PENDING → APPROVED/DENIED, либо EXPIRED). `intent.py` — чистые NL-предикаты решения
owner'а (`is_deny` проверяется ПЕРВЫМ как безопасный дефолт, затем `is_grant`,
`is_authorize`). `privilege.py` — шов оценки привилегии: `PrivilegeNeed` (исход:
`needs_permission` + `kind` tool/internal/owner_data + `what`), `PrivilegeContext` (вход:
текст + capability-подсказки + лёгкий контекст) и порт `PrivilegeJudge.assess`.

### Use-case'ы (application)

`Authorizer` (`usecases/authorizer.py`) — чистая политика доступа на единственном шлюзе:
owner допущен только внутри разрешённого чата (chat-scope связывает даже owner'а — утёкший
токен в чужом чате мёртв), любой другой — только на allowlist И в разрешённом чате.
`authorize`/`deauthorize` мутируют runtime-allowlist и персистят его через
`AllowlistStore`, так что `/authorize` переживает рестарт.

`SenderPerception` / `ReactorPerception` (`usecases/`) — шов, где `Authorizer` компонуется
с чистым `classify`: входящее `MessageReceived` (или реактор на сообщение Боба) становится
`Interlocutor`, который `HandleMessage` вплетает в голос. Это восприятие, НЕ гейт: читает
`is_owner`/`is_authorized`, но НЕ меняет решение о доступе.

`PermissionFlow` (`usecases/permission_flow.py`) — политика .2 над .1-доменом: владеет
КОГДА, не КАК. `maybe_request` для хода не-авторизованного участника спрашивает
`PrivilegeJudge`, привилегирован ли запрос; если да — заводит PENDING `PermissionRequest`,
НОТИФИЦИРУЕТ owner'а голосом Боба и мягко отвечает просителю. `maybe_decide` записывает
вердикт owner'а. `PermissionExecutor` (`usecases/permission_execution.py`) — половина
ИСПОЛНЕНИЯ (КАК): **GRANT** — перезапустить сохранённый `request_text` через
`PrivilegedFulfiller` как если бы проситель был авторизован, но ТОЛЬКО для этого одного
запроса (one-shot elevation, никакого долговечного состояния — привилегия не утекает на
другие/будущие сообщения); **AUTHORIZE** — durable-grant через `DurableAuthorizer`;
**DENY** — мягкий отказ.

`FirstImpressionTracker` / `RelationshipTracker` / `SulkTracker` (`usecases/*_sources.py`)
— тонкие live-шовы, держащие `HandleMessage` чистым от store/clock-плумбинга: `current`
/ `prior_impression` читают состояние для compose-пути, `note_first_contact` /
`record_interaction` фолдят сигналы хода и персистят. `SulkTracker` — **per-person**
(BOB-066.2.5): `current_for(sender_id)` грузит обиду к ОДНОМУ собеседнику для compose-пути
(обида на Лёшу не студит ответ Владимиру), `observe(sender_id=, person_warmth=, …)` фолдит
ход этого человека в его обиду и на свежем ВХОДЕ анонсирует её ровно раз через announcer,
`active_targets()` перечисляет тех, на кого Боб сейчас обижен, а `recover` итерирует
только активные обиды на reflect-тике (гарантированный выход временем). `current_active()`
читает обиду именно OWNER'а — это veto проактивности (Боб не пишет первым, пока обижен на
своего человека). Owner-гейт снят: любой участник ведёт свою обиду; owner — просто один
`sender_id`. `GroupSilentAnnouncer` — scope-aware null-object announcer: в owner-DM свежий
вход даёт системную строку GUPPI, в группе внеличностная строка была бы резкой, поэтому
вход МОЛЧАЛИВ (охлаждение читается через адресный тон к участнику, не broadcast'ом);
application инжектит его для group-scoped `observe`.

`SocialContext` (`usecases/social_context.py`, коллаборатор `handle_message` — BOB-062.6b, #9)
— per-person социальное чтение хода поверх этих live-швов, собирается в `HandleMessage.__init__`.
Владеет всей per-person перцепцией и эволюцией одного хода: `perceive_interlocutor`,
`recall_prior_impression`, `record_first_impression`, `load_relationship` /
`record_relationship`, `load_sulk` / `observe_sulk` (оба теперь берут `interlocutor` и
адресуют обиду по `interlocutor.sender_id` — адресный холод), а также `decide_stance` /
`relationship_tone` — ПУБЛИЧНЫЕ (их зовёт compose-путь `VoiceComposer` через инъектированный
stance-порт, так что personality не импортирует social).

`RunGenesis` (`usecases/run_genesis.py`) — одноразовое первое пробуждение (PRD US-1, US-4).
На первом запуске (нет `SOUL.md`): грузит `bob-soul/`-шаблоны («геном» — архетип, пулы
трейтов/вкусов, mood-baselines, phantom prefs, стили), генерирует конкретную уникальную
личность через `LLMRouter` на `TaskType.GENESIS` (Tier 1, Qwen) с самоосознанным
awakening-нарративом и персистит результат через `SoulStore` (`SOUL.md` + JSON). Чист по
зависимостям — только `SoulStore` (social-порт) + `router` (shared app), 0 импортов
personality.

### Адаптеры (infrastructure)

`KvAllowlistStore` (`adapters/allowlist_store.py`) — allowlist как JSON-массив под одним
ключом в `kv`-таблице (`SqliteMemoryRepo.kv_get/kv_set`). `SoulStore`
(`adapters/soul_store.py`) — файловый reader/writer `data/soul/` (`SOUL.md`, JSON-профили,
append-only `genesis_log.md`; каталог создаётся по требованию). `SqliteFirstImpressionStore`
— `INSERT … ON CONFLICT DO NOTHING` (впечатление формируется ОДИН раз).
`SqliteRelationshipStore` — UPSERT в `person_relationship` (имя выбрано, чтобы не путать с
legacy single-row `relationship` owner-blob). `SqliteSulkStore` — одна строка на
`persona_id` (legacy per-persona обида, BOB-014.2b; сохранён как источник owner-backfill).
`SqlitePersonSulkStore` (`adapters/person_sulk_store.py`, BOB-066.2.5) — per-`(persona,
sender)` обида в таблице `person_sulk`: `load` (unseen пара → свежий не-обиженный дефолт),
`save` — `INSERT … ON CONFLICT(persona_id, sender_id) DO UPDATE` (обида эволюционирует),
`active_sulks` перечисляет активные строки для recovery-тика. `backfill_owner` копирует
legacy-строку `sulk_state` в `person_sulk` ОДИН раз (existence-guarded, идемпотентно, не
воскрешает уже отошедшую обиду; no-op при отсутствии legacy-строки или неконфигурированном
owner id), так что обиженный на середине owner переносится **байт-в-байт**. Весь SQL
параметризован (`?`), НЕ трогает ни память, ни soul (анти-Exodus, отдельная таблица).
`SqlitePermissionRequestStore` — pending-запросы (idempotent `ensure_schema`).
`LlmPrivilegeJudge` (`adapters/privilege_judge.py`) — Tier-0 реализация `PrivilegeJudge`:
чистый билдер промпта + router-вызов на локальной модели + чистый парсер → `PrivilegeNeed`;
ошибки НЕ глотает (`PrivilegeJudgeParseError` / ошибка router'а всплывают).

`permission_channels.py` (`adapters/permission_channels.py`, инлайн-адаптеры гейта
привилегий BOB-052, вернувшиеся из `app.py` в BOB-062.7a) — транспортные края:
`_PermissionRequesterChannel` шлёт fulfilment/decline запрашивающему через бота Боба;
`_PermissionNotifier` кладёт owner-запрос «разрешить?» в топик Боба, а ack — запрашивающему;
`_SafeDefaultPrivilegeJudge` оборачивает Tier-0 судью так, что сбой суждения/парсинга даёт
безопасный не-привилегированный дефолт и не рвёт ход. `soul_loader.py`
(`adapters/soul_loader.py`) — `_load_soul` собирает in-memory `SOUL` из персиста
`data/soul/` (`SoulStore`), `_default_soul` даёт нейтральную стартовую soul до Genesis.

## Инварианты

- **Identity ≠ authz.** `classify` и восприятие (`SenderPerception`/`ReactorPerception`)
  читают authz-факты, но НЕ меняют решение о доступе. Единственный гейт — `Authorizer`.
- **owner/guest classify.** `classify` детерминированно выводит OWNER / KNOWN / GUEST / BOT
  + trust из `is_owner`/`is_authorized`/`is_bot`; `is_owner` не chat-scoped (Боб узнаёт
  owner'а везде), доступ — chat-scoped.
- **Allowlist-авторизация.** owner допущен только в разрешённом чате; прочие — только на
  allowlist И в разрешённом чате; `/authorize` переживает рестарт (через `AllowlistStore`).
- **Первое впечатление формируется однажды.** `save` — `INSERT … ON CONFLICT DO NOTHING`:
  у вернувшегося отправителя исходная заметка/`first_seen_at` неизменны (BOB-019).
- **Отношение аккретится и не убегает.** `apply_interaction` применяет мягкий дрейф к
  нейтральному `0` первым, дельты bounded, оси в `[-1, 1]`; отношение без поддержки
  релаксирует к нейтральному, никогда не пиннится в экстремум (BOB-014).
- **Обида — per-person, анти-Exodus, гарантированный выход (INV-6).** Вход требует порога
  И поддержания (не одно сообщение / не бытовой мат); обида ключуется по `(persona, sender)`
  в ОТДЕЛЬНОЙ таблице `person_sulk` — не трогает ни память, ни soul. Адресный холод: обида
  на одного участника оставляет тон к остальным тёплым (`current_for(sender_id)` изолирован
  per-sender). `recover` даёт ГАРАНТИРОВАННЫЙ выход одним лишь временем (даже при нулевом
  warmth — блокировки навсегда нет), тёплые ходы ускоряют выздоровление. Owner-путь
  **байт-в-байт** идентичен legacy: owner — единственный live-sender, тот же
  порог/затухание/анонс, а `backfill_owner` переносит обиду на середине через upgrade
  (BOB-014.2b, BOB-066.2.5).
- **Привилегия — двойной гейт.** Не-авторизованный участник с привилегированным запросом
  не исполняется сразу: `PrivilegeJudge` (семантика) → owner решает (`PermissionFlow`) →
  исполнение (`PermissionExecutor`). GRANT — one-shot elevation по сохранённому
  `request_text`, без утечки на другие сообщения; DENY — безопасный дефолт (BOB-052).
- **Genesis — one-shot.** Уникальная личность генерируется ровно раз на первом boot'е
  (нет `SOUL.md`), затем только читается.
- **Мультиперсональность.** per-person атрибуция (`sender_id`/`persona_id`) сосуществует
  с ЦЕЛЬНЫМ общим тредом группы (BOB-058): recall не фильтруется по автору.

### Границы модуля (AaC)

Дисциплина держится explicit-path `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ social VERTICAL module, сгенерированы `scripts/gen_boundary_rules.py`):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/` (`[!u]*` / `[!au]*`-глобы);
- `usecases/` не тянут чужой `infrastructure/` напрямую (только через порты);
- снаружи к `social` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`);
- легализованы: `social → personality` (`relationship → negotiation.Stance`/`Mood` —
  публичная domain-поверхность), `social.usecases → router` (shared app), `ports`-шим.
- 🔴 цикл `personality↔social` РАЗОРВАН (`no-dependency-cycles` зелёный): `voice.py`
  больше не импортит `InterlocutorKind` в runtime.

Внутренний layer-guard модуля — `tests/social/test_layering.py`.

## API

<!-- beadloom:track=src/bob/social/ports.py -->

Модуль `src/bob/social/ports.py` (порты-протоколы, только интерфейсы):
- `AllowlistStore` — долговечный стор allowlist (`load`/`add`/…). Реализация —
  `KvAllowlistStore`.
- `SoulStore` — файловый reader/writer soul-артефактов (несёт `JsonValue` — единственная
  cross-bucket зависимость).
- `FirstImpressionStore` / `RelationshipStore` / `SulkStore` — per-sender / per-persona
  сторы (переехали сюда из personality-портов в .5).
- `PersonSulkStore` — per-`(persona, sender)` стор обиды (`load`/`save`/`active_sulks`),
  обобщение `SulkStore` по `sender_id` (BOB-066.2.5). Реализация — `SqlitePersonSulkStore`.
- `PrivilegeJudge` — семантический шов оценки привилегии (re-export из
  `permission/privilege.py`).

Фасад `src/bob/social/__init__.py` — вход в модуль. Канонический импорт портов —
`from bob.social.ports import AllowlistStore` (транзитный ports-шим `bob.domain.ports`
удалён, BOB-062.8).

Ключевые точки входа:
- Домен: `interlocutor.classify`, `first_impression.impression_note_for`,
  `relationship.apply_interaction`, `sulk.observe_relationship`/`recover`.
- Permission: `permission.privilege.PrivilegeJudge`, `permission.entities.PermissionRequest`,
  `permission.intent.is_deny`/`is_grant`/`is_authorize`, `permission.state.PermissionState`.
- Use-case'ы: `usecases.Authorizer`, `SenderPerception`/`ReactorPerception`,
  `PermissionFlow`/`PermissionExecutor`, `FirstImpressionTracker`/`RelationshipTracker`/
  `SulkTracker`, `RunGenesis`.
- Адаптеры: `KvAllowlistStore`, `SoulStore`, `SqliteFirstImpressionStore`,
  `SqliteRelationshipStore`, `SqliteSulkStore`, `SqlitePersonSulkStore`,
  `SqlitePermissionRequestStore`, `LlmPrivilegeJudge`.

Композиция (wiring authz/permission/genesis, инъекция `PrivilegedFulfiller`, навешивание
recovery-тика обиды) — в композиционном корне (`runtime/`). Долговечная запись в SQLite
идёт через `.connection`-шов connection-kernel'а `SqliteConnection`
(`infrastructure/persistence/connection.py`).

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Домен: `tests/domain/personality/test_interlocutor.py`,
  `test_first_impression.py`, `test_relationship.py`, `test_sulk.py`;
  `tests/domain/permission/test_privilege.py`.
- Восприятие/authz: `tests/application/authz/test_authorizer.py`,
  `test_sender_perception.py`, `test_reactor_perception.py`;
  `tests/test_reaction_perception_wiring.py`.
- Permission-flow: `tests/application/usecases/test_permission_flow.py`,
  `test_permission_execution.py`, `test_permission_acceptance.py`,
  `test_reaction_perception_acceptance.py`.
- Live-шовы: `tests/application/usecases/test_first_impression_sources.py`,
  `test_relationship_sources.py`, `test_sulk_sources.py`.
- Genesis: `tests/application/usecases/test_run_genesis.py`,
  `test_run_genesis_hardening.py`.
- Адаптеры: `tests/infrastructure/persistence/test_first_impression_store.py`,
  `test_relationship_store.py`, `test_sulk_store.py`, `test_person_sulk_store.py`
  (per-person UPSERT + owner-backfill идемпотентность/не-воскрешение),
  `test_permission_request_store.py`; `tests/infrastructure/llm/test_privilege_judge.py`.
- Per-person обида (BOB-066.2.5): `tests/application/usecases/test_sulk_sources.py`
  (SulkTracker per-sender, изоляция per-(persona,sender), GroupSilentAnnouncer);
  BDD-сценарии `tests/acceptance/features/person_sulk.feature` +
  `tests/acceptance/steps/test_person_sulk.py` (адресный холод, бытовой мат ≠ hostile,
  гарантированный выход временем).
- Layer-guard модуля: `tests/social/test_layering.py`.
