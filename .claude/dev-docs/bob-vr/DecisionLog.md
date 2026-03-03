# Decision Log — Bob Avatar PoC (bob-vr)

> Decisions made during prototype validation. Feeds back into RFC updates.
> Format: numbered, with rationale and RFC impact.

---

## D-001: Visual Style — Vault Boy over Fleischer Rubber Hose

**Date:** 2026-03-01
**Context:** RFC specifies "1930s Fleischer rubber hose" style, but Bob needs to sit at desk, type on laptop, tap fingers — requires human-like proportions and visible fingers.
**Decision:** Switch to Vault Boy / Pip-Boy (Fallout) style.
**Rationale:**
- Stylized but human-proportionate (not noodle limbs)
- Visible fingers enable typing/tapping animations
- Clean bold outlines + flat colors = reliable SD generation
- Plenty of reference material for LoRA training
**RFC impact:** Update style references in sections 5.5, 4.3, performance tables.

---

## D-002: Animation Architecture — Mesh Deformation over Rigid Sprites

**Date:** 2026-03-01
**Context:** RFC describes assembling character from 6-10 separate PNG sprites. This always looks like a "paper doll" with visible seams at joints.
**Decision:** Use mesh deformation (Polygon2D + Skeleton2D in Godot 4) — one continuous image deformed by weighted bone mesh.
**Rationale:**
- No visible seams or joints
- Smooth natural movement like Live2D / VTuber
- One SD-generated image instead of 6-10 separate parts
- Hybrid 3-layer approach (body mesh + head swap + hand swap) handles expression/gesture changes
**Status:** Superseded by D-010 (full 3D approach).

---

## D-003: 12-Bone Skeleton Rig

**Date:** 2026-03-01
**Context:** Need enough bones for typing/sitting/walking but not so many that rigging becomes unreliable.
**Decision:** 12-bone rig: hip → spine → chest → neck/head, shoulders → elbows → wrists, hips → knees → ankles.
**Status:** Superseded by D-010 (52-bone 3D skeleton with fingers).

---

## D-004: SD Model — FLUX.2 4B over SD 1.5 / SDXL

**Date:** 2026-03-01
**Context:** RFC specifies SD 1.5 (lightweight) and SDXL (heavy) via mflux. But mflux v0.16.6 dropped SD 1.5/SDXL support entirely — only supports FLUX, Z-Image, FIBO, etc.
**Decision:** Use FLUX.2 4B (Jan 2026) as single model for both profiles.
**Rationale:**
- mflux no longer supports SD 1.5 or SDXL — no choice but to migrate
- FLUX.2 4B is the smallest/fastest model in mflux
- q4 quantization (~2 GB) → replaces SD 1.5 in LIGHTWEIGHT_GEN profile
- q8 quantization (~4 GB) → replaces SDXL in HEAVY_GEN profile (actually smaller!)
- Newer model = better quality than SD 1.5/SDXL
- Single model architecture simplifies ModelManager (same model, different quantization)
**RAM budget (Mac Mini M4 16 GB, 12.5 GB ML budget):**
- LIGHTWEIGHT_GEN: Ollama 7B+0.5B (4.9) + FLUX.2-q4 (2.0) + Guard (0.6) + CLIP (0.4) = ~7.9 GB
- HEAVY_GEN: Ollama 0.5B (0.5) + FLUX.2-q8 (4.0) + Guard (0.6) = ~5.1 GB
**RFC impact:** Update tech stack table in 5.5, ModelManager profiles in 3.2.4, config/bob.yaml.

---

## D-005: Prototype on MacBook Pro M1 Max, Target Mac Mini M4

**Date:** 2026-03-01
**Context:** Mac Mini M4 is in delivery. Prototype must validate on current hardware but be designed for target.
**Decision:** Develop and test on MacBook Pro 16" M1 Max, but use target model (FLUX.2 4B) and target quantization levels.
**Rationale:**
- M1 Max has more RAM (32+ GB) — no constraint during development
- But using same model/quantization ensures results translate to M4
- Performance will be similar (both Apple Silicon, similar GPU perf)
**RFC impact:** None — deployment target unchanged.

