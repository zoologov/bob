# RFC: Proof of VR Concept — Bob's Virtual Avatar

> **Status:** In Progress (Iteration 2)
> **Date:** 2026-03-02 (updated)
> **Author:** v.zoologov + Claude
> **Context:** Full 3D avatar for Bob. Second iteration after MHR proved insufficient.
> **Reference:** The Sims (isometric view, object interaction, character life simulation)

---

## 1. Problem

### 1.1 Limitations of the 2D Approach

The bob-vr prototype (2D phase) revealed fundamental limitations of sprite-based avatars:

| Problem | Details |
|---------|---------|
| **Hands** | img2img cannot change structural hand pose. flux2-edit works but takes ~10 min per gesture |
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
2. **Zero manual modeling**: no manual 3D work beyond initial setup
3. **Local-first**: everything generated locally (FLUX.2, TripoSR, MakeHuman/MPFB2, procedural code)
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
│  │ LLM decis.  │  │ Object pos   │  │          │  │ • 3D character      │  │
│  │ Generation  │  │ Held items   │  │  events  │  │ • IK animations    │  │
│  └──────┬──────┘  └───────┬───────┘  │◄─────────│  │ • NavMesh          │  │
│         │                 │          │          │  │ • Stylized shader  │  │
│  ┌──────▼──────┐  ┌───────▼───────┐  │          │  │ • Dynamic lighting │  │
│  │ Ollama LLM  │  │ Asset Gen     │  │          │  │ • Scene rendering  │  │
│  │ ~5 GB       │  │               │  │          │  └────────────────────┘  │
│  └─────────────┘  │ Blender       │  │          │                          │
│                   │  + MPFB2      │  │          │  Input: touch, voice     │
│                   │ FLUX.2 (tex)  │  │          │  Output: display, audio  │
│                   │ TripoSR (3D)  │  │          │                          │
│                   └───────────────┘  │          └──────────────────────────┘
└──────────────────────────────────────┘
```

### 3.2 Separation of Concerns

| Task | Runs On | Why |
|------|---------|-----|
| LLM inference (Bob's decisions) | Mac Mini M4 | Needs RAM for model weights |
| 3D asset generation | Mac Mini M4 | FLUX.2 + TripoSR need GPU/RAM |
| Character generation | Mac Mini M4 | Blender + MPFB2 headless |
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
| Blender + MPFB2 (genesis) | ~1.5 GB | On demand, unloaded after |
| FLUX.2 q4 (textures) | ~2.0 GB | On demand, unloaded after |
| TripoSR (3D gen) | ~2.0 GB | On demand, unloaded after |
| **Peak consumption** | **~12.35 GB** | During generation |
| **Headroom** | **~3.65 GB** | |

Key principle: Blender, FLUX.2 and TripoSR are loaded **only when generating new content**, then unloaded. During normal Bob operation they are not needed.

---

## 4. Character Generation (Bob Genesis)

### 4.1 Pipeline: Blender + MPFB2 (Headless)

```
Installation for a new user:

1. Blender (headless, --background --python script.py):
   - MPFB2 plugin creates human character
   - Parameters: height, build, face, skin/hair color
   - LLM chooses parameters or random set
   - Generation: ~10-30 sec

2. MPFB2 provides out of the box:
   ├── Body mesh with full skeleton (~52 bones)
   │   ├── Body: hip → spine → chest → neck → head (5)
   │   ├── Arms: shoulder → upper_arm → forearm → wrist × 2 (8)
   │   ├── Legs: upper_leg → lower_leg → foot × 2 (6)
   │   ├── Face: jaw, eye_L, eye_R, brow (4)
   │   └── Fingers: 5 fingers × 3 joints × 2 hands (30)
   ├── Eyes (separate mesh: sclera, iris, cornea)
   ├── Teeth and tongue
   ├── Hair (100+ mesh hairstyles)
   ├── Clothing (100+ garments: shirts, pants, shoes, etc.)
   ├── Skin textures (diffuse, normal, specular)
   └── Clothing textures

3. Blender exports → GLB/GLTF (native Blender export)

4. Godot loads GLB → applies stylized shader (cel-shading or Sims-like)

5. Cache: model saved locally,
   regeneration only on Bob's explicit request
