extends Node2D
## 2.5D Parallax Scene — loads depth-separated PNG layers and animates camera breathing.
##
## Bead: bob-1ao
## Layers are loaded from res://assets/parallax/ at runtime.
## Camera breathing: sinusoidal ±2px shift creates parallax depth illusion.

# --- Configuration ---

## Layer files (ordered far → near) and their motion_scale values.
## NOTE: Currently all layers use motion_scale=1.0 to verify alignment.
## True parallax requires: background-only layers (depth split) + Bob as separate sprite.
## Bob spans multiple depth bands, so splitting BY DEPTH tears him apart.
## Proper fix: generate background WITHOUT Bob, depth-split that, overlay Bob separately.
const LAYERS: Array[Dictionary] = [
	{"file": "layer_0_far.png", "motion_scale": Vector2(0.97, 0.97)},
	{"file": "layer_1_mid.png", "motion_scale": Vector2(0.99, 0.99)},
	{"file": "layer_2_near.png", "motion_scale": Vector2(1.0, 1.0)},
	{"file": "layer_3_foreground.png", "motion_scale": Vector2(1.01, 1.01)},
]

const LAYER_DIR := "res://assets/parallax/"

## Camera breathing amplitude in pixels (±)
## Larger values = more visible parallax between layers
const BREATHING_AMPLITUDE := Vector2(12.0, 6.0)
const BREATHING_PERIOD := 6.0
const BREATHING2_AMPLITUDE := Vector2(4.0, 2.0)
const BREATHING2_PERIOD := 10.0

# --- State ---
var _camera: Camera2D
var _time: float = 0.0


func _ready() -> void:
	# Camera FIRST — ParallaxBackground needs it to exist
	_create_camera()
	_create_parallax_layers()
	print("Parallax scene ready: %d layers loaded" % LAYERS.size())


func _process(delta: float) -> void:
	_time += delta
	_update_camera_breathing()


func _create_parallax_layers() -> void:
	var parallax_bg := ParallaxBackground.new()
	parallax_bg.name = "ParallaxBG"
	# Ensure parallax renders on same canvas layer as rest of scene
	add_child(parallax_bg)

	# Debug: viewport info
	var vp_size: Vector2 = get_viewport().get_visible_rect().size
	print("  Viewport size: ", vp_size)

	for i in range(LAYERS.size()):
		var layer_info: Dictionary = LAYERS[i]
		var file_path: String = LAYER_DIR + layer_info["file"]

		# Load texture at runtime
		var texture := _load_texture(file_path)
		if not texture:
			push_warning("Failed to load layer: " + file_path)
			continue

		# Create ParallaxLayer
		var p_layer := ParallaxLayer.new()
		p_layer.name = "Layer_%d" % i
		p_layer.motion_scale = layer_info["motion_scale"]
		parallax_bg.add_child(p_layer)

		# Create Sprite2D inside the layer
		var sprite := Sprite2D.new()
		sprite.name = "Sprite"
		sprite.texture = texture
		sprite.centered = true
		# Scale sprite to fill viewport
		var tex_size: Vector2 = Vector2(texture.get_width(), texture.get_height())
		var scale_factor: float = maxf(
			vp_size.x / tex_size.x,
			vp_size.y / tex_size.y
		)
		sprite.scale = Vector2(scale_factor, scale_factor)

		p_layer.add_child(sprite)

		print("  Layer %d: %s (%dx%d, format=%d, motion_scale=%.1f, scale=%.2f)" % [
			i, layer_info["file"],
			texture.get_width(), texture.get_height(),
			texture.get_image().get_format() if texture.get_image() else -1,
			layer_info["motion_scale"].x, scale_factor
		])


func _create_camera() -> void:
	_camera = Camera2D.new()
	_camera.name = "Camera"
	_camera.position = Vector2.ZERO
	add_child(_camera)
	_camera.make_current()
	print("  Camera created at ", _camera.position)


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

	# Debug: check if image has content
	var has_alpha: bool = img.detect_alpha() != Image.ALPHA_NONE
	print("    Loaded: %s (%dx%d, alpha=%s)" % [
		path.get_file(), img.get_width(), img.get_height(), has_alpha
	])

	var tex := ImageTexture.create_from_image(img)
	return tex
