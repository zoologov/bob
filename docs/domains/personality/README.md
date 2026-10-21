<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль personality — «кто Боб есть»

Характер Боба как единая вертикаль: его *настроение* (пятиосевой аффект Mood), *вкусы*
(TasteEngine и их медленная само-эволюция), стабильный *темперамент* (Disposition — черта-
аттрактор, из которой оптимизм Боба *вытекает*, а не прописан), текущая *увлечённость*
(Fascination и фантомные предпочтения-симфонии), *переговорная стойка* (насколько твёрдо
он держит позицию по зоне и убеждённости), *план выражения* хода (полный ответ против
терсого REACT_ONLY, редкие leak/callback-флаги, form-hint), его *голос* (тон по mood,
директивы стиля), *смысл реакций* на его сообщения (реакция как эмоциональный отклик
характера, не таблица emoji) и его *рефлексия* (заземлённый внутренний монолог + её
реаппрайзал). Это стабильное **ядро** личности: оно отвечает на вопрос «как сказать»
и «кто Боб есть», ничего не зная о том, как ведётся ход.

Это шестой **вертикальный** модуль domain-first раскладки (BOB-062.6a, срез 6/8 эпика
BOB-062): «кто Боб есть» собран в одном месте `src/bob/personality/`, а не размазан по
слоям `domain/personality/` + `application/usecases/{update_mood_from_text,apply_reflection,
reappraise_reflection,evolve_*,fascination_sources}` + persistence-сторы +
`infrastructure/llm/reaction_judge`. Модуль охватывает три слоя **внутри** одного bounded-
context, поэтому в графе он несёт не-слойный тег `module-vertical` (правило
`architecture-layers` его рёбра пропускает), а внутреннюю и внешнюю дисциплину держат
explicit-path `forbid_import`-правила в `.beadloom/_graph/rules.yml` (§ personality VERTICAL
module), сгенерированные `scripts/gen_boundary_rules.py`.

## 🔴 Ключевые решения по границам и принадлежности

1. **personality — стабильное ядро, 0 runtime-зависимостей на conversation/social.**
   В конвейере хода `conversation` решает *если/насколько* отвечать → `personality` решает
   *как сказать*. Правильное направление — `conversation → personality` однонаправленно;
   `personality` НИКОГДА не импортит `conversation` в runtime. Так разорван прежний цикл
   `voice ↔ brevity/engagement` (см. решение 2). Цикл `personality ↔ social` тоже разорван
   (BOB-062.5): `voice.py` больше не импортит `InterlocutorKind` — читает уже-вычисленное
   `kind.value`.
2. **`Verbosity` + `EngagementLevel` — часть вокабуляра выражения personality.** Это грани
   того, *как характер выражается* (рядом с `ExpressionMode` / `FormHint`), поэтому их
   *определения* живут в `personality/expression.py`. Вычисляющая логика (`decide_verbosity`
   / `decide_engagement` + пороги) осталась в `conversation` и теперь ВОЗВРАЩАЕТ эти
   personality-VO. Так `voice → Verbosity/EngagementLevel` — внутри-personality, а
   `conversation → Verbosity/EngagementLevel` — правильное ребро `conversation → personality`.
   🔴 Перенос behavior-preserving: тела функций не менялись, двигались только определения
   enum'ов + импорт-пути (BOB-062.6a .1), тон Боба идентичен.
3. **`negotiation` + `reaction_judgment` живут ЗДЕСЬ.** `negotiation` — стойка/убеждённость
   характера (насколько твёрдо Боб держит позицию). `reaction_judgment` производит `MoodDelta`
   — эмоциональный отклик характера на чужую реакцию, поэтому это personality, а не
   conversation. Классификатор *зоны* хода (`ZoneClassifier` / `TasteZoneClassifier`)
   наоборот — решение хода, он в `conversation`.
4. **`perceive_reaction` ОСТАЁТСЯ в `application/usecases/`.** Восприятие «меня получили» —
   cross-domain use-case над `personality` (mood + reaction-effect) И `social` (relationship
   реактора), поэтому это application-оркестрация, как `handle_message`, а не personality-
   домен. Модуль лишь предоставляет чистое ядро (`reaction_effect`, `reaction_meaning`) и
   Tier-0 адаптер `LlmReactionJudge`; сам сшивающий use-case держится вне вертикали.
5. **Порты живут в `personality/ports.py`** (`MessageReactor` / `ReflectionReader` /
   `FascinationStore` / `NotableReactionStore` / `CurrentFascinationReader`); канонический импорт —
   `from bob.personality.ports import MessageReactor` (транзитный ports-шим
   `bob.domain.ports` удалён, BOB-062.8).

## Спецификация

### Раскладка модуля

