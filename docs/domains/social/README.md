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
  interlocutor.py     # layer=domain          — Interlocutor (+ gender) + classify (owner/known/guest/bot + trust), BOB-019/BOB-078 A
  gender.py           # layer=domain          — Gender/GenderRead + detect_self_gender: грамматический род по САМО-презентации (не по имени), накопление ≥2 сигналов, BOB-078 A
  first_impression.py # layer=domain          — FirstImpression (+ display_name) + impression_note_for (лёгкая заметка на нового), BOB-019/BOB-080
  roster.py           # layer=domain          — RosterMember/is_newcomer/build_roster: ростер комнаты, новизна по времени (припоминание состава), BOB-080
  relationship.py     # layer=domain          — Relationship (4 оси) + apply_interaction (шаг за ход), BOB-014
  sulk.py             # layer=domain          — SulkState + observe_relationship/recover (обида на person, person-agnostic, анти-Exodus), BOB-014.2b/BOB-066.2.5
  disclosure.py       # layer=domain          — такт разглашения: may_surface/visibility_for_scope/filter_surfaceable (initiative-surfacing фильтр provenance), BOB-066.2.6
  endorsement.py      # layer=domain          — кредит доверия: detected_endorsement/owner_endorsed_sender (owner ручается за новичка), BOB-066.2.6
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
    social_context.py     —                    — SocialContext: per-person чтение хода (собеседник/впечатление/отношение/обида/стойка/тон/ростер), коллаборатор handle_message (BOB-062.6b/BOB-080)
    roster_recall.py      —                    — RosterRecall: ambient-окно ростера (пусто без свежих новичков) + приватность OWNER/KNOWN + best-effort, BOB-080
    run_genesis.py        —                    — RunGenesis: первое пробуждение, генерация уникальной личности
  adapters/           # layer=infrastructure
    allowlist_store.py     —                   — KvAllowlistStore (allowlist в kv-таблице)
    soul_store.py          —                   — SoulStore (файловый reader/writer data/soul/)
    first_impression_store.py —                — SqliteFirstImpressionStore (INSERT … ON CONFLICT DO NOTHING; recent(limit) recency-запрос + display_name, BOB-080)
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
остаётся источником одноразового owner-backfill. Колонка `person_relationship.gender`
(REAL, nullable, само-идентифицированный род-lean, BOB-078 A) добавлена guarded-ALTER'ом
`SqliteConnection._migrate_person_relationship_gender` (`CREATE TABLE IF NOT EXISTS` не
трогает уже существующую таблицу, поэтому колонку добавляет `ALTER` только когда её нет —
аддитивно и неразрушающе; legacy-строка берёт NULL = UNKNOWN). Колонка
`first_impression.display_name` (nullable, имя участника для ростера, BOB-080) добавлена тем
же guarded-ALTER-приёмом; legacy-строка (NULL) берёт имя парсингом из `note`.

**ОСТАЁТСЯ вне social:** `privileged_fulfiller.py` (application-оркестратор, решение 3);
`ports/personality.py` (MessageReactor / ReflectionReader / Fascination / ZoneClassifier
— реакция/рефлексия ≠ social); `reaction_judge.py` / `perceive_reaction.py` (personality).

### Идентичность и восприятие (чистый домен)

`Interlocutor` (`interlocutor.py`) — frozen value-object: id + display-name собеседника,
`InterlocutorKind` (OWNER / KNOWN / GUEST / BOT), `Trust` (TRUSTED / GUEST) и `gender`
(`Gender`, по умолчанию `UNKNOWN` — нейтрально, BOB-078 A). `classify` — чистая функция:
выводит идентичность из уже известных за ход authz-фактов (`is_owner` / `is_authorized`) и
Telegram-флага `is_bot`, а `gender` пробрасывает как уже-вычисленное значение. Транспорта не
касается, покрывает и людей, и ботов; сам по себе НЕ меняет доступ — это восприятие поверх
неизменной политики.

