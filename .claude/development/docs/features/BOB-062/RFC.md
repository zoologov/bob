<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-062 — «Domain-first реорганизация + доки» (эпик)

> **Status:** Approved
> **Created:** 2026-07-02
> **PRD:** `./PRD.md` (Approved) · Фаза 3 · BOB-Issues #1–6, #9–18
> **Вход:** карта «файл→модуль» + декомпозиция handle_message + hotspots app.py + инварианты (разведка сессии)

---

## Обзор

Эпик исполняется как **последовательность вертикальных срезов, PR за PR**, внутри рельс Фазы 2
(граф + AaC-правила + гранулярные аннотации). Каждый срез самостоятельно ценен, main всегда зелёный.
Ниже — стратегия переезда, модель энфорса слоёв в domain-first, декомпозиция монстров, чек-лист
инвариантов и порядок срезов.

---

## Стратегия переезда: атомарно по срезу

Для каждого модуля-среза — **атомарный переезд в одном PR**:
1. `git mv` файлов модуля из `domain/`/`application/`/`infrastructure/` в `src/bob/<module>/` (с
   внутренней структурой, см. ниже).
2. Механически переписать импорты **перемещённых файлов** и **их импортёров** на новый путь (в том же PR).
3. Перецелить `source:` граф-узла модуля + проставить `# beadloom:feature=<module>` где нужно.
4. Наполнить SPEC/DOC модуля (не скелет — реальное содержание).
5. Гейты зелёные (`pytest`/`ruff`/`mypy`/`beadloom ci`) + чек-лист инвариантов.

**Почему атомарно, а не «shim на старом пути»:** импортёры известны и конечны, тесты ловят промах,
lingering-шимы плодят двусмысленность. **Исключения-шимы** (осознанные, транзитные):
- `domain/ports/` re-export shim из Фазы 2 — живёт до конца эпика, удаляется в **#18**.
- Цикл **personality↔conversation** (см. Риски) — общий словарь (`expression`/`negotiation`/`taste`/
  `interlocutor`) выносится в маленький shared-под-слой с re-export, чтобы разрезать цикл.

## Внутренняя структура модуля + энфорс слоёв в domain-first

🔴 **Ключевое решение.** В domain-first нет верхних `domain/application/infrastructure` каталогов —
но Clean-Architecture-направление сохраняется **внутри модуля**. Каждый бизнес-модуль:
```
src/bob/<module>/
  ports.py          # контракты (из domain/ports/<module>.py) — # beadloom:layer=domain
  <entities/logic>  # доменная логика — layer=domain
  usecases/         # оркестрация модуля — layer=application
  adapters/         # инфра-реализации портов — layer=infrastructure
```
Слой помечается **файловым тегом** `# beadloom:layer=<L>` (движок принимает произвольные `\w+`-ключи;
Фаза-2-правило `layers` работает по тегам узлов — здесь адаптируем на per-file). Энфорс — **двумя
семействами правил** (оба на реальных импортах):
- **Направление слоёв (внутри и между модулями):** `forbid_import` — `**/adapters/**`→разрешено к
  `ports`/логике; логика (`layer=domain`) НЕ импортит `usecases`/`adapters`; `usecases` не импортит
  чужие `adapters`. Плюс существующее `layers`-правило переориентируем на per-module теги.
- **Границы модулей:** бизнес-модуль обращается к другому ТОЛЬКО через его `ports`/публичный фасад,
  не лезет во внутренности. `forbid_import` `src/bob/<A>/**`→`src/bob/<B>/(usecases|adapters)/**`.

> Это делает «смотря на дерево — понятно что есть что» (модули) И сохраняет чистоту слоёв (теги+правила),
> ровно как в целевой структуре, утв. в Ф2. Первый срез (**coding**) валидирует эту схему до массового
> применения.

## Декомпозиция `handle_message.py` (#9) — критический путь

Файл (3524) = 1 класс `HandleMessage`, метод `handle()` (1256–1552, 18 `await self._…`) — тонкий
оркестратор, ОСТАЁТСЯ. ~50 инъектируемых seam-ов конструктора — это и есть будущие коллабораторы
(не выдуманные классы). Извлекаем **методо-группами → целевые модули** (карта разведки), по одному
коллаборатору за шаг, `handle()` худеет до чистой оркестрации:

| Коллаборатор (извлечь) | → модуль |
|---|---|
| TurnGate, FloorAdvancer, VerifyStep, AntiRepeatGuard, BrevityGuard, EngagementModel | conversation |
| VoiceComposer, MoodPerceiver | personality |
| SocialContext | social |
| RecallAssembler, Persister | memory (+conversation) |
| DiagramSender | capabilities |
| CodingRouterShim | coding |
| EssentialGuard (остаётся) | application |

🔴 Декомпозиция идёт **в срезе personality+conversation** (они забирают бОльшую часть методов), финализ
`handle()` как тонкого оркестратора — в срезе application/runtime. Каждый извлечённый коллаборатор —
behavior-preserving (method-object рефактор: те же аргументы, тот же порядок вызова из `handle()`).

## Вынос `app.py`→`runtime/` (#10)

Карта (разведка §3): `build_application`+`_build_*`+entrypoint+`Application`+`SystemClock` → `runtime/`;
инлайн Telegram-адаптеры (`_AiogramBotAdapter`/`_*View`/`_BobReactionFilter`/`_build_real_bot`) →
`infrastructure/telegram/`; инлайн доменные адаптеры/loader → wiring соответствующих модулей.

