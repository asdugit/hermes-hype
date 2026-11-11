// Hype kit "terminal" — text-mode toolkit: character-grid strings (box-drawing panes, dot leaders, soft
// wrap), typing / printing cadences, cursor blink, the block-letter logo face and the phosphor palettes.
// Everything is a pure function of its arguments (no clocks); scenes derive all state from shot time t.

import { rng, hash32, clamp } from '../base/motion.js';

/** IBM Plex Mono advance width (em) and the line-height at which box-drawing and block glyphs connect. */
export const ADV = 0.6;
export const LH = 1.3;

/** Phosphor palettes (mirrors theme.css; canvases need the colours in JS). */
export const PHOSPHOR = {
  p3: { ph: '#FFB13B', hot: '#FFE6B8', mid: '#C98A2C', dim: '#7C531A', faint: '#3A2609', glass: '#0C0805', rgb: [255, 177, 59] },
  p1: { ph: '#4BFF86', hot: '#D9FFE6', mid: '#35C268', dim: '#1E7A40', faint: '#0E3A1E', glass: '#040905', rgb: [75, 255, 134] },
};
const CUSTOM = new Map();
const mixHex = (rgb, to, t) => '#' + rgb.map((c, i) => Math.round(c + (to[i] - c) * t).toString(16).padStart(2, '0')).join('').toUpperCase();
/** A phosphor palette from any hex (customization: `phosphor: '#00E5FF'`), shaped like the P1/P3 tables. */
export function customPhosphor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());
  if (!m) return null;
  const key = m[1].toUpperCase();
  if (!CUSTOM.has(key)) {
    const n = parseInt(key, 16), rgb = [n >> 16 & 255, n >> 8 & 255, n & 255];
    CUSTOM.set(key, { ph: '#' + key, hot: mixHex(rgb, [255, 255, 255], 0.72), mid: mixHex(rgb, [0, 0, 0], 0.22),
      dim: mixHex(rgb, [0, 0, 0], 0.52), faint: mixHex(rgb, [0, 0, 0], 0.78), glass: mixHex(rgb, [0, 0, 0], 0.955), rgb });
  }
  return CUSTOM.get(key);
}
export const phosphorOf = (p) => PHOSPHOR[String((p && p.phosphor) || 'p3').toLowerCase()] || customPhosphor(p && p.phosphor) || PHOSPHOR.p3;
/** CSS custom properties of a phosphor palette (custom hex phosphors re-skin the tube's DOM too). */
export const phosphorVars = (P) => ({ '--ph': P.ph, '--ph-hot': P.hot, '--ph-mid': P.mid, '--ph-dim': P.dim, '--ph-faint': P.faint,
  '--ph-rgb': P.rgb.join(', '), '--glass': P.glass });

export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
/** Visible length in characters (code points). */
export const len = (s) => [...String(s)].length;
/** Span with a phosphor class ('' = body colour). */
export const sp = (cls, s) => (cls ? `<span class="${cls}">${esc(s)}</span>` : esc(s));
export const pad = (s, n) => String(s) + ' '.repeat(Math.max(0, n - len(s)));
export const padL = (s, n) => ' '.repeat(Math.max(0, n - len(s))) + String(s);

/** Truncate to n characters with an ellipsis. */
export function fit(s, n) {
  const a = [...String(s)];
  return a.length <= n ? a.join('') : a.slice(0, Math.max(1, n - 1)).join('') + '\u2026';
}

/** Soft-wrap at word boundaries; continuation lines get `indent`. Long words hard-break. */
export function wrap(s, width, indent = '') {
  const out = [];
  for (const para of String(s).replace(/\t/g, '    ').split('\n')) {
    let rest = para, first = true;
    if (!rest.length) { out.push(''); continue; }
    while (rest.length) {
      const w = first ? width : Math.max(8, width - indent.length);
      if (len(rest) <= w) { out.push((first ? '' : indent) + rest); break; }
      const chars = [...rest];
      let cut = chars.slice(0, w + 1).join('').lastIndexOf(' ');
      if (cut < w * 0.35) cut = w;
      out.push((first ? '' : indent) + chars.slice(0, cut).join('').replace(/\s+$/, ''));
      rest = chars.slice(cut).join('').replace(/^ +/, '');
      first = false;
    }
  }
  return out;
}