---

## D-006: FLUX.2 Distilled — No Negative Prompts, No CFG Guidance

**Date:** 2026-03-01
**Context:** During Phase 1 implementation, discovered FLUX.2 Klein (distilled) models reject both `--negative-prompt` and `--guidance` flags at runtime. Only base models support these.
**Decision:** Use positive-only prompts with detailed descriptions. No CFG guidance (implicit guidance=1.0).
**Rationale:**
- Distilled models are pre-optimized for 4-step inference — guidance is baked in
- Prompt engineering shifts to describing what we WANT precisely, not what to avoid
- Built-in `--lora-style illustration` may compensate for lack of negative prompt control
**RFC impact:** Update AssetGenerator prompt templates — remove negative_prompt field for FLUX.2.

---

## D-007: FLUX.2 Full-Size Model is ~22 GB (not ~4 GB as estimated)

**Date:** 2026-03-01
**Context:** We estimated FLUX.2 4B at ~4 GB (4B params × 1 byte at INT8). Actual download: ~22 GB (FP16 weights + VAE + text encoders + tokenizer). Quantization happens at load time, not on disk.
**Decision:** Accept 22 GB disk footprint. Model cached in `~/.cache/huggingface/`. Quantized to q4 at runtime (~2 GB active RAM).
**RFC impact:** Update disk space requirements in tech stack table.

---

## D-008: Generation Performance — Actual Benchmarks on M1 Max

**Date:** 2026-03-01
**Context:** Phase 1 generation completed. Actual timing data.
**Measurements (FLUX.2 4B, q4, M1 Max):**
- 1024×1024 (full body): ~60 sec (4 steps × 15 sec/step)
- 512×512 (head): ~20 sec (4 steps × 5 sec/step)
- 256×256 (hand): ~11 sec (4 steps × 3 sec/step)
- flux2-edit (1024×1024, 8 steps): ~10 min
**Decision:** Accept these timings. Slower than RFC's SD 1.5 estimates but quality is dramatically better.
**RFC impact:** Update generation performance table.

---

## D-009: LoRA Illustration Style — No Visible Effect on FLUX.2

**Date:** 2026-03-01
**Context:** Tested mflux built-in `--lora-style illustration` with FLUX.2 Klein 4B. Output was virtually identical to base model.
**Decision:** Do not use built-in LoRA for style. Positive prompt alone is sufficient.
**RFC impact:** Update LoRA strategy — base style via prompt, custom LoRA only for evolved styles.

---

## D-010: Switch from 2D Sprites to Full 3D — The Pivotal Decision

**Date:** 2026-03-01
**Context:** After completing 2D Phase 1 (image generation) and attempting 2D Phase 2 (hand poses), fundamental limitations of the 2D approach became clear.

### What We Tried (2D Approach)

**Text-to-image generation (FLUX.2 Klein 4B via mflux):**
- Generated full body Bob in Vault Boy style — excellent results (seed 123 best)
- Generated 6 head emotions via text-only — inconsistent faces (different character each time)
- Generated 7 hand poses via text-only — inconsistent (some had 4 fingers, different styles)

**img2img approach (cropping base + re-generation):**
- Cropped head from base body → img2img with strength 0.4 for emotions — good consistency
- Cropped hands from base body → img2img with strength 0.5 for poses — FAILED
- Problem: strength 0.5 preserves source geometry too much, all hand poses look identical
- The model cannot structurally change hand pose (open → fist) at low strength

**flux2-edit approach (instruction-based editing):**
- "Change only the right hand to thumbs up" — WORKED WELL
- Distinct poses (thumbs up, fist, pointing), character identity preserved
- Problem: ~10 min per generation on M1 Max (8 steps in edit mode)
- On M4 16GB would be similar or worse, AND conflicts with LLM RAM budget

