# Exhaustive Research: Hair & Clothing Generation for 3D Humanoid Characters

> **Date:** 2026-03-02
> **Constraints:** macOS Apple Silicon (M1 Max / M4) | No NVIDIA GPU | No cloud APIs | pip-installable or buildable from source
> **Target:** MHR (Meta Momentum Human Rig) body mesh -> Godot 4.6 on Android | Sims-like stylized look

---

## Table of Contents

1. [HAIR: Strand-Based ML Generation](#1-hair-strand-based-ml-generation)
2. [HAIR: Mesh-Based Hair](#2-hair-mesh-based-hair)
3. [HAIR: Hair Cards (Game Industry Standard)](#3-hair-hair-cards)
4. [HAIR: Godot-Native Solutions](#4-hair-godot-native-solutions)
5. [HAIR: Procedural/Algorithmic Hair](#5-hair-proceduralalgorithmic-hair)
6. [HAIR: Facial Hair (Beard, Mustache, Eyebrows)](#6-hair-facial-hair)
7. [CLOTHING: ML-Based Generation (CPU/MPS)](#7-clothing-ml-based-generation)
8. [CLOTHING: Sewing Pattern to 3D Mesh](#8-clothing-sewing-pattern-to-3d-mesh)
9. [CLOTHING: Procedural in Godot](#9-clothing-procedural-in-godot)
10. [CLOTHING: Texture-Based (Paint on UV)](#10-clothing-texture-based)
11. [CLOTHING: Template/Layered Mesh Approach](#11-clothing-templatelayered-mesh)
12. [CLOTHING: Physics Simulation](#12-clothing-physics-simulation)
13. [COMBINED: Full Avatar Generation Pipelines](#13-combined-full-avatar-pipelines)
14. [COMBINED: Image-to-3D Pipelines](#14-combined-image-to-3d-pipelines)
15. [COMBINED: Text-to-3D Pipelines](#15-combined-text-to-3d-pipelines)
16. [PRACTICAL: Unconventional Approaches](#16-practical-unconventional-approaches)
17. [TOOLING: Key Python Libraries](#17-tooling-key-python-libraries)
18. [MHR SPECIFICS: Integration Notes](#18-mhr-specifics)
19. [FEASIBILITY MATRIX](#19-feasibility-matrix)
20. [RECOMMENDED APPROACH](#20-recommended-approach)

---

## 1. HAIR: Strand-Based ML Generation

### 1.1 DiffLocks (Meshcapade, CVPR 2025)

- **What:** Generates strand-based 3D hair from a single image using diffusion models
- **GitHub:** https://github.com/Meshcapade/difflocks
- **CUDA Required:** YES -- custom CUDA kernels needed (NATTEN sparse attention, FlashAttention-2)
- **MPS/CPU:** NOT SUPPORTED
- **Apple Silicon Feasibility:** BLOCKED -- hard CUDA dependency in attention kernels
- **Quality:** Photorealistic strand-level, 40K synthetic hair dataset

### 1.2 CT2Hair (Meta/Facebook Research, SIGGRAPH 2023)

- **What:** High-fidelity 3D hair from computed tomography scans
- **GitHub:** https://github.com/facebookresearch/CT2Hair
- **Requirements:** NVIDIA GPU with 24GB+ VRAM, CUDA 11.5+, 64GB RAM
- **MPS/CPU:** NOT SUPPORTED
- **Apple Silicon Feasibility:** BLOCKED -- requires CT scanner data + NVIDIA GPU
- **Verdict:** Completely impractical for our use case

### 1.3 Perm (ICLR 2025)

- **What:** Parametric representation for multi-style 3D hair modeling using PCA in frequency domain
- **GitHub:** https://github.com/c-he/perm
- **Requirements:** CUDA Toolkit 11.3+, 64GB RAM for PCA fitting
- **MPS/CPU:** NOT SUPPORTED (CUDA kernels)
- **Apple Silicon Feasibility:** BLOCKED
- **Note:** Interesting concept of disentangling global shape vs local strand detail

### 1.4 NeuralHaircut (ICCV 2023)

- **What:** Prior-guided strand-based hair reconstruction from monocular video
- **Requirements:** NVIDIA GPU, CUDA 11.1, PyTorch 1.8.1
- **MPS/CPU:** NOT SUPPORTED
- **Apple Silicon Feasibility:** BLOCKED

### 1.5 HairFastGAN (NeurIPS 2024)

- **What:** Virtual hairstyle fitting framework
- **GitHub:** https://github.com/AIRI-Institute/HairFastGAN
- **MPS/CPU:** Potentially partial MPS support (standard PyTorch GAN, no custom CUDA)
- **Apple Silicon Feasibility:** POSSIBLE WITH WORK -- standard PyTorch, may need MPS fallback for some ops
- **Quality:** 2D hairstyle transfer, would need adaptation for 3D

### 1.6 GaussianHaircut (ECCV 2024)

- **What:** Human hair reconstruction with strand-aligned 3D Gaussians
- **GitHub:** https://github.com/eth-ait/GaussianHaircut
- **Requirements:** CUDA (3D Gaussian Splatting)
- **MPS/CPU:** NOT SUPPORTED
- **Apple Silicon Feasibility:** BLOCKED

### VERDICT ON STRAND-BASED ML HAIR

**All major strand-based hair generation models require NVIDIA CUDA.** None have MPS support. This entire category is effectively BLOCKED for our constraints. The only partial exception is HairFastGAN which uses standard PyTorch ops but produces 2D results, not 3D strands.

---

## 2. HAIR: Mesh-Based Hair

### 2.1 Blender Headless with bpy Module

- **What:** Use Blender's Python module (`bpy`) headlessly to generate hair meshes
- **Install:** `pip install bpy` (official builds for macOS ARM64 available)
- **Blender builds page:** https://builder.blender.org/download/bpy/
- **Apple Silicon:** SUPPORTED (native ARM64 builds)
- **Approach:**
  1. Use Blender's Geometry Nodes to define parametric hair
  2. Convert curves to mesh
  3. Export as GLB
  4. Command line: `blender -b -P script.py`
- **Feasibility:** HIGH -- Blender is the most mature tool for mesh hair generation
- **Concerns:** bpy module compatibility with specific Python versions (3.11 recommended)

### 2.2 CharMorph (Blender Addon, GPLv3)

- **What:** Open-source 3D character generator with hair and clothing, spiritual successor to MB-Lab
- **GitHub:** https://github.com/Upliner/CharMorph
- **Version:** 0.4.0 (March 2025)
- **License:** GPLv3 (source), CC0/CC-BY (character models)
- **Features:**
  - Dynamic hairstyles with morphing
  - Clothing with real-time fitting
  - Support for Rigify
  - Compatible with Blender 4.4
- **Apple Silicon:** SUPPORTED (runs via Blender)
- **Headless:** Possible via bpy but not officially documented
- **Feasibility:** HIGH for asset pre-generation pipeline
- **Best for:** Pre-generating a library of hair/clothing assets in batch

### 2.3 MakeHuman + MPFB 2

- **What:** Open-source parametric character generator (Python)
- **GitHub:** https://github.com/makehumancommunity/makehuman
- **License:** AGPL (source), CC0 (exported models)
- **Features:**
  - Parametric hair, eyebrows, eyelashes
  - Clothing library
  - Export to FBX, OBJ, Collada (GLB via Blender bridge)
- **Headless:** Partial -- scripting plugin supports batch generation; community fork at https://github.com/severin-lemaignan/makehuman-commandline
- **Apple Silicon:** SUPPORTED (Python + Qt)
- **Feasibility:** MEDIUM-HIGH -- mature but aging codebase, headless mode is hacky

### 2.4 Low-Poly Hair Mesh Generation (Pure Python)

- **What:** Generate simple hair meshes programmatically using trimesh/numpy
- **Approach:**
  1. Define hair volume as a set of Bezier curves growing from scalp
  2. Extrude curves into tube meshes or ribbon meshes
  3. Merge into single mesh, simplify with pyfqmr
- **Libraries:** trimesh, numpy, pyfqmr, pyvista
- **Apple Silicon:** FULLY SUPPORTED (pure Python + numpy)
- **Feasibility:** HIGH but requires significant custom development
- **Quality:** Low-poly stylized (Sims-like, which is our target)

---

## 3. HAIR: Hair Cards

### 3.1 What Are Hair Cards?

Hair cards are textured polygon planes arranged to simulate hair volume. This is **THE standard game industry approach** for real-time hair in games from indie to AAA. A complete hairstyle typically uses:
- A few hundred to a few thousand polygons
- 1-2 texture sheets (2K for head hair, 1K for beard)
- Alpha-tested or alpha-blended rendering
- Textures include: Albedo+Alpha, Normal, AO, Flow, Depth, Root gradient

### 3.2 Generating Hair Card Textures with FLUX.2

- **Tool:** mflux (MLX-native FLUX on Apple Silicon)
- **Install:** `uv tool install mflux`
- **GitHub:** https://github.com/filipstrand/mflux
- **Apple Silicon:** NATIVE MLX (optimal performance)
- **Approach:**
  1. Generate hair strand texture strips with FLUX.2: "a strip of brown hair strands on black background, game asset, alpha channel, straight hair texture card"
  2. Use ControlNet depth/normal conditioning for consistency
  3. Post-process to extract alpha channel
  4. Arrange on UV atlas
- **LoRAs available:**
  - Flux-Seamless-Texture-LoRA: https://huggingface.co/gokaygokay/Flux-Seamless-Texture-LoRA (trigger: "smlstxtr")
  - Flux Hand-Painted Textures: generates stylized game textures with normal/height maps
- **Feasibility:** HIGH -- FLUX.2 runs natively on Apple Silicon via mflux
- **Quality:** Good for stylized/toon look; may need iteration for consistency

### 3.3 FiberShop

- **What:** Standalone real-time hair-card texture generator
- **URL:** https://cgpal.com/fibershop/
- **License:** COMMERCIAL (not open source)
- **Apple Silicon:** Unknown
- **Verdict:** Not pip-installable, not open source -- SKIP

### 3.4 Blender Hair Tool (Geometry Nodes)

- **What:** Blender addon for generating hair cards from curve guides
- **Approach:** Define hair curves -> convert to cards -> bake textures -> export
- **Documentation:** https://joseconseco.github.io/HairTool_3_Documentation/
- **Apple Silicon:** SUPPORTED (via Blender)
- **Feasibility:** HIGH for batch pre-generation

### 3.5 Pre-arrangement Strategy for Hair Cards

For a Sims-like game, the recommended approach:
1. **Pre-generate 20-50 base hairstyle meshes** (hair card arrangements in Blender)
2. **Generate texture variations** with FLUX.2 (different colors, styles)
3. **Export as GLB** with alpha textures embedded
4. **Load in Godot** with appropriate hair shader (anisotropic highlights)

---

## 4. HAIR: Godot-Native Solutions

### 4.1 Shell Fur Shaders

Three main addons:

**ShellFurGodot by Arnklit**
- GitHub: https://github.com/Arnklit/ShellFurGodot
- Mobile shader option optimized for Android
- Configurable shell layers
- **Best for:** Short hair, buzz cuts, stubble, eyebrows

**SO FLUFFY by maxmuermann**
- GitHub: https://github.com/maxvolumedev/sofluffy
- Material-based shell generation
- Dynamic LODs based on camera distance
- Bouncy physics

**Squiggles Fur**
- GitHub: https://github.com/QueenOfSquiggles/squiggles-fur
- No-code approach
- Configurable metalness/roughness

**Feasibility:** HIGH for short hair/stubble/eyebrows; NOT suitable for long flowing hair

### 4.2 SpringBoneSimulator3D (Godot 4.4+)

- **What:** Built-in SkeletonModifier3D for wiggling hair, cloth, tails
- **Docs:** https://docs.godotengine.org/en/stable/classes/class_springbonesimulator3d.html
- **Features:**
  - Bone chain physics (stiffness, drag, gravity per joint)
  - Self-standing collision shapes (SpringBoneCollision3D)
  - Returns to rest pose after perturbation
- **Best for:** Long hair physics on pre-modeled hair meshes
- **Android:** SUPPORTED (runs on CPU, no GPU compute needed)

### 4.3 Hair Shaders in Godot

**Kajiya-Kay Anisotropic Hair Shader:**
- Available as community implementation
- Achieves proper hair specular highlights
- Works with hair card meshes

**SimpleToonHair:**
- https://godotshaders.com/shader/simpletoonhair/
- Stylized toon hair shader
- Perfect for Sims-like aesthetic

**Marschner Hair Shader:**
- More physically accurate than Kajiya-Kay
- Community implementation available

### 4.4 GPUParticles3D for Hair

- Can render hundreds of thousands of particles
- Trail support with RibbonTrailMesh and TubeTrailMesh
- Custom particle shaders supported
- **Feasibility:** LOW for actual hair -- particles lack proper hair card structure
- **Better for:** Magical effects, not realistic hair rendering

### 4.5 Godot VRM Addon

- **GitHub:** https://github.com/V-Sekai/godot-vrm
- Imports VRM format with hair, clothing, and MToon shader
- VRM includes spring bone physics data for hair
- **Feasibility:** HIGH if we generate VRM-format characters

### 4.6 Godot Character Creation Suite (Pelatho)

- **URL:** https://thowsenmedia.itch.io/godot-character-creation-suite
- Pure GDScript addon for Godot 4
- Features:
  - Modular clothing/equipment system with slot-based management
  - PhysicalHairEquipment resource for physics-driven hair
  - Blend shapes for body/face customization
  - Equipment style variants (e.g., shirt tucked/untucked)
- **License:** Asset store (paid)
- **Feasibility:** MEDIUM -- good reference architecture but requires license

---

## 5. HAIR: Procedural/Algorithmic Hair

### 5.1 Bezier Curve Extrusion (Pure Python)

```python
# Conceptual approach
import numpy as np
import trimesh

def generate_hair_strand(root_pos, direction, length, segments=8):
    """Generate a single hair strand as a tube mesh."""
    points = []
    for i in range(segments):
        t = i / (segments - 1)
        # Add noise/curl
        offset = direction * length * t
        offset += np.random.normal(0, 0.002, 3) * t  # increasing randomness
        points.append(root_pos + offset)
    # Extrude to tube mesh with decreasing radius
    # ... use trimesh.creation.sweep_polygon or similar
```

- **Libraries:** trimesh, numpy, scipy (for B-spline interpolation)
- **Apple Silicon:** FULLY SUPPORTED
- **Quality:** Depends on effort; can achieve decent stylized results
- **Performance:** Fast generation, output is standard mesh

### 5.2 Scalp-Based Hair Volume Generation

1. Sample points on scalp region of MHR mesh
2. Compute outward normals at sample points
3. Generate curve guides following normals with perturbation
4. Group curves into "clumps" (5-20 strands per clump)
5. Create ribbon mesh (2 triangles per segment) along each clump
6. Merge all ribbons into single mesh
7. Generate UV coordinates for hair texture mapping

### 5.3 SDF-Based Hair Volume

- **Library:** https://github.com/fogleman/sdf (Simple SDF mesh generation in Python)
- **Install:** `pip install sdf` (or clone from GitHub)
- **Approach:** Define hair volume as SDF, use marching cubes to extract mesh
- **Quality:** Very low-poly, blob-like -- suitable only for very stylized (Lego-like) hair
- **Apple Silicon:** FULLY SUPPORTED (pure Python + numpy)

---

## 6. HAIR: Facial Hair (Beard, Mustache, Eyebrows)

### 6.1 Game Industry Approaches

**Eyebrows:**
- Typically texture-only on face UV map (alpha-blended decal)
- Or 1-2 hair card strips placed above eyes
- Shell texturing works well for thick eyebrows

**Mustache/Beard:**
- Hair cards: 50-200 polygons arranged on lower face
- Alpha-blended textures on face-conforming mesh strips
- Shell texturing for stubble/short beard

**Texture Maps:**
- Albedo+Alpha (hair color + transparency)
- Normal map (strand direction)
- AO map (depth/shadow at roots)
- Flow map (for anisotropic shader)
- Root gradient (darker at roots, lighter at tips)

### 6.2 Recommended Approach for Facial Hair

For a Sims-like game:
1. **Eyebrows:** Alpha texture decals on face mesh (simplest, most performant)
2. **Stubble/Short beard:** Shell texturing (ShellFurGodot with mobile shader)
3. **Full beard/mustache:** 2-5 hair card strips with alpha textures
4. **Texture generation:** FLUX.2 via mflux for generating hair card textures

### 6.3 Face Region Detection on MHR

MHR mesh has 18,439 vertices with defined topology. To place facial hair:
- Need vertex group definitions for chin, upper lip, cheeks, brow ridge
- Can be defined once per LOD level and stored as vertex index arrays
- Facial hair meshes snap to these vertex positions

---

## 7. CLOTHING: ML-Based Generation (CPU/MPS)

### 7.1 TailorNet (CVPR 2020)

- **What:** Predicts clothing mesh as vertex displacements on SMPL body
- **GitHub:** https://github.com/chaitanya100100/TailorNet
- **Requirements:** PyTorch >= 1.0, psbody.mesh, chumpy, scipy
- **MPS/CPU:** POSSIBLE -- standard PyTorch ops, no custom CUDA
- **Apple Silicon Feasibility:** MEDIUM -- psbody.mesh may need compilation
- **Approach:** Outputs per-vertex displacements added to body mesh
- **Garment types:** T-shirt, shirt, short-pant, pant
- **Limitations:** Only works with SMPL body (needs adaptation for MHR)

### 7.2 DrapeNet (CVPR 2023)

- **What:** Garment generation and self-supervised draping
- **GitHub:** https://github.com/liren2515/DrapeNet
- **Requirements:** PyTorch with CUDA (documented)
- **MPS/CPU:** UNCLEAR -- may work with CPU fallback
- **Apple Silicon Feasibility:** MEDIUM -- worth testing with PYTORCH_ENABLE_MPS_FALLBACK=1
- **Output:** Separate garment mesh draped on body

### 7.3 CAPE (CVPR 2020)

- **What:** Learning to Dress 3D People in Generative Clothing
- **GitHub:** https://github.com/qianlim/CAPE
- **Approach:** Clothing as per-vertex displacements: Vd = Vclothed - Vminimal
- **MPS/CPU:** POSSIBLE -- standard PyTorch
- **Limitations:** SMPL-specific topology

### 7.4 ChatGarment (CVPR 2025)

- **What:** Garment estimation, generation and editing via LLMs
- **GitHub:** https://github.com/biansy000/ChatGarment
- **Approach:**
  1. Fine-tuned VLM outputs JSON garment description
  2. JSON -> GarmentCode sewing patterns
  3. Patterns -> 3D mesh via simulation
- **Apple Silicon Feasibility:** MEDIUM-HIGH
  - VLM inference: possible on MPS (standard transformer)
  - GarmentCode: pure Python (SUPPORTED)
  - Simulation: uses NVIDIA Warp (supports CPU on macOS)
- **Quality:** Production-quality sewing patterns
- **This is one of the most promising approaches**

### 7.5 DressCode (TOG 2024)

- **What:** Text-guided garment generation via autoregressive sewing patterns
- **GitHub:** https://github.com/IHe-KaiI/DressCode
- **Architecture:** SewingGPT (GPT-based) + Stable Diffusion for PBR textures
- **Requirements:** conda environment with CUDA (documented)
- **MPS/CPU:** UNCLEAR -- GPT component may work on MPS; SD component can use MPS
- **Apple Silicon Feasibility:** MEDIUM -- needs testing

### 7.6 GarmentDiffusion (IJCAI 2025)

- **What:** 3D garment sewing pattern generation with multimodal diffusion transformer
- **GitHub:** https://github.com/Shenfu-Research/GarmentDiffusion
- **Requirements:** Ubuntu 22.04, CUDA 11.8, PyTorch 2.6
- **Apple Silicon Feasibility:** LOW -- documented CUDA requirement
- **Note:** 10x more compact than DressCode's SewingGPT

### 7.7 GarmageNet (SIGGRAPH Asia 2025)

- **What:** Multimodal framework for sewing pattern design and garment modeling
- **GitHub:** https://github.com/Style3D/garmagenet-impl
- **Requirements:** Ubuntu 22.04, CUDA 11.8, PyTorch 2.6
- **Dataset:** GarmageSet (14,801 professionally designed garments) on HuggingFace
- **Apple Silicon Feasibility:** LOW -- CUDA documented

---

## 8. CLOTHING: Sewing Pattern to 3D Mesh

### 8.1 GarmentCode + pygarment (THE KEY TOOL)

- **What:** Modular programming framework for parametric sewing patterns
- **GitHub:** https://github.com/maria-korosteleva/GarmentCode
- **PyPI:** `pip install pygarment`
- **License:** Open source
- **Features:**
  - DSL for garment construction (Edge, Panel, Component, Interface)
  - Box mesh generation from sewing patterns
  - Integration with NVIDIA Warp for XPBD simulation
  - High-level scripts for batch dataset generation
- **Apple Silicon Feasibility:** HIGH
  - pygarment itself: pure Python, FULLY SUPPORTED
  - Box mesh generation: SUPPORTED
  - XPBD simulation via Warp: SUPPORTED on CPU (macOS ARM64 builds available)
- **Quality:** Professional-grade parametric garments
- **THIS IS THE MOST VIABLE CLOTHING GENERATION TOOL**

### 8.2 NVIDIA Warp (for Cloth Draping)

- **What:** Python framework for simulation, JIT-compiled kernels
- **GitHub:** https://github.com/NVIDIA/warp
- **PyPI:** `pip install warp-lang`
- **Apple Silicon:** SUPPORTED (CPU mode, macOS ARM64 builds)
- **Features:**
  - XPBD cloth simulation
  - Runs on CPU (no CUDA required)
  - Example: `warp/examples/sim/example_cloth.py`
- **GarmentCode Fork:** https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode
  - Enhanced XPBD solver for garment draping
  - Collision resolution improvements
  - Drape correctness solutions
- **Performance on CPU:** Slower than GPU but functional
- **Feasibility:** HIGH

### 8.3 Garment-Pattern-Generator

- **What:** Generates datasets of 3D garments with sewing patterns
- **GitHub:** https://github.com/maria-korosteleva/Garment-Pattern-Generator
- **Features:** 19 garment types, 20,000+ samples
- **Depends on:** pygarment + simulation backend
- **Apple Silicon:** SUPPORTED

### 8.4 Combined Pipeline: Text -> Sewing Pattern -> 3D Mesh

```
Text prompt ("blue polo shirt")
    |
    v
LLM (Ollama local) -> JSON garment params
    |
    v
GarmentCode/pygarment -> 2D sewing pattern
    |
    v
NVIDIA Warp (CPU) -> drape on body mesh -> 3D garment mesh
    |
    v
FLUX.2 (mflux) -> generate UV texture
    |
    v
Export as GLB -> load in Godot
```

---

## 9. CLOTHING: Procedural in Godot

### 9.1 SurfaceTool

- **Docs:** https://docs.godotengine.org/en/stable/tutorials/3d/procedural_geometry/surfacetool.html
- **What:** OpenGL 1.x immediate-mode interface for mesh construction
- **Use case:** Generate simple garment shapes at runtime
- **Example:** Cylinder for sleeves, trapezoid for torso
- **Feasibility:** MEDIUM -- good for very simple geometric clothing

### 9.2 ArrayMesh

- **Docs:** https://docs.godotengine.org/en/stable/tutorials/3d/procedural_geometry/arraymesh.html
- **What:** Direct array-based mesh construction (faster than SurfaceTool)
- **Use case:** Offset body mesh vertices along normals to create clothing layer
- **Approach:**
  1. Take body mesh vertex positions
  2. For clothing region vertices, offset along normals
  3. Create new mesh from offset vertices
  4. Apply clothing material/texture

### 9.3 SoftBody3D for Cloth Simulation

- **Docs:** https://docs.godotengine.org/en/stable/classes/class_softbody3d.html
- **What:** Physics-based soft body deformation
- **Use case:** Cloaks, scarves, loose clothing parts
- **Limitations:**
  - Not specifically designed for cloth (generic soft body)
  - Performance concerns on mobile
  - Tricky integration with skinned meshes
- **Feasibility:** LOW for full clothing, MEDIUM for accessories

### 9.4 SpringBoneSimulator3D for Clothing Physics

- **Available in:** Godot 4.4+
- **Use case:** Skirts, coats, dangling parts
- **Approach:** Add bones to clothing mesh, simulate with spring physics
- **Performance:** Lightweight compared to SoftBody3D
- **Feasibility:** HIGH for secondary motion on pre-modeled clothing

### 9.5 CSG for Clothing

- **Verdict:** NOT SUITABLE -- CSG is designed for level prototyping, not character clothing
- Boolean operations are too heavy and imprecise for clothing

---

## 10. CLOTHING: Texture-Based (Paint on UV)

### 10.1 SMPLitex Approach

- **What:** Diffusion model that generates full-body UV texture maps
- **GitHub:** https://github.com/dancasas/SMPLitex
- **Paper:** BMVC 2023
- **Features:**
  - Text-prompted UV texture generation
  - Image-conditioned UV completion
  - Works in UV-space (not 3D)
- **Requirements:** Stable Diffusion U-Net, fine-tuned on UV textures
- **MPS/CPU:** POSSIBLE -- standard SD architecture
- **Limitations:** Only generates appearance, not geometry; clothing is "painted on"
- **Feasibility:** MEDIUM -- needs adaptation from SMPL UV layout to MHR UV layout

### 10.2 UVMap-ID (ACM MM 2024)

- **What:** Controllable, personalized UV map generation
- **GitHub:** https://github.com/twowwj/UVMap-ID
- **Features:**
  - ID-driven personalized generation
  - Text-prompted controllable UV maps
  - Fine-tuned diffusion model
  - Can apply directly to SMPL meshes
- **Requirements:** Text-to-image diffusion model
- **Apple Silicon Feasibility:** MEDIUM-HIGH (standard diffusion, can run on MPS)
- **Quality:** High-quality UV textures with clothing appearance

### 10.3 FLUX.2 for UV Texture Generation

- **Tool:** mflux (MLX-native)
- **Approach:**
  1. Render MHR body UV layout as conditioning image
  2. Use FLUX.2 with ControlNet (depth/normal conditioning)
  3. Generate clothing appearance as UV texture
  4. Apply to body mesh
- **Available LoRAs:**
  - Seamless Texture LoRA
  - Hand-Painted Textures LoRA
- **Feasibility:** HIGH -- FLUX.2 runs natively on Apple Silicon
- **Limitation:** No geometric detail (flat clothing look)
- **Best for:** T-shirts, form-fitting clothes, skin textures

### 10.4 TexGarment (CVPR 2025)

- **What:** Generates consistent garment UV textures in 4 seconds
- **Approach:** Diffusion transformer guided by 2D UV position map + 3D point cloud
- **Quality:** Fine details, organized UV layout
- **Code:** No public GitHub repository found at time of research
- **Apple Silicon Feasibility:** UNKNOWN

---

## 11. CLOTHING: Template/Layered Mesh Approach

### 11.1 Game Industry Standard: Shared Skeleton Method

This is how The Sims, most RPGs, and character-based games handle clothing:

1. **Base body mesh** is rigged to skeleton
2. **Clothing meshes** are separate meshes rigged to THE SAME skeleton
3. **Animation drives skeleton** -> all meshes follow
4. **Body parts hidden** under opaque clothing (performance optimization)
5. **Vertex groups** define how clothing deforms per bone

**Implementation in Godot 4.6:**
```gdscript
# All meshes reference same skeleton
var skeleton = $Skeleton3D
var body_mesh = $Skeleton3D/BodyMeshInstance
var shirt_mesh = $Skeleton3D/ShirtMeshInstance
var pants_mesh = $Skeleton3D/PantsMeshInstance

# Clothing meshes are skinned to same bones
# Animation plays on skeleton, everything follows
```

### 11.2 Approach for MHR + Godot

1. **Pre-generate clothing templates** in Blender (or via GarmentCode + Warp)
2. **Rig to MHR skeleton** (127 joints, can simplify for clothing)
3. **Export as separate GLB files** (one per garment)
4. **In Godot:** attach clothing mesh to same skeleton node
5. **Weight transfer:** use Blender's data transfer modifier to copy skin weights from body to clothing

### 11.3 Vertex Normal Offset Method (Simple Clothing)

For very tight-fitting clothes (undershirt, leggings):
```python
# Python (trimesh) - generate clothing from body mesh
import trimesh
import numpy as np

body = trimesh.load("body.glb")
# Select clothing region vertices (e.g., torso)
torso_indices = [...]  # vertex indices for torso
offset = 0.005  # 5mm offset

clothing_vertices = body.vertices.copy()
clothing_vertices[torso_indices] += body.vertex_normals[torso_indices] * offset
clothing_mesh = trimesh.Trimesh(vertices=clothing_vertices, faces=body.faces[torso_face_indices])
```

### 11.4 Pre-Generated Asset Library Strategy

For a Sims-like game with 20-50 clothing items:
- **T-shirts:** 5 styles (crew neck, v-neck, polo, tank, long sleeve)
- **Pants:** 5 styles (jeans, shorts, dress pants, joggers, skirt)
- **Outerwear:** 5 styles (jacket, hoodie, blazer, vest, coat)
- **Accessories:** 5 items (hat, glasses, scarf, watch, necklace)

Each pre-modeled, rigged, textured, and exported as GLB. Total ~20 base meshes with texture variations via FLUX.2.

---

## 12. CLOTHING: Physics Simulation

### 12.1 NVIDIA Warp on CPU (macOS)

- **Install:** `pip install warp-lang`
- **Cloth simulation example:** `warp/examples/sim/example_cloth.py`
- **XPBD integrator** for stable cloth draping
- **CPU mode:** Works on macOS ARM64
- **Use case:** Pre-compute garment draping offline, export static draped mesh
- **NOT suitable for:** Real-time cloth sim (too slow on CPU for game)

### 12.2 GarmentCode + Warp Pipeline

- **NvidiaWarp-GarmentCode fork:** https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode
- Enhanced collision resolution
- Drape correctness improvements
- **Pipeline:**
  1. Define garment in GarmentCode DSL
  2. Generate sewing pattern panels
  3. Create initial 3D mesh (box mesh)
  4. Simulate draping with XPBD on target body shape
  5. Export final draped mesh
- **Quality:** Publication-quality results (ECCV 2024)

### 12.3 Godot Runtime Physics Options

| Method | Use Case | Performance | Quality |
|--------|----------|-------------|---------|
| SpringBoneSimulator3D | Skirts, coats, hair | Good (CPU) | Good |
| SoftBody3D | Cloaks, scarves | Poor on mobile | Medium |
| Bone-driven blend shapes | Tight clothing wrinkles | Excellent | Medium |
| Vertex shader displacement | Breathing, muscle flex | Excellent | Low |

**Recommended for Android:** SpringBoneSimulator3D for secondary clothing motion

---

## 13. COMBINED: Full Avatar Generation Pipelines

### 13.1 CharMorph (BEST Open Source Option)

- **What:** Full character with body, hair, clothing in Blender
- **Hair:** Dynamic hairstyles, morphable
- **Clothing:** Real-time fitting, slot-based system
- **Characters:** CC0/CC-BY licensed base characters
- **Workflow:** CharMorph in Blender -> export GLB -> import to Godot
- **Batch generation:** Possible via bpy headless mode
- **Apple Silicon:** SUPPORTED
- **Feasibility:** HIGH

### 13.2 MakeHuman + MPFB 2

- **What:** Standalone character generator + Blender plugin
- **Hair:** Selection of default hairstyles
- **Clothing:** Community clothing library
- **Export:** CC0 licensed models
- **Headless:** Via scripting plugin or community command-line fork
- **Apple Silicon:** SUPPORTED
- **Feasibility:** MEDIUM-HIGH

### 13.3 VRoid Studio -> VRM -> Godot

- **What:** Anime-style character creator -> VRM export -> godot-vrm import
- **Hair:** Built-in hair editor (mesh-based)
- **Clothing:** Built-in clothing editor
- **Automation:** NO headless mode, NO Python API
- **Apple Silicon:** SUPPORTED (native app)
- **Feasibility:** LOW for automation (manual only)
- **Best for:** One-off character creation, not batch generation

### 13.4 Daz3D Studio

- **What:** Professional character generator
- **Scripting:** DAZ Script (not Python), supports headless mode (-headless flag)
- **Hair/Clothing:** Extensive asset library (mostly commercial)
- **Export:** FBX, OBJ, glTF
- **Apple Silicon:** SUPPORTED
- **Feasibility:** LOW -- not pip-installable, commercial ecosystem, DAZ Script not Python
- **Note:** Some hair plugins incompatible with headless mode

### 13.5 SimAvatar (NVIDIA, CVPR 2025)

- **What:** Simulation-ready avatars with layered hair and clothing from text
- **Features:** Separate garment mesh, body shape, and hair strands from text
- **Requirements:** NVIDIA GPU (Gaussian Splatting based)
- **Apple Silicon:** NOT SUPPORTED
- **Feasibility:** BLOCKED

---

## 14. COMBINED: Image-to-3D Pipelines

### 14.1 Hunyuan3D 2.1 (Tencent, BEST Image-to-3D Option)

- **What:** Image -> high-quality 3D mesh with PBR textures
- **GitHub:** https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- **Mac Fork:** https://github.com/Maxim-Lanskoy/Hunyuan3D-2-Mac (MPS backend)
- **License:** Open source
- **Apple Silicon:**
  - Shape generation: WORKS on MPS (good quality meshes)
  - Texture generation: SLOW/BROKEN (nvdiffrast needs CUDA)
  - Low-VRAM mode available for <64GB RAM
  - Generation time: 2-5 min per object on M1/M2/M3 Max
- **Output:** .obj / .glb
- **Quality:** Among best open-source image-to-3D
- **Feasibility:** MEDIUM -- shape works, texture is problematic

### 14.2 TripoSR (Stability AI + Tripo)

- **What:** Fast 3D reconstruction from single image (<0.5 sec on GPU)
- **GitHub:** https://github.com/VAST-AI-Research/TripoSR
- **Apple Silicon:** CPU fallback possible, no native MPS support
- **Performance on CPU:** Significantly slower, high RAM usage
- **Quality:** Good for Objaverse-like objects, less creative
- **Feasibility:** LOW-MEDIUM -- very slow without GPU

### 14.3 TRELLIS / TRELLIS.2 (Microsoft, CVPR 2025)

- **What:** Structured 3D latents for scalable 3D generation
- **GitHub:** https://github.com/microsoft/TRELLIS
- **Requirements:** Linux, NVIDIA GPU 16GB+
- **Apple Silicon:** NOT SUPPORTED
- **Feasibility:** BLOCKED

### 14.4 Pipeline: FLUX.2 -> Hunyuan3D -> Auto-rig -> Godot

```
Text prompt ("man in blue jumpsuit with blonde beard")
    |
    v
FLUX.2 (mflux, Apple Silicon native) -> 2D character image
    |
    v
Hunyuan3D-2-Mac (MPS) -> 3D mesh (.glb)
    |    [NOTE: includes clothing+hair as single geometry]
    v
Mesh cleanup (trimesh/PyMeshLab) -> separate body/clothing/hair
    |
    v
UniRig or Blender auto-rig -> rigged mesh
    |
    v
Export GLB -> Godot 4.6
```

**Challenges:**
- Hair/clothing fused with body (hard to separate)
- Rigging quality depends on mesh quality
- Texture may not transfer from Hunyuan3D
- Would need manual UV unwrapping
- **Overall feasibility:** LOW-MEDIUM (many failure points)

---

## 15. COMBINED: Text-to-3D Pipelines

### 15.1 LLaMA-Mesh (NVIDIA, text-to-mesh)

- **What:** LLM directly outputs 3D mesh vertices/faces as text tokens
- **GitHub:** https://github.com/nv-tlabs/LLaMA-Mesh
- **HuggingFace:** Zhengyi/LLaMA-Mesh
- **Apple Silicon:** CPU mode works (~2 min per mesh)
- **MPS:** Not explicitly tested, standard Transformers model
- **Blender addon:** MeshGen (CPU and GPU versions for Mac/Win/Linux)
- **Quality:** Simple objects; NOT suitable for detailed characters
- **Feasibility:** LOW for characters (can't generate detailed humanoid anatomy)
- **Possible use:** Generate simple clothing accessories (hat, glasses)

### 15.2 Stable-Dreamfusion

- **What:** Text-to-3D via NeRF + Stable Diffusion
- **GitHub:** https://github.com/ashawkey/stable-dreamfusion
- **Apple Silicon:** Taichi backend available (no CUDA), but limited functionality
- **Quality:** Medium; better for objects than characters
- **Feasibility:** LOW for our use case

### 15.3 Make-A-Character (Mach)

- **What:** Text-to-3D character using LLM+VLM
- **GitHub:** https://github.com/Human3DAIGC/Make-A-Character
- **Requirements:** NVIDIA GPU
- **Apple Silicon:** NOT SUPPORTED
- **Feasibility:** BLOCKED

---

## 16. PRACTICAL: Unconventional Approaches

### 16.1 FLUX.2 UV Texture Maps for Clothing Appearance

**Can FLUX.2 generate UV textures that look like clothing?**

YES, with caveats:
- FLUX.2 can generate textures conditioned on UV layout images
- ControlNet (depth/normal) helps maintain geometric consistency
- Seamless Texture LoRA enables tileable patterns
- **Result:** Clothing as painted-on texture (no geometry)
- **Best for:** T-shirts, tattoos, body paint, form-fitting underwear
- **NOT good for:** Jackets, loose clothing, anything that needs volume

### 16.2 SDF-Based Clothing Meshes

**Can we use SDFs to generate simple clothing?**

YES, for very simple shapes:
```python
from sdf import *

# Simple vest shape
body = sphere(1)  # approximate torso
vest = body.shell(0.05)  # 5cm shell
vest = vest & box([0.8, 1.2, 0.6])  # crop to vest shape
vest.save('vest.stl')
```

- **Library:** https://github.com/fogleman/sdf
- **Quality:** Very geometric, Minecraft-like
- **Feasibility:** LOW for Sims-like quality

### 16.3 Godot CSG for Clothing

**Verdict:** NOT PRACTICAL
- CSG is for level design, not character clothing
- Boolean operations too expensive at runtime
- No skinning support
- Cannot deform with skeleton

### 16.4 Godot ArrayMesh/SurfaceTool for Procedural Garments

**Can we generate clothing procedurally in Godot?**

YES, with significant effort:
```gdscript
# GDScript - simple procedural shirt
var st = SurfaceTool.new()
st.begin(Mesh.PRIMITIVE_TRIANGLES)
# Get body mesh vertices for torso region
# Offset along normals
# Create new surface with clothing UV mapping
var shirt_mesh = st.commit()
```

- **Feasibility:** MEDIUM for simple form-fitting clothes
- **NOT practical for:** Complex shapes, loose clothing

### 16.5 Full 2D-to-3D Character Pipeline

**Generate 2D -> TripoSR -> auto-rig -> Godot?**

Tested conceptual pipeline:
1. FLUX.2 generates consistent character turnaround views
2. Hunyuan3D-2-Mac generates mesh from front view
3. trimesh for mesh cleanup
4. UniRig (if CPU-compatible) or Blender bpy for rigging
5. Export GLB

**Problems:**
- Single-view 3D reconstruction loses detail on back
- Hair/clothing/body are fused
- Rigging quality is poor on ML-generated meshes
- UV unwrapping is needed manually
- **Verdict:** TOO FRAGILE for production pipeline

### 16.6 Hybrid Approach (RECOMMENDED)

Combine best tools from each category:

**For Hair:**
1. Pre-model 30 base hairstyle meshes in Blender/CharMorph
2. Generate hair card textures with FLUX.2 (mflux)
3. Use Kajiya-Kay shader in Godot for rendering
4. SpringBoneSimulator3D for physics

**For Clothing:**
1. Use GarmentCode + pygarment to define parametric garment patterns
2. Drape on MHR body with NVIDIA Warp (CPU mode)
3. Generate UV textures with FLUX.2
4. Export as GLB with skin weights
5. Load in Godot, bind to same skeleton

**For Facial Hair:**
1. Shell texturing for stubble/short beard (ShellFurGodot mobile shader)
2. Alpha-textured decals for eyebrows
3. Hair card strips for full beards (2-5 cards)
4. Textures generated by FLUX.2

---

## 17. TOOLING: Key Python Libraries

### Fully Apple Silicon Compatible (pip-installable)

| Library | Install | Use Case |
|---------|---------|----------|
| **trimesh** | `pip install trimesh` | Mesh loading, manipulation, export |
| **numpy** | `pip install numpy` | All numerical operations |
| **pygarment** | `pip install pygarment` | Sewing pattern DSL |
| **warp-lang** | `pip install warp-lang` | XPBD cloth simulation (CPU) |
| **pyvista** | `pip install pyvista` | Mesh processing, normals, boolean |
| **open3d** | `pip install open3d` | Mesh simplification, normals |
| **pyfqmr** | `pip install pyfqmr` | Fast quadric mesh reduction |
| **pymeshlab** | `pip install pymeshlab` | MeshLab operations from Python |
| **scipy** | `pip install scipy` | B-splines, spatial queries |
| **mflux** | `uv tool install mflux` | FLUX.2 image gen (MLX native) |
| **bpy** | Build from source or download | Blender as Python module |

### Partially Compatible (may need workarounds)

| Library | Install | Issue |
|---------|---------|-------|
| **torch** (MPS) | `pip install torch` | Some ops fall back to CPU |
| **diffusers** | `pip install diffusers` | MPS support with limitations |
| **transformers** | `pip install transformers` | Works on MPS for inference |

### NOT Compatible (CUDA required)

| Library | Why Blocked |
|---------|-------------|
| nvdiffrast | CUDA-only differentiable rendering |
| kaolin | NVIDIA's 3D deep learning library |
| pytorch3d | Facebook's 3D ML (CUDA extensions) |
| tiny-cuda-nn | CUDA-only neural networks |

---

## 18. MHR SPECIFICS: Integration Notes

### 18.1 MHR Mesh Specifications

- **Vertices:** 18,439 (LOD1)
- **LOD Levels:** 7 (LOD 0-6)
- **Joints:** 127 (root, spine, limbs, hands, fingers, eyes, jaw)
- **Parameters:** 45 shape + 204 articulation + 72 expression = 321 total
- **Export formats:** FBX, glTF
- **Performance:** >120 fps on desktop GPU

### 18.2 MHR <-> SMPL Compatibility

- MHR includes **conversion between MHR and SMPL/SMPL-X**
- This is critical because most clothing tools target SMPL
- **Workflow:**
  1. Convert MHR body to SMPL-equivalent
  2. Run SMPL-based clothing tools (TailorNet, CAPE, GarmentCode)
  3. Transfer clothing mesh back to MHR topology
  4. Or: keep clothing as separate mesh referencing MHR skeleton

### 18.3 Clothing Attachment Strategy for MHR

**Option A: Shared Skeleton (Recommended)**
- Clothing mesh rigged to MHR's 127-joint skeleton
- Simplified weight painting (clothing doesn't need finger bones)
- Import both meshes in Godot, bind to same Skeleton3D

**Option B: Vertex Displacement**
- Clothing as per-vertex offsets from MHR body surface
- Add offsets to body mesh at runtime
- Limited to tight-fitting clothing

**Option C: Bone-Attached Accessories**
- Hat attached to head bone
- Watch attached to wrist bone
- No separate skeleton needed

### 18.4 Hair Attachment Strategy for MHR

**Scalp region identification:**
- MHR mesh vertices for top/back/sides of head need to be identified
- Hair mesh root vertices are snapped to scalp vertices
- Hair skeleton (for SpringBoneSimulator3D) is child of head bone

**Facial hair placement:**
- Chin vertices -> beard attachment
- Upper lip vertices -> mustache attachment
- Brow ridge vertices -> eyebrow placement

---

## 19. FEASIBILITY MATRIX

### Hair Generation

| Approach | Apple Silicon | Pip Install | Quality | Effort | Verdict |
|----------|-------------|-------------|---------|--------|---------|
| Strand-based ML (DiffLocks etc) | NO | NO | Excellent | Low | BLOCKED |
| CharMorph/MakeHuman hair | YES | Partial | Good | Low | RECOMMENDED |
| Hair cards + FLUX.2 textures | YES | YES | Good | Medium | RECOMMENDED |
| Shell texturing (short hair) | YES (Godot) | N/A | Good | Low | RECOMMENDED |
| Procedural mesh hair (Python) | YES | YES | Medium | High | BACKUP |
| Blender bpy headless | YES | Build | Good | Medium | RECOMMENDED |

### Clothing Generation

| Approach | Apple Silicon | Pip Install | Quality | Effort | Verdict |
|----------|-------------|-------------|---------|--------|---------|
| GarmentCode + Warp (CPU) | YES | YES | Excellent | Medium | BEST OPTION |
| ChatGarment (VLM + GarmentCode) | PARTIAL | Partial | Excellent | High | PROMISING |
| TailorNet (vertex offset) | POSSIBLE | Partial | Good | Medium | WORTH TESTING |
| CharMorph/MakeHuman clothing | YES | Partial | Good | Low | RECOMMENDED |
| Shared skeleton templates | YES | N/A | Good | Medium | PRACTICAL |
| FLUX.2 UV texture only | YES | YES | Medium | Low | SUPPLEMENT |
| Hunyuan3D image-to-3D | PARTIAL | YES | Medium | Medium | RISKY |

### Combined Approaches

| Approach | Apple Silicon | Quality | Effort | Verdict |
|----------|-------------|---------|--------|---------|
| CharMorph batch gen | YES | Good | Low-Med | BEST FOR QUICK START |
| GarmentCode pipeline | YES | Excellent | High | BEST FOR PRODUCTION |
| Image-to-3D pipeline | PARTIAL | Medium | Very High | TOO FRAGILE |
| VRoid -> VRM -> Godot | YES | Good | Manual | NOT AUTOMATABLE |

---

## 20. RECOMMENDED APPROACH

### Phase 1: Quick Win (Week 1-2)

**Pre-generate character asset library using Blender:**

1. Install CharMorph in Blender (or use MakeHuman + MPFB2)
2. Generate 10 base body shapes using MHR-compatible skeleton
3. Export 20 hairstyle meshes (hair cards with alpha textures)
4. Export 20 clothing meshes (rigged to same skeleton)
5. Generate texture variations with FLUX.2 via mflux
6. All assets exported as GLB

**Godot setup:**
1. Import GLB assets
2. Use Kajiya-Kay hair shader for hair rendering
3. SpringBoneSimulator3D for hair physics
4. Shared Skeleton3D for clothing binding
5. ShellFurGodot mobile shader for eyebrows/stubble

### Phase 2: Parametric Generation (Week 3-6)

**Build programmatic clothing pipeline:**

1. `pip install pygarment warp-lang trimesh`
2. Define garment templates in GarmentCode DSL (shirt, pants, jacket, etc.)
3. For each body shape:
   a. Convert MHR body to SMPL-compatible mesh (using MHR's converter)
   b. Generate sewing patterns via pygarment
   c. Drape on body using NVIDIA Warp XPBD (CPU mode)
   d. Export draped mesh
4. Generate UV textures using FLUX.2 (mflux)
5. Apply textures, export as GLB
6. Load in Godot

**Build programmatic hair pipeline:**
1. Define hairstyle templates as Bezier curve configurations
2. For each style, extrude curves to ribbon/tube mesh
3. Generate hair card textures with FLUX.2
4. Apply anisotropic hair shader in Godot

### Phase 3: AI-Driven Customization (Week 7+)

**Optional advanced features:**

1. Integrate ChatGarment-style VLM for text-to-garment
2. Use local Ollama LLM to convert natural language to GarmentCode parameters
3. Use UVMap-ID or SMPLitex approach for personalized UV textures
4. Real-time garment fitting in Godot using ArrayMesh vertex offset

### Critical Path Summary

```
MHR Body Mesh (Meta)
    |
    +-- Hair System
    |    |-- Pre-modeled hair meshes (CharMorph/Blender)
    |    |-- FLUX.2 hair card textures (mflux)
    |    |-- Kajiya-Kay shader + SpringBoneSimulator3D (Godot)
    |    +-- ShellFurGodot for facial hair (Godot)
    |
    +-- Clothing System
    |    |-- GarmentCode/pygarment (sewing patterns)
    |    |-- NVIDIA Warp CPU (draping simulation)
    |    |-- FLUX.2 UV textures (mflux)
    |    +-- Shared skeleton binding (Godot)
    |
    +-- Godot 4.6 Renderer (Android)
         |-- VRM addon for import pipeline
         |-- Skeleton3D shared by body + hair + clothing
         |-- SpringBoneSimulator3D for secondary motion
         +-- Custom shaders (hair anisotropic, clothing PBR)
```

---

## Sources

### Hair Generation
- [DiffLocks GitHub](https://github.com/Meshcapade/difflocks)
- [CT2Hair GitHub](https://github.com/facebookresearch/CT2Hair)
- [Perm GitHub](https://github.com/c-he/perm)
- [HairFastGAN GitHub](https://github.com/AIRI-Institute/HairFastGAN)
- [GaussianHaircut GitHub](https://github.com/eth-ait/GaussianHaircut)
- [Awesome Hair and Fur Modeling Papers](https://github.com/Zhuoyang-Pan/Awesome-Hair-and-Fur-Modeling-Papers)
- [FiberShop Hair Card Generator](https://cgpal.com/fibershop/)

### Godot Hair/Clothing
- [ShellFurGodot](https://github.com/Arnklit/ShellFurGodot)
- [SO FLUFFY](https://github.com/maxvolumedev/sofluffy)
- [Squiggles Fur](https://github.com/QueenOfSquiggles/squiggles-fur)
- [SpringBoneSimulator3D Docs](https://docs.godotengine.org/en/stable/classes/class_springbonesimulator3d.html)
- [Godot SoftBody3D Docs](https://docs.godotengine.org/en/stable/classes/class_softbody3d.html)
- [Godot SurfaceTool Docs](https://docs.godotengine.org/en/stable/tutorials/3d/procedural_geometry/surfacetool.html)
- [Godot ArrayMesh Docs](https://docs.godotengine.org/en/stable/tutorials/3d/procedural_geometry/arraymesh.html)
- [Godot VRM Addon](https://github.com/V-Sekai/godot-vrm)
- [Godot Character Creation Suite](https://thowsenmedia.itch.io/godot-character-creation-suite)
- [SimpleToonHair Shader](https://godotshaders.com/shader/simpletoonhair/)

### Clothing Generation
- [GarmentCode GitHub](https://github.com/maria-korosteleva/GarmentCode)
- [pygarment PyPI](https://pypi.org/project/pygarment/)
- [NvidiaWarp-GarmentCode](https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode)
- [NVIDIA Warp GitHub](https://github.com/NVIDIA/warp)
- [DrapeNet GitHub](https://github.com/liren2515/DrapeNet)
- [TailorNet GitHub](https://github.com/chaitanya100100/TailorNet)
- [CAPE GitHub](https://github.com/qianlim/CAPE)
- [ChatGarment GitHub](https://github.com/biansy000/ChatGarment)
- [DressCode GitHub](https://github.com/IHe-KaiI/DressCode)
- [GarmentDiffusion GitHub](https://github.com/Shenfu-Research/GarmentDiffusion)
- [GarmageNet GitHub](https://github.com/Style3D/garmagenet-impl)
- [Garment-Pattern-Generator](https://github.com/maria-korosteleva/Garment-Pattern-Generator)
- [Awesome 3D Garments](https://github.com/Shanthika/Awesome-3D-Garments)

### Texture Generation
- [SMPLitex GitHub](https://github.com/dancasas/SMPLitex)
- [UVMap-ID GitHub](https://github.com/twowwj/UVMap-ID)
- [TexGarment Paper (CVPR 2025)](https://openaccess.thecvf.com/content/CVPR2025/papers/Liu_TexGarment_Consistent_Garment_UV_Texture_Generation_via_Efficient_3D_Structure-Guided_CVPR_2025_paper.pdf)
- [FLUX Seamless Texture LoRA](https://huggingface.co/gokaygokay/Flux-Seamless-Texture-LoRA)
- [mflux (MLX FLUX)](https://github.com/filipstrand/mflux)
- [StableGen Blender Plugin](https://github.com/sakalond/StableGen)

### Combined/Avatar Solutions
- [CharMorph GitHub](https://github.com/Upliner/CharMorph)
- [MakeHuman GitHub](https://github.com/makehumancommunity/makehuman)
- [MakeHuman Commandline](https://github.com/severin-lemaignan/makehuman-commandline)
- [Hunyuan3D-2 GitHub](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)
- [Hunyuan3D-2-Mac GitHub](https://github.com/Maxim-Lanskoy/Hunyuan3D-2-Mac)
- [TripoSR GitHub](https://github.com/VAST-AI-Research/TripoSR)
- [TRELLIS GitHub](https://github.com/microsoft/TRELLIS)
- [LLaMA-Mesh GitHub](https://github.com/nv-tlabs/LLaMA-Mesh)
- [UniRig GitHub](https://github.com/VAST-AI-Research/UniRig)
- [SimAvatar Paper](https://nvlabs.github.io/SimAvatar/)

### Python Libraries
- [trimesh](https://trimesh.org/)
- [pyfqmr PyPI](https://pypi.org/project/pyfqmr/)
- [PyVista](https://docs.pyvista.org/)
- [Open3D](https://www.open3d.org/)
- [PyMeshLab](https://pymeshlab.readthedocs.io/)
- [fogleman/sdf](https://github.com/fogleman/sdf)

### MHR (Meta Momentum Human Rig)
- [MHR GitHub](https://github.com/facebookresearch/MHR)
- [MHR Paper](https://arxiv.org/abs/2511.15586)

### Game Industry References
- [Making Hair and Beards for AAA Games](https://80.lv/articles/making-hair-and-beards-for-aaa-games)
- [Game Character Production Standards](https://80.lv/articles/game-character-production-industry-standards)
- [Layered Clothing Systems (GameDev.net)](https://www.gamedev.net/forums/topic/712598-layered-clothing-systems/)
- [Cloth Simulation for Games](https://80.lv/articles/cloth-simulation-for-games-difficulties-and-current-solutions)
- [PyTorch MPS Backend](https://docs.pytorch.org/docs/stable/notes/mps.html)
- [Blender Python Module](https://developer.blender.org/docs/handbook/building_blender/python_module/)
