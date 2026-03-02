class_name ProceduralRoom
extends Node3D
## Procedural room generator: floor, walls, ceiling, window.
## Room is centered at origin, floor at Y=0.

const ROOM_WIDTH: float = 6.0   # X axis
const ROOM_DEPTH: float = 4.0   # Z axis
const ROOM_HEIGHT: float = 3.0  # Y axis
const WALL_THICKNESS: float = 0.1


func _ready() -> void:
	_build_floor()
	_build_ceiling()
	_build_walls()
	_build_window()


func _build_floor() -> void:
	var mi := MeshInstance3D.new()
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(ROOM_WIDTH, ROOM_DEPTH)
	mi.mesh = mesh

	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.65, 0.45, 0.28)  # warm wood
	mi.material_override = mat

	mi.name = "Floor"
	add_child(mi)


func _build_ceiling() -> void:
	var mi := MeshInstance3D.new()
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(ROOM_WIDTH, ROOM_DEPTH)
	mi.mesh = mesh

	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.95, 0.92, 0.88)
	mi.material_override = mat

	mi.position = Vector3(0.0, ROOM_HEIGHT, 0.0)
	mi.rotation_degrees = Vector3(180.0, 0.0, 0.0)  # face downward
	mi.name = "Ceiling"
	add_child(mi)


func _build_walls() -> void:
	var half_w := ROOM_WIDTH / 2.0
	var half_d := ROOM_DEPTH / 2.0
	var half_h := ROOM_HEIGHT / 2.0
	var wall_color := Color(0.88, 0.83, 0.73)  # light beige

	# North wall (-Z)
	_add_wall("WallNorth",
		Vector3(0.0, half_h, -half_d),
		Vector3(ROOM_WIDTH, ROOM_HEIGHT, WALL_THICKNESS),
		wall_color)

	# South wall (+Z)
	_add_wall("WallSouth",
		Vector3(0.0, half_h, half_d),
		Vector3(ROOM_WIDTH, ROOM_HEIGHT, WALL_THICKNESS),
		wall_color)

	# East wall (+X)
	_add_wall("WallEast",
		Vector3(half_w, half_h, 0.0),
		Vector3(WALL_THICKNESS, ROOM_HEIGHT, ROOM_DEPTH),
		wall_color)

	# West wall (-X)
	_add_wall("WallWest",
		Vector3(-half_w, half_h, 0.0),
		Vector3(WALL_THICKNESS, ROOM_HEIGHT, ROOM_DEPTH),
		wall_color)


func _add_wall(wall_name: String, pos: Vector3, size: Vector3, color: Color) -> void:
	var mi := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = size
	mi.mesh = mesh

	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mi.material_override = mat

	mi.position = pos
	mi.name = wall_name
	add_child(mi)


func _build_window() -> void:
	# Emissive panel on north wall simulating a window
	var mi := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = Vector3(1.5, 1.2, 0.01)
	mi.mesh = mesh

	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.8, 0.9, 1.0)
	mat.emission_enabled = true
	mat.emission = Color(0.8, 0.9, 1.0)
	mat.emission_energy_multiplier = 2.0
	mi.material_override = mat

	# Slightly in front of north wall, upper half
	mi.position = Vector3(0.0, ROOM_HEIGHT * 0.6, -ROOM_DEPTH / 2.0 + WALL_THICKNESS + 0.01)
	mi.name = "Window"
	add_child(mi)
