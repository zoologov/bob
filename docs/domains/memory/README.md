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

## Kernel персистентности расщеплён (BOB-062.7b — долг варианта C закрыт)

В срезе .2 долговечный стор эпизодов и фактов оставили в
`infrastructure/persistence/` как «общий kernel персистентности» (вариант C),
потому что он совмещал две роли: connection/schema-kernel (кормит через
`.connection`-шов не только память, но и 13 чужих сторов) и собственно
memory-реализацию. Срез **BOB-062.7b** это расщепил, закрыв долг варианта C:

- **connection-kernel → `infrastructure/persistence/connection.py`**
  (`SqliteConnection`): чистое I/O — open/WAL/foreign_keys, загрузка sqlite-vec,
  идемпотентный `executescript(schema.sql)`, общий kv-стор и `.connection`-шов.
  Он остаётся в инфраструктуре (это не композиция) и кормит все сторы всех модулей.
- **memory-реализация → `memory/adapters/sqlite_memory_repo.py`**
  (`SqliteMemoryRepo`, реализует `memory.ports.MemoryRepo`) плюс
  `memory/adapters/vector_store.py` (`MemoryVectorStore`) — уехали в модуль
  `memory`. Репозиторий читает kernel структурно через его `.connection`-шов.

Обратное ребро `kernel → bob.memory.entities` **устранено**: маппинг
`EpisodicEvent` / `SemanticFact` в строки теперь живёт внутри
`memory/adapters/`, поэтому импорт memory-сущностей замкнут в самом модуле, а
kernel не зависит ни от какого бизнес-контекста.

## Спецификация

### Раскладка модуля

```
src/bob/memory/
  ports.py        # layer=domain          — порты-протоколы способности
  __init__.py     # layer=domain          — фасад (re-export EpisodicEvent, SemanticFact)
  entities.py     # layer=domain          — EpisodicEvent, SemanticFact (immutable value-objects)
  self_action.py  # layer=domain          — SelfActionKind, SelfAction, describe_self_action (автобиография, BOB-079)
  usecases/       # layer=application
    extract_facts.py       — ExtractFacts (Tier 0 «запомнить»: реплика → факты)
    consolidate_memory.py  — ConsolidateMemory (редкий дайджест старых эпизодов, BOB-021)
    dedup_facts.py         — DedupFacts (редкий консервативный merge дубль-фактов, BOB-021)
  adapters/       # layer=infrastructure
    sqlite_memory_repo.py  — SqliteMemoryRepo (MemoryRepo: episodic/semantic/vector/mood/taste)
    vector_store.py        — MemoryVectorStore (sqlite-vec vec0-таблица memory_vec)
    fts_recall.py          — Fts5MemoryRecall (P0 keyword-recall, BM25)
    hybrid_recall.py       — HybridMemoryRecall (semantic + keyword, RRF, + reranker)
    embedder_factory.py    — build_embedder (из config['embeddings'])
    ollama_embedder.py     — OllamaEmbedder (локальные dense-эмбеддинги, bge-m3 1024-dim)
    reranker_factory.py    — build_reranker (из config['reranker'], опционально → None)
    ollama_reranker.py     — OllamaReranker (локальный reranker как Ollama-scorer)
    self_action_recorder.py — MemoryBacked/NoOp SelfActionRecorder (автобиография, BOB-079)
```

**Connection-kernel (общий, в инфраструктуре):**
`infrastructure/persistence/connection.py` (`SqliteConnection`) + `schema.sql`.
`SqliteMemoryRepo` и все прочие сторы читают его через инъецированный
`.connection`-шов — memory-модуль владеет своей записью в SQLite, но не открывает
соединение сам.

### Сущности (чистый домен)

