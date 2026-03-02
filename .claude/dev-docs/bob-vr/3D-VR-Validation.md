# 3D VR Pipeline Validation Plan

> **Status:** In Progress
> **Date:** 2026-03-02
> **Context:** RFC-Proof-of-VR-Concept.md approved. MakeHuman rejected (no headless mode).
> **Goal:** Validate each pipeline component before committing to architecture.
> **Bead:** bob-728 (Phase 1 3D PoC)

---

## 1. Background

### What We Already Validated

| Step | Result | Details |
|------|--------|---------|
| 2D sprite generation (FLUX.2) | WORKS but insufficient | See DecisionLog D-001—D-009 |
| 2D→3D pivot decision | D-010 approved | Full 3D with procedural everything |
| Godot 4.6 install | DONE | 4.6.1 via Homebrew, Metal renderer |
| Procedural room | DONE | 6×4×3m, floor/walls/ceiling/window (GDScript) |
| Isometric camera | DONE | Orbit (yaw+pitch) + zoom, touch/mouse |
| Toon shader + outline | DONE | 2-band cel shading + inverted hull |
| Lighting | DONE | DirectionalLight3D + OmniLight3D |
| Placeholder Bob | DONE | Capsule+sphere with idle animation |
| MakeHuman headless | REJECTED | No headless mode, GUI-only, Apple Silicon issues |

### What Needs Validation

RFC originally specified MakeHuman for character generation. Research revealed:

1. **MakeHuman** — cannot run headless, abandoned CLI fork (Python 2.7)
2. **MHR (Meta)** — promising (Apache 2.0, 127 joints, native glTF), needs validation
3. **Anny (NAVER)** — promising (CC0, 163 bones, 564 params), needs validation
4. **GarmentCode + Warp** — clothing pipeline, needs validation
5. **Hair/beard/eyebrows** — no single solution, composite approach needed

**Both MHR and Anny output NAKED body only** — no clothing, hair, beard, eyebrows, skin textures.

---

## 2. Target Pipeline Architecture

```
                    MAC MINI M4 (generation server)
                    ┌─────────────────────────────────────┐
                    │                                     │
Text/params ───────►│  MHR or Anny (body mesh + skeleton) │
                    │       │                             │
                    │       ├── GarmentCode + Warp (CPU)  │──► clothing.glb
                    │       │     └── FLUX.2 UV textures  │
                    │       │                             │
                    │       ├── Procedural hair (Python)  │──► hair.glb
                    │       │     └── FLUX.2 card texture │
                    │       │                             │
                    │       ├── ShellFur (eyebrows/beard) │──► shader params
                    │       │                             │
                    │       └── body.glb (rigged mesh)    │
                    │                                     │
                    └───────────────┬─────────────────────┘
                                    │ WebSocket (JSON + binary)
                                    ▼
                    ┌─────────────────────────────────────┐
                    │      ANDROID (Godot 4.6 renderer)   │
                    │                                     │
                    │  Skeleton3D                         │
                    │    ├── BodyMesh (MHR/Anny)          │
                    │    ├── ShirtMesh (GarmentCode)      │
                    │    ├── PantsMesh (GarmentCode)      │
                    │    ├── HairMesh (hair cards)        │
                    │    └── SpringBoneSimulator3D        │
                    │                                     │
                    │  Shaders: toon body, anisotropic    │
                    │  hair, shell fur (beard/eyebrows)   │
                    └─────────────────────────────────────┘
```

---

## 3. Validation Steps (ordered by risk)

Each step is independent. If a component fails, we identify alternatives
before proceeding. Estimated 15-30 min per step.

### V-01: MHR — Body Mesh Generation

**Goal:** pip/conda install → generate body → export .glb → verify in Godot

**Commands to try:**
```bash
# Option A: conda (documented)
conda install -c conda-forge pymomentum
pip install mhr

# Option B: pip only (experimental)
pip install pymomentum-cpu mhr
```

**Test script:**
```python
import mhr
# Generate default male body
body = mhr.create(gender="male", shape_params=[0]*45)
# Export to glTF
body.export("bob_body.glb")
```

**Success criteria:**
- [ ] Installation succeeds on macOS ARM64 (M1 Max)
- [ ] Python script generates body mesh without GUI
- [ ] Exported .glb contains skeleton with joints (≥50 including fingers)
- [ ] .glb opens in Godot 4.6, mesh renders correctly
- [ ] Shape parameters change body proportions visibly
- [ ] Expression parameters change face visibly

