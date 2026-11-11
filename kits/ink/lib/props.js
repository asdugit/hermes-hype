// Auteur kit "ink" — props drawn on the page: sticky notes, tape, taped screenshots, luggage tags, speech
// bubbles, a legal pad, the little terminal machine, a corkboard, index cards, the desk/laptop/lamp set and the
// film strip motif. Each returns a positioned element (absolute div + SVG art + DOM text) and the handles the
// scene animates. All art is built once; wobble is seeded from the prop key.

import { h, css } from '../../base/dom.js';
import { clamp, rng } from '../../base/motion.js';
import { mediaOf } from '../../base/media.js';
import { highlight } from '../../base/syntax.js';
import { C, col, form, tube, stroke, svgBox, rrect, curveD, icon, tick, handles, MISREG } from './ink.js';
import { PENDING } from './page.js';

const R = (v) => Math.round(v * 10) / 10;

/** Masking-tape strip markup centred at (x, y), length w, angle a (deg). */
export function tape(x, y, w, a, key, o = {}) {
  const hh = o.h ?? 34, r = rng(key.length * 131 + Math.round(x + y));
  const zig = (x0, dir) => { let d = ''; for (let i = 0; i <= 6; i++) d += `L${R(x0 + dir * (i % 2 ? 5 : 0) + dir * r() * 2)},${R(-hh / 2 + (i * hh) / 6)} `; return d; };
  const d = `M${-w / 2},${-hh / 2} L${w / 2},${-hh / 2} ${zig(w / 2, 1)}L${-w / 2},${hh / 2} ${zig(-w / 2, -1).split(' ').reverse().join(' ')}Z`;
  return `<g transform="translate(${R(x)},${R(y)}) rotate(${a})" ${o.k ? `data-k="${o.k}"` : ''}>` +
    `<path d="${d.replace(/\s+/g, ' ')}" fill="${o.fill || 'rgba(251,244,226,.78)'}" stroke="rgba(107,94,83,.35)" stroke-width="1.5"/>` +
    `<path d="M${-w / 2 + 8},${-hh / 2 + 7} L${w / 2 - 8},${-hh / 2 + 7}" stroke="rgba(255,255,255,.55)" stroke-width="3"/></g>`;
}

/** Push pin markup at (x, y). */
export function pin(x, y, color = 'terra', key = 'pin') {
  return `<ellipse cx="${x + 4}" cy="${y + 7}" rx="11" ry="6" fill="${C.shadow}"/>` + form(['circle', x, y, 11], color, key, { sw: 2.4 }) +
    `<circle cx="${x - 3.5}" cy="${y - 4}" r="3.4" fill="#fff" opacity=".7"/>`;
}

/**
 * Sticky note (absolute div) at (x, y), w x w, rotated r. o: {color, num ('01'), text, size (Caveat px), check
 * ('done' | 'todo' | null), pin (pin colour) | tape: true, key}. Returns {el, tick (draw paths), box, text}.
 */
export function note(doc, x, y, w, o = {}) {
  const key = o.key || `note${x},${y}`;
  const fill = col(o.color || 'butter');
  const hh = o.h ?? w;
  let art = `<rect x="9" y="12" width="${w}" height="${hh}" fill="${C.shadow}"/>` +
    form(['path', `M0,0 H${w} V${hh - 30} L${w - 30},${hh} H0 Z`], fill, `${key}:n`, { sw: 2.8 }) +
    `<path d="M${w},${hh - 30} L${w - 30},${hh} L${w - 26},${hh - 26} Z" fill="rgba(92,62,38,.22)"/>`;
  if (o.check) {
    art += form(['rect', w - 70, 26, 38, 38, 3], null, `${key}:cb`, { sw: 3, stroke: 'inkS', noReg: true });
    if (o.check === 'done') art += tick(w - 46, 40, 52, `${key}:tk`, { draw: `${key}-tick` });
  }
  if (o.pin) art += pin(w / 2, 14, o.pin, `${key}:pin`);
  if (o.tape) art += tape(w / 2, 0, w * 0.5, -3, `${key}:tape`);
  const b = svgBox(doc, x, y, w, hh, art, 'ik-note');
  b.el.style.transformOrigin = '50% 0';
  let num = null, text = null;
  if (o.num) { num = h('div', 'ik-note-num', { text: o.num }); b.el.appendChild(num); }
  if (o.text != null) {
    text = h('div', 'ik-note-text', { text: o.text });
    text.style.cssText = `left:${o.padL ?? 30}px;top:${o.num ? 84 : 40}px;width:${w - (o.padL ?? 30) - 24}px;font-size:${o.size || 48}px;`;
    b.el.appendChild(text);
  }
  const H = handles(b.el);
  return { el: b.el, svg: b.svg, tick: H.d[`${key}-tick`] || [], text, num, w, h: hh };
}

