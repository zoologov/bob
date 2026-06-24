<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-025 — «Адресность по непрерывности диалога (conversational floor)»

> **Status:** Draft
> **Created:** 2026-06-24

---

## Обзор

Над поштучным детектором адресности (BOB-023) появляется **трекер «разговорной реплики»
(conversational floor)** — кто сейчас адресат живого обмена в треде. Чистый домен
`conversation_floor.py` хранит, «у микрофона» ли Боб, и **поднимает** безметочную `AMBIENT`-реплику
до `DIRECTED_TO_BOB`, пока floor = БОБ (непрерывность), от **любого** участника. Состояние floor
персистится на тред; обновляется при прямом обращении, при ответе Боба и при явном повороте к
другому человеку; затухает по тайм-ауту/уходу разговора. Цель BOB-023 сохранена: безметочное →
к Бобу ТОЛЬКО когда он держит реплику. Фундамент BobNet turn-taking; маркер theory-of-mind.

## Технический контекст

### Ограничения
- Python 3.12+, DDD/Clean: трекер floor — **чистый домен** (без I/O, детерминированно по
  инъектированному `now`; без рандома); персист за портом; композиция в `app.py`; инъекция
  Clock/портов. **TDD на фейках через `.venv/bin/pytest`** (uv run висит), `mypy --strict`,
  `ruff`, cov >=80%.
- Не ломать: BOB-023 (классификатор/политика/SILENT), BOB-019 (Interlocutor/owner/гость),
  BOB-014 .2a (аппетит), BOB-018 (REACT_ONLY), реактив/проактив/память/тиринг/authz. Гость-инвариант
  по правам не трогаем.

### Затрагиваемые области
`domain/personality/conversation_floor.py` (new), `domain/ports.py` (+`ConversationFloorStore`),
`infrastructure/persistence/` (+Sqlite-стор), `application/usecases/handle_message.py` (резолв
эффективной адресности + обновление floor после ответа), `app.py`, `config`.

---

## Предлагаемое решение

### (1) Трекер floor — чистый домен (`conversation_floor.py`)
- **`FloorHolder`** (Enum): `BOB`, `OTHER`, `IDLE`.
- **`ConversationFloor`** (`frozen, slots`): `holder: FloorHolder`, `holder_id: int | None`
  (id человека при `OTHER`), `since: datetime` (когда держателя в последний раз подтвердили),
  `idle_streak: int` (сколько подряд безметочных реплик прошло БЕЗ участия Боба — для распада).
- **Чистый `advance_floor(floor, *, addressivity, sender_id, bob_replied, now, config) ->
  ConversationFloor`** — переход по одному ходу:
  - `addressivity == DIRECTED_TO_BOB` → `holder=BOB`, `since=now`, `idle_streak=0`.
  - `addressivity == DIRECTED_TO_OTHER` → `holder=OTHER`, `holder_id=<адресат>`, `since=now` (Боб
    отступает).
  - `addressivity == AMBIENT`:
    - если floor уже БОБ и не истёк → остаётся БОБ, `since=now`, но `idle_streak += 1`, **если в
      этот ход Боб НЕ ответил** (он перестаёт «держать», если молчит на серию реплик); при
      `idle_streak >= config.reset_after_silent` → распад в `IDLE`.
    - иначе → без изменений (или `IDLE` по тайм-ауту).
  - **`bob_replied=True`** (Боб ответил этим ходом) → `holder=BOB`, `since=now`, `idle_streak=0`
    (ответ Боба «приклеивает» реплику к нему — US-1/US-2).
  - **Тайм-аут:** если `now - floor.since > config.timeout` → перед применением floor считается
    `IDLE` (распад по молчанию).
- **Чистый `resolve_addressivity(per_message, floor, *, now, config) -> Addressivity`** — поднимает
  непрерывность: если `per_message == AMBIENT` И floor=БОБ И не истёк → **`DIRECTED_TO_BOB`**;
  иначе возвращает `per_message` как есть. Прямое обращение и явный поворот к другому проходят без
  изменений.

### (2) Персист floor (порт + Sqlite)
- **`ConversationFloorStore(Protocol)`** (`domain/ports.py`): `load(chat_id, thread_id) ->
  ConversationFloor`, `save(chat_id, thread_id, floor)`. Ключ — тред (топик Боба). Sqlite-impl по
  паттерну существующих сторов (таблица `conversation_floor`).

