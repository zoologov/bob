extends Node2D
## 2.5D Scene — single unified image + camera breathing for atmosphere.
##
## Bead: bob-1ao
## Single Kontext-generated scene (Bob + environment as one image).
## Camera breathing creates subtle "alive" motion.
## Bob is NOT separated — the whole scene moves together.

# --- Configuration ---
const SCENE_FILE := "bob_scene_full.png"
const LAYER_DIR := "res://assets/parallax/"

## Camera breathing amplitude in pixels (±)
const BREATHING_AMPLITUDE := Vector2(10.0, 5.0)
const BREATHING_PERIOD := 6.0
const BREATHING2_AMPLITUDE := Vector2(3.0, 1.5)
const BREATHING2_PERIOD := 10.0

# --- State ---
var _camera: Camera2D
var _time: float = 0.0


func _ready() -> void:
	_create_camera()
	_create_scene()
	print("Scene ready")


func _process(delta: float) -> void:
	_time += delta
	_update_camera_breathing()


func _create_scene() -> void:
	var vp_size: Vector2 = get_viewport().get_visible_rect().size

	var texture := _load_texture(LAYER_DIR + SCENE_FILE)
	if not texture:
		push_error("Failed to load scene!")
		return

	var sprite := Sprite2D.new()
	sprite.name = "Scene"
	sprite.texture = texture
	sprite.centered = true
	# Scale to fill viewport + margin for breathing movement
	var tex_size := Vector2(texture.get_width(), texture.get_height())
	var scale_factor: float = maxf(vp_size.x / tex_size.x, vp_size.y / tex_size.y) * 1.10
	sprite.scale = Vector2(scale_factor, scale_factor)
	add_child(sprite)

	print("  Scene: %s (%dx%d, scale=%.2f)" % [
		SCENE_FILE, texture.get_width(), texture.get_height(), scale_factor
	])


func _create_camera() -> void:
	_camera = Camera2D.new()
	_camera.name = "Camera"
	_camera.position = Vector2.ZERO
	add_child(_camera)
	_camera.make_current()


func _update_camera_breathing() -> void:
	if not _camera:
		return
	var phase1: float = _time * TAU / BREATHING_PERIOD
	var offset1 := Vector2(
		sin(phase1) * BREATHING_AMPLITUDE.x,
		sin(phase1 * 0.7) * BREATHING_AMPLITUDE.y
	)
	var phase2: float = _time * TAU / BREATHING2_PERIOD
	var offset2 := Vector2(
		sin(phase2) * BREATHING2_AMPLITUDE.x,
		cos(phase2 * 0.6) * BREATHING2_AMPLITUDE.y
	)
	_camera.position = offset1 + offset2


func _load_texture(path: String) -> ImageTexture:
	var global_path: String = ProjectSettings.globalize_path(path)
	var img := Image.new()
	var err := img.load(global_path)
	if err != OK:
		push_error("Cannot load image: %s (error=%d)" % [global_path, err])
		return null
	print("    Loaded: %s (%dx%d)" % [path.get_file(), img.get_width(), img.get_height()])
	var tex := ImageTexture.create_from_image(img)
	return tex
