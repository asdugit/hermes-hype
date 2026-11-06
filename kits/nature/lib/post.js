// nature kit · post pipeline (no addons needed): HDR scene RT → ¼-res mist chain → ⅛-res bloom chain →
// god rays (radial blur toward the sun) → final composite at output size (upscales a lower internal res
// smoothly on the CPU tier): bloom + halation + rays + "pro-mist" diffusion, chromatic edge, vignette,
// soft-shoulder tone curve (keeps the authored pastel palette), sRGB, dither.
import { DISPLAY } from './glsl.js';

const VS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';

const DOWN_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform sampler2D src; uniform vec2 texel; uniform float threshold;
void main(){
  vec3 c = texture2D(src, vUv + texel * vec2(-1.0, -1.0)).rgb + texture2D(src, vUv + texel * vec2(1.0, -1.0)).rgb
         + texture2D(src, vUv + texel * vec2(-1.0, 1.0)).rgb + texture2D(src, vUv + texel * vec2(1.0, 1.0)).rgb;
  c *= 0.25;
  if (threshold > 0.0) { float l = max(max(c.r, c.g), c.b); float k = max(l - threshold, 0.0); k = k * k / (k + 0.25); c *= k / max(l, 1e-4); }
  gl_FragColor = vec4(min(c, vec3(40.0)), 1.0);
}`;

const BLUR_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform sampler2D src; uniform vec2 dir;
void main(){
  vec3 c = texture2D(src, vUv).rgb * 0.2270270;
  c += (texture2D(src, vUv + dir * 1.3846154).rgb + texture2D(src, vUv - dir * 1.3846154).rgb) * 0.3162162;
  c += (texture2D(src, vUv + dir * 3.2307692).rgb + texture2D(src, vUv - dir * 3.2307692).rgb) * 0.0702703;
  gl_FragColor = vec4(c, 1.0);
}`;

const RAYS_FS = /* glsl */`
precision highp float; varying vec2 vUv; uniform sampler2D src; uniform vec2 sun; uniform float onScreen;
#ifndef RAY_N
#define RAY_N 28
#endif
const int N = RAY_N;
void main(){
  vec2 d = (vUv - sun) / float(N) * 0.92;
  // per-pixel jittered start (interleaved gradient noise): without it a small bright spot is copied N times along
  // the ray = rows of evenly spaced dashes (very visible in 9:16, where the sun is far from the bottom)
  float j = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
  vec2 p = vUv + d * (0.5 - j); float w = 1.0; vec3 acc = vec3(0.0);
  for (int i = 0; i < N; i++) { p -= d; vec3 c = texture2D(src, p).rgb; float l = dot(c, vec3(0.2126, 0.7152, 0.0722)); acc += c * smoothstep(0.85, 1.7, l) * smoothstep(0.32, 0.1, length(p - sun)) * w; w *= 0.955; }   // only the sun's neighbourhood emits (bright rims on the cars must not)
  gl_FragColor = vec4(acc / float(N) * onScreen, 1.0);
}`;

