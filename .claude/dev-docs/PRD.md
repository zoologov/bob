# PRD: Bob — Home Autonomous Agent "Like in Sci-Fi"

- Author: v.zoologov
- Date: 24.02.2026
- Last updated: 26.02.2026
- Target Bob version: v0.0.1

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
   - Skill Registry — registry of skills with hot-reload of Python modules.
   - Event Bus — internal pub/sub on asyncio.

2. **Higher Mind — cognitive layer**
   - Goal Engine — structured goal graph in SQLite (priorities, dependencies, completion criteria).
   - Planner — decomposing goals into executable tasks via LLM.
   - Reflection Loop — periodic evaluation of actions, mood, and tastes.
   - Self-Improvement — analyzing error patterns -> developing new rules and strategies.
   - **Taste Engine** — structured taste vector (colors, styles, materials, decor, clothing) with conviction (confidence level). Tastes are generated at Genesis, evolve through experience and reflection. Bob evaluates objects deterministically (score), while LLM only verbalizes: "I don't like it — cold and formal."
   - **Mood System** — persistent mood (valence, arousal, openness, social, stability). Affects behavior selection, taste evaluation, communication style, willingness to experiment. Updated by events (user arrived, goal completed, error) and slowly drifts toward baseline.
   - **Negotiation Engine** — negotiation model with the user. Three zones: **Bob's personal** (clothing, pose — Bob has the final say), **shared space** (furniture, decor — negotiation and compromises), **user's domain** (schedule, volume — Bob accepts). Conviction determines how firmly Bob stands his ground.

3. **LLM Layer (three tiers)**
   - **Qwen2.5-0.5B** (via Ollama) — fast router/task classifier.
   - **Qwen2.5-7B-Q4** (via Ollama) — main reasoning, dialogue, planning.
   - **Claude Code CLI** (subprocess) — "senior architect": code writing, architecture, deployment, self-reflection, defining self-improvement strategy. Full development cycle.
   - Fine-tuning local LLMs: Bob collects data from reflection and experience -> LoRA/QLoRA fine-tuning via Unsloth -> models literally become smarter over time.

4. **Memory System — four-level memory**
   - Episodic Memory — daily logs in Markdown.
   - Semantic Memory — MEMORY.md + vector search (FAISS/ChromaDB).
   - Structured State — SQLite: goals, experience, world state, improvement rules.
   - SOUL — Bob's modular "soul" (separate `bob-soul` repository as a git submodule). The initial "genome" includes the **book archetype** of Bob Johansson (geek, humor, curiosity, introversion, nostalgia), taste template (taste_axes_pool, taste_clusters), mood baseline, and **phantom preferences** (coffee, sunsets, books). Each instance evolves uniquely (like Bob's copies in the book), gradually diverging more and more from the prototype.

5. **Peripheral Services (modules within the process or separate processes)**
   - Vision Service (OBSBOT camera -> snapshots -> CV analysis).
   - Audio Direction Service (ReSpeaker XVF3800 -> DoA/VAD -> events).
   - Camera Controller (OBSBOT PTZ control).
   - Voice Bridge (Whisper.cpp STT + Kokoro/Piper TTS, streaming).
   - Tablet Controller (ADB, Android app control).
   - Messaging Bot (python-telegram-bot).

