// nature kit · instanced sprite systems sharing one painted atlas:
//   meadow  — ground-anchored cylindrical billboards (grass tufts + 9 flower species + framing blossoms), wind sway
//   petals  — free billboards drifting analytically (wrap inside camera-base lanes), tumbling, backlit
//   fireflies (night) — additive glowing motes with blink
// Depth of field per instance: thin-lens CoC → fractional level in the atlas's pre-blurred rows.
import { NOISE } from './glsl.js';
import { CELL, BLUR_LEVELS, KINDS, K } from './atlas.js';
import { lin3 } from './presets.js';
import { mulberry32, terrainHeight, clamp } from './math.js';

const COMMON = /* glsl */`
uniform sampler2D atlas; uniform float cols, rows;
uniform float focus, cocK, pxScale;
vec2 cellUV(float kind, float level, vec2 uv){
  uv = clamp(uv, 0.5 / ${CELL.toFixed(1)}, 1.0 - 0.5 / ${CELL.toFixed(1)});
  return vec2((kind + uv.x) / cols, 1.0 - (level + 1.0 - uv.y) / rows);
}
float blurLevel(float bc){
  float b0 = ${BLUR_LEVELS[1].toFixed(2)}, b1 = ${BLUR_LEVELS[2].toFixed(2)}, b2 = ${BLUR_LEVELS[3].toFixed(2)}, b3 = ${BLUR_LEVELS[4].toFixed(2)};
  if (bc < b0) return bc / b0;
  if (bc < b1) return 1.0 + (bc - b0) / (b1 - b0);
  if (bc < b2) return 2.0 + (bc - b1) / (b2 - b1);
  return min(3.0 + (bc - b2) / (b3 - b2), 4.0);
}
vec4 sampleSprite(float kind, float level, vec2 uv){
  float l0 = floor(level), l1 = min(l0 + 1.0, 4.0), f = level - l0;
  if (f < 0.1) return texture2D(atlas, cellUV(kind, l0, uv));
  if (f > 0.9) return texture2D(atlas, cellUV(kind, l1, uv));
  return mix(texture2D(atlas, cellUV(kind, l0, uv)), texture2D(atlas, cellUV(kind, l1, uv)), f);
}
`;

// ------------------------------------------------------------------ meadow

const MEADOW_VS = /* glsl */`
attribute vec3 iPos; attribute vec2 iScale; attribute float iKind; attribute vec3 iTint; attribute vec3 iStem; attribute vec3 iCentre;
attribute float iPhase; attribute float iFlip;
uniform float t, windAmp; uniform vec2 windDir; uniform vec3 shift;
varying vec2 vUv; varying float vLevel; varying vec3 vTint; varying vec3 vStem; varying vec3 vCentre; varying float vKind; varying float vDist; varying vec3 vW;
${COMMON}
void main(){
  vUv = vec2(iFlip > 0.0 ? uv.x : 1.0 - uv.x, uv.y);
  vec3 camR = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
  vec3 right = normalize(vec3(camR.x, 0.0, camR.z));
  float gph = dot(iPos.xz, windDir) * 0.16 - t * 1.35;
  float gust = smoothstep(0.2, 1.0, sin(gph));
  float h = position.y;
  float sway = iScale.y * windAmp * (0.05 * sin(t * 1.9 + iPhase + iPos.x * 0.35) + 0.035 * sin(t * 3.3 + iPhase * 1.7) + 0.13 * gust) * pow(h, 1.6);
  vec3 wp = iPos + shift + right * (position.x * iScale.x + sway) + vec3(0.0, h * iScale.y * (1.0 - 0.06 * gust * h), 0.0);
  vec4 mv = viewMatrix * vec4(wp, 1.0);
  float z = max(-mv.z, 0.05);
  float coc = cocK * abs(1.0 / z - 1.0 / focus);
  float spritePx = iScale.y * pxScale / z;
  vLevel = blurLevel(coc * ${CELL.toFixed(1)} / max(spritePx, 1.0));
  vTint = iTint; vStem = iStem; vCentre = iCentre; vKind = iKind; vDist = z; vW = wp;
  gl_Position = projectionMatrix * mv;
}`;

