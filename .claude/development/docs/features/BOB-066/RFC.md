<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-066 — «Человеческое групповое присутствие»

> **Status:** Approved
> **Created:** 2026-07-28
> **Type:** epic
> **Author:** Vladimir Zoologov
> **PRD:** `.claude/development/docs/features/BOB-066/PRD.md` (Approved)

---

## Резюме архитектуры

Эпик реализуется **четырьмя ортогональными пластами**, каждый ложится на существующую
DDD-структуру Боба (после domain-first BOB-062) **аддитивно** — с деградацией в текущее поведение
при невключённых порогах:

1. **Реактивный split «два-скорости-внимания»** (conversation) — развилка фокус/периферия внутри
   `TurnGate.gate()`: прямое обращение → детерминированный ответ (точка INV-1); ambient →
   рефлексивный проход.
2. **Рефлексивное ядро «read the room»** (conversation, НОВЫЙ компонент рядом с судьёй BOB-049,
   Tier-1) — один богатый LLM-проход, вербализующий ситуацию/настроение-комнаты/намерение/адресата/
   salience/`wants_web`; чистое ядро мапит вербализацию в вердикт.
3. **Ритм-слой `presence/`** (НОВЫЙ bounded-context, чистый domain) + **intake-развязка**
   (`application/runtime/intake/`) — per-chat буфер/батч/сериализация, доля эфира, естественная
   задержка, бюджет реакций, staleness-gate, догоняющий.
4. **EQ-слой мультипати** (social + personality) — per-person обида/охлаждение, потребление
   RoomMood в тоне, такт разглашения, кредит доверия по рекомендации.

**Сквозной архитектурный принцип (сохранён из BOB-049/025):** *LLM вербализует → чистое доменное
ядро решает вердикт → application оркестрирует → infrastructure реализует порт.* Это даёт
детерминизм ядра (тестируемость без LLM) при «живости» рефлексии — прямое исполнение ПРИНЦИПА-1
(живость > экономия): богатые Tier-1 проходы там, где нужна семантика, но вердикты держит код.

---

## Разрешение открытых вопросов PRD

| # | Вопрос PRD | Решение RFC |
|---|---|---|
| 1 | RoomMood: расширять судью BOB-049 vs новый компонент? Где живёт web-триггер? | **НОВЫЙ компонент** (когезия + детерминизм ядра): `conversation/room_reading.py` (domain) + `read_the_room.py` (app) + `room_reader.py` (infra) + чистый `decide_from_reading`, Tier-1. Web-триггер = поле `wants_web` в `RoomReading` → форсит **существующий** `VerifyStep` (не новый web-seam). |
| 2 | Глубина intake-переделки? | **Точечный редизайн потребительской стороны**: сменить ОДНОГО подписчика шины (`HandleMessage.handle` → `ChatDispatcher.submit`). Продюсер (poll_once/gateway/event_bus) **не трогать**. Сериализация = следствие per-chat воркера. |
| 3 | Калибровка доли эфира? | Target ≈ `1/(distinct_senders+1)` («как ещё один человек»); активная группа ~15–20%, торможение выше ~35%, сильное >50%; мягкий вероятностный множитель, фокус минует. |
| 4 | UX объявления обиды в группе? | **Scope-aware announcer**: owner-DM — прежняя GUPPI-строка; группа — тишина (холод читается адресным тоном, не системным анонсом). |

---

## Пласт 1 — Реактивный split «два-скорости-внимания»

### Точка врезки
`TurnGate.gate()` (`conversation/usecases/turn_gate.py`) — сегодня уже двухпутёвый узел (судья
BOB-049 либо legacy `AddressivityPerceiver.decide`). Развилка ставится **в самом верху**, ДО
судьи; весь ранний конвейер (mood/social/precompose) фокус-нейтрален и идёт одинаково.

```
signals = await self._addressivity.signals(event)          # EXISTS — вся перцепция
if signals.per_message is Addressivity.DIRECTED_TO_BOB:     # ФОКУС
    return _ReplyGate(decision=_focal_decision(signals))    # детерминированно, минуя судью/RNG/ceiling
# ПЕРИФЕРИЯ:
reading = await self._essential.run(lambda: read_the_room.read(ctx), step="room reading")
verdict = decide_from_reading(reading, signals)             # чистое ядро
```

