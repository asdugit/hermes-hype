// Auteur kit "ink" — drawing primitives: palette, seeded Rough.js outlines (deterministic: every call passes a
// seed derived from a stable key), clean fills with the outline offset by the print misregistration, draw-on
// strokes (pathLength = 1, dashoffset driven by t), pictograms, sparkles, arrows, marker loops, ticks and the small
// motion helpers every ink scene shares. Art is built once in build(); render(t) only writes transforms/opacity/
// dashoffsets, so the same t always paints the same frame.

import rough from '../vendor/rough.mjs';
import { h, css } from '../../base/dom.js';
import { seg, ease, clamp, lerp, hash32, keys } from '../../base/motion.js';

/** The ink palette (styleframes/ink/NOTES.md): 4 hues + neutrals, one hero accent per scene (terra). */
export const C = {
  paper: '#F4ECDF', paperD: '#EADFCC', ink: '#2B2622', inkS: '#6B5E53',
  terra: '#D2603A', terraD: '#A9472A', mustard: '#E9B04A', mustardD: '#C98E2C',
  teal: '#3D7A72', tealD: '#2C5D57', peach: '#F0D3B6', peachD: '#E2B994',
  cream: '#FBF6EC', creamD: '#E6DAC6', skin: '#EDB794', skinD: '#D49674', hair: '#3A2C25',
  wood: '#C68A58', woodD: '#9E683F', cork: '#C9A273', corkD: '#A9814F',
  butter: '#F7DC7E', npeach: '#F5B9A0', mint: '#C3DCC3', sky: '#BED6E4', screen: '#2F2A26',
  shadow: 'rgba(92,62,38,.15)',
};
export const NOTE_COLORS = ['butter', 'mint', 'sky', 'npeach'];
export const col = (c) => C[c] || c;
const NS = 'http://www.w3.org/2000/svg';
export const MISREG = [-3, -2];
const GEN = rough.generator();

/** Stable Rough.js seed (1..2^31-2) for a key string. */
export const seedOf = (key) => (hash32(String(key)) % 2147483646) + 1;

/** Rounded-rect path data. */
export function rrect(x, y, w, hh, r = 0) {
  r = Math.max(0, Math.min(r, w / 2, hh / 2));
  if (!r) return `M${x},${y}H${x + w}V${y + hh}H${x}Z`;
  return `M${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hh - r}Q${x + w},${y + hh} ${x + w - r},${y + hh}` +
    `H${x + r}Q${x},${y + hh} ${x},${y + hh - r}V${y + r}Q${x},${y} ${x + r},${y}Z`;
}
/** Ellipse path data (two arcs). */
export function ell(cx, cy, rx, ry = rx) {
  return `M${cx - rx},${cy}a${rx},${ry} 0 1,0 ${2 * rx},0a${rx},${ry} 0 1,0 ${-2 * rx},0Z`;
}

/**
 * Shape spec -> clean path data. Specs: ['rect', x, y, w, h, r] · ['circle', cx, cy, r] · ['ellipse', cx, cy, rx, ry]
 * · ['line', x1, y1, x2, y2] · ['path', d] · ['curve', [[x, y], ...]] (catmull-rom through the points).
 */
export function cleanD(s) {
  switch (s[0]) {
    case 'rect': return rrect(s[1], s[2], s[3], s[4], s[5] || 0);
    case 'circle': return ell(s[1], s[2], s[3]);
    case 'ellipse': return ell(s[1], s[2], s[3], s[4]);
    case 'line': return `M${s[1]},${s[2]}L${s[3]},${s[4]}`;
    case 'curve': return curveD(s[1]);
    default: return s[1];
  }
}