const MEADOW_FS = /* glsl */`
precision highp float;
varying vec2 vUv; varying float vLevel; varying vec3 vTint; varying vec3 vStem; varying vec3 vCentre; varying float vKind; varying float vDist; varying vec3 vW;
uniform vec3 lightCol, ambCol, haze, sunDir; uniform float fogDensity, backlight, opacity;
${COMMON}
void main(){
  vec4 s = sampleSprite(vKind, vLevel, vUv);
  s.a *= smoothstep(0.0, 0.1, vUv.x) * smoothstep(1.0, 0.9, vUv.x) * smoothstep(1.0, 0.93, vUv.y);
  if (s.a < 0.004) discard;
  vec3 col = s.r * vTint + s.g * vStem + s.b * vCentre;
  vec3 V = normalize(cameraPosition - vW);
  float lit = 0.55 + 0.45 * vUv.y;
  col *= mix(ambCol, lightCol, lit);
  float bl = pow(max(dot(-V, sunDir), 0.0), 3.0) * backlight;
  col += lightCol * bl * (0.35 * s.r * (1.0 - s.g) + 0.10 * s.g) * (0.4 + 0.6 * vUv.y);
  col = mix(col, haze, 1.0 - exp(-vDist * fogDensity));
  gl_FragColor = vec4(col, s.a * opacity);
}`;

/** Tiny 2D value noise for colour patches (JS). */
function vnoise2(x, y, seed) {
  const h = (i, j) => { let v = Math.sin(i * 127.1 + j * 311.7 + seed * 74.7) * 43758.5453; return v - Math.floor(v); };
  const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
  const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
  return (h(i, j) * (1 - u) + h(i + 1, j) * u) * (1 - v) + (h(i, j + 1) * (1 - u) + h(i + 1, j + 1) * u) * v;
}

// species → [height range m, palette keys]
const SPECIES = {
  daisy: [[0.42, 0.68], ['white', 'cream']], buttercup: [[0.32, 0.5], ['yellow', 'butter']],
  cosmos: [[0.55, 0.85], ['pink', 'rose', 'peach', 'white']], lupine: [[0.6, 0.95], ['lupine', 'lilac']],
  babysbreath: [[0.48, 0.75], ['white', 'cream']], poppy: [[0.42, 0.66], ['peach', 'coral']],
  lavender: [[0.5, 0.72], ['lilac', 'lupine']], clover: [[0.24, 0.36], ['pink', 'white']], seedhead: [[0.7, 1.0], ['_tip']],
};
// preset palette key → species that carry it
const BY_COLOUR = { white: ['daisy', 'babysbreath', 'cosmos'], cream: ['daisy', 'babysbreath'], yellow: ['buttercup'], butter: ['buttercup'],
  pink: ['cosmos', 'clover'], rose: ['cosmos'], peach: ['poppy', 'cosmos'], coral: ['poppy'], lilac: ['lavender', 'lupine'],
  lupine: ['lupine'], blue: ['lavender'] };

/**
 * Build the meadow. opts: {preset, flowerColors, hills, sunDir, counts:{field, fg, frame}, view:{tanH, tanV, base, travel},
 *   seed, focus, cocK, pxScale, atlas, wind}
 */
