// Showreel kit "blueprint" — lettering parts shared by the scenes: sheet header (kick + title line), margin notes,
// the "frame + dimensions" around a rectangle, stamps, and run numbers stated in a test run's output.

import { h, css } from '../base/dom.js';
import { seg, ease } from '../base/motion.js';
import { line, rectD, stroke, dimension, leader, el, f1 } from './draw.js';

export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export const fitS = (s, n) => { const a = [...String(s)]; return a.length <= n ? a.join('') : a.slice(0, Math.max(1, n - 1)).join('') + '\u2026'; };

/** Kick (mono cyan caps) + a title line; title may be a path (dir dim, basename bright). Returns {kick, title, h}. */
export function header(S, kick, title, x, y, o = {}) {
  const k = S.text('bp-kick', kick, x, y);
  let t = null;
  if (title) {
    const size = o.size || 34;
    let html;
    if (o.path) {
      const s = String(title), i = s.lastIndexOf('/');
      html = i > 0 ? `<span style="color:var(--line-3)">${esc(s.slice(0, i + 1))}</span>${esc(s.slice(i + 1))}` : esc(s);
    } else html = esc(title);
    t = S.text(o.font === 'draw' ? 'bp-t' : '', '', x, y + 34, { html, size, w: o.w, nowrap: true });
    t.style.fontFamily = o.font === 'draw' ? 'var(--bp-f)' : 'var(--bp-m)';
    t.style.fontWeight = '500';
    t.style.overflow = 'hidden'; t.style.textOverflow = 'ellipsis';
  }
  return { kick: k, title: t, h: title ? 34 + (o.size || 34) * 1.2 : 26 };
}

/** Margin note: mono tag + lettering (html). Returns the element; plotter letters it in. */
export function note(S, tag, html, x, y, w, size = 26) {
  const e = S.text('bp-note', '', x, y, { html: `<span class="tag">${esc(tag)}</span>${html}`, w, size });
  return e;
}

/** Thin frame + width/height dimensions around a rect; queues them on the plotter. Labels are horizontal. */
export function frameDims(S, r, o = {}) {
  const P = S.P;
  const fr = stroke(S.svg, rectD(r.x, r.y, r.w, r.h), o.cls || 'thin');
  P.add(fr);
  const out = [];
  if (o.wLabel) {
    const dm = dimension(S.svg, [r.x, r.y + r.h], [r.x + r.w, r.y + r.h], -(o.off || 34));
    dm.parts.forEach((pp) => P.add(pp));
    dm.heads.forEach((hh) => P.pop(hh));
    const lbl = S.text('bp-lbl', o.wLabel, dm.mid[0] - 120, dm.mid[1] + 8, { w: 240, align: 'center' });
    P.letter(lbl, { x: dm.mid[0] - 40, y: dm.mid[1] + 8, w: 80, h: 24 });
    out.push(lbl);
  }
  if (o.hLabel) {
    const dm = dimension(S.svg, [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], -(o.off || 34));
    dm.parts.forEach((pp) => P.add(pp));
    dm.heads.forEach((hh) => P.pop(hh));
    const lbl = S.text('bp-lbl', o.hLabel, dm.mid[0] + 14, dm.mid[1] - 12);
    P.letter(lbl, { x: dm.mid[0] + 14, y: dm.mid[1] - 12, w: 90, h: 24 });
    out.push(lbl);
  }
  return { frame: fr, labels: out };
}

/** Rubber stamp (double border caps) that thumps in at `at`. Returns {el, update(t)}. */
export function stamp(S, text, x, y, o = {}) {
  const e = S.text('bp-stamp' + (o.red ? ' red' : ''), text, x, y);
  const rot = o.rot ?? -7;
  return {
    el: e,
    update(t) {
      const u = seg(t, o.at, o.at + 0.16, ease.outCubic);
      css(e, { visibility: t >= o.at ? 'visible' : 'hidden', transform: `rotate(${rot}deg) scale(${(1.7 - 0.7 * u).toFixed(3)})`,
        opacity: (0.35 + 0.65 * u).toFixed(3) });
    },
  };
}

/** Numbers a test run's verbatim output states (pytest/jest-style summaries). */
export function runNumbers(data) {
  const outp = (data.output || []).map(String).join('\n');
  const p = /(\d+) passed/.exec(outp), f = /(\d+) failed/.exec(outp), s = /\bin ([\d.]+) ?s(ec(onds)?)?\b/.exec(outp);
  return { passed: p ? Number(p[1]) : null, failed: f ? Number(f[1]) : null, secs: s ? s[1] : null };
}

/** Dog-leg leader from a point to a note's left edge at (nx, ny); queued on the plotter. */
export function leaderTo(S, from, nx, ny) {
  const knee = nx - 40;
  const L = leader(S.svg, [from, [knee, from[1]], [knee + 26, ny], [nx - 6, ny]]);
  S.P.add(L.stroke);
  S.P.pop(L.dot);
  return L;
}

export { line, el, f1, h };