```

### 4.2 Why Blender + MPFB2

| Feature | MHR (abandoned) | Standalone MakeHuman | Blender + MPFB2 |
|---------|-----------------|---------------------|----------------|
| Eyes | No (watertight mesh) | Yes | Yes |
| Hair | No | Yes (100+) | Yes (100+) |
| Clothing | No | Yes (100+) | Yes (100+) |
| Teeth/tongue | No | Yes | Yes |
| Skeleton | Yes (127 joints) | Yes (game-ready rigs) | Yes (multiple rigs) |
| Skin textures | No UVs in export | Yes | Yes |
| GLB export | Broken (GltfBuilder) | No (MHX2/FBX only) | Native Blender |
| Headless mode | Python API (pixi) | No (GUI-only) | `blender --background` |
| Apple Silicon | Yes (pixi/conda) | Issues (PyOpenGL) | Native (Blender 4.2+) |
| Install | pixi (complex) | pip (GUI app) | brew + extension |
| License | Apache 2.0 | AGPL-3.0 | GPL (Blender) + AGPL (assets) |

### 4.3 Headless Pipeline (Python → Blender → GLB)

Actual working pipeline (`godot/tools/generate_bob.py`):

```python
# generate_bob.py — runs inside Blender headless
# Called via: blender --background --python godot/tools/generate_bob.py

import bpy
from bl_ext.blender_org.mpfb.services.humanservice import HumanService
from bl_ext.blender_org.mpfb.services.assetservice import AssetService

# 1. Create base human with macro details
basemesh = HumanService.create_human(
    scale=0.1,  # MPFB cm → Blender meters
    macro_detail_dict={
        "gender": 1.0, "age": 0.4, "muscle": 0.5, "weight": 0.4,
        "proportions": 0.5, "height": 0.5, ...
        "race": {"caucasian": 1.0, "african": 0.0, "asian": 0.0},
    },
)

# 2. Add assets via AssetService + HumanService
HumanService.add_mhclo_asset(eyes_path, basemesh, asset_type="Eyes", ...)
HumanService.add_mhclo_asset(hair_path, basemesh, asset_type="Hair", ...)
HumanService.add_mhclo_asset(clothes_path, basemesh, asset_type="Clothes", ...)
HumanService.set_character_skin(skin_path, basemesh, skin_type="GAMEENGINE")
HumanService.add_builtin_rig(basemesh, "game_engine")

# 3. Fix materials for GLTF export (alpha modes, backface culling)
# 4. Process modifiers:
#    - Bake shape keys with apply_mix=True (CRITICAL — prevents body/accessory offset)
#    - Remove Armature modifier (no-op in rest pose)
#    - Apply MASK modifiers (Hide helpers, Delete.clothes, Delete.shoes)
# 5. Remove armature object, un-parent children
# 6. Export static GLB (no skeleton, no animations)
bpy.ops.export_scene.gltf(filepath=output, export_format="GLB", export_skins=False, ...)
```

**Execution:**
```bash
blender --background --python godot/tools/generate_bob.py
# Result: godot/assets/bob.glb (~18 MB, static geometry)
```

**Critical lesson learned:** `bpy.ops.object.shape_key_remove(all=True)` must use `apply_mix=True` — otherwise body reverts to basis shape while fitted accessories (hair, clothes) stay at deformed positions, causing visible offset. See DecisionLog D-014.

### 4.4 Appearance Customization (Runtime)

| What Changes | How | Speed |
|-------------|-----|-------|
| Skin / hair color | Shader uniform | Instant |
| Outfit color | Shader uniform | Instant |
| Outfit texture (pattern) | FLUX.2 → UV map | ~60 sec |
| Body shape (proportions) | Bone scale | Instant |
| Hairstyle | Blender re-generation (hair only) | ~10 sec |
| Clothing style (silhouette) | Blender re-generation (clothes) | ~10-30 sec |
| Full character rebuild | Blender headless re-generation | ~30-60 sec |

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
│   └── bob_v1.glb              # Current Bob model (from Blender/MPFB2)
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
        "slot_1": "book_002"
      }
    },
    "desk_001": {
      "position": [2, 0, -2],
      "surface": ["laptop_001"],
      "type": "interactive"
    }
  },
  "bob": {
    "position": [-2, 0, 0],
    "state": "sitting",
    "sitting_on": "armchair_001",
    "holding": {"right_hand": "book_002", "left_hand": null},
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

### 8.1 Approach: Stylized Shader (Configurable)

A flexible stylized shader configurable via parameters:

```
Style spectrum (one shader, different parameters):
├── Cartoon (Vault Boy): 2 shadow bands, bold outline, flat colors
├── Sims-like: soft shadows, subtle outline, warm tones
├── Anime: sharp shadows, colored outlines, vivid colors
└── Painterly: blurred shadows, no outline, brush stroke textures
```

Bob can change rendering style at runtime — it's just shader uniforms.

### 8.2 Toon Shader (Validated)

The toon shader has been validated and works with `render_mode unshaded, cull_disabled` to avoid Godot's Forward Mobile pipeline adding unwanted ambient/indirect light. Manual light calculation in `fragment()`:

```glsl
shader_type spatial;
render_mode unshaded, cull_disabled;

