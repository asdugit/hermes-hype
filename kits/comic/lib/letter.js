// Hype kit "comic" — lettering: narrator captions, speech balloons (pop from the tail, words by phrase,
// one stressed word in red bold italic), onomatopoeia that slams in, masthead/headline display lettering.
// Each block returns {el, update(t)} where update is a pure function of the shot-local time t.

import { h, css, fitSize, pickEmphasis } from '../../base/dom.js';
import { seg, ease, clamp, keys } from '../../base/motion.js';
import { tail } from './art.js';

/** Letterer's pop: 0.85 -> 1.04 -> 1 over `dur` (6 frames at 30 fps by default). Returns {s, op}. */
export function pop(t, t0, dur = 0.2, from = 0.85) {
  if (t < t0) return { s: from, op: 0 };
  const u = clamp((t - t0) / dur);
  return { s: keys(u, [[0, from], [0.6, 1.04], [1, 1]], ease.outQuad), op: clamp(u * 3) };
}

/** Onomatopoeia slam: 1.6 -> 1 in 4 frames, then a 2-frame shake. Returns {s, op, dx, dy}. */
export function slam(t, t0, o = {}) {
  if (t < t0) return { s: o.from || 1.6, op: 0, dx: 0, dy: 0 };
  const d = o.dur || 0.133;
  const u = clamp((t - t0) / d);
  const s = 1 + ((o.from || 1.6) - 1) * (1 - ease.outCubic(u));
  const k = t - t0 - d;
  const sh = k > 0 && k < 0.07 ? (k < 0.035 ? 1 : -1) * (o.shake ?? 7) : 0;
  return { s, op: clamp(u * 4), dx: sh, dy: -sh * 0.6 };
}

/** Page shake offset (sum of decaying 2-frame kicks at the given times). */
export function pageShake(t, times, amp = 9) {
  let dx = 0, dy = 0;
  for (const t0 of times) {
    const k = t - t0;
    if (k < 0 || k > 0.1) continue;
    const s = k < 0.034 ? 1 : k < 0.067 ? -0.7 : 0.35;
    dx += s * amp; dy -= s * amp * 0.55;
  }
  return [dx, dy];
}

/** Narrator caption box. o: {x, y, white, mono, wrap, size, maxW, rot}. update(t, t0) pops it in. */
export function caption(text, o = {}) {
  const el = h('div', 'cx-cap' + (o.white ? ' white' : '') + (o.mono ? ' mono' : '') + (o.wrap ? ' wrap' : ''), { text: String(text) });
  el.style.left = `${o.x ?? 16}px`;
  el.style.top = `${o.y ?? 16}px`;
  if (o.size) el.style.fontSize = `${o.size}px`;
  if (o.maxW) el.style.maxWidth = `${o.maxW}px`;
  if (o.bg) el.style.background = o.bg;
  const rot = o.rot || 0;
  return {
    el,
    update(t, t0 = 0) {
      const p = pop(t, t0, 0.2, 0.9);
      css(el, { opacity: p.op.toFixed(3), transform: `rotate(${rot}deg) scale(${p.s.toFixed(4)})`, transformOrigin: '0 0' });
    },
  };
}

/** Split a sentence into letterer phrases (~3-6 words, broken after punctuation). */
export function phrases(text, maxWords = 5) {
  const ws = String(text).trim().split(/\s+/).filter(Boolean);
  const out = [];
  let cur = [];
  for (const w of ws) {
    cur.push(w);
    if (cur.length >= maxWords || (/[,.;:!?…]$/.test(w) && cur.length >= 2)) { out.push(cur); cur = []; }
  }
  if (cur.length) out.push(cur);
  return out;
}

/**
 * Speech balloon (ellipse or rounded box) with a tail to (tx, ty) in the parent's coords. Words appear phrase by
 * phrase; the stressed word (auto: last long word, or o.stress) is red bold italic. Text stays verbatim.
 * o: {x, y, w, h, size, tail: [tx, ty], tailW, shape: 'oval'|'box', stress, maxWords, pad}
 */
export function balloon(doc, parent, text, o) {
  const str = String(text || '').trim();
  const el = h('div', 'cx-bal' + (o.shape === 'box' ? ' box' : ''));
  const pad = o.pad ?? (o.shape === 'box' ? 34 : Math.round(o.w * 0.11));
  el.style.cssText = `left:${o.x}px;top:${o.y}px;width:${o.w}px;height:${o.h}px;padding:0 ${pad}px;font-size:${o.size || 34}px;`;
  const inner = h('div', 'cx-t');
  const ph = phrases(str, o.maxWords || 5);
  const stress = o.stress === -1 ? -1 : (o.stress ?? pickEmphasis(str));
  let wi = 0;
  const groups = ph.map((ws) => {
    const g = h('span', 'cx-w');
    ws.forEach((w, k) => {
      const node = wi === stress && o.stress !== -1 ? h('em', '', { text: w }) : doc.createTextNode(w);
      g.appendChild(node);
      if (k < ws.length - 1) g.appendChild(doc.createTextNode(' '));
      wi++;
    });
    inner.appendChild(g);
    inner.appendChild(doc.createTextNode(' '));
    return g;
  });
  el.appendChild(inner);
  let tl = null;
  if (o.tail) {
    const cx = o.x + o.w / 2, cy = o.y + o.h / 2;
    const [tx, ty] = o.tail;
    const a = Math.atan2(ty - cy, tx - cx);
    const rx = o.w / 2 - 16, ry = o.h / 2 - 16;
    tl = tail(doc, cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, tx, ty, o.tailW || 64, o.bend ?? 0.18);
    parent.appendChild(tl);
  }
  parent.appendChild(el);
  const origin = o.tail ? `${((o.tail[0] - o.x) / o.w * 100).toFixed(1)}% ${((o.tail[1] - o.y) / o.h * 100).toFixed(1)}%` : '50% 50%';
  return {
    el, tail: tl, phrases: groups.length,
    /** pop at t0; phrases appear from t0 + 0.12 every `every` s (all at once when every = 0). */
    update(t, t0 = 0, every = 0.32) {
      const p = pop(t, t0, 0.2);
      css(el, { opacity: p.op.toFixed(3), transform: `scale(${p.s.toFixed(4)})`, transformOrigin: origin });
      if (tl) css(tl, { opacity: p.op.toFixed(3) });
      groups.forEach((g, i) => {
        const on = t >= t0 + 0.12 + i * every;
        css(g, { visibility: on ? 'visible' : 'hidden' });
      });
    },
    /** time the last phrase lands */
    doneAt(t0 = 0, every = 0.32) { return t0 + 0.12 + Math.max(0, groups.length - 1) * every; },
  };
}

