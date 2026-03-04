# Identity Persistence Plan — Bob's World

> **Status:** Active
> **Date:** 2026-03-04
> **Decision:** D-020
> **Goal:** Bob autonomously generates sprites with strictly persistent appearance

---

## Phase 1: Automated Validation Pipeline + Curated Dataset

### 1.1 Goal

Build `validate_bob.py` — a script that automatically checks every generated image for:
1. Character presence (is Bob in the image?)
2. Face identity match (is it OUR Bob?)
3. Style consistency (cartoon Vault-Tec, not photorealistic?)
4. Proportion sanity (Bob not a giant/dwarf relative to scene?)

If validation fails → auto-retry with a different seed. No human intervention.

Side effect: curate the best generations as training data for Phase 2.

### 1.2 Validation Pipeline Architecture (Updated 2026-03-04)

```
Generated Image
       │
       ▼
┌──────────────┐
│  YOLO11 nano │ → "Is there a person?" (conf > 0.7)
│  (6 MB, 50ms)│ → Bounding box → height % of frame
└──────┬───────┘
       │ PASS
       ▼
┌──────────────┐
│InsightFace   │ → Face detected? → 512-d ArcFace embedding
│ArcFace       │ → distance < 20.0, cosine > 0.50 → PASS
│(500 MB, 0.1s)│   (4x richer than dlib's 128-d)
└──────┬───────┘
       │ PASS (or SKIP if rear/side view)
       ▼
┌──────────────┐
│ DINOv2-base  │ → Face crop similarity (fine-grained)
│(330 MB, 0.2s)│ → 70% accuracy where CLIP scores 15%
│  (Meta, 2023)│ → cosine_sim > 0.75 → PASS
└──────┬───────┘
       │ PASS
       ▼
┌──────────────┐
│CLIP ViT-L-14 │ → Full-image style similarity
│(900 MB, 0.3s)│ → cosine_sim > 0.65 → PASS
│  (+12% acc)  │   (3x larger than ViT-B-32)
└──────┬───────┘
       │ PASS
       ▼
┌──────────────┐
│Inset removal │ → Check top-left corner for white rectangle
│  (PIL, 10ms) │ → No inset remnant → PASS
└──────┬───────┘
       │ PASS
       ▼
   ✅ VALIDATED
```

### 1.3 Script: `validate_bob.py`

**Location:** `godot/tools/validate_bob.py`

**Dependencies (Python 3.12 venv):**
```bash
uv pip install insightface onnxruntime ultralytics transformers \
    open-clip-torch pillow torch "setuptools<70"
```

**Interface:**
```python
class ValidationResult:
    passed: bool
    person_detected: bool
    person_confidence: float
    person_height_pct: float        # % of frame height
    face_detected: bool
    face_distance: float            # ArcFace 512-d euclidean, < 20.0 = match
    face_cosine_sim: float          # ArcFace cosine, > 0.50 = match
    face_dino_similarity: float     # DINOv2 face crop cosine, > 0.75 = match
    style_similarity: float         # CLIP ViT-L-14 cosine, > 0.65 = consistent
    inset_removed: bool
    errors: list[str]

def validate(
    generated_path: str,
    bob_ref_path: str = "bob-preview/bob_base_vaultboy.png",
    require_face: bool = True,        # False for rear/side views
    min_style_sim: float = 0.65,
    max_face_distance: float = 20.0,  # ArcFace scale
    min_face_dino_sim: float = 0.75,
) -> ValidationResult: ...
```

**Thresholds (calibrated on actual Bob images, 2026-03-04):**

| Check | Threshold | Source |
|-------|-----------|--------|
| Person confidence | > 0.7 | YOLO11n tested: 0.85-0.94 on Bob |
| Person height (in scene) | 20-85% of frame | YOLO11n tested: 64-72% |
| ArcFace distance (512-d) | < 20.0 | Tested: 28-30 on wrong faces, 0.0 on ref |
| ArcFace cosine similarity | > 0.50 | Tested: 0.33-0.37 on wrong faces, 1.0 on ref |
| DINOv2 face crop similarity | > 0.75 | Tested: 0.66-0.73 on wrong faces, 1.0 on ref |
| Style CLIP ViT-L-14 similarity | > 0.65 | Tested: 0.69-0.71 ref↔pose |
| Inset removal | corner avg brightness < 200 | Simple PIL check |

