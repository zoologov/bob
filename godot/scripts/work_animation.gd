class_name WorkAnimation
extends Node
## Procedural work animation: sitting pose + breathing + head look-at-screen + typing.
##
## Replaces IdleAnimation when Bob is seated at the laptop.
## Single script manages ALL bones to avoid conflicts between separate pose scripts.
##
## All bone modifications are applied as offsets ON TOP of initial pose.
## The initial pose is saved at _ready() and preserved — only additive offsets are applied.

var skeleton: Skeleton3D

## Set to false to freeze animation (debug rest pose)
@export var enabled: bool = true

# --- Bone indices: body ---
var _bone_pelvis: int = -1
var _bone_spine_01: int = -1
var _bone_spine_02: int = -1
var _bone_spine_03: int = -1
var _bone_neck: int = -1
var _bone_head: int = -1
var _bone_clavicle_l: int = -1
var _bone_clavicle_r: int = -1
var _bone_upperarm_l: int = -1
var _bone_upperarm_r: int = -1
var _bone_lowerarm_l: int = -1
var _bone_lowerarm_r: int = -1
var _bone_hand_l: int = -1
var _bone_hand_r: int = -1

# --- Bone indices: legs ---
var _bone_thigh_l: int = -1
var _bone_thigh_r: int = -1
var _bone_calf_l: int = -1
var _bone_calf_r: int = -1
var _bone_foot_l: int = -1
var _bone_foot_r: int = -1

# --- Bone indices: fingers ---
# Dictionary of finger_name -> Array[int] with [joint_01, joint_02, joint_03]
var _fingers_l: Dictionary = {}
var _fingers_r: Dictionary = {}
const FINGER_NAMES: PackedStringArray = ["thumb", "index", "middle", "ring", "pinky"]
# Fingers eligible for typing keystrokes (excluding thumb from normal typing)
const TYPING_FINGERS: PackedStringArray = ["index", "middle", "ring", "pinky"]

# --- Initial poses (saved at _ready) ---
var _init_rot: Dictionary = {}
var _init_pos: Dictionary = {}

var _time: float = 0.0
var _noise: FastNoiseLite
var _typing_rng: RandomNumberGenerator

# =============================================================================
# Sitting pose constants (radians unless noted)
# =============================================================================

## Pelvis vertical drop to seat height (meters)
const SIT_PELVIS_DROP: float = 0.35
## Thigh forward bend (~80°)
const SIT_THIGH_BEND: float = 1.4
## Calf backward bend at knee (~80°)
const SIT_CALF_BEND: float = -1.4
## Foot adjustment to flatten feet
const SIT_FOOT_ADJUST: float = 0.3
## Spine forward lean (split across spine_02 + spine_03)
const SIT_SPINE_LEAN: float = -0.08
## Neck tilt down toward screen
const SIT_NECK_TILT: float = -0.12
## Head tilt down toward screen
const SIT_HEAD_TILT: float = -0.08
## Upper arm: slight backward pull so elbows stay at desk height
const SIT_UPPERARM_FWD: float = -0.15
## Upper arm adduction (bring elbows toward body center)
const SIT_UPPERARM_ADDUCT_L: float = 0.2  # left arm inward
const SIT_UPPERARM_ADDUCT_R: float = -0.2  # right arm inward
## Elbow flexion — bring forearms horizontal to desk
const SIT_LOWERARM_BEND: float = 0.4
## Wrist angle (slightly down)
const SIT_HAND_ANGLE: float = 0.15

# =============================================================================
# Breathing (reduced amplitude vs idle — 50%)
# =============================================================================
const BREATH_SPEED: float = 0.8  # Hz
const BREATH_ANGLE: float = 0.02  # radians
const BREATH_SCALE: float = 0.008  # chest Y-scale delta

# =============================================================================
# Head micro-movements (subtle, looking at screen)
# =============================================================================
const HEAD_SPEED: float = 0.4  # Hz
const HEAD_ROT: float = 0.025  # radians
const NECK_ROT: float = 0.012  # radians

# =============================================================================
# Typing animation
# =============================================================================
## Resting finger curl (radians per joint)
const TYPE_CURL_REST: float = 0.3
## Finger curl when pressing a key (nearly extended)
const TYPE_CURL_PRESS: float = 0.05
## Average keystrokes per second
const TYPE_SPEED: float = 4.0
## Duration of a single keypress (extend + return)
const TYPE_PRESS_DUR: float = 0.08
## Hand micro-drift amplitude (radians)
const HAND_DRIFT: float = 0.02

# Typing state
var _active_keystrokes: Array = []  # [{finger: String, side: String, start_time: float}]
var _next_keystroke_time: float = 0.0


