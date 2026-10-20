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
импортирует эти сторы, а `proactivity_sources` тянет из `bob.kernel.ports` только
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
  rule_announcement.py # layer=domain         — стоит ли говорить: вердикт + кап попыток
  rule_voice.py       # layer=domain          — голос Боба на предложении поправить себя
  restart_voice.py    # layer=domain          — голос Боба на рестарте: «ухожу обновиться» / «вернулся»
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
    announce_restart.py #                      — AnnounceRestart (уход на обновление / возвращение, с таймаутом)
    self_improvement_sources.py — ActiveRulesReader (read-сейм APPROVED-правил для применения)
  adapters/           # layer=infrastructure
    proactivity_store.py     — SqliteProactivityStore (per-persona proactivity_state)
    goal_store.py            — SqliteGoalStore (per-persona goal/task граф)
    self_improvement_store.py — SqliteSelfImprovementStore (per-persona improvement_rule)
    restart_marker_store.py  — KvRestartMarkerStore (маркер апдейт-остановки + epoch в kv)
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
`RuleModulators` (значение живёт в `src/bob/kernel/modulators.py`, BOB-113), который
применяет `handle_message`.

`proposal_defect(rule, *, max_magnitude)` → `ProposalDefect | None` (BOB-096) — чистая
ПРИЧИНА, по которой предложение нельзя вынести владельцу, и единственный источник истины
о пригодности: `is_actionable_proposal` — ровно «изъяна нет», поэтому вердикт и его
объяснение не могут разойтись. Два изъяна, и они РАЗНЫЕ:

- `NOTHING_TO_APPROVE` — пустое `observation`, пустая `adjustment` или неположительный
  наклон: мусорный вывод модели, который не спасёт никакая настройка. Живой повод —
  правило с наблюдением-тавтологией, ПУСТОЙ поправкой и величиной `0.0`, доехавшее до
  владельца вопросом «включить?», на который нельзя ответить осмысленно;
- `ABOVE_CEILING` — одобрять ЕСТЬ ЧТО, но запрошенная величина выше конфигурного потолка
  (`self_improvement.max_magnitude`, граница включительна): применение урезало бы её
  (`clamp_magnitude`), то есть owner одобрял бы не то число, которое видит.

🔴 Пустота сильнее потолка (пустое предложение сверх потолка называется пустым: поднятие
потолка его не спасёт). Различать обязательно: в живой базе владельца из четырёх
отклонённых предложений мусор — ОДНО, у трёх остальных поправка осмысленная (47–74
символа). Одна метка на оба случая назвала бы содержательное предложение мусором и отняла
бы у владельца настоящее решение — поднять потолок или отклонить осознанно.

### Доставка предложения (чистый домен, `rule_announcement.py`)

Отдельная от `RuleState` ось (BOB-096 срез 1): «про это правило ещё говорить — и
услышал ли его owner?». Правило остаётся `PROPOSED`, пока owner не ответил, вне
зависимости от того, дошла ли реплика, поэтому доставка живёт в двух полях
`ImprovementRule` (`announced` / `announce_attempts`) и в вердиктах над ними —
`AnnounceStatus` (`PENDING` / `DELIVERED` / `UNDELIVERED` / `NOT_ACTIONABLE`),
`announce_status`, `next_to_announce` (какое ОДНО правило проговаривается сейчас: самое
старое `PROPOSED` в статусе `PENDING`, тай-брейк по `id`), `is_undelivered_proposal` (метка
«не доставлено») и `unactionable_reason` — ПОЧЕМУ Боб молчит о живом предложении
(`ProposalDefect | None`, `/rules` разводит это на две разные метки, см. ниже).

Кап — `MAX_ANNOUNCE_ATTEMPTS = 3`: reflect-тик идёт раз в 5 минут, значит это первая
попытка плюс два повтора в пределах примерно четверти часа. Моргнувшая сеть в это окно
укладывается, оглохший транспорт — нет, и Боб замолкает вместо бесконечного повтора.
🔴 **Кап — КОНСТАНТА модуля, а не ключ конфигурации.** Ключа
`self_improvement.max_announce_attempts` не существует, а параметр `max_attempts` у
доменных функций и у `AnnounceProposedRules` — тестовый шов (проверить границу, не
переписывая константу), не ручка владельца. Сказано прямо, потому что ключ, который
выглядит настройкой, а кодом не читается вовсе, — ровно тот дефект, что чинился рядом в
этом же эпике (`detector_tier`). Попытка засчитывается ДО отправки, поэтому кап
держится даже если процесс умрёт посреди отправки. Обратная сторона названа как
ограничение, а не как дефект: смерть процесса МЕЖДУ успешной отправкой и пометкой даёт
владельцу повтор — осознанный at-least-once в пределах тех же трёх попыток.