/**
 * Real screenshot taped to the page: cream mat, flat offset shadow, two tape strips, the capture cropped into a
 * w x hh window. o: {crop: [x, y, w, h] fractions (default cover, top-aligned), mat (14), tapes ('corners' |
 * 'top' | 'none'), key}. Returns {el, w, h, view, img, ix, iy, iw, ih, pt(fx, fy), rect([x, y, w, h])} in the
 * element's local px (the window starts at mat, mat).
 */
export function tapedShot(ctx, doc, img, w, hh, o = {}) {
  const key = o.key || 'shot';
  const m = mediaOf(ctx, img);
  const mat = o.mat ?? 14;
  const W = w + 2 * mat, H = hh + 2 * mat;
  let art = `<rect x="12" y="14" width="${W}" height="${H}" fill="${C.shadow}"/>` +
    form(['rect', 0, 0, W, H, 3], 'cream', `${key}:mat`, { sw: 2.6 });
  const b = svgBox(doc, 0, 0, W, H, art, 'ik-shot');
  const view = h('div', 'ik-view');
  view.style.cssText = `left:${mat}px;top:${mat}px;width:${w}px;height:${hh}px;`;
  let cr = o.crop;
  if (!cr) {
    const s = Math.max(w / m.w, hh / m.h);
    const vw = w / s / m.w, vh = hh / s / m.h;
    cr = [(1 - vw) / 2, 0, vw, vh];
  }
  const iw = w / cr[2], ih = hh / cr[3], ix = -cr[0] * iw, iy = -cr[1] * ih;
  let im = null;
  if (m.image && m.image.src) {
    im = doc.createElement('img');
    im.decoding = 'sync';
    im.draggable = false;
    im.style.cssText = `position:absolute;left:${ix.toFixed(2)}px;top:${iy.toFixed(2)}px;width:${iw.toFixed(2)}px;height:${ih.toFixed(2)}px;max-width:none;`;
    im.src = m.image.src;
    PENDING.push(im.decode().catch(() => {}));
    view.appendChild(im);
  } else {
    const ph = svgBox(doc, 0, 0, w, hh, `<rect width="${w}" height="${hh}" fill="${C.paperD}"/>` +
      stroke(['line', w * 0.1, hh * 0.2, w * 0.7, hh * 0.2], `${key}:ph1`, { sw: 6, stroke: 'inkS' }) +
      stroke(['line', w * 0.1, hh * 0.34, w * 0.5, hh * 0.34], `${key}:ph2`, { sw: 6, stroke: 'inkS' }) +
      form(['rect', w * 0.1, hh * 0.48, w * 0.8, hh * 0.38, 10], 'peach', `${key}:ph3`));
    view.appendChild(ph.el);
  }
  b.el.appendChild(view);
  const tp = o.tapes || 'corners';
  let tapes = '';
  if (tp === 'corners') tapes = tape(10, 10, Math.min(150, W * 0.22), -38, `${key}:t1`) + tape(W - 10, 10, Math.min(150, W * 0.22), 38, `${key}:t2`);
  else if (tp === 'top') tapes = tape(W / 2, 2, Math.min(190, W * 0.3), -2, `${key}:t1`);
  if (tapes) { const t = svgBox(doc, 0, 0, W, H, tapes, 'ik-tapes'); b.el.appendChild(t.el); }
  b.el.style.width = `${W}px`; b.el.style.height = `${H}px`;
  const pt = (fx, fy) => [mat + ix + fx * m.w * (iw / m.w), mat + iy + fy * m.h * (ih / m.h)];
  const rect = (bb) => { const [x0, y0] = pt(bb[0], bb[1]); const [x1, y1] = pt(bb[0] + bb[2], bb[1] + bb[3]); return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }; };
  return { el: b.el, w: W, h: H, view, img: im, ix, iy, iw, ih, mat, pt, rect, media: m };
}

