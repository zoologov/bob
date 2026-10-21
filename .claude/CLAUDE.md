<!-- beadloom:composed — this file is CORE + the architecture/stack overlays your
`.beadloom/flow.yml` selects. Put YOUR project's rules in `.beadloom/flow/claude/CLAUDE.md`:
the project layer composes AFTER the core, survives every upgrade, and does not trip
`beadloom config-check`. Editing this body directly is reported and never rewritten. -->

# CLAUDE.md — Multi-Agent Development Core

> **Version:** 3.1 (agents/ + commands/ split)
> **Integration:** steveyegge/beads CLI (1.0.4, embedded Dolt)
> **Process skills (`.claude/commands/`, slash, run in main loop):** `/task-init`, `/coordinator`, `/checkpoint`, `/templates`
> **Role subagents (`.claude/agents/`, launched via the `Agent` tool):** `explore`, `dev`, `test`, `review`, `tech-writer`
> **See §0.0 Process Architecture for how these fit together.**

---

## 0.0 Process Architecture (entry point → roles)

One entry point, two kinds of unit. This is the whole map:

```
CLAUDE.md  ← entry point: critical rules, setup, bd/beadloom essentials, this map
│
├─ .claude/commands/  — SLASH SKILLS, injected into the MAIN-LOOP session (you, now)
│    /task-init    scaffold any work item (PRD/RFC/CONTEXT/PLAN/ACTIVE or BRIEF) + create beads
│    /coordinator  orchestrate multi-agent work (waves, gates, landing lock) — MAIN-LOOP only
│    /checkpoint   bd-comment + ACTIVE.md progress saves
│    /templates    document templates used by /task-init
│
└─ .claude/agents/    — ROLE SUBAGENTS, launched via the `Agent` tool (isolated context)
     explore · dev · test · review · tech-writer   (canonical role definitions; scoped tools; model: opus)
```

**Why coordinator is a command, not an agent:** the coordinator IS the main-loop process that *spawns* subagents via the `Agent` tool. A subagent cannot spawn subagents, so orchestration must live in the main loop. `/coordinator` is a skill injected into that loop.

**Two ways a role runs:**
- **Multi-agent (default for epics/features):** `/coordinator` launches roles as subagents — `Agent(subagent_type="explore"|"dev"|"test"|"review"|"tech-writer", run_in_background=True)`. The role's full protocol lives in `.claude/agents/<role>.md` (single source of truth) and is NOT re-injected by the coordinator.
- **Single-agent (one small bead, no orchestration):** the main loop adopts the role inline by reading and following `.claude/agents/<role>.md` directly. (There are no `/explore` `/dev` `/test` `/review` `/tech-writer` slash commands — roles are subagents, not skills.)

**Flow:** `/task-init` (Explore derives the axes at step 0.5, then docs + beads) → `/coordinator` (waves: dev → test → review → tech-writer, gated by bead dependencies) → commit per wave. Durable state lives in files (`CONTEXT.md`/`ACTIVE.md`) + bead comments, never chat.

---

## 0. CRITICAL RULES

> **READ FIRST. ALWAYS FOLLOW.**

### Setup (one-time, per clone)

```bash
git config beads.role maintainer   # or "contributor" — required by bd 1.0.4 (silences GH#2950 warning)
beadloom install-hooks             # pre-commit (lint + sync-check + ACTIVE/tracker coherence) +
                                   # pre-push Beadloom Gate (`beadloom ci`; blocks on red, --no-verify to skip).
                                   # It does not run the test suite, and names that under its verdict.
```

### BEFORE any work

```bash
# 1. Get project context
beadloom prime                    # compact architecture + health overview

# 2. Check available tasks
bd ready

# 3. Claim task
bd update <bead-id> --status in_progress --claim

# 4. Read context via Beadloom (never hardcode paths)
beadloom ctx <ref-id>             # architecture context for the area you'll touch
beadloom why <ref-id>             # impact: what depends on this?

# 5. Read epic context (if applicable)
# .claude/development/docs/features/{ISSUE-KEY}/CONTEXT.md
# .claude/development/docs/features/{ISSUE-KEY}/ACTIVE.md

# 6. Confirm understanding to user
```

### DURING work

```bash
# Checkpoint every 30 min or 5 steps
bd comments add <bead-id> "CHECKPOINT: [what was done]"

# Update ACTIVE.md after each significant action
```

### WHEN COMPLETING bead

```bash
# 1. Tests pass, 2. lint + type-check clean
#    -> the concrete commands come from the STACK section below, not from here:
#       the core is stack-neutral and `uv run pytest` is not every project's suite.

# 3. Beadloom validation
beadloom reindex
beadloom sync-check
beadloom lint --strict

# 4. Final checkpoint
bd comments add <bead-id> "COMPLETED: [results]"

# 5. Close bead (shows newly unblocked work)
bd close <bead-id> --suggest-next
# (append --session "$CLAUDE_SESSION_ID" only if that env var is set)
```

---

## 0.1 Project: bob

<!-- beadloom:auto-start project-info -->
- **Stack:** Python (>=3.12) — aiogram, s
- **Tests:** pytest + pytest-cov
- **Linter/formatter:** ruff (lint + format)
- **Type checking:** mypy --strict
- **Architecture:** DDD packages -- `application/`, `capabilities/`, `coding/`, `conversation/`, `identity/`, `infrastructure/`, `interactive/`, `kernel/`, `memory/`, `personality/`, `presence/`, `proactivity/`, `runtime/`, `social/`
- **Current version:** 1.0.0
<!-- beadloom:auto-end -->

---

## 1. Skills — Dynamic Loading

**Slash skills (main loop):**

| Situation | Command | Description |
|-----------|---------|-------------|
| New work item | `/task-init` | Setup any type: epic, feature, bug, task, chore |
| Parallel work | `/coordinator` | Orchestrate multi-agent waves (spawns role subagents) |
| Need templates | `/templates` | PRD, RFC, CONTEXT, PLAN, ACTIVE, BRIEF |
| Create checkpoint | `/checkpoint` | Format, rules |

