// ctx.pixel: helpers for crisp pixel-art surfaces (palettes, string sprites, blits, 1-bit text, dithering).
import { drawText, parseColor } from './text.js';

/** Built-in palettes (authored for Auteur, CC0). */
export const PALETTES = {
  // "Auteur Dusk 32" — the pixel style-frame palette.
  dusk32: {
    ink: '#0d0b1e', night: '#1b1a3a', navy: '#262b5e', royal: '#34489c', blue: '#4a7bd1', sky: '#79b8ef',
    ice: '#c1e8ff', white: '#fdfcf5', plumdk: '#2e1d47', plum: '#4b2c6b', violet: '#75468f', lilac: '#a971b4',
    rose: '#e59ac0', forestdk: '#0f3328', forest: '#1b5e3b', green: '#2f9a4a', lime: '#8bd650', tealdk: '#127a7a',
    teal: '#2fd3c0', browndk: '#3f2219', brown: '#74402a', tan: '#c27443', peach: '#f2b07a', cream: '#ffe39a',
    gold: '#ffc533', amber: '#e9851c', maroon: '#6e1830', red: '#c8283c', coral: '#ff5f4f', greydk: '#3b3d55',
    grey: '#6f7390', silver: '#b2b7cf',
  },
  // four greens for handheld-console looks
  moss4: { d0: '#10200f', d1: '#35582d', d2: '#88ad5c', d3: '#dcefb1' },
  // monochrome ink
  mono2: { black: '#0b0b0c', white: '#f4f1e8' },
};

/**
 * A palette from a built-in name, a {name: hex} map or a hex array.
 * Returns {colors: hex[], named: {name: hex}, get(nameOrIndex), nearest(r,g,b) -> hex, rgb: [r,g,b][]}.
 */
export function palette(spec) {
  let named;
  if (typeof spec === 'string') {
    named = PALETTES[spec];
    if (!named) throw new Error(`unknown palette '${spec}' (built-ins: ${Object.keys(PALETTES).join(', ')})`);
  } else if (Array.isArray(spec)) named = Object.fromEntries(spec.map((h, i) => [String(i), h]));
  else named = { ...spec };
  const colors = Object.values(named);
  const rgb = colors.map((h) => parseColor(h).slice(0, 3));
  return {
    colors, named, rgb,
    get: (k) => (typeof k === 'number' ? colors[k] : named[k] ?? k),
    nearest(r, g, b) {
      let best = 0, bd = Infinity;
      rgb.forEach(([R, G, B], i) => {
        const d = (R - r) ** 2 * 0.3 + (G - g) ** 2 * 0.59 + (B - b) ** 2 * 0.11;
        if (d < bd) { bd = d; best = i; }
      });
      return colors[best];
    },
  };
}

const SPRITES = new Map();

/**
 * Sprite from string rows: sprite(['.aa.', 'abba'], {a: '#fff', b: 'gold'}) -> canvas (w = longest row).
 * '.' and ' ' are transparent; map values are hex/CSS colours or names of the optional palette.
 */
export function sprite(rows, map, pal = null) {
  const key = JSON.stringify([rows, map, pal ? pal.colors : null]);
  const hit = SPRITES.get(key);
  if (hit) return hit;
  const h = rows.length, w = Math.max(0, ...rows.map((r) => r.length));
  const c = document.createElement('canvas');
  c.width = Math.max(1, w); c.height = Math.max(1, h);
  const g = c.getContext('2d');
  const img = g.createImageData(c.width, c.height);
  const cache = {};
  for (let y = 0; y < h; y++) {
    const row = rows[y];
    for (let x = 0; x < row.length; x++) {
      const ch = row[x];
      if (ch === '.' || ch === ' ') continue;
      const col = map[ch];
      if (col == null) throw new Error(`sprite: character '${ch}' at row ${y} col ${x} has no colour in the map`);
      const rgba = cache[ch] || (cache[ch] = parseColor(pal ? pal.get(col) : col));
      const k = (y * c.width + x) * 4;
      img.data[k] = rgba[0]; img.data[k + 1] = rgba[1]; img.data[k + 2] = rgba[2]; img.data[k + 3] = Math.round(rgba[3] * 255);
    }
  }
  g.putImageData(img, 0, 0);
  c.w = c.width; c.h = c.height;
  SPRITES.set(key, c);
  return c;
}

