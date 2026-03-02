extends SceneTree
## V-06 validation: Test skinned .glb import in Godot.
## Run: godot --headless --script res://scripts/test_glb_import.gd

func _init() -> void:
	print("=== V-06: Skinned .glb Import Test ===\n")

	# Test 1: Import bare mesh (trimesh export)
	print("--- Test 1: Bare mesh GLB (trimesh export) ---")
	_test_glb("res://assets/bob_body_trimesh.glb", false)

	# Test 2: Import skinned mesh (GltfBuilder export with skeleton)
	print("\n--- Test 2: Skinned mesh GLB (GltfBuilder export) ---")
	_test_glb("res://assets/bob_body_skeleton.glb", true)

	print("\n=== V-06 COMPLETE ===")
	quit()


func _test_glb(path: String, expect_skeleton: bool) -> void:
	var gltf := GLTFDocument.new()
	var state := GLTFState.new()

	var err := gltf.append_from_file(path, state)
	if err != OK:
		print("  FAIL: Could not load " + path + " error=" + str(err))
		return

	print("  Loaded: " + path)
	print("  GLTF meshes: " + str(state.get_meshes().size()))
	print("  GLTF nodes: " + str(state.get_nodes().size()))
	print("  GLTF skeletons: " + str(state.get_skeletons().size()))

	# Generate scene
	var scene := gltf.generate_scene(state)
	if scene == null:
		print("  FAIL: generate_scene returned null")
		return

	print("  Scene root: " + scene.get_class() + " name=" + scene.name)
	print("  Children: " + str(scene.get_child_count()))

	# Walk children
	_walk_tree(scene, "  ")

	# Check for Skeleton3D
	var skel := _find_skeleton(scene)
	if skel != null:
		print("  Skeleton3D found: " + skel.name)
		print("  Bone count: " + str(skel.get_bone_count()))
		if skel.get_bone_count() > 0:
			print("  First 10 bones: ")
			for i in range(min(10, skel.get_bone_count())):
				var parent_idx := skel.get_bone_parent(i)
				var parent_name := "ROOT" if parent_idx < 0 else skel.get_bone_name(parent_idx)
				print("    [" + str(i) + "] " + skel.get_bone_name(i) + " -> parent: " + parent_name)

			# Count finger bones
			var finger_count := 0
			var face_count := 0
			for i in range(skel.get_bone_count()):
				var bname := skel.get_bone_name(i).to_lower()
				if "thumb" in bname or "index" in bname or "middle" in bname or "ring" in bname or "pinky" in bname:
					finger_count += 1
				if "jaw" in bname or "eye" in bname or "tongue" in bname:
					face_count += 1
			print("  Finger bones: " + str(finger_count))
			print("  Face bones: " + str(face_count))
		print("  PASS (skeleton imported)")
	elif expect_skeleton:
		print("  FAIL: Expected Skeleton3D but not found")
	else:
		print("  OK: No skeleton expected for bare mesh")

	# Check for MeshInstance3D
	var mesh_inst := _find_mesh_instance(scene)
	if mesh_inst != null:
		print("  MeshInstance3D found: " + mesh_inst.name)
		var mesh := mesh_inst.mesh
		if mesh != null:
			print("  Surface count: " + str(mesh.get_surface_count()))
			for s in range(mesh.get_surface_count()):
				var arrays := mesh.surface_get_arrays(s)
				if arrays.size() > 0 and arrays[0] != null:
					print("  Surface " + str(s) + " vertices: " + str(arrays[0].size()))
		print("  PASS (mesh imported)")
	else:
		print("  FAIL: No MeshInstance3D found")

	scene.queue_free()


func _walk_tree(node: Node, indent: String) -> void:
	print(indent + node.get_class() + ": " + node.name)
	for child in node.get_children():
		_walk_tree(child, indent + "  ")


func _find_skeleton(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node as Skeleton3D
	for child in node.get_children():
		var result := _find_skeleton(child)
		if result != null:
			return result
	return null


func _find_mesh_instance(node: Node) -> MeshInstance3D:
	if node is MeshInstance3D:
		return node as MeshInstance3D
	for child in node.get_children():
		var result := _find_mesh_instance(child)
		if result != null:
			return result
	return null