uniform vec3 base_color : source_color;
uniform vec3 shadow_color : source_color;
uniform vec3 light_dir = vec3(-0.5, -0.6, -0.5);
uniform float shadow_threshold = 0.1;
uniform float shadow_smoothness = 0.05;

void fragment() {
    vec3 light_vs = normalize((VIEW_MATRIX * vec4(normalize(light_dir), 0.0)).xyz);
    vec3 n = NORMAL;
    if (!FRONT_FACING) n = -n;  // handle inverted normals
    float NdotL = dot(n, light_vs);
    float intensity = smoothstep(
        shadow_threshold - shadow_smoothness,
        shadow_threshold + shadow_smoothness, NdotL
    );
    ALBEDO = mix(shadow_color, base_color, intensity);
}
```

### 8.3 Camera (Validated)

```
Isometric Camera:
- Projection: Orthographic (removes perspective distortion)
- Angle: 30-45° from above (like The Sims / Diablo)
- Rotation: user can rotate camera around room (touch/mouse)
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

// Expression
{"type": "expression", "face": "happy", "intensity": 0.8}

// New object
{"type": "spawn_object", "id": "bookshelf_001", "mesh": "<base64 glb>",
 "position": [0, 0, -3.5], "properties": {"type": "interactive", "slots": 8}}

// Outfit change
{"type": "outfit_change", "texture": "<base64 png>"}
```

### 9.3 Message Types: Tablet → Mac

```json
// Action complete
{"type": "action_complete", "action": "navigate", "target": "bookshelf_001"}

// User input
{"type": "user_input", "action": "tap", "target": "bob"}