/** Font size (px) <= max whose `cols` characters fit in `width` px (stepped to sizes where 1.3 x size is integral). */
export function gridFont(width, cols, max = 40, min = 20) {
  const steps = [70, 60, 50, 40, 36, 34, 30, 28, 26, 24, 22, 20, 18];
  for (const s of steps) if (s <= max && s >= min && cols * s * ADV <= width) return s;
  return min;
}
export const lineH = (fs) => Math.floor(fs * LH);

// --------------------------------------------------------------------------------------------- cadences

/**
 * Human typing: per-character times starting at t0. ~`cps` chars/s with seeded jitter, longer gaps after
 * spaces and punctuation, a short think-pause every ~14 chars. Returns {at, end, count(t), cues(o)}.
 * `maxDur` compresses the whole schedule to fit (long prompts type faster, never slower than 0.6 x cps).
 */
export function typing(text, t0, o = {}) {
  const chars = [...String(text)];
  const r = rng(hash32(`type:${o.seed ?? 0}:${text}`));
  const base = 1 / (o.cps || 16);
  const gaps = chars.map((ch, i) => {
    let g = base * (0.65 + 0.7 * r());
    if (ch === ' ') g *= 1.35;
    if (/[.,;:!?)]/.test(chars[i - 1] || '')) g *= 2.0;
    if (i > 0 && i % 14 === 0 && r() < 0.5) g += base * 2.5;
    return g;
  });
  let total = gaps.reduce((a, b) => a + b, 0);
  const k = o.maxDur && total > o.maxDur ? o.maxDur / total : 1;
  let acc = t0;
  const at = gaps.map((g) => (acc += g * k));
  const end = chars.length ? at[at.length - 1] : t0;
  function count(t) {
    if (t < t0) return 0;
    let lo = 0, hi = at.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (at[m] <= t) lo = m + 1; else hi = m; }
    return lo;
  }
  /** Key-tick cues: one every `every` characters (never on spaces), at most `max`. */
  function cues({ every = 3, max = 28, gain_db = -14 } = {}) {
    const out = [];
    for (let i = 0; i < chars.length && out.length < max; i += every) {
      let j = i;
      while (j < chars.length && chars[j] === ' ') j++;
      if (j < chars.length) out.push({ t: at[j], sfx: 'type', gain_db });
    }
    return out;
  }
  return { at, end, count, cues, n: chars.length, chars };
}

/** Machine output: n lines printed from t0, `per` seconds each (whole lines, never per letter). */
export function printing(n, t0, per = 0.05) {
  return {
    end: t0 + n * per,
    at: (i) => t0 + i * per,
    count: (t) => (t < t0 ? 0 : Math.min(n, Math.floor((t - t0) / per) + 1)),
  };
}

/** Block cursor: solid while `busy`, else blinking at `hz` (on for the first half of each period). */
export function blink(t, hz = 2, busy = false) {
  if (busy) return true;
  return ((t * hz) % 1 + 1) % 1 < 0.5;
}
export const cursor = (on) => `<span class="c${on ? '' : ' off'}"> </span>`;

/** Spinner glyph for running work (ASCII, 8 fps). */
export const spin = (t) => '|/-\\'[Math.floor(Math.max(0, t) * 8) % 4];

// --------------------------------------------------------------------------------------------- panes

/** A row for box(): html + visible length. */
export const row = (html, n) => ({ html, n });
export const txt = (cls, s) => row(sp(cls, s), len(s));

/**
 * Box-drawing pane: ┌─ title ──── right ─┐ │ row │ └────┘. `inner` = content columns. Rows longer than inner are
 * not clipped (caller wraps). Returns HTML lines; visible width = inner + 4.
 */
