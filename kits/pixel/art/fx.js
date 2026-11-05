// fx.js — small effect sprites and screen effects: emotes, dust, sparkles, impact bursts, the spinning
// blade, slash arcs, palette fades, flashes and the iris mask. All pure functions of their inputs.
import { Sprite } from './../core/gfx.js';
import { REMAP, NONE, ci, bayer } from './../core/palette.js';
import { rand } from './../core/motion.js';

const EM = { k: 'ink', w: 'white', g: 'gold', r: 'red', c: 'coral', s: 'silver' };
export const EMOTE = {
  bang: Sprite.rows(['.kkk.', 'kwgwk', 'kwgwk', 'kwgwk', 'kwgwk', '.kgk.', '.kwk.', '.kkk.', 'kwgwk', '.kkk.'], EM),
  question: Sprite.rows(['.kkkk.', 'kwwwwk', 'kwkkwk', '.k.kwk', '..kwk.', '..kwk.', '..kk..', '..kwk.', '..kk..'], EM),
  heart: Sprite.rows(['.kk.kk.', 'kcrkrrk', 'kcrrrrk', 'krrrrrk', '.krrrk.', '..krk..', '...k...'], EM),
  sweat: Sprite.rows(['..k.', '.ksk', 'kswk', 'kssk', '.kk.'], { k: 'ink', s: 'sky', w: 'white' }),
};

/** 4-frame dust puff (frame 0..3), ~10x6. */
const PUFF = [
  ['..........', '..........', '...ss.....', '..swss....', '...ss.....'],
  ['..........', '...s......', '.sswss.s..', 'sswwsss...', '.ssss.....'],
  ['...s......', '.s....s...', 's.s..s.s..', '.s.s....s.', '..........'],
  ['..s.......', '.......s..', '..........', 's.......s.', '..........'],
].map(r => Sprite.rows(r, { s: 'grey', w: 'silver' }));
export function puff(S, x, y, frame) { if (frame >= 0 && frame < 4) S.blit(PUFF[frame], Math.round(x) - 5, Math.round(y) - 5); }

/** Four-point sparkle, size 0..2. */
export function sparkle(S, x, y, size = 1, c = 'white', c2 = 'ice') {
  x = Math.round(x); y = Math.round(y);
  S.px(x, y, c);
  for (let i = 1; i <= size + 1; i++) { const k = i === size + 1 ? c2 : c; S.px(x - i, y, k); S.px(x + i, y, k); S.px(x, y - i, k); S.px(x, y + i, k); }
}

/** Impact star burst (radius R), drawn at its frame (0..3 grows then breaks up). */
export function burst(S, cx, cy, R = 14, frame = 0, cols = ['white', 'cream', 'gold', 'amber']) {
  if (frame > 3) return;
  const r = R * [0.55, 1, 0.9, 0.7][frame], hole = frame >= 2 ? r * (frame === 2 ? 0.45 : 0.75) : 0;
  for (let y = -Math.ceil(r); y <= r; y++) for (let x = -Math.ceil(r); x <= r; x++) {
    const a = Math.atan2(y, x), d = Math.hypot(x, y), spike = r * (0.42 + 0.58 * Math.abs(Math.cos(a * 4 + frame * 0.2)) ** 3);
    if (d > spike || d < hole) continue;
    S.px(cx + x, cy + y, d < spike * 0.45 ? cols[0] : d < spike * 0.7 ? cols[1] : d < spike * 0.9 ? cols[2] : cols[3]);
  }
}

