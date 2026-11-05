// dungeon.js — torch-lit dungeon set: vaulted ceiling, brick back wall, flagstone floor, torches with
// flicker + dithered light pools, banners, chains, pillars, and the sealed boss door (with open animation).
// All functions draw into a Screen in WORLD coordinates shifted by an integer camera x (camX).
import { Sprite } from './../core/gfx.js';
import { REMAP } from './../core/palette.js';
import { rand, flicker, step } from './../core/motion.js';
import { drawText, measure } from './../core/text.js';

/** Brick back wall + vaulted ceiling between y=top and y=floorY. */
export function wall(S, camX, { top = 26, floorY = 200, seed = 11, tint = null, skip = null } = {}) {
  const W = S.w;
  // ceiling: dark vault with ribs every 96 px
  S.vbands(0, 0, W, top, ['ink', 'ink', 'night'], 3);
  const rib = 96;
  for (let k = Math.floor(camX / rib) - 1; k <= Math.floor((camX + W) / rib) + 1; k++) {
    const x = k * rib - camX;
    for (let i = -rib / 2; i <= rib / 2; i++) { // shallow arch of the vault, 2 px thick
      const y = Math.round(top - 2 - (1 - (i / (rib / 2)) ** 2) * (top - 8));
      S.rect(x + i, y, 1, 2, 'greydk'); S.px(x + i, y, 'grey');
    }
    S.rect(x - 2, 0, 5, top, 'night'); S.rect(x - 1, 0, 1, top, 'greydk');
  }
  // bricks: 16x8 running bond, per-brick seeded shade (mostly one value: texture, not noise)
  const bh = 8, bw = 16;
  for (let y = top; y < floorY; y += bh) {
    const row = Math.floor((y - top) / bh), off = (row & 1) * (bw / 2);
    for (let bx = Math.floor((camX - off) / bw) - 1; bx <= Math.floor((camX - off + W) / bw) + 1; bx++) {
      const x = bx * bw + off - camX, r = rand(seed, bx, row);
      const face = r < 0.07 ? 'night' : r > 0.95 ? 'navy' : 'greydk';
      S.rect(x, y, bw, bh, face);
      S.rect(x, y, bw - 1, 1, r > 0.3 ? 'grey' : 'greydk');           // lit top edge
      S.rect(x + bw - 1, y, 1, bh, 'night'); S.rect(x, y + bh - 1, bw, 1, 'ink');   // mortar
      if (r > 0.92) { S.px(x + 4, y + 3, 'ink'); S.px(x + 5, y + 4, 'ink'); S.px(x + 6, y + 4, 'ink'); S.px(x + 7, y + 5, 'ink'); } // crack
      if (r > 0.86 && r < 0.89 && y > floorY - 40) { S.rect(x + 2, y + bh - 2, 5, 1, 'forestdk'); S.px(x + 3, y + bh - 3, 'forest'); } // moss low on the wall
    }
  }
  // pilasters every 128 px (torches mount on them): dressed stone with plinth and capital
  for (let k = Math.floor(camX / 128) - 1; k <= Math.floor((camX + W) / 128) + 1; k++) {
    const x = k * 128 - 12 - camX;
    if (skip && skip(k * 128)) continue;
    S.rect(x, top, 24, floorY - top, 'greydk'); S.rect(x, top, 2, floorY - top, 'grey'); S.rect(x + 22, top, 2, floorY - top, 'night');
    for (let y = top + 12; y < floorY; y += 16) { S.rect(x, y, 24, 1, 'ink'); S.rect(x, y + 1, 22, 1, 'grey'); }
    S.rect(x - 4, top, 32, 6, 'grey'); S.rect(x - 4, top + 6, 32, 1, 'ink'); S.rect(x - 4, top, 32, 1, 'silver');
    S.rect(x - 4, floorY - 10, 32, 8, 'grey'); S.rect(x - 4, floorY - 10, 32, 1, 'silver'); S.rect(x - 4, floorY - 3, 32, 1, 'ink');
  }
  // skirting ledge
  S.rect(0, floorY - 4, W, 1, 'grey'); S.rect(0, floorY - 3, W, 2, 'greydk'); S.rect(0, floorY - 1, W, 1, 'ink');
  if (tint) S.remap(tint, 0, 0, W, floorY);
}

