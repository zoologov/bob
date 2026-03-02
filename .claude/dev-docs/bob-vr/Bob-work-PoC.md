# Bob VR — Working at Laptop PoC

## Goal

Bob's 3D avatar sits in an office chair at a desk and types on a laptop keyboard.
Long-term vision: Bob autonomously decides poses and animations (e.g., lie in bed → get up → walk to desk → sit → type).

## Current State (as of 2026-03-03)

### What exists (Phase 1 — bead bob-728, in_progress)

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

## Approach 2: Inverse Kinematics (IK) — NEXT TO TRY

### Concept

Instead of manually computing rotations for each bone in the chain, define
**target positions** for key effectors (hands, feet, pelvis) and let the IK solver
compute all intermediate bone rotations automatically.

### Godot 4 IK Options

1. **SkeletonIK3D** — built-in Godot node
   - Set target position/rotation for end effector (e.g., hand)
   - Solver computes entire bone chain (shoulder → upper arm → forearm → hand)
   - Supports magnet position (hint for elbow direction)

2. **FABRIK** — Forward And Backward Reaching IK
   - Iterative solver, good for chains
   - Available in Godot or implementable

3. **Two-Bone IK** — simple analytical solution for 2-bone chains
   - Perfect for arm (upper arm + forearm) and leg (thigh + calf)
   - Deterministic, no iteration needed

### Proposed Architecture for Sitting Pose

```
Target positions (world space):
├── Pelvis → chair seat center (0.0, 0.48, 0.05)
├── Left hand → laptop keyboard left (−0.12, 0.78, −0.50)
├── Right hand → laptop keyboard right (0.12, 0.78, −0.50)
├── Left foot → floor in front of chair (−0.15, 0.0, −0.20)
└── Right foot → floor in front of chair (0.15, 0.0, −0.20)

IK solves:
├── Arm IK (2-bone): clavicle → upperarm → lowerarm → hand
├── Leg IK (2-bone): pelvis → thigh → calf → foot
└── Spine: interpolate between pelvis and chest target
```

### Why IK should work better

- **Target-based**: specify WHERE hands/feet go, not HOW each bone rotates
- **Bone-agnostic**: IK solver handles complex rest rotations internally
- **Portable**: same approach works for any pose (sitting, standing, reaching)
- **AI-compatible**: LLM can specify targets in world coordinates ("hands on keyboard")
  without understanding quaternion math

### Key questions to resolve

- Does SkeletonIK3D work with runtime-loaded GLB skeletons? (no .tscn pre-configuration)
- Can multiple IK chains coexist on one skeleton? (arms + legs simultaneously)
- How to handle spine/torso (not a simple 2-bone chain)?
- Performance with 4+ IK chains updating per frame?

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
- ✅ Layer 1 (IK): Godot's SkeletonIK3D for environmental adaptation
- ✅ Layer 1 (procedural): Idle overlay works well (breathing, head)
- ⚠️ Layer 2: Needs implementation but is standard game dev
- ❌ Real-time AI bone quaternion generation: not viable

---

## Files Reference

| File | Status | Notes |
|------|--------|-------|
| `godot/scripts/main.gd` | Modified | Loads furniture + work_animation (to be replaced with IK) |
| `godot/scripts/procedural_furniture.gd` | New, works | Keep as-is |
| `godot/scripts/work_animation.gd` | New, broken pose | Replace with IK approach |
| `godot/scripts/idle_animation.gd` | Works | Keep for procedural overlay |
| `/tmp/bone_discovery.gd` | Diagnostic | Run to list all 54 bone names/indices |
