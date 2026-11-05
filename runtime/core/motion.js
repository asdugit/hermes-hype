// Motion helpers: scalar math, progress segments, analytic springs, keyframes, shakes and paths.
// All are pure functions of their inputs (no state), so any frame can be computed in any order.
import { getEase } from './ease.js';
import { mulberry32 } from './rand.js';

export const clamp = (x, lo = 0, hi = 1) => (x < lo ? lo : x > hi ? hi : x);
export const lerp = (a, b, u) => a + (b - a) * u;
export const fract = (x) => x - Math.floor(x);

/** lerp for numbers or same-length arrays. */
export function mix(a, b, u) {
  if (Array.isArray(a)) return a.map((v, i) => v + (b[i] - v) * u);
  return a + (b - a) * u;
}

/** Hermite smoothstep of x between edges e0 and e1. */
export function smoothstep(e0, e1, x) {
  const u = clamp((x - e0) / (e1 - e0 || 1e-9));
  return u * u * (3 - 2 * u);
}

/** Map x from [a0,a1] to [b0,b1]; clamps unless clampIt === false. */
export function remap(x, a0, a1, b0, b1, clampIt = true) {
  let u = (x - a0) / (a1 - a0 || 1e-9);
  if (clampIt) u = clamp(u);
  return b0 + (b1 - b0) * u;
}

/** Eased 0..1 progress of t through [t0, t1] (0 before, 1 after). */
export function seg(t, t0, t1, easeFn) {
  const u = t1 > t0 ? clamp((t - t0) / (t1 - t0)) : (t >= t1 ? 1 : 0);
  return easeFn == null ? u : getEase(easeFn)(u);
}

/**
 * Analytic spring from `from` to `to`, released at t0 with velocity v0 (units/s).
 * freq = natural frequency in Hz, damp = damping ratio (1 = critically damped, < 1 overshoots).
 * Works for numbers or arrays.
 */
export function spring(t, opts = {}) {
  const { from = 0, to = 1, freq = 2, damp = 1, t0 = 0, v0 = 0 } = opts;
  if (Array.isArray(from)) {
    return from.map((f, i) => spring(t, { ...opts, from: f, to: to[i], v0: Array.isArray(v0) ? v0[i] : v0 }));
  }
  const s = t - t0;
  if (s <= 0) return from;
  const w = 2 * Math.PI * Math.max(freq, 1e-6);
  const z = Math.max(damp, 0);
  const x0 = from - to;
  let x;
  if (Math.abs(z - 1) < 1e-4) {
    x = (x0 + (v0 + w * x0) * s) * Math.exp(-w * s);
  } else if (z < 1) {
    const wd = w * Math.sqrt(1 - z * z);
    x = Math.exp(-z * w * s) * (x0 * Math.cos(wd * s) + ((v0 + z * w * x0) / wd) * Math.sin(wd * s));
  } else {
    const r = w * Math.sqrt(z * z - 1);
    const r1 = -z * w + r, r2 = -z * w - r;
    const c2 = (v0 - r1 * x0) / (r2 - r1);
    const c1 = x0 - c2;
    x = c1 * Math.exp(r1 * s) + c2 * Math.exp(r2 * s);
  }
  return to + x;
}

/**
 * Keyframe interpolation. kfs = [[t, value, ease?], ...] sorted by t; value = number or array.
 * The optional per-key ease shapes the segment that STARTS at that key; `easeFn` is the default.
 */
export function keys(t, kfs, easeFn) {
  if (!kfs || kfs.length === 0) return 0;
  if (t <= kfs[0][0]) return kfs[0][1];
  const last = kfs[kfs.length - 1];
  if (t >= last[0]) return last[1];
  let i = 0;
  while (i < kfs.length - 2 && t >= kfs[i + 1][0]) i++;
  const [ta, va, ea] = kfs[i];
  const [tb, vb] = kfs[i + 1];
  const e = getEase(ea ?? easeFn ?? 'linear');
  const u = e(tb > ta ? (t - ta) / (tb - ta) : 1);
  return mix(va, vb, u);
}

/**
 * Decaying camera shake starting at t0: returns [dx, dy, rot] (px, px, radians).
 * amp = peak px, freq = Hz, decay = 1/s exponential, rot = peak radians (default from amp).
 */
export function shake(t, opts = {}) {
  const { amp = 8, freq = 14, decay = 5, t0 = 0, seed = 1, rot = amp * 0.0015, dur = Infinity } = opts;
  const s = t - t0;
  if (s < 0 || s > dur) return [0, 0, 0];
  const r = mulberry32((seed * 2654435761) >>> 0);
  const ph = [r(), r(), r(), r(), r(), r()].map((v) => v * Math.PI * 2);
  const env = Math.exp(-decay * s);
  const w = 2 * Math.PI * freq;
  const osc = (a, b) => 0.62 * Math.sin(w * s + a) + 0.38 * Math.sin(w * 1.73 * s + b);
  return [amp * env * osc(ph[0], ph[1]), amp * env * osc(ph[2], ph[3]), rot * env * osc(ph[4], ph[5])];
}