func _ready() -> void:
	_noise = FastNoiseLite.new()
	_noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_noise.frequency = 1.0
	_noise.seed = randi()

	_typing_rng = RandomNumberGenerator.new()
	_typing_rng.randomize()

	if not skeleton:
		push_error("WorkAnimation: skeleton not set")
		return

	# --- Discover body bones ---
	_bone_pelvis = skeleton.find_bone("pelvis")
	_bone_spine_01 = skeleton.find_bone("spine_01")
	_bone_spine_02 = skeleton.find_bone("spine_02")
	_bone_spine_03 = skeleton.find_bone("spine_03")
	_bone_neck = skeleton.find_bone("neck_01")
	_bone_head = skeleton.find_bone("head")
	_bone_clavicle_l = skeleton.find_bone("clavicle_l")
	_bone_clavicle_r = skeleton.find_bone("clavicle_r")
	_bone_upperarm_l = skeleton.find_bone("upperarm_l")
	_bone_upperarm_r = skeleton.find_bone("upperarm_r")
	_bone_lowerarm_l = skeleton.find_bone("lowerarm_l")
	_bone_lowerarm_r = skeleton.find_bone("lowerarm_r")
	_bone_hand_l = skeleton.find_bone("hand_l")
	_bone_hand_r = skeleton.find_bone("hand_r")

	# --- Discover leg bones ---
	_bone_thigh_l = skeleton.find_bone("thigh_l")
	_bone_thigh_r = skeleton.find_bone("thigh_r")
	_bone_calf_l = skeleton.find_bone("calf_l")
	_bone_calf_r = skeleton.find_bone("calf_r")
	_bone_foot_l = skeleton.find_bone("foot_l")
	_bone_foot_r = skeleton.find_bone("foot_r")

	# --- Discover finger bones ---
	for fname in FINGER_NAMES:
		var joints_l: Array[int] = []
		var joints_r: Array[int] = []
		for joint_suffix in ["_01_", "_02_", "_03_"]:
			joints_l.append(skeleton.find_bone(fname + joint_suffix + "l"))
			joints_r.append(skeleton.find_bone(fname + joint_suffix + "r"))
		_fingers_l[fname] = joints_l
		_fingers_r[fname] = joints_r

	# --- Save initial poses for every bone we'll manipulate ---
	var all_indices: Array[int] = []
	all_indices.append_array([
		_bone_pelvis, _bone_spine_01, _bone_spine_02, _bone_spine_03,
		_bone_neck, _bone_head,
		_bone_clavicle_l, _bone_clavicle_r,
		_bone_upperarm_l, _bone_upperarm_r,
		_bone_lowerarm_l, _bone_lowerarm_r,
		_bone_hand_l, _bone_hand_r,
		_bone_thigh_l, _bone_thigh_r,
		_bone_calf_l, _bone_calf_r,
		_bone_foot_l, _bone_foot_r,
	])
	for fname in FINGER_NAMES:
		for idx: int in _fingers_l[fname]:
			all_indices.append(idx)
		for idx: int in _fingers_r[fname]:
			all_indices.append(idx)

	var found := 0
	for idx in all_indices:
		if idx >= 0:
			_init_rot[idx] = skeleton.get_bone_pose_rotation(idx)
			_init_pos[idx] = skeleton.get_bone_pose_position(idx)
			found += 1

	print("WorkAnimation: %d/%d bones found" % [found, all_indices.size()])


func _process(delta: float) -> void:
	if not skeleton or not enabled:
		return
	_time += delta
	_apply_sitting_pose()
	_animate_breathing()
	_animate_head()
	_animate_typing()


# =============================================================================
# Sitting pose — constant offsets from rest pose
# =============================================================================