### Why 2D Cannot Work for Bob's Requirements

1. **Hands**: Every new gesture requires AI image generation (~10 min). Not scalable.
2. **Fixed viewpoint**: Bob cannot turn sideways or show back. Fundamental 2D limit.
3. **No spatial interaction**: Cannot walk to shelf, pick up book, sit in chair.
4. **Every visual change = regeneration**: New outfit = 60 sec, new gesture = 10 min.
5. **No dynamic lighting**: Light is baked into the sprite.
6. **No depth**: Parallax is an illusion, not real space.

### Decision: Full 3D with Procedural Everything

**Architecture:** Godot 4.6 (3D) on Android tablet + Mac Mini M4 as command server via WebSocket.

**Key principles:**
- **Zero manual modeling**: MakeHuman for character, TripoSR for props, procedural code for room
- **Zero downloaded assets**: Everything generated by software dependencies (pip install), not asset libraries
- **Zero cloud APIs**: FLUX.2 + TripoSR + MakeHuman all run locally
- **100% procedural animations**: IK-based (Godot 4.6 has 7 IK solvers), no downloaded animation clips
- **Sims-like interaction**: NavMesh pathfinding, object pick-up/put-down, sitting, walking

**Why this solves every 2D problem:**
- Hands = 52-bone skeleton with IK. New gesture = JSON data (instant), not image generation
- Viewpoint = 3D camera. Bob rotates freely.
- Spatial interaction = NavigationAgent3D + IK. Walk to any object, interact with it.
- Visual changes = shader uniforms (instant) or texture swap (~60 sec for FLUX.2 texture)
- Lighting = real-time DirectionalLight3D + OmniLight3D
- Depth = true 3D with isometric camera

**Supersedes:** D-002 (mesh deformation), D-003 (12-bone 2D rig)
**RFC impact:** Major rewrite of sections 4.3, 5.5. Add Scene State Manager, WebSocket protocol, procedural animation system. See RFC-Proof-of-VR-Concept.md for full specification.

---

## D-011: Replace MakeHuman with MHR/Anny — Character Generation Pipeline

**Date:** 2026-03-02
**Context:** RFC specified MakeHuman for character generation. Deep research revealed it cannot run headless (GUI-only, PyOpenGL+PyQt5). The abandoned CLI fork requires Python 2.7. Apple Silicon compatibility issues on macOS 15.

### What We Researched

**MakeHuman (rejected):**
- PyPI package (`pip install makehuman`) installs full GUI app, not a library
- No headless/scriptable mode for batch character generation
- Severin Lemaignan's CLI fork — Python 2.7 only, unmaintained
- Apple Silicon: no native ARM64 build, known macOS 15 issues

**Alternatives evaluated (19+ tools across 7 categories):**
- Parametric body models: SMPL, SMPL-X, SMPL+H, STAR, SUPR, SKEL
- AI-based: DreamAvatar, HumanGaussian, StdGEN, IDOL (all need NVIDIA)
- Auto-riggers: UniRig, Puppeteer (need NVIDIA)
- Datasets: Khronos samples, OpenGameArt CC0, En3D library

### Decision: MHR (primary) + Anny (backup)

**MHR (Meta Momentum Human Rig):**
- Apache 2.0, no registration
- 127 joints with finger bones
- Native glTF + FBX export (huge advantage)
- 7 LOD levels (73K → 595 vertices) — ideal for mobile
- 45 shape + 204 pose + 72 expression parameters
- conda-forge has osx-arm64 packages
- SMPL/SMPL-X conversion built-in

**Anny (NAVER Labs, backup):**
- Apache 2.0 (code) + CC0 (assets), no registration
- `pip install anny` — simplest install
- 163 bones, 564 intuitive phenotype parameters
- UV mapping inherited from MakeHuman
- No native glTF export (needs pygltflib manual construction)

**Critical finding: both output NAKED body only.** No clothing, hair, beard, eyebrows, skin textures.

