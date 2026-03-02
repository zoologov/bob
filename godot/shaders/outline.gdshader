shader_type spatial;
render_mode unshaded, cull_front;

uniform float outline_width : hint_range(0.0, 0.1) = 0.02;
uniform vec3 outline_color : source_color = vec3(0.15, 0.12, 0.1);

void vertex() {
	VERTEX += NORMAL * outline_width;
}

void fragment() {
	ALBEDO = outline_color;
}