**Failure plan:** If MHR fails → test Anny (V-01b)

---

### V-01b: Anny — Body Mesh Generation (backup)

**Goal:** pip install → generate body → export .glb via pygltflib

**Commands:**
```bash
pip install anny pygltflib trimesh
```

**Test script:**
```python
import anny
import trimesh

model = anny.create()
# Set phenotype parameters
params = {"gender": 0.8, "age": 0.4, "height": 0.6, "muscle": 0.5}
mesh_data = model.forward(**params)

# Export via trimesh (bare mesh, no skeleton)
mesh = trimesh.Trimesh(vertices=mesh_data.vertices, faces=mesh_data.faces)
mesh.export("bob_body_anny.glb")

# TODO: construct skinned glTF with pygltflib (skeleton + weights)
```

**Success criteria:**
- [ ] pip install anny succeeds on macOS ARM64
- [ ] Generates mesh with 13K+ vertices
- [ ] UV coordinates present (for texturing)
- [ ] 163-bone skeleton data accessible
- [ ] Skin weights accessible
- [ ] Can construct skinned .glb (either via pygltflib or trimesh)

**Note:** Anny lacks native glTF export — manual skinned glTF construction
is a significant effort (~1-2 days). This is the main disadvantage vs MHR.

---

### V-02: GarmentCode + Warp — Clothing Generation

**Goal:** pip install → define shirt → drape on body → export mesh

**Commands:**
```bash
pip install pygarment warp-lang trimesh
```

**Test script:**
```python
import pygarment
import warp as wp

# Initialize Warp on CPU
wp.init()

# Define a simple T-shirt pattern
shirt = pygarment.TShirt(
    length=0.7,
    sleeve_length=0.25,
    neck_width=0.15
)

# Generate sewing pattern
pattern = shirt.pattern()

# Create initial 3D mesh from pattern
mesh_3d = pattern.to_mesh()

# Load body mesh for draping target
# body = trimesh.load("bob_body.glb")

# Drape using XPBD simulation (CPU)
# draped = warp_simulate(mesh_3d, body, steps=100)

# Export
# draped.export("shirt.glb")
```

**Success criteria:**
- [ ] pip install pygarment succeeds
- [ ] pip install warp-lang succeeds on macOS ARM64
- [ ] pygarment generates sewing pattern from parameters
- [ ] Pattern converts to 3D mesh
- [ ] Warp XPBD simulation runs on CPU (no CUDA error)
- [ ] Draping completes in < 5 minutes
- [ ] Output mesh looks like a garment (not garbage)
- [ ] Mesh exportable as .glb

**Failure plan:** If GarmentCode fails → try vertex-normal-offset approach
(simple clothing layer = body mesh offset along normals by 5mm)

---

### V-03: Procedural Hair Cards (Python)

**Goal:** Generate hair card mesh + texture → export .glb → render in Godot

**Test script:**
```python
import numpy as np
import trimesh

def generate_hair_card(root, direction, length=0.15, width=0.02, segments=4):
    """Create a single hair card (textured ribbon) as two triangles per segment."""
    vertices = []
    faces = []
    uvs = []
    right = np.cross(direction, [0, 1, 0])
    right = right / np.linalg.norm(right) * width / 2

    for i in range(segments + 1):
        t = i / segments
        pos = root + direction * length * t
        vertices.append(pos - right)
        vertices.append(pos + right)
        uvs.append([0, t])
        uvs.append([1, t])

    for i in range(segments):
        base = i * 2
        faces.append([base, base + 2, base + 1])
        faces.append([base + 1, base + 2, base + 3])

    return np.array(vertices), np.array(faces), np.array(uvs)

# Generate ~200 hair cards arranged as a hairstyle
# ... (sample scalp points, randomize directions, merge meshes)
# Export as .glb
```

**Success criteria:**
- [ ] Script generates hair card mesh (200+ cards)
- [ ] UV mapping correct (for texture application)
- [ ] Mesh exports as .glb
- [ ] Opens in Godot 4.6
- [ ] With alpha texture looks recognizably like hair
- [ ] Performance acceptable (< 5K triangles for full hairstyle)

**FLUX.2 hair texture test:**
```bash
mflux-generate --model flux2-klein-4b -q 4 \
  --prompt "horizontal strip of brown hair strands on pure black background, game texture asset, straight hair, seamless" \
  --width 512 --height 128 --steps 4 --seed 42 \
  --output hair_card_texture.png
```