### Clothing + Hair Pipeline

Since no single tool provides a dressed character with hair on Apple Silicon:

| Component | Tool | Install |
|-----------|------|---------|
| Clothing patterns | GarmentCode / pygarment | `pip install pygarment` |
| Cloth draping | NVIDIA Warp (CPU mode) | `pip install warp-lang` |
| Clothing textures | FLUX.2 via mflux | `uv tool install mflux` |
| Scalp hair | Procedural hair cards (Python + trimesh) | `pip install trimesh` |
| Hair textures | FLUX.2 via mflux | already installed |
| Hair physics | SpringBoneSimulator3D | Godot 4.4+ built-in |
| Beard/stubble | ShellFurGodot addon | Godot addon |
| Eyebrows | Alpha-textured decals or shell fur | Godot |

All strand-based ML hair tools (DiffLocks, Perm, CT2Hair) are **blocked** — require NVIDIA CUDA.

**Status:** All components need validation. See 3D-VR-Validation.md for step-by-step plan.
**Supersedes:** MakeHuman in RFC section 14 tech stack.
**RFC impact:** Update character generation section, add clothing/hair pipeline.

---

## D-012: 3D Pipeline Validation Results — Confirmed Architecture

**Date:** 2026-03-02
**Context:** Ran V-01 through V-07 validation steps from 3D-VR-Validation.md.

### Results Summary

| Step | Component | Result | Key Finding |
|------|-----------|--------|-------------|
| V-01 | MHR body generation | **PASS** | 127 joints, 7 LODs, pixi install required (pip broken) |
| V-01b | Anny (backup) | SKIPPED | MHR works, not needed |
| V-02 | Clothing (GarmentCode) | **PARTIAL** | pygarment FAIL (CGAL), normal-offset fallback WORKS |
| V-03 | Hair cards | **PASS** | 200 cards in 14ms, 1600 tris, GLB export |
| V-04 | Shell fur (beard) | **PARTIAL** | ShellFurGodot is Godot 3 only, Squiggles Fur has headless issues |
| V-05 | SpringBoneSimulator3D | **PASS** | 40 API methods, exists in Godot 4.6.1 |
| V-06 | Skinned GLB import | **PASS** | Full skeleton imports, bones controllable |
| V-07 | Full integration | **PASS** | All components load together, 19934 total verts |

### Confirmed Architecture

**Body:** MHR via pixi (NOT pip), LOD 2 for dev (10K verts), LOD 4-5 for mobile (1-2.5K verts)
**Clothing:** Vertex-normal-offset (simple, instant, works). GarmentCode deferred to production.
**Hair:** Procedural hair cards (Python + trimesh), FLUX.2 textures for alpha-cutout
**Facial hair:** Alpha-textured decals for PoC, Squiggles Fur for production
**Hair physics:** SpringBoneSimulator3D (Godot built-in)
**Export format:** .glb via pymomentum GltfBuilder (body+skeleton) or trimesh (clothing/hair)

### Critical Finding: pip vs pixi

`pymomentum-cpu` pip wheel has hardcoded CI rpaths (`/Users/runner/work/momentum/...`) for native libs (libezc3d, libre2, liburdfdom, libdispenso). **Must use pixi** or conda-forge for native deps. TorchScript model (`mhr_model.pt`, 664 MB) works without pymomentum as lightweight alternative (LOD 1 only, no skeleton export).

**RFC impact:** Update installation instructions, add pixi requirement, update clothing approach.

---

## D-013: MHR Abandoned — Switching to MakeHuman/MPFB2 via Blender

**Date:** 2026-03-02
**Context:** After spending a full session implementing the MHR-based 3D avatar (body generation, toon shader, eye sockets, clothing, hair), the approach proved too low-level. MHR provides only a naked watertight mesh — every feature (eyes, hair, clothing, textures) must be built from scratch.

### What MHR Could NOT Do

