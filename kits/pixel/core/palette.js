// palette.js — "Showreel Dusk 32": the pixel kit's only colours (original, CC0).
// Every surface the kit draws is an index buffer into this table; 255 = transparent.

/** Token name -> hex, in index order (index = position). */
export const PALETTE = {
  ink: '#0d0b1e', night: '#1b1a3a', navy: '#262b5e', royal: '#34489c',
  blue: '#4a7bd1', sky: '#79b8ef', ice: '#c1e8ff', white: '#fdfcf5',
  plumdk: '#2e1d47', plum: '#4b2c6b', violet: '#75468f', lilac: '#a971b4',
  rose: '#e59ac0', forestdk: '#0f3328', forest: '#1b5e3b', green: '#2f9a4a',
  lime: '#8bd650', tealdk: '#127a7a', teal: '#2fd3c0', browndk: '#3f2219',
  brown: '#74402a', tan: '#c27443', peach: '#f2b07a', cream: '#ffe39a',
  gold: '#ffc533', amber: '#e9851c', maroon: '#6e1830', red: '#c8283c',
  coral: '#ff5f4f', greydk: '#3b3d55', grey: '#6f7390', silver: '#b2b7cf',
};
export const NAMES = Object.keys(PALETTE);
export const NONE = 255;
/** Token -> index. */
export const IDX = Object.fromEntries(NAMES.map((n, i) => [n, i]));
/** Index -> [r, g, b]. */
export const RGB = NAMES.map(n => [1, 3, 5].map(i => parseInt(PALETTE[n].slice(i, i + 2), 16)));
/** Index -> perceived luminance 0..1. */
export const LUM = RGB.map(([r, g, b]) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255);

/** Resolve a colour (token name, index, or null) to an index. Unknown names throw (palette discipline). */
export function ci(c) {
  if (c === null || c === undefined) return NONE;
  if (typeof c === 'number') return c;
  const i = IDX[c];
  if (i === undefined) throw new Error(`pixel kit: "${c}" is not a palette token`);
  return i;
}

/** Material ramps, dark -> light (used by shading, fades and quantiser sub-palettes). */
export const RAMPS = {
  night: ['ink', 'night', 'navy', 'royal', 'blue', 'sky', 'ice', 'white'],
  dusk: ['plumdk', 'plum', 'violet', 'lilac', 'rose'],
  leaf: ['forestdk', 'forest', 'green', 'lime'],
  teal: ['tealdk', 'teal'],
  earth: ['browndk', 'brown', 'tan', 'peach', 'cream'],
  gold: ['brown', 'amber', 'gold', 'cream'],
  fire: ['maroon', 'red', 'amber', 'gold', 'cream'],
  blood: ['maroon', 'red', 'coral'],
  stone: ['ink', 'greydk', 'grey', 'silver', 'white'],
  steel: ['greydk', 'grey', 'silver', 'white'],
};

