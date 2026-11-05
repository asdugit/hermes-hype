// Seeded helpers for the selftest page (imported as an ES module to prove module loading works).
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
export const easeOutCubic = (x) => 1 - Math.pow(1 - clamp01(x), 3);