/** Luggage tag with a string, mono text (URL / CTA). Returns {el, w, h}. */
export function luggageTag(doc, text, o = {}) {
  const key = o.key || 'tag';
  const fs = o.size || 28;
  const S = 64;      // the string sits inside the box (left of the tag): no SVG overflow
  const tw = Math.round(Math.min(o.maxW || 760, Math.max(160, String(text).length * fs * 0.6 + 96)));
  const hh = Math.round(fs * 2.3);
  const art = `<path d="M4,${hh / 2 - 6} C22,${hh / 2 - 40} 42,${hh / 2 + 24} ${S + 22},${hh / 2}" fill="none" stroke="${C.inkS}" stroke-width="3"/>` +
    `<rect x="${S + 10}" y="12" width="${tw}" height="${hh}" fill="${C.shadow}"/>` +
    form(['path', `M${S + 22},0 H${S + tw} V${hh} H${S + 22} L${S},${hh - 18} V18 Z`], o.fill || 'cream', `${key}:t`, { sw: 2.8 }) +
    form(['circle', S + 24, hh / 2, 7], 'paper', `${key}:h`, { sw: 2.4 });
  const b = svgBox(doc, 0, 0, S + tw + 14, hh + 14, art, 'ik-tag');
  const tx = h('div', 'ik-tag-text', { text: String(text) });
  tx.style.cssText = `left:${S + 46}px;top:0;height:${hh}px;line-height:${hh}px;font-size:${fs}px;width:${tw - 62}px;`;
  b.el.appendChild(tx);
  return { el: b.el, w: S + tw, h: hh, text: tx, off: S };
}

/**
 * Speech bubble path: rounded rect w x hh with a tail whose base sits on `side` ('bottom' | 'left' | 'right' |
 * 'top') at fraction `at`, tip at [x, y] (local px).
 */
export function bubblePath(w, hh, r, side, at, tip, bw = 64) {
  const [tx, ty] = tip;
  const bx = clamp(at, 0.1, 0.9) * w, by = clamp(at, 0.15, 0.85) * hh;
  let d = `M${r},0 `;
  if (side === 'top') d += `H${bx - bw / 2} L${tx},${ty} L${bx + bw / 2},0 `;
  d += `H${w - r} Q${w},0 ${w},${r} `;
  if (side === 'right') d += `V${by - bw / 2} L${tx},${ty} L${w},${by + bw / 2} `;
  d += `V${hh - r} Q${w},${hh} ${w - r},${hh} `;
  if (side === 'bottom') d += `H${bx + bw / 2} L${tx},${ty} L${bx - bw / 2},${hh} `;
  d += `H${r} Q0,${hh} 0,${hh - r} `;
  if (side === 'left') d += `V${by + bw / 2} L${tx},${ty} L0,${by - bw / 2} `;
  d += `V${r} Q0,0 ${r},0 Z`;
  return d;
}

/** Speech bubble element (art only; scenes add their text). Returns {el, w, h}. */
export function bubble(doc, w, hh, side, at, tip, o = {}) {
  const key = o.key || 'bubble';
  const d = bubblePath(w, hh, o.r ?? 34, side, at, tip, o.bw ?? 64);
  const art = `<path d="${d}" fill="${C.shadow}" transform="translate(10,12)"/>` + form(['path', d], o.fill || 'cream', `${key}:b`, { sw: 3.4 });
  const b = svgBox(doc, 0, 0, w, hh, art, 'ik-bubble');
  return { el: b.el, w, h: hh };
}

/** Syntax tokens -> DOM spans (base highlighter; classes tk-*). */
export function codeLine(text, lang, path) {
  const row = h('div', 'ik-code-line');
  for (const [c, s] of highlight(String(text), lang, path)) row.appendChild(c ? h('span', `tk-${c}`, { text: s }) : h('span', '', { text: s }));
  if (!text) row.appendChild(h('span', '', { text: '\u00a0' }));
  return row;
}

/**
 * Legal pad page (cream, sky rules, terracotta margin, ink binding) with a folded tab carrying the file path.
 * Rows sit on the rules: row i baseline box at y = top + i * lh. Returns {el, w, h, top, lh, margin, body}.
 */