export function makeMeadow(THREE, opts) {
  const P = opts.preset, FC = opts.flowerColors, rnd = mulberry32((opts.seed * 31 + 7) >>> 0);
  const col = (k) => lin3(k === '_tip' ? P.grass.tip : k === '_lit' ? P.grass.lit : FC[k] || '#ffffff');
  const colourKeys = Object.entries(P.flowers);
  const totW = colourKeys.reduce((s, [, w]) => s + w, 0);
  const centreGold = lin3('#E9B53A'), centreDark = lin3('#3B2B2E');
  const stemA = lin3(P.grass.base), stemB = lin3(P.grass.lit), stemC = lin3(P.grass.shadow);
  const inst = [];
  const { base, tanH, travel } = opts.view;
  const pick = (r) => { let a = r * totW; for (const [k, w] of colourKeys) { a -= w; if (a <= 0) return k; } return colourKeys[0][0]; };

  function add(kindName, x, z, hgt, colourKey, extra = {}) {
    const y = terrainHeight(x, z, opts) - 0.03;
    const stemMix = rnd();
    const stem = stemA.map((v, i) => v * (1 - stemMix) + (stemMix < 0.5 ? stemC[i] : stemB[i]) * stemMix * 0.8 + v * 0.2 * stemMix);
    const tint = colourKey ? col(colourKey) : lin3(P.grass.tip);
    const jitter = 0.9 + rnd() * 0.2;
    inst.push({ kind: K[kindName], x, y, z, w: hgt * (extra.wmul || 1), h: hgt, tint: tint.map((v) => v * jitter), stem,
      centre: kindName === 'poppy' ? centreDark : centreGold, phase: rnd() * 6.283, flip: rnd() < 0.5 ? -1 : 1 });
  }

  // a) field: screen-uniform rows from 6.5 m to 240 m
  const dMin = 6.5, dMax = 240;
  for (let i = 0; i < (opts.counts.field || 0); i++) {
    const u = rnd();
    const d = 1 / (1 / dMin + Math.pow(u, 0.72) * (1 / dMax - 1 / dMin));
    const xs = (rnd() * 2 - 1) * (d * tanH * 1.18 + 2 + travel);
    const x = base[0] + xs, z = base[2] - d;
    const nx = vnoise2(x * 0.045, z * 0.045, opts.seed), grassy = vnoise2(x * 0.11 + 9, z * 0.11, opts.seed);
    if (rnd() < 0.40 + 0.25 * grassy + (d < 14 ? 0.3 * (1 - (d - dMin) / (14 - dMin)) : 0)) {
      { const g = rnd(); add(g < 0.68 ? 'grassA' : g < 0.93 ? 'grassB' : 'seedhead', x, z, (g < 0.93 ? 0.45 + rnd() * 0.5 : 0.5 + rnd() * 0.25), rnd() < 0.15 ? '_tip' : '_lit'); }
    } else {
      // colour patches: the low-frequency noise biases which palette colour grows here
      const ck = pick(clamp(nx * 0.75 + rnd() * 0.35));
      const sp = BY_COLOUR[ck] || ['daisy'];
      const s = sp[Math.floor(rnd() * sp.length)];
      const [hr] = SPECIES[s];
      add(s, x, z, hr[0] + rnd() * (hr[1] - hr[0]), ck);
    }
  }
  // b) foreground band 1.5–4.5 m, biased to the sides (frames the shot, keeps the centre clear)
  for (let i = 0; i < (opts.counts.fg || 0); i++) {
    const d = 1.6 + rnd() * 4.9;
    const side = rnd() < 0.5 ? -1 : 1;
    const xs = side * (0.42 + Math.pow(rnd(), 0.6) * 0.85) * d * tanH;
    const x = base[0] + xs, z = base[2] - d;
    if (rnd() < 0.55) add(rnd() < 0.7 ? 'grassA' : 'grassB', x, z, 0.75 + rnd() * 0.5, rnd() < 0.4 ? '_tip' : null);
    else { const ck = pick(rnd()); const sp = BY_COLOUR[ck] || ['daisy']; const s = sp[Math.floor(rnd() * sp.length)]; const [hr] = SPECIES[s]; add(s, x, z, (hr[0] + rnd() * (hr[1] - hr[0])) * 1.25, ck); }
  }
  // c) framing blossoms: big out-of-focus heads in the bottom corners (ref: Sotiya meadow, AoT)
  const frameKeys = ['pink', 'peach', 'white', 'yellow', 'pink', 'lilac'];
  for (let i = 0; i < (opts.counts.frame || 0); i++) {
    const side = i % 2 === 0 ? -1 : 1;
    const d = 1.35 + rnd() * 1.1;
    const xs = side * (0.66 + rnd() * 0.36) * d * tanH;
    const x = base[0] + xs, z = base[2] - d;
    const big = rnd() < 0.55 ? 'blossomBig' : 'daisyBig';
    const ck = big === 'daisyBig' ? (rnd() < 0.5 ? 'white' : 'yellow') : frameKeys[i % frameKeys.length];
    const hgt = 0.42 + rnd() * 0.26;
    const y = 0.78 + rnd() * 0.36;
    inst.push({ kind: K[big], x, y, z, w: hgt, h: hgt, tint: col(FC[ck] ? ck : 'pink'), stem: stemA, centre: centreGold,
      phase: rnd() * 6.283, flip: rnd() < 0.5 ? -1 : 1 });
  }
  // back-to-front relative to the base camera (static order is valid: the camera only drifts)
  inst.sort((a, b) => Math.hypot(b.x - base[0], b.z - base[2]) - Math.hypot(a.x - base[0], a.z - base[2]));

  const n = inst.length;
  const geo = new THREE.InstancedBufferGeometry();
  const q = new THREE.PlaneGeometry(1, 1); q.translate(0, 0.5, 0);
  geo.index = q.index; geo.setAttribute('position', q.getAttribute('position')); geo.setAttribute('uv', q.getAttribute('uv'));
  const A = (name, size, f) => { const arr = new Float32Array(n * size); inst.forEach((it, i) => f(it, arr, i * size)); geo.setAttribute(name, new THREE.InstancedBufferAttribute(arr, size)); };
  A('iPos', 3, (it, a, o) => { a[o] = it.x; a[o + 1] = it.y; a[o + 2] = it.z; });
  A('iScale', 2, (it, a, o) => { a[o] = it.w; a[o + 1] = it.h; });
  A('iKind', 1, (it, a, o) => { a[o] = it.kind; });
  A('iTint', 3, (it, a, o) => { a.set(it.tint, o); });
  A('iStem', 3, (it, a, o) => { a.set(it.stem, o); });
  A('iCentre', 3, (it, a, o) => { a.set(it.centre, o); });
  A('iPhase', 1, (it, a, o) => { a[o] = it.phase; });
  A('iFlip', 1, (it, a, o) => { a[o] = it.flip; });
  geo.instanceCount = n;
  const c3 = (h) => new THREE.Color(...lin3(h));
  const uniforms = {
    atlas: { value: opts.atlas.texture }, cols: { value: opts.atlas.cols }, rows: { value: opts.atlas.rows },
    focus: { value: opts.focus }, cocK: { value: opts.cocK }, pxScale: { value: opts.pxScale },
    t: { value: 0 }, windAmp: { value: opts.wind ?? 1 }, windDir: { value: new THREE.Vector2(0.86, -0.5) }, shift: { value: new THREE.Vector3() },
    lightCol: { value: c3(P.light) }, ambCol: { value: c3(P.ambient) }, haze: { value: c3(P.haze) }, sunDir: { value: opts.sunDir },
    fogDensity: { value: P.fogDensity }, backlight: { value: P.backlight }, opacity: { value: 1 },
  };
  const mat = new THREE.ShaderMaterial({ vertexShader: MEADOW_VS, fragmentShader: MEADOW_FS, uniforms, transparent: true, depthWrite: false, depthTest: true });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.frustumCulled = false; mesh.renderOrder = 20;
  return { mesh, count: n, uniforms, update(t, focus, shift) { uniforms.t.value = t; if (focus) uniforms.focus.value = focus; if (shift) uniforms.shift.value.set(...shift); } };
}