### (3) Интеграция в `handle_message` (поверх BOB-023)
Поток хода: perceive(BOB-019) → **per-message** `classify_addressivity` (BOB-023) → **load floor**
→ `resolve_addressivity` (непрерывность) → политика `decide_response` на ЭФФЕКТИВНОЙ адресности →
{SILENT | REACT | ENGAGE} → (если ENGAGE и Боб ответил) → `advance_floor(bob_replied=True)` →
`save`. Для не-ответных ходов floor тоже обновляется (`advance_floor` с фактическим исходом, чтобы
`idle_streak`/распад считались). `bob_user_id`/`others_present` — как в BOB-023.

### (4) Конфиг `addressivity.floor.*`
- `enabled` (true), `timeout_seconds` (**300** ≈ 5 мин), `reset_after_silent` (**2** — распад после
  2 безметочных реплик подряд, на которые Боб промолчал). Дефолты — утверждённые owner'ом.

### Композиция / границы
Гость-инвариант BOB-019 по правам не трогаем (гость по-прежнему restricted: без памяти/инструментов/
owner-данных) — floor меняет лишь распознавание адресности, не права. Прямое обращение всегда к
Бобу (BOB-023). SILENT-исход сохраняется для чужого диалога.

## Guardrails (под тестами)
- **US-1/US-2 (непрерывность):** после прямого обращения/ответа Боба безметочные реплики **любого**
  участника → `DIRECTED_TO_BOB`, пока floor держится (≤ timeout, без распада).
- **US-3 (поворот к другому):** `DIRECTED_TO_OTHER` (reply/имя-обращение к человеку) → floor=OTHER,
  Боб отступает (как BOB-023).
- **US-4 (распад):** floor → IDLE по тайм-ауту (≥300с) ИЛИ после `reset_after_silent` безметочных
  реплик, на которые Боб промолчал → возврат к осторожной ambient-логике (не встревает в чужое).
- **US-5 (прямое — всегда):** mention/reply-на-Боба/«Боб,…» → `DIRECTED_TO_BOB` и (пере)берёт floor.
- Не-перехват: пока floor НЕ у Боба, безметочное остаётся `AMBIENT` (BOB-023 не встревает).
- Трекер чист/детерминирован по `now`; гость-инвариант цел.

## Рассмотренные альтернативы
- **LLM-классификатор адресата на каждый ход** — отвергнуто: цена/недетерминизм; берём floor-эвристику
  поверх сигналов BOB-023 (порт абстрактен — усилить позже).
- **Деривация floor из недавней истории каждый ход (без персиста)** — отвергнуто: хрупко и дороже;
  явное персист-состояние на тред проще и детерминированнее.
- **Floor привязать к говорящему (owner-only непрерывность)** — отвергнуто owner'ом: непрерывность —
  про адресата (Боба), а не про того, кто произнёс (US-2: Норман продолжает разговор с Бобом).

## Риски
| Риск | Вер. | Влияние | Митигация |
|---|---|---|---|
| Боб «залипает» и встревает, когда разговор ушёл к двум другим | Med | Med | Распад: тайм-аут 300с + `reset_after_silent`=2 (молчание Боба снимает floor) |
| Боб теряет нить слишком быстро (распад агрессивен) | Low | Med | Ответ Боба рефрешит `since`; тайм-аут 5 мин; тесты US-1/US-2 |
| Гонки/устаревший floor на тред | Low | Low | Персист на тред + атомарный save; `now` инъектируется |
| Конфликт с SILENT/others_present BOB-023 | Med | Med | resolve работает ДО политики; прямое всегда к Бобу; тесты на композицию |

## Открытые вопросы
| # | Вопрос | Предложение |
|---|--------|-------------|
| Q1 | Что считать «явным поворотом к другому» | reply на не-Боба ИЛИ имя-обращение к участнику (DIRECTED_TO_OTHER из BOB-023) |
| Q2 | Рефреш `since` на каждой ambient-реплике или только на ответе Боба | На обеих (реплика в нить + ответ Боба держат floor), распад — по молчанию Боба/тайм-ауту |
| Q3 | Гранулярность ключа floor | (chat_id, thread_id) = топик Боба; на будущее — расширяемо |
