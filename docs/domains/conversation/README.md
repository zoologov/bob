<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль conversation — «как ведётся ход»

Ведение разговора как единая вертикаль: *адресность* (кому сообщение — Бобу, другому или
никому), *разговорная реплика* (conversation floor — кто «у микрофона» в треде и её
непрерывность), *краткость по запросу* (answer-demand → `Verbosity`), *вовлечённость/аппетит*
(`EngagementLevel` + затухающая усталость), *судьи хода* (семантический ResponseJudge «как
ответить», VolatilityJudge «нужна ли свежая проверка перед ответом»), *живая interim-строка*
на время проверки и *анти-тик* защита (повтор owner'а / повтор Боба / фраза-тик / повторяющийся
закрывающий мотив), *цель ответа на выходе* (`OutgoingTarget` — цитировать ли reply-to и кого
адресовать) и *рефлексивное «чтение комнаты»* (двускоростное внимание: фокус-путь для прямого
обращения против периферийного `ReadTheRoom` — «как живой равный участник группы»). Это модуль о
том, **как ведётся ход** — он спрашивает у характера, *как сказать*, но сам решает
*если/насколько*, *в какой форме* и *куда* Боб вступает.

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
/ AMBIENT, а `conversation_floor` поднимает безметочную AMBIENT-реплику до DIRECTED_TO_BOB, пока
floor держит Боб. **Floor-по-говорящему (BOB-066 .1):** у живого floor=БОБ есть набор
`participants` — id тех, чьи безметочные реплики Боб держит как обращённые к нему (кто реально в
нити с Бобом). Так безметочная реплика УЧАСТНИКА нити продолжает диалог, а реплика ПОСТОРОННЕГО в
многолюдном треде НЕ перехватывается Бобом ошибочно. Набор **аддитивен** и по умолчанию пуст
(`()` = legacy): пустой набор поднимает AMBIENT от любого участника — ровно поведение BOB-025 до
этого среза (1:1 owner↔Боб не меняется). Явный поворот к другому / распад снимают floor и
сбрасывают набор. После BOB-058 групповой тред — **общий**, а судьи хода читают его целиком:
per-person атрибуция сосуществует с цельным тредом, а не рвёт диалог на изолированные «Боб ↔
каждый».

## Спецификация

### Раскладка модуля

