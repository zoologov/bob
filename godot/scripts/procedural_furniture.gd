class_name ProceduralFurniture
extends Node3D
## Procedural furniture: computer desk, office chair, and laptop.
## Built from BoxMesh/CylinderMesh primitives — no external assets needed.

# Colors
const COLOR_DESK := Color(0.55, 0.35, 0.18)  # dark wood
const COLOR_CHAIR := Color(0.3, 0.3, 0.35)    # dark gray
const COLOR_CHAIR_METAL := Color(0.5, 0.5, 0.55)  # metallic
const COLOR_LAPTOP_BODY := Color(0.2, 0.2, 0.22)  # dark laptop
const COLOR_SCREEN := Color(0.7, 0.85, 1.0)  # blue-white glow

# Desk dimensions (standard computer desk)
const DESK_WIDTH: float = 1.2   # X
const DESK_DEPTH: float = 0.6   # Z
const DESK_HEIGHT: float = 0.75  # Y — standard desk height
const DESK_TOP_THICK: float = 0.04
const DESK_LEG: float = 0.05  # leg cross-section

# Chair dimensions (office chair)
const SEAT_HEIGHT: float = 0.45
const SEAT_W: float = 0.45
const SEAT_D: float = 0.45
const SEAT_THICK: float = 0.05
const BACK_H: float = 0.40
const BACK_THICK: float = 0.05

# Laptop dimensions
const LAP_W: float = 0.35
const LAP_D: float = 0.25
const LAP_THICK: float = 0.015
const SCREEN_W: float = 0.33
const SCREEN_H: float = 0.22
const SCREEN_THICK: float = 0.008

# Positions
const DESK_POS := Vector3(0.0, 0.0, -0.5)
const CHAIR_POS := Vector3(0.0, 0.0, 0.0)


func _ready() -> void:
	_build_desk()
	_build_chair()
	_build_laptop()


func _build_desk() -> void:
	var desk := Node3D.new()
	desk.name = "Desk"
	desk.position = DESK_POS
	add_child(desk)

	# Tabletop
	desk.add_child(_make_box("Tabletop",
		Vector3(DESK_WIDTH, DESK_TOP_THICK, DESK_DEPTH),
		Vector3(0.0, DESK_HEIGHT, 0.0),
		COLOR_DESK))

	# 4 legs at corners
	var leg_h := DESK_HEIGHT - DESK_TOP_THICK * 0.5
	var hx := DESK_WIDTH * 0.5 - DESK_LEG * 0.5 - 0.02
	var hz := DESK_DEPTH * 0.5 - DESK_LEG * 0.5 - 0.02
	var corners := [
		Vector3(hx, leg_h * 0.5, hz),
		Vector3(-hx, leg_h * 0.5, hz),
		Vector3(hx, leg_h * 0.5, -hz),
		Vector3(-hx, leg_h * 0.5, -hz),
	]
	for i in range(corners.size()):
		desk.add_child(_make_box("Leg%d" % i,
			Vector3(DESK_LEG, leg_h, DESK_LEG),
			corners[i], COLOR_DESK))


func _build_chair() -> void:
	var chair := Node3D.new()
	chair.name = "Chair"
	chair.position = CHAIR_POS
	add_child(chair)

	# Seat
	chair.add_child(_make_box("Seat",
		Vector3(SEAT_W, SEAT_THICK, SEAT_D),
		Vector3(0.0, SEAT_HEIGHT, 0.0),
		COLOR_CHAIR))

	# Backrest
	var back_y := SEAT_HEIGHT + SEAT_THICK * 0.5 + BACK_H * 0.5
	var back_z := SEAT_D * 0.5 - BACK_THICK * 0.5
	chair.add_child(_make_box("Backrest",
		Vector3(SEAT_W, BACK_H, BACK_THICK),
		Vector3(0.0, back_y, back_z),
		COLOR_CHAIR))

	# Pedestal (center column)
	var ped_h := SEAT_HEIGHT - 0.08
	var pedestal := _make_cylinder("Pedestal", 0.04, ped_h,
		Vector3(0.0, ped_h * 0.5 + 0.04, 0.0), COLOR_CHAIR_METAL)
	chair.add_child(pedestal)

	# 5 caster arms (star pattern)
	for i in range(5):
		var angle := float(i) / 5.0 * TAU
		var r := 0.25
		var tip := Vector3(cos(angle) * r, 0.04, sin(angle) * r)

		# Arm — thin horizontal cylinder from center to tip
		var arm_len := r
		var arm := _make_cylinder("CasterArm%d" % i, 0.015, arm_len,
			Vector3(cos(angle) * r * 0.5, 0.04, sin(angle) * r * 0.5),
			COLOR_CHAIR_METAL)
		# Rotate cylinder from vertical to point outward
		arm.rotation = Vector3(0.0, -angle, PI * 0.5)
		chair.add_child(arm)

		# Wheel at tip
		var wheel := _make_cylinder("Wheel%d" % i, 0.02, 0.025,
			tip, Color(0.15, 0.15, 0.15))
		chair.add_child(wheel)


func _build_laptop() -> void:
	var laptop := Node3D.new()
	laptop.name = "Laptop"
	# On desk surface
	laptop.position = DESK_POS + Vector3(0.0, DESK_HEIGHT + DESK_TOP_THICK * 0.5, 0.0)
	add_child(laptop)

	# Base (keyboard area)
	laptop.add_child(_make_box("LaptopBase",
		Vector3(LAP_W, LAP_THICK, LAP_D),
		Vector3(0.0, LAP_THICK * 0.5, 0.0),
		COLOR_LAPTOP_BODY))

	# Screen pivot at back edge of base
	var screen_pivot := Node3D.new()
	screen_pivot.name = "ScreenPivot"
	screen_pivot.position = Vector3(0.0, LAP_THICK, -LAP_D * 0.5)
	screen_pivot.rotation_degrees.x = -70.0  # open ~110° (180 - 110 = 70 tilt back)
	laptop.add_child(screen_pivot)

	# Screen body
	screen_pivot.add_child(_make_box("ScreenBody",
		Vector3(SCREEN_W, SCREEN_H, SCREEN_THICK),
		Vector3(0.0, SCREEN_H * 0.5, 0.0),
		COLOR_LAPTOP_BODY))

	# Screen emissive face (slightly in front of body)
	var face := MeshInstance3D.new()
	var face_mesh := BoxMesh.new()
	face_mesh.size = Vector3(SCREEN_W - 0.02, SCREEN_H - 0.02, 0.001)
	face.mesh = face_mesh

	var face_mat := StandardMaterial3D.new()
	face_mat.albedo_color = COLOR_SCREEN
	face_mat.emission_enabled = true
	face_mat.emission = COLOR_SCREEN
	face_mat.emission_energy_multiplier = 1.5
	face.material_override = face_mat
	face.position = Vector3(0.0, SCREEN_H * 0.5, SCREEN_THICK * 0.5 + 0.001)
	face.name = "ScreenFace"
	screen_pivot.add_child(face)


# --- Helpers ---

func _make_box(box_name: String, size: Vector3, pos: Vector3, color: Color) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = size
	mi.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mi.material_override = mat
	mi.position = pos
	mi.name = box_name
	return mi


func _make_cylinder(cyl_name: String, radius: float, height: float,
		pos: Vector3, color: Color) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var mesh := CylinderMesh.new()
	mesh.top_radius = radius
	mesh.bottom_radius = radius
	mesh.height = height
	mi.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mi.material_override = mat
	mi.position = pos
	mi.name = cyl_name
	return mi