`EpisodicEvent` (`entities.py`) — одно событие на ленте (сообщение, тик, действие):
`ts`, `event_type`, `content`, опциональный `mood_snapshot`, свободные `tags`,
`sender_id` (атрибуция реплики собеседнику — per-person память BOB-045; `None`
для тика/дайджеста/legacy-строки), `bob_message_id` (Telegram message_id
собственного ответа Боба, BOB-050, чтобы позднюю реакцию связать со сказанным) и
`visibility` (scope-провенанс хода — BOB-066 2.6 такт разглашения: `'public'` /
`'owner_private'`, либо `None` = public). `SemanticFact` — дистиллированный
долговечный факт: `ts`, `category`, `content`, `confidence` в `[0, 1]` и такой же
`visibility` (провенанс исходного хода). Оба — `frozen, slots` value-object'ы без
I/O; инварианты (timezone-aware `ts`, `confidence ∈ [0, 1]`) проверяются в
`__post_init__`, так что невалидная запись не может существовать в памяти.

`visibility` — провенанс, а не гейт: память **несёт** его вниз до слоя, который
фильтрует (такт разглашения в `social`/`application`, см. инвариант ниже); сама
`memory` его лишь пишет и протаскивает через recall. `None` = public держит
BOB-051 единую память и все legacy-строки нетронутыми, а owner recall остаётся
байт-в-байт (INV-7).

**Автобиография — самодействия от первого лица (BOB-079).** До BOB-079 лента
несла *слова* Боба (`event_type='message'`) и *чувства* (`'reflection'`), но не
*поступки*: у Боба не было следа собственных действий, поэтому свой же runaway-
инцидент он присвоить не мог. `self_action.py` (чистый домен, I/O-free) вводит
`SelfActionKind` (`StrEnum`: `coding_started/finished/aborted/failed/runaway`,
`tool_use`, `tool_failure`), value-object `SelfAction` (`kind`, опц. `target`/
`detail`) и детерминированный рендер `describe_self_action → RenderedSelfAction`
(`content` **всегда от первого лица** — «я …», `tags`, флаг `is_anomaly` для
failed/runaway/tool_failure). Рендер — mutation-ядро (100%). Действие оседает как
`EpisodicEvent(event_type='self_action')`, поэтому recall и такт разглашения
работают без спец-путей (это делимая автобиография, а не приватная рефлексия — из
recall не вырезается). Запись включает флаг `memory.autobiography` (default OFF →
no-op recorder, нулевое изменение поведения).

### Use-case'ы (application)

`ExtractFacts` (`usecases/extract_facts.py`) — Tier 0 шаг «запомнить» после
отправки ответа: просит дешёвый **локальный** Tier-0 провайдер (через `LLMRouter`,
`TaskType.EXTRACT_FACTS`) прочитать последний обмен и вернуть долговечные факты о
собеседнике (имя, предпочтение, человек, решение) как JSON-массив. Каждый пункт
становится `SemanticFact` (confidence 0.7 — дистиллированный, но модельный) и
пишется через шов `FactWriter` (kernel-репозиторий, чей FTS5-триггер индексирует
контент). Опциональный параметр `visibility` (BOB-066 2.6) штампует scope-провенанс
исходного хода на каждый извлечённый факт (`None` = public, дефолт). Best-effort:
провайдер, вернувший прозу вместо JSON, или ошибка не ломают ход диалога.

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

`SqliteMemoryRepo` (`adapters/sqlite_memory_repo.py`) — memory-реализация порта
`MemoryRepo` над connection-kernel'ом (BOB-062.7b). Держит весь memory-SQL и маппит
доменные сущности в строки и обратно: эпизодический архив
(`save_episode`/`save_episode_entity`/`load_episodes`/`recent_episodes`/
`recent_episodes_for`/`episode_by_bob_message_id`), семантические факты и дедуп
(`save_fact`/`load_facts`/`select_active_facts`/`supersede_facts`), консолидация
(`select_consolidatable_episodes`/`save_digest`/`mark_consolidated`), векторная
сторона (`vector_count`/`vector_knn` + on-write эмбеддинг), а также mood/taste
(`set_mood`/`get_mood`/`mood_history`/`set_taste_axis`/`load_taste_axes`). Соединение
не открывает — читает kernel через `.connection`-шов; memory-специфичные миграции
(`_migrate_episodic_*`, `_migrate_semantic_superseded_by`, guarded-additive
`_migrate_episodic_visibility` / `_migrate_semantic_visibility` — nullable-колонка
`visibility` с `NULL`-дефолтом, идемпотентно, не трогает существующую базу) и
FTS5-бэкфилл живут в его `initialize()`. `save_episode`/`save_fact` персистят
`visibility` параметризованно (`?`), а recall-SELECT'ы несут его дальше (см. ниже).
С опциональным `embedder` владеет `MemoryVectorStore`.

