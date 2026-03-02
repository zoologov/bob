extends SceneTree
## Test: Full scene — room + camera + lighting + BobCharacter.
## Run: godot --headless --script res://scripts/test_full_scene.gd

var _frame: int = 0


func _init() -> void:
	print("=== Test: Full Scene Integration ===\n")
	var main_script := load("res://scripts/main.gd")
	var scene := Node3D.new()
	scene.set_script(main_script)
	scene.name = "Main"
	root.add_child(scene)


func _process(delta: float) -> bool:
	_frame += 1
	if _frame < 5:
		return false

	if _frame == 5:
		_run_checks()
		quit()
	return false


func _run_checks() -> void:
	var main := root.get_node_or_null("Main")
	if main == null:
		print("  FAIL: Main node missing")
		return

	print("--- Scene components ---")
	for child in main.get_children():
		print("  " + child.name + " (" + child.get_class() + ")")

	# Verify each component
	var checks := {}

	# Room
	var room := main.get_node_or_null("Room")
	checks["Room"] = room != null
	if room:
		print("  Room children: " + str(room.get_child_count()))

	# Camera
	var cam_rig := main.get_node_or_null("CameraRig")
	checks["CameraRig"] = cam_rig != null
	var camera := _find_typed(main, "Camera3D") as Camera3D
	checks["Camera3D"] = camera != null
	if camera:
		print("  Camera projection: " + ("ortho" if camera.projection == Camera3D.PROJECTION_ORTHOGONAL else "persp"))

	# Bob
	var bob := main.get_node_or_null("Bob")
	checks["Bob"] = bob != null
	if bob:
		var skel := _find_typed(bob, "Skeleton3D") as Skeleton3D
		checks["Skeleton"] = skel != null
		if skel:
			print("  Bob skeleton: " + str(skel.get_bone_count()) + " bones")
		var mesh_count := _count_typed(bob, "MeshInstance3D")
		print("  Bob meshes: " + str(mesh_count))

	# Lighting
	var sun := main.get_node_or_null("SunLight")
	checks["SunLight"] = sun != null
	var lamp := main.get_node_or_null("RoomLamp")
	checks["RoomLamp"] = lamp != null

	# Environment
	var world_env := main.get_node_or_null("WorldEnvironment")
	checks["WorldEnvironment"] = world_env != null

	# Summary
	print("\n--- Results ---")
	var all_ok := true
	for key in checks:
		var status := "PASS" if checks[key] else "FAIL"
		if not checks[key]:
			all_ok = false
		print("  " + key + ": " + status)

	print("\n  Overall: " + ("PASS" if all_ok else "FAIL"))
	print("\n=== Test Complete ===")


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
