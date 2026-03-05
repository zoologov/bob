# Bob's World -- 2D Point-and-Click PoC

> Status: Active (Phase 2 -- LoRA Training)
> Date: 2026-03-05
> Architecture: D-019 (2D Point-and-Click with AI Sprites)

---

## 1. Vision

Bob lives in his own world -- an "aquarium" that the user observes. The camera is fixed. The user does not interact -- only watches. Bob autonomously generates his environments (Mars, a ship bridge, a cozy bunker, a Tokyo cafe) and lives in them: sitting, reading, working, walking, sleeping.

**Killer feature:** Unlimited environments. Bob can "dream" of any place -- and in 25 seconds be there. This is impossible in 3D (no open-source 3D scene generator for Apple Silicon), but trivial in 2D (FLUX.2 generates any scene).

**PoC success criteria:**

1. Bob is displayed over an AI-generated background
2. Bob can change pose (idle -> sitting -> typing)
3. Bob can "move" to a new environment in <60 sec
4. Bob's visual identity is preserved across scenes
5. The entire pipeline runs locally on Mac Mini M4 16GB

**NOT in scope for PoC:**

- Voice I/O (TTS, STT)
- User interaction with Bob
- LLM brain (autonomous decision-making)
- Mobile app / Android

---

## 2. Architecture: 2D Point-and-Click (D-019)

Monkey Island / Broken Sword style. AI generates assets, Godot animates.

```
Background (FLUX.2, wide shot, no Bob):
+-------------------------------------------+
|  [shelf]      [wall, posters]     [desk]  |
|                                           |
|  [books]         [armchair]      [lamp]   |
|                                           |
|  --------------- floor ----------------   |
+-------------------------------------------+

Bob (separate sprites, FLUX.2 Klein Edit + LoRA + rembg):
standing  walking  sitting  reading  at shelf
```

- **Background:** FLUX.2 Klein 4B (~25 sec)
- **Bob sprites:** FLUX.2 Klein Edit + LoRA for identity persistence (~1:50 per generation)
- **Sprite extraction:** rembg with isnet-anime (<5 sec)
- **Micro-animation (no new generations):**
  - Breathing: Godot shader -- sine deformation of chest area
  - Blinking: 2 sprites (eyes open/closed), swap every 3-5 sec
  - Head micro-movements: tween on sprite region
- **Macro-animation (pre-generated sprite library):**
  - Pose set: standing, sitting, walking, reading, reaching (~6-8 poses)
  - Generation: batch (~1:50 x 8 = ~15 min)
  - Godot: crossfade between poses + tween movement across scene
- **Target PoC scenario:**
  sitting reading -> stood up -> walked to bookshelf -> took a book -> walked back -> sat down -> reading

---

## 3. Bob Identity -- Golden Standard

- **Reference image:** `.claude/dev-docs/bob-vr/bob-preview/bob_base_vaultboy.png`
- **Style:** Vault Boy proportions (~5 heads tall), blonde, blue jumpsuit, short beard, Ryan Reynolds charisma vibe
- **Art style:** cartoon, bold outlines, cel shading, Fallout Vault-Tec 1950s aesthetic
- **Resolution:** 1280x768 (wide angle scenes), 1024x1024 (training images)
- **ALWAYS** read `godot/config/style_guide.yaml` before any image generation -- single source of truth
- **Identity persistence:** LoRA training on 8 curated images with trigger word `vaultboy_bob` (Phase 2, see `current.md`)

---

## 4. RAM Budget: Mac Mini M4 16GB

| Component         | RAM      |
|-------------------|----------|
| macOS + system    | ~3.5 GB  |
| **ML budget**     | **~12.5 GB** |

ML models load sequentially, not simultaneously. Bob switches between profiles as needed.

| Profile    | Models                                      | RAM      |
|------------|---------------------------------------------|----------|
| SCENE_GEN  | FLUX.2 Klein 4B (q4) + FLUX.2 Klein Edit (q4) | ~4.0 GB  |
| BRAIN      | Qwen3-8B + Qwen3-0.6B + Guard + embeddings | ~8.6 GB  |
| VOICE      | Qwen3-TTS-0.6B + Whisper Large-v3-Turbo     | ~4.5 GB  |
| VISION     | YOLO11n (camera)                            | ~0.3 GB  |
| VALIDATION | YOLO11n + ArcFace + DINOv2 + CLIP ViT-L-14 | ~2.0 GB  |
| DEV        | Claude Code CLI (Opus 4.6)                  | ~1-3 GB  |

Peak usage: ~8.6 GB (BRAIN) out of 12.5 GB budget. ~4 GB headroom.

---

## 5. LLM/AI Stack

