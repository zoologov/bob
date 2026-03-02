shader_type spatial;
render_mode unshaded, cull_disabled;

uniform vec3 base_color : source_color = vec3(0.85, 0.75, 0.65);
uniform vec3 light_dir = vec3(-0.5, -0.6, -0.5);  // world-space light direction (toward light)
uniform float shadow_threshold : hint_range(-1.0, 1.0) = 0.1;
uniform float shadow_smoothness : hint_range(0.0, 0.5) = 0.05;
uniform float shadow_strength : hint_range(0.0, 1.0) = 0.4;
uniform sampler2D albedo_texture : source_color, filter_linear_mipmap;

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

	// Sample texture and tint with base_color
	vec4 tex_color = texture(albedo_texture, UV);
	vec3 color = tex_color.rgb * base_color;
	vec3 shadow = color * (1.0 - shadow_strength);

	ALBEDO = mix(shadow, color, intensity);
	ALPHA = tex_color.a;
	if (tex_color.a < 0.5) {
		discard;
	}
}
