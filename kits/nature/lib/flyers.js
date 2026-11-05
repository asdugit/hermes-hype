// nature kit · flyers: the PRODUCT media (video frames or images) presented in 3D space and moved along varied,
// deterministic, staggered paths (descend, rise, drive-slope, float, orbit, arc, cross, hero).
// Presentation: cutout (alpha) when the asset has one, else an automatic key of plain studio backgrounds, else
// a soft-edged glass card. Graded into the scene light, warm rim light from the sun, distance haze, DOF blur,
// a soft halo behind, and a contact shadow when driving on the ground.
import { clamp, lerp, easeOutCubic, easeInCubic, easeInOutSine, easeInOutCubic, mulberry32, terrainHeight, smoothstep } from './math.js';
import { lin3 } from './presets.js';

export const PATHS = ['descend', 'rise', 'drive-slope', 'float', 'orbit', 'arc', 'cross', 'hero'];
/** Paths that park at their end pose (the others exit the frame and disappear). */
const HOLD = new Set(['descend', 'float', 'hero', 'drive-slope', 'orbit']);

/**
 * Default, deliberately non-uniform slots per path (fractions of the shot duration; sx/sy in base-camera NDC at depth d).
 * Never a formation: different depths, sides, start times and speeds.
 */
const SLOTS = {
  descend: { d: 20, x0: -0.62, x1: -0.40, y0: 1.5, y1: 0.24, t0: 0.0, t1: 0.6, size: 5.4 },
  rise: { d: 70, x0: 0.16, x1: 0.02, y0: -0.3, y1: 1.5, t0: 0.30, t1: 1.0, size: 6.0 },
  'drive-slope': { t0: 0.04, t1: 0.96, size: 5.2 },
  float: { d: 36, x0: 0.40, x1: 0.50, y0: 0.30, y1: 0.36, t0: 0.12, t1: 1.0, size: 6.0 },
  orbit: { d: 44, x0: -0.15, y0: 0.66, ax: 0.42, ad: 12, t0: 0.0, t1: 1.0, size: 5.8, turns: 0.75 },
  arc: { d: 90, x0: -1.35, x1: 1.35, y0: 0.42, y1: 0.42, apex: 0.4, t0: 0.30, t1: 0.95, size: 6.5 },
  cross: { d: 52, x0: 1.4, x1: -1.4, y0: 0.82, y1: 0.74, t0: 0.05, t1: 0.85, size: 5.6 },
  hero: { d: 16, x0: 0.0, y0: 0.0, t0: 0.0, t1: 1.0, size: 6.4 },
};

/** Fill defaults for a flyer spec (pure). `i` staggers the clip offset; `dur` = shot length. */
export function resolveFlyer(spec, i, dur, seed = 0) {
  const path = PATHS.includes(spec.path) ? spec.path : 'float';
  const s = { ...SLOTS[path], ...spec, path };
  const r = mulberry32(((seed + 1) * 9973 + i * 7919) >>> 0);
  s.t0 = (s.t0 ?? 0) * (spec.t0 == null ? dur : 1);
  s.t1 = (s.t1 ?? 1) * (spec.t1 == null ? dur : 1);
  if (spec.t0 != null) s.t0 = spec.t0;
  if (spec.t1 != null) s.t1 = spec.t1;
  s.clipOffset = spec.clipOffset ?? (i * 1.37 + r() * 0.8);
  s.clipRate = spec.clipRate ?? 1.0;
  s.phase = r() * 6.283;
  s.facing = spec.facing || 'right';
  return s;
}

/**
 * Pose of a flyer at shot time t (pure). Returns {visible, sx, sy, d} (base-camera NDC + depth) or {world:[x,y,z]} for
 * ground paths, plus {roll, dir (+1 right / -1 left), turn (−1..1 x-scale), opacity}.
 */
