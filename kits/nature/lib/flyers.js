// nature kit · flyers: the PRODUCT media (video frames or images) presented in 3D space and moved along varied,
// deterministic, staggered paths (descend, rise, drive-slope, float, orbit, arc, cross, pass, hero).
// Presentation: cutout (alpha) when the asset has one, else an automatic key of plain studio backgrounds, else
// a soft-edged glass card. Graded into the scene light, warm rim light from the sun, distance haze, DOF blur,
// motion blur along the screen velocity, a soft halo behind, and a contact shadow when driving on the ground.
// Every flyer is a real 3D card: it yaws (heading), pitches (nose up/down) and banks, and mirrors by direction,
// so no two cars share a pose. Moving cars draw anime speed lines and leave a wake of petals.
import { clamp, lerp, easeOutCubic, easeInCubic, easeInOutSine, easeInOutCubic, mulberry32, terrainHeight, smoothstep, fract } from './math.js';
import { lin3 } from './presets.js';

export const PATHS = ['descend', 'rise', 'drive-slope', 'float', 'orbit', 'arc', 'cross', 'pass', 'hero'];
/** Paths that park at their end pose (the others exit the frame and disappear). */
const HOLD = new Set(['descend', 'float', 'hero', 'drive-slope', 'orbit']);

/**
 * Default, deliberately non-uniform slots per path (fractions of the shot duration; sx/sy in base-camera NDC at depth d).
 * Never a formation: different depths, sides, start times, speeds and headings.
 */
const SLOTS = {
  descend: { d: 20, x0: -0.70, x1: -0.42, y0: 1.2, y1: 0.26, t0: 0.0, t1: 0.55, size: 5.4 },
  rise: { d: 64, x0: 0.18, x1: -0.06, y0: -0.3, y1: 1.5, t0: 0.30, t1: 1.0, size: 6.0 },
  'drive-slope': { t0: 0.04, t1: 0.92, size: 5.0 },
  float: { d: 34, x0: 0.42, x1: 0.50, y0: 0.32, y1: 0.38, t0: 0.12, t1: 1.0, size: 6.0 },
  orbit: { d: 48, x0: -0.95, x1: 0.85, y0: 0.62, y1: 0.55, ad: 22, t0: 0.0, t1: 1.0, size: 5.8 },
  arc: { d: 90, x0: -1.35, x1: 1.35, y0: 0.42, y1: 0.42, apex: 0.4, t0: 0.30, t1: 0.95, size: 6.5 },
  cross: { d: 52, x0: 1.4, x1: -1.4, y0: 0.82, y1: 0.74, t0: 0.05, t1: 0.85, size: 5.6 },
  pass: { d0: 19, d: 4.2, x0: 6.5, x1: -6.0, y0: -0.2, y1: -0.7, t0: 0.15, t1: 0.62, size: 5.2 },
  hero: { d: 16, x0: 0.0, y0: 0.0, t0: 0.0, t1: 1.0, size: 6.4 },
};
/** 9:16 slots: stacked vertically, narrower lateral travel, bigger relative size. */
const SLOTS_V = {
  descend: { d: 18, x0: -0.30, x1: 0.05, y0: 1.15, y1: 0.42, t0: 0.0, t1: 0.55, size: 5.0 },
  rise: { d: 58, x0: 0.45, x1: 0.15, y0: -0.25, y1: 1.4, t0: 0.30, t1: 1.0, size: 5.6 },
  'drive-slope': { t0: 0.04, t1: 0.92, size: 4.8 },
  float: { d: 30, x0: 0.10, x1: 0.20, y0: 0.05, y1: 0.12, t0: 0.12, t1: 1.0, size: 5.4 },
  orbit: { d: 44, x0: -0.9, x1: 0.8, y0: 0.70, y1: 0.62, ad: 18, t0: 0.0, t1: 1.0, size: 5.4 },
  arc: { d: 80, x0: -1.4, x1: 1.4, y0: 0.55, y1: 0.55, apex: 0.3, t0: 0.30, t1: 0.95, size: 6.0 },
  cross: { d: 48, x0: 1.4, x1: -1.4, y0: 0.85, y1: 0.78, t0: 0.05, t1: 0.85, size: 5.4 },
  pass: { d0: 26, d: 6.0, x0: 5.5, x1: -5.5, y0: -0.6, y1: -1.0, t0: 0.15, t1: 0.62, size: 4.6 },
  hero: { d: 16, x0: 0.0, y0: -0.1, t0: 0.0, t1: 1.0, size: 5.6 },
};
/** Default clip playback per path (wheel spin reads faster on the ground and on a pass). */
const CLIP_RATE = { 'drive-slope': 1.5, pass: 2.0, rise: 1.3, arc: 1.2, cross: 1.2 };