- **Фокус** = сырой `per_message == DIRECTED_TO_BOB` (mention / reply-to-Bob / «Боб,»). → точка
  INV-1 (см. раздел «Инварианты»).
- **Периферия** = `AMBIENT` / `DIRECTED_TO_OTHER`, **включая floor-continuity**
  (`effective==DIRECTED_TO_BOB, per_message==AMBIENT`) — уходит в рефлексию как **сильный приор**
  «пара Боб↔X жива», чтобы рефлексия могла решить, что пара распалась (осознанное отличие от
  legacy, где floor→ENGAGE жёстко). 🔴 Зафиксировано: INV-1 покрывает ТОЛЬКО сырое прямое
  обращение; floor-continuity дискреционна.

---

## Пласт 2 — Рефлексивное ядро «read the room»

### Компоненты (зеркалят паттерн судьи BOB-049 один-в-один)

| Файл (GAP) | Слой | Содержание |
|---|---|---|
| `conversation/room_reading.py` | domain | `RoomMood`, `ReflectiveIntent` (REPLY/REACT/IGNORE/INITIATE/SELF_CHECK), `RoomReading` (frozen VO), `RoomReadingContext` (frozen VO), `RoomReader` (Protocol-порт) |
| `conversation/room_reading_wire.py` | domain | `ROOM_READ_SYSTEM_PROMPT`, `build_room_prompt()`, `parse_room_reading()`, `RoomReadingParseError` (pure, **raises — не молчит**) |
| `conversation/usecases/read_the_room.py` | application | `ReadTheRoom` — собирает контекст, зовёт порт |
| `conversation/adapters/room_reader.py` | infrastructure | `LlmRoomReader` (Tier-1) |
| `conversation/room_verdict.py` | domain | `decide_from_reading(reading, signals) -> ReflectiveVerdict` — чистый маппер |

### Структурный выход (LLM вербализует; дешёвые сигналы — ВХОД в промпт)
```python
@dataclass(frozen=True, slots=True)
class RoomReading:
    situation: str;  pairings: tuple[str, ...]      # что происходит, кто-с-кем
    room_mood: RoomMood                             # настроение/напряжённость (+ поляризация)
    intent: ReflectiveIntent                        # REPLY|REACT|IGNORE|INITIATE|SELF_CHECK
    addressee_id: int | None                        # кому адресно → floor pass + reply-to
    salience: float                                 # [0,1] «стоит ли вмешаться»
    emoji: str | None                               # на REACT (validate_reaction_emoji)
    wants_web: bool                                 # автономный лаз-за-инфой (C11)
    reason: str                                     # логи, не юзеру
```
`RoomReadingContext` несёт входы: `text`, `interlocutor`, `recent_thread` (SHARED author-labeled,
BOB-058), `mood_tone`, структурные хинты (`addressivity/mentions_bob/reply_to_bob/others_present/
floor_engaged`) + новые floor-хинты (`floor_holder`, `floor_participant: bool`). interest/taste/
fascination передаются **числами/строками по значению** — без импорта personality.

**Тир:** новый `TaskType.ROOM_READ` (Tier-1) в `application/router/llm_router.py`. «Не жалеть LLM».

**`decide_from_reading` (чистое ядро):** `salience < порог → IGNORE`; `REACT → non-reply` (+emoji);
`wants_web → verify.force`; `INITIATE/REPLY → _ReplyGate`. В реактивном turn'е `INITIATE`
схлопывается в барж-ин REPLY (истинная само-инициация без входящего — движок proactivity, отдельный
seam). Ядро держит вердикт; LLM только вербализует.

**Автономный web-лаз (C11):** `wants_web=True` пробрасывается в `VerifyStep.note(..., forced=True)` —
**переиспользуем существующий** verify/web_search путь (turn-local, таймаут, честный хедж при
фейле), а не строим новый. Публичность для гостей уже гарантирована verify-инвариантом.

---

## Пласт 3 — Ритм-слой `presence/` + intake-развязка