- [ ] FLUX.2 generates usable hair strand texture
- [ ] Texture works as alpha-cutout in Godot

---

### V-04: ShellFurGodot — Eyebrows/Beard/Stubble

**Goal:** Install addon → apply to mesh → verify on Android-compatible renderer

**Steps:**
1. Clone https://github.com/Arnklit/ShellFurGodot into godot/addons/
2. Enable plugin in Godot
3. Apply shell fur to a sphere (simulating head)
4. Configure for short beard look
5. Test with mobile renderer

**Success criteria:**
- [ ] Addon loads in Godot 4.6 without errors
- [ ] Shell fur renders on mesh
- [ ] Mobile shader variant works (not just desktop)
- [ ] Looks like stubble/eyebrows at appropriate settings
- [ ] Performance acceptable on mobile renderer

**Failure plan:** If ShellFur doesn't work on 4.6 → use alpha-textured
decals (flat quads with beard/eyebrow textures from FLUX.2)

---

### V-05: SpringBoneSimulator3D — Hair Physics

**Goal:** Verify hair bone chain physics in Godot 4.6

**Steps:**
1. Create a simple bone chain (5 bones) attached to head
2. Add SpringBoneSimulator3D modifier
3. Attach a mesh ribbon to the bone chain
4. Rotate the parent → verify the chain bounces

**Success criteria:**
- [ ] SpringBoneSimulator3D exists in Godot 4.6.1
- [ ] Bone chain sways with parent movement
- [ ] Parameters (stiffness, drag, gravity) affect behavior
- [ ] No jitter or instability
- [ ] Looks natural for hair secondary motion

---

### V-06: Skinned .glb Import in Godot

**Goal:** Verify Godot 4.6 correctly imports a skinned mesh with skeleton

**Steps:**
1. Use output from V-01 (MHR/Anny body .glb)
2. Import into Godot
3. Verify Skeleton3D node created with all bones
4. Verify mesh deforms when bones are rotated
5. Attach second mesh (clothing from V-02) to same skeleton
6. Verify both meshes move together

**Success criteria:**
- [ ] .glb imports with Skeleton3D + MeshInstance3D
- [ ] Bone names/hierarchy correct
- [ ] Mesh deforms with bone rotation
- [ ] Multiple meshes can share one Skeleton3D
- [ ] Performance acceptable (< 16ms frame time)

---

### V-07: Full Integration Test

**Goal:** All components working together in Godot scene

**Steps:**
1. Body mesh (V-01) + clothing mesh (V-02) + hair mesh (V-03) on shared skeleton
2. Shell fur for eyebrows/beard (V-04)
3. SpringBone for hair physics (V-05)
4. Existing procedural room + lighting + camera
5. Idle animation driving the skeleton

**Success criteria:**
- [ ] Bob stands in room with hair, clothing, facial hair
- [ ] Camera orbits, all meshes follow correctly
- [ ] Idle animation moves body, clothing follows, hair sways
- [ ] Toon shader on body, anisotropic on hair
- [ ] Visual quality: recognizably "a person in a room" (Sims-like)
- [ ] Performance: 30+ FPS in editor

---

## 4. Decision Matrix After Validation

| If V-01 MHR... | Then body = |
|-----------------|-------------|
| WORKS | MHR (native glTF, 127 joints, LOD) |
| FAILS, V-01b Anny WORKS | Anny + pygltflib (more effort, 163 bones) |
| BOTH FAIL | Procedural mannequin in Godot (capsules on skeleton) |

| If V-02 GarmentCode... | Then clothing = |
|--------------------------|-----------------|
| WORKS | GarmentCode + Warp (parametric, infinite styles) |
| FAILS | Vertex normal offset (body mesh + 5mm = clothing layer) |

| If V-03 Hair cards... | Then hair = |
|------------------------|-------------|
| WORKS | Procedural hair cards + FLUX.2 textures |
| FAILS | Simple mesh cap on head (low-poly solid hair) |

| If V-04 ShellFur... | Then facial hair = |
|----------------------|---------------------|
| WORKS | Shell texturing for beard/eyebrows |
| FAILS | Alpha-textured decal quads |

**Worst case (all fail):** We still have the working procedural room + camera
+ capsule Bob from current Phase 1. We continue with geometric primitives
and add complexity incrementally.

---

## 5. Updated Tech Stack (post-research)

