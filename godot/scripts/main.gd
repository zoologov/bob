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
	# TODO: _create_bob() — will load MakeHuman/MPFB2 generated GLB


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
	sun.rotation_degrees = Vector3(-30.0, -45.0, 0.0)  # 45° сбоку, 30° сверху
	sun.shadow_enabled = false
	add_child(sun)
