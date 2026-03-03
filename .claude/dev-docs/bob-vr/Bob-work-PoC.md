# Bob VR — "Bob's World" PoC

## Goal

Bob lives in his own world — an "aquarium" that the user observes but doesn't interact with.
Bob autonomously generates his environments (Mars, spaceship bridge, cozy cabin) via AI,
and animates within them. The user watches Bob's life like a digital pet / living screensaver.

**Current direction: Full 2D + Parallax** (see D-017 in DecisionLog.md)

## Current State (as of 2026-03-03)

### What exists (3D phase — to be replaced by 2D)

- `godot/scripts/main.gd` — scene orchestrator, loads Bob GLB at runtime
- `godot/scripts/idle_animation.gd` — procedural idle: breathing, sway, head micro-movements
- `godot/scripts/procedural_room.gd` — floor (walls/ceiling commented out)
- `godot/scripts/camera_rig.gd` — isometric orthographic camera with orbit controls
- `godot/scripts/procedural_furniture.gd` — **NEW**: desk + office chair + laptop from BoxMesh/CylinderMesh
- `godot/scripts/work_animation.gd` — **NEW**: sitting pose + typing attempt (see results below)
- Bob's skeleton: 54 bones (MPFB2 game_engine rig), all discovered and confirmed

### Bone Discovery Results

All 54 bones confirmed via `/tmp/bone_discovery.gd`:
- Body: Root, pelvis, spine_01/02/03, neck_01, head
- Arms: clavicle, upperarm, lowerarm, hand (l/r)
- Legs: thigh, calf, foot, ball (l/r)
- Fingers: thumb/index/middle/ring/pinky × 01/02/03 × l/r (30 finger bones)
- Key finding: bones have large non-identity rest rotations from GLTF import
  (e.g., pelvis: 70° X, thigh_l: -10°/-153°/168°)

### Procedural Furniture (WORKS WELL)

`procedural_furniture.gd` creates:
- **Desk**: 1.2×0.6m tabletop at Y=0.75 + 4 legs, dark wood color
- **Chair**: seat at Y=0.45, backrest, center pedestal, 5 caster arms with wheels
- **Laptop**: base (keyboard) on desk + screen hinged open ~110° with emissive blue glow

All proportions look correct. Furniture is properly positioned.

---

## Approach 1: Manual Quaternion Bone Rotation — FAILED ❌

### What was tried

`work_animation.gd` applies per-bone quaternion offsets on top of initial rest poses:
```gdscript
var base: Quaternion = _init_rot[bone_idx]
skeleton.set_bone_pose_rotation(bone_idx, base * Quaternion(axis, angle))
```

Attempted to set sitting pose by rotating:
- Pelvis: drop Y position
- Thighs: rotate forward ~80° (hip flexion)
- Calves: rotate back ~80° (knee flexion)
- Upper arms: slight forward + adduction
- Lower arms: elbow flexion
- Fingers: curl animation for typing

### Why it failed

1. **Complex pre-existing bone rotations**: GLTF-imported MPFB2 bones have large
   non-trivial rest rotations (thigh_l: -10°, -153°, 168°). Applying
   `Quaternion(Vector3.RIGHT, angle)` doesn't map to intuitive anatomical axes.
   "Rotate thigh forward" requires unknown combination of local axes.

2. **Bone chain cascading**: Each bone rotation affects the entire chain below it.
   Small errors in thigh rotation compound through calf → foot. Without real-time
   visual feedback, calibration is blind trial-and-error.

3. **6+ iterations of screenshot-based tuning** still couldn't achieve natural sitting:
   - Arms went to face instead of desk (wrong rotation direction)
   - Legs bent backwards through the chair
   - Pelvis height never matched seat surface
   - Result: "Bob-snake" — torso floating above desk, legs inverted through chair

4. **Fundamentally unscalable**: Even if we eventually got sitting right through
   brute-force tuning, every new pose (lying, walking, standing up) would require
   the same painful per-bone calibration. This cannot be done by an AI autonomously.

### Conclusion

**Manual quaternion bone rotation is NOT a viable approach** for:
- Complex multi-bone poses (sitting, walking)
- AI-driven autonomous animation
- Any pose that involves the full skeleton (legs + arms + spine)

