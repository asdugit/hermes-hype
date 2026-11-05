// nature kit · shared GLSL chunks (WebGL2 / GLSL ES 3.0 via three.js ShaderMaterial).

export const NOISE = /* glsl */`
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float hash13(vec3 p3){ p3 = fract(p3 * 0.1031); p3 += dot(p3, p3.zyx + 31.32); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  float a = hash12(i), b = hash12(i + vec2(1.0, 0.0)), c = hash12(i + vec2(0.0, 1.0)), d = hash12(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p, int oct){
  float s = 0.0, a = 0.5, n = 0.0;
  mat2 r = mat2(0.8, -0.6, 0.6, 0.8);
  for (int i = 0; i < 7; i++) { if (i >= oct) break; s += a * vnoise(p); n += a; p = r * p * 2.03 + 17.1; a *= 0.5; }
  return s / n;
}
float billow(vec2 p, int oct){
  float s = 0.0, a = 0.5, n = 0.0;
  mat2 r = mat2(0.8, -0.6, 0.6, 0.8);
  for (int i = 0; i < 7; i++) { if (i >= oct) break; s += a * (1.0 - abs(vnoise(p) * 2.0 - 1.0)); n += a; p = r * p * 2.07 + 5.3; a *= 0.5; }
  return s / n;
}
`;

/** Display transform used by every final pass: soft shoulder (keeps authored pastels), sRGB encode, dither. */
export const DISPLAY = /* glsl */`
vec3 shoulder(vec3 x){
  const float k = 0.72;
  vec3 over = max(x - k, 0.0);
  return min(x, vec3(k)) + (1.0 - k) * (1.0 - exp(-over / (1.0 - k)));
}
vec3 toSRGB(vec3 c){ c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
`;
