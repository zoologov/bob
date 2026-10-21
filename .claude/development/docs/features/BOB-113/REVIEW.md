<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# REVIEW — BOB-113 (bob-etb.6), W1–W4a, `git diff 2804199..HEAD`

> **Ревьюер:** review-роль (read-only) · **Дата:** 2026-10-21 · **HEAD:** `cba8120`
> **Вердикт: ISSUES — 0 critical, 2 major, 5 minor** (+2 nitpick, 1 наблюдение). Беада остаётся открытой.

Все гейты ниже прогнаны мной на финальном дереве (§0.3 п.8), beadloom — только `uvx --from beadloom==9.0.0`.

## 3. Гейты (замер ревьюера)

| Гейт | Результат |
|---|---|
| `uv run ruff check src/ tests/` | `All checks passed!`, exit 0 |
| `uv run mypy src/` | `Success: no issues found in 410 source files` |
| `uv run mypy tests/` | `Success: no issues found in 656 source files` |
| чистый индекс + `lint --strict --no-reindex` | **EXIT 0**, `:error:`-строк **0**; 38 строк вывода = заголовок + 36 `rule_liveness` warn + 1 `layer_population` warn |
| строка `layer_population` | `# layer_population:architecture-layers:depends_on:15:81:66` / `architecture-layers:layer_population:warn::::` |
| `sync-check` | exit 0, 726 `[ok]`, 0 stale (4 `[warn]` про required sections / surface — не stale) |
| `docs audit` | exit 0, раздел Stale Mentions пуст (2 verified version mention) |
| `doctor` | exit 0; единственные `[warn]` — «Doc … has no ref_id» у feature-доков `.claude/development/docs/features/*` (в т.ч. BOB-113 CONTEXT/PLAN/PRD/RFC) |
| `uv run pytest -q -rs -p no:randomly` | **7994 passed, 16 skipped** (198.85 s); все 16 skip — live-smoke без `BOB_LIVE_*` |
| `beadloom diff --since 2804199` | меняются только `summary` узлов kernel / memory / proactivity / capabilities / social / runtime-app; узлы и рёбра графа YAML не добавлены и не удалены |

Рёбра (sqlite по чистому индексу): `depends_on` = **81**, с `derived` = **75**; type-only (все строки импорта ребра под `if TYPE_CHECKING:`, ast по `code_imports`) = **9**:
`capabilities→bob-domain`, `coding→bob-domain`, `coding→capabilities`, `interactive→identity`, `personality→bob-domain`, `runtime-app→bob-domain`, `social→conversation`, `telegram→memory`, `usecases→runtime-app`. Вверх по порядку вертикалей нет ни одного. Пар циклов 0, cycle-строк 0.

## 1. 22 имени: новый дом, старый путь, импортёры

Метод: (a) `grep -E "^(class|type) <Name>\b"` по `src/` — у каждого имени ровно одно объявление; (b) AST-скан `src/ tests/ scripts/`: `ImportFrom`/`Import` имени из старого модуля **или** из фасада старого пакета (`bob.social`, `bob.memory`, `bob.capabilities`, `bob.proactivity`, `bob.application.usecases`, `bob.application.runtime`) — **0 попаданий**; (c) `__all__` старых модулей и фасадов не содержит ни одного перенесённого имени; `import … as`-алиасов нет (старые модули импортируют имена из kernel только как потребители — mypy `--strict` без implicit re-export это держит); (d) grep точечных путей (`bob.social.interlocutor.Interlocutor`, `handle_message.ReplyGateway`, `capabilities.ports.ToolCall`, `application/runtime/events` …) по `src tests scripts docs .beadloom README.md AGENTS.md .claude/dev-docs` — одно попадание, исторический комментарий `rules.yml:1568` (см. m5). `src/bob/application/runtime/events.py` не существует.