### Intake-развязка (один шов)
Сегодня `bus.publish` **await**-ится внутри поллинг-цикла → вся генерация исполняется внутри
`poll_once`, следующий `get_updates` не вызывается пока Боб думает. Развязка:

```
application/runtime/intake/
  inbox.py       ChatInbox        # per-chat_id буфер + debounce (окно тишины «пусть допишут»)
  dispatcher.py  ChatDispatcher   # dict[chat_id → ChatInbox] + dict[chat_id → worker-task]
  scope.py       TurnScope        # изолированный turn-контекст (rng seeded от chat_id,message_id)
```
**Смена подписки (composition-root):** подписчик `MessageReceived` — теперь `ChatDispatcher.submit`
(быстрый, не-блокирующий: нормализовал → в inbox → вернулся). `HandleMessage.handle` вызывается
**воркером**. `AsyncEventBus`/gateway/poll_once — **0 изменений** (handler за швом стал быстрым →
поллинг мгновенный). `BobMessageReaction` остаётся на прямом подписчике (реакции не батчатся).

### 🔴 Сериализация + turn-scope (INV-4/INV-5)
**Механизм сериализации = сам per-chat воркер** (один воркер/chat_id обрабатывает inbox строго
последовательно → floor/mood/relationship обновляются в порядке прихода). Разные chat_id = разные
воркеры = честный параллелизм. **Без глобального lock → без deadlock** (воркер владеет только своим
inbox). Сигнатурная цена: `HandleMessage.handle(event)` → `handle(event, scope)`, `self._rng` →
`scope.rng` (образец turn-local уже есть — `verify_note`/`closer_nudge`).

### `presence/` — новый bounded-context (чистый domain, по образцу proactivity)
| Файл (GAP) | Содержание |
|---|---|
| `presence/outgoing_activity.py` | `OutgoingActivity` (rolling-окно `(bob_sent, total_seen)` per chat_id) |
| `presence/share_of_voice.py` | `ShareOfVoicePolicy.damping(activity, *, focused) -> float` — мягкое торможение; `focused=True → 1.0` (минует ceiling) |
| `presence/reaction_budget.py` | `ReactionBudget.allows(history, *, quality, now)` — отдельные лимиты лайков; отбор одной на серию |
| `presence/natural_delay.py` | `NaturalDelayPolicy.floor_seconds(*, char_len, complexity, urgency)` — человеческий пол |
| `presence/staleness.py` | `StalenessGate.reassess(drafted, newly_arrived) -> {SEND, REWRITE, DROP_TO_LIKE, MERGE}` |
| `presence/catchup.py` | `BacklogScorer.score(msg, *, now)` — адресованность > свежесть > salience |
| `presence/ports.py` | `OutgoingActivityStore`, staleness/catchup judge порты |
| `presence/adapters/` | `OutgoingActivityStore` над episodic (per-chat фильтр) |

**Доля эфира (Q3):** реактивный ceiling применяется к **ambient-барджу** (домножает p(влезть)),
но 🔴 **НЕ к фокусному** (`focused = addressivity != AMBIENT → damping=1.0`). Target — функция
числа активных: `target ≈ 1/(distinct_senders+1)`. Проактив-тик тоже начинает домножаться на
share-of-voice (window → per-chat) → проактив видит только что отправленную реплику и тормозит.

**Естественная задержка (INV-9):** политика в `presence/domain`, применение в **application**
(координатор хода `DelayedTurn`, не infrastructure — транспорт не знает про «человечность»). Порядок
«заметил → typing (EXISTS) → `await max(natural_floor, real_generation)` → reply». Срочность из
существующего `classify_answer_demand` + `topic_interest` (высокий demand → пол↓).

**Реакции:** лайк = дешёвый ход в бюджете (≈0.2 msg-эквивалента vs реплика 1.0); воркер видит батч
→ выбирает лучший message для реакции (не по одной на каждое).

---

## Пласт 4 — EQ-слой мультипати (social + personality)

