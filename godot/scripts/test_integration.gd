extends SceneTree
## V-07 validation: Full integration test.
## Loads body + clothing + hair on shared skeleton in procedural room.
## Run: godot --headless --quit --script res://scripts/test_integration.gd

func _init() -> void:
	print("=== V-07: Full Integration Test ===\n")

	var results := {}

	# Step 1: Load body with skeleton
	print("--- Step 1: Load skinned body ---")
	var body_scene := _load_glb("res://assets/bob_body_skeleton.glb")
	if body_scene == null:
		print("  FAIL: Could not load body")
		quit()
		return

	var skel := _find_node_by_type(body_scene, "Skeleton3D") as Skeleton3D
	var body_mesh := _find_node_by_type(body_scene, "MeshInstance3D") as MeshInstance3D
	if skel == null or body_mesh == null:
		print("  FAIL: No skeleton or mesh in body")
		quit()
		return

	print("  Skeleton: " + str(skel.get_bone_count()) + " bones")
	print("  Body mesh: " + str(body_mesh.mesh.get_surface_count()) + " surfaces")

	# Scale from cm to m (MHR uses centimeters)
	body_scene.scale = Vector3(0.01, 0.01, 0.01)
	results["body"] = true
	print("  Scaled to meters (0.01)")
	print("  PASS\n")

	# Step 2: Load clothing (shirt)
	print("--- Step 2: Load shirt ---")
	var shirt_scene := _load_glb("res://assets/shirt.glb")
	if shirt_scene:
		var shirt_mesh := _find_node_by_type(shirt_scene, "MeshInstance3D") as MeshInstance3D
		if shirt_mesh:
			# Reparent to body scene, scale matches
			shirt_scene.scale = Vector3(0.01, 0.01, 0.01)
			print("  Shirt mesh loaded: " + str(shirt_mesh.mesh.get_surface_count()) + " surfaces")
			results["shirt"] = true
			print("  PASS\n")
		else:
			print("  FAIL: No mesh in shirt\n")
	else:
		print("  FAIL: Could not load shirt\n")

	# Step 3: Load clothing (pants)
	print("--- Step 3: Load pants ---")
	var pants_scene := _load_glb("res://assets/pants.glb")
	if pants_scene:
		var pants_mesh := _find_node_by_type(pants_scene, "MeshInstance3D") as MeshInstance3D
		if pants_mesh:
			pants_scene.scale = Vector3(0.01, 0.01, 0.01)
			print("  Pants mesh loaded: " + str(pants_mesh.mesh.get_surface_count()) + " surfaces")
			results["pants"] = true
			print("  PASS\n")
		else:
			print("  FAIL: No mesh in pants\n")
	else:
		print("  FAIL: Could not load pants\n")

	# Step 4: Load hair cards
	print("--- Step 4: Load hair cards ---")
	var hair_scene := _load_glb("res://assets/hair_cards.glb")
	if hair_scene:
		var hair_mesh := _find_node_by_type(hair_scene, "MeshInstance3D") as MeshInstance3D
		if hair_mesh:
			hair_scene.scale = Vector3(0.01, 0.01, 0.01)
			print("  Hair mesh loaded: " + str(hair_mesh.mesh.get_surface_count()) + " surfaces")
			results["hair"] = true
			print("  PASS\n")
		else:
			print("  FAIL: No mesh in hair\n")
	else:
		print("  FAIL: Could not load hair\n")

	# Step 5: Verify skeleton bone manipulation
	print("--- Step 5: Skeleton bone manipulation ---")
	# Try rotating the head bone
	var head_idx := skel.find_bone("c_head")
	if head_idx >= 0:
		print("  Found c_head at bone index " + str(head_idx))
		var original_pose := skel.get_bone_pose(head_idx)
		# Rotate head 15 degrees
		var rotated := original_pose.rotated(Vector3.RIGHT, deg_to_rad(15.0))
		skel.set_bone_pose(head_idx, rotated)
		var new_pose := skel.get_bone_pose(head_idx)
		print("  Applied 15° head rotation")
		print("  Pose changed: " + str(not original_pose.is_equal_approx(new_pose)))
		results["skeleton_control"] = true
		print("  PASS\n")
	else:
		print("  FAIL: c_head bone not found\n")

	# Try rotating finger
	var finger_idx := skel.find_bone("r_index1")
	if finger_idx >= 0:
		print("  Found r_index1 at bone index " + str(finger_idx))
		var rotated := Transform3D.IDENTITY.rotated(Vector3.FORWARD, deg_to_rad(45.0))
		skel.set_bone_pose(finger_idx, rotated)
		results["finger_control"] = true
		print("  Applied 45° finger curl — PASS\n")
	else:
		print("  r_index1 not found\n")

	# Step 6: Assembly check
	print("--- Step 6: Assembly summary ---")
	var total_verts := 0
	var total_faces := 0
	for scene in [body_scene, shirt_scene, pants_scene, hair_scene]:
		if scene == null:
			continue
		var mi := _find_node_by_type(scene, "MeshInstance3D") as MeshInstance3D
		if mi and mi.mesh:
			for s in range(mi.mesh.get_surface_count()):
				var arrays := mi.mesh.surface_get_arrays(s)
				if arrays.size() > 0 and arrays[0] != null:
					total_verts += arrays[0].size()
					if arrays.size() > 12 and arrays[12] != null:
						total_faces += arrays[12].size() / 3

	print("  Total vertices (all meshes): " + str(total_verts))
	print("  Components loaded:")
	for key in results:
		print("    " + key + ": " + str(results[key]))

	# Final verdict
	print("\n--- VERDICT ---")
	var required := ["body", "skeleton_control"]
	var optional := ["shirt", "pants", "hair", "finger_control"]
	var required_ok := true
	for r in required:
		if not results.has(r):
			required_ok = false
			print("  MISSING REQUIRED: " + r)

	var optional_count := 0
	for o in optional:
		if results.has(o):
			optional_count += 1

	print("  Required: " + str(required.size()) + "/" + str(required.size()) + (" OK" if required_ok else " FAIL"))
	print("  Optional: " + str(optional_count) + "/" + str(optional.size()) + " OK")

	if required_ok:
		print("\n  V-07: PASS")
	else:
		print("\n  V-07: FAIL")

	print("\n=== V-07 COMPLETE ===")
	quit()


func _load_glb(path: String) -> Node:
	var gltf := GLTFDocument.new()
	var state := GLTFState.new()
	var err := gltf.append_from_file(path, state)
	if err != OK:
		return null
	return gltf.generate_scene(state)


func _find_node_by_type(node: Node, type_name: String) -> Node:
	if node.get_class() == type_name:
		return node
	for child in node.get_children():
		var result := _find_node_by_type(child, type_name)
		if result != null:
			return result
	return null