**Role subagents (via the `Agent` tool — see §0.0):** `explore` (the axes, before a work item has a type), `dev` (TDD implementation), `test` (tests, coverage), `review` (quality, read-only), `tech-writer` (doc refresh). Defined in `.claude/agents/<role>.md`. For a single small bead without orchestration, the main loop adopts a role inline by following its `.claude/agents/<role>.md`.

**Rule:** Invoke a slash skill when you need detailed instructions; launch a role subagent (or follow its agent file inline) to do role work.

---

## 2. Beads CLI — Essentials

```bash
# Available tasks (no blockers)
bd ready
bd ready --claim                  # atomically claim the next ready bead (1.0.4)

# All tasks — `--all` because bd otherwise omits every closed bead, silently,
# and caps the rest at 50 with a notice only on stderr (bd 1.0.4)
bd list --all

# Details + history
bd show <id>
bd comments <id>

# Claim task
bd update <id> --status in_progress --claim

# Add checkpoint (does NOT overwrite description)
bd comments add <id> "checkpoint text"

# Close task (--suggest-next shows newly unblocked beads; 1.0.4)
bd close <id> --suggest-next

# Dependency graph
bd graph --all

# Add dependency, then READ THE ECHO — bd names both beads' full titles, and that
# echo is the only check on an edge built from an id you wrote down yourself
bd dep add <id> <depends-on-id>
bd dep tree <id>                  # confirm the edge against the titles, not the ids
```

**Multi-agent coordination (new in 1.0.4) — used by `/coordinator`:**
- `bd swarm` — epic → DAG → waves (`create` / `validate` / `status`)
- `bd gate` — async wait conditions (review→tech-writer; CI via `gh:run` / `gh:pr`)
- the merge slot — serialize parallel LANDINGS: `bd merge-slot acquire --holder <bead-id>`,
  where exit 0 means you hold it, and `release --holder <bead-id>`, the only release form bd
  verifies. It orders the commits and nothing else; keeping two agents out of one FILE is what
  `beadloom waves` derives

**IMPORTANT:**
- `bd comments add` — for checkpoints (preserves history)
- `bd update --append-notes` — for notes
- NEVER work on a task without `--claim`
- ALWAYS close via `bd close`; `--suggest-next` lists *candidate* unblocked beads — **confirm with `bd ready --limit 0`** (it named a still-blocked bead in sixteen of twenty-three dependency shapes measured on bd 1.0.4; `--limit 0` because the default caps at 100)
- `--session "$CLAUDE_SESSION_ID"` on close is optional (audit trail; only if the env var is set)

---

## 2.1 Beadloom CLI — Essentials

```bash
# Agent context (start of session)
beadloom prime                   # compact context for AI agent injection (<2K tokens)

# Project structure (use instead of hardcoded paths)
beadloom status                  # overview: nodes, edges, docs, coverage, trends
beadloom graph                   # Mermaid architecture diagram
beadloom ctx <ref-id>            # full context: code, docs, constraints
beadloom ctx <ref-id> --json     # structured JSON for parsing
beadloom search "<query>"        # FTS5 search across nodes and docs
beadloom why <ref-id>            # impact analysis: upstream deps + downstream dependents

# Validation (run before committing)
beadloom reindex                 # rebuild index after code/graph changes
beadloom sync-check              # check doc-code freshness (exit 2 = stale)
beadloom lint --strict           # architecture boundary check (exit 1 = violation)
beadloom doctor                  # graph integrity validation

# Change tracking & visualization
beadloom diff --since <git-ref>  # graph changes vs a git ref (exit 1 = changes) — use in the review role
beadloom snapshot save           # snapshot architecture state; `snapshot compare <a> <b>` to diff
beadloom link <ref-id> <url>     # link a graph node to an external tracker issue (GitHub/Jira)

# Cross-repo federation (hub + satellites)
beadloom export [--out FILE]     # deterministic federation artifact (schema v1: graph + lifecycle + AMQP contract meta)
beadloom federate <exports...>   # hub: aggregate >=2 satellite exports -> federated graph (drift verdicts + staleness)

# Documentation
beadloom docs generate           # generate doc skeletons from graph
beadloom docs polish             # structured data for AI doc enrichment

# Setup (one-time)
beadloom init                    # initialize beadloom in a project
beadloom setup-rules             # create IDE rules files referencing AGENTS.md
beadloom setup-mcp               # configure MCP server for IDE
beadloom setup-agentic-flow      # compose+write role adapters from .beadloom/flow.yml (ddd|fsd × stack, claude/cursor)
beadloom install-hooks           # pre-commit (lint + sync-check + coherence) + pre-push Beadloom Gate (`beadloom ci`;
                                 # graph and documents, not the suite — the verdict names what it did not run)

# After changing code
# 1. beadloom reindex            — re-index changed files
# 2. beadloom sync-check         — check if docs went stale
# 3. If stale: update the doc, then beadloom reindex again
# 4. beadloom lint --strict      — verify architecture boundaries
```

**IMPORTANT:**
- NEVER hardcode file paths — use `beadloom ctx`/`graph`/`search` to discover structure
- ALWAYS start sessions with `beadloom prime` for project context
- ALWAYS run `beadloom sync-check` before committing
- If sync-check reports stale docs, update them before proceeding

---

## 3. File Memory (protection against auto-compaction)

<!-- beadloom:auto-start doc-language -->
**Document language:** ALL documents (PRD, RFC, CONTEXT, PLAN, ACTIVE, BRIEF) MUST be written in Russian — set by `language: ru` in `.beadloom/flow.yml`.
<!-- beadloom:auto-end -->

```
.claude/development/docs/features/{ISSUE-KEY}/
├── PRD.md       <- REQUIREMENTS: business goals (epic/feature only)
├── RFC.md       <- ARCHITECTURE: technical solution (epic/feature only)
├── CONTEXT.md   <- CORE: state, decisions, standards (epic/feature only)
├── PLAN.md      <- DAG: beads and dependencies (epic/feature only)
├── BRIEF.md     <- COMBINED: problem + solution + plan (bug/task/chore only)
└── ACTIVE.md    <- FOCUS: current work, progress (ALL types)
```

