// camera.js — pixel-disciplined camera for kit scenes. A scene draws its WORLD into a game-resolution Screen and
// (optionally) its UI into a second Screen; present() shows the world through a camera {zoom, x, y} and lays the
// UI on top unzoomed. On a hi-res surface (shot res = film size) every game pixel becomes an exact
// round(k * zoom) square, so zooms step through crisp integer pixel sizes (4 -> 5 -> 6 -> 8 px at 1080p) and pans
// move in whole output pixels. On a game-res surface (res [480,270]) the zoom floors to an integer crop.
import { seg, step, ease, lerp, clamp } from './motion.js';

/** A camera at rest: whole world, centred. */
export const REST = Object.freeze({ zoom: 1, x: null, y: null });

/**
 * Keyframed camera at time t: ks = [[t, {zoom, x, y}], ...]; x/y in world game px (null = world centre).
 * Each segment eases with `e` (default inOutCubic); zoom is stepped on twos so pixel sizes snap like a sprite.
 */
export function camAt(t, ks, e = ease.inOutCubic) {
  if (!ks || !ks.length) return { ...REST };
  const tq = step(t, 15);
  const pick = (a, b, u) => ({ zoom: lerp(a.zoom ?? 1, b.zoom ?? 1, u), x: mixN(a.x, b.x, u), y: mixN(a.y, b.y, u) });
  if (tq <= ks[0][0]) return { ...REST, ...ks[0][1] };
  for (let i = 1; i < ks.length; i++) {
    const [t0, a] = ks[i - 1], [t1, b] = ks[i];
    if (tq <= t1) {
      const f = b.ease || e, u = f(seg(tq, t0, t1));
      // pans run on the unquantised clock (smooth), zoom on twos
      const us = f(seg(t, t0, t1));
      const c = pick(a, b, u), s = pick(a, b, us);
      return { zoom: c.zoom, x: s.x, y: s.y };
    }
  }
  return { ...REST, ...ks[ks.length - 1][1] };
}
const mixN = (a, b, u) => (a == null && b == null ? null : lerp(a ?? b, b ?? a, u));

/** Camera punch: +amt zoom that snaps in on each impact time and settles over `dur` seconds. */
export function punch(t, times, amt = 0.25, dur = 0.25) {
  let z = 0;
  for (const ti of times || []) { const u = seg(t, ti, ti + dur); if (t >= ti && u < 1) z = Math.max(z, amt * (1 - ease.outCubic(u))); }
  return z;
}

/**
 * Resolve the camera against the world and the output surface. Returns {ps, ox, oy, vx, vy, vw, vh}:
 * ps = output px per game px (integer), (ox, oy) = output offset of world (0,0), view rect in world px.
 */
export function frameCam(cam, gw, gh, outW, outH, k) {
  const z = Math.max(1, cam && cam.zoom ? cam.zoom : 1);
  // k > 1: output = hi-res surface, any integer pixel size; k = 1: output = game res, integer crop zoom only
  const ps = k > 1 ? Math.max(1, Math.round(k * z)) : Math.max(1, Math.floor(z + 1e-6));
  const OW = k > 1 ? outW : gw, OH = k > 1 ? outH : gh;
  const vw = OW / ps, vh = OH / ps;
  let x = cam && cam.x != null ? cam.x : gw / 2, y = cam && cam.y != null ? cam.y : gh / 2;
  x = vw >= gw ? gw / 2 : clamp(x, vw / 2, gw - vw / 2);
  y = vh >= gh ? gh / 2 : clamp(y, vh / 2, gh - vh / 2);
  const ox = Math.round(OW / 2 - x * ps), oy = Math.round(OH / 2 - y * ps);
  return { ps, ox, oy, vx: -ox / ps, vy: -oy / ps, vw, vh };
}