**Key upgrade (D-020, 2026-03-04):**
- Replaced dlib (128-d) with **InsightFace ArcFace** (512-d) — dramatically better cartoon face discrimination
- Replaced CLIP ViT-B-32 face crop with **DINOv2-base** — 70% vs 15% on fine-grained tasks
- Replaced CLIP ViT-B-32 style with **CLIP ViT-L-14** — 3x larger, +12% accuracy
- Replaced YOLOv8n with **YOLO11n** — faster, more accurate

### 1.4 Auto-Generation Script: `generate_pose.py`

**Location:** `godot/tools/generate_pose.py`

**Interface:**
```python
def generate_pose(
    pose_name: str,           # e.g. "sitting_reading"
    pose_prompt: str,         # action description
    scene_path: str,          # background image
    bob_ref_path: str,        # Bob reference
    output_dir: str,          # where to save
    max_retries: int = 5,     # retry on validation fail
    seed_start: int = 42,     # initial seed
) -> str:                     # path to validated sprite
    """
    1. Create inset (bob_ref in corner of scene)
    2. Run mflux-generate-kontext
    3. Validate result
    4. If FAIL: retry with seed += 100
    5. If PASS: run rembg, save sprite
    6. Return sprite path
    """
```

**Retry strategy:**
- Seed sequence: 42, 142, 242, 342, 442 (max 5 attempts)
- Each attempt ~11 min on M1 Max (1280x768, 24 steps) → worst case ~55 min per pose
- Log all attempts with validation scores for analysis

### 1.5 Phase 1 Generation Results (2026-03-04)

**Test: sitting_reading pose, 5 attempts — ALL FAILED**

| Seed | Person | ArcFace dist | ArcFace cos | DINOv2 face | Style | Result |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| 42 | 0.872 | 28.3 | 0.43 | 0.58 | 0.70 | FAIL |
| 142 | 0.893 | 32.5 | 0.36 | 0.69 | 0.71 | FAIL |
| 242 | 0.883 | 31.1 | 0.36 | 0.67 | 0.73 | FAIL |
| 342 | 0.878 | — | — | — | 0.72 | FAIL (no face) |
| 442 | 0.878 | 30.5 | 0.34 | 0.73 | 0.70 | FAIL |

**Conclusion:** Kontext inset-method preserves style (0.70-0.73) and pose, but does NOT preserve face identity (dist 28-33 vs threshold <20). Validation pipeline works correctly. **Phase 2 (LoRA) is required** for face persistence.

### 1.6 Pose Library (8 poses for PoC scenario)

| # | Name | Prompt Description | Require Face |
|---|------|-------------------|:---:|
| 1 | sitting_reading | Sitting in armchair on left side, holding open book, relaxed expression | Yes |
| 2 | standing_idle | Standing near armchair, book in one hand hanging at side, looking ahead | Yes |
| 3 | walking_right | Walking to the right, mid-stride, carrying book, looking toward bookshelf | Yes (3/4) |
| 4 | at_bookshelf | Standing in front of bookshelf on right side, looking at books, one hand on shelf | Yes (3/4) |
| 5 | reaching_book | Reaching up with one hand to pull a book from upper shelf | Partial |
| 6 | walking_left | Walking to the left, mid-stride, carrying book, heading back to armchair | Yes (3/4) |
| 7 | sitting_down | Lowering into armchair, one hand on armrest, book in other hand | Yes |
| 8 | reading_new_book | Sitting comfortably in armchair, reading a different book, content smile | Yes |

### 1.7 Dataset Curation for Phase 2

**Updated strategy (2026-03-04):** Phase 1 generation produced 0 validated images (all faces different). Original plan to curate from validated generations is not viable. New approach:

