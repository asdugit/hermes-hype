// Easing curves. Every function maps u in [0,1] -> [0,1] (overshooting curves may leave the range).
// Inputs are clamped to [0,1] so callers can pass raw progress.

const c = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u);
const PI = Math.PI;

/**
 * Cubic bezier easing with control points (x1,y1) (x2,y2), like CSS cubic-bezier().
 * Solves x(s) = u with Newton steps and a bisection fallback.
 */
export function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (s) => ((ax * s + bx) * s + cx) * s;
  const sy = (s) => ((ay * s + by) * s + cy) * s;
  const dx = (s) => (3 * ax * s + 2 * bx) * s + cx;
  return function ease(uIn) {
    const u = c(uIn);
    if (u === 0 || u === 1) return u;
    let s = u;
    for (let i = 0; i < 8; i++) {
      const err = sx(s) - u;
      if (Math.abs(err) < 1e-7) return sy(s);
      const d = dx(s);
      if (Math.abs(d) < 1e-6) break;
      s -= err / d;
    }
    let lo = 0, hi = 1;
    s = u;
    for (let i = 0; i < 40; i++) {
      const x = sx(s);
      if (Math.abs(x - u) < 1e-7) break;
      if (x < u) lo = s; else hi = s;
      s = (lo + hi) / 2;
    }
    return sy(s);
  };
}

const outBounce = (uIn) => {
  const u = c(uIn), n = 7.5625, d = 2.75;
  if (u < 1 / d) return n * u * u;
  if (u < 2 / d) { const v = u - 1.5 / d; return n * v * v + 0.75; }
  if (u < 2.5 / d) { const v = u - 2.25 / d; return n * v * v + 0.9375; }
  const v = u - 2.625 / d; return n * v * v + 0.984375;
};

/** The ease set exposed as ctx.ease (functions) plus ease.bezier(...) and ease.get(nameOrFn). */
export const ease = {
  linear: (u) => c(u),
  inQuad: (u) => c(u) ** 2,
  outQuad: (u) => 1 - (1 - c(u)) ** 2,
  inOutQuad: (u) => { u = c(u); return u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2; },
  inCubic: (u) => c(u) ** 3,
  outCubic: (u) => 1 - (1 - c(u)) ** 3,
  inOutCubic: (u) => { u = c(u); return u < 0.5 ? 4 * u ** 3 : 1 - (-2 * u + 2) ** 3 / 2; },
  inQuart: (u) => c(u) ** 4,
  outQuart: (u) => 1 - (1 - c(u)) ** 4,
  inOutQuart: (u) => { u = c(u); return u < 0.5 ? 8 * u ** 4 : 1 - (-2 * u + 2) ** 4 / 2; },
  inQuint: (u) => c(u) ** 5,
  outQuint: (u) => 1 - (1 - c(u)) ** 5,
  inOutQuint: (u) => { u = c(u); return u < 0.5 ? 16 * u ** 5 : 1 - (-2 * u + 2) ** 5 / 2; },
  inSine: (u) => 1 - Math.cos((c(u) * PI) / 2),
  outSine: (u) => Math.sin((c(u) * PI) / 2),
  inOutSine: (u) => -(Math.cos(PI * c(u)) - 1) / 2,
  inExpo: (u) => { u = c(u); return u === 0 ? 0 : 2 ** (10 * u - 10); },
  outExpo: (u) => { u = c(u); return u === 1 ? 1 : 1 - 2 ** (-10 * u); },
  inOutExpo: (u) => {
    u = c(u);
    if (u === 0 || u === 1) return u;
    return u < 0.5 ? 2 ** (20 * u - 10) / 2 : (2 - 2 ** (-20 * u + 10)) / 2;
  },
  inCirc: (u) => 1 - Math.sqrt(1 - c(u) ** 2),
  outCirc: (u) => Math.sqrt(1 - (c(u) - 1) ** 2),
  inBack: (u) => { u = c(u); const k = 1.70158; return (k + 1) * u ** 3 - k * u * u; },
  outBack: (u) => { u = c(u); const k = 1.70158; return 1 + (k + 1) * (u - 1) ** 3 + k * (u - 1) ** 2; },
  inOutBack: (u) => {
    u = c(u); const k = 1.70158 * 1.525;
    return u < 0.5 ? ((2 * u) ** 2 * ((k + 1) * 2 * u - k)) / 2
      : ((2 * u - 2) ** 2 * ((k + 1) * (u * 2 - 2) + k) + 2) / 2;
  },
  outElastic: (u) => {
    u = c(u);
    if (u === 0 || u === 1) return u;
    return 2 ** (-10 * u) * Math.sin((u * 10 - 0.75) * ((2 * PI) / 3)) + 1;
  },
  outBounce,
  /** The house entrance curve (render-tech C2): cubic-bezier(.22,1,.36,1). */
  snappy: bezier(0.22, 1, 0.36, 1),
  bezier,
};

/** Resolve an ease given as a function, a name ('outCubic') or a 4-number array (bezier). */
export function getEase(e) {
  if (typeof e === 'function') return e;
  if (Array.isArray(e) && e.length === 4) return bezier(e[0], e[1], e[2], e[3]);
  if (typeof e === 'string' && typeof ease[e] === 'function' && e !== 'bezier') return ease[e];
  if (e == null) return ease.linear;
  throw new Error(`unknown ease ${JSON.stringify(e)}; use one of ${Object.keys(ease).filter((k) => k !== 'bezier').join(', ')} or bezier(x1,y1,x2,y2)`);
}
ease.get = getEase;
