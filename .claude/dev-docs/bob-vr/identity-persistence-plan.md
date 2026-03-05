# Identity Persistence Plan — Bob's World

> **Status:** Active — Phase 2 Training
> **Date:** 2026-03-05 (updated)
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

### 1.7 Dataset Curation for Phase 2 — COMPLETED (2026-03-05)

**Strategy:** Used turnaround LoRA (`kontext-turnaround-sheet-v1.safetensors`) to generate 7 individual views at 1024x1024 + bob_base_vaultboy.png as 8th reference.

**Final training dataset (8 images with captions):**

| # | File | View | ArcFace | DINOv2 | CLIP Style |
|---|------|------|:---:|:---:|:---:|
| 1 | bob_front_s42.png | front | 14.09 | 0.941 | 0.880 |
| 2 | bob_3q_left_s43.png | 3/4 left | no face | — | 0.900 |
| 3 | bob_left_profile_s44.png | left profile | no face | — | 0.874 |
| 4 | bob_back_s45.png | back | no face | — | 0.886 |
| 5 | bob_3q_right_s46.png | 3/4 right | 15.23 | 0.886 | 0.862 |
| 6 | bob_sitting_s47.png | sitting | 15.12 | 0.909 | 0.855 |
| 7 | bob_action_s48.png | action pose | 16.24 | 0.926 | 0.927 |
| 8 | bob_reference.png | front (golden ref) | ref | ref | ref |

4/7 passed full identity check. 3 no face detected (back=expected, profile=too sharp angle, 3/4 left=unexpected). Style consistency excellent across all (0.85-0.93). All 8 images useful for LoRA training.

Each image has a matching `.txt` caption file with trigger word `vaultboy_bob` + description.

**Storage:** `godot/assets/training_data/bob_identity/`

---

## Phase 2: Bob LoRA Fine-Tuning

### 2.1 Goal

Train a DreamBooth LoRA adapter that teaches FLUX to recognize Bob by a trigger token (`vaultboy_bob`). After training, any generation using the LoRA will produce OUR Bob — same face, same proportions, same style.

### 2.2 Prerequisites — ALL MET (2026-03-05)

- Phase 1 validation pipeline complete and tested ✅
- Training data: 8 images with captions ready ✅ (see §1.7)
- **mflux-train** (native MLX) — supports LoRA DreamBooth training since v0.5.0 ✅
- Training config validated via `--dry-run` ✅

### 2.3 Training Data — COMPLETED

See §1.7 for full dataset. 8 images with `.txt` caption files, trigger word `vaultboy_bob`.

Turnaround LoRA used for data generation: `godot/assets/lora/kontext-turnaround-sheet-v1.safetensors` (344 MB, from HuggingFace reverentelusarca/kontext-turnaround-sheet-lora-v1). Individual views at 1024x1024, 24 steps.

### 2.4 Training Configuration (Updated 2026-03-05)

**Tool: `mflux-train`** (native MLX on Apple Silicon) — best option for local training.

**Previous assumption was WRONG:** mflux now supports LoRA training (since v0.5.0), not just inference. No need for ai-toolkit, SimpleTuner, or cloud services.

**Alternatives researched (2026-03-05):**
- ai-toolkit Mac fork (hughescr) — PyTorch MPS, slower than native MLX
- SimpleTuner — PyTorch MPS, float64 compatibility issues on Mac
- fal.ai cloud — $8/1000 steps, fast but unnecessary
- **mflux-train (chosen)** — native MLX, already installed, best Apple Silicon performance

**Config:** `godot/assets/training_data/bob_identity/train.json`

