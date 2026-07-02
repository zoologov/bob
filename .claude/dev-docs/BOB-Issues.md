<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Bob Engineering Issues Log

> Потенциальные проблемы и улучшения, собираемые в процессе разработки (по образцу
> beadloom `BDL-UX-Issues.md`). Фиксируем находки — фиксим планово.
>
> **Total:** 30 · **Open:** 30 · **Closed:** 0
> 2026-07-02 (комплексный аудит, 5 субагентов read-only): заведён лог. Открыты #1–#30
> из аудита организации/DDD/доков/гигиены. Источник: сессия аудита `13b1e49b`.

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

### 📚 Документация (монолит → beadloom-parity дерево)

> 🔴 ROOT CAUSE (аудит ①): граф bob = **4 ноды** (1 service + 3 domain), все source-тэги
> `beadloom:domain=bob` (186 файлов, **0** feature/component). `docs generate` node-driven →
> эмитить нечего → tech-writer дописывает всё в `architecture.md` (4095 строк / ~110 секций).
> Эталон beadloom: ~65 нод → 32 SPEC + 19 DOC. Фикс — гранулярные тэги + ноды графа → генерация.

### #1 [2026-07-02] [HIGH] Пере-аннотировать исходники гранулярными `beadloom:feature=`/`component=`
**Area:** docs · **Issue:** все 186 файлов помечены blanket `beadloom:domain=bob` — нулевая гранулярность, из-за чего граф пуст и доки не генерятся. **Expected:** тэги domain + feature/component по целевым модулям (personality/conversation/memory/capabilities/social/proactivity/coding + infra-адаптеры). **Notes:** root-fix, всё остальное по докам зависит от этого; совпадает с domain-first реорг (#12–#19).

### #2 [2026-07-02] [HIGH] Достроить `.beadloom/_graph/services.yml`: feature + component ноды
**Area:** docs · **Issue:** граф не описывает ~30 фич + ~6 компонентов, что есть в коде. **Expected:** добавить ноды (по дереву аудита) + `part_of`/`depends_on`, `beadloom reindex`. **Depends:** #1.

### #3 [2026-07-02] [HIGH] `docs generate` + разбить `architecture.md` на per-node SPEC/DOC
**Area:** docs · **Issue:** 4095-строчный монолит; per-feature SPEC/DOC отсутствуют (0 vs beadloom 32+19). **Expected:** сгенерировать скелеты, мигрировать секции H2/H3 по карте аудита; infra `DOC.md` + capability-seam дописать руками (component DOC beadloom не генерит). **Depends:** #2.

### #4 [2026-07-02] [MEDIUM] Ужать `architecture.md` до навигационного обзора
**Area:** docs · **Issue:** сейчас всё-в-одном. **Expected:** таблица доменов + сервисов + Mermaid + ссылки (как beadloom `architecture.md`). **Depends:** #3.

### #5 [2026-07-02] [MEDIUM] Добавить `docs/getting-started.md` (+ минимальные `guides/`)
**Area:** docs · **Issue:** отсутствует quickstart/гайды (у beadloom есть). **Expected:** run/config быстрый старт + опц. гайды.

### #6 [2026-07-02] [LOW] Убрать закоммиченные `.DS_Store` + gitignore
**Area:** docs/hygiene · **Issue:** `docs/.DS_Store`, `docs/domains/.DS_Store` в git. **Expected:** удалить + правило в `.gitignore`.

### 🏛️ Domain-first реорганизация (screaming architecture, beadloom-parity)

> Целевые модули: **personality · conversation · memory · capabilities · social · proactivity ·
> coding** (бизнес) + **application · infrastructure · runtime** (техн.). Инкрементально,
> поведение-сохраняюще, per-module вертикали. Карта «файл→модуль» — в аудите ④.

### #7 [2026-07-02] [HIGH] Split `domain/ports.py` (1153 стр, God-ports) по модулям + shared kernel
**Area:** architecture · **Issue:** 49 портов/значений в одном файле; импортят **141 файл** (blast radius). **Expected:** каждый модуль владеет своими `ports.py`; `Clock`/`EventBus`/`LLMProvider`/`JsonValue` → `runtime/` (kernel). Транзитный re-export-шим `domain/ports.py` на время миграции. **Notes:** фундамент — блокирует вертикали #12–#19.

### #8 [2026-07-02] [HIGH] 🔴 Ввести beadloom-правило направления слоёв (сейчас НЕ энфорсится)
**Area:** architecture/tooling · **Issue:** lint гоняет ТОЛЬКО `domain-needs-parent`; инвариант domain←application←infrastructure лишь задокументирован (`depends_on`), не проверяется → дрейф невидим. **Expected:** `forbid`/`require` правила: бизнес-модули ← application ← infrastructure; runtime — единственный, кто импортит конкреты infra. **Notes:** ставит зубы всей реорганизации.

### #9 [2026-07-02] [HIGH] Декомпозиция `handle_message.py` (3523 стр, God use-case)
**Area:** architecture · **Issue:** 1 класс, ~50 инъекций, ~40 методов, 14 портов. **Expected:** ~14 cohesion-коллабораторов (TurnGate, VerifyStep, AntiRepeatGuard, SocialContext, VoiceComposer, EngagementDecider, RecallAssembler, ThreadReplay, DiagramPresenter, ReplyComposer, EssentialRunner…) → целевые модули; `handle()` = тонкий оркестратор (~40 строк). Волны 0→3 (аудит ②). 🔴 инварианты: verify-once-per-turn, регенерация, essential-vs-decorative, per-turn announcer, floor-advance на всех ветках.

### #10 [2026-07-02] [HIGH] Декомпозиция `app.py` (2815 стр, God composition-root)
**Area:** architecture · **Issue:** wiring + 8 инлайн-адаптеров + God-`build_application` (~700 стр) + entrypoint в одном файле. **Expected:** `runtime/{main,composition,config}.py`; инлайн-адаптеры → `infrastructure/telegram|llm/`; per-domain билдеры. 🔴 риски: boot-order, shared-instance инварианты (diagram_sink/notable_reaction), feature-flag «off→None→inert», `_REPO_ROOT` при переносе. Порядок AR-1→8 (аудит ③).

### #11 [2026-07-02] [MEDIUM] Вертикаль **coding** → `coding/`
**Area:** architecture · **Issue:** размазано (domain/coding + usecases/coding_* + infrastructure/coding). **Expected:** один вертикальный модуль. **Notes:** самый когезивный/безопасный первый реальный переезд. **Depends:** #7.

### #12 [2026-07-02] [MEDIUM] Вертикаль **memory** → `memory/`
**Area:** architecture · **Issue:** domain/memory + extract_facts/dedup/consolidate + recall/embedder/reranker. **Depends:** #7.

### #13 [2026-07-02] [MEDIUM] Вертикаль **proactivity** → `proactivity/` (drive + goals + self-improvement)
**Area:** architecture · **Depends:** #7.

### #14 [2026-07-02] [MEDIUM] Вертикаль **social** → `social/` (identity/first-impression/relationships + authz + permission)
**Area:** architecture · **Issue:** соц-логика расколота (domain/permission + application/authz + usecases/permission_*). **Depends:** #7.

### #15 [2026-07-02] [MEDIUM] Вертикаль **conversation** → `conversation/` (floor/адресность/brevity/судьи/анти-тик/interim)
**Area:** architecture · **Issue:** hotspot импортов (personality↔conversation). **Depends:** #7, частично #9 (куски handle_message).

### #16 [2026-07-02] [MEDIUM] Вертикаль **personality** (slimming, +voice) + **capabilities** (introspection/diagrams domain-логика)
**Area:** architecture · **Depends:** #7, #15.

### #17 [2026-07-02] [MEDIUM] **runtime/** + тонкий **application/** (кросс-доменные оркестраторы)
**Area:** architecture · **Depends:** #10, #9.

### #18 [2026-07-02] [LOW] Удалить шим `domain/ports.py` + финальный reindex/sync-check
**Area:** architecture · **Depends:** #7 + все вертикали.

### 🧹 Гигиена репозитория

### #19 [2026-07-02] [MEDIUM] Удалить `dialog.txt` + `test.txt` (корень, orphan-транскрипты) + gitignore
**Area:** hygiene · **Issue:** трекнутые дампы диалогов в корне; `test.txt` вводит в заблуждение (похоже на тест). **Expected:** удалить, расширить ignore-правило (как `first_dialogue.txt`).

### #20 [2026-07-02] [LOW] Добавить `.claude/worktrees/` в `.gitignore`
**Area:** hygiene · **Issue:** агентские worktree светятся в `git status`.

### #21 [2026-07-02] [LOW] Перенести `personality.md` из корня → `.claude/dev-docs/` (+ дата-штамп/рефреш)
**Area:** hygiene · **Issue:** снапшот Mermaid-карты не на месте, устарел (~8 дней).

### #22 [2026-07-02] [LOW] Оценить трекнутые бинарники в `.claude/dev-docs/archive/` (tar.gz + PNG)
**Area:** hygiene · **Issue:** бинарные блобы раздувают репо; история и так в git.

### 📄 README (устарели с 2026-02-27, до пивота)

### #23 [2026-07-02] [HIGH] Переписать `README.md` + `README-ru.md`: «сегодня» vs «визия»
**Area:** readme · **Issue:** продают замороженную визию (камера/планшет/FLUX/food-order) как отгруженное; нет раздела «что Боб умеет СЕЙЧАС». **Expected:** отдельно shipped (Telegram-чат, память SQLite+FTS5, личность, web_search/read_url, Боб-кодер, проактивность) и roadmap/frozen.

### #24 [2026-07-02] [HIGH] README: починить Tech Stack + добавить Installation/Quick-start (+ `./bob`)
**Area:** readme · **Issue:** стек неверный (FastAPI есть, Telegram/FTS5/Ollama нет); нет установки/запуска (у beadloom есть). **Expected:** Python 3.12/asyncio, python-telegram-bot/aiogram, Ollama+Qwen, Claude Code CLI, SQLite+FTS5; quick-start с `./bob start|stop|status`.

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

### #29 [2026-07-02] [LOW] Локальная чистка `data/*.bak-*` (~130 МБ, 14 бэкапов; НЕ в git)
**Area:** hygiene · **Issue:** мои pre-merge бэкапы БД копятся на диске (data/ gitignored). **Expected:** оставить 1–2 свежих, старые удалить локально.

### #30 [2026-07-02] [MEDIUM] Мастер-эпик реорганизации: связать #1–#18 в BOB-062
**Area:** architecture · **Notes:** доки (#1–#6) + domain-first (#7–#18) — один связанный эпик (per-module вертикали: код-переезд + `beadloom:` тэги + граф-ноды + доки за раз). Быстрые победы (#19–#24) — параллельно/вперёд.

---

## Closed Issues

> (пусто — лог заведён 2026-07-02)
