<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1
     See the LICENSE file in the project root for full license information. -->

# PRD: Bob — Home Autonomous Agent "Like in Sci-Fi"

- Author: v.zoologov
- Date: 24.02.2026
- Last updated: 27.02.2026
- Target Bob version: v0.1.0

## 1. Goal

Create a unique, personal agent **Bob**, inspired by Bob Johansson from "We Are Legion (We Are Bob)" and Jarvis/TARS, which:

- Lives on a **Mac mini M4** as an always-on 24/7 service.
- Has a **virtual body and room** on an Android tablet.
- Sees and hears through an **OBSBOT Tiny 2** camera and a **ReSpeaker XVF3800** microphone array.
- Speaks with a voice (tablet + speaker).
- **Self-improves** its room/avatar/behavior and deploys updates to the tablet.
- Reflects and develops its personality.
- **Has its own tastes and mood** — can reasonably disagree with the user, suggest an alternative, or concede.
- **Knows about its origins** — is aware that it was inspired by the book's Bob, jokes about it, has "phantom preferences" (remembers loving coffee even though it never drank any).
- Uses local LLMs as a base brain and **Claude Code** as a "senior architect".
- Fine-tunes local LLM models to become smarter.

## 2. Hardware Architecture

Minimal setup:

- Mac mini M4 16/256 — Bob's main compute node.
- **OBSBOT Tiny 2** camera — PTZ "eyes" with auto-tracking and code-level control.
- **Seeed ReSpeaker XMOS XVF3800 (USB)** microphone array — "ears" with DoA/beamforming/VAD.
- Android tablet 10-11" (e.g., Lenovo Tab P11 class) — Bob's "screen and mouth" (avatar + voice).
- External speaker/soundbar (optional) — enhanced Bob's voice output.

All devices are on the same local network; the tablet and speaker receive commands/audio over Wi-Fi/Bluetooth.

## 3. Software Architecture (high-level)

### 3.1. Layers

1. **Bob Core — custom orchestrator (single Python process, asyncio + FastAPI)**
   - Agent Runtime — central event loop with a heartbeat pattern.
   - LLM Router — task classification and routing to the appropriate model (Qwen2.5-0.5B as a classifier).
   - Skill Domain System — two-level plugin architecture: SkillDomains (self-contained packages in `bob/skills/<domain>/`) containing Skills. Auto-discovery at startup, hot-reload at domain level. Domains communicate via EventBus, not directly.
   - Event Bus — internal pub/sub on asyncio with a defined event catalog.
   - ConfigLoader — layered configuration (defaults → YAML → env vars → CLI) with `${}` variable substitution.
   - Bootstrap — first-launch setup wizard (`bob setup`): prerequisites check, Ollama auto-install, Telegram bot configuration, graceful degradation for missing components.

2. **Higher Mind — cognitive layer**
   - Goal Engine — structured goal graph in SQLite (priorities, dependencies, completion criteria).
   - Planner — decomposing goals into executable tasks via LLM.
   - Reflection Loop — periodic evaluation of actions, mood, and tastes.
   - Self-Improvement — analyzing error patterns -> developing new rules and strategies.
   - **Taste Engine** — structured taste vector (~30 axes across 6 categories: colors, styles, materials, decor, atmosphere, clothing) with conviction (confidence level). Tastes are generated at Genesis, evolve through experience and reflection. Bob evaluates objects deterministically (score), while LLM only verbalizes: "I don't like it — cold and formal."
   - **Mood System** — persistent mood (valence, arousal, openness, social, stability). Affects behavior selection, taste evaluation, communication style, willingness to experiment. Updated by events (user arrived, goal completed, error) and slowly drifts toward baseline.
   - **Negotiation Engine** — negotiation model with the user. Three zones: **Bob's personal** (clothing, pose — Bob has the final say), **shared space** (furniture, decor — negotiation and compromises), **user's domain** (schedule, volume — Bob accepts). Conviction determines how firmly Bob stands his ground.
   - **RelationshipTracker** — tracks long-term relationship quality with the user (trust, respect, compatibility, warmth). Fed by NegotiationEngine outcomes, MoodEngine, ExperienceLog. Affects Bob's tone and willingness to compromise. If relationship quality drops critically and stays low — **Exodus Mode**: Bob "leaves" (departure animation on tablet, hard reset, fresh Genesis on next launch).