export function legalPad(doc, w, hh, o = {}) {
  const key = o.key || 'pad';
  const lh = o.lh || 52, top = o.top || 110, margin = o.margin || 96;
  let rules = '';
  for (let y = top + lh - 4; y < hh - 20; y += lh) rules += `M18,${y}H${w - 18}`;
  const art = `<rect x="12" y="16" width="${w}" height="${hh}" fill="${C.shadow}"/>` +
    `<rect x="5" y="6" width="${w}" height="${hh}" fill="${C.creamD}"/>` +
    form(['rect', 0, 0, w, hh, 4], 'cream', `${key}:page`) +
    `<path d="${rules}" stroke="${C.sky}" stroke-width="2.2" fill="none"/>` +
    `<path d="M${margin - 14},${top - 26}V${hh - 10}M${margin - 8},${top - 26}V${hh - 10}" stroke="${C.terra}" stroke-opacity=".55" stroke-width="2" fill="none"/>` +
    form(['rect', -6, -10, w + 12, 54, 6], 'terraD', `${key}:bind`) +
    `<path d="M8,30H${w - 8}" stroke="rgba(0,0,0,.18)" stroke-width="3"/>`;
  const b = svgBox(doc, 0, 0, w, hh, art, 'ik-pad');
  const body = h('div', 'ik-abs');
  body.style.cssText = `left:0;top:0;width:${w}px;height:${hh}px;`;
  b.el.appendChild(body);
  return { el: b.el, w, h: hh, top, lh, margin, body };
}

/** A folded file tab (paper) with the path in mono. Returns {el, w, h}. */
export function fileTab(doc, path, o = {}) {
  const fs = o.size || 26;
  const tw = Math.round(Math.min(o.maxW || 900, String(path).length * fs * 0.6 + 70)), hh = Math.round(fs * 2.1);
  const art = `<rect x="8" y="10" width="${tw}" height="${hh}" fill="${C.shadow}"/>` +
    form(['path', `M0,${hh} V12 Q0,0 12,0 H${tw - 28} L${tw},${hh} Z`], o.fill || 'butter', `${o.key || 'tab'}:t`, { sw: 2.8 });
  const b = svgBox(doc, 0, 0, tw, hh, art, 'ik-tab');
  const tx = h('div', 'ik-tab-text', { text: String(path) });
  tx.style.cssText = `left:22px;top:0;line-height:${hh}px;font-size:${fs}px;`;
  b.el.appendChild(tx);
  return { el: b.el, w: tw, h: hh };
}

/**
 * The little terminal machine: a cream box on stubby feet, a dark screen (DOM rows go into `screen`), two knobs
 * and a vent. Returns {el, w, h, screen: {el, x, y, w, h}, lamp handles}.
 */
export function machine(doc, w, hh, o = {}) {
  const key = o.key || 'crt';
  const sx = 34, sy = 34, sw = w - 170, sh = hh - 92;
  const art = `<rect x="14" y="18" width="${w}" height="${hh}" rx="34" fill="${C.shadow}"/>` +
    `<rect x="${w * 0.12}" y="${hh - 6}" width="56" height="26" rx="8" fill="${C.ink}"/><rect x="${w * 0.88 - 56}" y="${hh - 6}" width="56" height="26" rx="8" fill="${C.ink}"/>` +
    form(['rect', 0, 0, w, hh, 34], 'creamD', `${key}:body`) +
    `<path d="M${w - 34},4 Q${w - 4},4 ${w - 4},34 V${hh - 34} Q${w - 4},${hh - 4} ${w - 34},${hh - 4} H${w - 60} Q${w - 30},${hh / 2} ${w - 60},4 Z" fill="rgba(92,62,38,.12)"/>` +
    form(['rect', sx - 10, sy - 10, sw + 20, sh + 20, 26], 'cream', `${key}:bezel`, { sw: 2.6 }) +
    `<rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" rx="18" fill="${C.screen}"/>` +
    `<path d="M${sx + 18},${sy + 14} Q${sx + sw * 0.5},${sy + 4} ${sx + sw - 18},${sy + 14}" stroke="rgba(251,246,236,.10)" stroke-width="10" fill="none" stroke-linecap="round"/>` +
    form(['circle', w - 68, 74, 22], 'mustard', `${key}:k1`, { sw: 2.6 }) + tube(`M${w - 68},60 L${w - 68},74`, 'ink', 4) +
    form(['circle', w - 68, 138, 16], 'terra', `${key}:k2`, { sw: 2.6 }) +
    `<g data-k="${key}-led">${form(['circle', w - 68, 192, 9], 'mint', `${key}:led`, { sw: 2.2 })}</g>` +
    tube(`M${w - 92},${hh - 92} H${w - 44} M${w - 92},${hh - 74} H${w - 44} M${w - 92},${hh - 56} H${w - 44}`, 'inkS', 4);
  const b = svgBox(doc, 0, 0, w, hh, art, 'ik-machine');
  const screen = h('div', 'ik-screen');
  screen.style.cssText = `left:${sx + 22}px;top:${sy + 18}px;width:${sw - 44}px;height:${sh - 30}px;`;
  b.el.appendChild(screen);
  return { el: b.el, w, h: hh, screen: { el: screen, x: sx + 22, y: sy + 18, w: sw - 44, h: sh - 30 }, K: handles(b.el).k };
}