`MemoryVectorStore` (`adapters/vector_store.py`) — sqlite-vec сторона памяти:
vec0-таблица `memory_vec` (`float[1024]`) в синхроне с архивом. `load_extension()`
грузит sqlite-vec на соединение (capability соединения), `backfill`/`embed_row`
питают стор (идемпотентно, best-effort — недоступный эмбеддер пропускается, не роняя
запись), `knn(vector, k)` обслуживает семантическую сторону гибрид-recall. KNN-SELECT
несёт `visibility` каждой строки-источника (BOB-066 2.6), так что провенанс доживает
до фильтра такта разглашения и на векторном пути, а не только на FTS5.

`Fts5MemoryRecall` (`adapters/fts_recall.py`) — P0 keyword-recall через SQLite FTS5
`MATCH` с BM25. Покрывает **и** семантические факты, **и** сырой эпизодический
архив (Fix A): старая реплика, из которой факт не извлекали, всё равно всплывает.
Сырой пользовательский текст санитизируется в безопасный FTS5-запрос, так что
операторные символы не вызовут синтаксическую ошибку и не пройдут инъекцией.
Recall-SELECT'ы (и по фактам, и по эпизодам) несут `visibility` каждого хита
(BOB-066 2.6), чтобы провенанс дожил до фильтра такта разглашения выше.

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
- **Visibility-провенанс (`NULL` = public, BOB-066 2.6):** `visibility` — nullable
  additive-колонка на `episodic_log` и `semantic_memory`; `NULL` читается как public,
  так что BOB-051 единая память и все pre-migration-строки остаются surfaceable, а
  owner recall — байт-в-байт (INV-7). Память лишь **пишет** провенанс (по scope хода)
  и **протаскивает** его через оба recall-пути (FTS5 + векторный KNN); собственно
  фильтрацию initiative-surfacing делает такт разглашения в `social`/`application` —
  memory не гейтит.
- **Приватность (локальность):** эмбеддинги и reranking считаются на LOCAL
  Ollama — содержимое памяти никогда не покидает машину.
- **Автобиография от первого лица (BOB-079):** `describe_self_action` формулирует
  всякое самодействие от первого лица («я …»), помечая сбои (`is_anomaly`).
  Присвоение гейтится **реально записанным** эпизодом `self_action` — без записи
  Боб не выдумывает поступок (без конфабуляции); свои действия (`self_action`) не
  смешиваются с внешними (`message`/`reaction_received`). Запись — best-effort и за
  флагом `memory.autobiography`: сбой записи не роняет ни coding-путь, ни приём.
- **Инварианты сущностей:** `ts` всегда timezone-aware, `confidence ∈ [0, 1]` —
  проверяются в `__post_init__`, невалидная запись не может существовать.

### Границы модуля (AaC)