| # | Model | Purpose | Runtime | RAM | Status |
|---|-------|---------|---------|-----|--------|
| 1 | Qwen3-0.6B (q4) | Fast decisions | Ollama | ~0.9 GB | RFC |
| 2 | Qwen3-8B (q4) | Brain (reasoning) | Ollama | ~6.5 GB | RFC |
| 3 | Qwen3-TTS-0.6B | TTS (Bob's voice) | mlx-audio | ~1.5 GB | RFC |
| 4 | Whisper Large-v3-Turbo | STT (Bob's hearing) | mlx-audio | ~3.0 GB | RFC |
| 5 | Qwen3Guard-Gen-0.6B (q4) | ContentGuard | Ollama | ~0.9 GB | Updated |
| 6 | nomic-embed-text | SemanticMemory embeddings | Ollama | ~0.3 GB | Updated |
| 7 | YOLO11n | Vision (camera) + sprite validation | ultralytics | ~0.3 GB | Validated (D-020) |
| 8 | FLUX.2 Klein 4B (q4) | Background generation | mflux | ~2.0 GB | Validated |
| 9 | FLUX.2 Klein Edit (q4) | Bob in scene (multi-image + LoRA) | mflux | ~2.0 GB | Validated (D-021) |
| 10 | InsightFace ArcFace (buffalo_l) | Face identity (512-d embeddings) | onnxruntime | ~0.5 GB | Validated (D-020) |
| 11 | DINOv2-base (Meta) | Face crop similarity (fine-grained) | HF Transformers + MPS | ~0.33 GB | Validated (D-020) |
| 12 | CLIP ViT-L-14 (OpenAI) | Style consistency | open-clip-torch | ~0.9 GB | Validated (D-020) |
| 13 | Claude Code CLI (Opus 4.6) | IQ boost, reflection, development | Claude Code CLI | ~1-3 GB | Active |

~~Depth Anything V2~~ -- validated (D-017) but excluded (D-019: 2.5D parallax rejected).

---

## 6. Visual Generation Pipeline

```
FLUX.2 Klein 4B          FLUX.2 Klein Edit + LoRA      rembg isnet-anime
  (background)      -->    (Bob in scene)         -->   (sprite extraction)
   ~25 sec                    ~1:50                       <5 sec
   1280x768                  1280x768                    transparent PNG
   mflux-generate-flux2      mflux-generate-flux2-edit
```

- **FLUX.2 Klein Edit (D-021):** Multi-image conditioning via `--image-paths scene.png bob_ref.png` -- no inset hack needed. 4 steps (vs 24 on old Kontext). Proper proportions, unified scene composition.
- **LoRA (Phase 2):** trained on 8 images with trigger word `vaultboy_bob` via `mflux-train` on `flux2-klein-4b` (natively supported). Intended to lock face identity across poses.
- **Validation:** `godot/tools/validate_bob.py` -- automated identity check (YOLO11n -> ArcFace -> DINOv2 -> CLIP).
- **Auto-generation:** `godot/tools/generate_pose.py` -- generate + validate + retry loop (up to 5 seeds).
- **RAM constraint:** NEVER run parallel mflux processes (OOM on M1 Max 32GB with two 1280x768).

---

## 7. Key Files

| Purpose | Path |
|---------|------|
| Style guide (source of truth) | `godot/config/style_guide.yaml` |
| Bob reference (golden standard) | `.claude/dev-docs/bob-vr/bob-preview/bob_base_vaultboy.png` |
| Background scene | `godot/assets/scenes/bunker_wide.png` |
| Validation script | `godot/tools/validate_bob.py` |
| Auto-generation script | `godot/tools/generate_pose.py` |
| Training data (8 images + captions) | `godot/assets/training_data/bob_identity/` |
| Training config | `godot/assets/training_data/bob_identity/train.json` |
| Turnaround LoRA (data gen) | `godot/assets/lora/kontext-turnaround-sheet-v1.safetensors` |
| LoRA training output | `godot/assets/lora/bob_identity_training/` |
| Godot scene script | `godot/scripts/parallax_scene.gd` |
| Current work | `.claude/dev-docs/bob-vr/current.md` |
| Decision log | `.claude/dev-docs/bob-vr/decisionLog.md` |
| Session prompt | `.claude/dev-docs/bob-vr/sessionPrompt.md` |
| Archive | `.claude/dev-docs/bob-vr/archive.md` |
| Identity persistence plan | `.claude/dev-docs/bob-vr/identity-persistence-plan.md` |

---

## 8. Beads DAG

```
bob-2a2 (epic: Bob's World PoC)
  |-- bob-oxb [CLOSED] -- background generation
  |-- bob-0zw [IN_PROGRESS] -- sprites + identity persistence
  |     |-- Phase 1.1: validate_bob.py              DONE
  |     |-- Phase 1.2: generate_pose.py             DONE
  |     |-- Phase 1.3: training data (8 imgs)       DONE
  |     |-- Phase 2.1: mflux-train config           DONE
  |     |-- Phase 2.2: train Bob LoRA            <- CURRENT
  |     |-- Phase 2.3: validate LoRA quality
  |     '-- Phase 2.4: generate 8 pose sprites with LoRA
  |-- bob-4gd [BLOCKED by bob-0zw] -- shader breathing
  |-- bob-soo [BLOCKED by bob-0zw] -- tween movement
  '-- bob-3xr [BLOCKED by bob-soo, bob-4gd] -- full scene assembly
```