func _apply_sitting_pose() -> void:
	# Pelvis: drop to seat height
	if _bone_pelvis >= 0:
		var base_pos: Vector3 = _init_pos[_bone_pelvis]
		skeleton.set_bone_pose_position(_bone_pelvis,
			base_pos + Vector3(0.0, -SIT_PELVIS_DROP, 0.0))
		skeleton.set_bone_pose_rotation(_bone_pelvis, _init_rot[_bone_pelvis])

	# Thighs: bend forward (hip flexion)
	_set_bone_offset(_bone_thigh_l, Vector3.RIGHT, SIT_THIGH_BEND)
	_set_bone_offset(_bone_thigh_r, Vector3.RIGHT, SIT_THIGH_BEND)

	# Calves: bend backward (knee flexion)
	_set_bone_offset(_bone_calf_l, Vector3.RIGHT, SIT_CALF_BEND)
	_set_bone_offset(_bone_calf_r, Vector3.RIGHT, SIT_CALF_BEND)

	# Feet: flatten
	_set_bone_offset(_bone_foot_l, Vector3.RIGHT, SIT_FOOT_ADJUST)
	_set_bone_offset(_bone_foot_r, Vector3.RIGHT, SIT_FOOT_ADJUST)

	# Upper arms: reach forward + adduct toward body center
	if _bone_upperarm_l >= 0:
		var base: Quaternion = _init_rot[_bone_upperarm_l]
		var fwd := Quaternion(Vector3.RIGHT, SIT_UPPERARM_FWD)
		var adduct := Quaternion(Vector3.FORWARD, SIT_UPPERARM_ADDUCT_L)
		skeleton.set_bone_pose_rotation(_bone_upperarm_l, base * fwd * adduct)
	if _bone_upperarm_r >= 0:
		var base: Quaternion = _init_rot[_bone_upperarm_r]
		var fwd := Quaternion(Vector3.RIGHT, SIT_UPPERARM_FWD)
		var adduct := Quaternion(Vector3.FORWARD, SIT_UPPERARM_ADDUCT_R)
		skeleton.set_bone_pose_rotation(_bone_upperarm_r, base * fwd * adduct)

	# Lower arms: bend elbows
	_set_bone_offset(_bone_lowerarm_l, Vector3.RIGHT, SIT_LOWERARM_BEND)
	_set_bone_offset(_bone_lowerarm_r, Vector3.RIGHT, SIT_LOWERARM_BEND)

	# Hands: wrist angle — overwritten later by _animate_hand_drift, but set base here
	# (hand_drift re-applies SIT_HAND_ANGLE + noise, so skip here to avoid double-set)


# =============================================================================
# Breathing — same as idle but reduced amplitude
# =============================================================================

func _animate_breathing() -> void:
	var breath := sin(_time * BREATH_SPEED * TAU)
	var breath_01 := (breath + 1.0) * 0.5  # 0..1

	if _bone_spine_02 >= 0:
		var base: Quaternion = _init_rot[_bone_spine_02]
		var lean := Quaternion(Vector3.RIGHT, SIT_SPINE_LEAN * 0.4)
		var breathe := Quaternion(Vector3.RIGHT, -breath_01 * BREATH_ANGLE * 0.5)
		skeleton.set_bone_pose_rotation(_bone_spine_02, base * lean * breathe)

	if _bone_spine_03 >= 0:
		var base: Quaternion = _init_rot[_bone_spine_03]
		var lean := Quaternion(Vector3.RIGHT, SIT_SPINE_LEAN * 0.6)
		var breathe := Quaternion(Vector3.RIGHT, -breath_01 * BREATH_ANGLE)
		skeleton.set_bone_pose_rotation(_bone_spine_03, base * lean * breathe)
		skeleton.set_bone_pose_scale(_bone_spine_03,
			Vector3(1.0, 1.0 + breath_01 * BREATH_SCALE, 1.0))


# =============================================================================
# Head micro-movements — looking at screen with subtle noise
# =============================================================================

func _animate_head() -> void:
	var t := _time * HEAD_SPEED

	if _bone_neck >= 0:
		var base: Quaternion = _init_rot[_bone_neck]
		var look_down := Quaternion(Vector3.RIGHT, SIT_NECK_TILT)
		var yaw := _noise.get_noise_2d(t, 300.0) * NECK_ROT
		var pitch := _noise.get_noise_2d(t, 400.0) * NECK_ROT
		var micro := Quaternion(Vector3.UP, yaw) * Quaternion(Vector3.RIGHT, pitch)
		skeleton.set_bone_pose_rotation(_bone_neck, base * look_down * micro)

	if _bone_head >= 0:
		var base: Quaternion = _init_rot[_bone_head]
		var look_down := Quaternion(Vector3.RIGHT, SIT_HEAD_TILT)
		var yaw := _noise.get_noise_2d(t * 1.3, 500.0) * HEAD_ROT
		var pitch := _noise.get_noise_2d(t * 1.3, 600.0) * HEAD_ROT * 0.7
		var roll := _noise.get_noise_2d(t * 0.7, 700.0) * HEAD_ROT * 0.3
		var micro := (Quaternion(Vector3.UP, yaw)
			* Quaternion(Vector3.RIGHT, pitch)
			* Quaternion(Vector3.FORWARD, roll))
		skeleton.set_bone_pose_rotation(_bone_head, base * look_down * micro)


# =============================================================================
# Typing animation — random keystrokes on finger bones
# =============================================================================