export function box(title, inner, rows, { right = '', titleCls = 'm', rightCls = 'm', edge = 'd' } = {}) {
  // rules (and the right-hand metadata: url, line range) are chrome a zoom may crop: data-qa="off"; the title is text
  const rule = (cls, s) => `<span class="${cls}" data-qa="off">${esc(s)}</span>`;
  const T = title ? fit(title, Math.max(4, inner - 6 - (right ? len(right) + 2 : 0))) : '';
  const R = right ? len(right) + 2 : 0;
  const fill = Math.max(1, inner - 2 - (T ? len(T) : -1) - R);
  const top = rule(edge, T ? '\u250c\u2500 ' : '\u250c\u2500\u2500') + (T ? sp(titleCls, T) + rule(edge, ' ') : '') +
    rule(edge, '\u2500'.repeat(fill)) + (right ? rule(rightCls, ' ' + right + ' ') : '') + rule(edge, '\u2500\u2510');
  const out = [top];
  for (const r of rows) out.push(rule(edge, '\u2502 ') + r.html + ' '.repeat(Math.max(0, inner - r.n)) + rule(edge, ' \u2502'));
  out.push(rule(edge, '\u2514' + '\u2500'.repeat(inner + 2) + '\u2518'));
  return out;
}

/** "label ........ [ OK ]" with dot leaders to `width` columns. */
export function leader(label, status, width, cls = 'm', labelCls = '') {
  const lab = fit(label, Math.max(6, width - len(status) - 4));
  const dots = Math.max(2, width - len(lab) - len(status) - 2);
  return row(sp(labelCls, lab) + ' ' + sp('f', '.'.repeat(dots)) + ' ' + sp(cls, status), len(lab) + dots + len(status) + 2);
}

// --------------------------------------------------------------------------------------------- logo face

