<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-066 — «Человеческое групповое присутствие»

> **Status:** Approved
> **Created:** 2026-07-29
> **Type:** epic
> **PRD/RFC/CONTEXT:** Approved / Approved / Approved

---

## Структура

Родитель — эпик-беад (тип `epic`, для `bd swarm`): **`bob-066` — Человеческое групповое
присутствие**. Под ним **10 срезов** (каждый = один PR = один shippable слой) в 3 фазах. Каждый срез
имеет полный набор роль-беадов (dev → test → review → tech-writer; для срезов с новым модулем/
границами добавляется dev-беад «AaC-правила»). Беады создаются в трекере **после** утверждения
PLAN.

**Волны координатора внутри среза:** `dev-impl` → [`dev-rules` — только где новый модуль/границы] →
`test` (инварианты) → `review` → `tech-writer` (Gate). Между срезами — PR + мерж owner.

**🔴 Состав test-волны КАЖДОГО среза (пирамида качества, CONTEXT):** (a) **TDD-unit** на чистые ядра;
(b) **mutation-gate** (`mutmut`, score ≥85%) на затронутый domain-модуль — только для срезов,
трогающих доменную логику; (c) **BDD `.feature`** acceptance-сценарии из соответствующих PRD-сценариев
+ покрытие инвариантов INV-1…9 через fake-gateway.

---

## Срез 0 — Инструментарий качества (фундамент перед Фазой 1)

- **dev:** добавить dev-зависимости `pytest-bdd` + `mutmut` (pyproject); scaffold
  `tests/acceptance/{features,steps}/` + общий fake-gateway conftest для acceptance; `mutmut`-конфиг
  (target = domain-пакеты, exclude adapters/LLM/async); первый `.feature` (напр. INV-1 фокусная
  гарантия) + первый mutation-прогон на существующем чистом ядре как эталон порога; решение по CI
  (mutation — НЕ в pre-commit; отдельный шаг/manual per-срез).
- **test:** BDD-harness работает (feature→steps→fake-gateway зелёный); mutmut запускается на
  domain-таргете; порог задокументирован.
- **review · tech-writer** (зафиксировать метод BDD+mutation в dev-доках).
- **Зависимости:** нет (первый). **Новый модуль:** нет (test-инфраструктура + pyproject).

## Фаза 1 — Примитивы присутствия (P0-фундамент, без intake-переделки)

Быстрый видимый скачок мультипати-корректности. Два независимых среза (могут идти параллельно, но
для одного мерж-слота — последовательно).

### Срез 1.1 — Reply-to на выходе
- **dev:** `reply_to_message_id` (additive) в `gateway.reply` + `BotLike.send_rich_message`/
  `send_message` (aiogram `ReplyParameters`) + `ReplyGateway` Protocol; per-turn VO `OutgoingTarget`
  в `handle()`; начальная детерминированная политика (`reply_to = event.message_id if
  others_present and not focal_1to1`).
- **test:** цитата на конкретное сообщение при 3+; `None` = топик-отправка не сломана; 1:1 не
  цитирует каждое.
- **review · tech-writer.**
- **Зависимости:** нет. **Новый модуль:** нет (правки infra+application).

### Срез 1.2 — Floor-по-говорящему
- **dev:** `ConversationFloor.participants: tuple[int,…]=()` (additive, legacy-дефолт); `advance_floor`/
  `resolve_addressivity` перестают игнорить `sender_id` (убрать `del sender_id`); проброс в
  `FloorManager.resolve_effective/advance_after_turn`; `floor_participant`/`floor_holder` в
  `AddressivityPerceiver.signals`; сериализация `participants` в store + guarded-миграция колонки.
- **test:** безметочное от участника нити = продолжение; от постороннего = не поднимать; legacy-
  режим (пустой набор) = текущее поведение; миграция/backfill.
- **review · tech-writer.**
- **Зависимости:** нет. **Новый модуль:** нет (правки conversation domain+adapter).

---

## Фаза 2 — Рефлексивное ядро + ритм (P0-живость, сердце эпика)

