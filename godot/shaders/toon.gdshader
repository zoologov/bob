shader_type spatial;
render_mode unshaded, cull_disabled;

uniform vec3 base_color : source_color = vec3(0.85, 0.75, 0.65);
uniform vec3 shadow_color : source_color = vec3(0.55, 0.45, 0.4);
uniform vec3 light_dir = vec3(-0.5, -0.6, -0.5);  // world-space light direction (toward light)
uniform float shadow_threshold : hint_range(-1.0, 1.0) = 0.1;
uniform float shadow_smoothness : hint_range(0.0, 0.5) = 0.05;

void fragment() {
	// Transform light direction to view space
	vec3 light_vs = normalize((VIEW_MATRIX * vec4(normalize(light_dir), 0.0)).xyz);

	// Flip normal if it faces away from camera (fixes inverted normals)
	vec3 n = NORMAL;
	if (!FRONT_FACING) {
		n = -n;
	}

	float NdotL = dot(n, light_vs);
	float intensity = smoothstep(
		shadow_threshold - shadow_smoothness,
		shadow_threshold + shadow_smoothness,
		NdotL
	);

	ALBEDO = mix(shadow_color, base_color, intensity);
}
