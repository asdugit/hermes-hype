// Showreel kit "comic" — the page: newsprint paper, a grid of ink-bordered panels with halftone / sunburst
// backgrounds, panels that assemble, and the motion-comic camera (holds on a panel, glides along the Z-path to
// the next, pulls back to the full page) with page shake on impacts. comicScene() registers a kit:comic scene.

import { sr, withDefaults } from '../../base/scene.js';
import { h, css, frame } from '../../base/dom.js';
import { BASE_CSS } from '../../base/css.js';
import { seg, ease, clamp, pchip, lerp, drift } from '../../base/motion.js';
import { COMMON } from '../../base/scenes-panels.js';
import { C, halftone, rays, svgEl, PENDING } from './art.js';
import { pageShake, pop } from './letter.js';
import { COMIC_CSS } from '../css.js';

export const CCOMMON = { ...COMMON, theme: { type: 'string', default: 'comic', doc: 'theme tokens (comic)' } };

const STATE = new WeakMap();
/**
 * Register a kit:comic scene. def.build(ctx, p, F, P) gets the base frame F and a fresh page P and returns
 * {render(t), cues}. Frame size is reference px (short side 1080); P.W x P.H = the frame. Same contract as
 * kit:base defineDomScene, plus an async setup that waits for the flattened art / printed shots to decode.
 */
export function comicScene(id, def) {
  const kind = def.kind || `cx-${id.split('/').pop().toLowerCase()}`;
  const params = { ...CCOMMON, ...(def.params || {}) };
  function ensure(ctx, p) {
    let s = STATE.get(ctx);
    if (!s) {
      const q = withDefaults(p, params);
      const F = frame(ctx, q, kind, BASE_CSS + COMIC_CSS);
      F.el.classList.add('sr-theme-comic');
      const P = makePage(F);
      const b = def.build(ctx, q, F, P) || {};
      s = { F, cues: b.cues || [], render: (t) => b.render(t), pending: PENDING.splice(0) };
      STATE.set(ctx, s);
    }
    return s;
  }
  sr.defineScene(id, {
    layer: 'dom',
    describe: def.describe,
    params,
    fonts: [],
    async setup(ctx, p) {
      const s = ensure(ctx, p);
      if (s.pending.length) await Promise.all(s.pending.splice(0));
    },
    render(ctx, t, p) { ensure(ctx, p).render(t); },
    cues(ctx, p) {
      const dur = Number(ctx.dur) || 1e9;
      const mute = new Set(Array.isArray(p && p._mute) ? p._mute : []);
      return (ensure(ctx, p).cues || []).filter((c) => c && c.t >= 0 && c.t < dur - 0.02 && !mute.has(c.sfx))
        .map((c) => ({ t: Math.round(c.t * 1000) / 1000, sfx: c.sfx, gain_db: c.gain_db ?? 0 }));
    },
  });
}

/** Panel background presets (art drawn once): calm dots, action rays, splash, cover sun, grey, night. */
const BG = {
  white: () => ({}),
  cyan: () => ({ tone: { color: 'cyan', angle: 15, f: (u, v) => v * 1.1 - 0.15 + u * 0.2 } }),
  magenta: () => ({ tone: { color: 'magenta', angle: 22, cell: 15, f: (u, v) => (1 - v) * 0.9 - 0.1 + u * 0.15 } }),
  action: (o) => ({ fill: C.yellow, rays: { color: C.white, n: 40, inner: 30 }, tone: { color: 'orange', angle: 45, blend: 'multiply', f: (u, v) => Math.hypot(u - o.rx, v - o.ry) * 1.6 - 0.1 } }),
  splash: (o) => ({ fill: C.red, rays: { color: C.yellow, n: 48 }, tone: { color: 'magenta', angle: 30, cell: 18, blend: 'multiply', f: (u, v) => Math.hypot(u - o.rx, v - o.ry) * 1.7 - 0.35 } }),
  sun: (o) => ({ fill: C.yellow, rays: { color: C.orange, n: 36 }, tone: { color: 'magenta', angle: 22, cell: 18, max: 0.6, blend: 'multiply', f: (u, v) => Math.hypot(u - o.rx, (v - o.ry) * 0.8) * 1.5 - 0.25 } }),
  blue: (o) => ({ fill: C.blue, rays: { color: '#2A73D6', n: 32 }, tone: { color: 'cyan', angle: 15, cell: 18, max: 0.55, f: (u, v) => Math.hypot(u - o.rx, v - o.ry) * 1.25 - 0.5 } }),
  grey: () => ({ fill: '#E9E4DA', tone: { color: '#A39C93', angle: 45, cell: 14, f: (u, v) => 0.25 + v * 0.35 } }),
  paper: () => ({ fill: C.white, tone: { color: '#E8D9B5', angle: 15, cell: 12, f: () => 0.45 } }),
};