func _animate_typing() -> void:
	# Schedule new keystrokes
	if _time >= _next_keystroke_time:
		_spawn_keystroke()
		_next_keystroke_time = _time + 1.0 / TYPE_SPEED + _typing_rng.randf_range(-0.08, 0.08)

	# Apply finger curls for typing fingers (index, middle, ring, pinky)
	for fname in TYPING_FINGERS:
		_apply_finger_curl(fname, _fingers_l, "l")
		_apply_finger_curl(fname, _fingers_r, "r")

	# Thumbs: reduced rest curl, occasional spacebar press
	_apply_thumb_curl(_fingers_l, "l")
	_apply_thumb_curl(_fingers_r, "r")

	# Clean up finished keystrokes
	var i := _active_keystrokes.size() - 1
	while i >= 0:
		if _time - float(_active_keystrokes[i]["start_time"]) > TYPE_PRESS_DUR:
			_active_keystrokes.remove_at(i)
		i -= 1

	# Hand micro-drift (subtle lateral noise)
	_animate_hand_drift()


func _apply_finger_curl(fname: String, fingers: Dictionary, side: String) -> void:
	var indices: Array = fingers[fname]
	var curl := TYPE_CURL_REST

	# Check if this finger is actively pressing a key
	for ks in _active_keystrokes:
		if ks["finger"] == fname and ks["side"] == side:
			var elapsed: float = _time - float(ks["start_time"])
			var progress: float = elapsed / TYPE_PRESS_DUR
			if progress < 0.5:
				curl = lerpf(TYPE_CURL_REST, TYPE_CURL_PRESS, progress * 2.0)
			else:
				curl = lerpf(TYPE_CURL_PRESS, TYPE_CURL_REST, (progress - 0.5) * 2.0)
			break  # only one active keystroke per finger

	for joint_idx: int in indices:
		if joint_idx >= 0:
			var base: Quaternion = _init_rot[joint_idx]
			skeleton.set_bone_pose_rotation(joint_idx,
				base * Quaternion(Vector3.RIGHT, curl))


func _apply_thumb_curl(fingers: Dictionary, side: String) -> void:
	var indices: Array = fingers["thumb"]
	var curl := TYPE_CURL_REST * 0.5  # thumbs less curled at rest

	for ks in _active_keystrokes:
		if ks["finger"] == "thumb" and ks["side"] == side:
			var elapsed: float = _time - float(ks["start_time"])
			var progress: float = elapsed / TYPE_PRESS_DUR
			if progress < 0.5:
				curl = lerpf(TYPE_CURL_REST * 0.5, TYPE_CURL_PRESS, progress * 2.0)
			else:
				curl = lerpf(TYPE_CURL_PRESS, TYPE_CURL_REST * 0.5, (progress - 0.5) * 2.0)
			break

	for joint_idx: int in indices:
		if joint_idx >= 0:
			var base: Quaternion = _init_rot[joint_idx]
			skeleton.set_bone_pose_rotation(joint_idx,
				base * Quaternion(Vector3.RIGHT, curl))


func _spawn_keystroke() -> void:
	# Pick a random finger (including occasional thumb for spacebar)
	var all_fingers: PackedStringArray = ["index", "middle", "ring", "pinky", "thumb"]
	var finger: String = all_fingers[_typing_rng.randi_range(0, all_fingers.size() - 1)]
	# 60% right hand, 40% left
	var side := "r" if _typing_rng.randf() < 0.6 else "l"
	_active_keystrokes.append({
		"finger": finger,
		"side": side,
		"start_time": _time,
	})


func _animate_hand_drift() -> void:
	var t := _time * 0.3
	if _bone_hand_l >= 0:
		var base: Quaternion = _init_rot[_bone_hand_l]
		var sit := Quaternion(Vector3.RIGHT, SIT_HAND_ANGLE)
		var drift := Quaternion(Vector3.UP, _noise.get_noise_2d(t, 1200.0) * HAND_DRIFT)
		skeleton.set_bone_pose_rotation(_bone_hand_l, base * sit * drift)
	if _bone_hand_r >= 0:
		var base: Quaternion = _init_rot[_bone_hand_r]
		var sit := Quaternion(Vector3.RIGHT, SIT_HAND_ANGLE)
		var drift := Quaternion(Vector3.UP, _noise.get_noise_2d(t, 1300.0) * HAND_DRIFT)
		skeleton.set_bone_pose_rotation(_bone_hand_r, base * sit * drift)


# =============================================================================
# Helpers
# =============================================================================

## Apply a single-axis rotation offset to a bone (base * Quaternion(axis, angle)).
func _set_bone_offset(bone_idx: int, axis: Vector3, angle: float) -> void:
	if bone_idx >= 0:
		var base: Quaternion = _init_rot[bone_idx]
		skeleton.set_bone_pose_rotation(bone_idx,
			base * Quaternion(axis, angle))
