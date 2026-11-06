// Showreel kit "launch" — scene scaffold: every kit:launch scene is a base content block placed on the lit
// table world, shot by a PCHIP look-at camera, with screen-space kinetic type on top.

import { defineDomScene } from '../base/scene.js';
import { h, css } from '../base/dom.js';
import { pchip, clamp, seg, ease } from '../base/motion.js';
import { COMMON } from '../base/scenes-panels.js';
import { makeWorld } from './world.js';
import { LAUNCH_CSS } from './css.js';

export const LCOMMON = {
  ...COMMON, theme: { type: 'string', default: 'launch', doc: 'theme tokens (launch by default)' },
  product_scale: { type: 'number', default: 1.0, doc: "multiplies the product media's on-screen size (camera moves closer; 0.5-3, cap 3)" },
};

/** The product_scale param, clamped to 0.5..3 (1 when absent or invalid). */
export function productScale(p) {
  const v = Number(p && p.product_scale);
  return Number.isFinite(v) && v > 0 ? clamp(v, 0.5, 3) : 1;
}

/**
 * Register a kit:launch scene. build(ctx, p, F, W) gets the frame and a fresh table world;
 * it returns {render(t), cues}. The world camera must be set every frame by render().
 */
export function launchScene(id, def) {
  defineDomScene(id, {
    kind: def.kind || id.split('/').pop().toLowerCase(),
    describe: def.describe,
    params: { ...LCOMMON, ...(def.params || {}) },
    css: LAUNCH_CSS,
    build(ctx, p, F) {
      const W = makeWorld(F, { P: def.P || (F.portrait ? 1900 : 1700) });
      const vig = h('div', 'slw-vignette');
      F.ov.appendChild(vig);
      return def.build(ctx, p, F, W);
    },
  });
}

/** Camera track: keys [[t, {target:[x,y,z], dist, yaw, pitch, roll}], ...] -> t => cam (PCHIP, flat ends). */
export function camTrack(keys) {
  const f = pchip(keys.map(([t, c]) => [t, [c.target[0], c.target[1], c.target[2] || 0, c.dist, c.yaw || 0, c.pitch || 0, c.roll || 0]]));
  return (t) => { const v = f(t); return { target: [v[0], v[1], v[2]], dist: v[3], yaw: v[4], pitch: v[5], roll: v[6] }; };
}

/** Node centre / rect centre in world space (node-local px rect {x,y,w,h}). */
export function rectCenter(W, n, r) { return W.nodePoint(n, r.x + r.w / 2, r.y + r.h / 2); }

/**
 * Camera distance that fits a node-local rect (w x h px) when viewed at `pitch` relative to the panel
 * normal (foreshortening), into fill fractions of the frame. Lens shift (region) handled by the caller.
 */
export function fitRect(W, F, w, hh, relPitch = 20, fill = 0.84, fillH = 0.78) {
  return W.fitDist(w, hh * Math.cos((relPitch * Math.PI) / 180), fill, fillH);
}

/**
 * Lens shift: move the whole view so the world origin projects to (ax, ay) instead of the frame centre
 * (keeps type columns clear without tilting the camera).
 */
export function lensShift(W, F, ax, ay, lift = 0) {
  W.curShift = [ax - F.W / 2, ay - F.H / 2 - lift];
  W.applyShift(W.curShift);
}

/** Panel entrance for nodes: rise from the table (z) + unblur, starting before t=0 so frame 0 is in motion. */
export function nodeIn(t, t0 = -0.3, dur = 0.9) {
  return seg(t, t0, t0 + dur, ease.outQuint);
}

/**
 * Standard UI camera grammar on one panel: establish wide (>= 1 s), push to `rect` (node px) at >= 1.4x in
 * 0.75 s, hold with drift. o: {tPush, dur, yaw0, pitchWide, pitchPush, wideMul, region:{x,y,w,h} (frame px
 * area the panel must live in; lens-shifted), keepLeft (keep the panel's left edge on screen)}.
 */