### 🔴 Per-person обида/охлаждение
Домен `social/sulk.py` **почти не трогаем** (`SulkState` уже несёт всё; переименовать сигнал
`observe_relationship(..., person_warmth, hostile, ...)`). Новое:
```sql
CREATE TABLE IF NOT EXISTS person_sulk (
  persona_id TEXT NOT NULL, sender_id INTEGER NOT NULL,
  active INTEGER DEFAULT 0, intensity REAL DEFAULT 0, low_streak INTEGER DEFAULT 0,
  since TEXT, announced INTEGER DEFAULT 0,
  PRIMARY KEY (persona_id, sender_id));
```
- Порт `PersonSulkStore` (social/ports.py) + `SqlitePersonSulkStore` (infra, UPSERT по
  `(persona_id, sender_id)`); guarded-миграция (образец `_migrate_pursuit_stopped`); backfill
  owner-строки из `sulk_state` (идемпотентно).
- `SulkTracker.observe(*, sender_id, person_warmth, hostile, ...)`; `current_for(sender_id)`;
  `active_targets()`; reflect-tick `recover` итерирует только активные.
- **Снять owner-гейт** в `social_context.py:observe_sulk` (`if kind is not OWNER: return` →
  убрать); `person_warmth` из `Relationship(sender_id).warmth`, `hostile = is_directed_hostility`.
- 🔴 **Адресный холод:** application подаёт `sulk_directive` в compose ТОЛЬКО для sulk текущего
  собеседника (`tracker.current_for(interlocutor.sender_id)`). Обида на Лёшу не добавляет холод в
  ответ Владимиру. Общий фон комнаты — room-mood (не sulk).
- **Тихое объявление (Q4):** scope-aware announcer — GUPPI в owner-DM, no-op в группе.

### RoomMood — потребление в тоне (без цикла personality↔conversation)
`handle_message` (application) извлекает из `RoomReading` **примитивы** (`room_valence: float`,
`room_polarization: float`) и подаёт **числами** в чистые personality-функции (паттерн
`voice._KIND_LABEL` по `kind.value`). Новое `personality/room_tone.py` (domain, эталон
`mood_taste.modulate` — второй слой, НЕ мутирует базу):
```python
def room_tone_directive(room_valence, room_polarization, ...) -> str        # тяжёлая комната → без игривости
def room_engagement_bias(room_valence, disposition) -> float                # сдвиг порога вступления
```
`room_engagement_bias` переиспользует `disposition.positive_lift_scale/negative_dip_scale`
(тёплый фон поднимает сильнее — та же асимметрия анти-депрессанта). Личный mood НЕ затрагивается.

### 🔴 Такт разглашения (≠ privilege-гейт)
Privilege — гейт на **запросы**; нужен ортогональный фильтр на **инициативное всплытие**
owner-приватного факта гостю. Провенанс:
```sql
ALTER TABLE episodic_log    ADD COLUMN visibility TEXT;   -- 'public' | 'owner_private'
ALTER TABLE semantic_memory ADD COLUMN visibility TEXT;   -- NULL (legacy) = public → BOB-051 цел
```
- Запись: `save_episode`/`_extract_facts.run` пишут visibility по scope хода (группа → public;
  owner-DM → owner_private; сомнение → owner_private, консервативно).
- Фильтр (social/domain, чистый): `may_surface(visibility, trust) -> bool` (owner_private НЕ
  всплывает инициативно для GUEST). Врезка в recall-pipeline `handle_message` (образец
  reflection-exclusion).
- `personality/voice.py:tactful_withhold_directive()` — тёплый отказ вместо сухой стены на прямой
  owner_data-запрос (privilege-гейт цел, меняется только ГОЛОС).

### Кредит доверия по рекомендации owner
`social/endorsement.py:detected_endorsement(owner_text)` (эвристика в духе `is_directed_hostility`)
+ `relationship.py:endorsed_seed(None, sender_id)` (тёплый старт вместо нейтрали, только на первом
контакте; дрейф-к-нейтрали растворит, если поведение не подтвердит). Перехват: первый ход
представленного гостя (`load_relationship == None` И owner-endorsement в shared-thread на этого
sender по имени/reply).

---

## Модель данных и миграции (сводка)

