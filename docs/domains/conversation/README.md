<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль conversation — «как ведётся ход»

Ведение разговора как единая вертикаль: *адресность* (кому сообщение — Бобу, другому или
никому), *разговорная реплика* (conversation floor — кто «у микрофона» в треде и её
непрерывность), *краткость по запросу* (answer-demand → `Verbosity`), *вовлечённость/аппетит*
(`EngagementLevel` + затухающая усталость), *судьи хода* (семантический ResponseJudge «как
ответить», VolatilityJudge «нужна ли свежая проверка перед ответом»), *живая interim-строка*
на время проверки и *анти-тик* защита (повтор owner'а / повтор Боба / фраза-тик / повторяющийся
закрывающий мотив). Это модуль о том, **как ведётся ход** — он спрашивает у характера, *как
сказать*, но сам решает *если/насколько* и *в какой форме* Боб вступает.

Это шестой **вертикальный** модуль domain-first раскладки (BOB-062.6a, срез 6/8 эпика
BOB-062), выделенный из `domain/personality/` рядом с `personality`: «как ведётся ход» собран
в одном месте `src/bob/conversation/`, а не размазан по `domain/personality/` +
`application/usecases/decide_response` + persistence-сторы (floor / closer-log) +
`infrastructure/llm/{response_judge,volatility_judge,interim_line}`. Модуль охватывает три слоя
**внутри** одного bounded-context, поэтому несёт не-слойный тег `module-vertical` (правило
`architecture-layers` его рёбра пропускает), а внутреннюю и внешнюю дисциплину держат
explicit-path `forbid_import`-правила в `.beadloom/_graph/rules.yml` (§ conversation VERTICAL
module), сгенерированные `scripts/gen_boundary_rules.py`.

## 🔴 Ключевые решения по границам и принадлежности

1. **`conversation → personality` однонаправленно.** В конвейере хода conversation решает
   *если/насколько* отвечать → personality решает *как сказать*. personality — стабильное
   ядро; **conversation зависит от personality**, не наоборот. Модуль читает personality-VO
   (`Verdict`, `Mood`, `NegotiationZone`, `FormHint`) и ВОЗВРАЩАЕТ personality-VO выражения
   (`Verbosity` / `EngagementLevel`, чьи *определения* переехали в `personality/expression.py`
   в .1). Обратного ребра нет — прежний цикл `voice ↔ brevity/engagement` разорван,
   `no-dependency-cycles` зелёный.
2. **`zone_classifier` (+ порт `ZoneClassifier`) живёт ЗДЕСЬ.** Классификатор *зоны* —
   решение хода: он определяет, чья территория топик (`BOB_PERSONAL`/`USER_DOMAIN`/`SHARED`),
   чтобы `personality.Negotiation` выбрал стойку. Зависит от `negotiation`/`taste` personality
   = `conversation → personality` ✓. Сама переговорная *стойка* (`Negotiation`) наоборот — в
   personality (характер, а не ход).
3. **Судьи `response_judgment` / `volatility_judgment` — решения хода.** Оба производят
   решение о ходе (как ответить / нужна ли проверка), поэтому conversation, а не personality.
   Их model-facing половины (prompt/parser) — чистые, тестируемы без модели; Tier-0-адаптеры —
   в `adapters/`.
4. **Порты живут в `conversation/ports.py`** (`ConversationFloorStore` / `CloserLog` /
   `ZoneClassifier`); канонический импорт — `from bob.conversation.ports import
   ConversationFloorStore` (транзитный ports-шим `bob.domain.ports` удалён, BOB-062.8).

## 🔴 Мультиперсональность: floor и адресность за многолюдный тред

Модуль ведёт ход в группе здорово: `addressivity` покрывает DIRECTED_TO_BOB / DIRECTED_TO_OTHER
/ AMBIENT, а `conversation_floor` поднимает безметочную AMBIENT-реплику ЛЮБОГО участника до
DIRECTED_TO_BOB, пока floor держит Боб, — owner и гость говорят с ним без метки в каждом
сообщении, но Боб не встревает в чужой диалог (явный поворот к другому / распад снимают floor).
После BOB-058 групповой тред — **общий**, а судьи хода читают его целиком: per-person атрибуция
сосуществует с цельным тредом, а не рвёт диалог на изолированные «Боб ↔ каждый».

