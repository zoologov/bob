<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1
     See the LICENSE file in the project root for full license information. -->

# RFC-VALIDATION-2: Full Architecture Review (Round 7)

> **Date:** 2026-02-28
> **Document analyzed:** RFC.md (~9717 lines)
> **Method:** 6 parallel review agents, each covering ~1600 lines, cross-referencing with actual codebase
> **Author:** Claude (validation), v.zoologov (review)

---

## Table of Contents

1. [Summary](#1-summary)
2. [Systemic Issues](#2-systemic-issues)
3. [Critical Issues](#3-critical-issues)
4. [Warnings](#4-warnings)
5. [Minor Issues](#5-minor-issues)
6. [Fix Log](#6-fix-log)

---

## 1. Summary

| Severity | Count (raw) | Count (deduplicated) |
|----------|-------------|----------------------|
| SYSTEMIC | — | 5 |
| CRITICAL | 26 | 13 |
| WARNING | 56 | 20 |
| MINOR | 34 | 15 |
| **Total** | **116** | **53** |

Grouped into **20 work items** (beads) for resolution.

---

## 2. Systemic Issues

### S1. `bob/` vs `src/bob/` — all file paths in RFC are wrong
- **Bead:** `VAL2-S1`
- **Lines:** ~100+ occurrences throughout entire document
- **Problem:** RFC uses `bob/skills/`, `bob/mind/`, etc. Actual project: `src/bob/`. Confirmed by `pyproject.toml` line 51: `packages = ["src/bob"]`.
- **Status:** [ ] Open

### S2. All code is hypothetical but written in present tense
- **Bead:** `VAL2-S2`
- **Lines:** Entire document
- **Problem:** Every module is stub-only (`__init__.py` with docstring). RFC reads as if systems exist ("are implemented", "provides", "runs"). Needs status markers or future tense.
- **Status:** [ ] Open

### S3. Missing imports in code examples (~20 places)
- **Bead:** `VAL2-S3`
- **Lines:** 348, 386, 459, 530, 650, 958, 1053, 2720, 3130, 3146, 3730, 3903, 4017, 8077, 8082, 8084
- **Problem:** `Any` from typing (~15 places), `UTC` from datetime (~5 places), `Literal` (2 places) used without import.
- **Status:** [ ] Open

### S4. Voice stack mismatch: RFC vs pyproject.toml
- **Bead:** `VAL2-S4`
- **Lines:** RFC 9123-9124 vs pyproject.toml lines 31-34
- **Problem:** RFC says whisper.cpp + Qwen3-TTS (mlx-audio). pyproject.toml has faster-whisper + kokoro.
- **Decision needed:** Which is canonical?
- **Status:** [ ] Open

### S5. License inconsistency across project
- **Bead:** `VAL2-S5`
- **Lines:** pyproject.toml line 11, source file headers, LICENSE files
- **Problem:** pyproject.toml says MIT; source headers say BUSL-1.1; skills/__init__.py says Apache-2.0.
- **Decision needed:** Which license applies?
- **Status:** [ ] Open

---

## 3. Critical Issues

### B1. Schema duplication: false claim in section 3.4.4
- **Bead:** `VAL2-B1`
- **Lines:** 4491-4493 (claim), 2606-2620, 3030-3067, 3569-3633, 4174-4228 (duplicates)
- **Problem:** Section 3.4.4 states "all CREATE TABLE defined here only" but schemas are duplicated in sections 3.3.8-3.3.11.
- **Decision needed:** Remove duplicates from subsections or update the claim?
- **Status:** [ ] Open

### B2. `inter_call_delay_sec`: dataclass=10.0 vs YAML=2
- **Bead:** `VAL2-B2`
- **Lines:** 4109 vs 4155
- **Problem:** Budget math requires 10s (50 x 11.5s = ~10 min). YAML says 2s (would give ~3 min, outside stated 5-15 min range).
- **Status:** [ ] Open

### B3. `object_experience` SQL missing `imprint_active` column
- **Bead:** `VAL2-B3`
- **Lines:** dataclass 1548-1560 vs SQL 1636-1647
- **Problem:** `ObjectExperience.imprint_active: bool` field has no corresponding column in CREATE TABLE.
- **Status:** [ ] Open

### B4. Sample rate contradiction: 24000 Hz vs 22050 Hz
- **Bead:** `VAL2-B4`
- **Lines:** 8006/8013 (24000) vs 8061 (22050)
- **Problem:** Config says 24000 Hz (Qwen3-TTS native), prose says 22050 Hz.
- **Status:** [ ] Open

### B5. Avatar parts count: 6 vs 10
- **Bead:** `VAL2-B5`
- **Lines:** 7414 ("6-8 parts"), 7490-7491 (10 parts in Skeleton2D), 7608-7613 (6 files), 9483-9486 (6 files)
- **Problem:** Skeleton2D rig lists 10 body parts (with upper/lower segments). Asset directories show 6 PNG files. Incompatible.
- **Decision needed:** 6-part or 10-part model?
- **Status:** [ ] Open

### B6. `game_state.json` vs `room_state.json` naming
- **Bead:** `VAL2-B6`
- **Lines:** game_state: 6411, 8588, 9460 | room_state: 7151, 7200, 7722
- **Problem:** Same conceptual file has two names.
- **Decision needed:** Which name?
- **Status:** [ ] Open

### B7. SD prerequisite checks wrong package
- **Bead:** `VAL2-B7`
- **Lines:** 5348-5351 vs 7375
- **Problem:** Checks `import mlx` and installs `mlx-image`, but tech stack says `mflux`.
- **Status:** [ ] Open

### B8. Filename inconsistencies (archetype, LoRA)
- **Bead:** `VAL2-B8`
- **Lines:** archetype: 5391, 5499 vs 4893, 9310 | LoRA: 7569, 7589 vs 7631, 9491
- **Problem:** `archetype.md` vs `book_archetype.md`; `bob_style_v1.safetensors` vs `bob_style.safetensors`
- **Status:** [ ] Open

### B9. Repository structure section (11) mismatches reality
- **Bead:** `VAL2-B9`
- **Lines:** 9298-9556
- **Problems:**
  - PRD.md/RFC.md shown at repo root, actually at `.claude/dev-docs/`
  - Entry point `bob/main.py` does not exist; no `[project.scripts]`
  - `src/bob/llm/` package exists in code but missing from RFC tree
  - `docs/domains/` subdir exists but not in RFC tree
  - `relationship_tracker.py` has test but no source file in tree
- **Status:** [ ] Open

### B10. 9 technologies in Tech Stack missing from pyproject.toml
- **Bead:** `VAL2-B10`
- **Lines:** 9127-9149
- **Missing:** FAISS, scikit-learn, librosa, mflux, unsloth, alembic, structlog, pydantic-settings
- **Decision needed:** Add to pyproject.toml (which group?) or mark as "Phase N" in RFC?
- **Status:** [ ] Open

### B11. Event dataclass code has import errors
- **Bead:** (covered by S3)
- **Lines:** 8074-8085
- **Problem:** `Any` not imported, `UTC` not imported. Code would raise NameError.
- **Status:** [ ] Open (tracked under S3)

### B12. Dead references to non-existent directories
- **Bead:** `VAL2-B12`
- **Lines:** bob-soul/: 69, 1365, 1607, 9307 | config/: 306, 884, 9333 | scripts/: 9168, 9546 | _template/: 159
- **Problem:** Directories referenced extensively but don't exist.
- **Decision needed:** Create skeleton dirs or mark as planned?
- **Status:** [ ] Open

### B13. Undefined classes referenced in event catalog and architecture
- **Bead:** `VAL2-B13`
- **Lines:** MemorySystem: 2476, 3942 | ContextEnricher: 3116, 3422 | PeripheralScanner: 8177 | TabletBridge: 8175 | AppearanceManager: 8185 | AuditLogger: 8194 | TelegramDomain: 8171
- **Problem:** Classes used as types/publishers/subscribers but never defined anywhere in RFC.
- **Status:** [ ] Open

---

## 4. Warnings

### W1. Mermaid diagram: `SkillRegistry` should be `SkillDomainRegistry`
- **Bead:** `VAL2-W1`
- **Lines:** 176
- **Status:** [ ] Open

### W2. Streaming TTS bypasses AudioRouter
- **Bead:** `VAL2-W2`
- **Lines:** 7962-7987 (streaming calls voice_bridge directly) vs 8016-8053 (AudioRouter design)
- **Status:** [ ] Open

### W3. WebSocket `/ws/events` lacks authentication
- **Bead:** `VAL2-W3`
- **Lines:** 8231-8242
- **Problem:** Accepts connections without auth token or origin check.
- **Status:** [ ] Open

### W4. ContentGuard disabled during Genesis (48 hours)
- **Bead:** `VAL2-W4`
- **Lines:** 8651-8656
- **Problem:** If Telegram is active during Genesis, adversarial input is unguarded.
- **Status:** [ ] Open

### W5. Permissive fallback when Llama Guard crashes
- **Bead:** `VAL2-W5`
- **Lines:** 8722, 9041, 9057-9061
- **Problem:** Default fallback = "permissive" — all content allowed if guard crashes.
- **Status:** [ ] Open

### W6. `ClaudeCodeBridge.execute()` missing error handling
- **Bead:** `VAL2-W6`
- **Lines:** 5945-5956
- **Problem:** No TimeoutError handling, no proc.returncode check, failed invocation returns stderr as success.
- **Status:** [ ] Open

### W7. Geolocation source inconsistency (system vs tablet)
- **Bead:** `VAL2-W7`
- **Lines:** bootstrap: 5400, 5515 vs runtime: 6933, 6965
- **Problem:** Bootstrap uses system timezone, runtime config says tablet.
- **Status:** [ ] Open

### W8. `lora_trained` field is stale in bootstrap.yaml
- **Bead:** `VAL2-W8`
- **Lines:** 5445
- **Problem:** LoRA is pre-trained and shipped, not trained during bootstrap.
- **Status:** [ ] Open

### W9. Headless mode: Stage 3 mislabeled as "room design"
- **Bead:** `VAL2-W9`
- **Lines:** 6632
- **Problem:** Stage 3 is "ENERGY BLOB", not "room design" (that's Stage 5).
- **Status:** [ ] Open

### W10. `tier_thresholds: [1, 3, 4]` — tier 2→3 gap is only 1 violation
- **Bead:** `VAL2-W10`
- **Lines:** 8718-8720 vs escalation table 8984-8986
- **Problem:** Escalation table says tier 2 at "2-3 violations", config says 3. Tier 2 is extremely narrow (1 violation wide).
- **Status:** [ ] Open

### W11. Claude Code rate limit 10/min vs ~45/5-hour quota
- **Bead:** `VAL2-W11`
- **Lines:** 8528-8529 vs 8402-8403
- **Problem:** 10 invocations/min would exhaust Pro quota in <5 minutes.
- **Status:** [ ] Open

### W12. `claude_code_bridge.py` placement: `mind/` (RFC) vs `llm/` (docstring)
- **Bead:** `VAL2-W12`
- **Lines:** RFC 9374 vs llm/__init__.py docstring
- **Status:** [ ] Open

### W13. Event publisher name inconsistency
- **Bead:** `VAL2-W13`
- **Lines:** source="messaging_bot" (8141) vs TelegramDomain (8171) vs MessagingBot (8195)
- **Problem:** Three different names for the same publisher.
- **Status:** [ ] Open

### W14. WebSocket event validation: dataclasses don't validate types
- **Bead:** `VAL2-W14`
- **Lines:** 8236-8242
- **Problem:** `Event(**data)` does not validate field types. Claims "validated via dataclass fields" but dataclasses don't do runtime validation.
- **Status:** [ ] Open

### W15. TTS latency: budget 300ms vs claimed streaming 97ms
- **Bead:** `VAL2-W15`
- **Lines:** 7948 vs 9124, 9682
- **Problem:** Latency table budgets 300ms, but streaming claim is 97ms TTFB.
- **Status:** [ ] Open

### W16. Phase 0 references non-existent `scripts/bootstrap.py`
- **Bead:** (covered by B12)
- **Status:** [ ] Open (tracked under B12)

### W17. Phase 1 references structlog without dependency
- **Bead:** (covered by B10)
- **Status:** [ ] Open (tracked under B10)

### W18. `_generate_appearance()` docstring misleading
- **Bead:** `VAL2-W18`
- **Lines:** 6605-6618
- **Problem:** Says "Each key maps to a Skeleton2D body part" but keys are coarse (head, torso, arms, legs) while rig has 10 fine-grained parts.
- **Status:** [ ] Open

### W19. `SandboxConfig` network enforcement mechanism unspecified
- **Bead:** `VAL2-W19`
- **Lines:** 8316-8354
- **Problem:** Describes network_access + whitelist but no enforcement mechanism (macOS sandbox profiles? firewall? seccomp?).
- **Status:** [ ] Open

### W20. "Open Questions" section: 34/35 resolved, title misleading
- **Bead:** `VAL2-W20`
- **Lines:** 9678-9716
- **Problem:** Should be renamed to "Design Decisions Log" or similar.
- **Status:** [ ] Open

---

## 5. Minor Issues

### D1. `=field(` missing space before `=` (3 places)
- **Bead:** `VAL2-D1`
- **Lines:** 542, 962, 3146
- **Status:** [ ] Open

### D2. `str` paths instead of `Path` (3 places)
- **Bead:** `VAL2-D2`
- **Lines:** 609, 1006, 4990-4991
- **Status:** [ ] Open

### D3. `ProsodicFeatures` docstring: says "Whisper" but uses librosa
- **Bead:** `VAL2-D3`
- **Lines:** 3152
- **Status:** [ ] Open

### D4. Unused `time` import from datetime
- **Bead:** `VAL2-D4`
- **Lines:** 3132, 3721
- **Status:** [ ] Open

### D5. `CodeChangeClassifier.classify()` returns `str` instead of enum
- **Bead:** `VAL2-D5`
- **Lines:** 6118
- **Status:** [ ] Open

### D6. `QueuedClaudeTask.priority: int` instead of enum
- **Bead:** `VAL2-D6`
- **Lines:** 6066-6067
- **Status:** [ ] Open

### D7. `AuditEntry.approval_level: str` instead of `ApprovalLevel` enum
- **Bead:** `VAL2-D7`
- **Lines:** 8546
- **Status:** [ ] Open

### D8. ASCII art diagrams vs Mermaid inconsistency
- **Bead:** `VAL2-D8`
- **Lines:** 7897-7938 (voice), 8266-8279 (communication)
- **Status:** [ ] Open

### D9. `content_violations` table not listed in bob.db summary
- **Bead:** `VAL2-D9`
- **Lines:** 8579
- **Status:** [ ] Open

### D10. APPROVAL_MAP keys lack unified namespace convention
- **Bead:** `VAL2-D10`
- **Lines:** 8366-8375
- **Status:** [ ] Open

### D11. `SoulEvolution.genesis()` returns `dict[str, Any]` instead of `GenesisResult`
- **Bead:** `VAL2-D11`
- **Lines:** 4994
- **Status:** [ ] Open

### D12. S14 "Code Exploits" is custom Llama Guard extension, not noted
- **Bead:** `VAL2-D12`
- **Lines:** 8684-8699
- **Status:** [ ] Open

### D13. `RefusalGenerator` uses LLMRouter but ContentGuard wraps LLMRouter — circular note missing
- **Bead:** `VAL2-D13`
- **Lines:** 8922-8935 vs 8614-8616
- **Status:** [ ] Open

### D14. HTTP API versioning inconsistent (some paths have /api/v1/, WebSocket does not)
- **Bead:** `VAL2-D14`
- **Lines:** 8284, 8290-8294
- **Status:** [ ] Open

### D15. `docs/` actual structure with `domains/` subdir not reflected in RFC
- **Bead:** (covered by B9)
- **Status:** [ ] Open (tracked under B9)

---

## 6. Fix Log

| # | Bead ID | Issue | Decision | Fixed in commit | Status |
|---|---------|-------|----------|-----------------|--------|
| 1 | VAL2-S1 | bob/ → src/bob/ paths | — | — | Open |
| 2 | VAL2-S2 | Present tense for planned code | — | — | Open |
| 3 | VAL2-S3 | Missing imports in examples | — | — | Open |
| 4 | VAL2-S4 | Voice stack mismatch | — | — | Open |
| 5 | VAL2-S5 | License inconsistency | — | — | Open |
| 6 | VAL2-B1 | Schema duplication claim | — | — | Open |
| 7 | VAL2-B2 | inter_call_delay_sec | — | — | Open |
| 8 | VAL2-B3 | imprint_active column | — | — | Open |
| 9 | VAL2-B4 | Sample rate 24000 vs 22050 | — | — | Open |
| 10 | VAL2-B5 | Avatar parts 6 vs 10 | — | — | Open |
| 11 | VAL2-B6 | game_state vs room_state | — | — | Open |
| 12 | VAL2-B7 | SD prerequisite package | — | — | Open |
| 13 | VAL2-B8 | Filename inconsistencies | — | — | Open |
| 14 | VAL2-B9 | Repo structure mismatches | — | — | Open |
| 15 | VAL2-B10 | Missing deps in pyproject.toml | — | — | Open |
| 16 | VAL2-B12 | Dead directory references | — | — | Open |
| 17 | VAL2-B13 | Undefined classes in RFC | — | — | Open |
| 18 | VAL2-W1 | SkillRegistry → SkillDomainRegistry | — | — | Open |
| 19 | VAL2-W2 | Streaming bypasses AudioRouter | — | — | Open |
| 20 | VAL2-W3 | WebSocket auth missing | — | — | Open |
| 21 | VAL2-W4 | ContentGuard off during Genesis | — | — | Open |
| 22 | VAL2-W5 | Permissive fallback default | — | — | Open |
| 23 | VAL2-W6 | ClaudeCodeBridge error handling | — | — | Open |
| 24 | VAL2-W7 | Geolocation source inconsistency | — | — | Open |
| 25 | VAL2-W8 | lora_trained stale field | — | — | Open |
| 26 | VAL2-W9 | Stage 3 mislabeled | — | — | Open |
| 27 | VAL2-W10 | tier_thresholds gap | — | — | Open |
| 28 | VAL2-W11 | Claude Code rate limit too high | — | — | Open |
| 29 | VAL2-W12 | claude_code_bridge placement | — | — | Open |
| 30 | VAL2-W13 | Event publisher name inconsistency | — | — | Open |
| 31 | VAL2-W14 | Dataclass validation claim | — | — | Open |
| 32 | VAL2-W15 | TTS latency budget vs claim | — | — | Open |
| 33 | VAL2-W18 | _generate_appearance docstring | — | — | Open |
| 34 | VAL2-W19 | Sandbox enforcement unspecified | — | — | Open |
| 35 | VAL2-W20 | "Open Questions" title misleading | — | — | Open |
| 36 | VAL2-D1 | =field( spacing | — | — | Open |
| 37 | VAL2-D2 | str → Path for paths | — | — | Open |
| 38 | VAL2-D3 | ProsodicFeatures docstring | — | — | Open |
| 39 | VAL2-D4 | Unused time import | — | — | Open |
| 40 | VAL2-D5 | classify() returns str | — | — | Open |
| 41 | VAL2-D6 | priority: int → enum | — | — | Open |
| 42 | VAL2-D7 | approval_level: str → enum | — | — | Open |
| 43 | VAL2-D8 | ASCII vs Mermaid diagrams | — | — | Open |
| 44 | VAL2-D9 | content_violations not in db list | — | — | Open |
| 45 | VAL2-D10 | APPROVAL_MAP namespace | — | — | Open |
| 46 | VAL2-D11 | genesis() return type | — | — | Open |
| 47 | VAL2-D12 | S14 custom extension note | — | — | Open |
| 48 | VAL2-D13 | RefusalGenerator circular dep note | — | — | Open |
| 49 | VAL2-D14 | API versioning inconsistency | — | — | Open |