| # | Имя | Новый дом (file:line) | Старый путь: объявл. / шим / `__all__` | Импортёры | Вердикт |
|---|---|---|---|---|---|
| 1 | `MessageReceived` | `kernel/events.py:42` | файла нет / нет / убран из `application/runtime/__init__` | все на `bob.kernel.events` | OK (см. m1: фасад telegram) |
| 1 | `BobMessageReaction` | `kernel/events.py:104` | файла нет / нет / убран | все новые | OK |
| 2 | `Recalled` | `kernel/episode_types.py:39` | нет / нет / нет (memory/ports импортирует под TYPE_CHECKING) | все новые | OK |
| 3 | `EpisodeReader` | `kernel/ports.py:133` | нет / нет / — | все новые | OK |
| 4 | `MemoryRecall` | `kernel/ports.py:146` | нет / нет / нет | все новые | OK |
| 5 | `ReplyGateway` | `kernel/ports.py:167` | нет / нет / — | все новые | OK |
| 6 | `BobUserIdSource` | `kernel/ports.py:197` | нет / нет / — | все новые | OK |
| 7 | `ToolDefinition` | `kernel/ports.py:51` | нет / нет / убран из `capabilities/__init__` | все новые | OK |
| 7 | `ToolCall` | `kernel/ports.py:216` | нет / нет / убран | все новые | OK |
| 7 | `ToolCallResult` | `kernel/ports.py:230` | нет / нет / убран | все новые | OK |
| 7 | `ToolCallingProvider` | `kernel/ports.py:242` | нет / нет / убран | все новые | OK |
| 8 | `RuleModulators` | `kernel/modulators.py:27` | нет / нет / убран из `self_improvement.__all__` | все новые | OK (см. M1) |
| 9 | `PersonalityState` | `personality/state.py:30` | нет / нет / убран из `application/usecases/__init__` | все новые (вкл. `runtime/wiring/{goals,proactivity}.py`) | OK |
| 10 | `EngagementState` | `conversation/engagement.py:354` | нет / нет / — | все новые | OK |
| 11 | `InterlocutorResolver` | `social/ports.py:218` | нет / нет / — | все новые | OK |
| 11 | `FirstImpressionReader` | `social/ports.py:235` | нет / нет / — | все новые | OK |
| 11 | `RosterRecaller` | `social/ports.py:258` | нет / нет / — | все новые | OK |
| 11 | `RelationshipReader` | `social/ports.py:277` | нет / нет / — | все новые | OK |
| 11 | `SulkReader` | `social/ports.py:308` | нет / нет / — | все новые | OK |
| 12 | `CurrentFascinationReader` | `personality/ports.py:89` | нет / нет / — | все новые | OK |
| 13 | `VerifySearch` / `HasAnswer` | `conversation/ports.py:125` / `:110` | `WebSearchProvider` остался в capabilities (свои потребители); `verify_step.py` из `bob.capabilities` ничего не импортирует | `verify_step`, 2 теста forced, новый narrow_port | OK |
| 14 | `Interlocutor` | `kernel/interlocutor.py:76` | нет / нет / убран из `social/interlocutor.__all__` (`['classify']`) | все новые | OK |
| 14 | `InterlocutorKind` | `kernel/interlocutor.py:48` | то же | все новые | OK |
| 14 | `Trust` | `kernel/interlocutor.py:62` | то же | все новые | OK |
| 14 | `Gender` | `kernel/interlocutor.py:36` | нет / нет / `social/gender.__all__ = ['GenderRead','detect_self_gender']` | все новые | OK |
| 15 | `Relationship` | `kernel/relationship.py:37` | нет / нет / убран | все новые | OK (см. M1) |
| 16 | `RosterMember` | `kernel/roster.py:34` | нет / нет / убран | все новые | OK |
| 17 | `SulkState` | `kernel/sulk.py:41` | нет / нет / убран | все новые | OK |

## 2. Поведение не изменилось

