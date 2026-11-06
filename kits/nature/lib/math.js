// nature kit · math helpers (pure JS, no THREE): seeded RNG, easing, splines, terrain height, camera rigs.
// Everything here is a pure function of its inputs (SDK §3 pure-function rule).

/** mulberry32 → () => [0,1) */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a 32-bit hash of a string. */
export function hashStr(s) {
  let h = 2166136261 >>> 0;
  const str = String(s);
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h;
}

/** Deterministic RNG for (seed, key). */
export const rngFor = (seed, key) => mulberry32((Math.imul((seed >>> 0) ^ 0x9E3779B9, 2654435761) ^ hashStr(key)) >>> 0);

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, u) => a + (b - a) * u;
export const smoothstep = (a, b, x) => { const u = clamp((x - a) / (b - a)); return u * u * (3 - 2 * u); };
export const fract = (x) => x - Math.floor(x);
export const easeInOut = (u) => { u = clamp(u); return u * u * (3 - 2 * u); };
export const easeInOutCubic = (u) => { u = clamp(u); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };
export const easeOutCubic = (u) => 1 - Math.pow(1 - clamp(u), 3);
export const easeInCubic = (u) => Math.pow(clamp(u), 3);
export const easeInOutSine = (u) => 0.5 - 0.5 * Math.cos(Math.PI * clamp(u));

/** Cheap deterministic 1D value noise (smooth), period-free. */
export function noise1(x, seed = 0) {
  const i = Math.floor(x), f = x - i;
  const h = (n) => { let v = Math.sin((n + seed * 17.13) * 127.1) * 43758.5453; return v - Math.floor(v); };
  const u = f * f * (3 - 2 * f);
  return lerp(h(i), h(i + 1), u) * 2 - 1;
}

/** Centripetal-ish Catmull–Rom through points (arrays of equal length) — returns {at(u), tangent(u)}. */
export function catmull(points) {
  const n = points.length;
  const P = (i) => points[Math.max(0, Math.min(n - 1, i))];
  const at = (u) => {
    u = clamp(u);
    const s = u * (n - 1), i = Math.min(Math.floor(s), n - 2), f = s - i;
    const p0 = P(i - 1), p1 = P(i), p2 = P(i + 1), p3 = P(i + 2);
    const f2 = f * f, f3 = f2 * f;
    return p1.map((_, k) => 0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * f + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * f2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * f3));
  };
  const tangent = (u, du = 1e-3) => { const a = at(u - du), b = at(u + du); return a.map((v, k) => (b[k] - v) / (2 * du)); };
  return { at, tangent };
}

/** Linear keyframes [[t, v|array], ...] with an easing per segment (default smooth). */
export function keys(t, kfs, ease = easeInOutSine) {
  if (t <= kfs[0][0]) return kfs[0][1];
  for (let i = 0; i < kfs.length - 1; i++) {
    const [t0, v0] = kfs[i], [t1, v1] = kfs[i + 1];
    if (t <= t1) {
      const u = ease((t - t0) / (t1 - t0));
      return Array.isArray(v0) ? v0.map((v, k) => lerp(v, v1[k], u)) : lerp(v0, v1, u);
    }
  }
  return kfs[kfs.length - 1][1];
}

// ------------------------------------------------------------------ terrain

/**
 * Terrain height (metres) at world (x, z); z < 0 is "forward" from the camera origin.
 * `hill` = {x, d, h, rx, rd} adds a gaussian hill (drive-slope lives on it). Deterministic, cheap.
 */
export function terrainHeight(x, z, opt) {
  const d = -z;
  let h = 0.35 * Math.sin(x * 0.045 + 1.3) * Math.sin(d * 0.035 + 0.4) + 0.25 * Math.sin(x * 0.11 + d * 0.07);
  h += 0.0016 * Math.max(d - 60, 0) * Math.max(d - 60, 0) * 0.02;     // far field rises gently toward the hills
  for (const hl of opt.hills || []) {
    const dx = (x - hl.x) / hl.rx, dd = (d - hl.d) / hl.rd;
    h += hl.h * Math.exp(-(dx * dx + dd * dd));
  }
  // keep the immediate foreground flat-ish so the camera never sits inside a bump
  const near = smoothstep(0, 10, d);
  return h * (0.25 + 0.75 * near);
}

