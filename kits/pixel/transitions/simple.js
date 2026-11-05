// simple.js — pixel-disciplined cut vocabulary: kit:pixel/iris, kit:pixel/screen-slide, kit:pixel/battle-swirl.
// Canvas transitions: everything moves in whole game pixels (gp = film px per game px, from the pixel shot's res).

const gpOf = (tx) => { const s = tx.from || tx.to; return s ? Math.max(1, Math.round(tx.w / s.width)) : 4; };
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

/** Battle swirl: alternating stripes slam shut over `from` (with a white flash), then open on `to`. */
function swirlRender(tx, u, p) {
  const { g, w, h } = tx, gp = gpOf(tx), band = gp * (p.band || 12), n = Math.ceil(h / band);
  const half = u < 0.5, k = half ? u / 0.5 : (u - 0.5) / 0.5;
  draw(tx, half ? tx.from : tx.to);
  if (half && u > 0.08 && u < 0.2 && Math.floor(u * 40) % 2 === 0) { g.fillStyle = 'rgba(253,252,245,0.85)'; g.fillRect(0, 0, w, h); }
  g.fillStyle = p.color || '#0d0b1e';
  for (let i = 0; i < n; i++) {
    const lag = (i % 3) * 0.08, kk = Math.max(0, Math.min(1, (half ? k : 1 - k) * 1.25 - lag));
    const len = snap(w * kk, gp * 4), y = i * band;
    if (i % 2) g.fillRect(w - len, y, len, band); else g.fillRect(0, y, len, band);
  }
}

export const iris = { id: 'kit:pixel/iris', def: { kind: 'canvas', describe: 'Pixel iris: stair-stepped circle closes on `center`, holds, opens on the next shot.', params: { center: { type: 'vec2', default: [0.5, 0.5] }, hold: { type: 'number', default: 0.12 } }, render: irisRender } };
export const screenSlide = { id: 'kit:pixel/screen-slide', def: { kind: 'canvas', describe: 'Next screen pushes the old one out in 4 stepped positions (dir left|right|up|down).', params: { dir: { type: 'string', default: 'left' }, steps: { type: 'number', default: 4 } }, render: slideRender } };
export const battleSwirl = { id: 'kit:pixel/battle-swirl', def: { kind: 'canvas', describe: 'RPG encounter wipe: white flash, stripes slam shut from alternating sides, open on the battle.', params: { band: { type: 'number', default: 12 } }, render: swirlRender } };