const DARKER = {
  ink: 'ink', night: 'ink', navy: 'night', royal: 'navy', blue: 'royal', sky: 'blue', ice: 'sky', white: 'ice',
  plumdk: 'ink', plum: 'plumdk', violet: 'plum', lilac: 'violet', rose: 'lilac',
  forestdk: 'ink', forest: 'forestdk', green: 'forest', lime: 'green', tealdk: 'night', teal: 'tealdk',
  browndk: 'ink', brown: 'browndk', tan: 'brown', peach: 'tan', cream: 'peach', gold: 'amber', amber: 'brown',
  maroon: 'browndk', red: 'maroon', coral: 'red', greydk: 'night', grey: 'greydk', silver: 'grey',
};
const LIGHTER = {
  ink: 'night', night: 'navy', navy: 'royal', royal: 'blue', blue: 'sky', sky: 'ice', ice: 'white', white: 'white',
  plumdk: 'plum', plum: 'violet', violet: 'lilac', lilac: 'rose', rose: 'peach',
  forestdk: 'forest', forest: 'green', green: 'lime', lime: 'cream', tealdk: 'teal', teal: 'ice',
  browndk: 'brown', brown: 'tan', tan: 'peach', peach: 'cream', cream: 'white', gold: 'cream', amber: 'gold',
  maroon: 'red', red: 'coral', coral: 'peach', greydk: 'grey', grey: 'silver', silver: 'white',
};
const BLOOM = {
  ink: ['lilac', 'rose'], night: ['rose', 'lilac'], navy: ['lilac', 'white'], royal: ['ice', 'lilac'], blue: ['ice', 'white'], sky: ['white', 'ice'], ice: ['white', 'cream'], white: ['white', 'cream'],
  plumdk: ['rose', 'lilac'], plum: ['rose', 'peach'], violet: ['rose', 'lilac'], lilac: ['rose', 'white'], rose: ['peach', 'white'],
  forestdk: ['cream', 'rose'], forest: ['cream', 'white'], green: ['cream', 'lime'], lime: ['cream', 'white'], tealdk: ['ice', 'lilac'], teal: ['ice', 'white'],
  browndk: ['rose', 'peach'], brown: ['peach', 'rose'], tan: ['peach', 'cream'], peach: ['cream', 'peach'], cream: ['white', 'cream'], gold: ['cream', 'gold'], amber: ['peach', 'gold'],
  maroon: ['rose', 'coral'], red: ['coral', 'rose'], coral: ['peach', 'rose'], greydk: ['lilac', 'rose'], grey: ['white', 'lilac'], silver: ['white', 'ice'],
};

function table(fn) {
  const m = new Uint8Array(256);
  for (let i = 0; i < 256; i++) m[i] = i < NAMES.length ? fn(i) : i;
  return m;
}
const byLum = (ramp) => (i) => {
  const r = ramp.map(ci);
  const l = LUM[i];
  let best = r[0], bd = 9;
  for (const j of r) { const d = Math.abs(LUM[j] - l); if (d < bd) { bd = d; best = j; } }
  return best;
};

/** Remap tables (index -> index); apply with Screen.remap(). */
export const REMAP = {
  /** fade[k]: k steps darker (k = 0..4); fade[4] is ~all ink. */
  fade: [0, 1, 2, 3, 4].map(k => table(i => { let n = NAMES[i]; for (let s = 0; s < k; s++) n = DARKER[n]; return IDX[n]; })),
  white: table(i => (LUM[i] < 0.08 ? IDX.ice : IDX.white)),
  red: table(byLum(['ink', 'maroon', 'red', 'coral', 'peach'])),
  grey: table(byLum(['ink', 'greydk', 'grey', 'silver', 'white'])),
  night: table(byLum(['ink', 'night', 'navy', 'royal', 'blue', 'sky'])),
  gold: table(byLum(['browndk', 'brown', 'amber', 'gold', 'cream'])),
  petal: table(byLum(['plum', 'violet', 'lilac', 'rose', 'peach', 'cream', 'white'])),
  /** torch-lit: stone/blue materials shifted into the warm earth ramp at similar brightness */
  warm: table(byLum(['ink', 'browndk', 'brown', 'tan', 'peach', 'cream'])),
  /** brighter torch core: one step lighter, then warm */
  warm2: table(i => byLum(['browndk', 'brown', 'tan', 'peach', 'cream', 'cream'])(IDX[LIGHTER[NAMES[i]]])),
  /** boss-room glow: shifted into the blood ramp */
  ember: table(byLum(['ink', 'plumdk', 'maroon', 'red', 'coral'])),
  /** boss chamber stone: cool purples */
  dusk: table(byLum(['ink', 'plumdk', 'plum', 'violet', 'lilac'])),
  lighter: table(i => IDX[LIGHTER[NAMES[i]]]),
  /** flower-petal pastels by material family (two variants for variety) — used by petal-bloom */
  bloomA: table(i => IDX[BLOOM[NAMES[i]][0]]),
  bloomB: table(i => IDX[BLOOM[NAMES[i]][1]]),
};