/** Numeric gradient of terrainHeight → [dh/dx, dh/dz]. */
export function terrainGrad(x, z, opt, e = 0.25) {
  return [(terrainHeight(x + e, z, opt) - terrainHeight(x - e, z, opt)) / (2 * e),
    (terrainHeight(x, z + e, opt) - terrainHeight(x, z - e, opt)) / (2 * e)];
}

// ------------------------------------------------------------------ camera rigs

/**
 * Camera pose for a named move at shot-local t (pure). Returns {pos:[x,y,z], yaw, pitch, roll, fov} (radians).
 * Moves: drift | push | crane-up | crane-dolly | sweep | tilt-down | pan | static | hero-arc.  `amt` scales the travel.
 */
export function cameraPose(move, t, dur, base, amt = 1) {
  const u = easeInOutSine(t / Math.max(dur, 1e-3));
  const lin = clamp(t / Math.max(dur, 1e-3));
  const [bx, by, bz] = base.pos;
  // never parked: a tiny breathing sway on top of every move
  const br = 0.004 * Math.sin(t * 0.7) + 0.0025 * Math.sin(t * 1.31 + 1.0);
  let pos = [bx, by, bz], yaw = base.yaw, pitch = base.pitch, roll = 0.0015 * Math.sin(t * 0.53), fov = base.fov;
  switch (move) {
    case 'push': pos = [bx, by + 0.25 * amt * u, bz - 9 * amt * u]; break;
    case 'crane-up': pos = [bx + 1.5 * amt * lin, by + lerp(-0.55, 3.2, u) * amt, bz - 2 * amt * u]; pitch = base.pitch + lerp(-0.04, 0.03, u) * amt; break;
    case 'crane-dolly': {   // rises up over the flowers while dollying in: the meadow drops away, the mountains rise
      pos = [bx + 1.2 * amt * lin, by + lerp(0.0, 2.6, u) * amt, bz - 8 * amt * u];
      pitch = base.pitch + lerp(0.035, -0.02, u) * amt; yaw = base.yaw - 0.04 * amt * (lin - 0.5); break;
    }
    case 'sweep': {         // lateral truck with a counter-pan: the subject holds while the foreground slides (parallax)
      pos = [bx + lerp(-4.5, 4.5, u) * amt, by + 0.25 * amt * Math.sin(Math.PI * lin), bz - 2.5 * amt * u];
      yaw = base.yaw + lerp(0.075, -0.075, u) * amt; break;
    }
    case 'tilt-down': pitch = lerp(base.pitch + 0.62 * amt, base.pitch, easeInOutCubic(lin)); pos = [bx, by, bz - 3 * amt * u]; break;
    case 'pan': yaw = base.yaw + lerp(0.10, -0.10, u) * amt; pos = [bx, by, bz - 2 * amt * u]; break;
    case 'static': break;
    case 'hero-arc': {
      const a = lerp(-0.22, 0.18, u) * amt;
      const c = base.target || [0, 0, -30];
      const r = Math.hypot(bx - c[0], bz - c[2]) * lerp(1.0, 0.82, u * amt);
      const a0 = Math.atan2(bx - c[0], bz - c[2]) + a;
      pos = [c[0] + r * Math.sin(a0), by + 0.35 * amt * u, c[2] + r * Math.cos(a0)];
      yaw = a0;
      break;
    }
    case 'drift':
    default: pos = [bx + 3.0 * amt * lin - 1.5 * amt, by + 0.18 * amt * Math.sin(lin * Math.PI), bz - 4 * amt * u]; yaw = base.yaw - 0.035 * amt * (lin - 0.5); break;
  }
  return { pos, yaw: yaw + br * 0.6, pitch: pitch + br, roll, fov };
}