```json
{
  "model": "dev",
  "data": "./",
  "seed": 42,
  "steps": 24,
  "guidance": 3.5,
  "max_resolution": 1024,
  "training_loop": {
    "num_epochs": 125,
    "batch_size": 1,
    "timestep_low": 4,
    "timestep_high": 24
  },
  "optimizer": { "name": "AdamW", "learning_rate": 1e-4 },
  "checkpoint": { "save_frequency": 25, "output_path": "../../lora/bob_identity_training" },
  "monitoring": { "preview_width": 1024, "preview_height": 1024, "generate_image_frequency": 25 },
  "lora_layers": {
    "targets": [
      "layers.{0-30}.attention.to_q/k/v/out.0 (rank 16)",
      "layers.{0-30}.feed_forward.w1/w2/w3 (rank 16)",
      "cap_embedder.1 (rank 16)",
      "all_final_layer.2-1.linear (rank 16)"
    ]
  }
}
```

**Key parameters:**
- `model: dev` — FLUX.1-dev base model
- `lora_rank: 16` — good balance of quality/size for character identity
- `num_epochs: 125` × 8 images = ~1000 total training steps
- `resolution: 1024` — matches training image size
- Checkpoints every 25 epochs (~200 steps) → `godot/assets/lora/bob_identity_training/`
- Preview images generated every 25 epochs for visual monitoring

**Training command:**
```bash
mflux-train --model dev --config godot/assets/training_data/bob_identity/train.json
# Optional: --quantize 4 if OOM on full precision
# Optional: --low-ram for reduced memory usage
```

**Expected training time on Mac M1 Max 32GB:** several hours (native MLX, faster than PyTorch MPS)
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

**Update (2026-03-04):** LoRA DOES work with pre-quantized 4-bit models (tested with turnaround LoRA — 494 layers, 988/988 keys). No need for full-precision download (~24 GB). The `akx/FLUX.1-Kontext-dev-mflux-4bit` model works fine.

**RAM constraints:**
- M1 Max 32GB: one generation at a time (two parallel → OOM)
- Mac Mini M4 16GB (target): 1024x1024 should work, 1280x768 may be tight. Test needed.
- Never run parallel mflux processes

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
│   └── style_guide.yaml                    # Visual generation config (exists)
├── tools/
│   ├── validate_bob.py                     # Phase 1: validation pipeline
│   ├── generate_pose.py                    # Phase 1: auto-generation with retry
│   └── .venv/                              # Python 3.12 venv for validation
├── assets/
│   ├── scenes/
│   │   └── bunker_wide.png                 # Background (exists)
│   ├── sprites/
│   │   └── bob_<pose>.png                  # Generated sprites (Phase 1 output)
│   ├── training_data/
│   │   └── bob_identity/
│   │       ├── bob_front_s42.png + .txt    # 8 training images with captions
│   │       ├── bob_3q_left_s43.png + .txt
│   │       ├── ...
│   │       ├── bob_reference.png + .txt
│   │       ├── preview.txt                 # Preview prompt for training monitoring
│   │       └── train.json                  # mflux-train config
│   └── lora/
│       ├── kontext-turnaround-sheet-v1.safetensors  # Pre-trained LoRA (data gen)
│       └── bob_identity_training/           # Training output (Phase 2)
│           ├── checkpoints/                 # LoRA checkpoints (.zip)
│           ├── loss/                        # Loss plots
│           └── preview/                     # Preview images per epoch
└── scripts/
    └── parallax_scene.gd                   # Godot scene script (exists)
```

---

## Beads DAG Update (2026-03-05)

```
bob-2a2 (epic)
  ├── bob-oxb [CLOSED] — background
  ├── bob-0zw [IN_PROGRESS] — sprites + identity persistence
  │   ├── Phase 1.1: validate_bob.py ✅
  │   ├── Phase 1.2: generate_pose.py ✅
  │   ├── Phase 1.3: training data (8 images + captions) ✅
  │   ├── Phase 2.1: mflux-train config ✅
  │   ├── Phase 2.2: train Bob LoRA ← CURRENT
  │   ├── Phase 2.3: validate LoRA quality
  │   └── Phase 2.4: generate 8 pose sprites with LoRA
  ├── bob-4gd [BLOCKED] — shader breathing
  ├── bob-soo [BLOCKED] — tween movement
  └── bob-3xr [BLOCKED] — full scene assembly
```
