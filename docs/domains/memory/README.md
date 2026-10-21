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
  self_action.py  # layer=domain          — SelfActionKind, SelfAction, describe_self_action + coding_terminal_kind (автобиография, BOB-079; два финала сессии — BOB-089)
  work_journal.py # layer=domain          — WorkEpisode + work_episode_event: дистиллированный dev-эпизод, event_type='work' (BOB-087.B1)
  register.py     # layer=domain          — Register (DEV/CASUAL) + may_recall_in_register/filter_by_register: чистый down-weight work-эпизодов в CASUAL (BOB-087.C1)
  register_pipeline.py # layer=domain     — register_ranked/pool_has_work: over-fetch → attenuate → re-sort → truncate («зубы» down-weight'а) + economy-gate (BOB-087.C2)
  digest_provenance.py # layer=domain     — provenance_window/parse_provenance_window: формат «<первый ts>..<последний ts>» окна источников дайджеста (bob-g7t)
  usecases/       # layer=application
    extract_facts.py       — ExtractFacts (Tier 0 «запомнить»: реплика → факты)
    consolidate_memory.py  — ConsolidateMemory (редкий дайджест старых эпизодов, BOB-021)
    dedup_facts.py         — DedupFacts (редкий консервативный merge дубль-фактов, BOB-021)
    classify_work_talk.py  — ClassifyWorkTalk (дешёвый Tier-0 «ход про dev-работу?», BOB-087.C2)
    resolve_register.py    — RegisterResolver (per-turn DEV/CASUAL, BOB-087.C2)
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
`'owner_private'`, либо `None` = public) и `origin_chat_id` / `origin_topic_id` —
ТОЧНЫЙ адрес места, где это было сказано (BOB-090.C2). `SemanticFact` — дистиллированный
долговечный факт: `ts`, `category`, `content`, `confidence` в `[0, 1]` и такой же
`visibility` (провенанс исходного хода). Оба — `frozen, slots` value-object'ы без
I/O; инварианты (timezone-aware `ts`, `confidence ∈ [0, 1]`) проверяются в
`__post_init__`, так что невалидная запись не может существовать в памяти.

`visibility` — провенанс, а не гейт: память **несёт** его вниз до слоя, который
фильтрует (такт разглашения в `social`/`application`, см. инвариант ниже); сама
`memory` его лишь пишет и протаскивает через recall. `None` = public держит
BOB-051 единую память и все legacy-строки нетронутыми, а owner recall остаётся
байт-в-байт (INV-7).

**Точный адрес источника (BOB-090.C2).** `origin_chat_id` / `origin_topic_id` — вторая,
ортогональная ось: `visibility` отвечает «кому это можно», адрес — «где это было сказано».
Записывается в общем шве `HandleMessage._persist`, поэтому его получают ВСЕ пути хода:
ответ, «промолчал», лайк-ход, аутейдж-маркер.

- 🔴 **`NULL` адреса = «источник неизвестен», а НЕ «публично».** Асимметрия с `visibility`
  (где `NULL` сознательно читается как public) намеренна: адрес — утверждение о МЕСТЕ, а
  выдуманное место и есть чинимый дефект (эпизод 3092: Боб «вспомнил», что писал в группу,
  хотя писал в личку). Дефолта и бэкфилла нет. `NULL` в `origin_topic_id` при известном
  `origin_chat_id` означает «топика нет» — личка либо группа без форум-топиков.
- **Флага у записи адреса нет** (единственный механизм эпика без флага): она безвредна,
  потому что адрес не выбирается на recall-пути и в промпт не попадает. Байт-в-байт
  доказан равенством: строки recall для эпизода с адресом и без совпадают как словари, а
  системный промпт композера посимвольно одинаков — и с выключенным, и с включённым
  провенансом C1.
- 🔴 **Читателя в проде у адреса пока нет.** Он пишется на каждом ходу, но ни один
  production-путь его не читает: адрес доставки берётся из конфига известных адресов, а не
  из памяти. Это фундамент под мультигруппы, и говорить о нём надо именно так — «Боб
  хранит место», а не «Боб знает точный адрес».

