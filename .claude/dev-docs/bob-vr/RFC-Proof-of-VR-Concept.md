# RFC: Proof of VR Concept — Bob's Virtual Avatar

> **Status:** Aproved
> **Date:** 2026-03-01
> **Author:** v.zoologov + Claude
> **Context:** Evolution of bob-vr approach from 2D sprites to full 3D
> **Predecessor:** BRIEF.md - deprecated and deleted (2D Vault Boy + mesh deformation), DecisionLog.md (D-001 — D-010)
> **Reference:** The Sims (isometric view, object interaction, character life simulation)

---

## 1. Problem

### 1.1 Limitations of the 2D Approach (BRIEF.md)

The bob-vr prototype (Phase 1) revealed fundamental limitations of the 2D approach:

| Problem | Details |
|---------|---------|
| **Hands** | img2img (strength 0.5) cannot change structural hand pose. flux2-edit works but takes ~10 min per gesture |
| **Fixed viewpoint** | 2D sprite = front view only. Bob cannot turn sideways or show his back |
| **Every change = regeneration** | New outfit = 60 sec, new gesture = 10 min. Does not scale |
| **No depth** | Parallax creates illusion but does not replace real perspective |
| **No space** | Bob cannot walk to a shelf, pick up a book, sit in a chair |
| **No lighting** | Light is baked into the sprite, no dynamic light sources |

### 1.2 What We Want

A full virtual space for Bob, inspired by The Sims:

- Bob moves freely around a room, interacts with objects
- Isometric camera with depth
- Bob rotates: facing user, sideways, back to camera
- Infinite animations: walking, sitting, reading, typing, hand gestures with fingers
- Dynamic lighting (window, lamps)
- Bob self-manages his space: generates furniture, changes outfits, rebuilds the room
- **100% autonomous**: no downloaded asset libraries, no cloud APIs
- All content is generated programmatically or via local AI

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. **Proof of Concept**: prove that a fully autonomous 3D avatar is feasible on Mac Mini M4 + Android tablet
2. **Zero manual modeling**: no Blender, no manual 3D work
3. **Local-first**: everything generated locally (FLUX.2, TripoSR, MakeHuman, procedural code)
4. **Self-sufficient Bob**: Bob generates and manages his own space
5. **Sims-like interaction**: navigation, picking up objects, sitting, standing, walking
6. **Natural animation**: smooth, natural movement without artifacts
7. **Genesis autonomy**: when a new user installs Bob, the avatar is created automatically

### 2.2 Non-Goals

- Multiplayer / multiple characters
- Realistic graphics (AAA level)
- VR/AR (despite the bob-vr name)
- Open world (single room / space only)
- Real-world physics (ragdoll, destructibility)

---

## 3. Architecture

### 3.1 Overview

```
┌──────────────────────────────────────┐          ┌──────────────────────────┐
│           Mac Mini M4 (16 GB)        │WebSocket │    Android Tablet        │
│                                      │  (LAN)   │                          │
│  ┌─────────────┐  ┌───────────────┐  │◄────────►│  ┌────────────────────┐  │
│  │ Bob Core    │  │ Scene State   │  │  JSON    │  │ Godot 4.6 (3D)     │  │
│  │ (FastAPI)   │  │ Manager       │  │  cmds    │  │                    │  │
│  │             │  │               │  │─────────►│  │ • Isometric camera │  │
│  │ LLM decisions│ │ Object pos   │  │          │  │ • 3D character      │  │
│  │ Generation  │  │ Held items   │  │  events  │  │ • IK animations    │  │
│  └──────┬──────┘  └───────┬───────┘  │◄─────────│  │ • NavMesh          │  │
│         │                 │          │          │  │ • Stylized shader  │  │
│  ┌──────▼──────┐  ┌───────▼───────┐  │          │  │ • Dynamic lighting │  │
│  │ Ollama LLM  │  │ Asset Gen     │  │          │  │ • Scene rendering  │  │
│  │ ~5 GB       │  │               │  │          │  └────────────────────┘  │
│  └─────────────┘  │ FLUX.2 (tex)  │  │          │                          │
│                   │ TripoSR (3D)  │  │          │  Input: touch, voice     │
│                   │ MakeHuman     │  │          │  Output: display, audio  │
│                   │ (on demand)   │  │          │                          │
│                   └───────────────┘  │          └──────────────────────────┘
└──────────────────────────────────────┘
```

