#!/usr/bin/env python3
"""
Bob Pose Auto-Generator with Validation (Phase 1, D-020).

Generates Bob pose sprites via FLUX.1 Kontext inset-method,
validates each attempt, retries on failure, and curates training data.

Usage:
    uv run --with face_recognition --with ultralytics --with open-clip-torch \
        --with "rembg[cpu,cli]" --with pillow --with mflux \
        python3 godot/tools/generate_pose.py --pose sitting_reading

    # Generate all 8 poses:
    uv run ... python3 godot/tools/generate_pose.py --all

Dependencies:
    All validate_bob.py deps + mflux + rembg
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from PIL import Image

# Import validation from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from validate_bob import ValidationResult, is_training_candidate, validate

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent  # godot/tools/ -> project root

BOB_REF = PROJECT_ROOT / ".claude/dev-docs/bob-vr/bob-preview/bob_base_vaultboy.png"
SCENE_BG = PROJECT_ROOT / "godot/assets/scenes/bunker_wide.png"
SPRITES_DIR = PROJECT_ROOT / "godot/assets/sprites"
TRAINING_DIR = PROJECT_ROOT / "godot/assets/training_data/bob_identity"
INSET_DIR = PROJECT_ROOT / "godot/assets/sprites/.insets"  # temp inset images

# From style_guide.yaml
OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 768
INSET_W = 192
INSET_H = 256
INSET_BORDER = 4
MAX_RETRIES = 5
SEED_INCREMENT = 100

ART_STYLE_SUFFIX = (
    "stylized cartoon illustration, clean bold outlines, cel shading, "
    "flat colors with subtle gradients, Fallout Vault-Tec retro-futuristic 1950s aesthetic"
)

BOB_IDENTITY = (
    "blonde messy hair, light stubble, blue eyes, charming smirk, blue vault jumpsuit"
)


# ---------------------------------------------------------------------------
# Pose Library (8 poses for PoC)
# ---------------------------------------------------------------------------


@dataclass
class PoseSpec:
    name: str
    prompt: str
    require_face: bool = True
    seed_start: int = 42


POSE_LIBRARY: dict[str, PoseSpec] = {
    "sitting_reading": PoseSpec(
        name="sitting_reading",
        prompt=(
            "The character is sitting comfortably in the armchair on the left side of the room, "
            "holding an open book, relaxed expression, legs crossed. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=42,
    ),
    "standing_idle": PoseSpec(
        name="standing_idle",
        prompt=(
            "The character is standing near the armchair, book in one hand hanging at his side, "
            "looking directly ahead with a confident smirk. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=77,
    ),
    "walking_right": PoseSpec(
        name="walking_right",
        prompt=(
            "The character is walking to the right, mid-stride, carrying a book, "
            "looking toward the bookshelf on the right side of the room. Three-quarter view. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=123,
    ),
    "at_bookshelf": PoseSpec(
        name="at_bookshelf",
        prompt=(
            "The character is standing in front of the tall bookshelf on the right side, "
            "looking at the books, one hand resting on a shelf. Three-quarter view from behind. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=200,
    ),
    "reaching_book": PoseSpec(
        name="reaching_book",
        prompt=(
            "The character is reaching up with one hand to pull a book from the upper shelf, "
            "standing on tiptoes, other hand at his side. Side view. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=False,
        seed_start=300,
    ),
    "walking_left": PoseSpec(
        name="walking_left",
        prompt=(
            "The character is walking to the left, mid-stride, carrying a book in one hand, "
            "heading back toward the armchair. Three-quarter view. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=400,
    ),
    "sitting_down": PoseSpec(
        name="sitting_down",
        prompt=(
            "The character is lowering himself into the armchair, one hand on the armrest, "
            "a book in the other hand, looking down at the seat. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=500,
    ),
    "reading_new_book": PoseSpec(
        name="reading_new_book",
        prompt=(
            "The character is sitting comfortably in the armchair, reading a different book "
            "with a content smile, leaning back slightly. Warm cozy atmosphere. "
            "Character occupies 20-25% of frame height."
        ),
        require_face=True,
        seed_start=600,
    ),
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _json_safe(val: object) -> object:
    """Convert numpy types to native Python types for JSON serialization."""
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.floating, float)):
        return float(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    return val


# ---------------------------------------------------------------------------
# Inset Creation
# ---------------------------------------------------------------------------


def create_inset_image(
    scene_path: Path,
    bob_ref_path: Path,
    output_path: Path,
) -> Path:
    """Place Bob reference (192x256) in top-left corner of scene with white border."""
    bg = Image.open(scene_path).convert("RGB")
    bob = Image.open(bob_ref_path).convert("RGBA")

    bob_small = bob.resize((INSET_W, INSET_H), Image.LANCZOS)

    # White border
    bordered_w = INSET_W + 2 * INSET_BORDER
    bordered_h = INSET_H + 2 * INSET_BORDER
    bordered = Image.new("RGB", (bordered_w, bordered_h), (255, 255, 255))

    # Paste Bob onto white background (handle alpha)
    bob_rgb = Image.new("RGB", bob_small.size, (255, 255, 255))
    bob_rgb.paste(bob_small, mask=bob_small.split()[3])
    bordered.paste(bob_rgb, (INSET_BORDER, INSET_BORDER))

    # Paste bordered inset onto scene
    bg.paste(bordered, (0, 0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(str(output_path), "PNG")
    return output_path


# ---------------------------------------------------------------------------
# Kontext Generation
# ---------------------------------------------------------------------------


def run_kontext(
    inset_path: Path,
    output_path: Path,
    pose_prompt: str,
    seed: int,
) -> bool:
    """Run mflux-generate-kontext. Returns True if command succeeded."""
    full_prompt = (
        f"Place the character from the small reference photo in the top-left corner "
        f"into this scene. {pose_prompt} "
        f"{BOB_IDENTITY}. "
        f"Remove the reference photo completely — no white rectangle in the corner. "
        f"{ART_STYLE_SUFFIX}"
    )

    cmd = [
        "mflux-generate-kontext",
        "--model", "akx/FLUX.1-Kontext-dev-mflux-4bit",
        "--width", str(OUTPUT_WIDTH),
        "--height", str(OUTPUT_HEIGHT),
        "--steps", "24",
        "--seed", str(seed),
        "--image-path", str(inset_path),
        "--prompt", full_prompt,
        "--output", str(output_path),
    ]

    print(f"\n  Running Kontext (seed={seed})...")
    print(f"  Prompt: {full_prompt[:120]}...")
    start = time.time()

    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start
    print(f"  Kontext finished in {elapsed:.0f}s (exit={result.returncode})")

    if result.returncode != 0:
        print(f"  STDERR: {result.stderr[:500]}")
        return False

    return output_path.exists()


# ---------------------------------------------------------------------------
# Background Removal (rembg)
# ---------------------------------------------------------------------------


def extract_sprite(input_path: Path, output_path: Path) -> bool:
    """Remove background using rembg isnet-anime."""
    cmd = [
        "uv", "run",
        "--with", "rembg[cpu,cli]",
        "--with", "pillow",
        "rembg", "i",
        "-m", "isnet-anime",
        str(input_path),
        str(output_path),
    ]

    print(f"  Extracting sprite with rembg...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  rembg failed: {result.stderr[:300]}")
        return False
    return output_path.exists()


# ---------------------------------------------------------------------------
# Main Generation Pipeline
# ---------------------------------------------------------------------------


def generate_pose(
    pose_name: str,
    max_retries: int = MAX_RETRIES,
    bob_ref_path: Path = BOB_REF,
    scene_path: Path = SCENE_BG,
    output_dir: Path = SPRITES_DIR,
    training_dir: Path = TRAINING_DIR,
) -> str | None:
    """
    Generate a validated Bob pose sprite.

    1. Create inset (Bob-ref in corner of scene)
    2. Run mflux-generate-kontext
    3. Validate result
    4. If FAIL → retry with seed += 100
    5. If PASS → rembg → save sprite
    6. If training candidate → copy to training_data/

    Returns path to validated sprite, or None if all retries exhausted.
    """
    if pose_name not in POSE_LIBRARY:
        print(f"Unknown pose: {pose_name}. Available: {list(POSE_LIBRARY.keys())}")
        return None

    spec = POSE_LIBRARY[pose_name]
    output_dir.mkdir(parents=True, exist_ok=True)
    training_dir.mkdir(parents=True, exist_ok=True)
    INSET_DIR.mkdir(parents=True, exist_ok=True)

    # Create inset base image
    inset_path = INSET_DIR / f"inset_{pose_name}.png"
    create_inset_image(scene_path, bob_ref_path, inset_path)
    print(f"  Inset created: {inset_path}")

    attempts_log: list[dict] = []

    for attempt in range(max_retries):
        seed = spec.seed_start + attempt * SEED_INCREMENT
        raw_output = output_dir / f"raw_{pose_name}_s{seed}.png"

        print(f"\n{'='*60}")
        print(f"  Pose: {pose_name} | Attempt {attempt + 1}/{max_retries} | Seed: {seed}")
        print(f"{'='*60}")

        # Generate
        if not run_kontext(inset_path, raw_output, spec.prompt, seed):
            attempts_log.append({"seed": seed, "status": "generation_failed"})
            continue

        # Validate
        result = validate(
            generated_path=str(raw_output),
            bob_ref_path=str(bob_ref_path),
            require_face=spec.require_face,
        )

        attempt_info = {
            "seed": seed,
            "status": "PASS" if result.passed else "FAIL",
            "person_conf": _json_safe(result.person_confidence),
            "person_height": _json_safe(result.person_height_pct),
            "face_dist": _json_safe(result.face_distance),
            "face_cos": _json_safe(result.face_cosine_sim),
            "face_dino": _json_safe(result.face_dino_similarity),
            "style_sim": _json_safe(result.style_similarity),
            "inset_ok": _json_safe(result.inset_removed),
            "errors": result.errors,
        }
        attempts_log.append(attempt_info)

        print(f"\n  Validation: {'PASS' if result.passed else 'FAIL'}")
        print(f"  Person: conf={result.person_confidence:.3f}, height={result.person_height_pct:.1f}%")
        print(f"  Face: dist={result.face_distance:.3f}, cos={result.face_cosine_sim:.3f}")
        print(f"  Style: sim={result.style_similarity:.3f}")
        print(f"  Inset: {'OK' if result.inset_removed else 'REMNANT'}")

        if not result.passed:
            print(f"  Errors: {result.errors}")
            # Keep raw file for debugging but continue
            continue

        # Extract sprite (remove background)
        sprite_path = output_dir / f"bob_{pose_name}.png"
        if not extract_sprite(raw_output, sprite_path):
            print("  Sprite extraction failed, keeping raw image")
            shutil.copy2(raw_output, sprite_path)

        print(f"\n  Sprite saved: {sprite_path}")

        # Check training candidacy
        if is_training_candidate(result):
            training_path = training_dir / f"bob_{pose_name}_s{seed}.png"
            shutil.copy2(str(raw_output), str(training_path))
            print(f"  Training candidate saved: {training_path}")

        # Save generation log
        log_path = output_dir / f"log_{pose_name}.json"
        with open(log_path, "w") as f:
            json.dump(
                {
                    "pose": pose_name,
                    "final_seed": seed,
                    "attempts": attempts_log,
                    "sprite_path": str(sprite_path),
                },
                f,
                indent=2,
            )

        return str(sprite_path)

    # All retries exhausted
    print(f"\n  FAILED: All {max_retries} attempts exhausted for pose '{pose_name}'")
    log_path = output_dir / f"log_{pose_name}.json"
    with open(log_path, "w") as f:
        json.dump(
            {"pose": pose_name, "attempts": attempts_log, "sprite_path": None},
            f,
            indent=2,
        )
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate validated Bob pose sprites")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pose", choices=list(POSE_LIBRARY.keys()), help="Generate single pose")
    group.add_argument("--all", action="store_true", help="Generate all 8 poses")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    parser.add_argument("--bob-ref", type=Path, default=BOB_REF)
    parser.add_argument("--scene", type=Path, default=SCENE_BG)
    parser.add_argument("--output-dir", type=Path, default=SPRITES_DIR)
    parser.add_argument("--training-dir", type=Path, default=TRAINING_DIR)
    args = parser.parse_args()

    poses = list(POSE_LIBRARY.keys()) if args.all else [args.pose]
    results: dict[str, str | None] = {}

    for pose_name in poses:
        sprite = generate_pose(
            pose_name,
            max_retries=args.max_retries,
            bob_ref_path=args.bob_ref,
            scene_path=args.scene,
            output_dir=args.output_dir,
            training_dir=args.training_dir,
        )
        results[pose_name] = sprite

    # Summary
    print(f"\n{'='*60}")
    print(f"  GENERATION SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for v in results.values() if v is not None)
    failed = sum(1 for v in results.values() if v is None)
    print(f"  Passed: {passed}/{len(results)}")
    print(f"  Failed: {failed}/{len(results)}")
    for name, path in results.items():
        status = "OK" if path else "FAILED"
        print(f"    {name}: {status}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
