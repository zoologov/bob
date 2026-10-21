<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BDL-UX — черновик записей из BOB-112 / BOB-113 (для переноса в лог beadloom)

> **Статус:** черновик, 2026-10-21. Лог `beadloom/.claude/development/BDL-UX-Issues.md` в этот день
> правит другая сессия (BDL-083 S4, записи 366–373), поэтому записи подготовлены здесь, обезличенно
> и по шаблону лога, а не вписаны туда параллельно (П.0.3 п.9 — файл на двоих). Перенос: взять
> номер `beadloom issue-number allocate --holder <bead>`, вставить запись под **Open Issues** в
> убывающем порядке и строку в индекс. Все замеры — релизная сборка **9.0.0**, проект-adopter:
> Python-монолит, DDD-вертикали + shared kernel, 23 узла / 121 ребро / 1635 символов.
> `measured_on: 2026-10-21 9.0.0`.

---

### [2026-10-21] [LOW] the `Stack:` line of the `project-info` auto-region is cut mid-word

**Severity:** low (cosmetic, but the auto-region is the one block CLAUDE.md asks the reader to trust)
**Command:** `beadloom config-check --fix`, `beadloom setup-agentic-flow`
**Context:** an adopter whose `pyproject.toml` lists `aiogram`, `structlog`, … as dependencies regenerated the auto-regions on 9.0.0.
**Issue:** the written line reads `- **Stack:** Python (>=3.12) — aiogram, s` — the second dependency is cut after its first letter; every later regeneration writes the same truncated line, so it is deterministic, not a race.
**Expected:** the full comma-separated list, or an explicit cap («aiogram, structlog, … (+N)») that says it is a cap.
**Workaround:** the project keeps an «authoritative facts» paragraph in its project layer right under the auto-region.

### [2026-10-21] [MEDIUM] `/task-init` core prints «ALL documents MUST be in English» although `flow.yml` says `language: ru`

