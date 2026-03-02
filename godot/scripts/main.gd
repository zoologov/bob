extends Node3D
## Main scene orchestrator.
## Procedurally creates: room, camera, placeholder Bob, lighting, environment.

const ProceduralRoomScript = preload("res://scripts/procedural_room.gd")
const CameraRigScript = preload("res://scripts/camera_rig.gd")
const BobPlaceholderScript = preload("res://scripts/bob_placeholder.gd")


func _ready() -> void:
	_setup_environment()
	_create_room()
	_create_camera()
	_create_bob()
	_create_lighting()


func _setup_environment() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.12, 0.12, 0.18)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.3, 0.28, 0.25)
	env.ambient_light_energy = 0.4
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC

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


func _create_bob() -> void:
	var bob := Node3D.new()
	bob.set_script(BobPlaceholderScript)
	bob.name = "Bob"
	add_child(bob)


func _create_lighting() -> void:
	# Sun through window (directional, from north and above)
	var sun := DirectionalLight3D.new()
	sun.name = "SunLight"
	sun.light_color = Color(1.0, 0.95, 0.85)
	sun.light_energy = 1.2
	sun.rotation_degrees = Vector3(-45.0, 0.0, 0.0)
	sun.shadow_enabled = true
	add_child(sun)

	# Room lamp (omni, near ceiling center)
	var lamp := OmniLight3D.new()
	lamp.name = "RoomLamp"
	lamp.light_color = Color(1.0, 0.9, 0.75)
	lamp.light_energy = 0.8
	lamp.omni_range = 6.0
	lamp.position = Vector3(0.0, 2.5, 0.0)
	lamp.shadow_enabled = true
	add_child(lamp)
