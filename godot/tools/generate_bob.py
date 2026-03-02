"""Generate Bob character via MPFB2 in Blender headless mode.

Usage:
    blender --background --python godot/tools/generate_bob.py

Output:
    godot/assets/bob.glb — skinned character with game_engine rig
    (body, eyes, hair, clothing + skeleton for procedural animation)

Requires:
    - Blender 5.0+ with MPFB2 extension installed
    - MakeHuman system assets installed
"""

import sys
import os

# Must run inside Blender
try:
    import bpy
except ImportError:
    print("ERROR: This script must be run inside Blender:")
    print("  blender --background --python godot/tools/generate_bob.py")
    sys.exit(1)


def enable_mpfb() -> None:
    """Enable MPFB2 addon."""
    bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.mpfb")
    print("[OK] MPFB2 enabled")


def clear_scene() -> None:
    """Remove default Blender objects (Cube, Camera, Light)."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    print("[OK] Scene cleared")


def create_bob():
    """Create male human character via MPFB2."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService

    basemesh = HumanService.create_human(
        scale=0.1,  # MPFB uses cm internally, 0.1 = convert to Blender meters
        macro_detail_dict={
            "gender": 1.0,       # 1.0 = male
            "age": 0.4,          # young adult
            "muscle": 0.5,
            "weight": 0.4,
            "proportions": 0.5,
            "height": 0.5,
            "cupsize": 0.5,
            "firmness": 0.5,
            "race": {
                "caucasian": 1.0,
                "african": 0.0,
                "asian": 0.0,
            },
        },
    )
    print(f"[OK] Human created: {basemesh.name}, verts={len(basemesh.data.vertices)}")
    return basemesh


def find_asset(assets, pattern: str):
    """Find asset matching pattern in list of PosixPath objects."""
    for a in assets:
        if pattern in str(a):
            return a
    return assets[0] if assets else None