// ---- the spinning blade: 4-point saw-blade, 17x17, 8 angles from two hand-drawn frames ------------
const BL = { k: 'ink', w: 'white', s: 'silver', g: 'grey', d: 'greydk', r: 'red', c: 'coral', m: 'maroon' };
const BLADE0 = Sprite.rows([
  '........k........',
  '.......kwk.......',
  '.......kwsk......',
  '......kwssk......',
  '......kwsgk......',
  '.....kkwsgkk.....',
  '....kgsdkdgdkkkk.',
  'kkkksssdrdddsswwk',
  'kwwssggrcrggsgkk.',
  '.kkkkdgdrddssk...',
  '.....kkgsgkkk....',
  '......kgsgk......',
  '......kgswk......',
  '......kssk.......',
  '.......kwk.......',
  '.......kk........',
  '........k........',
], BL);
const BLADE1 = Sprite.rows([
  '.................',
  '..kk.............',
  '.kwwk.......kk...',
  '.kwssk....kkwk...',
  '..ksssk..kswk....',
  '...ksgskksswk....',
  '....kgdrdsgk.....',
  '.....kdrcrdk.....',
  '.....krcwcrk.....',
  '.....kdrcrdk.....',
  '.....kgsdrdgk....',
  '....kwssskgsk....',
  '....kwsk..ksssk..',
  '...kwkk....kssk..',
  '...kk.......kwk..',
  '.............kk..',
  '.................',
], BL);
export const BLADE = (() => { const a = [BLADE0, BLADE1]; const out = []; for (let q = 0; q < 4; q++) for (const b of a) { let s = b; for (let i = 0; i < q; i++) s = s.rot90(); out.push(s); } return out; })();
/** Draw the blade centred at (x, y) at spin angle index (any integer; 8 per revolution). */
export function blade(S, x, y, angle, o = {}) { const s = BLADE[((angle % 8) + 8) % 8]; S.blit(s, Math.round(x) - 8, Math.round(y) - 8, o); }

/** Slash arc: crescent from angle a0..a1 (radians) at radius R, thickness th, at progress u (0..1). */
export function slashArc(S, cx, cy, R, a0, a1, u, cols = ['white', 'ice', 'sky']) {
  const head = a0 + (a1 - a0) * Math.min(1, u * 1.4), tail = a0 + (a1 - a0) * Math.max(0, u * 1.4 - 0.5);
  const n = Math.ceil(Math.abs(head - tail) * R) + 1;
  for (let i = 0; i <= n; i++) {
    const a = tail + (head - tail) * (i / n), f = i / n, th = Math.max(1, Math.round(f * 4));
    for (let k = 0; k < th; k++) { const r = R - k; S.px(cx + Math.cos(a) * r, cy + Math.sin(a) * r, k === 0 ? cols[0] : k < 2 ? cols[1] : cols[2]); }
  }
}

/** Whole-screen palette fade toward ink: level 0 (none) .. 4 (black). */
export function fade(S, level) { level = Math.max(0, Math.min(4, Math.round(level))); if (level) S.remap(REMAP.fade[level]); if (level >= 4) S.fill('ink'); }
/** Flash: 'white' | 'red' | 'gold' remap over the screen with coverage t (0..1, ordered dither). */
export function flash(S, kind, t = 1, rect = null) { if (t <= 0) return; const r = rect || { x: 0, y: 0, w: S.w, h: S.h }; S.remap(REMAP[kind], r.x, r.y, r.w, r.h, t); }

/** Iris: keep a circle of radius r around (cx, cy) (quantised to `stepPx`), fill the rest with `c`. */
export function iris(S, cx, cy, r, c = 'ink', stepPx = 8) {
  const k = ci(c), rq = Math.max(0, Math.round(r / stepPx) * stepPx), r2 = rq * rq;
  for (let y = 0; y < S.h; y++) for (let x = 0; x < S.w; x++) { const dx = x + 0.5 - cx, dy = y + 0.5 - cy; if (dx * dx + dy * dy > r2) S.d[y * S.w + x] = k; }
}

/** Seeded particle debris (shards falling with gravity) from (x, y) at time since spawn dt. */
export function debris(S, x, y, dt, n = 10, seed = 1, cols = ['grey', 'silver']) {
  for (let i = 0; i < n; i++) {
    const a = rand(seed, i) * Math.PI - Math.PI, v = 40 + rand(seed, i, 1) * 80;
    const px = x + Math.cos(a) * v * dt, py = y + Math.sin(a) * v * dt + 260 * dt * dt;
    S.rect(Math.round(px), Math.round(py), 2, 2, cols[i % cols.length]);
  }
}

/** Ordered-dither scanline wipe helper: true when pixel (x,y) is covered at progress u by a diagonal. */
export const diagCovered = (x, y, w, h, u) => (x / w + y / h) / 2 + (bayer(x, y) - 0.5) * 0.08 < u;
export { NONE };
