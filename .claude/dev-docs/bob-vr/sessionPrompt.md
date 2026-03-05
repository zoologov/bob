We're working on Bob's World — 2D Point-and-Click PoC. Identity Persistence (D-020/D-021), Phase 2 — LoRA Training on FLUX.2 Klein 4B.

**What's done:**
- Phase 1 (validation pipeline) COMPLETED
- Phase 2 training data: 8 images generated, validated, captioned
- D-021: Migrated from FLUX.1 Kontext to FLUX.2 Klein Edit
- FLUX.2 Klein Edit test WITHOUT LoRA: best result ever (1:50, proper proportions, unified scene)
- FLUX.2 Klein architecture fully mapped (transformer_blocks + single_transformer_blocks)
- train.json: model updated to flux2-klein-4b, lora_layers rewritten for FLUX.2 architecture
- Training experiments: OOM without quantization, Q4 works but 324 sec/step at 1024 — impractical
- Decision: optimize to 512×512 + 30 epochs (240 steps)

**CURRENT TASK — optimized LoRA training:**

1. Update train.json with optimized config (512, 30 epochs, full targets, rank 16)
2. Try Plan A: `mflux-train --config ... --low-ram --mlx-cache-limit-gb 24` (no quant, faster if fits)
3. If OOM → Plan B: `mflux-train --config ... --quantize 4` (known to work, ~80 sec/step)
4. Monitor training, find best checkpoint
5. Test: `mflux-generate-flux2-edit --model flux2-klein-4b --quantize 4 --image-paths scene.png bob_ref.png --lora-paths <checkpoint> --prompt "Place vaultboy_bob..." --steps 4`
6. Validate with validate_bob.py

**FLUX.2 Klein 4B architecture (CRITICAL — different from FLUX.1):**
- `transformer_blocks` (5 double-stream, 0-4): `attn.to_q/k/v/to_out`, `attn.add_q/k/v_proj/to_add_out`, `ff.linear_in/out`, `ff_context.linear_in/out`
- `single_transformer_blocks` (20 single-stream, 0-19): `attn.to_qkv_mlp_proj` (fused), `attn.to_out`
- Global: `x_embedder`, `context_embedder`, `proj_out`
- `steps: 4` (distilled), `timestep_low: 0`, `timestep_high: 4`
- FLUX.1-style paths (`layers`, `cap_embedder`, `all_final_layer`) will CRASH

**M1 Max 32GB training constraints:**
- No quantization → OOM (SIGKILL 137) on first step
- Q4 + 1024 → 324 sec/step (impractical)
- Q4 + 512 → ~80 sec/step (estimated)
- `--low-ram` + `--mlx-cache-limit-gb 24` without Q4 → untested, might be faster
- First step always slow (~5 min) due to MLX JIT compilation

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

**After training:**
1. Find best checkpoint (lowest validation loss or best preview quality)
2. Test with mflux-generate-flux2-edit + LoRA
3. Validate with validate_bob.py
4. Generate 8 pose sprites

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