Скрипт: для каждого имени — `ast.get_source_segment` класса/алиаса в `git show 2804199:<старый>` vs `<новый>` на HEAD.
- **IDENTICAL** (байт-в-байт): MessageReceived, BobMessageReaction, Recalled, EpisodeReader, MemoryRecall, ReplyGateway, BobUserIdSource, ToolDefinition, ToolCall, ToolCallResult, ToolCallingProvider, RuleModulators, PersonalityState, FirstImpressionReader, RosterRecaller, CurrentFascinationReader, Interlocutor, InterlocutorKind, Trust, Gender, RosterMember.
- **Только докстринг `:class:`-путь**: EngagementState (`PersonalityState` → `~bob.personality.state.PersonalityState`, перенос строк), InterlocutorResolver / RelationshipReader / SulkReader (`~bob.social.*` → `~bob.kernel.*`).
- **Переименование константы**: `Relationship.__post_init__` `_MIN_AXIS/_MAX_AXIS` → `MIN_AXIS/MAX_AXIS`; `SulkState.intensity` default `_MIN_INTENSITY` → `MIN_INTENSITY`.
- **Значения границ совпадают**: base `social/relationship.py:49-50` `_MIN_AXIS = -1.0`, `_MAX_AXIS = 1.0` ↔ `kernel/relationship.py:32-33` `MIN_AXIS = -1.0`, `MAX_AXIS = 1.0`; base `social/sulk.py:52-53` `_MIN_INTENSITY = 0.0`, `_MAX_INTENSITY = 1.0` ↔ `kernel/sulk.py:36-37` `MIN_INTENSITY = 0.0`, `MAX_INTENSITY = 1.0`.

Функции вне перенесённых объявлений (AST-сравнение каждой функции/метода/модульного оператора во всех изменённых файлах `src/`, без докстрингов и импортов/TYPE_CHECKING-блоков). Изменились только:
- `social/relationship.py::_clamp`, `social/sulk.py::_clamp_intensity` — только имя константы (`_MIN_AXIS`→`MIN_AXIS` и т.д.);
- `conversation/usecases/verify_step.py::VerifyStep.__init__`, `::_search_note` — только аннотация `WebSearchProvider` → `VerifySearch` (RFC E);
- `__all__` в `application/runtime/__init__`, `application/usecases/__init__`, `capabilities/__init__`, `proactivity/self_improvement`, `conversation/engagement`, `kernel/episode_types`, `social/{ports,interlocutor,gender,relationship,roster,sulk}` — только добавление/удаление перенесённых имён.
Ни одного иного изменённого тела. Тесты: тот же AST-скан по `tests/` — изменились только `_step()` в `test_verify_step_forced{,_hedge}.py` (аннотация фикстуры), 4 теста `tests/domain/test_ports.py` (`memory_ports`/`capabilities_ports` → `kernel_ports`, те же ассерты), добавлены 2 файла и 4 гарда в `test_no_runtime_import_cycles.py`. Ослабленных ассертов нет.

## 4. Правила

- `rules.yml:41-44`: `no-dependency-cycles` — `severity: error`, `forbid_cycles: {edge_kind: depends_on}`.
- `git diff 2804199..HEAD -- .beadloom/` → только `_graph/services.yml` (6 summary). `rules.yml` не тронут; `exempt`/`suppress`/`warn` для циклов не добавлено (единственный `exempt:` — давнее `module-coverage`, строка 1206).
- `uv run python scripts/gen_boundary_rules.py --check` → `rules.yml generated region is in sync`, exit 0.
- `kernel-no-*`: 13 правил `severity: error` (application, capabilities, coding, conversation, identity, infrastructure, interactive, memory, personality, presence, proactivity, runtime, social) — не менялись.

## 5. Изоляция kernel

- `grep -rn "from bob|import bob" src/bob/kernel/` → одна строка: `kernel/ports.py:37 from bob.kernel.episode_types import Recalled` (TYPE_CHECKING).
- `tests/domain/kernel/test_kernel_isolation.py` импортирует модули через `pkgutil.iter_modules(bob.kernel.__path__)` в `python -I` — покрыты все 12: `config_paths, episode_types, events, interlocutor, modulators, poll_backoff, poll_outage, ports, relationship, roster, sulk, visibility` (+ `__init__`); второй тест требует, чтобы 8 новых домов реально загрузились (защита от пустого импорта).

## 6. Кусачесть (саботаж мной; снят точечной правкой, не `git checkout`)

