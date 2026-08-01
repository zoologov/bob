> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-079

# PLAN — BOB-079 (DAG + seam-точки)

## Seam-точки (авторитетно, из разведки)

- Ядро: **новый** `memory/self_action.py` (domain, pure). Прецедент enum — `coding/state.py:42`.
- Entity/дверь записи: `memory/entities.py:37-63` (`EpisodicEvent`, `event_type: str` @54);
  `memory/adapters/sqlite_memory_repo.py:292-305` (`save_episode_entity`). Порт: `memory/ports.py:34`.
- Прецедент первого лица: `application/usecases/perceive_reaction.py:196-220`.
- Coding WRITE: `coding/usecases/coding_assistant.py` — start@225, stop@298, `_execute_and_open_pr`@337
  (PR_OPEN@367), `_fail`@446/FAILED@358, `_narrate_run`@400-426 (кап `_MAX_NARRATION` → runaway).
  Инъекция: `runtime/wiring/coding.py:111-142` (сейчас без памяти).
- Tool-loop WRITE: `capabilities/usecases/tool_loop.py:113-141` (run) / `_run_tool`@143-169 (dispatch@156,
  error@159-161). Инъекция: `application/usecases/handle_message.py:1231-1240` (`_make_tool_loop`, в
  скоупе `memory_repo`).
- READ surfaceable: `handle_message.py:~2049-2066` (`_recall_surfaceable`, `recalled_excluding_reflections`,
  `filter_surfaceable`). Рендер: `conversation/reply_context.py:95-97` (сейчас теряет `category`).
- Framing: `personality/voice.py:361-367` (`recalled_impression_directive` — образец);
  `personality/usecases/voice_composer.py:276-282/435-437` (сборка директив в system_prompt).
- Флаг: по образцу `presence.stream_read`; читать в composition/wiring, отдавать no-op recorder при OFF.

## Беады

```
BOB-079 [feature] — автобиографическая память: присвоение своих действий
├── .1 [dev] — ЯДРО: memory/self_action.py (SelfActionKind/SelfAction/describe_self_action) +
│              порт SelfActionRecorder + адаптер self_action_recorder (→ save_episode_entity) +
│              флаг memory.autobiography (no-op recorder при OFF). event_type="self_action".
├── .2 [dev] — CODING: инъекция recorder в CodingAssistant (wiring/coding.py) + запись на переходах
│              start/stop/finish/fail + runaway при капе нарратива. best-effort try/except. deps .1
├── .3 [dev] — TOOL-LOOP: инъекция recorder в _make_tool_loop; коалесцированный TOOL_USE (1/ход) +
│              TOOL_FAILURE; ход без инструментов → 0 записей. best-effort. deps .2
├── .4 [dev] — READ: self_action surfaceable (не режется как рефлексия) + voice-директива присвоения
│              (первое лицо/честность/без конфабуляции) + проброс category-сигнала из reply_context. deps .3
├── .5 [test] — unit (ядро: все kind/первое лицо/аномалия/теги; адаптер; no-op OFF; coalesce; failure;
│              surfaceable) + BDD .feature (S1 присвоение сбоя, S2 припоминание, S4 без конфабуляции) +
│              mutation ≥85% на self_action.py. deps .4
├── .6 [review] — INV-1..4; флуд-риск (коалесценция); best-effort не роняет пути; конфабуляция-гард;
│              приватность/surfaceable; DDD-границы (domain I/O-free, узкий порт). deps .5
└── .7 [tech-writer] — docs (memory: self_action автобиография; coding/tool-loop запись; recall/voice
                     присвоение; флаг memory.autobiography). deps .6
```

## Волны / критерии

Dev последовательно (.1→.2→.3→.4 — урок BOB-066, общие касания wiring/voice). Test → review → tw → PR →
self-merge → рестарт → живой прогон.

🔴 **Живой смоук:** свежая мини coding-сессия (start→stop) ИЛИ форс runaway-аномалии → эпизод `self_action`
в `episodic_log` (первое лицо) → «помнишь, что сейчас делал/помнишь инцидент?» → Боб присваивает от
первого лица и признаёт. S4: спросить о действии, которого не было → «не припоминаю за собой» (без выдумки).
Ядро `self_action.py` mutation ≥85%.

## Риски (из RFC)

- Флуд → коалесценция tool-use 1/ход + coding только на переходах + флаг + существующий кап нарратива.
- Конфабуляция → присвоение гейтится реальным recalled-эпизодом + voice-запрет.
- Запись роняет путь → best-effort try/except везде (урок Part D).
- Recall не поднял → короткие ключевые эпизоды + гибридный (векторный) recall + surfaceable-фильтр.
- Приватность → visibility из контекста; filter_surfaceable по trust сохранён.