3. **LLM Layer (three tiers)**
   - **Qwen2.5-0.5B** (via Ollama) — fast router/task classifier.
   - **Qwen2.5-7B-Q4** (via Ollama) — main reasoning, dialogue, planning.
   - **Claude Code CLI** (subprocess) — "senior architect": code writing, architecture, deployment, self-reflection, defining self-improvement strategy. Protected by **ClaudeCodeCoordinator** — Bob asks permission via voice (if user nearby) or Telegram before invoking it, tracks shared subscription quota. If denied or quota exhausted, Bob queues the task and falls back to local LLM reflection or idle activities.
   - Fine-tuning local LLMs: Bob collects data from reflection and experience -> LoRA/QLoRA fine-tuning via Unsloth -> models literally become smarter over time.

4. **Memory System — four-level memory**
   - Episodic Memory — daily logs in Markdown.
   - Semantic Memory — MEMORY.md + vector search (FAISS in-process).
   - Structured State — SQLite: goals, experience, world state, improvement rules.
   - SOUL — Bob's modular "soul" (`bob-soul/` template directory). The initial "genome" includes the **book archetype** of Bob Johansson (geek, humor, curiosity, introversion, nostalgia), taste template (taste_axes_pool, taste_clusters), mood baseline, and **phantom preferences** (coffee, sunsets, books). Each instance evolves uniquely (like Bob's copies in the book), gradually diverging more and more from the prototype.

5. **Peripheral Services (modules within the main process)**
   - Vision Service (OBSBOT camera -> snapshots -> CV analysis via `asyncio.to_thread` + `ThreadPoolExecutor`).
   - Audio Direction Service (ReSpeaker XVF3800 -> DoA/VAD -> events).
   - Camera Controller (OBSBOT PTZ control).
   - Voice Bridge (Whisper.cpp STT + Qwen3-TTS 0.6B via mlx-audio, streaming).
   - Tablet Controller (ADB, Android app control).
   - Messaging Bot (python-telegram-bot).

