// nature kit · sprite atlas painted procedurally on a 2D canvas (original art, seeded, deterministic).
// Channel-packed so one atlas serves every palette: R = petal/bloom luminance, G = stem/leaf/grass,
// B = flower centre; alpha = coverage. Shaders recombine: rgb = R*petalTint + G*stemTint + B*centreTint.
// Each kind is painted once and copied into 5 rows pre-blurred for depth of field (0, 1.5, 4, 8, 16 px).
import { mulberry32 } from './math.js';

export const CELL = 128;
export const BLUR_LEVELS = [0, 1.5, 4, 8, 16];
export const KINDS = ['grassA', 'grassB', 'daisy', 'buttercup', 'cosmos', 'lupine', 'babysbreath', 'poppy',
  'lavender', 'clover', 'seedhead', 'petalA', 'petalB', 'bokeh', 'blossomBig', 'daisyBig'];
export const K = Object.fromEntries(KINDS.map((k, i) => [k, i]));

const R = (a) => `rgba(255,0,0,${a})`;
const rgb = (r, g, b, a = 1) => `rgba(${r | 0},${g | 0},${b | 0},${a})`;

function blade(g, x0, y0, h, lean, w, rnd) {
  const tipX = x0 + lean, tipY = y0 - h;
  const grd = g.createLinearGradient(0, y0, 0, tipY);
  grd.addColorStop(0, rgb(0, 115, 0)); grd.addColorStop(0.6, rgb(0, 200, 0)); grd.addColorStop(1, rgb(85, 225, 0));
  g.fillStyle = grd;
  g.beginPath();
  g.moveTo(x0 - w, y0);
  g.quadraticCurveTo(x0 - w * 0.6 + lean * 0.35, y0 - h * 0.55, tipX, tipY);
  g.quadraticCurveTo(x0 + w * 0.6 + lean * 0.35, y0 - h * 0.5, x0 + w, y0);
  g.closePath(); g.fill();
}
function stem(g, x0, y0, x1, y1, w = 2.2) {
  g.strokeStyle = rgb(0, 170, 0); g.lineWidth = w; g.lineCap = 'round';
  g.beginPath(); g.moveTo(x0, y0); g.quadraticCurveTo(x0 + (x1 - x0) * 0.2, (y0 + y1) / 2, x1, y1); g.stroke();
}
function leaf(g, x, y, len, ang, w = 4) {
  g.save(); g.translate(x, y); g.rotate(ang); g.fillStyle = rgb(0, 190, 0);
  g.beginPath(); g.ellipse(len / 2, 0, len / 2, w, 0, 0, Math.PI * 2); g.fill(); g.restore();
}
function petalRing(g, cx, cy, n, len, wid, rot, shade = 0.78, notch = false) {
  for (let i = 0; i < n; i++) {
    const a = rot + (i / n) * Math.PI * 2;
    g.save(); g.translate(cx, cy); g.rotate(a);
    const grd = g.createLinearGradient(0, 0, len, 0);
    grd.addColorStop(0, rgb(255 * shade, 0, 0)); grd.addColorStop(0.5, rgb(255, 0, 0)); grd.addColorStop(1, rgb(245, 0, 0));
    g.fillStyle = grd;
    g.beginPath();
    if (notch) {
      g.moveTo(0, 0); g.quadraticCurveTo(len * 0.45, -wid * 1.25, len, -wid * 0.55); g.lineTo(len * 0.9, 0); g.lineTo(len, wid * 0.55);
      g.quadraticCurveTo(len * 0.45, wid * 1.25, 0, 0);
    } else g.ellipse(len * 0.55, 0, len * 0.5, wid, 0, 0, Math.PI * 2);
    g.fill(); g.restore();
  }
}
function centre(g, cx, cy, r) {
  const grd = g.createRadialGradient(cx - r * 0.3, cy - r * 0.3, 0, cx, cy, r);
  grd.addColorStop(0, rgb(0, 0, 255)); grd.addColorStop(1, rgb(0, 0, 175));
  g.fillStyle = grd; g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
}

