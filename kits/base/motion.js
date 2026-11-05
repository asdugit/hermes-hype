// Showreel kits/base — motion maths shared by every kit scene.
// Everything here is a pure function of its arguments (no clocks, no global state), so scenes stay
// pure functions of t as SDK §3 requires. Times are seconds.

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, u) => a + (b - a) * u;
export const remap = (x, a, b, c, d) => c + (d - c) * clamp((x - a) / (b - a || 1e-9));
export const smoothstep = (a, b, x) => { const u = clamp((x - a) / (b - a || 1e-9)); return u * u * (3 - 2 * u); };
export const fract = (x) => x - Math.floor(x);

/** Easing curves on [0,1]. outQuint matches cubic-bezier(.22,1,.36,1) closely (the house entrance curve). */
export const ease = {
  linear: (u) => u,
  inQuad: (u) => u * u,
  outQuad: (u) => 1 - (1 - u) * (1 - u),
  inOutQuad: (u) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2),
  inCubic: (u) => u * u * u,
  outCubic: (u) => 1 - Math.pow(1 - u, 3),
  inOutCubic: (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2),
  outQuart: (u) => 1 - Math.pow(1 - u, 4),
  inOutQuart: (u) => (u < 0.5 ? 8 * u ** 4 : 1 - Math.pow(-2 * u + 2, 4) / 2),
  outQuint: (u) => 1 - Math.pow(1 - u, 5),
  inOutQuint: (u) => (u < 0.5 ? 16 * u ** 5 : 1 - Math.pow(-2 * u + 2, 5) / 2),
  outExpo: (u) => (u >= 1 ? 1 : 1 - Math.pow(2, -10 * u)),
  inOutExpo: (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u < 0.5 ? Math.pow(2, 20 * u - 10) / 2 : (2 - Math.pow(2, -20 * u + 10)) / 2),
  inExpo: (u) => (u <= 0 ? 0 : Math.pow(2, 10 * u - 10)),
  outBack: (u) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2); },
  outBackSoft: (u) => { const c1 = 0.9, c3 = c1 + 1; return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2); },
};

/** Progress of t through [t0, t1] (0..1), eased. */
export function seg(t, t0, t1, e = ease.linear) {
  if (t1 <= t0) return t >= t1 ? 1 : 0;
  return e(clamp((t - t0) / (t1 - t0)));
}

/** Analytic critically damped step response from 0 to 1 (no overshoot); freq in Hz-ish. */
export function spring(t, freq = 3) {
  if (t <= 0) return 0;
  const w = 2 * Math.PI * freq * 0.5;
  return 1 - (1 + w * t) * Math.exp(-w * t);
}

/**
 * Monotone cubic (PCHIP / Fritsch-Carlson) through keys [[t, v], ...] with flat ends: no overshoot,
 * which is what gives designer-keyed camera moves their "mass". Values may be numbers or arrays.
 */
export function pchip(keys) {
  const n = keys.length;
  const ts = keys.map((k) => k[0]);
  const arr = Array.isArray(keys[0][1]);
  const dims = arr ? keys[0][1].length : 1;
  const vs = keys.map((k) => (arr ? k[1] : [k[1]]));
  const slopes = [];
  for (let d = 0; d < dims; d++) {
    const m = new Array(n).fill(0);
    const delta = [];
    for (let i = 0; i < n - 1; i++) delta.push((vs[i + 1][d] - vs[i][d]) / ((ts[i + 1] - ts[i]) || 1e-9));
    for (let i = 1; i < n - 1; i++) {
      if (delta[i - 1] * delta[i] <= 0) m[i] = 0;
      else {
        const h0 = ts[i] - ts[i - 1], h1 = ts[i + 1] - ts[i];
        const w1 = 2 * h1 + h0, w2 = h1 + 2 * h0;
        m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i]);
      }
    }
    slopes.push(m); // ends stay 0: flat ends
  }
  return (t) => {
    if (n === 1 || t <= ts[0]) return arr ? vs[0].slice() : vs[0][0];
    if (t >= ts[n - 1]) return arr ? vs[n - 1].slice() : vs[n - 1][0];
    let i = 0;
    while (i < n - 2 && t > ts[i + 1]) i++;
    const h = ts[i + 1] - ts[i];
    const s = (t - ts[i]) / h;
    const h00 = 2 * s ** 3 - 3 * s ** 2 + 1, h10 = s ** 3 - 2 * s ** 2 + s;
    const h01 = -2 * s ** 3 + 3 * s ** 2, h11 = s ** 3 - s ** 2;
    const out = [];
    for (let d = 0; d < dims; d++) {
      out.push(h00 * vs[i][d] + h10 * h * slopes[d][i] + h01 * vs[i + 1][d] + h11 * h * slopes[d][i + 1]);
    }
    return arr ? out : out[0];
  };
}