/** Build the page (paper + print dots) inside the camera layer. Returns the page API P. */
export function makePage(F) {
  const doc = F.el.ownerDocument;
  const W = F.W, H = F.H;
  const el = h('div', 'cx-page');
  el.style.cssText = `left:-60px;top:-60px;width:${W + 120}px;height:${H + 120}px;`;
  const content = h('div', 'cx-abs');
  content.style.cssText = `left:60px;top:60px;width:${W}px;height:${H}px;`;
  el.appendChild(content);
  el.appendChild(h('div', 'cx-print'));
  F.cam.appendChild(el);
  const panels = [];
  const spin = [];

  /** A bordered panel at rect {x, y, w, h} with a background preset. o: {bg, rays:[fx, fy], seed, rot}. */
  function panel(rect, o = {}) {
    const p = h('div', 'cx-panel');
    p.style.cssText = `left:${rect.x}px;top:${rect.y}px;width:${rect.w}px;height:${rect.h}px;`;
    const bgl = h('div', 'cx-bgl');
    p.appendChild(bgl);
    const [rx, ry] = o.rays || [0.5, 0.5];
    const spec = (BG[o.bg || 'white'] || BG.white)({ rx, ry });
    if (spec.fill) bgl.style.background = spec.fill;
    let r = null;
    if (spec.rays) {
      r = rays(doc, rect.w, rect.h, rect.w * rx, rect.h * ry, spec.rays.n, spec.rays.color, o.seed || 3, spec.rays.inner || 0);
      bgl.appendChild(r.el);
      spin.push({ el: r.el, rate: o.spin ?? 2.2, phase: o.seed || 3 });
    }
    if (spec.tone) bgl.appendChild(halftone(doc, rect.w, rect.h, { cell: 16, ...spec.tone }));
    content.appendChild(p);
    const api = { el: p, bg: bgl, x: rect.x, y: rect.y, w: rect.w, h: rect.h, rect, rays: r,
      cx: rect.x + rect.w / 2, cy: rect.y + rect.h / 2 };
    panels.push(api);
    return api;
  }

  /** Panel assembles: wipes in from the reading side, pops 0.96 -> 1. */
  function panelIn(pn, t, t0, dir = 'left') {
    const u = seg(t, t0, t0 + 0.28, ease.outCubic);
    const k = ((1 - u) * 100).toFixed(2);
    const clip = dir === 'top' ? `inset(-12px -12px calc(${k}% - 12px) -12px)` : dir === 'right' ? `inset(-12px -12px -12px calc(${k}% - 12px))`
      : `inset(-12px calc(${k}% - 12px) -12px -12px)`;
    const p = pop(t, t0, 0.3, 0.96);
    css(pn.el, { clipPath: u >= 1 ? 'none' : clip, visibility: t < t0 ? 'hidden' : 'visible', transform: `scale(${p.s.toFixed(4)})` });
  }

  /** Slow sunburst rotation (degrees per second); the halftone never moves (it is the paper). */
  function spinRays(t) {
    for (const s of spin) css(s.el, { transform: `rotate(${(t * s.rate + s.phase).toFixed(3)}deg)` });
  }

  /** Camera target for a rect (zoom to fit with pad, clamped so the view stays on the page). */
  function frameRect(r, pad = 40, zmax = 2.4) {
    if (r === 'page') return [W / 2, H / 2, 1];
    if (Array.isArray(r)) return clampView(r[0], r[1], r[2]);
    const z = clamp(Math.min(W / (r.w + 2 * pad), H / (r.h + 2 * pad)), 1, zmax);
    return clampView(r.x + r.w / 2, r.y + r.h / 2, z);
  }

  /** Keep a camera view (centre + zoom >= 1) on the page. */
  function clampView(cx, cy, z) {
    const zz = Math.max(1, z);
    const hw = W / (2 * zz), hh = H / (2 * zz);
    return [clamp(cx, hw, W - hw), clamp(cy, hh, H - hh), zz];
  }

  /**
   * Camera track: keys [[t, rect | 'page' | [cx, cy, z]], ...] (PCHIP: flat at every key, so duplicate keys hold).
   * Returns cam(t) -> [cx, cy, z].
   */
  function track(ks, pad = 40, zmax = 2.4) {
    const pts = ks.map(([t, r]) => [t, frameRect(r, pad, zmax)]);
    if (pts.length === 1) pts.push([pts[0][0] + 1, pts[0][1]]);
    return pchip(pts);
  }

  /** Apply the camera (with optional page-shake impacts) for time t. */
  function camera(t, cxyz, o = {}) {
    const [sx, sy] = pageShake(t, o.shakes || [], o.amp || 10);
    const [cx0, cy0, z] = clampView(cxyz[0], cxyz[1], cxyz[2]);
    const cx = cx0 - sx / z, cy = cy0 - sy / z;
    // 2D transforms only (like base flatCam): a composited camera layer keeps raster scales from
    // earlier frames when the zoom changes, so the same t could rasterise differently after a different seek path.
    const [dx, dy, dr] = drift(t, 7, o.drift ?? 1.4, 0.03);
    css(F.cam, { transform: `translate(${(W / 2).toFixed(2)}px,${(H / 2 - (o.lift || 0)).toFixed(2)}px) rotate(${dr.toFixed(4)}deg) scale(${z.toFixed(5)}) translate(${(-cx + dx).toFixed(2)}px,${(-cy + dy).toFixed(2)}px)` });
    css(F.bg, { '--gx': `${(-(cx - W / 2) * 0.08 + dx * 2).toFixed(2)}px`, '--gy': `${(-(cy - H / 2) * 0.08 + dy * 2).toFixed(2)}px` });
  }

  /** Standard Z-path grid in reference px. rows: [[colWeights...], heightWeight] list; m margin, g gutter. */
  function grid(rows, o = {}) {
    const m = o.m ?? 40, g = o.g ?? 26, top = o.top ?? m, bottom = o.bottom ?? m;
    const totalH = H - top - bottom - g * (rows.length - 1);
    const hsum = rows.reduce((a, r) => a + (r[1] || 1), 0);
    const out = [];
    let y = top;
    for (const [cols, hw] of rows) {
      const rh = Math.round((totalH * (hw || 1)) / hsum);
      const wsum = cols.reduce((a, b) => a + b, 0);
      const totalW = W - 2 * m - g * (cols.length - 1);
      let x = m;
      for (const cw of cols) {
        const w = Math.round((totalW * cw) / wsum);
        out.push({ x, y, w, h: rh });
        x += w + g;
      }
      y += rh + g;
    }
    return out;
  }

  return { el, content, doc, W, H, F, panel, panelIn, spinRays, frameRect, track, camera, grid, panels, svg: (w, hh, s, o) => svgEl(doc, w, hh, s, o) };
}

/** Tilt + rise entrance for a block inside a panel (snap with a little overshoot). */
export function snapIn(el, t, t0, o = {}) {
  const p = pop(t, t0, o.dur || 0.24, o.from ?? 0.9);
  const y = (1 - seg(t, t0, t0 + (o.dur || 0.24), ease.outCubic)) * (o.rise ?? 30);
  css(el, { opacity: p.op.toFixed(3), transform: `translate(0,${y.toFixed(2)}px) rotate(${o.rot || 0}deg) scale(${p.s.toFixed(4)})`, transformOrigin: o.origin || '50% 50%' });
}

export { C, h, css, seg, ease, clamp, lerp, pchip };