🔴 **Хрупкости (обязательный чек-лист среза runtime):**
- **`_REPO_ROOT = parents[2]`** (app.py:321) — при переезде глубина меняется → **пересчитать** `parents[N]`
  (использования: `_DEFAULT_TEMPLATES_DIR`, `PrivacyGuard(repo_root=)` ×2). Тест на резолв пути.
- **boot-order** (repo→recall→stores→multibot→trackers→handle_message; «built AFTER multibot») — сохранить
  топосорт при разносе wiring.
- **shared-instance:** `notable_reaction_store` (один kv на обе стороны), `diagram_sink`
  (`CollectingDiagramSink`, один инстанс в HandleMessage И в render_diagram capability) — НЕ раздваивать.
- **feature-flag off→None→inert:** `floor_store/rule_store/… = X if enabled else None` — сохранить контракт
  «None ⇒ поведение как до фичи» при разносе `_build_*_enabled` по модулям.

## Чек-лист инвариантов среза (🔴 из разведки §5 — прогонять в КАЖДОМ срезе)

| Инвариант | Где | Держать |
|---|---|---|
| verify-once-per-turn (BOB-057) | `handle:1413`+`_verify_note:2878` | note — **turn-local аргумент, НЕ атрибут**; reuse в compose+anti-repeat |
| анти-повтор-регенерация (BOB-022) | `_guard_against_verbatim_repeat:2603` | ровно 1 доп. генерация; на повтор — keep (no loop) |
| essential-vs-decorative / `_safe_addon` / GUPPI-нотис | `_safe_addon:2864`, `_run_essential:1187` | add-on ловит Exception→""; essential→retry→честный outage |
| per-turn announcer (BOB-060) | `_send_verify_interim:2925` + `progress_announcer` | live-only анонс |
| floor-advance (BOB-025) | `_advance_floor_after_turn:2310` | вызов ПОСЛЕ reply, RAW addressivity, best-effort |
| shared-instance | notable_reaction / diagram_sink | один инстанс |
| boot-order / feature-flag off→None→inert | `build_application` | топосорт + None-инертность |
| sulk once, no-memory (anti-Exodus) | `_observe_sulk:1839` + `sulk.py` | обида объявляется один раз |

Дополнительно на каждом срезе: `pytest` (полный, поведение идентично) · `ruff` · `mypy --strict` ·
`beadloom ci` (правила ловят нарушение границ) · `beadloom reindex` после перецеливания узлов.

## Порядок срезов (по риску, разведка §6)

| # | Срез | ~файлов | риск | несёт |
|---|---|---|---|---|
| .1 | **coding** | 17 | 🟢 | валидирует схему модуля+layer-теги+правила границ |
| .2 | **memory** | 14 | 🟢 | |
| .3 | **proactivity** | 21 | 🟡 | |
| .4 | **capabilities** | 23 | 🟡 | |
| .5 | **social** | 24 | 🟡 | authz/permission; обратное ребро в conversation(negotiation) через shim |
| .6 | **personality + conversation** (совместно) | 51 | 🔴 | двунаправленный цикл + бОльшая часть декомпозиции handle_message |
| .7 | **application + runtime** | ~15 | 🔴 | финализ `handle()` тонким; `app.py`→`runtime`(#10); infra-адаптеры |
| .8 | **доки + закрытие каркаса** | — | 🟡 | ужать `architecture.md`(#4), getting-started/guides(#5), флип `no-monster`→error, удалить ports-шим(#18) |

Каждый срез `.1–.8` — **отдельная фича/PR** под эпиком BOB-062 (свой мини task-init: CONTEXT+PLAN или
BRIEF), исполняется координатором (dev→test→review→tech-writer). Owner утверждает старт каждого среза.

## Риски

- 🔴 **personality↔conversation цикл** — разрезаем shared-словарём (`expression`/`negotiation`/`taste`/
  `interlocutor`) с re-export shim; срез .6 делает их совместно, чтобы не заморозить полудвижение.
- 🔴 **handle_message пронизывает все модули** — извлекаем коллабораторов инкрементально (method-object),
  тесты после каждого; финал `handle()` — в .7.
- **Большой объём** — 8 срезов, 8 PR; при усталости/дрейфе останавливаемся на границе среза (main зелёный).
- **Доки под текущую vs целевую** — доки пишутся В срезе (после переезда файлов модуля), не заранее — не
  переписываем.

## Открытые вопросы (к CONTEXT/PLAN)

- Схема layer-тегов внутри модуля: `# beadloom:layer=` + подкаталоги `usecases/`/`adapters/`, или плоско
  с тегами? (Рекомендация: лёгкие подкаталоги там, где ≥3 файлов слоя; иначе плоско + теги.) Валидируем на .1 coding.
- Ретро-совместимость `layers`-правила Ф2: переориентировать на per-module/ per-file теги в .1 или держать
  оба (top-level пока каталоги ещё есть) до .7? (Рекомендация: держать оба, переключить в .7/.8.)
- Разбивать ли .6 (personality+conversation, 51 файл) на два PR с общим shim, или один большой? (Обсудим в
  CONTEXT/PLAN среза .6, когда дойдём.)