Дисциплина держится path-glob `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ vertical modules):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/`;
- снаружи к `memory` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`);
- `memory/adapters/` читает connection-kernel наружу (`adapter →
  infrastructure/persistence`), а не наоборот — прежнее обратное ребро
  `kernel → bob.memory.entities` устранено в BOB-062.7b (маппинг сущностей замкнут
  внутри `memory/adapters/`).

Внутренний layer-guard модуля (`tests/memory/test_layering.py`) проверяет, что
`memory.usecases` не тянут `adapters/`, а домен — `usecases/` (эти узлы ушли
из-под охвата `tests/application/test_layering.py` при переезде).

## API

<!-- beadloom:track=src/bob/memory/ports.py -->

Модуль `src/bob/memory/ports.py` (порты-протоколы, только интерфейсы):
- `MemoryRepo` — долговечный стор эпизодов/фактов (`save_episode`, `save_fact`,
  `load_episodes`, `recent_episodes`). Реализация —
  `memory.adapters.SqliteMemoryRepo` над connection-kernel'ом.
- `MemoryRecall` — relevance-retrieval (`recall(query, *, k, surface_old=False)`
  → `Sequence[Recalled]`); P0 — FTS5, шов для векторов.
- `Embedder` — `embed(texts)` → `list[list[float]]` (по одному dense-вектору на
  текст, порядок сохраняется; локальный, приватный).
- `Reranker` — `rerank(query, candidates)` → `list[Recalled]` (пере-упорядочивание
  по релевантности, опциональный trim до top-`N`; аддитивно, деградирует мягко).
- `Recalled` = `Mapping[str, object]` — один recalled-элемент (контент + score).
- `SelfActionRecorder` (BOB-079) — узкий порт записи самодействия (`record(action,
  *, sender_id, visibility)`); НЕ расширяет `MemoryRepo` (умышленно узкий).
  Реализации — `memory.adapters.self_action_recorder` (memory-backed → пишет
  `EpisodicEvent(event_type='self_action')` через `save_episode_entity`; и no-op
  для флага OFF).

Фасад `src/bob/memory/__init__.py` re-export'ит `EpisodicEvent`, `SemanticFact`.
Канонический импорт портов — `from bob.memory.ports import MemoryRepo`; транзитный
ports-шим `bob.domain.ports` удалён (BOB-062.8), ~15 потребителей переведены на канон.

Ключевые точки входа:
- `usecases/extract_facts.py`: `ExtractFacts.run(...)` — извлечь факты из обмена.
- `usecases/consolidate_memory.py`: `ConsolidateMemory` — дайджест старых эпизодов.
- `usecases/dedup_facts.py`: `DedupFacts` — merge near-дубликатов фактов.
- `adapters/`: `SqliteMemoryRepo`, `MemoryVectorStore`, `Fts5MemoryRecall`,
  `HybridMemoryRecall`, `OllamaEmbedder`, `OllamaReranker`, фабрики
  `build_embedder` / `build_reranker`; `self_action_recorder` (BOB-079).
- `self_action.py` (чистый домен): `SelfActionKind`, `SelfAction`,
  `describe_self_action` — рендер самодействия от первого лица (BOB-079).

Композиция (создание connection-kernel'а, сборка `SqliteMemoryRepo` над ним, recall'а,
эмбеддера, reranker'а и навешивание extract/consolidate/dedup на heartbeat) — в
композиционном корне (`runtime/`). Долговечная запись в SQLite идёт через
`memory.adapters.SqliteMemoryRepo`, читающий общий `SqliteConnection`
(`infrastructure/persistence/connection.py`) через его `.connection`-шов.

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Сущности: `tests/domain/memory/test_entities.py`.
- Use-case'ы: `tests/application/usecases/test_extract_facts.py`,
  `test_consolidate_memory.py`, `test_consolidation_gaps.py`,
  `test_dedup_facts.py`.
- Persistence-/recall-/embedding-адаптеры (файлы тестов остались под
  `tests/infrastructure/persistence/`): `test_sqlite_repo.py`,
  `test_vector_store.py`, `test_fts_recall.py`,
  `test_hybrid_recall.py`, `test_recall_excludes_superseded.py`,
  `test_sender_attribution.py`, `test_consolidation_repo.py`,
  `test_dedup_repo.py`; visibility-провенанс (BOB-066 2.6) —
  `test_visibility_provenance.py` (запись+миграция `NULL`=public) и
  `test_visibility_recall_seam.py` (реальный sqlite-vec KNN несёт `visibility`:
  owner_private роняется гостю, byte-identical для TRUSTED, `NULL`=public);
  connection-kernel — `test_connection.py`;
  `tests/infrastructure/llm/test_ollama_embedder.py`,
  `test_embedder_factory.py`, `test_ollama_reranker.py`,
  `test_reranker_factory.py` (+ `*_hardening.py`).
- Layer-guard модуля: `tests/memory/test_layering.py`.
- Приёмка и e2e: `tests/test_acceptance_memory.py`,
  `tests/test_acceptance_consolidation.py`, `tests/test_e2e_memory_hybrid.py`.