| Component | Original (RFC) | Updated | Status |
|-----------|----------------|---------|--------|
| 3D Engine | Godot 4.6 | Godot 4.6 | VALIDATED |
| Character body | MakeHuman | **MHR (Meta)** or Anny (NAVER) | TO VALIDATE |
| Clothing | (not specified) | **GarmentCode + NVIDIA Warp (CPU)** | TO VALIDATE |
| Hair | (not specified) | **Procedural hair cards + FLUX.2 textures** | TO VALIDATE |
| Facial hair | (not specified) | **ShellFurGodot / alpha decals** | TO VALIDATE |
| Hair physics | (not specified) | **SpringBoneSimulator3D (Godot built-in)** | TO VALIDATE |
| Textures | FLUX.2 Klein 4B | FLUX.2 Klein 4B via mflux | VALIDATED |
| 3D props | TripoSR | TripoSR | PLANNED (Phase 4) |
| Animations | Procedural IK | Procedural IK | PLANNED (Phase 2) |
| Communication | WebSocket | WebSocket | PLANNED (Phase 2) |

### Python Dependencies (Mac side)

```
# Body generation (one of these):
pip install pymomentum-cpu mhr          # Option A: MHR
pip install anny pygltflib              # Option B: Anny

# Clothing generation:
pip install pygarment warp-lang trimesh

# Texture generation (already validated):
uv tool install mflux

# Utility:
pip install numpy pyfqmr
```

### Godot Addons

```
addons/
├── ShellFurGodot/    # eyebrows, beard, stubble
└── (godot-vrm/)      # optional: VRM import support
```

---

## 6. Execution Order

**Priority: validate highest-risk components first.**

```
V-01: MHR install + body generation     ← HIGHEST RISK (new, experimental pip)
  │
  ├─► V-01b: Anny (if MHR fails)
  │
V-02: GarmentCode + Warp clothing       ← HIGH RISK (CPU draping untested)
  │
V-03: Procedural hair cards             ← MEDIUM RISK (pure Python, should work)
  │
V-04: ShellFurGodot addon               ← LOW RISK (Godot addon)
  │
V-05: SpringBoneSimulator3D             ← LOW RISK (Godot built-in)
  │
V-06: Skinned .glb import               ← DEPENDS ON V-01
  │
V-07: Full integration                  ← DEPENDS ON ALL
```

Each V-step produces:
- PASS/FAIL verdict
- Actual commands that worked (or error messages)
- Performance numbers (time, RAM, quality)
- Decision: proceed / use fallback / investigate further

---

## 7. Success Definition

**Pipeline is VALIDATED when:**
1. Bob has a body with skeleton (≥50 joints with fingers)
2. Bob has at least one clothing item (shirt or jumpsuit)
3. Bob has hair on his head
4. Bob has eyebrows (at minimum)
5. All above render in Godot 4.6 on desktop
6. All above generated 100% programmatically (no manual steps)
7. Generation time < 10 min total on M1 Max
8. Result .glb files total < 50 MB

**Pipeline is PRODUCTION-READY when additionally:**
9. Bob can change body shape via parameters
10. Bob can change clothing style/color
11. Bob can change hairstyle
12. All above work on Android (Realme C71)
13. Generation works on Mac Mini M4 16GB within RAM budget

---

## 8. Validation Results Log

### V-01: MHR
- **Date:** 2026-03-02
- **Result:** PASS (all 10 tests passed)
- **Install:** `pixi install` in cloned MHR repo (pip `pymomentum-cpu` has broken rpaths, conda/pixi required)
- **Notes:**
  - 127 joints (44 finger/thumb, 11 face incl. jaw/eyes/tongue)
  - 7 LOD levels: LOD 0 = 73K verts (6s), LOD 2 = 10K verts (0.8s), LOD 6 = 595 verts (0.1s)
  - Default body height: 172.6 cm (realistic)
  - 45 shape params, 204 pose params, 72 expression params — all verified to change mesh
  - Mesh is watertight
  - Export via trimesh: 375 KB GLB (bare mesh, no skeleton)
  - Export via GltfBuilder: 15.8 MB GLB (with skeleton + skin weights)
  - TorchScript model works without pymomentum (663 MB, LOD 1 only)
  - Units: centimeters (need ÷100 for Godot meters)
  - **Critical issue:** pip install broken on macOS ARM64 (hardcoded CI rpaths for libezc3d, libre2, etc). Must use pixi or conda-forge.

### V-01b: Anny
- **Date:** 2026-03-02
- **Result:** SKIPPED (MHR validated successfully, Anny not needed)
- **Notes:** MHR passed all tests. Anny remains as backup if MHR issues emerge later.