**Автобиография — самодействия от первого лица (BOB-079).** До BOB-079 лента
несла *слова* Боба (`event_type='message'`) и *чувства* (`'reflection'`), но не
*поступки*: у Боба не было следа собственных действий, поэтому свой же runaway-
инцидент он присвоить не мог. `self_action.py` (чистый домен, I/O-free) вводит
`SelfActionKind` (`StrEnum`: `coding_started/finished/handed_off/aborted/failed/runaway`,
`tool_use`, `tool_failure`), value-object `SelfAction` (`kind`, опц. `target`/
`detail`) и детерминированный рендер `describe_self_action → RenderedSelfAction`
(`content` **всегда от первого лица** — «я …», `tags`, флаг `is_anomaly` для
failed/runaway/tool_failure). Рендер — mutation-ядро (100%). Действие оседает как
`EpisodicEvent(event_type='self_action')`, поэтому recall и такт разглашения
работают без спец-путей (это делимая автобиография, а не приватная рефлексия — из
recall не вырезается). Запись включает флаг `memory.autobiography` (default OFF →
no-op recorder, нулевое изменение поведения).

🔴 **Боб присваивает себе ровно то, что сделал (BOB-089, bob-a6b.8).** У успешного финала
coding-сессии ДВА разных поступка, и у каждого свой вид: на gh-пути Боб действительно открыл
PR (`coding_finished` → «я доделал «X», открыл PR»), а на форк-пути «Create pull request»
жмёт owner, и Боб лишь довёл работу до ветки в своём форке (`coding_handed_off` → «я довёл
«X» до ветки в своём форке и отдал ссылку — PR не открывал»). Выбор делает чистый
`coding_terminal_kind(opened_pr=…)` по ТОМУ ЖЕ признаку `opens_pr`, которым композиция
(`_build_pr_integration`) уже развела адаптер интеграции и терминальную реплику, — второго
источника правды о том, открыт ли PR, нет сознательно. Почему это не косметика: эпизод
автобиографии — источник будущих ответов Боба о себе, поэтому запись о несовершённом
действии стала бы конфабуляцией с провенансом «я это помню, я сам так сделал» — ровно тем
классом, против которого BOB-090.C строил анти-конфабуляционный провенанс.

**Рабочий журнал — дистиллированный dev-эпизод (BOB-087.B1).** `work_journal.py`
(чистый домен, I/O-free) вводит `WorkEpisode` — детальную первого-лица «операторскую»
вспоминку одной coding-сессии Боба («я попросил GUPPI починить X в файле Y; тесты Z
падали; подняли лимит — позеленело»). `work_episode_event(episode, *, ts, sender_id,
visibility)` осаждает её в `EpisodicEvent` на **отдельном** `event_type` `work`
(константа `WORK_EVENT_TYPE`, живёт в общем ядре `bob.kernel.episode_types` и
ре-экспортируется отсюда — слово общее для memory/conversation/personality, bob-abk.32),
а НЕ `self_action`: существующая self-action
озвучка/recall (`recall_has_self_action`, ключ по `self_action`) остаётся байт-в-байт,
а register-aware recall Среза C получает чистый шов по домену `work`. Провенанс (INV-3,
разделение акторства): эпизод помечается тегами `work`/`dev` и маркером актора
`actor:bob` — это операторская вспоминка Боба; атрибуция, где сделал GUPPI/тест, живёт
В контенте от первого лица («я попросил GUPPI…, GUPPI сделал…»). `visibility`/`sender_id`
пробрасываются вызывающим (coding-сессия owner-приватна — `VISIBILITY_OWNER_PRIVATE`).
Сама дистилляция фактов сессии в эпизоды — на стороне `coding` (см. модуль coding,
`work_journal_recorder` + `distill_work_journal`), за флагом `memory.work_journal`
(default OFF → no-op recorder, память байт-в-байт).

**Register-aware recall — регистр разговора красит recall (BOB-087.C).** Register — это
разговорный **режим** хода: Боб сейчас в роли разработчика (`DEV`) или просто болтает
(`CASUAL`). Это ортогонально такту разглашения (`social.disclosure`): такт ключуется по
тому, **кто слушает** (`Trust`), а register — по тому, **в каком режиме** идёт разговор.
Живёт в домене memory, потому что работает чисто над припомненными элементами по
провенансу `work`, отчеканенному рабочим журналом (B1).