### Срез 2.1 — Intake-развязка + сериализация + TurnScope
- **dev:** `application/runtime/intake/` (`ChatInbox` буфер+debounce, `ChatDispatcher` per-chat
  воркеры, `TurnScope` rng-изоляция); смена подписчика шины в composition-root (`HandleMessage.handle`
  → `ChatDispatcher.submit`); `handle(event, scope)` + `self._rng`→`scope.rng`. 🔴 фокусные не ждут
  debounce.
- **dev-rules:** граф-узел для intake-пакета (application/runtime — координация; аннотации).
- **test:** 🔴 гонки — 2 сообщения чата НИКОГДА не в `handle` одновременно; rng воспроизводим;
  turn-local не течёт между сообщениями батча; поллинг мгновенный (не блокируется генерацией).
- **review · tech-writer.**
- **Зависимости:** нет (но фундамент для 2.3/2.4/3.1/3.2). **Новый пакет:** intake (application).

### Срез 2.2 — Рефлексивный read-the-room + split + INV-1 + web-лаз
- **dev:** 5 компонентов (`conversation/room_reading.py`, `room_reading_wire.py`,
  `usecases/read_the_room.py`, `adapters/room_reader.py`, `room_verdict.py`); фокус/периферия split
  в `TurnGate.gate`; `TaskType.ROOM_READ` (Tier-1); `wants_web` → `VerifyStep.note(forced=True)`.
- **dev-rules:** правила границ для новых conversation-файлов (тот же модуль — узел есть; проверить
  layer-аннотации domain/app/infra).
- **test:** 🔴 **INV-1 матрица** {mention, reply-to-Bob, «Боб,»} × {пустой floor, шквал ambient,
  обида, ceiling исчерпан, батч, судья=ignore, судья упал} → везде ответ ИЛИ GUPPI-нотис;
  `decide_from_reading` детерминизм; wants_web форсит verify; parse-fail пробрасывается.
- **review · tech-writer.**
- **Зависимости:** 1.2 (floor-хинты в контекст), 1.1 (addressee → reply-to), 2.1 (воркер/scope).

### Срез 2.3 — Ритм-слой `presence/` + доля эфира
- **dev:** новый bounded-context `presence/` (`outgoing_activity`, `share_of_voice`,
  `natural_delay`, `ports.py`, `adapters/OutgoingActivityStore`); `DelayedTurn` координатор
  (application); ceiling на ambient-бардж (фокус минует); target ≈ `1/(distinct_senders+1)`;
  проактив-тик домножается на share-of-voice per-chat.
- **dev-rules:** 🔴 `python scripts/gen_boundary_rules.py` (новый модуль `presence` → узел
  `module-vertical` + explicit-path границы); `# beadloom:feature=presence`+`layer=`.
- **test:** доля эфира тормозит ambient при превышении, фокус НЕ тормозится; естественная задержка
  (пол vs реальная генерация); срочность↓пол; проактив тормозит после свежей реплики.
- **review · tech-writer.**
- **Зависимости:** 2.1 (воркер). **Новый модуль:** `presence/`.

### Срез 2.4 — RoomMood-в-тоне + салиенс/бюджет действий
- **dev:** `personality/room_tone.py` (`room_tone_directive` + `room_engagement_bias`,
  переиспользует disposition-контагион); прокидка `room_valence`/`room_polarization` из `RoomReading`
  примитивами через application; салиенс + бюджет действий top-k в воркере (несколько входящих →
  один ответ адресно + лайки); `ReactionBudget` (`presence/reaction_budget.py`, отбор одной на серию).
- **test:** тяжёлая/поляризованная комната давит игривость; личный mood не затронут; несколько
  входящих → один ответ; лайк-бюджет (не каждое).
- **review · tech-writer.**
- **Зависимости:** 2.2 (RoomReading), 2.3 (presence/reaction budget).

### Срез 2.5 — Per-person обида/охлаждение
- **dev:** таблица `person_sulk` (schema.sql) + `PersonSulkStore` (social/ports) +
  `SqlitePersonSulkStore` + guarded-миграция + backfill owner; `SulkTracker.observe(sender_id,…)`/
  `current_for`/`active_targets`; снять owner-гейт в `social_context.observe_sulk`; адресный
  `sulk_directive` (только текущий собеседник); scope-aware announcer (GUPPI в DM, тихо в группе).