### Грамматический род по само-идентификации (`gender.py`, BOB-078 A)

Живой баг: Боб обращался к женщине в мужском роде («он»), хотя её собственная речь была
женской («Пошл**а** учить Python»). 🔴 Принцип owner'а: **никогда не угадывать род по имени**
(«Саша»/«Женя» ненадёжны), только по **само-презентации** — как человек грамматически
помечает СЕБЯ в собственных словах. Чистое детерминированное ядро без I/O и без LLM (русское
прошедшее время несёт род окончанием глагола, разбирается правилом):

- `detect_self_gender(text)` → `Gender` (FEM / MASC / UNKNOWN) по ОДНОМУ сообщению.
  Единственный сигнал — само-презентация от 1-го лица: родовой глагол прошедшего времени о
  себе («пошла»/«сделал», в начале реплики как опущенное «я» ЛИБО сразу за «я») или явный
  маркер «я сама»/«я сам». Глагол, отданный 2-му/3-му лицу («пошёл **он**»), противоречивая
  пара в одном сообщении или имя — НЕ сигнал (UNKNOWN).
- `GenderRead` — накопительная frozen-ось уверенности: знаковый `lean` в `[-1, 1]` (`> 0`
  женский, `< 0` мужской). `observe(text)` толкает lean на один шаг по зафиксированному
  сигналу сообщения, противоречия взаимно гасятся, а `resolve()` коммитит род ТОЛЬКО когда
  `|lean|` перешагнул порог. Порог — **два шага** (BOB-078.8), поэтому род коммитится лишь
  после **≥2 согласных сигналов**: один ведущий родовой глагол, чей реальный субъект — не
  говорящий, а существительное («Была ошибка в коде»), лишь наклоняет и читается UNKNOWN —
  один глагол НЕ переворачивает род ложно. Слабая или противоречивая история остаётся UNKNOWN
  (Боб не навязывает рода).

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
`endorsed_seed(rel, sender_id)` (BOB-066.2.6, кредит доверия) — тёплый старт по
поручительству owner'а: ТОЛЬКО на первом контакте (`rel is None`) вернуть скромно
тёплую связь (`warmth 0.3` / `trust 0.2`, respect/compatibility нейтральны);
уже-сформированное отношение возвращается НЕИЗМЕНным (тот же объект), так что seed
никогда не переписывает накопленную историю, а обычный дрейф растворяет его, если
поведение новичка не подтвердит — head-start, не постоянная инфляция.

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

### Ростер комнаты — припоминание состава (`roster.py`, BOB-080)

Живой баг: на открытый вопрос «как тебе новые ребята в чате?» Боб молчал, пока имена не
назвали вслух — recall у него чисто лексический (FTS по тексту хода), и «новые ребята» не
матчило «Лиля»/«Паша», хотя оба уже лежали в `first_impression` с именем и `first_seen_at`.
🔴 Корень: у Боба не было **ростера** — retrieval-пути «перечисли недавно встреченных» (все
запросы к person-таблицам были точечные `WHERE sender_id=?`).

`roster.py` (чистый домен, I/O-free) вводит `RosterMember` (`sender_id`, `name`,
`first_seen_at`, `is_newcomer`), `is_newcomer(first_seen, now, newcomer_days)` — новизна
**строго по времени** (не по authz-kind/трасту/имени, INV-3) — и `build_roster(...)`
(исключает владельца/самого Боба, сортирует по `first_seen_at` DESC, кап `limit`, отмечает
новичков; имя — из новой колонки `first_impression.display_name`, для legacy-строк парсится из
`note`). Данные читает первый в коде **recency-запрос** `FirstImpressionStore.recent(limit)`
(`ORDER BY first_seen_at DESC`).

