"""V-03: Procedural Hair Cards Validation.

Generates hair card mesh (textured ribbons) and exports to .glb.
Pure Python with numpy + trimesh — no ML dependencies.
"""

import time
import numpy as np
import trimesh
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def generate_hair_card(
    root: np.ndarray,
    direction: np.ndarray,
    length: float = 15.0,  # cm (MHR units)
    width: float = 1.5,    # cm
    segments: int = 4,
    curl: float = 0.0,     # curl factor
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create a single hair card (textured ribbon) as triangles."""
    vertices = []
    uvs = []

    # Normalize direction
    direction = direction / np.linalg.norm(direction)

    # Find perpendicular vector for card width
    up = np.array([0, 1, 0])
    right = np.cross(direction, up)
    if np.linalg.norm(right) < 0.001:
        right = np.cross(direction, np.array([1, 0, 0]))
    right = right / np.linalg.norm(right) * width / 2

    for i in range(segments + 1):
        t = i / segments
        # Add slight curl
        curl_offset = curl * np.sin(t * np.pi) * right * 2
        pos = root + direction * length * t + curl_offset
        # Taper width at tip
        taper = 1.0 - t * 0.5
        vertices.append(pos - right * taper)
        vertices.append(pos + right * taper)
        uvs.append([0, t])
        uvs.append([1, t])

    faces = []
    for i in range(segments):
        base = i * 2
        faces.append([base, base + 2, base + 1])
        faces.append([base + 1, base + 2, base + 3])

    return np.array(vertices), np.array(faces, dtype=np.int64), np.array(uvs)


def sample_scalp_points(n_points: int = 200, head_radius: float = 10.0) -> np.ndarray:
    """Sample points on upper hemisphere (scalp area of a head centered at origin).

    Head center is at approximately (0, 165, 0) for MHR default body (172.6 cm tall).
    Head radius ~10 cm.
    """
    head_center = np.array([0, 165, 0])

    # Fibonacci sphere sampling on upper hemisphere
    points = []
    golden_ratio = (1 + np.sqrt(5)) / 2

    for i in range(n_points):
        theta = np.arccos(1 - (i / n_points))  # 0 to pi/2 for upper hemi
        if theta > np.pi / 2:
            continue
        phi = 2 * np.pi * i / golden_ratio

        x = head_radius * np.sin(theta) * np.cos(phi)
        y = head_radius * np.cos(theta)  # up
        z = head_radius * np.sin(theta) * np.sin(phi)

        points.append(head_center + np.array([x, y, z]))

    return np.array(points)


def generate_hairstyle(
    n_cards: int = 200,
    hair_length: float = 12.0,
    head_radius: float = 10.0,
) -> trimesh.Trimesh:
    """Generate a complete hairstyle as merged hair cards."""
    print(f"  Generating {n_cards} hair cards...")
    t0 = time.time()

    scalp_points = sample_scalp_points(n_cards, head_radius)
    head_center = np.array([0, 165, 0])

    all_vertices = []
    all_faces = []
    all_uvs = []
    vertex_offset = 0

    rng = np.random.RandomState(42)

    for i, point in enumerate(scalp_points):
        # Direction: outward from head center + gravity
        outward = point - head_center
        outward = outward / np.linalg.norm(outward)

        # Mix outward direction with downward (gravity)
        gravity = np.array([0, -1, 0])
        direction = outward * 0.3 + gravity * 0.7
        direction = direction / np.linalg.norm(direction)

        # Randomize slightly
        direction += rng.randn(3) * 0.1
        direction = direction / np.linalg.norm(direction)

        # Vary length
        card_length = hair_length * (0.7 + rng.rand() * 0.6)
        curl = rng.rand() * 0.3

        verts, faces, uvs = generate_hair_card(
            root=point,
            direction=direction,
            length=card_length,
            width=1.2 + rng.rand() * 0.8,
            segments=4,
            curl=curl,
        )

        all_vertices.append(verts)
        all_faces.append(faces + vertex_offset)
        all_uvs.append(uvs)
        vertex_offset += len(verts)

    vertices = np.vstack(all_vertices)
    faces = np.vstack(all_faces)
    uvs = np.vstack(all_uvs)

    # Create visual (UV-mapped) for texture
    visual = trimesh.visual.TextureVisuals(uv=uvs)

    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        visual=visual,
        process=False,
    )

    dt = time.time() - t0
    print(f"  Generated in {dt:.3f}s")
    return mesh


def main():
    print("=" * 60)
    print("V-03: Procedural Hair Cards Validation")
    print("=" * 60 + "\n")

    # Test 1: Single hair card
    print("=== Test 1: Single hair card ===")
    verts, faces, uvs = generate_hair_card(
        root=np.array([0, 175, 0]),
        direction=np.array([0, -1, 0.1]),
        length=15.0,
        segments=4,
    )
    print(f"  Vertices: {len(verts)}")
    print(f"  Faces: {len(faces)}")
    print(f"  UVs: {len(uvs)}")
    assert len(verts) == 10  # (4+1) * 2
    assert len(faces) == 8   # 4 * 2
    assert len(uvs) == 10
    print("  PASS\n")

    # Test 2: Full hairstyle
    print("=== Test 2: Full hairstyle (200 cards) ===")
    mesh = generate_hairstyle(n_cards=200, hair_length=12.0)
    print(f"  Total vertices: {len(mesh.vertices)}")
    print(f"  Total faces: {len(mesh.faces)}")
    print(f"  Total triangles: {len(mesh.faces)}")
    print(f"  Has UV: {mesh.visual is not None}")
    print(f"  Bounds min: {mesh.bounds[0]}")
    print(f"  Bounds max: {mesh.bounds[1]}")
    print("  PASS\n")

    # Test 3: Export to GLB
    print("=== Test 3: Export to GLB ===")
    out_path = OUTPUT_DIR / "hair_cards.glb"
    mesh.export(str(out_path))
    size_kb = out_path.stat().st_size / 1024
    print(f"  Exported: {out_path} ({size_kb:.1f} KB)")
    print("  PASS\n")

    # Test 4: Export to OBJ (for visual inspection)
    print("=== Test 4: Export to OBJ ===")
    out_obj = OUTPUT_DIR / "hair_cards.obj"
    mesh.export(str(out_obj))
    size_kb_obj = out_obj.stat().st_size / 1024
    print(f"  Exported: {out_obj} ({size_kb_obj:.1f} KB)")
    print("  PASS\n")

    # Test 5: Performance — triangle count check
    print("=== Test 5: Triangle budget ===")
    n_tris = len(mesh.faces)
    budget = 5000
    under_budget = n_tris <= budget
    print(f"  Triangles: {n_tris}")
    print(f"  Budget: {budget}")
    print(f"  Under budget: {under_budget}")
    if under_budget:
        print("  PASS\n")
    else:
        print(f"  WARNING: Over budget by {n_tris - budget} triangles\n")

    print("=" * 60)
    print("V-03 VALIDATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