| Feature | Problem |
|---------|---------|
| **Eyes** | Mesh is watertight — no eye sockets. Had to manually cut 274 faces from mesh via trimesh. Procedural eyes (sclera+iris+pupil spheres) still looked like "a monster" |
| **Hair** | No hair system at all. Procedural hair cards (flat textured ribbons) are not real hairstyles |
| **Clothing** | No clothing system. Vertex-normal-offset (pushing body surface outward by 5mm) is not real clothing |
| **Teeth/tongue** | Not present in mesh |
| **Skin textures** | GltfBuilder does NOT export UVs, despite mesh having them (11388 UVs, full [0,1] range) |
| **GLB export** | GltfBuilder exports DEFAULT body shape, ignoring identity parameters. Trimesh export has correct vertices but no skeleton |
| **Normals** | 37% of normals are inverted — requires special shader handling |
| **pip install** | pymomentum-cpu has hardcoded CI rpaths — must use pixi/conda, not pip |

### What MHR Could Do (preserved knowledge)

- Body mesh generation with 127 joints (7 LODs, from 73K to 595 vertices)
- Identity shape parameters (45 PCA components) — masculine body with BS[0]=-2.5, BS[1]=-1.5 gives shoulder/hip ratio 1.77
- Expression blendshapes (72 params) — verified to change face visibly
- Pose parameters (204 params) — verified to change pose

### Decision: Switch to MakeHuman/MPFB2 via Blender Headless

**MakeHuman + MPFB2** provides everything MHR lacks:

| Feature | MHR | MakeHuman/MPFB2 |
|---------|-----|----------------|
| Eyes | No | Yes (separate meshes: sclera, iris, cornea) |
| Hair | No | Yes (100+ mesh hairstyles) |
| Clothing | No | Yes (100+ garments with proper fit) |
| Teeth/tongue | No | Yes |
| Skin textures | No UV export | Yes (diffuse, normal, specular maps) |
| GLB export | Broken | Native Blender GLTF exporter |
| Headless mode | pixi only | `blender --background --python` |
| Apple Silicon | pixi/conda | Native Blender 4.2+ |

**Pipeline:**
```
Python script → subprocess.run(["blender", "--background", "--python", "generate_bob.py"]) → GLB → Godot
```

**Preserved from MHR work:**
- Toon shader (unshaded mode + FRONT_FACING normal handling) — general, reusable
- Camera rig (isometric orbit + zoom) — general, reusable
- Procedural room (floor, walls, window) — general, reusable
- Lighting setup (single directional, ambient disabled) — general, reusable

**Discarded:**
- All MHR-specific code (diagnose_body.py, generate_male_body.py, test_*.py)
- MHR assets (mhr_model.pt, body GLBs, hair cards GLB, clothing GLBs)
- MHR repo (5.7 GB validation/mhr_repo/)
- Eye socket cutting code
- Vertex-normal-offset clothing code
- Procedural hair cards code

**RFC impact:** Updated RFC-Proof-of-VR-Concept.md section 4 (Character Generation) to use Blender + MPFB2.

---

## D-014: Shape Key apply_mix — Root Cause of Mesh Offset in GLB Export

**Date:** 2026-03-02
**Context:** After switching to MPFB2, the exported GLB had all accessories (hair, eyes, clothes) visually offset from the body. The character appeared to have clothes floating off shoulders, no visible hair, and eyebrow smudges on forehead.

### Investigation (2 sessions)

Extensive debugging proved:
- All mesh positions in GLB are (0,0,0) — no node-level offset
- Vertex bounding boxes in GLB match exactly between Blender and Godot
- Armature modifier is a true no-op in rest pose (diff=0.000000)
- GLTF exporter preserves data correctly
- Godot imports data correctly

### Root Cause Found

**`bpy.ops.object.shape_key_remove(all=True)` defaults to `apply_mix=False`.**