const FINAL_FS = /* glsl */`
precision highp float; varying vec2 vUv;
uniform sampler2D scene, mist, bloom, rays; uniform vec2 res; uniform float t;
uniform float bloomK, mistK, raysK, caK, vignK, exposure, grainK;
uniform vec3 tintHi, tintLo, flareCol;
uniform vec2 sunUV; uniform float flareK, aspect;
${DISPLAY}
float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
// lens flare: soft ghosts strung along the sun -> centre axis + a thin anamorphic streak through the sun
vec3 ghost(vec2 uv, float f, float r, vec3 tint){
  vec2 c = sunUV + (vec2(0.5) - sunUV) * f * 2.0;
  float d = length((uv - c) * vec2(aspect, 1.0));
  float a = smoothstep(r, r * 0.55, d) * (0.55 + 0.45 * smoothstep(r * 0.2, r * 0.95, d));
  return tint * a;
}
vec3 flare(vec2 uv){
  vec3 acc = ghost(uv, 0.42, 0.030, vec3(1.0, 0.75, 0.55)) * 0.55;
  acc += ghost(uv, 0.68, 0.055, vec3(0.95, 0.62, 0.85)) * 0.30;
  acc += ghost(uv, 1.02, 0.020, vec3(0.75, 0.85, 1.0)) * 0.55;
  acc += ghost(uv, 1.30, 0.090, vec3(0.80, 0.70, 1.0)) * 0.16;
  acc += ghost(uv, 1.62, 0.040, vec3(1.0, 0.85, 0.65)) * 0.28;
  vec2 dv = (uv - sunUV) * vec2(aspect, 1.0);
  acc += flareCol * exp(-abs(dv.y) * 160.0) * exp(-abs(dv.x) * 2.6) * 0.55;
  return acc * flareCol;
}
void main(){
  vec2 uv = vUv;
  vec2 cc = uv - 0.5;
  float r2 = dot(cc, cc);
  vec3 col;
  if (caK > 0.0) {
    vec2 o = cc * r2 * caK * 0.012;
    col = vec3(texture2D(scene, uv + o).r, texture2D(scene, uv).g, texture2D(scene, uv - o).b);
  } else col = texture2D(scene, uv).rgb;
  vec3 m = texture2D(mist, uv).rgb, b = texture2D(bloom, uv).rgb, ry = texture2D(rays, uv).rgb;
  col += b * bloomK + ry * raysK;
  if (flareK > 0.0) col += flare(uv) * flareK;
  col = mix(col, max(col, m), mistK);                    // pro-mist: highlights bleed softly into the shadows
  col += m * mistK * 0.25;
  col *= exposure;
  float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col *= mix(tintLo, tintHi, smoothstep(0.05, 0.8, lum)); // split tone
  col *= 1.0 - vignK * smoothstep(0.12, 0.75, r2 * 1.6);
  col = shoulder(col);
  col = toSRGB(col);
  float n = h(uv * res + fract(t * 7.13) * 100.0) - 0.5;
  col += n * (1.0 / 255.0 + grainK);
  gl_FragColor = vec4(col, 1.0);
}`;

/**
 * Build the post pipeline. opts: {w, h, scale (internal/output), samples, rays:boolean, ca, grade}.
 * Returns {target (render the scene into this), render(renderer, sunNDC|null, t), dispose()}.
 */
