// Showreel kit "blueprint" — the sheet: every kit:blueprint scene is a DOM scene drawn on a cyanotype sheet with a
// registered drafting grid, a zoned double border, low-frequency mottling, a title block, an SVG drawing layer
// (plotted strokes), an HTML lettering layer and the pen on top. The camera is orthographic and calm: a 1-2 % scale
// drift, pans along the sheet and detail zooms; never hand-held.

import { defineDomScene } from '../base/scene.js';
import { COMMON } from '../base/scenes-panels.js';
import { h, css } from '../base/dom.js';
import { seg, ease, clamp, lerp, pchip, rng, hash32 } from '../base/motion.js';
import { highlight } from '../base/syntax.js';
import { NS } from './draw.js';
import { plotter } from './plot.js';

/** Params every blueprint scene accepts (on top of the base COMMON ones). */
export const BCOMMON = {
  ...COMMON,
  theme: { type: 'string', default: 'blueprint', doc: 'theme (blueprint tokens; kit:base scenes re-skin with it too)' },
  rev: { type: 'string', default: '', doc: 'REV letter in the title block (default per scene: A, B for diffs)' },
  dwg: { type: 'string', default: '', doc: 'drawing number in the title block (default from the scene data)' },
};

/** Border inset and the lettering-safe box (reference px). */
export function frameBox(F) {
  const bd = F.portrait ? 40 : 56;
  const s = F.safe;
  const box = F.portrait ? { x: 120, y: 232, w: F.W - 240, h: 1500 - 232 } : { x: 124, y: 104, w: F.W - 248, h: 960 - 104 };
  if (F.caps) box.h -= F.portrait ? 90 : 96;
  return { bd, box, safe: s };
}

/** Register a blueprint scene: def.build(ctx, p, F, S) -> {render(t), cues}. */
export function bpScene(id, def) {
  defineDomScene(id, {
    describe: def.describe,
    params: { ...BCOMMON, ...(def.params || {}) },
    build(ctx, p, F) {
      const S = sheet(ctx, p, F, def);
      const s = def.build(ctx, p, F, S) || {};
      S.front();
      return {
        cues: [...(s.cues || []), ...S.cues],
        render(t) { s.render && s.render(t); S.update(t); },
      };
    },
  });
}

/** Cyanotype mottling: a small deterministic value-noise canvas, scaled up (cheap, static). */
function mottle(doc, W, H, seed) {
  const gw = Math.round(W / 12), gh = Math.round(H / 12);
  const c = doc.createElement('canvas');
  c.width = gw; c.height = gh;
  const g = c.getContext('2d');
  const img = g.createImageData(gw, gh);
  const r = rng(seed);
  const lat = (n) => Array.from({ length: n }, () => r());
  const oct = [[9, 0.55], [21, 0.3], [47, 0.15]].map(([cells, amp]) => ({ cells, amp, v: lat((cells + 2) * (cells + 2)) }));
  const smooth = (x) => x * x * (3 - 2 * x);
  for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) {
    let v = 0;
    for (const o of oct) {
      const fx = (x / gw) * o.cells, fy = (y / gh) * o.cells, ix = Math.floor(fx), iy = Math.floor(fy);
      const tx = smooth(fx - ix), ty = smooth(fy - iy), n = o.cells + 2;
      const a = o.v[iy * n + ix], b = o.v[iy * n + ix + 1], c2 = o.v[(iy + 1) * n + ix], d2 = o.v[(iy + 1) * n + ix + 1];
      v += o.amp * lerp(lerp(a, b, tx), lerp(c2, d2, tx), ty);
    }
    const i = (y * gw + x) * 4;
    img.data[i] = 128; img.data[i + 1] = 153; img.data[i + 2] = 204; img.data[i + 3] = Math.round(clamp(v) * 230);
  }
  g.putImageData(img, 0, 0);
  c.className = 'bp-mottle';
  c.style.cssText = `width:${W}px;height:${H}px;`;
  return c;
}