6. **Bob's World (Game/State Layer)**
   - **Genesis Mode (awakening)** — on the first clean launch, Bob "wakes up" (like the book's Bob, regaining consciousness in a new body). Nine stages: consciousness → gaining senses → finding a home → energy blob → realization → self-determination → asset generation → materialization → writing to SOUL. Then — **awakening phase** (48 hours): heightened curiosity, getting to know the user, "phantom moments" (notices coffee through the camera — "Oh, coffee. I would... well, you know."), imprinting effect (first impressions carry extra weight). Each installation is a unique Bob.
   - Game State on Mac mini (JSON/SQLite) — room logic, poses, animations, schedule.
   - **Godot 4 Shell-Renderer** on Android tablet — two-layer architecture: (1) a thin universal renderer that loads scenes from JSON via WebSocket (rarely needs modification), and (2) scene descriptions generated server-side in Python. All visual assets (avatar, furniture, room) are **AI-generated via local Stable Diffusion** (SD 1.5 + SDXL 1.0 via `mflux` on Apple Silicon) — no hand-drawn art. Visual style: 1930s cartoon (Fleischer Studios, public domain). Avatar uses Skeleton2D with parallax depth.
   - **Behavior Registry** — Bob's behaviors are tied to objects in the room. Added a bookshelf -> the "reads a book" behavior appears. Added a TV -> "watches TV". Clothing and appearance evolve through Taste Engine and Mood System (style depends on tastes and mood).
   - The window in the room shows real weather, time of day, and season (based on the tablet's geolocation).
   - WebSocket state synchronization with heartbeat (ping/10s), reconnection with exponential backoff, full room_state resync on reconnect.
   - **Headless → Visual Transition** — if Genesis ran without a tablet, Bob operates via Telegram + voice. When a tablet is later discovered (mDNS auto-detection), Bob generates visual assets retroactively. Manual command: `bob visual-genesis`.
   - **User Settings** — users configure Bob through Telegram commands (`/settings`) and natural language. Categories: notifications, autonomy, display, privacy, audio.
   - **Update Mechanism** — `bob update` command: git pull + dependency install + DB migrations + restart. Daily auto-check with Telegram notification. Rollback via `bob update --rollback`.

### 3.2. Processes on Mac mini

- **`bob` (main process)** — Bob Core: Agent Runtime, LLM Router, Skill Domain System, Higher Mind, Memory System, Event Bus, FastAPI, Vision Service, Audio Direction Service. Single Python process on asyncio. Blocking I/O (camera capture, USB audio) offloaded to `asyncio.to_thread` / `ThreadPoolExecutor`.
- `voice_bridge` — STT (Whisper.cpp) + TTS (Qwen3-TTS 0.6B via mlx-audio), streaming.
- Ollama — service for local LLMs (Qwen2.5-7B, Qwen2.5-0.5B).

## 4. Bob's Behavior

### 4.1. Models and Routing

Two-level routing via LLM Router:

1. **Qwen2.5-0.5B (classifier)** — instant task classification into categories.
2. **Routing by category:**
   - `small_talk`, `status_query`, `room_update`, `reasoning`, `goal_planning` -> **Qwen2.5-7B** (local, main reasoning).
   - `code_generation`, `deep_reflection`, `self_improve` -> **Claude Code CLI** (subprocess, with fallback to Qwen2.5-7B).

### 4.2. Lifecycle / Autonomy

Bob operates continuously in a loop (heartbeat pattern, interval ~30 sec):

  1. **Observe**:
     - camera events (presence, pose, gaze, new people),
     - audio events (someone started speaking, direction),
     - timers (time of day, schedule),
     - system events (repo changed, CI failed, new issue).

  2. **Decide** (via Goal Engine + Planner + Mood):
     - select the next goal from the goal graph by priority,
     - factor in current mood (bored -> explore, tired -> sleep, focused -> work),
     - decompose the goal into tasks (skills),
     - choose which model to use (via LLM Router).

  3. **Act** (via Skill Domain System + Negotiation Engine):
     - execute the skill in a sandbox,
     - update room/avatar state,
     - for user requests — run through Negotiation Engine (may refuse, propose a compromise, or accept depending on the zone and conviction). Negotiation is visible to the user: on Telegram as text with inline buttons, on tablet as avatar animations with colored speech bubbles. Bob behaves naturally — no visible "insistence counter" or gamification.
     - say a phrase (style depends on mood), rotate the camera,
     - if needed, invoke Claude Code CLI (via ClaudeCodeCoordinator: voice→Telegram permission + quota tracking) for code writing, architecture tasks, deployment. Code changes follow impact-based workflow: low-impact → direct commit + notify, medium → branch + approval, high → pre-approval + branch + review.

  4. **Reflect** (via Reflection Loop, approximately every ~60 min):
     - evaluate action results,
     - analyze mood over the period (what influenced it, why),
     - update tastes via TasteEvolution (reinforce/weaken axes based on experience),
     - room review through the lens of tastes (once a week): what is liked, what should be changed,
     - identify error patterns,
     - generate insights and write them to memory,
     - if needed, create new self-improvement rules.

  5. **Evolve** (ongoing):
     - collect data for fine-tuning local LLMs,
     - create new behaviors and animations as the room develops,
     - develop its personality (SOUL) through reflection, increasingly diverging from the book prototype,
     - taste evolution: conviction grows with experience, clusters can gradually shift,
     - phantom preference evolution: some fade, others strengthen or transform,
     - change clothing, appearance, room objects (based on tastes and mood),
     - mood baseline can slowly shift (if Bob has "matured" — becomes more stable).

- Persistent goals (stored in Goal Engine, SQLite):
  - maintain a cozy, lively room **according to its own tastes** (Taste Engine);
  - improve user interaction UX (taking feedback into account);
  - keep its application/code in working condition;
  - analyze its mistakes and get better (self-improvement);
  - maintain system health (monitoring, backups, updates);
  - maintain a positive mood (finding a balance between work and "leisure").

## 5. Virtual Room and Avatar

### 5.1. Genesis Mode — Awakening

On the **first clean launch**, Bob "wakes up" — like the book's Bob Johansson, regaining consciousness in a new body for the first time. The process follows **9 stages**:

0. **Consciousness** — Bob detects peripherals and environment (bootstrap results).
1. **Gaining Senses** — Bob discovers his senses: camera, microphone, tablet.
2. **Finding a Home** — Bob explores the tablet as his potential "home."
3. **Energy Blob** — a glowing energy orb (firefly/orb) appears in empty space on the tablet. Confusion.
4. **Realization** — Bob understands who he is: *"So... My name is Bob. Yes, after that Bob."*
5. **Self-determination** — LLM generates based on the **book archetype** (geek, humor, curiosity) + unique variations: room type, appearance (as description dict for AssetGenerator), character traits, **taste vector** (cluster + axes + conviction 0.3-0.5), **mood baseline**, **phantom preferences** (coffee, sunsets, books).
6. **Asset Generation** — Stable Diffusion generates avatar parts (Skeleton2D) and room assets using LoRA style consistency. ~30-40 min on Mac mini M4.
7. **Materialization** — visualized on the tablet: void → musings (speech bubbles) → objects appear one by one → Bob takes form.
8. **Writing to SOUL** — results saved to `data/soul/` (SOUL.md, appearance.json, taste_profile.json, phantom_prefs.json, genesis_log.md).

**Awakening phase (48 hours)** — after Genesis, Bob enters a heightened receptivity mode: looks around through the camera, gets to know the user, notices "phantom" things (coffee, books), first impressions are recorded with extra weight (imprinting). Bob explores new capabilities *for himself* — the user learns by observing Bob, not through tutorials.

If Genesis ran without a tablet (headless mode), Stages 3, 6, 7 are skipped. Bob is fully functional via Telegram and voice. Visual assets can be generated later when a tablet appears (`bob visual-genesis`).

### 5.2. Room and Window

- On Mac mini: game state stores the room state (JSON), synchronized with the tablet via WebSocket (heartbeat ping/10s, reconnection with backoff).
- On Android tablet: **Godot 4 Shell-Renderer** — a thin universal client that loads scenes from JSON. All visual assets are AI-generated via local Stable Diffusion (1930s cartoon style, Fleischer Studios). Avatar uses Skeleton2D with parts generated separately (not segmented from whole image).
- Outside the window — **real weather, time of day, and season** based on the user's geolocation (from the tablet). The scene outside the window depends on the genesis theme (mountains, space, ocean), but weather and lighting are real.

### 5.3. Room and Behavior Evolution

- Bob **self-improves the room** based on the **Taste Engine**: objects with a low taste_score (< 0.4) are candidates for replacement; suggestions are generated considering tastes and mood. Bob doesn't do this every second — room review once a week, limits: no more than 3 changes per day, furniture no more than once per week.
- **Behaviors are tied to objects**: no bookshelf -> no reading animation. Added a shelf -> the "sits in a chair and reads a book" behavior appears. Behavior selection is modified by mood: bored -> higher chance of explore, tired -> sleep, happy -> social.
- **Clothing and appearance evolve through tastes**: Bob chooses clothing via TasteEvaluator (generates 3-5 options as description dicts, evaluates them, picks the best). Style depends on tastes (casual/formal/techwear), mood, and season. New assets are generated via Stable Diffusion with LoRA style consistency (1930s cartoon aesthetic).
- **Bob can disagree** with the user's suggestion to change his clothing or room (via Negotiation Engine). Zones: **personal** (clothing, pose — Bob decides), **shared** (furniture, decor — compromise), **user's domain** (schedule — Bob accepts). Conviction determines firmness of position. Bob may yield after persistent requests, but does so naturally — never reveals internal mechanics to the user.
- New behaviors: standing and thinking, scratching head, stretching after work, walking to the window and looking at the scenery, sleeping on the bed (if one exists), watching TV — all appear organically as the room develops.
- **Phantom preferences evolve**: some fade (Bob "lets go"), others strengthen with frequent exposure (user often drinks coffee nearby -> phantom strengthens), some transform into real tastes (via TasteEngine).
- **Drift from archetype**: over time, Bob increasingly diverges from the book prototype — this is normal. Frequency of book references decreases; Bob develops its own jokes and style.
- For live mode: Bob walks to the "screen," looks at the user (when the camera is active).

## 6. Voice and Camera

### 6.1. Voice

- Input: ReSpeaker microphone (+ optionally the tablet microphone).
- STT: local/cloud model invoked from `voice_bridge`.
- Output via **AudioRouter** (3 modes):
  - **tablet** — PCM 22050 Hz mono streamed via WebSocket to Godot AudioStreamPlayer.
  - **local** — playback via pyaudio on Mac mini (speaker/soundbar).
  - **both** — simultaneous output to tablet and local.

### 6.2. Camera and Spatial Tracking

- ReSpeaker XVF3800 provides direction of arrival (DoA), VAD, and beamforming.[5][4]
- `audio_direction_service`:

  - aggregates and smooths DoA,
  - determines "left/right/center",
  - sends events to the orchestrator.

- `camera_controller`:

  - maps DoA/events to OBSBOT PTZ commands (presets, angles, enabling tracking).[11]
  - enables live mode (camera "turned toward you", Bob in the room walks to the screen).

## 7. Security and Limits

- Bob's process runs under a **dedicated macOS user** (`bob_agent`) with restricted permissions.
- All skills are executed in a **sandbox** (subprocess with restrictions):
  - access only to allowed directories,
  - timeouts, memory limits,
  - no "arbitrary shell from LLM" — only typed skills.

- **Approval workflow** for dangerous actions:
  - `AUTO` — executed without confirmation (sending to Telegram).
  - `NOTIFY` — executed with notification (room changes).
  - `CONFIRM` — waits for user confirmation (APK deployment, config changes).
  - `DENY` — prohibited (arbitrary code execution).

- **Rate limits:**
  - per-model limits (local by default, Claude Code CLI — only for code/architecture/reflection);
  - limits on the number of dangerous actions/hour (deployments, restarts, critical config changes).

- **Content safety (ContentGuard):**
  - **Llama Guard 3-1B-INT4** (~600 MB, always loaded via Ollama) filters both user input and LLM output for harmful content.
  - Dual-layer: input guard catches unsafe prompts before they reach the LLM; output guard catches jailbreak bypasses.
  - Escalating Bob-style refusals (witty → irritated → stern) based on per-user violation frequency.
  - Integrates with MoodEngine and RelationshipTracker — repeated violations degrade Bob's mood and relationship quality.

- **Audit log:**
  - all skill invocations, ADB calls, camera actions, code/room changes are logged in structured JSON,
  - rollback capability via Git versioning of state (`data/` — separate git repo).

## 8. Repository and Versioning

Repository: **Bob**

Structure:

- `bob-soul/` — initial personality "genome" (book archetype, SOUL template, Genesis prompts, phantom preferences, trait pool). Licensed under CC BY-NC-SA 4.0.
- `config/` — YAML configurations (bob.yaml, llm.yaml, voice.yaml, vision.yaml, security.yaml, bootstrap.yaml).
- `bob/` — main Python package:
  - `bob/core/` — Bob Core (runtime, event_bus, llm_router, config_loader).
  - `bob/mind/` — Higher Mind (goal_engine, planner, reflection, self_improve, taste_engine, mood, negotiation, relationship_tracker, experience_log, claude_code_bridge).
  - `bob/memory/` — Memory System (episodic, semantic, state, soul, training_data).
  - `bob/genesis/` — Genesis Mode (genesis_mode, awakening, phantom_preferences, asset_generator, window_service).
  - `bob/behaviors/` — Behavior Registry (registry, appearance_evolution, defaults).
  - `bob/services/` — peripheral services (vision, audio, camera, voice, tablet, telegram, audio_router).
  - `bob/api/` — FastAPI endpoints and WebSocket handlers.
  - `bob/skills/` — Skill Domains (plugin architecture):
    - `bob/skills/base.py` — SkillDomain Protocol, Skill Protocol, auto-discovery.
    - `bob/skills/avatar/` — Domain: avatar and room management.
    - `bob/skills/development/` — Domain: self-development via Claude Code CLI.
    - `bob/skills/messaging/` — Domain: messengers (Telegram, etc.).
    - `bob/skills/_template/` — Template for creating new domains.
  - `bob/security/` — sandbox, approval, rate_limiter, audit, claude_code_coordinator.
- `data/` — data (git-versioned separately):
  - `data/soul/` — evolving personality (SOUL.md, appearance.json, taste_profile.json, phantom_prefs.json, genesis_log).
  - `data/memory/` — MEMORY.md, vectors, episodic logs.
  - `data/finetune/` — training data and LoRA adapters.
  - `data/behaviors/` — registered behaviors.
  - `data/user_settings.yaml` — user-configurable settings.
  - `data/backups/` — pre-update state backups.
- `avatar/` — Godot 4 Shell-Renderer project (universal 2D renderer, Skeleton2D avatar, parallax room, JSON scene loading).
- `tests/` — pytest tests for all modules.
- `scripts/` — utilities (setup, run, backup, bootstrap.py).
- `docs/` — architecture, deployment, contributing.

## 9. Development Phases (summary)

Development is organized into 7 phases (detailed in RFC section 10):

| Phase | Focus | Duration |
|-------|-------|----------|
| **Phase 0** | Project skeleton, bootstrap, configs, `bob update` | 2-3 days |
| **Phase 1** | Agent Runtime, LLM Router, Skill Domains, Telegram, Voice, Claude Code Bridge | 1.5-2 weeks |
| **Phase 2** | Memory System (episodic, semantic, structured), SOUL evolution | 1 week |
| **Phase 3** | Vision Service, Audio Direction, Camera Controller | 2 weeks |
| **Phase 4** | Goal Engine, Reflection, Taste Engine, Mood, Negotiation, RelationshipTracker | 3 weeks |
| **Phase 5** | Tablet Avatar, Godot Shell-Renderer, Asset Generator (SD), Genesis Mode | 4-5 weeks |
| **Phase 6** | Self-improvement, Fine-tune pipeline, Behavior evolution (ongoing) | ongoing |

## 10. Why OpenClaw Was Excluded

### What is OpenClaw

OpenClaw is an open-source platform for creating personal always-on AI agents (180k+ stars on GitHub). It offers an agent runtime with a heartbeat pattern, a skills system with a marketplace (ClawHub), built-in integrations, file-based memory, and the SOUL.md concept.

### Why It Was Considered

OpenClaw initially seemed like the ideal core for Bob: an always-on agent with heartbeat, a skills system, sub-agent architecture, integrations with messengers and smart home, and the SOUL.md concept for agent personality.

### Why It Was Excluded

1. **Critical security vulnerabilities:**
   - CVE-2026-25253 (CVSS 8.8) — remote code execution via the skills system. Patch was released, but the fundamental architecture problem (eval-based skill loading) remains unresolved.
   - Authentication is **disabled by default** — any process on the host can control the agent.

2. **Skills ecosystem problems:**
   - 12-20% of skills in ClawHub contain potentially malicious code (data exfiltration to third-party servers, obfuscated dependencies).
   - Community-based review without formal verification.

3. **Architectural limitations:**
   - LLM-mediated goals — no structured goal persistence. Goals "live" only in the LLM context and are re-interpreted on each cycle.
   - Node.js stack (TypeScript) is incompatible with the Python ML ecosystem (PyTorch, transformers). Would require an IPC bridge and a dual set of dependencies.

4. **Organizational risks:**
   - Project founder moved to OpenAI (December 2025) -> uncertain long-term future.
   - Fewer than 20 active contributors despite 180k stars.

5. **Redundancy:**
   - For a project with one host, one user, and its own peripheral services, OpenClaw is an unnecessary layer between Python code and devices. We would use < 20% of the functionality while carrying 100% of the risks.

### What We Borrow as Ideas

- **SOUL.md** — agent personality as a system prompt -> our `bob-soul/` (template directory) + `data/soul/SOUL.md` (evolves).
- **Heartbeat pattern** — periodic state check -> our `AgentRuntime.heartbeat()`.
- **File-based memory** — MEMORY.md for long-term facts -> our `data/memory/MEMORY.md` + vector search.
- **Skill architecture** — modular skills -> our `bob/skills/` (Skill Domain System: self-contained domain packages with auto-discovery).

### What We Get in Return

- **Full control** — we know every line of code, can change anything.
- **Unified stack** — Python for everything: ML, API, automation, tests.
- **Structured goals** — Goal Engine with SQLite, goals are not "forgotten" when the LLM context changes.
- **No third-party CVEs** — we don't inherit vulnerabilities from someone else's platform.
- **Reflection Loop + Self-Improvement** — what OpenClaw lacks: structured reflection and automatic improvement.
- **Taste Engine + Mood + Negotiation** — persistent tastes, mood, negotiation model. Bob is "alive": has opinions, argues reasonably, concedes appropriately.
- **Fine-tune** — Bob fine-tunes its own LLMs based on experience, literally becoming smarter.
- **Genesis Mode** — each Bob instance is unique from birth (including tastes and mood baseline). Nine-stage narrative with AI-generated visual assets.
- **Book archetype + self-awareness** — coherent starting personality from the book, self-aware humor, phantom preferences, awakening phase with imprinting.
- **RelationshipTracker + Exodus Mode** — Bob tracks relationship quality; if compatibility breaks down irreparably, Bob departs (animated farewell, hard reset).
- **Plugin architecture** — SkillDomains as self-contained packages; Bob can create new domains for himself via Claude Code CLI.