/** Piecewise keyframes [[t, v], ...] with one easing per segment (numbers or arrays). */
export function keys(t, ks, e = ease.inOutCubic) {
  if (t <= ks[0][0]) return ks[0][1];
  for (let i = 0; i < ks.length - 1; i++) {
    const [t0, v0] = ks[i], [t1, v1] = ks[i + 1];
    if (t <= t1) {
      const u = e(clamp((t - t0) / ((t1 - t0) || 1e-9)));
      return Array.isArray(v0) ? v0.map((x, j) => lerp(x, v1[j], u)) : lerp(v0, v1, u);
    }
  }
  return ks[ks.length - 1][1];
}

/** FNV-1a 32-bit hash of a string (stable seeds; never use hash() of objects). */
export function hash32(str) {
  let h = 0x811c9dc5;
  const s = String(str);
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return h >>> 0;
}

/** mulberry32 PRNG -> () => [0,1). */
export function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Hand-held drift: a sum of slow sines so no frame is ever parked. Returns [dx, dy, rotDeg].
 * amp in px (1-3 for flat UI, ~6 for the 3D camera), rot in degrees.
 */
export function drift(t, seed = 1, amp = 2, rot = 0.08) {
  const r = rng(seed);
  const p = [r(), r(), r(), r(), r(), r()].map((x) => x * Math.PI * 2);
  const dx = amp * (0.62 * Math.sin(t * 0.71 + p[0]) + 0.38 * Math.sin(t * 1.37 + p[1]));
  const dy = amp * (0.58 * Math.sin(t * 0.53 + p[2]) + 0.42 * Math.sin(t * 1.11 + p[3]));
  const dr = rot * (0.7 * Math.sin(t * 0.43 + p[4]) + 0.3 * Math.sin(t * 0.97 + p[5]));
  return [dx, dy, dr];
}

/** Decaying shake after t0: [dx, dy]. */
export function shake(t, t0, amp = 10, freq = 18, decay = 6, seed = 3) {
  if (t < t0) return [0, 0];
  const k = Math.exp(-(t - t0) * decay);
  const r = rng(seed);
  const a = r() * 6.28, b = r() * 6.28;
  return [amp * k * Math.sin((t - t0) * freq * 6.283 + a), amp * k * Math.sin((t - t0) * freq * 5.1 + b)];
}

/**
 * Standard entrance (render-tech C2): rise + opacity + blur over `dur` (0.4-0.6 s) with outQuint.
 * Returns {u, op, y, blur}; u = eased progress. Never a bare fade.
 */
export function entrance(t, t0, dur = 0.5, rise = 18, blur = 6) {
  const u = seg(t, t0, t0 + dur, ease.outQuint);
  return { u, op: clamp(u * 1.6), y: (1 - u) * rise, blur: (1 - u) * blur };
}

/** Faster exit (0.25-0.35 s): returns {u, op, y, blur}, u = 0 before t1, 1 when gone. */
export function exitAt(t, t1, dur = 0.3, rise = -12, blur = 6) {
  const u = seg(t, t1, t1 + dur, ease.inCubic);
  return { u, op: 1 - u, y: u * rise, blur: u * blur };
}

/** CSS fragment for an entrance/exit state. */
export function enterCss(st, extra = '') {
  const b = st.blur > 0.05 ? `blur(${st.blur.toFixed(2)}px)` : 'none';
  return { opacity: st.op.toFixed(3), transform: `translate3d(0,${st.y.toFixed(2)}px,0) ${extra}`.trim(), filter: b };
}
