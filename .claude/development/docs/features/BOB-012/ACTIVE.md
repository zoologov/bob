<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-012 — Проактив по-русски + сохраняется в память + grounded в реальной памяти

> **Status:** Done
> **Updated:** 2026-06-21
> **Branch:** `features/BOB-012` (коммит `f19a351`)

---

## Текущий фокус

Все три беады волны закрыты. Фича готова к PR.

## Прогресс по беадам

| ID | Роль | Статус | Итог |
|----|------|--------|------|
| BEAD-01 (`bob-wlg.1`) | dev | Готово | Язык персоны (`runtime.language=ru`) во все само-генерации; персист проактива в `episodic_log` (`event_type=proactive`); grounding компоновки через инъецированный `MemoryRecall` + анти-конфабуляция. 729 тестов зелёные, `ruff`/`mypy --strict`/`lint --strict` чисто. |
| BEAD-02 (`bob-wlg.2`) | review | Готово | Read-only ревью пройдено по всем шести измерениям (язык, персист, grounding, дешёвый дефолт, без регрессий, DDD). Валидация перепрогнана чисто. |
| BEAD-03 (`bob-wlg.3`) | tech-writer | Готово | `docs/architecture.md` обновлён под BOB-012; `sync-check` exit 0, `lint --strict` 0 нарушений. |

## Что сделано (dev)

- **Новый модуль** `src/bob/domain/personality/language.py` — `language_directive(language)`
  + `DEFAULT_LANGUAGE="ru"` (чистый домен).
- **Конфигурация** `runtime.language` (по умолчанию `ru`) в `DEFAULT_CONFIG` (`loader.py`).
- **Heartbeat** `InnerMonologueTick` и `ReflectTick` принимают `language` и дописывают
  директиву в промпты.
- **ProactivityEngine** принимает `recall` (`MemoryRecall`), `repo` (`EpisodeWriter`) и
  `language`: директива в гейте + компоновке, recall-then-ground компоновка, персист
  отправленной реплики как эпизод `event_type=proactive` в шаге Persist.
- **Композиция** в `app.py`: язык читается один раз из `runtime.language` и протягивается
  в тики и движок; `recall`/`repo` инъецируются в `_build_proactivity_engine`.

## Что сделано (tech-writer)

`docs/architecture.md` (единственный тронутый документ):
- новый подраздел «Язык персоны (BOB-012)» в «Higher Mind»;
- заметка про директиву языка в тиках монолога/рефлексии («Heartbeat»);
- переписаны шаги 5–7 «От тика к реплике» (директива языка в гейте, grounding +
  анти-конфабуляция в компоновке, персист проактива в `episodic_log`);
- интро `ProactivityEngine` и заметка о композиции в `app.py` (инъекция `recall`/`repo`/`language`);
- секция «Конфигурация» (`runtime.language`);
- секция «Тесты» (новые тест-файлы BOB-012).

## Заметки

- Пре-существующий бэклог staleness по `architecture.md` (52 пары, единый `ref_id: bob`)
  снят через `beadloom sync-update bob --yes` — контент тех областей уже точен, не переписывался.
- `sync-check` exit 0, `beadloom lint --strict` 0 нарушений. Коммит/пуш не делались (по правилам роли).
