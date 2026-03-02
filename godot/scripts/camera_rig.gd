class_name CameraRig
extends Node3D
## Isometric camera with orbit controls.
## Left-drag: rotate (yaw horizontal, pitch vertical).
## Right-drag or two-finger: pan.
## Scroll: zoom.

const CAMERA_DISTANCE: float = 8.0
const ROTATION_SPEED: float = 0.005
const ZOOM_STEP: float = 0.3
const MIN_SIZE: float = 2.5
const MAX_SIZE: float = 10.0
const MIN_PITCH_DEG: float = 10.0   # almost horizontal
const MAX_PITCH_DEG: float = 85.0   # almost top-down
const INITIAL_PITCH_DEG: float = 35.0
const INITIAL_YAW_DEG: float = 45.0  # diagonal view into room

var _target_yaw: float = deg_to_rad(INITIAL_YAW_DEG)
var _target_pitch: float = deg_to_rad(INITIAL_PITCH_DEG)
var _is_dragging: bool = false

var _pivot: Node3D   # rotates yaw (Y axis)
var _pitch: Node3D   # rotates pitch (X axis)
var _camera: Camera3D


func _ready() -> void:
	# Pivot at room center, slightly above floor
	position = Vector3(0.0, 1.0, 0.0)

	_pivot = Node3D.new()
	_pivot.name = "Pivot"
	add_child(_pivot)

	_pitch = Node3D.new()
	_pitch.name = "PitchArm"
	_pivot.add_child(_pitch)

	_camera = Camera3D.new()
	_camera.name = "Camera"
	_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	_camera.size = 5.0
	_camera.near = 0.1
	_camera.far = 50.0
	# Camera sits behind on Z, pitch arm rotates it up/down
	_camera.position = Vector3(0.0, 0.0, CAMERA_DISTANCE)
	_pitch.add_child(_camera)

	# Apply initial orientation
	_pivot.rotation.y = _target_yaw
	_pitch.rotation.x = -_target_pitch  # negative = tilt upward


func _unhandled_input(event: InputEvent) -> void:
	# Touch drag
	if event is InputEventScreenDrag:
		_target_yaw -= event.relative.x * ROTATION_SPEED
		_target_pitch += event.relative.y * ROTATION_SPEED
		_target_pitch = clamp(_target_pitch, deg_to_rad(MIN_PITCH_DEG), deg_to_rad(MAX_PITCH_DEG))

	# Mouse buttons
	elif event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT:
			_is_dragging = mb.pressed
		elif mb.button_index == MOUSE_BUTTON_WHEEL_UP and mb.pressed:
			_camera.size = max(MIN_SIZE, _camera.size - ZOOM_STEP)
		elif mb.button_index == MOUSE_BUTTON_WHEEL_DOWN and mb.pressed:
			_camera.size = min(MAX_SIZE, _camera.size + ZOOM_STEP)

	# Mouse drag
	elif event is InputEventMouseMotion and _is_dragging:
		_target_yaw -= event.relative.x * ROTATION_SPEED
		_target_pitch += event.relative.y * ROTATION_SPEED
		_target_pitch = clamp(_target_pitch, deg_to_rad(MIN_PITCH_DEG), deg_to_rad(MAX_PITCH_DEG))


func _process(delta: float) -> void:
	var t := delta * 5.0
	_pivot.rotation.y = lerp_angle(_pivot.rotation.y, _target_yaw, t)
	_pitch.rotation.x = lerp_angle(_pitch.rotation.x, -_target_pitch, t)
