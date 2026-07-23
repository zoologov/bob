<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль memory — «Боб помнит»

Память Боба как единая вертикаль: эпизодическая (append-only лента прожитого) и
семантическая (дистиллированные долговечные факты) память, гибридный recall
(FTS5-ключевые слова + векторный KNN, слитые Reciprocal Rank Fusion), редкая
недеструктивная консолидация эпизодов в дайджесты и консервативный дедуп фактов.
Эмбеддинги и reranker считаются локально — содержимое памяти никогда не покидает
машину.

Это второй **вертикальный** модуль domain-first раскладки (BOB-062.2, срез 2/8
эпика BOB-062): бизнес-логика способности собрана в одном месте `src/bob/memory/`,
а не размазана по слоям `domain/memory/` + `application/usecases/` +
`infrastructure/{persistence,llm}/`. Модуль охватывает три слоя **внутри** одного
bounded-context, поэтому в графе он несёт не-слойный тег `module-vertical` (правило
`architecture-layers` его рёбра пропускает), а внутреннюю и внешнюю дисциплину
держат path-glob `forbid_import`-правила в `.beadloom/_graph/rules.yml`.

## 🔴 Отсрочка kernel персистентности (вариант C, до среза .7)

Долговечный стор эпизодов и фактов (`SqliteMemoryRepo`, `schema.sql`,
`vector_store.py`) — это **общий kernel персистентности**, кормящий через
`.connection()`-шов не только память, но и десяток с лишним чужих сторов. Поэтому по решению
owner'а (вариант C) при переезде он **остаётся в
`infrastructure/persistence/`** до среза BOB-062.7 (консолидация инфра-kernel'а),
где `SqliteMemoryRepo` расщепится на connection-kernel и собственно
MemoryRepo-реализацию. Модуль `memory` забрал только свою бизнес-логику
(порты/сущности/use-case'ы) и recall-/embedding-адаптеры; конкретная запись в
SQLite по-прежнему идёт через kernel.

Единственное следствие — намеренно разрешённое обратное ребро
`kernel → bob.memory.entities`: `sqlite_repo` импортит `EpisodicEvent` /
`SemanticFact`, чтобы маппить их в строки и обратно. Это узаконенный (не
нарушение) `kernel → memory`-импорт, помеченный с TODO-.7 в правилах границ.

## Спецификация

### Раскладка модуля

```
src/bob/memory/
  ports.py        # layer=domain          — порты-протоколы способности
  __init__.py     # layer=domain          — фасад (re-export EpisodicEvent, SemanticFact)
  entities.py     # layer=domain          — EpisodicEvent, SemanticFact (immutable value-objects)
  usecases/       # layer=application
    extract_facts.py       — ExtractFacts (Tier 0 «запомнить»: реплика → факты)
    consolidate_memory.py  — ConsolidateMemory (редкий дайджест старых эпизодов, BOB-021)
    dedup_facts.py         — DedupFacts (редкий консервативный merge дубль-фактов, BOB-021)
  adapters/       # layer=infrastructure
    fts_recall.py          — Fts5MemoryRecall (P0 keyword-recall, BM25)
    hybrid_recall.py       — HybridMemoryRecall (semantic + keyword, RRF, + reranker)
    embedder_factory.py    — build_embedder (из config['embeddings'])
    ollama_embedder.py     — OllamaEmbedder (локальные dense-эмбеддинги, bge-m3 1024-dim)
    reranker_factory.py    — build_reranker (из config['reranker'], опционально → None)
    ollama_reranker.py     — OllamaReranker (локальный reranker как Ollama-scorer)
```

**Остаётся в `infrastructure/persistence/` (shared kernel до .7):**
`sqlite_repo.py` (`SqliteMemoryRepo`), `schema.sql`, `vector_store.py`
(тесно связан с `sqlite_repo` через connection) плюс прочие чужие сторы,
кормящиеся из того же kernel'а.

### Сущности (чистый домен)

`EpisodicEvent` (`entities.py`) — одно событие на ленте (сообщение, тик, действие):
`ts`, `event_type`, `content`, опциональный `mood_snapshot`, свободные `tags`,
`sender_id` (атрибуция реплики собеседнику — per-person память BOB-045; `None`
для тика/дайджеста/legacy-строки) и `bob_message_id` (Telegram message_id
собственного ответа Боба, BOB-050, чтобы позднюю реакцию связать со сказанным).
`SemanticFact` — дистиллированный долговечный факт: `ts`, `category`, `content`,
`confidence` в `[0, 1]`. Оба — `frozen, slots` value-object'ы без I/O; инварианты
(timezone-aware `ts`, `confidence ∈ [0, 1]`) проверяются в `__post_init__`, так что
невалидная запись не может существовать в памяти.

### Use-case'ы (application)

`ExtractFacts` (`usecases/extract_facts.py`) — Tier 0 шаг «запомнить» после
отправки ответа: просит дешёвый **локальный** Tier-0 провайдер (через `LLMRouter`,
`TaskType.EXTRACT_FACTS`) прочитать последний обмен и вернуть долговечные факты о
собеседнике (имя, предпочтение, человек, решение) как JSON-массив. Каждый пункт
становится `SemanticFact` (confidence 0.7 — дистиллированный, но модельный) и
пишется через шов `FactWriter` (kernel-репозиторий, чей FTS5-триггер индексирует
контент). Best-effort: провайдер, вернувший прозу вместо JSON, или ошибка не ломают
ход диалога.

`ConsolidateMemory` (`usecases/consolidate_memory.py`) — редкий недеструктивный
дайджест (BOB-021), навешенный на медленный reflect-тик heartbeat. Отбирает батч
**старых, ещё не консолидированных, не-дайджест** эпизодов старше порога возраста,
сжимает окно локальным Tier-0 вызовом в один дайджест (`event_type='digest'`,
эмбеддится на запись), а источники помечает `consolidated=1` (оригиналы
сохраняются, только выпадают из будущего отбора). Идемпотентно (повтор без
подходящих эпизодов — чистый no-op) и bounded (возраст/размер батча из config,
консервативные дефолты: ≥14 дней, батч 50).

`DedupFacts` (`usecases/dedup_facts.py`) — редкий консервативный merge
near-дубликатов фактов (BOB-021). Отбирает ACTIVE факты (`superseded_by IS NULL`,
кап из config), эмбеддит их батчем локально, кластеризует single-linkage по
косинусной близости **на/выше консервативного порога** (`memory.dedup.threshold`,
дефолт ~0.92), в каждом кластере ≥2 выбирает канонический (самый новый; тай-брейк —
самый длинный content, затем меньший id), остальные помечает `superseded_by`
каноническим. Недеструктивно (superseded-строки хранятся с провенансом, лишь
исключаются из recall), off-by-default (нулевой батч отключает шаг).

### Адаптеры (infrastructure)

`Fts5MemoryRecall` (`adapters/fts_recall.py`) — P0 keyword-recall через SQLite FTS5
`MATCH` с BM25. Покрывает **и** семантические факты, **и** сырой эпизодический
архив (Fix A): старая реплика, из которой факт не извлекали, всё равно всплывает.
Сырой пользовательский текст санитизируется в безопасный FTS5-запрос, так что
операторные символы не вызовут синтаксическую ошибку и не пройдут инъекцией.

`HybridMemoryRecall` (`adapters/hybrid_recall.py`) — drop-in замена keyword-only
recall'а: consumers (`handle_message` / `recall_memory`) по-прежнему видят
`recall(query, k) -> [Recalled]`. Внутри — два поиска над одним архивом:
**семантический** (эмбеддинг запроса через `Embedder` + sqlite-vec KNN по
`memory_vec`) и **keyword** (FTS5 BM25, переиспользует `Fts5MemoryRecall`). Списки
сливаются **Reciprocal Rank Fusion** (RRF-score = сумма по спискам `1 / (k0 +
rank)`), дедуплицируются по контенту, топ-`k` возвращается с тегом `source`.
Опциональный `Reranker` пересортировывает широкий top-`K` пул и подрезает до
тесного top-`N` (строго аддитивно). Опциональный `surface_old` подмешивает ОДНУ
старую-но-релевантную память (релевантна по эмбеддингу, смещена к более старому
`ts`). Graceful fallback: при отсутствующем/упавшем эмбеддере recall деградирует к
чистому FTS5 (Боб «не теряет память», лишь семантическую половину); ошибка
логируется, не пробрасывается.

`OllamaEmbedder` (`adapters/ollama_embedder.py`) — локальные dense-эмбеддинги через
LOCAL Ollama (дефолт `bge-m3`, 1024-dim, multilingual/русский). Две формы запроса
по порядку: batch `POST /api/embed` и legacy per-text `POST /api/embeddings`
(fallback для старых Ollama без batch-эндпоинта). Транзиентные сбои
(обрывы/таймауты/5xx) ретраятся bounded exponential backoff'ом
(`retry_with_backoff`); перманентные (4xx, битое тело, несовпадение размерности)
всплывают сразу. `OllamaReranker` (`adapters/ollama_reranker.py`) — локальный
reranker как Ollama-scorer (нативного rerank-эндпоинта нет — Q1): промптит модель
за одно число релевантности `[0, 1]` на пару `(query, candidate)` по
OpenAI-совместимой `/v1/chat/completions`, сортирует по убыванию, оставляет топ-`N`.
Аддитивный контракт: при недоступности эндпоинта, персистентном сбое или
непарсибельном скоре возвращает вход неизменным (никогда не роняет recall).
Фабрики `build_embedder` / `build_reranker` строят адаптеры из
провайдер-агностичных секций config (`embeddings` / `reranker`); `build_reranker`
возвращает `None`, когда секция отсутствует или `reranker.enabled` false — это
штатное «выключено», не ошибка.

## Инварианты

- **RRF-ранжирование:** гибридный recall сливает keyword- и векторный списки
  Reciprocal Rank Fusion (score = сумма по спискам `1 / (k0 + rank)`) — элемент,
  попавший в **оба** списка, накапливает больший fused-score, чем виденный в одном.
- **Аддитивная семантика:** векторная половина, reranker и `surface_old` строго
  аддитивны. Без эмбеддера / reranker'а / opt-in'а поведение — прежний keyword-only
  recall в неизменном порядке; ни один семантический слой не регрессирует
  retrieval, а его недоступность не роняет память (fallback к FTS5, логируется).
- **Superseded-исключение:** дедуп недеструктивен — merged-факты хранятся с
  провенансом (`superseded_by` = id канонического), но recall и повторный отбор
  видят только ACTIVE (`superseded_by IS NULL`).
- **Консервативный дедуп:** факты сливаются только при косинусной близости
  на/выше высокого порога (~0.92); непохожие остаются singleton-кластерами и
  НИКОГДА не мержатся — высокий порог защищает от ложного слияния (ложный merge
  молча теряет отдельную память).
- **Недеструктивная консолидация:** источники дайджеста лишь помечаются
  `consolidated=1`, оригиналы сохраняются; дайджест никогда не переваривается
  повторно (идемпотентно).
- **Sender-атрибуция:** `EpisodicEvent.sender_id` привязывает реплику к
  собеседнику (per-person память BOB-045); `None` — для тика/дайджеста/legacy.
- **Приватность (локальность):** эмбеддинги и reranking считаются на LOCAL
  Ollama — содержимое памяти никогда не покидает машину.
- **Инварианты сущностей:** `ts` всегда timezone-aware, `confidence ∈ [0, 1]` —
  проверяются в `__post_init__`, невалидная запись не может существовать.

### Границы модуля (AaC)

Дисциплина держится path-glob `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ vertical modules):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/`;
- снаружи к `memory` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`);
- обратное ребро `kernel → bob.memory.entities` (`sqlite_repo` маппит сущности в
  строки) помечено как временно разрешённое с TODO-.7 (до расщепления kernel'а).

Внутренний layer-guard модуля (`tests/memory/test_layering.py`) проверяет, что
`memory.usecases` не тянут `adapters/`, а домен — `usecases/` (эти узлы ушли
из-под охвата `tests/application/test_layering.py` при переезде).

## API

<!-- beadloom:track=src/bob/memory/ports.py -->

Модуль `src/bob/memory/ports.py` (порты-протоколы, только интерфейсы):
- `MemoryRepo` — долговечный стор эпизодов/фактов (`save_episode`, `save_fact`,
  `load_episodes`, `recent_episodes`). Реализация — kernel `SqliteMemoryRepo`.
- `MemoryRecall` — relevance-retrieval (`recall(query, *, k, surface_old=False)`
  → `Sequence[Recalled]`); P0 — FTS5, шов для векторов.
- `Embedder` — `embed(texts)` → `list[list[float]]` (по одному dense-вектору на
  текст, порядок сохраняется; локальный, приватный).
- `Reranker` — `rerank(query, candidates)` → `list[Recalled]` (пере-упорядочивание
  по релевантности, опциональный trim до top-`N`; аддитивно, деградирует мягко).
- `Recalled` = `Mapping[str, object]` — один recalled-элемент (контент + score).

Фасад `src/bob/memory/__init__.py` re-export'ит `EpisodicEvent`, `SemanticFact`.
Порты `memory` также re-export'ятся из `bob.domain.ports`, поэтому
`from bob.domain.ports import MemoryRepo` работает как раньше (шим для ~15
потребителей).

Ключевые точки входа:
- `usecases/extract_facts.py`: `ExtractFacts.run(...)` — извлечь факты из обмена.
- `usecases/consolidate_memory.py`: `ConsolidateMemory` — дайджест старых эпизодов.
- `usecases/dedup_facts.py`: `DedupFacts` — merge near-дубликатов фактов.
- `adapters/`: `Fts5MemoryRecall`, `HybridMemoryRecall`, `OllamaEmbedder`,
  `OllamaReranker`, фабрики `build_embedder` / `build_reranker`.

Композиция (сборка recall'а, эмбеддера, reranker'а и навешивание
extract/consolidate/dedup на heartbeat) — в композиционном корне `app.py`.
Долговечная запись в SQLite идёт через kernel `SqliteMemoryRepo`
(`infrastructure/persistence/`, до среза .7).

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Сущности: `tests/domain/memory/test_entities.py`.
- Use-case'ы: `tests/application/usecases/test_extract_facts.py`,
  `test_consolidate_memory.py`, `test_consolidation_gaps.py`,
  `test_dedup_facts.py`.
- Recall-/embedding-адаптеры (тесты остались при kernel'е — плюс варианта C):
  `tests/infrastructure/persistence/test_fts_recall.py`,
  `test_hybrid_recall.py`, `test_recall_excludes_superseded.py`,
  `test_sender_attribution.py`, `test_consolidation_repo.py`,
  `test_dedup_repo.py`; `tests/infrastructure/llm/test_ollama_embedder.py`,
  `test_embedder_factory.py`, `test_ollama_reranker.py`,
  `test_reranker_factory.py` (+ `*_hardening.py`).
- Layer-guard модуля: `tests/memory/test_layering.py`.
- Приёмка и e2e: `tests/test_acceptance_memory.py`,
  `tests/test_acceptance_consolidation.py`, `tests/test_e2e_memory_hybrid.py`.
