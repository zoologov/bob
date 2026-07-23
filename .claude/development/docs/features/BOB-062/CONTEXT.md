<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-062 — «Domain-first реорганизация + доки» (эпик)

> **Status:** Approved
> **Created:** 2026-07-02
> **PRD/RFC:** оба Approved (`./PRD.md`, `./RFC.md`)

---

## Суть

Фаза 3. Физический переезд кода в domain-first (screaming architecture) + наполнение доков + растворение
монстров (handle_message #9, app.py #10), внутри рельс Фазы 2 (граф + AaC-правила + аннотации). Весь
эпик **behavior-preserving** — рантайм Боба не меняется. Исполнение — **8 срезов, PR за PR**, main
всегда зелёный; owner утверждает старт каждого среза.

## Ключевые решения (из RFC)

- **Переезд атомарно по срезу:** `git mv` + переписать импорты перемещённых файлов и их импортёров в
  одном PR. Тесты — страховка. Шимы только: ports-шим Ф2 (до #18) + разрез цикла personality↔conversation.
- **Структура модуля + энфорс слоёв:** `src/bob/<module>/` = `ports.py` + доменная логика + `usecases/`
  + `adapters/`; слой = файловый тег `# beadloom:layer=<L>`. Энфорс двумя семействами `forbid_import`
  (направление слоёв + границы модулей: к чужому модулю — только через `ports`). Валидируется на срезе .1.
- **handle_message (#9):** ~50 seam-ов конструктора = коллабораторы; извлекаются method-object'ом в срез
  .6 (personality+conversation); `handle()` финализируется тонким оркестратором в .7.
- **app.py→runtime (#10):** в срез .7; чек-лист хрупкостей (`_REPO_ROOT`, boot-order, shared-instance,
  feature-flag) — обязателен.
- **Доки** пишутся В срезе (после переезда файлов модуля), не заранее. `architecture.md` ужимается и
  каркас закрывается (флип no-monster→error, удаление ports-шима #18) в срезе .8.

## Структура модуля (эталон, валидируется на .1 coding)

```
src/bob/<module>/
  ports.py            # layer=domain — контракты (из domain/ports/<module>.py)
  <entities/logic>.py # layer=domain — доменная логика
  usecases/           # layer=application — оркестрация модуля
  adapters/           # layer=infrastructure — реализации портов
```
Лёгкие подкаталоги `usecases/`/`adapters/` — там где ≥3 файлов слоя; иначе плоско + теги (рек. RFC).

## Инварианты (🔴 чек-лист КАЖДОГО среза — адреса в RFC §«Чек-лист инвариантов»)

verify-once-per-turn (turn-local note, НЕ атрибут) · анти-повтор-регенерация (1 доп. генерация) ·
essential-vs-decorative (`_safe_addon`→""/GUPPI-нотис) · per-turn announcer (live-only) · floor-advance
(после reply, RAW addressivity) · shared-instance (notable_reaction/diagram_sink — один инстанс) ·
boot-order + feature-flag off→None→inert · sulk-once/anti-Exodus. Плюс `_REPO_ROOT` при переносе app.py.

## Стандарты кода (CLAUDE.md §0.1)

Python 3.12+ asyncio · DDD/Clean Architecture · TDD (pytest, покрытие нового кода ≥80%) · ruff +
`mypy --strict` (без `Any`/`# type: ignore` без причины) · без print/breakpoint/bare-except/import-*.
Коммиты `[BOB-062.N] <type>: <desc>`. Доки — на русском.

## DoD среза (каждый .1–.8)

- Файлы модуля переехали в `src/bob/<module>/`; импорты переписаны; узел графа перецелен + аннотации.
- SPEC/DOC модуля наполнены (не скелет).
- `pytest` (поведение идентично) · `ruff` · `mypy --strict` · `beadloom ci` — зелёные.
- Чек-лист инвариантов пройден; поведение Боба не изменилось (рестарт `./bob` при мерже — по желанию owner).
- Один PR на срез; main зелёный.

## DoD эпика

Дерево `src/bob/` — domain-first; правило слоёв в `error`; монстры растворены (нет узлов > порога);
`architecture.md` — навигационный обзор; per-module SPEC/DOC наполнены; ports-шим удалён (#18);
BOB-Issues #1–6, #9–18 закрыты.

## Ссылки

Карта «файл→модуль» + декомпозиция handle_message (методы→коллабораторы) + hotspots app.py + инварианты
(адреса) — разведка сессии (в RFC). Целевая структура — [[bob-audit-hygiene-epic]]. BOB-Issues.md #1–18.
