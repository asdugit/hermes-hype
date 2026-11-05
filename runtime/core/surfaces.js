// Per-shot drawing surfaces for the four layers ('2d', 'three', 'webgl', 'dom') and three.js loading.

let threePromise = null;

/** Lazily import three.js r170 + the SDK addons through the page's import map. */
export function loadThree() {
  if (threePromise) return threePromise;
  threePromise = (async () => {
    let THREE;
    try {
      THREE = await import('three');
    } catch (err) {
      throw new Error(`three.js is not available in this job (vendor/three missing or no import map): ${err.message}`);
    }
    const mods = await Promise.all([
      import('three/addons/postprocessing/EffectComposer.js'),
      import('three/addons/postprocessing/RenderPass.js'),
      import('three/addons/postprocessing/UnrealBloomPass.js'),
      import('three/addons/postprocessing/BokehPass.js'),
      import('three/addons/postprocessing/OutputPass.js'),
      import('three/addons/postprocessing/ShaderPass.js'),
      import('three/addons/loaders/GLTFLoader.js'),
    ]);
    const addons = Object.assign({}, ...mods);
    return { THREE, addons };
  })();
  threePromise.catch(() => { threePromise = null; });
  return threePromise;
}

const VERT = `#version 300 es
in vec2 p; out vec2 vUv;
void main() { vUv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;

/**
 * ctx.shader(fragSource) for 'webgl' shots: a full-screen-triangle program.
 * The fragment shader gets `in vec2 vUv` and may declare uniforms u_res (vec2) and u_time (float).
 * Returns {program, draw(uniforms)} where uniforms = {name: number | number[] (vec2-4) | {mat: number[]}}.
 */
export function makeShader(gl, frag) {
  const compile = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(s);
      gl.deleteShader(s);
      throw new Error(`shader compile failed: ${log}`);
    }
    return s;
  };
  const src = /^\s*#version/.test(frag) ? frag : `#version 300 es\nprecision highp float;\n${frag}`;
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, src));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(`shader link failed: ${gl.getProgramInfoLog(prog)}`);
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.bindVertexArray(null);
  const locs = new Map();
  const uloc = (n) => {
    if (!locs.has(n)) locs.set(n, gl.getUniformLocation(prog, n));
    return locs.get(n);
  };
  return {
    program: prog,
    draw(uniforms = {}) {
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
      gl.useProgram(prog);
      const all = { u_res: [gl.drawingBufferWidth, gl.drawingBufferHeight], ...uniforms };
      for (const [n, v] of Object.entries(all)) {
        const l = uloc(n);
        if (l == null) continue;
        if (typeof v === 'number') gl.uniform1f(l, v);
        else if (Array.isArray(v)) [null, gl.uniform1fv, gl.uniform2fv, gl.uniform3fv, gl.uniform4fv][v.length]?.call(gl, l, v);
        else if (v && v.mat) (v.mat.length === 9 ? gl.uniformMatrix3fv : gl.uniformMatrix4fv).call(gl, l, false, v.mat);
        else if (v && v.int != null) gl.uniform1i(l, v.int);
      }
      gl.bindVertexArray(vao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindVertexArray(null);
    },
  };
}

/**
 * Create the surface for one shot instance.
 * @returns {{el, layer, w, h, pixel, canvas?, g?, gl?, root?, three?, THREE?, addons?, dispose()}}
 */
export async function createSurface(layer, { w, h, filmW, filmH, upscale, sceneId }) {
  const el = document.createElement('div');
  el.className = 'sr-shot';
  el.dataset.scene = sceneId;
  const pixel = (w < filmW || h < filmH) && upscale !== 'smooth';
  const s = { el, layer, w, h, pixel };
  const mkCanvas = () => {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    c.className = 'sr-surface';
    if (pixel) { c.style.imageRendering = 'pixelated'; c.dataset.pixel = '1'; }
    el.appendChild(c);
    return c;
  };
  if (layer === '2d') {
    s.canvas = mkCanvas();
    s.g = s.canvas.getContext('2d');
    s.g.imageSmoothingEnabled = !pixel;
    s.dispose = () => { s.canvas.width = 1; s.canvas.height = 1; };
  } else if (layer === 'webgl') {
    s.canvas = mkCanvas();
    s.gl = s.canvas.getContext('webgl2', { preserveDrawingBuffer: true, antialias: true, premultipliedAlpha: true, alpha: true });
    if (!s.gl) throw new Error('WebGL2 is not available in this browser (layer "webgl")');
    s.dispose = () => { const ext = s.gl.getExtension('WEBGL_lose_context'); if (ext) ext.loseContext(); };
  } else if (layer === 'three') {
    const { THREE, addons } = await loadThree();
    s.canvas = mkCanvas();
    const renderer = new THREE.WebGLRenderer({
      canvas: s.canvas, antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(1);
    renderer.setSize(w, h, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, w / h, 0.1, 2000);
    camera.position.set(0, 0, 10);
    const three = { renderer, scene, camera, manual: false };
    three.render = () => renderer.render(three.scene, three.camera);
    s.three = three; s.THREE = THREE; s.addons = addons;
    s.dispose = () => {
      three.scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
        for (const m of mats) {
          for (const v of Object.values(m)) if (v && v.isTexture) v.dispose();
          m.dispose();
        }
      });
      renderer.dispose();
      renderer.forceContextLoss();
    };
  } else if (layer === 'dom') {
    const root = document.createElement('div');
    root.className = 'sr-root';
    root.style.width = `${w}px`;
    root.style.height = `${h}px`;
    if (w !== filmW || h !== filmH) {
      root.style.transformOrigin = '0 0';
      root.style.transform = `scale(${filmW / w}, ${filmH / h})`;
    }
    el.appendChild(root);
    s.root = root;
    s.dispose = () => { root.replaceChildren(); };
  } else {
    throw new Error(`unknown layer '${layer}' (use '2d', 'three', 'webgl' or 'dom')`);
  }
  return s;
}
