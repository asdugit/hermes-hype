// Auteur kit "ink" — the page: warm paper with a procedural texture (grain tile + soft mottling, generated once
// per page size as PNG data URLs and shown as plain <img>/background layers, decoded in setup), a printed vignette,
// and the hand-held camera (2D transform: gentle drift, slow pushes along PCHIP keys). inkScene() registers a
// kit:ink scene with the same contract as kit:base defineDomScene plus an async setup that awaits image decodes.

import { sr, withDefaults } from '../../base/scene.js';
import { h, css, frame } from '../../base/dom.js';
import { BASE_CSS } from '../../base/css.js';
import { clamp, pchip, drift, rng } from '../../base/motion.js';
import { COMMON } from '../../base/scenes-panels.js';
import { INK_CSS } from '../css.js';
import { C } from './ink.js';

export const ICOMMON = { ...COMMON, theme: { type: 'string', default: 'ink', doc: 'theme tokens (ink)' } };

/** Image decodes started while building (taped shots, paper); inkScene's setup awaits them. */
export const PENDING = [];
const STATE = new WeakMap();
const TEX = new Map();
let UID = 0;
const T3D = /translate3d\(\s*([^,()]+),\s*([^,()]+),\s*0(?:px)?\s*\)/g;

/** Rewrite plain translate3d (z = 0) transforms of base blocks to 2D so the page stays one paint layer. */
function flat2d(root) {
  for (const el of root.querySelectorAll('[style*="translate3d"]')) {
    const tf = el.style.transform;
    if (tf && tf.includes('translate3d')) el.style.transform = tf.replace(T3D, 'translate($1, $2)');
  }
}

/**
 * Register a kit:ink scene. def.build(ctx, p, F, P) gets the base frame F and a fresh page P and returns
 * {render(t), cues}. Sizes are reference px (short side 1080). P.W x P.H = the frame.
 */
const C0 = { ...C };
/** film.theme.palette.ink overrides the JS palette (drawn art colours) for this film (customize/theme.py). */
function themePalette(ctx) {
  const o = ctx.film && ctx.film.theme && ctx.film.theme.palette && ctx.film.theme.palette.ink;
  Object.assign(C, C0, o && typeof o === 'object' ? o : {});
}

export function inkScene(id, def) {
  const kind = def.kind || `ik-${id.split('/').pop().toLowerCase()}`;
  const params = { ...ICOMMON, ...(def.params || {}) };
  function ensure(ctx, p) {
    let s = STATE.get(ctx);
    if (!s) {
      themePalette(ctx);
      const q = withDefaults(p, params);
      const F = frame(ctx, q, kind, BASE_CSS + INK_CSS);
      F.el.classList.add('sr-theme-ink');
      const P = makePage(F, ctx);
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
    render(ctx, t, p) {
      const s = ensure(ctx, p);
      s.render(t);
      flat2d(s.F.el);
    },
    cues(ctx, p) {
      const dur = Number(ctx.dur) || 1e9;
      const mute = new Set(Array.isArray(p && p._mute) ? p._mute : []);
      return (ensure(ctx, p).cues || []).filter((c) => c && c.t >= 0 && c.t < dur - 0.02 && !mute.has(c.sfx))
        .map((c) => ({ t: Math.round(c.t * 1000) / 1000, sfx: c.sfx, gain_db: c.gain_db ?? 0 }));
    },
  });
}

/** PNG data URL from an RGBA generator over a w x h grid (canvas used only to encode, never shown). */
function png(doc, w, hh, fn) {
  const c = doc.createElement('canvas');
  c.width = w; c.height = hh;
  const g = c.getContext('2d');
  const img = g.createImageData(w, hh);
  fn(img.data, w, hh);
  g.putImageData(img, 0, 0);
  return c.toDataURL('image/png');
}