// ------------------------------------------------------------------ petals & fireflies

const PETAL_VS = /* glsl */`
attribute vec4 iA; attribute vec4 iB; attribute vec4 iC; attribute vec3 iTint;
// iA: lane x, lane y, depth, size · iB: vx, vy, flutterF, phase · iC: spin, tumble, kind, blink
uniform float t; uniform vec3 bOrigin, bRight, bUp, bFwd; uniform float tanH, tanV, travel, fireflies;
uniform vec3 sunDir;
varying vec2 vUv; varying float vLevel; varying vec3 vTint; varying float vKind; varying float vDist; varying float vFace; varying float vBlink; varying vec3 vW;
${COMMON}
void main(){
  float d = iA.z;
  float hx = d * tanH * 1.25 + 1.5 + travel, hy = d * tanV * 1.25 + 1.0;
  float x = iA.x * hx + iB.x * t + sin(t * iB.z + iB.w) * 0.35 * iA.w * 8.0;
  float y = iA.y * hy + iB.y * t + sin(t * iB.z * 1.3 + iB.w * 2.1) * 0.25 * iA.w * 8.0;
  x = mod(x + hx, 2.0 * hx) - hx;
  y = mod(y + hy, 2.0 * hy) - hy;
  if (fireflies > 0.5) y = mod(y + hy, 2.0 * hy) * 0.18 - 0.3;
  float zj = sin(t * iB.z * 0.7 + iB.w) * 0.15 * d * 0.1;
  vec3 c = bOrigin + bFwd * (d + zj) + bRight * x + bUp * y;
  float ang = iC.x * t + iB.w * 3.0;
  float tum = cos(iC.y * t + iB.w);
  vFace = tum;
  vec2 q = position.xy;
  q.x *= max(abs(tum), 0.18);
  q = mat2(cos(ang), sin(ang), -sin(ang), cos(ang)) * q;
  vec3 camR = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
  vec3 camU = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
  vec3 wp = c + (camR * q.x + camU * q.y) * iA.w;
  vec4 mv = viewMatrix * vec4(wp, 1.0);
  float z = max(-mv.z, 0.05);
  float coc = cocK * abs(1.0 / z - 1.0 / focus);
  float px = iA.w * pxScale / z;
  vLevel = min(blurLevel(coc * ${CELL.toFixed(1)} * 0.35 / max(px, 1.0)), 3.0);
  vUv = uv; vTint = iTint; vKind = iC.z; vDist = z; vW = wp;
  vBlink = fireflies > 0.5 ? pow(0.5 + 0.5 * sin(t * (1.3 + iC.w * 2.0) + iB.w * 5.0), 6.0) : 1.0;
  gl_Position = projectionMatrix * mv;
}`;

