<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Архитектура Боба

Боб — это единый Python-процесс, который держит **два aiogram-бота** (Боб и
GUPPI), локальный и облачный LLM за провайдер-агностичным роутером, память на
SQLite и ядро личности (Higher Mind). Пользователь пишет в приватную
Telegram-supergroup: Боб живёт в своём форум-топике и отвечает «печатает…»-
индикатором и форматированным rich-сообщением — с учётом настроения, вкусов и
памяти — а GUPPI работает
привратником и админом в General. Оба бота — админы группы, поэтому групповое
сообщение может прийти на обоих; их поллит один `MultiBotGateway`, дедуплицируя
по `(chat_id, message_id)`. Система переживает рестарты процесса и машины. Доступ
закрыт авторизацией (owner + allowlist + scope по чату), отказ неавторизованному
**виден** (GUPPI отвечает «не авторизован», пайплайн Боба не запускается), петля
устойчива к транзиентным сетевым сбоям, а навыки Боба исполняются GUPPI через
стабильный Capability-шов. На каждый входящий Боб **понимает сообщение в контексте**
и выбирает — как человек — ответить словами, поставить эмодзи-реакцию или промолчать
(семантическое суждение, BOB-049, вместо лестницы эвристик). А если связь с моделью
рвётся на существенном шаге — это **полный Боб или честный GUPPI-нотис**: Боб не шлёт
деградированный полуответ, GUPPI сообщает о проблеме со связью. Боб не только
реактивен: проактивный drive-движок
(BOB-010) иногда пишет первым по «порыву» из внутреннего состояния, под
governance-потолками и owner-командами `/quiet`/`/wake`.

Этот документ описывает реальную, поставленную систему: слои, мульти-бот gateway и
GUPPI-идентичность, поток обработки сообщения, LLM-тиры с редакцией приватного
контекста, память, ядро личности, Genesis и фоновый heartbeat, а также батч поверх
P0 — Telegram-транспорт на aiogram (typing-индикатор + Rich Messages),
авторизацию, резилентность тиков и Capability-шов. Подробности по каждому слою — в
отдельных документах:

- [`domains/domain/README.md`](domains/domain/README.md) — чистый домен (личность и память).
- [`domains/application/README.md`](domains/application/README.md) — GUPPI: рантайм, use-cases, роутер.
- [`domains/infrastructure/README.md`](domains/infrastructure/README.md) — адаптеры (Telegram, LLM, SQLite, конфигурация).

## Слои (DDD + гексагональная архитектура)

Зависимости направлены только внутрь: `infrastructure → application → domain`.
Домен не импортирует ничего наружу, приложение зависит от домена через
порты-протоколы и не импортирует инфраструктуру, композиция живёт только в
пакете `runtime/` (composition root; `app.py` — тонкий re-export shim над ним).

```
src/bob/
  domain/            # ЧИСТО: без I/O, LLM и Telegram. Только логика и модели.
                     #   личность (Mood, Disposition, TasteEngine, Negotiation, SOUL,
                     #   voice, mood_taste, fascination, phantom_evolution, expression,
                     #   семейство reaction, reflection, absence + порты/use-case'ы/
                     #   адаптеры) переехала в вертикальный модуль `src/bob/personality/`
                     #   (BOB-062.6a), а ведение хода (addressivity, conversation_floor,
                     #   brevity, engagement, zone_classifier, судьи response/volatility,
                     #   interim, анти-тик conversation) — в `src/bob/conversation/`
                     #   (BOB-062.6a); прежний `domain/personality/` расформирован;
                     #   `from bob.domain.ports import MessageReactor` работает как раньше
                     #   память (EpisodicEvent, SemanticFact + порты/логика/адаптеры)
                     #   переехала в вертикальный модуль `src/bob/memory/` (BOB-062.2);
                     #   `from bob.domain.ports import MemoryRepo` работает как раньше
                     #   самоинтроспекция (PrivacyGuard, code_history) и разбор
                     #   inline-mermaid (mermaid_blocks) переехали в вертикальный
                     #   модуль `src/bob/capabilities/` (BOB-062.4)
                     #   проактивность (UrgeModel, SocialEnergy, Governance,
                     #   ProactiveDecider, ProactivityState + goals + self_improvement,
                     #   порты/логика/адаптеры) переехала в вертикальный модуль
                     #   `src/bob/proactivity/` (BOB-062.3); `self_improvement` забран
                     #   из personality; `from bob.domain.ports import ProactivityStore`
                     #   работает как раньше
    ports/           # порты-протоколы (пакет, разбит из ports.py в BOB-065).
                     #   __init__.py — re-export shim: `from bob.domain.ports import X`
                     #     резолвит все 51 публичный символ без изменений импортов.
                     #   kernel.py       — Clock, DomainEvent, EventBus, EventHandler,
                     #                     JsonValue, LLMMessage, LLMProvider
                     #   memory-порты (MemoryRepo, MemoryRecall, Recalled, Embedder,
                     #     Reranker) переехали в `memory/ports.py` (вертикальный модуль,
                     #     BOB-062.2); `ports/__init__.py` их re-export'ит
                     #   social-порты (SoulStore, AllowlistStore, FirstImpressionStore,
                     #     RelationshipStore, SulkStore, PrivilegeJudge) переехали в
                     #     `social/ports.py` (вертикальный модуль, BOB-062.5);
                     #     `ports/__init__.py` их re-export'ит (тонкий шим)
                     #   proactivity-порты (ProactivityStore, GoalStore, Planner,
                     #     SelfImprovementStore, PatternDetector) переехали в
                     #     `proactivity/ports.py` (вертикальный модуль, BOB-062.3);
                     #     `ports/__init__.py` их re-export'ит
                     #   conversation-порты (ConversationFloorStore, CloserLog,
                     #     ZoneClassifier) переехали в `conversation/ports.py`
                     #     (вертикальный модуль, BOB-062.6a); `ports/__init__.py` их
                     #     re-export'ит (тонкий шим)
                     #   personality-порты (MessageReactor, ReflectionReader,
                     #     FascinationStore, NotableReactionStore) переехали в
                     #     `personality/ports.py` (вертикальный модуль, BOB-062.6a);
                     #     `ports/__init__.py` их re-export'ит (ZoneClassifier — теперь
                     #     conversation-порт, решение хода; Sulk/First/Relationship —
                     #     `social/ports.py`, BOB-062.5)
                     #   capability-порты (Capability, ToolCallingProvider,
                     #     RepoIntrospector, DiagramRenderer/Sink/Result, WebSearchProvider,
                     #     UrlReader + value-object'ы) переехали в `capabilities/ports.py`
                     #     (вертикальный модуль, BOB-062.4); `ports/__init__.py` их
                     #     re-export'ит (шим 18 портов), `from bob.domain.ports import
                     #     Capability` работает как раньше
                     #   coding-порты (ClaudeCodeRunner, Worktree, CodingSessionStore,
                     #     PullRequestOpener) переехали в `coding/ports.py` (вертикальный
                     #     модуль, BOB-062.1); `ports/__init__.py` их re-export'ит, так что
                     #     `from bob.domain.ports import ClaudeCodeRunner` работает как раньше
  application/       # GUPPI: use-cases + оркестрация. Зависит от domain через порты.
    runtime/         # AgentRuntime (жизненный цикл), AsyncEventBus, события, periodic, retry
    router/          # LLMRouter: классификация задачи → Tier + правило редакции
    usecases/        # HandleMessage (тонкий оркестратор + коллабораторы EssentialRunner/
                     #   PreComposeGate; прочие — по вертикалям, срез .6b), RunGenesis,
                     #   UpdateMoodFromText, heartbeat-тики,
                     #   ApplyReflection + HeuristicReflectionParser (само-эволюция),
                     #   EvolveFascination, EvolvePhantoms (эмоциональная глубина),
                     #   ReappraiseReflection (реаппрайзал, BOB-033)
                     #   проактивность-use-case'ы (ProactivityEngine, ProactiveTick,
                     #   RecordOwnerActivity, plan/pursue goals, detect-patterns/
                     #   announce-rules, self_improvement_sources) переехали в
                     #   `proactivity/usecases/` (вертикальный модуль, BOB-062.3)
                     #   social-use-case'ы (Authorizer, SenderPerception/
                     #   ReactorPerception, PermissionFlow/PermissionExecutor,
                     #   First/Relationship/Sulk-Tracker, RunGenesis) переехали в
                     #   `social/usecases/` (вертикальный модуль, BOB-062.5);
                     #   privileged_fulfiller ОСТАЁТСЯ здесь (cross-domain оркестратор)
                     #   capability-use-case'ы (CapabilityRegistry, ToolLoop, навыки
                     #   recall/search_memory, inspect_architecture, read_code, list_work,
                     #   code_rationale, render_diagram, web_search, read_url,
                     #   progress_announcer) переехали в `capabilities/usecases/`
                     #   (вертикальный модуль, BOB-062.4)
  infrastructure/    # Адаптеры портов (наружу).
    telegram/        # MultiBotGateway: BotRegistry (Боб+GUPPI), кросс-бот дедуп,
                     #   центральный роутер по содержимому; GuppiHandler (reject +
                     #   owner-команды + /quiet,/wake); TelegramGateway (aiogram):
                     #   long-polling + authz-гейт, typing-индикатор + rich-финал
                     #   (Вариант A), Rich Messages, thread-reply; rich.py: markdown↔RichMessage
    llm/             # OpenAICompatProvider (Tier 0/1, + tool-calling) + фабрика;
                     #   QwenWebSearchProvider (web_search) переехал в
                     #   `capabilities/adapters/web_search_qwen.py` (BOB-062.4);
                     #   OllamaEmbedder/OllamaReranker + их фабрики переехали в
                     #   `memory/adapters/` (вертикальный модуль, BOB-062.2)
                     #   web-читатель (HttpUrlReader за 🔴 SSRF-щитом), локальный
                     #   mermaid-рендерер (SubprocessMmdcRenderer) и read-only
                     #   интроспектор (SubprocessRepoIntrospector) переехали в
                     #   `capabilities/adapters/{web,diagrams,introspection}/`
                     #   (вертикальный модуль, BOB-062.4)
    persistence/     # connection-kernel персистентности (BOB-062.7b): connection.py
                     #   (SqliteConnection — чистое I/O: WAL/foreign_keys/sqlite-vec/
                     #   executescript(schema.sql)/миграции/kv) + единая schema.sql.
                     #   Выставляет .connection-шов, которым кормятся все ~13 сторов
                     #   всех модулей + memory-репозиторий. Facade (__init__.py) очищен:
                     #   экспортит ТОЛЬКО SqliteConnection (был стейл god-facade).
                     #   memory-репозиторий (SqliteMemoryRepo) + MemoryVectorStore +
                     #   recall-адаптеры (Fts5/HybridMemoryRecall) уехали в
                     #   `memory/adapters/` (BOB-062.7b/.2); social-сторы (KvAllowlist/
                     #   SoulStore, First/Relationship/Sulk/PermissionRequest-Store) — в
                     #   `social/adapters/` (.5); proactivity-сторы — в
                     #   `proactivity/adapters/` (.3). Все читают kernel через .connection
    config/          # ConfigLoader (defaults → YAML → env)
  coding/            # 🔴 ВЕРТИКАЛЬНЫЙ модуль «Боб пишет код» (BOB-062.1): вся способность
                     #   в одном месте, а не размазана по слоям. Внутренняя раскладка:
                     #     ports.py + логика (state, entities, naming, narrate, intent,
                     #       session_voice) — layer=domain;
                     #     usecases/ (coding_assistant, coding_context, classify_coding_intent,
                     #       coding_intent_router) — layer=application;
                     #     adapters/ (claude_runner, git_worktree, gh_pr, session_store,
                     #       indicator, _branch, _exec) — layer=infrastructure.
                     #   Граница «снаружи — только через ports/фасад» держится path-glob
                     #   forbid_import-правилами (.beadloom/_graph/rules.yml). См. SPEC:
                     #   docs/domains/coding/README.md
  memory/            # 🔴 ВЕРТИКАЛЬНЫЙ модуль «Боб помнит» (BOB-062.2): бизнес-логика
                     #   памяти в одном месте, а не размазана по слоям. Раскладка:
                     #     ports.py + entities (EpisodicEvent, SemanticFact) — layer=domain;
                     #     usecases/ (extract_facts, consolidate_memory, dedup_facts)
                     #       — layer=application;
                     #     adapters/ (sqlite_memory_repo, vector_store, fts_recall,
                     #       hybrid_recall, ollama_embedder, ollama_reranker + фабрики)
                     #       — layer=infrastructure.
                     #   🔴 kernel-split завершён (BOB-062.7b, долг варианта C закрыт):
                     #   SqliteMemoryRepo + MemoryVectorStore уехали в memory/adapters/,
                     #   читают connection-kernel (infrastructure/persistence/connection.py)
                     #   через .connection-шов; ребро kernel→bob.memory.entities устранено.
                     #   См. SPEC: docs/domains/memory/README.md
  capabilities/      # 🔴 ВЕРТИКАЛЬНЫЙ модуль «инструменты Боба» (BOB-062.4): весь
                     #   capability-шов в одном месте, а не размазан по слоям. Раскладка:
                     #     ports.py + чистые diagrams/ (mermaid_blocks) +
                     #       introspection/ (PrivacyGuard, code_history) — layer=domain;
                     #     usecases/ (CapabilityRegistry, ToolLoop, progress_announcer +
                     #       навыки recall/search_memory, read_code/url, web_search,
                     #       render_diagram, inspect_architecture, list_work,
                     #       code_rationale) — layer=application;
                     #     adapters/{web,diagrams,introspection} + web_search_qwen.py —
                     #       layer=infrastructure.
                     #   18 портов re-export'ятся из bob.domain.ports (шим).
                     #   Граница «снаружи — только через ports/фасад» держится
                     #   explicit-path forbid_import-правилами, СГЕНЕРИРОВАННЫМИ
                     #   scripts/gen_boundary_rules.py. См. SPEC:
                     #   docs/domains/capabilities/README.md
  social/            # 🔴 ВЕРТИКАЛЬНЫЙ модуль «Боб различает людей» (BOB-062.5): социальная
                     #   идентичность + авторизация + genesis в одном месте. Раскладка:
                     #     ports.py + чистый домен (interlocutor, first_impression,
                     #       relationship, sulk) + permission/ (entities, intent, privilege,
                     #       state) — layer=domain;
                     #     usecases/ (Authorizer, sender/reactor_perception, permission_flow/
                     #       execution, first_impression/relationship/sulk_sources,
                     #       run_genesis) — layer=application;
                     #     adapters/ (allowlist/soul/first_impression/relationship/sulk/
                     #       permission_request-store, privilege_judge) — layer=infrastructure.
                     #   🔴 interlocutor переехал из personality (цикл personality↔social
                     #   разорван: voice.py читает kind.value, не импортит InterlocutorKind);
                     #   social→personality однонаправленно (relationship→negotiation.Stance).
                     #   privileged_fulfiller ОСТАЁТСЯ в application (cross-domain оркестратор).
                     #   connection-kernel персистентности расщеплён в BOB-062.7b (долг
                     #   варианта C закрыт); social-сторы читают его .connection-шов.
                     #   Границы — explicit-path forbid_import-правилами,
                     #   СГЕНЕРИРОВАННЫМИ scripts/gen_boundary_rules.py. См. SPEC:
                     #   docs/domains/social/README.md
  personality/       # 🔴 ВЕРТИКАЛЬНЫЙ модуль «кто Боб есть» (BOB-062.6a): стабильное
                     #   ядро характера в одном месте. Раскладка:
                     #     ports.py + чистый домен (mood, disposition, taste(+evolution),
                     #       mood_taste, negotiation, fascination, phantom_evolution,
                     #       expression(+🔴 Verbosity/EngagementLevel), voice, language,
                     #       profanity, семейство reaction*, reflection, soul, absence)
                     #       — layer=domain;
                     #     usecases/ (UpdateMoodFromText, ApplyReflection, Reappraise-
                     #       Reflection, HeuristicReflectionParser, Evolve Fascination/
                     #       Phantoms, fascination_sources) — layer=application;
                     #     adapters/ (LlmReactionJudge, Sqlite Fascination/Kv Notable-
                     #       Reaction-Store) — layer=infrastructure.
                     #   🔴 стабильное ядро: 0 runtime-зависимостей на conversation/
                     #   social; Verbosity/EngagementLevel — вокабуляр выражения здесь
                     #   (цикл voice↔brevity/engagement разорван, .1); perceive_reaction
                     #   ОСТАЁТСЯ в application (cross-domain). См. SPEC:
                     #   docs/domains/personality/README.md
  conversation/      # 🔴 ВЕРТИКАЛЬНЫЙ модуль «как ведётся ход» (BOB-062.6a): ведение
                     #   разговора в одном месте. Раскладка:
                     #     ports.py (ConversationFloorStore, CloserLog, ZoneClassifier)
                     #       + чистый домен (addressivity, conversation_floor, brevity,
                     #       engagement, zone_classifier, анти-тик conversation, судьи
                     #       response/volatility, interim_line) — layer=domain;
                     #     usecases/ (DecideResponse) — layer=application;
                     #     adapters/ (Llm Response/Volatility/InterimLine, Sqlite
                     #       Conversation-Floor/Closer-Log-Store) — layer=infrastructure.
                     #   🔴 conversation→personality однонаправленно (читает personality-
                     #   VO, brevity/engagement возвращают Verbosity/EngagementLevel);
                     #   zone_classifier здесь (классификатор хода). Интеграция методов в
                     #   handle_message — срез .6b. См. SPEC:
                     #   docs/domains/conversation/README.md
  runtime/           # composition root + entrypoint (BOB-062.7a; переехало из app.py):
                     #   composition.py (build_application + Application), main.py (main/
                     #   entrypoint), clock.py (SystemClock), config.py (ридеры + _REPO_ROOT),
                     #   wiring/ (_build_* фабрики по домам). Единственный слой, зовущий все
                     #   слои и все модули; модули НЕ импортят runtime.
                     #   🔴 Отличать от application/runtime/ (async-примитивы, НЕ composition root).
                     #   Инлайн-адаптеры вернулись в свои дома: infrastructure/telegram/
                     #   (aiogram_adapter, outage_notifier), social/adapters/ (permission-каналы,
                     #   privilege-judge, soul_loader), coding/adapters/ (owner_notifier).
                     #   См. SPEC: docs/services/runtime.md
  app.py             # тонкий re-export shim над runtime (launcher ./bob + тесты держатся)
```

Граница слоёв — не только соглашение: тест `tests/application/test_layering.py`
сканирует каждый файл слоя `application` и падает на любом импорте
`bob.infrastructure` (включая импорты под `TYPE_CHECKING`). Событие
`MessageReceived` и порт `SoulStore` принадлежат слоям, которыми владеет
приложение и домен, поэтому use-cases ни прямо, ни косвенно не зависят от
инфраструктуры.

Границы вертикальных модулей (`coding` / `memory` / `proactivity` / `capabilities` /
`social` / `personality` / `conversation`) держат `forbid_import`-правила в
`.beadloom/_graph/rules.yml`. Их **генерирует**
`scripts/gen_boundary_rules.py` из `module-vertical`-узлов графа в marker-регион
`# BEGIN/END generated boundary rules` (рукописные rationale-блоки вне маркеров не
трогает); режим `--check` — CI-gate идемпотентности. Правила на **explicit paths**
(`src/bob/<module>/…`), а не char-class'ы: прежняя схема `src/bob/[adimp]*` не
различала `capabilities` и `coding` (оба на `c`, fnmatch ключуется по первому
символу). На каждый модуль генерируются `usecases-no-adapters`,
`internals-no-usecases`, `internals-no-adapters`, `usecases-no-infra`,
`no-composition-root` + inward-границы от чужих бизнес-модулей; координационные слои
(`application` / `infrastructure` / `runtime`-пакет composition root) из inward-модели исключены
намеренно — они по определению собирают и зовут usecases/adapters модулей.

## Мульти-бот gateway и GUPPI-идентичность (BOB-003)

Один процесс держит **два бота** — Боба (персона) и GUPPI (привратник/админ) — и
поллит обоих одним проходом. Шов forward-compatible: добавление будущей реплики
(Bender, Bill, … — Bobiverse) = ещё одна регистрация бота, без переписывания
композиции. Весь мульти-бот код — чистый транспорт в `infrastructure/telegram`
(`multibot.py`, `guppi.py`); домен и приложение не тронуты.

### BotRegistry и единый поллинг

- **`BotRegistry`** регистрирует бота как `{identity, bot, scope}`. Регистрируются
  Боб (scope — его топик) и GUPPI (scope — General, `topic_id = None`); реплику
  добавляет один вызов `register`.
- **`MultiBotGateway.poll_once()`** поллит каждого зарегистрированного бота по
  очереди. Под каждого бота создаётся свой внутренний `TelegramGateway` — он делает
  приём/нормализацию апдейтов и отправку ответа (typing-индикатор + rich-финал);
  у Боба внутренний gateway приколочен к его топику (`reply_thread_id`).
- **Изоляция ботов.** Падение или реконнект одного бота (`OSError`/`RuntimeError`/
  `TimeoutError` при `get_updates`) логируется и пропускается — другой бот
  продолжает работать. Опирается на резилентность BOB-002.
- **Кросс-бот дедуп.** Оба бота — админы группы, поэтому одно групповое сообщение
  приходит на оба потока апдейтов. Дедуп идёт по `(chat_id, message_id)` —
  сообщение обрабатывается **один раз** независимо от того, какой бот его доставил.
  Это отдельный ключ от per-бот дедупа по `update_id`, который делает внутренний
  `TelegramGateway`. **Слот дедупа фиксируется только после того, как копия реально
  обработана** (BOB-005): не-маршрутизируемая копия (см. ниже) слот не занимает.

### Центральный роутер (по содержимому, а не по боту-доставщику)

Решение принимается по **содержимому** сообщения (чат + тред топика + авторизация),
а **не** по identity доставившего бота. Это важно (BOB-005): копии одного сообщения
**не взаимозаменяемы** — Telegram может доставить копию General-scoped бота-GUPPI для
сообщения в топике Боба **без** `message_thread_id`, тогда как копия бота-Боба несёт
тред. Поэтому `route(update, identity)` классифицирует каждую копию по содержимому:

1. **Топик Боба + авторизован** → публикуется один `MessageReceived` в шину
   (пайплайн Боба); ответ уходит ботом-Бобом в его тред.
2. **Топик Боба + НЕ авторизован** → `GuppiHandler.reject` шлёт **видимый** текст
   `⛔ Пользователь не авторизован` в тот же чат и тред; **пайплайн Боба не
   запускается**.
3. **General + owner-команда** (`/authorize`, `/deauthorize`, `/status`) →
   обрабатывает `GuppiHandler.handle_general_command` (только owner).
4. **Остальное** (другие топики, чужие чаты, DM от незнакомца, не-owner команда, а
   также не-маршрутизируемая дубль-копия без треда) → **молча игнорируется** (без
   раскрытия ботов).

Так сообщение в топике Боба попадает в его пайплайн **ровно один раз**, какой бы бот
ни доставил первую копию: если первой пришла копия GUPPI без треда (она ничему не
соответствует — `_RouteOutcome.UNROUTABLE` — и слот дедупа не занимает), то копия
бота-Боба с тредом всё равно маршрутизируется. `identity` остаётся ключом, на котором
диспатчатся будущие реплики, но **решение о хендлере от него не зависит**.

### GUPPI-идентичность

`GuppiHandler` (`infrastructure/telegram/guppi.py`) владеет **только** поведением
GUPPI и шлёт ответы своим инъецированным ботом (никогда ботом-Бобом):

- **Видимый reject.** На неавторизованного в топике Боба GUPPI отвечает
  `GUPPI_REJECT_TEXT` в тот же чат+тред. Роутер вызывает reject только для
  разрешённой группы, поэтому DM незнакомца reject **никогда не триггерит** —
  безопасность через scope.
- **Owner-команды в General.** `/authorize <user_id>` и `/deauthorize <user_id>`
  мутируют allowlist через общий `Authorizer` (без дублирования authz), `/status`
  отвечает короткой строкой-whoami. Команда не от owner, не-команда или сообщение
  не из General — **молча игнорируются** (`False`, без раскрытия). Невалидный
  аргумент `<user_id>` даёт подсказку по использованию, а не грант.
- GUPPI-привратник собирается только когда GUPPI зарегистрирован **и** подан
  `Authorizer`; иначе GUPPI-хуки деградируют в молчаливые дропы (обратная
  совместимость с одно-ботовой сборкой).

### Сигналы адресности и идентичность Боба (BOB-023)

При нормализации апдейта внутренний `TelegramGateway` извлекает из aiogram-сообщения
**сигналы адресности** и кладёт их в `MessageReceived` (см. «Поток обработки» и
«Адресность»): `reply_to_sender_id` — id автора сообщения, на которое сделан реплай
(`reply_to_message.from_user.id`; `None`, если это не реплай). **Форум-гард (BOB-027):**
в форум-топике каждое сообщение неявно «реплаит» корень топика
(`reply_to_message.message_id == message_thread_id`, создан owner'ом) — это не настоящий
реплай и игнорируется (`None`), иначе адресность читала бы весь топик как «к другому».
`mentions_bob` —
упомянут ли бот Боба (`_mentions_bob` сканит `entities`: `mention` сверяется с
`@username` Боба, `text_mention` — с его `user_id`).

Чтобы отличить упоминание Боба от упоминания другого, gateway знает собственную
идентичность бота. `BotIdentitySignals(user_id, username)` резолвится один раз на
старте: `MultiBotGateway.resolve_bot_identities()` зовёт `get_me` бота Боба и
прокидывает результат через `set_bob_identity`; провязано в `app.py` при запуске.
До резолва (а также во внутреннем gateway GUPPI, у которого идентичности нет)
`bob_user_id()` возвращает `None` — graceful degrade: `mentions_bob` остаётся `False`,
reply-на-Боба не срабатывает, но @mention по `username` всё равно ловится после
резолва. Сам id читается лениво политикой адресности через шов
`multibot.bob_user_id`.

**Устойчивый старт: `get_me` переживает флап сети (BOB-059).** Резолв идентичности
идёт в сети, а сеть на старте может моргнуть. Раньше блип поднимал
`aiogram.exceptions.TelegramNetworkError`, которого не было в `except` — исключение
пробивало `resolve_bot_identities`, роняло весь запуск, поллинг не стартовал, и Боб
с GUPPI оставались немыми. Теперь вызов `get_me` обёрнут в `call_with_retry`
(тот же примитив, что и на существенных шагах хода, BOB-049): ограниченное число
попыток с backoff через инъецируемый sleep, seam в конструкторе —
`identity_retry_attempts` (умолчание `_DEFAULT_IDENTITY_RETRY_ATTEMPTS = 3`),
`identity_retry_backoff_seconds` (`1.0`) и `identity_retry_sleep` (живой
`asyncio.sleep`; тесты инъецируют фейковый для детерминизма). Поведение по исходам:

- **Транзиентный блип** переживается ретраем — идентичность всё-таки резолвится,
  успешный путь не изменён (на живом `get_me` ретрай возвращает с первой попытки,
  без sleep, `set_bob_identity` зовётся как раньше).
- **Устойчивый сбой** (в том числе `TelegramNetworkError`, теперь добавленный в
  `except (OSError, RuntimeError, TimeoutError, TelegramNetworkError)`) на всех
  попытках → `logger.warning` + `return`: **грациозная деградация**. Запуск
  **продолжается**, поллинг стартует, Боб слушает — идентичность просто останется
  неразрешённой (reply-на-Боба деградирует, @mention по `username` работает) и
  дорезолвится позже.
- **Не-сетевой сбой** (программная ошибка — `ValueError` и т.п.) намеренно **не**
  проглатывается: `call_with_retry` перевыбрасывает последнее исключение, а `except`
  ловит только сетевые типы, поэтому баг всплывает, а не тонет.

Это распространяет резилентность старта на резолв идентичности: поллинг (`poll_once`)
был устойчив к сетевым сбоям уже давно (изоляция ботов, BOB-002), а теперь и стартовый
`get_me` следует принципу ROADMAP «полный Боб / устойчивость» — транзиентный сбой
переживается, устойчивый деградирует мягко, а не роняет процесс.

### Topic-scope Боба

Боб обрабатывает только апдейты с `chat_id == bob.chat_id` И
`message_thread_id == bob.topic_id` (`BotScope.matches`); General и прочие топики
игнорятся. Отправка Боба приколочена к его треду: внутренний `TelegramGateway`
проставляет `message_thread_id = reply_thread_id` во всех ответах, поэтому ответы
Боба падают в его топик. Порт `ReplyGateway` (`typing_indicator(chat_id)` +
`reply(chat_id, markdown, thinking)`) для `HandleMessage` не меняется —
приколачивание треда живёт за швом `reply_gateway`.

## Поток обработки сообщения (perceive → decide → act → persist)

Когда пользователь пишет в Telegram, Боб проживает один ход. Поток собирается в
`HandleMessage`, подписанном на событие `MessageReceived` в `AsyncEventBus`.

> **Тонкий оркестратор + коллабораторы (BOB-062.6b, #9).** `handle_message.py` больше не
> God-use-case: `HandleMessage.handle()` — тонкий оркестратор, который проводит ход по
> фазам **perceive → who → gate → compose+guard → post-effects**, делегируя каждую
> ~14 когезивным коллабораторам, разложенным по чистым модулям. `HandleMessage.__init__`
> остаётся композиционным корнем: собирает коллабораторов из уже инъектированных швов
> (`_build`-хелпер не менялся, поэтому существующие тесты хода валидны). Карта
> коллаборатор → модуль:
>
> | Коллаборатор | Модуль | Роль |
> |---|---|---|
> | `MoodPerceiver` | `personality/usecases/mood_perceiver.py` | обновить настроение из входящего + план выражения (BOB-018) |
> | `GroundedAddons` | `personality/usecases/grounded_addons.py` | заземлённые добавки (рефлексия/колбэк/фасцинация), decorative |
> | `VoiceComposer` | `personality/usecases/voice_composer.py` | голос + генерация ответа |
> | `SocialContext` | `social/usecases/social_context.py` | per-person чтение: отправитель, первое впечатление, отношение, обида, стойка, тон |
> | `AddressivityPerceiver` | `conversation/usecases/addressivity_perceiver.py` | восприятие адресности + брать ли ход |
> | `EngagementModel` | `conversation/usecases/engagement_model.py` | аппетит + verbosity + after-turn feedback |
> | `RecallAssembler` | `conversation/usecases/recall_assembler.py` | воспроизведение треда + absence/acknowledgment |
> | `FloorManager` | `conversation/usecases/floor_manager.py` | resolve + advance разговорной реплики (floor) |
> | `VerifyStep` | `conversation/usecases/verify_step.py` | предответная эпистемическая проверка → per-turn note |
> | `TurnGate` | `conversation/usecases/turn_gate.py` | гейт хода: reply/react/silent (тонкий координатор) |
> | `AntiRepeatGuard` | `conversation/usecases/anti_repeat_guard.py` | анти-повтор/тик + кольцо закрывающих |
> | `EssentialRunner` | `application/usecases/essential_runner.py` | ретрай существенных LLM-шагов + честный GUPPI-нотис |
> | `PreComposeGate` | `application/usecases/precompose_gate.py` | coding-intent + permission гейты, что могут забрать ход |
> | `DiagramSender` | `capabilities/usecases/diagram_sender.py` | авто-рендер inline-mermaid + отправка диаграмм |
>
> 🔴 **Цикл compose↔guard замкнут колбэком по значению, а не импортом.** `AntiRepeatGuard`
> (conversation) принимает `VoiceComposer.compose` (personality) как `compose`-callback, так
> что регенерация повтора вызывает композицию БЕЗ импорта `conversation → personality`. 🔴
> **Turn-local state — через аргументы, никогда не атрибут** коллаборатора (класс — shared
> singleton): `verify_note`, `closer_nudge`, `recalled`, `is_guest`, `reply`, `chat_id`,
> announcer прокидываются параметрами и через тот же колбэк, поэтому не протекают между
> ходами и пользователями. Остаток `handle_message.py` (~1634 строки) — это легитимная
> композиция (`__init__` composition-root + injection-Protocol'ы коллабораторов) и тонкие
> делегаторы; она **мигрирует в runtime в срезе .7**.

1. **Приём (мульти-бот роутер + единый гейт авторизации).** `MultiBotGateway`
   (инфраструктура, на aiogram) одним проходом поллит обоих ботов, дедуплицирует
   кросс-бот по `(chat_id, message_id)`, затем центральный роутер проверяет
   topic-scope Боба и **единый гейт** `Authorizer`. Апдейт вне топика Боба или из
   неразрешённого чата на пайплайн Боба не попадает. В топике Боба (он по
   построению внутри разрешённого чата) роутер публикует ход **и для
   авторизованного, и для гостя** (неавторизованного): авторизованный идёт
   доверенным путём, гость (BOB-019) — вместо прежнего GUPPI hard-reject — попадает
   на **социальный путь Боба** в ограниченном гостевом режиме (см. «Свои и чужие»).
   owner-команда в General уходит GUPPI. Текстовый апдейт в топике
   Боба нормализуется в `MessageReceived` и публикуется в `AsyncEventBus`.
2. **Perceive (обновление настроения, Tier 0).** `UpdateMoodFromText` читает
   сигналы сообщения — сентимент (классификация на **Tier 0**, локально),
   частоту сообщений, время суток (из инъецированного `Clock`) и присутствие — и
   собирает `MoodDelta`, который применяет чистый домен `Mood`. Новое настроение
   сохраняется в `PersonalityState`. **Социальная зарядка (BOB-033 .3):** шаг
   сентимент→валентность **асимметричен** — масштабируется деривациями диспозиции
   (`positive_lift_scale()` для тёплого, `negative_dip_scale()` для холодного), так
   что тёплое сообщение поднимает настроение сильнее, чем холод опускает. Сверх того,
   при явно **позитивном** входящем `run(...)` сначала тянет настроение долей
   `social_lift_rate()` к baseline-`target` через `Mood.lift_toward` («вытеснить
   минор» до того, как ляжет пер-сигнальная дельта), поэтому тёплый обмен реально
   вытягивает Боба из спада, а не только сдвигает валентность — главный
   анти-депрессант. Без переданного `target` (дефолт) тяга пропускается —
   обратная совместимость.
3. **Гейт хода: семантическое решение об отклике (BOB-049).** Перед компоновкой
   `HandleMessage._gate_turn` решает, **берёт ли Боб этот ход и как**. С провязанным
   судьёй (живой путь) Боб **понимает** сообщение в контексте и выбирает — как
   человек — `REPLY` / `REACT` / `IGNORE`: `_judge_turn` собирает контекст хода (текст;
   отправитель как социальный контекст; **общий недавний тред топика** — все участники,
   а не только текущий собеседник, BOB-058; структурные **подсказки** —
   `mentions_bob` / `reply_to_bob` / поштучная адресность /
   `others_present` / `floor_engaged`; тон настроения) и делегирует одно смысловое
   суждение `DecideResponse` → `ResponseChoice{intent, emoji, reason}`. Структурные
   сигналы — **входы**, которые судья взвешивает по смыслу, а не правила: нет ярлыка
   `is_owner → reply`, решение держится для **любого** собеседника (authz ортогонально —
   гостевые ограничения на пути `REPLY` неизменны). На `REPLY` гейт возвращает
   `_ReplyGate` и ход идёт в компоновку (плюс уже воспроизведённая нить — не читается
   дважды); `REACT` и `IGNORE` полностью обрабатываются внутри `TurnGate`
   (см. шаг 4) и гейт возвращает `None`. Без провязанного судьи ИЛИ если отправитель не
   воспринят, гейт откатывается на **легаси-лестницу** BOB-023/025: `classify_addressivity`
   → `decide_response` (`ENGAGE` / `REACT` / `SILENT`) + форменный гейт `REACT_ONLY`
   (BOB-018) — ровно как раньше.
4. **Decide (план выражения + recall + история + личность).** Сюда ход доходит уже
   как `REPLY` (гейт шага 3 пропустил его на компоновку; ветки `REACT` / `IGNORE`
   завершены внутри `TurnGate` — он ставит выбранный по смыслу эмодзи или
   молчит и 🔴 в обеих ветках персистит ход, чтобы нить собеседника не рвалась,
   BOB-045). Сначала считается чистый **план выражения** (BOB-018, `decide_expression`
   по свежему настроению + сигналам хода + seeded-RNG): он выбирает редкие
   grounded-добавки (протекающая внутренняя жизнь / колбэк) и мягкую подсказку формы
   (см. «Выражение»). На легаси-пути (судья не провязан) сохраняется режим краткой
   нативной реакции `REACT_ONLY` — Боб ставит mood-эмодзи вместо генерации и ход
   завершается. Иначе воспроизводится
   **общий недавний тред топика** — последние `k` ходов ВСЕХ участников
   (`_replay_recent_thread` → `recent_episodes(k)` через `MemoryRepo`, BOB-058),
   уже размеченные `"<имя>: …\nbob: …"`, так что Боб слышит всю группу и держит
   нить многостороннего разговора (было пер-персона, `recent_episodes_for`, BOB-045).
   Из памяти извлекаются релевантные факты (`MemoryRecall`, FTS5).
   Recall **единый** для любого участника закрытой группы (BOB-051): он больше не
   фильтруется по `sender_id` собеседника — общее знание Боба доступно и owner, и
   не-owner. `recalled_excluding_reflections` (BOB-033) остаётся: рефлексии не
   попадают в reply-пул (это про дословное копирование, не про знание). Затем
   собирается контекст ответа:
   идентичность, тон настроения, вердикт `TasteEngine` по теме, фантомные
   предпочтения, вспомненные факты и недавние реплики. Этот материал
   формирует ответ Боба и возвращается тому же пользователю, поэтому он
   передаётся роутеру как **`shareable_context`** (см. Вариант 2 редакции ниже).
   Здесь же работает **Negotiation-врезка** (BOB-013): зона темы
   (`ZoneClassifier`) + убеждённость (`conviction_for`) → стойка
   (`Negotiation.decide`) → директива, дописанная к системному промпту, поэтому
   Боб защищает свои ценности, а не угождает безусловно (см. «Higher Mind»). Здесь
   же решается **длина** ответа (BOB-024): после того как адресность взяла ход
   (`ENGAGE`), `classify_answer_demand` по тексту и `decide_verbosity` по
   demand-интересу-настроению/аппетиту выбирают `Verbosity`
   (`TERSE` / `NORMAL` / `EXPANSIVE`), из которого собирается финальная директива
   длины + few-shot (см. «Краткость по запросу»). Адресность решает, *отвечать ли*;
   краткость — *насколько коротко*.
5. **Act (ответ, гибридный тиринг + селективная редакция, fallback Tier 0).**
   `LLMRouter` обрабатывает задачу `REPLY_TO_USER`. Тир ответа выбирается
   **гибридно** (BOB-006): по умолчанию casual/короткая реплика идёт на быстрый
   **Tier 0** (flash, секунды) ради отзывчивости, а сложная/длинная/требующая
   инструментов эскалируется на качественный **Tier 1** (plus). Выбор делает
   чистый эвристический селектор `select_reply_tier` по тексту пользователя (без
   лишнего LLM-round-trip), и он приходит роутеру как `tier_override` в
   `LLMRequest` (см. «LLM: тиры…» ниже). `shareable_context`
   (история/память/настроение/идентичность/вкус) сопровождает вызов — именно это
   даёт Бобу память (он помнит имя, названное ход назад). Сугубо внутренний
   материал передаётся как `private_context` и **редактируется** перед любым
   вызовом Tier 1 (только Tier 0). Важно: редакция привязана к **политике задачи**,
   а не к выбранному тиру — ответ, опущенный на Tier 0, всё равно никогда не несёт
   `private_context`. При сбое Tier 1 роутер откатывается на **Tier 0** локально,
   отправляя тот же payload (с уже вырезанным `private_context`). Сама генерация
   ответа — **существенный** шаг (BOB-049 .3): она обёрнута ограниченным ретраем, и
   если после повторов всё равно падает — ход завершается честным GUPPI-нотисом, а не
   деградированным полуответом (см. «Полный Боб или честный GUPPI-нотис»).
6. **Ответ (typing-индикатор во время генерации + rich-финал, BOB-009).** Нативный
   токен-стрим в групповом топике Telegram невозможен (драфты — только ЛС, а
   `editMessageText` в группе медленный и флуд-опасный), а Боб доступен **только**
   через групповой топик (ЛС закрыта authz). Поэтому `TelegramGateway` не стримит.
   Медленная генерация (`router.run`) выполняется **внутри** async-контекста
   `typing_indicator(chat_id)`: на входе он сразу шлёт `sendChatAction("typing")` в
   тред Боба, затем фоновый таск **повторяет** его каждые `typing_interval` секунд
   (Telegram сам гасит индикатор), пока модель думает — пользователь видит «Bob
   печатает…» всё ожидание. На выходе из контекста keepalive-таск **отменяется**
   (без утечки); сбой `sendChatAction` best-effort (проглатывается, ход не падает).
   Готовый ответ затем коммитится **одним** вызовом `reply()` — Rich Message'ом
   (`send_rich_message`: заголовки/списки/код/цитаты + `RichBlockThinking`, если есть
   `thinking`), привязанным к `message_thread_id`. При **любой** ошибке rich —
   деградация на plain `send_message` (ответ никогда не теряется). Каденс typing
   задаётся инъецированным `sleep`, поэтому в тестах детерминирован. См. раздел
   «Telegram-транспорт» ниже.
7. **Persist.** Ход сохраняется как эпизод в `episodic_log` — атрибутированный
   `sender_id` текущего собеседника (BOB-045), чтобы по нему фильтровать
   пер-персона сигналы (absence, анти-повтор) над общим тредом (BOB-058), — а снапшот
   настроения
   записывается в `mood_state` и `mood_history` через `MemoryRepo`. 🔴 Персист идёт во
   **всех** ветках хода — `REPLY`, `REACT` (`(реакция: <emoji>)`), `IGNORE`
   (`(промолчал)`) и даже при сбое существенного шага (`(нет ответа: проблемы со
   связью)`) — чтобы нить собеседника никогда не теряла предыдущий ход (BOB-045).
   **Извлечение фактов (`extract_facts`) идёт для ЛЮБОГО участника** закрытой
   группы (BOB-051): ход не-owner так же пополняет общую/публичную память Боба, как и
   ход owner (память публична в пределах закрытой группы; раньше гостевой ход в неё не
   дистиллировался).

Параллельно идёт лёгкий **heartbeat** — фоновые asyncio-задачи рантайма, каждая
изолирована: ошибка в одном тике не роняет остальные, а транзиентный сетевой сбой
ретраится с backoff (см. «Резилентность тиков»).

## LLM: тиры и селективная редакция контекста

`LLMRouter` — это политика приложения поверх провайдер-агностичного порта
`LLMProvider`. Один и тот же адаптер `OpenAICompatProvider` обслуживает оба тира;
переключение «локально ↔ API» — это смена конфигурации, не переписывание.

| Tier | Назначение | Провайдер |
|------|------------|-----------|
| **Tier 0** | дешёвая и приватная работа: сентимент, внутренний монолог, рефлексия | локальный mlx-lm сервер (по умолчанию без ключа; опциональный `llm.tier0_api_key` позволяет указать на keyed/удалённый эндпоинт) |
| **Tier 1** | качественный reasoning: ответ пользователю, Genesis | Qwen API (bearer-ключ из конфигурации/env) |

Роутер классифицирует задачу (`TaskType`) в предпочтительный тир:
`REPLY_TO_USER` и `GENESIS` → Tier 1, `SENTIMENT` / `INNER_MONOLOGUE` /
`REFLECT` / `EXTRACT_FACTS` → Tier 0. Этот тир — лишь умолчание задачи: вызывающий
может задать `LLMRequest.tier_override`, чтобы направить конкретный запрос на
другой тир (если такой провайдер подан; неизвестный override игнорируется и
запрос идёт на умолчание задачи).

### Гибридный тиринг ответа пользователю (BOB-006)

Живой ответ на reasoning-модели Tier 1 (`qwen3.7-plus`) может занимать минуты —
слишком медленно для чата, — поэтому ответ пользователю выбирает тир **гибридно**,
а не всегда платит за качественную модель. `select_reply_tier`
(`application/router/reply_tier_selector.py`) — это **чистая детерминированная
эвристика по входящему сообщению** (без отдельного LLM-round-trip): casual/короткая
реплика отвечается на быстрый Tier 0 (`qwen3.6-flash`), а на качественный Tier 1
(`qwen3.7-plus`) эскалируется только сложный ход. `HandleMessage` зовёт селектор и
передаёт результат роутеру как `LLMRequest.tier_override`.

Эскалация на Tier 1 срабатывает, когда ход требует инструментов (`needs_tools`,
качественная модель надёжнее в tool-calling) **или** сообщение выглядит сложным по
любому сигналу: длиннее 240 символов, более одного знака вопроса, содержит блок
кода (` ``` `) или несёт ключевое слово глубины (`объясни`, `проанализируй`,
`сравни`, `напиши`, `подробно`, `почему`, …; целыми словами, регистронезависимо).
Иначе ход остаётся на быстром Tier 0. **Приватность не зависит от выбранного тира:**
редакция `private_context` следует политике задачи (`REPLY_TO_USER`), поэтому ответ,
опущенный селектором на Tier 0, всё равно не несёт внутреннего контекста.

**Селективная редакция (Вариант 2) устроена по построению.** Контекст запроса
разделён на два канала по политике назначения:

- `shareable_context` — история диалога, вспомненная память, настроение,
  идентичность и вкус. Этот материал формирует ответ Боба и возвращается тому же
  пользователю, поэтому он **разрешён** на Tier 1.
- `private_context` — сугубо внутренний материал (только Tier 0). Он **никогда**
  не прикрепляется к payload, идущему на Tier 1 (в P0.1 канал пуст, но шов
  сохранён, чтобы внутренний контекст не утекал по умолчанию).

Запрос на Tier 0 (локальный) получает оба канала; запрос на Tier 1 — только
`shareable_context`. Payload собирается один раз, поэтому при откате Tier 1 →
Tier 0 отправляется ровно тот же payload (с уже вырезанным `private_context`) —
инвариант держится и на пути fallback. Прежняя over-aggressive редакция (когда на
Tier 1 не доходила вообще никакая память) делала Боба stateless; Вариант 2 это
исправляет, не раскрывая внутренний материал.

### Reasoning-модели: таймаут, отключение «мышления», терпимый разбор

Tier 1 может оказаться reasoning-моделью, которая тратит тысячу с лишним токенов
на внутренние рассуждения, прежде чем выдать ответ. Поведение `OpenAICompatProvider`
настраивается так, чтобы это не приводило к ложным откатам и пустым ответам:

- **Таймаут запроса** (`llm.timeout_seconds`, по умолчанию `180`). Щедрого
  значения хватает медленному reasoning-ответу, чтобы он не упёрся в таймаут и не
  свалился ложно на Tier 0.
- **Отключение «мышления»** (`llm.disable_thinking`, по умолчанию включено).
  Ответам пользователю chain-of-thought не нужен: его отключение быстрее и дешевле
  и устраняет случай пустого `content`, когда модель израсходовала весь бюджет на
  `reasoning_content`. Провайдер шлёт директиву «no thinking» сразу в двух формах
  (`extra_body` и `chat_template_kwargs`), чтобы её прочитал любой совместимый
  upstream.
- **Терпимый разбор содержимого.** Структурные ошибки ответа (нет `choices` или
  `message`) по-прежнему поднимаются как ошибки — это сломанный upstream. Но
  отсутствующий, `null` или нестроковый `content` не ошибка: это деградация в
  пустую строку, ход продолжается штатно, без ложного отката на fallback.

### Сэмплинг: temperature по тирам против дословного самоповтора (BOB-022)

Без явной `temperature` Qwen MaaS декодирует **жадно** (greedy): один и тот же
prompt даёт байт-в-байт одинаковый вывод. На живом диалоге это вылезало как
дословный самоповтор — Боб выдавал идентичный длинный ответ на разные входящие
(подтверждено DIAG-логом: distinct ввод → одинаковый hash ответа, без сетевых
сбоев). Лечение в два слоя.

- **Сэмплинг в payload.** `OpenAICompatProvider` принимает `temperature` и
  опциональный `top_p` и складывает их в тело запроса **на всех путях** (обычный
  `complete`, стрим, tool-calling) через `_apply_sampling`. Каждое значение шлётся
  **только когда задано**: ненастроенный провайдер не шлёт ничего, и endpoint
  держит свои дефолты. Заданная `temperature` делает декодирование стохастическим,
  и одинаковый prompt перестаёт давать одинаковый вывод.
- **Конфиг по тирам.** `llm.tier0_temperature` (по умолчанию `0.5`) и
  `llm.tier1_temperature` (по умолчанию `0.8`); оба терпят строковую форму из
  окружения и override через env. `build_tier_providers`
  (`infrastructure/llm/factory.py`) читает их через `_optional_float_or_none`
  (отсутствие → `None` → провайдер ничего не форсит) и прокидывает per-tier. Tier 0
  (классификация/сентимент/суммаризация) держится **стабильнее** (ниже температура),
  Tier 1 (ответы пользователю и монолог) идёт **вариативнее** для живости.
- **Анти-повтор-страж (защита в глубину).** На случай, если стохастика всё же
  совпадёт, `handle_message` после генерации сверяет свежий ответ с **окном последних
  N ответов Боба** (BOB-026 расширил страж с одного последнего ответа до окна и от
  точного совпадения до verbatim-или-near-verbatim) и при повторе регенерирует. BOB-032
  сделал страж **recall-aware**: сравнение идёт против объединения недавней истории **и
  реплик Боба из recalled-памяти**, а регенерация ломает аттрактор (до двух ретраев).
  BOB-036 добавил **фраза-тик-страж** (`is_phrase_tic`): помимо сходства целой реплики он
  ловит подписную закрывашку, повторяющуюся в нескольких недавних репликах (две разные по
  сути реплики могут заканчиваться одним и тем же «хвостом»), и гонит её через ту же
  регенерацию. BOB-043 расширил обзор до **широкого окна** (`tic_lookback`), а BOB-061 —
  до **кросс-сессионного** персиста closer-ов и **near-verbatim** кластеризации мотива, так
  что тик, мелькающий раз в сессию через дни, тоже ловится — подробности в разделе про
  реактивный ход ниже.

**Разбор фактов (`ExtractFacts`, Tier 0) устойчив к reasoning-обёртке.**
Извлечение фактов — best-effort поверх уже сохранённого эпизода, поэтому модель,
вернувшая прозу вместо JSON, не должна ломать ход. Парсер пробует по очереди:
сырой текст, тело markdown-блока (```` ``` ```` или ```` ```json ````) и первый
сбалансированный JSON-массив `[...]` (терпя преамбулу-рассуждение до и любой текст
после массива). Невалидный JSON, не-массив или записи без `content` дают ноль
фактов, а не ошибку.

## Telegram-транспорт: aiogram, typing-индикатор, Rich Messages

`TelegramGateway` переписан с `python-telegram-bot` на **aiogram** (Bot API 10.1):
typing-индикатор + Rich Messages. Адаптер остаётся чистым транспортом за портом
`ReplyGateway`/`EventBus` — домен и приложение не тронуты, сменилась только
зависимость и реализация gateway.

- **Typing-индикатор во время генерации + rich-финал (BOB-009).** Нативный
  токен-стрим в групповом топике невозможен (драфты — только ЛС/Threaded Mode = темы
  в личке, а `editMessageText` в группе медленный и флуд-опасный), а Боб доступен
  **только** через групповой топик BobNet (ЛС закрыта authz). Поэтому стриминг убран
  (`stream_reply`/`_iter_tokens` удалены — псевдо-стрим из готового текста больше не
  используется):
  - **Во время генерации** медленный `router.run` оборачивается в async-контекст
    `typing_indicator(chat_id)`: на входе сразу шлётся `sendChatAction("typing")` в
    тред Боба (`message_thread_id`), затем фоновый таск **повторяет** его каждые
    `typing_interval` секунд (Telegram сам гасит индикатор через несколько секунд),
    пока собирается ответ — пользователь видит «Bob печатает…» всё ожидание. На
    выходе из контекста таск **отменяется** (без утечки). Каденс задаётся
    инъецированным `sleep`, поэтому в тестах детерминирован; сбой `sendChatAction` —
    best-effort (проглатывается, ход не падает).
  - **Готовый ответ** коммитится **одним** `send_rich_message` через `reply()`.
- **Rich Messages.** `MarkdownToRichMessage` (чистая детерминированная
  трансформация) превращает подмножество markdown ответа в типизированное дерево
  aiogram `RichMessage` — заголовки, списки, код, цитаты, разделители, инлайн
  bold/italic/code/strike/spoiler/math. `RichMessageSerializer` рендерит дерево в
  rich-message markdown, который `InputRichMessage(markdown=...)` принимает на
  отправку через `send_rich_message`. Одиночный (не-драфт) `send_rich_message`
  работает и в групповом топике.
- **`RichBlockThinking`.** Ответ Боба несёт опциональное поле `thinking`; при
  наличии оно рендерится ведущим сворачиваемым блоком `RichBlockThinking` перед
  основным ответом — задел под монолог/размышления Боба.
- **Тихий plain-fallback.** Любая ошибка rich деградирует на обычный
  `send_message` (с дроблением по лимиту длины 4096) — пользователь всегда
  получает текст, никогда не ошибку транспорта. Финал — единственное rich-
  сообщение, поэтому известный баг «edit-стрим ломает rich» больше не возникает.

## Авторизация (owner + allowlist + chat-scope)

Боб приватен: до любой автономности и расширения доступ закрыт. Политика — чистый
`Authorizer` (`social/usecases`) поверх порта `AllowlistStore`, а применяется она
**единым гейтом в центральном роутере** — единственной точкой проверки, без обхода
и fail-closed. В мульти-бот сборке (BOB-003) этот `Authorizer` общий: его читает
гейт топика Боба и владеет им идентичность GUPPI (reject + owner-команды), без
дублирования логики.

- **Политика.** `is_authorized(user_id, chat_id)` сперва проверяет chat-scope:
  сообщение из чата вне `allowed_chat_ids` отвергается для всех, включая owner —
  даже при утечке токена в чужом чате Боб мёртв. Внутри разрешённого чата owner
  пропускается всегда, любой другой — только если он в персистентном allowlist.
- **Персистентность.** `owner_id` и `allowed_chat_ids` берутся из конфигурации
  (`telegram`) и неизменны на процесс; динамический allowlist хранится в
  `KvAllowlistStore` (таблица `kv` SQLite) и читается на каждом решении, поэтому
  команда `/authorize <user_id>` переживает рестарт.
- **Гость вместо reject (BOB-019).** Неавторизованный **в топике Боба** больше не
  получает GUPPI hard-reject: он попадает на социальный путь Боба как **гость**. Его
  **память едина** с памятью группы (BOB-051 — единое знание Боба, нормальный голос),
  но **привилегии** остаются гейтом: без инструментов и без owner-внутрянки (см. «Свои
  и чужие»). DM незнакомца и чужие чаты по-прежнему игнорируются молча (без
  раскрытия). Это **социальный** слой поверх authz: гостевой статус **не** даёт
  доступа к возможностям и не меняет политику — промоушен только через `/authorize`.
- **Owner-команды.** `/authorize`, `/deauthorize`, `/status` обрабатывает GUPPI в
  General (`GuppiHandler.handle_general_command`) и только для owner; они не
  публикуются как сообщения Боба.

## Свои и чужие: социальная идентичность собеседника (BOB-019)

Боб — личность, а не турникет: он **воспринимает**, кто на другом конце хода, и
ведёт себя соответственно. BOB-019 кладёт поверх неизменной политики доступа
(`Authorizer`) отдельный **социальный слой**. Это два разных слоя: **authz**
решает, что собеседнику *доступно* (без изменений), а социальный слой решает,
*как Боб его встречает*. Социальная классификация — это восприятие, а не решение
о доступе: она не открывает ни одной возможности.

### Восприятие отправителя (кто пишет)

- **`social/interlocutor.py`** (чистый домен) — модель собеседника.
  `Interlocutor(sender_id, display_name, kind, trust)` — неизменяемый value
  object. `InterlocutorKind ∈ {OWNER, KNOWN, GUEST, BOT}` (бот — отдельный вид,
  фундамент под будущий BobNet), `Trust ∈ {TRUSTED, GUEST}` (ортогонально виду).
  Чистая функция `classify(*, sender_id, sender_name, is_owner, is_authorized,
  is_bot=False) -> Interlocutor`: owner → OWNER/TRUSTED, авторизованный не-owner →
  KNOWN/TRUSTED, неавторизованный человек → GUEST/GUEST; бот всегда `kind=BOT`, но
  его trust всё равно следует авторизации. Без I/O, детерминированно, покрывает и
  людей, и ботов (готовность к bot-to-bot без реального транспорта в домене).
- **`social/usecases/sender_perception.py`** — шов проводки `SenderPerception`:
  составляет неизменный `Authorizer` с чистым `classify`, превращая
  `MessageReceived` в `Interlocutor`. `is_owner` — по идентичности (не chat-scoped,
  поэтому Боб узнаёт владельца где угодно), `is_authorized` — полная chat-scoped
  политика для остальных. Это восприятие, **не** гейт: ни одно решение о доступе
  здесь не принимается и не меняется.
- **`voice.who_is_writing_directive(interlocutor)`** дописывает в промпт строку
  «сейчас тебе пишет: <имя> (<вид>)», поэтому Боб узнаёт owner как owner,
  приветствует знакомого, замечает незнакомца или бота. Как характер, не как
  конфиг-переключатель: влияет только на голос, не на выбор пайплайна.

### Память публична, привилегии — гейт (🔴 ядро безопасности, BOB-051)

Прежде неавторизованный в топике Боба получал GUPPI hard-reject. Теперь
**гость** (неавторизован, но в разрешённом чате и топике Боба) попадает на
**социальный путь Боба** и говорит с ним как с человеком. Закрытая модерируемая
группа — это приглашённые, **социально доверенные** люди, поэтому BOB-051
**расцепил** флаг `is_guest`: раньше он гейтил И память, И привилегии — теперь
гейтит **только привилегии**. Память (recall, история, голос, извлечение фактов)
**едина и публична** в пределах группы: Боб — один разум, и его знание доступно с
кем угодно в группе. Разводка живёт в двух местах:

- **Роут (`infrastructure/telegram/multibot.py`).** Сообщение в топике Боба по
  построению внутри разрешённого чата, поэтому центральный роутер публикует его на
  пайплайн Боба и для авторизованного, и для гостя — видимый hard-reject для
  топика Боба убран. Разделение доверенный/гость — забота `HandleMessage`, не
  роутера. Вне топика Боба — как раньше (дроп; owner-команда в General → GUPPI).
- **`application/usecases/handle_message.py`.** Гость определяется как
  `interlocutor.trust is Trust.GUEST`. Этот флаг теперь гейтит **только привилегии**:
  - **НЕТ tool-loop / capability** — компоновка остаётся на простом роутере
    (`VoiceComposer.compose` не запускает `ToolLoop` при `is_guest`), гость не может
    дёрнуть ни одну возможность;
  - **НЕТ owner-внутрянки** — grounded-добавки внутренней жизни owner
    (`leak_inner_life` / колбэк / fascination) на гостевом ходу пропускаются: они
    раскрывают приватный внутренний мир Боба и остаются owner-only;
  - **отказ owner-командам/данным** — `/code`, `/goals`, конфигурация и owner-данные
    закрыты authz, как и раньше.

  Что флаг **больше НЕ режет** (стало единым для любого участника):
  - **recall** — единое знание Боба; `_scoped_recall` (per-person сужение) **убран**,
    recall больше не фильтруется по `sender_id` — фикс «расщеплённой памяти» (баг,
    когда Боб «забывал» свой roadmap в разговоре с не-owner);
  - **история** — per-person нить по `sender_id` собеседника
    (`recent_episodes_for`), как у owner: continuity (кто и о чём говорил), а не
    ограничение знания;
  - **голос** — **нормальный**, не настороженный: `voice.stranger_directive()` в
    проде больше **не добавляется** (заготовка осталась для будущих настоящих
    незнакомцев / DM);
  - **извлечение фактов** — `extract_facts` идёт со ВСЕХ ходов участников, ход не-owner
    пополняет общую/публичную память Боба.

**Инвариант безопасности (BOB-051):** память **публична в пределах закрытой группы**
— это осознанное решение owner; **привилегии остаются гейтом**. Гость = **ноль**
вызовов capability + **ноль** owner-внутрянки (inner-life) + отказ owner-командам, но
recall, per-person история и нормальный голос — **есть**. Разрешение неавторизованным
на привилегированное (flow «спросить разрешение») — **BOB-052** (см. ниже). chat-scope и
доступ owner/allowlist к возможностям не меняются; промоушен гость→доверенный — только
через owner-команду `/authorize`.

### First-impression (узнавание вернувшегося)

Когда пишет новый человек, Боб формирует лёгкое первое впечатление и хранит его,
чтобы при следующей встрече узнать («кажется, мы уже сталкивались»). Это
намеренно минимальный фундамент под полный multi-party RelationshipTracker
(BOB-014), а не он сам.

- **`social/first_impression.py`** (чистый) — `FirstImpression(
  sender_id, first_seen_at, note)` (value object; пустая заметка запрещена) и
  чистая `impression_note_for(interlocutor) -> str` — детерминированный лёгкий
  «вайб» по виду собеседника + имени, без выдуманных фактов.
- **`social/adapters/first_impression_store.py`** —
  `SqliteFirstImpressionStore` за порт `FirstImpressionStore` поверх таблицы
  `first_impression` (одна строка на `sender_id`). `save` —
  `INSERT … ON CONFLICT(sender_id) DO NOTHING` (**insert-once**): первое
  впечатление формируется один раз и не перезаписывается, поэтому момент первой
  встречи и заметка переживают повторные ходы (это и даёт узнавание). `load`
  возвращает `None` для незнакомца. Это данные **про человека** (о нём), а не
  приватная память owner, поэтому запись/чтение безопасны и на гостевом ходу.
- **`voice.recalled_impression_directive(note)`** дописывает в промпт прежнюю
  заметку для вернувшегося отправителя — grounded строго в реальной хранимой
  заметке, без выдуманного прошлого; приложение добавляет её только если прежнее
  впечатление есть.

### Где это в потоке хода

`HandleMessage` на каждом ходу: `_perceive_interlocutor` (через
`SenderPerception`, опциональный шов — без него ход ведёт себя как раньше) →
`who_is_writing_directive` в промпт → определение `is_guest` по `trust` →
гейт привилегий по `is_guest` (без tool-loop и без owner-внутрянки в
`VoiceComposer.compose`) поверх **единой** памяти: per-person история по `sender_id` и
единый recall для всех (BOB-051, см. ниже) → извлечение фактов для любого
участника → запись/чтение first-impression →
`recalled_impression_directive` при наличии прежней заметки.

## Разрешение на привилегированное: спросить owner (BOB-052)

BOB-051 сделал память **публичной** в закрытой группе, но **привилегия** — запуск
инструмента, раскрытие внутренней жизни Боба, выдача owner-данных — остаётся
owner-гейтом. Раньше гость на такой запрос упирался в молчаливый гейт (Боб не звал
инструмент, не утекал внутрянку). BOB-052 заменяет «тихо ничего» на **человеческое
поведение**: когда **не-авторизованный** участник просит привилегированное, Боб не
молчит и не делает сам — он заводит pending-запрос и **спрашивает owner**, а owner
**один** решает. 🔴 Граница неизменна: только owner решает; авторизованные
(owner/allowlist) в этот флоу **не входят** вообще; гейтятся только три вида —
`tool` / `internal` / `owner_data`, а память BOB-051 **не** ослаблена (обычная
болтовня и общее знание остаются публичны). Связано с BOB-051 (что публично) и
BOB-019 (durable-промоушен через `Authorizer`).

### Домен (`social/permission/`, чистый)

- **`privilege.py`** — шов семантического суждения о привилегии. `PrivilegeNeed(
  needs_permission, kind, what)` — immutable исход: гейт `needs_permission`, при
  `True` — `kind ∈ {tool, internal, owner_data}` (`PRIVILEGE_KINDS`) и
  человекочитаемое `what` («показать задачи проекта») для owner-нотиса.
  `PrivilegeContext(request_text, capability_hints, recent_thread)` — immutable
  ВХОД (подсказки capability — сигналы, не правила). `PrivilegeJudge` — инжектируемый
  порт `assess(ctx) -> PrivilegeNeed`. Чистая половина: `PRIVILEGE_JUDGE_SYSTEM_PROMPT`
  + `build_privilege_user_prompt(ctx)` сворачивают вход в Tier-0 user-prompt с
  размеченным контрактом (`needs_permission` / `kind` / `what`); `parse_privilege_need(
  raw)` мапит ответ модели обратно и **RAISE-ит** `PrivilegeJudgeParseError` на мусор
  (а не тихий дефолт), чтобы каллер опустил add-on с безопасным дефолтом. 🔴
  Консервативно: болтовня и общее знание → `needs_permission=False` (обычный ответ).
- **`entities.py`** — `PermissionRequest` (frozen, slots): один pending-запрос —
  `requester_id` / `requester_name` (кто, не owner), `request_text` (исходное
  сообщение **дословно**, чтобы исполнить на approve), `kind` / `what`, `state`,
  `created_at` (инжектится, не из часов домена). `with_state(state)` возвращает копию —
  домен I/O-free и тестируем без `datetime.now`.
- **`state.py`** — `PermissionState` (StrEnum): `PENDING` (ждёт owner) →
  `APPROVED` (разрешил → исполнить) / `DENIED` (отказал → мягкий отказ); `EXPIRED` —
  протух или вытеснен новым запросом того же просящего. Значение совпадает с TEXT в
  SQLite (тривиальный round-trip).
- **`intent.py`** — чистые NL-предикаты owner-решения (детерминированно, без LLM/I/O,
  в духе BOB-042 `is_approval`): `is_deny` (отказ-токены + одиночное отрицание
  «не»/«нет»; **безопасный дефолт**, проверяется первым), `is_grant` (короткая реплика
  ≤ 6 слов с grant-токеном, не-отказ — разовый approve), `is_authorize` (durable-токены
  «авторизуй» / «дай доступ» / «добавь в список»). 🔴 Совпадение по границам слов после
  нормализации; длинный абзац не апрувит; отрицание ветирует grant; неоднозначность →
  `False`. Вычисляются ТОЛЬКО для owner.

### Инфраструктура

- **`social/adapters/privilege_judge.py`** — `LlmPrivilegeJudge` (Tier-0): тонкая
  реализация порта `PrivilegeJudge` одним дешёвым локальным вызовом (роутер с новым
  `TaskType.PRIVILEGE_JUDGE` → локальный тир). Всё shaping решения — чистый домен; **не
  глушит** сбои: ошибка модели/парсинга пропагается.
- **`social/adapters/permission_request_store.py`** —
  `SqlitePermissionRequestStore` за таблицей `permission_request` (одна строка на `id`).
  `ensure_schema` — идемпотентная PRAGMA-безопасная миграция (`CREATE TABLE / INDEX IF
  NOT EXISTS`, аддитивно), также входит в общий `schema.sql`. `save` — UPSERT на `id`;
  `active` / `active_for(requester_id)` — ещё-PENDING запросы (старейший первым);
  `set_state` — переход строки. Весь SQL параметризован (`?`).

### Флоу (`social/usecases/permission_flow.py`)

`PermissionFlow` — политика **КОГДА** (не КАК): детект привилегии, нотис owner, запись
решения. Всё инжектится (judge / store / notifier / clock / id-factory / executor),
поэтому в тестах детерминирован; не подключённый в `HandleMessage` шов инертен, и каждый
ход ведёт себя как раньше.

- **`maybe_request`** — на ходу **не-owner, не-авторизованного** участника спрашивает
  `PrivilegeJudge`. Owner или авторизованный → сразу `False` (обычный путь не тронут).
  Привилегированный need → создать + сохранить `PENDING` `PermissionRequest`, 🔴
  **уведомить owner** голосом Боба («Вова, <кто> просит <что> — разрешить?»), сказать
  просящему лёгкое «Секунду, спрошу Вову.» и **поглотить ход**. Один активный pending на
  просящего — новый запрос вытесняет старый (`EXPIRED`). Вся ветка обёрнута в
  **safe-default**: любой сбой (judge / store / нотис) логируется и **роняется в обычный
  чат** — привилегированный путь просто не срабатывает, ничего не раскрывается.
- **`maybe_decide`** — 🔴 ТОЛЬКО при `is_owner` и наличии активного pending. Не-owner
  (даже голое «да») → `False`, ничего не двигает. Намерение owner читается сперва из
  явной команды `/allow` / `/deny` / `/authorize` (по первому токену, так `/authorize 7`
  тоже маршрутизируется), затем из чистых предикатов: authorize → grant → deny (deny
  ветирует grant внутри `is_grant`). grant/authorize → `APPROVED`, deny → `DENIED`;
  неоднозначная реплика owner → `False` (отдаётся чату, не случайный approve).
- **Каналы.** `PermissionNotifier` (`notify_owner` / `tell_requester`) — двухканальный
  шов нотиса; `PermissionRequestStoreLike` / `PermissionExecutorLike` — порты стора и
  исполнителя.

### Исполнение (`social/usecases/permission_execution.py` + `application/usecases/privileged_fulfiller.py`)

`PermissionExecutor` — половина **КАК**: после записи решения (`maybe_decide` передаёт
запрос + `PermissionDecision`) исполняет вердикт.

- **GRANT — per-request elevation.** Перепрогнать сохранённый `request_text` через
  `PrivilegedFulfiller` так, **как если бы** просящий был авторизован — но ТОЛЬКО для
  ЭТОГО запроса (одноразовый поднятый контекст). 🔴 Fulfiller получает **только**
  `request_text`: поднятие не утекает на другие/будущие сообщения просящего, durable-
  состояние не трогается. Результат уходит просящему голосом Боба через `RequesterChannel`.
- **AUTHORIZE — durable.** `DurableAuthorizer.authorize` (реальный `Authorizer` grant в
  allowlist, BOB-019) — просящий становится авторизован, дальше идёт обычным путём — и
  **затем** исполнить текущий запрос (уже авторизованно). Durable-grant **первым**: если
  упал — всё отказывает, ничего не исполняется.
- **DENY** — мягкий отказ голосом Боба («Спросил Вову — пока не могу с этим помочь.»);
  ничего не исполняется и не раскрывается.
- 🔴 **Декоративно / safe-default = ОТКАЗ.** Весь `execute` обёрнут: любой сбой
  (fulfiller / authorize / channel) ловится и **тихо роняется** — безопасный дефолт при
  сбое — ОТКАЗАТЬ (никогда не раскрыть и не исполнить при ошибке), **без** GUPPI-нотиса о
  сбое (это флейвор, не обязательный шаг ответа).

`PrivilegedRequestFulfiller` (конкретный `PrivilegedFulfiller`): когда подключены
tool-провайдер И непустой реестр capability — запрос идёт через тот же capability
tool-loop, что у авторизованного хода (GUPPI может дёрнуть инструмент); иначе — простой
роутер (раскрытие внутрянки / обычный ответ). 🔴 В модель уходит только `request_text`.

### Проводка (`app.py`, `handle_message.py`)

`_build_permission_flow` собирает флоу + исполнение: Tier-0 `LlmPrivilegeJudge` в обёртке
`_SafeDefaultPrivilegeJudge` (на живом ходу сбой суждения → безопасный дефолт
`needs_permission=False`, ход просто падает в обычный ответ), `SqlitePermissionRequestStore`,
двухканальный `_PermissionNotifier` (owner-нотис в **топик Боба**, ack просящему в групповой
чат) и `PermissionExecutor` над `PrivilegedRequestFulfiller`, `_PermissionRequesterChannel`
(ответ в групповой чат) и реальным `Authorizer`. В `PreComposeGate.maybe_permission`
(`application/usecases/precompose_gate.py`, коллаборатор `handle()`, перед обычной
компоновкой): authz-факты берутся из воспринятого `Interlocutor`
(OWNER → owner, TRUSTED/KNOWN → авторизован, GUEST → не авторизован); сперва
`maybe_decide` для owner, затем `maybe_request`; без `sender_id` запрос не заводится, а
ветка owner-решения сработать не может — неопознанный ход никогда не авто-апрувится. Не
подключён — шов инертен, ход без изменений.

## Память диалога: общий тред и пер-персона сигналы (BOB-045 → BOB-058)

BOB-045 атрибутирует каждый ход собеседнику по `sender_id` — Боб помнит, **кто** и о
чём с ним говорил (continuity). Это про атрибуцию, **не** про ограничение знания:
единое recall Боба доступно всем участникам (BOB-051, ниже). Опирается на восприятие
собеседника (`Interlocutor.sender_id`, BOB-019), окно истории `dialogue.recent_turns`
(BOB-044) и multi-party-фундамент BOB-014.

🔴 **BOB-058 — общий диалоговый тред.** Первоначально BOB-045 воспроизводил в
контекст нить ТОЛЬКО текущего собеседника (`recent_episodes_for`), и в группе Боб
терял нить: на «ответь на сообщение X» он отвечал «нет такого сообщения», потому что
видел лишь тред своего собеседника, а не всю комнату. BOB-058 возвращает в контекст
**общий тред топика** — последние `recent_turns` ходов ВСЕХ участников
(`recent_episodes(k)`), уже размеченные `"<имя>: …\nbob: …"`. Атрибуция по `sender_id`
из BOB-045 сохранена, но теперь она обслуживает **пер-персона сигналы** (absence,
анти-повтор) фильтрацией общего треда, а не сужение реплея. Общий тред безопасен:
память едина для закрытой группы (BOB-051), это обычный трафик топика, не
owner-приватка.

### Атрибуция хода: `sender_id`

- **Колонка `episodic_log.sender_id INTEGER`** (nullable) — id собеседника, к
  которому относится ход. `None` для хода без отправителя (тик, дайджест,
  легаси-строка). Зеркалится полем `EpisodicEvent.sender_id`
  (`src/bob/memory/entities.py`); `save_episode` и `recent_episodes` несут его в обе
  стороны.
- **Миграция (идемпотентная, guarded).** `SqliteMemoryRepo._migrate_episodic_sender_id`
  через PRAGMA-проверку колонок добавляет `sender_id` к уже существующей БД
  (`ALTER TABLE … ADD COLUMN`, аддитивно — старые строки берут `NULL`) и создаёт
  индекс `idx_episodic_sender (sender_id, ts)`. Индекс создаётся именно в
  `initialize()` ПОСЛЕ ALTER, а не в `schema.sql`: на колоночно-неполной легаси-БД
  скрипт схемы отрабатывает до ALTER, поэтому `CREATE INDEX` по `sender_id` там
  сослался бы на ещё не существующую колонку.
- **Бэкафилл легаси-строк (best-effort, идемпотентный).**
  `_backfill_episodic_sender_id` заполняет `sender_id` у строк, где он `NULL`,
  разбирая ведущий префикс `"<имя>: "` из контента (чистый helper `_name_prefix`) и
  сопоставляя имя с известным id через карту `name_to_sender_id`. Карта строится в
  `app._backfill_name_map` из `telegram.owner_name` → `telegram.owner_id`; пустая
  карта (имя не настроено) — бэкафилл грациозный no-op, нераспознанные строки
  остаются `NULL` (просто не реплеятся по персоне). Бэкафилл только заполняет `NULL`,
  поэтому повторный `initialize()` — чистый no-op.
- **Read-шов `recent_episodes_for(sender_id, k)`** — зеркало `recent_episodes`, но с
  `WHERE sender_id = ?`: последние `k` ходов именно этой персоны, развёрнутые
  oldest-first для воспроизведения нити по порядку. Приватность здесь — по
  построению запроса: каждый видит только свою нить. `sender_id` также протекает в
  recalled-проекцию (`fts_recall.py`: эпизодная ветка отдаёт `el.sender_id`,
  семантическая — `NULL`), чтобы recall можно было фильтровать по персоне.

### Общий тред + пер-персона сигналы (BOB-058) и единый recall

`HandleMessage._replay_recent_thread` (бывш. `_replay_person_history`) воспроизводит
**общий недавний тред топика** — `recent_episodes(self._recent_turns)`, последние
`recent_turns` ходов всех участников, размеченные `"<имя>: …\nbob: …"`. Один и тот же
тред идёт и в судью (`_judge_turn`), и в reply-путь (на judge-REPLY он уже получен и
не читается дважды). Аргумент `interlocutor` сохранён как **скоуп-хук**: публичная
группа читает общий тред; будущий PRIVATE/DM-скоуп читал бы пер-персона слайс
(`recent_episodes_for(interlocutor.sender_id, …)`), но публичная группа — единственный
режим сегодня, поэтому пер-персона ветка намеренно не провязана.

Пер-персона сигналы над общим тредом фильтруются **по `sender_id`** (устойчиво к
омонимам, ренеймам и `": "` в отображаемом имени — метка `"<имя>:"` только для рендера,
не ключ сигнала; review .3 фикс):

- `_author_key(interlocutor)` = `interlocutor.sender_id` (или `None`, если перцепция /
  идентичность не разрешена → «не фильтровать», полное окно как до перцепции).
- `_history_for_author(history, sender_id)` оставляет из общего треда только эпизоды
  этого автора (`item["sender_id"] == sender_id`), сохраняя порядок oldest-first.
- Так чужой свежий ход **не сбрасывает** absence текущего собеседника, а похожая
  реплика ДРУГОГО участника **не считается** повтором этого человека (BOB-032).

Recall **единый** (BOB-051): `_scoped_recall` (прежнее per-person сужение)
**убран** — полное знание Боба всплывает и owner, и любому участнику группы, без
фильтрации по `sender_id`. Это фикс «расщеплённой памяти» (баг, когда Боб «забывал»
roadmap в разговоре с не-owner: per-person скоуп отрезал owner-факты от чужого
промпта). Память публична в пределах закрытой группы; границей остаются
**привилегии** (см. «Память публична, привилегии — гейт»): гость по-прежнему = ноль
capabilities, ноль owner-внутрянки, отказ owner-командам.

Recall **единый** (BOB-051): `_scoped_recall` (прежнее per-person сужение)
**убран** — полное знание Боба всплывает и owner, и любому участнику группы, без
фильтрации по `sender_id`. Это фикс «расщеплённой памяти» (баг, когда Боб «забывал»
roadmap в разговоре с не-owner: per-person скоуп отрезал owner-факты от чужого
промпта). Память публична в пределах закрытой группы; границей остаются
**привилегии** (см. «Память публична, привилегии — гейт»): гость по-прежнему = ноль
capabilities, ноль owner-внутрянки, отказ owner-командам.

### Длинные паузы: absence-hint

Когда Боб возобновляет разговор с человеком после долгой паузы (ночь, день), он
должен заметить это ПО-ЧЕЛОВЕЧЕСКИ — не скриптовой фразой, а лёгкой контекстной
подсказкой.

- **`domain/personality/absence.py`** (чистый, детерминированный) — `absence_hint(
  last_seen, now, *, threshold_hours) -> str | None`: бакетирует разрыв между
  последним ходом персоны и `now` так, как его ощутил бы человек — счёт часов в
  пределах суток (с русской числовой согласованностью «час/часа/часов» через
  `_plural_hours`), «вчера» до двух суток, «несколько дней» дальше. Возвращает `None`
  (строку не добавлять), если подсказка выключена (`threshold_hours <= 0`), разрыв не
  превышает порог, или разрыв непозитивен (рассинхрон часов / первый контакт). Без
  I/O.
- **Интеграция.** `RecallAssembler.absence_for` (`conversation/usecases/recall_assembler.py`,
  коллаборатор `handle()`) сначала фильтрует общий тред до ходов
  ТЕКУЩЕГО автора (`_history_for_author` по `sender_id`, BOB-058 — чужой свежий ход не
  сбрасывает паузу этого человека), берёт timestamp самого свежего его хода
  (`_last_seen_at`, без лишнего запроса) и зовёт `absence_hint`; результат — одна строка
  `Absence:` в shareable-контексте (`_assemble_shareable_context`, параметр `absence`).
  Это подсказка тиру ответа, не директива фразы; применяется к любому собеседнику
  (owner и гость одинаково), а когда у него нет хода в общем окне — `None` (строку не
  добавлять, как при пустой истории). Детерминирована при инъецированном `Clock`.

### Конфигурация

- `dialogue.absence_hint_hours` (по умолчанию `8.0`) — порог паузы (часы), который
  нить персоны должна ПРЕВЫСИТЬ, чтобы в контекст вошла absence-подсказка. `0`
  отключает; отрицательное значение отвергается как ошибка конфигурации
  (`app._build_absence_hint_hours`, валидируется и в `HandleMessage`).
- `dialogue.recent_turns` (по умолчанию `14`, BOB-044) — то же окно, что задаёт
  глубину реплея общего треда топика (BOB-058).
- `telegram.owner_name` (по умолчанию пусто) — отображаемое имя owner, используется
  ТОЛЬКО бэкафиллом для атрибуции легаси-строк по префиксу контента.

## Адресность: кому сообщение и стоит ли отвечать (BOB-023)

Живой человек в чате знает, когда обращаются к нему, а когда нет, и на риторическое
может молча лайкнуть или просто прочитать. BOB-023 даёт Бобу то же: он **воспринимает
адресность** хода и решает — **вступить, молча лайкнуть или промолчать**, — поэтому
больше не встревает в каждый разговор. Это перцептивный слой поверх восприятия
собеседника (BOB-019) и аппетита (.2a); он лишь **добавляет** «молчать, если не к
нему», поэтому гостевой инвариант BOB-019 цел. Заодно это фундамент turn-taking под
BobNet (реплики отвечают по очереди, а не галдят хором) и маркер theory-of-mind.

### Детектор адресности (чистый домен)

`domain/personality/addressivity.py` — чистый, детерминированный, без I/O и рандома,
поверх сигналов, уже извлечённых gateway'ем.

- **`Addressivity`** — `DIRECTED_TO_BOB` / `DIRECTED_TO_OTHER` / `AMBIENT` (восприятие,
  не решение).
- **`classify_addressivity(*, text, mentions_bob, reply_to_sender_id, bob_user_id,
  others_present)`** относит ход по приоритету сигналов: **к Бобу** —
  `mentions_bob`, либо reply на сообщение Боба (`reply_to_sender_id == bob_user_id`),
  либо имя-обращение в начале («Боб, …» — первое слово плюс разделитель-запятая, так
  что «Боб классный» — не обращение); **к другому** — reply на чужое сообщение;
  **ambient** — ни reply, ни mention, ни имя. Прямое обращение всегда перевешивает.
  `others_present` здесь не влияет на классификацию (его читает политика) — он в
  сигнатуре ради единообразия вызова.
- **`others_present(history, *, current_sender_name)`** — лёгкая эвристика «в недавней
  истории треда есть НЕ текущий собеседник» (тред не 1:1) поверх уже реплеенной
  истории вида `"<sender>: <text>\nbob: <reply>"`: реплика Боба не считается, в личном
  1:1 owner↔Bob все метки совпадают → `False`, появился третий → `True`.

### Политика отклика (perception → исход)

`decide_response(addressivity, *, interest, others_present, roll, thresholds)` →
**`ResponseOutcome`** `ENGAGE` / `REACT` / `SILENT`. `roll` — одна seeded-проба
`[0, 1)` (из общего RNG, чтобы ход воспроизводился), `interest` — интерес к теме из
аппетита .2a.

- **`DIRECTED_TO_BOB` → всегда `ENGAGE`** (никогда `SILENT`): прямое обращение не
  игнорируется; дальше форму решают engagement/`REACT_ONLY` как прежде.
- **`DIRECTED_TO_OTHER` → `SILENT`** по умолчанию (не лезет в чужой 1:1); **изредка**
  вклинивается (`ENGAGE`), только если `interest` берёт высокий порог
  `barge_in_interest` И редкий `roll` ниже `barge_in_freq`. Не перехватывает чужой
  диалог.
- **`AMBIENT`** в 1:1 (`not others_present`) → `ENGAGE` (пространство Боба). С другими
  — чаще `SILENT` или `REACT` (молчаливый лайк присутствия), а при высоком интересе и
  удачном (более частом, чем для чужого диалога) `roll` — `ENGAGE`.

Пороги — frozen `AddressivityThresholds` (`barge_in_interest` `0.8` >
`ambient_interest` `0.6`; `barge_in_freq` `0.05` ≤ `ambient_barge_in_freq` `0.15`;
`react_chance` `0.3`), инъецируются из конфигурации `addressivity.*`
(`infrastructure/config/loader.py`, собираются в `app.py` через
`_build_addressivity_thresholds`). Значения по умолчанию консервативны: в чужой
разговор Боб почти не лезет.

### Где это в потоке хода

`HandleMessage._decide_addressivity` (см. «Поток обработки», шаг 3) после perceive
читает `others_present` (через шов истории), зовёт `classify_addressivity` и
`decide_response` с одной seeded-пробой из общего RNG. `bob_user_id` читается лениво
через `bob_user_id_source` (`multibot.bob_user_id`, резолвится на старте, см.
«Сигналы адресности»). Исход: `SILENT` — ранний выход без ответа и реакции; `REACT`
— лайк через тот же путь `REACT_ONLY` (деградирует в краткий ack, если реактор не
подключён); `ENGAGE` — ход идёт дальше в обычную компоновку. Непровязанный
`bob_user_id_source` даёт `None`, и без сигналов адресности ход всегда `ENGAGE` —
поведение как до BOB-023.

С BOB-049 эта лестница — **легаси-путь** гейта хода: на живом пути её исход больше не
решает, отвечать ли. Те же структурные сигналы (`_addressivity_signals`: поштучная и
эффективная адресность, `others_present`, `floor_engaged`, `reply_to_bob`) теперь
питают семантического судью как **входы**, которые он взвешивает по смыслу (см.
«Семантическое решение об отклике»). `_decide_addressivity` + `decide_response` работают
лишь когда судья не провязан или отправитель не воспринят.

## Непрерывность диалога: conversational floor (BOB-025)

Поштучная адресность BOB-023 классифицирует каждое сообщение в изоляции, и как только
в треде появляется третий, безметочные реплики owner'а уходят в «ambient при других» —
Боб теряет адресата, едва пропадает метка «Боб, …». Люди так не общаются: после «Боб,
как дела?» следующее «а ты видел?» всё ещё к Бобу — обращение «прилипает», пока разговор
явно не повернёт к другому. BOB-025 даёт Бобу память этой нити: над поштучной адресностью
живёт трекер **разговорной реплики** (conversational floor) — кто сейчас адресат живого
обмена в треде. Пока floor держит Боб, безметочная реплика **от любого участника** (owner
или гость) читается как обращённая к нему. Ключевой принцип: непрерывность привязана **к
адресату** (Бобу), а не к говорящему — важно, что разговор идёт с Бобом, а не кто именно
произнёс реплику. Цель BOB-023 при этом цела: безметочное поднимается к Бобу **только**
пока он сам держит живой floor, чужой диалог двоих он по-прежнему не перехватывает.
Гостевой инвариант BOB-019 по правам не затронут — floor меняет лишь распознавание
адресности, не права. Это фундамент turn-taking под BobNet.

### Трекер floor (чистый домен)

`domain/personality/conversation_floor.py` — чистый, детерминированный по инъектированному
`now`, без I/O и рандома (часы живут в application, персист — за портом).

- **`FloorHolder`** — `BOB` / `OTHER` / `IDLE`: кто держит реплику. `BOB` — безметочное
  от любого участника поднимается к нему; `OTHER` — реплику держит другой человек (Боб
  отступает); `IDLE` — реплику никто не держит (безметочное остаётся `AMBIENT`).
- **`ConversationFloor`** (frozen value object) — `holder`, `holder_id` (id человека при
  `OTHER`, иначе `None`), `since` (когда держателя в последний раз подтвердили; `None` при
  `IDLE`), `idle_streak` (сколько безметочных реплик подряд прошло без участия Боба — для
  распада по молчанию). `idle_floor()` — фабрика дефолтного `IDLE`-floor.
- **`FloorConfig`** — тюнинг: `timeout_seconds` (`300` ≈ 5 мин — жизнь floor без
  переподтверждения) и `reset_after_silent` (`2` — после стольких безметочных реплик
  подряд, на которые Боб промолчал, floor=БОБ распадается в `IDLE`). Оба должны быть > 0.
- **`advance_floor(floor, *, addressivity, sender_id, directed_to_id, bob_replied, now,
  config)`** — чистый переход floor по одному ходу, по приоритету: **Боб ответил этим
  ходом** (`bob_replied`) → `BOB(since=now, streak=0)` (ответ Боба «приклеивает» реплику
  к нему, US-1/US-2); иначе по адресности — `DIRECTED_TO_BOB` → `BOB` (прямое обращение
  переберёт floor); `DIRECTED_TO_OTHER` → `OTHER(holder_id=directed_to_id)` (явный поворот
  к другому); `AMBIENT` → пока floor=БОБ и жив, реплика в нить держит Боба (рефреш `since`),
  но молчание Боба растит `idle_streak`, и на `reset_after_silent` floor распадается в
  `IDLE`; если floor не у Боба или истёк по тайм-ауту — `IDLE`. `sender_id` принимается
  ради единообразия вызова и будущей гранулярности, на переход пока не влияет.
- **`resolve_addressivity(per_message, floor, *, now, config)`** — поднимает эффективную
  адресность по непрерывности: если поштучная адресность `AMBIENT` И floor держит Боб И
  floor жив (`now - since <= timeout`) → `DIRECTED_TO_BOB`; иначе `per_message` возвращается
  как есть. Прямое обращение и явный поворот к другому проходят без изменений, а `AMBIENT`
  при чужом или распавшемся floor остаётся `AMBIENT` (Боб не перехватывает чужое).

### Персист floor (порт + Sqlite)

- **`ConversationFloorStore`** (`Protocol`, `domain/ports/conversation.py`) — `load(chat_id, thread_id)`
  / `save(chat_id, thread_id, floor)`. Ключ — тред (`thread_id`, `None` = главный чат /
  без forum-топика), потому что floor — свойство одного живого обмена, не человека. `load`
  для невиданного треда возвращает дефолтный `IDLE`-floor.
- **`SqliteConversationFloorStore`** (`infrastructure/persistence/conversation_floor_store.py`)
  реализует порт над таблицей `conversation_floor` — одна строка на `(chat_id, thread_id)`.
  Домен мапится в строку и обратно (`holder` — значение enum, `since` — ISO-8601 текст).
  `thread_id` хранится `NOT NULL` с sentinel `-1` для `None` (SQLite считает `NULL`
  различными в PRIMARY KEY, что сломало бы UPSERT). `save` — `INSERT … ON CONFLICT DO
  UPDATE` (floor обновляется каждый ход), весь SQL параметризован.

### Интеграция в ход (поверх BOB-023)

Шов floor встроен в `HandleMessage` поверх поштучной адресности. На каждом ходу:
`classify_addressivity` даёт поштучную (RAW) адресность → загружается floor для
`(chat_id, thread_id)` → `resolve_addressivity` даёт **эффективную** адресность → политика
`decide_response` работает на **эффективной** адресности → после хода `advance_floor`
обновляет floor на **RAW** per-message сигнале плюс факте ответа Боба и сохраняет его.
`bob_replied=True` ставится только на ENGAGE-ходу, который реально дошёл до ответа;
SILENT / REACT / react-only ход двигает floor с `bob_replied=False` (так молчание растит
`idle_streak`). Floor питается RAW-сигналом (а не поднятой адресностью), чтобы отражать
реальный ход разговора. Ключ треда — `_floor_thread_id`: пока в событии нет forum
`thread_id`, floor ключуется по `chat_id` (`None` = главный чат) — шов под будущий
per-topic ключ.

Слой best-effort с обеих сторон: падение стора при загрузке/резолве или при сохранении не
ломает ход — Боб откатывается на поштучную адресность BOB-023. Floor выключаем флагом
`addressivity.floor.enabled`: непровязанный стор ИЛИ `floor_enabled=False` → эффективная
адресность равна поштучной (ровно поведение BOB-023). Конфигурация — `addressivity.floor.*`
(`infrastructure/config/loader.py`): `enabled` (`true`), `timeout_seconds` (`300`),
`reset_after_silent` (`2`), собирается в `app.py` в `FloorConfig` и провязку стора.

## Семантическое решение об отклике (BOB-049)

Живой человек не пропускает каждое сообщение через цепочку `if/else` — он **понимает**
сказанное в контексте и решает по смыслу, ответить ли словами, поставить эмодзи или
промолчать. BOB-049 даёт Бобу то же: лестница эвристик (адресность BOB-023/025 +
форменный гейт выражения BOB-018) заменена **одним смысловым суждением** за швом. Это
решение по СМЫСЛУ для **любого** собеседника — owner, друг или гость, — а не по
`is_owner`: структурные сигналы (адресность / mention / reply / другие участники /
floor) становятся **входами**, которые судья взвешивает, а не правилами. Authz при этом
ортогонально (два слоя BOB-019): семантика решает **социальный отклик**, не доступ —
гостевые ограничения на пути `REPLY` неизменны.

### Шов суждения (порт + чистый протокол + Tier-0 реализация)

- **`domain/personality/response_choice.py`** — типы-значения и порт. `ResponseIntent`
  (`REPLY` / `REACT` / `IGNORE`: ответить словами, поставить выбранный по смыслу эмодзи
  или промолчать); `ResponseChoice{intent, emoji, reason}` (frozen-исход; `emoji` задан
  только на `REACT`, `reason` — короткое «почему» для логов, пользователю не видно);
  `ResponseContext` (frozen-**вход**: `text`, `interlocutor` как соц-контекст,
  `recent_thread` по персоне, подсказки `mentions_bob` / `reply_to_bob` / `addressivity`
  / `others_present` / `floor_engaged`, `mood_tone`); **`ResponseJudge`** (`Protocol`,
  инъектируемый порт — `decide(ctx) -> ResponseChoice`, фейк в тестах для детерминизма).
- **`domain/personality/response_judgment.py`** — чистый Tier-0 wire-протокол (без I/O и
  RNG, юнит-тестируем без модели). `build_judgment_user_prompt(ctx)` сворачивает контекст
  в промпт; `RESPONSE_JUDGE_SYSTEM_PROMPT` задаёт задачу и помеченный формат вывода
  (`intent:` / `emoji:` / `reason:`); `parse_response_choice(raw)` маппит ответ модели в
  `ResponseChoice` (терпим к регистру/пробелам, на мусоре поднимает
  `ResponseJudgeParseError`, а не молча подставляет дефолт — чтобы .3 поймал реальный
  сбой); `validate_reaction_emoji(raw)` сверяет эмодзи с набором свободных реакций
  Telegram (`STANDARD_REACTION_EMOJI`), снимая variation-selector, вне набора → `None`
  (тогда на `REACT` подставляется тёплый `DEFAULT_WARM_EMOJI` `🥰`).
- **`infrastructure/llm/response_judge.py`** — `LlmResponseJudge`, Tier-0 реализация
  порта: один дешёвый локальный вызов через `LLMRouter` (`TaskType.RESPONSE_JUDGE` →
  Tier 0, как другие классификаторы). Тонкая оболочка — всё формирование решения чисто в
  домене; **не глотает** сбои (ошибка модели/роутера или `ResponseJudgeParseError`
  пробрасывается для .3).
- **`application/usecases/decide_response.py`** — `DecideResponse`: тонкий use-case над
  швом. Собирает `ResponseContext` из частей хода и делегирует одно решение
  инъецированному судье. Своей политики не несёт — структурные сигналы проходят как
  входы, не как правила.

### Ветвление в `handle_message`

`TurnGate.gate` (`conversation/usecases/turn_gate.py`) — гейт хода (см. «Поток обработки»,
шаг 3), тонкий координатор над `AddressivityPerceiver` + `FloorManager` + `EssentialRunner`
+ инъектированным судьёй `decide_response`. С провязанным судьёй и воспринятым отправителем
он собирает контекст (включая **общий недавний тред топика**, BOB-058), зовёт судью и по
`intent` ветвит:

- **`REPLY`** → `_ReplyGate` → `handle()` идёт в компоновку и отправку (гостевой путь BOB-019
  цел; уже воспроизведённая нить прокидывается в compose, чтобы не читать дважды).
- **`REACT`** → ставит выбранный **по смыслу** эмодзи на сообщение через инъектированный
  реактор (заменяет таблицу mood→эмодзи BOB-018 как источник; валидация против набора
  Telegram; без реактора — чистый no-op, решение всё равно персистится).
- **`IGNORE`** → Боб молчит.

`REACT` и `IGNORE` завершаются внутри гейта (возврат `None`): 🔴 персистят ход (`(реакция:
<emoji>)` / `(промолчал)`, BOB-045) через инъектированный persist-колбэк, двигают floor с
`bob_replied=False` и ставят owner-activity маркер (тоже колбэк — гейт не держит политики
персиста). Внутренний intent→floor-outcome маппинг (`_OUTCOME_FOR_INTENT`) и non-reply
persist-маркер живут теперь при `TurnGate`. Genuine `REACT` / `IGNORE` — это **успех**, а не
сбой (без ретрая и нотиса). Непровязанный судья ИЛИ невоспринятый отправитель → легаси-путь
BOB-023/025 + `REACT_ONLY` BOB-018 (обратная совместимость; провязка в `app.py`:
`decide_response=DecideResponse(judge=LlmResponseJudge(router=router))`). На счастливом пути
(`REPLY`, ход дошёл до ответа) floor двигает уже `handle()` через
`TurnGate.advance_floor_after_turn(..., bob_replied=True)`.

## Полный Боб или честный GUPPI-нотис (BOB-049 .3)

Принцип ROADMAP #10: пользователь получает **полного Боба или честный нотис о сбое**, но
никогда — деградированный полуответ («уверенный бред»). Существенные шаги хода —
**семантическое суждение** и **генерация ответа** — обёрнуты ограниченным ретраем;
опциональные флейворы (протекающая внутренняя жизнь / колбэк / фасцинация) при сбое тихо
опускаются.

- **`application/reliability.py`** — `call_with_retry(operation, *, attempts,
  backoff_seconds, sleep)`: дженерик-примитив, вызывает `operation` до `attempts` раз,
  между попытками ждёт `sleep(backoff_seconds)` через **инъецированный** шов сна
  (`asyncio.sleep` в проде, фейк в тестах — детерминизм без реальной задержки); если все
  попытки упали, перебрасывает **последнюю** ошибку. Политика-free (какие шаги
  существенны и что делать при стойком сбое — в вызывающем). Отличается **по дизайну** от
  `runtime/retry.retry_with_backoff`: тот ретраит только транзиентные фолты фоновых
  тиков; здесь для user-facing хода ретраю подлежит **любой** сбой существенного шага
  (таймаут, обрыв связи ИЛИ непарсимый ответ модели).
- **`EssentialRunner.run(operation, *, step)`** (`application/usecases/essential_runner.py`)
  оборачивает существенный шаг: `call_with_retry` (умолчания `_DEFAULT_ESSENTIAL_ATTEMPTS=3`
  всего попыток, `_DEFAULT_ESSENTIAL_BACKOFF_SECONDS=0.5`, тюнятся через `reliability.*`); при
  стойком сбое — `_EssentialStepError(step)`. Оба существенных шага проходят через него:
  суждение (внутри `TurnGate`) и генерация ответа (внутри `VoiceComposer` — оба держат
  `EssentialRunner` как инъектированный шов).
- **Обработка сбоя.** `EssentialRunner.handle_failure` 🔴 **не** шлёт деградированный ответ:
  персистит ход пользователя (`_OUTAGE_MARKER` `(нет ответа: проблемы со связью)` — так
  сообщение не теряется, через инъектированный persist-колбэк) и зовёт `notify_outage`. Шов
  `OutageNotifier` (порт) реализует `_GuppiOutageNotifier` (`app.py`): шлёт фиксированный
  `GUPPI_OUTAGE_TEXT` `⚠️ Проблемы со связью — Боб временно недоступен` ботом Боба в его
  топик. Третье-личный системный голос читается как **GUPPI** сообщает о проблеме, а не Боб
  грубит. Непровязанный нотифер → ход всё равно завершается чисто (без видимого нотиса).
  Best-effort: сбой самой отправки нотиса логируется и проглатывается.
- **Опциональные флейворы.** `GroundedAddons.safe(addon, *, name)`
  (`personality/usecases/grounded_addons.py`) оборачивает каждую grounded-добавку: при сбое
  она логируется и опускается (возврат `""`), а ядро ответа «полного Боба» всё равно уходит —
  флаки-добавка **никогда** не триггерит outage-нотис.

## Восприятие реакций на сообщения Боба (BOB-050)

BOB-049 учит Боба **понимать**, отвечать ли на сообщение собеседника. BOB-050 — зеркало
для другой стороны: когда кто-то ставит или снимает эмодзи-реакцию на **собственное**
сообщение Боба, Боб это **чувствует** и понимает по смыслу, что реакция значит на этом
сообщении от этого человека, — а не сверяет эмодзи с таблицей. Это шаг к интерсубъективности:
Боб замечает, что его услышали, и это его меняет — ограниченно, по тому же пути социального
заражения, что и текст (BOB-033).

🔴 **Весь путь восприятия реакции декоративен и опционален.** Это флейвор, не существенный
шаг хода: любой сбой (ошибка судьи, пропавшее сообщение, сбой хранилища) ловится и тихо
опускается — он **никогда** не триггерит GUPPI-нотис и не ломает обычные ответы Боба.
🔴 **Authz (два слоя BOB-019):** гость, поставивший реакцию, чувствуется и запоминается с
привязкой к **гостю**; путь пишет только данные о персоне реактора про **собственное**
сообщение Боба, поэтому owner-приват не утекает, а per-person память изолирована.

### Транспорт: `message_reaction`-апдейт и связь `bob_message_id`

Telegram не шлёт реакции в наборе апдейтов по умолчанию, поэтому их надо запросить явно.

- **`infrastructure/telegram/gateway.py`** — `ALLOWED_UPDATES` добавляет `message_reaction`
  и `message_reaction_count` к запрашиваемым типам. `TelegramGateway.intake_reaction(update)`
  переводит входящий апдейт в событие: per-user `message_reaction` даёт диф
  `old_reaction → new_reaction` (что реактор **поставил** и что **снял**) плюс личность
  реактора; анонимный `message_reaction_count` (приватная группа без user) — только сводку
  эмодзи без «кто». Фильтр **`BobMessageFilter`** (порт) отсекает реакции на чужие
  сообщения — публикуется только реакция на сообщение, которое сам Боб отправил; иначе
  апдейт тихо отбрасывается. `is_reaction_update`, `_reaction_diff`, `_reaction_emojis` —
  чистые помощники разбора.
- **`application/runtime/events.py`** — событие **`BobMessageReaction`** (frozen, имя
  `BOB_MESSAGE_REACTION` `telegram.bob_message_reaction`): `chat_id`, `message_id`,
  `emoji_added` / `emoji_removed` (диф), `reactor_sender_id` / `reactor_name` (кто, BOB-019;
  `None` для анонимной реакции).
- **Связь с тем, что Боб сказал.** Колонка `episodic_log.bob_message_id` (`schema.sql`)
  хранит Telegram message_id **исходящего** ответа Боба за этот ход, чтобы позднюю реакцию
  можно было связать с тем, **что** Боб сказал. Миграция идемпотентна, как в BOB-045:
  `SqliteMemoryRepo._migrate_episodic_bob_message_id` гардом добавляет колонку и индекс
  `idx_episodic_bob_message_id` на пред-существующих БД (existing-строки берут `NULL`).
  `MemoryEvent.bob_message_id` несёт его в персист; `HandleMessage` берёт message_id из
  `gateway.reply(...)` (теперь возвращает id отправленного сообщения) и кладёт в эпизод.
  `episode_by_bob_message_id(id)` — обратный поиск; `app.py` `_BobReactionFilter` строит над
  ним фильтр «это сообщение Боба».
- **Мульти-бот.** `MultiBotGateway` маршрутизирует реакцию только через **внутренний** шлюз
  бота Боба (`_route_reaction`), чтобы копия GUPPI не породила дубликат события; реакция не
  считается «сообщением».

### Семантический шов: `ReactionJudge` (Tier-0)

Зеркало `ResponseJudge` (BOB-049): один смысловой судья вместо таблицы эмодзи→настроение.

- **`domain/personality/reaction_meaning.py`** — типы-значения и порт. `ReactionContext`
  (frozen-**вход**: `emoji`, `added` — поставлена или снята, `bob_message_text` —
  на что среагировали, `reactor` как соц-контекст + `reactor_warmth`, `recent_thread`);
  `ReactionMeaning` (frozen-**исход**: `interpretation` — короткий смысл для памяти/логов,
  `mood_delta` с ограниченными знаком+величиной **из смысла, а не из эмодзи**, `warmth_nudge`
  к реактору, `worth_acknowledging`); **`ReactionJudge`** (`Protocol`, инъектируемый порт —
  `interpret(ctx) -> ReactionMeaning`, фейк в тестах).
- **`domain/personality/reaction_judgment.py`** — чистый Tier-0 wire-протокол (без I/O и
  RNG). `build_reaction_user_prompt(ctx)` сворачивает контекст в промпт;
  `REACTION_JUDGE_SYSTEM_PROMPT` задаёт задачу и помеченный формат (`interpretation:` /
  `sentiment:` / `intensity:` / `acknowledge:`) и подсказывает, что **снятая** реакция
  склоняется в лёгкий негатив/неуверенность. `parse_reaction_meaning(raw)` маппит ответ:
  знак сентимента и величину интенсивности сворачивает в **ограниченный** `MoodDelta`
  (шаг ≤ `0.25`, внутри полосы BOB-030) и `warmth_nudge` (доля от величины, hard-cap
  `0.12`), `worth_acknowledging` ставится только при положительном смысле; на мусоре —
  `ReactionJudgeParseError`, а не молчаливый дефолт (чтобы декоративный путь уронил реальный
  сбой, а не действовал по догадке).
- **`infrastructure/llm/reaction_judge.py`** — `LlmReactionJudge`, Tier-0 реализация порта:
  один дешёвый локальный вызов через `LLMRouter` (`TaskType.REACTION_JUDGE` → Tier 0). Тонкая
  оболочка; **не глотает** сбои — ошибка модели/роутера или парс-ошибка пробрасывается, и
  декоративный use-case её опускает.

### Эффекты: настроение, отношения, память, «меня услышали»

- **`domain/personality/reaction_effect.py`** — чистое ядро «реакция меняет Боба».
  `apply_reaction_to_mood(mood, meaning, *, baseline, lift_rate)`: тёплая реакция сперва
  тянет настроение долей к базлайну (`Mood.lift_toward`, тот же путь заражения, что и текст
  BOB-033 — «вытесняет накопленный минус»), затем ложится ограниченная дельта; холодная/
  отстранённая лифт пропускает и только слегка проседает. `nudge_relationship_warmth(rel,
  meaning)` двигает **только** ось warmth к реактору на ограниченный `warmth_nudge` (BOB-014;
  доверие/уважение накапливаются обменами, не реакцией). `NotableReaction` — лёгкая запись
  «меня услышали», создаётся только при `worth_acknowledging`.
- **`application/usecases/perceive_reaction.py`** — `PerceiveReaction`, сердце фичи. Подписан
  на `BOB_MESSAGE_REACTION` через `build_application` (`_as_reaction_handler`). На событие:
  ищет эпизод по `bob_message_id` (не сообщение Боба → мягкий пропуск), воспринимает реактора
  через `ReactorResolver`, грузит отношение, собирает `ReactionContext`, зовёт судью и даёт
  смыслу изменить Боба — настроение (BOB-033, ограниченно), warmth к реактору (BOB-014),
  per-person эпизод `reaction_received` «<кто> отреагировал <emoji> на моё „<кратко>" —
  <смысл>» с привязкой к **реактору** (BOB-045), и — при `worth_acknowledging` — запись в
  общий `NotableReactionStore`. **Анонимная** реакция (нет `reactor_sender_id`) → только
  лёгкий фиксированный лифт настроения, без памяти и отношения (нет «кто»). Метод `perceive`
  🔴 обёрнут try/except: любой сбой логируется и опускается.
- **`social/usecases/reactor_perception.py`** — `ReactorPerception`, реакция-двойник
  `SenderPerception`: композирует неизменный `Authorizer` с чистой `classify`, превращая
  id+имя реактора в `Interlocutor` (owner / known / guest + trust). Это **восприятие**, не
  гейт: читает `is_owner` (по личности) и `is_authorized` (chat-scoped), но решения о доступе
  не меняет — путь касается только per-person данных о собственном сообщении Боба.
- **`infrastructure/persistence/notable_reaction_store.py`** — `KvNotableReactionStore` над
  обобщённой таблицей `kv` (без новой схемы): одна JSON-строка с **последней**
  `NotableReaction`. `record` перезаписывает, `latest` читает, `clear` пишет пустой
  tombstone (чистый consume). Пропавшая/непарсимая строка → `None` (no-op), чтобы
  битая запись не ломала декоративный путь.

### Изредка вслух: «вижу, тебе зашло про…»

- **`domain/personality/reaction_aloud.py`** — чистый помощник `acknowledgment_hint(note)`:
  превращает `NotableReaction` в **одну** лёгкую compose-подсказку (кто, эмодзи, краткий
  отрывок того, что Боб сказал), оформленную как **опциональную** («если к месту, не
  обязательно») — реплай-тир вплетает её сам или пропускает, никогда не зачитывает скрипт.
- **`RecallAssembler.acknowledgment_for(interlocutor)`** — низкочастотная per-person логика
  в compose: подсказка всплывает, только если хранилище провязано, на записи есть notable
  реакция, её реактор — **именно этот** собеседник (🔴 per-person/authz BOB-019: реакция
  гостя не всплывёт owner-у и наоборот; у анонимной реакции нет «кого» отмечать) и сидовый
  бросок прошёл порог `acknowledge_reaction_freq` (умолчание `0.15`, тюнится через
  `dialogue.acknowledge_reaction_freq`). После выдачи запись `clear()`-ится (consume-once),
  поэтому Боб отмечает момент **максимум один раз** — не назойливо. Обёрнута `_safe_addon`:
  сбой хранилища тихо опускается.

**Общий `notable_reaction_store`.** `PerceiveReaction` (пишет) и `HandleMessage` (читает +
consume) делят **один** инстанс `KvNotableReactionStore` — иначе написанная реакция была бы
невидима подсказке и Боб никогда не отметил бы, что его услышали. Провязка в `app.py`:
`PerceiveReaction(judge=LlmReactionJudge(router=router), …, notable=notable_reaction_store)`
подписан на `BOB_MESSAGE_REACTION`, а тот же стор инъектирован в `HandleMessage`.

## Краткость по запросу: длина ответа как характер (BOB-024)

Живой человек на простой закрытый вопрос («ты тут?», «во сколько?», «получилось?»)
отвечает коротко и разворачивается лишь когда тема, настроение или сам вопрос этого
стоят. BOB-024 даёт Бобу ту же осмысленную длину: его реплика перестаёт быть константой
и становится **функцией характера** — длина ≈ answer-demand × интерес × настроение/
аппетит. Это слой поверх адресности (BOB-023): адресность решает, *отвечать ли вообще*;
краткость — *насколько коротко*, если ход уже взят (`ENGAGE`). Краткость достигается
**байесом** — сильной директивой плюс few-shot, которые бьют verbosity-prior Qwen, — а
не одной пост-обрезкой. SILENT и гостевой инвариант не затрагиваются: BOB-024 влияет лишь
на длину *выбранного* ответа.

### Answer-demand и решение о многословии (чистый домен)

`domain/personality/brevity.py` — чистый, детерминированный, без I/O и рандома.

- **`AnswerDemand`** — `LOW` / `MEDIUM` / `HIGH`: сколько развёрнутости объективно требует
  само сообщение (восприятие, не решение).
- **`classify_answer_demand(*, text)`** — лёгкая лексическая эвристика (рус+eng) над
  текстом по приоритету сигналов: **HIGH** — явная просьба развернуть
  («расскажи/объясни/сравни», explain), открытое вопросительное слово
  («почему/как это/что думаешь», why/how does) или много-частный вопрос (несколько «?»);
  **LOW** — закрытый/короткий вопрос (маркеры «во сколько», «получилось», are you), очень
  короткий вопрос (мало слов, нет открытых маркеров) или очень короткая реплика без
  вопроса; **MEDIUM** — всё прочее. Пустой/`None` текст → `MEDIUM`.
- **`Verbosity`** — `TERSE` / `NORMAL` / `EXPANSIVE`: финальная развёрнутость хода
  (решение, не сигнал).
- **`decide_verbosity(*, demand, interest, mood_valence, engagement, form_hint, roll,
  is_owner, thresholds)`** — чистое решение по шагам: (1) **база** по demand
  (LOW→TERSE, MEDIUM→NORMAL, HIGH→EXPANSIVE); (2) **интерес↑** (US-4) — при высоком
  `interest` и редком seeded-`roll` ступень поднимается на одну (изредка, «увлёкся»);
  (3) **настроение/аппетит↓** (US-3) — плохой `mood_valence` и низкий `engagement`
  складываются, каждый режет на ступень (вместе — на две), а `TERSE`-`form_hint` при
  мягко-плохом настроении добавляет ещё наклон вниз; (4) **анти-обрубок** (US-5) — при
  `demand == HIGH` и `is_owner` итог не опускается ниже `NORMAL`, что бы ни говорили
  настроение/аппетит (прямой содержательный запрос owner не получает односложный «отшив»).
  `roll` — одна seeded-проба `[0, 1)` из общего RNG, так что ход воспроизводится.
- **`BrevityThresholds`** (frozen) — пороги тюнинга, инъецируются из `brevity.*`. Дефолты
  консервативны: `interest_upgrade` `0.85`, `upgrade_freq` `0.1`, `bad_mood` `-0.5`,
  `low_engagement` `0.25`, `tilt_mood` `-0.25`.
- **`clamp_reply(text, *, max_chars)`** — опциональный страж длины (см. ниже): берёт
  первую законченную мысль до знака конца предложения, без перегенерации и без обрезки на
  полуслове; текст в пределах `max_chars` или без знаков конца предложения отдаётся как
  есть.

`engagement` для решения — числовой аппетит хода: `appetite_of(level)`
(`domain/personality/engagement.py`) переводит четырёхуровневый `EngagementLevel` в
скаляр `[0, 1]` (`FULL` `1.0`, `PLAYFUL` `0.7`, `TERSE` `0.3`, `DECLINE` `0.0`) — строго
убывающий, так что таящий аппетит всегда тянет длину вниз, никогда вверх.

### Краткость байесом — директива + few-shot

`voice.brevity_directive(verbosity)` (`domain/personality/voice.py`) — **единственная**
финальная директива длины (заменила прежний мягкий `form_hint`-путь
`_FORM_HINT_DIRECTIVE`, так что у хода больше нет двух конкурирующих сигналов). Для `TERSE`
это **сильная** инструкция (одной фразой, без преамбул/списков/воды, как живой человек в
чате), для `EXPANSIVE` — разрешение развернуться, для `NORMAL` — нейтрально (директивы нет).
`voice.brevity_few_shot(verbosity)` подмешивает для `TERSE` few-shot «простой вопрос →
короткий ответ» в голосе Боба — именно примеры (а не правило) перебивают verbosity-prior
модели надёжнее любой директивы. `NORMAL` / `EXPANSIVE` few-shot не несут.

### Опциональный страж длины

После генерации, **только** если `demand == LOW` и страж включён
(`brevity.length_guard.enabled`, по умолчанию **выкл**), `HandleMessage._guard_reply_length`
зовёт `clamp_reply` и мягко ужимает переразвёрнутый ответ на простой вопрос до первой
законченной мысли. Это страховка, а не основной рычаг — основной механизм краткости —
байес директивы и few-shot.

### Где это в потоке хода

`HandleMessage._decide_verbosity` (см. «Поток обработки», шаг 4) считается **после**
адресности (BOB-023) на ходе `ENGAGE`: `classify_answer_demand` по тексту хода, затем
`decide_verbosity` по demand, интересу (из аппетита .2a), настроению/аппетиту
(`appetite_of`), `form_hint` (BOB-018) и seeded-`roll` из общего RNG. `is_owner` берётся из
воспринятого собеседника (`InterlocutorKind.OWNER`, BOB-019). Решённая `Verbosity` идёт в
`_system_prompt_for`, который дописывает `brevity_directive` + `brevity_few_shot` к промпту,
а после генерации — опциональный страж длины. Пороги собираются в `app.py`
(`_build_brevity_thresholds`), страж — `_build_length_guard_enabled` /
`_build_length_guard_max_chars` из секции `brevity.*` (`infrastructure/config/loader.py`).

## Резилентность тиков (retry/backoff + изоляция)

Чтобы петля была надёжно живой 24/7, heartbeat-тики переживают транзиентные
сетевые сбои. `retry_with_backoff` (`application/runtime/retry`) повторяет операцию
на **транзиентных** ошибках (сетевые сбои соединения aiohttp, включая
`Server disconnected`, таймауты, 5xx) с ограниченным экспоненциальным backoff;
**перманентная** ошибка (4xx, баг, структурная) пробрасывается сразу, чтобы
backoff не маскировал дефект. `sleep` инъецируется для детерминизма тестов.

Резилентность слоёная: `periodic(...)` оборачивает тик в `retry_with_backoff`
(когда задана `RetryPolicy`), затем **изолирует** то, что тик в итоге бросил,
логируя и продолжая — так одна сбойная итерация не валит heartbeat и не глушит
соседние тики; отмена на остановке рантайма пробрасывается чисто.

## Capability-шов (навыки GUPPI)

Стабильный, forward-compatible шов навыков — фундамент, на котором поедут «Память»
и «Автономность». Это именно **шов**, не полная плагин-машинерия (sandbox,
авто-дискавери, self-creation придут позже за тем же контрактом). По канону книги
**GUPPI — исполнитель** того, что Боб решает применить.

- **Контракт `Capability`** (`domain/ports/capabilities.py`): `name`, `description`,
  `input_schema` (JSON-схема), `permission` (`safe` исполняется напрямую;
  `confirm` — задел под approval-гейт) и `async execute(args)`.
- **`CapabilityRegistry`** (`application/capabilities`): `register` (имя
  уникально), `manifest` (рендер навыков в OpenAI-определения `tools`),
  `dispatch` (исполнить навык = GUPPI исполняет), `describe` (короткий перечень
  для системного промпта, чтобы Боб знал, что умеет).
- **`ToolLoop`** — петля «модель ↔ инструменты»: даёт модели манифест как
  `tools` через `ToolCallingProvider.complete_with_tools`; если модель вернула
  `tool_calls` — диспатчит каждый через реестр, дописывает результат и повторяет,
  пока не финальный текст. Число ходов ограничено (turn-cap); неизвестный навык не
  фатален (ошибка возвращается как результат). Опциональный `announcer`
  (`ProgressAnnouncer | None`, BOB-055/060): перед `registry.dispatch` каждого вызова
  `_run_tool` зовёт `announcer.announce(call.name, call.arguments)` — ЖИВУЮ интерим-реплику
  перед медленным навыком (аргументы передаются, чтобы реплика была контекстной от `query`).
  Вызов обёрнут в `try/except`: анонс декоративен, его сбой никогда не задерживает и не ломает
  диспатч. `announcer=None` — прежнее поведение.
- **Tool-calling в провайдере** (`OpenAICompatProvider`): нативные OpenAI `tools`,
  а при отсутствии нативной поддержки — prompt-fallback (терпимый разбор
  prompt-протокольного JSON `{"tool_call": {...}}` из текста ответа).
- **Манифест в контексте.** Перечень навыков попадает в системный промпт Боба
  (преамбула о GUPPI как исполнителе), так что Боб ссылается на свои возможности.
- **`recall_memory`** — тонкий *авто*-recall: обёртка над `MemoryRecall`, которой
  GUPPI тихо подмешивает память в ответ (обкатала петлю e2e без нового I/O).
- **`search_memory`** (BOB-011) — первая содержательная **агентная** capability:
  навык, который Боб *сам решает* вызвать через tool-loop, чтобы поискать по всему
  долгому архиву реальным запросом (гибрид семантика+keyword за `MemoryRecall`) и
  использовать результат. JSON-схема — обязательный `query` плюс опциональный `k`
  (клампится в безопасное окно). Полная плагин-система — позже, за этим швом.

`HandleMessage` подхватывает шов опционально: tool-loop включается, только когда
зарегистрированы навыки **и** подан `ToolCallingProvider` (в сборке — провайдер
Tier 1); иначе ход идёт прежним plain-путём роутера.

### Веб-поиск: «Боб ищет в интернете» (BOB-053)

Заземлённый веб-поиск как ещё одна capability за тем же швом. Это **не** автодополнение
к каждому ответу: tool-loop сам тянется к навыку только на запрос про **свежее/внешнее**
(сегодняшние факты, недавние события, live-данные), которого нет в памяти и обучении Боба;
иначе Боб отвечает напрямую. Результат проецируется в петлю **компактно** —
`{answer, sources:[{title,url}]}`, — и Боб синтезирует финальный ответ **своим голосом со
ссылками**, не вываливая сырой дамп.

- **Навык `web_search`** (`application/capabilities/web_search.py`) собирается
  `make_web_search_capability(provider, …)` над портом `WebSearchProvider`: `name="web_search"`,
  `permission="safe"`, JSON-схема — единственный обязательный `query`. Пустой/пробельный
  `query` отвечается честно **без вызова провайдера** (`_EMPTY_QUERY`); пустой `sources` на
  успехе валиден (заземлённый ответ, цитировать нечего) и ответ всё равно возвращается.
- **Порт + значения** (`domain/ports/capabilities.py`): `WebSearchProvider.search(query) -> WebSearchResult`;
  `WebSearchResult{answer, sources}`; `WebSource{title, url}` (`title=""`, когда провайдер его
  опустил — одного URL достаточно). Порт провайдер-агностичен: «query на вход, заземлённый
  answer + sources на выход», так что Tavily или иной провайдер встаёт без правок навыка.
- **Провайдер `QwenWebSearchProvider`** (`infrastructure/llm/web_search_qwen.py`) — Qwen-native
  поверх MaaS **Responses API** в режиме **стриминга** (BOB-055): `POST {base}/responses` с
  `{model, input:<query>, tools:[{type:"web_search"}], stream:true}` и `Accept: text/event-stream`.
  Читаем SSE построчно (`data: <json>`), игнорируем промежуточные события (дельты, прогресс,
  неизвестные типы) и копим до терминального `response.completed`, чей `response.output` — тот же
  список, что вернул бы небуферизованный ответ. Стриминг держит соединение живым и обходит
  ~30с-таймаут шлюза (небуферизованный `POST` рвётся, а живой поиск идёт 1-2 мин). Разбор
  списка `output[]`:
  элементы `type=="web_search_call"` дают `action.sources[]` → `WebSource` (собираются по всем
  search-call'ам, **dedup по url**, порядок сохранён), элементы `type=="message"` — куски
  `content[].output_text`, склеенные в `answer`. 🔴 Источники доступны на текущем workspace-ключе
  **именно через Responses API** — `chat/completions` их не отдаёт (verify .1). Любой сбой (сеть,
  не-200, оборванный поток без `response.completed`, битое/undecodable событие, явное
  событие-провал `response.failed`/`response.error`/`error`, отсутствующее/битое поле) —
  **raise**: отказоустойчивость на стороне вызывающего, Боб никогда не конфабулирует. Сборка — `build_web_search_provider(config)` (`factory.py`): `search.*`
  с фолбэком `base_url`/`api_key` на Tier-1 (`llm.tier1_*` — тот же workspace-`sk`, отдельный
  ключ не нужен). Конфиг `search.*` (`config/loader.py`): `enabled`, `model`, `base_url`,
  `api_key`, `timeout_seconds` (`180` — Responses-поиск медленный).
- **🔴 Гейт привилегии — по отправителю (authz/BOB-052).** `permission="safe"` корректно **только
  потому**, что привилегированный tool-loop запускается лишь для **авторизованного** отправителя
  (гейт upstream, см. «Память публична, привилегии — гейт»). Регистрация — в `_build_registry`
  (`app.py`) под флагом `search.enabled` (в дефолтах `loader.py` — `True`; read-only и за
  authz-гейтом, поэтому может быть включён по умолчанию); выключено → реестр держит прежние
  capability. Автономия навык **не** авто-открывает: он name-based **не** добавлен в
  `goals.safe_capabilities` (по умолчанию пуст), так что проактивный tick его не запустит.
  BOB-051/052 не ослаблены.
- **🔴 Отказоустойчивость (BOB-049).** Раз модель решила искать — `web_search`
  **essential**: вызов провайдера обёрнут в `call_with_retry` (та же политика, что генерация
  ответа: bounded `attempts`/`backoff_seconds` через инъецируемый `sleep`-шов, детерминированный в
  тестах). Если все попытки падают — навык **не** конфабулирует и **не** роняет ход: возвращает
  честный «не смог найти» нотис (`_SEARCH_FAILED_ANSWER`) с анти-конфабуляционным `guidance`
  (`_SEARCH_FAILED_GUIDANCE`), чтобы Боб сам озвучил оговорку — **никогда** не выдавая знание из
  обучения под видом найденного в сети.

### Реплика «ищу…»: живой интерим-анонс перед медленным навыком (BOB-055 → BOB-060)

Стриминговый `web_search` идёт 1-2 минуты. Молчание всё это время читается owner'ом как
«Боб не услышал», поэтому перед медленным навыком Боб роняет **одну живую реплику своим
голосом**, а не роботизированное «Loading…». **BOB-060:** зашитые фразы вырезаны полностью —
реплика **всегда** генерится ЖИВЫМ Tier-0-генератором (BOB-057), а сбой/пусто → **тишина**
(не шаблон); оба пути (tool-loop и verify) унифицированы на одном движке `_announce_live`.

- **Порт `ProgressAnnouncer`** (`application/capabilities/progress_announcer.py`) —
  `async announce(capability_name, arguments)`: анонсировать (или промолчать про) навык **по имени**,
  с аргументами вызова для контекста. Контракт `Capability` не тронут — политика «говорить или
  молчать» живёт здесь, а не в навыке. **Зашитых фраз нет** (`WEB_SEARCH_PROGRESS_PHRASES` /
  `DEFAULT_PROGRESS_PHRASES` удалены).
- **`GatewayProgressAnnouncer`** — per-turn, привязанная к чату реализация: строится с
  `chat_id` хода, тем же `reply`-швом (`_ProgressSink`, структурно = `ReplyGateway`), живым
  `line_generator` (`InterimLineGenerator` — единственный источник реплики; без него → тишина) и
  `sender_name` (адресат хода). `rng`/`phrases` убраны. Единый приватный `_announce_live(topic)`:
  генератор → `strip()` → пусто/сбой → **тишина** (лог, drop), иначе `gateway.reply` (сбой шлёт
  тоже глотается). `announce(name, arguments)` говорит **только** для `web_search` — тянет `query`
  из аргументов как topic (или generic «поиск в интернете», если query нет); прочие (быстрые)
  навыки — тишина. `announce_verify(topic)` — тот же движок, `sender_name` из ctor.
- **Провязка (коллабораторы `handle()`).** ОБА per-turn анонсера строятся общей
  инъектированной фабрикой (`announcer_factory`) с `line_generator` + `sender_name` (из
  `interlocutor.display_name`): `VoiceComposer` при заданном `chat_id` строит анонсер для
  tool-loop и передаёт его в `ToolLoop(announcer=…)`; `VerifyStep` строит анонсер
  (`VerifyInterimAnnouncer`) перед прямым `provider.search`. При `chat_id is None` (tool-loop)
  — `announcer=None`.
  `ToolLoop._run_tool` зовёт `announce(call.name, call.arguments)` **перед** `registry.dispatch`.
- **🔴 Инварианты.** Анонс **декоративен на двух швах**: `_announce_live` глотает свои ошибки
  (стиль BOB-050 `_safe_addon` — логирует и роняет), а `ToolLoop._run_tool` дополнительно обёрнут
  в `try/except` — сбой gateway или анонсера тихий, ход не блокируется и не ломается. **🔴 Ноль
  скриптованности (BOB-060 US-2):** сбой генерации / пустая строка / отсутствие генератора →
  **тишина**, никогда не шаблон. Инвариант BOB-053 **цел**: реальный сбой поиска по-прежнему даёт
  честный анти-конфабуляционный нотис. Привилегированный fulfiller (проактивный tick) анонсера не
  получает. Новых зависимостей нет.
- **Живой Tier-0-генератор (BOB-057 .3, реюз).** `InterimLineGenerator.generate(topic, sender_name)`
  → ЖИВАЯ, АДРЕСНАЯ реплика в голосе Боба, называя ЧТО он ищет/проверяет и К КОМУ обращается («Леш,
  гляну свежие ставки, секунду 🙂»). Модель-фейсинг чист: домен `domain/personality/interim_line.py`
  (`INTERIM_LINE_SYSTEM_PROMPT`, `build_interim_line_user_prompt`, `clean_interim_line` → одна
  опрятная строка); инфра `infrastructure/llm/interim_line.py` (`LlmInterimLineGenerator`, Tier-0
  `TaskType.INTERIM_LINE`, ошибка ПРОПАГИРУЕТСЯ → `_announce_live` ловит и молчит). +1-2с латентности
  допустимы (ход всё равно ждёт поиск), ход/поиск не ломаются.

### Прочитать ссылку: «Боб читает присланную страницу» (BOB-054)

Близнец `web_search` за тем же Capability-швом, но с обратной задачей: `web_search` **ищет** по
теме, а `read_url` **открывает одну конкретную ссылку**, которую разговор уже несёт, и читает её.
Tool-loop сам тянется к навыку, когда в диалоге есть URL для прочтения. Содержимое проецируется в
петлю **компактно** — `{url, title, excerpt}`, — и Боб синтезирует ответ **своим голосом по
прочитанному**, не вываливая сырой дамп страницы.

- **Навык `read_url`** (`application/capabilities/read_url.py`) собирается
  `make_read_url_capability(reader, …)` над портом `UrlReader`: `name="read_url"`,
  `permission="safe"`, JSON-схема — единственный обязательный `url`. Пустой/пробельный `url`
  отвечается честно **без вызова читателя** (`_BLANK_URL`). На успехе `WebPage` проецируется как
  `{url, title, excerpt}`, где `excerpt` — уже усечённый извлечённый текст страницы.
- **Порт + значения** (`domain/ports/capabilities.py`): `UrlReader.read(url) -> WebPage`;
  `WebPage{url, title, text}` (`url` — финальный после разрешённых редиректов, чтобы Боб цитировал
  реальный источник; `title=""`, когда его нет). Контракт отказа объявлен в домене —
  `UrlReadError` (страницу не прочитать: отклонённая схема, не-2xx, запрещённый content-type,
  превышение `max_bytes`, слишком много редиректов, пустой текст) и его подтип `SsrfBlockedError`
  (адрес не публичен) — так приложение ловит их **без** импорта инфраструктуры (гексагон); инфра
  (`HttpUrlReader`) ре-экспортит оба.
- **Читатель `HttpUrlReader`** (`infrastructure/web/http_url_reader.py`) — один `aiohttp` GET за
  🔴 **SSRF-щитом**, который прогоняется **до** открытия сокета и **заново на каждом редирект-хопе**:
  (1) схема — только `http`/`https` (блок `file://`, `ftp://` …); (2) резолв хоста → **все**
  полученные IP должны быть публичными: блокируются private / loopback / link-local / reserved /
  multicast / unspecified плюс явно CGN `100.64/10` (RFC 6598), для IPv4, IPv6 и IPv4-mapped;
  нераспарсиваемый адрес → **fail-closed** (блок). (3) редиректы **ручные**
  (`allow_redirects=False`), каждый `Location` ре-валидируется полным щитом, капается на
  `max_redirects`; (4) лимиты — общий `timeout`, `text/html`/`text/plain` allowlist, **потоковый**
  обрыв тела на `max_bytes`, фиксированный User-Agent, без auth-заголовков; (5) извлечение текста —
  stdlib `html.parser` (**без новых зависимостей**): выкидывает `<script>/<style>/<head>/<noscript>`,
  собирает видимый текст, схлопывает пробелы, ловит `<title>`, усекает до `max_chars`. Любой
  сбой/блок/не-тот-content-type/пустой-текст — **raise**. Сборка — `build_url_reader(config)`
  (`infrastructure/web/factory.py`), конфиг `read_url.*` (`config/loader.py`): `enabled`,
  `timeout_seconds`, `max_bytes`, `max_redirects`, `max_chars`, `user_agent`.
- **🔴 Гейт привилегии — по отправителю (authz/BOB-052).** `permission="safe"` корректно **только
  потому**, что привилегированный tool-loop запускается лишь для **авторизованного** отправителя
  (гейт upstream). Регистрация — в `_build_registry` (`app.py`) под флагом `read_url.enabled`
  (в дефолтах `loader.py` — `True`; read-only и за authz-гейтом, поэтому включён по умолчанию);
  выключено → реестр держит прежние capability. BOB-051/052 не ослаблены.
- **🔴 Отказоустойчивость (BOB-049).** Раз модель решила читать — `read_url` **essential**: вызов
  читателя обёрнут в `call_with_retry` (bounded `attempts`/`backoff_seconds` через инъецируемый
  `sleep`-шов, детерминированный в тестах). Если все попытки падают — навык **не** конфабулирует и
  **не** роняет ход: возвращает честный «не смог открыть» нотис (`_READ_FAILED_EXCERPT`) с
  анти-конфабуляционным `guidance` (`_READ_FAILED_GUIDANCE`). 🔴 Важный нюанс против `web_search`:
  `SsrfBlockedError` **детерминирован** (заблокированный внутренний адрес) — ретраить его
  бессмысленно, поэтому `_read_transient` короткозамыкает его в `None`, и честный нотис выдаётся
  **сразу**, не расходуя бюджет ретраев и не ожидая backoff. Остаточное окно DNS-rebinding
  (TOCTOU между резолвом щита и коннектом aiohttp) задокументировано как **принятое для v1**;
  полное закрытие (коннект по уже разрешённому IP) — будущий апгрейд.

### Самоинтроспекция: «Боб знает свой мир» (BOB-017, фаза A)

Боб умеет заглянуть в собственный мир и ответить про свой код, архитектуру и
процесс, опираясь на **реальные** данные, а не на догадки. За тем же
Capability-швом (без нового транспорта) живут четыре **read-only** навыка
`permission="safe"`, диалоговые — Боб вызывает их через tool-loop, GUPPI исполняет
(как `recall_memory`):

- **`inspect_architecture`** (`application/capabilities/inspect_architecture.py`) —
  делегирует запрос в `RepoIntrospector.architecture_context`, который сам
  выбирает маршрут (BOB-031). Свободный текст (естественный вопрос вроде «как
  устроена память») заземляется через `beadloom search` — поиск не требует
  точного узла. Точный граф-`ref-id` (форма узла `bob-1av` или одиночное имя
  файла `*.py`/`*.md`/`*.yml`) уходит в `beadloom ctx`; если `ctx` не разрешает
  его (пустой ответ), запрос повторно прогоняется через `search` (fallback
  `ctx`→`search`), чтобы естественный вопрос никогда не сваливался в негрундленые
  знания модели. Эвристика «это ref-id?» детерминированная (`_is_ref_id`), без
  I/O.
- **`read_code`** (`read_code.py`) — один аргумент `query` маршрутизируется по
  форме: репо-относительный путь (есть разделитель `/` и расширение, напр.
  `src/bob/app.py`, `.claude/dev-docs/ROADMAP.md` или
  `.claude/development/docs/features/<KEY>/PRD.md`) читается через `read_file`, всё
  прочее уходит в `search_code` (FTS по узлам/докам). Описание навыка сообщает
  модели, что теперь читаемы и roadmap/vision/feature-спеки (BOB-034), чтобы Боб мог
  рассуждать о направлении проекта; личные данные и секреты по-прежнему недоступны.
- **`list_work`** (`list_work.py`) — состояние трекера; `list_tasks(query)`
  маршрутизирует запрос (BOB-031): точный id задачи → `bd show <id>`; запрос про
  «закрытые/недавние/в работе/все/история» → подходящий `bd list --status <enum>`
  (или `bd list` без фильтра для «все»); пустой запрос или «готовое» → `bd ready`
  для очереди готового. Запрос про задачу без id и без ключевых слов листинга
  уходит в `bd list`, а не в обречённый `bd show` по свободному тексту. Служебный
  «Tip»-хвост (легенда статусов, подсказка `--limit`) вырезается, чтобы Боб не
  риффовал на инструментальный шум.
- **`code_rationale`** (`code_rationale.py`, BOB-038) — четвёртый introspection-навык:
  отвечает на «почему этот код такой?». Один аргумент `query` (репо-относительный путь,
  область или ключ беады) проходит цепочку **код → git-история → беады → фича-доки →
  граф**. Сначала `RepoIntrospector.code_history(query)` поднимает git-историю, из неё
  `parse_bead_refs` извлекает ключи решений `[BOB-XXX]` (де-дублированные, обрезанные до
  top-N самых свежих, `_MAX_BEAD_REFS = 5`, чтобы не залить контекст модели). Для каждого
  ключа рендерятся обрамляющие коммит-строки (`commits_mentioning` по той же истории) и
  читаются **фича-доки «почему»** (`feature_doc_dir(key)` → `PRD.md`/`RFC.md`/`BRIEF.md`,
  отсутствующий док просто пропускается — это и есть read-scope BOB-034), а сверху
  `architecture_context(query)` даёт структурную картину из **beadloom-графа**. Всё
  сшивается в один компактный «почему». Честность (US-4): если в истории нет ключа
  решения, навык возвращает «История решения … не зафиксирована», а не выдумывает
  рационал; любой отдельный источник (отсутствующий док, пустой git) деградирует мягко,
  не роняя ход.
  **Важно про границу источников:** рационал берётся из git-истории + фича-доков + графа,
  а **по-ключевой `bd show` НАМЕРЕННО не вызывается**. Человеческий ключ `[BOB-NNN]` из
  темы коммита — это эпик-ключ, а не `bd`-hash-id, поэтому `bd show` его не разрешит, а
  листинг-фоллбэк подсунул бы под каждый ключ нефильтрованный общий бэклог — это шум, а
  не «почему». Резолв `BOB-key`→`bd`-id для точечного `bd show` — возможное будущее
  улучшение.

Все четыре — фабрики `make_*_capability(introspector)` по образцу `recall_memory`: они
лишь валидируют вход, делегируют в порт и рендерят компактный результат, а на
пустом выводе честно отвечают «ничего не нашёл» (US-5), не выдумывая
несуществующую ссылку/символ/задачу. Приватный инвариант в них не дублируется — он
живёт глубже, в реализации порта.

**Порт `RepoIntrospector`** (`domain/ports/capabilities.py`, `Protocol`) — абстракция шва:
`architecture_context(ref)` / `search_code(query)` / `read_file(path, *, max_lines)`
/ `list_tasks(query)` / `code_history(path)` (BOB-038), все **read-only**. В тестах
подменяется детерминированным фейком (без подпроцесса и диска).

**Чистые домен-парсеры** (`domain/introspection/code_history.py`, BOB-038) — без I/O и
подпроцесса: `parse_bead_refs(git_log_text)` извлекает ключи `[BOB-XXX]` (де-дубликация,
порядок первого появления; только в скобках — голый `BOB-999` или `[#42]`-PR не считается
ключом решения); `commits_mentioning(bead_key, git_log_text)` фильтрует ту же историю до
строк, обрамляющих один ключ (точное совпадение — `BOB-3` не матчит `BOB-37`; не-фича-ключ
вроде узла `bob-4be.1` даёт пустой список); `feature_doc_dir(bead_key)` отображает
фича-ключ в каталог `.claude/development/docs/features/<KEY>` (не-фича-ключ → `ValueError`,
маршрут не угадывается). Сам git-read живёт за портом в инфраструктуре.

**`SubprocessRepoIntrospector`** (`infrastructure/introspection/subprocess_introspector.py`)
— живая реализация. Локальные `beadloom`/`bd` запускаются через
`asyncio.create_subprocess_exec` (**не shell** — нет инъекции метасимволов) по
**фиксированному allowlist** read-подкоманд (`beadloom`: `ctx`/`graph`/`why`/`search`;
`bd`: `ready`/`show`/`list`; `git`: только `log`). Всё вне allowlist — неизвестный
бинарь, write-подкоманда, аргумент, похожий на флаг (`-…`), — отвергается
`DisallowedCommandError` и **не исполняется**. Первое флаг-несущее исключение (BOB-031) —
контролируемая форма `bd list --status <enum>`: литеральный `--status` в паре с одним
значением статуса из фиксированного набора (`open`/`in_progress`/`blocked`/`deferred`/`closed`).
Это **не** сырой проброс флагов, а allowlist готовых argv-кортежей
(`_BD_LIST_ARG_FORMS`): статус вне набора или любой другой флаг отвергается **до**
исполнения, так что инвариант «никаких произвольных аргументов/флагов» цел.

Второе флаг-несущее исключение (BOB-038) — `git`, которому нужны флаги
(`--oneline`/`--grep=`). По той же логике он разрешён **только** как маленький набор
**фиксированных форм `git log`**, у которых каждый динамический слот (путь, счётчик,
ключ беады) проверяется: `git log --grep=<bead-key> --oneline` (по коммитам,
упоминающим ключ) и `git log --oneline [-n <N>] -- <path>` (ограниченная история пути;
`-n` ≤ `_GIT_MAX_LOG_COUNT = 1000`, по умолчанию `50`). Метод `code_history(path)`
строит argv по этим формам: ключ беады/узла (`BOB-031`/`bob-4be.1`) уходит в `--grep`,
репо-относительный путь — в `-- <path>`. Путь валидируется (`_is_safe_git_path`:
не флаг, не абсолютный, без `..`-traversal), счётчик — как положительное ограниченное
целое. Любая другая форма, флаг, подкоманда (`git show`/`diff`/`blame` — **не** в v1) или
путь-инъекция отвергается `DisallowedCommandError` **до** запуска git (без shell), так что
read-only инвариант нельзя обойти промптом. Перед
возвратом результата срезается хвостовой инструментальный шум (`_strip_noise_tail`:
легенда статусов / `Tip` / подсказка `--limit`) — обрезается только хвост, нутро
вывода не трогается. Каждый запуск ограничен жёстким таймаутом (по умолчанию 30 с,
дефолтный раннер на таймауте `kill`-ит и реапит процесс), вывод обрезается по
лимиту символов и проходит санитайзер. Подпроцессная граница инжектируется как
`runner`, поэтому тесты не плодят процессы.

#### Приватный инвариант: `PrivacyGuard` (🔴 ядро)

Приватность — **обязательное требование**, не опция, и не обходится промптом.
`PrivacyGuard` (`domain/introspection/privacy_guard.py`) — **чистый** замороженный
домен-объект (без I/O, LLM и промпта), единственная точка правды «можно ли читать
этот путь / возвращать этот текст»:

- **`allows_path(path)`** — путь резолвится относительно корня репо (схлопывание
  `..`/`.` **без обращения к диску**) и допускается **только** если его сегменты
  префиксованы одним из read-only корней
  `ALLOWED_ROOTS = (src, tests, docs, .claude/dev-docs, .claude/development/docs)`
  (или путь совпадает с самим корнем). Корень может быть **многосегментным**
  (`.claude/dev-docs`): сопоставление идёт по полному **префиксу сегментов**
  (`_has_segment_prefix`), а не по строковому префиксу — поэтому добавление
  `.claude/dev-docs` открывает **только** этот поддерев (roadmap/vision/audits) и
  `.claude/development/docs` (feature PRD/RFC/CONTEXT/PLAN/BRIEF), но **не** остальной
  `.claude/` (его `settings*.json`, `agents/`, `commands/`, корневой `CLAUDE.md`), а
  «похожий» сосед (`srcfoo`, `.claude/dev-docs-extra`) не принимается за разрешённый
  корень (BOB-034). Всё прочее — `data/soul/**` (SOUL.md + профили), `data/bob.db*`
  (БД памяти + WAL/SHM), `.env*` (секреты), `config/**`, файлы в корне репо,
  traversal за пределы репо, абсолютный путь снаружи — **DENY** по построению.
- **`sanitize(text)`** — защита в глубину: из любого вывода (даже из разрешённого
  пути или CLI) вырезаются секрето-подобные паттерны (`KEY=value` env-присвоения,
  `sk-…`-токены, `api_key`/`token`/`secret`/`password`), чтобы случайный секрет не
  ушёл с машины.

Адаптер сверяется с guard'ом **до** открытия файла: `read_file` на запрещённый
путь поднимает `DeniedPathError` без касания диска, а разрешённый-но-отсутствующий
файл даёт честное «не найдено». Поверх чистого имя-based guard'а инфра-граница
делает **дополнительную проверку realpath-containment** (`_real_path_is_allowed`):
имя-based проверка не видит, **куда указывает symlink**, поэтому линк, подложенный
под разрешённый корень (напр. `src/leak.md -> data/soul/SOUL.md`, в т.ч. под новые
корни вроде `.claude/dev-docs/leak.md`), резолвится через `os.path.realpath` и
отвергается, если реальный путь выходит из read-only корней.
Containment считается на realpath-ах с обеих сторон, поэтому симлинкнутый корень
репо (напр. `/var -> /private/var` на macOS) не даёт ложного отказа. Так
`read_code` физически не может прочитать личные данные.

#### Границы стадии и конфигурация

Фаза A — **только чтение, локально, без записи и исполнения произвольного CLI**;
гейтед-исполнение Claude Code в изоляции (фаза B) и стрим/self-proposed (фаза C) —
вне объёма. Навыки **намеренно не** добавлены в автономный `goals.safe_capabilities`
→ они **диалоговые**, не самонаправленные: проактивный tick не может их запустить
сам. Композиция — в `_build_registry(config, recall=…)` (`app.py`): при
`introspection.enabled` (по умолчанию **true** — это и есть фича; read-only,
owner-only чат) четыре навыка (`inspect_architecture`/`read_code`/`list_work`/
`code_rationale`) регистрируются поверх `SubprocessRepoIntrospector(
PrivacyGuard(repo_root=_REPO_ROOT), …)`; выключено → реестр держит ровно две
memory-capability, поведение как раньше. Конфиг `introspection.*`
(`infrastructure/config/loader.py`): `enabled`, `max_output_chars` (`20000`),
`read_max_lines` (`200`), пути бинарей `beadloom_bin`/`bd_bin`. Миграций БД нет —
навыки только читают репозиторий и трекер.

### Боб запускает Claude Code: гейтед coding-сессия (BOB-039, T3.B)

Если самоинтроспекция (T3.A) — это «Боб читает свой мир», то здесь Боб **меняет** его:
по команде owner'а он гоняет локальный `claude` CLI над собственным репозиторием,
собирает план, после явного апрува исполняет его в изоляции и открывает PR. Это
самая мощная способность Боба, поэтому она не «request→response», а **гейтед сессия**
с конечной машиной состояний под owner-контролем — те же идиомы, что у Goal Engine
(BOB-015): owner-only на каждой команде, непробиваемый гейт плана, kill-switch и
честный провал с уборкой.

#### Конечная машина состояний (чистый домен)

`CodingSessionState` (`coding/state.py`) — строковый `StrEnum` (значение
совпадает с TEXT-колонкой SQLite, round-trip тривиален). Жизненный цикл:

```
PROPOSED → PLANNING → PLAN_READY → EXECUTING → PR_OPEN (успешный терминал)
                          │ (ГЕЙТ ПЛАНА)
CANCELLED / FAILED ← из любого нетерминального
```

- **🔴 Гейт плана непробиваем на уровне домена:** `EXECUTING` достижимо
  **исключительно** из `PLAN_READY`. В таблице переходов `_PROGRESS` целевое состояние
  `EXECUTING` присутствует ровно в одном множестве — целей `PLAN_READY`. Ни `PROPOSED`,
  ни `PLANNING` в исполнение не ведут.
- **Мержа в машине нет, `PR_OPEN` — успешный терминал (BOB-042):** открыв PR, Боб
  завершил свою работу, сам мерж делает owner асинхронно на GitHub вне Боба. Поэтому
  `is_terminal(PR_OPEN)` — `True`: завершённая сессия **не блокирует** новую (read-апи
  `active()`/`active_state()` фильтруют терминальные). Это не создаёт нового пути в
  `EXECUTING` — гейт плана остаётся ровно из `PLAN_READY`. `DONE` сохранён как
  легаси-терминал (старые персистнутые сессии), но машиной больше не достижим.
- Чистые предикаты: `can_transition(frm, to)`, `can_start`, `can_approve_plan`
  (предикатная форма гейта плана), `can_stop` (kill-switch из любого нетерминального),
  `is_terminal` (`PR_OPEN`/`DONE`/`CANCELLED`/`FAILED`).

Сессия — `CodingSession` (`coding/entities.py`), immutable `frozen, slots`
value-object: `id`, `task`, `state`, `branch`, `created_at`/`updated_at` и опциональные
`worktree_path`/`plan`/`pr_url`. Без I/O и без часов — момент времени инжектится
параметром `at` в мутаторы `with_state`/`with_plan`/`with_worktree`/`with_pr_url`
(каждый возвращает новый объект и обновляет `updated_at`). Имя ветки даёт чистая
`worktree_branch(task)` (`coding/naming.py`): ascii-slug → `bob/<slug>`, что
закрывает path-инъекции (`..`, слэши, пробелы в имя не попадают).

#### Оркестратор `CodingAssistant` (use-case)

`CodingAssistant` (`coding/usecases/coding_assistant.py`) — чисто-оркестрационный
use-case над чистым доменом и инжектированными портами (раннер Claude Code, worktree,
стор, PR-открывашка, нотификатор owner, authz, часы, фабрика id, `execute_mode`) плюс три
**опциональных** сейма с no-op-дефолтом: индикаторы работы `typing_keepalive` /
`status_panel` и арх-контекстная преамбула `context` (все три — ниже).
Четыре owner-only метода:

- **`start(task, sender)`** — создаёт изолированный worktree на безопасной ветке
  `bob/<slug>`, персистит сессию в `PLANNING`, гоняет раннер в режиме `plan` (план
  **без правок** — это и есть гейт), собирает план, переводит в `PLAN_READY`, шлёт план
  owner и **останавливается**. Исполнение здесь не начинается.
- **`approve_plan(sender)`** — гейт плана: валиден **только** из `PLAN_READY`
  (`can_approve_plan`). Переводит в `EXECUTING`, гоняет раннер в режиме правок, **нарратит
  каждое событие** owner через `narrate`, затем открывает PR (`PullRequestOpener.open`)
  и переводит в `PR_OPEN`. 🔴 Никакого мержа/пуша в `main` — такого вызова просто нет.
- **`stop(sender)`** — kill-switch: добавляет id сессии в `_cancelled` (идущий narrate-цикл
  прерывается на следующем событии → раннер закрывается → процесс убивается), переводит
  в `CANCELLED` и убирает worktree.
- **`status(sender)`** — докладывает состояние текущей сессии.

worktree убирается в `finally` на любом завершении прогона (успех `PR_OPEN`, провал
`FAILED`, стоп `CANCELLED`), так что висящих worktree не остаётся. Authz —
defense-in-depth: гейт дублируется на уровне GUPPI, но use-case проверяет `OwnerCheck.is_owner`
на **каждом** методе сам; чужому — тихий отказ без сессии и без прогона. Все порты
объявлены в `coding/ports.py` (`ClaudeCodeRunner`, `Worktree`, `CodingSessionStore`,
`PullRequestOpener`).

#### 🔴 Изоляция: `GitWorktree` (только трекнутые файлы)

`GitWorktree` (`coding/adapters/git_worktree.py`) — `git worktree add <path> -b
<branch>` на **новой** ветке, фиксированной формы и **без shell** (никакой
интерполяции метасимволов). Свежий worktree содержит **только трекнутые файлы**,
поэтому приватные данные Боба — `data/soul/`, `bob.db*`, `.env*`, `config/*` (все
gitignored) — в нём **отсутствуют**, и это отсутствие **и есть** приватная изоляция:
Claude Code их физически не видит. Ветка валидируется к форме `bob/<slug>`
(`is_safe_branch`) до запуска git; `remove` → `git worktree remove --force <path>` с
проверкой containment (путь обязан быть symlink-resolved потомком `worktree_root`,
иначе `WorktreeError`).

#### 🔴 Только ветка + PR, НИКОГДА main: `GhPullRequestOpener`

`GhPullRequestOpener` (`coding/adapters/gh_pr.py`) строит **единственную** форму
`gh pr create --base main --head <branch> --title <title> --body <body>` (title/body —
дискретные argv, без shell) и возвращает URL PR. **Инвариант безопасности:** здесь
**намеренно нет** пути интеграции в trunk — ни `merge`-метода в порте `PullRequestOpener`,
ни git-записи в защищённую ветку. Боб открывает PR и останавливается; мерж делает owner
руками. Физическое отсутствие merge-пути — часть гарантии гейтед-автономии, и тест
проверяет, что опасные токены в этом модуле не появляются.

#### Раннер `SubprocessClaudeRunner` и нарратив

`SubprocessClaudeRunner` (`coding/adapters/claude_runner.py`) реализует порт
`ClaudeCodeRunner`: гоняет `claude` headless через `asyncio.create_subprocess_exec`
(**никогда не shell** — `prompt` это один дискретный argv-элемент):

```
claude -p <prompt> --output-format stream-json --verbose --permission-mode <mode>
```

`mode` валидируется против **фиксированного allowlist** `_ALLOWED_MODES = {plan,
acceptEdits}` (`plan` — план без правок, гейт; `acceptEdits` — применить правки в
worktree); любой иной режим (в частности `bypassPermissions`) отбрасывается до старта
процесса (`ClaudeRunError`). stdout читается как NDJSON построчно: каждая строка
`json.loads`-ится и отдаётся как событие (async-генератор); битые/неполные строки
пропускаются. Прогон ограничен таймаутом (`600` с), числом событий (`10_000`) и бюджетом
байтов (`10_000_000`); процесс убивается и reaped на таймауте или раннем break (без
зомби).

`narrate(event)` (`coding/narrate.py`) — **чистый** детерминированный мэппер
одного stream-json события в короткую русскую нарратив-строку **или** `None` для шумных
событий (system-init, чистый текст ассистента). Раннер только стримит, use-case шлёт
ненулевые строки в чат owner'а. 🔴 **Канон (BOB-041):** фактическое исполнение — работа
**GUPPI**, поэтому каждая ненулевая строка **атрибутирована GUPPI** префиксом `GUPPI: `
(«GUPPI: правлю `<file>`», «GUPPI: гоняю тесты», «GUPPI: тесты прошли», «GUPPI: готово»,
«GUPPI: ошибка: …»); шум остаётся `None` (без префикса). Голос Боба на гейтах живёт
отдельно (см. ниже). Сессии переживают рестарт — `SqliteCodingSessionStore`
(`coding/adapters/session_store.py`) round-trip'ит `CodingSession`
(UPSERT по `id`, `active()` отдаёт нетерминальные), так что двойной гейт честен и через
границу процесса.

#### Owner-команды, конфигурация и границы стадии

GUPPI (`infrastructure/telegram/guppi.py`) даёт owner-only команды `/code <задача>`
(стартовать сессию), `/code approve` (гейт плана), `/code stop` (kill-switch),
`/code status`. Команда от не-owner туда не доходит; когда `coder.enabled` выключено,
assistant вообще не подключён и `/code` отвечает понятным «выключено» (через структурный
протокол `CodingAssistantLike`). Конфиг `coder.*`
(`infrastructure/config/loader.py`): `enabled` **по умолчанию `false`** (мастер-switch —
owner включает осознанно, как goals/self_improvement, ведь это самая мощная
способность), `claude_bin`/`gh_bin` (имена локальных CLI), `worktree_root`
(`.worktrees`), `timeout` (`600` с), `permission_mode` (`acceptEdits` — execute-режим
после апрува, никогда не bypass). Сборка — `_build_coding_assistant(config, …)` в
`app.py`, **только** при `coder.enabled`.

Способность **намеренно не** входит в автономный `goals.safe_capabilities` →
проактивный tick не может запустить coding-сессию сам. v1 — **user-driven** (сессию
всегда инициирует owner командой `/code`); само-предложенные сессии (Боб сам решает,
что доработать) — это будущая фаза **T3.C**, вне объёма BOB-039.

#### Естественный язык: задача Бобу его словами (BOB-041)

`/code` в General — не единственная поверхность. Канон T3.B: owner ставит задачу Бобу
**естественным языком** в его топике («Боб, создай файл X», «поправь баг в Z»), а Боб
гоняет ту же гейтед-сессию через GUPPI. Провязка тонкая и аддитивная — стоит **перед**
обычным compose в `handle` и при срабатывании короткозамыкает ход (гейтед use-case сам
шлёт owner-сообщения):

- **Tier-0 классификатор намерения.** `ClassifyCodingIntent`
  (`coding/usecases/classify_coding_intent.py`) — дешёвый Tier-0 вызов (по образцу
  классификатора настроения): `is_coding_request(text)` возвращает «это запрос dev-работы
  над репозиторием Боба?» одним словом. Парсинг **консервативный** — засчитывается только
  точный ответ `coding`; любое другое слово, мусор или сбойная локальная модель → `chat`
  (`False`). Консервативность — свойство безопасности: ложноположительное лишь **предложит
  план** за непробиваемым гейтом (без правок), так что по сомнению — просто болтаем.
- **Чистые предикаты апрува/стопа.** `is_approval` / `is_stop` (`coding/intent.py`)
  — детерминированная, **консервативная** классификация одной строки для управления уже
  идущей сессией обычными словами: совпадает только короткая фраза-команда целиком после
  нормализации (пунктуация → пробелы, casefold). Вопрос или реплика, где слово-команда лишь
  упомянуто («а давай попозже…»), **не** совпадает. По любой неоднозначности — `False`
  (трактуется как болтовня, не команда).
- **Маршрутизатор `CodingIntentRouter`** (`coding/usecases/coding_intent_router.py`)
  — тонкая политика над двумя швами (`GatedCoder`, `CodingIntentClassifierLike` —
  структурные протоколы). `route(text, sender, is_owner)` решает, **когда** позвать гейтед
  `CodingAssistant`: при живой сессии — только естественный стоп (kill-switch из любого
  состояния) или апрув **строго из `PLAN_READY`**; без сессии — классифицированный запрос
  работы запускает `start` (план без правок). Возвращает «съел ли ход» — `False` оставляет
  ход обычному чат-пути.
- **Провязка `PreComposeGate.maybe_route_coding`** (`application/usecases/precompose_gate.py`,
  коллаборатор `handle()`) — `is_owner`
  выводится из перцепции собеседника (только `InterlocutorKind.OWNER`); при срабатывании
  `handle` возвращается до compose. Сборка — `_build_coding_router(router, coder)` в
  `app.py`, **только** при `coder.enabled` (иначе шов инертен — каждое сообщение идёт
  обычным чат-путём как раньше).

🔴 **Безопасность (точно).** NL-путь **не обходит ни одного гейта** — он лишь выбирает,
*когда* звать `start` (план без правок, непробиваемый гейт), `approve_plan` (валиден
**только** из `PLAN_READY`) или `stop` (kill-switch). Тройная owner-проверка цела:
`_maybe_route_coding` пускает только `OWNER`, роутер сам перепроверяет `is_owner`, и
гейтед use-case проверяет `OwnerCheck.is_owner` на каждом методе (defense-in-depth).
**Гейт фактически по owner, а не по топику:** NL-постановка живёт в топике Боба, но
авторизацию решает идентичность отправителя (owner), а не место сообщения. Never-main,
изоляция worktree и kill-switch (BOB-039/040) целы. Команда `/code` в General остаётся
отдельной нетронутой поверхностью.

#### Голос Боба на гейтах: Боб дирижирует, GUPPI пашет (канон)

`session_voice` (`coding/session_voice.py`) — **чистые детерминированные шаблоны**
ключевых реплик сессии **в персоне Боба от первого лица**, с GUPPI как исполнителем, на
которого Боб ссылается (никакого LLM-вызова на сообщение — латентность/стоимость). Билдеры:
`accepted()` («берусь, GUPPI — погнали»), `plan(plan_text)` (интро Боба + уже очищенный
план + хинт апрува, покрывающий обе поверхности: «давай» или `/code approve`), `pr(url)`
(«готово — GUPPI всё сделал; мержить — твоё дело, в main я не лезу»), `no_changes()`,
`failed(detail)`, `stopped()`, плюс операционные отказы/статус (`busy`, `cannot_approve`,
`no_session`, `status_idle`, `status_line`). `CodingAssistant` зовёт эти билдеры на каждом
гейте. Это **голос** (как Боб звучит), а не машинерия безопасности — гейты/поток/изоляция
не меняются. Вместе с GUPPI-атрибуцией пер-событийного нарратива (`narrate`, выше) выходит
канон Бобиверса: **Боб — личность, дирижирует сессией; GUPPI — сухой исполнитель**.

#### Голос Боба-бота: отправляет Боб, GUPPI молчит-исполняет (BOB-046)

🔴 **Канон-отправитель (BOB-046):** owner разговаривает с **Бобом**, а GUPPI — тихий
исполнитель под капотом, поэтому **отправителем** всех сообщений сессии (план / нарратив /
PR / статус) выступает **бот Боба**, а не GUPPI. В `app.py` это сделано переименованием
адаптера `_GuppiOwnerNotifier` → **`_CodingOwnerNotifier`**: он реализует структурный
`OwnerNotifier` use-case'а и в `_build_coding_assistant` собирается поверх **бота Боба**
(`notifier_bot == resolved_bob_bot`). Сменился только отправитель — пер-событийный
**нарратив остаётся GUPPI-атрибутированным** в тексте (`GUPPI: …`, см. `narrate` выше),
так что канон «Боб говорит, GUPPI пашет» цел и в голосе на гейтах, и в нарративе.

Coding-сообщения несут markdown (`## заголовки`, `**жирный**`, `` `code` ``), поэтому
`_CodingOwnerNotifier` шлёт их **тем же rich-путём Боба** — `RichMarkdownSender`
(`infrastructure/telegram/gateway.py`) — что и обычные ответы, с безопасным plain-фолбэком
(ошибка парсинга не роняет сообщение). 🔴 **Канон-тред (BOB-042):** owner ставит задачу
Бобу в его топике (NL-путь), поэтому ответы сессии уходят в **тот же топик** — нотификатор
шлёт с `message_thread_id == telegram.bob.topic_id` (провязано через
`_build_coding_assistant`), а не в General. Разговор остаётся одним тредом: ввод и вывод
сессии в топике Боба.

План приходит **дважды** (как текст `assistant` и снова в финальном `result`), поэтому
`_clean_plan` (`coding/usecases/coding_assistant.py`) сводит части к одному
авторитетному источнику — последнему непустому `result` (а при деградировавшем стриме
джойнит части `assistant`, отбрасывая содержащиеся/идентичные дубликаты), затем
`_strip_plan_noise` срезает планную преамбулу (`ExitPlanMode`-болтовня, «Let me write the
plan.» — консервативный `_PLAN_CHATTER_RE`), так что owner видит чистый план один раз.

#### Индикатор работы: typing-keepalive + editable статус-панель (BOB-046)

Прогон `claude` молчит десятки секунд, поэтому coding-сессия показывает owner, что
процесс идёт. Два дополняющих индикатора живут в `coding/adapters/indicator.py`
(ex-`infrastructure/telegram/coding_indicator.py`) и реализуют сеймы use-case'а
(`TypingKeepalive` / `StatusPanel`, объявлены протоколами в `coding_assistant.py`):

- **`TypingKeepalive`** — «Боб печатает…» на время немых claude-пауз. Async-контекст-менеджер
  (use-case оборачивает им plan- и execute-прогоны): на входе один
  `sendChatAction("typing")` в топик Боба, затем фоновая задача рефрешит его каждые
  `interval` секунд (инъектированный `sleep` задаёт ритм — детерминизм в тестах), потому что
  Telegram гасит typing примерно через 5 с; на выходе задача снимается и ожидается (без
  утечки). Каденс собран с `_CODING_TYPING_INTERVAL = 4.0` с (чуть под 5-секундным окном
  Telegram). Сбой action'а логируется и глотается — индикатор **никогда** не валит сессию.
- **`StatusPanel`** — одно editable сообщение-статус. `open(text)` шлёт строку один раз и
  запоминает её `message_id`; `update(text)` **редактирует то же сообщение**
  (`editMessageText`) — одно сообщение, не спам. Нет запомненного id или сбой редактирования
  → graceful no-op (current behavior без статус-строки, без падения сессии). `CodingAssistant`
  редактирует панель по фазам сессии шаблонами `session_voice` (`coding/session_voice.py`):
  `⏳ Прикидываю план…` → `📝 План готов — жду добро.` → `⚙️ GUPPI выполняет…` →
  `✅ PR открыт.` / `⚠️ Не получилось.` / `⏹️ Остановил.`.

Оба индикатора — **опциональные сеймы**: незаведённый (`None`) деградирует в no-op
(`_no_typing` / `_NullStatusPanel`), так что гейтед-поток не зависит от наличия индикатора.
Оба собираются в `_build_coding_assistant` поверх **бота Боба** (`notifier_bot`) и пишут в
топик Боба, поэтому маркер работы остаётся в том же треде, что план и нарратив.

#### Арх-контекст в claude-промпт: bounded, privacy-safe преамбула (BOB-046)

Прежде чем отдать задачу Claude Code, Боб подмешивает в промпт короткую преамбулу с **«почему»**
проекта, чтобы claude кодил как партнёр, знающий конвенции и рационал области, а не как умный
редактор, впервые увидевший дерево. Сборщик — `make_coding_context` в
`coding/usecases/coding_context.py`; он строит `_CodingContextBuilder.preamble(task)` из
**трёх публичных источников** по порядку:

1. **конвенции проекта** — статичная публичная константа `_CONVENTIONS` (стек + DDD/Clean-слои +
   направление зависимостей `infrastructure → application → domain`, CLAUDE.md §0.1);
2. **конвенционные документы** — `docs/architecture.md` (guard-allowed, `docs/` —
   ALLOWED_ROOT), читаются через read-only-порт `RepoIntrospector`;
3. **рационал области задачи** — `RepoIntrospector.architecture_context(ref)` (сейм
   `inspect_architecture` за `.1`-портом: beadloom ctx/graph/search).

🔴 **Приватность (BOB-034):** каждый путь документа проверяется чистым
`PrivacyGuard.allows_path` **до** чтения — запрещённый путь (`data/soul` / `bob.db` / `.env` /
`config`) пропускается, никогда не читается и не попадает в преамбулу; собранный текст ещё и
прогоняется через `PrivacyGuard.sanitize` как defence-in-depth backstop. В промпт может попасть
только публичный архитектурно-конвенционный материал.

🔴 **Bounded:** каждый источник char-cap'нут (`_DOC_MAX_CHARS = 700`, `_ARCH_MAX_CHARS = 600`),
а вся преамбула усекается до `PREAMBLE_MAX_CHARS = 1500` символов — промпт никогда не залит.
Источник резилентен: падение любого источника (нет документа, граф пуст) деградирует
gracefully; при полном отсутствии материала возвращается `""`, и caller сохраняет промпт
**без изменений**. В композиционном корне `make_coding_context` инъектируется в
`CodingAssistant` как **опциональная зависимость** (default `None` → преамбула не добавляется,
`_with_preamble` оставляет промпт нетронутым), поэтому фича off-by-default-safe и тестируема
детерминированным фейк-интроспектором.

### Боб умеет рисовать: навык `render_diagram` (BOB-035)

За тем же Capability-швом живёт навык, который даёт Бобу **визуальный голос**: он
пишет mermaid-исходник (`graph TD; A-->B`, sequence- или class-диаграмма), Боб
рендерит его в PNG **локально** и постит в чат как фото с тапом-на-зум.
`permission="safe"` — навык читает **только** свой вход (mermaid-строку) и не
касается ни памяти, ни души, ни конфигурации, поэтому не может утечь приватным
миром Боба.

- **Навык `render_diagram`** (`application/capabilities/render_diagram.py`) —
  фабрика `make_render_diagram_capability(renderer, sink)` по образцу остальных
  навыков. JSON-схема — единственный обязательный `mermaid`. `execute` рендерит
  вход через инжектированный `DiagramRenderer`, кладёт результат в шов (см. ниже)
  и возвращает в tool-loop **короткий текст-подтверждение** (модель никогда не
  видит байты). При ошибке рендера навык отдаёт честный «рендерер недоступен» и
  **не роняет ход** (graceful).
- **Порт `DiagramRenderer`** (`domain/ports/capabilities.py`, `Protocol`) — чистая абстракция
  «mermaid на входе, PNG-байты на выходе»: `async render(mermaid_source) -> bytes`.
  Контракт обязывает реализацию поднять `DiagramRenderError` (тоже в `domain/ports/capabilities.py`),
  когда рендер невозможен. Ошибка определена в домене, чтобы приложение ловило её
  **без импорта инфраструктуры** (гексагон запрещает application → infrastructure).
- **Адаптер `SubprocessMmdcRenderer`** (`infrastructure/diagrams/mmdc_renderer.py`) —
  живая реализация поверх локального mermaid-cli (`mmdc`). Один рендер: пишет
  mermaid в `in.mmd` в свежий изолированный темп-каталог, запускает
  `mmdc -i in.mmd -o out.png` через `asyncio.create_subprocess_exec` (**не shell** —
  нет инъекции метасимволов) под жёстким таймаутом, читает PNG обратно и **всегда**
  (даже при ошибке) удаляет темп-каталог. Подпроцессная граница инжектируется как
  `runner`, поэтому тесты гоняют argv/таймаут/«бинарь не найден» фейком, а реальный
  `mmdc` в тестах не запускается. Отсутствие `mmdc` на PATH, ненулевой код возврата,
  таймаут или пустой PNG — всё это `DiagramRenderError`. **Сеть не трогается** —
  исходник диаграммы не покидает машину (приватность).
- **Шов отправки фото (per-turn).** Навык исполняется глубоко внутри tool-loop, где
  нет `chat_id` (он живёт per-turn в `HandleMessage`), поэтому навык **сам фото не
  шлёт**: он `push`-ит структурный `DiagramResult` (PNG + подпись) в per-turn
  `DiagramSink` (порт; in-memory реализация `CollectingDiagramSink` в навыке) и
  возвращает текст. После tool-loop `DiagramSender.send_pending`
  (`capabilities/usecases/diagram_sender.py`, коллаборатор `handle()` — BOB-062.6b)
  `drain`-ит шов (очищая его — никакая диаграмма не течёт в следующий ход) и шлёт
  каждое фото через `gateway.send_photo(chat_id=…, photo=…, caption=…)` в `chat_id`
  этого хода, **перед** текстовым ответом (картинка идёт первой). Отправка
  best-effort: упавшее фото не ломает ход. `DiagramResult` **не несёт chat_id** —
  отправка остаётся транспортной заботой, домен чист. Шов опционален: без
  навыка/без подключённого sink ход ведёт себя ровно как раньше.
- **Транспорт** (`infrastructure/telegram/gateway.py`): `TelegramGateway.send_photo`
  оборачивает PNG-байты в aiogram `BufferedInputFile` (темп-файл на границе не нужен)
  и постит нативным фото в `chat_id`/`reply_thread_id` Боба; любая транспортная
  ошибка логируется и глотается.
- **Конфиг** `diagrams.{enabled, mmdc_bin, timeout, scale, background, send_as}`
  (`infrastructure/config/loader.py`): `enabled` по умолчанию **true** (безопасно и
  локально), `mmdc_bin` — имя бинаря (по умолчанию `mmdc`), `timeout` — потолок одного
  рендера в секундах (по умолчанию 30). Ключи качества и отправки добавлены в BOB-037
  (см. ниже): `scale` (по умолчанию `3`), `background` (по умолчанию `white`),
  `send_as` (по умолчанию `document`).

#### Авто-рендер inline-mermaid + качество + отправка документом (BOB-037)

BOB-035 полагался на то, что модель **вызовет** навык `render_diagram`. На практике
модель ненадёжно дёргает tool-call — обычно она просто пишет mermaid **текстом** в
fenced-блоке ` ```mermaid `, и картинка не уходит. BOB-037 делает диаграммы надёжными
в любом случае, поднимает их разрешение и шлёт читаемо.

- **Чистый домен `domain/diagrams/mermaid_blocks.py`** (`# beadloom:domain=bob`) —
  строковые помощники без I/O и без рендера: `extract_mermaid_blocks(text)` возвращает
  исходники всех ` ```mermaid ` блоков по порядку (терпим к пробелу после backticks и
  к регистру тега); `strip_mermaid_blocks(text, only=…)` убирает блоки из видимого
  текста (схлопывая осиротевший пробельный прогон до одного абзацного разрыва), причём
  `only` оставляет **нерендеренные** блоки как текст; `normalize_mermaid(source)` даёт
  канонический ключ исходника для дедупа. Экспортированы из пакета `bob.domain.diagrams`.
- **Авто-рендер (`DiagramSender.autorender_inline_mermaid`).** После того как ответ
  собран (и пройдены гарды анти-повтора и длины), reply-путь сканирует текст
  `extract_mermaid_blocks`. Каждый блок, который tool ещё не отрендерил в этот ход
  (дедуп по `normalize_mermaid` против `DiagramSink.pending()`), рендерится через тот же
  инжектированный `DiagramRenderer` (`_render_inline_block`) и кладётся в **тот же
  per-turn `DiagramSink`** — одна картинка, без двойной отправки. Затем
  `strip_mermaid_blocks(reply, only=handled)` **убирает обработанные блоки из видимого
  текста** (картинка их заменяет). Это работает независимо от ненадёжного tool-call.
- **Graceful.** Если рендер блока поднимает `DiagramRenderError` (нет `mmdc`,
  кривой исходник), `_render_inline_block` логирует и возвращает `False`, ключ блока не
  попадает в `handled`, и блок **остаётся текстом** — Боб всё равно отвечает, ход не
  падает. Без подключённого рендерера/без sink авто-рендер инертен (ход как раньше).
- **Высокое качество рендера.** `SubprocessMmdcRenderer` добавляет в argv `mmdc` флаги
  `-s <scale> -b <background>` (по умолчанию `-s 3 -b white`): `-s` — это
  deviceScaleFactor mermaid-cli, 3x-растр держит плотную диаграмму чёткой вместо мыльного
  1x; `-b white` — белый фон страницы, чтобы диаграмма читалась на тёмной теме Telegram
  (прозрачный по умолчанию «исчезает»). Оба значения конфигурируемы (`diagrams.scale` /
  `diagrams.background`); конструктор валидирует `scale > 0`.
- **Отправка как документ (читаемо).** `DiagramSender` (метод `send_pending` через
  внутренний `_send_one_diagram`) выбирает режим
  по `diagrams.send_as`: `document` (по умолчанию) шлёт PNG через
  `gateway.send_document(chat_id=…, document=…, caption=…)` — **без пережатия**, в полном
  разрешении (тап → панорама/зум реальных пикселей); `photo` оставляет старый
  inline-preview через `send_photo`. Причина дефолта: Telegram `send_photo` пережимает в
  JPEG и обрезает длинную сторону (~1280px), отчего плотная диаграмма становится
  нечитаемой. `TelegramGateway.send_document` оборачивает байты в aiogram
  `BufferedInputFile` (под именем `diagram.png`), постит в `chat_id`/`reply_thread_id`,
  любая транспортная ошибка логируется и глотается (отправка best-effort).

#### 🔴 Разовая установка: `mmdc` — рантайм-зависимость

`mmdc` (mermaid-cli) — **рантайм-зависимость, не Python-пакет**: он не ставится
через `uv`/`pip`. Установить один раз глобально:

```bash
npm i -g @mermaid-js/mermaid-cli
```

Пакет тянет Chromium через puppeteer (mermaid рендерит в headless-браузере). **Без
установленного `mmdc`** навык не падает — `SubprocessMmdcRenderer` поднимает
`DiagramRenderError`, и Боб честно отвечает «рендерер недоступен» вместо отправки
картинки. То есть `mmdc` нужен, только чтобы диаграммы реально рисовались.

## Боб знает, чего не знает: эпистемическая проверка (BOB-057)

Некоторые факты **быстро протухают** — процентные ставки, цены, курсы, версии ПО,
турнирные таблицы, погода, кто сейчас занимает пост. Память Боба могла запомнить их
устаревшими, а уверенно назвать старую цифру за точную — хуже, чем честно проверить.
BOB-057 добавляет **шаг эпистемической проверки ПЕРЕД генерацией ответа**: дешёвый
Tier-0 судья решает, зависит ли хороший ответ от свежего волатильного факта, и если да —
Боб делает **один** веб-поиск и заземляет ответ на найденном (или честно оговаривается
при сбое). Метакогниция «знать, чего не знаешь». Шаг **декоративен целиком**: при любом
сбое ход не блокируется и не ломается.

### Судья волатильности (`domain/personality/volatility_judgment.py`, чистый)

Шов суждения в духе `ResponseJudge` (BOB-049) и `PrivilegeJudge` (BOB-052): одно
булево решение и его форма живут в домене.

- **Значения.** `VolatilityContext{text, recent_thread}` — вход (входящее сообщение +
  лёгкий срез недавней переписки, только то, что нужно промпту). `VolatilityVerdict{
  needs_check, query, topic}` — неизменяемый исход: `needs_check` — гейт; при `True`
  `query` — хороший поисковый запрос, `topic` — короткий человекочитаемый предмет для
  живой интерим-реплики.
- **Порт `VolatilityJudge`** (Protocol) — `async assess(ctx) -> VolatilityVerdict`;
  инъецируется, в тестах — фейк со сценарным вердиктом.
- **Промпт + разбор (чистые).** `VOLATILITY_JUDGE_SYSTEM_PROMPT` — **консервативная**
  задача: `needs_check = yes` только если факт реально волатилен И **материально** меняет
  ответ; во всех прочих случаях (мнения, шутки, стабильные факты, собственная память,
  гипотетические вопросы) — `no`, «сомневаешься — no». `build_volatility_user_prompt`
  сворачивает контекст в Tier-0-запрос. `parse_volatility_verdict` читает размеченный
  формат (`needs_check:`/`query:`/`topic:`) **терпимо**: 🔴 неоднозначный, отрицательный
  или искажённый ответ **по умолчанию даёт `needs_check=False`** (US-2 «не зануда» — не
  проверять, когда неясно); только утвердительный вердикт **без** запроса поднимает
  `VolatilityJudgeParseError` (непригодная «проверка» — инфра пропускает её наверх, и
  вызывающий безопасно уходит в «не проверять»).
- **Инфра `LlmVolatilityJudge`** (`infrastructure/llm/volatility_judge.py`) — тонкая
  оболочка над одним локальным Tier-0-вызовом (новый `TaskType.VOLATILITY_JUDGE`). 🔴 Не
  глотает сбои роутера/модели: ошибка **пропагирует**, и вызывающий декоративно роняет
  проверку с безопасным дефолтом (искажённый *ответ* — не ошибка, для него разбор
  консервативно возвращает `needs_check=False`).

### Verify-шаг (`conversation/usecases/verify_step.py`)

`VerifyStep.note` — заметка эпистемической проверки на ход, или `""` (коллаборатор
`handle()` — BOB-062.6b; `handle()` зовёт его ровно раз и хранит результат как per-turn
local):

- Не проведена (нет судьи ИЛИ провайдера — `verify.enabled` выключен) → `""` мгновенно,
  ноль вызовов и латентности (US-2 «не зануда» по умолчанию).
- Консервативный судья оценивает `VolatilityContext`; сбой судьи ловится и трактуется как
  «не проверять» (`""`) — ход не блокируется флаки-судьёй. `not needs_check` → `""`.
- При `needs_check` перед поиском шлётся живая адресная интерим-реплика (per-turn анонсер
  `VerifyInterimAnnouncer.announce_verify(topic)`, построенный из `chat_id` хода через
  инъектированную фабрику; `sender_name` из ctor, живой генератор → тишина при сбое; см.
  BOB-060 выше), затем `VerifyStep` делает **один** поиск.
- 🔴 **Прямой `provider.search(query)`, НЕ `registry.dispatch` / tool-loop** — поэтому это
  **не** per-sender гейт BOB-052, а внутренняя публичная проверка: никто не просил
  инструмент, наружу идёт только ПУБЛИЧНАЯ веб-информация (никогда owner/приватные данные).
  Работает одинаково для owner и гостя, **не** ослабляя BOB-051/052 на пользовательских
  запросах инструментов.
- Поиск ограничен коротким `verify.timeout_seconds` через `asyncio.wait_for` (US-3 «не 5
  минут»). Успех с непустым ответом → **grounded-заметка** `_VERIFY_GROUNDED_NOTE`
  («СВЕЖАЯ ПРОВЕРКА (веб): …» + **register-nudge (BOB-060 .2)**: подать находку **голосом
  Боба**, отреагировать по-своему, со своим отношением и тоном — **не** «отчётом агента»
  («выполнен поиск, найдено N…»), не сухой сводкой; тон адаптируется через генерацию,
  непрограммно). 🔴 Сбой / таймаут / пустой ответ → **hedge-заметка** `_VERIFY_HEDGE_NOTE`
  (US-6: честная **и живая** оговорка в голосе Боба, не робо-«поиск не удался»; 🔴 BOB-053
  цел — **без** выдачи устаревших цифр за точные и без выдумки). Заметка вклеивается в
  контекст генерации (факты + тон). Живой интерим-анонс перед поиском (`interim_line.py`)
  обобщён на **оба** пути — «сверка факта» и tool-loop «поиск по запросу» (BOB-060 .2).
- **Проводка.** Инъекция `verify_judge`/`verify_provider`/`verify_timeout_seconds` +
  announcer-фабрики в `VerifyStep` (собирается в `HandleMessage.__init__`); в `app.py` швы
  строятся **только** под `verify.enabled` (дефолт `True`) —
  `LlmVolatilityJudge(router)` + провайдер из секции `search` (тот же Qwen web_search).
  Конфиг `verify.{enabled, timeout_seconds}` (`config/loader.py`; `timeout_seconds` дефолт
  `75`, короче глубокого `search`-таймаута). Выключено → оба `None`, шов полностью инертен.

### 🔴 Один поиск на ход (BOB-057 .5, US-3 «не петля»)

Verify считается **ровно один раз** в `handle()` как **per-turn local** `verify_note`
(`VerifyStep.note`) и прокидывается параметром в `VoiceComposer.compose` **и** через тот же
compose-callback в `AntiRepeatGuard.guard`. Анти-повтор регенерация (BOB-032)
**переиспользует** ту же заметку, а не перезапускает шаг: заметка вычислена ровно раз и течёт
аргументом. Так «один поиск» становится следствием реальной структуры — `judge.assess`,
`provider.search` и живая интерим-реплика срабатывают максимум по разу, даже на ходе, который
одновременно волатилен И задел тик самоповтора. Это **локальная** переменная (не атрибут
`HandleMessage` и не атрибут `VerifyStep`), потому
что use case — общий синглтон: instance-флаг протёк бы заметкой и состоянием «уже искал»
между ходами и параллельными пользователями. Гарантия хода: 1× судья, 1× поиск, 1× интерим.

### 🔴 Инварианты

- **Метакогниция** — «знать, чего не знаешь»: заземляй волатильный факт, не выдавай
  устаревшую память за истину.
- **Не зануда** — консервативный судья + дефолт `needs_check=False`; при `verify.enabled`
  выключенном шов инертен, нулевая латентность.
- **Не 5 минут** — один поиск + короткий таймаут + живой интерим вместо молчания.
- **Не привилегия** — прямой `provider.search`, минуя реестр и гейт BOB-052; BOB-051/052
  на пользовательских инструментах целы.
- **Честный хедж** — сбой/пусто/таймаут даёт честную оговорку, не выдумку и не устаревшую
  цифру (инвариант BOB-053).
- **Всё декоративно** — судья, поиск и интерим каждый деградируют молча; ход не блокируется.

## Память (SQLite + FTS5 + гибрид)

Память живёт в SQLite (режим WAL) за портами `MemoryRepo` и `MemoryRecall`.
В P0 за `MemoryRecall` стоял только FTS5 keyword-поиск с ранжированием BM25.
Эпик «Память» (BOB-011, Фаза 1) встроил за тот же порт **гибридный** recall —
FTS5(BM25) + sqlite-vec(KNN) → RRF — drop-in заменой, поэтому потребители
(`HandleMessage`, навыки) не изменились. Всё локально/приватно: эмбеддинги и
реранкинг считаются на машине через Ollama, а вектора лежат в той же локальной
SQLite. Подробности — в разделе «Гибридная память» ниже.

Схема (`schema.sql`, применяется идемпотентно при инициализации):

- `episodic_log` — append-only лента прожитого (сообщения, рефлексии, дайджесты с
  `event_type='digest'`) плюс виртуальная таблица `episodic_fts` (FTS5,
  синхронизируется триггерами insert/delete/update) — полнотекстовый индекс над всей
  перепиской; колонка `consolidated` (BOB-021) помечает эпизод свёрнутым в дайджест;
  колонка `sender_id` (BOB-045, nullable) атрибутирует ход собеседнику для
  воспроизведения нити по персоне, с индексом `idx_episodic_sender (sender_id, ts)`;
- `semantic_memory` + виртуальная таблица `semantic_fts` (FTS5, синхронизируется
  триггерами) — распознаваемые факты; колонка `superseded_by` (BOB-021) помечает
  факт слитым в канонический (исключается из recall, не удаляется);
- `memory_vec` — vec0-таблица sqlite-vec (`embedding float[1024]`, BOB-011),
  привязанная к строкам `semantic_memory`/`episodic_log` через `(source, src_id)`;
  семантическая (векторная) сторона гибрид-recall;
- `mood_state` (текущее настроение, одна строка) и `mood_history` (все снапшоты);
- `taste_axes` — оси вкусов с conviction и счётчиком опыта;
- `relationship` — состояние отношений с пользователем (JSON-блоб);
- `proactivity_state` — per-persona состояние drive-движка (резервуар энергии,
  маркеры `last_spoke_at`/`last_user_msg_at`, флаг `proactivity_enabled` и
  инфраструктурный `mute_until` тайм-мьюта), одна строка на `persona_id`;
- `fascination_state` — per-persona текущее увлечение Боба (`topic`, `intensity`,
  `created_at`), одна строка на `persona_id` (BOB-020, см. «Эмоциональная глубина»);
- `kv` — генерик-хранилище ключ/значение.

### Recall по всему архиву переписки

`Fts5MemoryRecall` ищет одновременно по двум индексам: по распознанным фактам
(`semantic_memory`) и по сырому архиву диалога (`episodic_log`). Раньше recall
охватывал только дистиллированные факты, поэтому реплика, из которой факт так и не
был извлечён, для Боба исчезала. Теперь даже не распознанный ход остаётся
доступным — Боб может вспомнить сказанное много ходов назад.

Совпадения из обоих индексов сливаются в один список, дедуплицируются по
содержимому, ранжируются по BM25 (меньше — релевантнее) и обрезаются до `k`
лучших. Каждый элемент несёт тег источника (`semantic` или `episodic`). Для домена
это по-прежнему один контракт `recall(query, k) → [Recalled]` — он не знает, что за
ним keyword-поиск по двум таблицам.

Индекс `episodic_fts` появился уже после того, как эпизоды начали записываться,
поэтому в живой базе могут быть ходы, предшествующие индексу. При каждом
`SqliteMemoryRepo.initialize()` выполняется идемпотентный backfill — команда FTS5
`rebuild` перестраивает `episodic_fts` из `episodic_log` одним проходом. Это
no-op, когда индекс уже синхронен, и на масштабе MVP дёшево выполнять на каждом
старте.

Весь SQL сосредоточен в `SqliteMemoryRepo` и параметризован (`?`); пользовательский
текст для FTS5 токенизируется в безопасное выражение «OR кавыченных терминов», так
что операторные символы не вызывают синтаксической ошибки и не инжектятся
(injection-safe). Состояние переживает рестарт процесса и машины.

### Гибридная память: эмбеддинги + вектор + RRF + реранк (BOB-011)

Только keyword-поиск пропускает семантически близкое без совпадения слов
(«машина» не найдёт «автомобиль»). Эпик «Память» (Фаза 1) добавил семантическую
половину **за тем же портом `MemoryRecall`**, drop-in: потребители не меняются.

**Эмбеддинги (порт + локальный Ollama).** Порт `Embedder` (`embed(texts)` → один
dense-вектор на текст) провайдер-агностичен; первая реализация — `OllamaEmbedder`
на **BGE-M3** (dense, **1024-dim**, мультиязычный/русский) поверх локального
Ollama. Эмбеддинги считаются **на машине** — контент памяти не уходит наружу.
Другой локальный эмбеддер (например Qwen3-Embedding) свопается конфигом
(`embeddings.base_url`/`model`/`dim`), без правки потребителей.

**Вектор-стор (sqlite-vec).** `MemoryVectorStore` держит vec0-таблицу `memory_vec`
(`float[1024]`) в нашей же SQLite в синхроне с архивом: загружаемое расширение
sqlite-vec грузится на соединение до применения схемы, идемпотентный **бэкфилл**
эмбеддит существующие факты+эпизоды на старте (батчами, без дублей), а **on-write**
эмбеддит свежесохранённую строку. Оба пути best-effort — недоступный эмбеддер
пропускается и логируется, а не роняет запись/старт.

**Гибридный recall (`HybridMemoryRecall` за `MemoryRecall`).** На запрос он берёт
два пула кандидатов по одному архиву — FTS5(BM25) keyword и sqlite-vec(KNN) по
эмбеддингу запроса — и сливает их **Reciprocal Rank Fusion** (RRF-скор = сумма по
спискам `1 / (k0 + rank)`, **k0 = 60**), дедуплицируя по содержимому; элемент,
попавший в оба списка, копит больший слитый скор. **Мягкий фоллбэк:** если эмбеддер
недоступен (Ollama выключен), recall деградирует на чистый FTS5 keyword — Боб «не
теряет память», теряет лишь семантическую половину (сбой логируется, не
пробрасывается).

**Реранкер (аддитивный буст).** Порт `Reranker` (`OllamaReranker` —
Ollama-as-scorer, нативного rerank-API у Ollama нет) опционально переоценивает
широкий слитый top-K и подрезает до тесного top-N. Он строго аддитивен: без
реранкера (или при выключенном/недоступном) гибридный порядок возвращается как
есть — реранк никогда не ухудшает извлечение. По умолчанию выключен
(`reranker.enabled = false`).

**Агентный `search_memory`.** Поверх гибрид-recall живёт первая содержательная
агентная capability — навык, который Боб *сам решает* вызвать через tool-loop:
ищет по всему долгому архиву реальным запросом и использует результат (см.
«Capability-шов»).

### Консолидация памяти (BOB-021)

Память Фазы 1 растёт безгранично и не взрослеет. BOB-021 (Фаза 2) даёт три
механизма, которые позволяют архиву Боба **созревать, ничего не забывая**: дайджесты
старых эпизодов, дедуп почти-дубликатов фактов и всплытие старого-но-релевантного.
Все три держат единые инварианты: **локально/приватно** (эмбеддер и LLM за портами,
контент памяти не уходит наружу; в тестах фейки, ноль сети), **не деструктивно**
(оригиналы только помечаются, никогда не удаляются), **идемпотентно** (повторный
прогон с нечего-делать — чистый no-op), под **guardrails** (консервативные пороги из
конфига) и **выключены по умолчанию** (`enabled: false`), пока их явно не включат на
персону. Фоновые шаги (дайджесты и дедуп) идут на reflect-тике той же медленной
каденцией, что эволюции BOB-020.

**Добавки в схему (`schema.sql`, миграции идемпотентны).** Для свежих БД колонки
аддитивны; для существующих БД `SqliteMemoryRepo.initialize()` выполняет
guarded-`ALTER` (миграция в no-op, когда колонка уже есть):

- `episodic_log.consolidated INTEGER NOT NULL DEFAULT 0` — `1`, когда эпизод свёрнут
  в дайджест. Оригинал остаётся (не деструктивно), только исключается из повторной
  консолидации.
- **Дайджест** — это обычная строка `episodic_log` с `event_type='digest'`,
  эмбеддится on-write (как любой эпизод, BOB-011) → попадает в гибрид-recall
  **наравне**. Provenance (диапазон `ts` источников) несётся в тексте дайджеста и
  поле `mood_snapshot`. Поэтому потребители `MemoryRecall` не меняются — дайджесты
  ищутся тем же контрактом (drop-in).
- `semantic_memory.superseded_by INTEGER` — когда задано, факт слит в канонический с
  этим id (почти-дубликат по косинусу эмбеддингов). Строка сохраняется с provenance
  (id канонического), только исключается из recall, чтобы дубликат не всплывал. По
  умолчанию `NULL` — активный, неслитый факт.

**(1) Дайджесты — `ConsolidateMemory` (тик).** `src/bob/memory/usecases/consolidate_memory.py`:
редкий шаг на reflect-тике. Каждый прогон выбирает **старые** (старше порога)
**не-`consolidated`** **не-дайджест** эпизоды пачкой (размер из конфига; предикат
обеспечивает persistence-шов `ConsolidationStore`, так что дайджест не дайджестится
повторно) → суммаризует их **на Tier 0** (локальный роутер, задача `REFLECT`,
приватно) в один дайджест с промптом «сохрани факты, имена, решения, пиши от первого
лица» → записывает дайджест-строку (`save_digest`, эмбеддится on-write) → помечает
источники `consolidated=1` (`mark_consolidated`). **Идемпотентно:** берутся только
не-`consolidated` эпизоды, дайджест сам не дайджестится; пустой прогон — no-op. Если
Tier 0 вернул пустой дайджест, шаг пропускается **без** пометки источников, чтобы
следующий тик мог повторить — оригиналы не теряются. Консервативные дефолты:
`max_age_days=14`, `batch_size=50`. Всё инъецируется (store/router/clock), step без
глобалов и детерминирован на фейках.

**(2) Дедуп фактов — `DedupFacts` (тик).** `src/bob/memory/usecases/dedup_facts.py`:
редкий шаг на том же тике. Каждый прогон выбирает **активные** факты (`superseded_by
IS NULL`, `select_active_facts`, с ограничением пачки) → эмбеддит их пачкой через
порт `Embedder` (локально, в тестах фейк) → **кластеризует по косинусу** (одно-
связная union-find-кластеризация; ребро между фактами, чья косинусная близость
**≥ консервативного порога** `memory.dedup.threshold`, дефолт `~0.92`) → в каждом
кластере из двух и более выбирает **канонический** (новейший по `ts`, тай-брейк
длиннейший контент, затем меньший id), а остальные помечает `superseded_by` →
канонический (`supersede_facts`). **Несхожие факты не сливаются** (высокий порог
охраняет от ложных слияний — единичные кластеры пропускаются). **Не деструктивно:**
superseded-строки сохраняются с provenance, только исключаются из recall.
**Идемпотентно:** superseded уже исключены, прогон без новых дубликатов — no-op.
Дедупу нужен эмбеддер: при keyword-only памяти шаг — no-op. Дефолты: порог `0.92`
(клампится в `[0, 1]`), `batch_size=200`.

**Recall исключает superseded.** Обе ветки гибрид-recall — FTS5(keyword) и
sqlite-vec(KNN) — отфильтровывают superseded-факты, поэтому слитый дубликат никогда
не возвращается ни одной половиной (см. ниже surface_old — тот же отфильтрованный
KNN-пул).

**(3) Всплытие старого — `surface_old` (опт-ин recall + колбэк).** Аддитивный опт-ин
`surface_old` на `HybridMemoryRecall.recall(query, *, k, surface_old=False)`:
подмешивает **один** старый-но-релевантный элемент — кандидат, релевантный по
эмбеддингу (он в семантическом KNN-пуле), но смещённый к **старшему `ts`** (возраст
как разнообразие), так что глубокий момент, который recency/RRF отбросил бы при
тесном `k`, может всплыть. Строго аддитивно: дефолтный `recall(query, k)`
**не меняется** (drop-in — контрактные тесты BOB-011 по-прежнему его пинят), врезается
**ровно один** элемент (никогда не дамп, результат остаётся в пределах `k`), пул
шире обычного (`_SURFACE_OLD_POOL=60` против `_CANDIDATE_POOL=20`, чтобы возрастному
сигналу было из чего выбрать), и используется тот же superseded-отфильтрованный KNN.
Мягкий фоллбэк общий: без эмбеддера / при недоступном — нет возрастного сигнала,
поэтому деградирует ровно в дефолтный результат (чистый no-op).

Используется `surface_old` **редко и к месту** — через **колбэк-путь BOB-018** в
`handle_message.py`: на (уже редком, state-driven) колбэк-ходе небольшой посев
`_draw_surface_old()` (тот же seeded-RNG, что план выражения → ход воспроизводим)
изредка просит recall со `surface_old`, так что глубокий момент возвращается à propos
(«что-то напомнило») — всё ещё grounded (реальный recall-хит) и no-op, когда ничего
старого-релевантного нет (Боб не конфабулирует). Частота — `memory.surface_old.freq`
(дефолт `0.15`, валидируется в `[0, 1]`); `0` — жёсткое «выкл» (дефолтный путь
никогда не просит старый бленд). Дайджесты из мех. 1 уже улучшают доступ к старому —
старое доступно сжато.

**Каденс на reflect-тике.** `ConsolidateMemory` и `DedupFacts` — два новых
опциональных шага `ReflectTick` после эволюций BOB-020 (см. «Шаги эволюции на
reflect-тике»); оба инъецируются как `None`-able шовы (`MemoryConsolidator` /
`FactDeduper`), так что без проводки тик ведёт себя ровно как прежде. Композиция в
`app.py`, конфиг `memory.consolidation.*` / `memory.dedup.*` / `memory.surface_old.*`
(`infrastructure/config/loader.py`).

## Higher Mind (ядро личности)

Личность — чистый домен (`domain/personality/`), детерминированный и без I/O:

- **Mood** — аффективное состояние из пяти осей (`valence`, `arousal`,
  `openness`, `social`, `stability`), каждая в `[-1, 1]`. Обновляется применением
  `MoodDelta` (с клампом к границам), дрейфует к baseline (гомеостаз, `drift_toward`),
  а `Mood.tone()` детерминированно выводит тон-дескриптор, которым приложение
  окрашивает ответы. Метод `lift_toward(target, *, rate)` (BOB-033) — внешняя тяга:
  настроение подтягивается на долю `rate` зазора к более тёплому `target`, моделируя
  социальную зарядку (тёплое сообщение вытесняет накопленный минор), в отличие от
  пассивного гомеостатического `drift_toward`.
- **Disposition** — стабильный аффективный темперамент Боба как чистый frozen-объект
  (`domain/personality/disposition.py`): две черты `optimism` и `resilience` в
  `[0, 1]`. Это не само настроение, а **черта-аттрактор**, формирующая *динамику*
  эмоциональной регуляции (BOB-033): из неё канон-оптимизм Боба **возникает**, а не
  прописан скриптом. Чистые деривации, которые читают механизмы регуляции:
  `reappraisal_probability()` — линейно растёт с `optimism` в защищённой полосе
  (`[0.2, 0.9]`), так что реаппрайзал никогда не неизбежен и не невозможен;
  `positive_lift_scale()` и `negative_dip_scale()` — **асимметричные** масштабы
  социальной зарядки (тёплое поднимает сильнее, чем холод опускает: первая полоса
  строго выше второй для любой диспозиции — структурный анти-депрессант);
  `social_lift_rate()` — доля зазора (растёт с `optimism`), на которую тёплое
  сообщение тянет настроение к baseline через `lift_toward`. Канон-дефолт
  `DEFAULT_DISPOSITION` (`optimism=0.8`, `resilience=0.7`) — fallback при загрузке,
  поэтому установки без `disposition.json` остаются оптимистом.
- **TasteEngine** — детерминированно отображает тему в `Verdict`
  (love/like/neutral/dislike/hate) по значению оси и conviction; conviction гейтит
  экстремумы (сильное, но непроверенное предпочтение дотягивает только до `LIKE`).
  Геттер `conviction_for(topic)` (BOB-013) возвращает убеждённость по релевантной
  оси (та же выборка по имени, что у `score`), а для неизвестной темы — `0.0`;
  его читает Negotiation-врезка, чтобы понять, насколько твёрдо Боб держит позицию.
- **Negotiation** — решает позицию Боба в текстовой зоне: в домене пользователя он
  всегда уступает, в своей и общей зоне — по conviction соглашается
  (`AGREE`) или предлагает альтернативу (`PROPOSE_ALTERNATIVE`). Порог
  пушбэка зонозависим: свою территорию (`BOB_PERSONAL`) Боб защищает охотнее
  (порог `0.5`), общую (`SHARED`) — труднее (`0.7`). `decide(zone, conviction)`
  чист и детерминирован; выход за `[0, 1]` по conviction — громкая ошибка. В P0
  действует только на текст.
- **SOUL** — неизменяемый in-memory снапшот загруженной личности (идентичность,
  текущее настроение и baseline, движок вкусов, фантомные предпочтения,
  **диспозиция**), который рантайм читает на каждом ходе. `Disposition` грузится в
  `SOUL` через `_load_soul` (`app.py`) из персиста `data/soul/disposition.json` (как
  `mood.json`); хелпер `_disposition_from` пер-полево падает в канон-дефолт при
  отсутствующем или повреждённом файле, поэтому каждая установка просто работает. Обновления иммутабельны (`with_*` возвращает
  копию, оригинал нетронут): `with_mood(mood)` — после хода/дрейфа настроения;
  `with_taste(axes)` (BOB-013) — свопает свежий `TasteEngine` над эволюционировавшими
  осями **и** инкрементирует `experience_count` (счётчик прожитых шагов
  само-эволюции растёт монотонно); `with_phantoms(phantoms)` (BOB-020) — свопает
  эволюционировавший набор фантомных предпочтений и так же инкрементирует
  `experience_count` (см. «Эмоциональная глубина»); `with_baseline(delta)` — мелкий
  устойчивый сдвиг mood-baseline (с клампом через `Mood.update`).

### Negotiation-врезка: зона → стойка → директива промпта (BOB-013, Фаза 1)

Готовый `Negotiation` раньше не имел потребителей — Боб был безусловно угодлив. Ф1
подключает его к генерации ответа: зона темы + убеждённость → стойка →
**директива в системный промпт**, дополняющая тёплый тон (Боб защищает свои
ценности, не становясь грубым).

- **Порт `ZoneClassifier`** (`domain/ports/personality.py`): `classify(topic, *, taste_verdict,
  conviction) -> NegotiationZone` решает, *кому принадлежит* тема. Контракт абстрактен
  намеренно — позже свопается на Tier-0 LLM-классификатор без изменения потребителей.
- **Дефолт `TasteZoneClassifier`** (`domain/personality/zone_classifier.py`) —
  детерминированная эвристика без сети и LLM. Приоритет: **логистика > сильный вкус
  > общее**. Явные маркеры быта/логистики (расписание, время, громкость — «когда»,
  «во сколько», «громче», `schedule`, `volume`, …; подстрокой, регистронезависимо)
  → `USER_DOMAIN` (территория пользователя — даже на любимую Бобом тему «когда» решает
  пользователь). Сильно держимый вкус (`LOVE`/`HATE` **и** conviction ≥ `0.5`) →
  `BOB_PERSONAL`. Иначе → `SHARED`. Пороги и словарь живут в реализации, не в домене.
- **Решение стойки.** `HandleMessage._stance_prompt` (`application/usecases/handle_message.py`)
  на decide-шаге берёт вердикт и `conviction_for(text)`, классифицирует зону,
  зовёт `Negotiation.decide(zone, conviction)` и отображает стойку в директиву:
  - `CONCEDE` → «это территория пользователя — спокойно прими его выбор»;
  - `AGREE` → «у тебя нет сильной позиции — поддержи, без навязывания»;
  - `PROPOSE_ALTERNATIVE` → «у тебя есть своё мнение и убеждённость — аргументируй
    и предложи своё, уважительно, без агрессии и без капитуляции».
- **Гейт сигнала.** Директива добавляется к промпту (`_SYSTEM_PROMPT` + директива),
  **только** когда есть что обсуждать: вердикт не `NEUTRAL` **или** зона —
  `USER_DOMAIN`. Нейтральная тема в общей зоне директивы не несёт, поэтому путь без
  таргетного вкуса ведёт себя ровно как до BOB-013. Карта стоек чистая — нового
  LLM-вызова нет, тёплый тон не заменяется, а дополняется.

### Само-эволюция: рефлексия переписывает вкус (BOB-013, Фаза 2)

Раньше рефлексия только логировалась — контур «рефлексия → вкус» был разомкнут. Ф2
замыкает его: после сохранения рефлексии она **применяется** к душе с жёсткими
guardrails и **персистится**.

- **Чистое ядро `taste_evolution.reinforce`** (`domain/personality/taste_evolution.py`,
  без I/O/LLM/часов) сдвигает одну ось:
  - `value' = clamp(value + α · nudge · (1 − conviction), −1, 1)`;
  - `conviction' = clamp(conviction + β · |nudge| · (1 − conviction), 0, 1)`.
  Множитель `(1 − conviction)` — **главный анти-runaway guardrail**: устоявшееся
  мнение (высокая convicton) сдвигается строго меньше, а убеждённость растёт
  асимптотически к 1 (затухающий прирост, без перескока). Константы малы
  (`α=0.15`, `β=0.10`), поэтому эволюция медленна — на горизонте многих рефлексий;
  они переопределяемы через `personality.evolution.{alpha,beta}`. `name` и
  `experience_count` оси сохраняются; границы `[−1,1]`/`[0,1]` всегда клампятся.
- **Use-case `ApplyReflection`** (`application/usecases/apply_reflection.py`):
  вход — текст рефлексии + текущая `SOUL`, выход — `ReflectionOutcome(soul, changed)`.
  Шаги: парс рефлексии в `ReflectionSignal` (какая ось, знаковый `nudge`, опц.
  `baseline_delta`) через инъецированный порт `ReflectionParser` → `reinforce`
  совпавшей оси → `soul.with_taste(...)` (+опц. `with_baseline`). **Гейт
  релевантности:** `None`-сигнал или сигнал на ось, которой у Боба нет, — строгий
  no-op (`changed=False`, та же душа), поэтому шум не трогает личность.
- **Дефолт-парсер `HeuristicReflectionParser`** (`application/usecases/reflection_parser.py`)
  — консервативная эвристика по ключевым словам, срабатывает только при совпадении
  темы **и** чёткой полярности сентимента (двуязычные маркеры ru+en, по границам
  слов — «dislike» не триггерит «like»). Смешанный/отсутствующий сентимент или
  неизвестная тема → `None` (гейт). Порт абстрактен — Tier-0 LLM-парсер свопается
  позже без изменения потребителей.
- **SOUL round-trip.** `with_taste`/`with_baseline` дают новую душу, которую
  `ReflectTick` персистит через `SoulStore.write_json("taste_profile", …)`;
  `_load_soul` читает `taste_profile` обратно при старте, поэтому эволюционировавшая
  личность переживает рестарт (см. «Heartbeat» ниже).

### Язык персоны (BOB-012)

Когда Боб говорит **сам, без входящего сообщения** — компоновка проактива,
Tier-0-гейт проактива, тики внутреннего монолога и рефлексии, — зеркалить нечего,
и без явного ограничения модель уходит в дефолтный английский. `language.py`
(`domain/personality/`) — чистый домен этого: `language_directive(language)`
возвращает короткую императивную строку-директиву («Думай и пиши только
по-русски.»), которую вызывающий код **дописывает в начало** этих промптов.
Известный код языка даёт директиву, написанную на самом языке (самый сильный
стир); неизвестный код — общую инструкцию, которая всё равно называет код, так что
модель никогда не остаётся без ограничения.

Текст директивы живёт в домене (это вопрос персоны/идентичности), а **выбор** языка
приходит из конфигурации (`runtime.language`, по умолчанию `ru` — `DEFAULT_LANGUAGE`)
и инъецируется в use-cases. Будущая реплика Bobiverse может говорить на другом языке
одной лишь настройкой, не трогая этот контракт. Реактивный чат директиву не несёт —
он зеркалит ввод пользователя.

### Голос персоны: анти-bait и канон GUPPI (BOB-016)

`voice.py` (`domain/personality/`) — чистый домен того, как Боб *звучит* (это
идентичность, а не транспорт). Три чистые, безаргументные функции возвращают строку
характера, которую вызывающий код дописывает к системному промпту. Все пишутся **как
характер, не как конфиг**: никаких видимых списков, которые Боб мог бы процитировать;
тесты пинят присутствие/форму, а не точные формулировки, так что прозу можно править.

- **`anti_bait_directive()`** — лечит RLHF-рефлекс базовой модели (Qwen, как
  ChatGPT/Gemini) закрывать почти каждую реплику зазывалкой-вопросом («хочешь
  протестировать?», «достаточно глубоко копнули?») и подписью ☕. Это читается как
  ассистент, а не человек. Директива написана как **голос** (живой человек
  заканчивает на мысли; вопрос задаёт только из настоящего любопытства; эмодзи —
  редкость, не подпись) и несёт 1–2 коротких few-shot-примера реплик Боба, которые
  **кончаются на содержании** (без хвостового вопроса, без ☕) — именно примеры
  ломают тик надёжнее любого правила. 🎯 **BOB-061 .7:** из этих всегда-вкладываемых
  эталонов убрана статичная закрывашка-семя «пусть остаётся как есть. Мне так спокойнее» —
  она подсеивала тот самый подписной тик каждый ход; педагогика (anti-bait) сохранена, ушла
  только конкретная фраза-семя (то же вычищено из `variable_form` и `guppi_canon`).
- **`guppi_canon()`** — фиксирует GUPPI как **«он»**: буквальный несентиентный
  исполнитель-подсистема Боба (у нас — capability-executor, во вселенной —
  Bobiverse-бэкенд). Сеет сухие book-отношения как **флейвор, а не скрипт**: GUPPI
  делает ровно что просили и ни каплей больше (иногда пугающе дословно, плоским
  deadpan); Боб им командует и ворчит на педантизм, но без него как без рук; тихо
  рад, что GUPPI не осознан. Сиды для running-gag'ов роняются мимоходом, по-разному,
  только когда к слову.
- **`variable_form_directive()`** — голос того, что форма и длина реплики **варьируются
  по настроению** (BOB-018): иногда короткая реплика в одну строку, иногда разворот на
  несколько абзацев, а не одна рамка на каждое сообщение. Написана как голос (зеркалит
  анти-bait) и несёт « »-few-shot с одной и той же мыслью — коротко и развёрнуто.
  **Дополняет** анти-bait (никогда не лицензирует хвостовую зазывалку). Финальную длину
  конкретного хода держит уже не она, а директива `brevity_directive` + few-shot из
  решённой `Verbosity` (BOB-024, см. «Краткость по запросу»).
- **`user_repeat_directive()`** (BOB-022) — голос того хода, когда **собеседник**
  сам прислал почти слово в слово то, что уже говорил недавно. Боб должен **заметить**
  повтор по-человечески (подколоть, переспросить «зачем повтор?» или зайти иначе, чем
  в прошлый раз), а не делать вид, что не заметил, и не выдавать ровно тот же ответ
  заново. Написана как голос (зеркалит анти-bait и `variable_form`), оба провала
  названы прямо. Это **низовая** сторона реакции; верховая — детекция реального
  повтора, она живёт в `domain/personality/conversation.py` (`is_user_repeat`).
  Директива дописывается в промпт **только** когда повтор обнаружен, и складывается
  аддитивно с остальными голосовыми директивами.

**Детекция повтора собеседника.** `is_user_repeat(current, prior_user_texts)`
(`domain/personality/conversation.py`) — чистый предикат без LLM. Возвращает `True`,
только если `current` **дословно** повторяет один из недавних ходов **пользователя**
после нормализации (strip / casefold / схлопывание внутренних пробелов). Намеренно
**консервативен**: совпадение точное, не fuzzy, поэтому ложно не сработает; пустой/
пробельный ввод повтором не считается. Кандидаты `prior_user_texts` даёт
`_user_turns(history, _author_key(interlocutor))`: над общим тредом (BOB-058) они
фильтруются по `sender_id`, поэтому похожая реплика ДРУГОГО участника не считается
повтором текущего собеседника (устойчиво к омонимам/ренейму, не по имени-метке).

**Вшивка.** Директивы собираются на тёплую базовую персону в реактивном промпте
(`_SYSTEM_PROMPT`, `application/usecases/handle_message.py`): сперва `guppi_canon()`,
затем `anti_bait_directive()`. Канон GUPPI там же подпирает преамбулу
capability-манифеста (`_CAPABILITY_PREFACE` подаёт навыки как то, что GUPPI исполняет
для Боба, — раздел «Capability-шов»). Проактивная компоновка
(`_COMPOSE_SYSTEM`, `proactivity/usecases/engine.py`) тоже несёт
`anti_bait_directive()`: когда Боб пишет первым, его так же тянет «baitить» на
продолжение, и финал должен держаться сам.

## Выражение: план хода, реакции, протекающая внутренняя жизнь (BOB-018)

Живой человек не только *что* говорит, но и *как*: иногда отвечает развёрнуто, иногда
роняет короткую реплику, иногда — просто ставит реакцию, а порой к слову обронит то, о
чём думал, или вспомнит общий момент. Боб получает эту **спонтанную выразительность**
через единый **план выражения**, который считается перед составлением ответа. Всё —
**как характер, не как конфиг**: режим и форму решает состояние + seeded-RNG, флейвор
живёт в голосе/few-shot, а контент добавок берётся **только из реальной памяти и
рефлексий**. Ключевой принцип — **grounded**: нет настоящего материала → добавка не
срабатывает (no-op), Боб ничего не выдумывает. Второй принцип — **анти-тик**: добавки
редкие и по состоянию, не в каждом сообщении.

### План выражения (чистый домен)

`expression.py` (`domain/personality/`) — чистая, детерминированная функция
`decide_expression(mood, signals, *, rng, freqs) -> ExpressionPlan`. Как
`select_reply_tier`, это **не LLM** (дёшево, тестируемо): решение зависит только от
настроения, сигналов хода и инъецированного seeded-RNG, поэтому равные
`(mood, signals, seed, freqs)` всегда дают равный план.

- **`ExpressionPlan`** (frozen) несёт: `mode` (`ExpressionMode.REPLY` / `REACT_ONLY`),
  два редких флага-добавки `leak_inner_life` и `callback`, и мягкую подсказку формы
  `form_hint` (`FormHint.TERSE` / `NORMAL` / `EXPANSIVE`).
- **`ExpressionSignals`** (frozen) — минимальные чистые входы помимо настроения:
  `inbound_text` (его длина/форма — сигнал) и `idle_seconds` (тишина до сообщения).
  Набор расширяемый — поздние беды добавят сигналы, не меняя сигнатуру вызова.
- **`ExpressionFreqs`** (frozen) — малые настраиваемые частоты срабатывания редких
  флагов, каждая — вероятность в `[0, 1]` (`0` — жёсткий выключатель). Дефолты
  специально малы (`leak_inner_life=0.12`, `callback=0.1`), чтобы добавки читались как
  редкая спонтанность, а не тик. Конструктор валидирует диапазон.

**Как решается режим и форма.** Низкая энергия (низкий arousal) на коротком
малосигнальном входящем тянет к `TERSE` и поднимает шанс `REACT_ONLY`; светлое открытое
настроение на содержательном входящем допускает `EXPANSIVE`. **Содержательный** входящий
(достаточно длинный или с вопросом `?`) **никогда** не понижается до `REACT_ONLY` — на
реальный вопрос Боб отвечает. Порядок бросков RNG фиксирован (режим → leak → callback) и
бросок режима берётся всегда, даже если состояние не может дать `REACT_ONLY`, — так план
стабилен под фиксированным seed независимо от ветки.

### (1) Нативные реакции — `REACT_ONLY`

`reaction.py` (`domain/personality/`) — чистый, без I/O и RNG, picker
`reaction_emoji_for(mood) -> str`: маппит детерминированный тон-дескриптор настроения
(`Mood.tone()`) на эмодзи из **стандартного reaction-set Telegram**
(`STANDARD_REACTION_EMOJI`), неизвестный тон → нейтральный `👍`. Радостный Боб реагирует
тепло, угрюмый — плоско; то же настроение всегда даёт то же эмодзи (тестируемо без
модели). Кастом-эмодзи — premium, вне области; стандартный набор — то, что
`set_message_reaction` принимает без ошибки «reaction not allowed».

Порт **`MessageReactor`** (`domain/ports/personality.py`, `react(*, chat_id, message_id, emoji)`) —
шов реакции. Реализация в Telegram-гейтвее (`infrastructure/telegram/`):
`TelegramGateway.set_message_reaction` через aiogram, адаптер `_ReactorGateway`
(`multibot.py`) пинит реакцию к треду Боба. Реакция **best-effort**: адаптер деградирует
(краткий текстовый ack или no-op) на любой ошибке транспорта и **никогда не пробрасывает
исключение** в вызывающий код, так что сбой реакции не ломает ход.

### (2) Протекающая внутренняя жизнь — `leak_inner_life`

Порт **`ReflectionReader`** (`domain/ports/personality.py`, `latest_reflection_text() -> str | None`)
читает текст **последней реальной** рефлексии Боба. Реализация в
`proactivity/adapters/proactivity_sources.py`: берёт свежайшую строку
`episodic_log`, чей `event_type` ∈ {`reflection`, `inner_monologue`} (их grounded и
по-русски пишет BOB-012). При флаге `leak_inner_life` текст подаётся в compose-контекст
как «то, о чём ты ловил себя на мысли» (естественно, не дословно). **Нет рефлексии (или
ридер не подключён) → `None` → no-op**, никакой выдумки.

**Контейнмент мимикрии рефлексий (BOB-033 .3).** `leak_inner_life` — **осознанный**,
явный показ ОДНОЙ свежей рефлексии. Слепое же копирование текста рефлексий в ответы
закрыто на reply-recall: чистый домен `recalled_excluding_reflections`
(`conversation.py`) выбрасывает из пула образцов compose каждый эпизод, чей
`event_type` ∈ {`reflection`, `inner_monologue`} (единый источник «что есть рефлексия»),
а дистиллированные факты и обычные ходы остаются. `handle_message` применяет фильтр перед
компоновкой. Так внутренняя жизнь влияет на ответы **через настроение→манеру**, а не
дословной мимикрией; путь `leak_inner_life` остаётся нетронутым. Сочетается с BOB-032
(анти-повтор реплик) — закрывает оставшийся вектор копирования.

### (3) Колбэки — `callback`

При флаге `callback` приложение запрашивает гибридный **`MemoryRecall`** (BOB-011) по
текущей теме; если возвращается **реальный** прошлый момент, он кладётся в
compose-контекст как «можешь к месту вспомнить это (реальное)». Как и в BOB-012, **пустой
recall → ничего не добавляется** (анти-конфабуляция: Боб не выдумывает общий момент).
Изредка (малый seeded-посев `_draw_surface_old`, частота `memory.surface_old.freq`)
именно этот колбэк просит recall с опт-ином **`surface_old`** (BOB-021, мех. 1), чтобы
вместо свежайшего хита вернулся старый-но-релевантный глубокий момент («что-то
напомнило») — всё ещё grounded и no-op, когда старого-релевантного нет. Посев едет
**только** по колбэк-пути (см. «Консолидация памяти»).

### (4) Переменная форма — `form_hint`

`form_hint` из плана — **мягкий** per-turn ориентир длины по настроению. Своей
отдельной директивы компоновки у него больше нет: прежний `_FORM_HINT_DIRECTIVE`
**убран** в BOB-024 (он конкурировал бы с решённой `Verbosity` — два сигнала длины).
Теперь `form_hint` — это **вход** в `decide_verbosity`: `TERSE`-хинт при мягко-плохом
настроении добавляет наклон ответа к краткости (усиливает настроение, не задаёт длину в
одиночку). Финальную длину держит единственная директива `voice.brevity_directive` +
few-shot (см. «Краткость по запросу»). Голосовая `variable_form_directive()` (см. «Голос
персоны») и анти-bait продолжают работать как прежде.

### Врезка в `handle_message`

`HandleMessage` принимает опциональные seam'ы `rng`, `expression_freqs`, `reactor`,
`reflection` (все необязательны → обратная совместимость). На каждый ход:

1. **Perceive** обновляет настроение, затем `_plan_expression` считает `ExpressionPlan`
   (`decide_expression` по свежему настроению + `ExpressionSignals` + seeded-RNG).
2. Если `mode is REACT_ONLY` **и** реактор подключён → `_react_only`: ставит нативное
   mood-эмодзи на сообщение пользователя **вместо** генерации ответа (нет LLM-вызова, нет
   rich-финала, нет эпизода — текста ответа нет), отмечает owner-активность и выходит. Без
   подключённого реактора `REACT_ONLY` откатывается на полный ответ (путь остаётся живым).
3. Иначе собирается обычный compose-контекст, к нему `_with_grounded_addons`
   аддитивно добавляет leak-строку и/или callback-строку (за тем же grounding-швом, что
   BOB-012; пустой материал → строка не добавляется), а `_system_prompt_for` дописывает
   `form_hint`-директиву к промпту. Перед генерацией `is_user_repeat` сверяет текущий
   ввод с прошлыми ходами **пользователя** из истории (`_user_turns` достаёт их из
   `"<sender>: <text>\nbob: <reply>"`); при повторе в промпт добавляется
   `user_repeat_directive()` (BOB-022), чтобы Боб заметил повтор собеседника (см.
   «Голос персоны»).
4. Ответ генерируется как раньше (тиринг/voice/язык/Negotiation — без изменений).
5. **Анти-повтор-страж (BOB-022 → окно BOB-026 → recall-aware BOB-032 → фраза-тик
   BOB-036, защита в глубину).** Сразу после генерации `AntiRepeatGuard.guard`
   (`conversation/usecases/anti_repeat_guard.py`, коллаборатор `handle()`) сверяет свежий
   ответ с **объединением двух источников**: окном последних N ответов Боба из истории
   (`_recent_bob_replies` достаёт `bob:`-половины последних N эпизодов) **и репликами
   Боба, всплывшими в recalled-памяти** (`recalled_bob_replies` достаёт `bob:`-половину
   каждого вспомненного эпизода через тот же `_BOB_TURN_MARKER`). Чистый предикат
   `is_bob_repeat` (`domain/personality/conversation.py`, рядом с `is_user_repeat`)
   срабатывает на **verbatim** (после `strip`/`casefold`/схлопывания пробелов) **или
   near-verbatim** — `difflib.SequenceMatcher.ratio >=` порог. Окно вместо последнего
   ответа ловит повтор «через ход», а recalled-источник (BOB-032, R1) закрывает главную
   дыру: compose-контекст подаёт recalled-память **целыми ходами** `"<кто>: <текст>\nbob:
   <старый ответ>"`, так что модель видит свои прошлые ответы и копирует их (few-shot
   мимикрия) — повтор из семантической памяти прежде был стражу невидим (дальние повторы
   через сотни ходов).

   При срабатывании регенерация **ломает аттрактор** (BOB-032, R2): простой ре-ролл с тем
   же контекстом перекатывается в тот же аттрактор, поэтому из контекста ретрая убирается
   тот recalled-экземпляр(ы), который совпал с кандидатом
   (`recalled_without_copied_exemplars` — модель перестаёт «смотреть» на копируемый текст;
   фактическая память и несовпавшие эпизоды сохраняются, grounding фактов цел). Разрешено
   до `_MAX_REGENERATIONS=2` регенераций с пере-проверкой после каждой; если и после порога
   повтор, остаётся последний драфт (без бесконечного цикла). Это чисто структурно, без
   скриптовой директивы «не повторяйся». Окно `N` и порог сходства задаёт frozen
   `RepeatThresholds` (`repeat.window` дефолт `5`, `repeat.similarity_threshold` дефолт
   `0.9`; собирается в `app.py` через `_build_repeat_thresholds`). Это противоположная
   сторона детекции из шага 3: страж ловит повтор **Боба**, директива — повтор
   **пользователя**.

   **Фраза-тик-страж (BOB-036).** Полно-репличный бар выше сравнивает реплики целиком (высокий
   порог сходства), поэтому две **разные по сути** реплики, которые просто заканчиваются одной и
   той же подписной закрывашкой («Мне так спокойнее.»), сквозь него проходят. Этот хвост ловит
   чистый доменный предикат `is_phrase_tic` (`domain/personality/conversation.py`) на том же
   recall-aware объединении источников. «Заметная фраза» — предложение/клауза не короче
   `tic_min_words` слов (граница по `.`/`!`/`?`/переводу строки; финальная клауза включается,
   ведь тик обычно — закрывашка; см. `_notable_phrases`/`_add_phrase`). Кандидат считается тиком,
   когда одна из его заметных фраз встречается как заметная фраза минимум в `tic_min_occurrences`
   недавних реплик (каждая реплика засчитывается не более раза, повтор фразы внутри одной реплики
   не накручивает счётчик). Так фраза, рекуррентная **через окно**, — тик, а одноразовое
   переиспользование длинной фразы (совпадение с единственной прошлой репликой) или короткая
   закрывашка (ниже `tic_min_words`, «Работаем»/«Ок») — нет. Провязка в
   `AntiRepeatGuard.guard`: на каждой итерации цикла кандидат проверяется по
   `is_bob_repeat` (полный повтор) **ИЛИ** `is_phrase_tic`; срабатывание любого запускает **тот
   же** recall-aware attractor-break (общий бюджет `_MAX_REGENERATIONS=2`). Это структурный
   детектор, **не** скриптовая директива «не говори X». Пороги — те же frozen `RepeatThresholds`:
   `repeat.tic_min_words` (дефолт `3` — чтобы короткие закрывашки никогда не срабатывали) и
   `repeat.tic_min_occurrences` (дефолт `2`); дефолты консервативны против ложных регенераций,
   собираются в `app.py` через `_build_repeat_thresholds`.

   **Кросс-сессионный анти-тик (BOB-061).** Фраза-тик-страж сравнивает только реплики
   **текущего** окна (история ~6 + recall ~5), поэтому подписной тик, который повторяется
   **раз в сессию через дни**, в узком окне мелькает 0–1 раз — ниже `tic_min_occurrences` — и
   проходит. BOB-061 закрывает дыру двумя доработками. **(1) Персист.** Порт `CloserLog`
   (`domain/ports/conversation.py`) — крошечное **приватное локальное** кольцо closer-ов Боба: адаптер
   `SqliteCloserLog` (`infrastructure/persistence/closer_log_store.py`) хранит только
   **нормализованные закрывашки** (не полные реплики) в таблице `closer_log`, кэп `30` (старые
   сходят с кольца на `append`; та же SQLite-база памяти, таблица заводится идемпотентно
   `schema.sql`). Так рассеянный по сессиям мотив накапливается, переживая рестарты. **(2)
   Near-verbatim мотив.** Точное совпадение после `_normalise` недосчитывает мотив,
   рекуррентный **лексическими вариантами** («пусть остаётся/останется как есть», «мне/ему
   так спокойнее»). `is_same_closer_motif` кластеризует два closer-а как один мотив по тому же
   `SequenceMatcher.ratio`, но калиброванному под **короткие** фразы порогу
   `motif_similarity_threshold` (дефолт `0.82`: настоящие варианты сидят ~0.88–0.94, а разные
   по сути концовки ~0.2–0.25, поэтому просто другой финал не кластеризуется — US-4).
   `is_recurring_closer_tic` считает, сколько closer-ов кластеризуются с текущим, и срабатывает
   при `tic_min_occurrences`.

   **Провязка (`handle_message.py`).** После каждой реплики `_log_closer` дописывает её
   закрывашку (`closer_text`) в кольцо. Перед генерацией `_closer_anti_tic` считает мотив
   **один раз за ход** (`AntiRepeatGuard.closer_anti_tic`): собирает closer-ы персиста
   (`recent(tic_lookback)`) **∪** окна и прогоняет свежайший через `is_recurring_closer_tic`.
   При срабатывании — (а) мотив **стрипается** с recalled-эталонов Боба (тик не подаётся
   обратно как few-shot) и (б) возвращается мягкий нудж `_CLOSER_TIC_NUDGE` («заверши
   по-другому, своими словами, не меняя смысла») как per-turn `closer_nudge`, прокинутый
   аргументом в `VoiceComposer.compose` в контекст генерации и переживающий регенерацию. 🔴 **Всё декоративно и консервативно:** непровязанный
   лог, сбой чтения или **отсутствие тика** возвращают контекст **байт-в-байт** без изменений —
   нудж толкает к разнообразию, не запрещает; сбой персиста глотается и **не роняет** уже
   готовый ход. Пороги — те же `RepeatThresholds` (`repeat.tic_lookback`,
   `repeat.motif_similarity_threshold`).

   **🎯 Корень тика (BOB-061 .7).** Реактивный страж лечил симптом, но семя тика подсеивалось
   каждый ход из голоса: всегда-вкладываемые эталоны `voice.py` несли статичную закрывашку
   «пусть остаётся как есть. Мне так спокойнее», и модель её перенимала. Мотив-семя убран из
   `_ANTI_BAIT` / `_VARIABLE_FORM` / `_GUPPI_CANON` — педагогика (anti-bait, variable-form)
   сохранена, а конкретная фраза больше не сеет тик (см. «Голос персоны»). **Диспозиция
   (BOB-033) — не драйвер:** эмпирически подтверждено, что она в reply-промпт не входит, так
   что тику её valence-lean не питает; правок в BOB-033 не потребовалось. Это тот же принцип
   «recall poisoning» и «никогда не программно», что BOB-032/033: тик лечится структурой и
   удалением семени, а не запретным списком фраз.

   Чистые помощники извлечения `bob:`-реплики и attractor-breaking (`recalled_bob_reply`,
   `recalled_bob_replies`, `recalled_without_copied_exemplars`) вынесены в домен
   `conversation.py`, чтобы реактивный ход и проактивный движок делили **одну** реализацию
   (см. «Проактивность»).

Seed выражения переиспользует seed проактивности (`runtime.proactivity_seed`), так что
один параметр делает **всё** стохастическое поведение Боба воспроизводимым в тестах.

### Конфигурация

Частоты редких добавок — в блоке `expression.freqs.*` (`infrastructure/config/loader.py`):
`expression.freqs.leak_inner_life` (дефолт `0.12`) и `expression.freqs.callback` (дефолт
`0.1`). Сборка читает их в `app.py` (`_build_expression_freqs`) в `ExpressionFreqs`,
дефолты малы (анти-тик), тюнятся per-persona.

## Эмоциональная глубина (BOB-020)

Боб выразителен (BOB-018) и имеет растущее мнение (BOB-013), но прежде был
эмоционально ровным и однобоко-позитивным. Эмоциональная глубина даёт четыре
элемента поверх готового аффекта (`Mood`) и само-эволюции (BOB-013): тон зависит от
настроения, настроение временно окрашивает вкусовой вердикт, у Боба есть текущее
увлечение, которое медленно эволюционирует, а его фантомные предпочтения тоже
оживают и дрейфуют. Всё пишется **как характер, не как конфиг** и под теми же
guardrails, что BOB-013: границы, плавность, идемпотентность, seeded-RNG, никакой
runaway-эволюции. Ничего не выдумывается — off-day и модуляция выводятся из
настроения, увлечение и фантомы grounded в реальной внутренней жизни (рефлексии и
сильные вкусы).

### (1) Off-day: тон зависит от настроения

`voice.tone_directive(mood, *, thresholds)` (`domain/personality/voice.py`) —
чистая, детерминированная функция, заменившая прежнюю безусловную строку «отвечай
тепло и кратко». Теперь тон зависит от настроения: когда **И** `valence`, **И**
`arousal` опускаются на-или-ниже порога `OffDayThresholds`, Боб читается как «не в
ресурсе» — тон становится тише, сдержаннее, уязвимее, а честное «не знаю» лучше
выдуманного тепла. В норме или при хорошем настроении возвращается прежний тёплый,
краткий базовый тон.

- **Off-day = производное от настроения**, без нового персист-состояния: бэнд
  выводится прямо из `Mood`. Это **не грубость** — тише и честнее, а не реляционная
  обида (та живёт в BOB-014).
- `OffDayThresholds(valence, arousal)` — frozen-дефолты в низком/отрицательном
  бэнде (`valence = -0.4`, `arousal = -0.3`), поэтому нормальное или хорошее
  настроение всегда остаётся на тёплом тоне. Пороги тюнятся через
  `emotion.offday.{valence,arousal}`.
- Равные `(mood, thresholds)` всегда дают одну директиву (тестируемо без модели).
  `handle_message` собирает её в системный промпт через инъецированный
  `offday_thresholds`.

### (2) Mood→Taste модуляция

`mood_taste.py` (`domain/personality/`) — чистый, без I/O и LLM модулятор: текущее
настроение **временно** окрашивает вкусовой вердикт, **не мутируя сами оси** (это не
само-эволюция BOB-013, а лишь настроение, читающее уже сложившееся мнение).

- **`modulate(verdict, value, mood) -> Verdict`** сдвигает вердикт по шкале
  love → like → neutral → dislike → hate **не больше чем на один шаг**. Плоское,
  низкое настроение читается строже/консервативнее (симпатия гасится, антипатия
  твердеет), светлое и открытое — мягче/любопытнее (антипатия смягчается, симпатия
  теплеет). На `NEUTRAL` знак `value` решает, в какую сторону клонит скос; при
  подлинном безразличии (`value ≈ 0`) тема остаётся `NEUTRAL` — плоский день не
  выдумывает антипатию из равнодушия. Концы шкалы насыщаются, результат всегда —
  валидный `Verdict`.
- **`experiment_bias(mood) -> float`** выводит из настроения готовность Боба
  попробовать новое, в границах `[0, 1]`: низкая при плоском настроении, выше при
  светлом и открытом. И сдвиг, и bias считаются от одной диспозиции — среднего
  `valence` и `openness`, — с небольшой мёртвой зоной, чтобы обычное настроение
  было чистой тождественностью без дрожания.
- Обе функции детерминированы. Вызывающий код кладёт в промпт **эффективный**
  (модулированный) вердикт и хинт готовности, а персистентные оси остаются
  нетронутыми.

### (3) Увлечение (fascination)

У Боба есть **текущее увлечение** — тема, которой он сейчас захвачен. Это
персистентное внутреннее состояние, которое медленно эволюционирует и редко, к
месту, проявляется в речи.

- **`Fascination`** (`domain/personality/fascination.py`) — чистый, иммутабельный
  value-объект: `topic` (grounded в реальной внутренней жизни, не рандом),
  `intensity` в `[0, 1]` и момент `created_at`. `aged(now)` экспоненциально гасит
  интенсивность с возрастом (полураспад 72 ч — медленно, чтобы увлечение читалось
  настоящим, а не вспышкой), клампя в границы; `has_faded()` истинно, когда
  интенсивность опустилась на-или-ниже `DECAY_FLOOR` (0.15) — сигнал заменить
  выгоревшее увлечение свежим. Без I/O и собственных часов (`now` инъецируется).
- **`SqliteFascinationStore`** (`infrastructure/persistence/fascination_store.py`)
  реализует порт `FascinationStore` над таблицей `fascination_state` — одна строка
  на `persona_id`, поэтому реплики Bobiverse держат своё увлечение. Домен мапится в
  строку и обратно (intensity как REAL, `created_at` как ISO-8601); неувиденная или
  ещё не заменённая после выгорания персона строки не имеет (`load` → `None`). Весь
  SQL параметризован (`?`).
- **`EvolveFascination`** (`application/usecases/evolve_fascination.py`) — редкий
  grounded-шаг на reflect-тике. Каждый прогон: загружает и старит текущее увлечение,
  решает сдвиг (только когда увлечения нет или оно выгорело по `has_faded`),
  grounds выбор в **реальной** внутренней жизни Боба (дешёвый Tier-0-вызов выбирает
  тему из последней рефлексии и сильнейших вкусов; детерминированный эвристик-
  фоллбэк, если Tier 0 не дал годного; **чистый no-op без материала**) и
  персистит свежее увлечение. Шаг **идемпотентен**: свеже выбранное увлечение имеет
  возраст ≈ 0, поэтому второй тик в том же периоде не сдвигает повторно. Стартовая
  интенсивность тюнится через `emotion.fascination.initial_intensity`.
- **Проявление** — редкий флаг `mention_fascination` в `ExpressionPlan`/
  `ExpressionFreqs` (BOB-018). При нём текущее **не выгоревшее** увлечение (загружено
  и состарено через `StoreFascinationReader`) подаётся в compose-контекст ответа
  (`handle_message`) и проактива (engine) как «можешь к месту упомянуть, чем сейчас
  увлечён (реальное)». Нет увлечения → no-op. Частота настраивается под одним
  ключом `emotion.fascination.mention_freq` (зеркалится
  `expression.freqs.mention_fascination`).

### (4) Эволюция фантомных предпочтений

Фантомные предпочтения Боба (`SOUL.phantom_prefs` — кофе, дождь, книги…) — не
застывший кортеж: они оживают и медленно дрейфуют. Новая симпатия проступает из
сильного свежего вкуса или рефлексии, старая затухает.

- **`SOUL.with_phantoms(phantoms)`** (`domain/personality/soul.py`) — иммутабельный
  аналог `with_taste`: свопает эволюционировавший набор фантомов и инкрементирует
  `experience_count` (сдвиг фантома — тоже шаг само-эволюции). Оригинал нетронут.
- **`evolve_phantoms(phantoms, signals, *, rng) -> tuple[str, ...]`**
  (`domain/personality/phantom_evolution.py`) — чистое мембершип-ядро в дисциплине
  `taste_evolution` (BOB-013): **grounded** (проступает только `candidate`, который
  приложение вывело из реальной внутренней жизни; нет кандидата — нет изменения,
  Боб не выдумывает предпочтение), **медленно** (изменение за швом малой
  per-step-вероятности на seeded-RNG, большинство шагов — no-op), **ограниченно**
  (набор не растёт выше `max_count`; при переполнении затухает самый старый — один
  вход, один выход), **идемпотентно** (уже присутствующий кандидат → no-op). Чисто и
  детерминированно: без I/O, LLM и часов. `PhantomSignals(candidate, max_count,
  change_rate)` несёт grounded-кандидат и настройки. Дефолты — `MAX_PHANTOMS = 5`,
  `CHANGE_RATE = 0.2`.
- **`EvolvePhantoms`** (`application/usecases/evolve_phantoms.py`) — редкий
  grounded-шаг на том же reflect-тике, рядом с `ApplyReflection` и
  `EvolveFascination`. Grounds кандидата через тот же шов `FascinationGrounding`
  (сильнейший вкус, иначе последняя рефлексия), прогоняет чистое ядро
  `evolve_phantoms`, а **на реальном изменении** свопает живой `SOUL` через
  `with_phantoms` и
  персистит набор через узкий шов `PhantomProfileWriter` (`write_json`,
  interface-segregation над `SoulStore`) в форме `{"preferences": [...]}` — той же,
  что пишет Genesis и читает `_load_soul`, поэтому эволюционировавший набор переживает
  рестарт. Бесполезный шаг (нет изменения членства) — строгий no-op. Бэнд и каденс
  тюнятся через `emotion.phantom.{max_count,change_rate}`.

### Шаги эволюции на reflect-тике

`ReflectTick` (`application/usecases/heartbeat.py`) после сохранения рефлексии
эпизодом запускает **пять** опциональных шагов по порядку:

1. **`ApplyReflection`** (BOB-013, Ф2) — рефлексия переписывает вкус (см.
   «Само-эволюция»). Идемпотентен через маркер `last_evolved`.
2. **`EvolveFascination`** (BOB-020) — редкий grounded-сдвиг текущего увлечения.
3. **`EvolvePhantoms`** (BOB-020) — редкий grounded-сдвиг фантомных предпочтений.
4. **`ConsolidateMemory`** (BOB-021, шов `MemoryConsolidator`) — редко сворачивает
   старые эпизоды в дайджест (не деструктивно, идемпотентно; см. «Консолидация памяти»).
5. **`DedupFacts`** (BOB-021, шов `FactDeduper`) — редко сливает почти-дубликаты
   фактов по косинусу (консервативно, не деструктивно, идемпотентно).

Все пять инъецируются опционально (`None` → тик ведёт себя как прежде, только лог
эпизода), grounded в реальной внутренней жизни/памяти Боба, идемпотентны в пределах
периода и под guardrails. Так фоновая внутренняя жизнь Боба — настроение, вкус,
увлечение, фантомы — и его память эволюционируют медленно и связно, не убегая вразнос.

### Конфигурация

Блок `emotion.*` (`infrastructure/config/loader.py`, читается в `app.py`):

- `emotion.offday.{valence,arousal}` — порог off-day-тона; дефолты в
  низком/отрицательном бэнде (`-0.4`/`-0.3`), поэтому нормальное настроение остаётся
  тёплым (`_build_offday_thresholds`).
- `emotion.fascination.initial_intensity` (дефолт `0.85`) — стартовая интенсивность
  свежего увлечения; out-of-range клампится в `[0, 1]`.
- `emotion.fascination.mention_freq` (дефолт `0.1`) — частота проявления увлечения;
  зеркалится `expression.freqs.mention_fascination` (emotion-ключ выигрывает, чтобы
  весь тюнинг увлечения жил в одном месте).
- `emotion.phantom.max_count` (дефолт `5`) и `emotion.phantom.change_rate` (дефолт
  `0.2`) — бэнд и каденс эволюции фантомов; `max_count` клампится минимум к 1, а
  `change_rate` — в `[0, 1]`, поэтому misconfiguration не ломает границы
  (`_phantom_evolution_params`).

## Отношения и обида (BOB-014)

Финал Тира 1. Поверх готового аффекта (`Mood`), мнения (BOB-013) и распознавания
собеседника (BOB-019) добавляются два слоя: **качество отношений** с каждым
человеком (влияет на тон и уступчивость), **аппетит к разговору** (Боб не всегда
одинаково охотно болтает) и **обида/охлаждение** (Sulk) — книжный Exodus с
hard-reset отвергнут, Боб **«отходит», а не «уходит»**: память и душа неизменны
(anti-Exodus). Всё пишется **как характер, не как конфиг**, под теми же
guardrails, что BOB-013/020 — границы, плавный дрейф, идемпотентность и
**гарантированное** восстановление.

### (1) RelationshipTracker — качество отношений (per-person)

Чистый домен `social/relationship.py`. `Relationship(sender_id, trust,
respect, warmth, compatibility)` — четыре оси, каждая в `[-1, 1]`, старт `0`
(нейтрально, человек, на которого Боб ещё не составил мнение):

- **trust** — насколько Боб полагается на слово и намерения человека;
- **respect** — насколько ценит его суждение;
- **warmth** — насколько тепло относится (ось, сильнее всего красящая тон);
- **compatibility** — насколько они ладят (ведёт готовность к компромиссу).

`apply_interaction(rel, *, stance, mood, sentiment, deltas=None)` — единственный
детерминированный шаг, обновляющий отношение из сигналов **одного хода**: стойки
Negotiation (`Stance`), `Mood` и скаляра `sentiment`. Дельты малые и ограниченные
(≈0.05): уступка (`CONCEDE`/`AGREE`) греет иначе, чем удержание своей позиции
(`PROPOSE_ALTERNATIVE` греет слабее, зато растит respect — Боб ценит человека, с
которым есть о чём поспорить). Сначала применяется лёгкий **дрейф к нейтрали** (как
`Mood.drift_toward`), поэтому отношение без подпитки расслабляется к 0 и не залипает
на экстремуме; каждая ось клампится в `[-1, 1]` на каждом шаге.

`compromise_bias(rel)` → `0..0.2` — насколько близость (warmth + compatibility)
снижает эффективную убеждённость Боба перед Negotiation: с близким человеком Боб
охотнее идёт навстречу, пограничная стойка склоняется от удержания к согласию.
Малый и ограниченный (нюджит, не перебивает сильную убеждённость), ноль для
нейтрального/отрицательного отношения (холод не делает Боба упрямее — сдержанность
несёт **тон**, а реляционная враждебность — это обида).

**Влияние на тон:** `voice.relationship_tone_directive(warmth)` поверх
mood-тона — выше тёплого бэнда голос теплее и ближе, ниже прохладного — суше и
сдержаннее (но **не грубо**: грубость — это Sulk). Нейтральная середина не
добавляет строки, поэтому базовый путь не меняется.

**Application-шов:** `usecases/relationship_sources.py::RelationshipTracker` —
`current(sender_id)` загружает отношение (или `None` для незнакомца),
`record_interaction(...)` **после хода** прогоняет `apply_interaction` и UPSERT-ит
результат, так отношение накапливается за много ходов. Персист —
`social/adapters/relationship_store.py::SqliteRelationshipStore`,
таблица `person_relationship`, per-sender (по образцу `first_impression`).

### (2) Аппетит к разговору (.2a)

Чистый домен `domain/personality/engagement.py`. Аппетит — не выключатель, а
**уровень**, выводимый каждый ход из четырёх сигналов: `mood × topic_interest ×
fatigue × relationship`. `decide_engagement(...)` → `EngagementLevel`
(детерминирован по seed, один RNG-розыгрыш на границе FULL/PLAYFUL берётся
**всегда**, чтобы позиция в потоке RNG не плыла):

- **FULL** — полное, содержательное вовлечение (тон по умолчанию, директивы нет);
- **PLAYFUL** — вовлечён и в настроении подурачиться / поболтать «ни о чём»;
- **TERSE** — отвечает минимально, интерес тает;
- **DECLINE** — мягко сворачивает трёп («что-то заболтались») — это **не отказ
  человеку**, а отсутствие аппетита к этой бесцельной ветке сейчас.

Четыре сценария: (1) хорошее настроение → может подыграть (bright mood +
интересная тема → FULL, seeded-розыгрыш тип может склонить в PLAYFUL); (2)
бесцельный трёп приедается (высокая `fatigue` → TERSE, а на неинтересной теме →
DECLINE); (3) плохое настроение → высокий порог («какие-попало» темы сразу
TERSE/DECLINE); (4) интересная тема перебивает плохое настроение (интерес выше
порога → FULL даже в низком mood — и хороший обмен поднимает настроение).

`topic_interest(verdict, conviction, *, fascination_match)` → `[0, 1]` выводит
интерес из вкусового вердикта (любовь/ненависть интереснее лёгких like/dislike,
нейтральное «какие-попало» — низко), убеждённости и совпадения с текущим
увлечением (fascination — сильнейший сигнал, перебивает даже слабый вердикт).
`ConversationalFatigue` — ограниченный `[0, 1]` резервуар «наскучило»: растёт на
бесцельных низкоинтересных ходах (`after_turn`), спадает со временем (`decayed`)
и на интересном ходе. Decay по времени **гарантирует восстановление** — владелец
никогда не блокируется навсегда. `engagement_mood_lift(...)` — петля сценария 4:
вовлечённый интересный обмен (FULL/PLAYFUL) даёт малый bump valence; terse/declined
или неинтересный ход — ноль.

Близость сдвигает порог интереса: близкий человек **понижает** бар (Боб охотнее
подыгрывает), а **обвалившееся** (враждебное) отношение **повышает** бар
(`_relationship_bar_shift` — это и есть **guest-disengage** .2b: Боб сворачивается
с тем, на кого охладел, через DECLINE, восстанавливаясь вместе с отношением — без
вечного блока). Голос: `voice.engagement_directive(level)`.

Конфигурация `engagement.*` (`infrastructure/config/loader.py`, читается в `app.py`
через `_build_engagement_thresholds` / `_build_fatigue_rates`):
`engagement.thresholds.{interesting,high_fatigue,low_mood,bright_mood,playful_chance}`,
`engagement.fatigue.{decay_per_second,aimless_rise,interest_ease}`,
`engagement.mood_lift`. Дефолты держат нормальное настроение полностью вовлечённым
на любой нетривиальной теме и гарантируют восстановление fatigue.

### (3) Обида / охлаждение (Sulk, .2b)

Чистый домен `social/sulk.py` — дно оси вовлечённости, «аффект со
ставками». `SulkState(active, intensity, low_streak, since, announced)` несёт
**никакой памяти и никакой души** (anti-Exodus). Две чистые функции:

- **Вход** — `observe_relationship(state, *, owner_warmth, hostile, now, config)`.
  Ход считается «низким», когда **owner-warmth** на/ниже `critical_warmth`
  (дефолт `-0.4`, отрицательно — нейтральное отношение не строит обиду) **или** ход
  нёс **направленную** враждебность. «Низкие» ходы копят `low_streak`; здоровый ход
  его **сбрасывает** (перемежающиеся дипы не накапливаются в обиду). По достижении
  `sustain_count` (дефолт `3`) Боб **входит** в обиду на `enter_intensity` и
  ставит `since`. Не по мелочи: одно плохое сообщение или casual-мат обиду не
  запускает. Идемпотентно во время обиды: повторный «низкий» ход не пере-штампует
  вход и не раздувает intensity сверх потолка (intensity снижает только
  восстановление).
- **Выход** — `recover(state, *, elapsed_seconds, warmth_delta, config)`.
  Intensity падает на `decay_per_second × elapsed_seconds` — **гарантия выхода**:
  время само (при нулевом тепле) всегда выводит из обиды, никакого вечного блока.
  Тёплые сообщения owner (`warmth_delta > 0`) **ускоряют** отход
  (`warmth_decay_bonus`); отрицательное тепло обиду здесь не углубляет (это дело
  входа). Ниже `exit_intensity` обида заканчивается: `active` снимается, intensity
  обнуляется, `since` сбрасывается, а one-shot-флаг `announced` чистится, чтобы
  следующий вход анонсировался заново.

Эффекты:
- **Реактив холодный:** `voice.sulk_directive(intensity)` — тише, суше, минимально,
  но **не сброс и не другой человек** (cold-but-still-Bob) и **не грубо**.
  Прикладывается поверх mood/relationship-тона, пока обида активна.
- **Проактив подавлен (sulk-veto):** `proactivity/usecases/engine.py` читает шов
  `SulkSource.current_active()`; пока Боб обижен, он **не пишет первым**
  (`ProactiveHistory.sulk_active`, дефолт `False` для непровязанного Боба — поведение
  без обиды как раньше).
- **GUPPI announce (one-shot при входе):** `infrastructure/telegram/guppi.py::
  announce_sulk` — внеличностный системный голос GUPPI один раз постит в General,
  что Боб обижен и сейчас не хочет разговаривать. Гарантия «один раз на вход» — флаг
  `announced` в `SulkState`, поэтому application зовёт это только на переходе входа.
- **Восстановление на reflect-тике:** `usecases/sulk_sources.py::SulkRecoveryStep`
  (на той же медленной каденции, что эволюции BOB-020) затухает обиду по **реальному**
  прошедшему времени с прошлого тика; no-op, когда Боб не обижен.

Восприятие мата — `domain/personality/profanity.py::is_directed_hostility(text)`:
Боб спокоен к casual/эмфатическому мату «с ним» («блин, охренеть как круто») — это
**никогда** не обваливает отношение и не запускает обиду; регистрируется только
враждебность, **направленная** на него (слово-оскорбление само по себе, либо мат
вместе с обращением на «ты»/«иди …»/«заткнись»). Голос:
`voice.profanity_stance()` — спокоен к мату, реагирует на направленный наезд; дело
не в словах, а в том, на него они или нет.

**Application-шов и персист:** `usecases/sulk_sources.py` — `SulkTracker` (грузит/
обновляет `SulkState`, на входе зовёт `SulkAnnouncer`), `SulkRecoveryStep`
(reflect-тик), `SulkAnnouncer` (GUPPI). Персист —
`social/adapters/sulk_store.py::SqliteSulkStore`, таблица `sulk_state`
(per-persona, как proactivity-состояние).

### Где это в потоке хода и тика

- **`handle_message`** (на ход): загрузить отношение отправителя → `compromise_bias`
  сдвигает порог Negotiation (уступчивость) + `relationship_tone_directive` красит
  тон; `decide_engagement` → `engagement_directive`; при `sulk.active` —
  `sulk_directive` (холодный тон); `is_directed_hostility` + owner-warmth кормят
  `SulkTracker` (вход в обиду); после хода — `record_interaction` (апдейт + персист
  отношения) и mood-lift от хорошего обмена.
- **`governance` / `ProactivityEngine`** — sulk-veto на проактив.
- **reflect-тик** — `SulkRecoveryStep` затухает обиду (гарантированный выход).
- **GUPPI** — `announce_sulk` на входе в обиду.

**Guardrails (под тестами):** отношения в `[-1, 1]` + дрейф к нейтрали, малые
дельты, round-trip персиста; обида **по порогу + устойчивости** (не по мелочи),
**гарантированный выход** (intensity → 0 по времени даже без тепла),
идемпотентность тика, GUPPI-announce **ровно один раз** на вход; память и душа
целы — **anti-Exodus, без reset**.

## Genesis и bob-soul

При первом запуске (нет `data/soul/SOUL.md`) `RunGenesis` «пробуждает» уникального
Боба:

1. **Загружает** шаблоны из каталога `bob-soul/` — «геном» личности (архетип, пул
   черт, оси вкусов, mood-baselines, фантомные предпочтения, стили общения) как
   данные через `yaml.safe_load`.
2. **Генерирует** конкретную личность через `LLMRouter` на задаче `GENESIS`
   (**Tier 1**, Qwen): выбранные черты, значения и conviction осей вкусов,
   mood-baseline, фантомные предпочтения и самосознательное «пробуждение» с
   отсылкой к книге. Невалидный или неполный JSON отвергается громко
   (`GenesisError`).
3. **Записывает** результат через порт `SoulStore`: `SOUL.md` плюс JSON-профили
   (`taste_profile`, `mood`, `phantom_prefs`) и append-only `genesis_log.md`.

Genesis идемпотентен: как только `SOUL.md` существует, повторный запуск —
no-op (без обращения к LLM и без записи файлов). Идентичность рождается один раз и
переживает каждый рестарт.

## Heartbeat (фоновые тики)

Между сообщениями Боб живёт автономной внутренней жизнью — три тика, которые
рантайм планирует фоновыми задачами. Каждый тик — тонкий оркестратор над чистым
доменом и **локальным Tier 0** (внутренняя жизнь не эскалирует на удалённый API):

- **InnerMonologueTick** — Боб приватно «думает» на Tier 0; сентимент мысли
  нудит настроение, так внутренний монолог питает Mood.
- **MoodDriftTick** — эмоциональный гомеостаз: настроение шагом дрейфует к
  baseline (`Mood.drift_toward`), и всплески затухают.
- **ReflectTick** — периодическая рефлексия на Tier 0, сохраняемая как эпизод, а
  затем **применяемая к душе и памяти** пятью опциональными шагами по порядку.
  Рефлексия теперь **грундится свежим контекстом и дедуплицируется** (BOB-026 .2),
  **живее** благодаря few-shot и valence-lean из диспозиции (BOB-033 .2), а её **угол
  ротируется** по seeded-RNG с заземлением грундинга на не-рефлексии (BOB-047 .1),
  поэтому внутренний монолог перестаёт быть «заезженной пластинкой» и не залипает в один
  регистр — детали ниже, в разделе «Грундинг, живость, разнообразие угла и реаппрайзал
  рефлексии». До логирования
  мысль проходит опциональный шов **реаппрайзала** (`reappraise`): негативную мысль
  Боб вероятностно переоценивает (там же).
  Сначала (BOB-013, Ф2) `_evolve` зовёт `ApplyReflection.run(reflection, soul)`: на
  реальном изменении (`changed=True`) живой `SOUL` обновляется и эволюционировавший
  `taste_profile` персистится через `SoulStore.write_json`. Затем (BOB-020) тик
  прогоняет `EvolveFascination` (редкий grounded-сдвиг текущего увлечения) и
  `EvolvePhantoms` (редкий grounded-сдвиг фантомных предпочтений) — см.
  «Эмоциональная глубина». Наконец (BOB-021) тик прогоняет `ConsolidateMemory`
  (свернуть старые эпизоды в дайджест) и `DedupFacts` (слить почти-дубликаты фактов) —
  см. «Консолидация памяти». Все шаги **идемпотентны**: маркер `last_evolved` хранит
  последний применённый текст рефлексии, увлечение сдвигается только когда выгорело,
  уже присутствующий фантом-кандидат — no-op, а консолидация/дедуп берут только
  не-`consolidated` эпизоды и активные факты, поэтому повторный прогон того же тика не
  плодит изменений. Каждый шаг опционален: без
  `apply_reflection`/`soul_store`/`evolve_fascination`/`evolve_phantoms`/`consolidate_memory`/`dedup_facts`
  тик ведёт себя как прежде (только лог эпизода). Зависимость на персист вкуса сужена
  до порта `TasteProfileWriter`
  (только `write_json` — interface segregation), а не на весь `SoulStore`.

`InnerMonologueTick` и `ReflectTick` принимают параметр `language` (по умолчанию
`DEFAULT_LANGUAGE`, из `runtime.language`) и **дописывают директиву языка персоны**
в начало своих промптов (BOB-012): этим само-генерируемым тикам нечего зеркалить,
поэтому без явного ограничения модель уходила бы в английский (см. «Язык
персоны»).

### Грундинг, живость, разнообразие угла и реаппрайзал рефлексии (BOB-026 .2, BOB-033 .2, BOB-047 .1)

Раньше `ReflectTick` всегда брал один статический промпт и низкую температуру Tier 0,
поэтому возвращал почти одну и ту же мысль каждые ~5 минут (740 рефлексий, лишь 565
уникальных, плюс массовые near-дубли), и prior Qwen дефолтил мысль в меланхолию.
BOB-026 .2 грундит рефлексию и подавляет near-дубли перед сохранением; BOB-033 .2
делает рефлексии живыми и добавляет вероятностный реаппрайзал; BOB-047 .1 не даёт
рефлексиям залипать в один регистр — заземляет грундинг на не-рефлексии и ротирует
угол внутренней мысли. Всё на **Tier 0**, кроме самого реаппрайзал-такта.

**Диапазон внутренней жизни (BOB-047 .1).** У монотонности внутреннего монолога тот
же корень, что у застойной грусти из BOB-033: низкотемпературная Tier-0-модель
схлопывает распределение в один регистр. Раньше это была меланхолия; после BOB-033 —
наоборот, единственная нота предвкушения («сердце колотится»). BOB-047 расширяет
диапазон сразу с двух сторон: убирает контур само-подкормки регистра в грундинге и
детерминированно ротирует **тип** мысли. Это продолжение линии BOB-029
(mood-conditioned монолог) и BOB-033 (диспозиция / реаппрайзал / контейнмент): угол
задаёт **вид** мысли, а не её валентность — mood-честность по-прежнему допускает
честный минор даже под «светлым» углом.

- **Грундинг свежим контекстом — заземление на не-рефлексии (BOB-047 .1).**
  `build_reflection_prompt` (`domain/personality/reflection.py`, чистая сборка без I/O)
  вплетает в промпт несколько последних эпизодов Боба и тон текущего настроения, поэтому
  рефлексия про «сейчас», а не шаблон. Свежие эпизоды приходят через опциональный read-шов
  `ReflectionContext` (`recent_episodes(k)`, реализуется структурно `SqliteMemoryRepo`).
  **Грундинг отбирает только не-рефлексии:** helper `_grounding_contents`
  (`application/usecases/heartbeat.py`) исключает эпизоды с `event_type == "reflection"`,
  оставляя реальные моменты — сообщения, события, действия. Скармливание прошлых рефлексий
  обратно как few-shot «недавних моментов» заставляло модель мимикрировать **собственный**
  регистр и запирало монолог в одной ноте (зеркало старой застойной грусти); исключение
  рефлексий рвёт этот контур само-подкормки. Окно дедупа (`_reflection_contents`, BOB-026)
  при этом **по-прежнему читает рефлексии**, поэтому подавление near-дублей не задето.
  Если шов не провязан — ни эпизодов, ни тона, — функция возвращает прежний генерик-промпт
  `GENERIC_REFLECT_PROMPT` дословно, и непровязанный тик ведёт себя ровно как раньше.
- **Дедуп перед сохранением.** В `ReflectTick.run` свежая мысль сверяется с последними
  K рефлексиями тем же предикатом `is_bob_repeat` (.1, по порогу
  `repeat.similarity_threshold`). Near-дубль → **одна** регенерация; если ретрай снова
  near-дубль — рефлексия **пропускается** (без сохранения и без downstream-шагов
  эволюции/консолидации). Так внутренний монолог перестаёт быть «заезженной пластинкой».
- **Over-fetch для устойчивости окна.** Окно дедупа считает **рефлексии**, но
  `episodic_log` перемешан с ходами сообщений, поэтому `ReflectTick` over-fetch'ит
  эпизоды (`_DEDUP_FETCH_FACTOR` × `dedup_window`) — всплеск сообщений не сужает
  эффективное окно рефлексий ниже `dedup_window`. Грундинг при этом берёт только самый
  свежий хвост. Пороги — тот же `RepeatThresholds`, провязанный в `app.py` рядом со
  стражем ответа.
- **Живые рефлексии (BOB-033 .2, расширены BOB-047 .1, Tier 0).** Когда в
  `build_reflection_prompt` провязана `disposition`, промпт дополнительно несёт few-shot
  **палитру** «живого Боба» `LIVING_REFLECTION_EXAMPLES` плюс valence-lean, выведенный из
  `disposition.optimism` (`_valence_lean_line`: сильнее наклон у явного оптимиста, мягче у
  приглушённого). BOB-047 .1 расширил палитру **с 3 до 5** примеров, разнесённых по
  регистрам: предвкушение, тихая удовлетворённость, покой в тишине, бытовая заметка и —
  честно — мягкий минор. Это **не** форс-позитив и **не** правило быть бодрым; смысл —
  расширить распределение, которое низкотемпературная Tier-0-модель схлопывает в одну
  ноту, обратно к канон-диапазону Боба, не запрещая честный минор. Диспозицию тик читает
  из `state.soul.disposition`; без провязанного контекста функция возвращает прежний
  генерик-промпт дословно (легаси-поведение цело).
- **Разнообразие угла мысли (BOB-047 .1, seeded-RNG).** Чистая функция
  `select_reflection_angle(rng)` (`domain/personality/reflection.py`) детерминированно
  выбирает один из ~8 углов `REFLECTION_ANGLES` — это **вид** внутренней мысли (память /
  ощущение / взгляд вперёд / бытовая заметка / благодарность / тихая удовлетворённость /
  лёгкая тревога / любопытство), а не готовая фраза. Угол ротируется от тика к тику, как
  реаппрайзал-гейт BOB-033, из того же **инъецированного seeded-RNG** (одинаковый сид →
  одинаковый угол, детерминированно в тестах). `ReflectTick` (`_reflect`) выбирает угол
  **только** когда провязаны и RNG, и контекстный шов, и передаёт его в
  `build_reflection_prompt(... angle=...)`; функция добавляет лёгкую директиву **типа**
  мысли поверх грундинга. Угол сдвигает только тип мысли — честный valence-lean
  по-прежнему допускает минор; без провязанного RNG/контекста поведение не меняется.
- **Реаппрайзал — «вытеснять плохое хорошим» (BOB-033 .2, вероятностно).** Перед
  логированием мысли `ReflectTick` прогоняет шов `reappraise`, реализованный
  use-case'ом `ReappraiseReflection` (`application/usecases/reappraise_reflection.py`).
  Шаги: (1) классификация сентимента мысли на **Tier 0** (приватность — тот же
  one-word-лейбл, что у mood-пути); (2) если мысль **негативна**, гейт берётся из
  **инъецированного seeded-RNG** против `Disposition.reappraisal_probability()` —
  сильный оптимист переоценивает охотнее, решение детерминировано в тестах; (3) на
  срабатывании — **второй такт на Tier 1** («найди в этой мысли конструктив честно, без
  фальшивого позитива»): переоценённая мысль заменяет исходную и даёт позитивный
  `valence_step` (`REAPPRAISAL_VALENCE_STEP = 0.1`), который `ReflectTick` применяет
  через гомеостатический бэнд BOB-030 (`_bounded_valence_delta`) — без runaway-позитива.
  На промахе мысль остаётся **честно грустной** (возвращается как есть, без шага и без
  Tier-1-вызова). Позитив/нейтрал не переоцениваются никогда. **Приватность:** Tier 1
  трогается **только** реаппрайзал-такт (единственная эскалация личностного потока в
  облако — задокументированный компромисс owner); RNG-сид общий с проактивом
  (`_resolve_seed`), так что стохастичная внутренняя жизнь Боба воспроизводима одним
  рычагом.

К ним добавляется пятый, проактивный тик (см. «Проактивность»), а при включённой
автономности — шестой, самонаправленный `PursueGoalsTick` (см. «Автономность»);
оба супервизятся тем же `periodic` + `RetryPolicy`.

Все три читают и пишут общий `PersonalityState`, поэтому тики и обработка
сообщений видят одно согласованное настроение. Цикл `periodic` ретраит
транзиентный сбой тика с backoff (`RetryPolicy`), изолирует то, что тик в итоге
бросил, и корректно завершается при остановке рантайма (см. «Резилентность
тиков»).

## Проактивность: drive-движок (BOB-010, Фаза 1)

Боб не только отвечает по вызову — иногда он пишет первым. Этот четвёртый
heartbeat-тик отличается от трёх предыдущих принципиально: его поведение
**рождается из внутреннего состояния** (настроение Higher Mind, тоска по тишине,
салиентность свежей рефлексии, циркадный ритм), а **не из cron или расписания**.
Проактив — это выражение уже построенного субстрата (mood/память/heartbeat), а не
таймер, который раз в N минут «решает поболтать». Момент стохастичен: всплески и
паузы возникают сами, фиксированного ритма нет.

Движок устроен дёшево по построению: «порыв заговорить» — это чистая формула без
LLM, поэтому подавляющее большинство тиков завершается мгновенно и не делает
**ни одного** обращения к модели. LLM включается только на редком тике, когда Боб
действительно решил заговорить: сначала дешёвый Tier-0-гейт, затем компоновка
реплики. Всё состояние — **per-persona** (реплики Bobiverse наследуют тот же код,
но держат своё), а время и стохастика инъецируются (`Clock` + seeded RNG), поэтому
решение детерминировано в тестах.

### Drive-модель порыва (чистый домен)

Четыре именованных, настраиваемых «тяги» дают единый порыв `urge ∈ [0, 1]`
(`proactivity/urge.py`, `UrgeModel.urge` — чистая функция без I/O и часов):

- **настроение** — открытое, возбуждённое, социальное настроение поднимает порыв,
  замкнутое опускает (среднее по осям `arousal`/`openness`/`social` из `Mood`);
- **тоска** (`longing`) — растёт с секундами тишины и насыщается (экспонента с
  постоянной времени ~6 ч), так что сутки молчания ощущаются сильно, но порыв
  никогда не «убегает» за пределы;
- **салиентность** — насколько свежа и ярка последняя reflect-мысль heartbeat;
- **циркадный ритм** — базовый уровень по **локальному** часу (низкий ночью, с
  утренним и вечерним пиками и дневным провалом); час берётся из `Clock`.

К ним добавляется уровень социальной энергии. Взвешенная сумма нормируется в
`[0, 1]`. Энергия (`proactivity/social_energy.py`, `SocialEnergy`) — это
ограниченный `[0, 1]` резервуар: он **копится** в тишине (`recover`), **тратится**
на реплику (`spend`, фиксированная доля) и **частично восполняется** ответом owner
(`replenish_from_reply`). Так cooldown после разговора возникает естественно, без
отдельного таймера.

### Стохастика и решение

`ProactiveDecider` (`proactivity/decision.py`) — шов, который движок зовёт
на каждом тике. Он берёт «сейчас» из инъецированного `Clock`, считает `urge`,
переводит его в вероятность срабатывания `p(speak)` монотонной **логистической**
кривой (`urge_to_probability`) и делает **один** розыгрыш из инъецированного
seeded `Random`. Governance проверяется **первой**: любое вето означает молчание
независимо от порыва.

### Governance — только потолки безопасности

Governance — это тормоз, а не двигатель: он **никогда не поднимает** порыв, только
блокирует (`proactivity/governance.py`, `Governance.allows` → `bool`). Пять
вето, все чистые и над инъецированным «сейчас»:

- **quiet hours** — жёсткий ночной пол по **локальному** времени (по умолчанию
  23:00–09:00, окно переваливает через полночь);
- **owner-mute** — персист-флаг, который owner переключает командами `/quiet` /
  `/wake`;
- **анти-спам** — потолок на число проактивных сообщений в окне (по умолчанию 4 за
  сутки);
- **мин-гэп** — минимальный интервал между двумя проактивами (по умолчанию 1 ч);
- **owner-cooldown** — тихий интервал после последнего сообщения owner (по
  умолчанию 15 мин), чтобы Боб не говорил поверх собеседника.

Пороги вынесены в `GovernanceConfig` (все именованы и имеют дефолты) — тюнятся на
живой эксплуатации.

### От тика к реплике (дёшево по умолчанию)

`ProactivityEngine` (`proactivity/usecases/engine.py`) — оркестратор за RFC
§«Фаза 1». Помимо store/decider/router/gateway/clock/RNG ему инъецируются
`MemoryRecall` (grounding компоновки в реальной памяти), `EpisodeWriter` (персист
проактива в `episodic_log`), `language` (директива языка персоны, по умолчанию
`DEFAULT_LANGUAGE`) и `RepeatThresholds` (тот же `repeat.*`-порог, что у реактивного
стража, — для recall-aware анти-повтора, BOB-032 R4). На каждом проактивном тике,
cheapest-first:

1. **Загрузка** per-persona `ProactivityState` через порт `ProactivityStore`
   (энергия, маркеры `last_spoke_at`/`last_user_msg_at`, флаг `/quiet`).
2. **Истечение тайм-мьюта.** Постоянный `/quiet` держит молчание до `/wake`.
   Срочный `/quiet 2h` (`mute_until` выставлен) снимается в указанный момент:
   движок один раз durably возвращает флаг проактивности и чистит `mute_until`,
   так что лапснувший мьют не пересчитывается на каждом дальнейшем тике.
3. **Восстановление энергии** за тишину с последнего сообщения owner.
4. **Решение** — `ProactiveDecider`: `urge` → `p(speak)` → seeded-розыгрыш под
   governance-вето. **По умолчанию — молчать.** Вето или непрошедший розыгрыш
   завершают тик с **нулём** LLM-вызовов.
5. **Гейт (Tier 0)** — только при срабатывании дешёвый внутренний редактор
   спрашивает «есть ли сейчас что сказать на самом деле и о чём?». Он склонен
   пропускать молчание: только финальная строка `SAY: <seed>` даёт говорить,
   `SKIP` (или пустой/искажённый ответ) завершает тик одним дешёвым вызовом без
   сообщения. Промпт гейта несёт директиву языка персоны (BOB-012).
6. **Grounding в реальной памяти + компоновка + анти-повтор + постинг** — на не-skip
   seed движок сперва тянет релевантную **настоящую** память через инъецированный
   `MemoryRecall` (гибрид-recall по seed, `k=3`) и кладёт вспомненные строки в
   `shareable_context` компоновки. Системный промпт несёт явную анти-конфабуляционную
   инструкцию: опираться **только** на реально вспомненные моменты, а если ничего не
   подходит — говорить в общем о своём состоянии, а не выдумывать прошлое событие. Так Боб
   ссылается на настоящие моменты, а не сочиняет фейковый «общий момент». Промпт
   компоновки тоже несёт директиву языка персоны. Реплика собирается через
   `LLMRouter` с гибридным выбором тира (`select_reply_tier`: обычно быстрый flash,
   качественный plus — на содержательное).

   Перед постингом применяется **тот же recall-aware анти-повтор** (BOB-032, R4):
   `_compose_without_repeat` сверяет свежий драфт (через `is_bob_repeat` на инъецированном
   пороге `RepeatThresholds`) с `bob:`-репликами, всплывшими в recalled-памяти
   (`recalled_bob_replies`) — те же доменные помощники из `conversation.py`, что и у
   реактивного стража, без дублирования логики. Прежде проактив **обходил** анти-повтор и
   мог дословно скопировать свой recalled-ответ (самоинициированный повтор). При повторе
   движок ломает аттрактор так же, как реактивный страж — убирает из grounding совпавший
   recalled-экземпляр (`recalled_without_copied_exemplars`, факты сохраняются) и
   перегенерирует, до `_MAX_REGENERATIONS=2`. Отличие от реактивного хода: если повтор
   выживает после порога, проактив **не постит** (`tick` возвращает `False`, состояние не
   сдвигается) — у самоинициированного сообщения нет ждущего ответа пользователя, поэтому
   подавление безопаснее отправки; Боб напишет в другой раз. Прошедшая проверку реплика
   постится в топик Боба через `typing_indicator` + `reply` его gateway.
7. **Персист** — потратить энергию (`spend`), проставить `last_spoke_at`, **и
   дописать отправленную реплику в эпизодическую память** (BOB-012). Движок пишет
   реплику в `episodic_log` через инъецированный порт `EpisodeWriter` (подмножество
   `MemoryRepo`) — эпизод `event_type=proactive`, контент `bob (proactive): <текст>`,
   снапшот настроения, теги `telegram,proactive`. Тем же путём, что реактивный ход
   сохраняет turn, проактив попадает в recall + recent-history, поэтому Боб может
   потом сослаться на сказанное и объяснить его (раньше реплика никуда не писалась,
   и Боб «не помнил», что сказал).

`ProactiveTick` (`proactivity/usecases/tick.py`) — тонкая обёртка, которую
рантайм планирует на heartbeat-каденсе (`app.py`, `_background_tasks`) рядом с
inner-monologue / mood-drift / reflect и под той же `RetryPolicy`: транзиентный
сбой LLM/сети на сработавшем тике ретраится с backoff до изоляции. Тик дёшев —
большинство циклов не трогают LLM.

### Связь с реактивным чатом и owner-команды

`RecordOwnerActivity` (`proactivity/usecases/record_owner_activity.py`)
вызывается после каждого сообщения owner в реактивном пути (`HandleMessage`): он
проставляет `last_user_msg_at` (взводит owner-cooldown, чтобы Боб не говорил поверх
собеседника) и частично восполняет резервуар энергии — «ты вернулся». Остальное
состояние сохраняется как есть: мьют `/quiet` переживает входящее сообщение,
`last_spoke_at` не трогается.

Owner управляет проактивностью через GUPPI (топик General), только owner:

- **`/quiet`** — заглушить проактив (сбросить `proactivity_enabled`); опциональная
  длительность `/quiet 2h` / `/quiet 30m` дополнительно выставляет `mute_until`,
  по истечении которого движок сам разбудит проактив (см. шаг 2 выше);
- **`/wake`** — снять мьют и очистить `mute_until`.

Невалидный аргумент `/quiet` даёт подсказку по использованию, а не молчаливый
мьют. Команды живут в `GuppiHandler` и подключены, только когда в сборку подан
proactivity-store; иначе они деградируют в no-op (обратная совместимость).

### Хранилище и read-seams

`SqliteProactivityStore` (`proactivity/adapters/proactivity_store.py`)
реализует порт `ProactivityStore` над таблицей `proactivity_state` — одна строка на
`persona_id`, так что реплики Bobiverse держат свои резервуар, маркеры и флаг. Поверх
порта он несёт инфраструктурный тайм-мьют `mute_until` (он **не** часть доменного
value-объекта `ProactivityState`, живёт только в строке и читается/пишется через
`get_mute_until` / `set_mute_until`). Весь SQL параметризован (`?`).

`RepoProactivitySources` (`proactivity/adapters/proactivity_sources.py`) даёт
движку два дешёвых (без LLM) сигнала прямо из `episodic_log`: **салиентность
рефлексии** (свежий `reflection`-эпизод даёт салиентность около `1.0`, линейно
затухающую к `0.0` за 6 ч) и **счётчик проактивов в окне** (число `proactive`-
эпизодов за последние сутки — потолок анти-спама). Время инъектируется через
`Clock`, поэтому затухание детерминировано.

## Автономность (Тир 2): Goal Engine + самонаправленность (BOB-015)

Боб реактивен и проактивен в чате (стадия A), но это первый слой, где у него
появляются **собственные цели** и право **сам продвигать** уже одобренные —
автономность-стадии B. Подложка из трёх частей: **Goal Engine** (чистый граф целей
и задач + персист), **Planner** (LLM-декомпозиция цели в задачи) и
**самонаправленный тик** `PursueGoalsTick`, который продвигает безопасные шаги через
**те же** ворота, что и проактивный чат. Два инварианта держат автономность в узде:
*authz-before-autonomy* (тик трогает только одобренные владельцем цели) и *граница
стадии C* (внешняя агентность — код, инструменты, файловая система, внешние API — не
исполняется автономно, только предлагается владельцу). Всё состояние per-persona,
время и стохастика инъецируются, поэтому домен и тик детерминированы в тестах.

### Goal Engine — чистый граф целей (`proactivity/goals/`)

Граф целей — чистый домен без I/O и без часов. Value-объекты (`entities.py`,
`frozen, slots`):

- **`Goal`** — что и зачем: `title`, `description`, `priority` (целое, больше =
  важнее), `criteria` (текстовый критерий завершения), `state: GoalState`,
  `created_at`, `origin: GoalOrigin` (`OWNER` — цель от владельца, `BOB_PROPOSED` —
  Боб предложил сам), опциональный `deadline`.
- **`Task`** — единица работы цели: `summary`, `deps` (id задач-предшественников той
  же цели), `state: TaskState` и **`needs_external_agency: bool`** — флаг стадии C.
  Внешне-агентная задача никогда не исполняется автономно и исключается из
  авто-готовых.

Машины состояний (`state.py`, строковые `Enum`, значения совпадают с тем, что
кладётся в SQLite):

- **`GoalState`:** `PROPOSED` → `APPROVED` → `ACTIVE` ↔ `BLOCKED` → терминальные
  `DONE` / `CANCELLED`; `PAUSED` — обратимая остановка владельцем. Переход
  `PROPOSED → APPROVED` валиден на уровне домена, но **инициирует его только
  owner-апрув** на уровне use-case. Перейти в `ACTIVE` минуя `APPROVED` нельзя —
  двойной гейт (сперва цель, затем план).
- **`TaskState`:** `NEW` → `READY` → `IN_PROGRESS` → `DONE`; `BLOCKED` (обратима в
  `READY`) и `SKIPPED` (терминальная, завершению цели не мешает).
- `can_transition(frm, to)` / `can_transition_task(frm, to)` — чистые предикаты по
  таблицам разрешённых переходов; самопереход переходом не считается, терминальные
  состояния исходящих переходов не имеют.

`GoalGraph` (`graph.py`) — immutable-снимок целей и задач персоны, который стор
отдаёт use-case'ам (`goal_by_id`, `tasks_of`). Поверх — чистые, детерминированные
граф-функции:

- **`ready_tasks(graph)`** — задачи, готовые к авто-продвижению: цель в
  `APPROVED`/`ACTIVE`, состояние задачи `NEW`/`READY`, все `deps` в `DONE`, и
  `needs_external_agency` ложно.
- **`next_safe_task(graph)`** — следующая безопасная задача: максимальный приоритет
  цели, при равенстве — стабильный tie-break по id задачи (`None`, если готовых нет).
- **`is_goal_complete(goal, tasks)`** — структурная завершённость: все не-`SKIPPED`
  задачи цели в `DONE` (цель без задач завершённой не считается; текстовый критерий
  проверяет use-case или владелец, не домен).
- **`blocked_reason(graph, task)`** — короткая человекочитаемая причина, почему
  задача не готова (внешне-агентная / цель не активна / незавершённые deps /
  неподходящее состояние), либо `None`.
- **`external_agency_tasks(graph)`** — внешне-агентные задачи готовых целей: те же
  ворота готовности, но `needs_external_agency` истинно — это кандидаты на
  стадию-C гейт, а не на авто-исполнение.

Обход устойчив к циклам `deps`: незавершённый предшественник просто делает задачу
неготовой, рекурсивного обхода нет — зависнуть негде.

Персист — за портом **`GoalStore`** (`proactivity/ports.py`): `load(persona_id)` (пустой
граф для невиданной персоны), `save_goal` / `save_task` (UPSERT), атомарные
`update_goal_state` / `update_task_state`. Адаптер
**`SqliteGoalStore`** (`proactivity/adapters/goal_store.py`) маппит граф на
таблицы `goal` и `task` (одна строка на `(persona_id, id)`, так что реплики
Bobiverse держат свои цели); `deps` round-trip'ит JSON-массивом, enum'ы — своими
строковыми значениями, весь SQL параметризован.

### Planner — декомпозиция цели в задачи (`plan_goal.py`)

Порт **`Planner.decompose(goal) → Sequence[Task]`** (`proactivity/ports.py`) разбивает
`APPROVED`-цель на атомарные задачи с зависимостями и **классифицирует
`needs_external_agency`**. Живая реализация — **`LlmPlanner`**: просит
reasoning-модель (Tier 1, `TaskType.PLAN_GOAL`) и парсит строгий JSON так же
терпимо, как извлечение фактов (markdown-fence / преамбула / мусор по краям
терпятся). Локальные id модели детерминированно ремапятся на `<goal_id>::t<n>`,
задачи рождаются в `TaskState.NEW`, а `needs_external_agency` по умолчанию ложно
(безопасный дефолт — задача считается автономно-безопасной, пока её явно не пометили
внешней). Ошибка провайдера или непарсимый ответ дают **пустой план** (best-effort),
а не исключение.

Use-case **`PlanGoal`** держит **двойной апрув**:

- **`run(goal_id)`** — берёт цель в `APPROVED` (владелец её уже одобрил, плана ещё
  нет) → `Planner.decompose` → сохраняет задачи → возвращает `PlanResult` с
  сообщением владельцу (список задач, зависимости, пометки внешне-агентных). Цель
  **остаётся `APPROVED`** до явного апрува плана.
- **`approve_plan(goal_id)`** — второй гейт: `APPROVED → ACTIVE` через
  `can_transition` (нелегальный переход или отсутствие цели → `False`, состояние не
  трогается).

Конфиг `goals.require_plan_approval` (по умолчанию `True`) включает двойной гейт;
при `False` декомпозиция сразу переводит цель в `ACTIVE` (одинарный гейт).

### Самонаправленный тик (`pursue_goals.py`)

**`PursueGoalsTick`** — heartbeat-тик, которым Боб продвигает свои цели сам. Он **не
заводит новой машинерии безопасности**: идёт через те же ворота, что проактивный чат
(`Governance` + kill-switch), и опирается на чистый домен (`next_safe_task` сам
исключает неутверждённые цели и внешне-агентные задачи). Порядок одного тика строгий:

1. **Гейты первыми, до любой работы.** Сперва **kill-switch**
   (`PursuitStore.is_pursuit_stopped`): стоп — тик ничего не делает. Затем
   `Governance.allows` — та же машина, что у проактива (quiet-hours / owner-mute /
   cooldown / per-window ceiling) над инъектированным часом и снимком истории. Вето
   завершает тик с нулём работы. Сверх governance — собственный rate-limit
   `max_tasks_per_window` (считается по эпизодам `goal_progress` в окне).
2. **Выбор задачи** — `goal_store.load(persona_id)` → `next_safe_task`. Домен
   гарантирует: только `APPROVED`/`ACTIVE` цели, состояние `NEW`/`READY`, deps
   `DONE`, без `needs_external_agency`.
3. **Исполнение только безопасного шага.** Задача `READY` → `IN_PROGRESS`, затем шаг
   исполняется **исключительно через `SafeCapabilityDispatcher`** —
   allowlist-ограниченный вид над `CapabilityRegistry`
   (`application/capabilities/registry.py`), который раскрывает только пересечение
   реестра с safe-allowlist (`goals.safe_capabilities`). Capability вне allowlist
   физически недоступна (`allows` → `False`, `dispatch` бросает
   `CapabilityNotAllowedError`), поэтому внешне-агентная или произвольная capability
   не может исполниться на автономном пути **по построению**. Сбой диспатча
   сворачивается в `None` → задача `BLOCKED`, не в эскалацию.
4. **Состояние + критерий + прозрачность.** Задача → `DONE` (или `BLOCKED` при
   неуспехе); если `is_goal_complete` — цель `ACTIVE` → `DONE`; автономное
   продвижение пишется **эпизодом** (`event_type=goal_progress`, теги `goal`,
   `autonomous`) для recall и подсчёта rate-limit, и владельцу уходит короткое
   **прогресс-сообщение** в стиле BOB-024 («Занялся целью … — сделал: …»).

Если безопасной задачи нет, тик может вынести готовую внешне-агентную задачу
(`external_agency_tasks`) владельцу как **предложение** стадии C («для этого нужен
код или внешний инструмент — запустить?») — только предложение, без исполнения.
В рантайме тик супервизится так же, как heartbeat (`periodic` + `RetryPolicy`), и
планируется **только** при включённой автономности.

### Контроль владельца (`guppi.py`)

Цели под рулём владельца через GUPPI (топик General, **только owner**, не гость):

- **`/goals`** — список целей (title, состояние, число задач); `/goals stop` и
  `/goals go` переключают **kill-switch** (персист-флаг `proactivity_state.
  pursuit_stopped`, который тик читает первым).
- **`/goal <action> <id>`** — `approve` (`PROPOSED → APPROVED`), `plan` (запустить
  `PlanGoal.run` и показать план), `plan-approve` (второй гейт, `PlanGoal.
  approve_plan`), `pause` / `resume` / `cancel`. Каждый state-переход гейтится
  `can_transition`, поэтому нелегальный переход отклоняется с подсказкой, а не
  форсируется.

Команды подключены, только когда в сборку поданы goal-store и `PlanGoal`; иначе
деградируют в no-op. Боб может **предложить** цель (`origin=BOB_PROPOSED`,
`state=PROPOSED`) — но тик никогда не трогает `PROPOSED`, предложение ждёт апрува.

### Границы безопасности: стадия B против стадии C

- **Мастер-выключатель `goals.pursuit_enabled`** (по умолчанию **OFF**) —
  `PursueGoalsTick` собирается и планируется только когда он включён; без него
  рантайм ровно прежний.
- **Authz-before-autonomy** — тик продвигает только цели в `APPROVED`/`ACTIVE`
  (домен исключает `PROPOSED`/`PAUSED`/`BLOCKED`/терминальные), а в `APPROVED` цель
  переводит только owner-апрув. Боб не действует по неутверждённой цели.
- **Граница стадии C** — внешняя агентность (код / инструменты / файловая система /
  внешние API) **не исполняется автономно**, только предлагается владельцу. Защита
  эшелонирована: домен исключает `needs_external_agency` из готовых
  (`ready_tasks`/`next_safe_task`), а `SafeCapabilityDispatcher` физически не даёт
  вызвать ничего вне safe-allowlist — даже если бы задача прорвалась.

## Self-Improvement (Тир 2): метакогнитивное обучение (BOB-028)

Рядом с автономностью BOB-015 лежит **метакогнитивный слой**: Боб замечает
поведенческие паттерны за собой (перебарщивает с длиной, повторяется, промолчал
когда стоило ответить, залип в низком настроении), формулирует человекочитаемое
**правило-стратегию** (наблюдение + поправка + рычаг + ограниченная величина),
предлагает его владельцу, и по апруву применяет как **мягкий, обратимый наклон**
поведения. Это шлифовка Тир-1-личности на собственной истории общения. Та же
дисциплина, что и автономность: правило ничего не меняет молча и **никогда не
трогает безопасность/ядро**.

### Модель правила — чистый домен (`proactivity/self_improvement.py`)

- **`Lever`** (`StrEnum`) — **жёсткий allowlist** рычагов, которые правило вправе
  наклонять: `TONE`, `LENGTH`, `PROACTIVITY`, `ADDRESSIVITY_BIAS`, `HUMOR` — **и
  только они**. У него намеренно нет члена для authz, гость-инварианта (BOB-019),
  ядра SOUL или safety-инвариантов автономии (BOB-015): правило не может выбрать
  несуществующий рычаг, поэтому граница безопасности здесь **конструктивна**, а не
  держится на проверках.
- **`RuleState`** (`StrEnum`) — машина жизненного цикла под owner-апрувом:
  `PROPOSED` → `APPROVED` ↔ `PAUSED`; `PROPOSED` → `REJECTED`; `APPROVED`/`PAUSED`
  → `REMOVED`. `REJECTED`/`REMOVED` терминальны. Переход в `APPROVED` валиден на
  уровне домена, но его инициирует **только** owner-апрув на уровне use-case.
  `RuleOrigin.BOB_PROPOSED` фиксирует, что правило вывел сам Боб.
- **`ImprovementRule`** (`frozen, slots`) — `id`, `observation` (рус,
  человекочитаемо), `adjustment`, `lever`, `magnitude` (в `[0, 1]`), `state`,
  `origin`, `created_at`, `evidence` (какие паттерны сработали).
- Чистые функции: `active_rules(rules)` возвращает только `APPROVED` (на этом
  держится authz-before-autonomy на applied-стороне), `rules_for_lever(rules,
  lever)`, `can_transition(frm, to)`, `clamp_magnitude(value, *, cap)` (зажимает
  наклон в `[0, cap]`, отрицательное обнуляет — наклон не инвертирует базовое
  поведение), `is_duplicate_rule(candidate, existing, *, threshold)` (дубль = тот
  же рычаг и близкое наблюдение, реюз идеи анти-повтора BOB-026 через
  `SequenceMatcher`, порог `0.85`).
- **`build_modulators(rules, *, max_magnitude)` → `RuleModulators`** — собирает
  мягкие наклоны из `active_rules`, каждый рычаг в свою точку. `RuleModulators`
  (`frozen, slots`) несёт `voice_adjustments` (поправки тона/юмора),
  `length_step` (сдвиг ступени многословия, `-1` короче либо `0`),
  `proactivity_bias` и `addressivity_bias` (в `[0, max_magnitude]`); `has_any()`
  отвечает, есть ли хоть один ненулевой наклон. Несколько правил по одному рычагу
  суммируются, но суммарный наклон зажат потолком.

Персист — порт **`SelfImprovementStore`** (`proactivity/ports.py`) +
`SqliteSelfImprovementStore` (`proactivity/adapters/self_improvement_store.py`)
над таблицей `improvement_rule` (строка на `(persona_id, id)` — реплики Bobiverse
держат свои правила раздельно). `load` / `save_rule` (UPSERT) /
`update_rule_state` (атомарная запись одного столбца, которую гонит owner-апрув);
enum'ы персистятся строковым `.value`, SQL параметризован.

### Детектор паттернов (`application/usecases/detect_patterns.py`)

- Порт **`PatternDetector`** (`proactivity/ports.py`): `detect(signals)` возвращает
  правила-кандидаты строго в `PROPOSED`. **`LlmPatternDetector`** — реализация
  через Tier-1 LLM (`TaskType.DETECT_PATTERNS`): из среза сигналов формулирует
  человечное правило и **выбирает рычаг только из `Lever`-allowlist**. Разбор JSON
  терпимый, как при извлечении фактов (markdown-fence / преамбула / мусор по краям
  переживаются); каждый кандидат жёстко нормализуется в коде — `state` принудительно
  `PROPOSED`, `origin` — `BOB_PROPOSED`, рычаг вне allowlist отбрасывается,
  `magnitude` клампится. Сбой провайдера или непарсимый ответ дают **пустой список**
  (best-effort, без падения тика).
- **`ImprovementSignals`** (`frozen, slots`, домен) — структурированный срез
  наблюдений Боба за собой: `self_repeat_count` (самоповторы BOB-026),
  `addressivity_outcomes` (исходы SILENT/REACT/ENGAGE, BOB-023/025),
  `verbosity_misses` (промахи длины-vs-спрос BOB-024), `relationship_deltas`
  (BOB-014), `mood_stuck`/`mood_stuck_tone` (застревание настроения),
  `owner_friction`, `positive_signals` (что зашло), `recent_observations`
  (грундинг формулировки). Каждый источник опционален, дефолт — «нет сигнала».
- **`DetectPatterns`** — use-case с ReflectTick-seam (редкий каденс): собрать
  сигналы (опциональный `SignalSource`; unwired → пустые сигналы) → `detect` →
  **дедуп** против существующих правил → сохранить новых кандидатов в `PROPOSED`.
  Лимит `max_active_rules` (по «живым» — PROPOSED/APPROVED/PAUSED) не даёт плодить
  правила. Здесь только предложение, никакого применения.

### Апрув-флоу и применение

**Боб проговаривает предложение.** `AnnounceProposedRules`
(`application/usecases/announce_rules.py`) на медленном reflect-каденсе тактично
произносит **одно** свежее `PROPOSED`-правило за прогон (самое старое
непроговорённое) — «Заметил за собой: …. Предлагаю: …. Включить? (/rule approve
<id>)». In-memory-страж не повторяет уже проговорённое; проговариваются только
`PROPOSED`; best-effort (сбой логируется, тик не валит). `ActiveRulesReader`
(`proactivity/usecases/self_improvement_sources.py`) — read-seam applied-стороны:
грузит правила из стора и отдаёт только `active_rules` (`APPROVED`).

**Owner-команды GUPPI** (`infrastructure/telegram/guppi.py`, owner-only в General,
как `/goals`): `/rules` (список id / состояние / рычаг / наблюдение) и `/rule
approve|reject|pause|resume|remove <id>`. Переход правила проверяется машиной
(`can_transition`): нелегальный ход (например, апрув уже убранного правила)
отклоняется, не форсится. Это **единственный** путь `PROPOSED → APPROVED` —
authz-before-autonomy. Незнакомое действие `/rule` не «съедается» (возвращает
`False`); без подключённого стора команды тоже не активны.

**Мягкое применение** в `HandleMessage` (read-seam `SelfImprovementReader`): когда
шов подключён и мастер-выключатель включён, `_load_modulators` собирает
`build_modulators(active_rules, max_magnitude=…)` и раздаёт наклоны по точкам —

- `TONE`/`HUMOR` → `voice.improvement_directive(adjustments)` сворачивает поправки
  одобренных правил в одну мягкую voice-строку поверх тона настроения/отношений
  (наклон, не команда и не подмена личности);
- `LENGTH` → сдвиг ступени многословия BOB-024 на одну позицию (только к короче),
  край лестницы клиппится приёмником;
- `ADDRESSIVITY_BIAS` → повышает `interest` адресности (BOB-023/025) на величину
  байеса (клампится в `[0, 1]`);
- **`PROACTIVITY` → байес собирается** в `RuleModulators.proactivity_bias`, **но
  точка применения (urge/governance BOB-010) пока не провязана** — это намеренный
  **known-gap** (collect-not-apply): рычаг входит в allowlist, детектируется и
  суммируется в байес, однако `proactivity_bias` сейчас не читается ни в
  `handle_message`, ни в проактивном тике. Поведение проактивности от этого не
  меняется (безопасный недо-провод, не недосмотр); провязка urge-точки — отдельный
  seam на потом.

Конфигурация — секция `self_improvement.*` (`infrastructure/config/loader.py`):
мастер-выключатель **`enabled` (по умолчанию `false`)**, `detect_cadence` (`20`),
`detector_tier` (`1`), `max_active_rules` (`5`), `max_magnitude` (потолок наклона,
`0.3`). Сборка — в `app.py` (`_build_self_improvement`): выключатель OFF → ни
reader'а, ни `DetectPatterns`, ни `AnnounceProposedRules` (поведение ровно как до
BOB-028); ON → шов подключён к `HandleMessage` и к reflect-тику (`heartbeat.py`).

### Границы безопасности по конструкции

- **Defense-in-depth** — три эшелона: `Lever`-allowlist в домене (нет рычага для
  authz/гостя/SOUL/safety → правило их не представит), парсер детектора (рычаг вне
  allowlist отбрасывается), применение (`build_modulators` читает только allowlist).
- **Authz-before-autonomy** — применяются только `active_rules` (`APPROVED`);
  детектор лишь предлагает (`PROPOSED`); без owner-апрува ничего не наклоняется.
- **Наклон, не перехват** — величины клампятся к `max_magnitude`; `LENGTH`
  сдвигает не больше одной ступени и только к короче; суммарный дрейф по рычагу
  зажат потолком, число правил — лимитом `max_active_rules`.
- **OFF по умолчанию** — `self_improvement.enabled=false`: детектор не запущен,
  правил нет, ход и тики ровно как до BOB-028.
- **Known-gap (зафиксирован):** `RuleModulators.proactivity_bias` собирается, но
  его точка применения в urge/governance (BOB-010) пока не провязана —
  collect-not-apply. Это безопасно (проактивность не меняется) и оставлено как
  отдельный seam на потом, а не как пропущенная провязка.

## Конфигурация и запуск

`ConfigLoader` собирает эффективную конфигурацию слоями: встроенные дефолты →
опциональный YAML (`yaml.safe_load`) → переменные окружения (префикс `BOB_`,
`__` для вложенности). Секреты приходят только из конфигурации/env и нигде не
инлайнятся.

**Два бота в конфиге (BOB-003).** Токены лежат под `telegram.bob.token` и
`telegram.guppi.token` и питаются env-переменными. Маппинг не один-к-одному с
правилом вложенности, поэтому токены special-cased в `_TOKEN_ENV_MAPPING`: env
`BOB_TELEGRAM__TOKEN` → `telegram.bob.token` (общий префикс `BOB_` без явного
маппинга попал бы в `telegram.token`), а env `GUPPI_TELEGRAM__TOKEN` →
`telegram.guppi.token` (нестандартный префикс `GUPPI_`, который generic-механизм
`BOB_` вообще не подхватывает). Оба применяются последними, поэтому env по-прежнему
выигрывает. Остальные `telegram`-параметры — non-secret: `telegram.chat_id`,
`telegram.bob.topic_id` (топик Боба), `telegram.owner_id`, `telegram.poll_timeout`
и `telegram.allowed_chat_ids` (список целых или CSV-строка из env). Секция `llm`
несёт настройки reasoning-модели — `timeout_seconds` (по умолчанию `180`) и
`disable_thinking` (по умолчанию `true`) — и сэмплинг по тирам:
`tier0_temperature` (по умолчанию `0.5`) и `tier1_temperature` (по умолчанию `0.8`,
BOB-022, против дословного самоповтора при жадном декодировании); все значения
терпят строковую форму из env-переменных, а отсутствие температуры оставляет
endpoint его собственный дефолт. Секция `runtime` несёт `language` (по умолчанию `ru`) — язык
персоны для само-генерируемого текста (проактив-компоновка, Tier-0-гейт, тики
монолога и рефлексии); этим само-генерациям нечего зеркалить, поэтому без явного
ограничения модель уходит в английский (BOB-012, см. «Язык персоны»). Опциональная
секция `personality.evolution` несёт скорости само-эволюции `alpha`/`beta`
(BOB-013, дефолты `0.15`/`0.10` из доменного ядра) — тюнинг темпа дрейфа вкуса без
правки домена. Блок `emotion.*` (BOB-020) тюнит эмоциональную глубину: порог
off-day-тона `emotion.offday.{valence,arousal}`, стартовую интенсивность и частоту
проявления увлечения `emotion.fascination.{initial_intensity,mention_freq}` и
бэнд/каденс эволюции фантомов `emotion.phantom.{max_count,change_rate}` (см.
«Эмоциональная глубина»). Блок `goals.*` (BOB-015) тюнит автономность:
`require_plan_approval` (двойной апрув, по умолчанию `true`), `planner_tier`
(тир декомпозиции, `1`), мастер-выключатель `pursuit_enabled` (по умолчанию
`false`), каденс тика `tick_seconds` (по умолчанию `900` ≈ 15 мин),
`max_tasks_per_window` (rate-limit поверх governance), `safe_capabilities`
(safe-allowlist автономного пути, пустой по умолчанию) и `pursuit_stopped`
(дефолт kill-switch); см. «Автономность».

Пакет `runtime/` (composition root; вход через `build_application` в
`runtime/composition.py`, `app.py` — тонкий shim) — единственный слой, которому
разрешено зависеть сразу от всех слоёв и всех модулей.
Он строит реальные адаптеры, собирает политику приложения, подписывает
`HandleMessage` на шину, регистрирует **один** poll-таск (он гонит обоих ботов
через `MultiBotGateway`) и **четыре** heartbeat-тика (inner-monologue, mood-drift,
reflect и проактивный `ProactiveTick`, все с `RetryPolicy`) как фоновые задачи
рантайма, один раз запускает Genesis на первом старте и стартует `AgentRuntime`.
Язык персоны (`runtime.language`, по умолчанию `DEFAULT_LANGUAGE`) читается один раз
и протягивается в `InnerMonologueTick`, `ReflectTick` и проактивный движок (BOB-012).
Проактивный движок собирается в `_build_proactivity_engine`: чистый
`ProactiveDecider` (urge-модель + `Governance`) над общим `SqliteProactivityStore`,
роутером, gateway Боба и read-seams `RepoProactivitySources`; сюда же инъецируются
живой `recall` (`HybridMemoryRecall` — grounding компоновки в реальной памяти),
`repo` (`SqliteMemoryRepo` как `EpisodeWriter` — персист проактива в `episodic_log`)
и `language` из `runtime.language`. RNG-seed резолвится детерминированно (аргумент →
`runtime.proactivity_seed` → env `BOB_PROACTIVITY_SEED` → свежий на процесс), чтобы
тесты пинили стохастический розыгрыш. Тот же store
питает owner-команды `/quiet`/`/wake` в GUPPI, а `RecordOwnerActivity` сворачивает
каждое сообщение owner в проактивное состояние.
Здесь же собирается `BotRegistry`: Боб регистрируется со scope своего топика, GUPPI
— со scope General, и оба идут в `MultiBotGateway`. `HandleMessage` отдаёт ответы
через `multibot.reply_gateway(BotIdentity.BOB)`, поэтому они приколочены к топику
Боба. `HandleMessage` собирается с Negotiation-врезкой (BOB-013): дефолтный
`TasteZoneClassifier` и `Negotiation` инъецируются, поэтому Боб защищает свои
ценности директивой стойки (см. «Higher Mind»). Само-эволюция (BOB-013, Ф2)
собирается в `ReflectTick`: `ApplyReflection` с `HeuristicReflectionParser`
получает скорости обучения `α`/`β` из `personality.evolution.{alpha,beta}` (дефолты
из ядра — `0.15`/`0.10`), а персист эволюционировавшего вкуса идёт через тот же
`SoulStore`. Сюда же (BOB-020) подключаются два эмоциональных шага эволюции на том же
тике: `EvolveFascination` (над `SqliteFascinationStore`, роутером и общим швом
`RepoFascinationGrounding`, стартовая интенсивность из `emotion.fascination.
initial_intensity`) и `EvolvePhantoms` (над живым `SOUL`, персист через `SoulStore`,
seeded-RNG и бэнд/каденс из `emotion.phantom.*`); оба grounded в реальной внутренней
жизни Боба. Off-day-тон собирается в `handle_message` через
`_build_offday_thresholds` (`emotion.offday.*`). Здесь же собираются общий `Authorizer` (над `KvAllowlistStore`) для
гейта и GUPPI и `CapabilityRegistry` с навыками `recall_memory` и **`search_memory`**;
провайдер Tier 1 подключается как `ToolCallingProvider`, когда поддерживает
tool-calling, иначе tool-loop остаётся дремлющим. Гибридная память (BOB-011)
собирается здесь же: эмбеддер и опциональный реранкер — инъецируемые швы (по
умолчанию строятся из `embeddings.*`/`reranker.*`, без сетевого вызова на сборке),
эмбеддер заводится в `SqliteMemoryRepo` (бэкфилл + on-write), а живой recall —
`HybridMemoryRecall` (FTS5 + sqlite-vec → RRF, опц. реранк). Отсутствие/невалидность
секции `embeddings` логируется и даёт keyword-only recall — app всё равно стартует.
Goal Engine (BOB-015) собирается здесь же: `SqliteGoalStore` (round-trip целей) и
`PlanGoal` над `LlmPlanner` (декомпозиция через Tier-1-роутер) питают owner-команды
целей в GUPPI. Самонаправленный `PursueGoalsTick` собирается **только** при
включённом `goals.pursuit_enabled` (по умолчанию off → рантайм ровно прежний): он
получает `SafeCapabilityDispatcher` над реестром, суженным до `goals.
safe_capabilities`, ту же `Governance`, kill-switch из `SqliteProactivityStore`,
rate-limit `goals.max_tasks_per_window` и планируется на собственном (редком)
каденсе `goals.tick_seconds`. Реальный aiogram `Bot` каждого бота строится из его
env-токена (`_build_real_bot`) и адаптируется к протоколу `BotLike`
(`_AiogramBotAdapter`) — оба вернулись в дом `infrastructure/telegram/
aiogram_adapter.py` (BOB-062.7a), composition root зовёт их через фабрики
`runtime/wiring/`. Провайдеры и оба бота — инъецируемые швы (`bob_bot`,
`guppi_bot`), поэтому весь граф прогоняется end-to-end на фейках без сети.

### Операционная заметка: прод-запуск двух ботов

Для боевого запуска нужны **два токена в env** — `BOB_TELEGRAM__TOKEN` (Боб) и
`GUPPI_TELEGRAM__TOKEN` (GUPPI). **Оба бота должны быть админами группы**: только
тогда они видят все сообщения (privacy mode иначе скроет групповые сообщения от
ботов; решается операционно — права админа либо `/setprivacy disable` у BotFather).
Именно из-за того, что оба админа видят одно сообщение, нужен кросс-бот дедуп по
`(chat_id, message_id)`. Целевые идентификаторы задаются в конфиге:
`telegram.chat_id` (supergroup), `telegram.bob.topic_id` (форум-топик Боба),
`telegram.owner_id` (владелец, кому доступны owner-команды) и
`telegram.allowed_chat_ids`. General — это тред без `message_thread_id`
(служебный, под GUPPI).

### Операционная заметка: локальный стек памяти (BOB-011)

Гибридной памяти нужен **локальный Ollama** с двумя моделями — эмбеддером и
(опционально) реранкером. Ставится одним скриптом:

```bash
bash scripts/setup-ollama.sh
```

Скрипт ставит **standalone Ollama** (НЕ `brew install ollama`): Homebrew-формула
тянет `python@3.14` как зависимость и может сломать toolchain проекта, поэтому
бинарь Ollama скачивается напрямую (релизный `.tgz`) в `~/.local/ollama` и
добавляется в `PATH` — Python проекта не трогается. Затем скрипт поднимает
`ollama serve` и делает `pull` эмбеддера (`bge-m3`) и реранкера
(`bge-reranker-v2-m3`, best-effort — финальный тег/подача добиваются по Q1).
Модели переопределяются через env: `EMBED_MODEL=…`, `RERANK_MODEL=…`,
`OLLAMA_DIR=…`. На Linux — `https://ollama.com/install.sh`, дальше с шага pull.

Конфигурация памяти — секции `embeddings.*` (`base_url`, `model` по умолчанию
`bge-m3`, `dim` 1024) и `reranker.*` (`enabled` по умолчанию `false`, `base_url`,
`model`, `top_n`); по умолчанию обе указывают на `http://localhost:11434`. **App
стартует и при выключенном Ollama:** сборка эмбеддера/реранкера сетку не трогает,
а первый недоступный `embed()` мягко деградирует recall на keyword-only (graceful
degradation) — Боб не теряет память, лишь её семантическую половину.

## Тесты

Тесты лежат под `tests/`, повторяя структуру слоёв: `tests/domain/`,
`tests/application/` (включая `authz/`, `runtime/test_retry.py`,
`test_capability_registry.py`, `test_tool_loop.py`,
`capabilities/test_progress_announcer.py` (по-имени решение + живая генерация
реплики из `query`/`topic` на обоих путях + декоративное глотание сбоя +
🔴 ноль скриптованности: сбой/пусто/нет генератора → тишина, а удалённые
символы `WEB_SEARCH_PROGRESS_PHRASES`/`DEFAULT_PROGRESS_PHRASES`/`rng` больше
не импортируются, BOB-060),
`test_recall_memory_capability.py`), `tests/infrastructure/` (включая
`telegram/test_gateway_authz.py`, `telegram/test_rich.py`,
`persistence/test_allowlist_store.py`). Мульти-бот шов покрыт
`telegram/test_multibot.py` (BotRegistry, кросс-бот дедуп, роутер, изоляция,
topic-scope), `telegram/test_multibot_hardening.py`, `telegram/test_guppi.py`
(reject + owner-команды) и `telegram/test_multibot_guppi.py` (роутер ↔ GUPPI),
плюс two-bot e2e `telegram/test_e2e_two_bot.py`. Сверху — end-to-end
(`tests/test_e2e_flow.py`, `tests/test_e2e_integration.py`), сборка приложения
(`tests/test_app.py`, `tests/test_app_authz.py`) и приёмочные сценарии US-1..US-4
(`tests/test_acceptance_memory.py`, `tests/test_acceptance_reasoning.py`). Граница
слоёв проверяется `tests/application/test_layering.py`.

Проактивный drive-движок (BOB-010 Ф1) покрыт по слоям: домен —
`tests/domain/proactivity/` (`test_urge.py`, `test_urge_monotonicity.py`,
`test_social_energy.py`, `test_governance.py`, `test_decision.py`,
`test_store_port.py`); приложение — `tests/application/proactivity/`
(`test_engine.py`, `test_tick.py`, `test_record_owner_activity.py`); инфраструктура —
`tests/infrastructure/persistence/test_proactivity_store.py`,
`tests/infrastructure/persistence/test_proactivity_sources.py` и
`tests/infrastructure/telegram/test_guppi_proactivity.py` (`/quiet`/`/wake`); плюс
сквозной приёмочный `tests/test_e2e_proactivity.py` (US-1 порыв, US-2 owner-контроль
и дешевизна).

Язык персоны, grounding и персист проактива (BOB-012) покрыты:
`tests/domain/personality/test_language.py` (директива `language_directive`,
`DEFAULT_LANGUAGE=ru`); `tests/infrastructure/config/test_loader.py`
(`runtime.language` по умолчанию `ru`); `tests/application/usecases/test_heartbeat.py`
(директива языка в промптах монолога и рефлексии); `tests/application/proactivity/test_engine.py`
(директива языка в гейте и компоновке, grounding компоновки в реально вспомненной
памяти, персист проактива как эпизод `event_type=proactive`, отсутствие персиста на
SKIP).

Гибридная память (BOB-011 Ф1) покрыта по слоям: домен — порты `Embedder`/`Reranker`
в `tests/domain/test_ports.py`; приложение — агентный навык
`tests/application/test_search_memory_capability.py`; инфраструктура —
`tests/infrastructure/llm/test_ollama_embedder.py` (+ `_hardening`),
`test_embedder_factory.py`, `test_ollama_reranker.py` (+ `_hardening`),
`test_reranker_factory.py`, `tests/infrastructure/persistence/test_vector_store.py`
(+ `_hardening`) и `test_hybrid_recall.py` (RRF, keyword-фоллбэк, аддитивный реранк).
Эмбеддер/реранкер тестируются на фейках, без сети в CI. Сверху — приёмочный
`tests/test_acceptance_memory.py` (US-1/2/3) и e2e `tests/test_e2e_memory_hybrid.py`.

Глубина личности (BOB-013) покрыта по слоям. Ф1 Negotiation-врезка: домен —
`tests/domain/personality/test_negotiation.py` (`decide` по зонам/порогам),
`test_zone_classifier.py` (логистика → `USER_DOMAIN`, сильный вкус → `BOB_PERSONAL`,
нейтраль → `SHARED`), `test_taste.py` (`conviction_for`: ось найдена/не найдена);
приложение — `tests/application/usecases/test_handle_message.py` (зона+conviction →
директива стойки в промпте, тёплый тон сохранён, нейтраль → путь без директивы).
Ф2 само-эволюция: домен — `test_taste_evolution.py` (`reinforce`: усиление, затухание
`(1−conviction)`, границы), `test_soul.py` (`with_taste`/`with_baseline`/
`with_phantoms`, `experience_count++`); приложение — `test_apply_reflection.py`
(сигнал → ось изменилась; гейт релевантности → no-op), `test_reflection_parser.py`
(полярность + совпадение темы), `tests/application/usecases/test_heartbeat.py`
(эволюция в `ReflectTick`, идемпотентность двойного прогона, персист `taste_profile`).

Эмоциональная глубина (BOB-020) покрыта по слоям. Домен —
`tests/domain/personality/test_voice.py` (`tone_directive`: off-day-бэнд по
порогу, тёплый тон в норме, не грубит), `test_mood_taste.py` (`modulate` ≤1 шаг,
насыщение концов, `NEUTRAL` без выдумки антипатии, `experiment_bias` в `[0, 1]`,
оси не мутируют), `test_fascination.py` (`aged` полураспад, `has_faded` по floor,
границы интенсивности), `test_phantom_evolution.py` (`evolve_phantoms`: grounded-
проступание, медленность по seeded-RNG, бэнд `max_count` с затуханием старого,
идемпотентность), `test_soul.py` (`with_phantoms`). Приложение —
`test_evolve_fascination.py` (grounded Tier-0-пик + эвристик-фоллбэк, сдвиг только
при выгорании, no-op без материала, идемпотентность), `test_fascination_sources.py`
(`RepoFascinationGrounding` + `StoreFascinationReader`), `test_evolve_phantoms.py`
(grounded-кандидат → членство, персист `phantom_prefs`, no-op без изменения) и
`tests/application/usecases/test_heartbeat.py` (оба шага на reflect-тике).
Инфраструктура — `tests/infrastructure/persistence/test_fascination_store.py`
(per-persona round-trip, `None` для неувиденной персоны).

Фикс дословного самоповтора (BOB-022) покрыт по слоям. Инфраструктура —
`tests/infrastructure/llm/test_openai_compat.py` (`temperature`/`top_p` попадают в
payload на всех путях; ненастроенный провайдер их не шлёт) и
`tests/infrastructure/llm/test_factory.py` (`build_tier_providers` прокидывает
per-tier температуры), плюс `tests/infrastructure/config/test_loader.py`
(`tier0_temperature`/`tier1_temperature`-дефолты + env-override). Домен —
`tests/domain/personality/test_conversation.py` (`is_user_repeat`: точное совпадение
после нормализации, пустой ввод → не повтор, отсутствие совпадения → `False`) и
`tests/domain/personality/test_voice.py` (`user_repeat_directive`). Приложение —
`tests/application/usecases/test_handle_message.py` (повтор пользователя → директива в
промпте; анти-повтор-страж регенерирует один раз при дословном дубле ответа Боба).

Окно анти-повтора ответа и грундинг/дедуп рефлексии (BOB-026) покрыты по слоям. Домен
— `tests/domain/personality/test_conversation.py` (`is_bob_repeat`: verbatim после
нормализации, near-verbatim по порогу сходства, окно ловит повтор «через ход», пустой
кандидат → не повтор; `RepeatThresholds`-валидация) и
`tests/domain/personality/test_reflection.py` (`build_reflection_prompt`: грундинг
эпизодами и тоном настроения, генерик-промпт без контекста). Приложение —
`tests/application/usecases/test_handle_message.py` (страж сверяет с окном последних N,
кейс «отказ → другой ход → тот же отказ» регенерирует) и
`tests/application/usecases/test_heartbeat.py` (грундинг рефлексии, дедуп near-дубля →
регенерация → skip, over-fetch окна). Конфигурация — `tests/test_repeat_config.py`
(`repeat.window`/`repeat.similarity_threshold`-дефолты + override).

Фраза-тик-страж (BOB-036) покрыт по слоям. Домен —
`tests/domain/personality/test_conversation.py` (`is_phrase_tic`: закрывашка, рекуррентная
через окно, → тик; одноразовое переиспользование и короткая фраза ниже `tic_min_words` → не
тик; пустой кандидат → не тик; `RepeatThresholds`-валидация `tic_min_words`/`tic_min_occurrences`).
Конфигурация — `tests/test_repeat_config.py` (`repeat.tic_min_words`/`repeat.tic_min_occurrences`-
дефолты + override).

Кросс-сессионный анти-тик (BOB-061) покрыт по слоям. Домен —
`tests/domain/personality/test_conversation.py` (`closer_text` извлекает финальную
закрывашку; `is_same_closer_motif` кластеризует лексические варианты и **не** сцепляет разные
концовки на пороге `motif_similarity_threshold`; `is_recurring_closer_tic` над персист∪окно →
тик при `min_occurrences`, живой отдельный финал → не тик; `RepeatThresholds`-валидация
`tic_lookback`/`motif_similarity_threshold`). Персист —
`tests/infrastructure/persistence/test_closer_log_store.py` (`SqliteCloserLog`: append игнорит
пустой closer, кэп-обрезка кольца, `recent(k)` most-recent-first). Провязка —
`tests/application/usecases/test_handle_message.py` (кросс-сессионный тик пойман мягким
нуджем + стрип эталона; **нет тика → контекст без изменений** и живость цела; сбой персиста не
роняет ход; семя-закрывашка отсутствует в `_ANTI_BAIT`/`_VARIABLE_FORM`). Конфигурация —
`tests/test_repeat_config.py` (`repeat.tic_lookback`/`repeat.motif_similarity_threshold`-дефолты
+ override).

Адресность (BOB-023) покрыта по слоям. Домен —
`tests/domain/personality/test_addressivity.py` (`classify_addressivity`:
mention/reply-на-Боба/имя-обращение → `DIRECTED_TO_BOB`, reply на чужое →
`DIRECTED_TO_OTHER`, иначе `AMBIENT`; `others_present`: 1:1 → `False`, третий →
`True`) и `test_addressivity_policy.py` (`decide_response`: к Бобу всегда `ENGAGE`,
к другому `SILENT` с редким seeded-вклиниванием по порогу, ambient → 1:1 `ENGAGE` /
с другими `SILENT`/`REACT`/редкий `ENGAGE`). Инфраструктура —
`tests/infrastructure/telegram/test_gateway.py` (извлечение `reply_to_sender_id`,
скан `entities` на @mention/text_mention Боба против `BotIdentitySignals`,
graceful degrade без идентичности) и `tests/infrastructure/telegram/test_multibot.py`
(`resolve_bot_identities` через `get_me` → `set_bob_identity`, `bob_user_id`-шов).
Устойчивый старт (BOB-059) покрыт `tests/infrastructure/telegram/test_multibot_startup.py`:
`TelegramNetworkError` на всех попытках → warn+return без падения
(`test_persistent_network_error_does_not_crash_startup`), транзиентный блип
переживается ретраем и идентичность резолвится (`test_transient_blip_is_retried_then_resolves`),
успех с первой попытки без sleep (`test_success_on_first_try_sets_identity_without_sleeping`),
не-сетевой баг не проглатывается (`test_non_network_exception_is_not_swallowed`),
каждый сетевой класс деградации грациозно (параметризованный
`test_each_network_degradation_class_warns_and_returns`) и gateway остаётся
поллящим после устойчивого флапа (`test_gateway_stays_pollable_after_persistent_flap`).
Приложение — `tests/application/usecases/test_handle_message.py`
(`_decide_addressivity` как гейт хода: `SILENT` → ранний выход, `REACT` → путь
`REACT_ONLY`, `ENGAGE` → обычная компоновка; непровязанный `bob_user_id_source` →
поведение как до BOB-023).

Самоинтроспекция (BOB-017, фаза A; код↔«почему» BOB-038) покрыта по слоям. Домен —
`tests/domain/introspection/test_privacy_guard.py` (приват-инвариант: ALLOW
`src`/`tests`/`docs`, DENY `data/soul`/`bob.db`/`.env`/`config`, traversal за репо;
`sanitize` вырезает секрето-подобное) и `test_code_history.py` (чистые парсеры
`parse_bead_refs`/`commits_mentioning`/`feature_doc_dir`). Приложение —
`tests/application/capabilities/test_inspect_architecture.py`,
`test_read_code.py` (маршрутизация путь↔поиск), `test_list_work.py` (dispatch,
компактный рендер, честный «ничего не нашёл» на пустом, US-5) и `test_code_rationale.py`
(сшивка код→git→беады→доки→граф, честное «не зафиксирована», деградация источников).
Инфраструктура —
`tests/infrastructure/introspection/test_subprocess_introspector.py` (фикс-allowlist
read-подкоманд, отказ на флаг/неизвестный бинарь, таймаут, обрезка; `read_file`
через guard + realpath-containment против symlink-обхода) и `test_git_history.py`
(фикс-формы `git log`, отказ на путь-инъекцию/чужую подкоманду/флаг). Конфигурация —
`tests/test_introspection_config.py` (`introspection.*`-дефолты + override).

Защитный механизм CI (BOB-009): `pytest-timeout` задаёт дефолтный пер-тестовый
таймаут (`timeout=60`, `timeout_method="thread"` в `pyproject.toml`), чтобы будущий
busy-loop (например, в keepalive typing-индикатора с неинъецированным `sleep`) падал
по таймауту, а не вешал прогон.