| Priority | File | When to read |
|----------|------|--------------|
| **P0** | CONTEXT.md | Always at the start |
| **P0** | ACTIVE.md | Always at the start |
| **P1** | beads comments | When resuming work |

**Rule:** NEVER rely on "memory" from chat. Read the files!

---

## 4. Agent Roles

| Role | How it runs | When to use |
|------|-------------|-------------|
| **Explorer** | `agents/explore.md` (`subagent_type: explore`) | Deriving how far a change ranges, before its type is chosen (`/task-init` step 0.5) |
| **Developer** | `agents/dev.md` (`subagent_type: dev`) | Implementing beads (TDD) |
| **Reviewer** | `agents/review.md` (`subagent_type: review`) | Quality verification (read-only) |
| **Tester** | `agents/test.md` (`subagent_type: test`) | Writing tests |
| **Tech Writer** | `agents/tech-writer.md` (`subagent_type: tech-writer`) | Documentation updates |
| **Coordinator** | `/coordinator` skill (main loop) | Multi-agent orchestration |

### Single agent (one small bead, no orchestration)
The main loop adopts the role inline by following `.claude/agents/<role>.md` directly; use `/checkpoint` for saving progress.

### Multi-agent mode (default for epics/features)
Coordinator MUST be activated before multi-bead work:
1. Invoke `/coordinator` skill (main-loop only — see §0.0).
2. Complete `/task-init` flow BEFORE creating any beads or writing code.
3. Coordinator gets technical context through filtered sources (strategy specs, sub-agent summaries), NEVER reads raw source code directly.
4. Coordinator launches roles as first-class subagents via the `Agent` tool (`subagent_type: explore|dev|test|review|tech-writer`), tracked through `bd swarm` / `gate` / the landing lock.

Roles are defined canonically in `.claude/agents/{explore,dev,test,review,tech-writer}.md` (single source of truth; no slash-command wrappers).

---

## 5. DAG and Priorities

| Priority | Description | Rule |
|----------|-------------|------|
| **P0** | Critical, blocks others | Execute first |
| **P1** | High, important | After P0 |
| **P2** | Medium, improvements | When there is time |
| **P3** | Low, nice-to-have | Last priority |

**Rules:**
- Only take from `bd ready`
- Do NOT take a bead with unresolved dependencies
- Do NOT take P2/P3 while P0/P1 exist

---

## 6. Git — Trunk-based development

`main` is **branch-protected** (no direct push). All work integrates via a PR.

```
Trunk-based flow:
1. Branch off main:   git switch -c features/{ISSUE-KEY}
2. Commit per wave    onto features/{ISSUE-KEY} (dev → test → review → tech-writer)
3. ONE PR to main     per epic/feature (or shippable slice) — not one PR per commit
4. The PR triggers     the AI tech-writer (commits its doc refresh INTO the PR branch)
                       + CI (`beadloom ci` is a REQUIRED status check)
5. Merge when green    human merges once CI is green + the doc refresh has landed
                       (no auto-merge; no direct push to main → main stays always-green)
```

```
Commit format:
[{ISSUE-KEY}] <type>: <description>

Types: feat, fix, refactor, docs, test, chore

Example:
[MCP-001] feat: add health endpoint
```

One-time per repo: `beadloom setup-branch-protection` configures `main` protection
(PR required, `beadloom ci` a required check, `enforce_admins: true` — strict
trunk-based, even the owner integrates via a PR — and 0 required reviews → the
owner still self-merges).

> **Idempotent is not harmless.** The command applies whatever
> `DEFAULT_STATUS_CHECK_CONTEXTS` currently says, not whatever is already live, so
> re-running it after an upgrade can require checks your workflow does not yet
> produce — and a required check that never reports makes `main` unmergeable.
> Before re-running, confirm every context it will require exists as a job and is
> green. `gh api repos/:owner/:repo/branches/main/protection` shows what is live now.

---

## 7. Anti-patterns (NEVER)

### Planning
- Starting without an agreed plan
- Taking a bead with unresolved dependencies
- Changing DAG without notifying the user
- Creating beads before PLAN is approved (beads are created in Step 3 of /task-init)
- Coordinator reading raw source code (use strategy specs + sub-agent summaries instead)

### Work
- Starting without reading CONTEXT.md
- Relying on chat memory
- Working on multiple beads simultaneously
- Ignoring checkpoints

### Completion
- Completing a bead without `bd comments add`
- Completing without `bd close`
- Committing with failing tests

### Beadloom
- Committing without `beadloom sync-check`
- Hardcoding file paths instead of using `beadloom ctx`/`graph`
- Skipping `beadloom reindex` after graph YAML changes
- Ignoring `beadloom lint` violations

> Language- and shell-specific anti-patterns live in the STACK section, composed
> from `.beadloom/flow.yml` — they are not universal and the core does not claim
> they are.

---

> **Need detailed instructions?** Slash skills: `/task-init` | `/coordinator` | `/templates` | `/checkpoint`.
> Role subagents (`Agent` tool / follow the agent file inline): `explore` | `dev` | `test` | `review` | `tech-writer` — see §0.0.

---

## STACK (Python) — composed from `.beadloom/flow.yml`

The core above is stack-neutral. These are this project's concrete commands and
the anti-patterns that only mean something in Python.

### Commands the completion checklist refers to

```bash
uv run pytest                      # 1. tests pass
uv run ruff check src/ tests/      # 2. lint (same check as CI)
uv run mypy src/                   # 2. types (strict)
beadloom ci                        # the full pre-push Gate (rc 0 required)
```

### Anti-patterns (Python)

- Using `Any` / `# type: ignore` without a stated reason
- Leaving `print()` / `breakpoint()` — use logging
- Bare `except:` without naming the exception type
- `import *`
- Mutable default arguments (`def f(x=[]):`)
- `os.path` instead of `pathlib`; f-strings in SQL instead of `?` parameters;
  `yaml.load` instead of `yaml.safe_load`