🔴 **Вердикт «есть что одобрять» спрашивается и на ВЫХОДЕ, а не только при рождении
правила** (BOB-096, фикс ревью). Поэтому у `announce_status` / `next_to_announce` /
`is_undelivered_proposal` `max_magnitude` — ОБЯЗАТЕЛЬНЫЙ параметр без дефолта: потолок
приезжает из конфига одним чтением (`_self_improvement_max_magnitude`) и раздаётся всем,
кто судит о правиле, — детектору, `DetectPatterns`, `AnnounceProposedRules` и списку
`/rules` у GUPPI. Порядок вердиктов: сперва содержание (`NOT_ACTIONABLE` сильнее любой
бухгалтерии отправки), потом доставка. Отклонённое правило не удаляется и НЕ помечается
проговорённым: оно остаётся `PROPOSED`, попытки на него не тратятся, и владелец видит его
в `/rules` названным честно — решает он.

🔴 **Названным ИМЕННО ТАК, как есть.** `/rules` показывает три разные пометки, потому что
это три разные новости: `· не доставлено` (пробовали, не дошло), `· нечего одобрять`
(мусор) и `· просит 0.7 при потолке 0.3` (содержание есть, не хватает разрешения на
величину). Числа в последней — не украшение: ровно из них владелец принимает решение
(поднять потолок или отклонить осознанно), и без них метка была бы приговором вместо
информации. Слова принадлежат GUPPI, причина — домену (`unactionable_reason`).

🔴 **Что этим исправлено (наблюдалось вживую шесть дней, 6–12 августа 2026).** Пометка
«проговорено» была `set` в памяти процесса и ставилась ПОСЛЕ успешной отправки, а сбой
уходил в `return` до неё. При битой сети предложение уходило owner'у на КАЖДОМ
reflect-тике, а каждый перезапуск проговаривал заново ВСЕ `PROPOSED`-правила. Теперь
пометка живёт в строке правила (миграция — guarded ALTER, идемпотентна, без бэкфилла:
правило, записанное до фикса, проговаривается ОДИН раз и умолкает).

🔴 **И что чуть не осталось незамеченным.** Отбраковка вырожденных предложений (срез 2)
стояла только на РОЖДЕНИИ правила, а в базе владельца лежат пять `PROPOSED`-правил,
родившихся раньше неё; годно по вердикту — одно. Первым уезжала как раз пустая поправка,
и новый живой голос озвучивал её как нормальное предложение («Хочу чуть поправить тон.
Попробуем?»): форму починили, пустоту спрятали — это ХУЖЕ исходного дефекта, потому что
брак перестал быть виден. Отсюда вердикт на доставке: отбраковка на рождении лечит только
будущее, а владелец живёт с наследством.

### Голос предложения (чистый домен, `rule_voice.py`)

Как это ЗВУЧИТ, когда Боб предлагает поправить самого себя (BOB-096 срез 5). Жалоба
owner'а была про конструкцию, а не про формулировку: реплика собиралась шаблоном с тремя
слотами, куда ДОСЛОВНО подставлялся вывод детектора, — «Заметил за собой: Боб замечает,
что его поведение часто повторяется**..** Предлагаю: **.** Включить? (/rule approve
rule-…)». Отсюда все швы разом: третье лицо о себе (так его назвала модель), двойная
точка от пустого слота, идентификатор внутри фразы.

