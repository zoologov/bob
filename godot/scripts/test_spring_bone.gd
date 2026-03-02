extends SceneTree
## V-05 validation: Test SpringBoneSimulator3D in Godot 4.6.
## Run: godot --headless --script res://scripts/test_spring_bone.gd

func _init() -> void:
	print("=== V-05: SpringBoneSimulator3D Test ===\n")

	# Test 1: Check if SpringBoneSimulator3D class exists
	print("--- Test 1: Class exists ---")
	var exists := ClassDB.class_exists("SpringBoneSimulator3D")
	print("  SpringBoneSimulator3D exists: " + str(exists))
	if not exists:
		print("  FAIL: SpringBoneSimulator3D not found in Godot " + Engine.get_version_info().string)
		print("  This node was added in Godot 4.4")
		quit()
		return
	print("  PASS\n")

	# Test 2: Create and configure
	print("--- Test 2: Create and configure ---")
	var skel := Skeleton3D.new()
	skel.name = "TestSkeleton"

	# Create a simple bone chain: root -> bone1 -> bone2 -> bone3 -> bone4
	# (simulating a hair strand attached to head)
	var bone_names := ["head", "hair_root", "hair_1", "hair_2", "hair_3", "hair_tip"]
	for i in range(bone_names.size()):
		var idx := skel.add_bone(bone_names[i])
		if i > 0:
			skel.set_bone_parent(idx, idx - 1)
		# Set bone rest pose — each bone 3cm below parent
		var rest := Transform3D.IDENTITY
		if i > 0:
			rest.origin = Vector3(0, -3.0, 0)  # 3cm down
		skel.set_bone_rest(idx, rest)

	print("  Skeleton created with " + str(skel.get_bone_count()) + " bones")
	for i in range(skel.get_bone_count()):
		var parent_name := "ROOT" if skel.get_bone_parent(i) < 0 else skel.get_bone_name(skel.get_bone_parent(i))
		print("    [" + str(i) + "] " + skel.get_bone_name(i) + " -> " + parent_name)

	# Create SpringBoneSimulator3D
	var spring := SpringBoneSimulator3D.new()
	spring.name = "SpringBone"

	# Add it to skeleton
	skel.add_child(spring)

	# Need to add to tree for it to work
	var root := Node3D.new()
	root.add_child(skel)
	get_root().add_child(root)

	print("  SpringBoneSimulator3D created")
	print("  PASS\n")

	# Test 3: Check properties
	print("--- Test 3: Check API/properties ---")
	var props := []
	for prop in spring.get_property_list():
		if not prop.name.begins_with("_") and prop.name != "":
			props.append(prop.name)

	# Print relevant properties
	var spring_props := props.filter(func(p: String) -> bool:
		return "spring" in p.to_lower() or "stiff" in p.to_lower() or "drag" in p.to_lower() or "gravity" in p.to_lower() or "bone" in p.to_lower() or "joint" in p.to_lower() or "center" in p.to_lower()
	)
	print("  Relevant properties: " + str(spring_props.size()))
	for p in spring_props:
		print("    " + p)
	print("  PASS\n")

	# Test 4: Check methods
	print("--- Test 4: Check methods ---")
	var methods := []
	for m in spring.get_method_list():
		if not m.name.begins_with("_"):
			methods.append(m.name)

	var spring_methods := methods.filter(func(m: String) -> bool:
		return "spring" in m.to_lower() or "joint" in m.to_lower() or "bone" in m.to_lower() or "setting" in m.to_lower()
	)
	print("  Relevant methods: " + str(spring_methods.size()))
	for m in spring_methods:
		print("    " + m)
	print("  PASS\n")

	print("=== V-05 COMPLETE ===")
	quit()
