<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# usecases — оркестрация домена GUPPI

Use-case'ы приложения: оркестрация доменной логики поверх портов. Узел `usecases`
(`part_of` слоя `bob-application`, source `src/bob/application/usecases/`) держит
**кросс-доменные** ходы, которые не принадлежат ни одному вертикальному модулю —
они сшивают несколько bounded-context'ов через инъецированные порты-протоколы.
Модуль-специфичные use-case'ы (personality/conversation/memory/…) живут в
`<module>/usecases/`, а не здесь.

## Спецификация

### Модули

- **handle_message.py** — `HandleMessage`, тонкий оркестратор полного хода
  сообщение → ответ → персист → запоминание (GUPPI act-loop): `handle(event, scope=None)`
  проводит фазы perceive → who → gate → compose+guard → post-effects, делегируя ~14
  когезивным коллабораторам-швам. Здесь же объявлены нужные ему порты-протоколы
  (`ReplyGateway`, `EpisodeWriter`/`EpisodeReader`, `InterlocutorResolver`,
  `FirstImpressionReader`, `RelationshipReader`, `SulkReader`, `CurrentFascinationReader`,
  `SelfImprovementReader`, `OwnerActivityRecorder`, `BargeCeiling`, `ReplyDelay` …) и
  in-memory-держатели `PersonalityState` / `EngagementState`.
- **heartbeat.py** — тики автономной внутренней жизни Боба между сообщениями:
  `InnerMonologueTick` (приватная мысль на Tier 0 → её сентимент кормит mood),
  `MoodDriftTick` (тянет mood к покойной базовой линии), `ReflectTick` (периодическая
  Tier-0-рефлексия: логируется эпизодом, затем применяется к душе), плюс узкие швы
  `ReflectionContext`, `Reappraiser`, `FascinationEvolver`, `PhantomEvolver`,
  `MemoryConsolidator`, `FactDeduper`, `SulkRecoverer`, `PatternDetectorStep`,
  `RuleAnnouncerStep`, `TasteProfileWriter`.
- **essential_runner.py** — `EssentialRunner`, ретрай существенного LLM-шага
  (суждение/генерация) с ограниченным backoff, затем честный GUPPI-outage-нотис
  вместо деградированного полу-ответа (`run` / `notify_outage` / `handle_failure`,
  «полный Боб или честный GUPPI-нотис», BOB-049 .3); шов `OutageNotifier`.
- **precompose_gate.py** — `PreComposeGate`, cross-domain гейты перед обычной
  компоновкой, что могут ЗАБРАТЬ ход: `maybe_route_coding` (NL-coding-intent для owner
  через шов `NaturalCodingRouter`, BOB-041) и `maybe_permission` (privilege-flow через
  `PermissionFlowLike`, BOB-052). 🔴 Резилентность приёма (BOB-078 D): `maybe_route_coding`
  дёргает роутер на КАЖДОМ сообщении (`session_store.active()` и подобное), поэтому любую
  ошибку роутера он глотает, логирует и трактует как «не coding» (`False`) — одна битая
  coding-сессия не роняет intake-воркер, ход продолжается обычным chat-путём.
- **privileged_fulfiller.py** — `PrivilegedRequestFulfiller`, исполнение ОДНОГО
  одобренного запроса с привилегией через tool-loop или обычный роутер (`fulfil`, BOB-052 .3).
- **perceive_reaction.py** — `PerceiveReaction`, Боб чувствует реакцию на одно из своих
  сообщений — декоративно, ограниченно, per-person (`perceive`, BOB-050); швы
  `BobMessageLookup`, `ReactionMemoryWriter`, `ReactorResolver`.
- **catch_up.py** — `CatchUp`, один re-entry-проход по backlog'у away-периода под
  бюджетом (флаг по умолчанию OFF, BOB-066 Срез 3.2); `CatchUpOutcome`, `to_backlog_message`.
- **room_mood_modulator.py** — `RoomMoodModulator`, настроение комнаты красит голос и
  аппетит Боба: `tone_line` + `engagement_shift` (BOB-066 Срез W.2).