export function pushTrack(W, F, n, b, rect, o) {
  const R = o.region || { x: 0, y: 0, w: F.W, h: F.H };
  const fx = R.w / F.W, fy = R.h / F.H;
  const shift = [R.x + R.w / 2 - F.W / 2, R.y + R.h / 2 - F.H / 2];
  const relW = o.pitchWide ?? 20, relP = o.pitchPush ?? 12;
  const cW = W.nodePoint(n, b.w / 2, b.h / 2);
  let dW = fitRect(W, F, b.w, b.h, relW, 0.88 * fx, 0.82 * fy) * (o.wideMul ?? 1.0);
  let dP = fitRect(W, F, rect.w, rect.h, relP, (o.pushFillW ?? 0.9) * fx, (o.pushFillH ?? 0.62) * fy);
  dP = clamp(dP, dW / (o.maxPush ?? 2.1), dW / 1.4);
  const ps = o.scale || 1;          // product_scale: the whole move happens closer
  dW /= ps; dP /= ps;
  const c = rectCenter(W, n, rect);
  let target = [c[0], c[1], c[2]];
  if (o.keepLeft !== false) {
    for (let k = 0; k < 4; k++) {
      W.camera(0, { target, dist: dP, yaw: -1, pitch: relP, roll: -0.4, shift }, { amp: 0, rollAmp: 0 });
      const sx = W.project(W.nodePoint(n, 0, rect.y + rect.h / 2))[0];
      const ex = W.project(W.nodePoint(n, b.w, rect.y + rect.h / 2))[0];
      const want = R.x + 40;
      if (sx >= want - 6 || ex - sx < R.w - 80) {
        if (ex - sx < R.w - 80) target = [cW[0] + (target[0] - cW[0]) * 0, target[1], target[2]];
        break;
      }
      target = [target[0] - ((want + 4 - sx) * dP) / W.P, target[1], target[2]];
    }
  }
  const tp = o.tPush;
  const y0 = o.yaw0 ?? -8;
  const tr = camTrack([
    [0, { target: [cW[0], cW[1] + 20, cW[2]], dist: dW * 1.08, yaw: y0, pitch: relW + 6, roll: -1.4 }],
    [tp, { target: cW, dist: dW, yaw: y0 * 0.6, pitch: relW, roll: -0.9 }],
    [tp + 0.75, { target, dist: dP, yaw: -1, pitch: relP, roll: -0.4 }],
    [o.dur + 1, { target: [target[0] + 12, target[1] + 10, target[2]], dist: dP * 0.97, yaw: 0, pitch: relP - 1, roll: -0.2 }],
  ]);
  return (t) => ({ ...tr(t), shift });
}

/** Connectors leaving a panel's right edge (output) and arriving at its left edge (input). */
export function panelWires(W, n, b, yOut, o = {}) {
  const p0 = W.nodePoint(n, b.w, yOut);
  const q0 = W.nodePoint(n, 0, b.h * 0.72);
  const out = W.wire([[p0[0] + 16, p0[1]], [p0[0] + 300, p0[1]], [p0[0] + 300, p0[1] + 900], [p0[0] + 3200, p0[1] + 900]],
    { pulseStart: o.outAt ?? 0.6, every: 1.2, draw: o.draw });
  const inn = W.wire([[q0[0] - 16, q0[1]], [q0[0] - 360, q0[1]], [q0[0] - 360, q0[1] + 1100], [q0[0] - 3200, q0[1] + 1100]],
    { pulseStart: 0.1, every: 1.4, reverse: true, port: true });
  return [out, inn];
}

/**
 * Converging connectors for type-led shots (TITLE/STATS/CALLOUT/END): `n` wires from far away to a hub
 * near (x, y) with pulses arriving at `arrive`. Deterministic layout from `seed`.
 */
export function hubWires(W, x, y, nWires = 4, o = {}) {
  const out = [];
  const angles = o.angles || [200, 160, 330, 20, 250, 290].slice(0, nWires);
  angles.forEach((a, i) => {
    const r = (a * Math.PI) / 180;
    const sx = Math.cos(r) >= 0 ? 1 : -1, sy = Math.sin(r) >= 0 ? 1 : -1;
    const r0x = o.r0x ?? 180, r0y = o.r0y ?? 110;
    const p0 = [x + sx * r0x, y + sy * (r0y * Math.abs(Math.sin(r)) + 10 * i)];
    const p1 = [x + sx * (520 + 150 * i), p0[1]];
    const p2 = [p1[0], y + sy * (380 + 130 * i)];
    const p3 = [p1[0] + sx * 3200, p2[1]];
    out.push(W.wire([p0, p1, p2, p3], { pulseStart: (o.arrive ?? 0.5) - 0.9 + i * 0.13, every: o.every ?? 1.6,
      reverse: true, port: o.ports ?? true, draw: o.draw }));
  });
  return out;
}

/** Screen-space kinetic headline helpers are reused from kits/base; re-export for scene files. */
export { h, css, clamp, seg, ease, pchip };