### Anti-patterns (shell)

- Using `cp`, `mv`, `rm` without `-f` (may hang on an interactive prompt)
<!-- Проектный слой Bob для CLAUDE.md. beadloom композирует этот файл ПОСЛЕ своего ядра и
     overlay'ев (`.beadloom/flow/claude/CLAUDE.md`), он переживает апгрейды и не считается
     дрейфом в config-check. Правило слоя: он ДОПОЛНЯЕТ ядро и не может удалить из него ни
     строки; там, где факт репозитория противоречит ядру, противоречие объявлено в
     `.beadloom/flow.yml` → overlays.suppress (с причиной и условием снятия) и печатается
     уведомлением в конце файла. Источник: BOB-112 срез .3 (2026-10-21). -->

---

# Проектный слой Bob — стоячие решения владельца и факты репозитория

> Ядро выше — стек-нейтральная методология beadloom. Всё ниже — то, чего в ядре нет: факты
> этого проекта, инженерные парадигмы, правила верификации, выстраданные на этом репозитории,
> и как здесь на самом деле устроен git. Нумерация «П.N» намеренно повторяет разделы ядра, к
> которым относится дополнение. Применяется ВСЕМИ ролями (`explore` / `dev` / `test` / `review`
> / `tech-writer` / координатор) — субагент получает этот файл так же, как главный цикл.

## П.0.1 Проект: авторитетные факты

Auto-блок `project-info` выше — beadloom-генерируемый и грубый (строка `Stack:` обрезается
форматтером; запись для BDL-UX подготовлена в `features/BOB-112/BDL-UX-draft.md`, в лог beadloom
переносится после BDL-083 S4). Авторитетно:

**Bob v1.0.0** (2026-08-18 — первый мажорный релиз: живой компаньон на VPS, память+EQ+самомодель,
групповое присутствие, dev-конвейер из Telegram, CD по тегу) · Python 3.12+ (asyncio) · Telegram —
`aiogram` 3.x (Bot API 10.1: rich/stream) · Tier-1 Qwen (облако), аварийный дублёр — локальный
Ollama `qwen3:8b` (2026-08-12: выбран замером через шов Боба; `qwen2.5:7b` отвергнут — выплёвывал
синтаксис вызова инструмента ТЕКСТОМ в реплику, `0.5b` галлюцинировал), эмбеддер `bge-m3` ·
SQLite + FTS5 (no RAG/embeddings in P0) · pytest · ruff · mypy --strict.
Архитектура: DDD-вертикали + shared kernel (`src/bob/kernel`), порядок вертикалей и правило
размещения контрактов — `docs/architecture.md` (BOB-113). Полный стек и продуктовое направление:
**`.claude/dev-docs/VISION.md`** + `ROADMAP.md`.

**Инструменты как в CI.** `ci.yml` и `deploy-bob.yml` пинят **`beadloom==9.0.0`**; все артефакты
beadloom в репозитории (роли, манифест, auto-блоки, сайт) пишутся **той же сборкой**:
`uvx --from beadloom==9.0.0 beadloom …`. Editable-установка из `~/beadloom` — для разработки
beadloom, не для артефактов Боба; «у меня зелено» локальной сборкой про CI ничего не доказывает.
Бамп версии — осознанный коммит с замером на чистом индексе (BOB-112 BRIEF). Кросс-репо
федерация (`beadloom export/federate` в списке команд ядра) здесь намеренно не используется —
Bob один монолит, не федерация микросервисов.
🔴 **Хуки (`pre-commit`, `pre-push`, PreToolUse-guard) вызывают `beadloom` с PATH** — у 9.0.0 нет
пина сборки в хуке. На машине владельца PATH-сборка с 2026-10-21 — релиз (`uv tool install
beadloom==9.0.0`); разработка beadloom — `uv run` внутри `~/beadloom`, не editable на PATH.
Ловушка: `beadloom --version` у editable-сборки печатает версию релиза — версия не отличает
сборку, смотри `uv tool list`. Пока на PATH стоит не релиз, вердикт хука — не про CI, и тогда
пуш идёт `--no-verify` только после ручного `uvx --from beadloom==9.0.0 beadloom ci` exit 0
с записанной причиной.

## П.0.2 Инженерные парадигмы (стоячая методология)

> **Применяется ко ВСЕЙ работе, не к одному эпику.** Ценности владельца: максимальное качество,
> честность, контроль, стиль, сопровождаемость, расширяемость, стабильность. Парадигмы —
> равноправные, ни одна не опциональна.

**Пирамида качества (приёмка снаружи-внутрь важнее юнитов изнутри-наружу):**

```
BDD acceptance (pytest-bdd + Gherkin .feature) — наблюдаемое поведение как исполняемый,
                                                 человекочитаемый контракт (живая документация)
Mutation gate  (mutmut, прицельно)             — измеряет СИЛУ ТЕСТОВ на чистых доменных ядрах
TDD unit                                       — чистые ядра, детерминизм (test-first)
DDD boundaries + Cohesion                      — структура: bounded contexts, одна именуемая ответственность
```

**Кто что держит** (роли `.claude/agents/`):
- **dev** — TDD (test-first) · DDD-размещение · Cohesion (назови одну ответственность) · пишет
  код, который переживает mutation и выражается как `.feature`.
- **test** — TDD unit · **BDD** `.feature` для работы с поведением · **mutation**-гейт на
  тронутом доменном ядре.
- **review** — границы DDD · Cohesion (в обе стороны) · BDD-покрытие нового поведения ·
  mutation-score.
- **tech-writer** — сценарии `.feature` как живая документация поведения (ссылки из доменных доков).

**🔴 Честный scoping (устойчивый — не правило, которое молча нарушают):**
- **BDD `.feature`** — для работы с наблюдаемым поведением (фичи/эпики/багфиксы); чисто
  механические chores могут пропустить. Сценарии выводятся из каталога сценариев PRD +
  инвариантов; ассертят наблюдаемое поведение через границу (фейковый gateway/CLI), никогда —
  приватное состояние. Живут в `tests/acceptance/{features,steps}/`.
