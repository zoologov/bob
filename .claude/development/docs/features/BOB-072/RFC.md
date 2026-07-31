> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-31
> **Issue:** BOB-072

# RFC — Holistic stream-read: коалесинг + семантический batch-выбор

## Обзор

Точка врезки — `application/runtime/intake/dispatcher.py` `_handle_batch` (сейчас: скриптованный
`plan_series_actions` top-k + per-message loop, каждое ambient → свой Tier-1 read). Меняем на:
коалесинг вспышки → ОДИН холистический batch-read над ambient-частью пачки → семантическое
per-message решение (reply/react/ignore) → применение с сохранением персиста/floor для ВСЕХ.

Focus (прямое обращение) отделяется РАНО и обрабатывается детерминированно (INV-1), минуя batch-read.

## Компоненты

### 1. Коалесинг (инфра готова — включить + провязать)
- `dialogue.intake_debounce_ms` → задать `> 0` (напр. 500-800мс, конфиг) — окно `ChatInbox.drain_batch`
  (`intake/inbox.py:75`) уже дренирует burst с debounce (`decisions.should_debounce`). Focus минует окно
  (`inbox.py:72-73` — INV-1 моментальность сохранена).
- `_handle_batch` получает settled-пачку `list[MessageReceived]` (уже так) — дальше НЕ loop-per-message.

### 2. Разделение focus / ambient в пачке
- В `_handle_batch`: раздели пачку на **focal** (raw `DIRECTED_TO_BOB`: @/reply-на-Боба/вокатив «Боб»
  — переиспользуй `classify_addressivity`/`_directed_engage`-логику) и **ambient**.
- **Focal** → каждое обрабатывается детерминированно как сейчас (`_handle_one` → `HandleMessage` →
  `TurnGate` focal short-circuit `turn_gate.py:336`). INV-1 без изменений.
- **Ambient** → идёт в новый batch-read (п.3).

### 3. Batch-read контракт (НОВОЕ, рядом с per-message — «компонент рядом»)
- Новый порт `BatchRoomReader.read(batch_ctx) -> BatchRoomReading`:
  - вход: **последовательность ambient-сообщений с атрибуцией** (sender_id/имя/текст/ts) + общий
    recent_thread + room hints (mood/floor/interest per msg);
  - выход: **решение по каждому сообщению** — `reply | react(emoji) | ignore` (0..N reply, 0..M react),
    + reason. Семантику выбора делает LLM.
- Реализация `LlmBatchRoomReader` (`infrastructure/llm` или conversation adapter) через ROOM_READ Tier-1
  с **batch-промптом** (переписать one-message framing `room_reading_wire.py:78` → «вот поток сообщений
  участников, реши по каждому»); `parse_batch_reading` (RAISE на garbage → безопасный all-IGNORE).
- Переиспользуй value-типы `RoomReading`/`ReflectiveIntent`/`RoomMood` (`conversation/room_reading.py`).
- Чистое ядро политики: `decide_batch(readings) -> list[Verdict]` (подъём `decide_from_reading`,
  `room_verdict.py:87`, до пачки; тот же `SALIENCE_THRESHOLD` + intent-маппинг, детерминизм,
  mutation-tested). Семантика — в read; политика — чистая проекция read→verdict.

### 4. Применение с сохранением инвариантов
- Для КАЖДОГО сообщения ambient-пачки (в порядке прибытия): персист incoming (episodic, per-sender) +
  `advance_floor_after_turn` — даже для IGNORE (INV-S2; ровно механизм BOB-071 Seam B: `_advance_silent`/
  `_react_turn` персистят). Reply/react — по решению batch-read.
- Seeded-RNG/turn-local: каждое применение под своим `TurnScope` (детерминизм INV-4); batch-read —
  один вызов, но проекция на N turn-scope сохраняет изоляцию.

### 5. Оставаться в настоящем (queue-level stale) — НОВОЕ
- Перед/во время batch: дроп/слияние **superseded** ambient в буфере (расширить staleness-ядро
  `presence/staleness.py` `decide_staleness` до очереди, либо новый чистый `coalesce_stale(batch)`),
  чтобы Боб не отвечал на реплику, которую поток обогнал. 🔴 Свежий прямой вопрос (focal) НЕ дропается
  (INV-1/INV-S3). MERGE-семантика уже есть в staleness (`staleness.py:124-137`) — переиспользовать дух.

### 6. Rate-cap Tier-1 (НОВОЕ, невидимо)
- `asyncio.Semaphore`/min-interval на Tier-1 пути (`application/router/llm_router.py` или на
  ROOM_READ-вызове) — потолок конкурентных/частоты вызовов Qwen. Не влияет на суждение, страхует от
  429/деградации при пачках разных chat_id. Конфиг (`llm.tier1_max_concurrency`).

## Что переиспользуется / что новое
- **Reuse:** `RoomReading`/verdict value-типы, `decide_from_reading` (→ batch), `ReadTheRoom`,
  `ChatInbox.drain_batch`+debounce, staleness-ядро, `TurnScope`, персист/floor из BOB-071.
- **Новое:** `BatchRoomReader` порт+adapter+batch-prompt/parse, `decide_batch`, focus/ambient split в
  `_handle_batch`, queue-stale-coalesce, Tier-1 rate-cap, включение debounce.
- **Уходит:** `plan_series_actions` скриптованный top-k (`presence/series_salience.py`) — заменён
  семантикой (или сводится к тонкому helper'у для лайк-бюджета, если нужен потолок «не спамить»).

## Риски / решения
- 🔴 **INV-1:** focal отделяется ДО batch-read и остаётся детерминированным (owner утвердил: прямое
  обращение = гарантия). Batch-семантика — только ambient.
- 🔴 **Персист/floor всех N:** обязательно, иначе рвётся тред (BOB-071). Тест-инвариант.
- **Латентность окна:** debounce добавляет ≤окно задержки для ambient — это человечно («дать
  договорить»), focal мгновенен. Порог конфигурируем.
- **Фолбэк:** batch-read падает/garbage → безопасный all-IGNORE + персист (не молчит на focal — тот вне
  batch). За флагом (напр. `presence.stream_read.enabled`), OFF → текущее поведение (обратная совместимость).

## Forward-compat
Batch-контракт участник-агностичен → готов к BobNet/репликам [[bob-replicas-as-bobiverse]]. Углубление
качества read-the-room промпта — поверх этого контракта отдельным заходом.