### 3.2 Separation of Concerns

| Task | Runs On | Why |
|------|---------|-----|
| LLM inference (Bob's decisions) | Mac Mini M4 | Needs RAM for model weights |
| 3D asset generation | Mac Mini M4 | FLUX.2 + TripoSR need GPU/RAM |
| Character generation | Mac Mini M4 | MakeHuman headless |
| Scene State (what is where) | Mac Mini M4 | Source of truth |
| 3D rendering | Tablet | Local display, GPU |
| IK / procedural animations | Tablet | Per-frame, needs low latency |
| Navigation (pathfinding) | Tablet | Real-time, per-frame |
| Dynamic lighting | Tablet | Real-time rendering |
| Touch/voice input | Tablet | Direct user interaction |
| Audio output (TTS) | Tablet | Speakers on tablet |

### 3.3 RAM Budget — Mac Mini M4 (16 GB)

| Component | RAM | Mode |
|-----------|-----|------|
| macOS + system | ~3.0 GB | Always |
| Ollama 7B (main LLM) | ~4.5 GB | Always |
| Ollama 0.5B (fast) | ~0.5 GB | Always |
| Guard model | ~0.6 GB | Always |
| Bob Core (FastAPI) | ~0.2 GB | Always |
| WebSocket server | ~0.05 GB | Always |
| **Always occupied** | **~8.85 GB** | |
| | | |
| FLUX.2 q4 (textures) | ~2.0 GB | On demand, unloaded after |
| TripoSR (3D gen) | ~2.0 GB | On demand, unloaded after |
| MakeHuman (genesis) | ~0.5 GB | Genesis only |
| **Peak consumption** | **~12.85 GB** | During generation |
| **Headroom** | **~3.15 GB** | |

Key principle: FLUX.2 and TripoSR are loaded **only when generating new content** (new furniture, new texture), then unloaded. During normal Bob operation they are not needed.

---

## 4. Character Generation (Bob Genesis)

### 4.1 Pipeline

```
Installation for a new user:

1. MakeHuman (headless, Python API):
   - Parameters: height, build, face, skin/hair color
   - LLM chooses parameters or random set
   - Generation: ~10-30 sec
   - Result: 3D mesh (.glb) with full skeleton

2. Skeleton:
   ~52 bones:
   ├── Body: hip → spine → chest → neck → head (5)
   ├── Arms: shoulder → upper_arm → forearm → wrist × 2 (8)
   ├── Legs: upper_leg → lower_leg → foot × 2 (6)
   ├── Face: jaw, eye_L, eye_R, brow (4)
   └── Fingers: 5 fingers × 3 joints × 2 hands (30)

3. Export → glTF → load into Godot

4. Apply stylized shader (cel-shading or Sims-like)

5. Cache: model saved locally,
   regeneration only on Bob's explicit request
```

### 4.2 Appearance Customization (Runtime)

| What Changes | How | Speed |
|-------------|-----|-------|
| Skin / hair color | Shader uniform | Instant |
| Outfit color | Shader uniform | Instant |
| Outfit texture (pattern) | FLUX.2 → UV map | ~60 sec |
| Body shape (proportions) | Bone scale | Instant |
| Hairstyle | MakeHuman re-generation (hair only) | ~10 sec |
| Clothing style (silhouette) | MakeHuman re-generation (clothes) | ~10-30 sec |

### 4.3 MakeHuman as a Dependency

MakeHuman is an open source Python package (AGPL), installed via pip:
- Not a downloaded asset library — it is a generator
- Parametric human model (analogous to FLUX.2 for 3D bodies)
- Full skeleton with fingers out of the box
- Has a clothing system (generated, not downloaded)
- Headless mode: works without GUI via Python API

> **Note**: if MakeHuman proves too heavy or limited, fallback is character generation via FLUX.2 (2D concept) → TripoSR (3D mesh) → auto-skeleton in Godot. Both options are fully local.

---

## 5. Procedural Animation System

### 5.1 Principle: No Downloaded Animations

All animations are created procedurally in code (GDScript in Godot 4.6). This is better than downloaded animations because:

- **Adaptive**: procedural "sit" adapts to any chair (IK finds seat height). A downloaded clip is tied to a specific height.
- **Infinite**: new gesture = new target rotations for bones, not a new file
- **Interactive**: Bob can pick up ANY object, not just those with pre-made animations

### 5.2 IK System (Godot 4.6)

Godot 4.6 brought back IK with 7 solvers:

| Solver | Application for Bob |
|--------|-------------------|
| **TwoBoneIK3D** | Arms (shoulder→elbow→wrist), legs (hip→knee→ankle) |
| **FABRIK3D** | Fingers (3 joints per finger), spine |
| **CCDIK3D** | Alternative for chains |
| **LookAt** | Head/eyes look at object of interest |

### 5.3 Procedural Animation Catalog

#### Base States (State Machine)

```
                    ┌──────────┐
                    │   Idle   │◄────────────────┐
                    └────┬─────┘                 │
                         │                        │
              ┌──────────┼───────────┐           │
              ▼          ▼           ▼           │
         ┌─────────┐ ┌───────┐ ┌─────────┐      │
         │ Walking │ │ Sit   │ │ Reach   │      │
         │         │ │ Down  │ │ Object  │      │
         └────┬────┘ └───┬───┘ └────┬────┘      │
              │          │          │            │
              ▼          ▼          ▼            │
         ┌─────────┐ ┌───────┐ ┌─────────┐      │
         │ Arrived │ │Sitting│ │ Holding │      │
         │         │ │       │ │ Object  │──────┘
         └────┬────┘ └───┬───┘ └─────────┘
              │          │
              ▼          ▼
         (next action)  ┌────────┐
                        │Reading │
                        │Typing  │
                        │Resting │
                        └────────┘
```

#### Implementation of Each Animation

**Idle (standing)**
```
- Breathing: sin(time * 0.8) * 0.02 → chest bone Y scale
- Swaying: perlin_noise(time * 0.3) * 0.005 → hip position
- Blinking: timer 3-6 sec → eyelid bones rotation 0→1→0 over 0.15 sec
- Head micro-movements: perlin_noise → neck rotation (±2°)
- Arms: slight swaying via perlin_noise on shoulder/elbow
```

**Walking**
```
- Navigation: NavigationAgent3D calculates path (NavMesh)
- Legs: procedural step cycle
  - Raycast down → determine floor height
  - Leg IK: foot target alternates left/right
  - Bezier curve for foot trajectory (lift-transfer-plant)
  - Step length proportional to speed
- Body: lean in direction of movement (±3°)
- Arms: counter-phase swing (right leg forward → left arm forward)
- Head: look-at in movement direction
- Smooth start/stop via easing
```

**Sitting (sit down in chair)**
```
- Walk to chair (Walking)
- Turn back to chair
- IK: hip target → seat position
- IK: spine → lean back to chair back
- IK: legs bend (knee angle ~90°)
- Arms: on armrests or on knees (IK targets)
- Blend time: 0.5-0.8 sec for smooth transition
```

**Picking up object**
```
- IK: right hand → object position (bezier curve, 0.5 sec)
- Fingers: curl 0→0.8 (grip object) via FABRIK
- Reparent: object becomes child of hand bone
- IK: hand returns to neutral position (object in hand)
```

**Reading (reading a book)**
```
- Book in both hands: BoneAttachment on both wrists
- Book open (blend shape opening 0→1)
- Head tilted down (look-at → book)
- Eyes: slow scanning left-right
- Page turning: every 20-40 sec → blend shape page_turn
- Breathing: additive layer on top of reading pose
```

**Typing (typing on keyboard)**
```
- Hands: IK targets on keyboard (2 points: left_hand_zone, right_hand_zone)
- Fingers: procedural typing cycle
  - Random finger extends (curl 0.6→0.1) and curls back
  - Hand alternation: 60% right, 40% left (right-handed)
  - Rate: 3-5 keystrokes/sec during active typing
- Head: look-at → monitor screen
- Body micro-movement: slight forward lean
```

### 5.4 LLM-Generated New Animations

Bob can create new behaviors via LLM:

```json
// LLM generates animation description:
{
  "animation": "stretch_arms_up",
  "description": "Stretch up after sitting for a long time",
  "keyframes": [
    {"time": 0.0, "bones": {"shoulder_l": {"rotation": [0, 0, 0]}, "shoulder_r": {"rotation": [0, 0, 0]}}},
    {"time": 0.5, "bones": {"shoulder_l": {"rotation": [-150, 0, -10]}, "shoulder_r": {"rotation": [-150, 0, 10]}}},
    {"time": 0.8, "bones": {"chest": {"rotation": [-5, 0, 0]}, "head": {"rotation": [-10, 0, 0]}}},
    {"time": 1.5, "bones": {"shoulder_l": {"rotation": [0, 0, 0]}, "shoulder_r": {"rotation": [0, 0, 0]}}}
  ],
  "additive_layers": ["breathing"],
  "blend_in": 0.3,
  "blend_out": 0.3
}
```

Godot AnimationPlayer can create animations programmatically from such JSON descriptions.

---

## 6. Environment Generation

### 6.1 Room (Procedural, from Code)

Base room is generated entirely from GDScript:

```
Room = parameters:
  - Size: width × depth × height (e.g. 6×8×3 m)
  - Walls: 4 MeshInstance3D (BoxMesh, thin)
  - Floor: MeshInstance3D (PlaneMesh)
  - Ceiling: MeshInstance3D (PlaneMesh)
  - Window: cutout in wall + DirectionalLight3D (sun)
  - Door: cutout in wall

Materials: ShaderMaterial with stylized rendering
Wall/floor colors: LLM chooses → shader uniforms
```

No downloaded assets — walls, floor, ceiling = geometric primitives.

### 6.2 Furniture and Objects (FLUX.2 → TripoSR Pipeline)

```
Bob decides: "I want a bookshelf"

1. Mac (FLUX.2, locally):
   Prompt: "single bookshelf with books, isometric view,
            clean white background, low-poly style"
   → 2D image generation (512×512, ~20 sec)

2. Mac (TripoSR, locally):
   Input: generated 2D image
   → 3D mesh (.glb) in ~5-30 sec

3. Mac → Tablet (WebSocket):
   - Sends .glb file
   - Position in room (x, y, z)
   - Object type (furniture, interactive, decoration)

4. Godot:
   - Loads .glb → MeshInstance3D
   - Applies stylized shader
   - Adds collision shape (for navigation)
   - Updates NavMesh (Bob walks around furniture)
   - If interactive: adds Area3D for interaction

Total: ~30-90 sec from idea to object in scene
```

### 6.3 Caching

```
~/.bob/assets/
├── character/
│   └── bob_v1.glb              # Current Bob model
├── furniture/
│   ├── bookshelf_001.glb       # Generated bookshelf
│   ├── bookshelf_001.meta.json # Generation parameters
│   ├── desk_001.glb
│   ├── armchair_001.glb
│   └── ...
├── props/
│   ├── book_001.glb
│   ├── laptop_001.glb
│   └── ...
├── textures/
│   ├── spacesuit_uv.png
│   └── ...
└── scenes/
    ├── cozy_room.json          # Layout: what is where
    └── spaceship_bridge.json
```

Generated assets are cached permanently. Regeneration only on Bob's explicit request.

### 6.4 Scene Change (Scenario: "Spaceship Bridge")

```
Bob: "I want a spaceship bridge"

LLM generates plan:
{
  "scene": "spaceship_bridge",
  "room": {"width": 10, "depth": 8, "height": 4, "wall_color": "#1a1a2e"},
  "objects_to_generate": [
    {"name": "captain_console", "prompt": "sci-fi control console with screens, cartoon style"},
    {"name": "captain_chair", "prompt": "sci-fi captain chair, futuristic, simple"},
    {"name": "viewport_window", "prompt": "large round spaceship window, simple frame"},
    {"name": "navigation_panel", "prompt": "spaceship navigation holographic panel"}
  ],
  "lighting": {
    "ambient": {"color": "#0a0a3a", "intensity": 0.3},
    "console_light": {"type": "omni", "color": "#00aaff", "position": [3, 1, 2]},
    "window_light": {"type": "directional", "color": "#ffffff", "intensity": 0.5}
  },
  "bob_outfit": {
    "texture_prompt": "silver futuristic spacesuit with blue accents, cartoon style"
  },
  "skybox": {
    "prompt": "deep space with stars and nebula, dark blue"
  }
}

Execution (parallel):
1. FLUX.2: generates 4 object images + outfit texture + skybox (~2 min)
2. TripoSR: converts 4 images to 3D (~1-2 min)
3. Godot: removes old scene, builds new room, places objects
4. FLUX.2: generates UV outfit texture → applies to Bob

Total: ~3-5 min for complete scene change
```

---

## 7. Scene State Management

### 7.1 Principle: Mac = Source of Truth, Tablet = Renderer

Mac Mini M4 holds the complete scene state:

```json
{
  "scene": "cozy_room",
  "room": {"width": 6, "depth": 8, "height": 3},
  "objects": {
    "bookshelf_001": {
      "position": [0, 0, -3.5],
      "rotation": [0, 0, 0],
      "slots": {
        "slot_0": "book_001",
        "slot_1": "book_002",
        "slot_2": null,
        "slot_3": "book_003"
      }
    },
    "desk_001": {
      "position": [2, 0, -2],
      "surface": ["laptop_001"],
      "type": "interactive"
    },
    "armchair_001": {
      "position": [-2, 0, 0],
      "type": "sittable"
    }
  },
  "bob": {
    "position": [-2, 0, 0],
    "state": "sitting",
    "sitting_on": "armchair_001",
    "holding": {
      "right_hand": "book_002",
      "left_hand": null
    },
    "expression": "focused",
    "activity": "reading"
  }
}
```

### 7.2 State Sync

- Mac sends **commands** (actions), not full state
- Tablet executes command, sends **confirmation**
- On desynchronization: Mac sends full snapshot → Tablet rebuilds scene
- State persisted in `~/.bob/scenes/` (JSON)
- On restart: Godot restores last scene

---

## 8. Visual Style

### 8.1 Approach: Stylized Shader (Not Necessarily Cartoon)

Instead of strict "Vault Boy cel-shading" — a flexible stylized shader configurable via parameters:

```
Style spectrum (one shader, different parameters):
├── Cartoon (Vault Boy): 2 shadow bands, bold outline, flat colors
├── Sims-like: soft shadows, subtle outline, warm tones
├── Anime: sharp shadows, colored outlines, vivid colors
└── Painterly: blurred shadows, no outline, brush stroke textures
```

Bob can change rendering style at runtime — it's just shader uniforms.

### 8.2 Lighting

```
Light sources:
├── DirectionalLight3D — sun through window
│   ├── Color: warm during day, cool in evening
│   ├── Shadows: soft shadows
│   └── Intensity: depends on time of day
├── OmniLight3D — room lamps
│   ├── Desk lamp on table
│   ├── Floor lamp by chair
│   └── Monitor light (cool blue)
└── Environment / Skybox
    ├── Daytime sky → warm ambient
    └── Space → cool ambient
```

### 8.3 Camera

```
Isometric Camera:
- Projection: Orthographic (removes perspective distortion)
- Angle: 30-45° from above (like The Sims / Diablo)
- Rotation: user can rotate camera around room (touch gesture)
- Zoom: pinch-to-zoom for close-up/wide view
- Follow: camera smoothly follows Bob when moving
```

---

## 9. Communication Protocol (Mac ↔ Tablet)

### 9.1 WebSocket (JSON)

Built into Godot 4.6. Bidirectional. LAN latency: 10-50ms.

### 9.2 Message Types: Mac → Tablet

```json
// Navigation
{"type": "navigate", "target": "bookshelf_001", "speed": 1.0}

// Interaction
{"type": "interact", "action": "pick_up", "object": "book_002", "hand": "right"}

// Action
{"type": "action", "animation": "sit_down", "target": "armchair_001"}

// Activity
{"type": "activity", "name": "reading", "params": {"book": "book_002", "page_turn_interval": 30}}

// Expression
{"type": "expression", "face": "happy", "intensity": 0.8}

// Speech (sync with TTS)
{"type": "speak", "visemes": [...], "duration": 3.5}

// New object
{"type": "spawn_object", "id": "bookshelf_001", "mesh": "<base64 glb>",
 "position": [0, 0, -3.5], "properties": {"type": "interactive", "slots": 8}}

// Scene change
{"type": "scene_change", "config": { ... full scene JSON ... }}

// Outfit change
{"type": "outfit_change", "texture": "<base64 png>"}

// Render style change
{"type": "render_style", "params": {"shadow_bands": 3, "outline_width": 2.0, "saturation": 1.2}}
```

### 9.3 Message Types: Tablet → Mac

```json
// Action complete
{"type": "action_complete", "action": "navigate", "target": "bookshelf_001"}

// User input
{"type": "user_input", "action": "tap", "target": "bob"}

// Voice input
{"type": "voice_input", "audio": "<base64 wav>"}

// Error
{"type": "error", "message": "object_not_found", "object_id": "book_999"}
```

---

## 10. Props Generation: FLUX.2 → TripoSR

### 10.1 TripoSR

- **Authors**: Stability AI + Tripo
- **License**: MIT
- **Installation**: `pip install triposr` (Python dependency, not an asset)
- **Input**: single 2D image
- **Output**: 3D mesh (.glb / .obj)
- **Speed**: ~5-30 sec on M4 (estimate, needs testing)
- **RAM**: ~2 GB when loaded (unloaded after use)
- **Backend**: PyTorch with MPS (Apple Silicon)

### 10.2 Quality Pipeline

```
For each new object:

1. FLUX.2 generates image with optimal prompt:
   - "single [object name], isometric view, clean white background,
     simple low-poly style, no text, centered"
   - Isometric view + white background = best input for TripoSR

2. TripoSR converts to 3D:
   - Mesh with texture
   - Automatic UV mapping

3. Post-processing (code):
   - Size normalization (scale to target dimensions)
   - Centering (pivot point at base center)
   - Collision shape generation (convex hull for NavMesh)

4. Apply stylized shader (same as on Bob)

5. Cache in ~/.bob/assets/
```

### 10.3 TripoSR Limitations

| Aspect | Quality |
|--------|---------|
| Simple furniture (table, chair, shelf) | Good |
| Tech (monitor, laptop) | Medium |
| Complex objects (plants, food) | Below average |
| Small details (book, pen) | Weak |

For weak categories — fallback to Godot primitives (BoxMesh + texture = sufficient for a book).

---

## 11. Proof of Concept: Scope and Phases

### Phase 1: Minimal Character in Room (1 week)

**Goal**: Bob stands in an empty room, camera rotates.

- [ ] Install Godot 4.6 + configure Android export
- [ ] Procedural room (walls, floor, ceiling, window) from GDScript
- [ ] Isometric camera with touch rotation
- [ ] MakeHuman → generate Bob headless → import into Godot
- [ ] Stylized shader (basic toon / Sims-like)
- [ ] DirectionalLight3D (window) + OmniLight3D (lamp)
- [ ] Idle animation (breathing + blinking + swaying)
- [ ] Test on Android tablet

**Result**: 3D Bob stands in a lit room, breathes and blinks. Camera rotates around him.

### Phase 2: Walking and Navigation (1 week)

**Goal**: Bob walks around the room, avoiding obstacles.

- [ ] NavMesh for room
- [ ] NavigationAgent3D
- [ ] Procedural walking (leg IK, arm swing, body lean)
- [ ] Walk → Idle transition (AnimationTree state machine)
- [ ] WebSocket: Mac sends "navigate to X" → Bob walks
- [ ] Bob rotation (facing, sideways, back to camera)
- [ ] 1-2 procedural objects (desk, chair) in room via Godot CSG/mesh

**Result**: Bob walks around the room on command from Mac.

### Phase 3: Object Interaction (1-2 weeks)

**Goal**: Bob picks up/puts down objects, sits down.

- [ ] Arm IK (TwoBoneIK3D)
- [ ] Pick up / put down system (reparent + IK)
- [ ] Sit down / stand up (IK hip target + leg bend)
- [ ] Scene State Manager on Mac
- [ ] Simple objects (book = BoxMesh + texture, armchair = CSG)
- [ ] Scenario: walk to desk → pick up book → sit → "read"

**Result**: Bob interacts with objects, scene remembers state.

### Phase 4: AI Content Generation (1-2 weeks)

**Goal**: Bob self-generates furniture and changes environment.

- [ ] TripoSR integration (locally)
- [ ] Pipeline: FLUX.2 → TripoSR → Godot import
- [ ] FLUX.2 generates UV textures for outfits
- [ ] LLM plans furniture arrangement
- [ ] Scene change (cozy room → spaceship bridge)
- [ ] Generated asset caching

**Result**: Bob says "I want a bookshelf" → in 1-2 min the shelf appears in the room.

### Phase 5: Fingers and Complex Animations (1 week)

**Goal**: detailed hands, typing, page turning.

- [ ] FABRIK3D for fingers (5×3 joints per hand)
- [ ] Procedural typing (fingers on keyboard)
- [ ] Procedural page turning (blend shape on book)
- [ ] Gestures on LLM command (thumbs up, pointing, wave)
- [ ] Smooth transitions between hand states

**Result**: Bob types on keyboard with fingers, turns book pages.

---

## 12. Technical Risks

| Risk | Probability | Mitigation |
|------|------------|------------|
| TripoSR won't run on M4 16GB | Medium | Fallback: Godot primitives (BoxMesh + texture) for all objects. Less pretty but works |
| MakeHuman doesn't work headless | Low | Fallback: FLUX.2 → TripoSR for character |
| TripoSR quality too low | Medium | Stylized shader hides artifacts. Simple objects (furniture) look better than complex ones |
| Procedural animations look unnatural | Medium | Iterative parameter tuning (easing, noise amplitude, blend times). Additive layers mask roboticness |
| Realme C71 can't handle 3D | High | Compatibility renderer (OpenGL ES 3.0). If < 20 FPS → need a better tablet |
| RAM shortage on M4 during generation | Medium | Strict on-demand: load FLUX.2 / TripoSR → generate → unload → Ollama back |
| WebSocket latency > 100ms | Low | LAN-only. If Wi-Fi is bad: USB tethering |

---

## 13. PoC Success Criteria

| # | Criterion | How to Verify |
|---|----------|--------------|
| 1 | Bob stands in a 3D room on tablet | Visual: character visible, room rendered |
| 2 | Camera rotates around Bob | Touch gesture: camera rotation |
| 3 | Bob walks to a target point | WebSocket command → Bob walks, avoiding furniture |
| 4 | Bob picks up and carries an object | Pick up → object in hand → walk → put down |
| 5 | Bob sits in a chair | IK adapts pose to specific chair |
| 6 | Animations are smooth, no jitter | Visual: breathing, blinking, smooth transitions |
| 7 | Bob rotates (front/side/back) | Visual: all angles look correct |
| 8 | AI generates new object into scene | "Want a shelf" → FLUX.2 → TripoSR → object in room |
| 9 | Scene persists | Restart → everything in place |
| 10 | Everything works 100% locally | Disconnect internet → everything works (after genesis) |

---

## 14. Technology Stack

| Component | Technology | License | Installation |
|-----------|-----------|---------|-------------|
| 3D Engine | Godot 4.6 | MIT | Binary ~100 MB |
| Character generation | MakeHuman | AGPL | pip install |
| 2D generation (textures, concept art) | FLUX.2 Klein 4B via mflux | Apache 2.0 | pip install + HF model ~22 GB |
| 3D generation (furniture, props) | TripoSR | MIT | pip install + model ~2 GB |
| LLM (decisions, planning) | Ollama (Qwen 7B) | MIT/Apache | ollama pull |
| Mac↔Tablet communication | WebSocket (built-in Godot) | — | Built-in |
| Protocol | JSON | — | Built-in |
| Server | FastAPI (Python) | MIT | pip install |

**Total cost: $0**
**Cloud dependencies: 0** (only Claude Code CLI and Telegram per existing design)

---

## 15. Relation to Main RFC

This PoC replaces the approach from BRIEF.md (2D sprite + mesh deformation). On PoC success:

1. Update RFC section 5.5 (Avatar/Asset Generation): 2D → 3D
2. Update RFC section 4.3 (Godot scene): Polygon2D+Skeleton2D → Node3D+Skeleton3D
3. Add to RFC: Scene State Manager, WebSocket protocol, procedural animation
4. DecisionLog: add D-010 (switch from 2D to 3D) with full rationale
5. Close bob-vr beads related to 2D approach
6. Create new beads for 3D PoC phases

---

## 16. Open Questions

1. **Tablet**: Can Realme C71 (Helio G36) handle 3D? Needs testing. If not — what's the minimum tablet?
2. **MakeHuman headless**: Does it work on macOS ARM? Needs testing.
3. **TripoSR on M4**: Speed and RAM? Needs testing.
4. **Character style**: Vault Boy cartoon or more Sims-like? Depends on MakeHuman + shader results.
5. **Finger scope**: Full 52 bones or simplified hands for PoC?
