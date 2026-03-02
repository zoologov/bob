class_name BobCharacter
extends Node3D
## Bob character: loads MHR body + clothing + hair from .glb files.
## Applies toon shader, runs idle animation (breathing, head movement, sway).

# --- Idle animation parameters ---
const BREATH_SPEED: float = 0.3       # Hz (~18 breaths/min)
const BREATH_AMOUNT: float = 0.012    # radians (spine rotation)
const HEAD_NOD_SPEED: float = 0.13    # Hz (slow nod)
const HEAD_NOD_AMOUNT: float = 0.006  # radians
const HEAD_TURN_SPEED: float = 0.07   # Hz (slow look around)
const HEAD_TURN_AMOUNT: float = 0.01  # radians
const SWAY_SPEED: float = 0.15        # Hz (weight shifting)
const SWAY_AMOUNT: float = 0.003      # radians (root Z rotation)

# --- Colors (Vault Boy inspired) ---
const SKIN_BASE := Color(0.92, 0.78, 0.65)
const SKIN_SHADOW := Color(0.72, 0.55, 0.42)
const SHIRT_BASE := Color(0.25, 0.45, 0.72)
const SHIRT_SHADOW := Color(0.15, 0.3, 0.52)
const PANTS_BASE := Color(0.22, 0.22, 0.32)
const PANTS_SHADOW := Color(0.12, 0.12, 0.2)
const HAIR_BASE := Color(0.28, 0.2, 0.13)
const HAIR_SHADOW := Color(0.14, 0.09, 0.05)

var _skeleton: Skeleton3D
var _time: float = 0.0

# Cached bone indices (-1 = not found)
var _spine0_idx: int = -1
var _spine1_idx: int = -1
var _spine2_idx: int = -1
var _neck_idx: int = -1
var _head_idx: int = -1

var _toon_shader: Shader
var _outline_shader: Shader


func _ready() -> void:
	_toon_shader = load("res://shaders/toon.gdshader")
	_outline_shader = load("res://shaders/outline.gdshader")

	_load_body()
	_load_part("res://assets/shirt.glb", "Shirt", SHIRT_BASE, SHIRT_SHADOW)
	_load_part("res://assets/pants.glb", "Pants", PANTS_BASE, PANTS_SHADOW)
	_load_part("res://assets/hair_cards.glb", "Hair", HAIR_BASE, HAIR_SHADOW)
	_cache_bone_indices()


func _load_body() -> void:
	var scene := _load_glb("res://assets/bob_body_skeleton.glb")
	if scene == null:
		push_error("BobCharacter: failed to load body GLB")
		return

	scene.scale = Vector3(0.01, 0.01, 0.01)  # MHR cm -> Godot m
	scene.name = "BodyRoot"
	add_child(scene)

	_skeleton = _find_typed(scene, "Skeleton3D") as Skeleton3D
	var body_mi := _find_typed(scene, "MeshInstance3D") as MeshInstance3D
	if body_mi:
		body_mi.material_override = _make_toon_material(SKIN_BASE, SKIN_SHADOW)

	if _skeleton:
		print("BobCharacter: skeleton loaded, ", _skeleton.get_bone_count(), " bones")


func _load_part(path: String, part_name: String, base: Color, shadow: Color) -> void:
	var scene := _load_glb(path)
	if scene == null:
		push_warning("BobCharacter: could not load " + part_name)
		return

	scene.scale = Vector3(0.01, 0.01, 0.01)
	scene.name = part_name
	add_child(scene)

	var mi := _find_typed(scene, "MeshInstance3D") as MeshInstance3D
	if mi:
		mi.material_override = _make_toon_material(base, shadow)


func _cache_bone_indices() -> void:
	if _skeleton == null:
		return

	# MHR bone naming: c_ = center, r_ = right, l_ = left
	_spine0_idx = _skeleton.find_bone("c_spine0")
	_spine1_idx = _skeleton.find_bone("c_spine1")
	_spine2_idx = _skeleton.find_bone("c_spine2")
	_neck_idx = _skeleton.find_bone("c_neck")
	_head_idx = _skeleton.find_bone("c_head")

	print("BobCharacter: bones — spine0=", _spine0_idx,
		" spine1=", _spine1_idx, " spine2=", _spine2_idx,
		" neck=", _neck_idx, " head=", _head_idx)


func _process(delta: float) -> void:
	_time += delta
	_idle_animation()


func _idle_animation() -> void:
	if _skeleton == null:
		return

	# Breathing: spine forward/back rotation (inhale = slight arch back)
	var breath := sin(_time * BREATH_SPEED * TAU) * BREATH_AMOUNT
	_set_bone_rotation(_spine0_idx, Vector3.RIGHT, breath)
	_set_bone_rotation(_spine1_idx, Vector3.RIGHT, breath * 0.6)
	_set_bone_rotation(_spine2_idx, Vector3.RIGHT, breath * 0.3)

	# Neck follows breathing slightly
	_set_bone_rotation(_neck_idx, Vector3.RIGHT, -breath * 0.3)

	# Head subtle nod + slow lateral turn
	var nod := sin(_time * HEAD_NOD_SPEED * TAU) * HEAD_NOD_AMOUNT
	var turn := sin(_time * HEAD_TURN_SPEED * TAU) * HEAD_TURN_AMOUNT
	if _head_idx >= 0:
		var pose := Transform3D.IDENTITY
		pose = pose.rotated(Vector3.RIGHT, nod)
		pose = pose.rotated(Vector3.UP, turn)
		_skeleton.set_bone_pose(_head_idx, pose)

	# Root weight-shifting sway
	rotation.z = sin(_time * SWAY_SPEED * TAU) * SWAY_AMOUNT


func _set_bone_rotation(bone_idx: int, axis: Vector3, angle: float) -> void:
	if bone_idx < 0:
		return
	_skeleton.set_bone_pose(bone_idx, Transform3D.IDENTITY.rotated(axis, angle))


func _make_toon_material(base: Color, shadow: Color) -> ShaderMaterial:
	var mat := ShaderMaterial.new()
	mat.shader = _toon_shader
	mat.set_shader_parameter("base_color", Vector3(base.r, base.g, base.b))
	mat.set_shader_parameter("shadow_color", Vector3(shadow.r, shadow.g, shadow.b))

	var outline := ShaderMaterial.new()
	outline.shader = _outline_shader
	mat.next_pass = outline

	return mat


func _load_glb(path: String) -> Node:
	var gltf := GLTFDocument.new()
	var state := GLTFState.new()
	var err := gltf.append_from_file(path, state)
	if err != OK:
		return null
	return gltf.generate_scene(state)


func _find_typed(node: Node, type_name: String) -> Node:
	if node.get_class() == type_name:
		return node
	for child in node.get_children():
		var result := _find_typed(child, type_name)
		if result != null:
			return result
	return null
