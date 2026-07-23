<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.1 — «Срез coding → src/bob/coding/» (Фаза 3, срез 1/8)

> **Status:** Approved
> **Created:** 2026-07-23
> **Type:** feature · срез эпика BOB-062 · BOB-Issues #11
> **Родитель:** `bob-8r4.1` (эпик `bob-8r4`) · Контекст: эпик `PRD/RFC/CONTEXT` (Approved)
> **🔑 КОНТРОЛЬНЫЙ срез** — валидирует схему модуля + layer-теги + правила границ + доки-в-срезе до .2–.8

---

## Проблема

Способность «Боб пишет код» (Bob-coder) сейчас размазана по трём слоям: `domain/coding/` +
`usecases/coding_*` + `infrastructure/coding/` + `persistence/coding_session_store` +
`telegram/coding_indicator` + `ports/coding`. Смотря на дерево, не видно «coding как единое целое».
Первый вертикальный срез собирает её в один модуль `src/bob/coding/` — и заодно **валидирует всю схему**
domain-first (структура модуля, `# beadloom:layer=`, правила границ, доки-в-срезе) до массового применения.

## Решение (атомарный переезд, behavior-preserving)

Целевая структура (по эпик-CONTEXT — `ports.py` + логика в корне модуля + `usecases/` + `adapters/`):

```
src/bob/coding/
  ports.py            # layer=domain  ← из domain/ports/coding.py
  __init__.py         # layer=domain  (фасад)
  entities.py · intent.py · naming.py · narrate.py · session_voice.py · state.py   # layer=domain
  usecases/           # layer=application  ← coding_assistant · coding_context ·
                      #                       classify_coding_intent · coding_intent_router
  adapters/           # layer=infrastructure ← _branch · _exec · claude_runner · gh_pr ·
                      #   git_worktree · __init__ · session_store (ex-persistence) · indicator (ex-telegram)
```

**~20 файлов** (8 domain + 4 app + 8 infra) — `git mv` + переписать импорты в **одном PR**:
- **Прод-импорты править ТОЛЬКО в:** `src/bob/app.py` (7 import-блоков) + `src/bob/domain/ports/__init__.py`
  (re-export coding-портов). `handle_message.py`, `guppi.py`, `multibot.py` — **НЕ трогать** (нет прямых import).
- **Тесты (~24 файла):** переписать импорты. 🔴 **Ловушка:** `tests/test_coding_never_merge_and_autonomy_guard.py`
  содержит **строковые литералы путей** (`src/bob/domain/coding/state.py`, `.../infrastructure/coding/*.py`,
  строки ~36–44, 97, 110) — править как строки, не только import.
- **Аннотации:** всем перемещённым файлам — `# beadloom:feature=coding` + `# beadloom:layer=<domain|application|
  infrastructure>` (6 сменить `coding-domain→coding`, 4 сменить `usecases→coding`, 10 добавить с нуля).
- **Граф:** перецелить узел `coding-domain`→узел `coding` с `source: src/bob/coding/` (+ снять устаревшие узлы,
  если coding раскидан по слой-узлам); `beadloom reindex`.

**AaC-правила границ модуля (валидация схемы, #8):** ввести per-module правила `forbid_import` — внутри
модуля: логика (`layer=domain`) не тянет `usecases/`/`adapters/`; `usecases` не тянет чужой `adapters`;
снаружи: к coding — только через `ports`/фасад. Прогнать `beadloom lint --strict`.

**3 cross-boundary находки** (из разведки — разрулить или осознанно пометить, НЕ ломая поведение):
1. `classify_coding_intent → application/router/llm_router` (app→app общего router-модуля) — пометить как
   разрешённую зависимость на shared-router (llm_router общий, остаётся вне coding).
2. `coding_context → domain/introspection/privacy_guard` (TYPE_CHECKING-only) — пометить.
3. `adapters/indicator → infrastructure/telegram/gateway` (TYPE-only, cross-infra) — пометить.

## Беады (роль-суб-беады под `bob-8r4.1`)

- **`.1` dev** — переезд: структура `src/bob/coding/`, `git mv` ~20 файлов, переписать прод-импорты
  (`app.py` + `ports/__init__`) + ~24 теста (вкл. строковые литералы!), `# beadloom:feature/layer` аннотации,
  перецелить граф-узел + `beadloom reindex`. `pytest`/`ruff`/`mypy --strict` зелёные.
- **`.2` dev** — AaC: правила границ модуля coding в `.beadloom/_graph/rules.yml` (layer внутри модуля +
  граница «только через ports»); разрулить/пометить 3 cross-boundary находки; `beadloom lint --strict` зелёный.
- **`.3` test** — полный `pytest` (поведение идентично) + 🔴 coding-инварианты (never-merge / plan-gate /
  PR-открывает-не-мержит / worktree-изоляция / NL-approve-stop) + `beadloom ci` зелёный.
- **`.4` review** — корректность переезда, границы/слои, поведение неизменно, доки честны; **+ явный вердикт:
  «схема модуля удобна?»** (контрольный вывод — влияет на .2–.8 эпика).
- **`.5` tech-writer** — наполнить `docs/` SPEC/DOC модуля coding (не скелет); закрыть BOB-Issues #11.

## Критерии приёмки

- `src/bob/coding/` собран по схеме CONTEXT; `git grep` не находит старых путей `domain/coding|infrastructure/
  coding|usecases/coding_`; импорты и строковые литералы обновлены.
- `pytest` зелёный (поведение идентично); coding-инварианты целы; `ruff`/`mypy --strict` зелёные.
- `beadloom ci` зелёный: граф перецелен, правила границ модуля активны и проходят, доки наполнены.
- Review вынес вердикт по схеме модуля (для эпика). BOB-Issues #11 закрыт.

## Связи

Эпик BOB-062 (`bob-8r4`), срез 1/8. RFC/CONTEXT эпика — источник схемы и чек-листа инвариантов.
Следующий по цепочке: `.2 memory` (`bob-8r4.2`, blocked до мержа этого среза).