## Спецификация

### Раскладка модуля

```
src/bob/conversation/
  ports.py            # layer=domain          — conversation-порты (ConversationFloorStore/CloserLog/ZoneClassifier)
  __init__.py         # layer=domain          — фасад модуля
  addressivity.py     # layer=domain          — Addressivity + classify_addressivity/others_present + decide_response (if/else-лестница, BOB-023)
  conversation_floor.py# layer=domain         — FloorHolder/ConversationFloor/FloorConfig, advance_floor, resolve_addressivity (BOB-025)
  brevity.py          # layer=domain          — AnswerDemand + BrevityThresholds + decide_verbosity → personality Verbosity, clamp_reply (BOB-024)
  engagement.py       # layer=domain          — decide_engagement → personality EngagementLevel + ConversationalFatigue (затухающий резервуар, BOB-014)
  zone_classifier.py  # layer=domain          — TasteZoneClassifier: дефолт ZoneClassifier (taste/логистика-эвристика)
  conversation.py     # layer=domain          — анти-тик предикаты: is_user_repeat/is_bob_repeat/is_phrase_tic/recurring-closer (BOB-022/026/061)
  interim_line.py     # layer=domain          — чистый prompt+cleaner живой interim-строки (BOB-057 .3)
  response_choice.py  # layer=domain          — ResponseIntent/ResponseChoice/ResponseContext + порт ResponseJudge (BOB-049)
  response_judgment.py# layer=domain          — чистый Tier-0 wire-протокол судьи ответа (prompt/parser/emoji-валидатор)
  volatility_judgment.py# layer=domain        — VolatilityVerdict/Context + порт VolatilityJudge + prompt/parser (BOB-057 .1)
  reply_context.py    # layer=domain          — _assemble_shareable_context: сборка reply-shaping контекста хода (free-функция → хелпер, BOB-062.6b)
  thread.py           # layer=domain          — проекция персиста в сигналы хода: _render_thread/_user_turns/_history_for_author/_recent_bob_replies/_strip_recalled_closer (BOB-062.6b)
  usecases/           # layer=application
    decide_response.py       —                — DecideResponse: собрать контекст и спросить судью по смыслу (BOB-049)
    turn_gate.py             —                — TurnGate: гейт хода reply/react/silent (тонкий координатор, BOB-062.6b)
    addressivity_perceiver.py —               — AddressivityPerceiver: восприятие адресности + брать ли ход (BOB-023/025)
    floor_manager.py         —                — FloorManager: resolve + advance разговорной реплики (floor, BOB-025)
    engagement_model.py      —                — EngagementModel: аппетит + verbosity + after-turn feedback (BOB-014/024)
    recall_assembler.py      —                — RecallAssembler: воспроизведение треда + absence/acknowledgment (BOB-044/045/050)
    verify_step.py           —                — VerifyStep: предответная эпистемическая проверка → per-turn note (BOB-057)
    anti_repeat_guard.py     —                — AntiRepeatGuard: анти-повтор/тик + кольцо закрывающих (BOB-022/061)
  adapters/           # layer=infrastructure
    response_judge.py        —                — LlmResponseJudge (Tier-0 реализация ResponseJudge)
    volatility_judge.py      —                — LlmVolatilityJudge (Tier-0 реализация VolatilityJudge)
    interim_line.py          —                — LlmInterimLineGenerator (живая interim-строка)
    conversation_floor_store.py —             — SqliteConversationFloorStore (per-thread floor, UPSERT)
    closer_log_store.py      —                — SqliteCloserLog (кросс-сессионное кольцо закрывающих)
```

**ОСТАЁТСЯ вне conversation:** переговорная *стойка* `negotiation.py` (это personality —
характер); долговечная запись floor / closer-log идёт через `SqliteMemoryRepo.connection()`-шов
общего kernel'а (до среза .7).

### Адресность и разговорная реплика (чистый домен)

`Addressivity` (`addressivity.py`) — чистый детектор, кому обращено сообщение
(DIRECTED_TO_BOB / DIRECTED_TO_OTHER / AMBIENT), по сигналам Telegram, уже извлечённым
gateway'ем (reply-to / @mention / текст) — без I/O и рандома. `others_present` — эвристика
«тред не 1:1». `decide_response` — исходная if/else-лестница отклика (её заменяет семантический
`ResponseJudge`, BOB-049).

