# Archive -- Bob's World PoC History

> This document contains obsolete approaches preserved for reference.
> For current state, see `general.md` and `current.md`.
> For decisions that led to pivots, see `decisionLog.md`.

---

## Phase 1: 2D Sprites (2026-03-01)

### What was tried

Text-to-image generation with FLUX.2 Klein 4B for Vault Boy style character sprites.
Three methods were tested for generating visual variations:

1. **Text-to-image** -- full body Bob worked well, but head emotions and hand poses
   produced inconsistent characters (different face each time, some had 4 fingers).
2. **img2img** -- cropping body parts and re-generating at low strength. Head emotions
   worked (strength 0.4), but hand poses failed completely (strength 0.5 preserves
   geometry too much, cannot change open hand to fist).
3. **flux2-edit** -- instruction-based editing ("change right hand to thumbs up").
   Quality was good, identity preserved, but took ~10 min per generation. Unscalable.

### Why it failed

- Every new gesture requires AI image generation (~10 min). Not scalable for living avatar.
- Fixed viewpoint: Bob cannot turn sideways or show back. Fundamental 2D limit.
- No spatial interaction: cannot walk, sit, pick up objects.
- No dynamic lighting -- light is baked into the sprite.
- Every visual change = full regeneration cycle.

### What was preserved

- Vault Boy style decision (D-001) carried forward to all subsequent phases.
- FLUX.2 Klein 4B validated as fast background generator (~25 sec).

**Reference:** D-001 (Vault Boy style), D-002 (mesh deformation), D-003 (12-bone rig),
D-004 (FLUX.2), D-006 (no negative prompts), D-007 (22GB disk), D-008 (benchmarks),
D-009 (LoRA no effect).

---

## Phase 2: Full 3D / MHR / MPFB2 (2026-03-02)

### MHR (Meta Momentum Human Rig) approach

MHR was selected as the primary character generation tool: Apache 2.0, 127 joints,
7 LOD levels, native glTF export. Installation required pixi (pip broken due to
hardcoded CI rpaths).

**What worked:**
- Body mesh generation with identity shape parameters (45 PCA components).
- Toon shader (unshaded mode + FRONT_FACING normal flipping) in Godot.
- Isometric camera with orbit/zoom, procedural room, vertex-normal-offset clothing,
  procedural hair cards (200 cards, 1600 tris).

**What failed critically:**
- No eye sockets (watertight mesh). Manual cutting of 274 faces still looked wrong.
- No real hair, clothing, teeth, or skin textures.
- GltfBuilder exports DEFAULT mesh ignoring identity parameters; no UV export.
- 37% inverted normals. Extremely low-level -- every feature built from scratch.

### MPFB2 (MakeHuman via Blender) approach

Replaced MHR. Blender headless + MPFB2 extension provided everything MHR lacked:
eyes, 100+ hairstyles, 100+ garments, teeth/tongue, skin textures, native GLB export.

**Working pipeline:** `blender --background --python generate_bob.py` produced a
complete 21 MB GLB with 53-bone skeleton, skinned accessories, and idle animation.

**Key technical lessons (carried forward):**
- `apply_mix=True` required when removing shape keys (D-014) -- otherwise accessories
  drift from body mesh.
- Eye material needs simplified node tree for GLTF round-trip (D-015).
- MPFB2 parents accessories to body mesh, not armature -- must re-parent with
  `ARMATURE_AUTO` for bone weights before export (D-016).

### Procedural animation attempts

Two approaches to make Bob sit at a desk both failed:

1. **Manual quaternion bone rotation** (6+ iterations): GLTF-imported bones have
   large non-identity rest rotations. "Rotate thigh forward" requires unknown
   combination of local axes. Result: "Bob-snake" -- floating torso, inverted legs.

2. **SkeletonIK3D** (7+ iterations): Persistent geometry collisions, limb crossing
   due to 180-degree rotation, backward-bending knees. IK solver finds anatomically
   wrong solutions. Blind numeric tuning of 20+ parameters via screenshots.

**Mixamo retargeting** was planned as Approach 3 but never attempted -- superseded
by the pivot to 2D.

