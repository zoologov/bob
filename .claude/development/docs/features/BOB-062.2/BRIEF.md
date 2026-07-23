<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.2 — «Срез memory → src/bob/memory/» (Фаза 3, срез 2/8)

> **Status:** Approved
> **Created:** 2026-07-23
> **Type:** feature · срез эпика BOB-062 · BOB-Issues #12
> **Родитель:** `bob-8r4.2` (эпик `bob-8r4`) · Контекст: эпик `RFC/CONTEXT` (Approved) + прецедент среза .1 coding

---

## Проблема

Способность «память» (эпизоды/факты/recall/консолидация/эмбеддинги) размазана по слоям:
`domain/memory/` + `usecases/{extract_facts,consolidate_memory,dedup_facts}` + `persistence/{recall,vector}` +
`llm/{embedder,reranker}` + `ports/memory`. Собираем в `src/bob/memory/` по валидированной схеме среза .1.

## 🔴 Главное решение (утв. owner): kernel персистентности ОТКЛАДЫВАЕТСЯ в срез .7

Разведка вскрыла: `sqlite_repo.py` (`SqliteMemoryRepo`, 641 стр) + `schema.sql` (таблицы **ВСЕХ**
модулей) — это **общий kernel персистентности**, кормящий 13 чужих сторов через `.connection()` seam,
а не «только память». **Решение owner (2026-07-23): вариант C** — memory забирает свою бизнес-логику;
connection/schema/sqlite_repo остаются в `infrastructure/persistence/` как shared kernel до среза .7
(application+runtime), где инфра-kernel и так консолидируется, а `SqliteMemoryRepo` расщепляется на
connection-kernel ↔ MemoryRepo-реализацию.

## Решение (атомарный переезд, behavior-preserving)

Целевая структура (схема CONTEXT, как в .1 coding):
```
src/bob/memory/
  ports.py        # layer=domain  ← из domain/ports/memory.py (MemoryRepo/MemoryRecall/Recalled/Embedder/Reranker)
  __init__.py     # layer=domain  (фасад, re-export entities)
  entities.py     # layer=domain  ← из domain/memory/entities.py (EpisodicEvent, SemanticFact)
  usecases/       # layer=application ← extract_facts · consolidate_memory · dedup_facts
  adapters/       # layer=infrastructure ← hybrid_recall · fts_recall (recall-адаптеры)
                  #   + embedder_factory · ollama_embedder · reranker_factory · ollama_reranker (embeddings)
```

**ОСТАЮТСЯ в `infrastructure/persistence/` (shared kernel до .7):** `sqlite_repo.py`, `schema.sql`,
`vector_store.py` (тесно связан с sqlite_repo через connection — едет с kernel), + 15 чужих сторов.

**НЕ переезжает:** `detect_patterns.py` (это self-improvement/proactivity, не память — импортит
`personality.self_improvement`, не memory-entities; остаётся в application/usecases).

### 🔴 Граница без обратных зависимостей (принцип для dev)

Оставшийся `sqlite_repo` (kernel) импортит `entities` (уезжает в memory). Правило: **избегать
infra-kernel→memory обратных зависимостей**. Неизбежная `sqlite_repo → bob.memory.entities` (т.к.
sqlite_repo — это memory-adapter, временно живущий в kernel до .7) **помечается разрешённой** в
правилах с TODO-.7. dev проводит границу так, что взаимосвязанные с sqlite_repo файлы (vector_store)
остаются с kernel; всё, что создаёт цикл, — либо остаётся, либо помечается временным исключением.

### Внешние прод-правки (шире, чем у coding — из-за entities-fan-out)

- `domain/ports/__init__.py` — 1 строка (re-export memory-портов из `bob.memory.ports`; шим закрывает ~15 потребителей).
- `entities` fan-out — 4 прод-файла на `from bob.memory.entities import EpisodicEvent`:
  `proactivity/engine.py`, `usecases/pursue_goals.py`, `usecases/heartbeat.py`, **`usecases/handle_message.py`** (🔴 runtime).
- `handle_message.py` — 2 строки (`:58` entities runtime, `:159` extract_facts TYPE); полная декомпозиция — срез .6, здесь только импорты.
- `app.py` — llm-блок (embedder/reranker), usecases (extract/consolidate/dedup), persistence-импорт (вынуть hybrid_recall; sqlite_repo остаётся).
- re-export пакеты: `usecases/__init__.py`, `persistence/__init__.py` (убрать recall), `llm/__init__.py` (убрать embedder/reranker).
- **Опция для сокращения fan-out:** тонкий шим `domain/memory/__init__.py` → re-export из `bob.memory.entities` (тогда 4 файла не трогать). Решение dev (прецедент coding — БЕЗ шима; но здесь fan-out шире → шим допустим, если чище).
- Тесты (~30): импорты; 🔴 ~13 чужих store-тестов НЕ трогаются (sqlite_repo остаётся на месте — плюс варианта C!). Проверить `tests/application/test_layering.py` — memory.usecases уходят из-под его охвата → нужен layer-guard внутри memory (беад .2).

## Беады (роль-суб-беады под `bob-8r4.2`)

- **`.1` dev** — переезд memory (структура + `git mv` бизнес-логики/recall/embeddings, kernel ОСТАВИТЬ; переписать импорты app.py + ports/__init__ + entities fan-out + handle_message 2 строки + re-export пакеты + ~30 тестов; `# beadloom:feature=memory`+`layer=`; перецелить граф-узел memory + reindex). pytest/ruff/mypy зелёные.
- **`.2` dev** — AaC: правила границ модуля memory (как у coding: layer внутри + к модулю через ports); пометить временную `sqlite_repo→bob.memory.entities` (kernel→memory, TODO-.7); layer-guard внутри memory. `beadloom lint --strict` зелёный.
- **`.3` test** — полный `pytest` (поведение идентично) + memory-инварианты (recall RRF-ранжирование, консолидация/дедуп не теряют факты, эмбеддинг-фолбэки, superseded-исключение) + `beadloom ci` зелёный.
- **`.4` review** — корректность переезда, границы (особо: kernel-отсрочка чиста, нет случайных обратных зависимостей кроме помеченной), поведение неизменно, доки честны.
- **`.5` tech-writer** — наполнить SPEC/DOC модуля memory; закрыть #12; Gate (`sync-update bob` + `setup-rules --refresh`).

## Критерии приёмки

- `src/bob/memory/` собран по схеме; `git grep` не находит старых memory-путей (кроме оставшегося kernel).
- kernel (sqlite_repo/schema/vector_store) на месте, 13 чужих сторов + их тесты не тронуты.
- `pytest` зелёный (поведение идентично); memory-инварианты целы; `ruff`/`mypy --strict` зелёные.
- `beadloom ci` зелёный; временная kernel→memory зависимость помечена с TODO-.7.
- BOB-Issues #12 закрыт.

## Связи

Эпик BOB-062, срез 2/8. Прецедент .1 coding (схема валидирована). 🔴 kernel-расщепление → срез .7.
Следующий: `.3 proactivity` (`bob-8r4.3`, blocked до мержа).
