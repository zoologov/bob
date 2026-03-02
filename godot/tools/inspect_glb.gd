extends SceneTree

func _init():
	var gltf_doc = GLTFDocument.new()
	var gltf_state = GLTFState.new()
	var err = gltf_doc.append_from_file(ProjectSettings.globalize_path("res://assets/bob.glb"), gltf_state)
	print("Load result: ", err)
	var bob = gltf_doc.generate_scene(gltf_state)
	_inspect(bob, 0)
	quit()

func _inspect(node: Node, depth: int):
	var indent = "  ".repeat(depth)
	if node is MeshInstance3D:
		var mi = node as MeshInstance3D
		print(indent, node.name, " MeshInstance3D surfaces=", mi.mesh.get_surface_count())
		for i in range(mi.mesh.get_surface_count()):
			var mat = mi.mesh.surface_get_material(i)
			print(indent, "  surface[", i, "] mat_type=", mat.get_class() if mat else "null")
			if mat is BaseMaterial3D:
				print(indent, "    albedo_color=", mat.albedo_color)
				print(indent, "    albedo_texture=", mat.albedo_texture)
				print(indent, "    transparency=", mat.transparency)
				print(indent, "    cull_mode=", mat.cull_mode)
	elif node is Skeleton3D:
		print(indent, node.name, " Skeleton3D bones=", node.get_bone_count())
	else:
		print(indent, node.name, " ", node.get_class())
	for child in node.get_children():
		_inspect(child, depth + 1)