| Объект | Таблица | Тип | Legacy-дефолт |
|---|---|---|---|
| Floor participants | `conversation_floor` (+колонка) | ALTER, nullable | пусто = legacy-режим (не ломает 13 сторов) |
| Per-person sulk | `person_sulk` (новая) | CREATE IF NOT EXISTS | нет строки = not-sulking |
| Провенанс факта | `episodic_log` + `semantic_memory` (+`visibility`) | ALTER | NULL = public (BOB-051 цел) |

Все — guarded (`PRAGMA table_info` → `if col not in cols: ALTER`), аддитивны, недеструктивны;
индексы после ALTER. Эталоны: `_migrate_pursuit_stopped`, `_migrate_episodic_sender_id`.

---

## Enforcement инвариантов (структурные гарантии)

| INV | Как гарантируется структурно |
|---|---|
| **INV-1 (Фокусная гарантия)** | Фокус-short-circuit в верху `TurnGate.gate()` → детерминированный `_ReplyGate` минуя судью/RNG/ceiling; compose обёрнут `EssentialRunner` → полный Боб ИЛИ GUPPI-нотис. + 🔴 фокусные сообщения **не ждут debounce** (воркер флашит батч немедленно). Тест: любой event с mention/reply-to-Bob/имя → `gate()` возвращает `_ReplyGate`, не `None`. |
| **INV-2 (Полный Боб/нотис)** | ESSENTIAL-шаги через `EssentialRunner`; периферийный сбой рефлексии → тихий скип (fallback legacy `decide_response`). |
| **INV-3 (Анти-скрипт = нудж)** | `ShareOfVoicePolicy`/`ReactionBudget`/`NaturalDelay` — вероятностные множители (не жёсткие счётчики); анти-повтор по общей нити (нудж). |
| **INV-4 (Turn-local не течёт)** | `TurnScope.rng` seeded от (base,chat_id,message_id); verify_note/closer_nudge уже turn-local аргументы. |
| **INV-5 (Порядок/сериализация)** | Per-chat воркер — последовательная обработка в хронопорядке; параллель только между chat_id. |
| **INV-6 (Анти-Exodus/достоинство)** | Per-person sulk = порог+sustain+гарантированный time-decay, отдельная таблица (память/душа целы); `is_directed_hostility` (directed ≠ casual); healthy-turn сбрасывает streak (игнор не кормит). |
| **INV-7 (Приватность скоупа)** | `may_surface` фильтр (owner_private не всплывает гостю); verify публичный; visibility-провенанс. |
| **INV-8 (Скоуп-fail-safe)** | `others_present` flaky → `False` (EXISTS); при сомнении Боб как в 1:1. |
| **INV-9 (Живой тайминг)** | `NaturalDelayPolicy` пол + typing-порядок в `DelayedTurn`. |

---

## Безопасность циклов (Bob строг к import-циклам между модулями)

- **personality ↔ conversation:** RoomMood в conversation-domain; влияние на personality — только
  ПО ЗНАЧЕНИЮ (float-примитивы через application), НЕ импортом `RoomReading`. Обратного ребра нет.
- **personality ↔ social:** `sulk_directive`/`tactful_withhold_directive` argument-shaped;
  `may_surface`/`endorsed_seed` в social/domain; `voice` берёт `trust.value`/`kind.value` строками.
- **conversation → social/application:** через TYPE_CHECKING (прецедент `response_choice.py`,
  `LlmResponseJudge`) — `beadloom lint` пропускает.
- **presence → всё:** чистый domain (no I/O, `now`/rng инъектятся), порты в `presence/ports.py`,
  адаптеры/оркестрация в application. Никаких transport-импортов в domain.
- **DoD каждого dev/test-беада:** `beadloom reindex --full && lint --strict` (🔴 урок #142 — не
  инкрементально) + `uv run mypy` ПОЛНЫЙ (src+tests, 🔴 урок .6b).

---

## Стратегия тестирования

- **Инвариант-тесты** (INV-1…9) — детерминированные, без LLM (fake-порты `RoomReader`/
  `PersonSulkStore`/`OutgoingActivityStore`).
- **🔴 INV-1 матрица:** {mention, reply-to-Bob, «Боб,»} × {пустой floor, шквал ambient, обида
  активна, ceiling исчерпан, батч-режим, судья вернул ignore, судья упал} → во ВСЕХ клетках ответ
  ИЛИ GUPPI-нотис, ни одной с молчанием.