/** Smooth value noise on a coarse lattice (bilinear, smoothstep), fbm of 3 octaves, values ~0..1. */
function mottleField(w, hh, seed) {
  const out = new Float32Array(w * hh);
  let amp = 1, tot = 0;
  for (let o = 0; o < 3; o++) {
    const cell = [22, 9, 4][o];
    const gw = Math.ceil(w / cell) + 2, gh = Math.ceil(hh / cell) + 2;
    const r = rng(seed * 31 + o * 7 + 1);
    const lat = new Float32Array(gw * gh);
    for (let i = 0; i < lat.length; i++) lat[i] = r();
    for (let y = 0; y < hh; y++) {
      const fy = y / cell, iy = Math.floor(fy), vy = fy - iy, sy = vy * vy * (3 - 2 * vy);
      for (let x = 0; x < w; x++) {
        const fx = x / cell, ix = Math.floor(fx), vx = fx - ix, sx = vx * vx * (3 - 2 * vx);
        const a = lat[iy * gw + ix], b = lat[iy * gw + ix + 1], c = lat[(iy + 1) * gw + ix], d = lat[(iy + 1) * gw + ix + 1];
        out[y * w + x] += amp * ((a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy);
      }
    }
    tot += amp; amp *= 0.5;
  }
  for (let i = 0; i < out.length; i++) out[i] /= tot;
  return out;
}

/** Paper textures for a page size (cached): {grain: 256 px tile, mottle: low-res stretched blotches}. */
export function paperTex(doc, W, H, seed = 7) {
  const key = `${W}x${H}:${seed}`;
  if (TEX.has(key)) return TEX.get(key);
  const grain = png(doc, 256, 256, (d) => {
    const r = rng(seed * 977 + 3);
    for (let i = 0; i < 256 * 256; i++) {
      const v = r(), fleck = r() > 0.9965 ? 0.55 : 0;
      d[i * 4] = 92; d[i * 4 + 1] = 62; d[i * 4 + 2] = 38;
      d[i * 4 + 3] = Math.round(255 * Math.min(0.6, v * v * 0.2 + fleck));
    }
  });
  const mw = Math.ceil(W / 8), mh = Math.ceil(H / 8);
  const f = mottleField(mw, mh, seed);
  const mottle = png(doc, mw, mh, (d) => {
    for (let i = 0; i < mw * mh; i++) {
      const v = clamp((f[i] - 0.38) * 1.6);
      d[i * 4] = 150; d[i * 4 + 1] = 112; d[i * 4 + 2] = 70;
      d[i * 4 + 3] = Math.round(255 * v * 0.2);
    }
  });
  const out = { grain, mottle };
  TEX.set(key, out);
  return out;
}

/** Decode an image URL into PENDING (so the first frame already shows it). */
export function preload(doc, src) {
  const im = doc.createElement('img');
  im.decoding = 'sync';
  im.src = src;
  PENDING.push(im.decode().catch(() => {}));
  return im;
}

/**
 * Build the page inside the camera layer: paper sheet (with margin for drift/pushes), texture layers, the art
 * root `content` (reference px, W x H), and a `top` layer for marks that sit over captures.
 */
export function makePage(F, ctx) {
  const doc = F.el.ownerDocument;
  const W = F.W, H = F.H, M = 160;
  const seed = 7;
  const tex = paperTex(doc, W, H, seed);
  const sheet = h('div', 'ik-sheet');
  sheet.style.cssText = `left:${-M}px;top:${-M}px;width:${W + 2 * M}px;height:${H + 2 * M}px;`;
  const mot = preload(doc, tex.mottle);
  mot.className = 'ik-mottle';
  const grain = h('div', 'ik-grain');
  grain.style.backgroundImage = `url("${tex.grain}")`;
  preload(doc, tex.grain);
  sheet.append(mot, grain);
  const content = h('div', 'ik-abs');
  content.style.cssText = `left:0;top:0;width:${W}px;height:${H}px;`;
  const top = h('div', 'ik-abs ik-top');
  top.style.cssText = `left:0;top:0;width:${W}px;height:${H}px;`;
  F.cam.append(sheet, content, top);
  F.ov.appendChild(h('div', 'ik-vignette'));
  const dur = Math.max(0.5, Number(ctx && ctx.dur) || 4);

  /** Keep a camera view (centre + zoom >= 1) within the sheet. */
  const B = { x0: 0, y0: 0, x1: W, y1: H };
  function clampView(cx, cy, z) {
    const zz = Math.max(1, z);
    const hw = W / (2 * zz), hh = H / (2 * zz);
    return [clamp(cx, B.x0 + hw - M * 0.5, B.x1 - hw + M * 0.5), clamp(cy, B.y0 + hh - M * 0.5, B.y1 - hh + M * 0.5), zz];
  }
  /** Grow the paper (content-space extents) for scenes that pan beyond the frame. */
  function bounds(x0, y0, x1, y1) {
    Object.assign(B, { x0, y0, x1, y1 });
    sheet.style.cssText = `left:${x0 - M}px;top:${y0 - M}px;width:${x1 - x0 + 2 * M}px;height:${y1 - y0 + 2 * M}px;`;
  }
  /** Camera target that frames rect r ({x,y,w,h}) with pad (zoom clamped to zmax). */
  function frameRect(r, pad = 60, zmax = 2.2) {
    if (r === 'page') return [W / 2, H / 2, 1];
    if (Array.isArray(r)) return r;
    const z = clamp(Math.min(W / (r.w + 2 * pad), H / (r.h + 2 * pad)), 1, zmax);
    return [r.x + r.w / 2, r.y + r.h / 2, z];
  }
  /** PCHIP camera track over keys [[t, rect | 'page' | [cx, cy, z]], ...] -> cam(t). */
  function track(ks, pad, zmax) {
    const pts = ks.map(([t, r]) => [t, frameRect(r, pad, zmax)]);
    if (pts.length === 1) pts.push([pts[0][0] + 1, pts[0][1]]);
    return pchip(pts);
  }
  /**
   * Apply the camera for time t: [cx, cy, z] plus hand-held drift. 2D transform on purpose (a composited
   * translate3d layer keeps raster scales from earlier seeks while zooming, which breaks determinism).
   */
  function camera(t, v, o = {}) {
    const [cx, cy, z] = clampView(v[0], v[1], v[2] ?? 1);
    const [dx, dy, dr] = drift(t, o.seed ?? 11, o.drift ?? 2.4, o.rot ?? 0);
    css(F.cam, { transform: `translate(${(W / 2).toFixed(2)}px,${(H / 2 - (o.lift || 0)).toFixed(2)}px) rotate(${dr.toFixed(4)}deg) scale(${z.toFixed(5)}) translate(${(-cx + dx).toFixed(2)}px,${(-cy + dy).toFixed(2)}px)` });
  }
  /** Is the caption band up (lift content clear of it)? */
  const lift = F.caps ? (F.portrait ? 0 : 40) : 0;
  const uid = `ik${(++UID).toString(36)}`;
  return { doc, W, H, F, sheet, content, top, track, camera, frameRect, bounds, dur, lift, uid, portrait: F.portrait, safe: F.safe };
}