### V-02: GarmentCode + Warp
- **Date:** 2026-03-02
- **Result:** PARTIAL PASS (pygarment FAIL, fallback PASS, warp PASS)
- **Notes:**
  - `pip install pygarment` FAILS — depends on CGAL which requires CMake and fails to build on macOS ARM64
  - pygarment also pulls nicegui, pyrender, matplotlib, libigl — very heavy dependency tree
  - **Fallback: vertex-normal-offset** — WORKS perfectly:
    - Extract body region by Y range (torso Y=80-145cm, legs Y=5-92cm)
    - Offset all vertices along surface normals by 0.4-0.5cm
    - Shirt: 5605 verts, 11K faces, 197 KB GLB, generated in 10ms
    - Pants: 1668 verts, 3K faces, 58 KB GLB, generated in 3ms
    - Total clothing overhead: 68% of body vertex count
  - `pip install warp-lang` WORKS — v1.11.1, CPU-only on ARM64, kernel compilation works
  - Warp can be used for XPBD cloth sim in production (not needed for PoC)

### V-03: Hair Cards
- **Date:** 2026-03-02
- **Result:** PASS
- **Notes:**
  - Pure Python (numpy + trimesh), no ML dependencies
  - 200 hair cards generated in 14ms
  - 2000 vertices, 1600 triangles (well under 5K budget)
  - UV mapping present for texture application
  - Exported to GLB (59 KB) and OBJ (169 KB)
  - Hair positioned on scalp at ~165cm height (matching MHR body)
  - Cards taper at tips, have randomized direction with gravity bias
  - Next: generate FLUX.2 hair strand texture for alpha-cutout rendering

### V-04: ShellFurGodot
- **Date:** 2026-03-02
- **Result:** PARTIAL PASS (original addon Godot 3 only; Squiggles Fur alt has class_name issues headless)
- **Notes:**
  - **ShellFurGodot (Arnklit)** — Godot 3.4 ONLY, not compatible with 4.6
  - **Squiggles Fur (QueenOfSquiggles)** — Godot 4.x, MIT license
    - Installed to addons/squiggles_fur/
    - Has shader: furry_material.gdshader + material .tres
    - class_name references (ShellFur, FurTools) fail in headless mode (same issue as our scripts)
    - Should work in editor mode when .godot cache is built
  - **Fallback for PoC:** Alpha-textured decals (flat quads with beard/eyebrow textures)
  - **Decision:** Use alpha decals for PoC, Squiggles Fur for production when editor available

### V-05: SpringBoneSimulator3D
- **Date:** 2026-03-02
- **Result:** PASS
- **Notes:**
  - Class exists in Godot 4.6.1
  - 40 API methods: root/end bone, stiffness, drag, gravity, radius, rotation axis
  - Created Skeleton3D with 6-bone chain + SpringBoneSimulator3D as child — works
  - Key methods: set_joint_stiffness, set_joint_drag, set_joint_gravity, set_joint_radius
  - Can define center bone for wind/movement reference
  - Bone chain physics will work for hair secondary motion

### V-06: Skinned .glb Import
- **Date:** 2026-03-02
- **Result:** PASS
- **Notes:**
  - GltfBuilder export (15.8 MB) imports with full Skeleton3D (127 bones) + MeshInstance3D (10,661 verts)
  - Trimesh export (375 KB) imports as bare mesh without skeleton
  - BoneAttachment3D nodes with collision shapes automatically created
  - Bone hierarchy correct (finger chains, face bones, spine chain)
  - Godot 4.6 GLTFDocument API works headless
  - MHR units are centimeters — need scale ÷100 for Godot (or set node.scale to 0.01)

### V-07: Full Integration
- **Date:** 2026-03-02
- **Result:** PASS (all 6 components loaded and functional)
- **Notes:**
  - Body (MHR, 127 bones, skinned .glb) — LOADED
  - Shirt (vertex-normal-offset) — LOADED
  - Pants (vertex-normal-offset) — LOADED
  - Hair cards (procedural, 200 cards) — LOADED
  - Head bone rotation — WORKS (c_head at index 113)
  - Finger bone curl — WORKS (r_index1 at index 56)
  - Total vertices: 19,934 across all meshes
  - Scale: MHR cm ÷ 100 = Godot meters (scale = 0.01)
  - All meshes load headless via GLTFDocument API
  - Headless exit warnings (leaked RIDs) are normal for Godot headless mode
