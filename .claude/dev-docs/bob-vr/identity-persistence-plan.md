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

### 1.2 Validation Pipeline Architecture

```
Generated Image
       │
       ▼
┌──────────────┐
│ YOLOv8 nano  │ → "Is there a person?" (conf > 0.7)
│  (6 MB, 60ms)│ → Bounding box → height % of frame
└──────┬───────┘
       │ PASS
       ▼
┌──────────────┐
│face_recognition│ → Face detected? → Embedding distance to bob_ref
│ (126 MB, 0.3s)│ → distance < 0.6 → PASS
└──────┬───────┘
       │ PASS (or SKIP if rear/side view)
       ▼
┌──────────────┐
│ CLIP ViT-B-32│ → Style similarity to reference poses
│(340 MB, 0.3s)│ → cosine_sim > 0.65 → PASS
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

**Dependencies:**
```bash
uv run --with face_recognition --with ultralytics --with open-clip-torch --with pillow python3 validate_bob.py
```

**Interface:**
```python
class ValidationResult:
    passed: bool
    person_detected: bool
    person_confidence: float
    person_height_pct: float      # % of frame height
    face_detected: bool
    face_distance: float          # euclidean, < 0.6 = match
    face_cosine_sim: float        # > 0.90 = strong match
    style_similarity: float       # CLIP cosine, > 0.65 = consistent
    inset_removed: bool
    errors: list[str]

def validate(
    generated_path: str,
    bob_ref_path: str = "bob-preview/bob_base_vaultboy.png",
    require_face: bool = True,      # False for rear/side views
    min_style_sim: float = 0.65,
    max_face_distance: float = 0.6,
) -> ValidationResult: ...
```

**Thresholds (calibrated on actual Bob images):**

| Check | Threshold | Source |
|-------|-----------|--------|
| Person confidence | > 0.7 | YOLOv8 tested: 0.90-0.94 on Bob |
| Person height (standing in scene) | 40-85% of frame | YOLOv8 tested: 55-72% |
| Person height (sitting) | 30-65% of frame | Estimated from pose_01 |
| Face distance | < 0.6 | dlib tested: 0.496-0.530 |
| Face cosine similarity | > 0.90 | dlib tested: 0.921-0.933 |
| Style CLIP similarity | > 0.65 | open_clip tested: 0.70-0.71 ref↔pose |
| Inset removal | corner avg brightness < 200 | Simple PIL check |

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
- Each attempt ~8 min → worst case ~40 min per pose
- Log all attempts with validation scores for analysis

### 1.5 Pose Library (8 poses for PoC scenario)

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

### 1.6 Dataset Curation for Phase 2

During Phase 1 generation, save ALL validated images (not just final sprites) as LoRA training candidates.

**Criteria for good training image:**
- Face clearly visible (face_distance < 0.5 — stricter than validation threshold)
- Style similarity > 0.70
- Bob fills significant portion of frame (height > 50%)
- Variety: different poses, angles, expressions

**Target:** 10-15 curated images for Phase 2 training.

**Storage:** `godot/assets/training_data/bob_identity/`

---

## Phase 2: Bob LoRA Fine-Tuning

### 2.1 Goal

Train a DreamBooth LoRA adapter that teaches FLUX to recognize Bob by a trigger token (e.g., `sks bob` or `vaultboy bob`). After training, any generation using the LoRA will produce OUR Bob — same face, same proportions, same style.

### 2.2 Prerequisites

- Phase 1 complete: 10-15 curated high-quality Bob images
- mflux v0.5.0+ (current: 0.16.7) — LoRA training supported

### 2.3 Training Data Preparation

**From Phase 1 (primary):**
- 10-15 best validated Kontext generations
- Variety of poses (front, 3/4, side)
- Consistent Vault-Tec cartoon style
- Cropped to focus on Bob (512x512 or 768x768)

**From existing assets (supplement):**
- `bob_base_vaultboy.png` — golden standard (crop to 768x768)
- `bob_inset_test.png` — Bob in bunker scene (crop Bob region)
- `bob_bunker_reading.png` — Bob reading (crop Bob region)

**Image preparation:**
```bash
# Crop and resize to 512x512 for training
uv run --with pillow python3 -c "
from PIL import Image
img = Image.open('source.png')
# Crop to Bob region, resize to 512x512
bob_region = img.crop((x1, y1, x2, y2))
bob_region = bob_region.resize((512, 512), Image.LANCZOS)
bob_region.save('training_data/bob_001.png')
"
```

### 2.4 Training Configuration

**mflux-train config (JSON):**
```json
{
    "model": "black-forest-labs/FLUX.1-dev",
    "data_dir": "godot/assets/training_data/bob_identity/",
    "output_dir": "godot/assets/lora/",
    "trigger_word": "vaultboy_bob",
    "resolution": 512,
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
- `resolution: 512` — standard for LoRA training, saves memory
- Checkpoints at 250, 500, 750, 1000 steps for quality comparison

**Expected training time on Mac M1 Max 32GB:** 1-4 hours
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
