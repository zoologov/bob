<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Bob Engineering Issues Log

> Потенциальные проблемы и улучшения, собираемые в процессе разработки (по образцу
> beadloom `BDL-UX-Issues.md`). Фиксируем находки — фиксим планово.
>
> **Total:** 51 · **Open:** 21 · **Closed:** 30 (Фаза 1: #6, #19–24, #29 · Фаза 2: #7, #8 · Фаза 3 — эпик BOB-062, ✅ **DONE**: #1–#5, #9–#18, #30 · #31/#32 групповая нагрузка) · 🔴 **ЭПИК BOB-062 → Done** (2026-07-28, срезы .1–.8/8): domain-first реорг завершена (7 бизнес-модулей + kernel/application/infrastructure/runtime), ports-шим удалён, `src/bob/domain/` удалён, kernel в `src/bob/kernel/`, no-monster-modules = error, `architecture.md` ужат 4318→260 строк (nav-shell), `getting-started.md` добавлен. **Open (бэклог):** #25–28 clean-code · #33 read-the-room качество (P3) · #34 Tier-0 отвал сети ✅ ЗАКРЫТ (BOB-087 Срез E: Ollama-фолбэк + целостность голоса E-M1; вживую сработал 2026-08-05) · #35/#36 🔴 кодер-UX (форматирование + обрезка ответов — отлаживаем сейчас). Отдельно: BOB-084 (runner >64КБ краш) ✅ отгружен (PR #117, не в этой нумерации — багфикс).
> **Заметка (BOB-062.6/.7a):** цикл `proactivity↔conversation` разорван в срезе .6; .6b-дефект и урок про инкрементальный `beadloom reindex` (может маскировать staleness — перед Gate гнать `reindex --full`) трекаются beadloom-стороной как #142.
> 2026-07-02 (комплексный аудит, 5 субагентов read-only): заведён лог. Открыты #1–#30
> из аудита организации/DDD/доков/гигиены. Источник: сессия аудита `13b1e49b`.

---

## Execution Plan (утв. 2026-07-02) — «Инженерная гигиена / организация»

> Порядок и структура зафиксированы owner'ом. Резать **поведение-сохраняюще**, PR за PR, тесты
> зелёные на каждом шаге. Доки (D) и domain-first реорг (E) — **один эпик** (per-module вертикали:
> переезд кода + `beadloom:`-тэги + граф-ноды + SPEC/DOC едут вместе).

| Фаза | Что | Issues | Тип | Статус |
|---|---|---|---|---|
| **1. Быстрые победы** (параллельно, независимы) | гигиена + README ×2 | #19–24, #29, #6, #20 | chore ×2 | ✅ done (BOB-063 PR#76 + BOB-064) |
| **2. Фундамент** | split `ports.py` (+re-export shim) · beadloom-правило слоёв | #7, #8 | feature | ✅ done (BOB-065: пакет `domain/ports/` + shim · 11 AaC-правил слоёв · граф 28 нод) |
| **3. Эпик BOB-062 «Domain-first + доки»** — per-module вертикали: `coding→memory→proactivity→social→conversation→personality/capabilities→runtime/application`; каждая несёт свои `beadloom:`-тэги + граф-ноды + SPEC/DOC | #1–6, #9–18, #30 | epic | ✅ **done** (срезы 1–8/8: #11 coding · #12 memory · #13 proactivity · #16 capabilities+personality · #14 social · #15 conversation · #9 handle_message → .6b · #17 runtime + #10 app.py→runtime → .7a · #10 kernel-split → .7b · #18 ports-шим удалён + #8-флип + #1–#5 доки-финиш → .8) |
| — монстры внутри ф.3 | ✅ `handle_message`(3523,#9)→растворён в conversation/personality/social/capabilities/application (.6b); ✅ `app.py`(2819,#10)→пакет `runtime/` (.7a, тонкий shim); ✅ kernel-split (#10, .7b)→`SqliteConnection` ↔ `SqliteMemoryRepo` (memory/adapters) | #9, #10 | — | ✅ (#9 ✅, #10 ✅ полностью) |
| — после реорга | ✅ включено правило слоёв (#8) как «зубы» (no-monster-modules flip warn→error, .8); ✅ удалён `ports.py`-шим (#18, .8) — импорты на канон `bob.<module>.ports` / `bob.kernel.ports` | #8, #18 | — | ✅ done (.8) |

**🔴 Инварианты рефакторинга** (не сломать при переезде): verify-once-per-turn (BOB-057), анти-повтор-регенерация (BOB-032/043), essential-vs-decorative (`_safe_addon`/GUPPI-нотис BOB-049), per-turn announcer, floor-advance на ВСЕХ ветках (BOB-025/058), shared-instance (diagram_sink/notable_reaction), feature-flag «off→None→inert», `_REPO_ROOT` при переносе app.py, boot-order в `build_application`.

**Корневые находки аудита:** (1) монолит доков = граф из 4 нод, все `beadloom:domain=bob`, 0 feature/component → `docs generate` no-op (→ BDL-UX #138); (2) правило слоёв beadloom НЕ энфорсится (только `domain-needs-parent`). Полные находки — сессия аудита `13b1e49b`, 5 субагентов.

---

## Template

```markdown
### #N [YYYY-MM-DD] [SEVERITY] Короткое описание

**Area:** docs | architecture | clean-code | hygiene | readme | tooling
**Context:** что делали / где всплыло
**Issue:** что не так
**Expected:** как должно быть
**Depends / Notes:** зависимости, ссылки
```

---

## Open Issues

### 🧰 Находки и долги сессии 2026-08-03…05 (эпики BOB-087 + BOB-090)

### #37 [2026-08-05] [HIGH] 🔴 Гейты умеют показывать зелёное, ничего не проверив — 5 случаев за два дня

**Area:** tooling · **Context:** эпики BOB-087 и BOB-090, независимая верификация координатором.
**Issue:** пять раз проверка отрапортовала «чисто» о том, чего не делала:
(1) `beadloom lint` на инкрементальном индексе не видит новых импортов — цикл `memory↔conversation`
прошёл сквозь всю верификацию, включая независимую перепроверку (BDL-UX #142, третье подтверждение);
(2) `sync-check` не строит пары для `component`-узлов — «чисто» по `llm`/`telegram`/`persistence`/`config`
означает «пар не существует» (BDL-UX #146);
(3) mutmut оставляет в `src/**/__pycache__` байткод из песочницы, и следующий `pytest` может
исполнить СТАРЫЙ код;
(4) объявленная mutation-цель в исключённой зоне (`*/adapters/*`) даёт 0 мутантов при «покрыто»;
(5) модуль в `source_paths`, но его тест не в `pytest_add_cli_args_test_selection` → 104 мутанта
«no tests» у `send_to_chat`, 100 у `consolidate_memory`.
**Expected:** проверка обязана отличать «проверил и чисто» от «не смотрел».
**Статус:** ⚠️ частично закрыт — заведён `CLAUDE.md` §0.3 «Правила верификации» (8 правил, каждое из
случая в этом репо), `scripts/mutation.sh` чистит байткод, оба фантомных гейта починены. Класс
проблемы остаётся: слепые зоны mutmut (модульные константы, `isinstance`, enum-вердикты) неустранимы
инструментом — их держат содержательные юниты и саботаж-проверки.

### #38 [2026-08-05] [MEDIUM] 🔴 Живой смоук — часть приёмки, а не «если останется время»

**Area:** process · **Context:** эпик BOB-090 был объявлен закрытым по зелёным гейтам (6117 тестов,
lint 0/224, mutation ядер); первый же реальный разговор вскрыл дефект, который тесты не видели.
**Issue:** Боб считал, что уже рассказал в группу, потому что нить не различала личку и комнату —
и не звал инструмент. Ни один из 6117 тестов этого не поймал: все они проверяли механизмы по
отдельности, а дефект жил в связке «нить → уверенность → решение не действовать».
**Expected:** эпик считается закрытым ПОСЛЕ живого смоука, а не после мёржа. Смоук записан в PLAN
как критерий приёмки — его нельзя двигать в конец «на потом».
**Notes:** родственно уроку BOB-084 (краш при 4675 зелёных) и BOB-087.D5b (мёртвый реюз worktree при
зелёных unit и BDD): тест на фейке доказывает контракт фейка.

### #39 [2026-08-05] [MEDIUM] `coding_assistant.py` — 955 строк, следующий монстр после разделения узла

**Area:** clean-code · **Context:** долг `bob-6u2` закрыт разделением узла `coding` → `coding` +
`interactive` (216 → 172 и 48 символов, спецправило удалено). Но файловая когезия осталась.
**Issue:** `coding/usecases/coding_assistant.py` — 955 строк / 30 символов: оркестратор гейтед-сессии
делает и план, и апрув, и исполнение, и PR, и нарратив. `interactive/usecases/session.py` после
выноса `ResumeNegotiation` + `SessionTeardown` — 709 строк / 22 метода.
**Expected:** разобрать по называемым ответственностям, как это сделали с интерактивом.
**Notes:** узловой потолок больше не давит (оба узла под общим 200) — это долг читаемости, не правил.

### #40 [2026-08-05] [LOW] Адрес эпизода пишется, но production-читателя у него нет

**Area:** architecture · **Context:** BOB-090.C2 добавил `origin_chat_id`/`origin_topic_id`.
**Issue:** адрес заполняется на каждом ходу, но ни один продакшн-путь его не читает: адрес доставки
берётся из конфига известных адресов, а не из памяти.
**Expected:** это фундамент под несколько комнат (BOB-048) — либо появится читатель, либо надо честно
описывать как «Боб хранит место», а не «знает точный адрес» (сейчас так и описано).

### #41 [2026-08-05] [LOW] Канон GUPPI разрезан: интерактивный терминал выбирает канал структурно

**Area:** architecture · **Context:** BOB-090.D ввёл `speaker_for`/`channel_for` как единственный
перевод «вид сообщения → бот».
**Issue:** канал живого интерактивного терминала выбирается по-старому, минуя ядро канона; сам канон
живёт в домене `coding`, тогда как `guppi_canon` — в `personality/voice.py`.
**Expected:** один перевод для всех каналов; канон в одном месте.

### #42 [2026-08-05] [MEDIUM] Goal Engine отгружен, но ни разу не валидирован вживую

**Area:** architecture · **Context:** ROADMAP Тир 2 (автономность) — приоритет ВЫШЕ кодера.
**Issue:** `goals.pursuit_enabled` выключен с момента отгрузки (BOB-015); движок собственной инициативы
не проверялся на живых данных ни разу. Чем дольше спит, тем дороже включение.
**Expected:** разобрать состояние детально, оценить нужную доработку, включить осознанно — вероятно
отдельным срезом с гейтом и живым смоуком.

### #43 [2026-08-05] [LOW] Остатки ревью, отложенные сознательно

**Area:** hygiene · **Context:** SECURITY-review срезов BOB-087.E и BOB-090.G.
**Issue:** (а) `extra_dir_argv` пропускает юникод-дефисы (`–`, `−`) — инъекции нет, но слот кэпа
съедается; (б) дедуп доп-директорий регистро-чувствителен — на case-insensitive FS один каталог
занимает два слота; (в) `_str_list` режет CSV по запятой, поэтому путь с запятой из env невыразим;
(г) `site/docs/**` отстал репо-широко — нужна регенерация `beadloom docs site` перед публикацией Pages;
(д) предсуществующий дрейф `architecture.md` держит `beadloom ci` красным одинаково на main и ветках.
**Expected:** разобрать пакетом в чоре, не срезом.

### 📚 Документация (монолит → beadloom-parity дерево)

> 🔴 ROOT CAUSE (аудит ①): граф bob = **4 ноды** (1 service + 3 domain), все source-тэги
> `beadloom:domain=bob` (186 файлов, **0** feature/component). `docs generate` node-driven →
> эмитить нечего → tech-writer дописывает всё в `architecture.md` (4095 строк / ~110 секций).
> Эталон beadloom: ~65 нод → 32 SPEC + 19 DOC. Фикс — гранулярные тэги + ноды графа → генерация.

### #1 [2026-07-02] [HIGH] ✅ ЗАКРЫТ Пере-аннотировать исходники гранулярными `beadloom:feature=`/`component=`
**Area:** docs · **Issue:** все 186 файлов помечены blanket `beadloom:domain=bob` — нулевая гранулярность, из-за чего граф пуст и доки не генерятся. **Expected:** тэги domain + feature/component по целевым модулям (personality/conversation/memory/capabilities/social/proactivity/coding + infra-адаптеры). **Notes:** root-fix, всё остальное по докам зависит от этого; совпадает с domain-first реорг (#12–#19). · **Статус:** ✅ **закрыт по завершении эпика BOB-062 (.1–.8).** Гранулярная аннотация ехала per-module с каждым срезом (7 бизнес-модулей + kernel/usecases/router/runtime-app + infra-компоненты llm/telegram/persistence/config). Граф вырос до 20 узлов (11 feature + 4 component + 3 domain + 2 service), doc coverage 60%; `beadloom docs audit`/`sync-check`/`config-check` зелёные.

### #2 [2026-07-02] [HIGH] ✅ ЗАКРЫТ Достроить `.beadloom/_graph/services.yml`: feature + component ноды
**Area:** docs · **Issue:** граф не описывает ~30 фич + ~6 компонентов, что есть в коде. **Expected:** добавить ноды (по дереву аудита) + `part_of`/`depends_on`, `beadloom reindex`. **Depends:** #1. · **Статус:** ✅ **закрыт по завершении эпика BOB-062 (.1–.8).** Граф достроен per-module: 11 feature-узлов (7 бизнес-модулей + kernel + usecases + router + runtime-app) + 4 component (llm/telegram/persistence/config) + 3 domain-слоя + 2 service (bob/runtime), 85 рёбер `part_of`/`depends_on`/`touches_code`. `beadloom doctor` — 20 checks clean.

### #3 [2026-07-02] [HIGH] ✅ ЗАКРЫТ `docs generate` + разбить `architecture.md` на per-node SPEC/DOC
**Area:** docs · **Issue:** 4095-строчный монолит; per-feature SPEC/DOC отсутствуют (0 vs beadloom 32+19). **Expected:** сгенерировать скелеты, мигрировать секции H2/H3 по карте аудита; infra `DOC.md` + capability-seam дописать руками (component DOC beadloom не генерит). **Depends:** #2. · **Статус:** ✅ **закрыт по завершении эпика BOB-062 (.1–.8).** 11 per-module SPEC наполнены вместе с domain-first переездом (`docs/domains/{application,capabilities,coding,conversation,domain,infrastructure,memory,personality,proactivity,social}/README.md` + `docs/services/runtime.md`) вместо голых скелетов — Gate требует наполненные доки (`missing_modules`). Монолит `architecture.md` ужат в nav-shell (см. #4). **Остаток (не блок эпика):** 8 узлов-без-SPEC (kernel + usecases/router/runtime-app + component-узлы llm/telegram/persistence/config) — component-DOC `beadloom docs generate` не эмитит; их поверхность описана в `domains/{domain,application,infrastructure}/README.md` + `services/runtime.md`. Отдельные DOC для component-узлов — опциональный follow-up вне эпика (doc coverage 60%).

### #4 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ Ужать `architecture.md` до навигационного обзора
**Area:** docs · **Issue:** сейчас всё-в-одном. **Expected:** таблица доменов + сервисов + Mermaid + ссылки (как beadloom `architecture.md`). **Depends:** #3. · **Статус:** ✅ **отгружено BOB-062.8.** `docs/architecture.md` ужат **4318 → 260 строк** (nav-shell): обзор слоёв (гексагон + kernel + модуль-вертикали), таблица 10 доменов/модулей + runtime-сервис со ссылками на per-module SPEC, курированный Mermaid из `beadloom graph`, сквозной поток «обработка сообщения» (тонкий оркестратор `HandleMessage` + карта 14 коллабораторов), указатели на getting-started/runtime/тесты. Вырезаны ~25 per-feature H2-нарративов (дублировали SPEC). 203 doc↔code пары `bob`-узла переаттестованы (`sync-update bob --yes`); `sync-check`/`docs audit` зелёные.

### #5 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ Добавить `docs/getting-started.md` (+ минимальные `guides/`)
**Area:** docs · **Issue:** отсутствует quickstart/гайды (у beadloom есть). **Expected:** run/config быстрый старт + опц. гайды. · **Статус:** ✅ **отгружено BOB-062.8.** Добавлен `docs/getting-started.md` — first-run walkthrough: предпосылки (uv/Ollama/Qwen), установка (`uv sync` + `scripts/setup-ollama.sh`), конфигурация (`config/bob.example.yaml` + env `BOB_*`/`GUPPI_TELEGRAM__TOKEN`), запуск лаунчером `./bob start|status|logs|restart|stop`, проверка (pytest/ruff/mypy). Консолидировано из README `## Installation`/`## Quick start` + прежней arch-секции «Конфигурация и запуск». Опциональные `guides/` не заводились (не требуются).

### 🏛️ Domain-first реорганизация (screaming architecture, beadloom-parity)

> Целевые модули: **personality · conversation · memory · capabilities · social · proactivity ·
> coding** (бизнес) + **application · infrastructure · runtime** (техн.). Инкрементально,
> поведение-сохраняюще, per-module вертикали. Карта «файл→модуль» — в аудите ④.

### #9 [2026-07-02] [HIGH] ✅ ЗАКРЫТ Декомпозиция `handle_message.py` (3523 стр, God use-case)
**Area:** architecture · **Issue:** 1 класс, ~50 инъекций, ~40 методов, 14 портов. **Expected:** ~14 cohesion-коллабораторов → целевые модули; `handle()` = тонкий оркестратор. 🔴 инварианты: verify-once-per-turn, регенерация, essential-vs-decorative, per-turn announcer, floor-advance на всех ветках. · **Статус:** ✅ **отгружено BOB-062.6b** (срез 6b/8): God-логика **растворена** — `HandleMessage.handle()` теперь тонкий оркестратор (perceive→who→gate→compose+guard→post-effects), делегирующий **14 когезивным коллабораторам**, разложенным по чистым вертикалям: `DiagramSender` (capabilities); `EssentialRunner`/`PreComposeGate` (application); `FloorManager`/`VerifyStep`/`AddressivityPerceiver`/`EngagementModel`/`RecallAssembler`/`TurnGate`/`AntiRepeatGuard` (conversation); `MoodPerceiver`/`GroundedAddons`/`VoiceComposer` (personality); `SocialContext` (social). 🔴 **Цикл compose↔guard замкнут callback по значению** (`AntiRepeatGuard` берёт `VoiceComposer.compose`, БЕЗ импорта `conversation→personality`); turn-local state (`verify_note`/`closer_nudge`/`recalled`/`is_guest`) — через аргументы, не атрибут (класс — shared singleton). Method-object рефактор behavior-preserving: `_build` не менялся (360 тестов валидны), seeded-RNG порядок draw'ов сохранён, инварианты целы (`pytest`/`ruff`/`mypy --strict` зелёные). **Остаток** `handle_message.py` (3524→**1634** стр) = легитимная композиция (`__init__` composition-root + injection-Protocol'ы коллабораторов + тонкие делегаторы) → **проводка мигрирует в runtime в .7** (вместе с #10 app.py→runtime). Доки наполнены: `docs/architecture.md` (handle_message-секция + пути коллабораторов) + SPEC `docs/domains/{application,conversation,personality,social,capabilities}/README.md`. #32 floor-персонализация не входила.

### #10 [2026-07-02] [HIGH] ✅ ЗАКРЫТ Декомпозиция `app.py` (2815 стр, God composition-root)
**Area:** architecture · **Issue:** wiring + 8 инлайн-адаптеров + God-`build_application` (~700 стр) + entrypoint в одном файле. **Expected:** `runtime/{main,composition,config}.py`; инлайн-адаптеры → `infrastructure/telegram|llm/`; per-domain билдеры. 🔴 риски: boot-order, shared-instance инварианты (diagram_sink/notable_reaction), feature-flag «off→None→inert», `_REPO_ROOT` при переносе. Порядок AR-1→8 (аудит ③). · **Статус:** ✅ **закрыт полностью — оба God-дела composition-root отгружены** (срезы 7a + 7b/8):
1. **`app.py`→`runtime/` (BOB-062.7a):** `app.py` (2819 стр) → пакет `src/bob/runtime/` (`composition.py` `build_application`+`Application` · `main.py` entrypoint · `clock.py` `SystemClock` · `config.py` ридеры + 🔴 `_REPO_ROOT parents[2]→[3]` с unit-тестом `test_runtime_repo_root.py` · `wiring/` `_build_*` фабрики по домам); инлайн-адаптеры вернулись в дома (`infrastructure/telegram/{aiogram_adapter,outage_notifier}`, `social/adapters/{permission_channels,soul_loader}`, `coding/adapters/owner_notifier`); `app.py` = тонкий re-export shim (launcher `./bob` + 27 тестов держатся). Инварианты целы (boot-order дословно, shared `diagram_sink`/`notable_reaction` не раздвоены, флаги off→None→inert); 7 правил `*-no-composition-root` расширены с `app.py` на `bob/runtime/`. 🔴 **Коллизия имён разведена:** `bob.runtime` (composition root) ≠ `bob.application.runtime` (async-примитивы). SPEC: `docs/services/runtime.md`.
2. **kernel-split (BOB-062.7b, долг варианта C с .2 закрыт структурно):** `SqliteMemoryRepo` (647 стр, совмещал connection/schema-kernel + memory-реализацию) расщеплён на **connection-kernel** `SqliteConnection` (`infrastructure/persistence/connection.py` — чистое I/O: WAL/foreign_keys/sqlite-vec/`executescript(schema.sql)`/миграции/kv/`.connection`-шов) ↔ **MemoryRepo** `SqliteMemoryRepo` (`memory/adapters/sqlite_memory_repo.py`); `MemoryVectorStore` → `memory/adapters/`. 13 «чужих» сторов код не тронут (структурный `.connection`-шов, composition-root инъектит `SqliteConnection`); ребро `kernel→bob.memory.entities` устранено (memory-типы замкнуты в модуле); `schema.sql` единой (schema-owner), `_migrate_pursuit_stopped` помечена future-relocation; persistence-facade очищен (был стейл god-facade → экспортит только `SqliteConnection`). SPEC: `docs/domains/{memory,infrastructure}/README.md` + `docs/architecture.md`.

### #14 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ Вертикаль **social** → `social/` (identity/first-impression/relationships + authz + permission)
**Area:** architecture · **Issue:** соц-логика расколота (domain/permission + application/authz + usecases/permission_*). **Depends:** #7. · **Статус:** ✅ **отгружено BOB-062.5** (срез 5/8): вертикаль `src/bob/social/` собрана (identity `interlocutor`/`first_impression`/`relationship`/`sulk` + `permission/` + `usecases/` authz/perception/permission-flow/`run_genesis` + `adapters/` сторы+`privilege_judge`). 🔴 **Разорваны 2 цикла — образцово для .6:** `personality↔social` (`interlocutor` переехал из personality; `voice.py` читает `kind.value`, не импортит `InterlocutorKind`) и `social↔ports` (тонкий re-export-шим). `social→personality` однонаправленно (`relationship→negotiation.Stance`); `privileged_fulfiller` остался в `application` (cross-domain оркестратор); kernel — вариант C до .7. SPEC: `docs/domains/social/README.md`. Тот же приём разрыва цикла применить к `personality↔conversation` в .6.

### #15 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ Вертикаль **conversation** → `conversation/` (floor/адресность/brevity/судьи/анти-тик/interim)
**Area:** architecture · **Issue:** hotspot импортов (personality↔conversation). **Depends:** #7, частично #9 (куски handle_message). · **Статус:** ✅ **отгружено BOB-062.6a** (срез 6/8): вертикаль `src/bob/conversation/` собрана (addressivity / conversation_floor / brevity / engagement / zone_classifier / судьи response+volatility / interim_line / анти-тик `conversation` + `usecases/DecideResponse` + `adapters/` Llm-судьи и Sqlite floor/closer-log-сторы). 🔴 **Разорван цикл `personality↔conversation`** (`voice↔brevity/engagement`): определения `Verbosity`/`EngagementLevel` перенесены в `personality/expression.py`, `brevity`/`engagement` их ВОЗВРАЩАЮТ → `conversation→personality` однонаправленно, `no-dependency-cycles` зелёный. `zone_classifier` + порт `ZoneClassifier` здесь (классификатор хода). SPEC: `docs/domains/conversation/README.md`.

### #16 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ Вертикаль **personality** (slimming, +voice) + **capabilities** (introspection/diagrams domain-логика)
**Area:** architecture · **Depends:** #7, #15. · **Статус:** ✅ **закрыт полностью** — **capabilities-вертикаль** отгружена BOB-062.4 (срез 4/8), **personality-вертикаль** отгружена BOB-062.6a (срез 6/8): `src/bob/personality/` — стабильное ядро характера (mood/disposition/taste(+evolution)/negotiation/fascination/phantom/expression/voice/reaction*/reflection/soul + `usecases/` mood/reflection/fascination + `adapters/` reaction-judge/сторы). 🔴 personality — стабильное ядро (0 runtime-deps на conversation/social); `Verbosity`/`EngagementLevel` — вокабуляр выражения здесь; `perceive_reaction` остаётся в `application` (cross-domain). SPEC: `docs/domains/personality/README.md`.

### #17 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ **runtime/** + тонкий **application/** (кросс-доменные оркестраторы)
**Area:** architecture · **Depends:** #10, #9. · **Статус:** ✅ **отгружено BOB-062.7a** (срез 7a/8): composition root вынесен из `app.py` в связный пакет `src/bob/runtime/` (composition/main/clock/config/wiring — единственный слой, зовущий все слои и все модули; модули НЕ импортят runtime, 7 правил `*-no-composition-root`). `application/` остаётся тонким: кросс-доменные оркестраторы, требующие несколько bounded-context'ов (`privileged_fulfiller`, `perceive_reaction`, `handle_message`-коллабораторы `EssentialRunner`/`PreComposeGate`), живут в `application/usecases/`, а сама проводка ушла в `runtime/`. 🔴 `bob.runtime` (composition root) разведён с `bob.application.runtime` (async-примитивы `AgentRuntime`/`AsyncEventBus`/`periodic` — узел `runtime-app`). SPEC: `docs/services/runtime.md`.

### #18 [2026-07-02] [LOW] ✅ ЗАКРЫТ Удалить шим `domain/ports.py` + финальный reindex/sync-check
**Area:** architecture · **Depends:** #7 + все вертикали. · **Статус:** ✅ **отгружено BOB-062.8.** Транзитный re-export-шим `domain/ports/` удалён целиком; 7 kernel-контрактов (`Clock`/`EventBus`/`EventHandler`/`DomainEvent`/`LLMProvider`/`LLMMessage`/`JsonValue`) переехали в shared kernel `src/bob/kernel/ports.py` (инфра-нейтральный inward-safe leaf, правила `kernel-no-*`). 109 импортёров переведены на канон (`bob.<module>.ports` / `bob.kernel.ports`); `from bob.domain.ports` больше не резолвится. Вырожденная `src/bob/domain/` удалена целиком — исчезла последняя layer-first папка. Финальный `reindex --full` + `sync-check` + `lint --strict` — EXIT 0. Заодно (#8-флип) `no-monster-modules` warn→error и char-class-дыра генератора границ закрыта explicit-path'ами.

### 🧼 Clean Code (база чистая; след. кандидаты после монстров)

> Позитив (аудит ⑤): нет bare-`except`/`print`/`breakpoint`; 54 `except Exception` — осознанный
> резилентный паттерн; TODO — это BOB-XXX-плейсхолдеры. Реальные кандидаты ниже.

### #25 [2026-07-02] [MEDIUM] Декомпозировать `infrastructure/telegram/gateway.py` (1004 стр)
**Area:** clean-code · **Issue:** вероятно мешает transport + dispatch. **Expected:** разнести по когезивным помощникам.

### #26 [2026-07-02] [LOW] Декомпозировать след.-тир use-cases (`coding_assistant` 674, `heartbeat` 668, `guppi` 670)
**Area:** clean-code · **Notes:** дружит с вертикалями #11/#13.

### #27 [2026-07-02] [LOW] Типизированный Protocol/stub для PTB-обёртки → убрать 10 `# type: ignore`
**Area:** clean-code · **Issue:** все 10 `# type: ignore[attr-defined]` в app.py (2670–2775), одна причина. **Expected:** типобезопасная обёртка бота.

### #28 [2026-07-02] [LOW] `Any` в `config/loader.py` (3) — оценить сужение типов
**Area:** clean-code · **Notes:** приемлемо, но кандидат на TypedDict/dataclass-конфиг.

### 🔧 Прочее / процесс

### #30 [2026-07-02] [MEDIUM] ✅ ЗАКРЫТ (мастер) Мастер-эпик реорганизации: связать #1–#18 в BOB-062
**Area:** architecture · **Notes:** доки (#1–#6) + domain-first (#7–#18) — один связанный эпик (per-module вертикали: код-переезд + `beadloom:` тэги + граф-ноды + доки за раз). Быстрые победы (#19–#24) — параллельно/вперёд. · **Статус:** ✅ **ЭПИК BOB-062 → Done (2026-07-28).** Все 8 срезов отгружены (.1 coding · .2 memory · .3 proactivity · .4 capabilities+генератор границ · .5 social · .6a personality+conversation · .6b handle_message · .7a runtime+app.py · .7b kernel-split · .8 ports-шим+доки-финиш). Закрыты #1–#6, #9–#18. Итог: 7 вертикальных бизнес-модулей + kernel/application/infrastructure/runtime, `src/bob/domain/` удалён, границы модулей энфорсятся генерируемыми explicit-path правилами (149 правил, 0 нарушений), доки — nav-shell + 11 SPEC + getting-started. `beadloom ci` EXIT 0. Остаток вне эпика: #25–28 clean-code, #31/#32 групповая нагрузка.

### 👥 Групповой диалог под нагрузкой (всплыло 2026-07-28 — команда заходит в группу)

> Аудит по коду перед приглашением команды (3+ активных: Владимир/Норман/Лёша). Мультиперсональный
> **контекст** здоров: cross-sender recall починен (BOB-058, общий тред + regress-тесты), атрибуция
> по `sender_id`, отдельные личности/отношения. Слабые места — **операционные** (нагрузка + адресность).

### #31 [2026-07-28] [HIGH] ✅ ЗАКРЫТ (BOB-066 + BOB-072) Пропускная способность: очередь/бэкпрешер на групповой поток
**Area:** runtime/performance · **Issue:** обработка **полностью последовательна** — `event_bus.py:42-53` (`await gather`) + единственный poll-таск `app.py:2366`; ~1 LLM-вызов даже на IGNORE (judge на каждое сообщение) + 4–6 на ответ; НЕТ очереди/rate-limit/бэкпрешера. Под плотным потоком троих Боб **отстаёт от темы** (отвечает на «протухший» контекст), нет параллелизма даже между разными людьми. **Expected:** per-chat очередь + бэкпрешер (дроп/слияние устаревших; дешёвый гейт ДО дорогого read; конкурентная обработка разных chat_id). **✅ Закрыт:** per-chat очередь + конкурентность chat_id — BOB-066 (`ChatDispatcher`/`ChatInbox`/per-chat воркеры); остаток — **BOB-072** (2026-07-31, PR #99): вместо дешёвого пре-гейта (огрубил бы суждение — против north star) — **коалесинг вспышки → ОДИН холистический batch-read → семантический выбор** (человечнее + быстрее) + queue-stale-coalesce (дроп протухших) + Tier-1 rate-cap. За флагом `presence.stream_read` (активирован). Живой смоук Qwen осмысленный.

### #32 [2026-07-28] [MEDIUM] ✅ ЗАКРЫТ (BOB-066) Персонализация conversation floor по говорящему (мультипати)
**Area:** conversation · **Issue:** floor **единый на чат** (`conversation_floor.py:161` `del sender_id # игнор`, `handle_message.py:2345-2356` thread=None-sentinel). После ответа Боб склонен принять следующую *чью-угодно* безадресную реплику за обращённую к нему → **встревает в кросс-ток** двоих на 1–2 сообщения (частично гасится `reset_after_silent=2` + `others_present`). **Expected:** floor учитывает `sender_id` при переходе (кто реально «держит слово»); Боб не влезает, когда двое других переговариваются между собой. **✅ Закрыт эпиком BOB-066** (2026-07-29, PR #89): floor-по-говорящему (`participants`, additive legacy-safe) — ключевой deliverable Фазы 1; floor учитывает `sender_id`, `others_present` + рефлексивный read гасят влезание в кросс-ток. Живо-валидирован.

> **Приватность (осознанный дизайн, не баг):** унифицированная память группы (BOB-051) «палит» факты
> owner любому авторизованному участнику (кроме reflection/inner-life). Для «своей команды» — ок; если
> захочется owner-only слоя в recall — завести отдельным issue (пока НЕ требуется).

### #33 [2026-07-31] [IMPROVEMENT] Углубить КАЧЕСТВО рефлексивного read-the-room (bd `bob-ew7` / BOB-073, P3)
**Area:** conversation · **Идея (owner):** механика холистического выбора «на что реагировать» готова
(BOB-072 batch-read), но САМО суждение read-the-room можно сделать **ещё тоньше** — чтобы Боб точнее
ловил семантическую адресованность, вопрос-к-Бобу-без-имени, подхват темы, эмоц.значимость реплики в
мультипати. **Не механика** (сделана), а **качество** промпта/сигналов `ROOM_READ`
(`conversation/room_reading_wire.py BATCH_ROOM_READ_SYSTEM_PROMPT`, `room_verdict.py`). **North star:**
максимально человечное понимание «когда реагировать», ноль скриптованности. **Notes:** отдельным
заходом, поверх batch-контракта BOB-072; в PRD BOB-072 явно scope-out.

### 🖥️ Кодер-режим / интерактивный терминал (T3.C⁺, отладка живых прогонов)

### #34 [2026-08-02] [MEDIUM] Tier-0 (Qwen/Aliyun) периодически отваливается по сети → «no fallback»
**Area:** infrastructure/llm · **Context:** анализ живого лога при отладке кодера (BOB-084) — **77×**
`Tier 0 completion failed with no fallback` за день. **Issue:** облачный Tier-0 endpoint
(`token-plan…maas.aliyuncs.com`) периодически недоступен (DNS/сеть); Tier-0 = классификация/монолог/гейты,
без fallback падают обычные ответы Боба (не кодер). **Expected:** устойчивость Tier-0 к отвалу облака —
кандидат: **локальный Ollama-fallback для Tier-0** (тогда сеть до Aliyun не точка отказа), либо проверить/
сменить endpoint. **Depends/Notes:** нужен ввод owner'а (окружение/ключи); отдельно от кодера. Всплыло из
[[bob-084-runner-limit-fix]].

### #35 [2026-08-02] [MEDIUM] Интерактив-терминал: слабое форматирование (не используется rich Telegram)
**Area:** coding/UX · **Context:** живой прогон `/code -i` в личке. **Issue:** `render_stream_event`
(`coding/stream_render.py`) выдаёт плоскую прозу; отправитель (`send_rich_message` →
`MarkdownToRichMessage`) умеет rich (код-блоки/списки/моно), но форматировать нечего. **Expected:**
интерактив-поток использует rich-формат Telegram — команды/код/диффы в код-блоках, пути в `inline code`,
markdown-вывод claude как markdown; удобный UI/UX терминала (возможно rolling-панель + отдельные шаги).
🔴 Приватный чат с ботом поддерживает то же rich-форматирование, что группа (Bot API MarkdownV2/HTML).
**Notes:** различать интерактив-DM (полный+rich) vs односторонний груп-нарратив (краткий).

### #36 [2026-08-02] [HIGH] Интерактив-терминал: ответы claude обрезаются до 200 символов («огрызки»)
**Area:** coding/UX · **Context:** owner просил у claude список багов с приоритетами — получал огрызки.
**Issue:** `stream_render.py:_MAX_TEXT = 200` — ассистентский текст claude намеренно усекается до **200
символов** (кэп был для *краткого* одностороннего нарратива в группу, BOB-082), душит двусторонний
терминал. **Expected:** в интерактив-DM полный текст claude доходит (без усечения либо очень щедрый кэп,
при нужде чанкинг по лимиту Telegram ~4096); краткий груп-нарратив кэп сохраняет. **Depends:** одна фича
с #35 (UX-оверхол интерактив-рендера). Всплыло из отладки [[bob-083-interactive-terminal]].

### #45 [2026-08-05] [MEDIUM] Запись в allowlist без вызывающего = «доступно» на бумаге, недостижимо в коде

**Area:** capabilities · **Context:** BOB-091 — owner попросил Боба нарисовать архитектуру. Разведка
показала: `graph` и `why` лежали в `_BEADLOOM_SUBCOMMANDS` адаптера интроспекции, но **ни один метод
порта до них не доходил** — из четырёх записей работали две (`ctx`, `search`).
**Issue:** allowlist читается как перечень возможностей, а на деле это перечень *разрешений*. Мёртвая
запись выглядит отгруженной фичей и живёт незамеченной сколько угодно (здесь — с BOB-017, то есть
несколько эпиков). Тот же класс возможен в `_BD_SUBCOMMANDS` и в любом будущем шве.
**Expected:** тест «каждая запись allowlist достигается хотя бы одним публичным входом» — иначе запись
либо врёт про доступность, либо это забытая расширенная поверхность subprocess (что хуже: разрешено
больше, чем используется).
**Notes:** закрыто по существу в BOB-091 (обе записи ожили), но **структурной проверки нет** — класс
остаётся открытым.

### #46 [2026-08-05] [MEDIUM] 🔴 Кап вывода резал ДО сжатия — Боб уверенно называл неверные числа

**Area:** capabilities / интроспекция · **Context:** BOB-091.2, живой прогон на реальном `beadloom`.
**Issue:** `_run` обрезал вывод по `introspection.max_output_chars` (20 000) **до** дайджеста. На длинных
отчётах это давало не отказ, а **уверенную неправду**: Боб говорил «274 пары док↔код» вместо 591 и
«150 правил» вместо 225, а у `prime` кап съедал весь хвост (домены, stale, нарушения). Худший класс
дефекта: ответ выглядит точным, число называется без оговорок, проверить его собеседник не может.
**Expected:** сжатие **до** капа для любого источника в шве, а регресс-тест берёт ожидаемое число **из
самого CLI**, а не из константы (иначе тест зафиксирует ту же ошибку).
**Статус:** ✅ исправлено в BOB-091.2 (`_run(..., condense=)`, `why` переведён туда же; числа сверены
координатором с реальностью — 591 и 225 совпали). Класс держать в голове при добавлении новых
источников: 🔴 каждый новый отчёт обязан сжиматься, иначе Боб начнёт врать цифрами.

### #47 [2026-08-05] [LOW] Восстановление саботажа через `git checkout` по файлу стирает работу волны

**Area:** process · **Context:** верификация BOB-091.1 координатором. Проверка на кусачесть требует
саботировать код и убедиться, что тесты краснеют (§0.3 п.5).
**Issue:** снимая саботаж, координатор сделал `git checkout -- <файл>` — а файл был **изменён агентом и
не закоммичен**, поэтому checkout откатил его к HEAD и стёр регистрацию инструментов. Поймано следующим
прогоном (3 красных теста), восстановлено руками. Дешёвая ошибка, но повторяемая: в незакоммиченной
волне `git checkout` снимает не саботаж, а работу.
**Expected:** саботаж снимать **точечной обратной правкой** (или из копии файла, снятой до саботажа);
`git checkout` по файлу допустим только когда волна уже закоммичена.
**Статус:** ✅ зафиксировано правилом `CLAUDE.md` §0.3 п.9.

### #48 [2026-08-06] [HIGH] 🔴 Права закрывают СЕТЬ, но не ФАЙЛЫ: локальная дорога к `main` owner'а остаётся

**Area:** security / инфраструктура · **Context:** BOB-089, тестовая волна; воспроизведено
координатором самостоятельно на выброшенном репозитории.
**Issue:** отдельный клон убрал дорогу, которая открывалась **сама** (в linked worktree refs были
общие), и сетевой путь закрыт по-настоящему — живой смоук 7/7 против настоящего GitHub. Но
**намеренный** обход жив: `.git/logs/HEAD` клона несёт `clone: from file:///<путь owner'а>`;
локальному транспорту креды не нужны; push прямо в `main` отбивает сам git
(`branch is currently checked out`), а вот push в **боковую** ветку проходит — и после него
`git --git-dir=<owner>/.git update-ref refs/heads/main` двигает ствол. Пять шагов, ни одного
пароля.
**Expected:** формулировать защиту по факту («убрана дорога, открывавшаяся сама» + «сетевой путь
закрыт правами»), а закрывать класс — **раздельным UID** (отдельный пользователь / контейнер /
другая машина). Ни один git-механизм тут не поможет: вопрос в правах ОС, а не в кредах.
**Отвергнуто:** гасить подсказку в reflog — security-by-obscurity (путь выводится из cwd, конфигов,
окружения), а хуже всего то, что она создаёт ощущение защиты там, где её нет.
**Адресат:** беада **`bob-r9l` / BOB-093**. Записано в PRD/CONTEXT/ACTIVE BOB-089.

### #49 [2026-08-06] [MEDIUM] Обещание документа надо проверять тестом наравне с кодом

**Area:** process · **Context:** BOB-089: PRD обещал, что «локальные трюки с ref'ами до `main`
owner'а не достают», RFC §3 описывал изоляцию через подмену `GIT_CONFIG_GLOBAL`. Оба утверждения
оказались неверны, и оба вскрылись **только на настоящем git** — первое в тестовой волне, второе
на первой же разведке среза C (`credential.helper=osxkeychain` приезжает из СИСТЕМНОГО
`/opt/homebrew/etc/gitconfig`, который `GIT_CONFIG_GLOBAL` не замещает).
**Issue:** утверждение в PRD/RFC читается как факт и переходит в отчёты, коммиты и разговор с
owner'ом, а проверки у него нет никакой — в отличие от кода, у которого есть гейты. Дважды за один
эпик документ обещал больше, чем схема держит.
**Expected:** заявление о **гарантии** в PRD/RFC либо имеет исполняемую проверку (тест «честной
рамки», как сделала тестовая волна), либо формулируется как замысел, а не как факт. И 🔴 исправлять
такое надо **видимой правкой** — оставляя запись об ошибке, а не переписывая задним числом: так
документ показывает, что проверено, а не что предполагалось.

### #50 [2026-08-06] [MEDIUM] Наш тест зависит от свежести индекса beadloom, который мутируют соседние инструменты

**Area:** tooling · **Context:** волна фиксов BOB-089; `test_prime_keeps_its_tail_sections_on_the_live_cli`
(из BOB-091) покраснел в общем прогоне и позеленел после `rm -f .beadloom/beadloom.db && beadloom
reindex`.
**Issue:** тест читает вывод **живого** `beadloom prime`, то есть его результат зависит от состояния
`.beadloom/beadloom.db`. А это состояние меняют соседние инструменты: плоский `beadloom lint` пишет в
индекс (BDL-UX #147), прогоны `mutmut` тоже его задевают. Получается **ложный красный, ждущий своего
часа**: тест падает не от дефекта кода, а от порядка запусков.
**Expected:** либо тест сам приводит индекс в известное состояние (реиндекс в фикстуре), либо ассертит
свойство, не зависящее от свежести (структура секций, а не их содержимое). Тест на живом CLI ценен —
именно он поймал реальные вещи в BOB-091, — но он не должен зависеть от невидимого общего состояния.
**Notes:** родственно #46: там кап резал числа, здесь окружение меняет вход. Общий класс — «тест на
живом инструменте обязан владеть его состоянием».

### #51 [2026-08-06] [MEDIUM] Параллельные агенты и один файл: восстановление саботажа целым файлом стирает соседа

**Area:** process · **Context:** волна фиксов BOB-089: три dev-агента работали одновременно, у двух
была общая точка — `src/bob/identity/spawn_isolation.py` (одному отдавался только список
`OWNER_CREDENTIAL_VARS`, другому всё остальное). Агент честно предупредил, что восстанавливал файл
**целиком** после саботажа — окно 21 секунда рядом с активной работой соседа.
**Issue:** правило §0.3 п.9 («снимай саботаж обратной правкой, а не `git checkout`») закрывает откат к
HEAD, но не закрывает восстановление **целым файлом из копии**: для соседа это то же стирание, только
из другого источника. Потерь в этот раз не случилось (проверено координатором: вклады обоих в файле
сосуществуют, гейты и живые смоуки зелёные), но это была удача, а не гарантия.
**Expected:** (а) не делить один файл между параллельными агентами — если деление неизбежно, зона
должна быть отдельным модулем; (б) правило §0.3 п.9 дополнить: восстановление **только точечной
обратной правкой**, любой способ, переписывающий файл целиком, в параллельной волне запрещён.

### 🧱 Границы контекстов (всплыло 2026-08-05 на гейте `no-monster-modules`)

### #44 [2026-08-05] [MEDIUM] `capabilities` держит ВТОРОЙ bounded context — развести read-only интроспекцию в свой узел
**Area:** capabilities / граф · **Context:** срез BOB-091.2 (остальной read-only beadloom) довёл узел
`capabilities` до **212 символов** при общем потолке `no-monster-modules` = 200. Узел честно
декомпозирован (41 файл, крупнейший — 22 символа, монстров нет), поэтому в срезе заведён явный бюджет
**230** — по образцу `coding`-220 из BOB-087.D3, с той же пометкой: **это отсрочка, а не решение**.
**Issue:** внутри `capabilities` живёт вторая вертикаль — «Боб читает свой репозиторий и трекер»
(read-only самоинтроспекция). Замер по индексу: `introspection/` 64 символа + `adapters/introspection/`
22 + навыки-чтения в `usecases/` (inspect_architecture / read_code / list_dir / find_file / list_work /
code_rationale / recent_commits / list_tasks / show_task / task_comments / draw_architecture /
architecture_impact / project_health) ≈ 50 → **~135 из 212**. Это отдельный bounded context, а не
подпапка. **Expected:** развести в собственный feature-узел ПАКЕТОМ-СОСЕДОМ (`src/bob/introspection/`),
как `interactive` в BOB-087.E — вложенный узел дал бы двойной учёт, потому что `max_symbols` считает по
префиксу `source`; вертикаль едет целиком (ядра + адаптер + навыки-чтения) вместе со своими
`beadloom:`-тэгами, граф-нодой и доком, после чего персональный бюджет СНИМАЕТСЯ и оба узла проходят
общие 200. **Адресат:** беада **`bob-fyf` / BOB-092** (P2) — на неё сослано и само правило в `rules.yml`,
чтобы отсрочка не жила только записью в файле; приёмка требует **удаления** персонального
правила, а не его ослабления.
**Notes:** в самом `rules.yml` (BOB-087.E) записано, что заводить персональный бюджет снова
= расписываться в том, что граница проведена не там; здесь это признано в открытую. Требует решения
owner'а (это архитектурная граница, а не побочный эффект dev-среза).

---

## Closed Issues

### Фаза 1 — быстрые победы (закрыты 2026-07-02)

**BOB-063 «Гигиена репозитория» (PR #76):**
- ✅ **#6** [.DS_Store] — **no-op**: аудит ① ошибся; `.DS_Store` уже в `.gitignore` (стр. 25) и НЕ трекнут (только на диске). Ничего не трогали.
- ✅ **#19** [dialog.txt/test.txt] — `git rm` orphan-транскриптов из корня; в `.gitignore` добавлены `dialog.txt`/`test.txt`.
- ✅ **#20** [.claude/worktrees/] — добавлено в `.gitignore` (агентские worktree больше не в `git status`).
- ✅ **#21** [personality.md] — `git mv` в `.claude/dev-docs/` + дата-штамп «снапшот» (исторический слепок 2026-06-24).
- ✅ **#22** [archive-бинарники] — `git rm` `old-tooling-state-20260618.tar.gz` + `bob-vr/bob-preview/*.png` (история сохранена в git).
- ✅ **#29** [data/*.bak] — локальный прун ~100 МБ старых бэкапов БД; оставлены `bob.db.bak-pre-bob052` + `…-pre-bob061` (не репо-изменение).

**BOB-064 «Актуализация README ×2» (текущий PR):**
- ✅ **#23** [README shipped vs визия] — оба README переписаны: раздел «What Bob does today (shipped)» (Telegram-чат/личность, память SQLite+FTS5, web_search/read_url, эпистемическая самопроверка, Боб-кодер, проактивность, групповая нить) отделён от `Roadmap / bigger vision` (frozen: облик/камера/планшет/FLUX/голос).
- ✅ **#24** [README Tech Stack + Installation/Quick-start] — стек починен (Python 3.12/asyncio · **aiogram** · Ollama+Qwen 2.5 7B/0.5B + Qwen MaaS · Claude Code CLI · SQLite+FTS5; **FastAPI убран**); добавлены Installation (`uv sync` + `config/bob.example.yaml` + env `BOB_TELEGRAM__TOKEN`/`BOB_LLM__TIER1_API_KEY`) и Quick start (`./bob start|stop|restart|status|logs`). RU=EN.

### Фаза 2 — фундамент (закрыты 2026-07-02, BOB-065, PR ветка `features/BOB-065`)

- ✅ **#7** [split `domain/ports.py`] — монолитный `ports.py` (God-ports) разбит на пакет `domain/ports/` с когезивными подмодулями (`kernel` · `capabilities` · `memory` · `personality` · `conversation` · `social` · `proactivity` · `coding`). `__init__.py` — re-export-шим: `from bob.domain.ports import X` резолвит все 51 публичный символ без изменения импортов (blast radius не тронут). Kernel-порты (`Clock`/`EventBus`/`LLMProvider`/`JsonValue`/`DomainEvent`/`EventHandler`/`LLMMessage`) вынесены в `kernel.py`. Удаление шима — по-прежнему #18 (после domain-first вертикалей).
- ✅ **#8** [beadloom-правило направления слоёв] — введены AaC-правила слоёв (11 правил): направление `domain ← application ← infrastructure` теперь энфорсится `beadloom lint --strict`, а не только документировано. Дрейф границ становится видимым в CI.

### Фаза 3 — domain-first вертикали (эпик BOB-062, срез 1/8)

**BOB-062.1 «Срез coding → `src/bob/coding/`» (первый вертикальный переезд, ветка `features/BOB-062.1`):**
- ✅ **#11** [Вертикаль **coding** → `coding/`] — способность «Боб пишет код» собрана из трёх слоёв (`domain/coding` + `application/usecases/coding_*` + `infrastructure/coding` + persistence/telegram-куски) в один вертикальный модуль `src/bob/coding/` (`ports.py` + логика — `layer=domain`; `usecases/` — `layer=application`; `adapters/` — `layer=infrastructure`). Граф-узел `coding` перецелен (тег `module-vertical`), границы модуля держат path-glob `forbid_import`-правила (внутренний layer + «снаружи только через ports/фасад»), 3 cross-boundary ссылки узаконены. Поведение идентично (`pytest`/`ruff`/`mypy --strict` зелёные), coding-инварианты целы (never-merge / двойной гейт плана / PR≠merge / worktree-изоляция / sender-is-bob). Доки наполнены: SPEC модуля `docs/domains/coding/README.md` + освежены coding-пути в `docs/architecture.md`. **Контрольный вывод:** схема модуля domain-first валидирована review'ом — применяется к срезам .2–.8. **Depends:** #7 (закрыт).

**BOB-062.2 «Срез memory → `src/bob/memory/`» (второй вертикальный переезд, ветка `features/BOB-062.2`):**
- ✅ **#12** [Вертикаль **memory** → `memory/`] — бизнес-логика памяти собрана из слоёв (`domain/memory` + `domain/ports/memory` + `application/usecases/{extract_facts,consolidate_memory,dedup_facts}` + `infrastructure/persistence` recall-адаптеры + `infrastructure/llm` embedder/reranker) в один вертикальный модуль `src/bob/memory/` (`ports.py`+`entities` — `layer=domain`; `usecases/` — `layer=application`; `adapters/` — `layer=infrastructure`). Граф-узел `memory` перецелен (тег `module-vertical`), границы держат path-glob `forbid_import`-правила. **🔴 Вариант C (утв. owner):** kernel персистентности (`SqliteMemoryRepo`+`schema.sql`+`vector_store.py`), кормящий через `.connection()`-шов ~десяток чужих сторов, **остаётся** в `infrastructure/persistence/` до среза **.7** (там инфра-kernel консолидируется и `SqliteMemoryRepo` расщепляется); разрешённое обратное ребро `kernel → bob.memory.entities` помечено TODO-.7 в правилах. Поведение идентично (`pytest`/`ruff`/`mypy --strict` зелёные), memory-инварианты целы (RRF-ранжирование гибридного recall / superseded-исключение / консервативный дедуп ≥0.92 / недеструктивная консолидация / sender-атрибуция / локальность эмбеддингов). Доки наполнены: SPEC модуля `docs/domains/memory/README.md` + освежены memory-пути в `docs/architecture.md`; `beadloom ci` зелёный. **Depends:** #7 (закрыт).

**BOB-062.3 «Срез proactivity → `src/bob/proactivity/`» (третий и крупнейший вертикальный переезд, ветка `features/BOB-062.3`):**
- ✅ **#13** [Вертикаль **proactivity** → `proactivity/`] — «фоновая жизнь Боба» (drive/проактивность + свои цели + самоулучшение) собрана из слоёв (`domain/proactivity` + `domain/goals` + `domain/personality/self_improvement` + `domain/ports/proactivity` + `application/proactivity` + `application/usecases/{plan_goal,pursue_goals,detect_patterns,announce_rules,self_improvement_sources}` + 4 стора в `infrastructure/persistence`) в один вертикальный модуль `src/bob/proactivity/` (`ports.py`+drive-core+`goals/`+`self_improvement` — `layer=domain`; `usecases/` — `layer=application`; `adapters/` — `layer=infrastructure`). Граф-узел `proactivity` перецелен (тег `module-vertical`), границы держат path-glob `forbid_import`-правила (char-class globs расширены `[adim]*→[adimp]*`), cross-boundary ссылки узаконены (personality-flow→`self_improvement`, guppi→proactivity-домен, guppi/multibot→`plan_goal`, ports-шим, `proactivity→memory.entities`). **🔴 Три решения по принадлежности:** `self_improvement.py` забран из `personality` (метакогниция BOB-028, не черта); `run_genesis.py` **остаётся** вне proactivity (first-boot генезис SOUL → срез .5/.6); `goals` — единый `feature=proactivity` (подпапка `goals/`). **🔴 Вариант C (утв. owner):** 4 стора получают connection через kernel-шов `SqliteMemoryRepo.connection()`; `schema.sql` (таблицы proactivity_state/goal/task/improvement_rule) **остаётся** в `infrastructure/persistence/` до среза **.7**; обратной `kernel→proactivity` зависимости НЕТ. Поведение идентично (`pytest`/`ruff`/`mypy --strict` зелёные), proactivity-инварианты целы (urge-монотонность / seeded-RNG детерминизм / 6 governance-вето / двойной гейт целей / стадия-C изоляция / самоулучшение-граница по конструкции + owner-апрув / engine-тишина по умолчанию). Доки наполнены: SPEC модуля `docs/domains/proactivity/README.md` (+ docs-линк узла) + освежены proactivity-пути в `docs/architecture.md`; `beadloom ci` зелёный. **Depends:** #7 (закрыт).

**BOB-062.4 «Срез capabilities → `src/bob/capabilities/`» (четвёртый и крупнейший вертикальный переезд + каркас правил, ветка `features/BOB-062.4`):**
- 🟡 **#16 (часть — capabilities)** [Вертикаль **capabilities** → `capabilities/`] — весь capability-шов «инструменты Боба» (registry + tool-loop + 9 навыков) собран из слоёв (`domain/ports/capabilities` + `domain/{diagrams,introspection}` + `application/capabilities/**` + `infrastructure/{web,diagrams,introspection}` + `infrastructure/llm/web_search_qwen`) в один вертикальный модуль `src/bob/capabilities/` (`ports.py`+`diagrams`/`introspection` — `layer=domain`; `usecases/` — `layer=application`; `adapters/{web,diagrams,introspection}`+`web_search_qwen` — `layer=infrastructure`). Граф-узел `capabilities` перецелен (тег `module-vertical`), 18 портов re-export'ятся из `bob.domain.ports` (шим). Cross-boundary ссылки узаконены (`llm.factory→capabilities.adapters` RUNTIME, `coding→capabilities` TC `PrivacyGuard`, `capabilities→memory.MemoryRecall`, ports-шим, `handle_message`/`privileged_fulfiller`→usecases). **🔴 Решения:** `CollectingDiagramSink` — один разделяемый инстанс на процесс (иначе inline-mermaid дедуп рвётся); `InterimLineGenerator` помечен кандидатом на извлечение в `conversation` (.6); kernel не тронут (вариант C). Поведение идентично (`pytest`/`ruff`/`mypy --strict` зелёные), capabilities-инварианты целы (SSRF-guard `read_url` / PrivacyGuard `ALLOWED_ROOTS` / tool-loop-порядок / announce live-only / web_search streaming / safe-allowlist автономии). Доки наполнены: SPEC модуля `docs/domains/capabilities/README.md` (+ docs-линк узла) + освежены capabilities-пути в `docs/architecture.md`; `beadloom ci` зелёный. **Остаётся по #16:** personality slimming (+voice) → срез .5/.6.
- ✅ **#8 (укрепление)** [каркас правил границ] — введён **генератор** `scripts/gen_boundary_rules.py`: эмитит per-module `forbid_import` на **explicit paths** (`src/bob/<module>/…`) в marker-регион `# BEGIN/END generated boundary rules`, режим `--check` — CI-gate идемпотентности. Закрыл **c/c-риск каркаса** (прежний char-class `src/bob/[adimp]*` физически не различал `capabilities` и `coding` — оба на `c`, fnmatch ключуется по первому символу; вердикт review .3) и **дыру internals-no-adapters** (доменная логика могла тянуть adapters — находка test .3): теперь у КАЖДОГО модуля есть `internals-no-adapters`. Char-class-правила coding/memory/proactivity конвертированы на explicit-path без ослабления семантики (сверка `beadloom lint` findings до/после); координационные слои (`application`/`infrastructure`/`runtime`/`app.py`) из inward-модели исключены намеренно. c/c-изоляция coding↔capabilities реально ловится (`tests/capabilities/test_layering.py`).

**BOB-062.6a «Срез personality + conversation → два bounded-context» (шестой переезд + разрыв 2-го цикла, ветка `features/BOB-062.6a`):**
- ✅ **#16 (часть — personality)** + ✅ **#15 (conversation)** [прежний `domain/personality/` расформирован в ДВА чистых вертикальных модуля] — критерий «максимально правильно по DDD/cohesion»: разные ubiquitous language + высокая внутренняя когезия → НЕ merged, а два контекста. `src/bob/personality/` («кто Боб есть» — стабильное ядро: mood/disposition/taste(+evolution)/mood_taste/negotiation/fascination/phantom/expression/voice/language/profanity/семейство reaction*/reflection/soul + `usecases/` mood/reflection/fascination + `adapters/` reaction-judge/сторы) и `src/bob/conversation/` («как ведётся ход»: addressivity/conversation_floor/brevity/engagement/zone_classifier/судьи response+volatility/interim/анти-тик + `usecases/DecideResponse` + `adapters/` Llm-судьи и Sqlite floor/closer-log-сторы). Оба узла перецелены (тег `module-vertical`, 7 верти­калей); порты re-export'ятся из `bob.domain.ports` (два тонких шима). **🔴 Разорван цикл `personality↔conversation`** (`voice↔brevity/engagement`, behavior-preserving, .1): определения `Verbosity`/`EngagementLevel` перенесены в `personality/expression.py` (вокабуляр выражения), `brevity`/`engagement` их ВОЗВРАЩАЮТ → `conversation→personality` однонаправленно, `no-dependency-cycles` зелёный, тон Боба идентичен. **🔴 Cohesion-раскол:** `negotiation`+`reaction_judgment` → personality (стойка/эмоц-отклик характера); `zone_classifier`(+порт)+`response`/`volatility_judgment` → conversation (решения хода); `perceive_reaction` остаётся в `application` (cross-domain над mood+relationship). Cross-module ссылки узаконены note-блоком rules.yml (conversation→personality однонапр.; perceive_reaction→personality+social; handle_message/heartbeat/proactivity.engine→conversation; social.relationship→negotiation.Stance; ports-шимы). Поведение идентично (`pytest`/`ruff`/`mypy --strict` зелёные), инварианты целы (voice-тон / brevity+verbosity / engagement+fatigue / floor-advance / адресность / анти-тик / судьи + разрыв обоих циклов). Доки наполнены: SPEC `docs/domains/personality/README.md` + `docs/domains/conversation/README.md` (+ docs-линки узлов) + освежены personality/conversation-пути в `docs/architecture.md`; `beadloom ci` зелёный. **Остаётся:** декомпозиция `handle_message.py` (#9, God use-case) → срез **.6b** (только импорт-пути перецелены в .6a); `#32` floor-персонализацию можно там же.

**BOB-062.8 «Закрытие каркаса: kernel + ports-шим + доки-финиш» (финальный срез 8/8 эпика, ветка `features/BOB-062.8`):**
- ✅ **#18** [удалить шим `domain/ports.py`] + ✅ **#8-флип** [no-monster «зубы»] — транзитный re-export-шим `domain/ports/` удалён; 7 kernel-контрактов (`Clock`/`EventBus`/`EventHandler`/`DomainEvent`/`LLMProvider`/`LLMMessage`/`JsonValue`) переехали в shared kernel `src/bob/kernel/ports.py` (инфра-нейтральный inward-safe leaf; правила `kernel-no-*`: модули→kernel легально, kernel↛модули). 109 импортёров переведены на канон (`bob.<module>.ports` / `bob.kernel.ports`), `from bob.domain.ports` не резолвится, вырожденная `src/bob/domain/` удалена целиком. `no-monster-modules` flip warn→error (0 warnings); char-class-дыра генератора границ (`[!au]*`/`[!u]*`) закрыта explicit-path'ами. Поведение неизменно (pytest/ruff/mypy ПОЛНЫЙ зелёные), `reindex --full && lint --strict` EXIT 0. Две мёртвые `domain-*` правила (ссылались на удалённый `src/bob/domain/**`) убраны из `rules.yml` (интент покрыт `kernel-no-*` + границами модулей).
- ✅ **#4** [ужать `architecture.md`] + ✅ **#5** [getting-started] + ✅ **#1/#2/#3** [аннотации/граф/доки-финиш] — `docs/architecture.md` ужат 4318→260 строк (nav-shell: слои+kernel обзор, таблица 10 модулей + runtime-сервис со ссылками на SPEC, курированный Mermaid из `beadloom graph`, сквозной поток «обработка сообщения» + карта 14 коллабораторов). Добавлен `docs/getting-started.md` (first-run: uv/Ollama/config/`./bob`). 11 per-module SPEC освежены под .8 (канон-импорты портов; `domains/domain/README.md` переписан из описания удалённой `src/bob/domain/` в навигационную карту domain-слоя = kernel + domain-слои модулей). 203 doc↔code пары `bob`-узла переаттестованы. `beadloom ci` EXIT 0 (reindex/lint/sync-check/docs-audit/config-check/doctor — все PASS); `setup-rules --refresh` синхронизировал auto-managed CLAUDE.md/AGENTS.md (kernel-модуль, no domain).
- 🔴 **ЭПИК BOB-062 → Done.** Эпик закрыт (#1–#6, #9–#18, #30). Остаток в бэклоге вне эпика: #25–28 clean-code, #31/#32 групповая нагрузка.
