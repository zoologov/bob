<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.4 — «Срез capabilities → src/bob/capabilities/ + генератор правил» (Фаза 3, срез 4/8)

> **Status:** Approved
> **Created:** 2026-07-23
> **Type:** feature · срез эпика BOB-062 · BOB-Issues #16 (часть) + #8 (укрепление правил)
> **Родитель:** `bob-8r4.4` · Контекст: эпик `RFC/CONTEXT` + прецеденты .1/.2/.3

---

## Проблема

Способность «инструменты Боба» (шов capability-registry/tool-loop + навыки web_search/read_url/
render_diagram/read_code/inspect_architecture/introspection) размазана: `domain/ports/capabilities` +
`domain/{diagrams,introspection}` + `application/capabilities/**` + `infrastructure/{web,diagrams,
introspection}` + `llm/web_search_qwen`. Собираем в `src/bob/capabilities/`. **Но сначала —
укрепление каркаса правил:** `capabilities` начинается на `c`, как `coding` → текущие char-class
glob-правила (`[adimp]*`) физически не различают их (вердикт review .3). Нужен переход на
explicit-path + генератор.

## Решение — ДВА этапа: (A) каркас правил, (B) переезд

### 🔴 Этап A: генератор правил + explicit-path + дыра internals-no-adapters (ДО capabilities)

Из дизайн-разведки (движок beadloom): `forbid_import` берёт **только одиночный glob** (не список),
brace `{}` не работает, «все кроме X» — лишь через `[!x]` (первый символ → коллизия c/c). Нативного
module-boundary primitive НЕТ (→ BDL-UX #143). Решение:
- **`scripts/gen_boundary_rules.py`** (~50–70 стр): читает `module-vertical` узлы из `services.yml`,
  эмитит per-module `forbid_import` на **explicit paths** в marker-регион `# BEGIN/END generated
  boundary rules`; рукописные rationale-блоки не трогает; режим `--check` (CI-gate, идемпотентность).
- **Конвертировать существующие** char-class правила coding/memory/proactivity → explicit-path
  (семантику НЕ ослаблять — сверка `beadloom lint` findings до/после).
- **Добавить `<M>-internals-no-adapters`** всем модулям (паттерн `src/bob/<M>/[!au]*` → `bob/<M>/
  adapters/*`; закрывает дыру каркаса из test .3; a/u-root-файлы = accepted-gap import-leaves).

### Этап B: переезд capabilities (~27 файлов, крупнейший)

Структура (схема CONTEXT + подпапки под-областей, как `goals/` в proactivity):
```
src/bob/capabilities/
  ports.py            # layer=domain  ← domain/ports/capabilities.py (18 портов)
  __init__.py         # layer=domain
  diagrams/           # layer=domain  ← domain/diagrams/ (mermaid_blocks)
  introspection/      # layer=domain  ← domain/introspection/ (code_history, privacy_guard)
  usecases/           # layer=application ← вся application/capabilities/ (13 файлов:
                      #   registry, tool_loop, progress_announcer, web_search, read_url,
                      #   render_diagram, read_code, inspect_architecture, list_work,
                      #   code_rationale, recall_memory, search_memory)
  adapters/           # layer=infrastructure ← infrastructure/{web,diagrams,introspection}/ +
                      #   llm/web_search_qwen.py  (подпапки web/diagrams/introspection допустимы)
```

**Решения (по разведке):**
- `progress_announcer.py` — целиком в capabilities (announce-политика = ядро шва, ToolLoop зависит).
  `InterimLineGenerator` (Protocol, 10 строк) — пометить кандидатом на извлечение в conversation (.6),
  НЕ разделять сейчас.
- `capabilities→memory` (recall/search_memory → `MemoryRecall` порт) — чисто, через фасад, циклов нет.
- kernel (вариант C) не трогаем.

**Внешние прод-правки:**
- `domain/ports/__init__.py` — re-export 18 портов из `bob.capabilities.ports` (шим).
- `app.py` — 5 import-точек (registry/sink/dispatcher/make_* × блок; PrivacyGuard; mmdc; introspector; url_reader) + 4 внутр. `_build_*` (символы те же).
- `handle_message.py` — progress_announcer/registry/tool_loop + `domain.diagrams` (extract/normalize/strip mermaid) + InterimLineGenerator (TC).
- 🔴 **`privileged_fulfiller.py`** (не был в первичном плане) — tool_loop/registry.
- 🔴 **`infrastructure/llm/factory.py`** — QwenWebSearchProvider (RUNTIME cross-infra edge, новый — пометить legalized).
- `coding/usecases/coding_context.py` — PrivacyGuard (TC, перенос существующего coding-ref).
- Тесты (~30) — импорты; строковых литералов путей НЕ найдено.

**🔴 Инварианты (чек-лист test):** SSRF-guard `read_url` (block private/loopback/metadata IP), tool-loop
(порядок tool_calls), PrivacyGuard `ALLOWED_ROOTS` (introspection не выходит за корни), **shared-instance
`CollectingDiagramSink`** (один инстанс в HandleMessage И в render_diagram — НЕ раздваивать при переезде
render_diagram), announce-политика (live-only, по имени capability), web_search streaming.

## Беады (роль-суб-беады под `bob-8r4.4`) — 6 (на 1 больше: генератор)

- **`.1` dev (каркас)** — `scripts/gen_boundary_rules.py` + конвертация coding/memory/proactivity правил
  на explicit-path + `internals-no-adapters` всем + `--check`. Семантика не ослаблена (сверка findings).
  `beadloom lint --strict` зелёный. (Ещё БЕЗ capabilities — 3 модуля.)
- **`.2` dev (переезд)** — `git mv` ~27 файлов capabilities + импорты (app.py/ports/__init__/handle_message/
  privileged_fulfiller/llm-factory/coding_context/re-export) + ~30 тестов + аннотации + узел module-vertical.
  pytest/ruff/mypy зелёные.
- **`.3` dev (правила capabilities)** — перезапустить генератор (теперь 4 модуля, узел capabilities есть) →
  правила границ capabilities + legalized refs (llm→capabilities RUNTIME, coding→capabilities TC,
  reliability shared). `beadloom lint --strict` зелёный (`reindex --full`).
- **`.4` test** — pytest + capabilities-инварианты (SSRF/tool-loop/PrivacyGuard/shared-sink/announce/
  streaming) + механика правил (🔴 подтвердить c/c изоляция coding↔capabilities реально ловится).
- **`.5` review** — переезд + генератор (не ослабил семантику, explicit-path верны, c/c изоляция) +
  дыра закрыта; вердикт для .5–.8.
- **`.6` tech-writer** — SPEC/DOC capabilities; закрыть #16 (часть); Gate.

## Критерии приёмки

- `src/bob/capabilities/` собран; генератор `gen_boundary_rules.py` работает + `--check`; правила на
  explicit-path (char-class убран); `internals-no-adapters` у всех модулей; c/c изоляция реально ловит.
- `pytest` зелёный (поведение идентично); инварианты целы; `ruff`/`mypy --strict` зелёные.
- `beadloom ci` зелёный; legalized refs помечены. BOB-Issues #16 (часть) закрыт.

## Связи

Эпик BOB-062, срез 4/8 (крупнейший + каркас правил). BDL-UX #143 (native primitive — предложен).
🔴 kernel-split → .7; InterimLineGenerator → .6. Следующий: `.5 social` (`bob-8r4.5`).