1. Use `bob_base_vaultboy.png` as the **anchor** (this IS Bob's face)
2. Generate 5-8 portrait variations of Bob on green/solid background via Kontext
3. Manually curate — select those with closest face to reference
4. Crop existing assets where Bob is visible

**Target:** 8-12 curated images for Phase 2 training.

**Storage:** `godot/assets/training_data/bob_identity/`

---

## Phase 2: Bob LoRA Fine-Tuning

### 2.1 Goal

Train a DreamBooth LoRA adapter that teaches FLUX to recognize Bob by a trigger token (`vaultboy_bob`). After training, any generation using the LoRA will produce OUR Bob — same face, same proportions, same style.

### 2.2 Prerequisites

- Phase 1 validation pipeline complete and tested
- mflux v0.16.7 — LoRA **inference** supported (`--lora-paths`), training NOT supported
- LoRA training: ai-toolkit Mac fork or cloud (fal.ai, Replicate)

### 2.3 Training Data Preparation (Updated 2026-03-04)

**Research findings (2026-03-04):** Comprehensive research of 15+ tools for consistent character generation. Full report in conversation history.

#### Tier 1: Flux Kontext Turnaround Sheet LoRA (TRY FIRST)

**What:** Specialized LoRA from Civitai that generates 5-view turnaround sheet (front, 3/4 left, left profile, back, right profile) from a single character image.

- **Source:** [civitai.com/models/1753109](https://civitai.com/models/1753109/flux-kontext-character-turnaround-sheet-lora)
- **Runs on:** Mac M1 Max via mflux + `--lora-paths`
- **Cartoon support:** Explicitly designed for "illustrated/stylized characters"
- **Trigger prompt:** "create turnaround sheet of this exact character, 5 full-body poses on pure white background: front view, 3/4 left, left profile, back view, right profile -- evenly spaced in a clean horizontal row"
- **Caveat:** LoRA requires full-precision model (`--model black-forest-labs/FLUX.1-Kontext-dev -q 8`), NOT pre-quantized 4-bit

**Pipeline:**
1. Download turnaround LoRA from Civitai
2. Run: `mflux-generate-kontext --model black-forest-labs/FLUX.1-Kontext-dev -q 8 --lora-paths turnaround.safetensors --image-path bob_base_vaultboy.png --prompt "..." --output turnaround.png`
3. Split panoramic output into 5 individual images
4. Validate each with `validate_bob.py`
5. Supplement with 3-5 crops from existing assets

#### Tier 2: Blender MPFB2 + Cel Shading (IF TIER 1 INSUFFICIENT)

**What:** Create 3D Bob in Blender, render from 8-12 angles with cel-shading.

- **MPFB2 v2.0.14** (Feb 2026) — `cartoon01` asset pack for ~5-head proportions
- **Shader:** Shader to RGB + ColorRamp (Constant) + Freestyle outlines = Vault-Tec look
- **Batch render:** Python script for 8-12 camera positions
- **Effort:** 4-6 hours modeling + shading
- **Guarantee:** Perfect geometric consistency (same 3D model)

#### Tier 3: Cloud Fallback

- **StdGEN** (CVPR 2025): Best for anime/cartoon single-img→3D. CUDA only. RunPod ~$0.50-2/hr
- **CharForge**: Full automated pipeline (sheet→caption→LoRA). 48GB VRAM required.
- **fal.ai / Replicate**: Cloud LoRA training, ~$1-5 per training run

#### Supplementary crops from existing assets:
- `bob_base_vaultboy.png` — golden standard, crop to 1024x1024
- `bob_bunker_reading.png` — crop Bob region
- `bob_spaceship_bridge.png` — crop Bob region
- `bob_mars_fallout.png` — crop Bob region (if face visible)

**Target:** 8-12 curated images at 1024x1024, solid background, consistent face.

### 2.4 Training Configuration

**Tool:** ai-toolkit Mac fork ([github.com/hughescr/ai-toolkit](https://github.com/hughescr/ai-toolkit)) for local training, or fal.ai for cloud.

**Note:** mflux does NOT support LoRA training (inference only). ai-toolkit requires `num_workers=0` on Mac, no T5 quantizer.

**Config:**
```json
{
    "model": "black-forest-labs/FLUX.1-dev",
    "data_dir": "godot/assets/training_data/bob_identity/",
    "output_dir": "godot/assets/lora/",
    "trigger_word": "vaultboy_bob",
    "resolution": 1024,
    "train_steps": 1000,
    "learning_rate": 1e-4,
    "lora_rank": 16,
    "batch_size": 1,
    "save_every": 250
}
```

**Key parameters:**
- `lora_rank: 16` — good balance of quality/size for character identity
- `train_steps: 1000` — typical for 10-15 image dataset
- `resolution: 1024` — optimal for FLUX LoRA (updated from 512)
- Checkpoints at 250, 500, 750, 1000 steps for quality comparison

**Expected training time on Mac M1 Max 32GB:** 3-5x slower than NVIDIA → 3-12 hours
**Expected LoRA size:** ~50-150 MB

### 2.5 Inference with LoRA

**Generation command:**
```bash
mflux-generate-kontext \
  --model akx/FLUX.1-Kontext-dev-mflux-4bit \
  --width 1280 --height 768 \
  --steps 24 --seed 42 \
  --lora-paths godot/assets/lora/bob_identity.safetensors \
  --image-path <scene_with_inset> \
  --prompt "Place vaultboy_bob into this scene. He is sitting in the armchair reading a book. stylized cartoon, Vault-Tec aesthetic" \
  --output output.png
```

**Important:** LoRA does NOT work with pre-quantized models. Use full-precision base + quantize on-the-fly:
```bash
mflux-generate-kontext \
  --model black-forest-labs/FLUX.1-Kontext-dev \
  -q 8 \
  --lora-paths godot/assets/lora/bob_identity.safetensors \
  ...
```

### 2.6 Validation (same pipeline as Phase 1)

After LoRA training, validate with the same `validate_bob.py`:
- Expected improvement: face_distance < 0.4 (vs < 0.6 without LoRA)
- Expected improvement: face_cosine_sim > 0.95 (vs > 0.90 without LoRA)
- Style should remain consistent (CLIP > 0.70)

### 2.7 Success Criteria

| Metric | Without LoRA | With LoRA Target |
|--------|:---:|:---:|
| Face distance (dlib) | 0.49-0.53 | < 0.35 |
| Face cosine sim | 0.92-0.93 | > 0.96 |
| First-try validation pass rate | ~50% (estimated) | > 85% |
| Visual identity ("is this Bob?") | Sometimes | Always |

---

## Phase 3: FLUX.2 Multi-Reference (Future)

### When

Monitor `mflux` GitHub releases for FLUX.2-dev support. FLUX.2 was released November 2025. mflux support expected in 2026 Q1-Q2.

### What It Enables

- Up to 10 reference images simultaneously (no inset hack)
- Native identity preservation without LoRA training
- Better pose control (multiple angles as references)
- 32B parameters — higher quality than FLUX.1

### Migration Path

1. Replace Kontext inset-method with FLUX.2 multi-reference
2. Keep LoRA as optional boost (can combine LoRA + multi-ref)
3. Keep validation pipeline unchanged
4. Update `generate_pose.py` to use new API

---

## File Structure

```
godot/
├── config/
│   └── style_guide.yaml          # Visual generation config (exists)
├── tools/
│   ├── validate_bob.py            # Phase 1: validation pipeline
│   └── generate_pose.py           # Phase 1: auto-generation with retry
├── assets/
│   ├── scenes/
│   │   └── bunker_wide.png        # Background (exists)
│   ├── sprites/
│   │   └── bob_<pose>.png         # Generated sprites (Phase 1 output)
│   ├── training_data/
│   │   └── bob_identity/          # Curated images (Phase 1 → Phase 2)
│   └── lora/
│       └── bob_identity.safetensors  # Trained LoRA (Phase 2 output)
└── scripts/
    └── parallax_scene.gd          # Godot scene script (exists)
```

---

## Beads DAG Update

Current DAG (bob-0zw blocked by identity problem):

```
bob-2a2 (epic)
  ├── bob-oxb [CLOSED] — background
  ├── bob-0zw [OPEN] — sprites ← SPLIT into sub-tasks:
  │   ├── NEW: validate_bob.py (Phase 1.1)
  │   ├── NEW: generate_pose.py (Phase 1.2)
  │   ├── NEW: generate 8 poses with validation (Phase 1.3)
  │   └── NEW: curate training dataset (Phase 1.4)
  ├── bob-4gd [BLOCKED] — shader breathing
  ├── bob-soo [BLOCKED] — tween movement
  └── bob-3xr [BLOCKED] — full scene assembly
```

Phase 2 beads (create after Phase 1):
```
  ├── NEW: prepare training config (Phase 2.1)
  ├── NEW: train Bob LoRA (Phase 2.2)
  └── NEW: validate LoRA quality (Phase 2.3)
```