const PETAL_FS = /* glsl */`
precision highp float;
varying vec2 vUv; varying float vLevel; varying vec3 vTint; varying float vKind; varying float vDist; varying float vFace; varying float vBlink; varying vec3 vW;
uniform vec3 lightCol, ambCol, haze, sunDir; uniform float fogDensity, backlight, fireflies, opacity;
${COMMON}
void main(){
  vec4 s = sampleSprite(vKind, vLevel, vUv);
  if (s.a < 0.004) discard;
  if (fireflies > 0.5) { gl_FragColor = vec4(vTint * s.r * 3.5 * vBlink, s.a * vBlink); return; }
  vec3 col = vTint * s.r;
  col *= mix(ambCol, lightCol, 0.72) * (vFace > 0.0 ? 1.0 : 0.82);
  vec3 V = normalize(cameraPosition - vW);
  float bl = pow(max(dot(-V, sunDir), 0.0), 2.0) * backlight;
  col += lightCol * vTint * bl * 0.7;
  col = mix(col, haze, 1.0 - exp(-vDist * fogDensity * 0.6));
  gl_FragColor = vec4(col, s.a * opacity * 0.96);
}`;

/**
 * Drifting petals (or fireflies at night). opts: {preset, flowerColors, count, view:{base frame}, wind, seed, focus, cocK, pxScale, atlas, fireflies}
 */