Surfacing — **ambient-осознание с окном**, НЕ keyword-детектор (north star: без скриптовости):
usecase `RosterRecall.recent_roster(now, viewer)` отдаёт ростер, ТОЛЬКО пока есть хоть один
свежий новичок (INV-4, не флуд) и ТОЛЬКО зрителю `OWNER`/`KNOWN` (гостю не выдаётся перечень
всех), best-effort (ошибка чтения → пустой ростер, ход не падает). Мульти-персонная
`roster_directive` (`personality/voice.py`) под рамкой «недавно зашли» называет **только**
`is_newcomer`-участников (старожилы не мислейблятся) с указанием «называй по поводу, не
притягивай». За флагом `social.roster` (+ `social.roster_newcomer_days`/`roster_limit`);
OFF → ростер пуст (ноль изменений поведения).

### Такт разглашения (`disclosure.py`, BOB-066.2.6)

Такт разглашения — **отдельная** забота от гейта привилегий (BOB-052): гейт решает,
что человек может *попросить* Боба сделать или раскрыть; такт решает, что Боб
*инициативно выкладывает* из собственной памяти в ответ. Две оси ортогональны — гость
ведёт совершенно обычный разговор (память публична, BOB-051), но Боб не должен по своей
воле выложить ему приватное owner'а. Чистое детерминированное ядро (без I/O):

- `may_surface(visibility, trust)` — предикат, который recall-конвейер спрашивает на
  каждую память. TRUSTED-собеседник (owner или известный peer) видит ВСЁ, поэтому
  owner-facing recall байт-в-байт (INV-7); гостю удерживается только `owner_private`, а
  `public` — и, защитно, legacy-`NULL` или неизвестный тег — всплывает (`NULL` = public
  держит BOB-051 нетронутой, неизвестный тег никогда молча не прячет публичную память).
  Сверка `owner_private` регистронезависима.
- `visibility_for_scope(is_group=)` — консервативный write-side классификатор: групповой
  ход — `public` (общая память комнаты), owner-DM ИЛИ *неопределённый* scope —
  `owner_private` (fail-safe, INV-8: сомнение удерживает, а не течёт).
- `filter_surfaceable(recalled, trust)` — recall-фильтр (зеркалит
  `conversation.recalled_excluding_reflections`): роняет `owner_private`-хиты, читая
  поле `visibility` каждого элемента. Для TRUSTED результат байт-в-байт равен входу
  (order-preserving, INV-7); гостю удерживается только `owner_private`.

Врезано live в `handle_message._recall_surfaceable` ПОВЕРХ unified recall (обоих путей —
FTS5 И векторного KNN, оба несут `visibility`), а write-side `_turn_visibility` штампует
провенанс на новые эпизоды и факты. Тон отказа гейта на голосовом слое —
`personality.voice.tactful_withhold_directive` (тёплая, не холодная стена). Фильтр латентен,
пока гость реально не в чате: owner (TRUSTED) всегда видит всё.

### Кредит доверия (`endorsement.py`, BOB-066.2.6)

Когда owner представляет или ручается за новичка («это мой друг Норман, ему можно
доверять»), Боб встречает того тёплым стартом, а не как чистого незнакомца — кредит
доверия, который owner выдаёт от его имени. Это *seed*, не постоянный грант: обычный
дрейф-к-нейтральному растворит его, если поведение человека не подтвердит. Чистое ядро:

- `detected_endorsement(owner_text)` — лёгкая эвристика (в духе
  `personality.profanity.is_directed_hostility`): срабатывает, когда текст читается как
  owner ПОРУЧИТЕЛЬСТВО — представление («познакомься, это мой друг») или вотум доверия
  («ему можно доверять», «я за него ручаюсь», «он свой»). Намеренно консервативна:
  нейтральное упоминание человека — не endorsement.
- `owner_endorsed_sender(owner_texts, sender_name=)` — сужает сигнал до ОДНОГО человека:
  endorsement среди недавних ходов owner'а, который НАЗЫВАЕТ этого отправителя (хватает
  имени, регистронезависимо). Тёплое слово о Лёше никогда не warm-start'ит Нормана.