/** Smooth path through points (Catmull-Rom -> cubic Bezier). */
export function curveD(pts) {
  if (pts.length < 2) return '';
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

/**
 * Seeded Rough.js outline for a shape spec -> path data (single stroke unless o.multi). The seed comes from `key`,
 * so the same key always yields the same wobble (no boil between frames or renders).
 */
export function roughD(s, key, o = {}) {
  const opt = { seed: seedOf(key), roughness: o.roughness ?? 0.9, bowing: o.bowing ?? 0.6, strokeWidth: o.sw ?? 3.2,
    disableMultiStroke: !o.multi, preserveVertices: !!o.keep, stroke: '#000', curveFitting: 0.95 };
  let dr;
  switch (s[0]) {
    case 'circle': dr = GEN.circle(s[1], s[2], s[3] * 2, opt); break;
    case 'ellipse': dr = GEN.ellipse(s[1], s[2], s[3] * 2, s[4] * 2, opt); break;
    case 'line': dr = GEN.line(s[1], s[2], s[3], s[4], opt); break;
    case 'curve': dr = GEN.curve(s[1], opt); break;
    default: dr = GEN.path(cleanD(s), opt);
  }
  return GEN.toPaths(dr).map((p) => p.d).join(' ');
}

const attrs = (o) => Object.entries(o).filter(([, v]) => v != null && v !== false).map(([k, v]) => `${k}="${v}"`).join(' ');

/**
 * A filled form: clean fill + seeded rough ink outline offset by the misregistration. o: {sw, stroke, key,
 * k (data-k handle for the whole group), draw (outline draws on: pathLength=1), noReg, opacity, rough opts}.
 */
export function form(s, fill, key, o = {}) {
  const d = cleanD(s);
  const fillEl = fill ? `<path d="${d}" fill="${col(fill)}"${o.fillOpacity != null ? ` fill-opacity="${o.fillOpacity}"` : ''}/>` : '';
  const [mx, my] = o.noReg ? [0, 0] : MISREG;
  const line = o.sw === 0 ? '' : `<path ${attrs({ d: roughD(s, key, o), fill: 'none', stroke: col(o.stroke || 'ink'), 'stroke-width': o.sw ?? 3.2,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', transform: mx || my ? `translate(${mx},${my})` : null,
    pathLength: o.draw ? 1 : null, class: o.draw ? 'ik-draw' : null, 'data-d': o.draw || null })}/>`;
  return `<g ${attrs({ 'data-k': o.k, opacity: o.opacity })}>${fillEl}${line}</g>`;
}

/** An ink line only (rough, seeded). o: {sw, stroke, draw (data-d handle: draws on), k, opacity, cap}. */
export function stroke(s, key, o = {}) {
  return `<path ${attrs({ d: roughD(s, key, o), fill: 'none', stroke: col(o.stroke || 'ink'), 'stroke-width': o.sw ?? 3.2,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', pathLength: o.draw ? 1 : null, class: o.draw ? 'ik-draw' : null,
    'data-d': o.draw || null, 'data-k': o.k, opacity: o.opacity, transform: o.transform })}/>`;
}

/** A clean (non-rough) stroke: tubes (arms), pictograms, marker strokes that must stay smooth. */
export function tube(d, color, width, o = {}) {
  return `<path ${attrs({ d, fill: 'none', stroke: col(color), 'stroke-width': width, 'stroke-linecap': o.cap || 'round',
    'stroke-linejoin': 'round', pathLength: o.draw ? 1 : null, class: o.draw ? 'ik-draw' : null, 'data-d': o.draw || null,
    'data-k': o.k, opacity: o.opacity, 'stroke-dasharray': o.dash })}/>`;
}

/** Positioned box (absolute div) holding an SVG of w x h (viewBox = local px, overflow visible). */
export function svgBox(doc, x, y, w, hh, inner, cls = '') {
  const el = h('div', `ik-box ${cls}`.trim());
  el.style.cssText = `left:${x}px;top:${y}px;width:${w}px;height:${hh}px;`;
  const s = doc.createElementNS(NS, 'svg');
  s.setAttribute('width', String(w));
  s.setAttribute('height', String(hh));
  s.setAttribute('viewBox', `0 0 ${w} ${hh}`);
  s.setAttribute('class', 'ik-svg');
  s.innerHTML = inner;
  el.appendChild(s);
  return { el, svg: s };
}

/** Handles inside built markup: k -> [elements with data-k=k], d -> [draw-on paths with data-d=d]. */
export function handles(root) {
  const k = {}, d = {};
  for (const e of root.querySelectorAll('[data-k]')) (k[e.getAttribute('data-k')] ||= []).push(e);
  for (const e of root.querySelectorAll('[data-d]')) (d[e.getAttribute('data-d')] ||= []).push(e);
  return { k, d };
}

/** Draw a set of pathLength=1 strokes to progress u (0 hidden .. 1 complete); several paths draw in sequence. */
export function drawOn(els, u) {
  if (!els || !els.length) return;
  const n = els.length;
  els.forEach((e, i) => {
    const v = clamp(u * n - i);
    e.style.strokeDasharray = '1 1';
    e.style.strokeDashoffset = (1 - v).toFixed(4);
    e.style.visibility = v <= 0 ? 'hidden' : 'visible';
  });
}

/** Pop-in (0.92 -> 1, no overshoot by default; settle = small overshoot). Returns {s, op}. */
export function popIn(t, t0, dur = 0.3, from = 0.9, settle = false) {
  if (t < t0) return { s: from, op: 0 };
  const u = clamp((t - t0) / dur);
  const s = settle ? keys(u, [[0, from], [0.62, 1.035], [1, 1]], ease.outQuad) : lerp(from, 1, ease.outCubic(u));
  return { s, op: clamp(u * 3) };
}

/** Transform an absolutely positioned element: translate + rotate + scale (2D only; no compositing layers). */
export function place(el, o = {}) {
  css(el, { transform: `translate(${(o.x || 0).toFixed(2)}px,${(o.y || 0).toFixed(2)}px) rotate(${(o.r || 0).toFixed(3)}deg) scale(${(o.s ?? 1).toFixed(4)})`,
    opacity: o.op == null ? '' : clamp(o.op).toFixed(3), transformOrigin: o.origin || '50% 50%' });
}

/** SVG group transform about (ox, oy). */
export function gpose(el, o = {}) {
  if (!el) return;
  const ox = o.ox || 0, oy = o.oy || 0;
  el.setAttribute('transform', `translate(${((o.x || 0) + ox).toFixed(2)},${((o.y || 0) + oy).toFixed(2)}) rotate(${(o.r || 0).toFixed(3)}) scale(${(o.s ?? 1).toFixed(4)}) translate(${-ox},${-oy})`);
  if (o.op != null) el.setAttribute('opacity', clamp(o.op).toFixed(3));
}

/** Entrance used for paper things: slides up 16 px and settles a rotation while the scale pops. */
export function settleIn(el, t, t0, o = {}) {
  const p = popIn(t, t0, o.dur || 0.34, o.from ?? 0.92, o.settle);
  const u = seg(t, t0, t0 + (o.dur || 0.34), ease.outCubic);
  place(el, { x: o.x || 0, y: (o.y || 0) + (1 - u) * (o.rise ?? 16), r: (o.r || 0) + (1 - u) * (o.spin ?? 2), s: p.s, op: p.op, origin: o.origin });
  return u;
}

/** Handwriting write-on: reveal an element left to right like a pen (clip-path), u 0..1. */
export function writeOn(el, u) {
  const k = ((1 - clamp(u)) * 100).toFixed(2);
  css(el, { clipPath: u >= 1 ? 'none' : `inset(-30% ${k}% -30% -4%)`, visibility: u <= 0 ? 'hidden' : 'visible' });
}

/** Hand-drawn arrow from a to b (bend = sideways bulge, px) with an open arrowhead. Returns markup. */
export function arrow(a, b, key, o = {}) {
  const bend = o.bend ?? 40;
  const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const nx = -(b[1] - a[1]) / L, ny = (b[0] - a[0]) / L;
  const c = [mx + nx * bend, my + ny * bend];
  const d = `M${a[0]},${a[1]} Q${c[0].toFixed(1)},${c[1].toFixed(1)} ${b[0]},${b[1]}`;
  const tx = b[0] - c[0], ty = b[1] - c[1], tl = Math.hypot(tx, ty) || 1;
  const ux = tx / tl, uy = ty / tl, hs = o.head ?? 22;
  const h1 = [b[0] - ux * hs - uy * hs * 0.62, b[1] - uy * hs + ux * hs * 0.62];
  const h2 = [b[0] - ux * hs + uy * hs * 0.62, b[1] - uy * hs - ux * hs * 0.62];
  const sw = o.sw ?? 3.8, color = o.stroke || 'terraD';
  return stroke(['path', d], `${key}:s`, { sw, stroke: color, roughness: 1.3, draw: o.draw, k: o.k }) +
    tube(`M${h1[0].toFixed(1)},${h1[1].toFixed(1)}L${b[0]},${b[1]}L${h2[0].toFixed(1)},${h2[1].toFixed(1)}`, color, sw, { draw: o.draw, k: o.k });
}

/** Marker loop around a box (double stroke, terracotta), draws on as one gesture. Returns markup. */
export function loop(x, y, w, hh, key, o = {}) {
  const cx = x + w / 2, cy = y + hh / 2, rx = w / 2 + (o.pad ?? 18), ry = hh / 2 + (o.pad ?? 18);
  const pts = [];
  const n = 26, over = 1.12;
  for (let i = 0; i <= n; i++) {
    const a = -Math.PI * 0.62 + (i / n) * Math.PI * 2 * over;
    const wob = 1 + 0.035 * Math.sin(i * 1.7 + 0.5) + (i / n) * 0.06;
    pts.push([cx + Math.cos(a) * rx * wob, cy + Math.sin(a) * ry * wob]);
  }
  return stroke(['curve', pts], key, { sw: o.sw ?? 6.5, stroke: o.stroke || 'terra', roughness: 1.1, multi: true, draw: o.draw, k: o.k });
}

/** Tick mark (teal marker). */
export function tick(x, y, s, key, o = {}) {
  return stroke(['path', `M${x - s * 0.45},${y} L${x - s * 0.1},${y + s * 0.38} L${x + s * 0.55},${y - s * 0.5}`], key,
    { sw: o.sw ?? 8, stroke: o.stroke || 'tealD', roughness: 0.8, draw: o.draw, k: o.k, keep: true });
}

/** A rough underline / brush stroke (draws on). */
export function underline(x, y, w, key, o = {}) {
  const d = `M${x},${y} C${x + w * 0.2},${y - 10} ${x + w * 0.48},${y + 8} ${x + w * 0.66},${y - 4} S${x + w * 0.94},${y - 5} ${x + w},${y + 2}`;
  return stroke(['path', d], key, { sw: o.sw ?? 7, stroke: o.stroke || 'terra', roughness: 1.4, bowing: 1.2, draw: o.draw, k: o.k });
}

/** 4-point sparkle (fill only). */
export function sparkle(x, y, r, fill = 'mustard', k = null) {
  const q = r * 0.18;
  return `<path ${attrs({ 'data-k': k, fill: col(fill) })} d="M${x},${y - r}Q${x + q},${y - q} ${x + r},${y}Q${x + q},${y + q} ${x},${y + r}Q${x - q},${y + q} ${x - r},${y}Q${x - q},${y - q} ${x},${y - r}Z"/>`;
}

// 0,0-centred pictograms (~34 px) in ink: the scene types / tool kinds of a session.
const SI = `stroke="${C.ink}" stroke-width="3.4" fill="none" stroke-linecap="round" stroke-linejoin="round"`;
export const ICONS = {
  code: `<path ${SI} d="M-6,-13 Q-13,-13 -12,-6 L-12,-3 Q-12,0 -16,0 Q-12,0 -12,3 L-12,6 Q-13,13 -6,13"/><path ${SI} d="M6,-13 Q13,-13 12,-6 L12,-3 Q12,0 16,0 Q12,0 12,3 L12,6 Q13,13 6,13"/>`,
  term: `<path ${SI} d="M-15,-9 L-5,0 L-15,9"/><path ${SI} d="M0,11 L14,11"/>`,
  check: `<path ${SI} stroke-width="4.4" d="M-14,0 L-4,10 L15,-12"/>`,
  play: `<path fill="${C.terra}" stroke="${C.ink}" stroke-width="3" stroke-linejoin="round" d="M-9,-13 L14,0 L-9,13 Z"/>`,
  bars: `<path ${SI} d="M-14,13 L-14,2 M-3,13 L-3,-6 M8,13 L8,-14 M-19,15 L16,15"/>`,
  diff: `<path ${SI} d="M-14,-6 L-2,-6 M-8,-12 L-8,0"/><path ${SI} d="M3,9 L15,9"/>`,
  star: `<path fill="${C.mustard}" stroke="${C.ink}" stroke-width="3" stroke-linejoin="round" d="M0,-15 L4,-4 L15,0 L4,4 L0,15 L-4,4 L-15,0 L-4,-4 Z"/>`,
  file: `<path ${SI} d="M-11,-15 L4,-15 L12,-7 L12,15 L-11,15 Z M4,-15 L4,-7 L12,-7"/><path ${SI} stroke-width="2.6" d="M-5,0 L6,0 M-5,7 L6,7"/>`,
  edit: `<path ${SI} d="M-12,12 L-10,3 L6,-13 L13,-6 L-3,10 Z M2,-9 L9,-2"/>`,
  search: `<circle ${SI} cx="-3" cy="-3" r="10"/><path ${SI} stroke-width="4.4" d="M5,5 L14,14"/>`,
  web: `<circle ${SI} cx="0" cy="0" r="14"/><path ${SI} stroke-width="2.6" d="M-14,0 L14,0 M0,-14 Q-9,0 0,14 M0,-14 Q9,0 0,14"/>`,
  list: `<path ${SI} d="M-6,-10 L14,-10 M-6,0 L14,0 M-6,10 L14,10"/><circle cx="-13" cy="-10" r="2.6" fill="${C.ink}"/><circle cx="-13" cy="0" r="2.6" fill="${C.ink}"/><circle cx="-13" cy="10" r="2.6" fill="${C.ink}"/>`,
  bot: `<rect ${SI} x="-13" y="-10" width="26" height="20" rx="6"/><path ${SI} d="M0,-10 L0,-16"/><circle cx="-5" cy="0" r="2.6" fill="${C.ink}"/><circle cx="5" cy="0" r="2.6" fill="${C.ink}"/>`,
  camera: `<rect ${SI} x="-15" y="-8" width="30" height="21" rx="4"/><path ${SI} d="M-6,-8 L-3,-13 L4,-13 L7,-8"/><circle ${SI} cx="0" cy="3" r="6"/>`,
};

/** Map a tool call kind/name to a pictogram. */
export function toolIcon(kind, tool) {
  const s = `${kind || ''} ${tool || ''}`.toLowerCase();
  if (/test|pytest|check/.test(s)) return 'check';
  if (/term|shell|bash|exec|run|command/.test(s)) return 'term';
  if (/patch|edit|write|diff|replace/.test(s)) return 'edit';
  if (/read|file|open/.test(s)) return 'file';
  if (/search|grep|find/.test(s)) return 'search';
  if (/web|browse|fetch|http|url/.test(s)) return 'web';
  if (/todo|plan|list/.test(s)) return 'list';
  if (/deleg|agent|task/.test(s)) return 'bot';
  if (/vision|screen|shot|image|capture/.test(s)) return 'camera';
  return 'code';
}

/** Icon markup at (x, y), scale s, rotation r. */
export function icon(name, x, y, s = 1, r = 0) {
  return `<g transform="translate(${x},${y}) rotate(${r}) scale(${s})">${ICONS[name] || ICONS.code}</g>`;
}

/** Split text into per-character spans inside el (for typing / letter rises). Returns the spans. */
export function charSpans(el, text) {
  const out = [];
  const doc = el.ownerDocument;
  for (const word of String(text).split(/(\s+)/)) {
    if (!word) continue;
    if (/^\s+$/.test(word)) { el.appendChild(doc.createTextNode(' ')); out.push(null); continue; }
    const w = h('span', 'ik-word');
    for (const ch of word) { const s = h('span', 'ik-ch', { text: ch }); w.appendChild(s); out.push(s); }
    el.appendChild(w);
  }
  return out;
}

/** Typing reveal: n visible characters (spans from charSpans; null = whitespace). */
export function typeTo(spans, n) {
  let i = 0;
  for (const s of spans) { if (s) s.style.visibility = i < n ? 'visible' : 'hidden'; i++; }
}

/** Letter rise: spans rise 0.5 em with a 30 ms stagger (titles). */
export function riseLetters(spans, t, t0, o = {}) {
  const st = o.stagger ?? 0.03, d = o.dur ?? 0.42;
  spans.forEach((s, i) => {
    if (!s) return;
    const u = seg(t, t0 + i * st, t0 + i * st + d, ease.outCubic);
    css(s, { transform: `translate(0,${((1 - u) * (o.rise ?? 0.42)).toFixed(3)}em)`, opacity: clamp(u * 2.2).toFixed(3) });
  });
}

export { h, css, seg, ease, clamp, lerp, keys };
