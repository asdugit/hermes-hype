// nature kit · mountains: 2–3 hazy layered ridges as cylinder sections around the camera's base position.
// Ridge shapes are 1D fbm in the fragment shader (soft anti-aliased edge), with aerial perspective toward the
// horizon haze, a warm rim on sun-facing ridgelines and faint painterly strata. Real geometry → true parallax.
import { NOISE } from './glsl.js';
import { lin3 } from './presets.js';

const D2R = Math.PI / 180;

const VS = /* glsl */`
varying vec3 vW; varying vec2 vUv;
void main(){ vUv = uv; vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`;

const FS = /* glsl */`
precision highp float;
varying vec3 vW; varying vec2 vUv;
uniform vec3 base; uniform float radius, elLo, elHi, seed, rough;
uniform vec3 col, haze, rimCol, sunDir; uniform float hazeAmt, layer;
${NOISE}
float ridge(float az){
  float f = 2.6 + layer * 2.2;
  float n = smoothstep(0.25, 0.8, fbm(vec2(az * f + seed, seed * 0.37), 4));
  float r = 1.0 - abs(vnoise(vec2(az * f * 2.2 + seed * 1.7, 2.0)) * 2.0 - 1.0);
  return clamp(mix(n, n * 0.8 + r * r * 0.25, rough), 0.0, 1.0);
}
void main(){
  vec3 rel = vW - base;
  float az = atan(rel.x, -rel.z);
  float el = atan(rel.y, length(rel.xz));
  float h = mix(elLo, elHi, ridge(az));
  float dh = (mix(elLo, elHi, ridge(az + 0.004)) - h) / 0.004;
  float aa = fwidth(el) * 1.2;
  float a = 1.0 - smoothstep(h - aa, h + aa, el);
  if (a <= 0.001) discard;
  float depthIn = clamp((h - el) / max(elHi - elLo, 1e-4), 0.0, 1.0);
  // fake slope normal from the ridge derivative → sun-facing slopes a touch lighter
  vec2 n2 = normalize(vec2(-dh, 1.0));
  float sunAz = atan(sunDir.x, -sunDir.z);
  float facing = clamp(n2.x * sign(sunAz - az) * 0.8 + 0.2, 0.0, 1.0);
  vec3 c = col * (0.92 + 0.16 * facing);
  float strata = fbm(vec2(az * 40.0 + seed, el * 900.0), 3);
  c *= 0.95 + 0.08 * strata;
  // aerial perspective: base of the layer dissolves into haze
  c = mix(c, haze, clamp(hazeAmt + depthIn * 0.35, 0.0, 1.0));
  // warm rim on the ridge line, strongest toward the sun
  float rim = exp(-(h - el) / max(aa * 3.0, 1e-5)) * exp(-abs(az - sunAz) / 0.6);
  c += rimCol * rim * 0.55;
  gl_FragColor = vec4(c, a);
}`;

/**
 * Build mountain layers. opts: {preset, base:[x,y,z] camera base, azMin, azMax (deg), seed}.
 * Returns {group, update(t)}.
 */
export function makeMountains(THREE, opts) {
  const P = opts.preset, group = new THREE.Group();
  const radii = [2600, 1300, 620, 300];
  const hazeAmts = [0.48, 0.34, 0.2, 0.14];
  const rims = lin3(P.sun.glow);
  P.mountains.forEach((m, i) => {
    const R = radii[i] || 400 + i * 300;
    const elHi = m.el[1] * D2R, elLo = m.el[0] * D2R;
    const top = Math.tan(elHi * 1.3) * R + 10, bottom = -40;
    const azMin = (opts.azMin - 15) * D2R, azMax = (opts.azMax + 15) * D2R;
    const geo = new THREE.CylinderGeometry(R, R, top - bottom, 192, 1, true, Math.PI - azMax, azMax - azMin);
    geo.translate(0, (top + bottom) / 2, 0);
    const mat = new THREE.ShaderMaterial({
      vertexShader: VS, fragmentShader: FS, side: THREE.DoubleSide, transparent: true, depthWrite: true,
      extensions: { derivatives: true },
      uniforms: {
        base: { value: new THREE.Vector3(...opts.base) }, radius: { value: R }, elLo: { value: elLo }, elHi: { value: elHi },
        seed: { value: (opts.seed % 53) * 1.37 + i * 11.3 }, rough: { value: 0.2 + 0.12 * i },
        col: { value: new THREE.Color(...lin3(m.col)) }, haze: { value: new THREE.Color(...lin3(P.haze)) },
        rimCol: { value: new THREE.Color(...rims) }, sunDir: { value: opts.sunDir }, hazeAmt: { value: hazeAmts[i] ?? 0.1 }, layer: { value: i },
      },
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(opts.base[0], 0, opts.base[2]);
    mesh.renderOrder = -90 + i; mesh.frustumCulled = false;
    group.add(mesh);
  });
  return { group, update() {} };
}
