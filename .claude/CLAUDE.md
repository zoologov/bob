# CLAUDE.md — Multi-Agent Development Core

> **Version:** 3.1 (agents/ + commands/ split)
> **Integration:** steveyegge/beads CLI (1.0.4, embedded Dolt)
> **Process skills (`.claude/commands/`, slash, run in main loop):** `/task-init`, `/coordinator`, `/checkpoint`, `/templates`
> **Role subagents (`.claude/agents/`, launched via the `Agent` tool):** `dev`, `test`, `review`, `tech-writer`
> **See §0.0 Process Architecture for how these fit together.**

---

## 0.0 Process Architecture (entry point → roles)

One entry point, two kinds of unit. This is the whole map:

```
CLAUDE.md  ← entry point: critical rules, setup, bd/beadloom essentials, this map
│
├─ .claude/commands/  — SLASH SKILLS, injected into the MAIN-LOOP session (you, now)
│    /task-init    scaffold any work item (PRD/RFC/CONTEXT/PLAN/ACTIVE or BRIEF) + create beads
│    /coordinator  orchestrate multi-agent work (waves, gates, merge-slot) — MAIN-LOOP only
│    /checkpoint   bd-comment + ACTIVE.md progress saves
│    /templates    document templates used by /task-init
│
└─ .claude/agents/    — ROLE SUBAGENTS, launched via the `Agent` tool (isolated context)
     dev · test · review · tech-writer   (canonical role definitions; scoped tools; model: opus)
```

**Why coordinator is a command, not an agent:** the coordinator IS the main-loop process that *spawns* subagents via the `Agent` tool. A subagent cannot spawn subagents, so orchestration must live in the main loop. `/coordinator` is a skill injected into that loop.

**Two ways a role runs:**
- **Multi-agent (default for epics/features):** `/coordinator` launches roles as subagents — `Agent(subagent_type="dev"|"test"|"review"|"tech-writer", run_in_background=True)`. The role's full protocol lives in `.claude/agents/<role>.md` (single source of truth) and is NOT re-injected by the coordinator.
- **Single-agent (one small bead, no orchestration):** the main loop adopts the role inline by reading and following `.claude/agents/<role>.md` directly. (There are no `/dev` `/test` `/review` `/tech-writer` slash commands — roles are subagents, not skills.)

**Flow:** `/task-init` (docs + beads) → `/coordinator` (waves: dev → test → review → tech-writer, gated by bead dependencies) → commit per wave. Durable state lives in files (`CONTEXT.md`/`ACTIVE.md`) + bead comments, never chat.

---

## 0. CRITICAL RULES

> **READ FIRST. ALWAYS FOLLOW.**

### Setup (one-time, per clone)

```bash
git config beads.role maintainer   # or "contributor" — required by bd 1.0.4 (silences GH#2950 warning)
beadloom install-hooks             # pre-commit (lint + sync-check + ACTIVE/tracker coherence) +
                                   # pre-push Beadloom Gate (full `beadloom ci`; blocks on red, --no-verify to skip)
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
# 1. Tests pass
uv run pytest

# 2. Code quality (same checks as CI)
uv run ruff check src/ tests/
uv run mypy src/

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
- **Stack:** Python 3.10+, SQLite, Rich
- **Tests:** pytest + pytest-cov
- **Linter/formatter:** ruff (lint + format)
- **Type checking:** mypy --strict
- **Architecture:** DDD packages -- `application/`, `capabilities/`, `coding/`, `conversation/`, `infrastructure/`, `interactive/`, `kernel/`, `memory/`, `personality/`, `presence/`, `proactivity/`, `runtime/`, `social/`
- **Current version:** 2.1.0
<!-- beadloom:auto-end -->

> **Authoritative project facts** (the auto-region above is beadloom-generated and coarse — it does
> not reflect the real stack, and "Current version: 2.1.0" is *beadloom's* version, not Bob's; a known
> beadloom quirk):
> **Bob v0.1.0** · Python 3.12+ (asyncio) · Telegram — `python-telegram-bot` · Ollama (Qwen 2.5 7B/0.5B)
> · SQLite + FTS5 (no RAG/embeddings in P0) · pytest · ruff · mypy --strict.
> Full stack & product direction: **`.claude/dev-docs/VISION.md`** + `ROADMAP.md`.

---

## 0.2 Engineering Paradigms (standing methodology)

> **Applies to ALL work, not one epic.** Path values (owner): maximum quality, honesty, control,
> style, maintainability, extensibility, stability. These paradigms are peers — none optional.

**Quality pyramid (outside-in acceptance over inside-out units):**

```
BDD acceptance (pytest-bdd + Gherkin .feature) — observable behavior as executable,
                                                 human-readable contracts (living documentation)