MPFB2 creates the body mesh with 7 shape keys (macro details: gender, age, muscle, weight, etc.) with non-zero values. Accessories (hair, clothes, eyes) are **fitted to the deformed body** (shape keys applied). When `shape_key_remove(all=True, apply_mix=False)` is called, the body mesh **reverts to basis shape**, but accessories keep their positions fitted to the deformed shape. This creates a visible offset between body and everything else.

### Fix

One-line change: `apply_mix=True`

```python
# BEFORE (broken): body reverts to basis, accessories stay at deformed positions
bpy.ops.object.shape_key_remove(all=True)

# AFTER (fixed): body keeps current deformed shape, matches accessories
bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
```

### Additional Fixes in Same Session

- **Material alpha export**: MPFB2 materials have alpha connections that cause GLTF exporter to use BLEND mode for everything. Fix: disconnect Alpha input for opaque materials, set CLIP mode with low threshold (0.05) for hair/eyebrows/eyelashes.
- **Godot alpha rendering**: Use `TRANSPARENCY_ALPHA_HASH` (stochastic) instead of `ALPHA_SCISSOR` (binary cutoff) for sparse-alpha textures like hair strands.
- **Backface culling**: Set `CULL_BACK` for opaque materials, `CULL_DISABLED` for alpha materials.

**RFC impact:** Updated generate_bob.py pipeline. Phase 1 character rendering now works correctly.

---

## D-015: Eye Material Fix — Preserve Alpha for Cornea Transparency

**Date:** 2026-03-02
**Context:** After GLB export, Bob's eyes appeared as "zombie eyes" — pale blue/white with barely visible iris/pupil.

### Root Cause

`fix_blend_modes()` treated eye mesh ("high-poly") as opaque, disconnecting its Alpha input from the Principled BSDF. MPFB2 high-poly eyes have layered geometry (sclera + iris + cornea) where the cornea is a transparent outer shell over the iris. Disconnecting alpha made the cornea opaque, blocking the iris beneath.

Additionally, the MPFB2 eye material has a `diffuseIntensity` MIX_RGB node between the texture and BSDF. Analysis showed Factor=1.0, Color1=white — a pure pass-through. But the GLTF exporter can't represent intermediate mix nodes, so we simplify it before export.

### Fix

1. Added `simplify_eye_material()` — removes pass-through MIX_RGB, connects texture directly to BSDF
2. Added `"high-poly"` to `alpha_meshes` set in `fix_blend_modes()` — preserves cornea alpha
3. Eyes now export with alpha (MASK mode in GLTF), rendered correctly after round-trip

**RFC impact:** Removed eye material from known issues.

---

## D-016: Clothing Switch — casualsuit04 over casualsuit01

**Date:** 2026-03-02
**Context:** `male_casualsuit01` (button-down shirt + jeans) had a visible gap in the pants mesh near the right ankle. The gap is a defect in the MakeHuman clothing asset itself (present before modifier application), not caused by our pipeline.

### Decision

Rather than implementing complex mesh deformation hacks (vertex shrinking, gap filling), switched to `male_casualsuit04` (t-shirt + jeans) which has no such artifacts. This aligns with the PoC principle of automated pipeline — no manual mesh fixes.

All 8 male outfit options were rendered and compared. casualsuit04 chosen for clean mesh, good coverage, and appropriate casual style.

**RFC impact:** Updated default outfit in generate_bob.py.

---

## D-017: Return to Full 2D + Parallax — The Second Pivot

**Date:** 2026-03-03
**Context:** After D-010 (switch to 3D), spent two sessions attempting to make Bob sit at a desk:
- Approach 1 (manual quaternion bone rotation): 6+ iterations, legs bent backwards, "Bob-snake"
- Approach 2 (SkeletonIK3D): 7+ iterations, legs crossing, kneeling instead of sitting, geometry collisions
- Approach 3 (Mixamo + Godot retargeting): planned but never attempted