- **disclosure_guard.py** — `DisclosureGuard`, тёплый ГОЛОС отказа гостю в owner_data
  (`withhold_directive`, BOB-066 Срез W.4).
- **disclosure_consent_gate.py** — owner-consent гейт (BOB-082): судит консервативным Tier-0,
  разрешил ли owner В ЭТОТ ход раскрыть приватное в группе (`owner_consented`); только owner+
  группа, неуверенность→нет. За флагом `coder.dev_dm`; best-effort (ошибка → нет согласия).
- **endorsement_seeder.py** — `EndorsementSeeder`, тёплый старт гостю, за которого
  поручился owner (`seed`, BOB-066 Срез W.4).
- **reply_rhythm.py** — `reply_delay_inputs`, чистая карта из спроса-на-ответ и интереса
  в ручки задержки ответа.

## Инварианты

- Use-case'ы зависят от домена **только** через порты-протоколы; инфраструктуру не
  импортируют (граница проверяется `tests/application/test_layering.py`).
- `EssentialRunner` ретраит ЛЮБОЙ сбой существенного шага, затем честный нотис — никогда
  не отдаёт деградированный полу-ответ.
- `HandleMessage.handle` — тонкий оркестратор: логика живёт в коллабораторах, не в нём;
  под intake-развязкой (BOB-066) `TurnScope.rng` прокидывается во все seeded-draw хода.
- `PreComposeGate.maybe_route_coding` не пробрасывает ошибку роутера: одна битая coding-сессия
  не крашит приём — сбой глотается, ход идёт chat-путём (резилентность, BOB-078 D).

## API

Модуль `src/bob/application/usecases/`:
- `HandleMessage.handle(event, scope=None)` — провести один полный ход Telegram.
- `EssentialRunner.run(...)` / `.notify_outage(...)` / `.handle_failure(...)` — ретрай + честный нотис.
- `PreComposeGate.maybe_route_coding(...)` / `.maybe_permission(...)` — cross-domain гейты перед compose.
- `PrivilegedRequestFulfiller.fulfil(...)` — исполнить одобренный привилегированный запрос.
- `PerceiveReaction.perceive(...)` — почувствовать реакцию на сообщение Боба.
- `ReflectTick.run(...)` / `InnerMonologueTick.run(...)` / `MoodDriftTick.run(...)` — heartbeat-тики.
- `CatchUp.plan(...)` — один re-entry-проход по backlog'у.
- `RoomMoodModulator.tone_line(...)` / `.engagement_shift(...)` — модуляция от настроения комнаты.

## Тестирование

Тесты: `tests/application/usecases/test_handle_message.py`, `test_heartbeat.py`,
`test_perceive_reaction.py`, `test_permission_flow.py`, `test_privileged_fulfiller.py`,
`test_catch_up.py`, `test_room_mood_modulator.py`, `test_disclosure_guard.py`,
`test_endorsement_seeder.py`, `test_reply_rhythm.py`.

<!-- beadloom:track=src/bob/application/usecases/handle_message.py -->
<!-- beadloom:track=src/bob/application/usecases/heartbeat.py -->
<!-- beadloom:track=src/bob/application/usecases/essential_runner.py -->
<!-- beadloom:track=src/bob/application/usecases/precompose_gate.py -->
<!-- beadloom:track=src/bob/application/usecases/privileged_fulfiller.py -->
<!-- beadloom:track=src/bob/application/usecases/perceive_reaction.py -->
<!-- beadloom:track=src/bob/application/usecases/catch_up.py -->
<!-- beadloom:track=src/bob/application/usecases/room_mood_modulator.py -->
<!-- beadloom:track=src/bob/application/usecases/disclosure_guard.py -->
<!-- beadloom:track=src/bob/application/usecases/disclosure_consent_gate.py -->
<!-- beadloom:track=src/bob/application/usecases/endorsement_seeder.py -->
<!-- beadloom:track=src/bob/application/usecases/reply_rhythm.py -->
