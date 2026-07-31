> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-079

# CONTEXT — BOB-079 Автобиографическая память

## Суть

Первый срез стоячего эпика self-model. Боб пишет свои значимые действия (coding-сессии + tool-loop) как
эпизоды `self_action` от первого лица; recall их поднимает; Боб присваивает и признаёт (в т.ч. сбой).
Всё за флагом `memory.autobiography`.

## Ключевые решения (из RFC)

- **Новый event_type `self_action`** — голая строка, миграции нет (`event_type: str`).
- **Чистое ядро** `memory/self_action.py`: `SelfActionKind(StrEnum)` + `SelfAction`/`RenderedSelfAction`
  + `describe_self_action` (первое лицо, флаг аномалии, теги) — mutation ≥85%.
- **Узкий порт** `SelfActionRecorder` (не тащим весь `MemoryRepo`); тонкий адаптер → `save_episode_entity`.
- **WRITE:** coding-lifecycle (start/stop/finish/fail + runaway при капе нарратива) — инъекция recorder
  в `CodingAssistant` через `wiring/coding.py`; tool-loop — коалесцированный `TOOL_USE` (1/ход) +
  `TOOL_FAILURE`, инъекция через `_make_tool_loop`.
- **READ:** `self_action` surfaceable (не режется как рефлексия); лёгкая voice-директива присвоения
  (первое лицо, честность, без конфабуляции).
- **Best-effort** запись (try/except) — не роняет coding/приём (урок Part D BOB-078).
- **Флаг** default OFF в коде → ON в running-config после ревью.

## Инварианты (из PRD)

- INV-1 первое лицо · INV-2 присвоение · INV-3 без конфабуляции · INV-4 разделение акторства.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio. **DDD + Clean Architecture** (domain I/O-free; порты; адаптеры на краю).
- TDD (test-first) · BDD `.feature` для поведения (`tests/acceptance/`) · mutation ≥85% на чистом ядре.
- ruff (lint+format) · mypy --strict (без `Any`/`# type: ignore` без причины).
- Никаких `print`/`breakpoint`; bare `except` — только с типом (кроме осознанного best-effort с логом);
  без мутабельных дефолтов.
- Beadloom: `reindex`/`sync-check`/`lint --strict` перед коммитом; пути через `beadloom ctx`, не хардкод.

## Границы

git-инструмент (2б), метакогниция эмоций, authz, ретро-реконструкция — вне scope. S1 в живом смоуке — на
свежем самодействии.

## Связи

[[bob-consciousness-markers-lens]] (эпик) · [[bob-076-coder-runaway]] (инцидент) ·
[[bob-078-dialogue-quality]] (урок Part D best-effort) · [[bob-072-stream-read]] (образец флага).