```
src/bob/personality/
  ports.py            # layer=domain          — personality-порты (MessageReactor/ReflectionReader/Fascination/NotableReaction/CurrentFascinationReader)
  state.py            # layer=domain          — PersonalityState: живой per-boot снимок SOUL, общий для хода/тиков/проактивности (BOB-113)
  __init__.py         # layer=domain          — фасад модуля
  mood.py             # layer=domain          — Mood (5 осей [-1,1]) + MoodDelta, update/drift/lift, tone()
  disposition.py      # layer=domain          — Disposition (optimism/resilience) — черта-аттрактор (BOB-033)
  taste.py            # layer=domain          — TasteEngine + TasteAxis + Verdict (детерминированные вердикты)
  taste_evolution.py  # layer=domain          — reinforce: медленная само-эволюция вкуса (анти-runaway (1-conviction))
  mood_taste.py       # layer=domain          — modulate/experiment_bias: mood временно окрашивает вердикт (без мутации осей)
  negotiation.py      # layer=domain          — Negotiation + Stance + NegotiationZone (переговорная стойка)
  fascination.py      # layer=domain          — Fascination (topic/intensity/created_at), старение-полураспад, has_faded
  phantom_evolution.py# layer=domain          — evolve_phantoms: медленный дрейф фантомных предпочтений (заземлён)
  expression.py       # layer=domain          — ExpressionMode/FormHint + 🔴 Verbosity/EngagementLevel + decide_expression
  voice.py            # layer=domain          — тон/директивы стиля (tone/brevity/engagement/sulk/relationship-tone + formatting_directive: форматируй под читателя по содержимому, BOB-086)
  language.py         # layer=domain          — language_directive (персона говорит на своём языке)
  profanity.py        # layer=domain          — is_directed_hostility: направленная враждебность vs бытовой мат
  reaction.py         # layer=domain          — reaction_emoji_for(mood): picker emoji из стандартного набора
  reaction_meaning.py # layer=domain          — ReactionContext/ReactionMeaning + порт ReactionJudge (семантика реакции)
  reaction_judgment.py# layer=domain          — чистый Tier-0 wire-протокол реакции (prompt/parser) → MoodDelta
  reaction_effect.py  # layer=domain          — apply_reaction_to_mood/nudge_warmth + NotableReaction (bounded-сдвиги)
  reaction_aloud.py   # layer=domain          — acknowledgment_hint: редкий hint «меня заметили» (BOB-050)
  reflection.py       # layer=domain          — build_reflection_prompt: заземлённый внутренний монолог (анти-«застрявшая пластинка»)
  soul.py             # layer=domain          — SOUL: иммутабельный снимок персистентной личности (with_*)
  absence.py          # layer=domain          — absence_hint: текстура длинной паузы («давно не виделись»)
  room_tone.py        # layer=domain          — 🔴 ВТОРОЙ СЛОЙ: room_tone_directive/room_engagement_bias — настроение комнаты (по значению, float) красит голос и аппетит поверх личного mood, БЕЗ его мутации (BOB-066)
  usecases/           # layer=application
    update_mood_from_text.py —                — UpdateMoodFromText: сигналы текста → MoodDelta (шаг perceive)
    apply_reflection.py      —                — ApplyReflection: рефлексия → само-эволюция вкуса (relevance-гейт)
    reappraise_reflection.py —                — ReappraiseReflection: вероятностный реаппрайзал тёмной мысли (BOB-033)
    reflection_parser.py     —                — HeuristicReflectionParser: детерминированный рефлексия→сигнал
    evolve_fascination.py    —                — EvolveFascination: редкий заземлённый сдвиг увлечённости
    evolve_phantoms.py       —                — EvolvePhantoms: редкий заземлённый сдвиг фантом-предпочтений
    fascination_sources.py   —                — Repo/StoreFascination: live-швы заземления и чтения увлечённости
    mood_perceiver.py        —                — MoodPerceiver: обновить настроение из входящего + план выражения (коллаборатор handle_message, BOB-062.6b)
    grounded_addons.py       —                — GroundedAddons: заземлённые добавки (рефлексия/колбэк/фасцинация), decorative
    voice_composer.py        —                — VoiceComposer: голос + генерация ответа хода
  adapters/           # layer=infrastructure
    reaction_judge.py        —                — LlmReactionJudge (Tier-0 реализация ReactionJudge)
    fascination_store.py     —                — SqliteFascinationStore (per-persona увлечённость)
    notable_reaction_store.py—                — KvNotableReactionStore (последняя «меня заметили»-реакция)
```

**ОСТАЁТСЯ вне personality:** `perceive_reaction.py` (application-оркестратор, решение 4);
зона хода `zone_classifier.py` + порт `ZoneClassifier` (это `conversation`); долговечная
запись сторов идёт через `SqliteMemoryRepo.connection()`-шов общего kernel'а (до среза .7).

### Ядро аффекта, вкуса и темперамента (чистый домен)