- **test:** обида к одному не гасит тон к другому; порог+sustain+time-decay per-person; casual мат
  не триггерит; игнор не кормит; анонс тихий в группе; миграция/backfill.
- **review · tech-writer.**
- **Зависимости:** нет нового (social/personality) — но после 2.4 (room-mood как «общий фон» vs
  адресный sulk). Может частично параллелиться.

### Срез 2.6 — Такт разглашения + кредит доверия
- **dev:** `visibility` в `episodic_log`+`semantic_memory` (guarded ALTER) + запись по scope в
  `save_episode`/`_extract_facts`; `may_surface(visibility, trust)` (social/domain) + фильтр в
  recall-pipeline `handle_message`; `tactful_withhold_directive` (voice) на owner_data-запрос;
  `social/endorsement.py` + `relationship.endorsed_seed` + перехват первого контакта представленного
  гостя.
- **test:** owner_private не всплывает гостю инициативно; public всем (BOB-051 цел); тактичный отказ
  вместо сухого; endorsement → тёплый старт; консервативный дефолт visibility.
- **review · tech-writer.**
- **Зависимости:** нет нового (social/memory/personality). Может параллелиться с 2.5.

---

## Фаза 3 — Догоняющий над backlog (устойчивость)

### Срез 3.1 — Staleness/merge-gate
- **dev:** `presence/staleness.py` (`StalenessGate.reassess → SEND/REWRITE/DROP_TO_LIKE/MERGE`) +
  порт judge; врезка перед `gateway.reply` (перечитать `inbox.peek_since`); слияние нового
  обращения с готовящимся.
- **test:** релевантный → send; устаревший → drop→like; уточнение → merge/rewrite; прямой вопрос
  поверх → слить.
- **review · tech-writer.**
- **Зависимости:** 2.1 (буфер peek), 2.3 (presence).

### Срез 3.2 — Backlog catch-up + бэкпрешер
- **dev:** `presence/catchup.py` (`BacklogScorer`: адресованность>свежесть>salience) +
  `application/usecases/catch_up.py` (рефлексивный проход над окном + бюджет top-k + absence-hint
  тон) + tick в wiring (re-entry); бэкпрешер с приоритетом (🔴 фокусное не теряется, схлопывается
  только периферия).
- **test:** один проход над окном (не N ответов); прямое обращение в backlog не теряется; старое-
  невадресованное дропается; re-entry тон по absence-бакету; бэкпрешер приоритет.
- **review · tech-writer.**
- **Зависимости:** 2.1 (буфер), 2.2 (рефлексивный проход), 3.1 (staleness как рубеж).

---

## Граф зависимостей срезов

```
Срез 0 (harness) ──> всё остальное
Фаза 1:  1.1 ─┐         1.2 ─┐
              │              │
Фаза 2:  2.1 ─┼──> 2.2 <─────┘        2.5 ─┐  (social/personality,
              │      │                 2.6 ─┤   могут параллелиться,
              └──> 2.3 ──> 2.4 <───────────┘   после сердца)
Фаза 3:              2.1,3.1 ──> 3.2
                     2.3 ──> 3.1
```

**Критический путь:** 0 → 1.2 → 2.1 → 2.2 → 2.4 → 3.2 (harness → сердце живости → догоняющий).

## Финал эпика (снятие блокера)

Все срезы в main · инвариант-тесты (INV-1…9) зелёные · анти-скриптованность-harness · регресс-1:1 ·
**живой прогон в реальной группе (owner + Боб)** → owner подтверждает «Боб живой». Тогда owner
добавляет команду.

## Что НЕ создаём как беады (вне скоупа — RFC)

durable inbox/at-least-once · реальный thread_id/кластеризация · дизамбигуация имени · «упомянут в
3-м лице» · приват/DM тред · BobNet loop-breaker/replica-kind/authenticity (будущий эпик).