/** Fill defaults for a flyer spec (pure). `i` staggers the clip offset; `dur` = shot length. */
export function resolveFlyer(spec, i, dur, seed = 0, portrait = false) {
  const path = PATHS.includes(spec.path) ? spec.path : 'float';
  const s = { ...(portrait ? SLOTS_V : SLOTS)[path], ...spec, path };
  const r = mulberry32(((seed + 1) * 9973 + i * 7919) >>> 0);
  s.t0 = (s.t0 ?? 0) * (spec.t0 == null ? dur : 1);
  s.t1 = (s.t1 ?? 1) * (spec.t1 == null ? dur : 1);
  if (spec.t0 != null) s.t0 = spec.t0;
  if (spec.t1 != null) s.t1 = spec.t1;
  s.clipOffset = spec.clipOffset ?? (i * 1.37 + r() * 0.8);
  s.clipRate = spec.clipRate ?? CLIP_RATE[path] ?? 1.0;
  s.phase = r() * 6.283;
  s.facing = spec.facing || 'right';
  s.streaks = spec.streaks ?? (path === 'drive-slope' ? 0 : 1);   // on the ground the grass cuts speed lines into dashes: wake only
  s.wake = spec.wake ?? (path === 'drive-slope' ? 0.4 : path === 'descend' || path === 'rise' ? 0.6 : 1);   // vertical/ground movers: a full wake reads as dotted rain
  s.idx = i;
  return s;
}

/**
 * Pose of a flyer at shot time t (pure). Returns {visible, sx, sy, d} (base-camera NDC + depth) or {world:[x,y,z]}
 * for ground paths, plus the car's attitude: nose (rad, + = nose up), bank (rad, + = roof tilts toward the camera),
 * heading (rad, + = nose turned toward the camera), dir (+1 moving right / -1 left), opacity.
 */
export function flyerPose(s, t, env) {
  const span = Math.max(s.t1 - s.t0, 1e-3);
  let u = (t - s.t0) / span;
  if (u < 0) return { visible: false };
  if (u > 1) { if (HOLD.has(s.path) && s.hold !== false) u = 1; else return { visible: false }; }
  const ph = s.phase, bob = Math.sin(t * 1.9 + ph) * 0.012, sway = Math.sin(t * 0.83 + ph * 1.3);
  let sx = 0, sy = 0, d = s.d || 30, nose = 0, bank = 0, heading = 0, dir = 1, opacity = 1;
  switch (s.path) {
    case 'descend': {                                   // drops in nose-down, flares out, settles with a bank
      const e = easeOutCubic(u);
      sx = lerp(s.x0, s.x1, easeInOutSine(u)); sy = lerp(s.y0, s.y1, e) + bob * smoothstep(0.6, 1, u); d = lerp(d * 1.3, d, e);
      dir = s.x1 >= s.x0 ? 1 : -1;
      nose = -0.20 * (1 - e) + 0.05 * Math.sin(Math.PI * smoothstep(0.55, 1, u)) + 0.02 * sway;
      bank = 0.18 * (1 - e) + 0.04 * Math.sin(t * 0.9 + ph);
      heading = lerp(0.30, 0.08, e) + 0.06 * Math.sin(t * 0.5 + ph);
      break;
    }
    case 'rise': {                                      // emerges from behind the meadow, climbs away nose-up
      const e = easeInCubic(Math.min(u * 1.05, 1));
      sx = lerp(s.x0, s.x1, easeInOutSine(u)); sy = lerp(s.y0, s.y1, e * 0.75 + u * 0.25); d = lerp(d, d * 1.25, u);
      dir = s.x1 >= s.x0 ? 1 : -1;
      nose = 0.30 * smoothstep(0.05, 0.6, u) + 0.02 * sway;
      bank = -0.12 * smoothstep(0.2, 0.9, u);
      heading = lerp(0.05, -0.35, smoothstep(0.1, 1, u));
      break;
    }
    case 'float': {                                     // glides in, hovers, slowly turns to show itself off
      const e = easeOutCubic(clamp(u * 3.2));
      sx = lerp(s.x0 - 1.7, s.x0, e) + (s.x1 - s.x0) * u + 0.02 * sway; sy = s.y0 + (s.y1 - s.y0) * u + 0.045 * Math.sin(t * 1.25 + ph) + 0.02 * Math.sin(t * 2.1);
      dir = 1;
      nose = 0.035 * Math.sin(t * 1.25 + ph + 0.8);
      bank = 0.06 * Math.sin(t * 0.7 + ph);
      heading = 0.32 * Math.sin(t * 0.42 + ph) * smoothstep(0.1, 0.35, u) + 0.15 * (1 - e);
      break;
    }
    case 'orbit': {                                     // half orbit in front of the camera: swoops close, banks, recedes
      const e = easeInOutSine(u), a = Math.PI * e;
      sx = lerp(s.x0, s.x1, e); d = (s.d || 48) - (s.ad || 20) * Math.sin(a); sy = lerp(s.y0, s.y1, e) - 0.10 * Math.sin(a) + bob;
      dir = s.x1 >= s.x0 ? 1 : -1;
      heading = 0.55 * Math.cos(a);                     // nose toward camera on the way in, away on the way out
      bank = 0.30 * Math.sin(a);
      nose = -0.06 * Math.cos(a);
      opacity = smoothstep(0, 0.06, u);
      break;
    }
    case 'arc': {                                       // long parabola across the sky, nose follows the arc
      const e = easeInOutSine(u);
      sx = lerp(s.x0, s.x1, e); sy = lerp(s.y0, s.y1, e) + s.apex * Math.sin(Math.PI * e); d = d * (1 - 0.25 * Math.sin(Math.PI * e));
      dir = s.x1 >= s.x0 ? 1 : -1;
      nose = 0.28 * Math.cos(Math.PI * e);
      bank = 0.22 * Math.sin(Math.PI * e);
      heading = -0.15 + 0.3 * e;
      break;
    }
    case 'cross': {
      const e = easeInOutSine(u);
      sx = lerp(s.x0, s.x1, e); sy = lerp(s.y0, s.y1, e) + 0.03 * Math.sin(u * 9 + ph);
      dir = s.x1 >= s.x0 ? 1 : -1;
      nose = 0.04 * Math.cos(u * 9 + ph); bank = 0.08 * Math.sin(u * 4.5 + ph); heading = -0.1;
      break;
    }
    case 'pass': {                                      // hero pass-by: a straight run past the lens, relative to the LIVE camera
      // (x0/x1 lateral metres, y0/y1 metres below eye level, d0 -> d depth): it holds on screen as it approaches and
      // grows, then whips off the side - the angular speed peaks as it passes, like a real car
      const e = lerp(u, easeInOutSine(u), 0.3);
      const x = lerp(s.x0, s.x1, e), y = lerp(s.y0, s.y1, e) + 0.05 * Math.sin(t * 2.3 + ph), dd = lerp(s.d0 || 24, s.d || 5.5, e);
      dir = s.x1 >= s.x0 ? 1 : -1;
      return { visible: true, cam: [x, y, dd], sx: x / (dd * 0.544), sy: y / (dd * 0.306), d: dd, dir, opacity: 1,
        heading: lerp(0.42, 0.05, smoothstep(0.3, 1, u)), bank: 0.10 * smoothstep(0.4, 0.9, u), nose: 0.03 * Math.sin(t * 3 + ph) };
    }
    case 'hero': {
      if (s.at) {
        const y = terrainHeight(s.at[0], s.at[1], env.terrain) + 0.05 + 0.006 * Math.sin(t * 6.0 + ph);
        return { visible: true, world: [s.at[0], y, s.at[1]], nose: 0.004 * Math.sin(t * 0.9), bank: 0, heading: s.heading ?? 0.12 * Math.sin(t * 0.3), dir: 1, opacity: 1, ground: true, flat: true };
      }
      sx = s.x0 + 0.01 * sway; sy = s.y0 + 0.012 * Math.sin(t * 1.1 + ph); d = s.d; dir = 1; nose = 0.01 * Math.sin(t * 0.9);
      heading = s.heading ?? 0.18 * Math.sin(t * 0.35 + ph);
      break;
    }
    case 'drive-slope': {                               // drives down the hill toward the camera, wheels on the grass
      const g = env.slope;
      const e = lerp(u, easeInOutCubic(u), 0.35);
      const x = lerp(g.a[0], g.b[0], e), z = lerp(g.a[1], g.b[1], e);
      const y = terrainHeight(x, z, env.terrain) + 0.06 + 0.02 * Math.abs(Math.sin(t * 7.0 + ph));
      dir = g.b[0] >= g.a[0] ? 1 : -1;
      return { visible: true, world: [x, y, z], nose: 0, bank: 0.02 * Math.sin(t * 5.0 + ph), heading: s.heading ?? 0.30, dir, opacity: 1, ground: true, slopeU: e };
    }
    default: break;
  }
  return { visible: true, sx, sy, d, nose, bank, heading, dir, opacity };
}

