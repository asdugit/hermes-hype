// nature kit · terrain: rolling meadow ground (analytic height field shared with JS placement) painted in the
// fragment shader: grass patches, sun/back light, travelling wind sheen, colour-patched flower dabs with
// footprint-aware LOD (no shimmer), and aerial perspective into the horizon haze.
import { NOISE } from './glsl.js';
import { lin3 } from './presets.js';
import { terrainHeight } from './math.js';

const VS = /* glsl */`
varying vec3 vW; varying vec3 vN;
void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal); gl_Position = projectionMatrix * viewMatrix * w; }`;

const FS = /* glsl */`
precision highp float;
varying vec3 vW; varying vec3 vN;
uniform vec3 gShadow, gBase, gLit, gTip, lightCol, ambCol, haze, sunDir;
uniform vec3 fCol[6]; uniform float fW[6];
uniform float fogDensity, t, backlight, flowerAmt;
uniform vec2 windDir;
${NOISE}
vec3 pickFlower(float r){
  float acc = 0.0; vec3 c = fCol[0];
  for (int i = 0; i < 6; i++) { acc += fW[i]; if (r <= acc) { c = fCol[i]; break; } }
  return c;
}
float dots(vec2 p, float cell, float rad, out vec3 dc, float patchSeed){
  vec2 g = p / cell; vec2 c = floor(g); vec2 f = fract(g) - 0.5;
  float h = hash12(c + patchSeed);
  vec2 o = (vec2(hash12(c + 3.7), hash12(c + 9.1)) - 0.5) * 0.55;
  float big = fbm(c * cell * 0.018 + patchSeed, 2);
  dc = pickFlower(fract(big * 2.7 + h * 0.35));
  return smoothstep(rad, rad * 0.55, length(f - o)) * step(0.22, h);
}
void main(){
  vec3 n = normalize(vN);
  vec3 V = normalize(cameraPosition - vW);
  float dist = length(cameraPosition - vW);
  vec2 xz = vW.xz;
  float patchN = fbm(xz * 0.045, 3);
  float lam = clamp(dot(n, sunDir) * 0.5 + 0.5, 0.0, 1.0);
  vec3 g = mix(gShadow, gBase, smoothstep(0.15, 0.65, lam));
  g = mix(g, gLit, smoothstep(0.35, 0.95, lam) * (0.45 + 0.55 * patchN));
  g *= 0.86 + 0.28 * fbm(xz * 0.9, 2);
  // wind sheen: bright bands rolling across the grass
  float wv = sin(dot(xz, windDir) * 0.16 - t * 1.35 + fbm(xz * 0.03, 2) * 7.0);
  g = mix(g, gTip, smoothstep(0.55, 1.0, wv) * 0.35);
  // back light (sun ahead) → glowing tips
  float bl = pow(max(dot(-V, sunDir), 0.0), 5.0) * backlight;
  g += gTip * bl * 0.35;
  // flower dabs at two scales, faded by footprint so distant rows become a smooth tint
  vec2 fw = fwidth(xz);
  float foot = max(fw.x, fw.y);
  vec3 dc1, dc2;
  float d1 = dots(xz, 0.32, 0.30, dc1, 1.0);
  float d2 = dots(xz + 7.3, 0.9, 0.22, dc2, 5.0);
  float lod1 = 1.0 - smoothstep(0.06, 0.22, foot);
  float lod2 = 1.0 - smoothstep(0.2, 0.7, foot);
  float mask = smoothstep(0.22, 0.52, fbm(xz * 0.07 + 3.0, 3)) * flowerAmt;
  vec3 avg = mix(dc1, dc2, 0.5);
  vec3 col = g;
  col = mix(col, avg * mix(ambCol, lightCol, lam) * 1.05, mask * (1.0 - lod2) * 0.28);
  col = mix(col, dc1 * mix(ambCol, lightCol, 0.7 + 0.3 * lam), d1 * lod1 * mask);
  col = mix(col, dc2 * mix(ambCol, lightCol, 0.7 + 0.3 * lam), d2 * lod2 * mask * 0.85);
  col *= mix(ambCol, lightCol, 0.55 + 0.45 * lam) * 1.05;
  float fog = 1.0 - exp(-dist * fogDensity * 0.55);
  col = mix(col, haze, fog);
  gl_FragColor = vec4(col, 1.0);
}`;

/**
 * Build the terrain mesh. opts: {preset, hills, xHalf, dNear, dFar, nx, nz, flowerAmt}.
 */
export function makeTerrain(THREE, opts) {
  const P = opts.preset;
  const nx = opts.nx || 160, nz = opts.nz || 160, xHalf = opts.xHalf || 420, dNear = opts.dNear ?? -6, dFar = opts.dFar || 700;
  const pos = [], idx = [];
  for (let j = 0; j <= nz; j++) {
    const v = j / nz, d = dNear + (dFar - dNear) * Math.pow(v, 2.2);
    for (let i = 0; i <= nx; i++) {
      const u = i / nx, s = (u * 2 - 1), x = Math.sign(s) * Math.pow(Math.abs(s), 1.6) * xHalf * (0.25 + 0.75 * v + 0.2);
      pos.push(x, terrainHeight(x, -d, opts), -d);
    }
  }
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const a = j * (nx + 1) + i, b = a + 1, c = a + nx + 1, d = c + 1;
    idx.push(a, b, c, b, d, c);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx); geo.computeVertexNormals();
  const fl = Object.entries(P.flowers).slice(0, 6);
  const tot = fl.reduce((s, [, w]) => s + w, 0);
  const FL = opts.flowerColors;
  const fCol = new Array(6).fill(0).map((_, i) => new THREE.Color(...lin3(FL[(fl[i] || fl[0])[0]] || '#ffffff')));
  const fW = new Array(6).fill(0).map((_, i) => (fl[i] ? fl[i][1] / tot : 0));
  const c3 = (h) => new THREE.Color(...lin3(h));
  const uniforms = {
    gShadow: { value: c3(P.grass.shadow) }, gBase: { value: c3(P.grass.base) }, gLit: { value: c3(P.grass.lit) }, gTip: { value: c3(P.grass.tip) },
    lightCol: { value: c3(P.light) }, ambCol: { value: c3(P.ambient) }, haze: { value: c3(P.haze) }, sunDir: { value: opts.sunDir },
    fCol: { value: fCol }, fW: { value: fW }, fogDensity: { value: P.fogDensity }, t: { value: 0 }, backlight: { value: P.backlight },
    flowerAmt: { value: opts.flowerAmt ?? 1 }, windDir: { value: new THREE.Vector2(0.86, -0.5) },
  };
  const mat = new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: FS, uniforms, extensions: { derivatives: true } });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.frustumCulled = false;
  return { mesh, update(t) { uniforms.t.value = t; } };
}
