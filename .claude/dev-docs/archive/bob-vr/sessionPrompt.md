We're working on Bob's World — 2D Point-and-Click PoC. Identity Persistence (D-020/D-021), Phase 2 — LoRA Training on FLUX.2 Klein 4B.

**What's done:**
- Phase 1 (validation pipeline) COMPLETED
- Phase 2 training data: 8 images generated, validated, captioned
- D-021: Migrated from FLUX.1 Kontext to FLUX.2 Klein Edit
- FLUX.2 Klein Edit test WITHOUT LoRA: best result ever (1:50, proper proportions, unified scene)
- FLUX.2 Klein architecture fully mapped (transformer_blocks + single_transformer_blocks)
- train.json: model updated to flux2-klein-4b, lora_layers rewritten for FLUX.2 architecture
- Training experiments: OOM at 1024, Q4 works but 324 sec/step — impractical
- Optimized: 512x512 + 30 epochs (240 steps)
- **Plan A WORKS:** no quant + --low-ram + --mlx-cache-limit-gb 24 = ~78 sec/step, ~7.5 GB unified memory
- **Training RUNNING** (started session 2026-03-05, ~5.2 hours ETA)

**CURRENT TASK — post-training validation:**

1. Check training completed successfully (240 steps, 30 epochs)
2. Review loss.html for convergence
3. Find best checkpoint in `godot/assets/lora/bob_identity_training/checkpoints/`
4. Test: `mflux-generate-flux2-edit --model flux2-klein-4b --quantize 4 --image-paths scene.png bob_ref.png --lora-paths <best_checkpoint> --prompt "Place vaultboy_bob..." --steps 4`
5. Validate with validate_bob.py
6. Generate 8 pose sprites

**Training config summary:**
- Model: flux2-klein-4b, 512x512, 30 epochs x 8 images = 240 steps
- No quantization, --low-ram, --mlx-cache-limit-gb 24
- Rank 16, lr 1e-4, AdamW
- Checkpoints every 10 epochs (steps 80, 160, 240)
- Preview images every 10 epochs
- Output: `godot/assets/lora/bob_identity_training/`

**FLUX.2 Klein 4B architecture (CRITICAL — different from FLUX.1):**
- `transformer_blocks` (5 double-stream, 0-4): `attn.to_q/k/v/to_out`, `attn.add_q/k/v_proj/to_add_out`, `ff.linear_in/out`, `ff_context.linear_in/out`
- `single_transformer_blocks` (20 single-stream, 0-19): `attn.to_qkv_mlp_proj` (fused), `attn.to_out`
- Global: `x_embedder`, `context_embedder`, `proj_out`
- `steps: 4` (distilled), `timestep_low: 0`, `timestep_high: 4`
- FLUX.1-style paths (`layers`, `cap_embedder`, `all_final_layer`) will CRASH

**M1 Max 32GB training performance:**
- Plan A (no quant, --low-ram, --mlx-cache-limit-gb 24): **78 sec/step** — CONFIRMED WORKING
- Q4 + 1024 → 324 sec/step (impractical)
- No quant + 1024 → OOM (SIGKILL 137)
- First step ~80 sec (JIT compilation), subsequent steps ~76-78 sec (stable)
- Initial checkpoint: 85 MB

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