/** Flagstone floor from floorY to the bottom, rows growing taller toward the viewer. */
export function floor(S, camX, { floorY = 200, seed = 5 } = {}) {
  const W = S.w, H = S.h;
  S.rect(0, floorY, W, H - floorY, 'night');
  let y = floorY, k = 0;
  while (y < H) {
    const rh = 5 + k * 2, sw = 24 + k * 6, off = (k & 1) * (sw >> 1);
    // parallax: nearer rows scroll a little faster
    const cx = Math.round(camX * (1 + k * 0.08));
    for (let s = Math.floor((cx - off) / sw) - 1; s <= Math.floor((cx - off + W) / sw) + 1; s++) {
      const x = s * sw + off - cx, r = rand(seed, s, k);
      S.rect(x, y, sw, rh, r < 0.85 ? 'greydk' : 'night');
      S.rect(x, y, sw - 1, 1, r < 0.85 ? 'grey' : 'greydk');
      S.rect(x + sw - 1, y, 1, rh, 'ink');
    }
    S.rect(0, y + rh - 1, W, 1, 'ink');
    y += rh; k++;
  }
  S.dither(0, floorY, W, 6, 'ink', 0.5);   // contact shadow under the wall
}

const FLAME = [
  ['...w...', '..wc...', '..cgc..', '.cgagc.', '.gaAag.', '.aArAa.', '..rAr..', '...r...'],
  ['...c...', '...wc..', '..cgc..', '.cgagc.', '.gaAag.', '.aArAa.', '..rAr..', '...r...'],
  ['..w....', '..cw...', '.ccgc..', '.cgagc.', '.gaAag.', '.aArAa.', '..rAr..', '...r...'],
  ['....w..', '...cw..', '..cgc..', '.cgagc.', '.gaAag.', '.aArAa.', '..rAr..', '...r...'],
];
const FMAP = { w: 'white', c: 'cream', g: 'gold', a: 'amber', A: 'red', r: 'maroon' };
const FLAMES = FLAME.map(r => Sprite.rows(r, FMAP));
const SCONCE = Sprite.rows(['kGGGGGk', '.kGDGk.', '..kGk..', '..kDk..', '.kGDk..', 'kDk....'], { k: 'ink', G: 'grey', D: 'greydk' });

/** Light sources of torches at world xs (flickering radius) in screen coords, for Screen.light(). */
export function torchLights(camX, xs, wy, t, { seed = 0, r = 58, floorY = 200 } = {}) {
  const out = [];
  for (const wx of xs) {
    const f = flicker(t, seed + wx), rr = r + Math.round(f * 3) * 2, x = wx - camX;
    if (x < -rr * 2 || x > 2000) continue;
    out.push({ x, y: wy, r: rr, sy: 1.15, k: 1 }, { x, y: floorY + 30, r: rr * 1.1, sy: 0.35, k: 0.8 });
  }
  return out;
}
/** Dungeon lighting levels: dark ambient -> dim -> stone -> warm -> hot (for Screen.light). */
export const DUNGEON_LEVELS = [REMAP.fade[2], REMAP.fade[1], REMAP.warm, REMAP.warm2];

/** Light pool of a torch at world (wx, wy) — call BEFORE drawing sprites so they stay unlit-crisp. */
export function torchLight(S, camX, wx, wy, t, { seed = 0, r = 42, floorY = 200 } = {}) {
  const f = flicker(t, seed + wx), rr = r + Math.round(f * 4) * 2, x = wx - camX;
  if (x < -rr * 2 || x > S.w + rr * 2) return;
  S.glow(x, wy, rr, REMAP.warm, 1.2);
  S.glow(x, wy, rr * 0.45, REMAP.warm2, 1.3);
  S.glow(x, floorY + 6, rr * 0.9, REMAP.warm, 1.0, 0.25);
}
/** Torch sconce + animated flame at world (wx, wy) = flame base. */
export function torch(S, camX, wx, wy, t, { seed = 0 } = {}) {
  const x = wx - camX; if (x < -10 || x > S.w + 10) return;
  S.blit(SCONCE, x - 3, wy);
  const fr = Math.floor(step(t, 10) * 10 + rand(seed, wx) * 4) & 3;
  S.blit(FLAMES[fr], x - 3, wy - 8);
  if (rand(seed, wx, Math.floor(t * 6)) > 0.7) S.px(x + Math.round(rand(seed, wx, Math.floor(t * 6) + 1) * 4) - 2, wy - 11 - (Math.floor(t * 12) % 4), 'gold'); // ember
}

/** Hanging banner (maroon cloth, gold sigil) at world x, top y. */
export function banner(S, camX, wx, y, { h = 40, sway = 0 } = {}) {
  const x = Math.round(wx - camX); if (x < -20 || x > S.w + 20) return;
  S.rect(x - 2, y - 2, 18, 2, 'brown'); S.rect(x - 2, y - 2, 18, 1, 'tan');
  for (let j = 0; j < h; j++) {
    const dx = Math.round(Math.sin((j / h) * 2 + sway) * (j / h) * 1.5);
    S.rect(x + dx, y + j, 14, 1, 'maroon'); S.px(x + dx, y + j, 'ink'); S.px(x + dx + 13, y + j, 'ink'); S.px(x + dx + 1, y + j, 'red');
  }
  for (let i = 0; i < 7; i++) { S.px(x + i * 2, y + h, 'maroon'); S.px(x + i * 2, y + h + 1, 'ink'); }
  // sigil: diamond with an eye
  const cx = x + 7, cy = y + Math.round(h * 0.45);
  for (let k = 0; k < 5; k++) { S.rect(cx - k, cy - 4 + k, 1, 1, 'gold'); S.rect(cx + k, cy - 4 + k, 1, 1, 'gold'); S.rect(cx - k, cy + 4 - k, 1, 1, 'gold'); S.rect(cx + k, cy + 4 - k, 1, 1, 'gold'); }
  S.rect(cx - 1, cy, 3, 1, 'amber'); S.px(cx, cy, 'cream');
}