// Voice input
{"type": "voice_input", "audio": "<base64 wav>"}
```

---

## 10. Props Generation: FLUX.2 → TripoSR

### 10.1 TripoSR

- **Authors**: Stability AI + Tripo
- **License**: MIT
- **Input**: single 2D image
- **Output**: 3D mesh (.glb / .obj)
- **Speed**: ~5-30 sec on M4 (estimate, needs testing)
- **RAM**: ~2 GB when loaded (unloaded after use)

### 10.2 Quality Pipeline

```
For each new object:
1. FLUX.2 generates image (isometric view, white background)
2. TripoSR converts to 3D mesh with texture
3. Post-processing: size normalization, centering, collision shape
4. Apply stylized shader
5. Cache in ~/.bob/assets/
```

---

## 11. Proof of Concept: Scope and Phases

### Phase 1: MakeHuman/MPFB2 Character in Room (in progress)

**Goal**: Bob (full character with eyes, hair, clothes) stands in a room.

- [x] Install Blender 5.0+ (headless) + MPFB2 extension (v2.0.14)
- [x] Python script: generate Bob via MPFB2 API headless (`godot/tools/generate_bob.py`)
- [x] Export to GLB (body + hair + clothing + eyes, static geometry)
- [x] Import GLB into Godot 4.6 (runtime via GLTFDocument)
- [x] Toon shader (`godot/shaders/toon.gdshader` — unshaded + manual light)
- [x] Procedural room (`godot/scripts/procedural_room.gd`)
- [x] Isometric camera with orbit/zoom (`godot/scripts/camera_rig.gd`)
- [x] DirectionalLight3D
- [x] Material fixes for GLTF round-trip (alpha modes, backface culling)
- [ ] Fix eye material export (irises appear washed out after GLTF round-trip)
- [ ] Idle animation (breathing + blinking + swaying)
- [ ] Test on Android tablet

**Current outfit**: male_casualsuit01 (blue button-down shirt + jeans + belt + brown shoes)
**Screenshot**: `godot/screenshot/blender_Bob_PoC.png`

**Known issues:**
- Eyes appear pale/washed out after GLTF export (iris texture not preserved correctly)
- Small skin gaps at clothing boundaries (inherent to MASK modifier application)
- Hair uses sparse alpha texture — requires ALPHA_HASH rendering in Godot

**Result**: Full 3D Bob stands in a lit room. Camera rotates around him.

### Phase 2: Walking and Navigation (1 week)

**Goal**: Bob walks around the room, avoiding obstacles.

- [ ] NavMesh for room
- [ ] NavigationAgent3D
- [ ] Procedural walking (leg IK, arm swing, body lean)
- [ ] Walk → Idle transition (AnimationTree state machine)
- [ ] WebSocket: Mac sends "navigate to X" → Bob walks
- [ ] 1-2 procedural objects (desk, chair) in room

**Result**: Bob walks around the room on command from Mac.

### Phase 3: Object Interaction (1-2 weeks)

**Goal**: Bob picks up/puts down objects, sits down.

- [ ] Arm IK (TwoBoneIK3D)
- [ ] Pick up / put down system (reparent + IK)
- [ ] Sit down / stand up (IK hip target + leg bend)
- [ ] Scene State Manager on Mac
- [ ] Scenario: walk to desk → pick up book → sit → "read"

### Phase 4: AI Content Generation (1-2 weeks)

**Goal**: Bob self-generates furniture and changes environment.

- [ ] TripoSR integration (locally)
- [ ] Pipeline: FLUX.2 → TripoSR → Godot import
- [ ] FLUX.2 generates UV textures for outfits
- [ ] Scene change (cozy room → spaceship bridge)

### Phase 5: Fingers and Complex Animations (1 week)

**Goal**: detailed hands, typing, page turning.

- [ ] FABRIK3D for fingers (5×3 joints per hand)
- [ ] Procedural typing (fingers on keyboard)
- [ ] Gestures on LLM command (thumbs up, pointing, wave)

---

## 12. Technical Risks

| Risk | Probability | Mitigation |
|------|------------|------------|
| MPFB2 Python API doesn't work headless | Medium | Blender Python API is well-documented; fallback to bpy operators |
| MPFB2 GLB export loses skeleton/weights | Low | Blender's GLTF exporter is mature and widely used |
| TripoSR won't run on M4 16GB | Medium | Fallback: Godot primitives (BoxMesh + texture) |
| Procedural animations look unnatural | Medium | Iterative tuning (easing, noise, blend times) |
| Realme C71 can't handle 3D | High | Compatibility renderer (OpenGL ES 3.0). If < 20 FPS → need better tablet |
| RAM shortage on M4 during generation | Medium | Strict on-demand: load Blender → generate → kill process |

---

## 13. PoC Success Criteria

| # | Criterion | How to Verify |
|---|----------|--------------|
| 1 | Bob stands in a 3D room on tablet | Visual: character visible, room rendered |
| 2 | Camera rotates around Bob | Touch gesture: camera rotation |
| 3 | Bob has eyes, hair, clothing | Visual: full character, not just body mesh |
| 4 | Bob walks to a target point | WebSocket command → Bob walks |
| 5 | Bob picks up and carries an object | Pick up → object in hand → walk → put down |
| 6 | Bob sits in a chair | IK adapts pose to specific chair |
| 7 | Animations are smooth, no jitter | Visual: breathing, blinking, transitions |
| 8 | AI generates new object into scene | FLUX.2 → TripoSR → object in room |
| 9 | Everything works 100% locally | Disconnect internet → everything works |

---

## 14. Technology Stack

| Component | Technology | License | Installation |
|-----------|-----------|---------|-------------|
| 3D Engine | Godot 4.6 | MIT | `brew install godot` |
| Character generation | Blender + MPFB2 | GPL + AGPL | `brew install blender` + Blender extension |
| 2D generation (textures) | FLUX.2 Klein 4B via mflux | Apache 2.0 | `uv tool install mflux` |
| 3D generation (props) | TripoSR | MIT | `pip install triposr` |
| LLM (decisions) | Ollama (Qwen 7B) | MIT/Apache | `ollama pull` |
| Communication | WebSocket (built-in Godot) | — | Built-in |
| Server | FastAPI (Python) | MIT | `pip install fastapi` |

**Total cost: $0**
**Cloud dependencies: 0** (only Claude Code CLI and Telegram per existing design)

---

## 15. Relation to Main RFC

This PoC replaces the 2D approach from the main RFC. On PoC success:

1. Update RFC section 5 (Avatar): Skeleton2D → Skeleton3D + Blender/MPFB2
2. Update RFC section 5.4.2 (Asset Generation): separate body parts → full character via MPFB2
3. Add to RFC: Scene State Manager, WebSocket protocol, procedural animation
4. DecisionLog: see D-010 (2D→3D), D-011 (MHR attempt), D-013 (MHR→MakeHuman/MPFB2)

---

## 16. Open Questions

1. ~~**MPFB2 headless API**~~ **RESOLVED**: Works via `bl_ext.blender_org.mpfb.services.humanservice.HumanService` and `AssetService`. See `godot/tools/generate_bob.py`.
2. **Tablet**: Can Realme C71 (Helio G36) handle 3D? Needs testing.
3. **TripoSR on M4**: Speed and RAM? Needs testing.
4. ~~**Character style**~~ **RESOLVED**: Realistic MPFB2 character with skin textures. Toon shader available but currently using StandardMaterial3D (GLTF default).
5. **Rig compatibility**: Does MPFB2's game-ready rig work well with Godot's IK solvers? (Currently exporting static geometry without skeleton)
6. ~~**GLB size**~~ **RESOLVED**: ~18 MB for full character (body + clothes + hair + eyes + textures, static geometry).
7. **Eye material export**: MPFB2 eye materials appear washed out after GLTF round-trip. Iris/pupil barely visible. Needs investigation.

---

## Appendix A: Previous Attempts Summary

### A.1 2D Sprite Approach (2026-03-01, abandoned)

**What was tried:**
- FLUX.2 Klein 4B text-to-image for Vault Boy style character
- img2img for head emotions (worked) and hand poses (failed)
- flux2-edit for structural hand changes (worked but 10 min/pose)

**Why abandoned:** Fixed viewpoint, no spatial interaction, every visual change requires AI regeneration. See DecisionLog D-010.

### A.2 MHR (Meta Momentum Human Rig) Approach (2026-03-02, abandoned)

**What was tried:**
- MHR body generation via pixi (pip broken on macOS ARM64)
- Masculine body with identity PCA: BS[0]=-2.5, BS[1]=-1.5 (shoulder/hip ratio 1.77)
- Toon shader development (unshaded mode with FRONT_FACING normal flipping)
- Eye socket cutting from watertight mesh (trimesh, 274 faces removed)
- Procedural eyes (sclera + iris + pupil spheres with blink animation)
- Vertex-normal-offset clothing (shirt 5605 verts, pants 1668 verts)
- Procedural hair cards (200 cards, 1600 tris)

**What worked:**
- MHR body mesh generation (127 joints, 7 LODs)
- Toon shader in Godot (unshaded + manual light calculation)
- Isometric camera with orbit/zoom
- Procedural room (floor, walls, window)
- Vertex-normal-offset clothing
- Hair cards generation

**Why abandoned:**
- **No eyes** — mesh is watertight, no eye socket holes. Had to cut holes manually, eyes still looked wrong ("like a monster")
- **No hair** — only procedural hair cards (flat textured ribbons), no real hairstyles
- **No clothing** — only vertex-normal-offset (body shape pushed outward), no real garments
- **No teeth/tongue** — not present in mesh
- **No skin textures** — GltfBuilder doesn't export UVs despite mesh having them
- **GltfBuilder exports DEFAULT mesh** — ignores identity shape parameters, exports base body
- **37% inverted normals** — requires special shader handling
- **Complex pipeline** — every feature requires manual implementation from scratch
- **pip broken** — pymomentum-cpu has hardcoded CI rpaths, must use pixi/conda

**Key technical findings preserved:**
- Toon shader must use `render_mode unshaded` to avoid Godot's Forward Mobile adding unwanted light
- `FRONT_FACING` check for inverted normals is better than `abs(NdotL)` (avoids dark artifacts)
- MHR units are centimeters (÷100 for Godot meters)
- Ambient light must be disabled when using unshaded toon shader

See DecisionLog D-011, D-012, D-013 for full details.