- **C1 — чистое ядро (`register.py`).** `Register` (`DEV`/`CASUAL`),
  `may_recall_in_register(*, category, tags, register)` → вес и
  `filter_by_register(recalled, register)` → атенюированный кортеж. В `CASUAL` work-эпизод
  (узнаётся по `category` `work` ИЛИ любому work-тегу, источник — `work_journal._WORK_TAGS`
  + `WORK_EVENT_TYPE`, одно определение провенанса на write- и read-стороне) получает малый
  вес `CASUAL_WORK_WEIGHT` (0.15): его relevance-`score` умножается на этот вес, поэтому он
  редко выигрывает слот, но **никогда не вырезается** (сквозной Боб — сильный матч всё ещё
  может всплыть). В `DEV` — тождество, вход байт-в-байт (`RECALL_WEIGHT_FULL` = 1.0).
  Не-work память всегда полный вес. Чисто и детерминированно (без I/O).
- **C2 — «зубы» rank-пайплайна (`register_pipeline.py`).** Сама атенюация порядок-сохраняюща
  и на display-k пуле выселить work-эпизод не может (нечего поднять снизу).
  `register_ranked(pool, register, *, display_k)` кладёт зубы: над **over-fetched** пулом
  (best-first) он штампует higher-is-better позиционную relevance из ранга recall'а (чтобы
  down-weight не зависел от знака BM25-score), даёт C1 приглушить work-эпизоды, **пере-сортирует**
  по relevance (убыв.) и подрезает до display-k. Так в CASUAL приглушённый work реально
  выпадает из финальных слотов, а не-work поднимается из глубины пула — при этом сквозной
  Боб держится: если не-work не хватает на слоты, сильнейший work всё же всплывает
  (приглушённый, не вырезанный). В DEV — тождество-подрезка (объекты элементов не трогаются).
  `pool_has_work(pool)` — Tier-0 economy-gate: есть ли в пуле хоть один work-эпизод, чтобы
  резолвер пропустил классификатор, когда глушить нечего. Оба — mutation-ядро.
- **C2 — резолвер (`resolve_register.py`).** `RegisterResolver.resolve(event, *,
  pool_has_work)` — memory-зеркало `HandleMessage._surface_audience`: ход = `DEV`, если
  сработал **детерминированный** сигнал (чат — dev-DM `coder.dev_dm_chat_id`, 1:1-канал
  оператора) ИЛИ дешёвый Tier-0 `ClassifyWorkTalk` судит ход как про dev-работу (механизм
  owner'а «прямой вопрос поднимает работу», живой в ЛЮБОМ чате); иначе `CASUAL`. Экономия:
  классификатор зовётся, **только** когда пул реально держит work-эпизоды (`pool_has_work`)
  — глушить нечего → не жжём локальный вызов.
- **C2 — Tier-0 классификатор (`classify_work_talk.py`).** `ClassifyWorkTalk.is_work_talk(text)`
  — один дешёвый локальный вызов (`TaskType.WORK_TALK`), возвращает одно слово, парсится
  КОНСЕРВАТИВНО (`parse_work_talk_verdict`): только точный `work` считается, любое другое
  слово / мусор / сбой модели → `chat` (`False`). Консерватизм — безопасный пол: ложный
  негатив лишь оставляет casual-recall глушащим work (дефолт), никогда не озвучивает
  приватный dev-контекст не тому.

Провенанс: work-эпизоды, которые глушит register-фильтр, приходят из рабочего журнала
(`work_journal`, event_type `work`) — те же теги `work`/`dev`/`actor:bob`.

🔴 **Граница покрытия (известное ограничение, follow-up BOB-087 / bob-abk.17).**
Register-фильтр покрывает **только первичный reply-recall** (`HandleMessage._recall_surfaceable`).
МИМО фильтра идут: grounded-addons, tool-recall (`search_memory` / `recall_memory`) и
проактивный seed — их work-эпизоды в CASUAL НЕ приглушаются. Пока флаг
`memory.register_recall` OFF (дефолт) живой утечки нет (register-recall вообще не собран).
Полное покрытие этих путей — **обязательная предпосылка активации флага** (follow-up
bob-abk.17); активировать флаг до закрытия этой границы нельзя, иначе work-контекст
просочится casual-путями в обход фильтра.

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
`visibility` с `NULL`-дефолтом, идемпотентно, не трогает существующую базу;
`_migrate_episodic_origin` — тем же приёмом добавляет `origin_chat_id` /
`origin_topic_id` (BOB-090.C2), аддитивно и без бэкфилла; `_repair_digest_visibility` —
идемпотентное дозаполнение метки у дайджестов, записанных до фикса, bob-g7t) и
FTS5-бэкфилл живут в его `initialize()`. `save_episode`/`save_fact` персистят
`visibility` параметризованно (`?`), понимают необязательные ключи `origin_chat_id` /
`origin_topic_id`, а recall-SELECT'ы несут `visibility` дальше (см. ниже);
`load_episodes` отдаёт и адрес.
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
🔴 Это один из двух модулей дерева, которые ходят к генеративной модели СВОИМ HTTP, а не
портом провайдера, поэтому шов канона о голосе (BOB-096) его не касается — подробнее и с
названным следствием см. инвариант ниже.
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
- **Свёртка не отмывает приватность (bob-g7t):** дайджест наследует САМУЮ СТРОГУЮ
  метку своих источников (`kernel.visibility.strictest_visibility`) — хоть один
  `owner_private` среди свёрнутых эпизодов, и весь дайджест приватен. До фикса строка
  дайджеста писалась вообще без `visibility`, а отсутствие метки читается как публично,
  поэтому свёртка превращала приватное в общедоступное навсегда. Метку дайджестов,
  записанных ДО фикса, идемпотентно дозаполняет `_repair_digest_visibility`: она
  восстанавливает её ПО ИСТОЧНИКАМ (ts-окно провенанса, `digest_provenance.py`), а не
  «оставить как есть» и не «пометить всё приватным» — публичная память комнаты остаётся
  публичной. Неразрешимый провенанс трактуется строго (INV-8: сомнение придерживает).
  Тот же класс дыры для оси РЕГИСТРА закрыт раньше, в BOB-087.C8.