// ------------------------------------------------------------------ rendering

const VS = /* glsl */`
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

const FS = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D map; uniform int mode;   // 0 cutout · 1 key · 2 card
uniform vec3 keyCol; uniform float keyTol;
uniform vec4 crop;        // u0, v0, u1, v1 of the media inside the card (card = crop + padding)
uniform float flip, blurPx, opacity, rimI, hazeAmt, cardR, aspect;
uniform vec2 rimDir, texel, mblur;
uniform vec3 lightCol, ambCol, haze, rimCol; uniform float prodExp, shade;
vec4 tap(vec2 uv){
  vec4 c = texture2D(map, uv);
  if (mode == 1) {
    float dk = distance(c.rgb, keyCol);
    float a = smoothstep(keyTol, keyTol * 2.2, dk);
    float lumK = dot(keyCol, vec3(0.333)), lum = dot(c.rgb, vec3(0.333));
    float shadow = smoothstep(0.08, 0.0, length(c.rgb - vec3(lum))) * smoothstep(lumK * 0.98, lumK * 0.55, lum);
    a = max(a * (1.0 - shadow * 0.9), step(lum, lumK * 0.42));
    c.a = a;
    c.rgb = mix(c.rgb, c.rgb - (keyCol - vec3(lumK)) * 0.6, 1.0 - a);
  }
  return c;
}
vec4 sampleBlur(vec2 uv){
  float mb = length(mblur);
  if (blurPx < 0.8 && mb < 0.8) return tap(uv);
  vec4 s = vec4(0.0);
  for (int i = 0; i < 12; i++) {
    float fi = float(i); float r = sqrt((fi + 0.5) / 12.0) * blurPx; float a = fi * 2.39996;
    vec2 o = vec2(cos(a), sin(a)) * r + mblur * ((fi + 0.5) / 12.0 - 0.5);
    s += tap(uv + o * texel);
  }
  return s / 12.0;
}
float roundRect(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main(){
  vec2 uv = vUv; if (flip < 0.0) uv.x = 1.0 - uv.x;
  vec2 m = (uv - crop.xy) / (crop.zw - crop.xy);
  vec4 c = vec4(0.0);
  if (m.x >= -0.02 && m.x <= 1.02 && m.y >= -0.02 && m.y <= 1.02) c = sampleBlur(m);
  float a = c.a;
  if (mode == 2) {
    vec2 p = (m - 0.5) * vec2(aspect, 1.0);
    float sd = roundRect(p, vec2(0.5 * aspect, 0.5), cardR);
    float fw = 0.004 + blurPx * texel.y;
    a = 1.0 - smoothstep(-fw, fw, sd);
    float edge = 1.0 - smoothstep(0.0, 0.012, abs(sd + 0.004));
    vec2 n = normalize(p + 1e-4);
    float key = clamp(dot(n, normalize(rimDir)) * 0.7 + 0.3, 0.0, 1.0);
    c.rgb += rimCol * edge * key * rimI * 1.6;
  }
  if (a < 0.01) discard;
  vec3 col = c.rgb;
  // grade into the scene light: warm key, ambient-tinted shadows; turning away from the light dims a touch
  float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = mix(col, col * lightCol * 1.1, 0.55) * 0.95 * shade + ambCol * 0.07 * (1.0 - lum);
  if (mode != 2) {
    // rim light on silhouette edges that face the sun
    vec2 off = rimDir * texel * (5.0 + blurPx);
    float ao = sampleBlur(m + off).a;
    float rimD = clamp(a - ao, 0.0, 1.0);
    col += rimCol * rimD * 1.5 * rimI;
  }
  col = mix(col * prodExp, haze, hazeAmt);
  gl_FragColor = vec4(col, a * opacity);
}`;