export function makePetals(THREE, opts) {
  const P = opts.preset, FC = opts.flowerColors, rnd = mulberry32((opts.seed * 131 + 17) >>> 0);
  const n = opts.count, ff = !!opts.fireflies;
  const iA = new Float32Array(n * 4), iB = new Float32Array(n * 4), iC = new Float32Array(n * 4), iT = new Float32Array(n * 3);
  const keys = ff ? ['#FFD36A'] : (P.petals || ['pink']).map((k) => FC[k] || '#F2A3B3');
  const items = [];
  for (let i = 0; i < n; i++) {
    const u = rnd();
    const d = ff ? 3 + Math.pow(u, 1.4) * 40 : 0.9 * Math.pow(85, Math.pow(u, 1.25));
    const size = ff ? 0.05 + rnd() * 0.05 : (0.045 + rnd() * 0.05) * (d < 4 ? 1.2 : 1) * (d > 25 ? 1.6 : 1);
    const wind = opts.wind ?? 1;
    items.push({ d, a: [rnd() * 2 - 1, rnd() * 2 - 1, d, size],
      b: [ff ? (rnd() - 0.5) * 0.3 : (0.55 + rnd() * 0.9) * wind * (1 + d * 0.01), ff ? (rnd() - 0.5) * 0.2 : -(0.12 + rnd() * 0.25) * wind, 0.6 + rnd() * 1.4, rnd() * 6.283],
      c: [(rnd() - 0.5) * 2.4, 1.2 + rnd() * 3.2, ff ? K.bokeh : (rnd() < 0.55 ? K.petalA : K.petalB), rnd()],
      tint: lin3(keys[Math.floor(rnd() * keys.length)]).map((v) => v * (0.92 + rnd() * 0.16)) });
  }
  items.sort((a, b) => b.d - a.d);
  items.forEach((it, i) => { iA.set(it.a, i * 4); iB.set(it.b, i * 4); iC.set(it.c, i * 4); iT.set(it.tint, i * 3); });
  const geo = new THREE.InstancedBufferGeometry();
  const q = new THREE.PlaneGeometry(1, 1);
  geo.index = q.index; geo.setAttribute('position', q.getAttribute('position')); geo.setAttribute('uv', q.getAttribute('uv'));
  geo.setAttribute('iA', new THREE.InstancedBufferAttribute(iA, 4));
  geo.setAttribute('iB', new THREE.InstancedBufferAttribute(iB, 4));
  geo.setAttribute('iC', new THREE.InstancedBufferAttribute(iC, 4));
  geo.setAttribute('iTint', new THREE.InstancedBufferAttribute(iT, 3));
  geo.instanceCount = n;
  const v = opts.view;
  const c3 = (h) => new THREE.Color(...lin3(h));
  const uniforms = {
    atlas: { value: opts.atlas.texture }, cols: { value: opts.atlas.cols }, rows: { value: opts.atlas.rows },
    focus: { value: opts.focus }, cocK: { value: opts.cocK }, pxScale: { value: opts.pxScale }, t: { value: 0 },
    bOrigin: { value: new THREE.Vector3(...v.base) }, bRight: { value: v.right }, bUp: { value: v.up }, bFwd: { value: v.fwd },
    tanH: { value: v.tanH }, tanV: { value: v.tanV }, travel: { value: v.travel }, fireflies: { value: ff ? 1 : 0 },
    lightCol: { value: c3(P.light) }, ambCol: { value: c3(P.ambient) }, haze: { value: c3(P.haze) }, sunDir: { value: opts.sunDir },
    fogDensity: { value: P.fogDensity }, backlight: { value: P.backlight }, opacity: { value: 1 },
  };
  const mat = new THREE.ShaderMaterial({ vertexShader: PETAL_VS, fragmentShader: PETAL_FS, uniforms, transparent: true, depthWrite: false,
    blending: ff ? THREE.AdditiveBlending : THREE.NormalBlending });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.frustumCulled = false; mesh.renderOrder = 40;
  return { mesh, count: n, uniforms, update(t, focus) { uniforms.t.value = t; if (focus) uniforms.focus.value = focus; } };
}

export { KINDS };