### Why 3D was abandoned

- Animation is too hard for AI agent to implement autonomously (blind parameter tuning).
- AI cannot generate arbitrary 3D environments on Apple Silicon (no open-source
  text-to-3D-scene tool works locally).
- The killer feature is unlimited environments, not precise finger animation.

**Reference:** D-010 (2D to 3D pivot), D-011 (MHR selection), D-012 (validation results),
D-013 (MHR to MPFB2), D-014 (shape key fix), D-015 (eye material), D-016 (clothing).

---

## Phase 3: 2.5D Parallax (2026-03-03 -- 2026-03-04)

### Depth Anything V2 validation -- PASSED

Depth estimation worked well: 2.5s inference on 1024x768, ~400 MB RAM, clean
separation of foreground (Bob), mid-ground (furniture), background (wall).
Model: `Depth-Anything-V2-Small-hf`, runtime: HF Transformers + PyTorch MPS.

### Kontext inset-method -- DISCOVERED

Key discovery of this phase: placing Bob reference (192x256) in the top-left corner
of a scene image (1024x768) causes Kontext to understand "place this character in
this scene" and removes the inset. Full resolution output, good identity preservation.
This method carried forward to the current pipeline.

### Why parallax was rejected

All depth-split approaches produced artifacts when Bob was part of the scene:

- **Depth-split with Bob**: Bob spans multiple depth bands, tears apart at different
  parallax speeds.
- **Cutout Bob from background**: black holes visible when layers shift.
- **Blur-inpaint Bob area**: ghost blob in foreground layer.
- **Two-layer minimal parallax**: rembg edge artifacts cause Bob ghost doubling.

**Conclusion:** 2.5D parallax is impossible without quality AI inpainting of the
background behind Bob. The approach was abandoned in favor of 2D point-and-click.

**Reference:** D-017 (return to 2D), D-018 (parallax validation), D-019 (pivot to
point-and-click).

---

## Phase 4: 2D Point-and-Click (2026-03-04 -- current)

This is the current approach. AI generates background scenes and Bob pose sprites;
Godot composes them with tween movement, crossfade transitions, and shader-based
micro-animation (breathing, blinking). Architecture inspired by Monkey Island /
Broken Sword adventure games.

Details in `general.md` and `current.md`.

**Reference:** D-019 (architecture), D-020 (identity persistence via LoRA).

---

## Appendix: 3D VR Concept (RFC)

The original RFC (`RFC-Proof-of-VR-Concept.md`) described a full 3D Sims-like avatar
system: Mac Mini M4 as command server via WebSocket, Android tablet running Godot 4.6
with 3D rendering, isometric camera, NavMesh pathfinding, IK-based procedural animation.

### Key elements from the RFC (now superseded)

- **Architecture**: Mac (FastAPI + Ollama + asset generation) communicates with tablet
  (Godot 3D renderer) via WebSocket JSON protocol. Mac holds scene state as source
  of truth.
- **Character generation**: Blender + MPFB2 headless pipeline producing GLB with
  53-bone skeleton. Appearance customization via shader uniforms (instant) or texture
  generation (FLUX.2, ~60 sec).
- **Animation catalog**: Procedural idle (breathing, swaying, blinking), walking
  (NavMesh + leg IK + arm counter-swing), sitting (IK hip target + knee bend),
  object pickup (hand IK + finger FABRIK), reading, typing -- all planned as
  code-only, no downloaded clips.
- **Props pipeline**: FLUX.2 generates 2D image, TripoSR converts to 3D mesh,
  Godot applies stylized shader. Total: ~30-90 sec per object.
- **Garment research (Section 17)**: Evaluated 6 AI garment tools (ChatGarment,
  DressCode, Garment3DGen -- all CUDA-only), 3 parametric pattern tools
  (GarmentCode, FreeSewing, Costumy -- M4-compatible), and MakeClothes (already
  in MPFB2). Recommended phased strategy from MPFB2 community assets to
  GarmentCode + Claude Code CLI generation.

The RFC was superseded by D-017 (return to 2D) and D-019 (point-and-click pivot).
The garment research remains relevant if 3D is revisited in the future.