export function flyerPose(s, t, env) {
  const span = Math.max(s.t1 - s.t0, 1e-3);
  let u = (t - s.t0) / span;
  if (u < 0) return { visible: false };
  if (u > 1) { if (HOLD.has(s.path) && s.hold !== false) u = 1; else return { visible: false }; }
  const ph = s.phase, bob = Math.sin(t * 1.9 + ph) * 0.012, sway = Math.sin(t * 0.83 + ph * 1.3);
  let sx = 0, sy = 0, d = s.d || 30, roll = 0, dir = 1, opacity = 1, world = null;
  switch (s.path) {
    case 'descend': {
      const e = easeOutCubic(u);
      sx = lerp(s.x0, s.x1, easeInOutSine(u)); sy = lerp(s.y0, s.y1, e) + bob * smoothstep(0.6, 1, u); d = lerp(d * 1.3, d, e);
      dir = s.x1 >= s.x0 ? 1 : -1; roll = -0.10 * (1 - e) * dir + 0.02 * sway; break;
    }
    case 'rise': {
      const e = easeInCubic(Math.min(u * 1.05, 1));
      sx = lerp(s.x0, s.x1, easeInOutSine(u)); sy = lerp(s.y0, s.y1, e * 0.75 + u * 0.25); d = lerp(d, d * 1.15, u);
      dir = s.x1 >= s.x0 ? 1 : -1; roll = 0.13 * dir * smoothstep(0.1, 0.7, u) + 0.015 * sway; break;
    }
    case 'float': {
      const e = easeOutCubic(clamp(u * 3.2));
      sx = lerp(s.x0 - 1.7, s.x0, e) + (s.x1 - s.x0) * u + 0.02 * sway; sy = s.y0 + (s.y1 - s.y0) * u + 0.045 * Math.sin(t * 1.25 + ph) + 0.02 * Math.sin(t * 2.1);
      dir = 1; roll = 0.03 * Math.sin(t * 1.25 + ph + 0.8); break;
    }
    case 'orbit': {
      const a = ph + u * Math.PI * 2 * (s.turns || 0.75);
      sx = s.x0 + s.ax * Math.cos(a); d = d + s.ad * Math.sin(a); sy = s.y0 + 0.04 * Math.sin(a * 2 + 0.5) + bob;
      const vx = -Math.sin(a);
      dir = vx >= 0 ? 1 : -1; roll = 0.05 * vx; opacity = smoothstep(0, 0.08, u) * (1 - smoothstep(0.95, 1, u) * (s.t1 < env.dur - 0.01 ? 1 : 0));
      return { visible: true, sx, sy, d, roll, dir, turn: clamp(vx * 3.0, -1, 1), opacity };
    }
    case 'arc': {
      const e = easeInOutSine(u);
      sx = lerp(s.x0, s.x1, e); sy = lerp(s.y0, s.y1, e) + s.apex * Math.sin(Math.PI * e); d = d * (1 - 0.25 * Math.sin(Math.PI * e));
      dir = s.x1 >= s.x0 ? 1 : -1; roll = -0.22 * dir * Math.cos(Math.PI * e); break;
    }
    case 'cross': {
      const e = easeInOutSine(u);
      sx = lerp(s.x0, s.x1, e); sy = lerp(s.y0, s.y1, e) + 0.03 * Math.sin(u * 9 + ph);
      dir = s.x1 >= s.x0 ? 1 : -1; roll = 0.03 * Math.sin(u * 9 + ph + 1.2); break;
    }
    case 'hero': {
      if (s.at) {
        const y = terrainHeight(s.at[0], s.at[1], env.terrain) + 0.05 + 0.006 * Math.sin(t * 6.0 + ph);
        return { visible: true, world: [s.at[0], y, s.at[1]], roll: 0.004 * Math.sin(t * 0.9), dir: 1, turn: 1, opacity: 1, ground: true, flat: true };
      }
      sx = s.x0 + 0.01 * sway; sy = s.y0 + 0.012 * Math.sin(t * 1.1 + ph); d = s.d; dir = 1; roll = 0.01 * Math.sin(t * 0.9);
      break;
    }
    case 'drive-slope': {
      const g = env.slope; // {a:[x,z], b:[x,z]}
      const e = lerp(u, easeInOutCubic(u), 0.35);
      const x = lerp(g.a[0], g.b[0], e), z = lerp(g.a[1], g.b[1], e);
      const y = terrainHeight(x, z, env.terrain) + 0.06 + 0.02 * Math.abs(Math.sin(t * 7.0 + ph));
      world = [x, y, z];
      dir = g.b[0] >= g.a[0] ? 1 : -1;
      return { visible: true, world, roll: 0, dir, turn: dir, opacity: 1, ground: true, slopeU: e };
    }
    default: break;
  }
  return { visible: true, sx, sy, d, roll, dir, turn: dir, opacity };
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
uniform vec2 rimDir, texel;
uniform vec3 lightCol, ambCol, haze, rimCol;
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
  if (blurPx < 0.8) return tap(uv);
  vec4 s = vec4(0.0);
  for (int i = 0; i < 10; i++) {
    float fi = float(i); float r = sqrt((fi + 0.5) / 10.0) * blurPx; float a = fi * 2.39996;
    s += tap(uv + vec2(cos(a), sin(a)) * r * texel);
  }
  return s / 10.0;
}
float roundRect(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main(){
  vec2 uv = vUv; if (flip < 0.0) uv.x = 1.0 - uv.x;
  vec2 m = (uv - crop.xy) / (crop.zw - crop.xy);
  vec4 c = vec4(0.0);
  if (m.x >= 0.0 && m.x <= 1.0 && m.y >= 0.0 && m.y <= 1.0) c = sampleBlur(m);
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
  // grade into the scene light: warm key, ambient-tinted shadows
  float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = mix(col, col * lightCol * 1.1, 0.62) * 0.92 + ambCol * 0.07 * (1.0 - lum);
  if (mode != 2) {
    // rim light on silhouette edges that face the sun
    vec2 off = rimDir * texel * (5.0 + blurPx);
    float ao = sampleBlur(m - off).a;
    float rimD = clamp(a - ao, 0.0, 1.0);
    col += rimCol * rimD * 2.4 * rimI;
  }
  col = mix(col, haze, hazeAmt);
  gl_FragColor = vec4(col, a * opacity);
}`;

const GLOW_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform vec3 col; uniform float strength;
void main(){ vec2 p = (vUv - 0.5) * 2.0; float r = length(p * vec2(1.0, 1.6)); float a = exp(-r * r * 2.6) * strength; gl_FragColor = vec4(col * a, a); }`;

const SHADOW_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform float strength;
void main(){ vec2 p = (vUv - 0.5) * 2.0; float a = exp(-dot(p, p) * 3.0) * strength; gl_FragColor = vec4(0.0, 0.0, 0.0, a); }`;

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

/**
 * Build flyer meshes. opts: {specs, assets(name)->asset, preset, sunDir, dur, quality:{flyerTex}, env:{slope, terrain}, seed}
 * Returns {group, update(t, camera, frame), poses}.
 */
export function makeFlyers(THREE, opts) {
  const P = opts.preset, group = new THREE.Group();
  const c3 = (h) => new THREE.Color(...lin3(h));
  const flyers = [];
  const maxW = opts.quality.flyerTex || 1280;
  opts.specs.forEach((spec0, i) => {
    const s = resolveFlyer(spec0, i, opts.dur, opts.seed);
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
    // the quad shows media region [cu0,cu1]x[cv0,cv1]; crop maps quad uv -> media uv
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
      cardR: { value: 0.06 }, aspect: { value: aspect }, rimDir: { value: new THREE.Vector2(0, 1) },
      texel: { value: new THREE.Vector2(1 / Math.min(asset.w || 1280, maxW), 1 / Math.min(asset.h || 720, maxW / aspect)) },
      lightCol: { value: c3(P.light) }, ambCol: { value: c3(P.ambient) }, haze: { value: c3(P.haze) }, rimCol: { value: c3(P.sun.glow) },
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
    group.add(shadow, glow, mesh);
    flyers.push({ s, asset, src, useCut, mode, mesh, glow, shadow, uniforms, tex, scaler, qw, qh, bboxH: bh, lastImg: null, info });
  });

  const v3 = new THREE.Vector3(), v4 = new THREE.Vector3(), q = new THREE.Quaternion(), e = new THREE.Euler();
  const view = opts.view;
  function worldFromNDC(sx, sy, d) {
    return [view.base[0] + view.fwd.x * d + view.right.x * sx * d * view.tanH + view.up.x * sy * d * view.tanV,
      view.base[1] + view.fwd.y * d + view.right.y * sx * d * view.tanH + view.up.y * sy * d * view.tanV,
      view.base[2] + view.fwd.z * d + view.right.z * sx * d * view.tanH + view.up.z * sy * d * view.tanV];
  }
  const project = (p, camera) => { v4.set(p[0], p[1], p[2]).project(camera); return [v4.x, v4.y, v4.z]; };

  return {
    group, flyers,
    worldFromNDC,
    update(t, camera, dof) {
      const sunP = [camera.position.x + opts.sunDir.x * 3000, camera.position.y + opts.sunDir.y * 3000, camera.position.z + opts.sunDir.z * 3000];
      const sunS = project(sunP, camera);
      for (const f of flyers) {
        const pose = flyerPose(f.s, t, { dur: opts.dur, slope: opts.env.slope, terrain: opts.env.terrain });
        f.mesh.visible = f.glow.visible = pose.visible;
        f.shadow.visible = !!(pose.visible && pose.ground);
        if (!pose.visible) continue;
        const p = pose.world || worldFromNDC(pose.sx, pose.sy, pose.d);
        // media frame
        const ct = (t - f.s.t0) * f.s.clipRate + f.s.clipOffset;
        let img = f.src.frame ? f.src.frame(ct, { loop: true }) : f.src.image;
        if (img !== f.lastImg) {
          f.lastImg = img;
          if (f.scaler) { const g = f.scaler.getContext('2d'); g.clearRect(0, 0, f.scaler.width, f.scaler.height); g.drawImage(img, 0, 0, f.scaler.width, f.scaler.height); img = f.scaler; }
          f.tex.image = img; f.tex.needsUpdate = true;
        }
        // orientation: billboard facing the camera, rolled in screen space
        let roll = pose.roll;
        const facingSign = f.s.facing === 'left' ? -1 : 1;
        if (pose.ground) {
          if (!pose.flat) {
            const s2 = flyerPose(f.s, t + 0.08, { dur: opts.dur, slope: opts.env.slope, terrain: opts.env.terrain });
            const p2 = s2.world || p;
            const a = project(p, camera), b = project(p2, camera);
            const dx = (b[0] - a[0]) * camera.aspect, dy = b[1] - a[1];
            if (Math.hypot(dx, dy) > 1e-6) roll = clamp(Math.atan2(dy * pose.dir, dx * pose.dir), -0.14, 0.14);
          }
          f.shadow.position.set(p[0], terrainHeight(p[0], p[2], opts.env.terrain) + 0.03, p[2]);
          f.shadow.scale.set(f.s.size * 0.95, f.s.size * 0.38, 1);
          f.shadow.material.uniforms.strength.value = 0.42;
        }
        f.mesh.position.set(p[0], p[1], p[2]);
        f.mesh.quaternion.copy(camera.quaternion);
        e.set(0, 0, roll); q.setFromEuler(e); f.mesh.quaternion.multiply(q);
        const turn = pose.turn * facingSign;
        f.mesh.scale.set(f.qw * Math.max(Math.abs(turn), 0.04), f.qh, 1);
        f.uniforms.flip.value = turn < 0 ? -1 : 1;
        f.uniforms.opacity.value = pose.opacity;
        // halo behind the product
        v3.set(0, f.qh * 0.35, -0.2).applyQuaternion(f.mesh.quaternion);
        f.glow.position.set(p[0] + v3.x, p[1] + v3.y, p[2] + v3.z);
        f.glow.quaternion.copy(f.mesh.quaternion);
        f.glow.scale.set(f.qw * 1.5, f.qh * 1.6, 1);
        f.glow.material.uniforms.strength.value = 0.32 * pose.opacity;
        // depth of field, haze, rim direction
        const dist = camera.position.distanceTo(f.mesh.position);
        const cocPx = dof.cocK * Math.abs(1 / dist - 1 / dof.focus);
        const texPxPerScreenPx = (1 / f.uniforms.texel.value.x) / Math.max(f.qw * dof.pxScale / dist, 1);
        f.uniforms.blurPx.value = Math.min(cocPx * texPxPerScreenPx, 24);
        f.uniforms.hazeAmt.value = clamp((1 - Math.exp(-dist * opts.preset.fogDensity)) * 0.85, 0, 0.6);
        const ps = project(p, camera);
        let rx = (sunS[0] - ps[0]) * camera.aspect, ry = sunS[1] - ps[1];
        const cr = Math.cos(-roll), sr = Math.sin(-roll);
        [rx, ry] = [rx * cr - ry * sr, rx * sr + ry * cr];
        if (f.uniforms.flip.value < 0) rx = -rx;
        const L = Math.hypot(rx, ry) || 1;
        f.uniforms.rimDir.value.set(rx / L, ry / L);
        f.uniforms.rimI.value = opts.rim ?? 1;
      }
    },
  };
}