/** 2-px-stroke bitmap face (clean-room, ours). '#' = lit pixel; 8 rows. */
export const FACE = {
  A: ['.####.', '##..##', '##..##', '######', '##..##', '##..##', '##..##', '##..##'],
  B: ['#####.', '##..##', '##..##', '#####.', '##..##', '##..##', '##..##', '#####.'],
  C: ['.####.', '##..##', '##....', '##....', '##....', '##....', '##..##', '.####.'],
  D: ['####..', '##.##.', '##..##', '##..##', '##..##', '##..##', '##.##.', '####..'],
  E: ['######', '##....', '##....', '#####.', '##....', '##....', '##....', '######'],
  F: ['######', '##....', '##....', '#####.', '##....', '##....', '##....', '##....'],
  G: ['.####.', '##..##', '##....', '##....', '##.###', '##..##', '##..##', '.#####'],
  H: ['##..##', '##..##', '##..##', '######', '##..##', '##..##', '##..##', '##..##'],
  I: ['####', '.##.', '.##.', '.##.', '.##.', '.##.', '.##.', '####'],
  J: ['..####', '....##', '....##', '....##', '....##', '##..##', '##..##', '.####.'],
  K: ['##..##', '##.##.', '####..', '###...', '####..', '##.##.', '##..##', '##..##'],
  L: ['##....', '##....', '##....', '##....', '##....', '##....', '##....', '######'],
  M: ['##...##', '###.###', '#######', '##.#.##', '##.#.##', '##...##', '##...##', '##...##'],
  N: ['##..##', '###.##', '######', '##.###', '##..##', '##..##', '##..##', '##..##'],
  O: ['.####.', '##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '.####.'],
  P: ['#####.', '##..##', '##..##', '#####.', '##....', '##....', '##....', '##....'],
  Q: ['.####.', '##..##', '##..##', '##..##', '##..##', '##.###', '##.##.', '.##.##'],
  R: ['#####.', '##..##', '##..##', '#####.', '####..', '##.##.', '##..##', '##..##'],
  S: ['.####.', '##..##', '##....', '.####.', '....##', '....##', '##..##', '.####.'],
  T: ['######', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..'],
  U: ['##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '.####.'],
  V: ['##..##', '##..##', '##..##', '##..##', '##..##', '.####.', '.####.', '..##..'],
  W: ['##...##', '##...##', '##...##', '##.#.##', '##.#.##', '#######', '###.###', '##...##'],
  X: ['##..##', '##..##', '.####.', '..##..', '..##..', '.####.', '##..##', '##..##'],
  Y: ['##..##', '##..##', '##..##', '.####.', '..##..', '..##..', '..##..', '..##..'],
  Z: ['######', '....##', '...##.', '..##..', '.##...', '##....', '##....', '######'],
  0: ['.####.', '##..##', '##.###', '######', '###.##', '##..##', '##..##', '.####.'],
  1: ['..##..', '.###..', '####..', '..##..', '..##..', '..##..', '..##..', '######'],
  2: ['.####.', '##..##', '....##', '...##.', '..##..', '.##...', '##....', '######'],
  3: ['.####.', '##..##', '....##', '..###.', '....##', '....##', '##..##', '.####.'],
  4: ['...###', '..####', '.##.##', '##..##', '######', '....##', '....##', '....##'],
  5: ['######', '##....', '##....', '#####.', '....##', '....##', '##..##', '.####.'],
  6: ['.####.', '##....', '##....', '#####.', '##..##', '##..##', '##..##', '.####.'],
  7: ['######', '....##', '...##.', '..##..', '..##..', '..##..', '..##..', '..##..'],
  8: ['.####.', '##..##', '##..##', '.####.', '##..##', '##..##', '##..##', '.####.'],
  9: ['.####.', '##..##', '##..##', '.#####', '....##', '....##', '....##', '.####.'],
  '-': ['....', '....', '....', '####', '....', '....', '....', '....'],
  '.': ['..', '..', '..', '..', '..', '..', '##', '##'],
  '!': ['##', '##', '##', '##', '##', '..', '##', '##'],
  '?': ['.####.', '##..##', '....##', '...##.', '..##..', '..##..', '......', '..##..'],
  ':': ['..', '##', '##', '..', '..', '##', '##', '..'],
  "'": ['##', '##', '..', '..', '..', '..', '..', '..'],
  '/': ['....##', '....##', '...##.', '..##..', '..##..', '.##...', '##....', '##....'],
  '_': ['......', '......', '......', '......', '......', '......', '......', '######'],
};

/** True when every character of `word` has a glyph (letters are upper-cased). */
export const logoable = (word) => [...String(word)].every((c) => c === ' ' || FACE[c.toUpperCase()]);

/** Logo width in pixels (each pixel = 2 cells). */
export function logoWidth(word) {
  let x = 0;
  for (const ch of String(word).toUpperCase()) x += ch === ' ' ? 3 : (FACE[ch] ? FACE[ch][0].length + 1 : 0);
  return Math.max(0, x);
}

/**
 * Block-letter logo -> 9 HTML lines (8 glyph rows + the drop-shadow row). Each pixel = "██" (class lo),
 * shadow "░░" (class ls) offset by +1 px / +1 row. `rows` limits the painted rows (row-by-row build).
 */
export function logo(word, rows = 9) {
  const H = 8, grid = Array.from({ length: H + 1 }, () => []);
  let x = 0;
  for (const ch of String(word).toUpperCase()) {
    if (ch === ' ') { x += 3; continue; }
    const g = FACE[ch];
    if (!g) continue;
    g.forEach((r, y) => [...r].forEach((p, i) => { if (p === '#') grid[y][x + i] = 1; }));
    x += g[0].length + 1;
  }
  const W = x + 1, out = [];
  for (let y = 0; y <= H; y++) {
    if (y >= rows) { out.push(''); continue; }
    let line = '', cur = null, buf = '';
    const flush = () => { if (buf) line += cur ? sp(cur, buf) : buf; buf = ''; };
    for (let i = 0; i < W; i++) {
      const on = grid[y][i] === 1, sh = !on && y > 0 && grid[y - 1][i - 1] === 1;
      const c = on ? 'lo' : sh ? 'ls' : null;
      if (c !== cur) { flush(); cur = c; }
      buf += on ? '\u2588\u2588' : sh ? '\u2591\u2591' : '  ';
    }
    flush();
    out.push(line);
  }
  return { lines: out, cols: W * 2 };
}

/** Split a title into logo lines that fit `maxPx` pixels each (greedy by words); null if a word is too wide. */
export function logoLines(title, maxPx) {
  const words = String(title).trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  for (const w of words) {
    if (logoWidth(w) > maxPx) return null;
    const cand = cur ? cur + ' ' + w : w;
    if (logoWidth(cand) <= maxPx) cur = cand;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  return lines;
}

/** Numeric odometer target from a display string: {pre, digits, sepPos: Map(index->char), unit}. */
export function splitDisplay(display) {
  const s = String(display ?? '').trim();
  const m = /^([^\d]*?)(\d[\d,.]*)(.*)$/.exec(s);
  if (!m) return { pre: '', body: '', unit: s };
  return { pre: m[1], body: m[2].replace(/[.,]$/, ''), unit: m[3] + (/[.,]$/.test(m[2]) ? m[2].slice(-1) : '') };
}

export { clamp };