const PAINT = {
  grassA(g, r) { for (let i = 0; i < 13; i++) blade(g, 64 + (r() - 0.5) * 46, 128, 62 + r() * 56, (r() - 0.5) * 46, 2.2 + r() * 1.6, r); },
  grassB(g, r) { for (let i = 0; i < 8; i++) blade(g, 64 + (r() - 0.5) * 40, 128, 40 + r() * 46, (r() - 0.5) * 60, 3.5 + r() * 2.5, r); },
  daisy(g, r) {
    stem(g, 64, 128, 60, 40); leaf(g, 62, 100, 22, -2.6); leaf(g, 63, 92, 18, -0.5);
    g.save(); g.translate(60, 38); g.scale(1, 0.62); petalRing(g, 0, 0, 15, 24, 4.2, r() * 6, 0.86); g.restore();
    centre(g, 60, 38, 6.5);
  },
  buttercup(g, r) {
    stem(g, 64, 128, 66, 52, 2); leaf(g, 64, 108, 18, -2.4, 3);
    g.save(); g.translate(66, 50); g.scale(1, 0.72); petalRing(g, 0, 0, 5, 15, 8.5, r() * 6, 0.82); g.restore();
    centre(g, 66, 50, 4);
  },
  cosmos(g, r) {
    stem(g, 64, 128, 58, 34, 2); leaf(g, 60, 92, 26, -2.8, 2.5); leaf(g, 61, 78, 20, -0.3, 2.5);
    g.save(); g.translate(58, 32); g.rotate(-0.15); g.scale(1, 0.7); petalRing(g, 0, 0, 8, 27, 9, r() * 6, 0.7, true); g.restore();
    centre(g, 58, 32, 5.5);
  },
  lupine(g, r) {
    stem(g, 64, 128, 64, 30, 3); leaf(g, 63, 112, 24, -2.5, 4); leaf(g, 64, 110, 24, -0.6, 4);
    for (let i = 0; i < 70; i++) {
      const v = i / 70, y = 98 - v * 74, wdt = 13 * (1 - v * 0.75);
      const x = 64 + (r() - 0.5) * 2 * wdt, s = 3.6 * (1 - v * 0.5) + r() * 1.5;
      g.fillStyle = rgb(170 + 85 * r(), 0, 0); g.beginPath(); g.ellipse(x, y, s, s * 0.8, 0, 0, Math.PI * 2); g.fill();
    }
  },
  babysbreath(g, r) {
    for (let i = 0; i < 7; i++) {
      const x1 = 64 + (r() - 0.5) * 70, y1 = 24 + r() * 50; stem(g, 64, 128, x1, y1, 1.2);
      for (let k = 0; k < 6; k++) { g.fillStyle = R(1); g.beginPath(); g.arc(x1 + (r() - 0.5) * 14, y1 + (r() - 0.5) * 12, 2 + r() * 2.2, 0, Math.PI * 2); g.fill(); }
    }
  },
  poppy(g, r) {
    stem(g, 64, 128, 68, 46, 2.2);
    g.save(); g.translate(68, 42);
    for (let i = 0; i < 4; i++) {
      const a = -Math.PI / 2 + (i - 1.5) * 0.75;
      const grd = g.createRadialGradient(0, 4, 2, 0, 0, 22); grd.addColorStop(0, rgb(170, 0, 0)); grd.addColorStop(1, rgb(255, 0, 0));
      g.fillStyle = grd; g.beginPath(); g.ellipse(Math.cos(a) * 9, Math.sin(a) * 7 + 2, 13, 11, a, 0, Math.PI * 2); g.fill();
    }
    centre(g, 0, 2, 4.5); g.restore();
  },
  lavender(g, r) {
    for (let s = 0; s < 3; s++) {
      const x1 = 64 + (s - 1) * 14 + (r() - 0.5) * 6, y1 = 26 + r() * 16; stem(g, 64, 128, x1, y1, 1.6);
      for (let i = 0; i < 16; i++) { const v = i / 16; g.fillStyle = rgb(190 + 65 * r(), 0, 0); g.beginPath(); g.ellipse(x1 + (r() - 0.5) * 5, y1 + v * 30, 3, 2.4, 0, 0, Math.PI * 2); g.fill(); }
    }
  },
  clover(g, r) {
    stem(g, 64, 128, 62, 58, 2); leaf(g, 62, 110, 14, -2.2, 6); leaf(g, 63, 108, 14, -0.9, 6);
    for (let i = 0; i < 46; i++) { const a = r() * Math.PI * 2, d = Math.sqrt(r()) * 12; g.fillStyle = rgb(180 + 75 * r(), 0, 0); g.beginPath(); g.ellipse(62 + Math.cos(a) * d, 54 + Math.sin(a) * d * 0.9, 3, 2, a, 0, Math.PI * 2); g.fill(); }
  },
  seedhead(g, r) {
    for (let s = 0; s < 3; s++) {
      const x1 = 64 + (s - 1) * 18 + (r() - 0.5) * 8, y1 = 14 + r() * 20; stem(g, 64 + (s - 1) * 4, 128, x1, y1 + 26, 1.4);
      for (let i = 0; i < 12; i++) { const v = i / 12; g.fillStyle = rgb(140 + 100 * v, 150, 0); g.beginPath(); g.ellipse(x1 + (i % 2 ? 3 : -3), y1 + v * 28, 2.4, 4.2, (i % 2 ? 0.5 : -0.5), 0, Math.PI * 2); g.fill(); }
    }
  },
  petalA(g) {
    const grd = g.createRadialGradient(56, 60, 2, 64, 64, 34); grd.addColorStop(0, rgb(255, 0, 0)); grd.addColorStop(1, rgb(205, 0, 0));
    g.fillStyle = grd; g.beginPath(); g.ellipse(64, 64, 26, 18, 0.4, 0, Math.PI * 2); g.fill();
  },
  petalB(g) {
    const grd = g.createLinearGradient(40, 40, 90, 90); grd.addColorStop(0, rgb(255, 0, 0)); grd.addColorStop(1, rgb(190, 0, 0));
    g.fillStyle = grd; g.beginPath(); g.moveTo(64, 100); g.bezierCurveTo(24, 76, 30, 32, 56, 34); g.quadraticCurveTo(64, 44, 72, 34);
    g.bezierCurveTo(98, 32, 104, 76, 64, 100); g.fill();
  },
  bokeh(g) {
    const grd = g.createRadialGradient(64, 64, 0, 64, 64, 40); grd.addColorStop(0, rgb(200, 0, 0, 0.75)); grd.addColorStop(0.85, rgb(235, 0, 0, 0.9)); grd.addColorStop(1, rgb(255, 0, 0, 0));
    g.fillStyle = grd; g.beginPath(); g.arc(64, 64, 40, 0, Math.PI * 2); g.fill();
  },
  blossomBig(g, r) {
    g.save(); g.translate(64, 62); g.scale(1, 0.8); petalRing(g, 0, 0, 8, 44, 15, r() * 6, 0.62, true); g.restore();
    centre(g, 64, 62, 9);
  },
  daisyBig(g, r) {
    g.save(); g.translate(64, 64); g.scale(1, 0.75); petalRing(g, 0, 0, 18, 42, 6.5, r() * 6, 0.85); g.restore();
    centre(g, 64, 64, 11);
  },
};