It works adequately for **small additive offsets on few bones** (idle breathing,
head micro-movements) where errors are small and not visually obvious.

---

## Approach 2: SkeletonIK3D (Inverse Kinematics) — FAILED ❌

### What was tried

Extensive IK experimentation over 7+ iterations using Godot's SkeletonIK3D
(deprecated but functional in 4.6). Test scripts: `/tmp/ik_sitting{1-7}.gd`.

**Research findings:**
- **TwoBoneIK3D** (new Godot 4.6 IKModifier3D system) does NOT work with
  runtime-loaded GLTF skeletons — bones never move despite correct configuration
- **SkeletonIK3D** (deprecated) DOES work — confirmed that `ik.target` uses
  global coordinates (not skeleton-local)

**Configuration that partially worked (v5):**
```
Bob position: Vector3(0.0, -0.38, -0.18), rotation_degrees.y = 180.0
Hand targets (global): Vector3(±0.08, 0.79, -0.48)
Foot targets (global): Vector3(±0.10, 0.03, -0.25)
Arm IK: root=upperarm_l/r, tip=hand_l/r, magnet=(±0.12, -0.3, 0.15)
Leg IK: root=thigh_l/r, tip=foot_l/r, magnet=(0.0, 0.3, -0.5)
Spine lean: Quaternion(Vector3.RIGHT, +0.06) per vertebra (POSITIVE = forward)
Neck tilt: +0.15, Head tilt: +0.12
```

### Why it failed

1. **Persistent geometry collisions**: Torso clips through desk, pelvis through
   chair seat, hands embedded in desk surface. Adjusting positions creates new
   collisions elsewhere.

2. **Limb crossing/mirroring**: Bob is rotated 180°, which flips the X axis.
   `hand_l` bone ends up at world -X, but targets at +X cause arms to cross.
   Same issue with legs — they cross or bend backward instead of forward.
   7 iterations of adjustments couldn't fully resolve this.

3. **Leg anatomy failure**: IK solver consistently finds wrong solutions for
   legs — knees bending backward ("kneeling" instead of sitting), legs crossing
   in X pattern from front view. Magnet hints don't reliably control bend direction
   when skeleton is rotated 180°.

4. **No visual realism**: Even the best iteration (v5) had:
   - Legs at 180° from torso (body faces desk, legs face away)
   - Arms partially embedded in desk surface
   - Pelvis floating above chair seat
   - Alpha artifacts around head (hair transparency)

5. **Fundamentally same problem as Approach 1**: While IK simplifies WHAT to
   specify (positions vs rotations), the blind trial-and-error tuning of
   coordinates is equally painful. An AI agent cannot efficiently tune 20+
   numeric parameters (4 targets × 3 coords + 4 magnets × 3 coords + spine angles)
   through screenshot-based iteration.

### Conclusion

**SkeletonIK3D is NOT viable for full-body sitting pose** in this setup:
- The 180° rotation creates mirroring issues that are hard to debug
- IK solvers find anatomically wrong solutions (backward knees, crossed limbs)
- No collision avoidance — mesh interpenetration everywhere
- Each pose still requires extensive manual coordinate tuning

SkeletonIK3D might work for **small adjustments on top of existing animations**
(e.g., adjust hand position to reach a specific object), but it cannot create
a full sitting pose from scratch.

---

## Approach 3: Hybrid — Mixamo Animations in Godot — SUPERSEDED ⏭️

**Status:** Never attempted. Superseded by D-017 (switch to full 2D).
The 3D approach has fundamental issues beyond animation: AI cannot generate
arbitrary 3D environments (spaceship bridge, Mars surface). 2D generation
via FLUX.2 solves this instantly.

### Concept

Instead of manually posing bones (Approach 1) or manually specifying IK targets
(Approach 2), use **pre-made motion capture animations from Mixamo** and load them
in Godot. Mixamo has a library of professionally created animations including
sitting, typing, idle, and transitions.

### Why this should work

1. **Animations are pre-made by artists**: sitting, typing, walking — all solved
   problems in the animation industry. No need for AI to reinvent bone math.

2. **Mixamo provides retargetable FBX**: download animations for any humanoid
   skeleton, Godot can retarget to our MPFB2 rig via `SkeletonProfileHumanoid`.