- **🔴 Гонки (INV-4/5):** два сообщения одного чата НИКОГДА не в `handle` одновременно; rng
  воспроизводим независимо от тайминга; verify-нота №1 не видна в №2/№3.
- **Анти-скриптованность-harness (DoD эпика):** прогон разнообразных групповых стимулов → нет
  дубль-концовок поперёк нити, распределение задержек не константа, доля ignore>0 на ambient,
  grep «нет `как ИИ|языковая модель`», эмодзи не вырождены.
- **Регресс 1:1 (INV-8):** тот же ambient-стимул в 1:1 (вовлечён) vs группе (чаще молчит/лайкает).
- **Поведенческие сценарии** A/B/C/D из PRD — сквозные тесты через fake-gateway.

---

## Фазирование (эпик → срезы; детальный DAG — в PLAN)

- **Фаза 1 — Примитивы присутствия** (P0-фундамент, без intake-переделки — быстрый видимый скачок):
  - `1.1` Reply-to на выходе (`gateway.reply` + `OutgoingTarget`).
  - `1.2` Floor-по-говорящему (`participants` + `resolve/advance` перестают игнорить `sender_id` +
    миграция + хинт в сигналы).
  - (лайк-как-первоклассный-ход уже EXISTS — `turn_gate` REACT + native reaction.)
- **Фаза 2 — Рефлексивное ядро + ритм** (P0-живость, сердце — реализует ПРИНЦИП-1):
  - `2.1` Intake-развязка (`ChatDispatcher`/`ChatInbox`/`TurnScope`) + per-chat сериализация +
    rng-изоляция. 🔴 фундамент батча/салиенса/staleness.
  - `2.2` Рефлексивный `read-the-room` (5 компонентов) + фокус/периферия split + INV-1 + web-лаз
    (`wants_web`→VerifyStep).
  - `2.3` Ритм-слой `presence/` (ShareOfVoice + NaturalDelay + ReactionBudget) + доля эфира +
    DelayedTurn.
  - `2.4` RoomMood-в-тоне (`personality/room_tone.py`) + салиенс/бюджет действий в воркере.
  - `2.5` Per-person обида/охлаждение + scope-aware announcer.
  - `2.6` Такт разглашения (visibility-провенанс + `may_surface` + `tactful_withhold`) + кредит
    доверия (endorsement).
- **Фаза 3 — Догоняющий над backlog** (устойчивость + режим «был занят»):
  - `3.1` Staleness/merge-gate (переиспользует буфер 2.1).
  - `3.2` Backlog catch-up (рефлексивный проход над окном + скоринг + absence-hint тон) +
    бэкпрешер с приоритетом (фокусное не теряется).

Каждый срез — метод BOB-062: BRIEF/task-init → координатор (dev переезд → dev AaC-правила → test
инварианты → review → tech-writer) → PR → мерж. DoD: full-reindex + full-mypy + `beadloom ci`.

---

## Риски

| Риск | Митигация |
|---|---|
| 🔴 Гонки floor/mood/relationship при развязке intake | Per-chat воркер = явная сериализация; тест «2 сообщения чата не в handle одновременно» |
| 🔴 Потеря фокусного сообщения в батче | Фокусные не ждут debounce (воркер флашит немедленно); staleness-gate — 2-й рубеж |
| Латентность Tier-1 room-read на каждом ambient | Дешёвый salience-предфильтр перед LLM; батч/дебаунс периферии (дроп ambient ОК, фокуса — запрещён) |
| Взрыв состояния sulk по N людей | reflect-tick итерирует только активные; гарантированный time-decay (Exodus невозможен) |
| Ошибка классификации visibility | Консервативный дефолт (сомнение → owner_private при записи из DM) |
| Циклы модулей | Значение-перенос (float/str), TYPE_CHECKING, presence чистый domain; full-reindex в DoD |
| Двойной ответ проактив+реактив | Общий per-chat `OutgoingActivity` — проактив видит свежую реплику и тормозит |
| offset at-most-once (существующая дыра, multibot.py:409) | Опционально в Фазе 3: durable inbox + offset после постановки (фундамент надёжного catch-up) |