/** Hanging chain from the ceiling (world x), length in px; swings slightly. */
export function chain(S, camX, wx, len, t = 0) {
  const x = Math.round(wx - camX); if (x < -4 || x > S.w + 4) return;
  for (let j = 0; j < len; j += 3) { const dx = Math.round(Math.sin(t * 1.6 + wx) * (j / len) * 1.2); S.px(x + dx, j, j % 6 ? 'grey' : 'greydk'); S.px(x + dx, j + 1, 'greydk'); S.px(x + dx + ((j / 3) & 1 ? 1 : -1), j + 1, 'ink'); }
}

/** Foreground pillar silhouette at screen x (already parallaxed), spanning the full height. */
export function fgPillar(S, x, { w = 26, floorY = 200 } = {}) {
  x = Math.round(x); if (x < -w || x > S.w) return;
  S.rect(x, 0, w, S.h, 'ink');
  S.rect(x + 2, 0, 2, S.h, 'night'); S.rect(x + w - 3, 0, 1, S.h, 'night');
  for (let y = 18; y < S.h; y += 24) S.rect(x, y, w, 2, 'night');
  S.rect(x - 3, floorY + 34, w + 6, 6, 'ink'); S.rect(x - 3, floorY + 34, w + 6, 1, 'night');
}

/** Skull + bones floor clutter. */
export function bones(S, camX, wx, y) {
  const x = Math.round(wx - camX); if (x < -10 || x > S.w + 10) return;
  S.blit(SKULL, x, y - SKULL.h);
}
const SKULL = Sprite.rows(['..kkkk...', '.kwwwwk..', 'kwwwwwwk.', 'kwkkwkwk.', 'kwkkwkwk.', '.kwwwwk.k', 'kkwkwkkwk', 'kwk.kk.k.'], { k: 'ink', w: 'silver' });

/**
 * The sealed boss door, centred at world x `wx`, standing on floorY.
 * o: {open 0..1 (halves swing), chains 0..1 (1 intact, 0 shattered), label ('LOCKED BOSS'), glow t, eyes}
 * Returns the door's opening rect in screen coords {x, y, w, h}.
 */