- **Адрес источника: `NULL` = «не знаю» (BOB-090.C2).** `origin_chat_id` /
  `origin_topic_id` пишутся на всех путях хода, миграция аддитивна и без бэкфилла, поэтому
  все старые записи остаются с `NULL`. Читать `NULL` как «публично» нельзя: у этой оси
  умолчания нет, отсутствие адреса означает именно неизвестность. На recall-строку адрес не
  выбирается — дверь откроется вместе со своим потребителем.
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
- **Рабочий журнал — отдельный event_type (BOB-087.B1):** дистиллированный dev-эпизод
  оседает как `EpisodicEvent(event_type='work')` (НЕ `self_action`), поэтому self-action
  озвучка/recall остаётся байт-в-байт; провенанс — теги `work`/`dev` + `actor:bob` (это
  операторская вспоминка Боба, атрибуция GUPPI/теста живёт в контенте от первого лица).
  Осаждение — best-effort и за флагом `memory.work_journal` (default OFF → память
  байт-в-байт как сегодня).
- **Register-aware recall — down-weight, не силос (BOB-087.C):** в `CASUAL` work-эпизод
  лишь приглушается (`score × CASUAL_WORK_WEIGHT` = 0.15), но НИКОГДА не вырезается
  (сквозной Боб — сильный матч всплывает приглушённым); в `DEV` recall байт-в-байт.
  «Зубы» дают выселение (over-fetch → attenuate → re-sort → truncate), а `pool_has_work`
  — economy-gate (нет work → не зовём Tier-0). Провенанс — теги `work`/`dev`/`actor:bob`
  из рабочего журнала. За флагом `memory.register_recall` (default OFF → резолвер `None`
  → recall байт-в-байт, over-fetch выключен, INV-5). Граница: покрыт только первичный
  reply-recall; grounded-addons / tool-recall / проактивный seed идут мимо (follow-up
  bob-abk.17, обязателен до активации флага).
- **🔴 Запись, рождённая моделью, несёт канон о голосе (BOB-096).** Всё, что ложится в
  архив от лица Боба, завтра вернётся к модели её собственным few-shot, поэтому запрет отыгрывать
  GUPPI доезжает до каждой такой двери: рефлексия и её переоценка, дайджест консолидации,
  дневник работы, выжимка фактов, прочтение реакции. Не копипастой директивы по
  use-case'ам — ни один из них не правился, — а швом в тех местах, где payload уходит
  модели портом провайдера (`LLMRouter._build_messages` и петля инструментов). Форма
  разная: прозаической двери едет полная директива, машинной (JSON фактов) — та же суть
  клаузой о записи, иначе сломался бы контракт ответа. Автобиография (`self_action`) —
  единственная из этих дверей БЕЗ модели: формулировку от первого лица строит
  детерминированный `describe_self_action`, поэтому канон ей обеспечен конструкцией, а не
  промптом. При отвале облака двери-голоса (рефлексия, дайджест, дневник работы) не
  рождаются вовсе, а выжимка фактов продолжает работать на локальном дублёре: её вывод
  сохраняется, но голосом Боба не звучит.
