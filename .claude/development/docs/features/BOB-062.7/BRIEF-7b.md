<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.7b — «kernel-split: SqliteMemoryRepo → connection-kernel ↔ MemoryRepo» (Фаза 3, 7b/8)

> **Status:** Approved
> **Created:** 2026-07-28
> **Type:** feature · часть b среза .7 · BOB-Issues #10 (kernel-остаток) · долг варианта C (с .2)
> **Родитель:** `bob-8r4.7` · Предшественник: .7a (PR #86, runtime/) в main

---

## Проблема

`infrastructure/persistence/sqlite_repo.py` (`SqliteMemoryRepo`, 647 стр) совмещает ДВЕ роли: (1)
**connection/schema-kernel** (open/WAL/pragma/close/`.connection` seam/kv/`_load_schema`) — общий, кормит
13 сторов всех модулей + memory; (2) **memory-реализацию** (episodic/semantic/vector/mood/taste/
consolidation/dedup). В .2 (memory) расщепление отложили (вариант C) — делаем здесь. Цель: чистая граница
«connection-kernel (инфраструктура I/O) ↔ MemoryRepo (адаптер memory-модуля)».

## Решение (behavior-preserving хирургия — blast radius по 13 сторам ≈0)

### Расщепление SqliteMemoryRepo
- **Connection-kernel → `infrastructure/persistence/connection.py`** (`SqliteConnection`): `initialize()`
  (open+WAL+foreign_keys+sqlite-vec load+`executescript(schema.sql)`+миграции+backfill), `close()`,
  `journal_mode()`, `_db()`, **`connection` (@property — THE SEAM)**, `kv_set`/`kv_get`, `_load_schema()`.
  Это чистое I/O (aiosqlite), НЕ композиция — потому infrastructure, НЕ runtime (runtime лишь СОЗДАЁТ kernel
  и инъектит его во все сторы).
- **Memory-часть → `memory/adapters/sqlite_memory_repo.py`** (реализует `memory.ports.MemoryRepo`):
  episodic (save_episode/load/recent/recent_for/by_bob_message_id), semantic/dedup (save_fact/load/select_
  active/supersede), consolidation (select_consolidatable/save_digest/mark_consolidated), vector (vector_count/
  knn/embed/store), mood/taste (set_mood/get_mood/mood_history/set_taste_axis/load_taste_axes), memory-миграции.
  Зависит от connection-kernel через `.connection` seam (структурно).
- **`vector_store.MemoryVectorStore` → `memory/adapters/`** (завязан на Embedder + VectorSource — чисто
  memory). 🔴 `load_extension()` (vec0) грузит connection-kernel при init (capability соединения); knn/
  backfill/embed → memory.

### 🔴 13 «чужих» сторов — код НЕ меняется (blast radius ≈0)
Все объявляют локальный структурный `_ConnectionProvider` Protocol (`@property connection` + kv) и берут
`self._repo.connection` — им нужен ЛЮБОЙ объект с `.connection`. Composition-root (runtime) просто передаёт
`SqliteConnection` вместо `SqliteMemoryRepo`. Изменения в сторах = 0 (максимум docstring). Сторы:
personality/adapters/{fascination,notable_reaction}, social/adapters/{relationship,sulk,first_impression,
permission_request,allowlist,soul}, proactivity/adapters/{proactivity,goal,self_improvement,sources},
coding/adapters/session_store, conversation/adapters/{closer_log,conversation_floor}.

### 🔴 Реальные concrete-refs (правятся)
- `memory/adapters/fts_recall.py:41` + `hybrid_recall.py:91` — `__init__(repo: SqliteMemoryRepo)` → тип на
  новый `SqliteMemoryRepo` (в memory/adapters) ИЛИ на connection-kernel если им нужен только `.connection`.
  Проверить что им нужно (recall юзают `.connection.execute`) — вероятно connection-kernel достаточно.
- `runtime/composition.py` (owner — создаёт оба; boot-order: connection-kernel ПЕРЕД memory_repo и сторами).
- `infrastructure/persistence/__init__.py` (re-export).
- 🔴 Убрать задокументированное ребро `kernel(sqlite_repo) → memory.entities` (rules.yml) — memory-методы
  уезжают в memory-модуль, забирая импорт `EpisodicEvent`/`SemanticFact` внутрь себя. Это ЦЕЛЬ .7b.

### 🔴 Особые точки
- **`_migrate_pursuit_stopped`/`_proactivity_columns`** — proactivity-миграции живут в `initialize()` memory-
  репо (скрытая cross-module связка). При split: connection-kernel остаётся «schema/migration-owner» (запускает
  ВСЕ миграции из schema.sql — это его роль как владельца соединения), либо пометить для будущего переноса в
  proactivity. Рекомендация: оставить в kernel (schema-owner), пометить `# BOB-062: proactivity-specific,
  future relocation`.
- **`schema.sql` остаётся ЕДИНЫМ** в connection-kernel (FTS5 external-content триггеры + foreign_keys +
  ordering + memory_vec vec0 связаны одним `executescript`). Дробление по модулям = отдельный будущий срез.
- **mood/taste в memory-репо:** `set_mood` используется в prod (handle_message/heartbeat); get_mood/taste —
  только тесты; set_relationship — dead (legacy blob). Едут с memory-частью (это memory-persistence по факту).

## Беады .7b (под `bob-8r4.7`, продолжение нумерации .7+)

- **`.7` dev** — расщепить: `infrastructure/persistence/connection.py` (SqliteConnection) + `memory/adapters/
  sqlite_memory_repo.py` (MemoryRepo) + vector_store→memory. Composition-root: создать connection-kernel,
  инъектить его в 13 сторов + memory_repo (boot-order: kernel первым). fts/hybrid_recall concrete-ref. Убрать
  kernel→memory.entities ребро. schema.sql единым. 🔴 13 сторов код не менять. pytest/ruff/mypy(полный) зелёные.
- **`.8` dev** — правила: перецелить граф-узлы (connection-kernel в infrastructure/persistence; memory-репо в
  memory); note-блок legalized (memory/adapters→connection-kernel наружу; сторы→connection через инъекцию БЕЗ
  import). `reindex --full && lint --strict` EXIT 0 (kernel→memory.entities ребра больше нет; проба).
- **`.9` test** — pytest + 🔴 persistence-инварибанты (WAL/foreign_keys/sqlite-vec load, schema executescript
  один раз, миграции/backfill, connection seam кормит все сторы, recall RRF, episodic/semantic целостность,
  set_mood prod-путь). connection-kernel один инстанс всем (shared). `reindex --full && lint --strict` +
  mypy ПОЛНЫЙ. beadloom ci.
- **`.10` review** — расщепление чисто (connection-kernel = I/O, memory-репо = адаптер); 13 сторов не тронуты;
  kernel→memory ребро убрано; schema единой оправдано; boot-order (kernel первым) цел; поведение идентично.
- **`.11` tech-writer** — SPEC обновить (memory: sqlite_memory_repo; infrastructure/persistence: connection-
  kernel); закрыть #10 полностью (app.py .7a + kernel-split .7b); Gate.

## Критерии приёмки

- `SqliteMemoryRepo` расщеплён: connection-kernel (`infrastructure/persistence/connection.py`) ↔ MemoryRepo
  (`memory/adapters/`); vector→memory; 13 сторов код не тронут (структурный seam); kernel→memory.entities убрано.
- `pytest` зелёный (поведение идентично) · `mypy` ПОЛНЫЙ 0 · `ruff` · **`reindex --full && lint --strict` EXIT 0**
  · `beadloom ci` зелёный. BOB-Issues #10 → Closed полностью (kernel-split остаток отгружен).

## Связи

Срез 7b/8 (закрывает долг варианта C с .2 + #10). После — .8 (доки/закрытие: ужать architecture.md #4,
удалить ports-шим #18, флип no-monster→error, эпик-хардинг).
