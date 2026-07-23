<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль proactivity — «фоновая жизнь Боба»

Проактивность Боба как единая вертикаль: чистая drive-модель («тяга заговорить
первым» — urge из настроения, тоски, свежести последней рефлексии и суточного
ритма), governance-тормоз из шести вето поверх неё, свой Goal Engine (Боб ставит
и продвигает собственные цели под двойным гейтом owner'а) и метакогнитивное
самоулучшение (Боб замечает поведенческие паттерны за собой и предлагает
человекочитаемые правила). Engine пуст по умолчанию: подавляющее большинство
тиков решает молчать и не тратит ни одного LLM-вызова.

Это третий и самый крупный **вертикальный** модуль domain-first раскладки
(BOB-062.3, срез 3/8 эпика BOB-062): бизнес-логика способности собрана в одном
месте `src/bob/proactivity/`, а не размазана по слоям `domain/proactivity/` +
`domain/goals/` + `domain/personality/self_improvement.py` +
`application/proactivity/` + `application/usecases/` + `infrastructure/persistence/`.
Модуль охватывает три слоя **внутри** одного bounded-context, поэтому в графе он
несёт не-слойный тег `module-vertical` (правило `architecture-layers` его рёбра
пропускает), а внутреннюю и внешнюю дисциплину держат path-glob
`forbid_import`-правила в `.beadloom/_graph/rules.yml`.

## 🔴 Три решения по принадлежности

1. **`self_improvement.py` забран в proactivity** из `domain/personality/`. Это
   метакогниция над собственным поведением (BOB-028), а не черта личности; модуль
   не импортирует ничего из `bob.*`, поэтому цикла не возникает. Переезд потянул
   смену тега `feature=personality → proactivity` и относящиеся тесты. Стык
   `application/usecases/handle_message → proactivity.self_improvement`
   (read-модуляторы `RuleModulators` / `build_modulators`) — намеренно разрешённое
   ребро: `self_improvement.py` это публичная доменная поверхность proactivity.
2. **`run_genesis.py` остаётся вне proactivity** (не перенесён). По зависимостям
   это first-boot генезис SOUL (тянет `SoulStore` / social + router), а не
   drive/goals. Уедет в срез social (BOB-062.5) или personality (BOB-062.6);
   `GenesisResult` / `RunGenesis` по-прежнему живут в `application/usecases/`.
3. **goals — единый `feature=proactivity`** (структурно подпапка `goals/`), как
   один feature на модуль в эталоне coding / memory.

## 🔴 Отсрочка kernel персистентности (вариант C, до среза .7)

Четыре долговечных стора (`SqliteProactivityStore`, `SqliteGoalStore`,
`SqliteSelfImprovementStore` и live-сеймы `RepoProactivitySources`) переехали в
`adapters/`, но подключение к SQLite получают через **общий kernel
персистентности** — шов `SqliteMemoryRepo.connection()` (как и десяток с лишним
других сторов). Поэтому по решению owner'а (вариант C) `SqliteMemoryRepo`,
`schema.sql` (таблицы `proactivity_state` / `goal` / `task` / `improvement_rule`)
и прочий kernel **остаются в `infrastructure/persistence/`** до среза BOB-062.7
(консолидация инфра-kernel'а).

Направление ребра — наружу: `proactivity → infra kernel` (адаптеры зависят от
kernel'а). Обратной зависимости `kernel → proactivity` НЕТ — `sqlite_repo` не
импортирует эти сторы, а `proactivity_sources` тянет из `bob.domain.ports` только
`Clock` (тип). Единственное разрешённое исходящее рантайм-ребро в чужой домен —
`proactivity → memory.entities` (движок читает `episodic_log` через recall-сейм);
`entities` это публичная поверхность memory, ребро помечено в правилах границ.

## Спецификация

### Раскладка модуля

```
src/bob/proactivity/
  ports.py            # layer=domain          — 5 портов-протоколов способности
  __init__.py         # layer=domain          — фасад (drive-core: UrgeModel, Governance, …)
  urge.py             # layer=domain          — UrgeModel: чистая формула «тяги заговорить»
  governance.py       # layer=domain          — Governance: шесть вето-тормозов
  social_energy.py    # layer=domain          — SocialEnergy: [0,1]-резервуар тяги
  decision.py         # layer=domain          — ProactiveDecider: urge → p → seeded-семпл → вето
  state.py            # layer=domain          — ProactivityState (персист-снимок между тиками)
  self_improvement.py # layer=domain          — 🔴 из personality: модель правил + модуляторы
  goals/              # layer=domain            (когезивная подобласть Goal Engine)
    entities.py       #                        — Goal, Task, GoalOrigin (immutable value-objects)
    state.py          #                        — GoalState / TaskState + предикаты переходов
    graph.py          #                        — GoalGraph + чистые граф-функции готовности
  usecases/           # layer=application
    engine.py         #                        — ProactivityEngine (drive-модель → сообщение)
    tick.py           #                        — ProactiveTick (гонит engine на heartbeat)
    record_owner_activity.py — RecordOwnerActivity (входящее owner-сообщение → state)
    plan_goal.py      #                        — LlmPlanner + PlanGoal (декомпозиция + двойной гейт)
    pursue_goals.py   #                        — PursueGoalsTick (Боб сам продвигает свои цели)
    detect_patterns.py       — LlmPatternDetector + DetectPatterns (метакогнитивный детектор)
    announce_rules.py #                        — AnnounceProposedRules (Боб проговаривает правило)
    self_improvement_sources.py — ActiveRulesReader (read-сейм APPROVED-правил для применения)
  adapters/           # layer=infrastructure
    proactivity_store.py     — SqliteProactivityStore (per-persona proactivity_state)
    goal_store.py            — SqliteGoalStore (per-persona goal/task граф)
    self_improvement_store.py — SqliteSelfImprovementStore (per-persona improvement_rule)
    proactivity_sources.py   — RepoProactivitySources (live read-сеймы salience/window-count)
```

**Остаётся в `infrastructure/persistence/` (shared kernel до .7):**
`sqlite_repo.py` (`SqliteMemoryRepo` + `.connection()`-шов) и `schema.sql`
(включая таблицы proactivity_state / goal / task / improvement_rule).
**Остаётся в `application/usecases/` (переедет в social/personality-срез):**
`run_genesis.py` (`RunGenesis`, `GenesisResult`).

### Drive-модель (чистый домен)

`UrgeModel` (`urge.py`) — чистая формула «тяги заговорить первым»: сводит четыре
именованных, настраиваемых драйва в один `[0, 1]`-скор — **mood** (открытое
возбуждённое настроение поднимает тягу), **longing** (растёт с `silence_seconds`,
сатурирует, чтобы не разгоняться), **salience** (насколько ярка свежая рефлексия)
и **circadian** (базлайн по локальному часу: низко ночью, бимодальные пики утром и
вечером). Детерминированна и без I/O — время суток приходит уже как
clock-производное значение, а не читается здесь.

`SocialEnergy` (`social_energy.py`) — ограниченный `[0, 1]`-резервуар тяги как
value-object: **восстанавливается** во время тишины, **тратится** на проактивное
сообщение и **частично восстанавливается**, когда owner отвечает («ты вернулся»).
Все переходы чистые, elapsed-время инжектит вызыватель — естественный cooldown без
таймера и I/O.

`Governance` (`governance.py`) — чистые потолки, которые **ветируют** проактивное
сообщение (тормоз поверх движка-двигателя). `Governance.allows` даёт единственный
булев ответ по шести вето: **quiet-hours** (жёсткий пол по локальным часам, дефолт
23:00–09:00), **owner-mute** (флаг `/quiet` / `/wake`), **anti-spam** (потолок на
окно), **min-gap** (минимальный интервал между двумя сообщениями),
**owner-cooldown** (пауза после последнего сообщения owner'а) и **sulk** (потолок,
пока Боб обижен, BOB-014; снимается сам по мере восстановления обиды — гарантия
выхода). Governance только блокирует, никогда не поднимает тягу; «now» инжектится
вызывателем, поэтому политика детерминирована.

`ProactiveDecider` (`decision.py`) — сейм, который движок зовёт на тике: выводит
локальный час из инжектированного `Clock`, скорит `UrgeModel`, отображает тягу в
вероятность через монотонную логистику (`urge_to_probability`), тянет один раз из
**инжектированного seeded-RNG** и даёт `Governance` ветировать. Чист при
фиксированных clock и RNG — ни `datetime.now()`, ни глобального `random`, — поэтому
фиксированный seed делает решение полностью воспроизводимым в тестах.

`ProactivityState` (`state.py`) — plain value-object, который `ProactivityStore`
round-trip'ит в хранилище: текущий `SocialEnergy`-резервуар, когда Боб последний
раз говорил проактивно, когда owner последний раз писал, и флаг
`proactivity_enabled` (`/quiet` / `/wake`). Без поведения и I/O.

### Goal Engine (чистый домен, `goals/`)

`Goal` / `Task` (`goals/entities.py`) — immutable `frozen, slots` value-objects.
`Goal` (что и зачем, критерий завершения, состояние, происхождение) и `Task`
(единица работы: описание, зависимости-предшественники `deps`, состояние и флаг
`needs_external_agency` — нужна ли стадия-C: код / внешние инструменты / ФС /
внешние API). `GoalOrigin` различает цель владельца (`OWNER`) и цель, предложенную
Бобом (`BOB_PROPOSED`).

`GoalState` / `TaskState` (`goals/state.py`) — строковые `StrEnum` (значения =
SQLite TEXT-колонки). Разрешённые переходы заданы таблицами; `can_transition` /
`can_transition_task` — чистые предикаты. Жизненный цикл цели: `PROPOSED` (ждёт
owner-апрува) → `APPROVED` (ждёт плана) → `ACTIVE` (план одобрен, тик может
продвигать) ↔ `BLOCKED` → терминальные `DONE` / `CANCELLED`; `PAUSED` — обратимая
остановка owner'ом. **Двойной гейт** (authz-before-autonomy): переход
`PROPOSED → APPROVED` валиден в домене, но ИНИЦИИРУЕТ его только owner-апрув на
уровне use-case; в `ACTIVE` минуя `APPROVED` перейти нельзя.

`GoalGraph` (`goals/graph.py`) — immutable-снимок целей и задач + чистые
детерминированные функции готовности: `ready_tasks` (готовы к авто-продвижению,
ИСКЛЮЧАЯ `needs_external_agency`), `next_safe_task` (следующая безопасная задача по
приоритету, стабильный tie-break по id), `is_goal_complete`, `blocked_reason`,
`external_agency_tasks` (для предложения owner'у). Без I/O и часов, устойчив к
циклам `deps` (не виснет).

### Самоулучшение (чистый домен, `self_improvement.py`, 🔴 из personality)

Метакогнитивный слой (BOB-028): Боб замечает поведенческие паттерны за собой и
формирует человекочитаемое `ImprovementRule` (наблюдение + поправка + рычаг из
жёсткого allowlist + ограниченная `magnitude`). **Граница безопасности по
конструкции:** `Lever` — жёсткий allowlist рычагов, которые правило вправе наклонять
(тон / длина / проактивность / адресность / юмор); у него НАМЕРЕННО НЕТ члена для
authz, гость-инварианта, ядра SOUL или safety-инвариантов автономии, поэтому
правило НЕ способно их представить *по конструкции*. `active_rules` берёт лишь
`APPROVED` (`RuleState`), так что неодобренное правило не влияет на поведение;
`build_modulators` сводит активные правила в нейтральный по умолчанию
`RuleModulators`, который применяет `handle_message`.

### Use-case'ы (application)

`ProactivityEngine` (`usecases/engine.py`) — оркестратор, превращающий drive-модель
в реальное сообщение, cheapest-first (большинство тиков не делает ничего и НОЛЬ
LLM-вызовов): загрузить `ProactivityState` → восстановить `SocialEnergy` за тишину
→ **решить** через `ProactiveDecider` (по умолчанию молчать) → на fire дешёвый
Tier-0 gate «есть ли что сказать?» (склонен к SKIP) → на non-skip сначала recall
реальной памяти, затем composе и пост в топик Боба. `ProactiveTick`
(`usecases/tick.py`) — heartbeat-сиблинг reflect-тиков, гонит движок на ~30s
кадэнсе (дёшево, LLM только на редком fire).

`RecordOwnerActivity` (`usecases/record_owner_activity.py`) — сворачивает входящее
owner-сообщение в состояние проактивности: штампует `last_user_msg_at` (взводит
owner-cooldown вето) и частично восстанавливает `SocialEnergy`. `/quiet`-mute и
`last_spoke_at` сохраняются как есть.

`LlmPlanner` + `PlanGoal` (`usecases/plan_goal.py`) — декомпозиция цели и **двойной
гейт**. `LlmPlanner` (порт `Planner`) просит reasoning-модель (Tier 1) разбить
APPROVED-цель на атомарные `Task` (строгий JSON, устойчивый парсинг), локальные id
ремапятся на `<goal_id>::<n>`, задачи в `TaskState.NEW`. `PlanGoal.run` берёт цель
в `APPROVED` → планировщик → сохраняет задачи → формирует сообщение owner'у; цель
ОСТАЁТСЯ `APPROVED` до явного `approve_plan` (`APPROVED → ACTIVE`). Конфиг
`goals.require_plan_approval` (дефолт `True`); при `False` — одинарный гейт.

`PursueGoalsTick` (`usecases/pursue_goals.py`) — самонаправленный heartbeat-тик
(автономность-стадия B): Боб продвигает СВОИ цели под теми же воротами. Порядок
строгий: сначала гейт (kill-switch `is_pursuit_stopped`, затем `Governance.allows`)
→ выбор `next_safe_task` (домен гарантирует только `APPROVED` / `ACTIVE`, deps
`DONE`, БЕЗ `needs_external_agency`) → исполнение ТОЛЬКО безопасного шага
(`READY → IN_PROGRESS`); внешне-агентные задачи лишь выносятся owner'у как
предложение (стадия-C гейт).

`LlmPatternDetector` + `DetectPatterns` (`usecases/detect_patterns.py`) —
метакогнитивный детектор на редком reflect-кадэнсе. `LlmPatternDetector` (порт
`PatternDetector`) просит LLM по срезу `ImprovementSignals` сформулировать
правила-кандидаты; КАЖДЫЙ жёстко нормализуется доменом (`state` → `PROPOSED`,
`origin` → `BOB_PROPOSED`, `lever` только из allowlist, `magnitude` клампится).
`DetectPatterns` дедуплицирует кандидатов против существующих правил и сохраняет
новых в `PROPOSED` — только предлагает, никогда не применяет.

`AnnounceProposedRules` (`usecases/announce_rules.py`) — Боб тактично проговаривает
owner'у ОДНО свежее `PROPOSED`-правило за раз («Заметил за собой… Предлагаю…
Включить?»), помечает его announced (in-memory, на процесс) и не повторяет.
Best-effort: сбой гейтвея не валит тик; unwired — no-op.

`ActiveRulesReader` (`usecases/self_improvement_sources.py`) — application-адаптер
чтения (реализует `SelfImprovementReader`, read-сейм `HandleMessage`): грузит
правила из `SelfImprovementStore` и возвращает ТОЛЬКО `active_rules` (APPROVED) —
applied-сторона никогда не видит PROPOSED/PAUSED/REJECTED/REMOVED
(authz-before-autonomy держится здесь, ещё до доменного `build_modulators`).
Best-effort: сбой стора → пусто, не исключение.

### Адаптеры (infrastructure)

`SqliteProactivityStore` (`adapters/proactivity_store.py`) реализует порт
`ProactivityStore` над таблицей `proactivity_state` (одна строка на `persona_id` —
Bobiverse-реплики держат свой резервуар и mute-флаг). Поверх порта — инфра-уровневый
`mute_until` (таймерный mute из `/quiet 2h`), живущий только в строке
(`get_mute_until` / `set_mute_until`). `SqliteGoalStore`
(`adapters/goal_store.py`) реализует `GoalStore` над таблицами `goal` / `task`
(`deps` round-trip'ит как JSON-массив, upsert на композитном ключе, атомарные
`update_goal_state` / `update_task_state`). `SqliteSelfImprovementStore`
(`adapters/self_improvement_store.py`) реализует `SelfImprovementStore` над
`improvement_rule` (только owner-апрув двигает `PROPOSED → APPROVED`).
`RepoProactivitySources` (`adapters/proactivity_sources.py`) — live read-сеймы,
которые движок читает на каждом тике прямо из `episodic_log`: **reflection
salience** (свежесть последней рефлексии, линейно затухает) и **proactive window
count** (сколько проактивных эпизодов в анти-спам окне). Весь SQL параметризован
(`?`), подключение — через kernel-шов `.connection()`.

## Инварианты

- **Urge-монотонность:** `urge_to_probability` строго возрастает по тяге; при
  прочих равных большая тяга даёт не меньшую вероятность заговорить. Каждый драйв
  (mood / longing / salience / circadian) сатурирует в `[0, 1]` и не разгоняется.
- **Seeded-RNG детерминизм:** `ProactiveDecider` тянет один раз из инжектированного
  seeded-RNG и выводит час из инжектированного `Clock` — ни `datetime.now()`, ни
  глобального `random`. Фиксированный seed → полностью воспроизводимое решение.
- **Шесть governance-вето:** `Governance.allows` блокирует при любом из quiet-hours
  / owner-mute / anti-spam / min-gap / owner-cooldown / sulk. Governance только
  опускает потолок, никогда не поднимает тягу; sulk снимается сам (гарантия выхода).
- **Двойной гейт целей (authz-before-autonomy):** переход `PROPOSED → APPROVED`
  инициирует только owner-апрув на уровне use-case; самонаправленный тик работает
  ТОЛЬКО с `APPROVED` / `ACTIVE` и никогда не трогает `PROPOSED`. В `ACTIVE` минуя
  `APPROVED` перейти нельзя (цель, затем план — два независимых апрува).
- **Стадия-C изоляция:** `ready_tasks` / `next_safe_task` исключают
  `needs_external_agency`; внешне-агентные задачи лишь предлагаются owner'у, тик
  их не исполняет.
- **Самоулучшение — граница по конструкции:** `Lever` — жёсткий allowlist рычагов
  (тон / длина / проактивность / адресность / юмор); правило не способно наклонить
  authz, гость-инвариант, SOUL или safety-инварианты автономии. Применяются ТОЛЬКО
  `active_rules` (APPROVED); owner-апрув — единственный путь `PROPOSED → APPROVED`.
- **Engine-тишина по умолчанию:** вето или несостоявшийся семпл завершают тик без
  LLM-вызова; подавляющее большинство тиков делает НОЛЬ вызовов.

### Границы модуля (AaC)

Дисциплина держится path-glob `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ vertical modules, расширенными в .2):
- `usecases/` не импортят `adapters/` и чужой `infrastructure/` (только порты;
  адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/`;
- снаружи к `proactivity` — только через фасад/порты (не `usecases/`/`adapters/`
  напрямую);
- модуль не импортит композиционный корень (`app.py`).

Намеренно разрешённые кросс-рёбра (все — на публичную доменную поверхность):
- `handle_message → proactivity.self_improvement` (read-модуляторы);
- `guppi → proactivity.goals.state` / `.self_improvement` / `.state` (UI-рендер
  `/quiet` / `/wake` над доменным состоянием);
- `guppi` и `multibot → proactivity.usecases.plan_goal.PlanGoal` (тип);
- `domain/ports/__init__ → proactivity.ports` (шим re-export 5 портов);
- `proactivity → memory.entities` (движок читает `episodic_log`);
- kernel → proactivity ребра НЕТ (проверено).

## API

<!-- beadloom:track=src/bob/proactivity/ports.py -->

Модуль `src/bob/proactivity/ports.py` (порты-протоколы, только интерфейсы):
- `Planner` — `decompose(goal)` → `Sequence[Task]`: разбить APPROVED-цель на
  атомарные задачи (в `TaskState.NEW`). Реализация — `LlmPlanner` (Tier 1) +
  детерминированный fake в тестах.
- `PatternDetector` — сформулировать правила-кандидаты из `ImprovementSignals` о
  собственном поведении Боба (BOB-028). Реализация — `LlmPatternDetector`.
- `ProactivityStore` — round-trip `ProactivityState` (`load` / `save`).
  Реализация — `SqliteProactivityStore`.
- `GoalStore` — стор графа целей (`load` → `GoalGraph`, `save_goal` / `save_task`,
  `update_goal_state` / `update_task_state`). Реализация — `SqliteGoalStore`.
- `SelfImprovementStore` — стор правил (`load`, `save_rule`, `update_rule_state`).
  Реализация — `SqliteSelfImprovementStore`.

Фасад `src/bob/proactivity/__init__.py` re-export'ит drive-core: `UrgeModel`,
`Governance`, `GovernanceConfig`, `ProactiveHistory`, `ProactiveDecider`,
`urge_to_probability`, `SocialEnergy`, `ProactivityState`. Порты `proactivity`
также re-export'ятся из `bob.domain.ports`, поэтому
`from bob.domain.ports import ProactivityStore` работает как раньше (шим для
потребителей).

Ключевые точки входа:
- Drive-core: `urge.UrgeModel`, `governance.Governance`, `social_energy.SocialEnergy`,
  `decision.ProactiveDecider` / `urge_to_probability`, `state.ProactivityState`.
- Goal Engine: `goals.entities` (`Goal`, `Task`, `GoalOrigin`), `goals.state`
  (`GoalState`, `TaskState`, `can_transition`), `goals.graph`
  (`GoalGraph`, `ready_tasks`, `next_safe_task`, `blocked_reason`).
- Самоулучшение: `self_improvement` (`ImprovementRule`, `Lever`, `RuleState`,
  `active_rules`, `build_modulators`, `RuleModulators`).
- Use-case'ы: `usecases.engine.ProactivityEngine`, `usecases.tick.ProactiveTick`,
  `usecases.record_owner_activity.RecordOwnerActivity`, `usecases.plan_goal`
  (`LlmPlanner`, `PlanGoal`), `usecases.pursue_goals.PursueGoalsTick`,
  `usecases.detect_patterns` (`LlmPatternDetector`, `DetectPatterns`),
  `usecases.announce_rules.AnnounceProposedRules`,
  `usecases.self_improvement_sources.ActiveRulesReader`.
- Адаптеры: `SqliteProactivityStore`, `SqliteGoalStore`,
  `SqliteSelfImprovementStore`, `RepoProactivitySources`.

Композиция (сборка движка, планировщика, детектора и навешивание тиков на
heartbeat) — в композиционном корне `app.py`. Долговечная запись в SQLite идёт
через kernel-шов `SqliteMemoryRepo.connection()` (`infrastructure/persistence/`,
до среза .7).

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Drive-core: `tests/domain/proactivity/test_urge.py`,
  `test_urge_monotonicity.py`, `test_governance.py`, `test_social_energy.py`,
  `test_decision.py`, `test_store_port.py`.
- Goal Engine: `tests/domain/goals/test_state.py`, `test_graph.py`.
- Самоулучшение: `tests/domain/personality/test_self_improvement.py`,
  `test_self_improvement_modulators.py` (переехали вместе с модулем; смена тега
  `feature=personality → proactivity`); `tests/test_self_improvement_config.py`.
- Use-case'ы: `tests/application/proactivity/` (`test_engine.py`, `test_tick.py`,
  `test_record_owner_activity.py`) и `tests/application/usecases/`
  (`test_plan_goal.py`, `test_pursue_goals.py`, `test_detect_patterns.py`,
  `test_announce_rules.py`, `test_self_improvement_sources.py`).
- Адаптеры (тесты остались при kernel'е — плюс варианта C):
  `tests/infrastructure/persistence/test_proactivity_store.py`,
  `test_goal_store.py`, `test_self_improvement_store.py`,
  `test_proactivity_sources.py`.
- Стыки UI: `tests/infrastructure/telegram/test_guppi_goals.py`,
  `test_guppi_proactivity.py`.
- Layer-guard модуля: `tests/proactivity/test_layering.py` (usecases не тянут
  adapters, домен не тянет usecases).
- Приёмка и e2e: `tests/test_e2e_proactivity.py`.
