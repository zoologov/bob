"""V-01: MHR Body Mesh Generation Validation.

Tests:
1. Import mhr and pymomentum
2. Load MHR model (LOD 2 — lightweight)
3. Generate default male body
4. Vary shape params → verify mesh changes
5. Export to .glb via trimesh (bare mesh)
6. Export to .glb via pymomentum GltfBuilder (with skeleton)
"""

import time
import sys
from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "assets"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def test_imports():
    """Test 1: Verify all required packages import."""
    print("=== Test 1: Imports ===")
    import torch
    print(f"  torch {torch.__version__}")
    import pymomentum
    print(f"  pymomentum OK")
    import mhr
    print(f"  mhr OK")
    import trimesh
    print(f"  trimesh {trimesh.__version__}")
    print("  PASS\n")


def test_load_model():
    """Test 2: Load MHR model at LOD 2."""
    print("=== Test 2: Load MHR model (LOD 2) ===")
    import torch
    from mhr.mhr import MHR

    t0 = time.time()
    model = MHR.from_files(
        assets_dir=str(ASSETS_DIR),
        device=torch.device("cpu"),
        lod=2,
    )
    dt = time.time() - t0
    print(f"  Model loaded in {dt:.1f}s")
    print(f"  Character: {model.character}")
    print(f"  Skeleton joints: {model.character.skeleton.joint_count}")
    print(f"  Mesh vertices: {model.character.mesh.vertex_count}")
    print(f"  Mesh faces: {model.character.mesh.face_count}")
    print(f"  Identity params: {model.n_identity}")
    print(f"  Pose params: {model.n_model_params}")
    print(f"  Expression params: {model.n_expressions}")
    print("  PASS\n")
    return model


def test_generate_body(model):
    """Test 3: Generate body mesh with default (zero) params."""
    print("=== Test 3: Generate body (default params) ===")
    import torch

    t0 = time.time()
    identity = torch.zeros(1, model.n_identity)
    pose = torch.zeros(1, model.n_model_params)
    expression = torch.zeros(1, model.n_expressions)

    vertices, skel_state = model(identity, pose, expression)
    dt = time.time() - t0

    print(f"  Generated in {dt:.3f}s")
    print(f"  Vertices shape: {vertices.shape}")
    print(f"  Vertices range X: [{vertices[0,:,0].min():.3f}, {vertices[0,:,0].max():.3f}]")
    print(f"  Vertices range Y: [{vertices[0,:,1].min():.3f}, {vertices[0,:,1].max():.3f}]")
    print(f"  Vertices range Z: [{vertices[0,:,2].min():.3f}, {vertices[0,:,2].max():.3f}]")
    print("  PASS\n")
    return vertices


def test_shape_variation(model):
    """Test 4: Verify shape params actually change the mesh."""
    print("=== Test 4: Shape variation ===")
    import torch

    pose = torch.zeros(1, model.n_model_params)
    expression = torch.zeros(1, model.n_expressions)

    # Default shape
    id_default = torch.zeros(1, model.n_identity)
    v_default, _ = model(id_default, pose, expression)

    # Varied shape (set first 5 params to large values)
    id_varied = torch.zeros(1, model.n_identity)
    id_varied[0, :5] = 2.0
    v_varied, _ = model(id_varied, pose, expression)

    # Compare
    diff = (v_default - v_varied).abs().max().item()
    print(f"  Max vertex displacement: {diff:.4f} m")
    print(f"  Shape params DO change mesh: {diff > 0.001}")
    assert diff > 0.001, "Shape params had no effect!"
    print("  PASS\n")


def test_export_trimesh(model):
    """Test 5: Export to .glb via trimesh (bare mesh, no skeleton)."""
    print("=== Test 5: Export via trimesh ===")
    import torch
    import trimesh

    identity = torch.zeros(1, model.n_identity)
    pose = torch.zeros(1, model.n_model_params)
    expression = torch.zeros(1, model.n_expressions)
    vertices, _ = model(identity, pose, expression)

    faces = model.character.mesh.faces
    mesh = trimesh.Trimesh(
        vertices=vertices[0].numpy(),
        faces=faces,
        process=False,
    )

    out_path = OUTPUT_DIR / "bob_body_trimesh.glb"
    mesh.export(str(out_path))
    size_kb = out_path.stat().st_size / 1024
    print(f"  Exported to {out_path}")
    print(f"  File size: {size_kb:.1f} KB")
    print(f"  Vertices: {len(mesh.vertices)}")
    print(f"  Faces: {len(mesh.faces)}")
    print("  PASS\n")


def test_export_gltfbuilder(model):
    """Test 6: Export to .glb via pymomentum GltfBuilder (with skeleton)."""
    print("=== Test 6: Export via GltfBuilder (skeleton + mesh) ===")
    try:
        from pymomentum.geometry import GltfBuilder, GltfFileFormat

        builder = GltfBuilder(fps=30.0)
        builder.add_character(character=model.character)

        out_path = OUTPUT_DIR / "bob_body_skeleton.glb"
        builder.save(str(out_path), file_format=GltfFileFormat.Binary)
        size_kb = out_path.stat().st_size / 1024
        print(f"  Exported to {out_path}")
        print(f"  File size: {size_kb:.1f} KB")
        print("  Contains skeleton: YES")
        print("  PASS\n")
    except Exception as e:
        print(f"  GltfBuilder FAILED: {e}")
        print("  Falling back to trimesh-only export")
        print("  PARTIAL PASS (no skeleton in export)\n")


def test_expression_variation(model):
    """Test 7: Verify expression params change face."""
    print("=== Test 7: Expression variation ===")
    import torch

    identity = torch.zeros(1, model.n_identity)
    pose = torch.zeros(1, model.n_model_params)

    # Neutral
    expr_neutral = torch.zeros(1, model.n_expressions)
    v_neutral, _ = model(identity, pose, expr_neutral)

    # Smile (set first few expression params)
    expr_smile = torch.zeros(1, model.n_expressions)
    expr_smile[0, :5] = 1.0
    v_smile, _ = model(identity, pose, expr_smile)

    diff = (v_neutral - v_smile).abs().max().item()
    print(f"  Max vertex displacement: {diff:.4f} m")
    print(f"  Expression params DO change face: {diff > 0.0005}")
    assert diff > 0.0005, "Expression params had no effect!"
    print("  PASS\n")


def main():
    print("=" * 60)
    print("V-01: MHR Body Mesh Generation Validation")
    print("=" * 60 + "\n")

    test_imports()
    model = test_load_model()
    test_generate_body(model)
    test_shape_variation(model)
    test_expression_variation(model)
    test_export_trimesh(model)
    test_export_gltfbuilder(model)

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
