<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BDL-UX — черновик записей из BOB-112 / BOB-113 (для переноса в лог beadloom)

> **Статус:** черновик, 2026-10-21 (обновлён после ревью .9). Лог
> `beadloom/.claude/development/BDL-UX-Issues.md` в этот день правит другая сессия (BDL-083 S4,
> записи 366–373), поэтому записи подготовлены здесь по шаблону лога, а не вписаны туда параллельно
> (П.0.3 п.9 — файл на двоих). Перенос — беада `bob-v25`: взять номер
> `beadloom issue-number allocate --holder <bead>`, вставить запись под **Open Issues** в убывающем
> порядке и строку в индекс, вписать номера в `reason` обоих `overlays.suppress` и в слой CLAUDE.md.
> Записи **обезличены** по правилу лога: проект-adopter описан как «a DDD monolith: Python 3.12,
> ~400 source files, 23 nodes / 121 derived edges / 1635 symbols, bounded contexts as vertical
> packages plus a shared kernel», имена модулей заменены на роли. Все замеры — релизная сборка
> **9.0.0**, `measured_on: 2026-10-21 9.0.0`.

---

### [2026-10-21] [LOW] the `Stack:` line of the `project-info` auto-region is cut mid-word

**Severity:** low (cosmetic, but the auto-region is the one block CLAUDE.md asks the reader to trust)
**Command:** `beadloom config-check --fix`, `beadloom setup-agentic-flow`
**Context:** an adopter whose `pyproject.toml` lists several dependencies regenerated the auto-regions on 9.0.0.
**Issue:** the written line reads `- **Stack:** Python (>=3.12) — <first dependency>, s` — the second dependency is cut after its first letter; every later regeneration writes the same truncated line, so it is deterministic, not a race.
**Expected:** the full comma-separated list, or an explicit cap («a, b, … (+N)») that says it is a cap.
**Workaround:** the project keeps an «authoritative facts» paragraph in its project layer right under the auto-region.

### [2026-10-21] [MEDIUM] `/task-init` core prints «ALL documents MUST be in English» although `flow.yml` says `language: ru`

