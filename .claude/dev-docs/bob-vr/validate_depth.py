#!/usr/bin/env python3
"""
Validate Depth Anything V2 on Apple Silicon.

Bead: bob-6sp
Goal: Generate depth map + parallax layers from Bob preview image.

Run: uv run --with torch --with torchvision --with transformers --with pillow --with numpy validate_depth.py
"""

import time
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation


# --- Config ---
INPUT_IMAGE = Path(__file__).parent / "bob-preview" / "bob_bunker_reading.png"
OUTPUT_DIR = Path(__file__).parent / "depth-validation"
MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
NUM_LAYERS = 4  # far, mid, near, foreground


def detect_device() -> str:
    """Pick best available device."""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def generate_depth_map(image: Image.Image, device: str) -> np.ndarray:
    """Run Depth Anything V2 and return normalized depth map (0.0-1.0)."""
    print(f"Loading model: {MODEL_ID}")
    t0 = time.time()
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to(device)
    t_load = time.time() - t0
    print(f"  Model loaded in {t_load:.1f}s on {device}")

    print("Running inference...")
    t0 = time.time()
    inputs = processor(images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    # Get depth and resize to original image size
    predicted_depth = outputs.predicted_depth.squeeze().cpu().numpy()
    t_infer = time.time() - t0
    print(f"  Inference done in {t_infer:.3f}s")
    print(f"  Raw depth shape: {predicted_depth.shape}, "
          f"range: [{predicted_depth.min():.2f}, {predicted_depth.max():.2f}]")

    # Resize depth to match original image
    from PIL import Image as PILImage
    depth_pil = PILImage.fromarray(predicted_depth)
    depth_pil = depth_pil.resize(image.size, PILImage.BILINEAR)
    depth_resized = np.array(depth_pil)

    # Normalize to 0.0-1.0 (0 = far, 1 = near)
    d_min, d_max = depth_resized.min(), depth_resized.max()
    if d_max - d_min > 0:
        depth_norm = (depth_resized - d_min) / (d_max - d_min)
    else:
        depth_norm = np.zeros_like(depth_resized)

    return depth_norm


def save_depth_map(depth: np.ndarray, output_dir: Path) -> None:
    """Save depth map as grayscale PNG (white = near, black = far)."""
    depth_uint8 = (depth * 255).astype(np.uint8)
    img = Image.fromarray(depth_uint8, mode="L")
    path = output_dir / "depth_map.png"
    img.save(path)
    print(f"  Saved: {path}")


def split_into_layers(
    image: Image.Image,
    depth: np.ndarray,
    output_dir: Path,
    num_layers: int = 4,
) -> None:
    """Split image into parallax layers based on depth thresholds.

    Layers (depth 0=far, 1=near):
      Layer 0 (far):   depth < threshold[0]  — sky, distant background
      Layer 1 (mid):   threshold[0] - threshold[1]  — walls, mid-ground
      Layer 2 (near):  threshold[1] - threshold[2]  — furniture, objects near Bob
      Layer 3 (fg):    depth > threshold[2]  — foreground objects, Bob
    """
    img_rgba = image.convert("RGBA")
    img_array = np.array(img_rgba)

    # Calculate thresholds using quantiles for even distribution
    thresholds = []
    for i in range(1, num_layers):
        q = i / num_layers
        thresholds.append(np.quantile(depth, q))

    print(f"  Depth thresholds (quantile-based): {[f'{t:.3f}' for t in thresholds]}")

    layer_names = ["far", "mid", "near", "foreground"]
    if num_layers > len(layer_names):
        layer_names = [f"layer_{i}" for i in range(num_layers)]

    for i in range(num_layers):
        # Create mask for this layer
        if i == 0:
            mask = depth < thresholds[0]
        elif i == num_layers - 1:
            mask = depth >= thresholds[-1]
        else:
            mask = (depth >= thresholds[i - 1]) & (depth < thresholds[i])

        # Apply mask: keep pixels in this depth range, make others transparent
        layer = img_array.copy()
        layer[~mask, 3] = 0  # Set alpha to 0 for pixels outside this layer

        # Also apply soft edge (feather) to reduce hard boundaries
        # Simple: dilate mask by 2px and apply linear falloff
        from scipy.ndimage import binary_dilation
        dilated = binary_dilation(mask, iterations=3)
        edge = dilated & ~mask
        layer[edge, 3] = 128  # 50% opacity for edge pixels

        layer_img = Image.fromarray(layer, mode="RGBA")
        name = layer_names[i] if i < len(layer_names) else f"layer_{i}"
        path = output_dir / f"layer_{i}_{name}.png"
        layer_img.save(path)

        pixel_count = mask.sum()
        pct = 100.0 * pixel_count / mask.size
        print(f"  Layer {i} ({name}): {pixel_count:,} pixels ({pct:.1f}%) → {path.name}")


def main() -> None:
    print("=" * 60)
    print("Depth Anything V2 — Validation on Apple Silicon")
    print("=" * 60)

    # Check input
    if not INPUT_IMAGE.exists():
        print(f"ERROR: Input image not found: {INPUT_IMAGE}")
        sys.exit(1)

    print(f"\nInput: {INPUT_IMAGE}")
    image = Image.open(INPUT_IMAGE).convert("RGB")
    print(f"  Size: {image.size[0]}x{image.size[1]}")

    # Create output dir
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Output dir: {OUTPUT_DIR}")

    # Detect device
    device = detect_device()
    print(f"Device: {device}")

    # Step 1: Generate depth map
    print("\n--- Step 1: Generate Depth Map ---")
    depth = generate_depth_map(image, device)
    save_depth_map(depth, OUTPUT_DIR)

    # Print depth distribution stats
    print(f"\n  Depth stats:")
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        print(f"    P{int(q*100):2d}: {np.quantile(depth, q):.3f}")

    # Step 2: Split into layers
    print(f"\n--- Step 2: Split into {NUM_LAYERS} Parallax Layers ---")
    split_into_layers(image, depth, OUTPUT_DIR, NUM_LAYERS)

    # Summary
    print("\n--- Summary ---")
    output_files = sorted(OUTPUT_DIR.glob("*.png"))
    total_size = 0
    for f in output_files:
        size_kb = f.stat().st_size / 1024
        total_size += size_kb
        print(f"  {f.name}: {size_kb:.0f} KB")
    print(f"  Total: {total_size:.0f} KB")

    print("\nValidation complete!")


if __name__ == "__main__":
    main()
