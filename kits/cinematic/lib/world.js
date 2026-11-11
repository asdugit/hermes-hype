// cinematic kit · the 3D world: emissive glass cards at depth, per-object depth of field (mip-biased disc blur
// per card, CoC-sized bokeh for dust), haze backdrop with one warm pool, halos, bloom, ACES, chromatic edge,
// vignette, split-tone, grain, 2.39 letterbox and a 2D type overlay — all a pure function of t.
// Ported from the approved style frame (styleframes/cinematic/world.js); camera/focus are now functions of t.
import { PAD, RADIUS } from './cards.js';

export const TPU = 1000;   // card canvas texels per world unit

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, u) => a + (b - a) * u;
export const smooth = (u) => { u = clamp(u); return u * u * (3 - 2 * u); };
export const inOut = (u) => { u = clamp(u); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };
export const outCubic = (u) => 1 - Math.pow(1 - clamp(u), 3);

/** Keyed camera: kfs = [[t, {pos:[..], look:[..], fov?, roll?}], ...] with smooth segments + a breathing drift. */
export function rig(kfs, t, o = {}) {
  let a = kfs[0], b = kfs[kfs.length - 1], u = 0;
  if (t <= kfs[0][0]) { a = b = kfs[0]; } else if (t >= b[0]) { a = b; } else {
    for (let i = 0; i < kfs.length - 1; i++) if (t <= kfs[i + 1][0]) { a = kfs[i]; b = kfs[i + 1]; u = (o.ease || inOut)((t - a[0]) / (b[0] - a[0])); break; }
  }
  const L = (k) => a[1][k].map((v, i) => lerp(v, b[1][k][i], u));
  const br = o.breath ?? 1;
  const pos = L('pos'); const look = L('look');
  pos[0] += br * 0.006 * Math.sin(t * 0.61 + 0.3); pos[1] += br * 0.004 * Math.sin(t * 0.83 + 1.1);
  return { pos, look, fov: lerp(a[1].fov ?? 30, b[1].fov ?? 30, u), roll: lerp(a[1].roll ?? 0, b[1].roll ?? 0, u) + br * 0.0025 * Math.sin(t * 0.47) };
}

const CARD_VS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }';
const CARD_FS = /* glsl */`
uniform sampler2D map; uniform vec2 texSize; uniform vec4 panel; uniform float radius;
uniform float blur; uniform float exposure; uniform float dim; uniform float rimI; uniform vec3 rimCol; uniform float sheen;
uniform vec3 band;   // texel-space rows [y0, y1] (from the top) brightened by band.z (lit PASS line, focus range)
varying vec2 vUv;
float sdRound(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main(){
  vec4 c;
  if (blur < 0.75) { c = texture2D(map, vUv); }
  else {
    float lod = log2(max(blur / 3.0, 1.0));
    c = vec4(0.0);
    for (int i = 0; i < TAPS; i++) {
      float fi = float(i); float r = sqrt((fi + 0.5) / float(TAPS)) * blur; float a = fi * 2.39996323;
      c += textureLod(map, vUv + vec2(cos(a), sin(a)) * r / texSize, lod);
    }
    c /= float(TAPS);
  }
  if (c.a < 0.03) discard;
  vec2 px = vUv * texSize;
  vec2 ctr = 0.5 * (panel.xy + panel.zw); vec2 hb = 0.5 * (panel.zw - panel.xy);
  float d = sdRound(px - ctr, hb, radius);
  float w = 1.4 + blur * 0.9;
  float rim = 1.0 - smoothstep(0.0, w, abs(d + 1.0));
  vec2 n = normalize(px - ctr + vec2(1e-3));
  float key = smoothstep(-0.2, 1.0, dot(n, normalize(vec2(-0.45, 0.9))));
  float inside = 1.0 - smoothstep(-w, w, d);
  vec3 col = c.rgb * exposure;
  float yt = texSize.y - px.y;
  if (band.z != 1.0) col *= mix(1.0, band.z, smoothstep(band.x - 6.0, band.x + 2.0, yt) * (1.0 - smoothstep(band.y - 2.0, band.y + 6.0, yt)));
  float sb = (vUv.x * 0.7 + vUv.y);
  col += sheen * inside * smoothstep(0.42, 0.0, abs(sb - 1.22)) * vec3(1.0, 0.97, 0.92);
  col *= mix(0.86, 1.04, vUv.y);
  col += rimCol * rimI * rim * key / (1.0 + blur * 0.25);
  gl_FragColor = vec4(col * dim, c.a * clamp(dim * 4.0, 0.0, 1.0));
}`;
const HALO_FS = /* glsl */`
uniform vec3 col; uniform float strength; uniform vec2 aspect; varying vec2 vUv;
void main(){ vec2 p = (vUv - 0.5) * aspect; float d = length(max(abs(p) - aspect * 0.18, 0.0));
  float g = exp(-d * d * 9.0) * strength; gl_FragColor = vec4(col * g, 1.0); }`;
