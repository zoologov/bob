<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.6b — «Декомпозиция handle_message.py (#9)» (Фаза 3, срез 6b/8)

> **Status:** Approved
> **Created:** 2026-07-28
> **Type:** feature · часть b среза .6 · BOB-Issues #9
> **Родитель:** `bob-8r4.6` · Предшественник: .6a (PR #84, два bounded-context) в main

---

## Проблема

`src/bob/application/usecases/handle_message.py` — **3524 строки**, God use-case: 1 класс `HandleMessage`,
~63 метода, ~50 инъекций-seam. Сердце диалога Боба. #9: растворить в тонкий оркестратор `handle()`
(~40-60 строк) + когезивные коллабораторы, разложенные по чистым модулям (personality/conversation/
memory/social/capabilities — все собраны в .1–.6a).

## 🔴 Принципы (review .5: «настоящая КОГЕЗИЯ, не перенос монстра»)

- **method-object рефактор**, behavior-preserving: тот же вызов из `handle()`, те же аргументы, `git diff` =
  перемещение тел + `self.` → `collaborator.`.
- 🔴 **НЕ менять `_build`-хелпер** (360 тестов идут через него) — коллабораторы собирать внутри
  `HandleMessage.__init__` из уже инжектированных seam. Тогда 360 тестов валидны без правок = критерий
  behavior-preserving.
- 🔴 **turn-local state — через аргументы, НИКОГДА не атрибут** коллаборатора: `verify_note` (singleton-leak
  риск!), `closer_nudge`, `recalled`, `is_guest`, `reply`, `chat_id`, announcer. Иначе протечёт между
  ходами/юзерами (класс — shared singleton).
- 🔴 **seeded-RNG порядок** draw'ов между коллабораторами обязан сохраниться (скрытый ordering-инвариант;
  seed-sweep тесты поймают смещение).
- Каждая волна — коммит, зелёные 360 тестов между.

## Волны (из разведки декомпозиции)

- **Волна 0** (`.1` dev): 16 free-функций → `conversation/`-хелперы (`_assemble_shareable_context`,
  `_render_thread`, `_history_for_author`, `_user_turns`, `_author_key`, `_strip_recalled_closer`,
  `_stance_directive`, clamps…). Уже чистые — риск ~ноль.
- **Волна 1** (`.2` dev, листовые независимые): **DiagramSender** (capabilities), **EssentialRunner**
  (application, reliability-примитив), **FloorManager** (conversation), **VerifyStep** (conversation),
  **PreComposeGate** (coding/social — `_maybe_route_coding`/`_maybe_permission`).
- **Волна 2** (`.3` dev, средние): **AddressivityPerceiver** (conversation), **EngagementModel**+
  **MoodPerceiver** (personality), **SocialContext** (social — SocialModel-методы), **RecallAssembler**
  (conversation/memory).
- **Волна 3** (`.4` dev, 🔴 ЯДРО, highest-risk): **VoiceComposer** (personality/conversation — сначала
  выделить внутренний `GroundedAddons`: leak/callback/fascination/`_safe_addon`, потом composer) +
  **AntiRepeatGuard** (принимает `compose`-callback VoiceComposer'а — замыкает цикл compose↔guard).
  🔴 verify-once turn-local через аргументы; единственная регенерация; per-turn announcer локально.
  **Перед волной 3 (review .5-рек): явный инвариант-тест «единственная регенерация turn-local».**
- **Волна 4** (`.5` dev, оркестрация): **TurnGate** (тонкий координатор над Addressivity+judge+Floor+
  Essential) + финал `handle()` тонким оркестратором (~40-60 строк). 🔴 floor-advance на ВСЕХ ветках;
  порядок side-effects и seeded-draw'ов не сместить.

## 🔴 Критичные инварианты (чек-лист, из разведки — точные места)

| Инвариант | Держать |
|---|---|
| verify-once-per-turn | `verify_note` turn-local аргумент (НЕ `self.`); reuse в compose+guard; None=не вычислен, ""=judged-no-note |
| единственная регенерация | AntiRepeatGuard `_MAX_REGENERATIONS`; strip-fallback не пустить пустую строку |
| essential-vs-decorative | VerifyStep/GroundedAddons/DiagramSender/closer НИКОГДА через `_run_essential`; только judge+reply-gen |
| per-turn announcer | конструировать локально из per-turn chat_id; НЕ instance-атрибут |
| floor-advance на ВСЕХ ветках | SILENT/REACT/REACT_ONLY/act_non_reply/happy-path; `bob_replied` флаг |
| shared-instance diagram_sink | один инстанс, инжектится в DiagramSender И capability registry; push/drain на одном объекте |
| notable_reaction read→roll→clear | consume-once; unlucky не тратит draw |
| guest privilege | `is_guest` per-turn аргумент; гейтит tools+addons; recall/history НЕ гейтит (BOB-051) |
| seeded-RNG порядок | plan→engagement→verbosity→addressivity→surface/ack — порядок draw'ов сохранить |

## Беады .6b (роль-суб-беады под `bob-8r4.6`, продолжение нумерации .7+)

- **`.7` dev** — Волна 0 (free-функции → conversation-хелперы). pytest зелёный.
- **`.8` dev** — Волна 1 (DiagramSender/EssentialRunner/FloorManager/VerifyStep/PreComposeGate).
- **`.9` dev** — Волна 2 (Addressivity/Engagement/Mood/SocialContext/RecallAssembler).
- **`.10` dev** — 🔴 Волна 3 ЯДРО (GroundedAddons→VoiceComposer + AntiRepeatGuard callback). + инвариант-тест
  «регенерация turn-local» перед началом.
- **`.11` dev** — Волна 4 (TurnGate + тонкий `handle()`). handle_message.py < ~400 строк.
- **`.12` test** — полный pytest + все инварианты (чек-лист) + `_build` не менялся + seeded-RNG порядок.
- **`.13` review** — когезия коллабораторов (не перенос монстра), turn-local не протёк, инварианты, `handle()` тонкий.
- **`.14` tech-writer** — обновить доки (handle_message → оркестратор + коллабораторы по модулям); закрыть #9; Gate.

## Критерии приёмки

- `handle_message.py` — тонкий оркестратор (~40-60 стр `handle()` + `__init__` сборка коллабораторов);
  коллабораторы в чистых модулях; `_build` не менялся (360 тестов валидны).
- Все инварианты целы (чек-лист); поведение Боба идентично; seeded-RNG порядок сохранён.
- `pytest` (3287+) зелёный на каждой волне; `ruff`/`mypy --strict`; `beadloom ci` зелёный. #9 закрыт.
- (Опц.) #32 floor-персонализацию можно доработать тут или отдельно.

## Связи

Срез 6b/8. После — .7 (application+runtime, app.py→runtime #10 + kernel-split из .2), .8 (доки/закрытие).