`Mood` (`mood.py`) — аффективное состояние Боба как ограниченный пятиосевой вектор (valence,
arousal, openness, social, stability, каждый в `[-1, 1]`). Обновляется применением `MoodDelta`
(клампится к границам), затухает к baseline через `drift_toward`, а `lift_toward` тянет
пропорциональную долю к цели (соц. со-регуляция BOB-033). `tone()` выводит детерминированный
tone-дескриптор, которым application окрашивает реплики — тот же вход всегда даёт тот же
дескриптор, тон тестируем без модели.

`Disposition` (`disposition.py`) — стабильный темперамент как frozen-вектор двух черт
(`optimism` / `resilience` в `[0, 1]`), из которого канон-оптимизм Боба *вытекает*, а не
прописан. Чистые деривации: `reappraisal_probability` (готовность переосмыслить тёмную
мысль), `positive_lift_scale` / `negative_dip_scale` (🔴 **асимметрия** соц. контагиона —
тёплое сообщение поднимает сильнее, чем холодное роняет: структурный анти-депрессант),
`social_lift_rate` (доля к baseline, на которую тёплый ход подтягивает mood).

`TasteEngine` (`taste.py`) — детерминированные вердикты по осям вкуса Боба. Каждая
`TasteAxis` несёт `value` (`[-1, 1]`), `conviction` (`[0, 1]`) и `experience_count`; `score`
детерминированно отображает топик в `Verdict` (love/like/neutral/dislike/hate) — LLM только
*вербализует* вердикт, никогда его не решает. Убеждённость гейтит экстремумы (сильная, но
непроверенная симпатия дотягивает только до `LIKE`). `taste_evolution.reinforce` — чистое
ядро само-эволюции: сдвиг вкуса и рост убеждённости масштабируются на `(1 - conviction)` —
THE анти-runaway-гардрейл. `mood_taste.modulate` — mood временно окрашивает вердикт (±1 шаг
по шкале) **без мутации осей**; `experiment_bias` выводит готовность попробовать новое.

`Fascination` (`fascination.py`) — топик, которым Боб *увлечён* прямо сейчас: `topic`
(заземлён из реальной внутренней жизни, никогда не случаен), `intensity` (`[0, 1]`) и
`created_at`. Старение — закон распада: интенсивность гаснет по экспоненциальному полураспаду,
`aged` возвращает ту же страсть «сейчас», `has_faded` (ниже `DECAY_FLOOR`) — сигнал шага
эволюции заменить выдохшуюся страсть на свежезаземлённую. `phantom_evolution.evolve_phantoms`
— чистое ядро мембершипа фантом-предпочтений (кофе, дождь, книги…): заземлённый кандидат
может проявиться (за seeded-RNG гейтом), набор ограничен `max_count`, ≤1 изменение за шаг,
идемпотентно.

### План выражения, голос и рефлексия

`ExpressionPlan` (`expression.py`) — план хода Боба про *как* он выражается: `mode` (полный
`REPLY` против терсого `REACT_ONLY`), редкие флаги (`leak_inner_life` / `callback`) и мягкий
`FormHint` (terse/normal/expansive). Решение — чистая детерминированная эвристика на mood +
сигналах хода + инъектированном seeded-RNG. 🔴 Здесь же живут **определения** `Verbosity`
(TERSE/NORMAL/EXPANSIVE) и `EngagementLevel` (FULL/PLAYFUL/TERSE/DECLINE) — вокабуляр
выражения personality, который `conversation` вычисляет и возвращает.