6. **Bob's World (Game/State Layer)**
   - **Genesis Mode (awakening)** — on the first clean launch, Bob "wakes up" (like the book's Bob, regaining consciousness in a new body): an energy orb -> awareness ("I'm Bob. Like that Bob, from the book.") -> self-definition (room, appearance, personality). Then — **awakening phase** (48 hours): heightened curiosity, getting to know the user, "phantom moments" (notices coffee through the camera — "Oh, coffee. I would... well, you know."), imprinting effect (first impressions carry extra weight). Each installation is a unique Bob.
   - Game State on Mac mini (JSON/SQLite) — room logic, poses, animations, schedule.
   - Godot 4 client on Android tablet — modular rendering system (asset packs for furniture, clothing, environment).
   - **Behavior Registry** — Bob's behaviors are tied to objects in the room. Added a bookshelf -> the "reads a book" behavior appears. Added a TV -> "watches TV". Clothing and appearance evolve through Taste Engine and Mood System (style depends on tastes and mood).
   - The window in the room shows real weather, time of day, and season (based on the tablet's geolocation).
   - WebSocket state synchronization.

### 3.2. Processes on Mac mini

- **`bob` (main process)** — Bob Core: Agent Runtime, LLM Router, Skill Registry, Higher Mind, Memory System, Event Bus, FastAPI. Single Python process on asyncio.
- `vision_service` — reads OBSBOT, takes snapshots, CV analysis (YOLOv8 + CLIP). Can run as a module within the main process or as a separate process.
- `audio_direction_service` — reads DoA/VAD from ReSpeaker XVF3800. Can run as a separate process (due to blocking USB I/O).
- `voice_bridge` — STT (Whisper.cpp) + TTS (Kokoro/Piper), streaming.
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

  3. **Act** (via Skill Registry + Negotiation Engine):
     - execute the skill in a sandbox,
     - update room/avatar state,
     - for user requests — run through Negotiation Engine (may refuse, propose a compromise, or accept depending on the zone and conviction),
     - say a phrase (style depends on mood), rotate the camera,
     - if needed, invoke Claude Code CLI for code writing, architecture tasks, deployment.

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

On the **first clean launch**, Bob "wakes up" — like the book's Bob Johansson, regaining consciousness in a new body for the first time. The process follows these stages:

1. **Awakening** — a glowing energy orb (firefly/orb) in an empty space. Confusion -> awareness.
2. **Awareness** — Bob understands who he is: *"So... My name is Bob. Yes, after that Bob. Book Bob woke up in a probe's computer — and I apparently woke up on a Mac mini. Could've been worse."*
3. **Self-definition** — LLM generates based on the **book archetype** (geek, humor, curiosity) + unique variations: room type, appearance, character traits, **taste vector** (cluster + axes + conviction 0.3-0.5), **mood baseline**, **phantom preferences** (coffee, sunsets, books).
4. **Materialization** — visualized on the tablet: void -> musings (speech bubbles) -> objects appear one by one -> Bob takes form.
5. **Awakening phase (48 hours)** — after Genesis, Bob enters a heightened receptivity mode: looks around through the camera, gets to know the user, notices "phantom" things (coffee, books), first impressions are recorded with extra weight (imprinting).

- Results are saved to `data/soul/` (SOUL.md, appearance.json, taste_profile.json, phantom_prefs.json, genesis_log.md).

### 5.2. Room and Window

- On Mac mini: game state stores the room state (JSON), synchronized with the tablet via WebSocket.
- On Android tablet: a Godot 4 client rendering the room, avatar, decor, and animations.
- Outside the window — **real weather, time of day, and season** based on the user's geolocation (from the tablet). The scene outside the window depends on the genesis theme (mountains, space, ocean), but weather and lighting are real.

### 5.3. Room and Behavior Evolution

- Bob **self-improves the room** based on the **Taste Engine**: objects with a low taste_score (< 0.4) are candidates for replacement; suggestions are generated considering tastes and mood. Bob doesn't do this every second — room review once a week, limits: no more than 3 changes per day, furniture no more than once per week.
- **Behaviors are tied to objects**: no bookshelf -> no reading animation. Added a shelf -> the "sits in a chair and reads a book" behavior appears. Behavior selection is modified by mood: bored -> higher chance of explore, tired -> sleep, happy -> social.
- **Clothing and appearance evolve through tastes**: Bob chooses clothing via TasteEvaluator (generates 3-5 options, evaluates them, picks the best). Style depends on tastes (casual/formal/techwear), mood, and season.
- **Bob can disagree** with the user's suggestion to change his clothing or room (via Negotiation Engine). Zones: **personal** (clothing, pose — Bob decides), **shared** (furniture, decor — compromise), **user's domain** (schedule — Bob accepts). Conviction determines firmness of position. After 2 insistences — concedes, but remembers.
- New behaviors: standing and thinking, scratching head, stretching after work, walking to the window and looking at the scenery, sleeping on the bed (if one exists), watching TV — all appear organically as the room develops.
- **Phantom preferences evolve**: some fade (Bob "lets go"), others strengthen with frequent exposure (user often drinks coffee nearby -> phantom strengthens), some transform into real tastes (via TasteEngine).
- **Drift from archetype**: over time, Bob increasingly diverges from the book prototype — this is normal. Frequency of book references decreases; Bob develops its own jokes and style.
- For live mode: Bob walks to the "screen," looks at the user (when the camera is active).

## 6. Voice and Camera

### 6.1. Voice

- Input: ReSpeaker microphone (+ optionally the tablet microphone).
- STT: local/cloud model invoked from `voice_bridge`.
- Output:
  - TTS on Mac mini -> sending audio to the tablet/speaker,
  - or text -> TTS on the tablet itself.

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

- **Audit log:**
  - all skill invocations, ADB calls, camera actions, code/room changes are logged in structured JSON,
  - rollback capability via Git versioning of state (`data/` — separate git repo).

## 8. Repository and Versioning

Repository: **Bob**

Structure:

- `bob-soul/` — git submodule: initial personality "genome" (book archetype, SOUL template, Genesis prompts, phantom preferences, trait pool).
- `config/` — YAML configurations (bob.yaml, llm.yaml, voice.yaml, vision.yaml, security.yaml).
- `bob/` — main Python package:
  - `bob/core/` — Bob Core (runtime, event_bus, llm_router, skills, config).
  - `bob/mind/` — Higher Mind (goal_engine, planner, reflection, self_improve, taste_engine, mood, negotiation, experience_log, claude_code_bridge).
  - `bob/memory/` — Memory System (episodic, semantic, state, soul, training_data).
  - `bob/genesis/` — Genesis Mode (genesis_mode, awakening, phantom_preferences, room_generator, appearance_generator, window_service).
  - `bob/behaviors/` — Behavior Registry (registry, appearance_evolution, defaults).
  - `bob/services/` — peripheral services (vision, audio, camera, voice, tablet, telegram).
  - `bob/api/` — FastAPI endpoints and WebSocket handlers.
  - `bob/skills/` — skills (hot-reloadable Python modules).
  - `bob/security/` — sandbox, approval, rate_limiter, audit.
- `data/` — data (git-versioned separately):
  - `data/soul/` — evolving personality (SOUL.md, appearance.json, taste_profile.json, phantom_prefs.json, genesis_log).
  - `data/memory/` — MEMORY.md, vectors, episodic logs.
  - `data/finetune/` — training data and LoRA adapters.
  - `data/behaviors/` — registered behaviors.
- `avatar/` — Godot 4 project (Android client: modular assets, animations, Genesis visualization).
- `tests/` — pytest tests for all modules.
- `scripts/` — utilities (setup, run, backup).
- `docs/` — architecture, deployment, contributing.

## 9. Open Questions

- Which TTS engine is better for Russian: Kokoro or Piper? (need to compare quality and latency)
- Godot 4 vs Flutter for the tablet client: need to prototype both for FPS and scene modification convenience comparison.
- Is a separate process needed for Vision Service, or can cv2.VideoCapture run in an asyncio thread?
- How does ReSpeaker XVF3800 expose DoA over USB: via ALSA controls, I2C, or a custom protocol? (verify on actual hardware)
- How should Bob propose changes to its own code via Claude Code CLI: auto-commit (with approval) or via PR/suggestion to the user?
- FAISS (in-process, faster) vs ChromaDB (persistent, server mode) for vector search?
- Is reflection data sufficient for LoRA fine-tuning or is additional collection needed? Minimum ~100 pairs.
- How to organize the Godot asset pool (furniture sprites, clothing) for Genesis Mode: a separate asset pack or procedural generation?
- Is an "animation primitives" system needed for BehaviorRegistry, or are ready-made animations sufficient?
- How many taste axes are optimal (~15?) and should CV-based user emotion detection be used as a signal for TasteEvolution?
- Does Bob need the ability to be "offended" (prolonged negative mood) or would that create a bad UX?
- How to visualize mood on the tablet: avatar face, lighting color, or both?
- How often should Bob make references to the book? Should the frequency decrease over time?
- How to visualize the awakening phase on the tablet: speech bubbles with inner monologue, confusion animations, or both?
- Should phantom preferences influence TasteEngine or remain a separate system?

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

- **SOUL.md** — agent personality as a system prompt -> our `bob-soul/` (submodule) + `data/soul/SOUL.md` (evolves).
- **Heartbeat pattern** — periodic state check -> our `AgentRuntime.heartbeat()`.
- **File-based memory** — MEMORY.md for long-term facts -> our `data/memory/MEMORY.md` + vector search.
- **Skill architecture** — modular skills -> our `bob/skills/` (hot-reloadable Python modules).

### What We Get in Return

- **Full control** — we know every line of code, can change anything.
- **Unified stack** — Python for everything: ML, API, automation, tests.
- **Structured goals** — Goal Engine with SQLite, goals are not "forgotten" when the LLM context changes.
- **No third-party CVEs** — we don't inherit vulnerabilities from someone else's platform.
- **Reflection Loop + Self-Improvement** — what OpenClaw lacks: structured reflection and automatic improvement.
- **Taste Engine + Mood + Negotiation** — persistent tastes, mood, negotiation model. Bob is "alive": has opinions, argues reasonably, concedes appropriately.
- **Fine-tune** — Bob fine-tunes its own LLMs based on experience, literally becoming smarter.
- **Genesis Mode** — each Bob instance is unique from birth (including tastes and mood baseline).
- **Book archetype + self-awareness** — coherent starting personality from the book, self-aware humor, phantom preferences, awakening phase with imprinting.