Сам кредит применяется в `relationship.endorsed_seed` (см. ниже) и только на первом
контакте — этот модуль лишь ВОСПРИНИМАЕТ endorsement.

> **Live-wiring (BOB-066 Срез W.4) — за флагами, латентно, пока гости не live.** Оба
> стыка врезки провязаны:
> - **кредит доверия** за флагом `presence.endorsement.enabled` — коллаборатор
>   `EndorsementSeeder` (`application/usecases/endorsement_seeder.py`) фильтрует owner-ходы
>   из общего треда по `owner_id` через чистую `endorsement_seed()` и после реплея истории
>   пере-биндит отношение `endorsed_seed`-ом (turn-local seed, врезка в
>   `handle_message._prepare_eq_live`);
> - **такт разглашения** за флагом `presence.tact.enabled` — коллаборатор `DisclosureGuard`
>   (`application/usecases/disclosure_guard.py`) переиспользует порт `PrivilegeJudge` и на
>   гостевой `owner_data`-запрос выдаёт `tactful_withhold_directive`, threaded в compose+guard
>   (turn-constant, как `room_tone`).
>
> Оба флага OFF по умолчанию → builder возвращает `None`, врезка не строится, путь
> байт-в-байт (`_prepare_eq_live`: seeder None → relationship без изменений, guard None →
> `withhold_directive` пуст). 🔴 Привилегия-ГЕЙТ не тронут — DisclosureGuard красит только
> ГОЛОС отказа. Recall-фильтр такта разглашения и write-side `visibility` **уже были live**
> (BOB-066.2.6). Весь код латентен, пока гость реально не в чате (owner всегда TRUSTED).

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
`is_owner`/`is_authorized`, но НЕ меняет решение о доступе. Когда проведён опциональный
`gender_store` (шов `GenderMemory`, BOB-078 A), `resolve` сперва вкладывает текст хода в
само-презентацию отправителя (`observe_gender`) и читает обратно накопленный `Gender`
(`load_gender`) — так Боб обращается в верном грамматическом роде (UNKNOWN → нейтрально,
никогда не по имени); без шва или без keyable `sender_id` — UNKNOWN, ход байт-идентичен.
`perceive_kind(event)` — лёгкий брат `resolve` для холистического stream-read (BOB-078 B):
та же authz-классификация до `InterlocutorKind`, но БЕЗ накопления рода (само-презентация уже
свёрнута на основном handle-пути — повторное наблюдение здесь двоило бы счёт).

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
legacy single-row `relationship` owner-blob). BOB-078 A добавил per-person грамматический
род: `observe_gender(sender_id, text)` вкладывает само-презентацию хода через чистый
`GenderRead` и UPSERT'ит ТОЛЬКО колонку `gender` (четыре оси отношения нетронуты —
несформированное отношение сохраняет нейтральные дефолты), `load_gender(sender_id)` читает
накопленный lean и резолвит его в `Gender` (NULL / неизвестный отправитель → UNKNOWN). `SqliteSulkStore` — одна строка на
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
- **Такт разглашения — ортогонален гейту, owner байт-в-байт (INV-7, BOB-066.2.6).**
  `may_surface`/`filter_surfaceable` фильтруют ИНИЦИАТИВНОЕ всплытие памяти (не запросы —
  их держит `PrivilegeGate`); для TRUSTED (owner/known peer) — no-op, recall байт-в-байт,
  гостю удерживается только `owner_private` на ОБОИХ recall-путях (FTS5 + векторный KNN,
  оба несут `visibility`). Write-side `visibility_for_scope` fail-safe: неопределённый
  scope → `owner_private` (INV-8, сомнение удерживает); `NULL` = public держит BOB-051
  память нетронутой. `tactful_withhold_directive` — только ГОЛОС отказа гейта, не подмена
  гейта.