/** Corkboard: wood frame + cork with seeded speckles. Returns {el, w, h, inset}. */
export function corkboard(doc, w, hh, o = {}) {
  const key = o.key || 'cork';
  const f = 26, r = rng(91);
  let sp = '';
  for (let i = 0; i < (w * hh) / 900; i++) {
    const x = f + r() * (w - 2 * f), y = f + r() * (hh - 2 * f), rr = 1.2 + r() * 2.6;
    sp += `M${R(x - rr)},${R(y)}a${R(rr)},${R(rr * 0.7)} 0 1,0 ${R(2 * rr)},0a${R(rr)},${R(rr * 0.7)} 0 1,0 ${R(-2 * rr)},0`;
  }
  const art = `<rect x="14" y="18" width="${w}" height="${hh}" fill="${C.shadow}"/>` +
    form(['rect', 0, 0, w, hh, 10], 'wood', `${key}:frame`) +
    `<rect x="${f}" y="${f}" width="${w - 2 * f}" height="${hh - 2 * f}" fill="${C.cork}"/>` +
    `<path d="${sp}" fill="${C.corkD}" opacity=".55"/>` +
    `<rect x="${f}" y="${f}" width="${w - 2 * f}" height="10" fill="rgba(92,62,38,.18)"/>` +
    form(['rect', f, f, w - 2 * f, hh - 2 * f, 2], null, `${key}:in`, { sw: 2.6, stroke: 'woodD' });
  const b = svgBox(doc, 0, 0, w, hh, art, 'ik-cork');
  return { el: b.el, w, h: hh, inset: f };
}

/** Index card with a pictogram doodle, a title (tool) and a mono arg. Returns {el, w, h, draw}. */
export function indexCard(doc, w, hh, item, o = {}) {
  const key = o.key || 'card';
  const rl = o.rule || 44;
  let rules = '';
  for (let y = 100 + rl; y < hh - 16; y += rl) rules += `M16,${y}H${w - 16}`;
  const art = `<rect x="9" y="12" width="${w}" height="${hh}" fill="${C.shadow}"/>` +
    form(['rect', 0, 0, w, hh, 4], 'cream', `${key}:c`, { sw: 2.8 }) +
    `<path d="M16,92H${w - 16}" stroke="${C.terra}" stroke-opacity=".6" stroke-width="2.4"/><path d="${rules}" stroke="${C.sky}" stroke-width="1.8"/>` +
    form(['circle', 60, 48, 32], o.dot || 'peach', `${key}:dot`, { sw: 2.4 }) + icon(o.icon || 'code', 60, 48, 1.05);
  const b = svgBox(doc, 0, 0, w, hh, art, 'ik-card');
  const title = h('div', 'ik-card-tool', { text: String(item.tool || item.kind || '') });
  title.style.cssText = `left:110px;top:16px;width:${w - 124}px;font-size:${o.toolSize || 54}px;`;
  const arg = h('div', 'ik-card-arg', { text: String(item.arg || '') });
  arg.style.cssText = `left:24px;top:${100 + rl - (o.argSize || 30) * 1.25}px;width:${w - 48}px;font-size:${o.argSize || 30}px;line-height:${rl}px;max-height:${rl * 3}px;`;
  b.el.append(title, arg);
  return { el: b.el, w, h: hh };
}

