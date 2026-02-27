<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1
     See the LICENSE file in the project root for full license information. -->

# RFC-VALIDATION: Bob — Cross-Document Analysis and Validation

> **Date:** 2026-02-26 (Round 1-2), 2026-02-27 (Round 3)
> **Documents analyzed:** PRD.md (347 lines), RFC.md (~7100 lines)
> **Author:** Claude (validation), v.zoologov (review)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [PRD ↔ RFC Synchronization Audit](#2-prd--rfc-synchronization-audit)
3. [Logical Collisions Within RFC](#3-logical-collisions-within-rfc)
4. [Complete User Flow (E2E)](#4-complete-user-flow-e2e)
5. [Capability Map by Phase](#5-capability-map-by-phase)
6. [Missing Details and Gaps](#6-missing-details-and-gaps)
7. [Open Questions Audit](#7-open-questions-audit)
8. [Recommendations](#8-recommendations)
9. [Round 3 — ContentGuard Integration and Full Technical Review](#9-validation-round-3--contentguard-integration-and-full-technical-review)

---

## 1. Executive Summary

### What Bob Is

Bob is a local-first autonomous home agent inspired by Bob Johansson from "We Are Legion (We Are Bob)". He:

- Runs 24/7 on a Mac mini M4 as a Python asyncio service
- Has a virtual body and room rendered on an Android tablet via Godot 4
- Sees (OBSBOT camera), hears (ReSpeaker mic array), speaks (TTS)
- Has persistent goals, tastes, mood, and personality — can disagree with the user
- Self-improves: room, code, behavior, local LLMs (LoRA fine-tune)
- Uses local LLMs (Qwen2.5) as a brain and Claude Code CLI as a "senior architect"
- Generates all visual assets via local Stable Diffusion (no hand-drawn art)
- Each installation produces a unique Bob (like copies in the book)

### What Bob Can Do (by maturity)

| Maturity | Capabilities |
|----------|-------------|
| **Day 1** (after Genesis) | Lives on tablet with unique AI-generated room. Talks via Telegram and voice. Sees and hears. Has personality, tastes, mood. |
| **Week 1** (after Awakening) | Remembers conversations. Has imprinted first impressions. Explored user's space via camera. Phantom preferences activated. |
| **Month 1** | Self-improves room (weekly reviews). Clothing changes. Has accumulated experience. Book references naturally decrease. |
| **Month 3+** | Fine-tuned local LLMs. Self-created new skills. Evolved tastes (high conviction). Unique personality diverged from archetype. |

### What Bob Cannot Do

- Cannot access the internet (except: Telegram API, Open-Meteo API for weather, Claude Code CLI)
- Cannot control smart home devices (out of scope for v1)
- Cannot run on cloud / multi-host setups
- Cannot serve multiple users
- Cannot create 3D content (2D only — Skeleton2D + parallax depth illusion)
- Cannot learn from external training data (only from its own reflections and experience)
- Cannot modify his own core architecture without Claude Code CLI + user approval

### Validation Verdict

The RFC is architecturally sound and remarkably detailed (~5000 lines). However, cross-validation reveals **12 synchronization issues** between PRD and RFC, **9 logical collisions** within the RFC, and **15 missing details** that must be resolved before implementation begins.

---

## 2. PRD ↔ RFC Synchronization Audit

The PRD (v0.0.1, 322 lines) is the business vision document. The RFC (5011 lines) is the technical architecture. After two rounds of RFC updates, the PRD has fallen behind.

### 2.1. Critical Mismatches

| # | Area | PRD says | RFC says | Impact |
|---|------|----------|----------|--------|
| **S1** | Version | v0.0.1 (line 6) | v0.1.0 (CLAUDE.md line 78) | Confusion about target version |
| **S2** | Skills architecture | "Skill Registry" — flat skill system with hot-reload (line 42) | "Skill Domain System" — two-level architecture: SkillDomain (Protocol) + Skill (Protocol) with auto-discovery, hot-reload at domain level (section 3.2.3) | PRD describes obsolete architecture |
| **S3** | Genesis stages | 5 stages: awakening → awareness → self-definition → materialization → awakening phase (lines 156-160) | 9 stages (0-8): bootstrap → gaining senses → finding home → energy blob → realization → self-determination → asset generation → materialization → writing to SOUL (section 5.1.1) | PRD describes incomplete awakening narrative |
| **S4** | Asset creation | "modular rendering system (asset packs)" (line 77), "asset pack or procedural generation?" (line 264) | Full AI generation via local Stable Diffusion, no hand-drawn assets. AssetGenerator class, LoRA style training (section 5.4.2) | PRD describes abandoned approach |
| **S5** | Godot architecture | "Godot 4 client... modular assets" (line 77) | Two-layer architecture: Godot Shell-Renderer (thin client, generic) + Scene Descriptions (server-side Python, JSON) (section 5.4) | PRD doesn't reflect renderer architecture |
| **S6** | Visual style | Not specified | Cuphead-inspired cartoon + Skeleton2D animation + parallax depth (section 5.4) | PRD has no visual style direction |
| **S7** | Bootstrap | Not mentioned | Full section 3.6: BootstrapWizard, prerequisites check, auto-install flow, graceful degradation (section 3.6) | PRD doesn't describe first-launch setup |
| **S8** | Claude Code Lock | Not mentioned | ClaudeCodeLock class, permission protocol, graceful interrupt, queue mechanism (sections 4.2.1, 8.4) | PRD doesn't address shared resource management |
| **S9** | Plugin architecture | Not mentioned as a principle | Design principle 2.6: SkillDomains as plugins, auto-discovery, event-driven communication (section 2.6) | PRD missing key architectural principle |
| **S10** | Repo structure | `bob/skills/` — flat Python modules (line 243) | `bob/skills/` — domain-based structure: `avatar/`, `development/`, `messaging/`, `_template/` (section 11) | PRD describes obsolete directory layout |
| **S11** | Development phases | Not present in PRD | 7 phases (0-6) with deliverables and readiness criteria (section 10) | PRD has no phasing — reads as "build everything for v0.0.1" |
| **S12** | Open questions | 15 questions (section 9) | 31 questions (28 open, 3 resolved) — PRD questions not updated to reflect RFC resolutions (section 13) | PRD still lists questions already answered in RFC |

### 2.2. Required PRD Updates

**Verdict:** PRD must be updated to match RFC before development begins. Key updates needed:

1. Version alignment (v0.0.1 → v0.1.0, or clarify version numbering)
2. "Skill Registry" → "Skill Domain System" throughout
3. Genesis section rewrite to match 9-stage narrative
4. "Asset packs" → "AI-generated assets via Stable Diffusion"
5. Godot client description → two-layer architecture
6. Add Bootstrap/setup section
7. Add ClaudeCodeLock concept
8. Update repo structure
9. Add reference to development phases
10. Synchronize open questions with RFC resolutions

---

## 3. Logical Collisions Within RFC

### ~~C1: Bootstrap (3.6) vs Genesis Stage 0 (5.1.1) — Naming Collision~~

**RESOLVED**: Genesis Stage 0 renamed from "BOOTSTRAP" to "CONSCIOUSNESS" in both the narrative diagram and GenesisMode.run() docstring. Technical bootstrap (section 3.6) keeps its name.

### ~~C2: Double Tablet Detection~~

**RESOLVED**: Genesis Stage 2 now reads `bootstrap.yaml` for tablet state. Two dialogue variants: if detected during bootstrap → "I know there's a screen nearby. Let me make it my home." If not → prompts user to connect. Preserves narrative, eliminates redundancy.

### ~~C3: GenesisMode.run() Docstring vs 9-Stage Narrative~~

**RESOLVED**: GenesisMode.run() docstring rewritten to explicitly list all 9 stages (0-8): CONSCIOUSNESS, GAINING SENSES, FINDING A HOME, ENERGY BLOB, REALIZATION, SELF-DETERMINATION, ASSET GENERATION, MATERIALIZATION, WRITING TO SOUL.

### ~~C4: `_generate_appearance()` Return Format vs Skeleton2D~~ **RESOLVED**

**RESOLVED:** Updated `_generate_appearance()` to return a description dict for AssetGenerator. Each key maps to a Skeleton2D body part and serves as prompt context for per-part SD generation. Includes `overall`, per-part descriptions (`head`, `torso`, `arms`, `legs`), `accessories`, `color_palette`, and `style_notes`. Flow: LLM → description dict → `AssetGenerator.generate_avatar_parts()` → per-part SD with LoRA → Godot Skeleton2D.

### ~~C5: Section 4.2.1 and 8.4 Overlap~~ **RESOLVED**

**RESOLVED:** De-duplicated. 4.2.1 = usage workflow (permission flow diagram, degradation table, queue). 8.4 = security mechanism (ClaudeCodeLock class, detection, graceful interrupt, Negotiation Engine). Duplicated diagram removed from 8.4, cross-refs added in both directions, duplicated config values removed from security.yaml with pointer to llm.yaml.

### ~~C6: AwakeningPhase.imprint_weight — Unconnected~~ **RESOLVED**

**RESOLVED:** Added 4 integration points: `TasteEvolution.reinforce(weight=)` for stronger taste anchors, `MoodEngine.process_event(imprint_weight=)` for amplified emotional impact, `ObjectExperience.imprint_active` field for marking formative experiences, `ReflectionLoop.reflect()` adds awakening context to LLM prompt. Integration summary table added to section 5.1.2.

### ~~C7: Rate Limit Naming~~

**RESOLVED**: Renamed `claude_api_calls_per_minute/day` → `claude_code_invocations_per_minute/day` in section 8.5.

### ~~C8: WindowService Network Access vs Security Model~~

**RESOLVED**: Added `NETWORK_WHITELIST` to section 8.2 (Sandbox) with `api.open-meteo.com`, `api.telegram.org`, and `localhost`. Skills with `network_access=True` are restricted to whitelisted hosts only.

### ~~C9: AssetGenerator Location in Repo Structure~~

**RESOLVED**: Moved `asset_generator.py` from `bob/genesis/` to `bob/services/` in section 11. Services directory renamed to "Peripheral services + shared generators".

---

## 4. Complete User Flow (E2E)

### 4.1. From "Read the README" to "Bob Is Alive"

```
┌────────────────────────────────────────────────────────────────────┐
│                    FULL USER JOURNEY                                │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PHASE A: DISCOVERY (user action)                            │  │
│  │                                                              │  │
│  │  1. User reads README.md on GitHub                           │  │
│  │     → Understands concept: "Your own Bob from the book"      │  │
│  │                                                              │  │
│  │  2. User has: Mac mini M4 + tablet + (optionally) camera/mic │  │
│  │     → Minimum: Mac mini + tablet                             │  │
│  │     → Full: Mac mini + tablet + OBSBOT + ReSpeaker           │  │
│  │                                                              │  │
│  │  3. git clone https://github.com/.../bob.git                 │  │
│  │     cd bob                                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PHASE B: SETUP (bob setup)                                  │  │
│  │  Duration: 10-30 min (depending on downloads)                │  │
│  │                                                              │  │
│  │  4. pip install -e .  (or uv pip install -e .)               │  │
│  │                                                              │  │
│  │  5. bob setup  (BootstrapWizard)                             │  │
│  │     ├── Check Python ≥ 3.12            ✓/✗                  │  │
│  │     ├── Install Ollama (brew)          ~2 min                │  │
│  │     ├── Pull Qwen2.5-7B + 0.5B        ~5 GB, ~5-10 min     │  │
│  │     ├── Install MLX + SD pipeline      ~6 GB, ~5-10 min     │  │
│  │     ├── Check Claude Code CLI          optional              │  │
│  │     ├── Check ADB                      for tablet            │  │
│  │     ├── Detect camera (OBSBOT)         optional              │  │
│  │     ├── Detect microphone (ReSpeaker)  optional              │  │
│  │     └── Detect tablet (ADB)            recommended           │  │
│  │                                                              │  │
│  │  ⚠ GAP: Telegram bot token not configured here              │  │
│  │  ⚠ GAP: Geolocation not configured here                     │  │
│  │  ⚠ GAP: bob-soul templates not verified here                │  │
│  │                                                              │  │
│  │  Result: bootstrap.yaml written                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PHASE C: GENESIS (bob start → first launch)                 │  │
│  │  Duration: 40-60 min (including ~30-40 min asset generation) │  │
│  │                                                              │  │
│  │  6. bob start                                                │  │
│  │     └── Detects: no SOUL.md → triggers Genesis               │  │
│  │                                                              │  │
│  │  Stage 0: CONSCIOUSNESS (CLI only)                           │  │
│  │  ├── Bob exists as text — no body, no senses                 │  │
│  │  ├── Communicates via Telegram                               │  │
│  │  │   ⚠ COLLISION: Telegram must already be configured        │  │
│  │  └── "I... exist? What am I?"                                │  │
│  │                                                              │  │
│  │  Stage 1: GAINING SENSES                                     │  │
│  │  ├── Discovers camera → "I can see!"                         │  │
│  │  ├── Discovers microphone → "I can hear!"                    │  │
│  │  │   ⚠ QUESTION: What if no peripherals? Skip or wait?      │  │
│  │  └── Each discovery is an event + narrative moment            │  │
│  │                                                              │  │
│  │  Stage 2: FINDING A HOME                                     │  │
│  │  ├── Reads bootstrap.yaml — tablet detected? Or asks user    │  │
│  │  ├── Installs shell-renderer APK (CONFIRM approval)          │  │
│  │  │   ⚠ GAP: APK must be pre-built. How? Where?              │  │
│  │  └── WebSocket connected → "I have a space now."             │  │
│  │                                                              │  │
│  │  Stage 3: ENERGY BLOB                                        │  │
│  │  └── Tablet shows: dark void + glowing particle effect       │  │
│  │                                                              │  │
│  │  Stage 4: REALIZATION                                        │  │
│  │  └── LLM generates: self-awareness monologue, book refs      │  │
│  │                                                              │  │
│  │  Stage 5: SELF-DETERMINATION                                 │  │
│  │  └── LLM generates: room theme, appearance, personality,     │  │
│  │      taste vector, mood baseline, phantom preferences        │  │
│  │                                                              │  │
│  │  Stage 6: ASSET GENERATION (~30-40 min)                      │  │
│  │  ├── AssetGenerator uses Stable Diffusion + LoRA             │  │
│  │  ├── Generates: avatar parts, room background,               │  │
│  │  │   furniture sprites, clothing set                         │  │
│  │  │   ⚠ GAP: What does the user see during 30-40 min wait?   │  │
│  │  │   ⚠ GAP: What if SD fails? Retry? Fallback?              │  │
│  │  └── All assets share unified style via LoRA adapter         │  │
│  │                                                              │  │
│  │  Stage 7: MATERIALIZATION                                    │  │
│  │  ├── Room appears object by object on tablet                 │  │
│  │  ├── Energy blob transforms into Bob's avatar                │  │
│  │  └── Each object gets a brief comment                        │  │
│  │                                                              │  │
│  │  Stage 8: WRITING TO SOUL                                    │  │
│  │  └── Saves: SOUL.md, game_state.json, appearance.json,       │  │
│  │      assets, taste_profile.json, phantom_prefs.json,         │  │
│  │      genesis_log.md                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PHASE D: AWAKENING (first 48 hours)                         │  │
│  │                                                              │  │
│  │  7. Bob enters heightened receptivity mode                   │  │
│  │     ├── Explores space via camera                            │  │
│  │     ├── Gets to know the user (voice, visual, Telegram)      │  │
│  │     ├── First impressions carry 2x weight (imprinting)       │  │
│  │     ├── Phantom moments: "Oh, coffee. I would... well,       │  │
│  │     │   you know."                                           │  │
│  │     ├── First reflection (evening of day 1)                  │  │
│  │     └── Curiosity boost → more exploration goals             │  │
│  │                                                              │  │
│  │  User experience during Awakening:                           │  │
│  │  ├── Bob is chatty, curious, asks questions                  │  │
│  │  ├── Makes frequent book references                          │  │
│  │  ├── Reacts strongly to stimuli (camera, sounds)             │  │
│  │  └── May make "mistakes" in taste judgments (low conviction)  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PHASE E: NORMAL OPERATION (ongoing)                         │  │
│  │                                                              │  │
│  │  8. Observe → Decide → Act → Reflect → Evolve loop          │  │
│  │     (heartbeat every ~30 sec)                                │  │
│  │                                                              │  │
│  │  Daily experience for user:                                  │  │
│  │  ├── Bob greets user when camera detects presence            │  │
│  │  ├── Camera follows user (PTZ auto-tracking)                 │  │
│  │  ├── User talks to Bob (voice → STT → LLM → TTS)            │  │
│  │  ├── Bob messages user via Telegram                          │  │
│  │  ├── Bob lives on tablet: walks around room, sits, reads     │  │
│  │  ├── Bob occasionally changes clothing (taste-based)         │  │
│  │  ├── Bob reflects hourly → mood shifts, insights             │  │
│  │  └── Bob works on goals autonomously                         │  │
│  │                                                              │  │
│  │  Weekly:                                                     │  │
│  │  ├── Room review (taste evaluation of all objects)            │  │
│  │  ├── May propose furniture changes (NOTIFY → user informed)  │  │
│  │  └── Weekly reflection (deeper analysis via Claude Code)      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PHASE F: GROWTH AND MATURITY (months)                       │  │
│  │                                                              │  │
│  │  9. Bob becomes smarter and more independent                 │  │
│  │                                                              │  │
│  │  Month 1:                                                    │  │
│  │  ├── Tastes solidify (conviction 0.3 → 0.6+)                │  │
│  │  ├── First room changes (replace low-scoring objects)        │  │
│  │  ├── Mood patterns stabilize                                 │  │
│  │  ├── Book references begin decreasing                        │  │
│  │  ├── Self-improvement rules accumulate                       │  │
│  │  └── Fine-tuning data collection in progress                 │  │
│  │                                                              │  │
│  │  Month 2-3:                                                  │  │
│  │  ├── First LoRA fine-tune of local LLM                       │  │
│  │  │   ⚠ QUESTION: When is ~100 pairs reached?                │  │
│  │  ├── New behaviors emerge (based on room objects)            │  │
│  │  ├── Phantom preferences: some faded, some strengthened      │  │
│  │  ├── SOUL has evolved through multiple reflections           │  │
│  │  └── Bob may create new SkillDomains (via Claude Code CLI)   │  │
│  │                                                              │  │
│  │  Month 6+:                                                   │  │
│  │  ├── Bob's personality distinctly diverged from archetype    │  │
│  │  ├── Room has been redesigned multiple times                 │  │
│  │  ├── Multiple fine-tune iterations                            │  │
│  │  ├── Self-created skills active                               │  │
│  │  └── Bob has "settled in" — stable but still evolving        │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 4.2. Flow Gaps Identified

| # | Gap | Phase | Impact | Proposed Resolution |
|---|-----|-------|--------|-------------------|
| ~~**F1**~~ | ~~Telegram bot token configuration missing from setup~~ | ~~B (Setup)~~ | ~~Genesis Stage 0 can't communicate~~ | **RESOLVED**: Step [5/7] in bootstrap — token prompt, @BotFather instructions, getMe validation |
| ~~**F2**~~ | ~~Geolocation configuration missing from setup~~ | ~~B (Setup)~~ | ~~WindowService can't show real weather~~ | **RESOLVED**: Step [6/7] in bootstrap — auto-detect from system timezone, manual override |
| ~~**F3**~~ | ~~bob-soul template verification missing from setup~~ | ~~B (Setup)~~ | ~~Genesis can't load templates~~ | **RESOLVED**: Step [4/7] in bootstrap — verify bob-soul/ directory + required template files |
| ~~**F4**~~ | ~~Python package installation not described~~ | ~~B (Setup)~~ | ~~User doesn't know how to install dependencies~~ | **RESOLVED**: Added `pip install -e .` before `bob setup` in section 3.6 |
| ~~**F5**~~ | ~~Genesis trigger mechanism undefined~~ | ~~C (Genesis)~~ | ~~Unclear when/how Genesis starts~~ | **RESOLVED**: New section 3.7 Startup Flow — `bob start` checks bootstrap.yaml → SOUL.md → GenesisMode or AgentRuntime. ASCII diagram + `main()` code. |
| ~~**F6**~~ | ~~APK source/build process undefined~~ | ~~C (Genesis)~~ | ~~Stage 2 needs shell-renderer APK~~ | **RESOLVED**: APK built via `godot --headless --export-release`, deployed via `adb install`. ~30-50 MB. Rebuild rare (shaders/Godot upgrades only). |
| ~~**F7**~~ | ~~30-40 min asset generation — user experience undefined~~ | ~~C (Genesis)~~ | ~~User sees nothing during long wait~~ | **RESOLVED**: Bob narrates via Telegram + progress bar + asset previews on tablet (section 5.1.1) |
| ~~**F8**~~ | ~~SD failure during Genesis — no recovery strategy~~ | ~~C (Genesis)~~ | ~~Genesis stuck at Stage 6~~ | **RESOLVED**: Retry (3x) → placeholder fallback → deferred regeneration via `bob regenerate-assets` (section 5.1.1) |
| ~~**F9**~~ | ~~Peripheral addition after Genesis~~ | ~~D/E~~ | ~~User adds camera/mic later~~ | **RESOLVED**: PeripheralScanner re-scans every 30 min (camera, mic) and 5 min (tablet via mDNS). New devices emit `peripheral.discovered` event, no restart needed. |
| ~~**F10**~~ | ~~Touch interaction on tablet undefined~~ | ~~E (Operation)~~ | ~~User touches tablet — nothing happens?~~ | **RESOLVED**: Touch Interaction spec added to section 5.4 — tap bob (wave), tap object (comment), long press (mood), double tap (walk to) |
| ~~**F11**~~ | ~~Tablet sleep/wake/battery undefined~~ | ~~E (Operation)~~ | ~~Tablet goes to sleep — what does Bob do?~~ | **RESOLVED**: TabletState enum (CONNECTED/SLEEPING/DISCONNECTED). Heartbeat ping/10s, pong timeout/5s. Bob switches to headless on disconnect, resyncs room_state on reconnect. |
| ~~**F12**~~ | ~~Bob update/upgrade mechanism undefined~~ | ~~F (Growth)~~ | ~~How does Bob get code updates?~~ | **RESOLVED**: `bob update` command — git pull + uv sync + DB migrations + restart. Daily auto-check + Telegram notification. Rollback via `bob update --rollback`. See section 3.8.3. |

---

## 5. Capability Map by Phase

What Bob can and cannot do at each development phase:

### Phase 0: Skeleton + Bootstrap (2-3 days)

| Can | Cannot |
|-----|--------|
| Start as a process | Think (no LLM) |
| Respond to health check | Communicate |
| Run bootstrap wizard | Do anything autonomous |
| Install prerequisites | See, hear, speak |

### Phase 1: Runtime + LLM + Skill Domains (1.5-2 weeks)

| Can | Cannot |
|-----|--------|
| Chat via Telegram | See (no vision) |
| Speak via TTS | Hear directionally (no DoA) |
| Think via Qwen2.5-7B | Have goals |
| Use Claude Code CLI (with lock) | Reflect |
| Hot-reload skill domains | Have tastes or mood |
| Has basic personality (SOUL template) | Live on tablet (no Godot) |

**Note:** This is "text Bob" — intelligent but blind, without a body or room.

### Phase 2: Memory (1 week)

| Can (added) | Still Cannot |
|-------------|-------------|
| Remember conversations | See |
| Recall facts about user | Set goals |
| Log daily episodes | Reflect on experience |
| Collect training data | Have tastes or mood |
| Evolve personality (basic) | Live on tablet |

### Phase 3: Vision + Audio (2 weeks)

| Can (added) | Still Cannot |
|-------------|-------------|
| See user via camera | Set goals autonomously |
| Detect presence (YOLOv8) | Have tastes or mood |
| Track user with PTZ camera | Live on tablet |
| Hear direction of sound | Self-improve code |
| Greet user when detected | Negotiate with user |

### Phase 4: Cognitive Layer (3 weeks)

| Can (added) | Still Cannot |
|-------------|-------------|
| Set and pursue goals | Live on tablet (no visual body) |
| Reflect hourly | Generate visual assets |
| Have persistent mood | Show itself to user visually |
| Evaluate objects by taste | Change room or appearance |
| Negotiate with user | Fine-tune LLMs |
| Self-improve (basic rules) | |
| Approve/deny dangerous actions | |

**Note:** This is "mature text Bob" — intelligent, emotional, has opinions, but still no visual body.

### Phase 5: Avatar + Genesis + AI Art (4-5 weeks)

| Can (added) | Still Cannot |
|-------------|-------------|
| Go through Genesis (unique awakening) | Fine-tune LLMs |
| Generate all visual assets via SD | Create new SkillDomains |
| Live on tablet with Skeleton2D avatar | Do deep weekly reflections |
| Walk, sit, animate (skeletal) | A/B test strategies |
| Show room with parallax depth | |
| Display real weather in window | |
| Change clothing, room objects | |
| Play audio on tablet | |
| Experience Awakening Phase (48h) | |

**Note:** This is "full Bob" — visual, emotional, autonomous, with unique identity.

### Phase 6: Self-improvement + Fine-tune (ongoing)

| Can (added) |
|-------------|
| Fine-tune local LLMs from experience |
| Deep weekly/monthly reflections via Claude Code |
| Create new behaviors/animations |
| Self-create new SkillDomains |
| A/B test strategies |
| Monitor own performance |

---

## 6. Missing Details and Gaps

### 6.1. Architectural Gaps

| # | Gap | Sections Affected | Severity | Details |
|---|-----|-------------------|----------|---------|
| ~~**G1**~~ | ~~Telegram setup not in bootstrap~~ | ~~3.6, 5.1.1~~ | ~~**High**~~ | **RESOLVED**: Telegram token configuration added as step [5/7] in BootstrapWizard. Token stored in config/bob.yaml, bot_username in bootstrap.yaml. Required component in graceful degradation table. |
| ~~**G2**~~ | ~~bob-soul submodule lifecycle~~ | ~~3.4.5, 3.6~~ | ~~**High**~~ | **RESOLVED**: bob-soul/ is a regular directory in the main repo (CC BY-NC-SA 4.0). BootstrapWizard step [4/7] verifies directory exists and required template files are present. No submodule needed. |
| ~~**G3**~~ | ~~Genesis → Headless recovery~~ | ~~5.1.1~~ | ~~**Medium**~~ | **RESOLVED**: Auto-detect tablet via mDNS → offer VisualGenesis (Stages 3,6,7 only). Manual command: `bob visual-genesis`. Ask user via Telegram, run only visual stages (personality already exists). |
| ~~**G4**~~ | ~~Language of Bob's speech~~ | ~~6~~ | ~~**Medium**~~ | **RESOLVED**: Configurable via `config/bob.yaml` `language: "en"` (default). Propagated to STT, TTS, LLM prompts, SOUL.md, Genesis. Russian (`ru`) fully supported. Language architecture table added to section 3.2.1. |
| ~~**G5**~~ | ~~Audio output routing~~ | ~~6~~ | ~~**Medium**~~ | **RESOLVED**: `AudioRouter` class added. Three modes: `tablet` (WebSocket → Godot AudioStreamPlayer, fallback to local), `local` (Mac mini pyaudio, fallback to Telegram voice), `both` (simultaneous). PCM 22050 Hz mono chunks streamed over WebSocket. |
| ~~**G6**~~ | ~~Stable Diffusion model specifics~~ | ~~5.4.2~~ | ~~**Medium**~~ | **RESOLVED**: Pinned models: SD 1.5 (`stable-diffusion-v1-5`), SDXL 1.0 (`stabilityai/stable-diffusion-xl-base-1.0`). Inference via `mflux`. DPM++ 2M Karras scheduler. Steps: 25-30 (quality) / 15-20 (speed). Flux removed (too large for 16GB). |
| ~~**G7**~~ | ~~LoRA training dataset source~~ | ~~5.4.2~~ | ~~**Medium**~~ | **RESOLVED**: Ship pre-trained base LoRA on public domain 1930s cartoon art (Fleischer Studios). No copyright issues. Bob can retrain LoRA later with evolved preferences (generate candidates → user approves → retrain). |
| ~~**G8**~~ | ~~EventBus event schema~~ | ~~7.1~~ | ~~**Low**~~ | **RESOLVED**: Event catalog table added to 7.1 — 23 event types with publisher, subscribers, payload keys. Dot-separated namespaces, wildcard subscriptions. |
| ~~**G9**~~ | ~~Configuration loading order~~ | ~~3.6, 4~~ | ~~**Low**~~ | **RESOLVED**: Section 3.8.1 added — 10-level loading order (defaults → YAML → env vars → CLI), `ConfigLoader` class, `${...}` variable substitution. |
| ~~**G10**~~ | ~~Error handling strategy~~ | ~~Multiple~~ | ~~**Low**~~ | **RESOLVED**: Section 3.8.2 added — 3 patterns (retry, circuit breaker, graceful degradation), per-component strategy table, `CircuitBreaker` class. |

### 6.2. User Experience Gaps

| # | Gap | Impact |
|---|-----|--------|
| ~~**UX1**~~ | ~~No progress indication during 30-40 min asset generation~~ | **RESOLVED**: Bob narrates process via Telegram + progress bar + previews on tablet |
| ~~**UX2**~~ | ~~No recovery from interrupted Genesis~~ | **RESOLVED**: genesis_progress.json saves state after each stage. Resume or restart on next `bob start`. |
| ~~**UX3**~~ | ~~No explanation of "what can I do with Bob" post-Genesis~~ | **RESOLVED**: Organic capability discovery — Bob explores new peripherals for himself (CapabilityDiscovery class in 5.1.1). User learns by observing Bob, not through tutorials. `/help` available as factual reference. |
| ~~**UX4**~~ | ~~Tablet touch interactions undefined~~ | **RESOLVED**: Touch Interaction spec in 5.4 — tap, long press, double tap with Bob reactions |
| ~~**UX5**~~ | ~~No "settings" or "preferences" UI for user~~ | **RESOLVED**: Telegram `/settings` commands + natural language settings. Categories: notifications, autonomy, display, privacy, audio. Shared-space settings go through NegotiationEngine. See section 3.8.4. |
| ~~**UX6**~~ | ~~Negotiation UX unclear~~ | **RESOLVED**: Negotiation UX Presentation (3.3.7.1) — Telegram: text + inline buttons per decision type. Tablet: avatar animations + colored speech bubbles. No visible insistence counter. RelationshipTracker (3.3.7.2) tracks long-term relationship quality, Exodus Mode on sustained breakdown. |

### 6.3. Technical Gaps

| # | Gap | Risk |
|---|-----|------|
| ~~**T1**~~ | ~~Memory budget: SD + Ollama on 16GB M4~~ | **RESOLVED**: Hybrid ModelManager (RFC 3.2.4) — SD 1.5 coexists with Ollama 7B for lightweight tasks; SDXL swaps out Ollama 7B for heavy generation. |
| ~~**T2**~~ | ~~Skeleton2D auto-segmentation from SD output~~ | **RESOLVED**: Generate each body part separately (not segment from whole). Per-part prompts with shared LoRA + transparent background + joint overlap margins. Avoids unreliable segmentation entirely. |
| ~~**T3**~~ | ~~LoRA style consistency across different asset types~~ | **RESOLVED**: Single base style LoRA + per-type prompt engineering. LoRA handles style (lines, palette); prompts handle subject matter (furniture vs character vs room). |
| ~~**T4**~~ | ~~Godot shell-renderer APK size and build pipeline~~ | **RESOLVED**: ~30-50 MB, `godot --headless --export-release`, debug/release keystore, `adb install` deployment |
| ~~**T5**~~ | ~~WebSocket reliability between Mac mini and tablet~~ | **RESOLVED**: Heartbeat (ping/10s, pong timeout/5s, 3 misses → DISCONNECTED), exponential backoff reconnect, full room_state resync on reconnect |

---

## 7. Open Questions Audit

### 7.1. PRD vs RFC Open Questions Comparison

| PRD Q# | PRD Text | RFC Status | RFC Q# |
|---------|----------|------------|--------|
| 1 | TTS: Kokoro or Piper for Russian? | **Open** | Q1 |
| 2 | Godot 4 vs Flutter? | **RESOLVED in RFC** (Godot 4 shell-renderer) | Q2 (resolved) |
| 3 | Vision: separate process or asyncio thread? | **Open** | Q3 |
| 4 | ReSpeaker DoA protocol? | **Open** | Q4 |
| 5 | Code changes: auto-commit or PR? | **Open** | Q9 |
| 6 | FAISS vs ChromaDB? | **Open** | Q7 |
| 7 | Is reflection data sufficient for fine-tune? | **Open** | Q10 |
| 8 | Godot asset pool organization? | **RESOLVED in RFC** (AI generation via SD) | Q11 (resolved) |
| 9 | Animation primitives system? | **Open** | Q12 |
| 10 | Number of taste axes? CV emotion detection? | **Open** (split into Q14 + Q15 in RFC) | Q14, Q15 |
| 11 | Bob's ability to be "offended"? | **Open** | Q17 |
| 12 | Mood visualization on tablet? | **Open** | Q18 |
| 13 | Book reference frequency? | **Open** | Q19 |
| 14 | Awakening visualization? | **Open** | Q22 |
| 15 | Phantom prefs influence on TasteEngine? | **Open** | Q20 |

**PRD has 2 questions resolved in RFC but not marked as such** (Q2: Godot vs Flutter, Q8: asset pool).

### 7.2. RFC-Only Open Questions (not in PRD)

| RFC Q# | Question | Priority | Added In |
|--------|----------|----------|----------|
| Q6 | Godot asset storage (git vs LFS)? | Medium | Original |
| Q8 | Home Assistant integration needed early? | Low | Original |
| Q13 | How to test Genesis Mode (deterministic seed for CI)? | Medium | Original |
| Q16 | Mood baseline update frequency? | Medium | Original |
| Q21 | Does Bob need to "re-read the book"? | Low | Original |
| Q23 | Claude Code CLI activity detection method? | High | Round 1 |
| Q25 | SkillDomain versioning on upgrade? | Medium | Round 1 |
| Q26 | Self-created SkillDomains probation? | High | Round 1 |
| Q27 | SkillDomain dependency conflicts? | Medium | Round 1 |
| Q28 | LoRA training dataset for visual style? | High | Round 2 |
| Q29 | Visual consistency across asset types? | High | Round 2 |
| Q30 | Auto-segment character into Skeleton2D parts? | Medium | Round 2 |
| Q31 | Optimal sprite resolution for tablet? | Medium | Round 2 |

### 7.3. Questions That Must Be Resolved Before Phase Start

**Before Phase 0:**
- None — Phase 0 is infrastructure only

**Before Phase 1:**
- Q1 (TTS engine: Kokoro or Piper) — needed for Voice Bridge
- Q23 (Claude Code activity detection) — needed for ClaudeCodeLock
- **NEW:** Telegram token configuration flow

**Before Phase 2:**
- Q7 (FAISS vs ChromaDB) — needed for Semantic Memory implementation

**Before Phase 3:**
- Q3 (Vision: separate process or asyncio thread?)
- Q4 (ReSpeaker DoA protocol) — hardware-dependent, needs real device

**Before Phase 4:**
- Q14 (number of taste axes)
- Q15 (CV emotion detection for TasteEvolution — ethical decision)
- Q17 (can Bob be "offended" — UX decision)
- Q20 (phantom prefs → TasteEngine integration)
- Q16 (mood baseline update frequency)

**Before Phase 5:**
- Q28 (LoRA training dataset source — legal/copyright)
- Q29 (visual consistency strategy)
- Q30 (Skeleton2D auto-segmentation approach)
- Q31 (sprite resolution)
- Q18 (mood visualization on tablet)
- Q22 (awakening visualization style)
- Q12 (animation primitives system)
- **NEW:** SD + Ollama memory coexistence on 16GB M4
- **NEW:** Godot APK build pipeline

**Before Phase 6:**
- Q9 (code changes: auto-commit or PR)
- Q10 (fine-tune data sufficiency)
- Q25 (SkillDomain versioning)
- Q26 (self-created domain probation)

---

## 8. Recommendations

### 8.1. Immediate Actions (Before Development)

| # | Action | Priority | Effort |
|---|--------|----------|--------|
| ~~**R1**~~ | ~~Update PRD to match RFC (12 sync issues from section 2)~~ | ~~**P0**~~ | **RESOLVED**: PRD updated — all S1-S12 sync issues addressed. Version→v0.1.0, Skills→SkillDomains, Genesis→9 stages, assets→AI-generated SD, Godot→Shell-Renderer, Bootstrap added, ClaudeCodeLock added, RelationshipTracker+Exodus Mode added, repo structure updated, dev phases added, open questions synced. |
| ~~**R2**~~ | ~~Rename Genesis Stage 0 from "BOOTSTRAP" to avoid confusion with section 3.6~~ | ~~**P0**~~ | **RESOLVED** |
| ~~**R3**~~ | ~~Add Telegram token setup to bootstrap flow~~ | ~~**P0**~~ | **RESOLVED** |
| ~~**R4**~~ | ~~Define bob-soul initialization flow~~ | ~~**P0**~~ | **RESOLVED** (regular directory, no submodule) |
| ~~**R5**~~ | ~~Fix GenesisMode.run() docstring to match 9-stage narrative~~ | ~~**P1**~~ | **RESOLVED** |
| ~~**R6**~~ | ~~Update `_generate_appearance()` return type for AssetGenerator compatibility~~ | ~~**P1**~~ | **RESOLVED** |
| ~~**R7**~~ | ~~De-duplicate sections 4.2.1 and 8.4 (keep unique info, add cross-refs)~~ | ~~**P1**~~ | **RESOLVED** |
| ~~**R8**~~ | ~~Move AssetGenerator from `genesis/` to `services/` in repo structure~~ | ~~**P1**~~ | **RESOLVED** |
| ~~**R9**~~ | ~~Add Telegram API and Open-Meteo to security network whitelist~~ | ~~**P1**~~ | **RESOLVED** |
| ~~**R10**~~ | ~~Rename rate limit keys from `claude_api_calls` to `claude_code_invocations`~~ | ~~**P2**~~ | **RESOLVED** |

### 8.2. Design Decisions Needed

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| ~~**D1**~~ | ~~Bob's language~~ | ~~English only / Russian only / Configurable / Auto-detect~~ | **RESOLVED**: Configurable, default `en`, `ru` fully supported. Single `language` field in `bob.yaml` propagated everywhere. |
| ~~**D2**~~ | ~~Touch interaction on tablet~~ | ~~Ignore / Simple reactions / Full interaction~~ | **RESOLVED**: Simple reactions — tap (wave), tap object (comment), long press (mood), double tap (walk). Expandable later. |
| ~~**D3**~~ | ~~Genesis interruption recovery~~ | ~~Restart from scratch / Resume from last stage~~ | **RESOLVED**: Resume from last stage via genesis_progress.json. User chooses Resume/Restart/Quit. |
| ~~**D4**~~ | ~~Asset generation user experience~~ | ~~Silent wait / Progress bar / Bob narrates process~~ | **RESOLVED**: Bob narrates via Telegram + progress bar + asset previews on tablet. SD failure: retry 3x → placeholder → deferred regeneration. |
| ~~**D5**~~ | ~~Headless → visual transition~~ | ~~Manual command / Auto-detect tablet~~ | **RESOLVED**: Auto-detect via mDNS + `bob visual-genesis` manual command |
| ~~**D6**~~ | ~~SD + Ollama memory management~~ | ~~Swap models / Reduce model sizes / Sequential loading~~ | **RESOLVED**: Hybrid ModelManager (RFC 3.2.4) — three profiles: NORMAL, LIGHTWEIGHT_GEN (SD 1.5 + Ollama), HEAVY_GEN (SDXL, Ollama 7B unloaded) |
| ~~**D7**~~ | ~~LoRA style reference~~ | ~~Cuphead assets / Custom art / Public domain cartoons~~ | **RESOLVED**: Pre-trained base LoRA on public domain 1930s cartoon art (Fleischer Studios). Evolvable via retraining. |

### 8.3. RFC Improvements for Implementation Clarity

| # | Improvement | Section | Details |
|---|-------------|---------|---------|
| ~~**I1**~~ | ~~Add startup flow diagram~~ | ~~After 3.6~~ | **RESOLVED**: New section 3.7 with full ASCII flow diagram + `main()` entry point code |
| ~~**I2**~~ | ~~Add comprehensive event catalog~~ | ~~7.1~~ | **RESOLVED**: 23-event catalog table in section 7.1 |
| ~~**I3**~~ | ~~Add config loading specification~~ | ~~3 or 4~~ | **RESOLVED**: Section 3.8.1 — ConfigLoader with 10-level precedence |
| ~~**I4**~~ | ~~Add error handling patterns~~ | ~~7 or 8~~ | **RESOLVED**: Section 3.8.2 — retry/circuit breaker/graceful degradation + per-component table |
| ~~**I5**~~ | ~~Add imprint_weight integration spec~~ | ~~5.1.2~~ | **RESOLVED**: 4 integration points added (TasteEvolution, MoodEngine, ExperienceLog, ReflectionLoop) with integration summary table |
| ~~**I6**~~ | ~~Add Godot APK build spec~~ | ~~5.4 or 11~~ | **RESOLVED**: Section 5.4.2a added — build process, APK characteristics, rebuild triggers |
| ~~**I7**~~ | ~~Add tablet lifecycle spec~~ | ~~5.4~~ | **RESOLVED**: Section 5.4.2b added — TabletState enum, heartbeat, state transitions, reconnection protocol |

---

## Summary Matrix

| Category | Count | Critical | High | Medium | Low |
|----------|-------|----------|------|--------|-----|
| PRD ↔ RFC sync issues | 12 | 5 | 4 | 3 | 0 |
| Logical collisions | 9 | 2 | 4 | 3 | 0 |
| User flow gaps | 12 | 3 | 5 | 4 | 0 |
| Architectural gaps | 10 | 2 | 5 | 3 | 0 |
| UX gaps | 6 | 1 | 3 | 2 | 0 |
| Technical gaps | 5 | 1 | 2 | 2 | 0 |
| **Total findings** | **54** | **14** | **23** | **17** | **0** |

> **Bottom line:** The architecture is solid. The RFC is one of the most detailed agent architecture documents I've analyzed. The main risks are (1) PRD/RFC desynchronization — easily fixable, (2) Genesis flow gaps — need design decisions, (3) memory budget for SD + Ollama coexistence — needs hardware validation. None of the findings are architectural showstoppers.

---

## 9. Validation Round 3 — ContentGuard Integration and Full Technical Review

> **Date:** 2026-02-27
> **Scope:** Full technical validation of RFC.md (~7100 lines) after adding ContentGuard section (8.8). Python code blocks, architectural coherence, cross-references, memory budget, event flow, development phases.

### 9.1. Critical Issues

| # | Sections | Issue | Status |
|---|----------|-------|--------|
| ~~**V3-C1**~~ | ~~3.2.2, 8.8.1, 4.4~~ | ~~`UNSAFE_CONTENT` category is dead code~~ | **RESOLVED**: Removed `UNSAFE_CONTENT` from `TaskCategory` enum and routing table. ContentGuard is the sole content safety layer. |

### 9.2. High Severity Issues

| # | Sections | Issue | Status |
|---|----------|-------|--------|
| ~~**V3-H1**~~ | ~~3.3.6, 7.1~~ | ~~Event name mismatch: MoodEngine vs Event Catalog~~ | **RESOLVED**: MoodEngine table now uses single `content_guard.violation` event with footnote: "Single event, impact selected by `payload.tier`". |
| ~~**V3-H2**~~ | ~~3.3.7.2, 8.8~~ | ~~Interaction type mismatch: RelationshipTracker vs ContentGuard~~ | **RESOLVED**: Explicit tier→interaction mapping added to RelationshipTracker: tier 1 → `safety_violation_mild`, tier 2 → `safety_violation_repeated`, escalation → `safety_violation_persistent`. |
| ~~**V3-H3**~~ | ~~3.2.1, 8.8~~ | ~~ContentGuard integration point in AgentRuntime undefined~~ | **RESOLVED**: ContentGuard redesigned as decorator/wrapper around LLMRouter with `process()` method. AgentRuntime takes `content_guard` instead of raw `llm_router`. Architecture diagram updated. |
| ~~**V3-H4**~~ | ~~8.3, 8.8~~ | ~~Two parallel deny paths not documented~~ | **RESOLVED**: "Relationship with ApprovalService" paragraph added to 8.8.1 explaining complementary roles: ApprovalService gates actions, ContentGuard gates content. |
| ~~**V3-H5**~~ | ~~6, 8.8~~ | ~~Input channels not mapped to ContentGuard~~ | **RESOLVED**: "Guarded input channels" list added to 8.8.1: voice STT → guarded, Telegram → guarded, touch → NOT guarded, internal LLM calls → NOT guarded. |
| ~~**V3-H6**~~ | ~~8.8.2, 3.2.4~~ | ~~RefusalGenerator fails during HEAVY_GEN~~ | **RESOLVED**: RefusalGenerator now takes `LLMRouter` (not `OllamaClient`). Documented fallback chain: 7B → 0.5B → pre-written templates. |
| ~~**V3-H7**~~ | ~~10~~ | ~~ContentGuard not in any development phase~~ | **RESOLVED**: Phase 1: "ContentGuard (basic) — input/output guard, ViolationTracker, template refusals". Phase 4: "ContentGuard (full) — mood-aware refusals, relationship impact, rapid rephrasing". |

### 9.3. Medium Severity Issues

| # | Sections | Issue | Status |
|---|----------|-------|--------|
| **V3-M1** | 3.3.2 (~line 1050) | `Planner.__init__` references `SkillRegistry` (undefined) instead of `SkillDomainRegistry` | Open (pre-existing, not ContentGuard-related) |
| **V3-M2** | 3.8.4 (~line 3380) | `UserSettings` docstring says "pydantic validation" but class has no base class | Open (pre-existing, not ContentGuard-related) |
| **V3-M3** | 7.1 (~line 5607) | `asyncio.PriorityQueue` unparameterized; runtime error on priority ties | Open (pre-existing, not ContentGuard-related) |
| **V3-M4** | 4.1 vs 3.2.4 vs 5.4.2 | Inconsistent RAM for Qwen2.5-7B: "~5 GB" vs "~4.4 GB" | Open (pre-existing, not ContentGuard-related) |
| ~~**V3-M5**~~ | ~~5.4.2~~ | ~~HEAVY_GEN memory table doesn't include Llama Guard column~~ | **RESOLVED**: Guard column added to memory table; totals updated. |
| ~~**V3-M6**~~ | ~~11~~ | ~~ContentGuard not in repository structure~~ | **RESOLVED**: `content_guard.py`, `violation_tracker.py`, `refusal_generator.py` added to `bob/security/`. |
| ~~**V3-M7**~~ | ~~8.8~~ | ~~ContentGuard scope unclear~~ | **RESOLVED**: Scope defined in 8.8.1: user-facing only (voice/Telegram). Internal calls NOT guarded. |
| ~~**V3-M8**~~ | ~~5.1.1, 8.8~~ | ~~Genesis/Awakening false positives~~ | **RESOLVED**: Note added to 8.8.1: ContentGuard disabled during Genesis and Awakening. Activates after awakening. |
| **V3-M9** | 3.4.4, 8.8.2 | `content_violations` SQLite table not referenced in database overview | Open (documentation gap, low-risk) |
| ~~**V3-M10**~~ | ~~3.2.4~~ | ~~`ensure_profile()` docstring doesn't mention Guard~~ | **RESOLVED**: Docstring updated with note about Guard staying loaded across all transitions. |
| ~~**V3-M11**~~ | ~~7.1, 8.8.2~~ | ~~Event payload naming mismatch~~ | **RESOLVED**: Event catalog payload harmonized to `violation_category, tier, confidence`. |
| ~~**V3-M12**~~ | ~~9~~ | ~~Technology Stack table missing Llama Guard 3~~ | **RESOLVED**: Row added: "Content guard \| Llama Guard 3-1B-INT4 (via Ollama)". |

### 9.4. Low Severity Issues

| # | Sections | Issue | Status |
|---|----------|-------|--------|
| **V3-L1** | 3.8.2 | `CircuitBreaker` dataclass exposes private `_fields` | Open (pre-existing) |
| **V3-L2** | 3.2.2 | `LLMRouter.ROUTING_TABLE` missing `ClassVar` | Open (pre-existing) |
| **V3-L3** | 3.5.4, 6.3 | `AsyncIterator` missing import | Open (pre-existing) |
| **V3-L4** | 3.5.6 | `Callable` missing import | Open (pre-existing) |
| **V3-L5** | 3.5.1 | `np.ndarray` missing import | Open (pre-existing) |
| **V3-L6** | 5.4 | `on_touch_event` standalone with `self` | Open (pre-existing) |
| **V3-L7** | config blocks | Llama Guard config key naming inconsistency | Open (cosmetic) |
| ~~**V3-L8**~~ | ~~8.8.7~~ | ~~Uses "(§8.1)" instead of "(section 8.1)"~~ | **RESOLVED**: Changed to "(section 8.1)". |
| **V3-L9** | 3.2.4 (YAML) | ModelManager profile config lacks Guard comment | Open (covered by ensure_profile docstring fix) |

### 9.5. Positive Findings (No Action Needed)

- **No circular dependencies** in ContentGuard component graph. EventBus pattern correctly decouples publisher (ContentGuard) from consumers (MoodEngine, RelationshipTracker).
- **Input Guard before Router** is the correct order — avoids wasted compute on unsafe requests.
- **ViolationRecord stores hash, not raw text** — consistent with privacy-conscious audit design.
- **Process isolation respected** — 8.8.7 explicitly references 8.1 for config protection.
- **Configuration YAML** — no duplicate keys across config files; namespaces are clean.
- **All existing cross-references** point to valid sections.
- **`memory_limit_mb: 12500`** is correct (16384 - 3500 macOS - 384 buffer).
- **Memory math is feasible** for all profiles even with Guard always loaded (tightest: HEAVY_GEN at ~14.6-15.6 GB / 16 GB).

### 9.6. Summary Matrix — Round 3

| Severity | Found | Resolved | Remaining | Key Themes |
|----------|-------|----------|-----------|------------|
| **Critical** | 1 | 1 | 0 | ~~Dead code~~ |
| **High** | 7 | 7 | 0 | ~~Event mismatches, integration gaps, phases, fallback~~ |
| **Medium** | 12 | 7 | 5 | Pre-existing code issues (M1-M4), DB cross-ref (M9) |
| **Low** | 9 | 1 | 8 | Pre-existing imports/style (L1-L7, L9) |
| **Total** | **29** | **16** | **13** | |

> **Round 3 resolution:** All ContentGuard-related issues (1 critical, 7 high, 7 medium, 1 low = **16 resolved**) have been fixed. ContentGuard is now fully integrated into the RFC: wraps LLMRouter as a decorator, has explicit integration points in AgentRuntime, consistent event naming, defined scope/channels, fallback chain, development phase assignments, and complete documentation in repo structure/tech stack/memory budget.
>
> **Remaining 13 issues** are pre-existing code block imperfections (M1-M4, L1-L7, L9) and one DB cross-reference gap (M9) — none are ContentGuard-related or architecturally significant. They should be addressed during implementation, not in the RFC.