`ConversationFloor` (`conversation_floor.py`) — трекер разговорной реплики: кто «у микрофона»
(`FloorHolder` BOB/OTHER/IDLE), когда держателя последний раз подтвердили (`since`) и серия
безметочных реплик без Боба (`idle_streak`). `advance_floor` — чистый переход floor по ходу;
`resolve_addressivity` поднимает AMBIENT→DIRECTED_TO_BOB, пока floor=БОБ жив; `FloorConfig`
тюнит `timeout_seconds` + `reset_after_silent`. Модуль детерминирован по инъектированному `now`.

### Краткость и вовлечённость (возвращают personality-VO)

`brevity.py` — краткость по запросу: `AnswerDemand` (LOW/MEDIUM/HIGH, лексическая эвристика
`classify_answer_demand`) объединяется с интересом, настроением/аппетитом и `FormHint` в
`decide_verbosity`, которое возвращает personality-`Verbosity` (TERSE/NORMAL/EXPANSIVE).
`BrevityThresholds` — инъекция порогов из `brevity.*`; `clamp_reply` — жёсткий страж длины.
Решение детерминировано по явному `roll` (рандома внутри нет).

`engagement.py` — аппетит Боба к разговору как уровень: `decide_engagement` из четырёх сигналов
(mood, интерес топика, усталость, отношение) → personality-`EngagementLevel`
(FULL/PLAYFUL/TERSE/DECLINE) с одним seeded-RNG-броском на границе FULL/PLAYFUL.
`ConversationalFatigue` — ограниченный затухающий резервуар (растёт на бесцельных ходах,
восстанавливается со временем — никогда не перманентный lock-out); `topic_interest` выводит
`[0, 1]`-интерес из вкуса + совпадения с увлечённостью; `engagement_mood_lift` — лифт mood.
🔴 *Определения* `Verbosity`/`EngagementLevel` живут в `personality/expression.py` — здесь
только вычисляющая логика, возвращающая эти VO.

### Судьи хода и анти-тик (BOB-049/057/022/026/061)

`ResponseJudge` / `ResponseChoice` / `ResponseContext` (`response_choice.py`) — семантический
судья «как ответить» (REPLY/REACT/IGNORE), заменивший if/else-лестницу адресности единым
решением-по-смыслу для ЛЮБОГО собеседника. Структурные сигналы (mentions/reply/адресность/
floor) — входы, которые судья взвешивает, а не override-правила (нет `is_owner → reply`
шортката). `response_judgment.py` — чистый Tier-0 wire-протокол (`build_judgment_user_prompt`
/ `parse_response_choice` c `ResponseJudgeParseError` на мусоре / `validate_reaction_emoji`).

`VolatilityJudge` / `VolatilityVerdict` (`volatility_judgment.py`) — перед ответом дешёвый
Tier-0 судья решает, зависит ли хороший ответ от СВЕЖЕГО, быстро-протухающего факта. 🔴 US-2
«не зануда»: неоднозначный/негативный/битый ответ ДЕФОЛТИТ в `needs_check=False`;
`interim_line.py` — чистый prompt+cleaner живой одностроки на время проверки («Леш, надо
кое-что проверить, погоди…»), decorative по дизайну (пустой clean = «нет живой строки»).

`conversation.py` — анти-тик чистые предикаты без LLM: `is_user_repeat` (owner повторяется,
BOB-022 — точный матч после нормализации, консервативно), `is_bob_repeat` (Боб эхом повторяет
свой недавний ответ по всему окну, BOB-026), `is_phrase_tic` (фраза-тик), `recurring_closer` /
`is_recurring_closer_tic` (повторяющийся закрывающий мотив, в т.ч. кросс-сессионно через
`CloserLog`-кольцо, BOB-061).

### Use-case и адаптеры

`DecideResponse` (`usecases/decide_response.py`) — тонкий application-use-case над судьёй
ответа: собирает контекст хода (сообщение, отправитель как соц. контекст, per-person тред,
структурные hints, mood-тон) в `ResponseContext` и делегирует единственное семантическое
решение инъектированному `ResponseJudge`; своей политики не держит.

