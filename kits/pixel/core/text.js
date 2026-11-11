// text.js — crisp 1-bit bitmap text for the pixel kit (glyph tables baked from OFL fonts).
// Fonts: 'mono' (11 px, 7 px advance: body, dialogue, code), 'caps' (8 px: menus, names, numbers),
// 'tiny' (8 px proportional: small labels). `scale` >= 2 is only for drawn titles (re-detailed with
// bands/outline/highlight so it reads as art, not an upscaled font).
import { GLYPHS } from './glyphs.js';
import { ci, NONE } from './palette.js';

const FALLBACK = {
  '✓': 'v', '✗': 'x', '★': '*', '♥': '<3', '…': '...', '→': '->', '←': '<-', '↪': '>', '▼': 'v', '►': '>', '•': '.', '·': '.', '×': 'x',
  // typography real product names and model-written captions use (E4: 'Tempo — focus timer' printed 'Tempo ? focus timer')
  '—': '-', '–': '-', '‒': '-', '―': '-', '−': '-', '‐': '-', '‑': '-', '‘': "'", '’': "'", '‚': ',', '′': "'", '`': "'", '´': "'",
  '“': '"', '”': '"', '„': '"', '″': '"', '«': '"', '»': '"', '‹': '<', '›': '>', '\u00a0': ' ', '\u2009': ' ', '\u202f': ' ',
  '\u2007': ' ', '\u2002': ' ', '\u2003': ' ', '\u200b': '', '\u200d': '', '\ufe0f': '', '©': '(c)', '®': '(r)', '™': 'TM',
  '°': 'o', '½': '1/2', '¼': '1/4', '¾': '3/4', '≥': '>=', '≤': '<=', '≠': '!=', '≈': '~', '±': '+-', '÷': '/', '∙': '.',
  '●': '*', '◆': '*', '■': '#', '□': '[]', '☐': '[]', '☑': '[v]', '✔': 'v', '✘': 'x', '⇒': '=>', '↑': '^', '↓': 'v', '¡': '!', '¿': '?',
  'ß': 'ss', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE', 'ø': 'o', 'Ø': 'O', 'đ': 'd', 'Đ': 'D', 'ł': 'l', 'Ł': 'L', 'ı': 'i', 'þ': 'th',
};

/** Font metrics {size, asc, lh}. */
export function fontInfo(font = 'mono') { const f = GLYPHS[font]; return { size: f.size, asc: f.asc, lh: f.lh }; }

function glyph(f, ch) { return f.glyphs[ch] || null; }
const has = (f, s) => [...s].every((c) => glyph(f, c));
/**
 * Normalise characters the font lacks: the fallback map, then the letter without its accents (é -> e), then the
 * other case; anything still unknown (emoji, CJK) is dropped instead of printing '?'.
 */
export function normalize(str, font = 'mono') {
  const f = GLYPHS[font]; let out = '';
  for (const ch of String(str)) {
    if (glyph(f, ch)) { out += ch; continue; }
    if (ch === '\t') { out += '  '; continue; }
    if (ch in FALLBACK && has(f, FALLBACK[ch])) { out += FALLBACK[ch]; continue; }
    const base = ch.normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
    if (base && base !== ch && has(f, base)) { out += base; continue; }
    if (base && base !== ch && has(f, base.toUpperCase())) { out += base.toUpperCase(); continue; }
    if (glyph(f, ch.toUpperCase())) { out += ch.toUpperCase(); continue; }
    if (glyph(f, ch.toLowerCase())) { out += ch.toLowerCase(); continue; }
    if (/\s/.test(ch) && glyph(f, ' ')) { out += ' '; continue; }
    // unknown: drop it (never a '?'), but keep words apart
  }
  return out.replace(/ {2,}/g, (m) => (String(str).includes(m) ? m : ' ')).replace(/^ (?=\S)/, (m) => (/^\s/.test(String(str)) ? m : ''));
}

/** Width in screen px of `str` (normalised) at `scale`. */
export function measure(str, font = 'mono', scale = 1, spacing = 0) {
  const f = GLYPHS[font], s = normalize(str, font); let w = 0, n = 0;
  for (const ch of s) { w += glyph(f, ch)[0]; n++; }
  return (w + Math.max(0, n - 1) * spacing) * scale;
}

/** Build the 1-bit mask of a string: {w, h, base, d: Uint8Array(0/1)} with `pad` empty px around it. */
export function mask(str, font = 'mono', scale = 1, spacing = 0, pad = 3) {
  const f = GLYPHS[font], s = normalize(str, font), lh = f.lh;
  const w = measure(s, font, 1, spacing) + pad * 2 + 2, h = lh + pad * 2;
  const m = new Uint8Array(w * h);
  let pen = pad;
  for (const ch of s) {
    const g = glyph(f, ch), [adv, x0, y0, gw, gh] = g;
    for (let j = 0; j < gh; j++) { const bits = g[5 + j]; for (let i = 0; i < gw; i++) if (bits >> i & 1) {
      const x = pen + x0 + i, y = pad + f.asc + y0 + j; if (x >= 0 && x < w && y >= 0 && y < h) m[y * w + x] = 1; } }
    pen += adv + spacing;
  }
  if (scale === 1) return { w, h, d: m, pad };
  const W = w * scale, H = h * scale, M = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) M[y * W + x] = m[((y / scale) | 0) * w + ((x / scale) | 0)];
  return { w: W, h: H, d: M, pad: pad * scale };
}
function dilate(m, w, h, diag) {
  const o = m.slice();
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (m[y * w + x]) continue;
    const g = (i, j) => i >= 0 && j >= 0 && i < w && j < h && m[j * w + i];
    if (g(x - 1, y) || g(x + 1, y) || g(x, y - 1) || g(x, y + 1) || (diag && (g(x - 1, y - 1) || g(x + 1, y - 1) || g(x - 1, y + 1) || g(x + 1, y + 1)))) o[y * w + x] = 1;
  }
  return o;
}