- **Mutation** — ТОЛЬКО чистые **доменные ядра** (детерминированные вердикты/политики/пороги);
  НЕ адаптеры/LLM/async/gateway (медленно, недетерминированно, неинформативно). Прогон
  **по срезу**, осознанно, **НЕ** в pre-commit (цена). Score **≥85 %** + явный триаж
  эквивалентных мутантов (никогда не «паддить»). Слепые зоны mutmut (в т.ч. методы классов
  с декоратором `@dataclass` — не мутируются вовсе) — `.claude/dev-docs/MUTATION.md`.
- Харнесс репо-wide с BOB-066 Срез 0 (`pytest-bdd` + `mutmut`, `scripts/mutation.sh`).

**🔴 Без полумер (решение владельца, 2026-10-21, BOB-112 → BOB-113):**
- Красное от гейта чинится **структурно**, а не ярлыком: `exempt`, `severity: warn`, `skip`,
  «временно, until…» — это не фикс, а отложенный долг, и по умолчанию он **не выбирается**,
  даже если структурный фикс кратно дороже (50 импорт-сайтов — исходник для плана, а не
  аргумент против). Прецедент: 15 «циклов» 9.0.0 из type-only импортов под `TYPE_CHECKING` —
  связь по контракту есть связь; контракты переехали в `kernel`/`ports.py` (BOB-113), а не
  помечены.
- Временная мера допустима только при **всех четырёх**: явное решение владельца · `until`
  с названным событием · беада на снятие · видимость (аннотация/warn, не тишина). Без любого
  из них — не делать. Объявленные `overlays.suppress` в `.beadloom/flow.yml` — ровно эта форма:
  решение владельца (2026-10-21), `reason`, `until`, печать в каждом композированном файле и
  беада на снятие у каждого (`bob-933` — защита `main`, `bob-yjv` — язык в ядре `/task-init`).
- Сначала ЗАМЕР: разделить «сдвиг вердикта инструмента» и «настоящий дефект» (чистый индекс,
  две версии инструмента на одном дереве, точные числа), потом чинить дефект — не вердикт.
- Скрупулёзность — норма для всех ролей: кусачесть каждого нового теста доказана саботажем
  с именами покрасневших; у mutation — число мутантов и поимённый триаж выживших; гейты
  перепроверяются на финальном дереве **релизной** сборкой инструмента (той же, что в CI);
  отчёт субагента — не доказательство, координатор перепроверяет сам.

## П.0.3 Правила верификации — 🔴 гейт умеет показывать зелёное, ничего не проверив

> **Стоячее правило, не одного эпика.** За два дня работы гейты трижды отрапортовали
> «чисто» о проверке, которой не было. Каждый пункт ниже — не теория, а случай из этого
> репозитория. Применяется ВСЕМИ ролями (`dev` / `test` / `review` / координатор).

