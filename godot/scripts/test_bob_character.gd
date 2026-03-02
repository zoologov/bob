extends SceneTree
## Test: Verify BobCharacter loads body + clothing + hair with toon shading.
## Run: godot --headless --quit --script res://scripts/test_bob_character.gd

var _bob: Node3D
var _frame: int = 0


func _init() -> void:
	print("=== Test: BobCharacter Loading ===\n")
	_bob = Node3D.new()
	var script := load("res://scripts/bob_character.gd")
	_bob.set_script(script)
	_bob.name = "Bob"
	root.add_child(_bob)
	# _ready() is deferred — check in _process after 2 frames


func _process(delta: float) -> bool:
	_frame += 1
	if _frame < 3:
		return false  # wait for _ready() to run

	if _frame == 3:
		_run_checks()
		quit()
	return false


func _run_checks() -> void:
	print("--- Node tree ---")
	_print_tree(_bob, 0)

	print("\n--- Verification ---")
	var body_root := _bob.get_node_or_null("BodyRoot")
	if body_root:
		print("  BodyRoot: FOUND (scale=" + str(body_root.scale) + ")")
	else:
		print("  BodyRoot: MISSING")

	var shirt := _bob.get_node_or_null("Shirt")
	print("  Shirt: " + ("FOUND" if shirt else "MISSING"))

	var pants := _bob.get_node_or_null("Pants")
	print("  Pants: " + ("FOUND" if pants else "MISSING"))

	var hair := _bob.get_node_or_null("Hair")
	print("  Hair: " + ("FOUND" if hair else "MISSING"))

	# Check skeleton
	var skel := _find_typed(_bob, "Skeleton3D") as Skeleton3D
	if skel:
		print("  Skeleton3D: " + str(skel.get_bone_count()) + " bones")
		var bones_to_check := ["c_spine0", "c_spine1", "c_spine2",
			"c_neck", "c_head", "r_wrist", "l_wrist", "r_index1"]
		for bone_name in bones_to_check:
			var idx := skel.find_bone(bone_name)
			print("    " + bone_name + ": " + ("idx=" + str(idx) if idx >= 0 else "NOT FOUND"))
	else:
		print("  Skeleton3D: MISSING")

	# Check toon shader
	var body_mi := _find_typed(_bob, "MeshInstance3D") as MeshInstance3D
	if body_mi and body_mi.material_override:
		var mat := body_mi.material_override as ShaderMaterial
		if mat and mat.shader:
			print("  Toon shader: APPLIED")
			print("  Outline pass: " + ("APPLIED" if mat.next_pass else "MISSING"))
		else:
			print("  Toon shader: NOT ShaderMaterial")
	else:
		print("  Body mesh material: MISSING")

	var mesh_count := _count_typed(_bob, "MeshInstance3D")
	print("  Total MeshInstance3D nodes: " + str(mesh_count))

	# Test idle animation ran
	print("\n--- Idle animation ---")
	print("  Root sway (rotation.z): " + str(_bob.rotation.z))
	if skel:
		var head_idx := skel.find_bone("c_head")
		if head_idx >= 0:
			var pose := skel.get_bone_pose(head_idx)
			print("  c_head animated: " + str(not pose.is_equal_approx(Transform3D.IDENTITY)))

	print("\n--- VERDICT ---")
	var required_ok := body_root != null and skel != null
	var all_parts := body_root != null and shirt != null and pants != null and hair != null
	print("  Body + Skeleton: " + ("PASS" if required_ok else "FAIL"))
	print("  All parts loaded: " + ("PASS" if all_parts else "PARTIAL"))
	print("  Overall: " + ("PASS" if required_ok else "FAIL"))
	print("\n=== Test Complete ===")


func _print_tree(node: Node, depth: int) -> void:
	var indent := "  ".repeat(depth + 1)
	var info := node.name + " (" + node.get_class() + ")"
	if node is MeshInstance3D and node.material_override:
		info += " [toon]"
	print(indent + info)
	for child in node.get_children():
		if depth < 4:
			_print_tree(child, depth + 1)


func _find_typed(node: Node, type_name: String) -> Node:
	if node.get_class() == type_name:
		return node
	for child in node.get_children():
		var result := _find_typed(child, type_name)
		if result != null:
			return result
	return null


func _count_typed(node: Node, type_name: String) -> int:
	var count := 0
	if node.get_class() == type_name:
		count += 1
	for child in node.get_children():
		count += _count_typed(child, type_name)
	return count
