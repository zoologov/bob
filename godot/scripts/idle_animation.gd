class_name IdleAnimation
extends Node
## Procedural idle animation for Bob's skeleton.
##
## All bone modifications are applied as offsets ON TOP of initial pose.
## The initial pose is saved at _ready() and preserved — only additive
## offsets are applied each frame.

var skeleton: Skeleton3D

## Set to false to freeze animation (debug rest pose)
@export var enabled: bool = true

# Bone indices
var _bone_spine_02: int = -1
var _bone_spine_03: int = -1
var _bone_pelvis: int = -1
var _bone_neck: int = -1
var _bone_head: int = -1
var _bone_clavicle_l: int = -1
var _bone_clavicle_r: int = -1
var _bone_upperarm_l: int = -1
var _bone_upperarm_r: int = -1

# Initial poses (saved at _ready, used as base for additive animation)
var _init_rot: Dictionary = {}
var _init_pos: Dictionary = {}

var _time: float = 0.0
var _noise: FastNoiseLite

## Breathing
const BREATH_SPEED: float = 0.8  # Hz
const BREATH_ANGLE: float = 0.04  # radians (~2.3°)
const BREATH_SCALE: float = 0.015  # chest Y-scale delta

## Sway
const SWAY_SPEED: float = 0.3
const SWAY_POS: float = 0.006  # meters
const SWAY_ROT: float = 0.012  # radians (~0.7°)

## Head
const HEAD_SPEED: float = 0.5
const HEAD_ROT: float = 0.04  # radians (~2.3°)
const NECK_ROT: float = 0.02  # radians (~1.1°)

## Shoulder
const SHOULDER_ROT: float = 0.015  # radians (~0.9°)

## Arm
const ARM_ROT: float = 0.01  # radians (~0.6°)


func _ready() -> void:
	_noise = FastNoiseLite.new()
	_noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_noise.frequency = 1.0
	_noise.seed = randi()

	if not skeleton:
		push_error("IdleAnimation: skeleton not set")
		return

	_bone_spine_02 = skeleton.find_bone("spine_02")
	_bone_spine_03 = skeleton.find_bone("spine_03")
	_bone_pelvis = skeleton.find_bone("pelvis")
	_bone_neck = skeleton.find_bone("neck_01")
	_bone_head = skeleton.find_bone("head")
	_bone_clavicle_l = skeleton.find_bone("clavicle_l")
	_bone_clavicle_r = skeleton.find_bone("clavicle_r")
	_bone_upperarm_l = skeleton.find_bone("upperarm_l")
	_bone_upperarm_r = skeleton.find_bone("upperarm_r")

	# Save initial poses — CRITICAL: bones have non-identity default rotations
	# that position the character upright. We must preserve them.
	var all_bones := [_bone_spine_02, _bone_spine_03, _bone_pelvis, _bone_neck,
		_bone_head, _bone_clavicle_l, _bone_clavicle_r,
		_bone_upperarm_l, _bone_upperarm_r]
	for idx in all_bones:
		if idx >= 0:
			_init_rot[idx] = skeleton.get_bone_pose_rotation(idx)
			_init_pos[idx] = skeleton.get_bone_pose_position(idx)

	var found := 0
	for idx in [_bone_spine_02, _bone_spine_03, _bone_pelvis, _bone_neck,
			_bone_head, _bone_clavicle_l, _bone_clavicle_r]:
		if idx >= 0:
			found += 1
	print("IdleAnimation: %d/7 core bones found" % found)


func _process(delta: float) -> void:
	if not skeleton or not enabled:
		return
	_time += delta
	_animate_breathing()
	_animate_sway()
	_animate_head()
	_animate_shoulders()
	_animate_arms()


