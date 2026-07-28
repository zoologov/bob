<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.7 — «application+runtime: app.py→runtime + kernel-split» (Фаза 3, срез 7/8)

> **Status:** .7a Approved · .7b — свой раздел, старт после мержа .7a
> **Created:** 2026-07-28
> **Type:** feature (под-эпик .7a + .7b) · BOB-Issues #10 (+ #17) + kernel-split (отложен с .2)
> **Родитель:** `bob-8r4.7` · Прецеденты: .1–.6 + приём split (.6)

---

## Структура (2 PR — два ортогональных риска)

- **.7a** — `app.py` (2819 стр) → `src/bob/runtime/` (composition root + entrypoint) + инлайн-адаптеры по
  домам + тонкий `app.py`-shim. Механический перенос-графа.
- **.7b** — kernel-split: `SqliteMemoryRepo` → connection-kernel (`infrastructure/persistence/connection.py`)
  ↔ MemoryRepo (`memory/adapters/`). Хирургия персистентности (отложена с .2, вариант C).

Бить, т.к. провалы диагностируются по-разному; .7a даёт `runtime/`, на который опирается .7b.

---

## .7a — app.py → runtime/ (ТЕКУЩИЙ)

### Целевая структура
```
src/bob/runtime/
  __init__.py
  composition.py   # build_application() + Application + _as_handler (composition root)
  main.py          # main()/_run()/_configure_logging/__main__ (entrypoint)
  clock.py         # SystemClock/_async_sleep/_monotonic
  config.py        # _section/_str/_int/… + path-readers + 🔴 _REPO_ROOT
  wiring/          # _build_* фабрики (telegram/coding/proactivity/registry/…)
```
🔴 **Коллизия имён:** существует `bob.application.runtime` (AgentRuntime/AsyncEventBus/periodic — async-примитивы, ОСТАЮТСЯ). Новый `bob.runtime` = composition-root/entrypoint. Развести docstring'ами.

### Инлайн-адаптеры по домам (НЕ в runtime)
- Telegram (`_AiogramBotAdapter`/`_*View`/`_BobReactionFilter`/`_build_real_bot`/`_to_update_view`) →
  `infrastructure/telegram/aiogram_adapter.py`.
- Доменные: `_PermissionRequesterChannel`/`_SafeDefaultPrivilegeJudge`/`_PermissionNotifier` →
  `social/adapters/`; `_CodingOwnerNotifier` → `coding/adapters/`; `_GuppiOutageNotifier` →
  `infrastructure/telegram/`; `_load_soul`/`_default_soul`/`_*_from` → `social/adapters/` (SoulStore там).

### 🔴 Хрупкие инварианты (чек-лист — точные строки в разведке)
- **`_REPO_ROOT`**: `parents[2]`→**`parents[3]`** после переезда (src/bob/runtime/config.py). 3 использования
  (_DEFAULT_TEMPLATES_DIR, PrivacyGuard ×2). 🔴 промах = DENY всего интроспекшн-дерева. **Unit-тест
  `_REPO_ROOT == <repo>`** обязателен.
- **boot-order**: multibot → {sulk_tracker(announcer=guppi), self_improvement(gateway=reply), engine,
  pursue_goals, handle_message}. Комментарии «built AFTER multibot». Переносить блоками, порядок дословно.
- **shared-instance**: `_build_registry` возвращает КОРТЕЖ `(registry, diagram_sink, diagram_renderer)` —
  один sink в handle_message И capability. notable_reaction_store — один kv (handle_message + perceive_reaction).
  resolved_bob_bot — один инстанс всем. НЕ раздваивать.
- **feature-flag off→None→inert**: floor/rule/coding/pursuit/verify(×3)/consolidate/dedup/introspection/
  diagrams/search/read_url. Контракт «flag off ⇒ None ⇒ inert» сохранить.