`voice.py` — чистый домен того, как Боб *звучит*: `tone_directive(mood)` (единственный
источник тона), `brevity_directive(verbosity)` / `brevity_few_shot` (длина хода из решённой
`Verbosity`), `engagement_directive(level)`, `sulk_directive`, `relationship_tone_directive`,
`who_is_writing_directive` / `stranger_directive` (читают уже-вычисленный `kind.value`
собеседника — БЕЗ runtime-импорта `InterlocutorKind`; `who_is_writing_directive` также
доклеивает родовую клаузу по уже-вычисленному `gender.value` — «обращайся в женском/мужском
роде», UNKNOWN → ничего, BOB-078 A, тоже без импорта social `Gender`), `profanity_stance`,
`user_repeat_directive`, `improvement_directive`, `tactful_withhold_directive`
(BOB-066.2.6 — тёплый отказ такта разглашения: гейт привилегий по-прежнему НЕ раскрывает
приватные данные owner'а гостю, а эта строка лишь заменяет сухую стену на человечное «это
лучше у него самого спросить», не роняя ни детали, ни намёка; чистая, application
дописывает её ТОЛЬКО на guest owner_data-запрос). `operator_stance` (BOB-087.B2 —
позитивная рамка поверх `guppi_canon`: когда доходит до работы с кодом, Боб — **оператор**,
который направляет GUPPI и по-человечески реагирует на вехи своими словами (взялся / позеленело
/ сломалось / готово-PR), а не построчный робот-нарратор; усиливает анти-нарратив-гейт BOB-074
из голого запрета в позу — dev-реплики Боба короткие живые реакции, его характер, а не лог;
чистая, вплетена в базовую персону). `guppi_no_roleplay_directive` (BOB-090.D3 — Боб НЕ
отыгрывает GUPPI: живые эпизоды показали «GUPPI упрямо твердит…», «GUPPI посмотрел на меня с тем
самым выражением, которое бывает у камня», «GUPPI, перенеси мой ответ в общий чат» — сразу два
нарушения канона: приписал личность тому, у кого её нет, и подменил действие рассказом о
действии (класс BOB-074). Директива запрещает говорить ЗА GUPPI, приписывать ему мнения, чувства
и реплики и пересказывать свой приказ вместо самого дела — и НЕСЁТ ПОЛОЖИТЕЛЬНУЮ ЗАМЕНУ (вызови
инструмент, дай результат, дальше говори от себя), потому что голый запрет recall-яд обходит.
Разрешённое каноном ворчание про буквализм GUPPI она не трогает: это про характер Боба, а не про
чувства исполнителя. Механику при этом озвучивает сам GUPPI своим ботом — см. ядро
`bob.coding.speaker`. Чистая, вплетена в базовую персону рядом с `operator_stance`).
`recall_has_work` / `recalled_work_directive`
(BOB-087.C3 — провенанс-директива register-aware recall, зеркало self_action-строки: когда
recall поднял ОДИН из СОБСТВЕННЫХ `work` dev-эпизодов Боба — его операторскую вспоминку, как
он вёл GUPPI по коду — вплетается ЛЁГКИЙ анти-конфабуляционный бэкстоп: говори о ней от
первого лица («я попросил GUPPI…»), честно про сбои и промахи, и НЕ выдумывай деталей — не
смешивай работу с болтовнёй. `recall_has_work` — чистый предикат: True, если среди
припомненного есть память с `category` `work` ИЛИ любым work-тегом (`work`/`dev`/`actor:bob`
— документированное зеркало `memory.work_journal`, чтобы чистый personality-домен ничего не
импортил из memory). Ортогональна self_action-строке: work-эпизод несёт event_type `work`,
не `self_action`, поэтому обе могут сработать на одном ходу; нет work → строки нет,
дефолтный путь байт-в-байт). `recalled_origin_directive`
(BOB-090.C1 — провенанс «ГДЕ это было сказано», третий член того же семейства. Живой баг:
Боб уверенно заявлял «я объяснил Норману в группе пару сообщений назад», хотя писал в
личку (эпизод 3092) — метка `visibility` в памяти была, но в промпт не попадала, и место
он домысливал. Чистая функция читает `visibility` припомненного и строит ОДНУ живую
строку: всё сказано наедине, всё сказано при всех, либо и то и другое — и тогда строка
предупреждает не путать одно с другим. 🔴 Неизвестный источник — пустой recall, старые
строки без метки, незнакомое значение — не называется ВОВСЕ: молчание о месте честно,
выдуманное место и есть чинимый дефект. Ничего не фильтрует: выборка recall читается
целиком, сквозная память BOB-082 не тронута. Ось «где сказано» ортогональна оси регистра
«про что» (`recalled_work_directive`), поэтому приватный work-эпизод поднимает обе строки.
Метки видимости здесь — документированное ЗЕРКАЛО `bob.social.disclosure` под
drift-guard-тестом, чтобы `personality` не импортировал `social`. За флагом
`memory.origin_provenance`, ВЫКЛЮЧЕННЫМ по умолчанию. Флаг стоит на `VoiceComposer`, а не
на ходе, чтобы регенерация анти-повтора видела тот же провенанс; OFF → системный промпт
байт-в-байт). `language.py` — `language_directive`
(персона говорит на своём языке). `reflection.py` — `build_reflection_prompt`: вплетает
свежий контекст (недавние эпизоды + текущий тон) в промпт заземлённого монолога, лечит
«застрявшую пластинку»; без свежего контекста возвращает generic-промпт дословно.

🔴 **`guppi_voice_canon(*, prose_answer)` — досягаемость канона, а не второй канон
(BOB-096.3).** До этого среза запрет отыгрывать GUPPI стоял в базовой персоне, то есть
доезжал ровно до одной двери — разговорного хода. Рефлексия, переоценка, дайджест,
проактивная реплика, дневник работы и выжимка фактов его не видели, а их вывод ложится в
память и возвращается к модели её собственным few-shot (механизм BOB-074). Теперь текст
канона отдаётся наружу одной функцией в двух формах: прозаической двери — ДОСЛОВНО
`guppi_no_roleplay_directive()` (второго канона у Боба не завелось, это пинается тестом),
машинной (`prose_answer=False`: JSON фактов, JSON правил, профиль пробуждения) — та же
суть клаузой о записи, без прозаических указаний. Различать обязательно: в полной
директиве есть «вызови инструмент… говори от себя, своим голосом», и канон без различения
формы молча сломал бы JSON-контракт извлечения фактов. Функция чистая и о роутере ничего
не знает: роутер получает её инъекцией и сообщает единственный факт о двери — читает ли
ответ человек. Само вплетение живёт в `application/router` и в петле инструментов
(`capabilities`), поэтому `personality` по-прежнему не импортирует ни того ни другого.