/**
 * Paint the atlas and return a THREE.CanvasTexture plus layout info.
 * @returns {{texture, cols:number, rows:number, cell:number}}
 */
export function makeAtlas(THREE, seed = 1) {
  const cols = KINDS.length, rows = BLUR_LEVELS.length;
  const cv = new OffscreenCanvas(KINDS.length * CELL, BLUR_LEVELS.length * CELL);

  const g = cv.getContext('2d');
  const tmp = new OffscreenCanvas(CELL, CELL);
  const tg = tmp.getContext('2d');
  KINDS.forEach((k, ci) => {
    tg.clearRect(0, 0, CELL, CELL);
    PAINT[k](tg, mulberry32((seed * 7919 + ci * 104729) >>> 0));
    BLUR_LEVELS.forEach((b, ri) => {
      g.save();
      g.beginPath(); g.rect(ci * CELL, ri * CELL, CELL, CELL); g.clip();
      g.filter = b > 0 ? `blur(${b}px)` : 'none';
      g.drawImage(tmp, ci * CELL, ri * CELL);
      g.restore();
    });
  });
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.NoColorSpace;          // channel masks, not colours
  tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter; tex.magFilter = THREE.LinearFilter;
  tex.premultiplyAlpha = false;
  tex.flipY = true;
  return { texture: tex, cols, rows, cell: CELL, canvas: cv };
}
