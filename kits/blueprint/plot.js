// Auteur kit "blueprint" — the plotter. Strokes are drawn on at a constant pen speed (px/s) in a planned order
// with short pen-up moves between them, so drawing time follows path length (plotter cadence). Fills pop when their
// stroke lands; lettering is revealed left -> right with the pen riding the reveal edge. Pure function of t.

import { css } from '../base/dom.js';
import { seg, clamp } from '../base/motion.js';
import { el, circleD } from './draw.js';

/** stroke-dasharray (pathLength = 1 units) for a dashed pattern drawn up to fraction u of a path of length L. */
function dashUpTo(pattern, L, u) {
  const pat = pattern.split(/[ ,]+/).map(Number).filter((x) => x > 0);
  const per = pat.reduce((a, b) => a + b, 0);
  const upto = u * L;
  if (u >= 1) return pat.map((x) => (x / L).toFixed(6)).join(' ');
  const out = [];
  let acc = 0;
  while (acc < upto && out.length < 2000) {
    for (let i = 0; i < pat.length && acc < upto; i++) { const seg0 = Math.min(pat[i], upto - acc); out.push(seg0 / L); acc += seg0; if (seg0 < pat[i]) break; }
  }
  if (out.length % 2 === 1) out.push(0);
  out.push(2);
  return out.map((x) => x.toFixed(6)).join(' ');
}

/**
 * Plotter for one shot. add(strokeEl, opts) queues a stroke; pop(fillEl) makes a fill appear with the previous
 * stroke; letter(htmlEl, box) queues a lettering reveal; plan(t0, o) assigns times; update(t) draws.
 * Items may carry fixed windows ({at: [t0, t1]}) instead of being planned.
 */
export function plotter(svg, o = {}) {
  const items = [];
  const pen = el(o.penLayer || svg, 'g', { class: 'bp-pen' });
  el(pen, 'circle', { cx: 0, cy: 0, r: 22, class: 'penglow' });
  el(pen, 'path', { d: circleD(0, 0, 9), class: 'pen' });
  el(pen, 'path', { d: 'M-18 0 L18 0 M0 -18 L0 18', class: 'pen' });
  el(pen, 'circle', { cx: 0, cy: 0, r: 3.2, class: 'pendot' });
  let last = null;

  function add(e, opt = {}) {
    if (!e) return null;
    let L = 0;
    try { L = e.getTotalLength ? e.getTotalLength() : 0; } catch (err) { L = 0; }
    const it = { e, kind: 'stroke', L: Math.max(1, L), at: opt.at || null, w: opt.weight ?? 1, fills: [], dash: e.dataset ? e.dataset.dash : null, track: opt.track || 'main' };
    items.push(it);
    last = it;
    e.style.visibility = 'hidden';
    return it;
  }
  /** Fill elements that appear when the previous stroke (or `after`) completes. */
  function pop(e, after = last) {
    if (!e || !after) return;
    after.fills.push(e);
    e.style.visibility = 'hidden';
  }
  /** Lettering: reveal an HTML element left -> right; box = {x, y, w, h} in sheet px (for the pen). */
  function letter(e, box, opt = {}) {
    const it = { e, kind: 'letter', L: Math.max(1, box.w * (opt.factor ?? 0.6)), box, at: opt.at || null, fills: [], track: opt.track || 'main' };
    items.push(it);
    last = it;
    return it;
  }
  /** Plan untimed items in order from t0 at `speed` px/s with `gap` s pen-up moves; compress to fit `maxDur`. */
  function plan(t0, { speed = 2600, gap = 0.035, maxDur = Infinity, track = 'main', min = 0.05 } = {}) {
    const todo = items.filter((it) => !it.at && it.track === track);
    const durs = todo.map((it) => Math.max(min, it.L / speed));
    const total = durs.reduce((a, b) => a + b, 0) + gap * Math.max(0, todo.length - 1);
    const k = total > maxDur ? maxDur / total : 1;
    let t = t0;
    todo.forEach((it, i) => { const dd = durs[i] * k; it.at = [t, t + dd]; t += dd + gap * k; });
    return t;
  }
  /** Draw state at time t. Returns the pen tip [x, y] or null. */
  function update(t) {
    let tip = null, tipStart = -1;
    for (const it of items) {
      const [a, b] = it.at || [0, 0];
      const u = seg(t, a, b);
      if (it.kind === 'stroke') {
        const key = u <= 0 ? -1 : u >= 1 ? 2 : Math.round(u * 400);
        if (it.key !== key) {
          it.key = key;
          css(it.e, { visibility: u > 0 ? 'visible' : 'hidden' });
          if (u > 0) {
            if (it.dash) { it.e.style.strokeDasharray = dashUpTo(it.dash, it.L, u); it.e.style.strokeDashoffset = '0'; }
            else { it.e.style.strokeDasharray = '1 1'; it.e.style.strokeDashoffset = String((1 - u).toFixed(4)); }
          }
        }
        if (u > 0 && u < 1 && a > tipStart) {
          try { const p = it.e.getPointAtLength(u * it.L); tip = [p.x, p.y]; tipStart = a; } catch (err) { /* detached */ }
        }
      } else {
        const v = u <= 0 ? 0 : u;
        css(it.e, { visibility: v > 0 ? 'visible' : 'hidden', clipPath: v >= 1 ? 'none' : `inset(-20% ${((1 - v) * 100).toFixed(2)}% -20% -2%)` });
        if (u > 0 && u < 1 && a > tipStart) { tip = [it.box.x + it.box.w * u, it.box.y + it.box.h * 0.62]; tipStart = a; }
      }
      for (const f of it.fills) css(f, { visibility: u >= 1 ? 'visible' : 'hidden' });
    }
    if (tip) css(pen, { visibility: 'visible', transform: `translate(${tip[0].toFixed(1)}px,${tip[1].toFixed(1)}px)` });
    else css(pen, { visibility: 'hidden' });
    return tip;
  }
  const end = () => items.reduce((m, it) => Math.max(m, it.at ? it.at[1] : 0), 0);
  return { add, pop, letter, plan, update, end, items, pen };
}

export { clamp };