/** Draw a sprite at integer coordinates with nearest-neighbour scaling. opts: {flip, flipY, scale, alpha, frame}. */
export function blit(g, spr, x, y, opts = {}) {
  const s = opts.scale || 1;
  const w = spr.width * s, h = spr.height * s;
  g.save();
  g.imageSmoothingEnabled = false;
  if (opts.alpha != null) g.globalAlpha *= opts.alpha;
  const rx = Math.round(x), ry = Math.round(y);
  if (opts.flip || opts.flipY) {
    g.translate(rx + (opts.flip ? w : 0), ry + (opts.flipY ? h : 0));
    g.scale(opts.flip ? -1 : 1, opts.flipY ? -1 : 1);
    g.drawImage(spr, 0, 0, w, h);
  } else g.drawImage(spr, rx, ry, w, h);
  g.restore();
}

/**
 * Crisp 1-bit text drawer for a font (CSS font string or {font,size}); text is registered for QA via `textFn`.
 * Returns {draw(g, str, x, y, opts), measure(str) -> width}.
 */
export function pixelFont(spec, textFn) {
  const base = typeof spec === 'string' ? { font: spec } : { ...spec };
  return {
    draw(g, str, x, y, opts = {}) {
      return (textFn || drawText)(g, str, { ...base, x, y, baseline: 'top', ...opts, pixel: true });
    },
    measure(str) {
      const c = document.createElement('canvas').getContext('2d');
      c.font = /px/.test(base.font || '') ? base.font : `${base.weight || 400} ${base.size || 8}px "${base.font}"`;
      return Math.ceil(c.measureText(String(str)).width);
    },
  };
}

const BAYER4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
const PATTERNS = new Map();

/** Ordered-dither fill: mixes colour a and b at `level` (0 = all a, 1 = all b) with a 4x4 Bayer matrix. */
export function dither(g, x, y, w, h, a, b, level) {
  const q = Math.max(0, Math.min(16, Math.round(level * 16)));
  const key = `${a}|${b}|${q}`;
  let pat = PATTERNS.get(key);
  if (!pat) {
    const c = document.createElement('canvas');
    c.width = c.height = 4;
    const cg = c.getContext('2d');
    for (let i = 0; i < 16; i++) {
      cg.fillStyle = BAYER4[i] < q ? b : a;
      cg.fillRect(i % 4, Math.floor(i / 4), 1, 1);
    }
    pat = g.createPattern(c, 'repeat');
    PATTERNS.set(key, pat);
  }
  g.save();
  g.fillStyle = pat;
  g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  g.restore();
}

/**
 * Stepped gradient bands with dithered seams (skies, water). colors = hex list top->bottom (or left->right
 * with {dir:'h'}); seam = dither band height in px.
 */
export function bands(g, x, y, w, h, colors, opts = {}) {
  const n = colors.length;
  if (!n) return;
  const horiz = opts.dir === 'h';
  const len = horiz ? w : h;
  const step = len / n;
  const seam = Math.max(0, Math.round(opts.seam ?? Math.min(6, step / 3)));
  for (let i = 0; i < n; i++) {
    const a0 = Math.round(i * step), a1 = Math.round((i + 1) * step);
    if (horiz) { g.fillStyle = colors[i]; g.fillRect(x + a0, y, a1 - a0, h); }
    else { g.fillStyle = colors[i]; g.fillRect(x, y + a0, w, a1 - a0); }
    if (i < n - 1 && seam > 0) {
      for (let k = 0; k < seam; k++) {
        const lvl = (k + 1) / (seam + 1);
        if (horiz) dither(g, x + a1 - seam + k, y, 1, h, colors[i], colors[i + 1], lvl);
        else dither(g, x, y + a1 - seam + k, w, 1, colors[i], colors[i + 1], lvl);
      }
    }
  }
}

/** The ctx.pixel namespace; textFn is the instance's QA-registering ctx.text. */
export function makePixel(textFn) {
  return {
    PALETTES,
    palette,
    sprite,
    blit,
    font: (spec) => pixelFont(spec, textFn),
    dither,
    bands,
  };
}