```
src/bob/conversation/
  ports.py            # layer=domain          — conversation-порты (ConversationFloorStore/CloserLog/ZoneClassifier)
  __init__.py         # layer=domain          — фасад модуля
  addressivity.py     # layer=domain          — Addressivity + classify_addressivity/others_present + decide_response (if/else-лестница, BOB-023); вокатив «Боб» в любой позиции реплики (BOB-069) + вокатив-с-точкой при запятой-обращении слева (BOB-071)
  conversation_floor.py# layer=domain         — FloorHolder/ConversationFloor(+participants)/FloorConfig, advance_floor, resolve_addressivity, is_floor_participant (BOB-025/066 .1)
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
  outgoing_target.py  # layer=domain          — OutgoingTarget VO + resolve_outgoing_target: КУДА ложится ответ (цитата reply-to + адресат), BOB-066 Срез 1.1
  room_reading.py     # layer=domain          — RoomMood/ReflectiveIntent/RoomReading(+Context) VO + порт RoomReader: форма ОДНОГО рефлексивного «чтения комнаты» (BOB-066 Срез 2.2); + пачечный шов BatchAmbientMessage/BatchRoomReadingContext/BatchRoomReading + порт BatchRoomReader (BOB-072)
  room_reading_wire.py# layer=domain          — чистый Tier-1 wire-протокол «чтения комнаты» (ROOM_READ_SYSTEM_PROMPT/build_room_prompt/parse_room_reading, бросает RoomReadingParseError); + пачечный BATCH_ROOM_READ_SYSTEM_PROMPT/build_batch_room_prompt/parse_batch_reading (garbage→all-IGNORE, толерантен, BOB-072)
  room_verdict.py     # layer=domain          — VerdictKind/ReflectiveVerdict + decide_from_reading + SALIENCE_THRESHOLD: чистое ядро вердикта (LLM вербализует → ядро решает); + decide_batch: проекция read→verdict по всей пачке (BOB-072)
  usecases/           # layer=application
    decide_response.py       —                — DecideResponse: собрать контекст и спросить судью по смыслу (BOB-049)
    read_the_room.py         —                — ReadTheRoom: собрать периферийный контекст и спросить рефлексивного читателя (BOB-066 Срез 2.2)
    turn_gate.py             —                — TurnGate: гейт хода reply/react/silent + фокус/периферия-развилка (тонкий координатор, BOB-062.6b/066 Срез 2.2); non-reply-ветки персистят вход симметрично judge (BOB-071)
    addressivity_perceiver.py —               — AddressivityPerceiver: восприятие адресности + брать ли ход (BOB-023/025)
    floor_manager.py         —                — FloorManager: resolve + advance разговорной реплики (floor, BOB-025)
    engagement_model.py      —                — EngagementModel: аппетит + verbosity + after-turn feedback (BOB-014/024)
    recall_assembler.py      —                — RecallAssembler: воспроизведение треда + absence/acknowledgment (BOB-044/045/050)
    verify_step.py           —                — VerifyStep: предответная эпистемическая проверка → per-turn note (BOB-057)
    anti_repeat_guard.py     —                — AntiRepeatGuard: анти-повтор/тик + кольцо закрывающих (BOB-022/061)
  adapters/           # layer=infrastructure
    room_reader.py           —                — LlmRoomReader (Tier-1 реализация RoomReader: богатый рефлексивный read, ROOM_READ) + LlmBatchRoomReader (пачечный stream-read, толерантный all-IGNORE, BOB-072)
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

🔴 **Вокатив-обращение по имени в любой позиции (BOB-069).** `_is_name_address_to_bob`
распознаёт оклик по имени «Боб»/«bob» (регистронезависимо) не только в начале реплики, но и
в СЕРЕДИНЕ — «Кстати, Боб, расскажи», «эй Боб!». Вхождение считается вокативом, когда
выполнены оба условия: слева от имени — граница слова (начало строки / пробел / разделитель,
проверяет `_has_left_word_boundary`), а справа ВПЛОТНУЮ — терминатор-обращения из
`_ADDRESS_TERMINATORS` (`,` / `:` / `!` / `?`), ЛИБО конец строки при непробельном
address-контексте слева (трейлинг-вокатив «…, Боб», проверяет `_has_left_address_context`).
Тире `-` / `—` вплотную за именем НАМЕРЕННО не терминатор: «Боб-строитель» / «Боб—робот» —
композит/3-е лицо, остаётся AMBIENT; настоящий оклик через тире идёт с пробелом («эй Боб -
ты тут?»). Guard против падежей и 3-го лица сохранён: «Бобу» / «Боба» (справа буква), «Боб
молодец» (справа пробел + слово) и одинокое «Боб» — AMBIENT, а не обращение. Хелперы
`_is_vocative_at` / `_has_left_word_boundary` / `_has_left_address_context` — module-level и
чистые; публичная сигнатура `classify_addressivity` не менялась.

🔴 **Вокатив-с-точкой при запятой-обращении слева (BOB-071 Seam A).** Точка `.` вплотную за
именем — терминатор-обращения ОСОБОГО рода: в отличие от `,` / `:` / `!` / `?`, она частотна и
в сказуемом/3-м лице («Это Боб.», «Меня зовут Боб.»), поэтому одна лишь точка справа вокатива
не даёт. Точка засчитывается окликом ТОЛЬКО при реальном address-сепараторе — запятой-обращении
вплотную слева (`_has_left_comma_context`, игнорирует пробелы между запятой и именем): «Привет,
Боб.» → DIRECTED_TO_BOB (запятая слева = оклик), а «Это Боб.» / «Меня зовут Боб.» → AMBIENT
(слева слово-сказуемое, а не запятая). Так чинится живой баг, где участнику группы, написавшему
«Привет, Боб. Тебя починили?», Боб молча не отвечал (раньше AMBIENT → тишина гостю), без ложных
срабатываний на сказуемое. Матрица BOB-069 (`,` / `:` / `!` / `?` / трейлинг / падежи / тире)
цела; хелпер `_has_left_comma_context` — module-level и чистый, сигнатура `classify_addressivity`
не менялась. **Известное ограничение:** перечисление, оканчивающееся на «…, Боб.» (например
«Пришли Аня, Петя, Боб.»), ложно читается как обращение — запятая слева легитимирует точку. Это
редкий доброкачественный случай, оставленный сознательно по принципу «лучше ответить, чем ложно
промолчать» (симметрично трейлинг-вокативу «…, Боб» без точки).

`ConversationFloor` (`conversation_floor.py`) — трекер разговорной реплики: кто «у микрофона»
(`FloorHolder` BOB/OTHER/IDLE), когда держателя последний раз подтвердили (`since`), серия
безметочных реплик без Боба (`idle_streak`) и `participants` — набор id говорящих живой нити при
`holder=BOB` (BOB-066 .1). `advance_floor` — чистый переход floor по ходу; на ветках БОБА (ответ
Боба / прямое обращение) `sender_id` доливается в `participants` (dedup + потолок 8), поворот к
другому и распад в IDLE — сбрасывают набор. `resolve_addressivity` поднимает
AMBIENT→DIRECTED_TO_BOB, пока floor=БОБ жив **И говорящий признан участником нити** (набор
пуст=legacy / `sender_id` неизвестен fail-safe / `sender_id` в наборе); посторонний при непустом
наборе остаётся AMBIENT. `is_floor_participant` — тот же чистый предикат «эта реплика — часть
живой нити Боба с этим говорящим» (на нём же стоит подъём). `FloorConfig` тюнит `timeout_seconds`
+ `reset_after_silent`. Модуль детерминирован по инъектированному `now`.

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

### Цель ответа на выходе — reply-to (BOB-066 Срез 1.1)

`OutgoingTarget` / `resolve_outgoing_target` (`outgoing_target.py`) — чистое доменное ядро
решения, **куда** ложится ответ Боба в этом ходе: цитирует ли он сообщение, на которое отвечает
(Telegram reply-to), и кого адресует. Решение детерминировано, без LLM и без транспорта.

`OutgoingTarget` — маленький frozen-VO с двумя полями: `reply_to_message_id` (id сообщения,
которое ответ ЦИТИРУЕТ, либо `None` — сегодняшняя отправка в топик без цитаты) и `addressee_id`
(`sender_id` того, кому Боб отвечает, для будущего использования floor/адресацией, либо `None`).
Голый дефолт — легаси-отправка без цитаты и без адресата, поэтому неустановленная цель
поведения не меняет.

`resolve_outgoing_target` выводит цель из структурных сигналов хода: ответ цитирует адресованное
`message_id` ровно тогда, когда рядом есть третий участник (`others_present`) И ход НЕ является
запертым фокальным 1:1 (`focal_1to1`); иначе он уходит без цитаты (`None`). В многолюдном треде
цитата снимает неоднозначность, за каким сообщением идёт ответ Боба; в 1:1 цитата не нужна.
`addressee_id` пробрасывается без изменений — он называет, кому Боб отвечает, независимо от того,
цитирует ли ответ этого человека визуально.

**Проводка.** `HandleMessage._resolve_outgoing_target` — тонкий коллаборатор (не толстит
`handle`): он читает два сигнала (`others_present` — та же заземлённая эвристика «третий участник
в недавнем треде», что использует addressivity-perceiver, поверх уже воспроизведённого общего
треда; `focal_1to1` — прямо-адресованный ход в треде без третьего) и отдаёт примитивы ядру, затем
пробрасывает `target.reply_to_message_id` в шлюз. Цитирование — транспортный концерн выхода,
которым владеет use-case, вынесенный из домена *того, что* Боб говорит: `VoiceComposer` цель не
видит. 🔴 В этом первом срезе `focal_1to1` поглощён `others_present` (1:1 не имеет others → и так
не цитирует), но сохранён как отдельный именованный сигнал, чтобы поздний рефлексивный адресат
(Пласт 2) сделал его самостоятельно значащим без изменения сигнатуры политики.

Шлюз ответа получил аддитивный параметр `reply_to_message_id` (по умолчанию `None` = сегодняшнее
поведение, без регресса): `ReplyGateway.reply` / `BotLike.send_message` / `send_rich_message` /
`TelegramGateway.reply` пробрасывают его в aiogram `ReplyParameters(message_id=…)`. Продакшн-адаптеры
(`aiogram`-шлюз, `multibot._ReplyGateway`) обновлены пробросом без изменения текущего поведения при
`None`.

### Рефлексивное «чтение комнаты» — двускоростное внимание (BOB-066 Срез 2.2)

Пласт 1 эпика «человеческое групповое присутствие»: в многолюдном треде Боб — живой равный
участник, а не коммутатор и не скрипт-бот. Развилка **двух скоростей внимания** сидит в самом
верху `TurnGate.gate()`, ДО судьи BOB-049, и работает, только когда рефлексивный читатель проведён
(флаг ниже) И отправитель распознан.

- 🔴 **Детерминированный ход (INV-1 + легаси-ENGAGE, фикс BOB-066).** Чистый предикат
  `_directed_engage(signals)` отбирает ход, который легаси-политика адресности ответила бы
  детерминированно — зеркаля ENGAGE-набор `addressivity.decide_response` на ЭФФЕКТИВНОЙ адресности
  (`signals.effective` — сырьё `per_message`, поднятое floor'ом): (1) сырое `DIRECTED_TO_BOB` —
  упоминание / reply на Боба / «Боб, …» (INV-1); (2) **floor-continuity** — `effective` поднят до
  `DIRECTED_TO_BOB`, потому что Боб держит живой floor с этим говорящим; (3) **1:1 / собственное
  пространство** — `AMBIENT` без третьего участника (`not others_present`). Любой из трёх замыкается
  на ДЕТЕРМИНИРОВАННЫЙ `_ReplyGate` — минуя рефлексивный read, RNG и потолок доли голоса, — поэтому
  прямое обращение, простой follow-up на вопрос Боба и реплика в его собственном пространстве
  получают ответ ЛИБО (при сбое генерации ниже по потоку) честную GUPPI-заметку, но НИКОГДА не
  молчание. Путь читает `signals()` (сырое восприятие), а не `decide()` (несущий RNG/политику);
  `rng` принят только ради паритета сигнатуры и намеренно НЕ используется (это и есть инвариант).
  Это чинит живой регресс, где простой follow-up в собственном пространстве Боба молча
  проглатывался прежней raw-only проверкой фокуса (только `per_message is DIRECTED_TO_BOB`).
- **Периферия (только НАСТОЯЩИЙ многолюдный ambient / directed-to-other).** Всё, что
  `_directed_engage` НЕ отобрал (в т.ч. genuine ambient при третьем участнике или явное обращение к
  другому), — дискреционная периферия: одно богатое рефлексивное чтение → чистый вердикт. Боб
  «читает комнату», как человек: понимает ситуацию, кто с кем говорит, настроение комнаты и — как
  ЛИЧНОСТЬ — стоит ли вмешиваться. Сбой чтения безопасно дефолтит в молчаливый IGNORE (floor
  продвигается, БЕЗ GUPPI-заметки — это не фокальная гарантия).

**Пять компонентов, зеркалящих судью BOB-049 один-в-один:**

1. **VO + порт (`room_reading.py`).** `RoomReading` — неизменяемый ИТОГ одного чтения: `situation`
   (короткая фраза, что происходит), `pairings` (кто-с-кем, author-labelled), `room_mood`,
   `intent`, `addressee_id`, `salience` («стоит ли влезть»), опциональный `emoji`, `wants_web` и
   внутренний `reason` (только логи). `RoomReadingContext` — неизменяемый ВХОД: сообщение,
   отправитель как соц. контекст, общий author-labelled тред (BOB-058), mood-тон, структурные +
   floor-хинты (`addressivity`/`mentions_bob`/`reply_to_bob`/`others_present`/`floor_engaged` +
   `floor_holder`/`floor_participant` из Среза 1.2) и `interest` по значению — каждое поле сигнал,
   ни одно не override. `ReflectiveIntent` — REPLY/REACT/IGNORE/INITIATE/SELF_CHECK.
   🔴 `RoomMood` (PLAYFUL/WARM/NEUTRAL/SOMBRE/TENSE/HEATED) несёт `valence`/`polarization` как
   plain-float свойства, которые Срез W.2 потребляет ПО ЗНАЧЕНИЮ в тон (surfaced на `_ReplyGate`,
   `RoomMoodModulator` за `presence.room_mood.enabled`) — без импорта conversation в
   personality (ребро остаётся однонаправленным). `RoomReader` — инъектируемый порт
   `read(ctx) -> RoomReading`.
2. **Wire-протокол (`room_reading_wire.py`).** Model-facing половина, чистая (без I/O и RNG):
   `build_room_prompt` сворачивает контекст в Tier-1 user-prompt, `ROOM_READ_SYSTEM_PROMPT` задаёт
   задачу и размеченный контракт. 🔴 `parse_room_reading` БРОСАЕТ `RoomReadingParseError` на мусоре
   (отсутствующий/битый `intent` или `salience`) вместо молчаливого дефолта; мягкие поля деградируют
   мягко (`mood`→NEUTRAL, `addressee`→None, `wants_web`→False). `salience` парсится знаковым
   float-regex и клампится в `[0, 1]` (отрицательное → 0, не читается как модуль).
3. **Use-case (`usecases/read_the_room.py`).** `ReadTheRoom` — тонкий application-use-case над
   портом, зеркало `DecideResponse`: собирает куски периферийного хода в `RoomReadingContext` и
   делегирует единственное богатое чтение инъектированному `RoomReader`; своей политики не держит.
4. **Tier-1 адаптер (`adapters/room_reader.py`).** `LlmRoomReader` — тонкая оболочка: чистый билдер
   промпта → router на Tier-1 модели (задача `ROOM_READ` — «не жалеть LLM» на рефлексии) → чистый
   парсер. НЕ глотает сбои: `RoomReadingParseError` или ошибка модели/роутера ПРОБРАСЫВАЮТСЯ, чтобы
   периферийный гейт безопасно ушёл в молчаливый IGNORE.
5. **Чистое ядро вердикта (`room_verdict.py`).** 🔴 Несущий инвариант всего среза: *LLM ВЕРБАЛИЗУЕТ
   чтение, а это чистое ядро РЕШАЕТ вердикт* — детерминированное отображение без I/O и RNG (как
   `addressivity.decide_response` на легаси-пути). `decide_from_reading` читает ТОЛЬКО reading (все
   сигналы уже свёрнуты в него; параметр `signals` намеренно опущен — иначе цикл domain→application):
   `salience < SALIENCE_THRESHOLD` (0.35) → IGNORE, что бы ни сказал intent; иначе REACT→REACT(+emoji),
   IGNORE/SELF_CHECK→IGNORE, REPLY/INITIATE→REPLY. `wants_web` едет на REPLY-вердикте как `force_web`,
   `addressee_id` — для floor-пасса / reply-to.

**Проводка в гейте.** `TurnGate.__init__` получил `read_the_room: ReadTheRoom | None = None`; при
проводке и распознанном отправителе `gate()` уходит в `_reflective_gate`, который зовёт чистый
`_directed_engage(signals)`: True → детерминированный `_ReplyGate` (набор выше), иначе — периферийное
`_read_room` → `_act_reflective`. Без проводки/распознанного отправителя — байт-идентично судья
BOB-049 или легаси. `_ReplyGate` получил `force_web: bool = False` (`True`
только когда периферийный read выставил `wants_web`) и `room_mood` (surfaced на периферийном REPLY,
чтобы `RoomMoodModulator` потребил его по значению в тон, Срез W.2). Периферийное чтение собирается
в `_read_room` (общий тред + структурные/floor-хинты + interest), сбой ловится в `except Exception`
→ молчаливый IGNORE.

**Ритм-потолки и бюджет серии (Срез W).** `gate()` / `_reflective_gate` / `_act_reflective`
получили `series_ceiling` (по умолчанию `ENGAGE`) — потолок из batch top-k плана
(`plan_series_actions`, за `presence.series_budget.enabled`), который режет ambient-REPLY
рефлексивного пути, НО никогда не трогает детерминированный ход (INV-1: `_directed_engage`
короткозамыкает в `_ReplyGate` выше и `series_ceiling`, и `barge_ceiling`). `barge_ceiling`
(за `presence.rhythm.enabled`) домножает вероятность ambient-барджа на долю эфира на периферийном
REPLY; на детерминированном пути потолок НЕ консультируется, RNG не берётся (INV-4).

**`wants_web` (C11) переиспользует `VerifyStep`.** `VerifyStep.note(..., forced=False)` получил флаг
`forced`: когда рефлексивный read выбрал сходить проверить, судья волатильности ПРОПУСКАЕТСЯ (Боб уже
решил), и текст хода гонит ОДИН поиск по ТОМУ ЖЕ существующему verify/web-шву (`_verdict` строит
утвердительный `VolatilityVerdict` прямо из текста). Никакого нового веб-шва; отсутствие провайдера
по-прежнему коротит в `""`. `HandleMessage` читает `gate.force_web` и прокидывает `forced=force_web`
в `self._verify.note(...)`.

**🔴 Флаг `presence.reflective` (по умолчанию OFF).** Рефлексивный читатель собирается в
`runtime/composition.py` только при `presence.reflective` — весь эпик «человеческое групповое
присутствие» отгружается ОДНИМ куском (блокер владельца), поэтому продакшн остаётся на судье BOB-049,
пока эпик не готов целиком, а сама развилка test-driven. OFF → `read_the_room=None` → рефлексивная
ветка `TurnGate` пропускается (гард `read_the_room is not None`), поведение байт-идентично.
`TaskType.ROOM_READ` добавлен в `llm_router` (Tier-1).

*Заметка на будущее (не dead-code, forward-scaffolding):* `RoomReading.addressee_id` /
`ReflectiveVerdict.addressee_id` парсятся и несутся, но `_act_reflective` пока их не использует
(floor-сигнал ответа берёт сырой `signals.directed_to_id`); reply-to-нить прокладывается в позднем
срезе.

### Холистический stream-read пачки (BOB-072, за `presence.stream_read`, OFF)

Второй, ПАЧЕЧНЫЙ шов рядом с per-message-чтением («компонент рядом»): вместо одного Tier-1 read
на КАЖДОЕ ambient-сообщение (скриптованный top-k) Боб читает ЦЕЛУЮ осевшую вспышку ambient-болтовни
разом и решает — по смыслу, как человек, догоняющий групповой чат, — что каждое сообщение
заслуживает (слово, лайк или молчание). 🔴 Никакой скриптованности: промпт не просит «ответь на
первое/самое салиентное», а просит понять, что именно ТРЕБУЕТ реакции. 🔴 Focal-развилка (прямое
обращение) детерминирована и отделяется ДО этого шва (INV-1) — здесь всё ambient.

1. **VO + порт (`room_reading.py`).** `BatchAmbientMessage` — одно атрибутированное ambient-сообщение
   (`sender_id`/`sender_name`/`text`/`ts` + per-message floor/interest-хинты). `BatchRoomReadingContext`
   — вход: вспышка в порядке прибытия + общий author-labelled тред (read-only) + mood-тон +
   `others_present`. `BatchRoomReading` — итог: по ОДНОМУ `RoomReading` на сообщение В ТОМ ЖЕ ПОРЯДКЕ
   + `room_mood` по всей вспышке + `reason` (логи). Порт `BatchRoomReader.read(batch_ctx) ->
   BatchRoomReading` — инъектируемый, участник-агностичный (готов к репликам-Бобам).
2. **Wire (`room_reading_wire.py`).** `build_batch_room_prompt` сворачивает атрибутированный поток в
   пронумерованный Tier-1 промпт; `BATCH_ROOM_READ_SYSTEM_PROMPT` задаёт «прочитай ВЕСЬ поток и реши по
   каждому». 🔴 В ОТЛИЧИЕ от `parse_room_reading`, `parse_batch_reading(raw, count)` ТОЛЕРАНТЕН: битый
   или отсутствующий блок деградирует в безопасный молчаливый IGNORE ДЛЯ ТОГО сообщения, а целиком
   нечитаемый ответ — в all-IGNORE нужной длины (Боб никогда не действует по угаданному пачечному read;
   план всегда ровно `count` чтений). Блоки разделяются строкой `---`; per-блок парсинг переиспользует
   `parse_room_reading`.
3. **Чистое ядро (`room_verdict.py`).** `decide_batch(readings)` поднимает `decide_from_reading` над
   всей пачкой: ТА ЖЕ детерминированная политика (порог `SALIENCE_THRESHOLD` сначала, затем
   intent-маппинг) к каждому чтению в порядке прибытия. Семантика — в read, ПОЛИТИКА — чистая проекция;
   пустая пачка → пустой план. Mutation-цель (как per-message путь один-в-один).
4. **Tier-1 адаптер (`adapters/room_reader.py`).** `LlmBatchRoomReader` — тонкая оболочка над одним
   `ROOM_READ`-вызовом (liveness > экономия): пустая вспышка коротит без вызова модели; ответ парсится
   толерантно (garbage → безопасный all-IGNORE), а ошибка модели/роутера ПРОБРАСЫВАЕТСЯ для
   application-фолбэка (бид .2).

**🔴 Флаг `presence.stream_read` (bare bool, по умолчанию OFF).** Собирается в
`runtime/wiring/stream_read.py` (`build_batch_room_reader` — ЕДИНСТВЕННОЕ место чтения флага):
OFF → `None` (hot-path байт-идентичен, per-message top-k), ON → `LlmBatchRoomReader`. Врезка в
`_handle_batch`, что ПОТРЕБЛЯЕТ компонент, — отдельный бид .2; здесь компонент лишь появляется за
флагом.

### Use-case и адаптеры

`DecideResponse` (`usecases/decide_response.py`) — тонкий application-use-case над судьёй
ответа: собирает контекст хода (сообщение, отправитель как соц. контекст, per-person тред,
структурные hints, mood-тон) в `ResponseContext` и делегирует единственное семантическое
решение инъектированному `ResponseJudge`; своей политики не держит.

**Коллабораторы хода (BOB-062.6b, #9).** Декомпозиция God-use-case `handle_message` вынесла
разговорную логику хода в когезивные method-object'ы этой вертикали, собираемые в
`HandleMessage.__init__` из уже инъектированных швов. 🔴 **Seeded-розыгрыши хода берут rng из
per-turn `TurnScope` (BOB-066 Срез 2.1, INV-4).** Под intake-развязкой разные чаты идут на
разных воркер-тасках параллельно, поэтому оркестратор прокидывает в каждый seeded-draw-сайт
турна опциональный `rng` (`decide` / `decide_engagement` / `decide_verbosity` / `gate` /
`guard`) — розыгрыш засеян координатами `(base, chat_id, message_id)`, так что конкурентные
чаты никогда не делят один поток розыгрышей, а ход воспроизводим независимо от порядка
диспетчеризации. Параметр опционален: при прямом unit-вызове без `rng` коллаборатор
откатывается на инъектированный per-boot rng (`self._rng`), поэтому legacy-поведение
байт-идентично.
- `AddressivityPerceiver` (`addressivity_perceiver.py`) — восприятие адресности + решение,
  берёт ли Боб ход (`decide(event, interest, *, rng=None)` / `signals`, поверх `FloorManager`
  для BOB-025 continuity-raise; legacy-лестница засевается турновым `rng`).
  `_AddressivitySignals` несёт `floor_holder` (кто держит floor, `None` на инертном шве) и
  `floor_participant` (в нити ли этот говорящий) — хинты для рефлексивного read (BOB-066 .1).
- `FloorManager` (`floor_manager.py`) — resolve + advance разговорной реплики
  (`resolve_effective` / `advance_after_turn`), на примитивных id (без inward-зависимости на
  application-событие). `resolve_effective(chat_id, per_message, *, sender_id)` возвращает
  `FloorResolution` (`effective` адресность, поднятая по floor + текущий `holder` + `participant`
  — признан ли говорящий); инертный шов (стор не проведён / floor выключен) отдаёт
  `effective == per_message`, `holder is None`, `participant is False` (поведение BOB-023).
- `EngagementModel` (`engagement_model.py`) — аппетит + verbosity + after-turn feedback
  (`topic_interest` / `decide_engagement` / `decide_verbosity` / `apply_feedback` /
  `guard_reply_length`); возвращает personality-VO. `decide_engagement` и `decide_verbosity`
  принимают опциональный турновый `rng` (граница FULL/PLAYFUL и брезгливый бросок verbosity).
- `RecallAssembler` (`recall_assembler.py`) — воспроизведение общего треда + лёгкая
  absence/acknowledgment-текстура (`replay_recent_thread` / `absence_for` /
  `acknowledgment_for`; 🔴 `acknowledgment_for` читает notable-reaction маркер ДО seeded-броска,
  consume-once).
- `VerifyStep` (`verify_step.py`) — предответная эпистемическая проверка (`note`), возвращает
  turn-local заметку; per-turn интерим-анонсер строится из `chat_id` хода через инъектированную
  фабрику. `note(..., *, forced=False)`: `forced=True` (рефлексивный `wants_web`, C11) пропускает
  судью волатильности и гонит ОДИН поиск по тому же verify/web-шву.
- `ReadTheRoom` (`read_the_room.py`) — тонкий application-use-case над портом `RoomReader`
  (BOB-066 Срез 2.2): собирает периферийный контекст (сообщение + отправитель + общий тред + mood-тон
  + структурные/floor-хинты + interest) в `RoomReadingContext` и делегирует одно богатое чтение;
  вердикт решается чисто ниже (`decide_from_reading`). Инъектируется в `TurnGate` (и оттуда в
  `HandleMessage`) через `read_the_room` kwarg; `None` = легаси-поведение (судья BOB-049).
- `TurnGate` (`turn_gate.py`) — тонкий координатор гейта хода (reply/react/silent) над
  `AddressivityPerceiver` + `FloorManager` + судьёй + `EssentialRunner`; persist / owner-activity
  прокинуты колбэками (гейт не держит политики персиста). `gate(..., *, rng=None)` прокидывает
  турновый `rng` в legacy-розыгрыш адресности. 🔴 `read_the_room: ReadTheRoom | None = None` (BOB-066
  Срез 2.2): когда читатель проведён И отправитель распознан, в самом верху `gate()` включается
  развилка `_reflective_gate` — чистый `_directed_engage(signals)` отбирает детерминированный ход
  (сырое `DIRECTED_TO_BOB` / floor-continuity / 1:1-ambient → `_ReplyGate`), остальное уходит в
  периферийное `_read_room` → `_act_reflective`; иначе — судья BOB-049 / легаси байт-идентично.
  `_ReplyGate.force_web` несёт рефлексивный `wants_web` в caller. 🔴 **Персист рефлексивного
  non-reply (BOB-071 Seam B):** осознанные рефлексивные ветки без ответа `_advance_silent`
  (IGNORE → `(промолчал)`) и `_react_turn` (REACT → `(реакция: <emoji>)`) теперь персистят
  входящее сообщение в `episodic_log` симметрично judge-пути `_act_non_reply` — включая сбой
  чтения комнаты (`reading is None` уходит в `_advance_silent`, а не в голое продвижение floor).
  Так реплика участника группы попадает в тред даже при сознательном рефлексивном IGNORE/REACT
  («читаю комнату, но помню разговор»), и тред не рвётся. В отличие от judge-пути owner-activity
  здесь НЕ штампуется — периферийное чтение не обязательно означает взаимодействие owner'а.
- `AntiRepeatGuard` (`anti_repeat_guard.py`) — регенерация повтора/тика (`guard`) + кольцо
  закрывающих (`log_closer` / `closer_anti_tic`). 🔴 Принимает `VoiceComposer.compose` как
  `compose`-callback (по значению, не импорт — цикл compose↔guard замкнут БЕЗ
  `conversation → personality` импорта); `verify_note` / `closer_nudge` текут turn-local
  аргументами через тот же колбэк. `guard(..., *, rng=None)` прокидывает турновый `rng`
  в КАЖДУЮ регенерацию, поэтому пере-компоновка тянет из ТОГО ЖЕ per-turn потока (INV-4).

`LlmResponseJudge` / `LlmVolatilityJudge` / `LlmInterimLineGenerator` (`adapters/`) — Tier-0
реализации портов (билдер промпта + router + парсер). `LlmRoomReader` (`adapters/room_reader.py`) —
Tier-1 реализация `RoomReader`: тот же тонкий шов (билдер + router на `ROOM_READ` + парсер), но
пробрасывает сбои наверх для безопасного молчаливого IGNORE периферийного гейта.
`SqliteConversationFloorStore` — per-thread
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
  детерминирован по seeded-RNG — под intake-развязкой это per-turn `TurnScope.rng`
  (координаты `(base, chat_id, message_id)`), поэтому конкурентные чаты не делят поток
  розыгрышей (INV-4).
- **Floor продвигается и распадается корректно.** AMBIENT→DIRECTED_TO_BOB только пока floor=БОБ
  жив; явный поворот к другому / тайм-аут / серия безметочных без Боба снимают floor, возвращая
  осторожную ambient-логику BOB-023; floor — свойство ТРЕДА (chat_id + thread_id), не человека.
- **Floor-по-говорящему аддитивен и legacy-безопасен.** Пустой набор `participants` (`()`,
  дефолт VO + `NULL` в SQLite) = legacy raise-any — 1:1 owner↔Боб сохраняет поведение BOB-025 без
  регресса; непустой набор поднимает безметочную реплику только признанного говорящего (или с
  неизвестным `sender_id`, fail-safe), а посторонний остаётся AMBIENT (Боб не перехватывает
  чужое). Набор dedup'ится, ограничен потолком 8 (вытесняется старейший) и сбрасывается при
  повороте к другому / распаде.
- **Адресность — perception, не решение.** `classify_addressivity` чист и детерминирован; над
  ним политика отклика (судья), сам детектор доступ/отклик не решает. Вокатив «Боб» ловится в
  любой позиции реплики только при границе слова слева И терминаторе-обращения (`,`/`:`/`!`/`?`)
  либо трейлинг-контексте справа — тире-композит и падежи остаются AMBIENT (консервативно,
  без ложных срабатываний, BOB-069). Точка `.` справа даёт вокатив ТОЛЬКО при запятой-обращении
  вплотную слева (`_has_left_comma_context`): «Привет, Боб.» → обращение, «Это Боб.» → AMBIENT
  (BOB-071); сознательное известное ограничение — перечисление «…, Петя, Боб.» ложно-положительно
  (редкий доброкачественный случай, «лучше ответить, чем ложно промолчать»).
- **Анти-тик консервативен.** `is_user_repeat` — только точный матч после нормализации (Боб не
  обвиняет owner'а зря); `is_bob_repeat` проверяет всё окно (повтор «через ход» не проскакивает);
  `CloserLog` ловит мотив, рассеянный по сессиям.
- **Судьи по смыслу, безопасный дефолт.** Структурные сигналы — входы, не override-правила;
  VolatilityJudge при неоднозначности дефолтит `needs_check=False` (US-2 «не зануда»); парсеры
  бросают на мусоре, а не молча дефолтят некорректно.
- **Цель ответа аддитивна и детерминирована.** `resolve_outgoing_target` чист и тотален (одни и
  те же сигналы → одна и та же цель); голый `OutgoingTarget` и `reply_to_message_id=None` на всех
  путях шлюза = сегодняшняя отправка в топик без цитаты (нулевой регресс). Цитата появляется ровно
  при третьем участнике и НЕ в фокальном 1:1.
- 🔴 **INV-1: прямое обращение → ответ-или-заметка, никогда молчание.** Чистый `_directed_engage`
  отбирает детерминированный ход на эффективной адресности — сырое `DIRECTED_TO_BOB` (INV-1),
  floor-continuity (`effective` поднят floor'ом) и 1:1/собственное пространство (`AMBIENT` без
  третьего) — и замыкает его на детерминированный `_ReplyGate` ДО рефлексивного read, RNG и
  потолка доли голоса; ни одно условие не может замолчать эту ветку, а сбой генерации ниже по
  потоку становится честной GUPPI-заметкой, а не тишиной. Путь не берёт ни одного розыгрыша
  (`rng` намеренно не используется). Только genuine многолюдный ambient / directed-to-other уходит
  в дискреционное рефлексивное чтение.
- 🔴 **Двуклассовое расщепление сбоя.** Периферийный сбой чтения (`RoomReadingParseError` /
  ошибка модели) ловится → молчаливый IGNORE + продвижение floor, БЕЗ GUPPI-заметки (INV-2 —
  периферийная рефлексия падает тихо). Фокальный сбой генерации → GUPPI-заметка. `parse_room_reading`
  всегда БРОСАЕТ на мусоре (`intent`/`salience`), `LlmRoomReader` пробрасывает — половины никогда не
  дефолтят молча.
- 🔴 **LLM вербализует, ядро решает.** `decide_from_reading` чист, детерминирован и читает ТОЛЬКО
  `RoomReading`: `salience < SALIENCE_THRESHOLD` → IGNORE вне зависимости от intent; ниже порога Боб
  не влезает в комнату, к которой в этот ход не относится. `RoomMood.valence`/`polarization` —
  plain-float, потребляются Срезом 2.4 по значению (ребро `conversation → personality` остаётся
  однонаправленным).
- **Рефлексивная развилка за флагом, OFF = без изменений.** `presence.reflective` (по умолчанию
  OFF) → `read_the_room=None` → рефлексивная ветка `TurnGate` пропускается, судья BOB-049 работает
  байт-идентично; эпик отгружается целиком.
- 🔴 **Non-reply-ход персистит вход, тред цел (BOB-071 Seam B).** Все ветки без ответного текста —
  judge-путь `_act_non_reply` и рефлексивные `_advance_silent` / `_react_turn` (в т.ч. сбой чтения
  комнаты) — персистят входящее сообщение в `episodic_log` (`(промолчал)` / `(реакция: <emoji>)`),
  поэтому осознанный IGNORE/REACT участнику группы не рвёт нить. Двойного персиста нет: reply-путь
  персистит downstream, non-reply — в гейте, взаимоисключимо. Пишется только эпизодическая запись,
  без owner-факта (гость не попадает в память owner'а, BOB-019); на рефлексивном пути, в отличие
  от judge, owner-activity НЕ штампуется.

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
  `resolve_addressivity`/`is_floor_participant` (→ `ConversationFloor` c `participants`),
  `brevity.decide_verbosity` (→ `Verbosity`), `engagement.decide_engagement`
  (→ `EngagementLevel`) + `ConversationalFatigue`, `zone_classifier.TasteZoneClassifier`,
  `conversation.is_user_repeat`/`is_bob_repeat`/`is_recurring_closer_tic`,
  `response_choice.ResponseChoice`/`ResponseJudge`, `volatility_judgment.VolatilityJudge`,
  `interim_line.build_interim_line_user_prompt`,
  `outgoing_target.resolve_outgoing_target` (→ `OutgoingTarget` c `reply_to_message_id`/`addressee_id`),
  `room_reading.{RoomReading,RoomReadingContext,RoomMood,ReflectiveIntent,RoomReader}`,
  `room_reading_wire.{build_room_prompt,parse_room_reading,ROOM_READ_SYSTEM_PROMPT,RoomReadingParseError}`,
  `room_verdict.decide_from_reading` (→ `ReflectiveVerdict` c `force_web`/`addressee_id`) + `SALIENCE_THRESHOLD` (BOB-066 Срез 2.2).
- Use-case: `usecases.DecideResponse`; коллабораторы хода `usecases.{TurnGate,
  AddressivityPerceiver, FloorManager, EngagementModel, RecallAssembler, VerifyStep,
  AntiRepeatGuard, ReadTheRoom}` (BOB-062.6b / BOB-066 Срез 2.2); `FloorManager.resolve_effective`
  → `FloorResolution` (`effective`/`holder`/`participant`, BOB-066 .1); `VerifyStep.note(forced=)`
  (C11); `TurnGate(read_the_room=)` — фокус/периферия-развилка.
- Адаптеры: `LlmResponseJudge`, `LlmVolatilityJudge`, `LlmInterimLineGenerator`, `LlmRoomReader`
  (Tier-1 `RoomReader`, задача `ROOM_READ`), `SqliteConversationFloorStore`, `SqliteCloserLog`.

Композиция (wiring floor/судей/interim в ход `handle_message`, инъекция портов) — в
композиционном корне `app.py`; коллабораторы хода собираются в `HandleMessage.__init__` из
инъектированных швов (интеграция методов в `handle_message` завершена — срез .6b). Долговечная
запись в SQLite — через kernel `SqliteMemoryRepo` (`infrastructure/persistence/`, до среза .7).

## Тесты

Тесты покрывают инварианты и поведение (identical после переезда):

- Домен: `tests/domain/personality/test_addressivity.py`, `test_addressivity_policy.py`,
  `test_conversation_floor.py`, `test_brevity.py`, `test_engagement.py`,
  `test_zone_classifier.py`, `test_conversation.py`, `test_response_judgment.py`,
  `test_volatility_judgment.py`, `test_interim_line.py`;
  `tests/domain/conversation/test_outgoing_target.py` (truth-table reply-to + mutation-покрытие);
  `tests/domain/conversation/test_room_reading.py`, `test_room_reading_wire.py`, `test_room_verdict.py`,
  `test_room_verdict_determinism.py` (рефлексивные VO / wire-парсер / чистый вердикт, mutation-ready).
- Use-case: `tests/application/usecases/test_decide_response.py`;
  `tests/conversation/usecases/test_read_the_room.py`, `test_turn_gate_reflective.py`,
  `test_turn_gate_inv1_matrix.py` (INV-1 матрица: прямое обращение всегда отвечено), `test_turn_gate_clamp.py`,
  `test_verify_step_forced.py`, `test_verify_step_forced_hedge.py` (C11 `forced=`).
- Адаптер рефлексивного чтения: `tests/infrastructure/llm/test_room_reader.py`.
- Приёмочный BDD «чтение комнаты»: `tests/acceptance/features/read_the_room.feature` +
  `tests/acceptance/steps/test_read_the_room.py` (INV-1 фокус всегда отвечен даже когда судья
  игнорит; ambient низкой salience → молчание).
- Приёмочный BDD reply-to: `tests/acceptance/features/reply_to.feature` +
  `tests/acceptance/steps/test_reply_to.py` (цитирует при 3+ участниках, не цитирует в 1:1 через
  FakeGateway).
- Приёмочный BDD floor-по-говорящему: `tests/acceptance/features/floor_by_speaker.feature` +
  `tests/acceptance/steps/test_floor_by_speaker.py` (реплика участника нити продолжает диалог,
  реплика постороннего не перехватывается — через FakeGateway).
- Адаптеры: `tests/infrastructure/llm/test_response_judge.py`, `test_volatility_judge.py`,
  `test_interim_line.py`; `tests/infrastructure/persistence/test_conversation_floor_store.py`,
  `test_closer_log_store.py`.
- Layer-guard модуля: `tests/conversation/test_layering.py`.