- **Кредит доверия — только seed на первом контакте (BOB-066.2.6).** `endorsed_seed`
  warm-start'ит ТОЛЬКО новичка (`rel is None`); сформированная связь неизменна. Seed
  скромный и растворяется обычным дрейфом-к-нейтральному, если поведение не подтвердит —
  head-start, не постоянный грант. `detected_endorsement`/`owner_endorsed_sender`
  консервативны (нужно поручительство И имя отправителя, иначе `False`).
- **Род — только по само-идентификации, накопление ≥2, никогда по имени (BOB-078 A).**
  `detect_self_gender` читает FEM/MASC лишь из само-презентации 1-го лица (родовой глагол о
  себе / «я сам»/«я сама»); имя и глагол 3-го лица — не сигнал. `GenderRead.resolve` коммитит
  род только когда `|lean|` перешагнул порог в ДВА шага, поэтому один сигнал не переворачивает
  род — нужно ≥2 согласных наблюдения; противоречия гасятся, слабая история остаётся UNKNOWN.
  UNKNOWN → нейтрально (Боб не навязывает рода). Род per-person (колонка `gender`), не трогает
  четыре оси отношения; без проведённого шва каждый отправитель читается UNKNOWN.
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
- Домен: `interlocutor.classify` (+ `Interlocutor.gender`),
  `gender.detect_self_gender`/`GenderRead.observe`/`resolve` (+ `Gender`),
  `first_impression.impression_note_for`,
  `relationship.apply_interaction`/`endorsed_seed`, `sulk.observe_relationship`/`recover`,
  `disclosure.may_surface`/`visibility_for_scope`/`filter_surfaceable`
  (+ `VISIBILITY_PUBLIC`/`VISIBILITY_OWNER_PRIVATE`),
  `endorsement.detected_endorsement`/`owner_endorsed_sender`.
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
  `test_gender.py` (BOB-078 A: `detect_self_gender` — 1-е лицо vs 3-е лицо vs имя,
  `GenderRead` — накопление ≥2 сигналов до коммита, противоречия гасятся, порог),
  `test_voice.py` (родовая клауза `who_is_writing_directive`: FEM/MASC/UNKNOWN);
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
  `test_relationship_store.py` (в т.ч. `load_gender`/`observe_gender` — накопление,
  изоляция от четырёх осей, legacy-NULL → UNKNOWN),
  `test_sulk_store.py`, `test_person_sulk_store.py`
  (per-person UPSERT + owner-backfill идемпотентность/не-воскрешение),
  `test_permission_request_store.py`; `tests/infrastructure/llm/test_privilege_judge.py`.
- Per-person обида (BOB-066.2.5): `tests/application/usecases/test_sulk_sources.py`
  (SulkTracker per-sender, изоляция per-(persona,sender), GroupSilentAnnouncer);
  BDD-сценарии `tests/acceptance/features/person_sulk.feature` +
  `tests/acceptance/steps/test_person_sulk.py` (адресный холод, бытовой мат ≠ hostile,
  гарантированный выход временем).
- Такт разглашения и кредит доверия (BOB-066.2.6): чистые ядра —
  `tests/domain/personality/test_disclosure.py` (`may_surface`/`filter_surfaceable`/
  `visibility_for_scope`: TRUSTED/GUEST × public/private/`NULL`/unknown, регистр, scope,
  порядок), `test_endorsement.py` (поручительство + сужение по имени),
  `test_relationship.py` (`endorsed_seed`: seed на первом контакте, no-op на
  сформированной связи), `test_voice.py` (`tactful_withhold_directive`); врезка recall —
  `tests/application/usecases/test_handle_message.py` +
  `tests/application/usecases/test_turn_visibility.py`; BDD —
  `tests/acceptance/features/disclosure_tact.feature` +
  `tests/acceptance/steps/test_disclosure_tact.py` (7 сценариев).
- Layer-guard модуля: `tests/social/test_layering.py`.