Базовая линия: `tests/test_no_runtime_import_cycles.py tests/domain/kernel/` — **41 collected / 41 passed**.
- **A** — в `personality/voice.py` под `TYPE_CHECKING` добавлено `from bob.social.roster import build_roster` → **1 failed, 40 passed**: `FAILED test_no_type_checking_import_points_upward_against_the_vertical_order` (сообщение `personality → social (bob/personality/voice.py:43)`); старый `test_runtime_imports_form_no_cycle_between_modules` остался зелёным — двойной прогон доказан. beadloom 9.0.0 на чистом индексе: **exit 1**, 8 строк `no-dependency-cycles:cycle:error` (пары personality:social, personality:conversation, memory:telegram, personality:proactivity, memory:proactivity).
- **B** — в `kernel/roster.py` runtime `from bob.memory.ports import Embedder` → **3 failed, 38 passed**: `test_runtime_imports_form_no_cycle_between_modules`, `test_runtime_edges_follow_the_declared_vertical_order`, `test_importing_every_kernel_module_loads_no_other_bob_module`. Все FAILED, не ERROR. beadloom: exit 1, `kernel-no-memory:forbid_import:error` ×1 (цикла beadloom здесь НЕ видит — см. наблюдение O1).
- **C (обман гарда, §0.3 п.12)** — в `personality/voice.py` под `TYPE_CHECKING` добавлено `from bob import social` → **41 passed**, beadloom **exit 0, 0 `:error:`** (в `code_imports` импорт разрешён в корневой узел `bob`). См. **M2**.
После каждого снятия: `git diff --stat src/` пуст, `grep SABOTAGE src tests` пуст, 41 passed, чистый индекс → lint exit 0.

## 7. Cohesion / DDD

- В kernel только значения и порты; поведение social (`classify`, `detect_self_gender`, `apply_interaction`, `build_roster`, `observe_relationship`, `recover` …) осталось в social. Логика в kernel: `Relationship.__post_init__` (инвариант значения) и `RuleModulators.has_any` (тривиальный предикат) — по смыслу значения, допустимо; но см. M1 про mutation-scope.
- Новые модули kernel с правильной аннотацией `domain=bob / feature=kernel / layer=domain`; `personality/state.py` — `feature=personality`.
- `handle_message.py` (2426 → 2213 строк) больше не объявляет ни одного из 11 имён; оставшиеся Protocol (`EpisodeWriter`, `SelfImprovementReader`, `OwnerActivityRecorder`, `BargeCeiling`, `ReplyDelay`) импортирует только он сам и тест; из `src` в `handle_message` ходит лишь composition root (`runtime/composition.py:49`, `HandleMessage`). `capabilities/ports.py` импортирует только своё (`introspection.graph_form`). Вверх по порядку ничего не указывает (гард + beadloom).
- `conversation/ports.py` `HasAnswer`/`VerifySearch` читаются как порт потребителя: одно read-only свойство, `async search(query) -> HasAnswer`; capabilities не импортируется; `WebSearchResult` подходит структурно (mypy это доказывает в `handle_message`). Не копия.
- Противоречий RFC-правилу в размещении не нашёл.

## 8. Доки (для `.7`)

Старые пути в `docs/` не названы (grep пуст, кроме исторических упоминаний «переехали из … в BOB-113»). Домашние доки описывают новые дома: architecture.md:40-47, 180-184; social README реш. 5-6; memory README:437; proactivity README:177; personality README:65-66; conversation README (EngagementState, VerifySearch/HasAnswer); capabilities README:655-682; kernel SPEC. Что осталось для `.7` — см. m2, m5.

## 9. Числа ACTIVE

| Строка ACTIVE | ACTIVE | Мой замер | |
|---|---|---|---|
| W3 depends_on | 81 (75 произв.) | 81 / 75 | совпадает |
| W3 type-only | 9 (тот же список) | 9, тот же список | совпадает |
| W3 cycle-строк / пар | 0 / 0 | 0 / 0 | совпадает |
| W3 lint | exit 0, 38 строк (36+1+заголовок) | exit 0, 38 строк, 37 `:warn:` | совпадает |
| W4 `.5` pytest | 7994 / 16 | 7994 / 16 | совпадает |
| старт | 98 / 30 | (не перемерял base) | расхождение 99/29 из W1-заметки не разобрано — m3 |
| Прогресс | `[ ] W2` | `.2`/`.3` закрыты, строки 9-13 ✓ | m3 |

---

## Находки

### Major

