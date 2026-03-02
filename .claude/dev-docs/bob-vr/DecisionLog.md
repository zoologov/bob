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