Лечение — то же разделение ролей, что в `social/permission/request_voice.py`: вердикт
детектора остаётся ВНУТРИ и лишь ВЫБИРАЕТ готовые слова Боба. `proposal_speech(lever,
magnitude)` — что Боб говорит (наблюдение от первого лица + намерение + вопрос):
`Lever` выбирает формулировку, `magnitude` — полосу величины («чуть» < 0.15 ≤ «заметно»
< 0.5 ≤ «сильно»). Сырой текст детектора (`observation` / `adjustment` / `evidence`)
билдер НЕ ПРИНИМАЕТ, поэтому попасть в реплику не может; пустых слотов и двойной
пунктуации нет по конструкции — фраза склеена из непустых констант.
`proposal_message(…, rule_id)` добавляет служебную сноску отдельной строкой.

🔴 **Что эта конструкция НЕ даёт.** Пустой слот и третье лицо о себе она исключает по
построению, но не гарантирует, что озвученное совпадёт с тем, что заметил детектор:
слова выбирает РЫЧАГ — грубая ось из пяти значений, — а не само наблюдение. Правило с
рычагом «адресность» и наблюдением «Отсутствие адаптации ответов под конкретного
собеседника» прозвучит как «пропускаю мимо ушей разговоры, в которых мне есть что
сказать», и это другое утверждение о себе. Точный текст наблюдения владелец видит в
`/rules`, поправку — пока нет. Полосы величины (0.15 и 0.5) — тоже константы модуля, с
конфигурным потолком они не связаны: опустив `max_magnitude` до 0.1, владелец получит
«чуть» на всём диапазоне, и слова разойдутся с числом молча.

🔴 **Граница канона внутри одного сообщения** (BOB-090.D, `coding/speaker.py`).
Предложение изменить себя — голос Боба; команда `/rule approve <id>` — механика, и она
уже принадлежит GUPPI (`/rule` и `/rules` обрабатывает `GuppiHandler` своим ботом).
Разводить одно предложение на двух ботов владельцу хуже (два сообщения пришлось бы
сопоставлять глазами) и потребовало бы второго канала в доставке, поэтому сообщение
ОДНО, боту Боба, но идентификатор не произносится: он вынесен голой командой отдельной
строкой. Пустой идентификатор сноской не становится вовсе.

### Голос рестарта (чистый домен, `restart_voice.py`)

Как это ЗВУЧИТ, когда Боба перезапускают по деплою (BOB-094 срез 1). Канон BOB-090.D:
рестарт — это ГОЛОС Боба (его бот по-человечески предупреждает, что обновляется, и
говорит, что вернулся), а НЕ строка деплой-скрипта и не системный нотис GUPPI. По образцу
`rule_voice`: не шаблон со слотами, а веер готовых человеческих реплик от первого лица, из
которого выбор лишь ВЫБИРАЕТ. `restart_voice(moment, marker)` — `RestartMoment.LEAVING`
(«ухожу обновиться, скоро вернусь») / `RestartMoment.RETURNED` («вернулся, обновился»);
`marker` детерминированно выбирает одну реплику из веера по устойчивому хешу SHA-256
(`random`/время в этом окружении запрещены и всё равно сделали бы реплику
невоспроизводимой). Тотально: любой маркер, включая пустой, даёт валидную непустую
реплику.

**Оркестрация** — `usecases/announce_restart.py::AnnounceRestart` (application): решает
КОГДА и КУДА говорить, но не подбирает слова. `announce_leaving()` зовётся в
graceful-shutdown ДО закрытия транспорта — предупреждает owner'а И группу (решение
owner'а) и кладёт маркер апдейт-остановки в `kv`. 🔴 Отправка ограничена ТАЙМАУТОМ
(`asyncio.wait_for`): сеть легла → реплика молча не уходит, но завершение НЕ блокируется
(`systemctl restart` шлёт SIGTERM, окно короткое). Маркер ставится ДАЖЕ при неудачной
отправке. `announce_returned()` зовётся на старте: говорит «вернулся» ТОЛЬКО когда маркер
есть, и КОНСУМИТ его (одно возвращение на один апдейт); упал сам (маркера нет) → молчит,
притворяться апдейтом нельзя. Порты `RestartNotifier` (owner-DM + группа) и
`RestartMarkerStore` (маркер + растущий epoch) — за инфраструктурой:
`infrastructure/telegram/restart_notifier.py` (бот Боба) и `adapters/restart_marker_store.py`
(kv). За флагом `runtime.restart_notice` (default OFF → хуки не собираются → lifecycle
байт-в-байт).

### Use-case'ы (application)