const DUST_VS = /* glsl */`
attribute float aSize; attribute float aBright; attribute vec3 aColor; attribute float aDof;
uniform float focus; uniform float aperturePx; uniform float maxSize; uniform float bokehGain; uniform float t; uniform float pxScale;
varying float vA; varying vec3 vC; varying float vBig;
void main(){
  vec3 p = position + vec3(sin(t * 0.21 + position.y * 3.0), cos(t * 0.17 + position.x * 2.0), 0.0) * 0.02 * aDof;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  float depth = -mv.z;
  float coc = aDof * aperturePx * abs(depth - focus) / max(depth, 0.01);
  float size = clamp(max(aSize * pxScale, coc), 1.0, maxSize);
  gl_PointSize = size;
  vBig = smoothstep(3.0, 14.0, size);
  vA = aBright * mix(pow(aSize * pxScale / size, 2.0), bokehGain, vBig);
  vC = aColor;
  gl_Position = projectionMatrix * mv;
}`;
const DUST_FS = /* glsl */`
varying float vA; varying vec3 vC; varying float vBig;
void main(){
  float r = length(gl_PointCoord - 0.5) * 2.0;
  float soft = exp(-r * r * 3.2);
  float disc = 1.0 - smoothstep(0.82, 1.0, r);
  float ring = 0.78 + 0.42 * smoothstep(0.5, 0.95, r);
  float shape = mix(soft, disc * ring, vBig);
  if (shape < 0.002) discard;
  gl_FragColor = vec4(vC * vA * shape, 1.0);
}`;
const BACK_FS = /* glsl */`
uniform vec3 haze; uniform vec3 warm; uniform vec2 warmAt; varying vec2 vUv;
void main(){ vec2 p = vUv - 0.5;
  float g = exp(-dot(p * vec2(1.2, 1.9), p * vec2(1.2, 1.9)) * 7.0);
  float w = exp(-dot((vUv - warmAt) * vec2(1.3, 2.0), (vUv - warmAt) * vec2(1.3, 2.0)) * 18.0);
  gl_FragColor = vec4(haze * g + warm * w, 1.0); }`;

