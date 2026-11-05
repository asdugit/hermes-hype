// worlds.js — parallax backdrops: overworld (dusk), night sky, castle. Layers scroll at different integer rates
// (far 0.1x ... near 1x of camX); everything is palette art: banded skies with dithered seams, faceted peaks,
// puffy clouds, pines, stars and a moon. Each takes (S, t, {camX}) and fills the whole Screen.
import { Sprite } from './../core/gfx.js';
import { rand, rng } from './../core/motion.js';
import { REMAP } from './../core/palette.js';

/** Faceted mountain range: peaks [[x, y, slopeL, slopeR], ...]; lit left face, shadow right, optional snowcap. */
export function peaks(S, list, baseY, cols, o = {}) {
  const ordered = list.map((p, k) => [p, k]).sort((a, b) => a[0][1] - b[0][1]);
  for (const [[px, py, sl, sr], k] of ordered) {
    const r = rng(1000 + k * 17 + (o.seed || 0));
    const ridge = []; let off = 0; for (let y = py; y < baseY; y++) { if ((y - py) % 4 === 3) off += r() < 0.5 ? 0 : 1; ridge.push(off); }
    const jag = []; for (let i = 0; i < 64; i++) jag.push(Math.floor(r() * 3));
    for (let y = Math.max(0, py); y < baseY; y++) {
      const d = y - py, xl = Math.round(px - d / sl), xr = Math.round(px + d / sr), split = px + Math.round(d * 0.3) + ridge[d];
      for (let x = Math.max(0, xl); x <= Math.min(S.w - 1, xr); x++) {
        const lit = x < split;
        let c = lit ? cols.lit : cols.dark;
        if (o.snow && d < o.snow + jag[(x - xl) & 63] - (Math.abs(x - px) > d * 0.7 ? 2 : 0)) c = lit ? 'white' : 'ice';
        if (lit && cols.rim && x === xl) c = cols.rim;
        S.px(x, y, c);
      }
    }
  }
}

/** Puffy cumulus cloud (union of circles, flat base, 3 tones + white top rim). */
export function cloud(S, x, y, w, cols = { top: 'rose', mid: 'lilac', bot: 'violet' }, seed = 1) {
  const r = rng(seed), h = 30, circ = [], n = Math.max(3, Math.round(w / 11));
  for (let i = 0; i < n; i++) { const u = (i + 0.5) / n, rad = (9 + r() * 7) * (1.2 - Math.abs(u - 0.5) * 1.1); circ.push([u * w + (r() - 0.5) * 6, h - 5 - rad * 0.55 - r() * 3, rad]); }
  const B = new Sprite(Math.ceil(w), h);
  for (let yy = 0; yy < h - 3; yy++) for (let xx = 0; xx < B.w; xx++) {
    if (!circ.some(([cx, cy, cr]) => (xx - cx) ** 2 + (yy - cy) ** 2 <= cr * cr)) continue;
    B.set(xx, yy, yy > h - 8 ? cols.bot : yy > h - 12 ? cols.mid : cols.top);
  }
  for (let yy = h - 1; yy > 0; yy--) for (let xx = 0; xx < B.w; xx++) if (B.get(xx, yy) !== 255 && B.get(xx, yy - 1) === 255) B.set(xx, yy, 'white');
  S.blit(B, Math.round(x), Math.round(y));
}

export function pine(S, x, base, h, cols = { a: 'forestdk', b: 'forest' }) {
  for (let j = 0; j < h; j++) { const half = Math.floor((j % Math.max(4, Math.floor(h / 3))) * 0.8 + j / 5) + 1;
    for (let i = -half; i <= half; i++) S.px(x + i, base - h + j, i < 0 && i > -half ? cols.b : cols.a); }
  S.rect(x, base, 1, 2, 'browndk');
}

export function stars(S, x0, y0, w, h, seed, n, t = 0) {
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const x = x0 + Math.floor(r() * w), y = y0 + Math.floor(r() * h), k = r(), tw = rand(seed, i, Math.floor(t * 3)) > 0.85;
    if (k > 0.94) { S.px(x, y, 'white'); if (!tw) { S.px(x - 1, y, 'sky'); S.px(x + 1, y, 'sky'); S.px(x, y - 1, 'sky'); S.px(x, y + 1, 'sky'); } }
    else S.px(x, y, tw ? 'navy' : k > 0.6 ? 'ice' : 'sky');
  }
}

export function moon(S, cx, cy, r) {
  S.ellipse(cx, cy, r, r, 'ice'); S.ellipse(cx - 1, cy - 1, r - 2, r - 2, 'white');
  S.ellipse(cx + r * 0.35, cy - r * 0.15, r * 0.25, r * 0.22, 'ice'); S.ellipse(cx - r * 0.3, cy + r * 0.35, r * 0.18, r * 0.16, 'ice');
  S.glow(cx, cy, r * 2.6, REMAP.lighter, 0.5);
}

const wrapX = (x, period) => ((x % period) + period) % period;

