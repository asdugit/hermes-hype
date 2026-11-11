// Selftest page runtime: implements the window.__sr contract (showreel_core/contracts.py).
// Every frame is a pure function of t: no Math.random, Date, performance.now, timers or CSS transitions.
import { mulberry32, easeOutCubic } from './rng.mjs';

const q = new URLSearchParams(location.search);
const DUR = Number(q.get('dur') || 6);
const FPS = Number(q.get('fps') || 30);
const FONT = q.get('font') || '';            // optional local @font-face file served next to this page
const $ = (id) => document.getElementById(id);

if (FONT) {
  const style = document.createElement('style');
  style.textContent = `@font-face { font-family: 'SRTest'; src: url('./${FONT}'); font-display: block; }`;
  document.head.appendChild(style);
}

const bg = $('bg'), panel = $('panel'), title = $('title'), hud = $('hud'), img = $('img');
const code = panel.querySelector('.code');
const CODE = [
  'def render(scene, fps=30):',
  '    for i in range(frames):',
  '        t = i / fps',
  '        page.seek(t)',
  '        ffmpeg.write(page.capture())',
  '    return "out.mp4"',
];
const TITLE = 'Hype renderer selftest';
title.innerHTML = [...TITLE].map((c) => `<span>${c === ' ' ? '&nbsp;' : c}</span>`).join('');
const letters = [...title.children];

// WAAPI animation, paused and driven by currentTime (the contract's way to use CSS animations).
const pulse = $('pulse').animate(
  [{ transform: 'scale(0.6)', opacity: 0.35 }, { transform: 'scale(1.35)', opacity: 1 }],
  { duration: 1500, iterations: Infinity, direction: 'alternate', easing: 'ease-in-out' });
pulse.pause();

// Seeded noise canvas.
const nctx = $('noise').getContext('2d');
const nimg = nctx.createImageData(320, 180);

// Minimal WebGL: a rotating triangle (exercises GPU / SwiftShader paths).
const glc = $('gl');
const gl = glc.getContext('webgl', { preserveDrawingBuffer: true, antialias: true });
let glDraw = null;
if (gl) {
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER,
    'attribute vec2 p; attribute vec3 c; uniform float a; varying vec3 v;' +
    'void main(){ float s=sin(a), k=cos(a); gl_Position=vec4(p.x*k-p.y*s, (p.x*s+p.y*k)*1.6, 0., 1.); v=c; }'));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, 'precision mediump float; varying vec3 v; void main(){ gl_FragColor=vec4(v,1.); }'));
  gl.linkProgram(prog);
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, .5, .79, .95, .36, -.45, -.3, .3, .9, .8, .45, -.3, .4, .7, 1]), gl.STATIC_DRAW);
  const P = gl.getAttribLocation(prog, 'p'), C = gl.getAttribLocation(prog, 'c'), A = gl.getUniformLocation(prog, 'a');
  gl.enableVertexAttribArray(P); gl.vertexAttribPointer(P, 2, gl.FLOAT, false, 20, 0);
  gl.enableVertexAttribArray(C); gl.vertexAttribPointer(C, 3, gl.FLOAT, false, 20, 8);
  glDraw = (t) => {
    gl.viewport(0, 0, glc.width, glc.height);
    gl.clearColor(0.06, 0.07, 0.10 + 0.05 * Math.sin(t), 1); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(A, t * 0.9); gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
}

function frame(t) {
  const f = Math.round(t * FPS);
  bg.style.background = `linear-gradient(${120 + 30 * Math.sin(t * 0.5)}deg, #0b0c0e 0%, #1d2a55 55%, #3a1d4f 100%)`;
  letters.forEach((el, i) => {
    const p = easeOutCubic((t - 0.2 - i * 0.03) / 0.5);
    el.style.transform = `translateY(${(1 - p) * 6}vh)`;
    el.style.opacity = String(p);
  });
  const u = 0.5 - 0.5 * Math.cos(t * 0.8);
  panel.style.transform = `translateX(${4 + 18 * u}vw) rotateY(${-16 + 12 * Math.sin(t * 0.7)}deg) rotateX(${4 * Math.sin(t * 0.5)}deg)`;
  const shown = Math.min(CODE.length, Math.floor(t * 3) + 1);
  const text = CODE.slice(0, shown).join('\n');
  if (code.textContent !== text) code.textContent = text;
  pulse.currentTime = t * 1000;
  const r = mulberry32(f + 1), d = nimg.data;
  for (let i = 0; i < d.length; i += 4) { const v = r() * 255; d[i] = v * 0.55; d[i + 1] = v * 0.6; d[i + 2] = v; d[i + 3] = 255; }
  nctx.putImageData(nimg, 0, 0);
  nctx.fillStyle = '#c9f25c';
  nctx.fillRect(10 + ((f * 4) % 280), 70, 30, 40);
  if (glDraw) glDraw(t);
  hud.textContent = `t=${t.toFixed(3)}s  frame ${f}  ${gl ? 'webgl' : 'no-webgl'}`;
}

const fontReady = FONT
  ? document.fonts.load("400 16px 'SRTest'").then(() => {
    if (!document.fonts.check("400 16px 'SRTest'")) throw new Error('SRTest font did not load');
  })
  : Promise.resolve();

window.__sr = {
  dur: DUR, fps: FPS, w: innerWidth, h: innerHeight, cues: [], scenes: [{ i: 0, t0: 0, t1: DUR }],
  webgl: !!gl,
  ready: Promise.all([fontReady, img.decode(), document.fonts.ready]).then(() => { frame(0); }),
  seek(t) { frame(t); return new Promise((res) => requestAnimationFrame(() => res())); },
  qa() { return []; },
};
