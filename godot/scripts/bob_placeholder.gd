class_name BobPlaceholder
extends Node3D
## Placeholder Bob character made from capsule (body) + sphere (head).
## Includes idle animation: breathing, subtle sway.
## Will be replaced by MakeHuman model later.

const BREATH_FREQ: float = 0.3    # Hz (~18 breaths/min, slightly animated feel)
const BREATH_AMOUNT: float = 0.012 # scale Y variation
const SWAY_FREQ: float = 0.15      # Hz (slow weight shifting)
const SWAY_AMOUNT: float = 0.004   # radians

var _body: MeshInstance3D
var _head: MeshInstance3D
var _time: float = 0.0

var _toon_shader: Shader
var _outline_shader: Shader


func _ready() -> void:
	_toon_shader = load("res://shaders/toon.gdshader")
	_outline_shader = load("res://shaders/outline.gdshader")

	_build_body()
	_build_head()


func _build_body() -> void:
	_body = MeshInstance3D.new()
	var mesh := CapsuleMesh.new()
	mesh.radius = 0.25
	mesh.height = 1.2
	_body.mesh = mesh

	_body.material_override = _make_toon_material(
		Color(0.3, 0.45, 0.7),  # blue jumpsuit (Vault Boy)
		Color(0.2, 0.3, 0.5)
	)

	_body.position = Vector3(0.0, 0.6, 0.0)  # feet on floor
	_body.name = "Body"
	add_child(_body)


func _build_head() -> void:
	_head = MeshInstance3D.new()
	var mesh := SphereMesh.new()
	mesh.radius = 0.2
	mesh.height = 0.4
	_head.mesh = mesh

	_head.material_override = _make_toon_material(
		Color(0.9, 0.78, 0.65),  # skin
		Color(0.7, 0.55, 0.42)
	)

	_head.position = Vector3(0.0, 1.4, 0.0)  # on top of body
	_head.name = "Head"
	add_child(_head)


func _make_toon_material(base: Color, shadow: Color) -> ShaderMaterial:
	var mat := ShaderMaterial.new()
	mat.shader = _toon_shader
	mat.set_shader_parameter("base_color", Vector3(base.r, base.g, base.b))
	mat.set_shader_parameter("shadow_color", Vector3(shadow.r, shadow.g, shadow.b))

	# Outline as second pass
	var outline := ShaderMaterial.new()
	outline.shader = _outline_shader
	mat.next_pass = outline

	return mat


func _process(delta: float) -> void:
	_time += delta
	_idle_animation()


func _idle_animation() -> void:
	# Breathing: body Y scale oscillation
	var breath := sin(_time * BREATH_FREQ * TAU) * BREATH_AMOUNT
	_body.scale = Vector3(1.0, 1.0 + breath, 1.0)

	# Head follows breathing
	_head.position.y = 1.4 + breath * 2.0

	# Subtle weight-shifting sway
	var sway := sin(_time * SWAY_FREQ * TAU) * SWAY_AMOUNT
	rotation.z = sway
