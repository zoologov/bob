<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-065 — «Фундамент: split ports + граф + AaC»

> **Status:** Approved
> **Created:** 2026-07-02
> **PRD/RFC:** оба Approved (`./PRD.md`, `./RFC.md`)

---

## Суть

Фаза 2 аудита. Ставим архитектурный каркас до физического переезда кода (Фаза 3):
разбить God-`ports.py`, детализировать граф beadloom, наполнить правила Architecture-as-Code.
Всё — **поведение-сохраняюще**; рантайм Боба не меняется.

## Ключевые решения (из RFC)

- **`domain/ports.py` → пакет `domain/ports/`.** `__init__.py` реэкспортирует все 51 символа
  (`__all__` неизменен) → ~140 импортёров не трогаем. Определения — по подмодулям
  (kernel/capabilities/memory/personality/conversation/social/proactivity/coding).
- **Kernel** временно в `domain/ports/kernel.py` (инфра-нейтрален, легально в domain);
  в Фазе 3 → `runtime/`.
- **Граф** = слои (domain/application/infrastructure + runtime=app.py, теги слоёв) + подмодульные
  узлы на **реальных текущих путях**. Файлы мапятся по `source`-префиксу — 186 файлов вручную
  не аннотируем; точечно переопределяем.
- **AaC-правила** — реальные примитивы движка: `layers` (runtime→infra→application→domain),
  `forbid_import` ×3 (сканирует реальные импорты), `forbid_cycles`, `deny`, `module_coverage`,
  `check`. **Severity-ratchet:** чистое — `error` сразу; `no-monster-modules` — `warn` (→ `error`
  в Фазе 3 после декомпозиции).
- **Граница с Фазой 3:** узлы-слои и правила структурно-инвариантны и переживут реорг; подмодульные
  узлы позже перецеливаются на domain-first пути; шим удаляется в #18.

## Инварианты (не сломать)

- 🔴 `__all__` пакета `ports/` = точное объединение прежних 51 символа (тест-импорт всех + mypy).
- 🔴 Новые `error`-правила должны быть зелёными на текущем коде; ложные срабатывания — триаж
  (чинить или понижать до `warn` с TODO), НЕ замазывать.
- Поведение рантайма неизменно (Часть A — чистый move; B/C — только метаданные/конфиг).
- `beadloom reindex` после любого изменения графа/аннотаций.
- Общие рефактор-инварианты проекта (verify-once-per-turn BOB-057, анти-повтор, floor-advance,
  feature-flag off→None→inert и т.д.) — здесь не задеваются (код не двигаем), но регресс-тесты их
  стерегут.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio. DDD + Clean Architecture (`domain ← application ← infrastructure`).
- **TDD**: тест до/вместе с кодом. `pytest` + pytest-cov, покрытие ≥ 80% для нового кода.
- `ruff check` + `ruff format`; `mypy --strict` (без `Any`/`# type: ignore` без причины).
- Без `print`/`breakpoint`; без bare `except`; без `import *`; без mutable-default-аргументов.
- Коммиты: `[BOB-065] <type>: <desc>` (feat/fix/refactor/docs/test/chore).

## DoD (Definition of Done) фичи

- `domain/ports/` пакет; `from bob.domain.ports import <любой из 51>` работает; mypy зелёный.
- Граф детализирован (слои + подмодули); `beadloom reindex` чистый; `docs generate` эмитит скелеты.
- `.beadloom/_graph/rules.yml` наполнен; `beadloom lint --strict` зелёный (error-правила проходят,
  известные `warn` задокументированы).
- `pytest`, `ruff`, `mypy --strict`, `beadloom sync-check` — зелёные.
- BOB-Issues #7 закрыт; #8 введён; #1/#2 отмечены частично выполненными (граф-каркас).

## Ссылки

- Разведка `ports.py`: 51 символ, корзины, blast radius (~140 файлов) — в истории сессии.
- Разведка rule-движка beadloom: 9 типов правил, `depends_on` из реальных импортов, эталон
  `/Users/v.zoologov/beadloom/.beadloom/_graph/rules.yml`.
- BOB-Issues.md #7/#8 (+ #1/#2). Эталон графа: `beadloom/.beadloom/_graph/services.yml`.