const PVS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';
const DOWN_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform sampler2D src; uniform vec2 texel; uniform float threshold;
void main(){
  vec3 c = (texture2D(src, vUv + texel * vec2(-1.0, -1.0)).rgb + texture2D(src, vUv + texel * vec2(1.0, -1.0)).rgb
          + texture2D(src, vUv + texel * vec2(-1.0, 1.0)).rgb + texture2D(src, vUv + texel * vec2(1.0, 1.0)).rgb) * 0.25;
  if (threshold > 0.0) { float l = max(max(c.r, c.g), c.b); float k = max(l - threshold, 0.0); k = k * k / (k + 0.3); c *= k / max(l, 1e-4); }
  gl_FragColor = vec4(min(c, vec3(30.0)), 1.0);
}`;
const BLUR_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform sampler2D src; uniform vec2 dir;
void main(){
  vec3 c = texture2D(src, vUv).rgb * 0.2270270;
  c += (texture2D(src, vUv + dir * 1.3846154).rgb + texture2D(src, vUv - dir * 1.3846154).rgb) * 0.3162162;
  c += (texture2D(src, vUv + dir * 3.2307692).rgb + texture2D(src, vUv - dir * 3.2307692).rgb) * 0.0702703;
  gl_FragColor = vec4(c, 1.0);
}`;
const FINAL_FS = /* glsl */`
precision highp float; varying vec2 vUv;
uniform sampler2D scene, bloomA, bloomB, overlay; uniform vec2 res; uniform float t, seed;
uniform float bloomK, exposure, grain, vig, ca, barH, flare; uniform vec2 flareAt;
float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21) + seed); p += dot(p, p + 45.32); return fract(p.x * p.y); }
vec3 aces(vec3 x){ return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }
vec3 toSRGB(vec3 c){ return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
void main(){
  vec2 fc = vUv * res;
  vec4 ov = texture2D(overlay, vec2(vUv.x, 1.0 - vUv.y));
  if (fc.y < barH || fc.y > res.y - barH) { vec3 o = ov.rgb; gl_FragColor = vec4(o + vec3((h21(floor(fc)) - 0.5) / 255.0), 1.0); return; }
  vec2 d = vUv - 0.5; float asp = res.x / res.y; vec2 da = d * vec2(asp, 1.0); float r2 = dot(da, da);
  vec2 off = d * ca * r2 * 4.0;
  vec3 c = vec3(texture2D(scene, vUv - off).r, texture2D(scene, vUv).g, texture2D(scene, vUv + off).b);
  c += (texture2D(bloomA, vUv).rgb * 0.6 + texture2D(bloomB, vUv).rgb) * bloomK;
  c += vec3(1.0, 0.86, 0.66) * flare * exp(-pow((vUv.x - flareAt.x) * 2.2, 2.0)) * (0.35 + 0.65 * exp(-pow((vUv.y - flareAt.y) * 3.0, 2.0)));
  c = aces(c * exposure);
  float v = smoothstep(1.05, 0.28, length(da * vec2(0.62, 1.0)));
  c *= mix(1.0 - vig, 1.0, v);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(c, c * vec3(0.94, 1.0, 1.07), (1.0 - l) * 0.3);
  c = mix(c, c * vec3(1.05, 1.0, 0.93), smoothstep(0.35, 1.0, l) * 0.35);
  c = toSRGB(c);
  c = c * (1.0 - ov.a) + ov.rgb;                       // type overlay (premultiplied, already display-referred)
  vec2 ip = floor(fc);
  float n = h21(ip + fract(t * 3.17) * 64.0) + h21(ip + 31.7) - 1.0;
  c += n * grain * (0.45 + 0.55 * (1.0 - abs(l - 0.4) * 1.5));
  c += (h21(ip + 7.1) - 0.5) / 255.0;
  gl_FragColor = vec4(c, 1.0);
}`;

/** Is the GL renderer a CPU rasteriser? */
export function softwareGL(renderer) {
  try { const gl = renderer.getContext(); const e = gl.getExtension('WEBGL_debug_renderer_info');
    return /swiftshader|llvmpipe|software/i.test(String(gl.getParameter(e ? e.UNMASKED_RENDERER_WEBGL : gl.RENDERER))); } catch { return false; }
}

/**
 * Build a cinematic world. o = {
 *   items: [{card, pos:[x,y,z], rot:[deg], scale, exposure, rim, halo, dim, anim?(t) -> {exposure?, dim?, band?:[y0,y1,gain], pos?, rot?}}],
 *   cam(t) -> {pos, look, fov, roll}, focus(t) -> distance, aperturePx, seed, stars, dust, motes, haze, warm, warmAt,
 *   overlay(g, t, F) — draws type on a W×H 2D canvas (F = {w, h, barH, portrait, scale}); overlayKey(t) -> string,
 *   flare(t) -> {k, at:[u,v]}, quality: 'auto'|'high'|'low', letterbox: bool, exposure, bloom }
 */
