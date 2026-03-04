#!/usr/bin/env python3
"""
Bob Identity Validation Pipeline (Phase 1, D-020).

5-tier validation:
  1. YOLO26 nano  — person detection + bounding box proportions
  2. InsightFace ArcFace (buffalo_l) — 512-d face embedding vs Bob reference
  2.5. DINOv2 face crop — fine-grained visual similarity on cropped face regions
  3. CLIP ViT-L-14 — full-image style consistency
  4. Inset removal — verify no white rectangle remnant in top-left corner

Dependencies (all pip-installable, no CUDA needed, Mac M1 compatible):
    insightface    — ArcFace buffalo_l, 512-d embeddings (~500 MB)
    onnxruntime    — inference backend for InsightFace
    ultralytics    — YOLO26 nano (auto-downloads)
    transformers   — DINOv2-base from Meta (Apache 2.0, ~330 MB)
    open-clip-torch — ViT-L-14 CLIP (~900 MB)
    pillow         — image loading

Install (Python 3.12 venv):
    uv pip install insightface onnxruntime ultralytics transformers \
        open-clip-torch pillow torch "setuptools<70"
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class ValidationResult:
    passed: bool = False
    # Tier 1: Person detection
    person_detected: bool = False
    person_confidence: float = 0.0
    person_height_pct: float = 0.0
    person_bbox: list[int] = field(default_factory=list)  # [x1, y1, x2, y2]
    # Tier 2: Face identity (InsightFace ArcFace, 512-d)
    face_detected: bool = False
    face_distance: float = 1.0  # euclidean, lower = better
    face_cosine_sim: float = 0.0  # higher = better
    # Tier 2.5: DINOv2 face crop similarity
    face_dino_similarity: float = 0.0  # DINOv2 cosine on cropped faces
    # Tier 3: Style consistency
    style_similarity: float = 0.0  # CLIP cosine, > 0.65 = consistent
    # Tier 4: Inset removal
    inset_removed: bool = False
    # Errors
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        def _convert(obj: object) -> object:
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
        return json.dumps(asdict(self), indent=2, default=_convert)


# ---------------------------------------------------------------------------
# Tier 1: Person Detection (YOLO26 nano)
# ---------------------------------------------------------------------------


def check_person(
    image_path: str,
    min_confidence: float = 0.7,
    min_height_pct: float = 20.0,
    max_height_pct: float = 85.0,
) -> tuple[bool, float, float, list[int]]:
    """Detect person using YOLO26 nano. Returns (detected, confidence, height_pct, bbox)."""
    from ultralytics import YOLO

    model = YOLO("yolo11n.pt")  # YOLO26 may need ultralytics update; fall back to v11
    results = model(image_path, verbose=False)

    img = Image.open(image_path)
    img_h = img.height

    best_conf = 0.0
    best_bbox: list[int] = []
    best_height_pct = 0.0

    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            if cls == 0 and conf > best_conf:  # class 0 = person
                best_conf = conf
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                best_bbox = [int(x1), int(y1), int(x2), int(y2)]
                best_height_pct = (y2 - y1) / img_h * 100

    detected = (
        best_conf >= min_confidence
        and min_height_pct <= best_height_pct <= max_height_pct
    )
    return detected, best_conf, best_height_pct, best_bbox


# ---------------------------------------------------------------------------
# Tier 2: Face Identity (InsightFace ArcFace — 512-d embeddings)
# ---------------------------------------------------------------------------

# Module-level cache for InsightFace app (heavy init)
_insightface_app = None


def _get_insightface_app():
    """Lazy-init InsightFace app (buffalo_l model)."""
    global _insightface_app
    if _insightface_app is None:
        from insightface.app import FaceAnalysis
        _insightface_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        _insightface_app.prepare(ctx_id=-1, det_size=(640, 640))
    return _insightface_app


def check_face_identity(
    image_path: str,
    ref_path: str,
    max_distance: float = 0.6,
    min_cosine_sim: float = 0.90,
) -> tuple[bool, float, float, bool]:
    """Compare 512-d ArcFace embeddings. Returns (match, distance, cosine_sim, face_detected)."""
    import cv2

    app = _get_insightface_app()

    ref_img = cv2.imread(ref_path)
    ref_faces = app.get(ref_img)
    if not ref_faces:
        return False, 1.0, 0.0, False

    gen_img = cv2.imread(image_path)
    gen_faces = app.get(gen_img)
    if not gen_faces:
        return False, 1.0, 0.0, False

    ref_emb = ref_faces[0].embedding
    gen_emb = gen_faces[0].embedding

    # Euclidean distance
    distance = float(np.linalg.norm(ref_emb - gen_emb))

    # Cosine similarity
    dot = float(np.dot(ref_emb, gen_emb))
    norm_ref = float(np.linalg.norm(ref_emb))
    norm_gen = float(np.linalg.norm(gen_emb))
    cosine_sim = dot / (norm_ref * norm_gen) if (norm_ref * norm_gen) > 0 else 0.0

    match = distance < max_distance and cosine_sim > min_cosine_sim
    return match, distance, cosine_sim, True


def _get_face_bbox(image_path: str) -> tuple[int, int, int, int] | None:
    """Get face bounding box via InsightFace. Returns (x1, y1, x2, y2) or None."""
    import cv2

    app = _get_insightface_app()
    img = cv2.imread(image_path)
    faces = app.get(img)
    if not faces:
        return None
    bbox = faces[0].bbox.astype(int)
    return int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])


# ---------------------------------------------------------------------------
# Tier 2.5: DINOv2 Face Crop Similarity
# ---------------------------------------------------------------------------

# Module-level cache for DINOv2
_dinov2_model = None
_dinov2_transform = None


def _get_dinov2():
    """Lazy-init DINOv2-base model."""
    global _dinov2_model, _dinov2_transform
    if _dinov2_model is None:
        import torch
        from transformers import AutoImageProcessor, AutoModel

        _dinov2_transform = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
        _dinov2_model = AutoModel.from_pretrained("facebook/dinov2-base")
        _dinov2_model.eval()
    return _dinov2_model, _dinov2_transform


def _get_face_crop(image_path: str, padding: float = 0.6) -> Image.Image | None:
    """Extract face region with padding for hair/stubble context.

    Uses InsightFace to find face bbox, then expands by `padding` ratio
    to include hair, jawline, stubble — features critical for cartoon identity.
    """
    bbox = _get_face_bbox(image_path)
    if bbox is None:
        return None

    x1, y1, x2, y2 = bbox
    h = y2 - y1
    w = x2 - x1

    # Expand bbox by padding ratio
    pad_h = int(h * padding)
    pad_w = int(w * padding)

    img = Image.open(image_path).convert("RGB")
    img_w, img_h = img.size
    crop_x1 = max(0, x1 - pad_w)
    crop_y1 = max(0, y1 - pad_h)
    crop_x2 = min(img_w, x2 + pad_w)
    crop_y2 = min(img_h, y2 + pad_h)

    return img.crop((crop_x1, crop_y1, crop_x2, crop_y2))


def check_face_dino(
    image_path: str,
    ref_path: str,
    min_similarity: float = 0.75,
) -> tuple[bool, float]:
    """DINOv2 similarity on cropped face regions.

    DINOv2 scores 70% on fine-grained visual tasks where CLIP scores 15%.
    Excels at distinguishing subtle cartoon face differences:
    - Hair style/color
    - Facial hair details
    - Expression nuances
    - Face shape and proportions
    """
    import torch

    ref_crop = _get_face_crop(ref_path)
    gen_crop = _get_face_crop(image_path)

    if ref_crop is None or gen_crop is None:
        return False, 0.0

    model, processor = _get_dinov2()

    def get_embedding(img: Image.Image) -> torch.Tensor:
        inputs = processor(images=img, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        # Use CLS token embedding
        emb = outputs.last_hidden_state[:, 0, :]
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb

    emb_ref = get_embedding(ref_crop)
    emb_gen = get_embedding(gen_crop)

    similarity = float((emb_gen @ emb_ref.T).item())
    return similarity >= min_similarity, similarity


# ---------------------------------------------------------------------------
# Tier 3: Style Consistency (CLIP ViT-L-14)
# ---------------------------------------------------------------------------

# Module-level cache for CLIP
_clip_model = None
_clip_preprocess = None


def _get_clip():
    """Lazy-init CLIP ViT-L-14 model."""
    global _clip_model, _clip_preprocess
    if _clip_model is None:
        import open_clip
        _clip_model, _, _clip_preprocess = open_clip.create_model_and_transforms(
            "ViT-L-14", pretrained="openai"
        )
        _clip_model.eval()
    return _clip_model, _clip_preprocess


def check_style_consistency(
    image_path: str,
    ref_path: str,
    min_similarity: float = 0.65,
) -> tuple[bool, float]:
    """CLIP ViT-L-14 style similarity. 3x larger than ViT-B-32, +12% accuracy."""
    import torch

    model, preprocess = _get_clip()

    def get_embedding(path: str) -> torch.Tensor:
        img = preprocess(Image.open(path).convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            emb = model.encode_image(img)
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb

    emb_gen = get_embedding(image_path)
    emb_ref = get_embedding(ref_path)

    similarity = float((emb_gen @ emb_ref.T).item())
    return similarity >= min_similarity, similarity


# ---------------------------------------------------------------------------
# Tier 4: Inset Removal Check
# ---------------------------------------------------------------------------


def check_inset_removed(
    image_path: str,
    corner_size: int = 200,
    brightness_threshold: float = 200.0,
) -> bool:
    """Check top-left corner for white rectangle remnant (inset artifact)."""
    img = Image.open(image_path).convert("RGB")
    corner = img.crop((0, 0, corner_size, corner_size))
    arr = np.array(corner, dtype=np.float64)
    avg_brightness = arr.mean()
    return avg_brightness < brightness_threshold


# ---------------------------------------------------------------------------
# Main Validation
# ---------------------------------------------------------------------------


def validate(
    generated_path: str,
    bob_ref_path: str = "bob-preview/bob_base_vaultboy.png",
    require_face: bool = True,
    min_person_confidence: float = 0.7,
    min_height_pct: float = 20.0,
    max_height_pct: float = 85.0,
    max_face_distance: float = 20.0,  # ArcFace 512-d: 0=identical, ~30=different face
    min_face_cosine_sim: float = 0.50,  # ArcFace cosine: 1.0=identical, <0.4=different
    min_face_dino_sim: float = 0.75,  # DINOv2 face crop: 1.0=identical, <0.7=different
    min_style_sim: float = 0.65,
) -> ValidationResult:
    """Run full 5-tier validation pipeline on a generated image."""
    result = ValidationResult()

    # Tier 1: Person detection
    try:
        detected, conf, height_pct, bbox = check_person(
            generated_path, min_person_confidence, min_height_pct, max_height_pct
        )
        result.person_detected = detected
        result.person_confidence = round(conf, 4)
        result.person_height_pct = round(height_pct, 2)
        result.person_bbox = bbox
        if not detected:
            reason = f"conf={conf:.3f}" if conf < min_person_confidence else f"height={height_pct:.1f}%"
            result.errors.append(f"Person detection failed: {reason}")
    except Exception as e:
        result.errors.append(f"Person detection error: {e}")

    # Tier 2: Face identity (InsightFace ArcFace 512-d)
    try:
        match, dist, cos_sim, face_found = check_face_identity(
            generated_path, bob_ref_path, max_face_distance, min_face_cosine_sim
        )
        result.face_detected = face_found
        result.face_distance = round(dist, 4)
        result.face_cosine_sim = round(cos_sim, 4)
        if require_face and not match:
            if not face_found:
                result.errors.append("Face not detected in generated image")
            else:
                result.errors.append(
                    f"Face identity mismatch: dist={dist:.3f} (max {max_face_distance}), "
                    f"cos={cos_sim:.3f} (min {min_face_cosine_sim})"
                )
    except Exception as e:
        result.errors.append(f"Face identity error: {e}")

    # Tier 2.5: DINOv2 face crop similarity
    if require_face and result.face_detected:
        try:
            dino_ok, dino_sim = check_face_dino(
                generated_path, bob_ref_path, min_face_dino_sim
            )
            result.face_dino_similarity = round(dino_sim, 4)
            if not dino_ok:
                result.errors.append(
                    f"Face DINOv2 mismatch: sim={dino_sim:.3f} (min {min_face_dino_sim})"
                )
        except Exception as e:
            result.errors.append(f"Face DINOv2 error: {e}")

    # Tier 3: Style consistency
    try:
        consistent, similarity = check_style_consistency(
            generated_path, bob_ref_path, min_style_sim
        )
        result.style_similarity = round(similarity, 4)
        if not consistent:
            result.errors.append(
                f"Style inconsistent: sim={similarity:.3f} (min {min_style_sim})"
            )
    except Exception as e:
        result.errors.append(f"Style consistency error: {e}")

    # Tier 4: Inset removal
    try:
        result.inset_removed = check_inset_removed(generated_path)
        if not result.inset_removed:
            result.errors.append("Inset remnant detected in top-left corner")
    except Exception as e:
        result.errors.append(f"Inset check error: {e}")

    # Overall result
    face_ok = (not require_face) or (result.face_detected and result.face_distance < max_face_distance)
    result.passed = (
        result.person_detected
        and face_ok
        and result.style_similarity >= min_style_sim
        and result.inset_removed
        and len(result.errors) == 0
    )

    return result


# ---------------------------------------------------------------------------
# Training Data Curation
# ---------------------------------------------------------------------------


def is_training_candidate(
    result: ValidationResult,
    max_face_distance: float = 15.0,  # stricter ArcFace threshold for training
    min_face_dino_sim: float = 0.80,
    min_style_sim: float = 0.70,
    min_person_height_pct: float = 50.0,
) -> bool:
    """Stricter thresholds for LoRA training data curation."""
    return (
        result.passed
        and result.face_detected
        and result.face_distance < max_face_distance
        and result.face_dino_similarity >= min_face_dino_sim
        and result.style_similarity >= min_style_sim
        and result.person_height_pct >= min_person_height_pct
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Bob identity in generated image")
    parser.add_argument("image", help="Path to generated image")
    parser.add_argument(
        "--bob-ref",
        default=".claude/dev-docs/bob-vr/bob-preview/bob_base_vaultboy.png",
        help="Path to Bob reference image",
    )
    parser.add_argument("--require-face", action="store_true", default=True)
    parser.add_argument("--no-require-face", dest="require_face", action="store_false")
    parser.add_argument("--min-style-sim", type=float, default=0.65)
    parser.add_argument("--max-face-distance", type=float, default=20.0)
    parser.add_argument("--min-face-dino-sim", type=float, default=0.75)
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = validate(
        generated_path=args.image,
        bob_ref_path=args.bob_ref,
        require_face=args.require_face,
        min_style_sim=args.min_style_sim,
        max_face_distance=args.max_face_distance,
        min_face_dino_sim=args.min_face_dino_sim,
    )

    if args.json:
        print(result.to_json())
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{'='*60}")
        print(f"  Bob Validation: {status}")
        print(f"{'='*60}")
        print(f"  Person:   {'YES' if result.person_detected else 'NO'} "
              f"(conf={result.person_confidence:.3f}, height={result.person_height_pct:.1f}%)")
        print(f"  Face:     {'YES' if result.face_detected else 'NO'} "
              f"(dist={result.face_distance:.3f}, cos={result.face_cosine_sim:.3f})")
        print(f"  FaceDINO: sim={result.face_dino_similarity:.3f}")
        print(f"  Style:    sim={result.style_similarity:.3f}")
        print(f"  Inset:    {'removed' if result.inset_removed else 'REMNANT DETECTED'}")
        if result.errors:
            print(f"\n  Errors:")
            for err in result.errors:
                print(f"    - {err}")
        print(f"{'='*60}")

        # Training data candidacy
        if result.passed:
            candidate = is_training_candidate(result)
            print(f"  LoRA training candidate: {'YES' if candidate else 'NO (thresholds too strict)'}")
            print(f"{'='*60}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