**Severity:** medium (two artifacts of one composition contradict each other; the adopter's only honest route is a declared suppression of a core rule that the tool itself wrote wrong)
**Command:** `beadloom setup-agentic-flow` with `language: ru` in `.beadloom/flow.yml`
**Context:** adopting the project layer on 9.0.0; the team writes every PRD/RFC/CONTEXT/PLAN/BRIEF in Russian.
**Issue:** the `doc-language` auto-region of CLAUDE.md correctly says «MUST be written in Russian — set by `language: ru`», and the shared role fragments `_writing/_rooms/_landing/_tracker` arrive localised, but `commands/task-init.md` (Template rules + both checklists) still says English, and `commands/templates.md` ships no `.ru` fragment at all. Core and overlay are append-only, so the project cannot correct the line — it declared `overlays.suppress` on «Template rules» with `until: the task-init core reads language from flow.yml`.
**Expected:** every shipped fragment that states the document language reads it from `language:`; where a localisation is missing, the composition note says so (it does for role fragments, silently not for commands).
**Workaround:** a declared suppression + the rule restated in `.beadloom/flow/commands/task-init.md`.

### [2026-10-21] [LOW] a suppression's `rule` cannot name a heading written in a non-Latin script

**Severity:** low (a documented limit would be enough; today the mismatch is reported only as «matches no rule» without saying why)
**Command:** `beadloom config-check` with `overlays.suppress` in `flow.yml`
**Context:** the project layer's own headings are Russian («П.6 Git — как оно есть…»); the first attempt named the rule as `CLAUDE.md §6 Git — «main is branch-protected»…` with a `/` inside the quoted text.
**Issue:** `suppresses_nothing` normalises both sides with `[^a-z0-9]+ → space`, so every Cyrillic character vanishes and the `/` inside the quote splits the path into segments; the finding says only «matches no rule in the composed flow — name the rule by its heading path». It took reading `flow_suppression.py` to learn that (a) the rule is a `/`-separated path, (b) only `[a-z0-9]` survive, (c) a segment matches by substring.
**Expected:** the finding prints the three matching rules and the nearest heading candidates; the normaliser keeps Unicode letters (`\w`), so a heading in the adopter's language can be named.
**Workaround:** name the shipped (English) heading: `Git — Trunk-based development`, `Template rules`.

### [2026-10-21] [MEDIUM] `lint` does not see `from pkg import subpackage` and relative imports as graph edges

**Severity:** medium (an architecture gate blind to two legal import forms is a gate a refactor can walk around without noticing)
**Command:** `beadloom reindex --full && beadloom lint --strict`
**Context:** BOB-113-class refactor: moving cross-context contracts into a shared kernel, with an in-repo AST guard as the second tooth.
**Issue:** the review of that guard found it blind to `from bob import social` (package import, attribute access later) and to `from . import x` / `from ..y import z`; the same probes against `lint` showed the same blindness — the derived `depends_on` edges come only from `import a.b` / `from a.b import c` forms. A cycle written through either form is invisible to `no-dependency-cycles`. Measured again in BOB-112 .7 with a parity test (every import the AST reads must be in `code_imports`): `from bob import memory`, `from bob.memory import adapters`, `from . import x` and `import a.b as c` are all absent from the index. The same hole inside one node: `from bob.coding import usecases` in `coding/untrusted_repo.py` leaves `lint` green although `coding-internals-no-usecases-untrusted_repo` (`to: bob/coding/usecases*`) should fire; the adopter has two such imports today (`coding/usecases/coding_assistant.py:60`, `interactive/usecases/session.py:97`).
**Expected:** the import resolver derives an edge for every form Python binds a module by (absolute, aliased, package-attribute, relative), resolving `from P import name` to `P.name` when `P/name.py` or `P/name/` exists, or `lint` states which forms it does not read.
**Workaround:** the adopter's own AST guard (`tests/test_no_runtime_import_cycles.py`) reads all forms for the vertical order; `tests/test_beadloom_sees_every_import.py` pins the parity with the index (SKIP with reason without beadloom on PATH). Rewriting legal Python (~45 call sites) to a form the tool reads was refused: the fix belongs to the resolver.

### [2026-10-21] [MEDIUM] `no-dependency-cycles` cannot see an edge that starts in a node sharing its `source:` with another node

**Severity:** medium (a shared kernel is the textbook DDD shape, and the rule goes blind exactly there)
**Command:** `beadloom lint --strict` with `forbid_cycles`
**Context:** `kernel` is declared with a `source:` under the same tree as the umbrella `bob-domain` node (`part_of`). After moving contracts into the kernel, a deliberate sabotage (kernel importing a vertical) stayed green in `lint`.
**Issue:** the edge from the kernel is attributed to the umbrella node (or dropped) because two nodes claim one source root; the cycle rule then judges the umbrella, not the kernel. Nothing in `lint` output says the attribution is ambiguous.
**Expected:** `doctor`/`lint` flag overlapping `source:` roots as a population problem («N files claimed by two nodes»), and the cycle rule names the node whose annotation won.
**Workaround:** explicit `# beadloom:feature=` annotations on the kernel's files + the in-repo AST guard.

### [2026-10-21] [MEDIUM] `type-only` (`TYPE_CHECKING`) imports are indistinguishable in `lint` output, and `forbid_cycles` has no way to say how it judged them

**Severity:** medium (the 2.1.0 → 9.0.0 jump turned 0 lint errors into 925 lines / 15 cycle pairs, all from `TYPE_CHECKING` imports; a team cannot tell a verdict shift from a defect without instrumenting the resolver itself)
**Command:** `beadloom lint --strict`, `beadloom why <node>`
**Context:** triage of an upgrade on an untouched graph; the team wrote its own resolver probe to count type-only edges (30 of 98 derived edges).
**Issue:** neither the finding nor `why` marks an edge as type-only; `forbid_cycles` has no `exempt`, and the docs do not state that a `TYPE_CHECKING` import is an edge. The adopter chose to treat contract coupling as real coupling and refactor (no exemption) — but the decision had to be made blind.
**Expected:** `why`/`lint --json` carry `type_only: true` per edge; the rule's documentation states the policy; a `lint` summary line says «N of M edges are type-only».
**Workaround:** own AST probe; the refactor made the question moot (29 → 8 type-only edges, all downward).

### [2026-10-21] [LOW] `doctor` reports ~248 `no ref_id` warnings for work-item documents that by convention never carry one

**Severity:** low (noise that hides the graph warnings a reader is looking for)
**Command:** `beadloom doctor`
**Context:** 93 work items under `.claude/development/docs/features/<KEY>/` (PRD/RFC/CONTEXT/PLAN/ACTIVE/BRIEF).
**Issue:** every one of them is listed as a document without `ref_id`; the summary line reads «0 error(s), 248 warning(s)» and the 5 graph-relevant warnings are buried.
**Expected:** documents under a declared work-item root are a separate population («N work-item documents, not judged for ref_id»), or `doctor` groups them in one line; and a guide that is deliberately no node's document (`docs/getting-started.md`) can be declared as such in `config.yml` — today `doctor.py` has no key for it, so the only ways to silence the warning are a false `ref_id` or deleting the guide.
**Workaround:** `grep -v "no ref_id"`; the decision «guide, not a node document» is written in the adopter's BRIEF instead of the config.

### (снято) `rule_liveness` — 36 «правил, которые не могут сработать»

Запись удалена до переноса: это дубль открытой **BDL-UX #328** «rule_liveness calls a live
forbid_import rule dead» с неверной рамкой. Ревью BOB-112 .5 саботажем показало, что все три
класса правил (composition-root с glob `bob/app`, `untrusted_repo.py`, `identity/usecases*`) живые
и называют файл и строку; ноль совпадений — соблюдённый инвариант или упреждающий гард. Полезное
дополнение к #328 для апстрима, если его там ещё нет: файл без единого импорта не попадает в
«indexed source files», и `from:`-glob на него читается как «matches 0» — второй источник ложного
сигнала помимо «to:-glob без совпадений».

### [2026-10-21] [HIGH] `import a.b.c as d` derives no edge — any `forbid_import` rule is walked around by an alias

**Severity:** high (a boundary rule that one keyword defeats is not a boundary; the form is idiomatic and ruff does not rewrite it)
**Command:** `beadloom reindex --full && beadloom lint --strict`
**Context:** review sabotage on a DDD adopter: `import bob.memory.adapters.fts_recall as _f` in a module of another context.
**Issue:** the index holds no `code_imports` row for the aliased import, so `lint` is green; the same line without `as` is red (`memory-boundary-no-coding-adapters`, file and line). The derived `depends_on` edge is missing too, so `why`, the cycle rule and the layer rule are all blind to it. In the adopter's source the form occurs 0 times today — the hole is latent, which is exactly when a gate should find it.
**Expected:** the resolver reads `import a.b.c as d` (and `import a.b.c, a.b.d as e`) exactly as `import a.b.c`; a test in beadloom's own suite enumerates every import form Python has.
**Workaround:** the adopter's AST guard (`tests/test_no_runtime_import_cycles.py`) reads the alias form since BOB-112 .7; a `ruff` rule banning `import … as` is not acceptable (it bans an idiom to patch a tool).

### [2026-10-21] [LOW] `beadloom --version` of an editable install prints the release version string

**Severity:** low (the one command a person runs to tell builds apart does not tell them apart)
**Command:** `beadloom --version`
**Context:** a machine with a beadloom checkout installed as `uv tool install -e`; the adopter pins `beadloom==9.0.0` in CI.
**Issue:** the editable build printed «beadloom, version 9.0.0» while `uv tool list` showed `beadloom v7.0.0` and its `config-check` judged 8 artifacts «stale vs CORE» against templates the release does not ship. The hooks and the PreToolUse guard call whatever `beadloom` is on PATH, so a wrong build fails a push with a verdict about another version.
**Expected:** `--version` of a non-release build says so (`9.0.0+editable.<sha>` or `… (from /path, branch …)`), and `install-hooks` prints which build the hook will run.
**Workaround:** `uv tool list`; `uv tool install beadloom==<pin> --force` on the machine.

### [2026-10-21] [LOW] `config-check` prints the «project layer in effect» warning on every run once a project layer exists

**Severity:** low (a permanent warning trains readers to skip warnings; the verdict line says «1 warning(s)» for a state the tool itself recommends)
**Command:** `beadloom config-check`
**Context:** adopting `.beadloom/flow/` as 9.0.0 recommends.
**Issue:** the warning text itself says «this is the supported place for a standing practice and needs no action» — a warning that needs no action is a notice.
**Expected:** a `::notice` (or `info`) line listing the fragments; `warn` only when a fragment contradicts a core heading without a declared suppression (which the text already hints it could detect).
**Workaround:** none; the line is read and ignored.

### [2026-10-21] [MEDIUM] the pre-push hook written by `install-hooks` runs whatever `beadloom` is on PATH — a different build than CI can block or pass a push

**Severity:** medium (the adopter pins `beadloom==9.0.0` in CI; the hook ran an editable 7.0.0 and reported 8 composed artifacts «stale vs CORE» — a verdict about another version's templates)
**Command:** `beadloom install-hooks` → `.git/hooks/pre-push`
**Context:** a developer machine where a beadloom checkout is installed as a uv tool (editable), and the adopter repo pins the release in CI.
**Issue:** the hook has no way to name the build: it calls `beadloom ci` from PATH and exits 0 silently when none is found. The gate's verdict therefore depends on what happens to be installed, which is exactly the «local and CI are different builds» trap the adopter documents for its roles.
**Expected:** `install-hooks --pin <version>` (or `pin:` under `hooks:` in `config.yml`) writes `uvx --from beadloom==<version> beadloom ci` into the hook; `install-hooks` prints which build the hook will run.
**Workaround:** `uv tool install beadloom==<version> --force` on the machine (what the adopter did, 2026-10-21); before that, `git push --no-verify` after running the pinned `beadloom ci` by hand, with the reason written in the bead.

### [2026-10-21] [LOW] `site:` has no way to add a nav item of the project's own

**Severity:** low (the portal is otherwise fully declarative; one link is the only thing left that pushes an adopter back to owning `config.mjs`)
**Command:** `beadloom docs site`
**Context:** an adopter ships a hand-made architecture landing (`public/<landing>.html`) and had a «Схема архитектуры» item in the top nav of its previous hand-written portal.
**Issue:** `site:` accepts title/description/base/repo_url/forges/logo/powered_by/repo_icon; the nav comes only from `config.generated.mjs`. To keep the item the adopter would have to overlay `.vitepress/config.mjs`, i.e. own a scaffold file again — the thing the overlay model was built to avoid. The adopter dropped the item and kept the link in the home hero.
**Expected:** `site.nav: [{text, link, target?}]` appended after the generated nav (and the same for a footer link).
**Workaround:** the link in the overlay's `index.md` hero/features.