/** Balloon font size so `text` fits a w x hh ellipse (rough capacity model, verbatim text never shrinks < min). */
export function balloonSize(text, w, hh, max = 40, min = 28, oval = true) {
  const n = Math.max(1, String(text).length);
  const effW = w * (oval ? 0.74 : 0.86), effH = hh * (oval ? 0.7 : 0.82);
  for (let s = max; s >= min; s -= 1) {
    const perLine = Math.floor(effW / (s * 0.5));
    const lines = Math.ceil(n / Math.max(1, perLine));
    if (lines * s * 1.16 <= effH) return s;
  }
  return min;
}

/**
 * Balloon box fitted to its text: the largest size (<= max) that fits maxW x maxH, then the ellipse shrinks to
 * hug the text (so a short quote gets a snug balloon). Returns {w, h, size}.
 */
export function fitBalloon(text, maxW, maxH, max = 60, min = 30, minW = 420) {
  const size = balloonSize(text, maxW, maxH, max, min);
  const n = Math.max(1, String(text).length);
  const perLine = Math.max(1, Math.floor((maxW * 0.74) / (size * 0.5)));
  const lines = Math.ceil(n / perLine);
  const textW = Math.min(maxW * 0.74, (Math.ceil(n / lines) + 2) * size * 0.5);
  const w = Math.round(Math.min(maxW, Math.max(textW / 0.72, minW)));
  const hh = Math.round(Math.min(maxH, Math.max((lines * size * 1.16) / 0.66, w * 0.42)));
  return { w, h: hh, size };
}

/** Onomatopoeia word. o: {x, y, size, color, rot, ext, stroke}. update(t, t0) slams it in. */
export function sfx(text, o = {}) {
  const el = h('div', 'cx-sfx' + (o.ext === false ? '' : ' ext'), { text: String(text) });
  el.style.cssText = `left:${o.x}px;top:${o.y}px;font-size:${o.size || 120}px;` + (o.color ? `color:${o.color};` : '') +
    (o.stroke ? `-webkit-text-stroke-width:${o.stroke}px;` : '');
  const rot = o.rot ?? -6;
  return {
    el,
    update(t, t0) {
      const s = slam(t, t0, o);
      css(el, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) rotate(${rot}deg) scale(${s.s.toFixed(4)})`, transformOrigin: '50% 60%' });
    },
  };
}

/** Masthead lettering with per-letter drop-in (letters fall 2 frames apart and snap). */
export function masthead(text, o = {}) {
  const el = h('div', 'cx-mast');
  el.style.cssText = `left:${o.x}px;top:${o.y}px;font-size:${o.size || 300}px;` + (o.ls != null ? `letter-spacing:${o.ls}px;` : '');
  const letters = [];
  for (const ch of Array.from(String(text))) {
    if (ch === ' ') { el.append(' '); continue; }
    const s = h('span', 'cx-l', { text: ch });
    el.appendChild(s);
    letters.push(s);
  }
  return {
    el, letters,
    update(t, t0 = 0, step = 0.067) {
      letters.forEach((s, i) => {
        const a = t0 + i * step;
        const u = seg(t, a, a + 0.16, ease.outCubic);
        const y = (1 - u) * -60;
        const sq = t >= a + 0.16 && t < a + 0.22 ? 0.94 : 1;
        css(s, { opacity: t < a ? '0' : '1', transform: `translate(0,${y.toFixed(1)}%) scaleY(${sq})`, transformOrigin: '50% 100%' });
      });
    },
  };
}

/** Headline in display lettering (white, ink stroke, red step shadow); words snap in one by one. */
export function headline(text, o = {}) {
  const el = h('div', 'cx-head');
  const size = o.size || fitSize(text, o.w || 700, o.lines || 3, o.max || 120, o.min || 64, 0.46);
  el.style.cssText = `left:${o.x}px;top:${o.y}px;font-size:${size}px;` + (o.w ? `width:${o.w}px;` : '') + (o.align ? `text-align:${o.align};` : '') +
    (o.color ? `color:${o.color};` : '');
  const ws = String(text).trim().split(/\s+/).filter(Boolean).map((w, i, arr) => {
    const s = h('span', 'cx-w', { text: w });
    el.appendChild(s);
    if (i < arr.length - 1) el.append(' ');
    return s;
  });
  const rot = o.rot || 0;
  return {
    el, size,
    update(t, t0 = 0, step = 0.1) {
      css(el, { transform: `rotate(${rot}deg)` });
      ws.forEach((s, i) => {
        const p = pop(t, t0 + i * step, 0.18, 1.35);
        css(s, { opacity: p.op.toFixed(3), transform: `scale(${p.s.toFixed(4)})`, transformOrigin: '50% 70%' });
      });
    },
  };
}