def add_eyes(basemesh) -> None:
    """Add high-poly eyes."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    eyes_list = AssetService.list_mhclo_assets(asset_subdir="eyes")
    eyes_file = find_asset(eyes_list, "high-poly")

    if eyes_file:
        HumanService.add_mhclo_asset(
            str(eyes_file), basemesh,
            asset_type="Eyes",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Eyes added: {os.path.basename(os.path.dirname(str(eyes_file)))}")
    else:
        print("[WARN] No eyes found")


def add_eyebrows(basemesh) -> None:
    """Add eyebrows."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    eyebrows = AssetService.list_mhclo_assets(asset_subdir="eyebrows")
    asset = find_asset(eyebrows, "eyebrow001")
    if asset:
        HumanService.add_mhclo_asset(
            str(asset), basemesh,
            asset_type="Eyebrows",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Eyebrows added: {os.path.basename(os.path.dirname(str(asset)))}")


def add_eyelashes(basemesh) -> None:
    """Add eyelashes."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    eyelashes = AssetService.list_mhclo_assets(asset_subdir="eyelashes")
    asset = find_asset(eyelashes, "eyelashes01")
    if asset:
        HumanService.add_mhclo_asset(
            str(asset), basemesh,
            asset_type="Eyelashes",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Eyelashes added: {os.path.basename(os.path.dirname(str(asset)))}")


def add_teeth(basemesh) -> None:
    """Add teeth."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    teeth = AssetService.list_mhclo_assets(asset_subdir="teeth")
    asset = find_asset(teeth, "teeth_shape01")
    if asset:
        HumanService.add_mhclo_asset(
            str(asset), basemesh,
            asset_type="Teeth",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Teeth added: {os.path.basename(os.path.dirname(str(asset)))}")


def add_hair(basemesh) -> None:
    """Add short male hairstyle."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    hair_list = AssetService.list_mhclo_assets(asset_subdir="hair")
    hair_file = find_asset(hair_list, "/short01/")
    if hair_file:
        HumanService.add_mhclo_asset(
            str(hair_file), basemesh,
            asset_type="Hair",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Hair added: {os.path.basename(os.path.dirname(str(hair_file)))}")
    else:
        print("[WARN] No hair found")


def add_clothes(basemesh) -> None:
    """Add male outfit (suit + shoes)."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    clothes_list = AssetService.list_mhclo_assets(asset_subdir="clothes")

    # Add suit: casualsuit04 (t-shirt + jeans)
    outfit_file = find_asset(clothes_list, "/male_casualsuit04/")
    if outfit_file:
        HumanService.add_mhclo_asset(
            str(outfit_file), basemesh,
            asset_type="Clothes",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Clothes added: {os.path.basename(os.path.dirname(str(outfit_file)))}")

    # Add shoes
    shoes_file = find_asset(clothes_list, "/shoes01/")
    if shoes_file:
        HumanService.add_mhclo_asset(
            str(shoes_file), basemesh,
            asset_type="Clothes",
            subdiv_levels=0,
            material_type="MAKESKIN",
        )
        print(f"[OK] Shoes added: {os.path.basename(os.path.dirname(str(shoes_file)))}")


def customize_tshirt_texture() -> None:
    """Replace casualsuit04 diffuse texture with custom 'I'm Bob' version.

    The custom texture (godot/assets/tshirt_texture_bob.png) is the original
    MPFB2 casualsuit04 diffuse with 'I'M BOB!' on the front panel and
    'AI POWERED' on the back, in orange matching the MakeHuman logo style.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    custom_path = os.path.join(os.path.dirname(script_dir), "assets", "tshirt_texture_bob.png")

    if not os.path.exists(custom_path):
        print(f"[WARN] Custom t-shirt texture not found: {custom_path}")
        return

    for obj in bpy.data.objects:
        if obj.type != "MESH" or "casualsuit" not in obj.name.lower():
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    if "diffuse" in node.name.lower():
                        node.image = bpy.data.images.load(custom_path)
                        print(f"[OK] Custom t-shirt texture applied")
                        return


def add_skin(basemesh) -> None:
    """Apply young caucasian male skin."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService

    skins = AssetService.list_mhmat_assets(asset_subdir="skins")
    skin_file = find_asset(skins, "young_caucasian_male/")
    if not skin_file:
        skin_file = find_asset(skins, "caucasian_male")
    if skin_file:
        HumanService.set_character_skin(
            str(skin_file), basemesh,
            skin_type="GAMEENGINE",
        )
        print(f"[OK] Skin applied: {os.path.basename(os.path.dirname(str(skin_file)))}")
    else:
        print("[WARN] No skin found")


def add_rig(basemesh) -> None:
    """Add game-engine rig (optimized for Godot)."""
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService

    HumanService.add_builtin_rig(basemesh, "game_engine")
    print("[OK] Game engine rig added")


def simplify_eye_material() -> None:
    """Remove pass-through MIX_RGB node from eye material for clean GLTF export.

    MPFB2 eye material has: diffuseTexture → diffuseIntensity (MIX_RGB) → BSDF.
    The MIX_RGB node (Factor=1.0, MIX, Color1=white) is a no-op pass-through,
    but the GLTF exporter can't represent intermediate mix nodes cleanly.
    Connect texture directly to Principled BSDF Base Color instead.
    """
    for obj in bpy.data.objects:
        if obj.type != "MESH" or "high-poly" not in obj.name.lower():
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat or not mat.node_tree:
                continue

            tree = mat.node_tree
            principled = None
            mix_rgb = None
            tex_image = None
            for node in tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    principled = node
                elif node.type == "MIX_RGB":
                    mix_rgb = node
                elif node.type == "TEX_IMAGE":
                    tex_image = node

            if not all([principled, mix_rgb, tex_image]):
                continue

            # Remove link from MIX_RGB to Base Color
            for link in list(tree.links):
                if link.to_node == principled and link.to_socket.name == "Base Color":
                    tree.links.remove(link)

            # Connect texture directly to Base Color
            tree.links.new(tex_image.outputs["Color"], principled.inputs["Base Color"])
            tree.nodes.remove(mix_rgb)
            print(f"  {obj.name}/{mat.name}: simplified eye node tree")


def fix_blend_modes() -> None:
    """Fix material blend modes and node trees for correct GLTF export.

    MPFB2 materials have alpha connections that cause GLTF exporter to use
    BLEND mode for everything, resulting in ALPHA_HASH in Godot.
    For opaque materials: disconnect Alpha input, set to 1.0.
    For alpha-textured materials (hair, eyebrows, eyelashes, eyes): set CLIP mode.
    Eyes need alpha for cornea transparency over the iris.
    """
    alpha_meshes = {"short01", "eyebrow001", "eyelashes01", "high-poly"}

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat or not mat.node_tree:
                continue

            mesh_name = obj.name.split(".")[-1] if "." in obj.name else obj.name

            # Find Principled BSDF node
            principled = None
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    principled = node
                    break

            if not principled:
                continue

            alpha_input = principled.inputs.get("Alpha")
            if not alpha_input:
                continue

            if mesh_name in alpha_meshes:
                # Keep alpha connections for shape cutout, set CLIP mode
                # Low threshold (0.05) because hair textures are very sparse
                # (~94% of pixels have zero alpha, strands have partial alpha)
                mat.blend_method = "CLIP"
                mat.alpha_threshold = 0.05
                mat.use_backface_culling = False  # double-sided for thin geometry
                print(f"  {obj.name}/{mat.name}: CLIP (alpha cutoff 0.05)")
            else:
                # Remove all alpha connections to force OPAQUE export
                if alpha_input.is_linked:
                    for link in list(mat.node_tree.links):
                        if link.to_socket == alpha_input:
                            mat.node_tree.links.remove(link)
                alpha_input.default_value = 1.0
                mat.blend_method = "OPAQUE"
                mat.use_backface_culling = True  # single-sided for solid geometry
                print(f"  {obj.name}/{mat.name}: OPAQUE (alpha disconnected, backface cull)")


def skin_accessories_to_armature() -> None:
    """Transfer bone weights to clothes/hair/eyes so they follow skeleton.

    MPFB2 parents accessories to the body mesh (not the armature directly),
    so they have no vertex groups and won't deform with the skeleton.
    Fix: re-parent each accessory to the armature with automatic weights.
    """
    armature_obj = None
    body_mesh = None
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            armature_obj = obj
        elif obj.type == "MESH" and obj.parent and obj.parent.type == "ARMATURE":
            body_mesh = obj

    if not armature_obj or not body_mesh:
        print("[WARN] Could not find armature or body mesh for weight transfer")
        return

    accessories = [obj for obj in bpy.data.objects
                   if obj.type == "MESH" and obj != body_mesh and obj.parent == body_mesh]

    for obj in accessories:
        # Save world transform (re-parenting changes local transform)
        world_mat = obj.matrix_world.copy()

        # Clear current parent
        obj.parent = None
        obj.matrix_world = world_mat

        # Re-parent to armature with automatic weights (heat diffusion)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        armature_obj.select_set(True)
        bpy.context.view_layer.objects.active = armature_obj

        try:
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
            groups = len(obj.vertex_groups) if obj.vertex_groups else 0
            print(f"  {obj.name}: auto-weights OK ({groups} groups)")
        except RuntimeError as e:
            # Fallback: parent without weights (static attachment to nearest bone)
            obj.parent = armature_obj
            obj.parent_type = "OBJECT"
            obj.matrix_world = world_mat
            print(f"  {obj.name}: auto-weights FAILED ({e}), static parent")


def print_skeleton_info() -> None:
    """Print skeleton bone hierarchy for debugging."""
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        armature = obj.data
        print(f"\nSkeleton: {obj.name} ({len(armature.bones)} bones)")
        for bone in armature.bones:
            parent_name = bone.parent.name if bone.parent else "ROOT"
            depth = 0
            b = bone
            while b.parent:
                depth += 1
                b = b.parent
            indent = "  " + "  " * depth
            print(f"{indent}{bone.name} (parent: {parent_name})")


def export_glb(output_path: str) -> None:
    """Export scene to GLB with skeleton (skinned mesh)."""
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format="GLB",
        export_animations=False,
        export_skins=True,
        export_normals=True,
        export_materials="EXPORT",
        export_texcoords=True,
        use_selection=False,
    )
    file_size = os.path.getsize(output_path)
    print(f"[OK] Exported: {output_path} ({file_size / 1024 / 1024:.1f} MB)")


def main() -> None:
    """Generate Bob character and export to GLB."""
    # Determine output path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)  # godot/
    output_path = os.path.join(project_dir, "assets", "bob.glb")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print("=" * 60)
    print("  Generating Bob character via MPFB2")
    print("=" * 60)

    enable_mpfb()
    clear_scene()

    basemesh = create_bob()
    add_eyes(basemesh)
    add_eyebrows(basemesh)
    add_eyelashes(basemesh)
    add_teeth(basemesh)
    add_hair(basemesh)
    add_clothes(basemesh)
    customize_tshirt_texture()
    add_skin(basemesh)
    add_rig(basemesh)

    # Transfer bone weights to accessories (clothes, hair, eyes, teeth).
    # MPFB2 parents accessories to the body mesh, not the armature,
    # so they have no vertex groups and won't follow skeletal animation.
    print()
    print("Skinning accessories to armature:")
    skin_accessories_to_armature()

    # Simplify eye material (remove pass-through MIX_RGB node)
    print()
    print("Simplifying eye material:")
    simplify_eye_material()

    # Fix material blend modes for proper GLTF alpha export
    print()
    print("Fixing blend modes:")
    fix_blend_modes()

    # Process modifiers for skinned export:
    # Strategy: temporarily remove Armature, apply all others (MASK, etc.),
    # then re-add Armature. Avoids "not first modifier" warnings.
    print()
    print("Processing modifiers:")
    armature_obj = None
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            armature_obj = obj
            break

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Remove shape keys — MUST use apply_mix=True to keep current shape!
        if obj.data.shape_keys:
            count = len(obj.data.shape_keys.key_blocks)
            bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
            print(f"  Baked {count} shape keys from {obj.name}")

        # Temporarily remove Armature modifier (save reference to armature)
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                obj.modifiers.remove(mod)

        # Apply all remaining modifiers (MASK, etc.) — clean stack
        while obj.modifiers:
            mod = obj.modifiers[0]
            mod_name = mod.name
            mod_type = mod.type
            try:
                bpy.ops.object.modifier_apply(modifier=mod_name)
                print(f"  {obj.name}: applied {mod_name} ({mod_type})")
            except RuntimeError as e:
                print(f"  {obj.name}: WARN applying {mod_name}: {e}")
                obj.modifiers.remove(mod)

        # Re-add Armature modifier if mesh has vertex groups (is skinned)
        if obj.vertex_groups and armature_obj:
            arm_mod = obj.modifiers.new("Armature", "ARMATURE")
            arm_mod.object = armature_obj

        obj.select_set(False)

    # Report: all meshes with their skinning state
    print()
    print("Final mesh state:")
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            mods = [f"{m.name}({m.type})" for m in obj.modifiers]
            vgroups = len(obj.vertex_groups) if obj.vertex_groups else 0
            parent = obj.parent.name if obj.parent else "None"
            print(f"  {obj.name}: {len(obj.data.vertices)} verts, groups={vgroups}, parent={parent}, mods={mods}")

    # Print skeleton info for reference
    print()
    print("Skeleton info:")
    print_skeleton_info()

    export_glb(output_path)

    print()
    print("=" * 60)
    print(f"  Bob generated: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