Mutation gate  (mutmut, targeted)             — measures TEST STRENGTH on pure domain cores
TDD unit                                      — pure cores, deterministic (test-first)
DDD boundaries + Cohesion                     — structure: bounded contexts, one nameable responsibility
```

**Enforced by the role subagents** (`.claude/agents/`):
- **dev** — TDD (test-first) · DDD placement · Cohesion (name the one responsibility) · writes code that survives mutation + makes behavior expressible as `.feature`.
- **test** — TDD unit · **BDD** `.feature` for behavior-bearing work · **mutation** gate on the touched domain core.
- **review** — DDD boundaries · Cohesion (both directions) · BDD-coverage of new behavior · mutation-score.
- **tech-writer** — `.feature` scenarios are living behavior docs (referenced from domain docs).

**🔴 Honest scoping (sustainable — not a rule we silently break):**
- **BDD `.feature`** — for behavior-bearing work (features/epics/bugfixes with observable behavior);
  pure mechanical chores may skip. Scenarios derive from the PRD scenario catalog + invariants;
  assert observable behavior through the boundary (fake gateway/CLI), never private state.
  Live in `tests/acceptance/{features,steps}/`.
- **Mutation** — ONLY pure **domain cores** (deterministic verdicts/policies/thresholds); NOT
  adapters/LLM/async/gateway (slow, non-deterministic, uninformative). Deliberate **per-slice** run,
  **NOT** in pre-commit (cost). Score **≥85%** + explicit equivalent-mutant triage (never pad).
- Harness is repo-wide once bootstrapped (established in BOB-066 Срез 0: `pytest-bdd` + `mutmut`).

---

## 0.3 Правила верификации — 🔴 гейт умеет показывать зелёное, ничего не проверив

> **Стоячее правило, не одного эпика.** За два дня работы гейты трижды отрапортовали
> «чисто» о проверке, которой не было. Каждый пункт ниже — не теория, а случай из этого
> репозитория. Применяется ВСЕМИ ролями (`dev` / `test` / `review` / координатор).

**1. `beadloom lint` — только на ЧИСТОЙ БД.**
Инкрементальный `reindex` НЕ обновляет рёбра импортов, поэтому `lint --strict` на несвежем
индексе врёт. Так цикл `memory ↔ conversation` прошёл сквозь всю верификацию, включая
независимую перепроверку координатора, и был найден случайно через сутки. Гоняй так:
```bash
rm -f .beadloom/beadloom.db && beadloom reindex && beadloom lint --strict
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
100% на четырёх мутантах — фикция. Слепые зоны mutmut и как писать ядро, чтобы гейт был
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
В этой сессии так трижды: в комментарии беады выполнились `git update-ref` и `git branch -f`
(main выжил случайно), в сообщении коммита — `add -A` и `git config --list`. Длинный текст
всегда через файл: `bd comments add <id> "$(cat file)"`, `git commit -F file`. В самом файле
обратные кавычки безопасны.

## 1. Skills — Dynamic Loading

**Slash skills (main loop):**

| Situation | Command | Description |
|-----------|---------|-------------|
| New work item | `/task-init` | Setup any type: epic, feature, bug, task, chore |
| Parallel work | `/coordinator` | Orchestrate multi-agent waves (spawns role subagents) |
| Need templates | `/templates` | PRD, RFC, CONTEXT, PLAN, ACTIVE, BRIEF |
| Create checkpoint | `/checkpoint` | Format, rules |

**Role subagents (via the `Agent` tool — see §0.0):** `dev` (TDD implementation), `test` (pytest, coverage), `review` (quality, read-only), `tech-writer` (doc refresh). Defined in `.claude/agents/<role>.md`. For a single small bead without orchestration, the main loop adopts a role inline by following its `.claude/agents/<role>.md`.

**Rule:** Invoke a slash skill when you need detailed instructions; launch a role subagent (or follow its agent file inline) to do role work.

---

## 2. Beads CLI — Essentials

```bash
# Available tasks (no blockers)
bd ready
bd ready --claim                  # atomically claim the next ready bead (1.0.4)

# All tasks
bd list

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

# Add dependency
bd dep add <id> <depends-on-id>
```