**Коллабораторы хода (BOB-062.6b, #9).** Декомпозиция God-use-case `handle_message` вынесла
разговорную логику хода в когезивные method-object'ы этой вертикали, собираемые в
`HandleMessage.__init__` из уже инъектированных швов:
- `AddressivityPerceiver` (`addressivity_perceiver.py`) — восприятие адресности + решение,
  берёт ли Боб ход (`decide` / `signals`, поверх `FloorManager` для BOB-025 continuity-raise).
- `FloorManager` (`floor_manager.py`) — resolve + advance разговорной реплики
  (`resolve_effective` / `advance_after_turn`), на примитивных id (без inward-зависимости на
  application-событие).
- `EngagementModel` (`engagement_model.py`) — аппетит + verbosity + after-turn feedback
  (`topic_interest` / `decide_engagement` / `decide_verbosity` / `apply_feedback` /
  `guard_reply_length`); возвращает personality-VO.
- `RecallAssembler` (`recall_assembler.py`) — воспроизведение общего треда + лёгкая
  absence/acknowledgment-текстура (`replay_recent_thread` / `absence_for` /
  `acknowledgment_for`; 🔴 `acknowledgment_for` читает notable-reaction маркер ДО seeded-броска,
  consume-once).
- `VerifyStep` (`verify_step.py`) — предответная эпистемическая проверка (`note`), возвращает
  turn-local заметку; per-turn интерим-анонсер строится из `chat_id` хода через инъектированную
  фабрику.
- `TurnGate` (`turn_gate.py`) — тонкий координатор гейта хода (reply/react/silent) над
  `AddressivityPerceiver` + `FloorManager` + судьёй + `EssentialRunner`; persist / owner-activity
  прокинуты колбэками (гейт не держит политики персиста).
- `AntiRepeatGuard` (`anti_repeat_guard.py`) — регенерация повтора/тика (`guard`) + кольцо
  закрывающих (`log_closer` / `closer_anti_tic`). 🔴 Принимает `VoiceComposer.compose` как
  `compose`-callback (по значению, не импорт — цикл compose↔guard замкнут БЕЗ
  `conversation → personality` импорта); `verify_note` / `closer_nudge` текут turn-local
  аргументами через тот же колбэк.

`LlmResponseJudge` / `LlmVolatilityJudge` / `LlmInterimLineGenerator` (`adapters/`) — Tier-0
реализации портов (билдер промпта + router + парсер). `SqliteConversationFloorStore` — per-thread
floor (UPSERT — floor продвигается каждый ход); `SqliteCloserLog` — ограниченное кольцо
нормализованных закрывающих Боба, переживающее рестарты (закрывает кросс-сессионную разреженность
тика). Запись идёт через `SqliteMemoryRepo.connection()`-шов общего kernel'а (до среза .7).

## Инварианты

- **`conversation → personality` однонаправленно.** Модуль читает и возвращает personality-VO
  (`Verbosity`/`EngagementLevel`/`Verdict`/`Mood`/`NegotiationZone`/`FormHint`), но personality
  НЕ импортит conversation — цикл `voice↔brevity/engagement` разорван (`no-dependency-cycles`
  зелёный).
- **Краткость/verbosity детерминированы.** `decide_verbosity` — по явному `roll`, без рандома
  внутри; `clamp_reply` держит жёсткий предел длины; HIGH-demand owner защищён от обрубка.
- **Вовлечённость восстанавливается.** `ConversationalFatigue` ограничена и затухает —
  бесцельная болтовня заводит Боба, но никогда не запирает навсегда; `decide_engagement`
  детерминирован по seeded-RNG.
- **Floor продвигается и распадается корректно.** AMBIENT→DIRECTED_TO_BOB только пока floor=БОБ
  жив; явный поворот к другому / тайм-аут / серия безметочных без Боба снимают floor, возвращая
  осторожную ambient-логику BOB-023; floor — свойство ТРЕДА (chat_id + thread_id), не человека.
- **Адресность — perception, не решение.** `classify_addressivity` чист и детерминирован; над
  ним политика отклика (судья), сам детектор доступ/отклик не решает.
- **Анти-тик консервативен.** `is_user_repeat` — только точный матч после нормализации (Боб не
  обвиняет owner'а зря); `is_bob_repeat` проверяет всё окно (повтор «через ход» не проскакивает);
  `CloserLog` ловит мотив, рассеянный по сессиям.
- **Судьи по смыслу, безопасный дефолт.** Структурные сигналы — входы, не override-правила;
  VolatilityJudge при неоднозначности дефолтит `needs_check=False` (US-2 «не зануда»); парсеры
  бросают на мусоре, а не молча дефолтят некорректно.

### Границы модуля (AaC)

Дисциплина держится explicit-path `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ conversation VERTICAL module, сгенерированы `scripts/gen_boundary_rules.py`):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/` (`[!u]*` / `[!au]*`-глобы);
- `usecases/` не тянут чужой `infrastructure/` напрямую (только через порты);
- снаружи к `conversation` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`);
- легализовано: `conversation → personality` однонаправленно (читает personality-VO,
  возвращает `Verbosity`/`EngagementLevel`); `conversation.usecases/adapters → router`
  (shared app); `ports`-шим.

Внутренний layer-guard модуля — `tests/conversation/test_layering.py`.

## API

<!-- beadloom:track=src/bob/conversation/ports.py -->

Модуль `src/bob/conversation/ports.py` (порты-протоколы, только интерфейсы):
- `ConversationFloorStore` — долговечный per-thread стор разговорной реплики (BOB-025;
  `load` отдаёт дефолтный IDLE для невиданного треда, `save` UPSERT'ит). Реализация —
  `SqliteConversationFloorStore`.
- `CloserLog` — ограниченное локальное кольцо недавних закрывающих Боба через сессии
  (BOB-061; `append`/`recent`). Реализация — `SqliteCloserLog`.
- `ZoneClassifier` — классификатор зоны переговоров топика (решение хода; дефолт —
  `TasteZoneClassifier`, позже Tier-0 LLM без изменения потребителей). Возвращает
  personality-`NegotiationZone` — ребро `conversation → personality`.

Фасад `src/bob/conversation/__init__.py` — вход в модуль. Канонический импорт портов —
`from bob.conversation.ports import ConversationFloorStore` (транзитный ports-шим
`bob.domain.ports` удалён, BOB-062.8).

Ключевые точки входа:
- Домен: `addressivity.classify_addressivity`, `conversation_floor.advance_floor`/
  `resolve_addressivity`, `brevity.decide_verbosity` (→ `Verbosity`), `engagement.decide_engagement`
  (→ `EngagementLevel`) + `ConversationalFatigue`, `zone_classifier.TasteZoneClassifier`,
  `conversation.is_user_repeat`/`is_bob_repeat`/`is_recurring_closer_tic`,
  `response_choice.ResponseChoice`/`ResponseJudge`, `volatility_judgment.VolatilityJudge`,
  `interim_line.build_interim_line_user_prompt`.
- Use-case: `usecases.DecideResponse`; коллабораторы хода `usecases.{TurnGate,
  AddressivityPerceiver, FloorManager, EngagementModel, RecallAssembler, VerifyStep,
  AntiRepeatGuard}` (BOB-062.6b).
- Адаптеры: `LlmResponseJudge`, `LlmVolatilityJudge`, `LlmInterimLineGenerator`,
  `SqliteConversationFloorStore`, `SqliteCloserLog`.

Композиция (wiring floor/судей/interim в ход `handle_message`, инъекция портов) — в
композиционном корне `app.py`; коллабораторы хода собираются в `HandleMessage.__init__` из
инъектированных швов (интеграция методов в `handle_message` завершена — срез .6b). Долговечная
запись в SQLite — через kernel `SqliteMemoryRepo` (`infrastructure/persistence/`, до среза .7).

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Домен: `tests/domain/personality/test_addressivity.py`, `test_addressivity_policy.py`,
  `test_conversation_floor.py`, `test_brevity.py`, `test_engagement.py`,
  `test_zone_classifier.py`, `test_conversation.py`, `test_response_judgment.py`,
  `test_volatility_judgment.py`, `test_interim_line.py`.
- Use-case: `tests/application/usecases/test_decide_response.py`.
- Адаптеры: `tests/infrastructure/llm/test_response_judge.py`, `test_volatility_judge.py`,
  `test_interim_line.py`; `tests/infrastructure/persistence/test_conversation_floor_store.py`,
  `test_closer_log_store.py`.
- Layer-guard модуля: `tests/conversation/test_layering.py`.