Additionally, fundamental limitation discovered: **AI cannot generate arbitrary 3D environments.**
No open-source text-to-3D-scene tool works on Apple Silicon (Holodeck needs GPT-4 API, Text2Room is NVIDIA-only, Infinigen only does realistic interiors). Bob cannot "dream up" a spaceship bridge or Mars surface in 3D.

### Decision: Full 2D + Parallax

**Architecture:**
- **Backgrounds:** FLUX.2 Klein 4B (via mflux) generates any 2D scene Bob wants
- **Depth:** Depth Anything V2 separates image into parallax layers
- **Bob:** 2D animated character on top of parallax layers (animation method TBD)
- **Camera:** Fixed — user observes "Bob's Aquarium" without interaction

**Validation:**
- Generated Mars scene in 25 seconds (1024x768, q4, 4 steps, M1 Max)
- Quality: professional concept art level
- Result: `.claude/dev-docs/bob-vr/mars_parallax_concept.png`

**Why 2D wins this time (different from D-010):**
- D-010 rejected 2D because hands/gestures needed per-image AI generation (~10 min each)
- New insight: the ENVIRONMENT is the killer feature, not hand poses
- Bob's ability to "imagine" any world (Mars, spaceship, cabin) is more valuable than precise finger animation
- 2D background generation is instant and unlimited
- 3D character animation is too hard for AI agent to implement autonomously

**What's different from the original 2D approach (pre-D-010):**
- Original: 2D sprites assembled from parts, parallax room backgrounds
- New: AI-generated full scene backgrounds, Bob as animated character layer
- Original failed on hand consistency; new approach sidesteps this with simpler animation
- Parallax from depth estimation (Depth Anything V2) vs manual layer painting

**Supersedes:** D-010 (switch to 3D), D-011 (MHR character), D-012 (3D validation), D-013 (MPFB2)
**RFC impact:** Major rewrite needed — 2D architecture replaces 3D Godot pipeline.

---

## D-018: Parallax Pipeline — Depth Split + Scene Composition Validation

**Date:** 2026-03-04
**Context:** Validating the full 2.5D parallax pipeline from D-017. Tested depth estimation, layer splitting, Godot rendering, and multi-image generation for scene/character separation.

### What Was Validated

**Depth Anything V2 — PASS:**
- Model: `depth-anything/Depth-Anything-V2-Small-hf` (24.8M params)
- Runtime: HuggingFace Transformers + PyTorch MPS
- Inference: **2.525s** on 1024x768 (M1 Max)
- RAM: ~300-500 MB — fits M4 16GB DEPTH profile
- Quality: excellent depth separation between foreground (Bob), mid-ground (furniture), background (wall)
- Script: `validate_depth.py`, output: `depth-validation/`

**Godot ParallaxBackground — PARTIAL PASS:**
- 4 depth-split layers load and render correctly in Godot 4.6
- Camera breathing (sinusoidal ±px) works
- Problem: **depth-split tears Bob apart** — his upper body is "near" layer, lower body is "foreground" layer, different motion_scale values make them drift apart
- With uniform motion_scale (0.97–1.01), no visible parallax effect — looks like a single 2D image moving
- **Conclusion: real parallax requires SEPARATE background and Bob layers, not depth-split of a single image containing Bob**

**Empty room generation — PASS:**
- FLUX.2 Klein 4B generated `bunker_bg_empty.png` (empty bunker room, no character) in 25 sec
- Quality: consistent cartoon style, warm lighting, green armchair, bookshelf, desk with lamp and radio

### What FAILED

**Qwen-Image-Edit (multi-image composition) — FAIL:**
- Goal: take bob_base (identity) + bunker_bg (scene) → generate Bob sitting in that specific armchair
- q4 quantization: **mosaic/pointillism artifacts**, unusable quality
- q8 quantization: quality acceptable but **identity lost** — Bob barely resembles reference
- Performance: q4 = 17 min, q8 = **66 min** (heavy swap on M1 Max 64GB)
- Full precision: OOM killed (exit code 137) — 54 GB model doesn't fit 64 GB RAM
- **Not viable for Mac Mini M4 16 GB** (model is 27-54 GB)

