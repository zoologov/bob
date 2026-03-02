shader_type spatial;

uniform vec3 base_color : source_color = vec3(0.85, 0.75, 0.65);
uniform vec3 shadow_color : source_color = vec3(0.55, 0.45, 0.4);
uniform float shadow_threshold : hint_range(-1.0, 1.0) = 0.0;
uniform float shadow_smoothness : hint_range(0.0, 0.5) = 0.05;

void fragment() {
	ALBEDO = base_color;
	METALLIC = 0.0;
	ROUGHNESS = 1.0;
}

void light() {
	float NdotL = dot(NORMAL, LIGHT);
	float intensity = smoothstep(
		shadow_threshold - shadow_smoothness,
		shadow_threshold + shadow_smoothness,
		NdotL
	);
	vec3 shaded = mix(shadow_color, base_color, intensity);
	DIFFUSE_LIGHT += shaded * ATTENUATION * LIGHT_COLOR;
	SPECULAR_LIGHT = vec3(0.0);
}