const GLOW_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform vec3 col; uniform float strength;
void main(){ vec2 p = (vUv - 0.5) * 2.0; float r = length(p * vec2(1.0, 1.6)); float a = exp(-r * r * 2.6) * strength; gl_FragColor = vec4(col * a, a); }`;

const SHADOW_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform float strength;
void main(){ vec2 p = (vUv - 0.5) * 2.0; float a = exp(-dot(p, p) * 3.0) * strength; gl_FragColor = vec4(0.0, 0.0, 0.0, a); }`;

// speed lines: thin additive quads; aL = (along 0 head .. 1 tail, across -1..1), aA = alpha
const STREAK_VS = /* glsl */`
attribute vec2 aL; attribute float aA; varying vec2 vL; varying float vA;
void main(){ vL = aL; vA = aA; gl_Position = projectionMatrix * viewMatrix * vec4(position, 1.0); }`;
const STREAK_FS = /* glsl */`
precision highp float; varying vec2 vL; varying float vA; uniform vec3 col;
void main(){ float a = vA * pow(1.0 - vL.x, 1.3) * (1.0 - vL.y * vL.y) * smoothstep(0.0, 0.06, vL.x); gl_FragColor = vec4(col * 1.6, a * 0.85); }`;
// petal wake: soft petals in petal colours, normal blending
const WAKE_VS = /* glsl */`
attribute vec2 aL; attribute float aA; attribute vec3 aC; varying vec2 vL; varying float vA; varying vec3 vC;
void main(){ vL = aL; vA = aA; vC = aC; gl_Position = projectionMatrix * viewMatrix * vec4(position, 1.0); }`;
const WAKE_FS = /* glsl */`
precision highp float; varying vec2 vL; varying float vA; varying vec3 vC; uniform vec3 lightCol;
void main(){
  vec2 p = vL; float r = length(p * vec2(1.0, 1.55)) + 0.18 * smoothstep(0.55, 1.0, p.y) * (1.0 - abs(p.x) * 3.0);
  float a = smoothstep(1.0, 0.72, r) * vA; if (a < 0.01) discard;
  gl_FragColor = vec4(vC * mix(vec3(1.0), lightCol, 0.4) * (0.85 + 0.25 * (1.0 - p.y)), a);
}`;

/** Estimate the media's bbox from alpha (cutout) or from distance to a border key colour. Returns {u0,v0,u1,v1, key}. */
export function analyseMedia(img, hasAlpha) {
  const W = 160, H = Math.max(1, Math.round(160 * (img.height || 9) / (img.width || 16)));
  const cv = new OffscreenCanvas(W, H), g = cv.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0, W, H);
  const d = g.getImageData(0, 0, W, H).data;
  let kr = 0, kg = 0, kb = 0, n = 0;
  const border = [];
  for (let x = 0; x < W; x++) { border.push([x, 0], [x, H - 1]); }
  for (let y = 0; y < H; y++) { border.push([0, y], [W - 1, y]); }
  for (const [x, y] of border) { const o = (y * W + x) * 4; kr += d[o]; kg += d[o + 1]; kb += d[o + 2]; n++; }
  kr /= n; kg /= n; kb /= n;
  let vr = 0;
  for (const [x, y] of border) { const o = (y * W + x) * 4; vr += (d[o] - kr) ** 2 + (d[o + 1] - kg) ** 2 + (d[o + 2] - kb) ** 2; }
  const std = Math.sqrt(vr / n / 3);
  const keyable = !hasAlpha && std < 14;
  let x0 = W, y0 = H, x1 = -1, y1 = -1;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const o = (y * W + x) * 4;
    const on = hasAlpha ? d[o + 3] > 128 : keyable ? Math.hypot(d[o] - kr, d[o + 1] - kg, d[o + 2] - kb) > 60 : true;
    if (on) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  }
  if (x1 < 0) { x0 = 0; y0 = 0; x1 = W - 1; y1 = H - 1; }
  const toLin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  return { u0: x0 / W, u1: (x1 + 1) / W, v0: 1 - (y1 + 1) / H, v1: 1 - y0 / H, keyable, key: [toLin(kr), toLin(kg), toLin(kb)], std };
}