/** 4x4 Bayer threshold in (0,1) for pixel (x, y). */
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
export const bayer = (x, y) => (BAYER[((y & 3) << 2) | (x & 3)] + 0.5) / 16;

// ---- quantiser: RGB -> nearest palette index (5-bit LUT per sub-palette, perceptual weighting) ----
const LUTS = new Map();
function lutFor(sub) {
  const key = sub ? sub.join(',') : '*';
  let lut = LUTS.get(key);
  if (lut) return lut;
  const ids = sub ? sub.map(ci) : NAMES.map((_, i) => i);
  lut = new Uint8Array(32768);
  for (let r = 0; r < 32; r++) for (let g = 0; g < 32; g++) for (let b = 0; b < 32; b++) {
    const R = r * 8 + 4, G = g * 8 + 4, B = b * 8 + 4;
    let best = ids[0], bd = Infinity;
    for (const j of ids) {
      const [pr, pg, pb] = RGB[j], rm = (R + pr) / 2;
      const d = (2 + rm / 256) * (R - pr) ** 2 + 4 * (G - pg) ** 2 + (2 + (255 - rm) / 256) * (B - pb) ** 2;
      if (d < bd) { bd = d; best = j; }
    }
    lut[(r << 10) | (g << 5) | b] = best;
  }
  LUTS.set(key, lut);
  return lut;
}

/**
 * Quantise RGBA pixels to palette indices.
 * @param {Uint8ClampedArray|Uint8Array} rgba  w*h*4 source pixels
 * @param {number} w @param {number} h
 * @param {{palette?: string[]|null, dither?: number, ox?: number, oy?: number, alphaCut?: number}} o
 *   palette: sub-palette tokens (null = all 32); dither: ordered-dither spread in 0..255 units (0 = none);
 *   ox/oy: dither-pattern origin (keeps the pattern locked to the screen when a sprite moves).
 * @returns {Uint8Array} indices (NONE where alpha < alphaCut)
 */
export function quantize(rgba, w, h, o = {}) {
  const lut = lutFor(o.palette || null), spread = o.dither ?? 24, ox = o.ox | 0, oy = o.oy | 0;
  const cut = o.alphaCut ?? 128, out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const p = (y * w + x) * 4;
    if (rgba[p + 3] < cut) { out[y * w + x] = NONE; continue; }
    const d = spread ? (bayer(x + ox, y + oy) - 0.5) * spread : 0;
    const r = Math.max(0, Math.min(255, rgba[p] + d)) >> 3;
    const g = Math.max(0, Math.min(255, rgba[p + 1] + d)) >> 3;
    const b = Math.max(0, Math.min(255, rgba[p + 2] + d)) >> 3;
    out[y * w + x] = lut[(r << 10) | (g << 5) | b];
  }
  return out;
}

const THEMED = new Map();
/**
 * Palette words with the film's customization overrides (film.theme.palette.pixel = {token: '#RRGGBB'}): the
 * art stays index-locked, only the colours behind the tokens change (showreel_core/customize/theme.py).
 */
export function themedWords(theme) {
  const pal = theme && theme.palette && theme.palette.pixel;
  if (!pal || typeof pal !== 'object') return WORDS;
  const key = JSON.stringify(pal);
  let t = THEMED.get(key);
  if (!t) {
    t = WORDS.slice();
    for (const [name, hex] of Object.entries(pal)) {
      const i = IDX[name], m = /^#?([0-9a-f]{6})$/i.exec(String(hex));
      if (i === undefined || !m) continue;
      const n = parseInt(m[1], 16);
      t[i] = (255 << 24 | (n & 255) << 16 | (n >> 8 & 255) << 8 | n >> 16 & 255) >>> 0;
    }
    THEMED.set(key, t);
  }
  return t;
}

/** Packed little-endian ABGR words for ImageData (index -> uint32). Index 255 -> transparent. */
export const WORDS = (() => {
  const t = new Uint32Array(256);
  RGB.forEach(([r, g, b], i) => { t[i] = (255 << 24 | b << 16 | g << 8 | r) >>> 0; });
  return t;
})();