- **🔴 Предел этого шва, названный прямо.** Шов стоит на путях, идущих ЧЕРЕЗ ПОРТ
  провайдера. `OllamaReranker` (`adapters/ollama_reranker.py`) собирает chat-payload сам и
  POST'ит его в `/v1/chat/completions` мимо обеих точек. Канон ему не нужен по свойству
  вывода (число релевантности расходуется в этом же ходе и никуда не сохраняется), то есть
  дефекта в поведении нет — но и архитектурный гард такую форму не видит: модуль, который
  сочинит «Ты Боб…» и отправит это своим POST'ом, все гарды пройдёт. Второй живой
  прецедент той же формы — `capabilities/adapters/web_search_qwen.py`.
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
- `MemoryRecall` и `Recalled` живут в shared kernel (`src/bob/kernel/ports.py`,
  `src/bob/kernel/episode_types.py`, BOB-113): их читают модули ниже `memory` по
  runtime-порядку (`Recalled` — `conversation` и `personality`, `MemoryRecall` —
  `personality`). Реализации порта (`Fts5MemoryRecall`, `HybridMemoryRecall`,
  `CasualFloorRecall`) остаются в `memory/adapters/`. `MemoryRecall` —
  relevance-retrieval (`recall(query, *, k, surface_old=False)` → `Sequence[Recalled]`);
  P0 — FTS5, шов для векторов. `memory/ports.py` импортирует `Recalled` из ядра только
  для аннотаций и не ре-экспортирует его.
- `Embedder` — `embed(texts)` → `list[list[float]]` (по одному dense-вектору на
  текст, порядок сохраняется; локальный, приватный).
- `Reranker` — `rerank(query, candidates)` → `list[Recalled]` (пере-упорядочивание
  по релевантности, опциональный trim до top-`N`; аддитивно, деградирует мягко).
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
- `work_journal.py` (чистый домен): `WorkEpisode`, `work_episode_event`,
  `WORK_EVENT_TYPE` (ре-экспорт из `bob.kernel.episode_types` — общий словарь трёх
  контекстов, bob-abk.32) — дистиллированный dev-эпизод, event_type `work` (BOB-087.B1).
- `register.py` (чистый домен): `Register` (DEV/CASUAL), `may_recall_in_register`,
  `filter_by_register`, `RECALL_WEIGHT_FULL`, `CASUAL_WORK_WEIGHT` — down-weight
  work-эпизодов в CASUAL (BOB-087.C1).
- `register_pipeline.py` (чистый домен): `register_ranked(pool, register, *, display_k)`,
  `pool_has_work(pool)` — rank-пайплайн («зубы») + economy-gate (BOB-087.C2).
- `digest_provenance.py` (чистый домен): `provenance_window(first_ts, last_ts)`,
  `parse_provenance_window(value)` — формат окна источников дайджеста; читается починкой
  метки приватности, поэтому писатель и читатель знают одно определение (bob-g7t).
- `usecases/resolve_register.py`: `RegisterResolver.resolve(event, *, pool_has_work)` —
  per-turn DEV/CASUAL (детерминированный dev-DM сигнал + Tier-0 судья); `WorkTalkClassifier`
  — Protocol-шов классификатора (BOB-087.C2).
- `usecases/classify_work_talk.py`: `ClassifyWorkTalk.is_work_talk(text)`,
  `parse_work_talk_verdict(label)` — дешёвый Tier-0 «ход про dev-работу?» (BOB-087.C2).

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
  адрес источника (BOB-090.C2) — `test_episode_origin.py` (guarded ALTER идемпотентен,
  старые строки остаются с `NULL`, строка recall не меняется);
  connection-kernel — `test_connection.py`;
  `tests/infrastructure/llm/test_ollama_embedder.py`,
  `test_embedder_factory.py`, `test_ollama_reranker.py`,
  `test_reranker_factory.py` (+ `*_hardening.py`).
- Layer-guard модуля: `tests/memory/test_layering.py`.
- Приёмка и e2e: `tests/test_acceptance_memory.py`,
  `tests/test_acceptance_consolidation.py`, `tests/test_e2e_memory_hybrid.py`.