### Семейство реакций (BOB-050)

`ReactionMeaning` / `ReactionContext` / `ReactionJudge` (`reaction_meaning.py`) — семантика
того, что чужая реакция на сообщение Боба *значит*: emoji — сигнал, никогда не ключ-таблица.
`reaction_judgment.py` — чистый Tier-0 wire-протокол (`build_reaction_user_prompt` /
`parse_reaction_meaning`, `ReactionJudgeParseError` на мусоре). `reaction_effect.py` — чистое
ядро «реакция меняет Боба»: `apply_reaction_to_mood` (тёплая реакция сперва тянет mood к
baseline, потом ложится bounded-дельта — тот же путь соц. контагиона, что и текст),
`nudge_relationship_warmth` (клампит теплоту границами `kernel.relationship.MIN_AXIS`/
`MAX_AXIS` — единственный источник инварианта оси, своей копии нет, bob-etb.8),
`NotableReaction` (лёгкая запись «меня получили», только когда
`worth_acknowledging`). `reaction_aloud.acknowledgment_hint` — редкий hint упомянуть это
вслух; `reaction.reaction_emoji_for(mood)` — picker emoji из стандартного набора.

### Настроение комнаты — второй слой тона (BOB-066, Пласт 4)

`room_tone.py` — чистый детерминированный **второй слой**, зеркало `mood_taste.modulate`:
поверх личного настроения и тона отношений Боба общая атмосфера *комнаты* красит, насколько
игриво он звучит и насколько охотно вступает — **без мутации личного `Mood`** (тот не является
входом по построению). Модуль потребляет настроение комнаты **по значению**, как обычные
`float` (`room_valence` / `room_polarization`), которые application извлекает из `RoomReading`
слоя `conversation` и передаёт напрямую — поэтому `personality` НЕ импортит `conversation`
(нет цикла; тот же паттерн, что `voice._KIND_LABEL` по `kind.value`).

- `room_tone_directive(room_valence, room_polarization, *, thresholds=None)` — голосовая
  строка настроения комнаты на этот ход. Тяжёлая (`room_valence` на/ниже пола `heavy_valence`,
  по умолчанию −0.35) ИЛИ поляризованная (`room_polarization` на/выше потолка `polarized`, 0.5)
  комната гасит игривость — реплика «считай обстановку, сбавь трёп»; тёплая неполяризованная
  (`room_valence` на/выше `warm_valence`, 0.35) разрешает лёгкий тон; ровная середина не
  добавляет ничего (`""`, дефолтный путь неизменен). Поляризация ПЕРЕКРЫВАЕТ тепло — накалённый
  спор не праздник, какой бы ни была средняя валентность. Полосы настраиваются через
  `RoomToneThresholds` (frozen+slots, `heavy_valence`/`warm_valence`/`polarized`) из
  конфигурации `presence.room_tone.*`.
- `room_engagement_bias(room_valence, disposition)` — знаковый сдвиг порога вовлечённости Боба.
  Тёплая комната поднимает аппетит вступить (положительный сдвиг), тяжёлая — гасит
  (отрицательный), ровная не двигает ничего. Величины ПЕРЕИСПОЛЬЗУЮТ асимметрию соц. контагиона
  диспозиции: тёплая масштабируется на `Disposition.positive_lift_scale()`, холодная — на
  строго меньший `negative_dip_scale()`, поэтому равные по силе тёплая и холодная комнаты НЕ
  взаимогасятся — тепло двигает Боба сильнее холода, тот же структурный анти-депрессант.

Обе — module-level функции (детерминированы, без I/O, без `Mood`), поэтому unit- и
mutation-тестируемы, а личное настроение не тронуто по построению.

🔴 **LIVE-провязка (BOB-066 Срез W.2):** `room_tone` теперь потребляется в конвейере хода
за флагом `presence.room_mood.enabled` (OFF по умолчанию → тон пуст, аппетит как был). Из
рефлексивного `RoomReading` (surfaced на `_ReplyGate` при `presence.reflective`) коллаборатор
`RoomMoodModulator` (`application/usecases/room_mood_modulator.py`) по значению даёт
`room_tone_directive` в compose-стек (`VoiceComposer.compose` + `AntiRepeatGuard.guard`,
turn-local) и `room_engagement_bias` re-map порога аппетита (без двойного fatigue-decay).
🔴 Зависимость: без `presence.reflective` `RoomReading` не рождается, поэтому модулятор
работает над пустым чтением. Личное настроение (`Mood`) не тронуто по построению. Отдельно
воркерный top-k action-budget (несколько входящих → один ответ + отбор реакций) провязан в
intake-воркер за `presence.series_budget.enabled` (см. `conversation`/`presence`).