export function makeCine(ctx, o) {
  const THREE = ctx.THREE, { renderer, scene, camera } = ctx.three;
  // customization theme (film.theme.tokens, showreel_core/customize): the room's haze, warm glow and dust follow it
  const TT = (ctx.film && ctx.film.theme && ctx.film.theme.tokens) || {};
  const themeHaze = TT.bg ? new THREE.Color(TT.bg).lerp(new THREE.Color(0x8fa6c8), 0.07) : null;
  const themeWarm = TT.accent ? new THREE.Color(TT.accent).multiplyScalar(0.17) : null;
  const W = ctx.w, H = ctx.h, portrait = H > W;
  const low = o.quality === 'low' || (o.quality !== 'high' && softwareGL(renderer));
  const scale = low ? 0.67 : 1;   // text cards need more plate resolution than the meadow
  const barH = (o.letterbox ?? !portrait) ? Math.max(0, Math.round((H - W / 2.39) / 2)) : 0;
  const R = mulberry32(o.seed || 1);
  ctx.three.manual = true;
  camera.near = 0.05; camera.far = 400;

  const back = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShaderMaterial({ vertexShader: CARD_VS, fragmentShader: BACK_FS, depthWrite: false, depthTest: false,
    uniforms: { haze: { value: o.haze != null ? new THREE.Color(o.haze) : (themeHaze || new THREE.Color(0x141c28)) }, warm: { value: o.warm != null ? new THREE.Color(o.warm) : (themeWarm || new THREE.Color(0x2a1606)) }, warmAt: { value: new THREE.Vector2(...(o.warmAt ?? [0.62, 0.45])) } } }));
  back.renderOrder = -10; back.frustumCulled = false; scene.add(back);

  const aniso = renderer.capabilities.getMaxAnisotropy();
  const cards = o.items.map((L) => {
    const card = L.card;
    const tex = new THREE.CanvasTexture(card.cv);
    tex.colorSpace = THREE.SRGBColorSpace; tex.premultiplyAlpha = true; tex.anisotropy = aniso;
    tex.minFilter = THREE.LinearMipmapLinearFilter; tex.generateMipmaps = true;
    const tw = card.cv.width, th = card.cv.height, s = L.scale ?? 1;
    const geo = new THREE.PlaneGeometry(tw / TPU * s, th / TPU * s);
    const mat = new THREE.ShaderMaterial({
      vertexShader: CARD_VS, fragmentShader: CARD_FS, defines: { TAPS: low ? 12 : 24 }, transparent: true, depthWrite: true, premultipliedAlpha: true,
      blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
      uniforms: { map: { value: tex }, texSize: { value: new THREE.Vector2(tw, th) }, panel: { value: new THREE.Vector4(PAD, PAD, tw - PAD, th - PAD) },
        radius: { value: card.radius ?? RADIUS }, blur: { value: 0 }, exposure: { value: L.exposure ?? 1.0 }, dim: { value: 1 },
        rimI: { value: L.rim ?? 2.2 }, rimCol: { value: new THREE.Color(L.rimCol ?? 0xfff1df) }, sheen: { value: L.sheen ?? 0.035 }, band: { value: new THREE.Vector3(0, 0, 1) } } });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.frustumCulled = false; scene.add(mesh);
    let halo = null;
    if (L.halo !== 0) {
      const hw = geo.parameters.width * 2.0, hh = geo.parameters.height * 2.2;
      halo = new THREE.Mesh(new THREE.PlaneGeometry(hw, hh), new THREE.ShaderMaterial({ vertexShader: CARD_VS, fragmentShader: HALO_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
        uniforms: { col: { value: new THREE.Color(...card.tint) }, strength: { value: 0 }, aspect: { value: new THREE.Vector2(hw, hh) } } }));
      halo.renderOrder = -1; halo.frustumCulled = false; scene.add(halo);
    }
    return { L, card, tex, mesh, mat, halo, s };
  });

  // dust / stars / near motes around the camera's start pose
  const c0 = o.cam(0);
  const fwd0 = new THREE.Vector3(...c0.look).sub(new THREE.Vector3(...c0.pos)).normalize();
  const right0 = new THREE.Vector3().crossVectors(fwd0, new THREE.Vector3(0, 1, 0)).normalize();
  const up0 = new THREE.Vector3().crossVectors(right0, fwd0);
  const k = low ? 0.5 : 1;
  const nStar = Math.round((o.stars ?? 600) * k), nDust = Math.round((o.dust ?? 110) * k), nNear = o.motes ?? 6, N = nStar + nDust + nNear;
  const pos = new Float32Array(N * 3), size = new Float32Array(N), bright = new Float32Array(N), col = new Float32Array(N * 3), dof = new Float32Array(N);
  const tanH0 = Math.tan(THREE.MathUtils.degToRad((c0.fov ?? 30) / 2));
  const warmC = TT.accent ? new THREE.Color(TT.accent).lerp(new THREE.Color(0xffffff), 0.45) : new THREE.Color(0xffc488), coolC = new THREE.Color(0xc9d6ea), whiteC = new THREE.Color(0xf3eee6);
  for (let i = 0; i < N; i++) {
    const kind = i < nStar ? 0 : i < nStar + nDust ? 1 : 2;
    const z = kind === 0 ? 60 + R() * 120 : kind === 1 ? 2 + Math.pow(R(), 1.3) * 26 : 0.6 + R() * 2.0;
    const hx = z * tanH0 * (W / H) * 1.3, hy = z * tanH0 * 1.3;
    const sx = kind === 2 ? (R() < 0.5 ? -1 : 1) * (0.62 + R() * 0.45) : R() * 2 - 1;
    const p = new THREE.Vector3(...c0.pos).addScaledVector(fwd0, z).addScaledVector(right0, sx * hx).addScaledVector(up0, (R() * 2 - 1) * hy);
    pos.set([p.x, p.y, p.z], i * 3);
    dof[i] = kind === 0 ? 0.12 : 1.0;
    size[i] = kind === 0 ? 1.0 + R() * 0.9 : 1.3 + R() * 1.4;
    bright[i] = kind === 0 ? 0.18 + Math.pow(R(), 5) * 2.2 : kind === 1 ? 0.35 + Math.pow(R(), 3) * 1.6 : 0.6 + R() * 0.8;
    const cc = kind === 0 ? (R() < 0.25 ? coolC : whiteC) : (R() < 0.35 ? warmC : whiteC);
    col.set([cc.r, cc.g, cc.b], i * 3);
  }
  const dg = new THREE.BufferGeometry();
  dg.setAttribute('position', new THREE.BufferAttribute(pos, 3)); dg.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
  dg.setAttribute('aBright', new THREE.BufferAttribute(bright, 1)); dg.setAttribute('aColor', new THREE.BufferAttribute(col, 3)); dg.setAttribute('aDof', new THREE.BufferAttribute(dof, 1));
  const dustU = { focus: { value: 5 }, aperturePx: { value: 1 }, maxSize: { value: 90 * H / 1080 * scale }, bokehGain: { value: 0.05 }, t: { value: 0 }, pxScale: { value: scale * H / 1080 } };
  const dust = new THREE.Points(dg, new THREE.ShaderMaterial({ vertexShader: DUST_VS, fragmentShader: DUST_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: dustU }));
  dust.renderOrder = 5; dust.frustumCulled = false; scene.add(dust);

  // post targets
  const iw = Math.round(W * scale), ih = Math.round(H * scale);
  const hdr = { type: THREE.HalfFloatType, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: false };
  const target = new THREE.WebGLRenderTarget(iw, ih, { ...hdr, depthBuffer: true, samples: low ? 0 : 4 });
  const q4 = [Math.max(8, iw >> 2), Math.max(8, ih >> 2)], q8 = [Math.max(4, iw >> 3), Math.max(4, ih >> 3)];
  const a4 = new THREE.WebGLRenderTarget(...q4, hdr), b4 = new THREE.WebGLRenderTarget(...q4, hdr), a8 = new THREE.WebGLRenderTarget(...q8, hdr), b8 = new THREE.WebGLRenderTarget(...q8, hdr);
  const oc = new OffscreenCanvas(W, H), og = oc.getContext('2d');
  const otex = new THREE.CanvasTexture(oc); otex.colorSpace = THREE.NoColorSpace; otex.premultiplyAlpha = true; otex.generateMipmaps = false; otex.minFilter = THREE.LinearFilter; otex.flipY = false;
  const pcam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1), quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2)), psc = new THREE.Scene();
  quad.frustumCulled = false; psc.add(quad);
  const M = (fs, u) => new THREE.ShaderMaterial({ vertexShader: PVS, fragmentShader: fs, uniforms: u, depthTest: false, depthWrite: false });
  const down = M(DOWN_FS, { src: { value: null }, texel: { value: new THREE.Vector2() }, threshold: { value: 0 } });
  const blur = M(BLUR_FS, { src: { value: null }, dir: { value: new THREE.Vector2() } });
  const fin = M(FINAL_FS, { scene: { value: target.texture }, bloomA: { value: a4.texture }, bloomB: { value: a8.texture }, overlay: { value: otex },
    res: { value: new THREE.Vector2(W, H) }, t: { value: 0 }, seed: { value: ((o.seed || 1) % 97) / 97 },
    bloomK: { value: o.bloom ?? 0.6 }, exposure: { value: o.exposure ?? 1.08 }, grain: { value: o.grain ?? 0.03 }, vig: { value: o.vignette ?? 0.45 },
    ca: { value: low ? 0 : 0.0012 }, barH: { value: barH }, flare: { value: 0 }, flareAt: { value: new THREE.Vector2(0.5, 0.5) } });
  const pass = (mat, rt) => { quad.material = mat; renderer.setRenderTarget(rt); renderer.render(psc, pcam); };
  const blur2 = (A, B, w, h, kk) => { blur.uniforms.src.value = A.texture; blur.uniforms.dir.value.set(kk / w, 0); pass(blur, B); blur.uniforms.src.value = B.texture; blur.uniforms.dir.value.set(0, kk / h); pass(blur, A); };

  const F = { w: W, h: H, barH, portrait, scale: H / 1080, rail: o.rail };
  let lastKey = null;
  const v = new THREE.Vector3();
  const aperture0 = (o.aperturePx ?? 26) * (H / 1080);

  function render(t) {
    const c = o.cam(t);
    camera.fov = c.fov ?? 30; camera.aspect = W / H; camera.updateProjectionMatrix();
    camera.position.set(...c.pos); camera.up.set(0, 1, 0); camera.lookAt(...c.look); camera.rotateZ(c.roll || 0); camera.updateMatrixWorld(true);
    const backDist = 140, vh = 2 * backDist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    back.scale.set(vh * camera.aspect * 1.1, vh * 1.1, 1);
    back.position.copy(camera.position).add(camera.getWorldDirection(v).multiplyScalar(backDist)); back.quaternion.copy(camera.quaternion);
    const focus = o.focus(t), apertureCss = aperture0 * (o.aperture ? o.aperture(t) : 1);
    const tanHalf = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    for (const cd of cards) {
      const an = cd.L.anim ? cd.L.anim(t) || {} : {};
      const p = an.pos || cd.L.pos, r = an.rot || cd.L.rot || [0, 0, 0];
      cd.mesh.position.set(...p); cd.mesh.rotation.set(...r.map(THREE.MathUtils.degToRad)); cd.mesh.updateMatrixWorld();
      if (an.refresh) { cd.tex.needsUpdate = true; }
      v.copy(cd.mesh.position).applyMatrix4(camera.matrixWorldInverse);
      const depth = Math.max(-v.z, 0.05);
      const cocPx = apertureCss * Math.abs(depth - focus) / depth;
      const pxPerUnit = (H * scale) / (2 * depth * tanHalf);
      cd.mat.uniforms.blur.value = Math.min(cocPx * scale / (pxPerUnit * cd.s) * TPU, 220);
      const dimv = (an.dim ?? cd.L.dim ?? 1) * Math.exp(-Math.max(0, depth - 3) * (o.aerial ?? 0.035));
      cd.mat.uniforms.dim.value = dimv;
      cd.mat.uniforms.exposure.value = an.exposure ?? cd.L.exposure ?? 1;
      if (an.band) cd.mat.uniforms.band.value.set(...an.band); else cd.mat.uniforms.band.value.set(0, 0, 1);
      cd.mesh.visible = dimv > 0.003;
      if (cd.halo) { cd.halo.position.copy(cd.mesh.position); cd.halo.quaternion.copy(cd.mesh.quaternion); cd.halo.translateZ(-0.06); cd.halo.material.uniforms.strength.value = (cd.L.halo ?? 0.08) * dimv; cd.halo.visible = cd.mesh.visible; }
    }
    dustU.focus.value = focus; dustU.aperturePx.value = apertureCss * scale; dustU.t.value = t;
    // overlay type
    const key = o.overlayKey ? o.overlayKey(t) : String(Math.round(t * 30));
    if (key !== lastKey) {
      lastKey = key;
      og.setTransform(1, 0, 0, 1, 0, 0); og.clearRect(0, 0, W, H);
      if (o.overlay) o.overlay(og, t, F);
      otex.needsUpdate = true;
    }
    const fl = o.flare ? o.flare(t) : null;
    fin.uniforms.flare.value = fl ? fl.k : 0; if (fl) fin.uniforms.flareAt.value.set(...fl.at);
    fin.uniforms.t.value = t;
    renderer.setRenderTarget(target); renderer.setClearColor(0x050608, 1); renderer.clear(true, true, true);
    renderer.render(scene, camera);
    down.uniforms.src.value = target.texture; down.uniforms.texel.value.set(1 / iw, 1 / ih); down.uniforms.threshold.value = o.threshold ?? 0.9; pass(down, a4);
    blur2(a4, b4, q4[0], q4[1], 1.0);
    down.uniforms.src.value = a4.texture; down.uniforms.texel.value.set(1 / q4[0], 1 / q4[1]); down.uniforms.threshold.value = 0; pass(down, a8);
    blur2(a8, b8, q8[0], q8[1], 1.0); blur2(a8, b8, q8[0], q8[1], 2.0);
    pass(fin, null);
  }
  return { render, F, low, barH, cards };
}