const NSTREAK = 16, NWAKE = 40;

/** A dynamic quad batch (positions rewritten per frame) with per-vertex aL (vec2), aA (float) and optional aC (vec3). */
function quadBatch(THREE, n, withColour) {
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(n * 4 * 3), aL = new Float32Array(n * 4 * 2), aA = new Float32Array(n * 4), idx = [];
  for (let i = 0; i < n; i++) { const o = i * 4; idx.push(o, o + 1, o + 2, o, o + 2, o + 3); }
  geo.setIndex(idx);
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('aL', new THREE.BufferAttribute(aL, 2).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('aA', new THREE.BufferAttribute(aA, 1).setUsage(THREE.DynamicDrawUsage));
  let aC = null;
  if (withColour) { aC = new Float32Array(n * 4 * 3); geo.setAttribute('aC', new THREE.BufferAttribute(aC, 3)); }
  return { geo, pos, aL, aA, aC, n };
}

/**
 * Build flyer meshes. opts: {specs, assets(name)->asset, preset, sunDir, dur, quality:{flyerTex}, env:{slope, terrain}, seed,
 * view, portrait, flowerColors}. Returns {group, flyers, worldFromNDC, update(t, camera, dof), centreAt(i, t)}.
 */
export function makeFlyers(THREE, opts) {
  const P = opts.preset, group = new THREE.Group();
  const c3 = (h) => new THREE.Color(...lin3(h));
  const flyers = [];
  const maxW = opts.quality.flyerTex || 1280;
  const petalCols = (P.petals || ['pink']).map((k) => lin3((opts.flowerColors || {})[k] || '#F2A3B3'));
  opts.specs.forEach((spec0, i) => {
    const s = resolveFlyer(spec0, i, opts.dur, opts.seed, opts.portrait);
    const asset = opts.assets(s.media);
    const useCut = !!asset.cutout && s.cutout !== false;
    const src = useCut ? asset.cutout : asset;
    const info = analyseMedia(src.image, useCut);
    const mode = useCut ? 0 : (info.keyable && s.key !== false ? 1 : 2);
    // card size: the visible product (bbox) gets `size` metres of width
    const aspect = (asset.w || 16) / (asset.h || 9);
    const bw = mode === 2 ? 1 : (info.u1 - info.u0), bh = mode === 2 ? 1 : (info.v1 - info.v0);
    const pad = mode === 2 ? 0.0 : 0.06;
    const cu0 = mode === 2 ? 0 : Math.max(0, info.u0 - pad), cu1 = mode === 2 ? 1 : Math.min(1, info.u1 + pad);
    const cv0 = mode === 2 ? 0 : Math.max(0, info.v0 - pad), cv1 = mode === 2 ? 1 : Math.min(1, info.v1 + pad);
    const qw = s.size * (cu1 - cu0) / Math.max(bw, 1e-3);
    const qh = qw * ((cv1 - cv0) / (cu1 - cu0)) / aspect;
    const tex = new THREE.Texture();
    tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter; tex.generateMipmaps = false;
    let scaler = null;
    if ((asset.w || 0) > maxW) { const sh = Math.round(maxW * (asset.h || 9) / (asset.w || 16)); scaler = new OffscreenCanvas(maxW, sh); }
    const crop = new THREE.Vector4(-cu0 / (cu1 - cu0), -cv0 / (cv1 - cv0), (1 - cu0) / (cu1 - cu0), (1 - cv0) / (cv1 - cv0));
    const uniforms = {
      map: { value: tex }, mode: { value: mode }, keyCol: { value: new THREE.Vector3(...info.key) }, keyTol: { value: 0.06 },
      crop: { value: crop }, flip: { value: 1 }, blurPx: { value: 0 }, opacity: { value: 1 }, rimI: { value: 1 }, hazeAmt: { value: 0 },
      cardR: { value: 0.06 }, aspect: { value: aspect }, rimDir: { value: new THREE.Vector2(0, 1) }, mblur: { value: new THREE.Vector2(0, 0) },
      texel: { value: new THREE.Vector2(1 / Math.min(asset.w || 1280, maxW), 1 / Math.min(asset.h || 720, maxW / aspect)) },
      lightCol: { value: c3(P.light) }, ambCol: { value: c3(P.ambient) }, haze: { value: c3(P.haze) }, rimCol: { value: c3(P.sun.glow) },
      prodExp: { value: P.productExposure ?? 1 }, shade: { value: 1 },
    };
    const mat = new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: FS, uniforms, transparent: true, depthWrite: true, side: THREE.DoubleSide });
    const geo = new THREE.PlaneGeometry(1, 1);
    // anchor: bottom-centre of the product bbox at the origin (so ground paths put wheels on the ground)
    const vb = mode === 2 ? 0 : (info.v0 - cv0) / (cv1 - cv0);
    const uc = mode === 2 ? 0.5 : ((info.u0 + info.u1) / 2 - cu0) / (cu1 - cu0);
    geo.translate(0.5 - uc, 0.5 - vb, 0);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = 10;
    const glowMat = new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: GLOW_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { col: { value: c3(P.sun.glow) }, strength: { value: 0.3 } } });
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), glowMat);
    glow.renderOrder = 9;
    const shadowMat = new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: SHADOW_FS, transparent: true, depthWrite: false, uniforms: { strength: { value: 0.0 } } });
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), shadowMat);
    shadow.rotation.x = -Math.PI / 2; shadow.renderOrder = 8; shadow.visible = false;
    // speed lines + petal wake
    const sb = quadBatch(THREE, NSTREAK, false), wb = quadBatch(THREE, NWAKE, true);
    const streakCol = new THREE.Color(...lin3(P.sun.color)).lerp(new THREE.Color(1, 1, 1), 0.5);
    const streaks = new THREE.Mesh(sb.geo, new THREE.ShaderMaterial({ vertexShader: STREAK_VS, fragmentShader: STREAK_FS, transparent: true, depthWrite: false,
      side: THREE.DoubleSide, uniforms: { col: { value: streakCol } } }));
    streaks.frustumCulled = false; streaks.renderOrder = 11;
    const wake = new THREE.Mesh(wb.geo, new THREE.ShaderMaterial({ vertexShader: WAKE_VS, fragmentShader: WAKE_FS, transparent: true, depthWrite: false,
      side: THREE.DoubleSide, uniforms: { lightCol: { value: c3(P.light) } } }));
    wake.frustumCulled = false; wake.renderOrder = 12;
    const rr = mulberry32((opts.seed * 131 + i * 977 + 5) >>> 0);
    const lines = Array.from({ length: NSTREAK }, () => ({ o: (rr() * 2 - 1), b: rr(), l: 0.8 + rr() * 1.6, w: 0.0035 + rr() * 0.008, ph: rr(), a: 0.55 + rr() * 0.45 }));
    const motes = Array.from({ length: NWAKE }, () => ({ ph: rr(), ox: rr() * 2 - 1, oy: rr() * 2 - 1, sz: 0.10 + rr() * 0.16, sp: (rr() - 0.5) * 9, c: petalCols[Math.floor(rr() * petalCols.length)] }));
    for (let k = 0; k < NWAKE; k++) for (let v = 0; v < 4; v++) wb.aC.set(motes[k].c, (k * 4 + v) * 3);
    group.add(shadow, glow, mesh, streaks, wake);
    flyers.push({ s, asset, src, useCut, mode, mesh, glow, shadow, streaks, wake, sb, wb, lines, motes, uniforms, tex, scaler, qw, qh, bboxH: bh, lastImg: null, info });
  });

  const v3 = new THREE.Vector3(), v4 = new THREE.Vector3(), q = new THREE.Quaternion(), e = new THREE.Euler();
  const camR = new THREE.Vector3(), camU = new THREE.Vector3(), camF = new THREE.Vector3();
  const view = opts.view;
  function worldFromNDC(sx, sy, d) {
    return [view.base[0] + view.fwd.x * d + view.right.x * sx * d * view.tanH + view.up.x * sy * d * view.tanV,
      view.base[1] + view.fwd.y * d + view.right.y * sx * d * view.tanH + view.up.y * sy * d * view.tanV,
      view.base[2] + view.fwd.z * d + view.right.z * sx * d * view.tanH + view.up.z * sy * d * view.tanV];
  }
  const project = (p, camera) => { v4.set(p[0], p[1], p[2]).project(camera); return [v4.x, v4.y, v4.z]; };
  const envOf = () => ({ dur: opts.dur, slope: opts.env.slope, terrain: opts.env.terrain });
  /** World position of a pose: ground (world), live-camera-relative (cam) or base-camera NDC. */
  function posOf(pose, t) {
    if (pose.world) return pose.world;
    if (pose.cam && opts.viewAt) {
      const V = opts.viewAt(t), [x, y, d] = pose.cam;
      return [V.base[0] + V.fwd[0] * d + V.right[0] * x + V.up[0] * y, V.base[1] + V.fwd[1] * d + V.right[1] * x + V.up[1] * y,
        V.base[2] + V.fwd[2] * d + V.right[2] * x + V.up[2] * y];
    }
    return worldFromNDC(pose.sx, pose.sy, pose.d);
  }
  /** World position of flyer f's body centre at time t (null when hidden). */
  function centreAt(f, t) {
    const pose = flyerPose(f.s, t, envOf());
    if (!pose.visible) return null;
    const p = posOf(pose, t);
    return [p[0], p[1] + f.qh * 0.42, p[2]];
  }

  return {
    group, flyers,
    worldFromNDC, posOf,
    centreAt: (i, t) => (flyers[i] ? centreAt(flyers[i], t) : null),
    update(t, camera, dof) {
      const sunP = [camera.position.x + opts.sunDir.x * 3000, camera.position.y + opts.sunDir.y * 3000, camera.position.z + opts.sunDir.z * 3000];
      const sunS = project(sunP, camera);
      camera.matrixWorld.extractBasis(camR, camU, camF);
      for (const f of flyers) {
        const pose = flyerPose(f.s, t, envOf());
        f.mesh.visible = f.glow.visible = pose.visible;
        f.shadow.visible = !!(pose.visible && pose.ground);
        f.streaks.visible = f.wake.visible = pose.visible;
        if (!pose.visible) continue;
        const p = posOf(pose, t);
        // media frame (each flyer at its own clip offset and wheel-spin rate)
        const ct = (t - f.s.t0) * f.s.clipRate + f.s.clipOffset;
        let img = f.src.frame ? f.src.frame(ct, { loop: true }) : f.src.image;
        if (img && img !== f.lastImg) {
          f.lastImg = img;
          if (f.scaler) { const g = f.scaler.getContext('2d'); g.clearRect(0, 0, f.scaler.width, f.scaler.height); g.drawImage(img, 0, 0, f.scaler.width, f.scaler.height); img = f.scaler; }
          f.tex.image = img; f.tex.needsUpdate = true;
        }
        // screen-space velocity (from the pose 1/15 s ago) → motion blur, speed lines, wake
        const c0 = centreAt(f, t), c1 = centreAt(f, t - 1 / 15) || c0;
        const a = project(c0, camera), b = project(c1, camera);
        const vx = (a[0] - b[0]) * 15 * camera.aspect, vy = (a[1] - b[1]) * 15;       // NDC-height units per second
        const speed = Math.hypot(vx, vy);
        // attitude: a real 3D card. Facing: the clip's car faces `facing`; mirror when it moves the other way.
        const facingSign = f.s.facing === 'left' ? -1 : 1;
        const sx = (pose.dir || 1);                    // +1: nose to screen-right
        let nose = pose.nose || 0;
        if (pose.ground && !pose.flat) {
          if (speed > 1e-4) nose = clamp(Math.atan2(vy, vx * sx), -0.16, 0.16);
        }
        f.mesh.position.set(p[0], p[1], p[2]);
        f.mesh.quaternion.copy(camera.quaternion);
        e.set(pose.bank || 0, -(pose.heading || 0) * sx, nose * sx, 'ZYX'); q.setFromEuler(e); f.mesh.quaternion.multiply(q);
        f.mesh.scale.set(f.qw, f.qh, 1);
        f.uniforms.flip.value = sx * facingSign < 0 ? -1 : 1;
        f.uniforms.opacity.value = pose.opacity;
        f.uniforms.shade.value = 1 - 0.12 * clamp(-(pose.heading || 0) * 1.6, 0, 1);
        if (pose.ground) {
          f.shadow.position.set(p[0], terrainHeight(p[0], p[2], opts.env.terrain) + 0.03, p[2]);
          f.shadow.scale.set(f.s.size * 0.95, f.s.size * 0.38, 1);
          f.shadow.material.uniforms.strength.value = 0.42;
        }
        // halo behind the product
        v3.set(0, f.qh * 0.35, -0.2).applyQuaternion(f.mesh.quaternion);
        f.glow.position.set(p[0] + v3.x, p[1] + v3.y, p[2] + v3.z);
        f.glow.quaternion.copy(camera.quaternion);
        f.glow.scale.set(f.qw * 1.5, f.qh * 1.6, 1);
        f.glow.material.uniforms.strength.value = 0.32 * pose.opacity;
        // depth of field, haze, rim direction, motion blur
        const dist = camera.position.distanceTo(f.mesh.position);
        const cocPx = dof.cocK * Math.abs(1 / dist - 1 / dof.focus);
        const pxPerTex = Math.max(f.qw * dof.pxScale / dist, 1) * f.uniforms.texel.value.x;   // screen px per texel
        f.uniforms.blurPx.value = Math.min(cocPx / Math.max(pxPerTex, 1e-3), 24);
        const mbPx = Math.min(speed * (dof.hpx || 540) / 45, 120);                                // 270-degree shutter (screen px)
        const mbTex = mbPx / Math.max(pxPerTex, 1e-3);
        let mx = vx, my = vy; const ml = Math.hypot(mx, my) || 1; mx /= ml; my /= ml;
        const cr = Math.cos(-nose * sx), sr = Math.sin(-nose * sx);
        [mx, my] = [mx * cr - my * sr, mx * sr + my * cr];
        if (f.uniforms.flip.value < 0) mx = -mx;
        f.uniforms.mblur.value.set(mx * Math.min(mbTex, 40), my * Math.min(mbTex, 40));
        f.uniforms.hazeAmt.value = clamp((1 - Math.exp(-dist * opts.preset.fogDensity)) * 0.85, 0, 0.6);
        const ps = project(p, camera);
        let rx = (sunS[0] - ps[0]) * camera.aspect, ry = sunS[1] - ps[1];
        const rc = Math.cos(-nose * sx), rs = Math.sin(-nose * sx);
        [rx, ry] = [rx * rc - ry * rs, rx * rs + ry * rc];
        if (f.uniforms.flip.value < 0) rx = -rx;
        const L = Math.hypot(rx, ry) || 1;
        f.uniforms.rimDir.value.set(rx / L, ry / L);
        f.uniforms.rimI.value = opts.rim ?? 1;
        // speed lines: drawn the anime way, along the SCREEN velocity in a plane just behind the car (so a car rushing
        // toward the lens still trails lines across the frame, and its body covers where they start)
        const k = clamp((speed - 0.12) / 0.7) * f.s.streaks * pose.opacity;
        const Vd = v3.set(0, 0, 0).addScaledVector(camR, vx).addScaledVector(camU, vy);
        if (Vd.lengthSq() > 1e-12) Vd.normalize(); else Vd.copy(camR);
        const perp = new THREE.Vector3().crossVectors(Vd, camF).normalize();
        const cBack = [c0[0] - camF.x * 0.4, c0[1] - camF.y * 0.4, c0[2] - camF.z * 0.4];
        writeStreaks(f, cBack, Vd, perp, k, t);
        writeWake(f, t, k, camR, camU, centreAt);
      }
    },
  };
}

