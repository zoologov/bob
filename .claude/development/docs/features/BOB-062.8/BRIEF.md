<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.8 — «Закрытие каркаса: kernel + ports-шим + доки» (Фаза 3, срез 8/8 — ФИНАЛ)

> **Status:** Approved
> **Created:** 2026-07-28
> **Type:** feature · ФИНАЛЬНЫЙ срез эпика BOB-062 · BOB-Issues #18, #8-флип, #4, #5, #3, #1/#2-финиш
> **Родитель:** `bob-8r4.8` · Все предыдущие срезы (.1–.7b) в main

---

## Проблема

domain-first реорг завершена (7 срезов). Осталось закрыть каркас: удалить транзитный ports-шим (#18),
дать правилам «зубы» (флип no-monster→error #8), доусилить генератор (хардинг), ужать монолит
`architecture.md` (#4), добавить getting-started (#5), доген доки (#3). После — **эпик BOB-062 закрыт**.

## 🔴 Ключевое решение (kernel home — утв. owner)

При удалении ports-шима 7 kernel-контрактов (`Clock`/`EventBus`/`EventHandler`/`DomainEvent`/`LLMProvider`/
`LLMMessage`/`JsonValue`) нуждаются в доме. 🔴 **НЕ runtime** (сломает `no-runtime-root` — capabilities/
social.ports импортят kernel). **Решение: `src/bob/kernel/`** — классический DDD **shared kernel** (инфра-
нейтральные кросс-модульные контракты; каждый модуль может импортить, inward-safe, циклов нет). И
**удалить вырожденную `src/bob/domain/`** целиком (после реорга там только шим+kernel) — символичное
завершение: исчезает последняя layer-first папка. `kernel.py` docstring про «→ runtime» — стейл, поправить.

## Беады .8 (под `bob-8r4.8`)

- **`.1` dev (#18 + kernel):** создать `src/bob/kernel/ports.py` (перенести 7 kernel-контрактов из
  `domain/ports/kernel.py`, тег layer-domain/shared); перецелить 3 прямых импортёра kernel + 109 файлов
  `from bob.domain.ports import X` на канон (44 non-kernel → `<module>.ports`; 7 kernel → `bob.kernel.ports`);
  удалить шим `domain/ports/__init__.py` + `tests/domain/test_ports_reexport.py`; удалить пустую `src/bob/
  domain/`. Граф-узел kernel + аннотации. pytest/ruff/mypy(ПОЛНЫЙ)/reindex --full зелёные.
- **`.2` dev (правила-зубы + хардинг):** флип `no-monster-modules` warn→error (безопасно, 0 warnings);
  🔴 `scripts/gen_boundary_rules.py` — char-class `[!au]*`/`[!u]*` → explicit-path (покрыть root-файлы
  addressivity/absence/urge, которые сейчас пропускаются); опц. app→adapters warn-правило; kernel-узел в
  генератор (модули→kernel легально; kernel↛модули). regen + `--check`. `reindex --full && lint --strict`
  EXIT 0.
- **`.3` test:** полный pytest + `from bob.domain.ports` НЕ находится (grep) + kernel импорты работают +
  🔴 `reindex --full && lint --strict` EXIT 0 (no-monster error не падает) + mypy ПОЛНЫЙ + пробы
  (модуль→kernel ок; root-файл→adapters горит после хардинга). beadloom ci.
- **`.4` review:** ports-шим удалён чисто (домен/domain/ исчез), kernel в shared-месте (не runtime,
  циклов нет), no-monster флип обоснован, хардинг закрыл char-class дыру; поведение неизменно.
- **`.5` tech-writer:** 🔴 ужать `architecture.md` 4318→nav-shell (#4: таблица доменов + Mermaid + ссылки
  на 11 per-module SPEC; вырезать ~25 дублей H2; reindex + re-mark 203 bob-пары + docs audit); getting-
  started.md (#5, из README+arch); опц. guides/; `docs generate` скелеты для 8 недокум. узлов (#3);
  закрыть BOB-Issues #18/#8/#4/#5/#3/#1/#2 + мастер #30 + пометить эпик BOB-062 Done. Gate (full-reindex).

## Критерии приёмки (закрытие эпика)

- `src/bob/domain/` удалён; kernel в `src/bob/kernel/`; ports-шим удалён; 109 импортёров на канон; нет
  `from bob.domain.ports`. no-monster-modules = error (проходит). Генератор char-class дыра закрыта.
- `architecture.md` — навигационный обзор; getting-started есть; doc-coverage вырос.
- `pytest` зелёный · mypy ПОЛНЫЙ 0 · `reindex --full && lint --strict` EXIT 0 · `beadloom ci` 0.
- BOB-Issues #1–6, #9–18, #30 закрыты; **эпик BOB-062 → Done**. Open → минимум (остаются #25 gateway,
  #26–28 clean-code, #31/#32 групповая нагрузка — вне domain-first эпика).

## Связи

Финал эпика BOB-062 (срез 8/8). После — эпик закрыт; остаётся отдельный бэклог (#25-28 clean-code,
#31/#32 групповая нагрузка). 🔴 УРОК: `reindex --full` в DoD (не инкрем — #142) + mypy ПОЛНЫЙ (src+tests).
