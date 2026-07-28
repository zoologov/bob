<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.6 — «personality + conversation + декомпозиция handle_message» (Фаза 3, срез 6/8)

> **Status:** Approved (структура), .6a Approved · .6b — свой BRIEF после мержа .6a
> **Created:** 2026-07-28
> **Type:** feature (под-эпик: .6a + .6b) · BOB-Issues #15, #16 (personality-часть), #9
> **Родитель:** `bob-8r4.6` · Контекст: эпик `RFC/CONTEXT` + прецеденты .1–.5 + генератор правил (.4) + приём разрыва цикла (.5)

---

## Решение по структуре (утв. owner — критерий «максимально правильно по DDD/cohesion»)

Срез .6 = **два PR**:
- **.6a** — установить ДВА чистых bounded-context: `src/bob/personality/` + `src/bob/conversation/` + разрыв
  цикла (правильной однонаправленной зависимостью). Behavior-preserving.
- **.6b** — декомпозиция `handle_message.py` (#9, 3524 стр, God use-case) волнами 0→4. Отдельный BRIEF.

**Почему два bounded-context (а не один merged):** personality («кто Боб есть»: mood/taste/disposition/
fascination/negotiation/expression/voice/reaction-meaning/reflection) и conversation («как ведётся ход»:
адресность/floor/brevity/engagement/судьи/interim/анти-тик) — разные ubiquitous language + высокая
внутренняя когезия каждого. Текущий цикл `voice↔brevity↔expression` — **design smell, не признак единого
контекста**. Слить = лечить симптом; правильно — починить границу.

---

## .6a — два vertical + разрыв цикла (ТЕКУЩИЙ)

### 🔴 Разрыв цикла (правильное направление: conversation → personality однонаправленно)

В конвейере хода conversation решает *если/насколько* отвечать → personality решает *как сказать*.
personality — стабильное ядро; **conversation зависит от personality**, не наоборот. Единственные
«неправильные» рёбра — `voice.py:35-36 → brevity.Verbosity, engagement.EngagementLevel` (P→C, runtime
dict-ключи).

**Механизм (минимальный корректный срез):** перенести *определения* enum `Verbosity` + `EngagementLevel`
из `conversation`(brevity/engagement) в **personality-вокабуляр выражения** (они — грани того, *как
характер выражается*, рядом с `ExpressionMode`/`FormHint`). Вычисляющая логика `BrevityThresholds`/
`FatigueRates`/`decide_*` ОСТАЁТСЯ в conversation и теперь возвращает personality-VO. Тогда:
- `voice → Verbosity/EngagementLevel` = внутри-personality ✓
- `brevity/engagement (conversation) → Verbosity/EngagementLevel (personality)` = conversation→personality ✓
- `brevity → FormHint (personality)` = conversation→personality ✓ (FormHint уже в expression)
Цикла нет. 🔴 **Тела функций не меняются** — двигаются только определения enum + импорт-пути. Проба на
`no-dependency-cycles` (как в .5) обязательна.

### Целевая структура (два module-vertical)

```
src/bob/personality/          # «кто Боб есть»
  ports.py            ← ports/personality.py (MessageReactor/ReflectionReader/Fascination/NotableReaction)
  soul mood mood_taste taste taste_evolution disposition fascination phantom_evolution
  language profanity expression(+Verbosity/EngagementLevel) voice reaction reaction_aloud
  reaction_effect reaction_meaning reaction_judgment negotiation reflection absence   # layer=domain
  usecases/  update_mood_from_text apply_reflection reappraise_reflection reflection_parser
             evolve_fascination evolve_phantoms fascination_sources perceive_reaction  # layer=application
  adapters/  reaction_judge fascination_store notable_reaction_store                   # layer=infrastructure
src/bob/conversation/         # «как ведётся ход»
  ports.py            ← ports/conversation.py (ConversationFloorStore, CloserLog) + ZoneClassifier
  conversation conversation_floor addressivity brevity engagement zone_classifier
  interim_line response_choice response_judgment volatility_judgment                   # layer=domain
  usecases/  decide_response                                                            # layer=application
  adapters/  response_judge volatility_judge interim_line conversation_floor_store closer_log_store
```

### 🔴 Cohesion-раскол спорных файлов (по ответственности)
- `negotiation` → **personality** (стойка/убеждённость характера; `social.relationship` тянет `Stance` —
  social→personality, allowed).
- `reaction_judgment` → **personality** (производит `MoodDelta` — эмоц. отклик характера на реакцию).
- `zone_classifier` (+ ZoneClassifier порт) → **conversation** (классифицирует топик хода; зависит от
  `negotiation`/`taste` personality = conversation→personality ✓).
- `response_judgment`/`volatility_judgment` → **conversation** (решения хода).

### Внешние прод-правки (import-пути, не логика)
`app.py` (~14 config-объектов), `handle_message.py` (~18 personality + все conversation — ТОЛЬКО импорт-
пути, методы не трогаем — это .6b), `heartbeat.py`, `proactivity/{engine,decision,urge}`, `memory/
consolidate_memory`, `social/{relationship,relationship_sources}`, 8 infra-адаптеров, `ports/__init__` шим,
`ports/{personality,conversation}.py` → `personality/ports.py`+`conversation/ports.py`. Тесты (~много) — импорты.

### Kernel (вариант C) — soul_store уже в social; SOUL value-object в personality. Сторы через seam.

## Беады .6a (роль-суб-беады под `bob-8r4.6`)

- **`.1` dev (разрыв цикла — ИЗОЛИРОВАННО первым)** — перенести Verbosity/EngagementLevel enum-определения
  в personality expression-вокабуляр (файлы ещё в domain/personality — БЕЗ переезда модулей); voice не
  тянет conversation-enum runtime. Behavior-preserving, pytest зелёный. Проба no-dependency-cycles.
- **`.2` dev (переезд)** — `git mv` в `src/bob/personality/` + `src/bob/conversation/` (два vertical, cohesion-
  раскол выше); импорты внешних + аннотации feature=personality/conversation + layer=; узлы module-vertical + reindex.
- **`.3` dev (правила)** — генератор (2 новых узла personality/conversation) → правила границ; note-блок
  legalized (conversation→personality однонапр., cross-модульные). 🔴 no-dependency-cycles зелёный. lint --strict.
- **`.4` test** — pytest + инварианты (🔴 voice-тон идентичен после переноса enum; conversation-судьи; floor;
  multi-party/cross-sender) + механика правил (personality↔conversation изоляция + проба цикла). beadloom ci.
- **`.5` review** — разрыв цикла behavior-preserving + два чистых bounded-context + cohesion-раскол верен;
  вердикт готовности к .6b (что осталось в handle_message).
- **`.6` tech-writer** — SPEC personality + SPEC conversation; закрыть #15 + #16(personality); Gate.

## Критерии приёмки .6a

- Два vertical `personality/` + `conversation/`; цикл разорван (conversation→personality однонапр.,
  no-dependency-cycles зелёный + проба); Verbosity/EngagementLevel в personality; voice-тон идентичен.
- `pytest` зелёный (поведение идентично); `ruff`/`mypy --strict`; `beadloom ci` зелёный.
- handle_message.py НЕ декомпозирован (только импорт-пути) — это .6b. BOB-Issues #15 + #16(personality) закрыты.

## .6b — декомпозиция handle_message #9 (после мержа .6a, свой BRIEF)

Волны 0→4 (разведка): 0 free-функции → 1 листовые (DiagramSender/EssentialRunner/FloorManager/VerifyStep/
PreComposeGate) → 2 (Addressivity/Engagement/Mood/Social/RecallAssembler) → 3 ядро (VoiceComposer+
AntiRepeatGuard, callback-цикл) → 4 (TurnGate + тонкий handle()). 🔴 Инварианты: verify-once turn-local
(НЕ атрибут!), единственная регенерация, essential-vs-decorative, floor-на-всех-ветках, seeded-RNG порядок,
shared-instance diagram_sink. 🔴 НЕ менять `_build`-хелпер (360 тестов) — коллабораторы собирать в
`HandleMessage.__init__`. Каждая волна — коммит, зелёные тесты между. #32 floor-персонализацию можно тут.