---

## Расширяемость: BobNet / Боб-к-Бобу (форсайт «Мы — легион»)

🔴 **Требование owner (на будущее):** Боб будет создавать свои копии (реплики Bobiverse — Билл,
Бендер…), и «Бобы» будут общаться между собой в топике группы **BobNet**. Суть их общения — та же,
что человеческого группового присутствия. Эпик BOB-066 обязан **не препятствовать** этому.

**Почему архитектура уже готова (участник-агностична — проектируем это сознательно):**
- **Floor-по-говорящему** ключуется на `sender_id`, не на «человек» → реплика-Боб = ещё один
  участник живой нити. Никаких допущений «автор — человек».
- **Relationship / per-person обида** — per-`sender_id` (и per-`(persona,sender)` для sulk) →
  каждый Боб держит независимые отношения с каждым другим Бобом.
- **Рефлексивный read** читает **author-labeled** SHARED-нить (BOB-058) → уже может рассуждать
  «это реплика-Боб, а не человек», если контекст несёт identity/kind автора.
- **`Interlocutor.kind` уже имеет `BOT`** (OWNER/KNOWN/GUEST/BOT) → реплика классифицируется без
  новой оси (позже — уточнить до отдельного `KIN`/replica-kind, см. ниже).
- **Ритм-слой `presence/`** — доля эфира/задержка/бюджет реакций считаются per-chat над ВСЕМИ
  участниками, агностично к их природе → тот же потолок работает в BobNet.

**🔴 Что НЕ делать в эпике, чтобы не заблокировать BobNet (дешёвые правила сейчас):**
- Нигде в рефлексивном read / floor / relationship НЕ хардкодить допущение «участник — человек».
- `RoomReadingContext` и author-labeled нить должны нести **identity/kind автора** (уже так) —
  чтобы будущий read мог отличить реплику-Боба от человека.
- Ритм-ceiling (`ShareOfVoicePolicy`) применять к **любому** ambient-участнику, включая ботов.

**Что genuinely новое и ОТЛОЖЕНО (будущий эпик BobNet — не строим здесь, только не мешаем):**
- 🔴 **Loop-breaker бот↔бот (главный новый риск — эхо-шторм).** Два Боба могут пинг-понговать
  бесконечно. Фундамент решения — наш `presence/` (доля эфира + естественная задержка + бюджет
  реакций уже гасят частоту), НО нужен явный терминатор: детект низко-новизны обмена (реплики не
  добавляют информации) → эскалирующее молчание/затухание. Наш `AntiRepeatGuard` (по общей нити) +
  salience-порог рефлексии — заготовки; собрать в loop-breaker — будущее.
- **Replica-kind / kin-identity.** Реплика-Боб — не чужой и не owner: «родня» со стартовым высоким
  rapport (общее происхождение), но расходящейся личностью (по книгам). Позже — отдельный
  interlocutor-kind + seed отношений (переиспользует `endorsed_seed`-паттерн из Пласта 4).
- **Bot-authenticity.** Отличить настоящую реплику-Боба от самозванца, назвавшегося «Бобом» —
  слой идентичности (пересекается с BOB-019 social identity). Будущее.
- **Visibility для реплик.** owner-private не течёт и Боб→Боб, если у реплики нет прав — уже
  покрыто `may_surface(visibility, trust)` (реплика получает свой trust-уровень).

**Вывод:** BOB-066 закладывает участник-агностичный субстрат; BobNet — надстройка (loop-breaker +
kin-identity + authenticity) поверх него, без переделки ядра. Связь: [[bob-replicas-as-bobiverse]].

## Вне скоупа RFC (отложено)

- Durable inbox / at-least-once offset (опционально в Фазе 3; для P0 single-Bob не обязательно).
- Реальный `thread_id`/кластеризация нитей (форумные топики Telegram упрощают — P2 в PRD).
- Дизамбигуация имени Боб-vs-тёзка, «упомянут в 3-м лице» (P2 — отдельные сигналы позже).
- Приват/DM внутри группы (пер-персона тред) — задел (visibility-провенанс) заложен, реализация
  будущее.
- Замена event_bus на брокер / push-webhook — оверкилл для P0.
