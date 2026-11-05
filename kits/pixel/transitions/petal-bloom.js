// petal-bloom.js — kit:pixel/petal-bloom (canvas transition, SDK §5).
// The outgoing (pixel) image bursts into petals: a radial wave from `origin` detaches the picture cell by cell;
// each cell lifts off as a crisp pixel block, then turns into a soft HD petal that flutters, spins and drifts
// away on the wind, its colour easing into pastel petal tones. Underneath, the incoming shot "blooms" from coarse
// blocks up to full resolution, with a light burst at the origin. Pure function of u (and the two surfaces).
import { RGB, REMAP } from './../core/palette.js';
import { hash32, rng } from './../core/motion.js';

const PARAMS = {
  origin: { type: 'vec2', default: [0.5, 0.55], doc: 'burst centre in 0..1 of the frame (boss-battle BUY: kit pixelPickOrigin)' },
  cell: { type: 'number', default: 0, doc: 'source px per petal (0 = auto: ~120 petals across)' },
  density: { type: 'number', default: 0.55, doc: 'fraction of cells that fly off as petals (the rest dissolve)' },
  wind: { type: 'vec2', default: [0.45, -1.0], doc: 'drift direction (x, y); negative y = up' },
  wave: { type: 'number', default: 0.55, doc: 'fraction of the transition the detach wave takes to cross the frame' },
  pastel: { type: 'bool', default: true, doc: 'petals ease into pastel petal colours as they fly' },
  bloom: { type: 'number', default: 0.55, doc: 'strength of the light burst / resolution bloom (0..1)' },
};

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const smooth = (a, b, v) => { const x = clamp01((v - a) / (b - a)); return x * x * (3 - 2 * x); };
const hexOf = (i) => `rgb(${RGB[i][0]},${RGB[i][1]},${RGB[i][2]})`;

/** Nearest palette index for an RGB triple (exact match for palette-locked sources). */
function nearestIdx(r, g, b, memo) {
  const k = (r << 16) | (g << 8) | b;
  let v = memo.get(k);
  if (v !== undefined) return v;
  let best = 0, bd = Infinity;
  for (let i = 0; i < RGB.length; i++) { const d = (RGB[i][0] - r) ** 2 + (RGB[i][1] - g) ** 2 + (RGB[i][2] - b) ** 2; if (d < bd) { bd = d; best = i; } }
  memo.set(k, best);
  return best;
}

/** Atlas of soft HD petals, one per palette colour (64x64 cells), built once per page. */
let ATLAS = null;
function petalAtlas() {
  if (ATLAS) return ATLAS;
  const S = 64, c = new OffscreenCanvas(S * RGB.length, S), g = c.getContext('2d');
  RGB.forEach(([r, gg, b], i) => {
    g.save(); g.translate(i * S + S / 2, S / 2);
    const lr = Math.min(255, r + 60), lg = Math.min(255, gg + 50), lb = Math.min(255, b + 50);
    const grad = g.createLinearGradient(0, -S * 0.42, 0, S * 0.42);
    grad.addColorStop(0, `rgb(${lr},${lg},${lb})`); grad.addColorStop(0.55, `rgb(${r},${gg},${b})`);
    grad.addColorStop(1, `rgb(${Math.round(r * 0.72)},${Math.round(gg * 0.7)},${Math.round(b * 0.75)})`);
    g.fillStyle = grad;
    g.beginPath();                                   // petal: rounded top with a notch, tapering to the base
    g.moveTo(0, S * 0.44);
    g.bezierCurveTo(-S * 0.40, S * 0.10, -S * 0.34, -S * 0.40, -S * 0.06, -S * 0.40);
    g.lineTo(0, -S * 0.32);
    g.lineTo(S * 0.06, -S * 0.40);
    g.bezierCurveTo(S * 0.34, -S * 0.40, S * 0.40, S * 0.10, 0, S * 0.44);
    g.fill();
    g.globalAlpha = 0.35; g.fillStyle = '#fff';      // soft highlight along one side
    g.beginPath(); g.ellipse(-S * 0.12, -S * 0.08, S * 0.08, S * 0.22, -0.25, 0, Math.PI * 2); g.fill();
    g.restore();
  });
  ATLAS = { canvas: c, size: S };
  return ATLAS;
}

