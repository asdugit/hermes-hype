// Deterministic simplex noise (2D/3D) and fractal Brownian motion, seeded per film.
// Implementation follows the public-domain simplex algorithm description (Perlin 2001 / Gustavson 2005).
import { mulberry32 } from './rand.js';

const GRAD = [
  [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
  [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
  [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
];
const F2 = 0.5 * (Math.sqrt(3) - 1);
const G2 = (3 - Math.sqrt(3)) / 6;
const F3 = 1 / 3;
const G3 = 1 / 6;

/**
 * Build seeded noise functions.
 * @returns {{noise2:(x:number,y:number)=>number, noise3:(x:number,y:number,z:number)=>number,
 *           fbm2:(x:number,y:number,oct?:number,lac?:number,gain?:number)=>number,
 *           fbm3:(x:number,y:number,z:number,oct?:number,lac?:number,gain?:number)=>number}}
 *   all outputs are in [-1, 1].
 */
export function makeNoise(seed) {
  const rnd = mulberry32(seed);
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    const tmp = p[i]; p[i] = p[j]; p[j] = tmp;
  }
  const perm = new Uint8Array(512);
  const g12 = new Uint8Array(512);
  for (let i = 0; i < 512; i++) { perm[i] = p[i & 255]; g12[i] = perm[i] % 12; }

  function corner2(gi, x, y) {
    let k = 0.5 - x * x - y * y;
    if (k <= 0) return 0;
    const g = GRAD[gi];
    k *= k;
    return k * k * (g[0] * x + g[1] * y);
  }

  function noise2(xin, yin) {
    const s = (xin + yin) * F2;
    const i = Math.floor(xin + s), j = Math.floor(yin + s);
    const t = (i + j) * G2;
    const x0 = xin - (i - t), y0 = yin - (j - t);
    const i1 = x0 > y0 ? 1 : 0, j1 = 1 - i1;
    const x1 = x0 - i1 + G2, y1 = y0 - j1 + G2;
    const x2 = x0 - 1 + 2 * G2, y2 = y0 - 1 + 2 * G2;
    const ii = i & 255, jj = j & 255;
    return 70 * (corner2(g12[ii + perm[jj]], x0, y0)
      + corner2(g12[ii + i1 + perm[jj + j1]], x1, y1)
      + corner2(g12[ii + 1 + perm[jj + 1]], x2, y2));
  }

  function corner3(gi, x, y, z) {
    let k = 0.6 - x * x - y * y - z * z;
    if (k <= 0) return 0;
    const g = GRAD[gi];
    k *= k;
    return k * k * (g[0] * x + g[1] * y + g[2] * z);
  }

  function noise3(xin, yin, zin) {
    const s = (xin + yin + zin) * F3;
    const i = Math.floor(xin + s), j = Math.floor(yin + s), k = Math.floor(zin + s);
    const t = (i + j + k) * G3;
    const x0 = xin - (i - t), y0 = yin - (j - t), z0 = zin - (k - t);
    let i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) {
      if (y0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
      else if (x0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1; }
      else { i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1; }
    } else if (y0 < z0) { i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1; }
    else if (x0 < z0) { i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1; }
    else { i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
    const x1 = x0 - i1 + G3, y1 = y0 - j1 + G3, z1 = z0 - k1 + G3;
    const x2 = x0 - i2 + 2 * G3, y2 = y0 - j2 + 2 * G3, z2 = z0 - k2 + 2 * G3;
    const x3 = x0 - 1 + 3 * G3, y3 = y0 - 1 + 3 * G3, z3 = z0 - 1 + 3 * G3;
    const ii = i & 255, jj = j & 255, kk = k & 255;
    return 32 * (corner3(g12[ii + perm[jj + perm[kk]]], x0, y0, z0)
      + corner3(g12[ii + i1 + perm[jj + j1 + perm[kk + k1]]], x1, y1, z1)
      + corner3(g12[ii + i2 + perm[jj + j2 + perm[kk + k2]]], x2, y2, z2)
      + corner3(g12[ii + 1 + perm[jj + 1 + perm[kk + 1]]], x3, y3, z3));
  }

  function fbm2(x, y, oct = 4, lac = 2, gain = 0.5) {
    let sum = 0, amp = 1, norm = 0, f = 1;
    for (let o = 0; o < oct; o++) {
      sum += amp * noise2(x * f + o * 17.31, y * f - o * 9.73);
      norm += amp; amp *= gain; f *= lac;
    }
    return sum / norm;
  }

  function fbm3(x, y, z, oct = 4, lac = 2, gain = 0.5) {
    let sum = 0, amp = 1, norm = 0, f = 1;
    for (let o = 0; o < oct; o++) {
      sum += amp * noise3(x * f + o * 17.31, y * f - o * 9.73, z * f + o * 3.17);
      norm += amp; amp *= gain; f *= lac;
    }
    return sum / norm;
  }

  return { noise2, noise3, fbm2, fbm3 };
}