### The Fundamental Problem Discovered

**FLUX.1 Kontext dev** preserves Bob's identity perfectly (proven with 4 images). But it accepts **only 1 input image**. To place Bob into a specific scene, we need the model to see BOTH the character reference AND the scene simultaneously. No locally-runnable model does this.

| Tool | Identity | Scene-aware | Local M4 16GB | Status |
|------|----------|-------------|---------------|--------|
| Kontext dev | Yes (excellent) | No (1 image input) | Yes (~6 GB q4) | Proven |
| Qwen-Image-Edit | No (identity lost) | Yes (multi-image) | No (27-54 GB) | Failed |
| Kontext Max API | Yes | Yes (up to 8 images) | Cloud only ($0.08/img) | Not tested |

### Proposed Solutions (not yet validated)

**Solution A: Kontext side-by-side hack**
- Stitch `bob_base.png` + `scene.png` into one wide image
- Prompt: "Place the character from the left into the armchair from the right"
- Quick to test (~10 min). Documented in ComfyUI community as working with variable quality.
- Risk: model not trained for this, results may be inconsistent.

**Solution B: LoRA trained on Bob (`mflux-train`)**
- Train LoRA on 5-10 Bob images → identity "baked" into model weights
- Then `mflux-generate-fill` with LoRA inserts Bob into any scene with identity preserved
- Both conditions satisfied simultaneously: identity (LoRA) + scene awareness (fill/inpainting)
- Requires: dataset preparation, training time (one-time investment)
- `mflux-train` is available in mflux 0.16.7

### mflux Toolkit Discovery

Full inventory of mflux 0.16.7 (28 commands). Key tools for Bob's World:

| Command | Use Case |
|---------|----------|
| `mflux-generate-flux2` | Base background generation (~25 sec) |
| `mflux-generate-fill` | **Inpainting** — insert objects into scene by mask (lighting/style consistent) |
| `mflux-generate-kontext` | Bob identity preservation (single reference image) |
| `mflux-generate-depth` | Depth-conditioned generation |
| `mflux-generate-redux` | Multi-image style/content transfer |
| `mflux-train` | **LoRA finetuning** — train custom LoRA on Bob images |

Also discovered `rembg` (PyPI) with `isnet-anime` model — specifically trained for cartoon/anime character background removal. Not yet tested.

### Revised Architecture: "Bob's World" as Compositional Pipeline

```
AI generates ASSETS (sprites) → Godot COMPOSES them into scene

1. Background: FLUX.2 → empty room
2. Objects: mflux-generate-fill → inpaint furniture into scene (consistent lighting)
3. Bob poses: Kontext (identity) → rembg (extract sprite) → overlay in Godot
4. Lighting: Godot CanvasModulate / shaders (instant, no generation)
5. Parallax: Depth Anything V2 on background → depth layers in Godot
```

**Open problem:** Step 3 generates Bob "in a generic armchair", not in the specific armchair from Step 2. Solutions A and B above address this.

**RFC impact:** Architecture section needs major update — compositional pipeline vs single-image generation.

---

## Artifacts from 2D Validation Phase

The following files were generated during 2D validation (Phase 1) and are archived for reference:

**Generated images (output/ directory — deleted):**
- `full_body_seed123.png` — Best full body variant (1024×1024)
- `i2i_head_*.png` — 6 head emotions via img2img (consistent)
- `i2i_hand_*.png` — 7 hand poses via img2img (FAILED — all identical)
- `edit_thumbs_up.png`, `edit_fist.png`, `edit_pointing.png` — flux2-edit results (WORKED but too slow)

**Scripts (deleted):**
- `generate_bob.py` — FLUX.2 generation script with prompt templates
- `BRIEF.md` — Original 2D approach specification
- `3D_AVATAR_RESEARCH.md` — Intermediate research document

**Key learnings preserved in this Decision Log and RFC-Proof-of-VR-Concept.md.**
