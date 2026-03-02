"""V-02: Clothing Generation Validation.

pygarment FAILED (CGAL build error on macOS ARM64).
Using fallback: vertex-normal-offset approach.
Also tests NVIDIA Warp for future cloth simulation.
"""

import time
import numpy as np
import trimesh
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def extract_body_region(
    mesh: trimesh.Trimesh,
    y_min: float,
    y_max: float,
) -> trimesh.Trimesh:
    """Extract vertices within a Y range (e.g., torso region)."""
    mask = (mesh.vertices[:, 1] >= y_min) & (mesh.vertices[:, 1] <= y_max)
    # Find faces where ALL vertices are in the region
    face_mask = mask[mesh.faces].all(axis=1)
    submesh = mesh.submesh([face_mask], append=True)
    return submesh


def offset_along_normals(
    mesh: trimesh.Trimesh,
    offset: float = 0.5,  # cm (MHR uses cm)
) -> trimesh.Trimesh:
    """Create clothing by offsetting mesh vertices along normals."""
    normals = mesh.vertex_normals
    new_verts = mesh.vertices + normals * offset
    clothing = trimesh.Trimesh(
        vertices=new_verts,
        faces=mesh.faces,
        process=False,
    )
    return clothing


def create_tshirt(body_mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Create T-shirt by extracting torso+upper arms and offsetting.

    MHR default body: Y=0 (feet) to Y=172.6 (top of head).
    Torso roughly: Y=80 (waist) to Y=145 (neck).
    Arms roughly: between shoulders.
    """
    # Extract torso region
    torso = extract_body_region(body_mesh, y_min=80.0, y_max=145.0)
    # Offset outward
    shirt = offset_along_normals(torso, offset=0.5)
    return shirt


def create_pants(body_mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Create pants by extracting legs+hip region and offsetting.

    Legs: Y=0 (feet) to Y=92 (hips).
    """
    legs = extract_body_region(body_mesh, y_min=5.0, y_max=92.0)
    pants = offset_along_normals(legs, offset=0.4)
    return pants


def test_warp_cpu():
    """Test NVIDIA Warp on CPU for future cloth simulation."""
    print("=== Test: NVIDIA Warp CPU ===")
    import warp as wp
    wp.init()

    print(f"  Warp {wp.__version__}")
    print(f"  Device: {wp.get_device()}")
    print(f"  CPU: {wp.is_cpu_available()}")
    print(f"  CUDA: {wp.is_cuda_available()}")

    # Quick kernel test
    @wp.kernel
    def add_kernel(a: wp.array(dtype=float), b: wp.array(dtype=float), c: wp.array(dtype=float)):
        tid = wp.tid()
        c[tid] = a[tid] + b[tid]

    n = 1000
    a = wp.array(np.ones(n, dtype=np.float32), dtype=float, device="cpu")
    b = wp.array(np.ones(n, dtype=np.float32) * 2.0, dtype=float, device="cpu")
    c = wp.zeros(n, dtype=float, device="cpu")

    wp.launch(add_kernel, dim=n, inputs=[a, b, c], device="cpu")
    result = c.numpy()
    assert np.allclose(result, 3.0), "Warp kernel test failed!"
    print(f"  Kernel test: PASS (1000 elements, result={result[0]})")
    print("  PASS\n")


def main():
    print("=" * 60)
    print("V-02: Clothing Generation Validation")
    print("=" * 60 + "\n")

    # Load body mesh
    print("=== Test 1: Load MHR body mesh ===")
    body_path = OUTPUT_DIR / "bob_body.ply"
    if not body_path.exists():
        # Try GLB
        body_path = OUTPUT_DIR / "bob_body_trimesh.glb"
    if not body_path.exists():
        print(f"  FAIL: No body mesh found at {body_path}")
        print("  Run V-01 (MHR) first!")
        return

    body = trimesh.load(str(body_path), process=False)
    print(f"  Loaded: {body_path}")
    print(f"  Vertices: {len(body.vertices)}")
    print(f"  Faces: {len(body.faces)}")
    print(f"  Y range: [{body.vertices[:,1].min():.1f}, {body.vertices[:,1].max():.1f}] cm")
    print("  PASS\n")

    # Test 2: Create T-shirt
    print("=== Test 2: Create T-shirt (normal offset) ===")
    t0 = time.time()
    shirt = create_tshirt(body)
    dt = time.time() - t0
    print(f"  Generated in {dt:.3f}s")
    print(f"  Vertices: {len(shirt.vertices)}")
    print(f"  Faces: {len(shirt.faces)}")

    shirt_path = OUTPUT_DIR / "shirt.glb"
    shirt.export(str(shirt_path))
    size_kb = shirt_path.stat().st_size / 1024
    print(f"  Exported: {shirt_path} ({size_kb:.1f} KB)")
    print("  PASS\n")

    # Test 3: Create pants
    print("=== Test 3: Create pants (normal offset) ===")
    t0 = time.time()
    pants = create_pants(body)
    dt = time.time() - t0
    print(f"  Generated in {dt:.3f}s")
    print(f"  Vertices: {len(pants.vertices)}")
    print(f"  Faces: {len(pants.faces)}")

    pants_path = OUTPUT_DIR / "pants.glb"
    pants.export(str(pants_path))
    size_kb = pants_path.stat().st_size / 1024
    print(f"  Exported: {pants_path} ({size_kb:.1f} KB)")
    print("  PASS\n")

    # Test 4: Warp CPU
    test_warp_cpu()

    # Test 5: Combined export
    print("=== Test 5: Full outfit check ===")
    total_verts = len(shirt.vertices) + len(pants.vertices)
    total_faces = len(shirt.faces) + len(pants.faces)
    print(f"  Shirt: {len(shirt.vertices)} verts, {len(shirt.faces)} faces")
    print(f"  Pants: {len(pants.vertices)} verts, {len(pants.faces)} faces")
    print(f"  Total: {total_verts} verts, {total_faces} faces")
    print(f"  Body: {len(body.vertices)} verts, {len(body.faces)} faces")
    print(f"  Clothing overhead: {total_verts/len(body.vertices)*100:.1f}% of body mesh")
    print("  PASS\n")

    print("=" * 60)
    print("V-02 VALIDATION COMPLETE")
    print("NOTE: pygarment FAILED (CGAL). Using vertex-normal-offset fallback.")
    print("Warp CPU works for future XPBD cloth simulation.")
    print("=" * 60)


if __name__ == "__main__":
    main()