`ProactivityEngine` (`usecases/engine.py`) — оркестратор, превращающий drive-модель
в реальное сообщение, cheapest-first (большинство тиков не делает ничего и НОЛЬ
LLM-вызовов): загрузить `ProactivityState` → восстановить `SocialEnergy` за тишину
→ **решить** через `ProactiveDecider` (по умолчанию молчать) → на fire дешёвый
Tier-0 gate «есть ли что сказать?» (склонен к SKIP) → на non-skip сначала recall
реальной памяти, затем composе и пост в топик Боба. `ProactiveTick`
(`usecases/tick.py`) — heartbeat-сиблинг reflect-тиков, гонит движок на ~30s
кадэнсе (дёшево, LLM только на редком fire).

🔴 **Share-of-voice throttle (BOB-066 Срез W.1).** `ProactivityEngine.__init__` получил
`share_ceiling` (опц., за флагом `presence.rhythm.enabled`, OFF по умолчанию → `None`):
проактивный бардж домножается на ту же долю эфира, что и реактивный (ОДИН
`ShareOfVoiceGate` на per-chat окно). Throttle стоит ДО Tier-0 gate, поэтому
задавленный порыв тратит НОЛЬ LLM-вызовов. `share_ceiling=None` → бардж свободен
(`_admits_proactive_barge` → True), поведение байт-в-байт.

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
`DetectPatterns` отбраковывает вырожденных кандидатов (`is_actionable_proposal` с
конфигурным потолком), дедуплицирует остальных против существующих правил, режет по
`max_active_rules` и сохраняет новых в `PROPOSED` — только предлагает, никогда не
применяет. Отбраковка стоит ПЕРЕД дедупом и лимитом: мусорный кандидат не должен ни
блокировать содержательный по рычагу, ни съедать бюджет живых правил.

🔴 Два ключа конфига, которые здесь перестали быть обещаниями (BOB-096 срез 2):
`self_improvement.detector_tier` теперь ЧИТАЕТСЯ и определяет тир, на котором детектор
рассуждает (до этого ключ лежал в `config/bob.yaml` без единого читателя, а детектор
строился без тира вовсе — §0.3 п.10), а `self_improvement.max_magnitude` уезжает В
СИСТЕМНЫЙ ПРОМПТ модели (`_system_prompt(cap)`). Второе обязательно: не назвав модели
диапазон, отбраковка «сверх потолка» стала бы тихим выключателем самоулучшения — при
потолке `0.3` модель просила бы привычные `0.5`, и все её предложения гибли бы молча.

🔴 Отдельно от тира — КТО вправе думать за этой дверью. `DETECT_PATTERNS` размечена как
«голос, который остаётся» (BOB-096.4), поэтому аварийный локальный дублёр к ней не
допускается: при отвале облака предложение не рождается ВООБЩЕ, вместо того чтобы
родиться чужим голосом. Именно так и появилось живое правило-пустышка в ночь 6 августа
2026 — тир детектора был штатным, но Tier-1 отвалился, и правило сочинил дублёр.
Ограничение этого решения названо прямо: в живой конфигурации оба облачных тира стоят
на одном хосте, поэтому его падение оставляет самоулучшение молчащим до восстановления
связи. Разметка двери и вердикт живут в `application/router` (см. SPEC роутера).

`AnnounceProposedRules` (`usecases/announce_rules.py`) — Боб тактично проговаривает
owner'у ОДНО свежее `PROPOSED`-правило за раз СВОИМИ словами (текст целиком принадлежит
доменному `rule_voice`, см. ниже), выбирая кандидата доменным `next_to_announce` и
помечая его в ХРАНИЛИЩЕ
(`record_announce_attempt` до отправки, `mark_announced` после успеха), поэтому
проговорённое не повторяется ни на следующем тике, ни после перезапуска процесса.
Кандидат обязан пройти вердикт «есть что одобрять» — потолок величины приезжает в
use-case из конфига (обязательный `max_magnitude`), поэтому вырожденное правило,
лежащее в базе с прошлых версий, владельцу не проговаривается вовсе.
Best-effort: сбой гейтвея не валит тик и НЕ превращается в вечный повтор — попытки
капятся, после исчерпания правило видно владельцу в `/rules` как недоставленное;
unwired — no-op.

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
- `proactivity → memory.entities` (движок читает `episodic_log`);
- `proactivity.usecases → personality.state` / `personality.ports` (типы `PersonalityState` и
  `CurrentFascinationReader` для движка и `PursueGoals`; до BOB-113 тянулись вверх из
  `application/usecases/handle_message`);
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
`urge_to_probability`, `SocialEnergy`, `ProactivityState`. Канонический импорт портов —
`from bob.proactivity.ports import ProactivityStore`; транзитный ports-шим
`bob.domain.ports` удалён (BOB-062.8).

