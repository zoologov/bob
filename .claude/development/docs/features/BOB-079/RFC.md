> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-079

# RFC — Автобиографическая память: запись и присвоение своих действий

## Резюме решения

Ввести новый класс эпизода — **самодействие Боба от первого лица** (`event_type="self_action"`) — и
писать его в двух WRITE-дырах, где сегодня действия Боба теряются: **coding-сессии** и **tool-loop**.
Ядро — чистая доменная функция, превращающая структурированную запись действия в русскую формулировку
от первого лица + теги + флаг аномалии. Recall уже гибридный (FTS+вектор) — эпизоды нужно только
**создать** и сделать **surfaceable** (не отбрасывать, как рефлексии). Лёгкая voice-директива страхует
присвоение (первое лицо, честное признание сбоя, без конфабуляции). Всё за флагом
`memory.autobiography` (по образцу `presence.stream_read`: default OFF в коде → ON в running-config
после ревью → живой смоук).

## Корневой дефект (из разведки)

- `memory/entities.py:54` — `event_type: str` (голая строка, не enum). Значения (`reflection`,
  `message`, `reaction_received`, `digest`, `proactive`) разбросаны литералами. **Ни одного значения
  для собственного действия Боба.**
- `capabilities/usecases/tool_loop.py:143-169` — `_run_tool` вызывает инструмент (`dispatch` @156),
  ловит успех/ошибку — но **не имеет инъекции памяти**. Действие «Боб вызвал инструмент X» нигде не
  оседает.
- `coding/usecases/coding_assistant.py` — переходы `start`/`stop`/`_execute_and_open_pr`/`_fail` пишут
  только мутабельную строку `coding_session`; **memory-репозиторий не инъектирован**. «Боб начал/
  бросил/провалил сессию» и **runaway-флуд** (кап нарратива `_narrate_run` @400-426) не оседают как
  автобиография.

Итог: автобиография Боба = слова (`message`) + чувства (`reflection`), но не поступки.

## Доменная модель (новое, чистое ядро)

**`memory/self_action.py`** (layer=domain, I/O-free — **mutation-ядро**):

```python
class SelfActionKind(StrEnum):          # прецедент: coding/state.py CodingSessionState
    CODING_STARTED = "coding_started"
    CODING_FINISHED = "coding_finished" # PR открыт
    CODING_ABORTED = "coding_aborted"   # owner-kill / cancel
    CODING_FAILED = "coding_failed"
    CODING_RUNAWAY = "coding_runaway"    # сорвался: кап нарратива сработал
    TOOL_USE = "tool_use"                # коалесцированный итог tool-loop за ход
    TOOL_FAILURE = "tool_failure"        # инструмент упал

@dataclass(frozen=True)
class SelfAction:
    kind: SelfActionKind
    target: str | None = None            # задача/файлы/инструменты — коротко
    detail: str | None = None            # причина сбоя и т.п.

@dataclass(frozen=True)
class RenderedSelfAction:
    content: str          # ОТ ПЕРВОГО ЛИЦА, по-русски
    tags: tuple[str, ...]
    is_anomaly: bool

def describe_self_action(a: SelfAction) -> RenderedSelfAction: ...
```

`describe_self_action` — детерминированный рендер от первого лица. Примеры:
- `CODING_RUNAWAY` → «я залип на задаче «X» — флудил правками, пришлось себя осадить» (`is_anomaly=True`,
  теги `self`, `coding`, `anomaly`).
- `CODING_STARTED` → «я взялся за «X» в кодере».
- `CODING_FINISHED` → «я доделал «X», открыл PR».
- `TOOL_USE` → «я воспользовался инструментами: read_code, list_dir» (коалесцированно, 1 на ход).
- `TOOL_FAILURE` → «я попробовал X — не вышло (<detail>)» (`is_anomaly=True`).

**Инвариант ядра:** формулировка всегда от первого лица («я …»); аномалии помечаются (для будущего
«вспомни свои косяки» и для честного признания). Чистая, без БД/времени — TDD + mutation ≥85%.

## Порт и запись (edge)

**`memory/ports.py`** — узкий порт (не тащим весь `MemoryRepo` в кодер/tool-loop):

```python
class SelfActionRecorder(Protocol):
    async def record(self, action: SelfAction, *, sender_id: int | None,
                     visibility: str | None) -> None: ...
```

**`memory/adapters/self_action_recorder.py`** — тонкий адаптер: `describe_self_action(action)` →
`EpisodicEvent(event_type="self_action", content=rendered.content, tags=rendered.tags, sender_id=...,
visibility=..., mood_snapshot=None)` → `repo.save_episode_entity(event)` (типизированная дверь
`sqlite_memory_repo.py:292-305`). Флаг `is_anomaly` кодируется тегом `anomaly` (retrievable), отдельная
колонка не нужна — `event_type` уже голая строка, миграции нет.

Прецедент формы — `perceive_reaction.py:196-220` (первое лицо, теги, sender_id, save_episode).

## WRITE-точки