3. **Proven approach**: The [Realtime_Avatar_AI_Companion](https://github.com/igna-s/Realtime_Avatar_AI_Companion)
   project successfully uses Mixamo FBX → VRM retargeting in Three.js. Their
   bone mapping + quaternion correction code works.

4. **AI-friendly**: An AI agent can download/select animations from Mixamo library,
   not tune numeric parameters. "Use sitting_idle.fbx" vs "set thigh_l to 0.08 rad".

### Relevant Mixamo animations

| Animation | Mixamo name | Use case |
|-----------|-------------|----------|
| Sitting idle | "Sitting Idle" | Bob at desk, breathing |
| Typing | "Typing" | Bob typing on keyboard |
| Sitting talking | "Sitting Talking" | Future: Bob in conversation |
| Sit down | "Sitting Down" | Transition: standing → sitting |
| Stand up | "Standing Up" | Transition: sitting → standing |

### Technical approach

```
Pipeline:
1. Download FBX from Mixamo (with "Without Skin" option for animation-only)
2. Import FBX into Godot project (godot/assets/animations/)
3. Create bone name mapping: Mixamo names → MPFB2 names
   - mixamorigHips → pelvis
   - mixamorigSpine → spine_01
   - mixamorigLeftArm → upperarm_l
   - etc.
4. Use Godot's AnimationPlayer + SkeletonProfileHumanoid for retargeting
5. Layer procedural overlay on top (breathing, head look-at from idle_animation.gd)
```

### Key bone mapping (Mixamo → MPFB2)

```
mixamorigHips          → pelvis
mixamorigSpine         → spine_01
mixamorigSpine1        → spine_02
mixamorigSpine2        → spine_03
mixamorigNeck          → neck_01
mixamorigHead          → head
mixamorigLeftShoulder  → clavicle_l
mixamorigLeftArm       → upperarm_l
mixamorigLeftForeArm   → lowerarm_l
mixamorigLeftHand      → hand_l
mixamorigRightShoulder → clavicle_r
mixamorigRightArm      → upperarm_r
mixamorigRightForeArm  → lowerarm_r
mixamorigRightHand     → hand_r
mixamorigLeftUpLeg     → thigh_l
mixamorigLeftLeg       → calf_l
mixamorigLeftFoot      → foot_l
mixamorigRightUpLeg    → thigh_r
mixamorigRightLeg      → calf_r
mixamorigRightFoot     → foot_r
```

### Open questions

- Does Godot's FBX importer handle Mixamo animations correctly?
- Does `SkeletonProfileHumanoid` retargeting work with runtime-loaded GLTF?
- Can we apply Mixamo animation to MPFB2 skeleton with different rest poses?
- Alternative: convert Mixamo FBX → glTF/GLB animation, embed in Bob's GLB?
- Can we layer procedural overlay (breathing) on top of Mixamo clip?

### Reference

- [Realtime_Avatar_AI_Companion](https://github.com/igna-s/Realtime_Avatar_AI_Companion) —
  working Mixamo→VRM retargeting in Three.js (bone mapping + quaternion correction)
- Mixamo: https://www.mixamo.com (free Adobe account required)
- Godot retargeting docs: AnimationTree + SkeletonProfileHumanoid

---

---

## Approach 4: Full 2D + Parallax — CURRENT DIRECTION 🎯

### Concept

Bob's world is fully 2D. AI (FLUX.2 Klein 4B via mflux) generates any background
Bob wants. The scene is split into depth layers for parallax effect. Bob is rendered
as a 2D animated character on top.

**Validated:** Mars scene generated in 25 seconds on M1 Max (q4, 4 steps).
Result: `.claude/dev-docs/bob-vr/mars_parallax_concept.png`

### Architecture

```
Fixed camera → User observes "Bob's Aquarium"

Background layers (AI-generated):
├── Far: sky/space/distant landscape (slowest parallax)
├── Mid: terrain/walls/mid-ground objects
├── Near: furniture/props near Bob
└── Foreground: objects in front of Bob (partial occlusion)

Bob layer:
├── 2D animated character (method TBD — see Open Questions)
├── Multiple poses: sitting, standing, walking, typing, lying
├── Smooth transitions between poses
└── Interaction with near-layer objects (sitting on chair, typing on laptop)

Depth separation:
├── Depth Anything V2 → depth map from AI image
├── Split into 3-5 layers by depth
└── Parallax shift on subtle camera movement (if any)
```

### Why this works

1. **Unlimited environments**: FLUX.2 generates anything — Mars, spaceship, cabin, Tokyo café
2. **25-second generation**: Fast enough for Bob to "redecorate" in real-time
3. **No 3D mesh problems**: No IK, no bone rotations, no geometry collisions
4. **Consistent quality**: FLUX.2 output is consistently high quality
5. **M4 16GB compatible**: q4 model uses ~2GB RAM, leaves room for everything else

### Open questions (for next session)

1. **Bob animation method**: How to animate Bob in 2D?
   - Spine 2D / DragonBones (skeletal 2D)
   - AI-generated sprite sheets (consistency problem)
   - Pre-rendered 3D→2D sprites (render MPFB2 Bob from fixed angle)
   - Live2D / Inochi2D (VTuber-style)

2. **Bob-environment interaction**: How does Bob "sit on" a 2D chair?
   - Pre-composed: generate image WITH Bob already in it
   - Layered: Bob sprite placed between background layers
   - Hybrid: near objects (chair, desk) are separate sprites Bob interacts with

3. **Animation transitions**: Walking, sitting down, standing up
   - Sprite sheet approach (pre-rendered frames)
   - Skeletal 2D deformation
   - AI-generated transition frames (consistency?)

4. **Parallax implementation**: Godot 2D or web-based?
   - Godot has ParallaxBackground/ParallaxLayer nodes
   - Could also be HTML5/Canvas based

5. **Style consistency**: Bob must look the same across all environments
   - Vault Boy style (D-001) or new style?
   - How to maintain character identity across generated backgrounds?

### Reference

- Mars concept: `.claude/dev-docs/bob-vr/mars_parallax_concept.png`
- FLUX.2 Klein 4B via `mflux-generate-flux2` (see D-004 in DecisionLog)
- [Realtime_Avatar_AI_Companion](https://github.com/igna-s/Realtime_Avatar_AI_Companion) — reference for VRM/animation approach
- Depth Anything V2 — depth estimation for parallax layer separation

---

## Long-term Vision: AI-Driven Animation

### Architecture (layered)

```
Layer 3 — AI Brain (LLM):
  "I want to sit at the desk and work"
  → produces semantic action sequence

Layer 2 — Animation Controller (state machine):
  idle → walk_to(desk) → sit_down(chair) → type(laptop)
  → selects animation clips + IK targets per state

Layer 1 — Motion Execution:
  Pre-made clips (walk cycle, sit-down transition)
  + IK for environmental adaptation (hand on THIS keyboard, foot on THIS floor)
  + Procedural overlay (breathing, head look-at, finger typing)
```

### What each layer does

| Layer | Responsibility | Technology |
|-------|---------------|------------|
| Brain | Decide WHAT to do | LLM (Claude/Ollama) |
| Controller | Decide HOW to transition | State machine + animation tree |
| Execution | Move bones correctly | Animation clips + IK + procedural |

### What's realistic today

- ✅ Layer 3: LLM can decide actions from context
- ✅ Layer 1 (clips): Mixamo/mocap libraries have sitting, walking, typing clips
- ⚠️ Layer 1 (IK): SkeletonIK3D works but only for small adjustments, not full poses
- ✅ Layer 1 (procedural): Idle overlay works well (breathing, head)
- ⚠️ Layer 2: Needs implementation but is standard game dev
- ❌ Real-time AI bone quaternion generation: not viable
- ❌ Full-body IK from scratch: not viable (too many parameters to tune)

---

## Files Reference

| File | Status | Notes |
|------|--------|-------|
| `godot/scripts/main.gd` | Working | Loads furniture + idle animation |
| `godot/scripts/procedural_furniture.gd` | Working | Desk + chair + laptop |
| `godot/scripts/idle_animation.gd` | Working | Breathing, sway, head micro-movements |
| `godot/scripts/procedural_room.gd` | Working | Floor |
| `godot/scripts/camera_rig.gd` | Working | Isometric camera with orbit |
| `godot/scripts/work_animation.gd` | DELETED | Failed IK approach, removed |