export function bossDoor(S, camX, wx, floorY, t, o = {}) {
  const open = o.open ?? 0, chains = o.chains ?? 1, dw = 72, dh = 96, x = Math.round(wx - camX - dw / 2), y = floorY - dh;
  const inner = { x, y, w: dw, h: dh };
  // stone arch frame (big voussoirs)
  const ax = x - 10, aw = dw + 20, ay = y - 22;
  S.rect(ax, ay + 16, aw, dh + 6, 'greydk');
  for (let i = 0; i <= aw; i++) { const u = (i / aw) * 2 - 1, yy = ay + Math.round((1 - Math.sqrt(1 - u * u)) * 22); S.rect(ax + i, yy, 1, ay + 24 - yy, 'greydk'); S.px(ax + i, yy, 'grey'); }
  for (let k = 0; k < 9; k++) { const u = k / 8 * Math.PI; const px = Math.round(x + dw / 2 - Math.cos(u) * (dw / 2 + 6)), py = Math.round(y + 2 - Math.sin(u) * 18); S.rect(px - 1, py - 1, 3, 3, 'ink'); }
  for (let j = y + 6; j < floorY; j += 12) { S.rect(ax, j, 10, 1, 'ink'); S.rect(ax + aw - 10, j, 10, 1, 'ink'); S.rect(ax, j + 1, 9, 1, 'grey'); S.rect(ax + aw - 10, j + 1, 9, 1, 'grey'); }
  // keystone with a red gem
  S.rect(x + dw / 2 - 6, ay - 2, 12, 14, 'grey'); S.frame(x + dw / 2 - 6, ay - 2, 12, 14, 'ink'); S.rect(x + dw / 2 - 5, ay - 1, 10, 1, 'silver');
  const gemOn = 0.5 + 0.5 * Math.sin(t * 5);
  S.rect(x + dw / 2 - 2, ay + 3, 4, 4, gemOn > 0.5 ? 'coral' : 'red'); S.px(x + dw / 2 - 1, ay + 3, 'peach');
  // doorway interior (revealed as the halves open): red fog + boss eyes
  S.vbands(x, y, dw, dh, ['ink', 'plumdk', 'maroon', 'plumdk'], 4);
  S.glow(x + dw / 2, y + dh * 0.62, dw * 0.55, REMAP.ember, 1.2, 1.1);
  if (o.eyes !== false && open > 0.35) {
    const e = step(t, 15), on = Math.floor(e * 3) % 7 !== 0;
    if (on) for (const ex of [x + dw / 2 - 12, x + dw / 2 + 8]) { S.rect(ex, y + 52, 5, 3, 'gold'); S.rect(ex + 1, y + 53, 3, 1, 'cream'); S.glow(ex + 2, y + 53, 9, REMAP.gold, 0.9); }
  }
  // door halves: each swings inward, its visible width shrinks from dw/2 to 4 px
  const half = Math.max(3, Math.round((dw / 2) * (1 - open)));
  const drawHalf = (hx, hw, left) => {
    S.rect(hx, y, hw, dh, 'brown');
    for (let i = 0; i < hw; i += 6) { S.rect(hx + i, y, 1, dh, 'browndk'); if (i + 1 < hw) S.rect(hx + i + 1, y, 1, dh, 'tan'); }
    for (const by of [y + 14, y + dh - 22]) { S.rect(hx, by, hw, 4, 'greydk'); S.rect(hx, by, hw, 1, 'grey'); for (let i = 2; i < hw - 1; i += 6) S.px(hx + i, by + 2, 'silver'); }
    S.frame(hx, y, hw, dh, 'ink');
    if (hw > 14) { const rx = left ? hx + hw - 9 : hx + 5; S.ring(rx + 2, y + 52, 4, 1, 'amber'); S.px(rx + 2, y + 48, 'gold'); }
    if (open > 0) S.remap(REMAP.fade[Math.min(3, 1 + Math.floor(open * 3))], hx, y, hw, dh);
  };
  drawHalf(x, half, true);
  drawHalf(x + dw - half, half, false);
  // red light leaking from under/between the closed halves
  if (open < 0.05) { S.rect(x + dw / 2 - 1, y + 4, 2, dh - 4, gemOn > 0.4 ? 'red' : 'maroon'); S.rect(x + 2, floorY - 1, dw - 4, 1, 'red'); }
  S.glow(x + dw / 2, floorY + 4, dw * (0.6 + open * 0.8), REMAP.ember, 0.7 + open * 0.5, 0.22);
  // chains in an X with a padlock; on break, links scatter (driven by `chains` going 1 -> 0)
  if (chains > 0) {
    const brk = 1 - chains;
    const link = (px, py, i) => {
      const fx = brk > 0 ? Math.round((rand(7, i) - 0.5) * 120 * brk) : 0, fy = brk > 0 ? Math.round(brk * brk * 160 - rand(8, i) * 40 * brk) : 0;
      S.rect(px + fx - 1, py + fy - 1, 3, 3, i & 1 ? 'grey' : 'silver'); S.px(px + fx, py + fy, 'ink');
    };
    for (let i = 0; i <= 18; i++) { const u = i / 18; link(Math.round(x - 4 + u * (dw + 8)), Math.round(y + 8 + u * (dh - 30)), i); link(Math.round(x + dw + 4 - u * (dw + 8)), Math.round(y + 8 + u * (dh - 30)), i + 40); }
    const ly = y + dh / 2 - 6 + Math.round(brk * brk * 120), lx = x + dw / 2 - 7;
    S.ring(lx + 7, ly, 6, 2, 'grey'); S.rect(lx, ly, 14, 12, 'gold'); S.frame(lx, ly, 14, 12, 'ink'); S.rect(lx + 1, ly + 1, 12, 1, 'cream'); S.rect(lx + 1, ly + 10, 12, 1, 'amber');
    S.rect(lx + 6, ly + 4, 2, 2, 'ink'); S.rect(lx + 6, ly + 6, 2, 3, 'ink');
  }
  // plaque
  const label = o.label ?? 'LOCKED BOSS';
  if (label) {
    const tw = measure(label, 'caps'), pw = tw + 14, px = Math.round(x + dw / 2 - pw / 2), py = ay - 18;
    S.rect(px, py, pw, 14, 'maroon'); S.frame(px, py, pw, 14, 'ink'); S.rect(px + 1, py + 1, pw - 2, 1, 'red'); S.frame(px + 2, py + 2, pw - 4, 10, 'amber');
    for (const bx of [px + 4, px + pw - 5]) S.px(bx, py + 7, 'gold');
    drawText(S, label, x + dw / 2, py + 3, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'], align: 'center' });
  }
  return inner;
}
