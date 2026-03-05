We're working on Bob's World — 2D Point-and-Click PoC. Identity Persistence (D-020), Phase 2 — LoRA Training.

**What's done:**
- Phase 1 (validation pipeline) COMPLETED
- Phase 2 training data: 8 images generated, validated, captioned
- Training tool: `mflux-train` (native MLX, already installed)
- Training config: `godot/assets/training_data/bob_identity/train.json` — validated via --dry-run
- Old YAML config (ai-toolkit) replaced with mflux-native JSON

**Training dataset (8 images + captions):**

| # | File | View | Validation |
|---|------|------|-----------|
| 1 | bob_front_s42.png | front | PASS: ArcFace 14.09, DINOv2 0.941, CLIP 0.880 |
| 2 | bob_3q_left_s43.png | 3/4 left | no face, CLIP 0.900 |
| 3 | bob_left_profile_s44.png | left profile | no face, CLIP 0.874 |
| 4 | bob_back_s45.png | back | no face (expected), CLIP 0.886 |
| 5 | bob_3q_right_s46.png | 3/4 right | PASS: ArcFace 15.23, DINOv2 0.886, CLIP 0.862 |
| 6 | bob_sitting_s47.png | sitting | PASS: ArcFace 15.12, DINOv2 0.909, CLIP 0.855 |
| 7 | bob_action_s48.png | action pose | PASS: ArcFace 16.24, DINOv2 0.926, CLIP 0.927 |
| 8 | bob_reference.png | front (golden ref) | Reference image (bob_base_vaultboy.png) |

**CURRENT TASK — start LoRA training:**

```bash
mflux-train --model dev --config godot/assets/training_data/bob_identity/train.json
```

Optional: `--quantize 4` if OOM on full precision (32GB M1 Max).

**Training config summary:**
- Model: FLUX.1-dev (via mflux native MLX)
- Epochs: 125 (= ~1000 steps on 8 images)
- LoRA rank: 16, lr: 1e-4, AdamW
- Checkpoints: every 25 epochs (~200 steps) → `godot/assets/lora/bob_identity_training/`
- Preview: 1024x1024 every 25 epochs
- Trigger word in captions: `vaultboy_bob`

**After training completes:**
1. Find best checkpoint (lowest loss / best preview quality)
2. Test inference:
   ```bash
   mflux-generate-kontext \
     --model akx/FLUX.1-Kontext-dev-mflux-4bit \
     --lora-paths godot/assets/lora/bob_identity_training/checkpoints/<best>.zip \
     --width 1280 --height 768 --steps 24 --seed 42 \
     --image-path godot/assets/scenes/bunker_wide.png \
     --prompt "Place vaultboy_bob into this scene sitting in armchair reading a book" \
     --output test_lora_output.png
   ```
3. Validate with: `source godot/tools/.venv/bin/activate && python godot/tools/validate_bob.py test_lora_output.png`
4. If PASS → rename best checkpoint to `bob_identity.safetensors`
5. Generate 8 pose sprites for PoC scene

**Key files:**
- Plan: `.claude/dev-docs/bob-vr/identity-persistence-plan.md`
- Training config: `godot/assets/training_data/bob_identity/train.json`
- Training data: `godot/assets/training_data/bob_identity/`
- Training output: `godot/assets/lora/bob_identity_training/`
- Turnaround LoRA (used for data generation): `godot/assets/lora/kontext-turnaround-sheet-v1.safetensors`
- Validation: `godot/tools/validate_bob.py`
- Style guide: `godot/config/style_guide.yaml`
- Bob ref: `.claude/dev-docs/bob-vr/bob-preview/bob_base_vaultboy.png`
- Venv: `godot/tools/.venv`
- Bead: `bob-0zw` (in_progress)

Language: Russian. Commits: yes, push: no.
