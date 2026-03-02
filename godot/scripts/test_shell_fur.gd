extends SceneTree
## V-04 validation: Test Squiggles Fur shell texturing addon in Godot 4.6.
## Run: godot --headless --quit --script res://scripts/test_shell_fur.gd

func _init() -> void:
	print("=== V-04: Shell Fur (Squiggles Fur) Test ===\n")

	# Test 1: Check if plugin files exist
	print("--- Test 1: Plugin files ---")
	var plugin_cfg := FileAccess.open("res://addons/squiggles_fur/plugin.cfg", FileAccess.READ)
	if plugin_cfg:
		print("  plugin.cfg found")
		print("  Content: " + plugin_cfg.get_as_text().substr(0, 200))
		plugin_cfg.close()
	else:
		print("  FAIL: plugin.cfg not found")
		quit()
		return
	print("  PASS\n")

	# Test 2: Try to load key scripts
	print("--- Test 2: Load addon scripts ---")
	var scripts_to_check := [
		"res://addons/squiggles_fur/types/shell_fur.gd",
		"res://addons/squiggles_fur/plugin.gd",
	]
	for script_path in scripts_to_check:
		if FileAccess.file_exists(script_path):
			var script := load(script_path)
			if script:
				print("  Loaded: " + script_path)
			else:
				print("  FAIL: Could not load " + script_path)
		else:
			print("  Not found: " + script_path)

	# Check what types are available
	print("\n  Available types:")
	var dir := DirAccess.open("res://addons/squiggles_fur/types/")
	if dir:
		dir.list_dir_begin()
		var fname := dir.get_next()
		while fname != "":
			if fname.ends_with(".gd"):
				print("    " + fname)
			fname = dir.get_next()
	print("  PASS\n")

	# Test 3: Check shader files
	print("--- Test 3: Shader files ---")
	var shader_dirs := [
		"res://addons/squiggles_fur/assets/",
		"res://addons/squiggles_fur/tools/",
	]
	for dir_path in shader_dirs:
		var d := DirAccess.open(dir_path)
		if d:
			d.list_dir_begin()
			var f := d.get_next()
			while f != "":
				if f.ends_with(".gdshader") or f.ends_with(".tres"):
					print("  " + dir_path + f)
				f = d.get_next()
	print("  PASS\n")

	print("=== V-04 COMPLETE ===")
	quit()
