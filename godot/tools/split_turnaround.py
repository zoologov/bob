#!/usr/bin/env python3
"""
Split a turnaround sheet into individual character views for LoRA training.

Detects character silhouettes on the sheet and crops each one into a separate
1024x1024 image with solid background (white or green chroma key).

Usage:
    python3 godot/tools/split_turnaround.py \
        --input godot/assets/training_data/turnaround/bob_turnaround_s42.png \
        --output-dir godot/assets/training_data/bob_identity/ \
        --prefix bob_view

Dependencies:
    pillow
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def find_character_columns(
    img: Image.Image,
    bg_threshold: int = 240,
    min_content_rows: int = 50,
    min_gap: int = 20,
) -> list[tuple[int, int]]:
    """
    Find character bounding columns by scanning for non-background vertical strips.

    Returns list of (x_start, x_end) tuples for each detected character.
    """
    width, height = img.size
    pixels = img.load()

    # For each column, count how many rows have non-background pixels
    col_content = []
    for x in range(width):
        count = 0
        for y in range(height):
            r, g, b = pixels[x, y][:3]
            if r < bg_threshold or g < bg_threshold or b < bg_threshold:
                count += 1
        col_content.append(count)

    # Find contiguous column ranges with content
    in_region = False
    regions: list[tuple[int, int]] = []
    start = 0

    for x, count in enumerate(col_content):
        if count >= min_content_rows and not in_region:
            in_region = True
            start = x
        elif count < min_content_rows and in_region:
            in_region = False
            regions.append((start, x))

    if in_region:
        regions.append((start, width))

    # Merge regions that are too close (less than min_gap apart)
    if not regions:
        return []

    merged: list[tuple[int, int]] = [regions[0]]
    for start, end in regions[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end < min_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    return merged


def find_character_rows(
    img: Image.Image,
    x_start: int,
    x_end: int,
    bg_threshold: int = 240,
) -> tuple[int, int]:
    """Find top and bottom bounds of character content within given columns."""
    width, height = img.size
    pixels = img.load()

    top = height
    bottom = 0

    for y in range(height):
        for x in range(x_start, min(x_end, width)):
            r, g, b = pixels[x, y][:3]
            if r < bg_threshold or g < bg_threshold or b < bg_threshold:
                top = min(top, y)
                bottom = max(bottom, y)
                break

    return top, bottom + 1


def crop_and_pad(
    img: Image.Image,
    x_start: int,
    x_end: int,
    y_start: int,
    y_end: int,
    target_size: int = 1024,
    bg_color: tuple[int, int, int] = (255, 255, 255),
    padding_pct: float = 0.1,
) -> Image.Image:
    """
    Crop character region and pad to square target_size.

    Adds padding_pct of the character size as margin on all sides.
    """
    char_w = x_end - x_start
    char_h = y_end - y_start

    # Add padding
    pad_x = int(char_w * padding_pct)
    pad_y = int(char_h * padding_pct)

    crop_x1 = max(0, x_start - pad_x)
    crop_y1 = max(0, y_start - pad_y)
    crop_x2 = min(img.width, x_end + pad_x)
    crop_y2 = min(img.height, y_end + pad_y)

    cropped = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # Scale to fit in target_size while maintaining aspect ratio
    cw, ch = cropped.size
    scale = min(target_size / cw, target_size / ch) * 0.85  # 85% fill
    new_w = int(cw * scale)
    new_h = int(ch * scale)

    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    # Center on square canvas
    canvas = Image.new("RGB", (target_size, target_size), bg_color)
    offset_x = (target_size - new_w) // 2
    offset_y = (target_size - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y))

    return canvas


VIEW_NAMES = [
    "front",
    "three_quarter_left",
    "left_profile",
    "back",
    "right_profile",
]


def split_turnaround(
    input_path: Path,
    output_dir: Path,
    prefix: str = "bob_view",
    target_size: int = 1024,
    bg_color: tuple[int, int, int] = (255, 255, 255),
) -> list[Path]:
    """
    Split turnaround sheet into individual views.

    Returns list of saved file paths.
    """
    img = Image.open(input_path).convert("RGB")
    print(f"Input image: {img.size[0]}x{img.size[1]}")

    # Detect character columns
    columns = find_character_columns(img)
    print(f"Detected {len(columns)} character regions: {columns}")

    if not columns:
        print("ERROR: No characters detected in turnaround sheet")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for i, (x_start, x_end) in enumerate(columns):
        # Find vertical bounds
        y_start, y_end = find_character_rows(img, x_start, x_end)
        print(f"  View {i+1}: x=[{x_start}-{x_end}], y=[{y_start}-{y_end}], "
              f"size={x_end-x_start}x{y_end-y_start}")

        # Crop and pad to square
        view = crop_and_pad(img, x_start, x_end, y_start, y_end,
                           target_size=target_size, bg_color=bg_color)

        # Name based on expected view order
        view_name = VIEW_NAMES[i] if i < len(VIEW_NAMES) else f"view_{i+1}"
        out_path = output_dir / f"{prefix}_{view_name}.png"
        view.save(str(out_path), "PNG")
        saved.append(out_path)
        print(f"  Saved: {out_path} ({target_size}x{target_size})")

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Split turnaround sheet into views")
    parser.add_argument("--input", type=Path, required=True, help="Turnaround sheet image")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    parser.add_argument("--prefix", default="bob_view", help="Output filename prefix")
    parser.add_argument("--size", type=int, default=1024, help="Output image size (square)")
    parser.add_argument("--bg", default="white", choices=["white", "green"],
                       help="Background color")
    args = parser.parse_args()

    bg = (255, 255, 255) if args.bg == "white" else (0, 177, 64)

    paths = split_turnaround(
        input_path=args.input,
        output_dir=args.output_dir,
        prefix=args.prefix,
        target_size=args.size,
        bg_color=bg,
    )

    print(f"\nSplit complete: {len(paths)} views saved")


if __name__ == "__main__":
    main()
