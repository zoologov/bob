extends SceneTree
## Diagnose how Godot's GLTFDocument imports the GLB.
## Prints node hierarchy, transforms, and mesh AABBs.

func _init():
	var gltf_doc = GLTFDocument.new()
	var gltf_state = GLTFState.new()
	var glb_path = ProjectSettings.globalize_path("res://assets/bob.glb")

	var err = gltf_doc.append_from_file(glb_path, gltf_state)
	if err != OK:
		print("FAILED to load GLB: ", err)
		quit()
		return

	var root = gltf_doc.generate_scene(gltf_state)
	if not root:
		print("FAILED to generate scene")
		quit()
		return

	# Must add to tree for global transforms to work
	get_root().add_child(root)

	print("=" .repeat(70))
	print("GODOT GLTFDocument IMPORT DIAGNOSTIC")
	print("=" .repeat(70))

	_inspect_recursive(root, 0)

	print("\n" + "=" .repeat(70))
	print("MESH AABB COMPARISON (global space)")
	print("=" .repeat(70))

	var meshes: Array[Dictionary] = []
	_collect_meshes(root, meshes)

	for m in meshes:
		var mi: MeshInstance3D = m["node"]
		var aabb: AABB = mi.get_aabb()
		var global_aabb_pos = mi.global_position + aabb.position
		var global_aabb_end = global_aabb_pos + aabb.size
		print("\n  %s:" % m["path"])
		print("    local_pos:  %s" % str(mi.position))
		print("    global_pos: %s" % str(mi.global_position))
		print("    AABB pos:   %s  size: %s" % [str(aabb.position), str(aabb.size)])
		print("    global AABB Y: [%.4f, %.4f]" % [global_aabb_pos.y, global_aabb_end.y])
		print("    global AABB X: [%.4f, %.4f]" % [global_aabb_pos.x, global_aabb_end.x])
		print("    global AABB Z: [%.4f, %.4f]" % [global_aabb_pos.z, global_aabb_end.z])
		print("    surfaces: %d" % mi.mesh.get_surface_count())
		for si in range(mi.mesh.get_surface_count()):
			var mat = mi.mesh.surface_get_material(si)
			var mat_info = ""
			if mat:
				mat_info = " class=%s" % mat.get_class()
				if mat is BaseMaterial3D:
					mat_info += " transparency=%d cull=%d" % [mat.transparency, mat.cull_mode]
			print("    surface[%d]: %s%s" % [si, mat.resource_name if mat else "null", mat_info])

	quit()


func _inspect_recursive(node: Node, depth: int):
	var indent = "  ".repeat(depth)
	var info = "%s%s (%s)" % [indent, node.name, node.get_class()]

	if node is Node3D:
		var n3d = node as Node3D
		if n3d.position != Vector3.ZERO:
			info += " pos=%s" % str(n3d.position)
		if n3d.rotation != Vector3.ZERO:
			info += " rot=%s" % str(n3d.rotation)
		if n3d.scale != Vector3.ONE:
			info += " scale=%s" % str(n3d.scale)
		# Show global position if different from local
		if n3d.global_position != n3d.position:
			info += " GLOBAL_POS=%s" % str(n3d.global_position)

	if node is MeshInstance3D:
		var mi = node as MeshInstance3D
		info += " [MESH: verts_approx=%d]" % _approx_verts(mi)

	print(info)

	for child in node.get_children():
		_inspect_recursive(child, depth + 1)


func _approx_verts(mi: MeshInstance3D) -> int:
	var total = 0
	for si in range(mi.mesh.get_surface_count()):
		total += mi.mesh.surface_get_arrays(si)[Mesh.ARRAY_VERTEX].size()
	return total


func _collect_meshes(node: Node, result: Array[Dictionary], path: String = ""):
	var current_path = path + "/" + node.name
	if node is MeshInstance3D:
		result.append({"node": node, "path": current_path})
	for child in node.get_children():
		_collect_meshes(child, result, current_path)