### 1. Coding-сессии (главный таргет S1) — `wiring/coding.py:111-142` + `coding_assistant.py`
Инъектировать `SelfActionRecorder` в `CodingAssistant` (сейчас конструктор без памяти). Писать на
переходах:
- `start` (@225) → `CODING_STARTED(target=task)`
- `stop` (@298, owner-kill) → `CODING_ABORTED`
- `_execute_and_open_pr` успех (@367 PR_OPEN) → `CODING_FINISHED(target=task)`
- `_fail`/`FAILED` (@446/@358) → `CODING_FAILED(target=task, detail=reason)`
- **runaway-аномалия:** в `_narrate_run` (@400-426), когда сработал кап `_MAX_NARRATION` (BOB-076) →
  `CODING_RUNAWAY(target=task)`. Это и есть автобиографический след флуда, привязанный к реальному
  сигналу в коде.

Запись best-effort: обёрнута в try/except → провал записи автобиографии НЕ роняет coding-путь и приём
(урок Part D [[bob-078-dialogue-quality]]).

### 2. Tool-loop (S2/S3) — `handle_message.py:1231-1240` `_make_tool_loop`
Инъектировать recorder (в скоупе `HandleMessage.self` → `memory_repo`). В `ToolLoop.run` (@113-141)
**коалесцировать** имена успешно вызванных инструментов за ход → одна запись `TOOL_USE` в конце хода
(НЕ по вызову — избегаем повторения flood-риска BOB-076). Упавший инструмент (@159-161) → `TOOL_FAILURE`.
Тривиальные ходы без инструментов ничего не пишут. Один эпизод на ход — объёмно безопасно.

## READ-точки (recall + framing)

- **Surfaceability:** `self_action` — это делимая автобиография, НЕ приватная рефлексия. Убедиться, что
  `recalled_excluding_reflections` (handle_message.py вокруг :2063) и `filter_surfaceable` **не
  отбрасывают** `self_action` (visibility ставим по контексту owner-действия). Recall гибридный
  (`HybridMemoryRecall`, composition.py:375) — лексический+векторный арм уже поймают «инцидент с
  кодером» → эпизод «я залип… флудил правками». **Ключ: эпизод должен существовать и проходить фильтр;**
  сам recall уже работает.
- **Framing (лёгкая страховка присвоения):** контент уже пред-сформулирован от первого лица (как
  `perceive_reaction`), поэтому тяжёлой правки voice не нужно. Добавить в `personality/voice.py` мелкую
  директиву (рядом с `recalled_impression_directive:361-367`): когда среди recalled есть self_action —
  «это ТВОИ прошлые поступки; говори о них от первого лица, честно признай промах, не приписывай
  внешним силам; НЕ выдумывай действий, которых нет в памяти» (INV-1/2/3). Сигнал «в recalled есть
  self_action» прокинуть из `reply_context.py:95-97` (там сейчас `event_type/category` отбрасывается —
  начать его учитывать для этой директивы). INV-4 обеспечен самим `event_type` + «я»-формой.

## Флаг

`memory.autobiography` (bool). OFF → recorder — no-op (ноль записей, поведение как сейчас). ON →
запись включена. Default OFF в коде; в running-config включаем после ревью (образец
`presence.stream_read` [[bob-072-stream-read]]). Consumer’ы получают recorder всегда; no-op решает флаг
(чисто, без ветвлений по коду).

## Границы / не-цели (как в PRD)

git/беады-инструмент (2б), метакогниция эмоций, authz, **ретро-реконструкция прошлых действий из
git/`coding_session`** — вне scope. ⇒ S1 в живом смоуке проверяется на **свежем** самодействии
(маленькая coding-сессия start→stop или форс-аномалия), затем «помнишь?» — присвоение. Честно: фича
даёт способность копить автобиографию с момента поставки, а не воскрешает прошлый инцидент.

## Риски и меры

- **Автобиографический флуд** (повтор BOB-076) → коалесценция tool-use в 1 эпизод/ход + coding пишет
  только на переходах; всё за флагом; кап уже есть в нарративе.
- **Конфабуляция** (INV-3) → присвоение гейтится реальным recalled-эпизодом + voice-запрет выдумывать.
- **Recall не поднял эпизод** → эпизоды короткие, богатые ключевыми словами («кодер», «правки»,
  «сорвался»); гибридный recall (вектор) добирает семантику; surfaceable-фильтр не режет.
- **Запись роняет путь** → best-effort try/except на всех write-точках (урок Part D).
- **Приватность** → visibility наследуется от контекста действия; self_action не утекает шире, чем
  обычная память; `filter_surfaceable` по trust сохраняется.

## Тест-стратегия

- **Unit/TDD:** `describe_self_action` — все `SelfActionKind`, первое лицо, флаг аномалии, теги
  (**mutation ≥85%**, чистое ядро). Recorder-адаптер: строит верный `EpisodicEvent`; no-op при флаге OFF.
- **Coding:** запись на каждом переходе + runaway-аномалия при капе; best-effort не роняет сессию.
- **Tool-loop:** коалесценция в 1 эпизод/ход; failure→аномалия; ход без инструментов → 0 записей.
- **Surfaceability:** self_action проходит `filter_surfaceable`/не режется как рефлексия.
- **BDD `.feature`** (поведение через границу, `tests/acceptance/`): S1 присвоение сбоя, S2 припоминание
  действия, S4 без конфабуляции (нет эпизода → «не припоминаю»), — через fake gateway/recorder.
- **Живой смоук:** свежая мини coding-сессия/аномалия → «помнишь?» → присвоение от первого лица.