Ключевые точки входа:
- Drive-core: `urge.UrgeModel`, `governance.Governance`, `social_energy.SocialEnergy`,
  `decision.ProactiveDecider` / `urge_to_probability`, `state.ProactivityState`.
- Goal Engine: `goals.entities` (`Goal`, `Task`, `GoalOrigin`), `goals.state`
  (`GoalState`, `TaskState`, `can_transition`), `goals.graph`
  (`GoalGraph`, `ready_tasks`, `next_safe_task`, `blocked_reason`).
- Самоулучшение: `self_improvement` (`ImprovementRule`, `Lever`, `RuleState`,
  `active_rules`, `build_modulators`, `RuleModulators`, `is_actionable_proposal`,
  `proposal_defect`, `ProposalDefect`, `MAGNITUDE_RANGE_TOP`).
- Доставка предложения: `rule_announcement` (`AnnounceStatus`, `announce_status`,
  `next_to_announce`, `is_undelivered_proposal`, `unactionable_reason`,
  `MAX_ANNOUNCE_ATTEMPTS`).
- Голос предложения: `rule_voice` (`proposal_speech`, `proposal_message`).
- Голос рестарта: `restart_voice` (`restart_voice`, `RestartMoment`).
- Use-case'ы: `usecases.engine.ProactivityEngine`, `usecases.tick.ProactiveTick`,
  `usecases.record_owner_activity.RecordOwnerActivity`, `usecases.plan_goal`
  (`LlmPlanner`, `PlanGoal`), `usecases.pursue_goals.PursueGoalsTick`,
  `usecases.detect_patterns` (`LlmPatternDetector`, `DetectPatterns`),
  `usecases.announce_rules.AnnounceProposedRules`,
  `usecases.announce_restart.AnnounceRestart` (порты `RestartNotifier`,
  `RestartMarkerStore`),
  `usecases.self_improvement_sources.ActiveRulesReader`.
- Адаптеры: `SqliteProactivityStore`, `SqliteGoalStore`,
  `SqliteSelfImprovementStore`, `KvRestartMarkerStore`, `RepoProactivitySources`.

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
- Доставка предложения: `tests/domain/proactivity/test_rule_announcement.py` (четыре
  статуса, граница капа, граница потолка, выбор кандидата, причина молчания) и
  `tests/infrastructure/persistence/test_announce_rules_durability.py` — те же две
  проверки на НАСТОЯЩЕМ SQLite («перезапуск» = закрыть и открыть базу), потому что тест
  на фейке доказывает контракт фейка. Потолок из конфига до обоих владельческих концов
  (реплика Боба и список `/rules`) —
  `tests/runtime/wiring/test_self_improvement_ceiling.py`, тир и потолок до детектора —
  `tests/runtime/wiring/test_self_improvement_detector.py`.
- Живая документация поведения (BDD): `tests/acceptance/features/rule_proposal.feature`
  — двадцать один сценарий на настоящей сборке, настоящей SQLite и настоящей команде
  `/rules` (в том числе «наследство»: отклонённое правило из базы владельцу не
  проговаривается, но видно ему с НАЗВАННОЙ причиной — мусор отдельно, превышение
  потолка отдельно и с числами). Отвал облака у этой двери —
  `tests/acceptance/features/voice_that_stays.feature` (предложение не рождается вовсе)
  и `tests/test_the_understudy_never_speaks_for_bob.py`, где ночь 6 августа
  воспроизведена на настоящей проводке с живым локальным дублёром.
- Голос предложения: `tests/domain/proactivity/test_rule_voice.py` (первое лицо, свои
  слова на каждый рычаг, полосы величины, невозможность пустого слота, сноска отдельно
  от речи).
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