/** Dusk overworld: banded sky, sun glow, clouds, two faceted ranges, rolling hills with pines. */
export function overworld(S, t, o = {}) {
  const camX = o.camX || 0, seed = o.seed ?? 3;
  const W = S.w, H = S.h, hz = Math.round(H * 0.62);
  S.vbands(0, 0, W, hz, ['night', 'plum', 'violet', 'lilac', 'rose', 'peach'], 4);
  S.glow(W * 0.72, hz - 6, H * 0.35, REMAP.lighter, 0.9, 0.6);
  for (let i = 0; i < 4; i++) { const cw = 60 + rand(seed, i) * 50, period = W + cw + 40;
    cloud(S, wrapX(rand(seed, i, 1) * period - camX * 0.1 - t * (3 + i), period) - cw, H * (o.cloudY ?? 0.36) + H * 0.045 * i, cw, i < 2 ? { top: 'rose', mid: 'lilac', bot: 'violet' } : { top: 'peach', mid: 'rose', bot: 'lilac' }, seed + i); }
  const far = [], near = [];
  const kf = Math.floor(camX * 0.2 / 120), kn = Math.floor(camX * 0.4 / 90);
  for (let k = kf - 1; k < kf + 6; k++) { const x0 = k * 120 - Math.round(camX * 0.2); far.push([x0 + 30 + Math.round(rand(seed, k, 2) * 60), hz - 34 - Math.round(rand(seed, k) * 40), 0.6 + rand(seed, k, 3) * 0.4, 0.65 + rand(seed, k, 4) * 0.4]); }
  for (let k = kn - 1; k < kn + 8; k++) { const x0 = k * 90 - Math.round(camX * 0.4); near.push([x0 + 20 + Math.round(rand(seed + 5, k, 2) * 50), hz - 16 - Math.round(rand(seed + 5, k) * 30), 0.8 + rand(seed + 5, k, 3) * 0.5, 0.9 + rand(seed + 5, k, 4) * 0.5]); }
  peaks(S, far, hz + 4, { lit: 'lilac', dark: 'violet', rim: 'rose' }, { snow: 6, seed });
  peaks(S, near, hz + 10, { lit: 'violet', dark: 'plum', rim: 'lilac' }, { seed: seed + 1 });
  // hills
  for (let x = 0; x < W; x++) { const wx = x + camX * 0.7, y = hz + 6 + Math.round(Math.sin(wx / 47) * 5 + Math.sin(wx / 19) * 2); S.rect(x, y, 1, H - y, 'forest'); S.px(x, y, 'green'); }
  for (let x = 0; x < W; x++) { const wx = x + camX, y = hz + 30 + Math.round(Math.sin(wx / 63 + 2) * 6); S.rect(x, y, 1, H - y, 'forestdk'); S.px(x, y, 'forest'); }
  for (let k = -1; k < W / 22 + 2; k++) { const wx = k * 22 + Math.floor(camX / 22) * 22, x = Math.round(wx - camX); if (rand(seed, Math.floor(wx / 22)) < 0.55) pine(S, x, hz + 34 + Math.round(Math.sin((wx) / 63 + 2) * 6), 14 + Math.round(rand(seed, wx) * 8)); }
}

/** Night sky: deep bands, twinkling stars, moon, silhouette ridge with a faint rim. */
export function nightSky(S, t, { camX = 0, seed = 9, moonAt = [0.78, 0.22] } = {}) {
  const W = S.w, H = S.h, hz = Math.round(H * 0.72);
  S.vbands(0, 0, W, hz, ['ink', 'night', 'night', 'navy', 'royal'], 5);
  stars(S, 0, 0, W, hz - 20, seed, Math.round(W * H / 700), t);
  moon(S, Math.round(W * moonAt[0]), Math.round(H * moonAt[1]), Math.round(Math.min(W, H) * 0.06));
  const far = []; for (let k = -1; k < 7; k++) { const x0 = k * 100 - wrapX(camX * 0.25, 100); far.push([x0 + 50, hz - 30 - Math.round(rand(seed, k) * 20), 0.8, 0.9]); }
  peaks(S, far, hz + 2, { lit: 'navy', dark: 'night', rim: 'royal' }, { seed });
  S.rect(0, hz, W, H - hz, 'ink');
  for (let x = 0; x < W; x++) { const y = hz - 2 + Math.round(Math.sin((x + camX) / 31) * 2); S.rect(x, y, 1, H - y, 'ink'); }
}

/** Castle on a hill at dusk with lit windows and a pennant. */
export function castle(S, t, { camX = 0, seed = 5 } = {}) {
  overworld(S, t, { camX, seed });
  const W = S.w, H = S.h, cx = Math.round(W * 0.68 - camX * 0.5), base = Math.round(H * 0.62) + 8;
  const block = (x, y, w, h) => { S.rect(x, y, w, h, 'plumdk'); S.rect(x, y, 1, h, 'plum'); for (let i = 0; i < w; i += 4) S.rect(x + i, y - 3, 2, 3, 'plumdk'); };
  block(cx - 40, base - 30, 80, 30); block(cx - 52, base - 46, 16, 46); block(cx + 36, base - 46, 16, 46); block(cx - 10, base - 62, 20, 62);
  S.poly([[cx - 13, base - 62], [cx, base - 80], [cx + 13, base - 62]], 'maroon');
  S.line(cx, base - 80, cx, base - 92, 'browndk'); S.rect(cx + 1, base - 92 + (Math.floor(t * 4) & 1), 7, 3, 'gold');
  const win = (x, y) => { const on = rand(seed, x, Math.floor(t * 2 + x)) > 0.1; S.rect(x, y, 2, 3, on ? 'gold' : 'amber'); };
  [[cx - 46, base - 36], [cx + 42, base - 36], [cx - 2, base - 50], [cx - 2, base - 38], [cx - 26, base - 20], [cx + 22, base - 20]].forEach(([x, y]) => win(x, y));
  S.rect(cx - 6, base - 14, 12, 14, 'ink'); S.ellipse(cx, base - 14, 6, 4, 'ink');
}

export const WORLDS = { overworld, night: nightSky, castle };