**M1 — Mutation-scope молча потерял перенесённую логику (§0.3 п.7).**
`pyproject.toml:2605` `[tool.mutmut].source_paths` содержит `src/bob/social` и `src/bob/proactivity`, но не `src/bob/kernel` («technical layers — … kernel — are excluded by simply not being listed»). Вместе с переездом из-под мутации ушли:
`kernel/relationship.py:46` `Relationship.__post_init__` (проверка 4 осей на `[MIN_AXIS, MAX_AXIS]` — инвариант домена, раньше в `social/relationship.py`) и `kernel/modulators.py:53` `RuleModulators.has_any` (раньше в `proactivity/self_improvement.py`). Тела не менялись, но `scripts/mutation.sh bob.social.relationship` / `bob.proactivity.self_improvement` теперь отчитается своим score без этих строк — гейт показывает зелёное, не проверив их. Комментарий в самом `pyproject.toml:2655` называет ровно это фантомным гейтом.
*Рекомендация:* добавить файлы поштучно (как `reply_rhythm.py`, `rich.py`): `"src/bob/kernel/relationship.py"`, `"src/bob/kernel/modulators.py"` с комментарием BOB-113; прогнать `scripts/mutation.sh` по ним и записать в ACTIVE число мутантов + поимённый триаж выживших. Либо явно записать решение «это не ядро» с обоснованием — но не молча.

**M2 — Гард «TYPE_CHECKING не вверх» и beadloom обходятся одной и той же формой импорта (§0.3 п.12, прогон-обман).**
Саботаж C: `from bob import social` под `TYPE_CHECKING` в `personality/voice.py` → новый гард **41 passed**, `lint --strict` **exit 0**. Причина в тесте: `tests/test_no_runtime_import_cycles.py:66-67` `_is_first_party` требует `module.startswith("bob.")`, так что `from bob import X` (module `bob`) и относительные импорты (`level > 0`) отбрасываются; `from bob.application import usecases` / `from bob.infrastructure import telegram` дают `_node_of(("application",))` вне `_VERTICAL_ORDER` → `None` → не судится. beadloom разрешает `from bob import social` в корневой узел `bob` — та же слепая зона, то есть «второй, независимый от beadloom зуб» (RFC) на этом входе не независим. Форма правдоподобна: `bob/social/__init__.py` ре-экспортирует порты, так что `social.AllowlistStore` в аннотации — рабочий код. В текущем дереве таких импортов 0 (`grep "from bob import" src` пуст, относительных 0), поэтому вердикт ацикличности сейчас верен; дыра — в гарде на будущее.
*Рекомендация:* в коллекторах (`_type_checking_imports` и `_runtime_imports`) разворачивать `ImportFrom(module="bob" | "bob.application" | "bob.infrastructure", names=[X])` в `bob.X…` и резолвить относительные импорты по пути файла (или явно падать на них); добавить юнит-кейс с этой формой и саботаж-«обман» в `.5`-доказательство. Апстриму — BDL-UX (обезличенно): `from pkg import subpkg` резолвится в корневой узел, ребро на подпакет теряется.

### Minor

**m1 — Второй публичный путь `MessageReceived`.** `src/bob/infrastructure/telegram/__init__.py:38,51` ре-экспортирует `MESSAGE_RECEIVED, MessageReceived` (было и до BOB-113, импорт перенаправлен на kernel). Импортёров через фасад 0. Против «один дом у каждого имени» (RFC D). *Рекомендация:* убрать из фасада telegram.

**m2 — `src/bob/kernel/__init__.py:8-13` докстринг устарел**: перечисляет только Clock/EventBus/LLMProvider/LLMMessage/JsonValue, не события интейка, порты памяти/ответа/tool-calling, модуляторы и социальный словарь (dev `.1` пометил TODO). sync-check это не видит (§0.3 п.2-класс). *Для `.7`* (или dev).

**m3 — ACTIVE/RFC неточности.** ACTIVE «Прогресс»: `[ ] W2` при закрытых `.2`/`.3` и ✓ в строках 9-13; строка «старт» 98/30 против перемера W1 99/29 — «не разбиралось» (честно, но открыто); RFC C всё ещё пишет `Recalled` в `memory/entities.py` (ACTIVE исправил, RFC нет). *Рекомендация:* отметить W2, дописать в RFC сноску-исправление.

