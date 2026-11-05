// nature kit · sky: gradient dome + baked painterly cloud layers + sun/moon with halation (+ stars at night).
// Clouds are baked ONCE per shot into angular (azimuth, elevation) textures covering exactly the region the
// camera will see (plus drift margin), so per-frame cost is two texture lookups — cheap on SwiftShader.
import { NOISE } from './glsl.js';
import { lin3 } from './presets.js';

const D2R = Math.PI / 180;

const BAKE_VS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';

const BAKE_MAIN_FS = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform vec4 region;      // azMin, azMax, elMin, elMax (rad)
uniform vec2 sunAE;       // sun az, el (rad)
uniform vec3 cLit, cMid, cShadow, cRim;
uniform float cover, seed, bandLo, bandHi;
${NOISE}
float dens(vec2 P){
  vec2 q = P * 0.62 + vec2(seed * 3.1, seed * 1.7);
  vec2 w = vec2(fbm(q * 0.5 + 3.0, 3), fbm(q * 0.5 + 9.0, 3));
  float b = billow(q * vec2(0.8, 1.0) + w * 0.55, 5);
  float big = fbm(q * 0.28 + 11.0, 3);
  return b * 0.62 + big * 0.58;
}
// plane-projected clouds near the horizon (true perspective), cross-faded into an angular field overhead
// (the plane mapping degenerates toward the zenith)
float densAE(float az, float el){
  float e = max(el, 0.0);
  float D = 1.0 / (tan(e) + 0.075);
  float w = smoothstep(0.30, 0.60, e);
  float d1 = w < 1.0 ? dens(vec2(sin(az) * D * 1.15, cos(az) * D)) : 0.0;
  float d2 = w > 0.0 ? dens(vec2(az * 3.6, e * 4.4) + 31.0) : 0.0;
  return mix(d1, d2, w);
}
void main(){
  float az = mix(region.x, region.y, vUv.x), el = mix(region.z, region.w, vUv.y);
  float eld = el * 57.2958;
  float band = smoothstep(bandLo - 3.0, bandLo + 2.0, eld) * (1.0 - smoothstep(bandHi - 6.0, bandHi + 6.0, eld));
  float d = densAE(az, el);
  float th = mix(0.84, 0.42, cover);
  float a = smoothstep(th, th + 0.055, d) * band;
  // light: march toward the sun (low, ahead) → bottoms / sun-side edges glow
  vec2 toSun = normalize(vec2(sunAE.x - az, sunAE.y - el) + vec2(0.0, -0.05));
  float acc = 0.0;
  for (int i = 1; i <= 5; i++) { vec2 s = vec2(az, el) + toSun * float(i) * 0.022; acc += max(densAE(s.x, s.y) - th + 0.06, 0.0); }
  float T = exp(-acc * 3.2);
  // painterly: soften into ~3 tones
  float Tq = mix(T, floor(T * 3.0 + 0.5) / 3.0, 0.35);
  float body = smoothstep(th, th + 0.32, d);
  vec3 col = mix(cShadow, cMid, smoothstep(0.05, 0.6, Tq));
  col = mix(col, cLit, smoothstep(0.45, 1.0, Tq));
  col = mix(col, mix(cShadow, cMid, 0.35), body * (1.0 - Tq) * 0.25);
  // silver lining near the edges, stronger near the sun
  float sunAng = acos(clamp(dot(vec3(cos(el) * sin(az), sin(el), cos(el) * cos(az)), vec3(cos(sunAE.y) * sin(sunAE.x), sin(sunAE.y), cos(sunAE.y) * cos(sunAE.x))), -1.0, 1.0));
  float near = exp(-sunAng / 0.35);
  float edge = a * (1.0 - smoothstep(th + 0.02, th + 0.16, d));
  col += cRim * edge * (0.25 + 1.6 * near) * (0.4 + 0.6 * T);
  col = mix(col, cLit * 1.15, near * 0.45 * T);
  // brushy streaks
  float br = fbm(vec2(az * 40.0, el * 160.0) + 4.0, 3);
  col *= 0.96 + 0.07 * br;
  gl_FragColor = vec4(col, a);
}`;

const BAKE_LOW_FS = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform vec4 region; uniform vec2 sunAE;
uniform vec3 cLit, cMid, cShadow, cRim;
uniform float seed, bandLo, bandHi;
${NOISE}
void main(){
  float az = mix(region.x, region.y, vUv.x), el = mix(region.z, region.w, vUv.y);
  float eld = el * 57.2958;
  float band = smoothstep(bandLo - 0.8, bandLo + 0.6, eld) * (1.0 - smoothstep(bandHi - 1.5, bandHi + 1.0, eld));
  vec2 q = vec2(az * 5.5, eld * 0.9) + seed * 7.0;
  float w = fbm(q * vec2(0.6, 1.0) + 2.0, 3);
  float n = fbm(vec2(q.x * 0.8 + w * 1.4, q.y * 1.6 + w * 0.6), 5);
  float a = smoothstep(0.54, 0.70, n) * band * 0.92;
  float sunAng = abs(az - sunAE.x);
  float near = exp(-sunAng / 0.32);
  float under = smoothstep(0.54, 0.78, fbm(vec2(q.x * 0.8 + w, q.y * 1.6 + 0.35), 4));
  vec3 col = mix(cMid, cShadow, under * 0.5);
  col = mix(col, cLit, 0.35 + 0.65 * near);
  col += cRim * near * (1.0 - smoothstep(0.54, 0.62, n)) * 1.2;
  gl_FragColor = vec4(col, a);
}`;