/** Arc-length sampler for a Catmull-Rom curve through pts: {len, at(s) -> [x, y, angleDeg]}. */
export function sampler(pts, n = 400) {
  const seg = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    seg.push([p1, c1, c2, p2]);
  }
  const P = [];
  const per = Math.ceil(n / seg.length);
  for (const [a, b, c, d] of seg) {
    for (let k = 0; k < per; k++) {
      const u = k / per, v = 1 - u;
      P.push([v * v * v * a[0] + 3 * v * v * u * b[0] + 3 * v * u * u * c[0] + u * u * u * d[0], v * v * v * a[1] + 3 * v * v * u * b[1] + 3 * v * u * u * c[1] + u * u * u * d[1]]);
    }
  }
  P.push(pts[pts.length - 1]);
  const S = [0];
  for (let i = 1; i < P.length; i++) S.push(S[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
  const len = S[S.length - 1];
  function at(s) {
    const x = clamp(s, 0, len);
    let lo = 0, hi = S.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (S[m] <= x) lo = m; else hi = m; }
    const u = (x - S[lo]) / ((S[hi] - S[lo]) || 1);
    const p = [P[lo][0] + (P[hi][0] - P[lo][0]) * u, P[lo][1] + (P[hi][1] - P[lo][1]) * u];
    return [p[0], p[1], (Math.atan2(P[hi][1] - P[lo][1], P[hi][0] - P[lo][0]) * 180) / Math.PI];
  }
  return { len, at };
}

/**
 * The film strip motif along a curve (points): layered strokes (base, sprockets, core, frames) revealed by a
 * mask that unspools from the start; pictograms ride the frames. Returns {markup, bind(root) -> update(reveal
 * 0..1, scroll px)}. uid must be unique per shot (mask id).
 */
export function filmStrip(pts, uid, o = {}) {
  const d = curveD(pts);
  const W = o.width ?? 96, fr = o.frame ?? 74, gap = o.gap ?? 14, period = fr + gap;
  const sm = sampler(pts);
  const icons = o.icons || ['code', 'check', 'term', 'diff', 'bars', 'play', 'star'];
  const nIcons = Math.ceil(sm.len / period) + 2;
  let ic = '';
  for (let k = 0; k < nIcons; k++) ic += `<g data-k="${uid}-ic">${icon(icons[k % icons.length], 0, 0, 1)}</g>`;
  const markup = `<defs><mask id="${uid}-m" maskUnits="userSpaceOnUse" x="-4000" y="-4000" width="9000" height="9000">` +
    `<path data-k="${uid}-rev" d="${d}" fill="none" stroke="#fff" stroke-width="${W + 40}" pathLength="1" stroke-dasharray="1 1" stroke-dashoffset="1"/></mask></defs>` +
    `<g mask="url(#${uid}-m)">` +
    `<path d="${d}" fill="none" stroke="rgba(92,62,38,.16)" stroke-width="${W}" transform="translate(10,14)"/>` +
    `<path d="${d}" fill="none" stroke="${C.ink}" stroke-width="${W}"/>` +
    `<path data-k="${uid}-spr" d="${d}" fill="none" stroke="${C.cream}" stroke-width="${W - 14}" stroke-dasharray="9 9"/>` +
    `<path d="${d}" fill="none" stroke="${C.ink}" stroke-width="${W - 34}"/>` +
    `<path data-k="${uid}-fr" d="${d}" fill="none" stroke="${C.peach}" stroke-width="${W - 40}" stroke-dasharray="${fr} ${gap}"/>` +
    ic + '</g>';
  function bind(root) {
    const K = handles(root).k;
    const rev = (K[`${uid}-rev`] || [])[0], spr = (K[`${uid}-spr`] || [])[0], frm = (K[`${uid}-fr`] || [])[0];
    const ics = K[`${uid}-ic`] || [];
    return function update(reveal, scroll = 0) {
      if (rev) rev.setAttribute('stroke-dashoffset', (1 - clamp(reveal)).toFixed(4));
      const sc = ((scroll % period) + period) % period;
      if (spr) spr.setAttribute('stroke-dashoffset', (-(scroll % 18)).toFixed(2));
      if (frm) frm.setAttribute('stroke-dashoffset', (-sc).toFixed(2));
      const head = clamp(reveal) * sm.len;
      ics.forEach((e, k) => {
        const s = sc + fr / 2 + (k - 1) * period;
        const [x, y, a] = sm.at(s);
        const vis = s > fr / 2 && s < sm.len - fr / 2 && s < head - fr * 0.3;
        e.setAttribute('transform', `translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${a.toFixed(1)})`);
        e.setAttribute('opacity', vis ? '1' : '0');
      });
    };
  }
  return { markup, bind, len: sm.len };
}