**m4 — Второй источник инварианта осей отношения.** `src/bob/personality/reaction_effect.py:46-47,72` держит свои `_MIN_AXIS = -1.0 / _MAX_AXIS = 1.0` и клампит ими `rel.warmth` (ось `Relationship`). W3 сделал границы публичными ради «одного источника», но этот потребитель остался на копии. Существовало до BOB-113. *Рекомендация:* `from bob.kernel.relationship import MAX_AXIS, MIN_AXIS` (вниз, легально) отдельной правкой. (`personality/mood.py` `_MIN_AXIS` — оси Mood, другой инвариант, не трогать.)

**m5 — Остатки для `.7`.** `docs/domains/social/README.md:87` строка дерева `ports.py` перечисляет только сторы, без 5 читателей (реш. 5 их называет); `.beadloom/_graph/rules.yml:1568` рукописный комментарий называет `social.relationship.Relationship` (вне генерируемой области — правка допустима); `site/` (сгенерированный) содержит старые пути — регенерация в BOB-112 `.4`.

### Nitpick
- `EpisodeWriter(Protocol)` объявлен в 4 местах (handle_message, heartbeat, engine, pursue_goals) — ISP у потребителя, существовало до BOB-113.
- Докстринги kernel ссылаются `:func:`-ами на поведение social (`~bob.social.relationship.apply_interaction` …) — только проза, не импорт.

### Наблюдение (не дефект этой работы)
**O1 — `no-dependency-cycles` слеп к рёбрам ИЗ kernel.** Саботаж B (`kernel → memory`, runtime) не дал ни одного derived-ребра из `kernel`/`bob-domain` и ни одной cycle-строки; узлы `kernel` и `bob-domain` делят `source: src/bob/kernel/`, входящие импорты резолвятся в `bob-domain`. Держат три других зуба — `kernel-no-*` (beadloom, укусил), `test_kernel_isolation`, `test_runtime_imports_form_no_cycle_between_modules` (оба укусили). С BOB-113 в kernel лежат 22 контракта, поэтому важно, что именно эти три зуба, а не правило циклов, охраняют направление. `bob.app` в `kernel-no-*` не входит (держит тест изоляции).

## Итог
Перенос сделан чисто: 29 идентификаторов (22 решения RFC) объявлены по одному разу в новых домах, шимов/ре-экспортов на старых путях нет, тела идентичны (кроме докстринг-путей и переименования констант с теми же значениями), гейты на финальном дереве зелёные с числами, совпадающими с ACTIVE. Блокируют закрытие две вещи класса §0.3: потерянный mutation-scope (M1) и гард, который обходится правдоподобной формой импорта (M2).

---

# Re-review — после фикса bob-etb.8 (HEAD `b041f7f`)

> **Вердикт: OK** — 0 critical, 0 major, 0 minor из прошлого списка открыто. Беада `.6` закрывается.

## Гейты на `b041f7f` (мой прогон, beadloom только `uvx --from beadloom==9.0.0`)

| Гейт | Результат |
|---|---|
| `ruff check src/ tests/` | `All checks passed!` |
| `mypy src/` / `mypy tests/` | 0 issues: 410 / 658 файлов |
| чистый индекс + `lint --strict --no-reindex` | **EXIT 0**, 0 `:error:`, 38 строк (36 `rule_liveness` + 1 `layer_population` warn + заголовок); `# layer_population:architecture-layers:depends_on:15:81:66` |
| рёбра | `depends_on` 81, derived 75, type-only **8** (было 9: `personality→bob-domain` стало runtime, т.к. `reaction_effect` теперь импортирует границы из kernel); вверх — 0; cycle-строк 0, пар 0 |
| `sync-check` | exit 0, 726 `[ok]`, 0 stale |
| `docs audit` | exit 0; 1 stale mention `docs/domains/coding/README.md:570` `"2.2.0"` — существовал до BOB-113 (BOB-112, версия beadloom в прозе), не эта работа |
| `doctor` | exit 0, только «no ref_id» у feature-доков |
| `gen_boundary_rules.py --check` | `generated region is in sync`; `no-dependency-cycles` — `severity: error` (`rules.yml:41-44`), в правка `rules.yml` только рукописный комментарий |
| `pytest -q -rs -p no:randomly` | **8074 passed, 16 skipped** (live smoke) |

