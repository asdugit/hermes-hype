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
  vec2 p = vUv; float w = 1.0; vec3 acc = vec3(0.0);
  for (int i = 0; i < N; i++) { p -= d; vec3 c = texture2D(src, p).rgb; float l = max(max(c.r, c.g), c.b); acc += c * smoothstep(0.75, 1.6, l) * w; w *= 0.955; }
  gl_FragColor = vec4(acc / float(N) * onScreen, 1.0);
}`;

const FINAL_FS = /* glsl */`
precision highp float; varying vec2 vUv;
uniform sampler2D scene, mist, bloom, rays; uniform vec2 res; uniform float t;
uniform float bloomK, mistK, raysK, caK, vignK, exposure, grainK;
uniform vec3 tintHi, tintLo;
${DISPLAY}
float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
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
      // rays from the ¼ image before blurring
      if (opts.rays && sunNDC) {
        raysM.uniforms.src.value = a4.texture; raysM.uniforms.sun.value.set(sunNDC[0] * 0.5 + 0.5, sunNDC[1] * 0.5 + 0.5);
        raysM.uniforms.onScreen.value = 1 - Math.min(1, Math.max(0, Math.max(Math.abs(sunNDC[0]), Math.abs(sunNDC[1])) - 1.0) * 2.0);
        pass(raysM, r4);
      }
      blur2(a4, b4, q4[0], q4[1], 1.0); blur2(a4, b4, q4[0], q4[1], 2.2);   // wide: a soft glow, never an outline
      // bloom chain (⅛, thresholded)
      down.uniforms.src.value = a4.texture; down.uniforms.texel.value.set(1 / q4[0], 1 / q4[1]); down.uniforms.threshold.value = 0.85; pass(down, a8);
      blur2(a8, b8, q8[0], q8[1], 1.0); blur2(a8, b8, q8[0], q8[1], 2.0);
      fin.uniforms.t.value = t;
      pass(fin, null);
      renderer.autoClear = prevAuto;
    },
    dispose() { [target, a4, b4, a8, b8, r4].forEach((r) => r.dispose()); },
  };
}