function render(tx, u, p) {
  const P = { ...Object.fromEntries(Object.entries(PARAMS).map(([k, v]) => [k, v.default])), ...(p || {}) };
  const { g, w: W, h: H } = tx, from = tx.from, to = tx.to;
  const C = tx.cache;
  // ---- incoming shot: resolution bloom (coarse blocks -> full res) -------------------------------------
  const STEPS = [40, 32, 24, 16, 12, 8, 6, 4, 3, 2, 1];
  const ru = smooth(0.12, 0.88, u), block = STEPS[Math.min(STEPS.length - 1, Math.floor(ru * STEPS.length))];
  if (to) {
    if (block <= 1) { g.imageSmoothingEnabled = true; g.drawImage(to, 0, 0, W, H); }
    else {
      const bw = Math.max(1, Math.round(W / block)), bh = Math.max(1, Math.round(H / block));
      C.mos = C.mos || {}; let m = C.mos[block];
      if (!m) { m = new OffscreenCanvas(bw, bh); C.mos[block] = m; }
      const mg = m.getContext('2d'); mg.imageSmoothingEnabled = true; mg.imageSmoothingQuality = 'high';
      mg.clearRect(0, 0, bw, bh); mg.drawImage(to, 0, 0, bw, bh);
      g.imageSmoothingEnabled = false; g.drawImage(m, 0, 0, W, H);
    }
  } else { g.fillStyle = '#fdfcf5'; g.fillRect(0, 0, W, H); }
  if (!from) return;

  // ---- outgoing shot: cells detach in a radial wave from the origin -------------------------------------
  const sw = from.width, sh = from.height, cell = P.cell > 0 ? P.cell : Math.max(1, Math.round(sw / 120));
  const nx = Math.ceil(sw / cell), ny = Math.ceil(sh / cell), sx = W / sw, sy = H / sh;
  if (!C.src || C.src.width !== sw || C.src.height !== sh) {
    C.src = new OffscreenCanvas(sw, sh); C.mask = new OffscreenCanvas(sw, sh); C.memo = new Map();
  }
  const sg = C.src.getContext('2d', { willReadFrequently: true });
  sg.clearRect(0, 0, sw, sh); sg.drawImage(from, 0, 0);
  const img = sg.getImageData(0, 0, sw, sh), d = img.data;
  const [ox, oy] = P.origin, ocx = ox * sw, ocy = oy * sh;
  const maxD = Math.hypot(Math.max(ocx, sw - ocx), Math.max(ocy, sh - ocy));
  const seed = hash32('petal-bloom', tx.seed || 0);
  const petals = [];
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    const cx = (i + 0.5) * cell, cy = (j + 0.5) * cell;
    const r = rng(hash32(seed, i, j)), jit = r();
    const td = 0.04 + P.wave * (Math.hypot(cx - ocx, cy - ocy) / maxD) + jit * 0.06;
    if (u < td - 0.035) continue;                                   // still part of the picture
    const x0 = i * cell, y0 = j * cell, ww = Math.min(cell, sw - x0), hh = Math.min(cell, sh - y0);
    const p0 = ((y0 + (hh >> 1)) * sw + x0 + (ww >> 1)) * 4;
    const ci = nearestIdx(d[p0], d[p0 + 1], d[p0 + 2], C.memo);
    if (u < td) {                                                    // wave front: the cell flashes lighter
      const lc = RGB[REMAP.lighter[REMAP.lighter[ci]]];
      for (let y = y0; y < y0 + hh; y++) for (let x = x0; x < x0 + ww; x++) { const q = (y * sw + x) * 4; d[q] = lc[0]; d[q + 1] = lc[1]; d[q + 2] = lc[2]; }
      continue;
    }
    for (let y = y0; y < y0 + hh; y++) for (let x = x0; x < x0 + ww; x++) d[(y * sw + x) * 4 + 3] = 0;   // punch out
    const r1 = r(), r2 = r(), r3 = r(), r4 = r();
    petals.push({ i, j, cx, cy, ci, td, r1, r2, r3, r4, keep: r4 < P.density });
  }
  const mg = C.mask.getContext('2d');
  mg.putImageData(img, 0, 0);
  g.imageSmoothingEnabled = false;
  g.drawImage(C.mask, 0, 0, W, H);

  // ---- light burst at the origin ----------------------------------------------------------------------
  const burst = P.bloom * Math.max(0, Math.sin(Math.PI * clamp01((u - 0.02) / 0.5)));
  if (burst > 0.01) {
    const R = Math.max(W, H) * (0.15 + u * 0.9), gx = ox * W, gy = oy * H;
    const grd = g.createRadialGradient(gx, gy, 0, gx, gy, R);
    grd.addColorStop(0, `rgba(255,250,235,${(0.9 * burst).toFixed(3)})`); grd.addColorStop(0.35, `rgba(255,214,226,${(0.4 * burst).toFixed(3)})`); grd.addColorStop(1, 'rgba(255,214,226,0)');
    g.save(); g.globalCompositeOperation = 'lighter'; g.fillStyle = grd; g.fillRect(0, 0, W, H); g.restore();
  }

  // ---- petals ------------------------------------------------------------------------------------------
  const A = petalAtlas(), AS = A.size, cellW = cell * sx, cellH = cell * sy;
  const [wx, wy] = P.wind, wl = Math.hypot(wx, wy) || 1;
  g.save();
  for (const q of petals) {
    const life = (u - q.td) / Math.max(0.2, 1.02 - q.td);          // 0..1 over the petal's flight
    const L = clamp01(life), ease = L * L * (3 - 2 * L);
    // burst outward from the origin, then ride the wind; flutter sideways
    const rx = q.cx - ocx, ry = q.cy - ocy, rl = Math.hypot(rx, ry) || 1;
    const burstV = (0.12 + q.r1 * 0.18) * Math.max(W, H);
    const windV = (0.45 + q.r2 * 0.8) * Math.max(W, H);
    let x = q.cx * sx + (rx / rl) * burstV * Math.sqrt(L) + (wx / wl) * windV * ease * L;
    let y = q.cy * sy + (ry / rl) * burstV * 0.6 * Math.sqrt(L) + (wy / wl) * windV * ease * L;
    x += Math.sin(L * 9 + q.r3 * 6.28) * 18 * L; y += Math.cos(L * 7 + q.r4 * 6.28) * 10 * L;
    if (x < -80 || x > W + 80 || y < -80 || y > H + 80) continue;
    const pixelPhase = life < 0.14;                                  // first a crisp pixel block...
    let ci = q.ci;
    if (!q.keep && life > 0.12) continue;                           // dissolving cells: a brief lift, then gone
    if (P.pastel && life >= 0.14) ci = (q.r3 < 0.5 ? REMAP.bloomA : REMAP.bloomB)[ci];
    const alpha = 1 - smooth(0.82, 1.0, u) * (0.6 + 0.4 * q.r2);
    if (alpha <= 0.02) continue;
    g.globalAlpha = alpha;
    if (pixelPhase) {
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = hexOf(ci);
      const lift = life * 30;
      g.fillRect(Math.round(x - cellW / 2), Math.round(y - cellH / 2 - lift), Math.ceil(cellW), Math.ceil(cellH));
      continue;
    }
    // ...then a soft HD petal: spin + 3D flutter (scaleX = cos), size grows a little then shrinks with depth
    const ang = q.r1 * 6.28 + life * (4 + q.r2 * 6) * (q.r3 < 0.5 ? -1 : 1);
    const flip = Math.cos(life * (8 + q.r4 * 8) + q.r1 * 6.28);
    const size = Math.max(cellW, cellH) * (1.4 + q.r3 * 1.1) * (1 - 0.3 * L);
    const cs = Math.cos(ang), sn = Math.sin(ang), k = size / AS;
    g.setTransform(cs * flip * k, sn * flip * k, -sn * k, cs * k, x, y);
    g.imageSmoothingEnabled = true;
    g.drawImage(A.canvas, ci * AS, 0, AS, AS, -AS / 2, -AS / 2, AS, AS);
  }
  g.restore();

  // ---- soft overall bloom as the resolution resolves -----------------------------------------------------
  const glow = P.bloom * 0.35 * Math.max(0, Math.sin(Math.PI * clamp01((u - 0.3) / 0.7)));
  if (glow > 0.01) { g.save(); g.globalAlpha = glow; g.globalCompositeOperation = 'screen'; g.fillStyle = '#ffe9f0'; g.fillRect(0, 0, W, H); g.restore(); }
}

export const petalBloom = {
  id: 'kit:pixel/petal-bloom',
  def: {
    kind: 'canvas',
    describe: 'Pixel picture bursts into petals from `origin` (radial wave, blocks -> HD petals drifting on the wind) while the next shot blooms from coarse blocks to full resolution. 1.2-1.6 s.',
    params: PARAMS,
    render,
  },
};
