extends Node3D
## Main scene orchestrator.
## Procedurally creates: room, camera, Bob character, lighting, environment.

const ProceduralRoomScript = preload("res://scripts/procedural_room.gd")
const CameraRigScript = preload("res://scripts/camera_rig.gd")

func _ready() -> void:
	_setup_environment()
	_create_room()
	_create_camera()
	_create_lighting()
	_create_bob()


func _setup_environment() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.4, 0.45, 0.5)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED  # toon shader handles fill
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR

	var world_env := WorldEnvironment.new()
	world_env.environment = env
	world_env.name = "WorldEnvironment"
	add_child(world_env)


func _create_room() -> void:
	var room := Node3D.new()
	room.set_script(ProceduralRoomScript)
	room.name = "Room"
	add_child(room)


func _create_camera() -> void:
	var rig := Node3D.new()
	rig.set_script(CameraRigScript)
	rig.name = "CameraRig"
	add_child(rig)


func _create_lighting() -> void:
	# Single directional light — toon shader handles lit vs shadow
	var sun := DirectionalLight3D.new()
	sun.name = "SunLight"
	sun.light_color = Color(1.0, 1.0, 1.0)
	sun.light_energy = 1.0
	sun.rotation_degrees = Vector3(-30.0, -45.0, 0.0)  # 45° from side, 30° from above
	sun.shadow_enabled = false
	add_child(sun)


func _create_bob() -> void:
	# Load GLB at runtime via GLTFDocument (works without editor import)
	var glb_path := ProjectSettings.globalize_path("res://assets/bob.glb")
	var gltf_doc := GLTFDocument.new()
	var gltf_state := GLTFState.new()

	var err := gltf_doc.append_from_file(glb_path, gltf_state)
	if err != OK:
		push_error("Failed to load Bob GLB: " + glb_path + " error=" + str(err))
		return

	var bob: Node3D = gltf_doc.generate_scene(gltf_state)
	if not bob:
		push_error("Failed to generate scene from GLB")
		return

	bob.name = "Bob"
	bob.position = Vector3(0.0, 0.0, 0.0)
	add_child(bob)

	# Fix transparency and make eyes/hair visible
	_fix_materials_recursive(bob)

	print("Bob loaded: ", bob.name)


func _fix_materials_recursive(node: Node) -> void:
	if node is MeshInstance3D:
		var mi := node as MeshInstance3D
		for surface_idx in range(mi.mesh.get_surface_count()):
			var mat := mi.mesh.surface_get_material(surface_idx)
			if mat is StandardMaterial3D:
				var std_mat := mat as StandardMaterial3D
				var has_alpha := std_mat.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED
				if has_alpha:
					# Use alpha hash for sparse-alpha textures (hair, eyebrows)
					# ALPHA_HASH approximates Blender's HASHED mode — renders
					# partial-alpha pixels stochastically instead of hard cutoff
					std_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_HASH
					std_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
				else:
					std_mat.cull_mode = BaseMaterial3D.CULL_BACK
	for child in node.get_children():
		_fix_materials_recursive(child)