/** Pendant lamp + warm light cone (markup) hanging at x from the top; the shade swings about (x, 0). */
export function lamp(x, y1, coneH, key, k, top = -200) {
  return `<g data-k="${k}">` + `<path d="M${x},${top} L${x},${y1}" stroke="${C.ink}" stroke-width="3"/>` +
    `<path d="M${x - 48},${y1 + 64} L${x - 204},${y1 + 64 + coneH} L${x + 208},${y1 + 64 + coneH} L${x + 48},${y1 + 64} Z" fill="${C.mustard}" opacity=".16"/>` +
    form(['path', `M${x - 42},${y1} L${x + 42},${y1} L${x + 72},${y1 + 64} L${x - 72},${y1 + 64} Z`], 'terra', `${key}:shade`) +
    `<ellipse cx="${x}" cy="${y1 + 66}" rx="22" ry="9" fill="${C.mustard}"/></g>`;
}

/** Desk (top + front + legs) markup: top surface y, from x0 to x1, legs of height lh. */
export function desk(x0, x1, y, lh, key) {
  return form(['rect', x0 + 34, y + 38, 30, lh, 0], 'woodD', `${key}:legL`) + form(['rect', x1 - 64, y + 38, 30, lh, 0], 'woodD', `${key}:legR`) +
    form(['rect', x0, y, x1 - x0, 18, 4], 'wood', `${key}:top`) + form(['rect', x0, y + 18, x1 - x0, 26, 0], 'woodD', `${key}:front`);
}

/** Laptop seen from behind (lid with a play sticker), base sitting on y. */
export function laptop(cx, y, key) {
  const x = cx - 147;
  return form(['rect', x, y - 154, 294, 160, 12], 'creamD', `${key}:lid`) +
    `<rect x="${x + 6}" y="${y - 149}" width="282" height="7" rx="3" fill="${C.cream}"/>` +
    form(['circle', cx, y - 76, 25], 'terra', `${key}:stk1`, { sw: 2.6 }) + `<path d="M${cx - 8},${y - 89} L${cx + 13},${y - 76} L${cx - 8},${y - 63} Z" fill="${C.cream}"/>` +
    form(['rect', cx + 59, y - 42, 54, 22, 11], 'mustard', `${key}:stk2`, { sw: 2.6 }) +
    `<path d="M${cx - 165},${y} L${cx + 165},${y} L${cx + 159},${y + 8} L${cx - 159},${y + 8} Z" fill="${C.inkS}"/>`;
}

/** Mug + books on a desk at (x, y = desk top). */
export function mugBooks(x, y, key) {
  return form(['rect', x, y - 18, 158, 18, 3], 'teal', `${key}:b1`) + form(['rect', x + 12, y - 36, 134, 18, 3], 'terra', `${key}:b2`) +
    tube(`M${x + 48},${y - 66} C${x + 40},${y - 82} ${x + 60},${y - 96} ${x + 50},${y - 112} M${x + 74},${y - 70} C${x + 64},${y - 90} ${x + 88},${y - 100} ${x + 76},${y - 120}`, 'inkS', 3.2, { opacity: 0.7 }) +
    tube(`M${x + 38},${y - 50} C${x + 14},${y - 50} ${x + 14},${y - 16} ${x + 42},${y - 18}`, 'mustardD', 10) +
    form(['path', `M${x + 36},${y - 64} L${x + 110},${y - 64} L${x + 105},${y - 46} Q${x + 103},${y - 36} ${x + 93},${y - 36} L${x + 53},${y - 36} Q${x + 43},${y - 36} ${x + 41},${y - 46} Z`], 'mustard', `${key}:mug`) +
    `<ellipse cx="${x + 73}" cy="${y - 63}" rx="36" ry="6" fill="${C.hair}"/>`;
}

export { MISREG };