function sheet(ctx, p, F) {
  const W = F.W, H = F.H, L = F.portrait;
  const { bd, box } = frameBox(F);
  const doc = F.el.ownerDocument;
  const sh = h('div', 'bp-sheet');
  sh.style.cssText = `left:0;top:0;width:${W}px;height:${H}px;--gb:${bd}px;--lamp:${L ? '50% 36%' : '40% 42%'};`;
  F.cam.appendChild(sh);
  sh.appendChild(mottle(doc, W, H, hash32('mottle:' + (ctx.id || ''))));
  const bo = h('div', 'bp-border-out');
  bo.style.cssText = `left:${bd - 22}px;top:${bd - 22}px;width:${W - 2 * (bd - 22)}px;height:${H - 2 * (bd - 22)}px;`;
  const bi = h('div', 'bp-border-in');
  bi.style.cssText = `left:${bd}px;top:${bd}px;width:${W - 2 * bd}px;height:${H - 2 * bd}px;`;
  sh.append(bo, bi);
  // zone references between the borders (sheet furniture)
  const nx = L ? 4 : 8, ny = L ? 8 : 4, letters = 'HGFEDCBA'.slice(8 - ny);
  for (let i = 0; i < nx; i++) for (const y of [bd - 11, H - bd + 11]) {
    const z = h('div', 'bp-zone', { text: String(nx - i), 'data-qa': 'off' });
    z.style.left = `${bd + (W - 2 * bd) * (i + 0.5) / nx}px`; z.style.top = `${y}px`;
    sh.appendChild(z);
  }
  for (let i = 0; i < ny; i++) for (const x of [bd - 11, W - bd + 11]) {
    const z = h('div', 'bp-zone', { text: letters[i], 'data-qa': 'off' });
    z.style.left = `${x}px`; z.style.top = `${bd + (H - 2 * bd) * (i + 0.5) / ny}px`;
    sh.appendChild(z);
  }
  const mkSvg = () => {
    const s = doc.createElementNS(NS, 'svg');
    s.setAttribute('class', 'bp-draw');
    s.setAttribute('width', W); s.setAttribute('height', H); s.setAttribute('viewBox', `0 0 ${W} ${H}`);
    return s;
  };
  const svg = mkSvg();
  const html = h('div', '');
  html.style.cssText = `position:absolute;left:0;top:0;width:${W}px;height:${H}px;`;
  const top = mkSvg();
  F.cam.append(svg, html, top);
  const vig = h('div', 'bp-vig');
  F.ov.appendChild(vig);
  const P = plotter(svg, { penLayer: top });
  const cues = [];
  const stamps = [];
  let camFn = null;

  /** Absolutely positioned lettering. o: {size, w, align, html, weight, color} */
  function text(cls, str, x, y, o = {}) {
    const e = h('div', 'bp-t ' + cls);
    e.style.left = `${Math.round(x)}px`; e.style.top = `${Math.round(y)}px`;
    if (o.size) e.style.fontSize = `${o.size}px`;
    if (o.w) { e.style.width = `${Math.round(o.w)}px`; e.style.whiteSpace = o.nowrap ? 'pre' : 'normal'; }
    if (o.align) e.style.textAlign = o.align;
    if (o.html != null) e.innerHTML = o.html; else e.textContent = String(str);
    (o.parent || html).appendChild(e);
    return e;
  }

  /**
   * Title block (HTML grid). fields: {title, drawn, scale, dwg, rev}. Placed bottom-right (top-right while captions
   * are up). The REV letter stamps in at `stampAt` (rubber-stamp scale + thunk).
   */
  function titleBlock(f, stampAt = 0.6) {
    const w = L ? 520 : 560;
    const tb = h('div', 'bp-tb', { 'data-qa': 'off' });
    tb.style.gridTemplateColumns = '1.25fr .8fr .55fr';
    tb.style.width = `${w}px`;
    const cell = (k, v, cls = '', span = '') => {
      const c = h('div', cls);
      if (span) c.style.gridColumn = span;
      c.append(h('span', 'k', { text: k }), h('span', 'v' + (k === 'Title' ? ' big' : '') + (k === 'Rev' ? ' red' : ''), { text: v }));
      tb.appendChild(c);
      return c;
    };
    cell('Title', f.title || '', 'nr', '1 / 4');
    cell('Drawn by', f.drawn || 'Hermes', 'nb');
    cell('Scale', f.scale || 'NTS', 'nb');
    const rv = cell('Rev', f.rev || 'A', 'nr nb');
    const x = L ? 960 - w : W - bd - w;
    const y = L ? 1500 - 132 : F.caps ? bd : H - bd - 128;
    tb.style.left = `${x}px`; tb.style.top = `${y}px`;
    html.appendChild(tb);
    const v = rv.querySelector('.v');
    stamps.push({ e: v, at: stampAt });
    cues.push({ t: stampAt, sfx: 'appear', gain_db: -10 });
    return { el: tb, x, y, w, h: 128 };
  }

  /** Revision table rows [[letter, description]] at (x, y) width w. */
  function revTable(rows, x, y, w, stampAt = 0) {
    const t = h('div', 'bp-tb', { 'data-qa': 'off' });
    t.style.cssText += `left:${x}px;top:${y}px;width:${w}px;grid-template-columns:64px 1fr;`;
    const hd = (s) => { const c = h('div', ''); c.append(h('span', 'k', { text: s })); c.style.paddingBottom = '2px'; t.appendChild(c); return c; };
    hd('Rev'); hd('Description').classList.add('nr');
    rows.forEach(([r, desc], i) => {
      const last = i === rows.length - 1;
      const a = h('div', last ? 'nb' : '');
      a.appendChild(h('span', 'v red', { text: r }));
      const b = h('div', 'nr' + (last ? ' nb' : ''));
      b.appendChild(h('span', 'v', { text: desc }));
      t.append(a, b);
      if (last && stampAt) stamps.push({ e: b, at: stampAt });
    });
    html.appendChild(t);
    return t;
  }

  /** Camera keys [[t, [cx, cy, zoom]], ...] (sheet px); default: centred, 1.2 % scale drift over the shot. */
  function camera(keys) { camFn = pchip(keys); }

  function update(t) {
    P.update(t);
    for (const s of stamps) {
      const u = seg(t, s.at, s.at + 0.18, ease.outCubic);
      css(s.e, { visibility: t >= s.at ? 'visible' : 'hidden', transform: u < 1 ? `scale(${(1.6 - 0.6 * u).toFixed(3)})` : 'none',
        display: 'block', transformOrigin: '0 50%' });
    }
    const dur = Number(ctx.dur) || 4;
    const [cx, cy, z] = camFn ? camFn(t) : [W / 2, H / 2, 1 + 0.012 * seg(t, 0, dur, ease.inOutQuad)];
    css(F.cam, { transform: `translate3d(${(W / 2).toFixed(2)}px,${(H / 2).toFixed(2)}px,0) scale(${z.toFixed(5)}) translate3d(${(-cx).toFixed(2)}px,${(-cy).toFixed(2)}px,0)` });
  }
  const front = () => { top.appendChild(P.pen); };
  return { W, H, L, bd, box, svg, html, top, P, text, titleBlock, revTable, camera, update, cues, front, sheet: sh };
}