const DOME_VS = /* glsl */`
varying vec3 vDir;
void main(){ vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position.z = gl_Position.w * 0.99999; }`;

const DOME_FS = /* glsl */`
precision highp float;
varying vec3 vDir;
uniform float stopsEl[8]; uniform vec3 stopsCol[8]; uniform int nStops;
uniform vec3 sunDir; uniform vec3 sunCol, glowCol; uniform float sunSize, sunPower, halo, moon;
uniform sampler2D cloudsA, cloudsB; uniform vec4 regionA; uniform float driftA, driftB, t;
uniform float stars;
${NOISE}
vec3 gradient(float el){
  vec3 c = stopsCol[0];
  for (int i = 1; i < 8; i++) { if (i >= nStops) break; float e0 = stopsEl[i - 1], e1 = stopsEl[i];
    c = mix(c, stopsCol[i], smoothstep(0.0, 1.0, clamp((el - e0) / (e1 - e0), 0.0, 1.0))); }
  return c;
}
void main(){
  vec3 d = normalize(vDir);
  float el = asin(clamp(d.y, -1.0, 1.0));
  float az = atan(d.x, -d.z);
  vec3 col = gradient(max(el, 0.0));
  float ang = acos(clamp(dot(d, sunDir), -1.0, 1.0));
  float sunAz = atan(sunDir.x, -sunDir.z);
  // warm horizon glow around the sun's azimuth + atmospheric halo
  float hz = exp(-abs(az - sunAz) / 0.55) * exp(-max(el, 0.0) / 0.12);
  col = mix(col, glowCol, hz * 0.55 * (1.0 - moon));
  vec3 glow = glowCol * (exp(-ang / 0.32) * 0.45 + exp(-ang / 0.08) * 0.9) * halo;
  // clouds
  vec2 uvA = vec2((az - driftA * t - regionA.x) / (regionA.y - regionA.x), (el - regionA.z) / (regionA.w - regionA.z));
  vec2 uvB = vec2((az - driftB * t - regionA.x) / (regionA.y - regionA.x), uvA.y);
  vec4 cb = texture2D(cloudsB, uvB);
  vec4 ca = texture2D(cloudsA, uvA);
  float hazeB = 0.35, hazeA = 0.55 * exp(-max(el, 0.0) / 0.14);
  if (stars > 0.0) {
    vec2 g = vec2(az, el) * 260.0; vec2 c = floor(g); vec2 f = fract(g) - 0.5;
    float h = hash12(c); vec2 o = vec2(hash12(c + 3.1), hash12(c + 7.7)) - 0.5;
    float s = step(0.985, h) * smoothstep(0.16, 0.0, length(f - o * 0.6)) * smoothstep(0.03, 0.25, el);
    col += vec3(0.9, 0.93, 1.0) * s * (0.6 + 0.4 * sin(t * (1.0 + h * 3.0) + h * 40.0)) * stars * 2.0;
  }
  // sun / moon disc (behind clouds)
  float disc = smoothstep(sunSize, sunSize * 0.82, ang);
  col += sunCol * disc * sunPower;
  col = mix(col, mix(cb.rgb, col, hazeB), cb.a);
  col = mix(col, mix(ca.rgb, col, hazeA), ca.a);
  float occl = 1.0 - max(ca.a, cb.a) * 0.75;
  col += glow * occl;
  col += sunCol * disc * sunPower * 0.15 * (1.0 - occl);    // a little of the disc leaks through thin cloud
  gl_FragColor = vec4(col, 1.0);
}`;

