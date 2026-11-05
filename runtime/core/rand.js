// Seeded randomness for the Showreel runtime: string/number seed mixing and a small fast PRNG.
// Every random-looking value in a film comes from here, so a frame is a pure function of (seed, t).

/** 32-bit FNV-1a over a string, finished with a murmur3-style avalanche. */
export function hashString(s) {
  let h = 0x811c9dc5;
  const str = String(s);
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return avalanche(h);
}

/** Final mix so nearby inputs land far apart. */
export function avalanche(h) {
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

/** Combine any number of seed parts (numbers or strings) into one unsigned 32-bit seed. */
export function mixSeed(...parts) {
  let h = 0x9e3779b9;
  for (const p of parts) {
    const v = typeof p === 'number' && Number.isFinite(p) ? (p | 0) ^ Math.floor(p * 65536) : hashString(p);
    h = avalanche((h ^ v) + 0x6d2b79f5 + (h << 6) + (h >>> 2));
  }
  return h >>> 0;
}

/** mulberry32: tiny 32-bit PRNG, returns () => float in [0, 1). */
export function mulberry32(seed) {
  let s = seed >>> 0;
  return function next() {
    s = (s + 0x6d2b79f5) >>> 0;
    let z = s;
    z = Math.imul(z ^ (z >>> 15), z | 1);
    z ^= z + Math.imul(z ^ (z >>> 7), z | 61);
    return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
  };
}

/** A PRNG with convenience draws: float(a,b), int(a,b) inclusive, pick(arr), sign(), gauss(). */
export function makeRng(seed) {
  const r = mulberry32(seed);
  const f = () => r();
  f.float = (a = 0, b = 1) => a + (b - a) * r();
  f.int = (a, b) => a + Math.floor(r() * (b - a + 1));
  f.pick = (arr) => arr[Math.floor(r() * arr.length)];
  f.sign = () => (r() < 0.5 ? -1 : 1);
  f.gauss = () => {
    const u = Math.max(r(), 1e-12), v = r();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  return f;
}