## M2 — гард читает все формы импорта: ЗАКРЫТО
Коллекторы (`_resolve_from`) резолвят `from bob import X`, `from bob.application import usecases`, `from pkg import sub` и относительные импорты (по `__package__` файла; выход за пакет → `ValueError`); 21 форма × 2 коллектора параметризованы + кейс `__init__`. Базовая линия `tests/test_no_runtime_import_cycles.py tests/domain/kernel/`: **119 collected / 119 passed**.
- **C** `from bob import social` под `TYPE_CHECKING` в `personality/voice.py` → **1 failed, 118 passed**: `FAILED test_no_type_checking_import_points_upward_against_the_vertical_order` — `personality → social (bob/personality/voice.py:43)`.
- **D** относительный runtime `from ..social import roster` в `personality/voice.py` → **2 failed, 117 passed**: `FAILED test_runtime_imports_form_no_cycle_between_modules` (компонента `application.runtime, conversation, infrastructure.telegram, memory, personality, proactivity, social`), `FAILED test_runtime_edges_follow_the_declared_vertical_order` (`personality → social`). Оба FAILED, не ERROR.
Сняты точечной правкой; `git diff --stat src/` пуст, `SABOTAGE` в дереве нет, 119 passed. beadloom обе формы по-прежнему не видит — апстрим-пробел, записан в коммите как BDL-UX; pytest-гард теперь его закрывает.

## M1 — mutation-scope: ЗАКРЫТО
- `pyproject.toml` `[tool.mutmut].source_paths` + `src/bob/kernel/relationship.py`, `src/bob/kernel/modulators.py` (поштучно, с обоснованием).
- Утверждение dev подтверждено по исходнику mutmut 3.6.0: `.venv/…/mutmut/mutation/file_mutation.py` — `if isinstance(node, cst.ClassDef) and len(node.decorators): return True`, т.е. методы `@dataclass`-классов не мутировались и до переезда.
- Поведение и API не изменились (сравнение с `git show e7ccbb0:src/bob/kernel/relationship.py`): поля и сигнатуры `Relationship`/`RuleModulators` те же; `__post_init__` вызывает `_require_axes_within_bounds(self)`, которая проверяет оси в том же порядке (trust, respect, warmth, compatibility) тем же условием `not MIN_AXIS <= value <= MAX_AXIS` и бросает `ValueError` с байт-в-байт тем же текстом (две f-строки слиты в одну); `has_any()` возвращает `_has_any_lever(self)` — то же выражение `bool(a or b or c or d)`. Новые тесты `tests/domain/kernel/test_relationship_value.py`, `test_rule_modulators.py`.
- Перемер мной (`scripts/mutation.sh kernel.relationship` / `kernel.modulators`, `mutants/src/bob/kernel/*.meta`): **kernel.relationship 28/28 killed** (exit_code 1 ×28), **kernel.modulators 4/4 killed**; выживших нет. `__pycache__` вычищен скриптом; после — guard + kernel + reaction_effect тесты зелёные.
- Слепая зона (~50 методов декорированных классов в scope) записана в `MUTATION.md` — отдельная беада, вне BOB-113.

## Minor m1–m5: все применены
- m1: `infrastructure/telegram/__init__.py` больше не импортирует и не экспортирует `MessageReceived`/`MESSAGE_RECEIVED` (докстринг ссылается на `~bob.kernel.events.MessageReceived`).
- m2: `kernel/__init__.py` докстринг перечисляет все группы контрактов kernel и правило «только stdlib/typing».
- m3: ACTIVE `[x] W2` + строка `.8`; RFC C — сноска ¹ про `Recalled` в `memory/ports.py`.
- m4: `personality/reaction_effect.py` берёт `MIN_AXIS`/`MAX_AXIS` из `bob.kernel.relationship`, свои копии удалены (ребро personality→kernel, вниз).
- m5: `rules.yml:1568` комментарий → `kernel.relationship.Relationship`; `social/README.md:87` строка `ports.py` называет 5 читателей. (`site/` — регенерация в BOB-112 `.4`, как и было отмечено.)

## Итог
Обе Major закрыты структурно, а не ярлыком; кусачесть нового гарда доказана саботажами C и D (прогон-обман, на котором прежний гард и beadloom были зелёными); mutation-гейт на перенесённой логике впервые реальный (28 + 4 мутанта, все убиты). Остаток вне scope: pre-existing stale mention `coding/README.md:570` (BOB-112) и слепая зона mutmut по методам декорированных классов (своя беада).
