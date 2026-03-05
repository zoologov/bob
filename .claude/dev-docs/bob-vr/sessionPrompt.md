We're working on Bob's World — 2D Point-and-Click PoC. Identity Persistence (D-020/D-021), Phase 2 — LoRA Training on FLUX.2 Klein.

**What's done:**
- Phase 1 (validation pipeline) COMPLETED
- Phase 2 training data: 8 images generated, validated, captioned
- D-021: Migrated from FLUX.1 Kontext to FLUX.2 Klein Edit
- FLUX.2 Klein Edit test WITHOUT LoRA: best result ever (1:50, proper proportions, unified scene)
- Training tool: `mflux-train` (native MLX, v0.16.7)
- Training config needs update: change model from "dev" to "flux2-klein-4b"

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

**CURRENT TASK — update config + start LoRA training:**

1. Update train.json: change `"model": "dev"` to `"model": "flux2-klein-4b"`
2. Run: `mflux-train --config godot/assets/training_data/bob_identity/train.json`
3. Optional: `--quantize 4` if OOM

**After training:**
1. Find best checkpoint
2. Test: `mflux-generate-flux2-edit --model flux2-klein-4b --quantize 4 --image-paths scene.png bob_ref.png --lora-paths <checkpoint> --prompt "Place vaultboy_bob..." --steps 4 --output test.png`
3. Validate with validate_bob.py
4. Generate 8 pose sprites

**New pipeline (D-021):**
- Background: `mflux-generate-flux2` (FLUX.2 Klein 4B, ~25 sec)
- Bob in scene: `mflux-generate-flux2-edit` + LoRA (~1:50, multi-image, no inset)
- Sprite: rembg isnet-anime (<5 sec)

**Key files:**
- Plan: `.claude/dev-docs/bob-vr/current.md`
- General: `.claude/dev-docs/bob-vr/general.md`
- Decisions: `.claude/dev-docs/bob-vr/decisionLog.md`
- Training config: `godot/assets/training_data/bob_identity/train.json`
- Training data: `godot/assets/training_data/bob_identity/`
- Training output: `godot/assets/lora/bob_identity_training/`
- Validation: `godot/tools/validate_bob.py`
- Style guide: `godot/config/style_guide.yaml`
- Bob ref: `.claude/dev-docs/bob-vr/bob-preview/bob_base_vaultboy.png`
- FLUX.2 test result: `/tmp/flux2_edit_test.png`
- Bead: `bob-0zw` (in_progress)

Language: Russian. Commits: yes, push: no.