/**
 * Bake one cloud layer into a render target. Returns the texture.
 * @param {object} THREE @param {THREE.WebGLRenderer} renderer
 */
function bake(THREE, renderer, fs, uniforms, w, h) {
  const rt = new THREE.WebGLRenderTarget(w, h, { type: THREE.UnsignedByteType, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: false });
  const mat = new THREE.ShaderMaterial({ vertexShader: BAKE_VS, fragmentShader: fs, uniforms, depthTest: false, depthWrite: false });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  const sc = new THREE.Scene(); sc.add(quad);
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const prev = renderer.getRenderTarget();
  renderer.setRenderTarget(rt); renderer.render(sc, cam); renderer.setRenderTarget(prev);
  mat.dispose(); quad.geometry.dispose();
  rt.texture.wrapS = rt.texture.wrapT = THREE.ClampToEdgeWrapping;
  return rt;
}

/**
 * Build the sky. opts: {preset, region:{azMin,azMax,elMin,elMax} (deg), texelsPerDeg, seed, drift (deg/s)}.
 * Returns {mesh, update(t, camera), sunDir (THREE.Vector3), dispose()}.
 */
export function makeSky(THREE, renderer, opts) {
  const P = opts.preset, R = opts.region, tpd = opts.texelsPerDeg || 16;
  const reg = new THREE.Vector4(R.azMin * D2R, R.azMax * D2R, R.elMin * D2R, R.elMax * D2R);
  const maxTex = Math.min(renderer.capabilities.maxTextureSize, 4096);
  const w = Math.min(maxTex, Math.ceil((R.azMax - R.azMin) * tpd)), h = Math.min(maxTex, Math.ceil((R.elMax - R.elMin) * tpd));
  const sunAE = new THREE.Vector2(P.sun.az * D2R, P.sun.el * D2R);
  const c = P.clouds;
  const cu = (k) => new THREE.Color(...lin3(k));
  const common = { region: { value: reg }, sunAE: { value: sunAE }, cLit: { value: cu(c.lit) }, cMid: { value: cu(c.mid) },
    cShadow: { value: cu(c.shadow) }, cRim: { value: cu(c.rim) }, seed: { value: (opts.seed % 97) * 0.37 } };
  const rtA = bake(THREE, renderer, BAKE_MAIN_FS, { ...common, cover: { value: c.cover }, bandLo: { value: c.band[0] }, bandHi: { value: c.band[1] } }, w, h);
  const rtB = bake(THREE, renderer, BAKE_LOW_FS, { ...common, bandLo: { value: c.lowBand[0] }, bandHi: { value: c.lowBand[1] } }, Math.min(maxTex, w), Math.max(64, Math.ceil(h * 0.6)));

  const sunDir = new THREE.Vector3(Math.cos(sunAE.y) * Math.sin(sunAE.x), Math.sin(sunAE.y), -Math.cos(sunAE.y) * Math.cos(sunAE.x));
  const stopsEl = new Array(8).fill(0), stopsCol = new Array(8).fill(0).map(() => new THREE.Color());
  P.sky.slice(0, 8).forEach(([e, hx], i) => { stopsEl[i] = e * D2R; stopsCol[i] = cu(hx); });
  const uniforms = {
    stopsEl: { value: stopsEl }, stopsCol: { value: stopsCol }, nStops: { value: Math.min(8, P.sky.length) },
    sunDir: { value: sunDir }, sunCol: { value: cu(P.sun.color) }, glowCol: { value: cu(P.sun.glow) },
    sunSize: { value: P.sun.size * D2R }, sunPower: { value: P.sun.power }, halo: { value: P.sun.halo }, moon: { value: P.sun.moon ? 1 : 0 },
    cloudsA: { value: rtA.texture }, cloudsB: { value: rtB.texture }, regionA: { value: reg },
    driftA: { value: (opts.drift ?? 0.22) * D2R }, driftB: { value: (opts.drift ?? 0.22) * 0.45 * D2R }, t: { value: 0 },
    stars: { value: P.stars || 0 },
  };
  const mat = new THREE.ShaderMaterial({ vertexShader: DOME_VS, fragmentShader: DOME_FS, uniforms, side: THREE.BackSide, depthWrite: false, depthTest: false });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1000, 64, 32), mat);
  mesh.renderOrder = -100; mesh.frustumCulled = false;
  return {
    mesh, sunDir,
    update(t, camera) { uniforms.t.value = t; mesh.position.copy(camera.position); },
    dispose() { rtA.dispose(); rtB.dispose(); mat.dispose(); mesh.geometry.dispose(); },
  };
}
