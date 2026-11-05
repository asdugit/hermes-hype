// motion.js — pure, deterministic timing helpers for pixel animation (no wall clock, no Math.random).
// Pixel motion grammar: state steps "on twos" (15 Hz inside a 30 fps film), positions are whole pixels.

export const TICK = 1 / 15;
/** Quantise time to animation ticks (default 15 Hz = on twos at 30 fps). */
export const step = (t, hz = 15) => Math.floor(t * hz + 1e-6) / hz;
export const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
export const lerp = (a, b, u) => a + (b - a) * u;
/** 0..1 progress of t through [t0, t1], clamped. */
export const seg = (t, t0, t1) => (t1 <= t0 ? (t >= t1 ? 1 : 0) : clamp((t - t0) / (t1 - t0)));
export const ease = {
  linear: u => u,
  inQuad: u => u * u,
  outQuad: u => 1 - (1 - u) * (1 - u),
  inOutQuad: u => (u < 0.5 ? 2 * u * u : 1 - 2 * (1 - u) * (1 - u)),
  outCubic: u => 1 - (1 - u) ** 3,
  inCubic: u => u ** 3,
  inOutCubic: u => (u < 0.5 ? 4 * u ** 3 : 1 - (-2 * u + 2) ** 3 / 2),
  outBack: u => { const c = 1.70158; return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2; },
  outBounce: u => {
    const n = 7.5625, d = 2.75;
    if (u < 1 / d) return n * u * u;
    if (u < 2 / d) return n * (u -= 1.5 / d) * u + 0.75;
    if (u < 2.5 / d) return n * (u -= 2.25 / d) * u + 0.9375;
    return n * (u -= 2.625 / d) * u + 0.984375;
  },
};
/** Eased, tick-stepped progress: the pixel-art way to move (a 40 px move in 0.4 s = 6 stepped positions). */
export const stepSeg = (t, t0, t1, e = ease.outCubic, hz = 15) => e(seg(step(t, hz), t0, t1));
/** Parabolic hop: 0 at u=0 and u=1, peak `h` at 0.5. */
export const hop = (u, h) => (u <= 0 || u >= 1 ? 0 : 4 * h * u * (1 - u));
/** Keyframes [[t, v], ...] (numbers or arrays) with optional ease per segment. */
export function keys(t, ks, e = ease.linear) {
  if (t <= ks[0][0]) return ks[0][1];
  for (let i = 1; i < ks.length; i++) {
    if (t <= ks[i][0]) {
      const [t0, a] = ks[i - 1], [t1, b] = ks[i], u = e(seg(t, t0, t1));
      return Array.isArray(a) ? a.map((v, k) => lerp(v, b[k], u)) : lerp(a, b, u);
    }
  }
  return ks[ks.length - 1][1];
}

// ---- seeded randomness ------------------------------------------------------------------
/** 32-bit FNV-1a of a string/number (stable across machines; never use hash()). */
export function hash32(...parts) {
  let h = 0x811c9dc5;
  for (const p of parts) { const s = String(p); for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); } h ^= 0x2c; }
  return h >>> 0;
}
/** mulberry32 PRNG -> () => [0,1). */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0; let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
/** Stateless random in [0,1) for (seed, i, j). */
export const rand = (seed, i = 0, j = 0) => rng(hash32(seed, i, j))();

/** Torch/candle flicker level 0..1 for time t (changes ~8x per second, deterministic per seed). */
export function flicker(t, seed = 0, hz = 8) {
  const k = Math.floor(t * hz), a = rand(seed, k), b = rand(seed, k + 1), u = t * hz - k;
  return a + (b - a) * (u < 0.5 ? 0 : 1) * 0.5;
}

/**
 * Integer screen-shake offset at t for impacts listed as [{t, amp, dur}] (decaying, steps on twos).
 * Returns [dx, dy].
 */
export function shakeAt(t, hits, seed = 7) {
  let dx = 0, dy = 0; const tq = step(t, 30);
  for (const h of hits) {
    const u = (tq - h.t) / (h.dur || 0.35);
    if (u < 0 || u >= 1) continue;
    const a = (h.amp ?? 3) * (1 - u) ** 1.5, k = Math.floor((tq - h.t) * 20);
    dx += Math.round((rand(seed, h.t * 100, k) * 2 - 1) * a);
    dy += Math.round((rand(seed + 1, h.t * 100, k) * 2 - 1) * a * 0.6);
  }
  return [dx, dy];
}

/**
 * Hit-stop: maps scene time to animation time, freezing for `frames` frames (at fps) after each
 * impact time. Returns the animation time (monotone, continuous except for holds).
 */
export function hitstop(t, impacts, frames = 3, fps = 30) {
  let lost = 0; const hold = frames / fps;
  for (const ti of impacts) { if (t > ti) lost += Math.min(hold, t - ti); }
  return t - lost;
}

/** Blink: true during the "on" half of each period. */
export const blink = (t, period = 1, duty = 0.5, phase = 0) => ((t + phase) / period) % 1 < duty;