/**
 * Draw text on a Screen. (x, y) = top-left of the line box (y + asc*scale = baseline).
 * o: {font='mono', scale=1, color='white', bands:[tokens top->bottom], outline, outline2, diag=true,
 *     shadow:[dx,dy,token], highlight: token (1-px top edge), align: 'left'|'center'|'right', spacing,
 *     reveal: 0..1 fraction of glyphs drawn (typewriter, measured on the full string so layout never shifts)}
 * Returns {x, y, w, h} — the box actually covered (for QA registration).
 */
export function drawText(S, str, x, y, o = {}) {
  const font = o.font || 'mono', scale = o.scale || 1, sp = o.spacing || 0;
  let s = normalize(str, font);
  const full = measure(s, font, scale, sp);
  if (o.align === 'center') x -= Math.round(full / 2); else if (o.align === 'right') x -= full;
  if (o.reveal !== undefined && o.reveal < 1) s = [...s].slice(0, Math.floor([...s].length * Math.max(0, o.reveal) + 1e-6)).join('');
  if (o.chars !== undefined) s = [...s].slice(0, Math.max(0, o.chars | 0)).join('');
  if (!s.length) return { x, y, w: full, h: GLYPHS[font].lh * scale };
  const M = mask(s, font, scale, sp), { w, h, d, pad } = M, ox = Math.round(x) - pad, oy = Math.round(y) - pad;
  let top = h, bot = -1;
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if (d[j * w + i]) { if (j < top) top = j; if (j > bot) bot = j; }
  const diag = o.diag !== false;
  const o1 = o.outline ? dilate(d, w, h, diag) : null, o2 = (o1 && o.outline2) ? dilate(o1, w, h, true) : null;
  const sil = o2 || o1 || d;
  const put = (m, c, dx = 0, dy = 0) => { const k = ci(c); if (k === NONE) return; for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if (m[j * w + i]) S.px(ox + i + dx, oy + j + dy, k); };
  if (o.shadow) put(sil, o.shadow[2], o.shadow[0], o.shadow[1]);
  if (o2) put(o2, o.outline2);
  if (o1) put(o1, o.outline);
  if (o.bands) {
    const n = o.bands.length, ks = o.bands.map(ci), span = Math.max(1, bot - top + 1);
    for (let j = 0; j < h; j++) { const k = ks[Math.min(n - 1, Math.floor((j - top) / span * n))]; for (let i = 0; i < w; i++) if (d[j * w + i]) S.px(ox + i, oy + j, k); }
  } else put(d, o.color || 'white');
  if (o.highlight) { const k = ci(o.highlight); for (let j = 1; j < h; j++) for (let i = 0; i < w; i++) if (d[j * w + i] && !d[(j - 1) * w + i]) S.px(ox + i, oy + j, k); }
  return { x: Math.round(x), y: Math.round(y), w: full, h: GLYPHS[font].lh * scale };
}

/** Word-wrap to lines no wider than maxW px. Never splits inside a word unless the word alone is too wide. */
export function wrap(str, maxW, font = 'mono', scale = 1) {
  const out = [];
  for (const para of String(str).split('\n')) {
    let line = '';
    for (const word of para.split(/ +/)) {
      const cand = line ? line + ' ' + word : word;
      if (measure(cand, font, scale) <= maxW) { line = cand; continue; }
      if (line) out.push(line);
      if (measure(word, font, scale) <= maxW) { line = word; continue; }
      let chunk = '';   // hard-break an over-long token
      for (const ch of word) { if (measure(chunk + ch, font, scale) > maxW) { out.push(chunk); chunk = ch; } else chunk += ch; }
      line = chunk;
    }
    out.push(line);
  }
  return out;
}

/** Ellipsise a string to fit maxW. */
export function fit(str, maxW, font = 'mono', scale = 1) {
  let s = normalize(str, font);
  if (measure(s, font, scale) <= maxW) return s;
  while (s.length > 1 && measure(s + '...', font, scale) > maxW) s = s.slice(0, -1);
  return s.trimEnd() + '...';
}

/** Typewriter: number of characters visible at time t (cps chars/second, stepped 2 chars per tick). */
export function typed(t, t0, n, cps = 30) {
  if (t <= t0) return 0;
  const c = Math.floor((t - t0) * cps); return c >= n ? n : c - (c % 2);
}
/** Typewriter blip times (one every `every` chars), absolute in the same clock as t0. */
export function typedBlips(t0, n, cps = 30, every = 4) {
  const out = []; for (let i = 2; i <= n; i += every) out.push(t0 + i / cps); return out;
}