func _animate_breathing() -> void:
	var breath := sin(_time * BREATH_SPEED * TAU)
	var breath_01 := (breath + 1.0) * 0.5  # 0..1

	if _bone_spine_02 >= 0:
		var base: Quaternion = _init_rot[_bone_spine_02]
		var offset := Quaternion(Vector3.RIGHT, -breath_01 * BREATH_ANGLE * 0.5)
		skeleton.set_bone_pose_rotation(_bone_spine_02, base * offset)

	if _bone_spine_03 >= 0:
		var base: Quaternion = _init_rot[_bone_spine_03]
		var offset := Quaternion(Vector3.RIGHT, -breath_01 * BREATH_ANGLE)
		skeleton.set_bone_pose_rotation(_bone_spine_03, base * offset)
		skeleton.set_bone_pose_scale(_bone_spine_03,
			Vector3(1.0, 1.0 + breath_01 * BREATH_SCALE, 1.0))


func _animate_sway() -> void:
	if _bone_pelvis < 0:
		return
	var t := _time * SWAY_SPEED
	var sx := _noise.get_noise_2d(t, 0.0) * SWAY_POS
	var sz := _noise.get_noise_2d(t, 200.0) * SWAY_POS * 0.5
	var sr := _noise.get_noise_2d(t, 100.0) * SWAY_ROT

	var base_rot: Quaternion = _init_rot[_bone_pelvis]
	var base_pos: Vector3 = _init_pos[_bone_pelvis]
	skeleton.set_bone_pose_rotation(_bone_pelvis, base_rot * Quaternion(Vector3.FORWARD, sr))
	skeleton.set_bone_pose_position(_bone_pelvis, base_pos + Vector3(sx, 0.0, sz))


func _animate_head() -> void:
	var t := _time * HEAD_SPEED

	if _bone_neck >= 0:
		var base: Quaternion = _init_rot[_bone_neck]
		var yaw := _noise.get_noise_2d(t, 300.0) * NECK_ROT
		var pitch := _noise.get_noise_2d(t, 400.0) * NECK_ROT
		var offset := Quaternion(Vector3.UP, yaw) * Quaternion(Vector3.RIGHT, pitch)
		skeleton.set_bone_pose_rotation(_bone_neck, base * offset)

	if _bone_head >= 0:
		var base: Quaternion = _init_rot[_bone_head]
		var yaw := _noise.get_noise_2d(t * 1.3, 500.0) * HEAD_ROT
		var pitch := _noise.get_noise_2d(t * 1.3, 600.0) * HEAD_ROT * 0.7
		var roll := _noise.get_noise_2d(t * 0.7, 700.0) * HEAD_ROT * 0.3
		var offset := Quaternion(Vector3.UP, yaw) * Quaternion(Vector3.RIGHT, pitch) * Quaternion(Vector3.FORWARD, roll)
		skeleton.set_bone_pose_rotation(_bone_head, base * offset)


func _animate_shoulders() -> void:
	var breath_phase := sin(_time * BREATH_SPEED * TAU + 0.5)
	var t := _time * 0.25

	if _bone_clavicle_l >= 0:
		var base: Quaternion = _init_rot[_bone_clavicle_l]
		var rise := breath_phase * SHOULDER_ROT * 0.5
		rise += _noise.get_noise_2d(t, 800.0) * SHOULDER_ROT
		skeleton.set_bone_pose_rotation(_bone_clavicle_l, base * Quaternion(Vector3.FORWARD, rise))

	if _bone_clavicle_r >= 0:
		var base: Quaternion = _init_rot[_bone_clavicle_r]
		var rise := breath_phase * SHOULDER_ROT * 0.5
		rise += _noise.get_noise_2d(t, 900.0) * SHOULDER_ROT
		skeleton.set_bone_pose_rotation(_bone_clavicle_r, base * Quaternion(Vector3.FORWARD, -rise))


func _animate_arms() -> void:
	var t := _time * 0.2

	if _bone_upperarm_l >= 0:
		var base: Quaternion = _init_rot[_bone_upperarm_l]
		var swing := _noise.get_noise_2d(t, 1000.0) * ARM_ROT
		skeleton.set_bone_pose_rotation(_bone_upperarm_l, base * Quaternion(Vector3.RIGHT, swing))

	if _bone_upperarm_r >= 0:
		var base: Quaternion = _init_rot[_bone_upperarm_r]
		var swing := _noise.get_noise_2d(t, 1100.0) * ARM_ROT
		skeleton.set_bone_pose_rotation(_bone_upperarm_r, base * Quaternion(Vector3.RIGHT, swing))
