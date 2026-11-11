// Hype kits/base — the single import point of the runtime + the DOM scene wrapper used by all kits.
// (If the runtime entry moves, only this file changes.)
import { sr } from '../../runtime/showreel.js';
import { BASE_CSS } from './css.js';
import { frame, css } from './dom.js';
import { drift, clamp, setMotion } from './motion.js';

export { sr };

const STATE = new WeakMap();

/** Apply documented defaults ({name: {default}}) to params. */
export function withDefaults(p, docs) {
  const out = { ...(p || {}) };
  for (const [k, d] of Object.entries(docs || {})) {
    if (out[k] === undefined && d && Object.prototype.hasOwnProperty.call(d, 'default')) out[k] = d.default;
  }
  return out;
}

/**
 * Register a 'dom' scene whose build(ctx, p, F) returns {render(t), cues?}. The build runs once per shot
 * instance (setup, or the first cues()/render() call); render(t) must be a pure function of t.
 * F = the scene frame from frame() (reference-px layout, theme applied).
 */
export function defineDomScene(id, def) {
  const kind = def.kind || id.split('/').pop().toLowerCase();
  function ensure(ctx, p) {
    let s = STATE.get(ctx);
    if (!s) {
      setMotion(ctx.film && ctx.film.theme);
      const q = withDefaults(p, def.params);
      const F = frame(ctx, q, kind, BASE_CSS + (def.css || ''));
      s = def.build(ctx, q, F) || {};
      s.F = F;
      STATE.set(ctx, s);
    }
    return s;
  }
  sr.defineScene(id, {
    layer: 'dom',
    describe: def.describe,
    params: def.params || {},
    fonts: [],
    setup(ctx, p) { ensure(ctx, p); },
    render(ctx, t, p) { ensure(ctx, p).render(t); },
    cues(ctx, p) {
      const dur = Number(ctx.dur) || 1e9;
      const mute = new Set(Array.isArray(p && p._mute) ? p._mute : []);
      return (ensure(ctx, p).cues || []).filter((c) => c && c.t >= 0 && c.t < dur - 0.02 && !mute.has(c.sfx))
        .map((c) => ({ t: Math.round(c.t * 1000) / 1000, sfx: c.sfx, gain_db: c.gain_db ?? 0 }));
    },
  });
}

/**
 * Flat 2.5D camera on F.cam: place content point (cx, cy) at the frame centre with `zoom`, plus hand-held
 * drift so no frame is parked. Also parallaxes the background grid.
 */
export function flatCam(F, t, cx, cy, zoom = 1, o = {}) {
  const [dx, dy, dr] = drift(t, o.seed ?? 7, o.drift ?? 2.2, o.rot ?? 0.05);
  const lift = o.lift || 0;
  const ax = o.ax ?? F.W / 2, ay = o.ay ?? F.H / 2;
  css(F.cam, { transform: `translate(${ax.toFixed(2)}px, ${(ay - lift).toFixed(2)}px) rotate(${((o.roll || 0) + dr).toFixed(4)}deg) scale(${zoom.toFixed(5)}) translate(${(-cx + dx).toFixed(2)}px, ${(-cy + dy).toFixed(2)}px)` });
  css(F.bg, { '--gx': `${(-(cx - F.W / 2) * 0.08 + dx * 2).toFixed(2)}px`, '--gy': `${(-(cy - F.H / 2) * 0.08 + dy * 2).toFixed(2)}px` });
}

/** Place an element absolutely at (x, y) with size (w, h) in reference px. */
export function place(el, x, y, w, h) {
  el.style.position = 'absolute';
  el.style.left = `${Math.round(x)}px`;
  el.style.top = `${Math.round(y)}px`;
  if (w != null) el.style.width = `${Math.round(w)}px`;
  if (h != null) el.style.height = `${Math.round(h)}px`;
  return el;
}

/** Zoom so that a w x h rect fills at most `fill` of the frame's usable area (never below minZoom). */
export function fitZoom(F, w, h, fill = 0.82, minZoom = 0.3, maxZoom = 3) {
  const uw = F.W - F.safe.l - F.safe.r, uh = F.H - F.safe.t - F.safe.b;
  return clamp(Math.min((uw * fill) / w, (uh * fill) / h), minZoom, maxZoom);
}

/** Standard per-scene clamp of local time to the shot (transitions may pass t slightly outside). */
export const tl = (t, dur) => clamp(t, -0.5, dur + 1.5);

/**
 * A full-frame flex box (inside F.cam) that centres its children: layout by CSS, so nothing depends on
 * measuring text while the shot may still be hidden. dy shifts the centre (reference px).
 */
export function centerBox(F, dy = 0, dir = 'column') {
  const box = F.el.ownerDocument.createElement('div');
  box.style.cssText = `position:absolute;left:0;top:${dy}px;width:${F.W}px;height:${F.H}px;display:flex;flex-direction:${dir};` +
    'align-items:center;justify-content:center;text-align:center;';
  F.cam.appendChild(box);
  return box;
}