### Use-case'ы (application)

`UpdateMoodFromText` (`usecases/update_mood_from_text.py`) — шаг perceive: читает четыре
сигнала входящего (sentiment на локальном Tier-0, частота, время суток из `Clock`, присутствие)
и превращает их в `MoodDelta`, который применяет чистый `Mood`. `ApplyReflection` — закрывает
петлю рефлексия→вкус через relevance-гейт: неузнанный/нерелевантный сигнал — строгий no-op,
шум не трогает личность. `ReappraiseReflection` — вероятностный реаппрайзал (BOB-033 .2):
классифицирует сентимент, при негативе тянет гейт из seeded-RNG против
`reappraisal_probability`, при срабатывании переосмысляет тёмную мысль на Tier-1 (иначе она
остаётся честно грустной). `EvolveFascination` / `EvolvePhantoms` — редкие заземлённые шаги
на reflect-тике (идемпотентны в периоде). `RepoFascinationGrounding` / `StoreFascinationReader`
(`fascination_sources.py`) — live-швы заземления и чтения.

🔴 **Выбор увлечения ходит своей дверью `FASCINATION_PICK` (BOB-096.8).** Раньше он шёл
`INNER_MONOLOGUE`, то есть числился служебным ходом, — а ответ модели ложится в
`fascination_state` (SQLite) и неделями вплетается в контекст ответа как «меня сейчас
занимает…». То есть дверь производит долгоживущий материал речи Боба: ей нужен канон о
голосе (иначе тема вида «упрямство GUPPI» месяц звучала бы его увлечением и возвращалась
припоминанием — механизм BOB-074), и аварийный дублёр выбирать её не вправе. При отвале
шаг не теряется: тему даёт детерминированная опора на тот же реальный материал
(последняя мысль + сильные вкусы), которая ничего не выдумывает.