/** Anime speed lines: NSTREAK thin quads behind the car, scrolling backward, length ∝ car size. */
function writeStreaks(f, c, V, perp, k, t) {
  const { pos, aL, aA, geo } = f.sb, W = f.qw, H = f.qh;
  for (let i = 0; i < NSTREAK; i++) {
    const L = f.lines[i], cyc = fract(L.ph + t * 1.6), back = W * (0.25 + 0.9 * cyc), len = W * L.l * (0.35 + 0.45 * k);
    const off = L.o * H * 0.55, wdt = W * L.w;
    const hx = c[0] - V.x * back + perp.x * off, hy = c[1] - V.y * back + perp.y * off, hz = c[2] - V.z * back + perp.z * off;
    const tx = hx - V.x * len, ty = hy - V.y * len, tz = hz - V.z * len;
    const o = i * 12;
    const P4 = [[hx + perp.x * wdt, hy + perp.y * wdt, hz + perp.z * wdt], [tx + perp.x * wdt, ty + perp.y * wdt, tz + perp.z * wdt],
      [tx - perp.x * wdt, ty - perp.y * wdt, tz - perp.z * wdt], [hx - perp.x * wdt, hy - perp.y * wdt, hz - perp.z * wdt]];
    P4.forEach((v, j) => pos.set(v, o + j * 3));
    aL.set([0, 1, 1, 1, 1, -1, 0, -1], i * 8);
    const a = k * L.a * Math.sin(Math.PI * cyc);
    aA.fill(a, i * 4, i * 4 + 4);
  }
  geo.attributes.position.needsUpdate = true; geo.attributes.aL.needsUpdate = true; geo.attributes.aA.needsUpdate = true;
}