**1. `beadloom lint` — только на ЧИСТОЙ БД.**
Инкрементальный `reindex` НЕ обновляет рёбра импортов, поэтому `lint --strict` на несвежем
индексе врёт. Так цикл `memory ↔ conversation` прошёл сквозь всю верификацию, включая
независимую перепроверку координатора, и был найден случайно через сутки. Гоняй так:
```bash
rm -f .beadloom/beadloom.db && uvx --from beadloom==9.0.0 beadloom reindex && uvx --from beadloom==9.0.0 beadloom lint --strict
```
(апстрим-баг beadloom, BDL-UX #142 — третье подтверждение в дикой природе)

**2. `sync-check` не видит `component`-узлы.**
Пары строятся только для `kind: feature` и сервиса. Для `llm` / `telegram` / `persistence`
/ `config` отчёт «чисто» означает **«пар не существует»**, а не «доки свежие». Свежесть их
доков проверяй чтением кода. (BDL-UX #146)

**3. После `mutmut` чисти байткод.**
mutmut оставляет в `src/**/__pycache__` `.pyc` из своей песочницы, и следующий прогон
тестов может молча исполнить СТАРЫЙ код — то есть верификация после мутации покажет
зелёное, ничего не проверив. `scripts/mutation.sh` теперь чистит сам; если гонял mutmut
иначе — почисти руками:
```bash
find src tests -name __pycache__ -prune -exec rm -rf {} +
```

**4. Тест на фейке доказывает контракт ФЕЙКА.**
Для транспорта, git и subprocess нужен тест на НАСТОЯЩЕМ инструменте. Прецеденты: краш
интерактива при 4675 зелёных тестах (BOB-084, лимит буфера реального `StreamReader`);
мёртвый реюз worktree при зелёном unit и зелёном BDD (BOB-087.D5b — unit гонял абсолютный
`tmp_path`, BDD подсовывал фейк, а прод падал на относительном пути).

**5. Проверяй тесты на кусачесть.**
Написал фикс — саботируй его и убедись, что тест краснеет. Зелёный тест, который не падает
на сломанном коде, не тест. Это дёшево (`git stash` / точечная правка / восстановление) и
ловит вакуумные ассерты.
🔴 **И проверь сам харнесс кусачести.** «Не зелёное» ≠ «покраснело»: кривой вызов pytest даёт
`ERROR`/`no tests ran`, и это неотличимо от саботажа, если смотреть только на цвет. В BOB-089
ревьюер так выдал три прохода вакуумных «10/10» — путь-параметр не расщепился в zsh, pytest не
нашёл файлы (Issues #52). Поэтому: до саботажа убедись, что тесты **собраны и зелёные**
(сравнивай ЧИСЛА собранных/пройденных, а не цвет), отличай `ERROR` от `FAILED`, и в отчёте
называй **имена** покрасневших тестов — их из сломанного вызова не получить.

**6. Смотри на ЧИСЛО мутантов, а не только на score.**
100 % на четырёх мутантах — фикция. Слепые зоны mutmut и как писать ядро, чтобы гейт был
настоящим, — в `.claude/dev-docs/MUTATION.md` §«Порог и честность».

**7. Заявленная mutation-цель вне scope = гейта нет.**
`*/adapters/*`, `*/ports.py`, `*/__init__.py` исключены конвенцией. Объявить функцию
mutation-целью и оставить её в адаптере — значит прогонять 0 мутантов и рапортовать
«покрыто» (BOB-087.D4). Чистое ядро живёт в домене, а модуль — в `[tool.mutmut].source_paths`.

**8. Отчёт агента — не доказательство.**
Координатор перепроверяет гейты САМ, на финальном состоянии дерева. Резюме субагента может
быть добросовестным и при этом описывать прогон, сделанный до последних правок.

**9. Саботаж снимай обратной правкой, а НЕ `git checkout` по файлу.**
Волна субагента ещё не закоммичена, поэтому `git checkout -- <файл>` откатывает файл к HEAD
и стирает РАБОТУ, а не саботаж. Поймано на BOB-091.1: восстановление саботажа снесло
регистрацию инструментов, дефект вскрылся только следующим прогоном (Issues #47). Снимай
точечной обратной правкой; `checkout` допустим лишь когда волна закоммичена.
🔴 **В параллельной волне — ТОЛЬКО точечной правкой.** Восстановление файла целиком (из копии,
из бэкапа, перезаписью) для соседнего агента равно стиранию: в BOB-089 два агента делили
`spawn_isolation.py`, и восстановление целым файлом дало окно 21 с рядом с активной работой
соседа (Issues #51). Лучше вообще не делить файл между параллельными агентами.

**10. Разрешение без вызывающего — не возможность.**
Запись в allowlist читается как «фича есть», хотя означает лишь «разрешено». В BOB-091
выяснилось, что `beadloom graph` и `why` лежали в allowlist интроспекции несколько эпиков,
но ни один путь до них не доходил: Боб «умел» рисовать схему только на бумаге. Проверяя
доступность, ищи ВЫЗОВ, а не запись (Issues #45).

**11. Не ставь обратные кавычки в текст, который уходит через shell.**
Внутри двойных кавычек `` `…` `` — это подстановка команды: shell ИСПОЛНИТ содержимое.
Так трижды за одну сессию: в комментарии беады выполнились `git update-ref` и `git branch -f`
(main выжил случайно), в сообщении коммита — `add -A` и `git config --list`. Длинный текст
всегда через файл: `bd comments add <id> "$(cat file)"`, `git commit -F file`. В самом файле
обратные кавычки безопасны.

**12. 🔴 Гейт, читающий ИСХОДНИК, наследует его иллюзии.**
Пять раз за два эпика проверка проверяла не то, что утверждала: гейт на несвежем индексе (#37),
запись в allowlist без вызывающего (#45), харнесс кусачести на кривом вызове (#52), гард по
ИМЕНИ модуля (#53) и — уже после его починки — гард по ПОДСТРОКЕ `voice_canon=` в исходнике,
при том что `None` легальное значение: шов выключался одним словом при 7586 зелёных. Мы дважды
починили сломанное тем же способом, каким оно было сломано.
Правило: гард формулируется как **поведение собранной системы**, а не как форма кода. И
доказывается **двойным прогоном** — саботаж, на котором НОВЫЙ гард краснеет, а старый остаётся
зелёным. «Новый тоже зелёный» доказательством не является.

🔴 **Дополнено 2026-08-15 — правило было и не помогло.** Процессный гейт BOB-098 писался прямо
по этому пункту и всё равно вышел по подстроке: дату сверки карты он искал корнем «свер», так
что фразу гасило слово «сверх» — а на живой карте гейт **вообще не мог покраснеть**, потому что
свежую дату ему подсовывали три ЧЕСТНЫЕ строки («Отгружено после прежней сверки (… 2026-08-15)»).
Карта гасила собственный гейт своей же практикой видимых правок. Два вывода:
- **У гейта бывает второй, текстовый вход.** «Не суди форму кода» прочиталось узко — про
  исходник; документ, который гейт читает, тоже текст, и там та же ловушка. Ищи ВСЕ входы.
- **Саботаж должен пытаться ОБМАНУТЬ гард, а не только сломать проверяемое.** Прогон «сломал
  предмет → покраснело» доказывает лишь кусачесть. Отдельно нужен прогон «предмет сломан, а
  гарду подсунута правдоподобная фраза» — на нём гард обязан остаться красным.

🔴 **Дополнено 2026-10-21 (BOB-113, BOB-112 .5).** Ast-гард на циклы импортов был слеп к формам
`from bob import social` и к относительным импортам — проверял форму кода (п.12), ревью поймало;
второе ревью нашло третью форму — `import bob.x.y as z` (латентно: в src таких 0). Гард читает
**все** формы импорта, включая алиас; у `beadloom lint` 9.0.0 слепы все три (`from bob import x`,
относительные, алиас — последним обходится любое `forbid_import`-правило); записи для BDL-UX —
в `features/BOB-112/BDL-UX-draft.md`. И: mutation-цель, попавшая в scope, но лежащая в классе
с декоратором, прогоняет 0 мутантов — «28/28» надо перемерять по модулю, а не читать из `.meta`.
И ещё: **предупреждение инструмента — тоже отчёт, не доказательство.** `rule_liveness` 9.0.0
назвал 36 правил «неспособными сработать» — координатор пересказал это как мёртвые правила и
предложил их снять; ревью саботажем показало, что правила живые (BDL-UX #328). Перемеряй.

## П.3 Документы: язык, шаблоны, спека и беада

**Язык документов — русский.** Задан как `language: ru` в `.beadloom/flow.yml` (решение проекта
2026-06-18): auto-блок `doc-language` выше печатает Russian, общие фрагменты ролей (`_writing`,
`_rooms`, `_landing`, `_tracker`) приходят локализованными. Ядро `/task-init` в beadloom 9.0.0 тег
языка не читает и по-прежнему говорит «English» — это расхождение объявлено в
`overlays.suppress` (см. уведомление в конце файла; беада на снятие `bob-yjv`), запись для
апстрима — в `features/BOB-112/BDL-UX-draft.md`; правило проекта — русский, без исключений. Комментарии к беадам, чекпоинты, отчёты ревью — тоже по-русски.

**Адаптация шаблонов `/templates` к Bob** (скелеты — generic апстрим, их плейсхолдеры **не
копировать дословно**): контент по-русски; **Python 3.12+**; слоение Bob — **DDD-вертикали +
shared kernel** (а не пример «CLI → Core → Storage» из шаблона, это артефакт beadloom-CLI); стек
по П.0.1 (Telegram/aiogram · Qwen/Ollama · SQLite+FTS5).

### 🔴 Спека — источник, беада — состояние (правило добавлено 2026-08-13 по факту дрейфа)

**Волна не запускается, пока у работы нет её документов.** Правило «беады создаются после
утверждения PLAN» есть, а обратного — «не работать без спеки» — не было, и конвейер уехал:
в августе пять работ подряд завелись беадами с развёрнутыми описаниями и **без единого
документа**, а `ROADMAP.md` отстал на семь недель («сверено с main 2026-06-25», при том что
T3.C давно отгружен). Описание беады подменило спеку — удобно агенту, но даёт **два источника
правды**, и авторитетный отстаёт от фактического.

- **Спека (`PRD`/`RFC`/`CONTEXT`/`PLAN` или `BRIEF`) — источник намерения.** Беада — **состояние**
  и хронология: чекпоинты, находки, решения по ходу. Развёрнутое описание в беаде спеку **не
  заменяет**.
- Перед первой волной по работе: папка `features/{ISSUE-KEY}/` существует и комплект по типу
  заполнен (epic/feature — полный; bug/task/chore — `BRIEF` + `ACTIVE`).
- Спека пишется **при взятии в работу**, а не заранее на весь бэклог (иначе устареет раньше,
  чем пригодится) и не задним числом после (иначе описывает не замысел, а результат).
- 🔴 **Реконструкция отгруженного помечается как реконструкция** — `Status: Reconstructed`,
  дата, перечень источников (коммиты, PR, беады), и честное «не зафиксировано» там, где
  причины решения в источниках нет. Реконструкция, выдающая себя за исходный замысел, — это
  тот же класс, что «документ обещает больше, чем схема держит», только применительно к
  истории.

**Гейт против дрейфа (BOB-098):** `tests/test_process_drift_gate.py` + `tests/support/process_coherence.py`.
Держит три вещи: у беады **в работе** есть папка `features/{ISSUE-KEY}/` с комплектом по типу;
`ROADMAP.md` несёт якорь «сверено с main YYYY-MM-DD» и не отстаёт от `main` больше порога;
у открытой P0/P1-работы есть место в карте. 🔴 Что он **НЕ** держит: закрытую беаду, работа
которой не доехала до `main` (обе узкие проверки замерены и отвергнуты как шумные — разбор в
Issues #56). Этот класс ловится глазами при закрытии dev-беады и на ревью.
🔴 Без трекера (клон Боба-кодера, раннер CI) три из четырёх проверок дают **SKIP с причиной**
«согласованность НЕ ПРОВЕРЯЛАСЬ» — не `ERROR` и, что важнее, не молчаливое зелёное.

## П.6 Git — как оно есть в этом репозитории

`main` интегрируется через PR — **по дисциплине, а не по правам.**

🔴 **Branch protection на этом плане недоступна**: API отвечает `403 Upgrade to GitHub Pro or make
this repository public`. Прямой push в `main` технически проходит. Фразы ядра про «branch-protected»
и «REQUIRED status check» здесь не действуют — это объявлено в `overlays.suppress`, а
`beadloom setup-branch-protection` на этом плане молча ничего не настраивает.

🔴 **CI по PR ЕСТЬ (BOB-095, отгружено 2026-08-18) — но ИНФОРМАТИВНЫЙ, не required.**
На `pull_request → main` работает `ci.yml` (порядок с BOB-112 .6): `uv sync --extra dev` →
установка `beadloom==${BEADLOOM_VERSION}` (единственный пин в workflow, `env` job'а) → `reindex`
на чистом индексе → `ruff` + `mypy(src,tests)` → `pytest -rs` → гейт **одной** командой
`beadloom ci --format github` на чистом индексе (та же, что pre-push хук и ручная перепроверка
координатора; каждая подпроверка печатает свой `::notice`, находки — аннотации). Установка и
индекс стоят **до** pytest намеренно: ~30 тестов интроспекции/диаграмм/здоровья инструментов
гоняют настоящий бинарь и без него на раннере молча давали SKIP (замер ревью .5: 331/37 против
368/368) — формат `why`/`diff` закреплённой сборки CI не проверял. Гард
`tests/test_ci_runs_real_tool_tests.py` на раннере краснеет, если во время pytest нет бинаря,
индекса или версия ≠ пину; вне Actions — SKIP с причиной «НЕ проверялось». Красный виден в
PR, но не может **БЛОКИРОВАТЬ** мёрж. Называть его «required»/«blocking» — то же желаемое-за-действующее, что
мы правили в BOB-089. 🔴 На раннере нет `bd`/базы трекера → процессный гейт
`test_process_drift_gate` даёт **SKIP с причиной** (флаг `-rs` её печатает), не ERROR и не
молчаливое зелёное — CI не читается как «согласованность проверена».

🔴 **BOB-108 (2026-08-18): beadloom-гейт в CI полтора дня не проверял НИЧЕГО.** Шаг стоял под
`continue-on-error`, потому что `beadloom reindex` падал нативно (exit 139, ноль вывода), — и
прогон читался зелёным при аннотации о сегфолте внутри себя. Корень: beadloom требовал
`tree-sitter>=0.23` **без верхней границы**, грамматики собраны под ABI 0.25, свежая установка
тянула ядро 0.26.0 → крах на загрузке грамматики. «Локально работает, на раннере падает» — дело
было не в раннере, а в **дате установки**. Три урока, которые остались правилами:
- дыра в гейте была **задокументирована** — и потому выглядела решением, а не долгом. Честная
  запись про отключённую проверку не перестаёт быть отключённой проверкой; у неё должен быть
  срок и беада, иначе она застывает (см. «Без полумер», П.0.2);
- у исключения условие окончания **самообъявляется** (шаг сам печатает «условие наступило,
  верни меня в гейт»), иначе его надо помнить — а это тот же долг, только отложенный;
- `continue-on-error` даёт шагу conclusion **`success`**, и его ошибка **не попадает в
  ANNOTATIONS** — «информативный красный» не виден никому, кто не открыл лог шага (замерено на
  PR #138). Если где-то ставишь `continue-on-error` ради «видимого красного» — проверь
  ANNOTATIONS, а не намерение.
Хроника, чтобы не переоткрывать: до BOB-095 в `.github/workflows` лежал только `deploy-site.yml`
(+ с BOB-094 `deploy-bob.yml`) и `beadloom ci` по PR не запускался вовсе. BOB-108 устранён пином
`uv tool install beadloom --with "tree-sitter<0.26"`; пять проверок (`reindex`/`lint --strict`/
`sync-check`/`docs audit`/`doctor`) снова валят прогон, кусачесть доказана саботажем границы
(правило назвалось, файл и строка, exit 1). Из гейта тогда остался исключён `config-check` — и
не из-за дрейфа наших файлов, а из-за **рассинхрона релиза beadloom**: Cohesion-параграф ролей и
раздел автономии координатора были вкодифицированы в сами шаблоны beadloom (BDL-059), лежали в
`main` beadloom, но PyPI 2.1.0 их не содержал → локально (сборка из исходника) exit 0, в CI —
3 drifted; `--fix` был бы разрушителен (42 удаления, 0 добавлений, включая методологию §0.2).
Апстриму заведены BDL-UX #151 (релиз) и #152 (проектного оверлея нет — методологию пришлось
нести в сам beadloom).
✅ Закрыто в BOB-112 (2026-10-21): релиз **9.0.0** несёт шаблоны BDL-059 (#151) и проектный слой
(#152, появился в 3.0.0 — этот самый файл), `config-check` вернулся в блокирующий гейт,
обходной шаг удалён, версии пинятся (П.0.1), рукописная методология живёт здесь, а не в
`.claude/agents/*.md` — иначе `config-check` снова читает нас как дрейф. Замер перехода
2.1.0 → 9.0.0 на нетронутом графе (lint 0 → 36 находок, sync 0 → 2; после семантики 6.0 —
925 строк, из них 904 — 15 пар type-only циклов → BOB-113) и разбор —
`.claude/development/docs/features/BOB-112/BRIEF.md`.

Что реально держит `main`: дисциплина ветки на эпик, перепроверка гейтов координатором на
финальном состоянии дерева (каждую волну), **видимый CI по PR** (BOB-095, с работающим
арх-гейтом — BOB-108) и pre-push хук **в основном репозитории** — он работает, когда пушит
человек или координатор, но 🔴 НЕ работает на ветке Боба: её пушит процесс Боба, а он с BOB-089
хуков не исполняет (иначе хук модели был бы неотличим от хука владельца).

Мёржит человек/координатор — после того, как гейты перепроверены **на финальном дереве**
релизной сборкой и доки обновлены. «Зелёный CI» здесь не гарантия, а описание того, чего пока
нет. Коммиты и PR — с префиксом `[{ISSUE-KEY}]` по формату ядра; длинное сообщение — через
файл (`git commit -F`), см. П.0.3 п.11.

## П.7 Анти-паттерны Bob (сверх ядра)

### Shell
- 🔴 **`uv run ruff format` на этом дереве** — репозиторий НЕ format-clean, и команда
  переписывает посторонние файлы (замечено в BOB-096: 12 файлов вне зоны работы). Форматирование
  проверяет и требует только `ruff check`; массовый `format` — отдельное решение отдельной
  работой, а не побочный эффект чужой волны.
- Обратные кавычки в тексте, уходящем через shell (комментарий беады, сообщение коммита) —
  П.0.3 п.11: только через файл.
- `git checkout -- <файл>` как способ снять саботаж в незакоммиченной волне — П.0.3 п.9.

### Процесс
- Волна без спеки (папка `features/{ISSUE-KEY}/` с комплектом по типу) — П.3.
- `exempt` / `severity: warn` / `until` как способ погасить красный гейт без решения владельца
  и без всех четырёх условий — П.0.2 «Без полумер».
- Гейт на несвежем индексе, mutation-цель вне scope, гард по форме кода, отчёт субагента как
  доказательство — П.0.3 пп.1, 7, 12, 8.

---

## Project rule suppressions (declared in `.beadloom/flow.yml`)

The core rules below are stood down **in this project only**. The core text above is unchanged — a suppression is a declaration, never a deletion — and each one names its reason and its exit condition.

- Git — Trunk-based development: в CLAUDE.md §6 ядро утверждает «main is branch-protected», «beadloom ci is a REQUIRED status check» и что setup-branch-protection настраивает защиту — в этом репозитории всё три не действуют: репозиторий приватный на плане GitHub Free, API защиты ветки и rulesets отвечают «403 Upgrade to GitHub Pro or make this repository public»; main держится дисциплиной PR, перепроверкой гейтов координатором на финальном дереве и видимым (не required) CI по PR — раздел П.6 проектного слоя (until репозиторий станет публичным или план — GitHub Pro: тогда выполняется beadloom setup-branch-protection и эта запись снимается)
- Template rules: в /task-init ядро 9.0.0 пишет «ALL documents MUST be in English» и «(in English)» в чеклисте, хотя язык документов задан здесь как language: ru и auto-блок doc-language в CLAUDE.md уже печатает Russian — ядро task-init тег языка не читает, расхождение внутри самого beadloom (BDL-UX); в этом проекте все документы по-русски, остальные пункты раздела (статусы, формат метаданных) действуют (until ядро /task-init в beadloom читает language из flow.yml и печатает тот же язык, что auto-блок doc-language)