**Severity:** medium (two artifacts of one composition contradict each other; the adopter's only honest route is a declared suppression of a core rule that the tool itself wrote wrong)
**Command:** `beadloom setup-agentic-flow` with `language: ru` in `.beadloom/flow.yml`
**Context:** adopting the project layer on 9.0.0; the team writes every PRD/RFC/CONTEXT/PLAN/BRIEF in Russian.
**Issue:** the `doc-language` auto-region of CLAUDE.md correctly says «MUST be written in Russian — set by `language: ru`», and the shared role fragments `_writing/_rooms/_landing/_tracker` arrive localised, but `commands/task-init.md` (Template rules + both checklists) still says English, and `commands/templates.md` ships no `.ru` fragment at all. Core and overlay are append-only, so the project cannot correct the line — it declared `overlays.suppress` on «Template rules» with `until: the task-init core reads language from flow.yml`.
**Expected:** every shipped fragment that states the document language reads it from `language:`; where a localisation is missing, the composition note says so (it does for role fragments, silently not for commands).
**Workaround:** a declared suppression + the rule restated in `.beadloom/flow/commands/task-init.md`.

### [2026-10-21] [LOW] a suppression's `rule` cannot name a heading written in a non-Latin script, and the mismatch finding does not say why

**Severity:** low (a documented limit would be enough; today the mismatch is reported only as «matches no rule»)
**Command:** `beadloom config-check` with `overlays.suppress` in `flow.yml`
**Context:** the project layer's own headings are Russian; the first attempt named the rule with a quoted core sentence that contained a `/`.
**Issue:** `suppresses_nothing` normalises both sides with `[^a-z0-9]+ → space`, so every Cyrillic character vanishes and the `/` inside the quote splits the path into segments; the finding says only «matches no rule in the composed flow — name the rule by its heading path». It took reading `flow_suppression.py` to learn that (a) the rule is a `/`-separated path, (b) only `[a-z0-9]` survive, (c) a segment matches by substring.
**Expected:** the finding prints the matching rules and the nearest heading candidates; the normaliser keeps Unicode letters (`\w`), so a heading in the adopter's language can be named.
**Workaround:** name the shipped (English) heading: `Git — Trunk-based development`, `Template rules`.

### [2026-10-21] [HIGH] four legal import forms derive no `code_imports` row — `forbid_import`, `forbid_cycles` and `why` are blind to them

**Severity:** high (a boundary rule that one keyword or one spelling defeats is not a boundary; inside a node one of the forms walks around 38 of the adopter's 262 `forbid_import` rules)
**Command:** `beadloom reindex --full && beadloom lint --strict`, `beadloom why <node>`
**Context:** a review sabotage on the adopter, then a parity test the adopter wrote: every import its AST reads must be present in `code_imports` as the full module.
**Issue:** measured absent from the index on 9.0.0 — (1) `import a.b.c as d` (alias; the same line without `as` is red with file and line); (2) `from a import b` where `b` is a sub-package (package attribute); (3) `from a.b import c` where `c` is a sub-package of the same node, e.g. `from <context> import usecases` inside that context — `lint` stays green although the context's own `internals-no-usecases` rule should fire, and the adopter had two such imports in production code; (4) `from . import x` / `from ..y import z`. A cycle or a boundary breach written through any of them is invisible to `no-dependency-cycles`, to every `forbid_import` and to `why`.
**Expected:** the resolver derives an edge for every form Python binds a module by (absolute, aliased, package-attribute, relative), resolving `from P import name` to `P.name` when `P/name.py` or `P/name/` exists; a test in beadloom's own suite enumerates the forms.
**Workaround:** the adopter's AST guards read every form for its vertical order; a parity test (AST set ⊆ `code_imports`, clean index in a temp dir, SKIP with reason without beadloom on PATH) pins the gap; the two intra-node imports were rewritten to `from <context>.usecases.<module> import <name>` — the one form the resolver indexes as a full module. Banning an idiom with a linter rule was refused: it patches a tool by bending the code.

### [2026-10-21] [MEDIUM] `no-dependency-cycles` cannot see an edge that starts in a node sharing its `source:` with another node

**Severity:** medium (a shared kernel is the textbook DDD shape, and the rule goes blind exactly there)
**Command:** `beadloom lint --strict` with `forbid_cycles`
**Context:** the kernel node is declared with a `source:` under the same tree as the umbrella node it is `part_of`. After moving contracts into the kernel, a deliberate sabotage (kernel importing a vertical) stayed green in `lint`.
**Issue:** the edge from the kernel is attributed to the umbrella node (or dropped) because two nodes claim one source root; the cycle rule then judges the umbrella, not the kernel. Nothing in `lint` output says the attribution is ambiguous.
**Expected:** `doctor`/`lint` flag overlapping `source:` roots as a population problem («N files claimed by two nodes»), and the cycle rule names the node whose annotation won.
**Workaround:** explicit `# beadloom:feature=` annotations on the kernel's files + the adopter's kernel-isolation test.

### [2026-10-21] [MEDIUM] `TYPE_CHECKING`-only imports are indistinguishable in `lint`/`why` output, and the cycle rule's policy on them is unstated

**Severity:** medium (the 2.1.0 → 9.0.0 jump turned 0 lint errors into 925 lines / 15 cycle pairs, all from `TYPE_CHECKING` imports; a team cannot tell a verdict shift from a defect without instrumenting the resolver itself)
**Command:** `beadloom lint --strict`, `beadloom why <node>`
**Context:** triage of an upgrade on an untouched graph; the team wrote its own resolver probe to count type-only edges (30 of 98 derived edges).
**Issue:** neither the finding nor `why` marks an edge as type-only; `forbid_cycles` has no `exempt`, and the docs do not state that a `TYPE_CHECKING` import is an edge. The adopter chose to treat contract coupling as real coupling and refactor (no exemption) — but the decision had to be made blind.
**Expected:** `why`/`lint --json` carry `type_only: true` per edge; the rule's documentation states the policy; a `lint` summary line says «N of M edges are type-only».
**Workaround:** own AST probe; the refactor made the question moot (29 → 8 type-only edges, all downward).

### [2026-10-21] [LOW] `doctor` lists every work-item document and every deliberate guide as «no ref_id», ~250 warnings on one project

**Severity:** low (noise that hides the graph warnings a reader is looking for; and a guide that is no node's document cannot be declared as such)
**Command:** `beadloom doctor`
**Context:** 93 work items under `.claude/development/docs/features/<KEY>/` (PRD/RFC/CONTEXT/PLAN/ACTIVE/BRIEF) and one deployment guide under `docs/`.
**Issue:** every one of them is listed as a document without `ref_id`; the summary line reads «0 error(s), 249 warning(s)» and the graph-relevant warnings are buried. `doctor.py` has no config key to declare a document outside the graph, so the only ways to silence the guide's warning are a false `ref_id` or deleting the guide.
**Expected:** documents under a declared work-item root are a separate population («N work-item documents, not judged for ref_id»), and `config.yml` can name documents that are deliberately no node's (`docs: unlinked: [...]`).
**Workaround:** `grep -v "no ref_id"`; the decision «guide, not a node document» is written in the adopter's BRIEF instead of the config.

### (снято) `rule_liveness` — 36 «правил, которые не могут сработать»

Запись удалена до переноса: это дубль открытой **BDL-UX #328** «rule_liveness calls a live
forbid_import rule dead» с неверной рамкой. Ревью BOB-112 .5 саботажем показало, что все три
класса правил живые и называют файл и строку; ноль совпадений — соблюдённый инвариант или
упреждающий гард. Полезное дополнение к #328 для апстрима, если его там ещё нет: файл без единого
импорта не попадает в «indexed source files», и `from:`-glob на него читается как «matches 0» —
второй источник ложного сигнала помимо «to:-glob без совпадений».

### [2026-10-21] [LOW] `config-check` prints the «project layer in effect» warning on every run once a project layer exists

**Severity:** low (a permanent warning trains readers to skip warnings; the verdict line says «1 warning(s)» for a state the tool itself recommends)
**Command:** `beadloom config-check`
**Context:** adopting `.beadloom/flow/` as 9.0.0 recommends.
**Issue:** the warning text itself says «this is the supported place for a standing practice and needs no action» — a warning that needs no action is a notice.
**Expected:** a `::notice` (or `info`) line listing the fragments; `warn` only when a fragment contradicts a core heading without a declared suppression (which the text already hints it could detect).
**Workaround:** none; the line is read and ignored.

### [2026-10-21] [MEDIUM] the hooks written by `install-hooks` run whatever `beadloom` is on PATH — a different build than CI can block or pass a push

**Severity:** medium (the adopter pins the release in CI; the hook ran an editable build and reported 8 composed artifacts «stale vs CORE» — a verdict about another version's templates)
**Command:** `beadloom install-hooks` → `.git/hooks/pre-push`, `.git/hooks/pre-commit`, the PreToolUse guard adapter
**Context:** a developer machine where a beadloom checkout is installed as a uv tool (editable), and the adopter repo pins the release in CI.
**Issue:** the hooks have no way to name the build: they call `beadloom` from PATH and exit 0 silently when none is found. The gate's verdict therefore depends on what happens to be installed, which is exactly the «local and CI are different builds» trap the adopter documents for its roles.
**Expected:** `install-hooks --pin <version>` (or `pin:` under `hooks:` in `config.yml`) writes `uvx --from beadloom==<version> beadloom ci` into the hook; `install-hooks` prints which build the hook will run.
**Workaround:** `uv tool install beadloom==<version> --force` on the machine (what the adopter did); before that, `git push --no-verify` after running the pinned `beadloom ci` by hand, with the reason written in the bead.

### [2026-10-21] [MEDIUM] the pre-push hook's `beadloom ci` reindexes incrementally, so the push gate runs on the index whose import edges can be stale

**Severity:** medium (the one check that stands between a developer and the remote is the one that can read a stale pair or a missing edge `ok`; #142 is the same family)
**Command:** `.git/hooks/pre-push` → `beadloom ci`
**Context:** the adopter's CI and its coordinator run `rm -f .beadloom/beadloom.db && beadloom ci` (a documented rule since an incremental reindex let a cycle through); the hook written by `install-hooks` runs `beadloom ci` as is, and its first line says `reindex PASS: up to date`.
**Issue:** `ci` has `--no-reindex` but no `--full`/clean-index option, and the hook is managed (rewritten by `install-hooks`), so the adopter cannot make the push gate honest without owning the hook. The documentation calls the hook «the same gate» as CI.
**Expected:** `beadloom ci --full` (or `ci` rebuilding the index by default) and the hook written with it; or the hook text stating that it judges an incremental index.
**Workaround:** the adopter's documentation names the hook an early diagnosis, not a proof; the authoritative gates are CI and the coordinator's clean-index run.

### [2026-10-21] [LOW] `beadloom --version` of an editable install prints the release version string

**Severity:** low (the one command a person runs to tell builds apart does not tell them apart)
**Command:** `beadloom --version`
**Context:** a machine with a beadloom checkout installed as `uv tool install -e`; the adopter pins the release in CI.
**Issue:** the editable build printed «beadloom, version 9.0.0» while `uv tool list` showed another version and its `config-check` judged 8 artifacts «stale vs CORE» against templates the release does not ship.
**Expected:** `--version` of a non-release build says so (`9.0.0+editable.<sha>` or `… (from /path, branch …)`), and `install-hooks` prints which build the hook will run.
**Workaround:** `uv tool list`; `uv tool install beadloom==<pin> --force` on the machine.

### [2026-10-21] [LOW] `site:` has no way to add a nav item of the project's own

**Severity:** low (the portal is otherwise fully declarative; one link is the only thing left that pushes an adopter back to owning `config.mjs`)
**Command:** `beadloom docs site`
**Context:** an adopter ships a hand-made architecture landing (`public/<landing>.html`) and had a link to it in the top nav of its previous hand-written portal.
**Issue:** `site:` accepts title/description/base/repo_url/forges/logo/powered_by/repo_icon; the nav comes only from `config.generated.mjs`. To keep the item the adopter would have to overlay `.vitepress/config.mjs`, i.e. own a scaffold file again — the thing the overlay model was built to avoid. The adopter dropped the item and kept the link in the home hero.
**Expected:** `site.nav: [{text, link, target?}]` appended after the generated nav (and the same for a footer link).
**Workaround:** the link in the overlay's `index.md` hero/features.