**Multi-agent coordination (new in 1.0.4) — used by `/coordinator`:**
- `bd swarm` — epic → DAG → waves (`create` / `validate` / `status`)
- `bd gate` — async wait conditions (review→tech-writer; CI via `gh:run` / `gh:pr`)
- `bd merge-slot` — serialize parallel merges (one agent merges at a time)

**IMPORTANT:**
- `bd comments add` — for checkpoints (preserves history)
- `bd update --append-notes` — for notes
- NEVER work on a task without `--claim`
- ALWAYS close via `bd close`; `--suggest-next` lists *candidate* unblocked beads — **confirm with `bd ready`** (it may list still-blocked beads; verified bd 1.0.4 quirk, see BDL-UX-Issues #97)
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

# (Cross-repo federation `beadloom export/federate` intentionally omitted — Bob is a single
#  monolith, not a federated microservices product.)

# Documentation
beadloom docs generate           # generate doc skeletons from graph
beadloom docs polish             # structured data for AI doc enrichment

# Setup (one-time)
beadloom init                    # initialize beadloom in a project
beadloom setup-rules             # create IDE rules files referencing AGENTS.md
beadloom setup-mcp               # configure MCP server for IDE
beadloom setup-agentic-flow      # compose+write role adapters from .beadloom/flow.yml (ddd|fsd × stack, claude/cursor)
beadloom install-hooks           # pre-commit (lint + sync-check + coherence) + pre-push Beadloom Gate (full `beadloom ci`)

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

**Document language:** ALL project documents (PRD, RFC, CONTEXT, PLAN, ACTIVE, BRIEF) MUST be written in **Russian** (project decision, 2026-06-18). This project-level rule **overrides** the vendored `/task-init` + `/templates` skill files, which still say "English" (they are drift-guarded byte-identical copies of the upstream beadloom flow and cannot be edited without breaking `config-check`).

**Adapting templates to Bob (the `/templates` skeletons are generic upstream — DO NOT copy their placeholder facts verbatim):** when scaffolding a doc, substitute this project's real facts — write content in **Russian**; **Python 3.12+** (not the template's "3.10+"); Bob's **DDD + Clean Architecture** layering (NOT the template's example "CLI → Core → Storage", which is a beadloom-CLI artifact); stack per §0.1 (Telegram / Ollama / SQLite+FTS5).

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
4. Coordinator launches roles as first-class subagents via the `Agent` tool (`subagent_type: dev|test|review|tech-writer`), tracked through `bd swarm` / `gate` / `merge-slot`.

Roles are defined canonically in `.claude/agents/{dev,test,review,tech-writer}.md` (single source of truth; no slash-command wrappers).

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
owner still self-merges). Safe to re-run.

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

### Shell
- Using `cp`, `mv`, `rm` without `-f` flag (may hang on interactive prompts)

### Code
- Using `Any` / `# type: ignore` without reason
- Leaving `print()` / `breakpoint()`
- Writing code without a test (TDD violation)
- Bare `except:` without specifying exception type
- `import *`
- Mutable default arguments (`def f(x=[]):`)

---

## 8. Quick Reference

### Session start
```bash
beadloom prime                        # project context
bd ready
bd update <id> --status in_progress --claim
beadloom ctx <ref-id>                 # architecture context for the area
# Read CONTEXT.md, ACTIVE.md (if epic)
# Confirm to user
```

### During work
```bash
# Every 30 min
bd comments add <id> "CHECKPOINT: ..."
# Update ACTIVE.md
```

### Completing bead
```bash
uv run pytest
bd comments add <id> "COMPLETED: ..."
bd close <id> --suggest-next          # shows newly unblocked beads
```

### New work item
```
/task-init
```

### Need templates
```
/templates
```

---

## 9. Agent Checklist

### At start
- [ ] `beadloom prime` -> project overview
- [ ] `bd ready` -> selected a task
- [ ] `bd update <id> --status in_progress --claim`
- [ ] `beadloom ctx <ref-id>` -> architecture context
- [ ] Read CONTEXT.md and ACTIVE.md (if epic)
- [ ] Confirmed understanding to user

### During work
- [ ] Updating ACTIVE.md
- [ ] Checkpoint in beads every 30 min
- [ ] Following TDD (if code)

### At completion
- [ ] Tests pass
- [ ] `bd comments add` — final checkpoint
- [ ] `bd close <id>`
- [ ] ACTIVE.md cleaned

---

> **Need detailed instructions?** Slash skills: `/task-init` | `/coordinator` | `/templates` | `/checkpoint`.
> Role subagents (`Agent` tool / follow the agent file inline): `dev` | `test` | `review` | `tech-writer` — see §0.0.