**Коллабораторы хода (BOB-062.6b, #9).** Декомпозиция `handle_message` вынесла «кто есть Боб»
— его голос — в method-object'ы personality, собираемые в `HandleMessage.__init__`. Seeded-draw
методы принимают опциональный турновый `rng`: при прямом unit-вызове без него — откат на
инъектированный per-boot `self._rng` (legacy-поведение байт-идентично).
- `MoodPerceiver` (`mood_perceiver.py`) — обновить настроение из входящего + план выражения
  (`perceive` / `plan_expression(event, soul, *, rng=None)`; мутабельный per-boot
  `PersonalityState` передаётся ПО ВЫЗОВУ, никогда не захватывается). Seeded-план выражения
  засевается турновым `rng` из `TurnScope` (BOB-066 Срез 2.1, INV-4).
- `GroundedAddons` (`grounded_addons.py`) — свернуть РЕАЛЬНУЮ рефлексию/колбэк/фасцинацию в
  контекст (`with_grounded_addons(context, text, plan, *, rng=None)`); `safe` оборачивает каждую
  добавку — anti-confabulation + decorative (упавшая добавка падает в `""`, никогда не триггерит
  outage). Розыгрыш «surface old» тянет из турнового `rng` (INV-4).
- `VoiceComposer` (`voice_composer.py`) — форма голоса + генерация ответа (`compose(..., *,
  rng=None)`, прокидывает турновый `rng` в grounded-добавки). 🔴
  Дотягивается до КАЖДОЙ другой вертикали ТОЛЬКО через инъектированные порты/значения
  (context-assembler и recall/verify-порты conversation, stance-порт social, plain-reply +
  essential-генераторы application, tool-loop/announcer-фабрики capabilities) — personality не
  импортирует conversation/social/capabilities. Отдаёт `compose` как callback в
  `AntiRepeatGuard` (замыкает цикл compose↔guard по значению).
  🔴 **Анти-нарратив преамбула манифеста (BOB-074, recall-poisoning).** Перед описанием
  навыков (`registry.describe()`) `compose` ставит `_CAPABILITY_PREFACE` — императивное
  анти-few-shot правило: возможности исполняет GUPPI, и если для ответа нужен инструмент, Боб
  ВЫЗЫВАЕТ его (tool call) и даёт РЕАЛЬНЫЙ результат. НИКОГДА не описывает, что GUPPI «пошёл/
  заглянет/ищет/перебирает» — нарратив о намерении без реального результата запрещён. Правило
  противодействует мимикрии, которой прошлые нарратив-ответы Боба в истории учат Qwen; на
  выходе его дублирует консервативный backstop tool-loop (см. `capabilities`).

### Адаптеры (infrastructure)

`LlmReactionJudge` (`adapters/reaction_judge.py`) — Tier-0 реализация `ReactionJudge`:
чистый билдер промпта + router-вызов + чистый парсер → `ReactionMeaning`. 🔴 Его дверь
`REACTION_JUDGE` числилась служебной, но `interpretation` вплетается в эпизод «X
отреагировал 👍 на моё «…» — <прочтение>» и в стор заметных реакций, откуда возвращается
припоминанием: с BOB-096.8 у неё `output_is_kept`, то есть канон о голосе ей досылается
(в машинной форме — ответ разбирает код).
`SqliteFascinationStore` (`adapters/fascination_store.py`) — per-persona увлечённость через
`SqliteMemoryRepo.connection()`-шов. `KvNotableReactionStore`
(`adapters/notable_reaction_store.py`) — единственная последняя запись «меня заметили» в
kv-таблице (`record`/`latest`/`clear` — hint всплывает не более раза).

## Инварианты

- **personality — стабильное ядро.** 0 runtime-зависимостей на `conversation`/`social`;
  `voice.py` не импортит ни `Verbosity`/`EngagementLevel` из conversation (они теперь
  здесь), ни `InterlocutorKind` из social (читает `kind.value`). Цикл `voice↔brevity/
  engagement` разорван — `no-dependency-cycles` зелёный.
- **Mood/taste ограничены и не убегают.** Оси Mood в `[-1, 1]` (клампятся); эволюция вкуса
  масштабируется на `(1 - conviction)` — устоявшееся мнение почти не движется, tone
  детерминирован (тестируем без модели). `mood_taste.modulate` окрашивает вердикт ≤1 шага и
  НЕ мутирует оси.
- **Убеждённость гейтит стойку и экстремумы.** `TasteEngine.score` не дотягивает до
  `LOVE`/`HATE` без убеждённости; `Negotiation.decide` уступает в `USER_DOMAIN`, а в
  `BOB_PERSONAL`/`SHARED` твёрдая позиция эскалирует от согласия к `PROPOSE_ALTERNATIVE`.
- **Fascination заземлён и распадается.** Топик всегда из реальной внутренней жизни (не
  случаен), интенсивность гаснет по полураспаду в `[MIN, MAX]`, сдвиг — только когда страсть
  выдохлась; фантом-эволюция ≤1 изменение за шаг, идемпотентна. С BOB-096.8 тему не
  выбирает и аварийный дублёр: дверь `FASCINATION_PICK` — «голос, который остаётся», а при
  отвале облака шаг берёт детерминированную опору (последняя мысль + сильные вкусы), то
  есть тема рождается без модели, а не теряется.
- **Реакция → bounded MoodDelta от СМЫСЛА.** Знак и величина `mood_delta` идут от значения
  реакции, не от emoji; каждый сдвиг внутри BOB-030-полосы (нудж, не свинг); `NotableReaction`
  пишется только при `worth_acknowledging`.
- **Рефлексия заземлена, leak — только реальный.** `build_reflection_prompt` без свежего
  контекста = generic-промпт дословно; `ReflectionReader` отдаёт текст только реальной
  персистентной рефлексии (никакой фабрикации — `None` = leak no-op).
- **Реаппрайзал вероятностен и никогда не механичен.** Гейт из seeded-RNG против
  `reappraisal_probability`; на промахе мысль остаётся честно грустной, Tier-1-вызова нет.
- **Настроение комнаты — второй слой, не мутатор.** `room_tone` берёт настроение комнаты по
  значению (`float`), личный `Mood` не является входом — мутация невозможна структурно.
  Поляризация перекрывает тепло; ровная комната — чистая identity (`""` / 0.0). Асимметрия
  вовлечённости переиспользует `Disposition.positive_lift_scale`/`negative_dip_scale`, а не
  хардкодит коэффициенты, поэтому тёплая комната поднимает сильнее, чем холодная роняет.

### Границы модуля (AaC)

Дисциплина держится explicit-path `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ personality VERTICAL module, сгенерированы `scripts/gen_boundary_rules.py`):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/` (`[!u]*` / `[!au]*`-глобы);
- `usecases/` не тянут чужой `infrastructure/` напрямую (только через порты);
- снаружи к `personality` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`);
- 🔴 personality НЕ импортит `conversation`/`social` (стабильное ядро; входящее ребро от
  `conversation → personality` однонаправленно, легализовано в note-блоке rules.yml).

Внутренний layer-guard модуля — `tests/personality/test_layering.py`.

## API

<!-- beadloom:track=src/bob/personality/ports.py -->

Модуль `src/bob/personality/ports.py` (порты-протоколы, только интерфейсы):
- `MessageReactor` — react-only шов: поставить нативную emoji-реакцию на сообщение
  (best-effort, никогда не роняет ход). Реализация — Telegram-адаптер.
- `ReflectionReader` — leak-inner-life шов: текст последней РЕАЛЬНОЙ рефлексии Боба
  (`None` = нет записи, leak no-op).
- `FascinationStore` — долговечный per-persona стор текущей увлечённости. Реализация —
  `SqliteFascinationStore`.
- `NotableReactionStore` — лёгкий стор последней «меня получили»-реакции. Реализация —
  `KvNotableReactionStore`.
- `CurrentFascinationReader` — шов чтения ТЕКУЩЕЙ живой увлечённости (состаренной, не
  угасшей; `None` = нет, упоминание no-op). Переехал сюда из `handle_message.py` (BOB-113).

Фасад `src/bob/personality/__init__.py` — вход в модуль. Канонический импорт портов —
`from bob.personality.ports import MessageReactor` (транзитный ports-шим
`bob.domain.ports` удалён, BOB-062.8).

Ключевые точки входа:
- Домен: `mood.Mood`/`MoodDelta`, `disposition.Disposition`, `taste.TasteEngine`/`Verdict`,
  `taste_evolution.reinforce`, `mood_taste.modulate`, `negotiation.Negotiation`/`Stance`,
  `fascination.Fascination`, `phantom_evolution.evolve_phantoms`, `expression.decide_expression`
  (+ `Verbosity`/`EngagementLevel`/`ExpressionMode`/`FormHint`), `voice.tone_directive`/
  `brevity_directive`/`engagement_directive`/`tactful_withhold_directive`/
  `recall_has_work`/`recalled_work_directive` (BOB-087.C3),
  `recalled_origin_directive` (BOB-090.C1), `guppi_no_roleplay_directive` (BOB-090.D3),
  `guppi_voice_canon` (BOB-096.3 — тот же запрет в двух формах, реализация порта
  `VoiceCanon` роутера), `reaction_meaning.ReactionMeaning`,
  `reaction_effect.apply_reaction_to_mood`, `reflection.build_reflection_prompt`, `soul.SOUL`,
  `room_tone.room_tone_directive`/`room_engagement_bias` (+ `RoomToneThresholds`).
- Use-case'ы: `usecases.UpdateMoodFromText`, `ApplyReflection`, `ReappraiseReflection`,
  `EvolveFascination`, `EvolvePhantoms`, `HeuristicReflectionParser`.
- Адаптеры: `LlmReactionJudge`, `SqliteFascinationStore`, `KvNotableReactionStore`.

Композиция (wiring mood/reflection/fascination-тиков, инъекция `ReactionJudge`) — в
композиционном корне `app.py`. Восприятие «меня получили» (`perceive_reaction`) — cross-domain
use-case в `application/usecases/`, вне вертикали. Долговечная запись в SQLite — через kernel
`SqliteMemoryRepo` (`infrastructure/persistence/`, до среза .7).

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда — тон Боба идентичен):

- Домен: `tests/domain/personality/test_mood.py`, `test_disposition.py`, `test_taste.py`,
  `test_taste_evolution.py`, `test_mood_taste.py`, `test_negotiation.py`,
  `test_fascination.py`, `test_phantom_evolution.py`, `test_expression.py`, `test_voice.py`,
  `test_language.py`, `test_profanity.py`, `test_reaction.py`, `test_reaction_meaning.py`,
  `test_reaction_judgment.py`, `test_reaction_effect.py`, `test_reaction_aloud.py`,
  `test_reflection.py`, `test_soul.py`, `test_absence.py`, `test_room_tone.py`.
- BDD-приёмка второго слоя: `tests/acceptance/features/room_tone.feature` +
  `tests/acceptance/steps/test_room_tone.py` (тяжёлая/поляризованная комната гасит игривость,
  личный mood не тронут).
- Провенанс источника (BOB-090.C1): `tests/domain/personality/test_voice_origin_provenance.py`
  (личка / комната / смесь / неизвестный источник → пустая строка) +
  `tests/domain/personality/test_voice_composer_work_provenance.py` (ортогональность оси
  регистра); BDD — `tests/acceptance/features/origin_provenance.feature` +
  `tests/acceptance/steps/test_origin_provenance.py`.
- Канон GUPPI в голосе (BOB-090.D3): `tests/domain/personality/test_voice_guppi_no_roleplay.py`
  (там же обе формы `guppi_voice_canon` и то, что прозаическая совпадает с базовой
  директивой ДОСЛОВНО); BDD — `tests/acceptance/features/guppi_canon.feature`.
- Досягаемость канона до дверей personality (BOB-096): `tests/test_canon_reaches_every_door.py`
  (тема увлечения настоящим `EvolveFascination`, прочтение реакции настоящим
  `LlmReactionJudge`) и `tests/test_the_understudy_never_speaks_for_bob.py` (дублёр не
  выбирает увлечение, но шаг переживает отвал); BDD —
  `tests/acceptance/features/voice_that_stays.feature`.
- Use-case'ы: `tests/application/usecases/test_update_mood_from_text.py`,
  `test_apply_reflection.py`, `test_reappraise_reflection.py`, `test_reflection_parser.py`,
  `test_evolve_fascination.py`, `test_evolve_phantoms.py`, `test_fascination_sources.py`.
- Адаптеры: `tests/infrastructure/llm/test_reaction_judge.py`,
  `tests/infrastructure/persistence/test_fascination_store.py`,
  `test_notable_reaction_store.py`.
- Layer-guard модуля: `tests/personality/test_layering.py`.