// ------------------------------------------------------------------------------------------- paths

/** Fritsch-Carlson monotone slopes for uniformly spaced samples ys. */
function pchipSlopes(ys) {
  const n = ys.length;
  const d = new Array(n).fill(0);
  if (n < 2) return d;
  const delta = [];
  for (let i = 0; i < n - 1; i++) delta.push(ys[i + 1] - ys[i]);
  if (n === 2) { d[0] = d[1] = delta[0]; return d; }
  for (let i = 1; i < n - 1; i++) {
    const a = delta[i - 1], b = delta[i];
    d[i] = a * b <= 0 ? 0 : (2 * a * b) / (a + b);
  }
  // one-sided three-point ends, kept shape preserving (flat ends stay flat)
  const end = (d0, d1) => {
    let m = (3 * d0 - d1) / 2;
    if (Math.sign(m) !== Math.sign(d0)) m = 0;
    else if (Math.sign(d0) !== Math.sign(d1) && Math.abs(m) > Math.abs(3 * d0)) m = 3 * d0;
    return m;
  };
  d[0] = end(delta[0], delta[1]);
  d[n - 1] = end(delta[n - 2], delta[n - 3]);
  return d;
}

function hermite(p0, p1, m0, m1, s) {
  const s2 = s * s, s3 = s2 * s;
  return (2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * m0 + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * m1;
}

function hermiteD(p0, p1, m0, m1, s) {
  const s2 = s * s;
  return (6 * s2 - 6 * s) * p0 + (3 * s2 - 4 * s + 1) * m0 + (-6 * s2 + 6 * s) * p1 + (3 * s2 - 2 * s) * m1;
}

/**
 * A path through points ([x,y] or [x,y,z]) with u in [0,1] spread uniformly over the segments.
 * kind: 'pchip' (monotone, no overshoot; default), 'catmull' (smooth, may overshoot), 'linear'.
 * Returns {at(u), tangent(u) (unit vector), angle(u) (2D heading, radians), length, points}.
 */
export function path(points, opts = {}) {
  const kind = opts.kind || 'pchip';
  if (!Array.isArray(points) || points.length === 0) throw new Error('path(points): need at least one point');
  const n = points.length;
  const dim = points[0].length;
  const cols = [];
  for (let k = 0; k < dim; k++) cols.push(points.map((p) => p[k]));
  let slopes;
  if (kind === 'pchip') slopes = cols.map(pchipSlopes);
  else if (kind === 'catmull') {
    slopes = cols.map((ys) => ys.map((_, i) => {
      const a = ys[Math.max(i - 1, 0)], b = ys[Math.min(i + 1, n - 1)];
      return (b - a) / (i === 0 || i === n - 1 ? 1 : 2);
    }));
  } else if (kind !== 'linear') throw new Error(`path kind must be pchip|catmull|linear, got ${kind}`);

  const locate = (u) => {
    const x = clamp(u) * (n - 1);
    const i = Math.min(Math.floor(x), n - 2);
    return [i, x - i];
  };
  function at(u) {
    if (n === 1) return points[0].slice();
    const [i, s] = locate(u);
    return cols.map((ys, k) => (kind === 'linear' ? ys[i] + (ys[i + 1] - ys[i]) * s
      : hermite(ys[i], ys[i + 1], slopes[k][i], slopes[k][i + 1], s)));
  }
  function deriv(u) {
    if (n === 1) return new Array(dim).fill(0);
    const [i, s] = locate(u);
    return cols.map((ys, k) => (kind === 'linear' ? ys[i + 1] - ys[i]
      : hermiteD(ys[i], ys[i + 1], slopes[k][i], slopes[k][i + 1], s)));
  }
  function tangent(u) {
    let d = deriv(u);
    let len = Math.hypot(...d);
    if (len < 1e-9) { d = deriv(clamp(u + 1e-3)); len = Math.hypot(...d); }
    if (len < 1e-9) { d = deriv(clamp(u - 1e-3)); len = Math.hypot(...d); }
    return len < 1e-9 ? d.map((_, k) => (k === 0 ? 1 : 0)) : d.map((v) => v / len);
  }
  let length = 0;
  let prev = at(0);
  for (let k = 1; k <= 64; k++) {
    const p = at(k / 64);
    length += Math.hypot(...p.map((v, j) => v - prev[j]));
    prev = p;
  }
  return { at, tangent, angle: (u) => { const d = tangent(u); return Math.atan2(d[1], d[0]); }, length, points };
}
