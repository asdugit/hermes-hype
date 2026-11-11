// Auteur kit "ink" — scene helpers: full-frame art layers, positioned text, the shot clock (beats scale with
// the shot length so 3 s Quick shots land every beat), word-aware text fitting for the hand / serif faces.

import { h } from '../../base/dom.js';
import { clamp } from '../../base/motion.js';
import { svgBox, handles } from './ink.js';

/** Full-frame SVG art layer (reference px) in P.content (or P.top). Returns {el, svg, K, D}. */
export function layer(P, markup, where = 'content') {
  const b = svgBox(P.doc, 0, 0, P.W, P.H, markup, 'ik-art');
  P[where].appendChild(b.el);
  const H = handles(b.el);
  return { el: b.el, svg: b.svg, K: H.k, D: H.d };
}

/** Absolutely positioned text div. */
export function text(P, cls, s, x, y, style = '', where = 'content') {
  const e = h('div', cls, { text: String(s) });
  e.style.cssText = `left:${Math.round(x)}px;top:${Math.round(y)}px;${style}`;
  (typeof where === 'string' ? P[where] : where).appendChild(e);
  return e;
}

/** Shot clock: beat times authored for a 4 s shot, scaled to the real length (0.62x .. 1.25x). */
export function clockOf(dur) {
  const k = clamp((Number(dur) || 4) / 4, 0.62, 1.25);
  const f = (x) => x * k;
  f.k = k;
  return f;
}

/** Lines needed to set `str` greedily at `size` in `width` (char width cw em). */
export function linesAt(str, width, size, cw) {
  const per = Math.max(1, Math.floor(width / (size * cw)));
  let lines = 1, cur = 0;
  for (const w of String(str).split(/\s+/).filter(Boolean)) {
    const n = w.length;
    if (cur === 0) { cur = n; if (n > per) { lines += Math.floor(n / per); cur = n % per; } continue; }
    if (cur + 1 + n <= per) cur += 1 + n;
    else { lines++; cur = n; if (n > per) { lines += Math.floor(n / per); cur = n % per; } }
  }
  return lines;
}

/** Largest size (step 2) in [min, max] that sets `str` in <= maxLines lines of `width`. */
export function fitText(str, width, maxLines, max, min, cw) {
  for (let s = max; s >= min; s -= 2) if (linesAt(str, width, s, cw) <= maxLines) return s;
  return min;
}

/** Largest size whose wrapped block fits a width x height box (line height lh em). */
export function fitBox(str, width, height, max, min, cw, lh = 1.1) {
  for (let s = max; s >= min; s -= 2) if (linesAt(str, width, s, cw) * s * lh <= height) return s;
  return min;
}

/** Clip text to n chars at a word boundary with an ellipsis. */
export function clip(str, n) {
  const s = String(str || '').trim();
  if (s.length <= n) return s;
  return s.slice(0, n).replace(/\s+\S*$/, '').replace(/[,;:.\s]+$/, '') + '\u2026';
}

// Character width models (em) for the bundled faces.
export const CW = { hand: 0.41, serif: 0.53, serifIt: 0.47, display: 0.56, mono: 0.6, sans: 0.53 };
