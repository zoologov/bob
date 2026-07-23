<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.2 — «Срез memory → src/bob/memory/»

> **Status:** In Progress
> **Updated:** 2026-07-23
> **Branch:** `features/BOB-062.2` · **Родитель:** `bob-8r4.2` (эпик `bob-8r4`)

---

## Беады (последовательно)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.2.1` | dev — переезд memory (kernel остаётся) | ✔ done |
| `bob-8r4.2.2` | dev — AaC правила + пометка kernel→memory | ● blocked (.1) |
| `bob-8r4.2.3` | test — pytest + memory-инварианты + ci | ● blocked (.1,.2) |
| `bob-8r4.2.4` | review — переезд + границы (kernel чиста) | ● blocked (.3) |
| `bob-8r4.2.5` | tech-writer — SPEC/DOC + #12 + Gate | ● blocked (.4) |

Критпуть: `.1 → .2 → .3 → .4 → .5` (один PR на срез).

## Ключевое решение (утв. owner 2026-07-23)

🔴 **Вариант C — kernel персистентности отложен в срез .7.** memory забирает бизнес-логику
(entities/ports/usecases/recall-адаптеры/embeddings); `sqlite_repo`+`schema.sql`+`vector_store`
остаются в `infrastructure/persistence/` как shared kernel (13 чужих сторов не тронуты) до среза
.7 (application+runtime), где `SqliteMemoryRepo` расщепляется connection↔MemoryRepo.

## Заметки

- 🔴 Избегать обратных зависимостей infra-kernel→memory; `sqlite_repo→memory.entities` помечается
  разрешённой (TODO-.7).
- entities fan-out — 4 прод-файла (или шим `domain/memory/__init__`).
- handle_message тянет память (2 строки, здесь; декомпозиция — .6).
- `detect_patterns` НЕ переезжает (self-improvement).

## Прогресс

- 2026-07-23: BRIEF Approved (вариант C); роль-беады созданы; ветка `features/BOB-062.2`. Старт Волны 0.
- 2026-07-23: **.1 dev DONE.** `git mv` 11 файлов → `src/bob/memory/` (ports/entities/__init__ + usecases×3 +
  adapters×6); `domain/memory/` удалён; kernel не тронут. entities-подход — **fan-out** (без шима). Внешние
  правки: ports-шим→`bob.memory.ports`, `app.py`, re-export пакеты (usecases/persistence/llm), ~24 теста.
  Аннотации `feature=memory`+`layer=`; граф-узел `memory`→`src/bob/memory/` (tag `module-vertical`).
  Единственная kernel→memory: `sqlite_repo→bob.memory.entities` (помечена, TODO-.7). Gate: pytest 3269 ·
  ruff · mypy --strict · reindex · lint --strict 0 — всё зелёное. НЕ закоммичено (координатор). Далее: `.2`.