### app.py → тонкий shim (blast radius ~0)
`app.py` = re-export из `bob.runtime` (build_application/Application/SystemClock/main + `_build_*`, которые
тянут 27 тестов). 🔴 launcher `./bob`: `from bob.app import main` в LAUNCH + **pgrep PATTERN** (обнаружение
процесса для stop/status) — оставить работающим (shim держит) ИЛИ обновить оба. `monkeypatch("bob.app.
asyncio.run")` (test_app_hardening) — перенаправить на `bob.runtime.main.asyncio` (shim не спасает патч-по-атрибуту).

### 🔴 Правила (инвариант под угрозой)
7 правил `*-no-composition-root` в rules.yml таргетят `src/bob/app.py`. После переезда модуль сможет
импортнуть `bob.runtime.composition` необнаруженно. **Расширить globs на `bob/runtime`** (или через
генератор). Плюс `runtime→все модули` легально (composition root); `модули→runtime` запретить.

## Беады .7a (под `bob-8r4.7`)

- **`.1` dev** — app.py→runtime/ (composition/main/clock/config/wiring) + инлайн-адаптеры по домам +
  тонкий app.py-shim + 🔴 `_REPO_ROOT parents[3]` + unit-тест + boot-order/shared-instance/flags дословно +
  launcher `./bob` (LAUNCH+pgrep) + monkeypatch-редирект. pytest/ruff/mypy(ПОЛНЫЙ src+tests) зелёные.
- **`.2` dev** — правила: расширить 7 `*-no-composition-root` на `bob/runtime` (генератор/вручную); note
  про коллизию application.runtime vs runtime; no-dependency-cycles зелёный + проба (модуль→runtime горит).
- **`.3` test** — pytest + 🔴 инварианты (boot-order, shared diagram_sink один, notable_reaction один,
  _REPO_ROOT резолвит, feature-flags off→None→inert) + launcher smoke + **mypy ПОЛНЫЙ (src+tests)** +
  beadloom ci. 🔴 УРОК .6b: mypy без пути (не только src/).
- **`.4` review** — composition-root чист, инварибанты целы, shim корректен, коллизия имён разведена, правила расширены.
- **`.5` tech-writer** — SPEC runtime + architecture; закрыть #10(app.py-часть)/#17; Gate.

## Критерии приёмки .7a

- `bob/runtime/` (composition+entrypoint); app.py тонкий shim; инлайн-адаптеры по домам; `_REPO_ROOT`
  корректен (unit-тест); launcher `./bob` работает; boot-order/shared-instance/flags целы.
- `pytest` зелёный; **mypy ПОЛНЫЙ (src+tests) 0**; ruff; `beadloom ci` зелёный; правила расширены на runtime.
- BOB-Issues #10(app.py) + #17 отгружены (kernel-split #10-остаток → .7b).

## .7b — kernel-split (после .7a, свой раздел)

`SqliteMemoryRepo` расщепить: connection-kernel (open/WAL/pragma/close/`.connection`/kv/`_load_schema`) →
`infrastructure/persistence/connection.py` (`SqliteConnection`); memory-методы (episodic/semantic/vector/
mood/taste/consolidation/dedup + memory-миграции) → `memory/adapters/sqlite_memory_repo.py` (реализует
`memory.ports.MemoryRepo`); vector_store → memory. 🔴 13 сторов НЕ меняются (структурный `.connection`
Protocol — composition передаёт SqliteConnection вместо SqliteMemoryRepo, blast radius кода = 0). Убрать
ребро kernel→memory.entities. **schema.sql остаётся единым** в kernel (дробление — будущий срез). Аномалия
`_migrate_pursuit_stopped` (proactivity в memory-init) — развязать/пометить. Concrete-refs: fts_recall/
hybrid_recall (memory-внутренние, ок).

## Связи

Срез 7/8. После — .8 (доки/закрытие: ужать architecture.md #4, удалить ports-шим #18, флип no-monster→error).