export function makePost(THREE, renderer, opts) {
  const W = opts.w, H = opts.h;
  const iw = Math.max(16, Math.round(W * opts.scale)), ih = Math.max(16, Math.round(H * opts.scale));
  const hdr = { type: THREE.HalfFloatType, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: false };
  const target = new THREE.WebGLRenderTarget(iw, ih, { ...hdr, depthBuffer: true, samples: opts.samples || 0 });
  const q4 = [Math.max(8, iw >> 2), Math.max(8, ih >> 2)], q8 = [Math.max(4, iw >> 3), Math.max(4, ih >> 3)];
  const a4 = new THREE.WebGLRenderTarget(q4[0], q4[1], hdr), b4 = new THREE.WebGLRenderTarget(q4[0], q4[1], hdr);
  const a8 = new THREE.WebGLRenderTarget(q8[0], q8[1], hdr), b8 = new THREE.WebGLRenderTarget(q8[0], q8[1], hdr);
  const r4 = new THREE.WebGLRenderTarget(q4[0], q4[1], hdr);
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
  const sc = new THREE.Scene(); sc.add(quad); quad.frustumCulled = false;
  const M = (fs, uniforms) => new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: fs, uniforms, depthTest: false, depthWrite: false });
  const down = M(DOWN_FS, { src: { value: null }, texel: { value: new THREE.Vector2() }, threshold: { value: 0 } });
  const blur = M(BLUR_FS, { src: { value: null }, dir: { value: new THREE.Vector2() } });
  const raysM = M(RAYS_FS, { src: { value: null }, sun: { value: new THREE.Vector2(0.5, 0.5) }, onScreen: { value: 0 } });
  raysM.defines = { RAY_N: opts.raySamples || 28 };
  const g = opts.grade || {};
  const fin = M(FINAL_FS, {
    scene: { value: target.texture }, mist: { value: a4.texture }, bloom: { value: a8.texture }, rays: { value: r4.texture },
    res: { value: new THREE.Vector2(W, H) }, t: { value: 0 },
    bloomK: { value: g.bloom ?? 0.8 }, mistK: { value: g.mist ?? 0.15 }, raysK: { value: opts.rays ? (g.rays ?? 0.5) : 0 }, caK: { value: opts.ca ?? 1.0 },
    vignK: { value: g.vignette ?? 0.22 }, exposure: { value: g.exposure ?? 1.0 }, grainK: { value: g.grain ?? 0.0 },
    tintHi: { value: new THREE.Vector3(...(g.tintHi || [1.02, 1.0, 0.97])) }, tintLo: { value: new THREE.Vector3(...(g.tintLo || [0.97, 0.98, 1.04])) },
    flareCol: { value: new THREE.Vector3(...(g.flareCol || [1.0, 0.86, 0.7])) }, sunUV: { value: new THREE.Vector2(0.5, 0.5) }, flareK: { value: 0 },
    aspect: { value: W / H },
  });
  const pass = (mat, rt) => { quad.material = mat; renderer.setRenderTarget(rt); renderer.render(sc, cam); };
  function blur2(rtA, rtB, w, h, k = 1) {
    blur.uniforms.src.value = rtA.texture; blur.uniforms.dir.value.set(k / w, 0); pass(blur, rtB);
    blur.uniforms.src.value = rtB.texture; blur.uniforms.dir.value.set(0, k / h); pass(blur, rtA);
  }
  return {
    target, iw, ih, uniforms: fin.uniforms,
    render(sunNDC, t) {
      const prevAuto = renderer.autoClear; renderer.autoClear = true;
      // mist chain (¼, full colour)
      down.uniforms.src.value = target.texture; down.uniforms.texel.value.set(1 / iw, 1 / ih); down.uniforms.threshold.value = 0; pass(down, a4);
      blur2(a4, b4, q4[0], q4[1], 1.0); blur2(a4, b4, q4[0], q4[1], 2.2);   // wide: a soft glow, never an outline
      // rays from the BLURRED ¼ image: a sharp source (a white blossom, a chrome glint) smaller than the march step
      // is hit by only some rays = a dotted / dashed line away from the sun (hero 9:16 at 34 s); blurred sources are
      // wider than the step, so they streak smoothly and tiny ones fall under the bright-pass
      if (opts.rays && sunNDC) {
        raysM.uniforms.src.value = a4.texture; raysM.uniforms.sun.value.set(sunNDC[0] * 0.5 + 0.5, sunNDC[1] * 0.5 + 0.5);
        raysM.uniforms.onScreen.value = 1 - Math.min(1, Math.max(0, Math.max(Math.abs(sunNDC[0]), Math.abs(sunNDC[1])) - 1.0) * 2.0);
        pass(raysM, r4);
      }
      // bloom chain (⅛, thresholded)
      down.uniforms.src.value = a4.texture; down.uniforms.texel.value.set(1 / q4[0], 1 / q4[1]); down.uniforms.threshold.value = 0.85; pass(down, a8);
      blur2(a8, b8, q8[0], q8[1], 1.0); blur2(a8, b8, q8[0], q8[1], 2.0);
      fin.uniforms.t.value = t;
      if (sunNDC && (g.flare ?? 0) > 0) {
        const on = 1 - Math.min(1, Math.max(0, Math.max(Math.abs(sunNDC[0]), Math.abs(sunNDC[1])) - 0.92) * 4);
        fin.uniforms.sunUV.value.set(sunNDC[0] * 0.5 + 0.5, sunNDC[1] * 0.5 + 0.5);
        fin.uniforms.flareK.value = g.flare * on;
      } else fin.uniforms.flareK.value = 0;
      pass(fin, null);
      renderer.autoClear = prevAuto;
    },
    dispose() { [target, a4, b4, a8, b8, r4].forEach((r) => r.dispose()); },
  };
}