// ------------------------------------------------------------------------------------- listings
const TK = { k: 'k', f: 'k', s: 's', c: 'c', n: 'n', p: '' };
const escH = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
/** Syntax-highlighted HTML for one code line (blueprint classes). */
export function codeHtml(text, lang, path) {
  return highlight(text, lang, path).map(([c, s]) => (TK[c] ? `<span class="${TK[c]}">${escH(s)}</span>` : escH(s))).join('');
}

/**
 * A listing (CODE / DIFF / TERMINAL rows) in a bordered detail box. rows: [{g, text, cls, html}].
 * o: {x, y, w, fs, rowH, gut, pad}. Rows are HTML (QA-measurable); geometry helpers for clouds and leaders.
 */
export function listing(S, rows, o) {
  const fs = o.fs || 24, rowH = o.rowH || Math.round(fs * 1.9), gut = o.gut ?? Math.round(fs * 2.7), pad = o.pad ?? 22;
  const cw = fs * 0.6;
  const el = h('div', 'bp-list');
  el.style.cssText = `left:${o.x}px;top:${o.y}px;width:${o.w}px;height:${rows.length * rowH + 2 * pad}px;font-size:${fs}px;`;
  const maxChars = Math.floor((o.w - gut - 24) / cw);
  const rowEls = rows.map((r, i) => {
    const e = h('div', 'bp-row ' + (r.cls || ''));
    e.style.cssText = `top:${pad + i * rowH}px;height:${rowH}px;grid-template-columns:${gut}px 1fr;width:${o.w}px;`;
    const txt = String(r.text);
    const clipped = txt.length > maxChars ? txt.slice(0, maxChars - 1) + '\u2026' : txt;
    e.innerHTML = `<span class="g">${escH(r.g || '')}</span><span class="t">${r.html && clipped === txt ? r.html : escH(clipped)}</span>`;
    el.appendChild(e);
    return { e, len: clipped.length };
  });
  S.html.appendChild(el);
  return {
    el, rowEls, rowH, fs, cw, pad, gut, maxChars,
    x: o.x, y: o.y, w: o.w, h: rows.length * rowH + 2 * pad,
    rowY: (i) => o.y + pad + i * rowH + rowH / 2,
    rowTop: (i) => o.y + pad + i * rowH,
    textX: o.x + gut,
    rowBox: (i) => ({ x: o.x + gut, y: o.y + pad + i * rowH, w: Math.max(cw, rowEls[i].len * cw), h: rowH }),
  };
}

export { clamp, lerp, seg, ease, rng };
