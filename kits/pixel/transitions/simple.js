// simple.js — pixel-disciplined cut vocabulary: kit:pixel/iris, kit:pixel/screen-slide, kit:pixel/battle-swirl.
// Canvas transitions: everything moves in whole game pixels (gp = film px per game px, from the pixel shot's res).

import { txCue } from './../cues.js';

// game px size: a hi-res pixel shot (res = film size) publishes it as canvas.dataset.gp; else from the upscale
const gpOf = (tx) => { for (const s of [tx.from, tx.to]) { const g = s && s.dataset && Number(s.dataset.gp); if (g > 0) return g; } const s = tx.from || tx.to; return s ? Math.max(1, Math.round(tx.w / s.width)) : 4; };
const snap = (v, q) => Math.round(v / q) * q;
const draw = (tx, src, x = 0, y = 0) => { if (src) { tx.g.imageSmoothingEnabled = src.width >= tx.w ? true : false; tx.g.drawImage(src, x, y, tx.w, tx.h); } };

/** Iris: a circle closes on `center` over `from` (8 game-px steps), holds black, opens over `to`. */
function irisRender(tx, u, p) {
  const { g, w, h } = tx, gp = gpOf(tx), [cx, cy] = (p.center || [0.5, 0.5]).map((v, i) => v * (i ? h : w));
  const hold = Math.max(0, Math.min(0.4, p.hold ?? 0.12)), a = (1 - hold) / 2;
  const closing = u < a, opening = u > a + hold, src = closing ? tx.from : tx.to;
  const R = Math.hypot(Math.max(cx, w - cx), Math.max(cy, h - cy));
  const k = closing ? 1 - u / a : opening ? (u - a - hold) / a : 0;
  const r = snap(R * (k * k * (3 - 2 * k)), gp * 8);
  g.fillStyle = p.color || '#0d0b1e'; g.fillRect(0, 0, w, h);
  if (r <= 0 || !src) return;
  g.save(); g.beginPath();
  // stair-stepped circle: build the clip from game-pixel rows so the edge stays pixel art
  for (let y = snap(cy - r, gp); y < cy + r; y += gp) {
    const dy = y + gp / 2 - cy, hw = Math.sqrt(Math.max(0, r * r - dy * dy));
    const x0 = snap(cx - hw, gp), x1 = snap(cx + hw, gp);
    if (x1 > x0) g.rect(x0, y, x1 - x0, gp);
  }
  g.clip(); draw(tx, src); g.restore();
}

/** Screen slide: the new screen pushes the old one out in `steps` stepped positions (default 4). */
function slideRender(tx, u, p) {
  const { w, h } = tx, gp = gpOf(tx), steps = p.steps || 4, dir = p.dir || 'left';
  const e = Math.min(1, Math.ceil(u * steps) / steps);
  const horiz = dir === 'left' || dir === 'right', sgn = dir === 'left' || dir === 'up' ? -1 : 1;
  const d = snap((horiz ? w : h) * e, gp) * sgn;
  tx.g.fillStyle = '#0d0b1e'; tx.g.fillRect(0, 0, w, h);
  if (horiz) { draw(tx, tx.from, d, 0); draw(tx, tx.to, d - sgn * w, 0); }
  else { draw(tx, tx.from, 0, d); draw(tx, tx.to, 0, d - sgn * h); }
}

/** Spiral order of an nx x ny block grid (outer ring first, clockwise, inward) -> rank 0..1 per block. Cached. */
function spiralRank(cache, nx, ny) {
  const key = `${nx}x${ny}`;
  if (cache.spiral && cache.spiral.key === key) return cache.spiral.rank;
  const rank = new Float32Array(nx * ny); let x0 = 0, y0 = 0, x1 = nx - 1, y1 = ny - 1, k = 0;
  const put = (i, j) => { rank[j * nx + i] = k++; };
  while (x0 <= x1 && y0 <= y1) {
    for (let i = x0; i <= x1; i++) put(i, y0);
    for (let j = y0 + 1; j <= y1; j++) put(x1, j);
    if (y1 > y0) for (let i = x1 - 1; i >= x0; i--) put(i, y1);
    if (x1 > x0) for (let j = y1 - 1; j > y0; j--) put(x0, j);
    x0++; y0++; x1--; y1--;
  }
  for (let i = 0; i < rank.length; i++) rank[i] /= Math.max(1, k - 1);
  cache.spiral = { key, rank };
  return rank;
}

/**
 * Battle swirl (RPG encounter): the old screen flashes three times at triple brightness (its own colours blown out,
 * never a grey wash),
 * blocks spiral in from the edges to the centre, then the battle opens with stripes sliding apart.
 */
function swirlRender(tx, u, p) {
  const { g, w, h } = tx, gp = gpOf(tx), ink = p.color || '#0d0b1e';
  if (u < 0.3) {                                                       // 3 inverted flashes on the old screen
    draw(tx, tx.from);
    const f = Math.floor(u / 0.3 * 6);
    if (f % 2 === 1 && tx.from) { g.save(); g.globalCompositeOperation = 'lighter'; draw(tx, tx.from); draw(tx, tx.from); g.restore(); }
    return;
  }
  if (u < 0.66) {                                                      // spiral of blocks closing in
    draw(tx, tx.from);
    const bs = gp * (p.block || 16), nx = Math.ceil(w / bs), ny = Math.ceil(h / bs), rank = spiralRank(tx.cache || {}, nx, ny);
    const k = (u - 0.3) / 0.36;
    g.fillStyle = ink;
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) if (rank[j * nx + i] <= k) g.fillRect(i * bs, j * bs, bs, bs);
    return;
  }
  const band = gp * (p.band || 12), n = Math.ceil(h / band), k = (u - 0.66) / 0.34;   // stripes slide open on the new screen
  draw(tx, tx.to);
  g.fillStyle = ink;
  for (let i = 0; i < n; i++) {
    const lag = (i % 3) * 0.08, kk = Math.max(0, Math.min(1, (1 - k) * 1.25 - lag));
    const len = snap(w * kk, gp * 4), y = i * band;
    if (i % 2) g.fillRect(w - len, y, len, band); else g.fillRect(0, y, len, band);
  }
}

export const iris = { id: 'kit:pixel/iris', def: { kind: 'canvas', describe: 'Pixel iris: stair-stepped circle closes on `center`, holds, opens on the next shot.', params: { center: { type: 'vec2', default: [0.5, 0.5] }, hold: { type: 'number', default: 0.12 } }, render: irisRender } };
export const screenSlide = { id: 'kit:pixel/screen-slide', def: { kind: 'canvas', describe: 'Next screen pushes the old one out in 4 stepped positions (dir left|right|up|down).', params: { dir: { type: 'string', default: 'left' }, steps: { type: 'number', default: 4 } }, render: slideRender } };
export const battleSwirl = { id: 'kit:pixel/battle-swirl', def: { kind: 'canvas', describe: 'RPG encounter: three over-bright flashes of the old screen, blocks spiral in to black, stripes slide open on the battle (0.6-0.9 s).', params: { band: { type: 'number', default: 12 }, block: { type: 'number', default: 16 } }, render: swirlRender,
  cues: () => [txCue(0, 'encounter'), txCue(0.3, 'whoosh')] } };