/** Petal wake: motes born on the car's past path drift out, tumble and fade (pure: age = fract(phase + t / life)). */
function writeWake(f, t, k, camR, camU, centreAt) {
  const { pos, aL, aA, geo } = f.wb, life = 1.6, W = f.qw;
  for (let i = 0; i < NWAKE; i++) {
    const m = f.motes[i], age = fract(m.ph + t / life) * life, born = t - age;
    const c = centreAt(f, born);
    const o = i * 12;
    if (!c || k <= 0.02 || f.s.wake <= 0) { aA.fill(0, i * 4, i * 4 + 4); pos.fill(0, o, o + 12); continue; }
    const spread = (0.15 + age * 0.55) * W * 0.25;
    const x = c[0] + camR.x * m.ox * spread + camU.x * m.oy * spread * 0.6 + 0.6 * age;
    const y = c[1] + camR.y * m.ox * spread + camU.y * m.oy * spread * 0.6 - 0.35 * age * age - f.qh * 0.15;
    const z = c[2] + camR.z * m.ox * spread + camU.z * m.oy * spread * 0.6;
    const s = m.sz * (W / 5) * (1 - 0.3 * age / life), ang = m.sp * age + m.ph * 6.283, ca = Math.cos(ang), sa = Math.sin(ang);
    const flutter = 0.35 + 0.65 * Math.abs(Math.cos(age * 6 + m.ph * 9));
    const corner = (u, v) => { const uu = u * ca * flutter - v * sa, vv = u * sa * flutter + v * ca; return [x + (camR.x * uu + camU.x * vv) * s, y + (camR.y * uu + camU.y * vv) * s, z + (camR.z * uu + camU.z * vv) * s]; };
    [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([u, v], j) => pos.set(corner(u, v), o + j * 3));
    aL.set([-1, -1, 1, -1, 1, 1, -1, 1], i * 8);
    aA.fill(k * f.s.wake * smoothstep(0.0, 0.12, age) * (1 - smoothstep(life * 0.55, life, age)) * 0.9, i * 4, i * 4 + 4);
  }
  geo.attributes.position.needsUpdate = true; geo.attributes.aL.needsUpdate = true; geo.attributes.aA.needsUpdate = true;
}
