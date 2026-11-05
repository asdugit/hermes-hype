// Pure-module checks for the runtime (no DOM): run by tests/runtime/test_runtime_node.py with Node >= 18.
// Prints one JSON object {name: true | "failure message"}.
import { mulberry32, mixSeed, hashString, makeRng } from '../../runtime/core/rand.js';
import { makeNoise } from '../../runtime/core/noise.js';
import { ease, bezier, getEase } from '../../runtime/core/ease.js';
import { clamp, lerp, mix, smoothstep, remap, fract, seg, spring, keys, shake, path } from '../../runtime/core/motion.js';
import { normalizeFilm, liveAt, clampTime, defaultSafe } from '../../runtime/core/film.js';
import { framePath, frameIndex } from '../../runtime/core/assets.js';

const out = {};
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
function check(name, fn) {
  try {
    const r = fn();
    out[name] = r === true ? true : `returned ${JSON.stringify(r)}`;
  } catch (e) {
    out[name] = String(e && e.message || e);
  }
}

check('mulberry32 deterministic', () => {
  const a = mulberry32(42), b = mulberry32(42);
  const xs = Array.from({ length: 5 }, () => a());
  return xs.every((x) => x === b() && x >= 0 && x < 1);
});
check('mixSeed stable and order sensitive', () => mixSeed(7, 'walk', 3) === mixSeed(7, 'walk', 3)
  && mixSeed(7, 'walk', 3) !== mixSeed(7, 3, 'walk') && hashString('a') !== hashString('b'));
check('rng helpers', () => {
  const r = makeRng(9);
  const i = r.int(3, 5), f = r.float(2, 4), p = r.pick(['x', 'y']);
  return i >= 3 && i <= 5 && f >= 2 && f < 4 && ['x', 'y'].includes(p) && Number.isFinite(r.gauss());
});
check('noise range and determinism', () => {
  const n1 = makeNoise(5), n2 = makeNoise(5), n3 = makeNoise(6);
  let lo = 9, hi = -9, same = true, diff = false;
  for (let i = 0; i < 5000; i++) {
    const x = i * 0.173, y = i * 0.091;
    const v = n1.noise2(x, y);
    lo = Math.min(lo, v); hi = Math.max(hi, v);
    same = same && v === n2.noise2(x, y) && n1.noise3(x, y, 0.5) === n2.noise3(x, y, 0.5);
    diff = diff || v !== n3.noise2(x, y);
  }
  const f = n1.fbm2(1.3, 2.7, 5);
  return same && diff && lo >= -1 && hi <= 1 && hi - lo > 1.2 && f >= -1 && f <= 1;
});
check('ease endpoints', () => Object.entries(ease).filter(([k, v]) => typeof v === 'function' && !['bezier', 'get'].includes(k))
  .every(([, e]) => near(e(0), 0, 1e-9) && near(e(1), 1, 1e-9)));
check('bezier matches linear and css ease', () => near(bezier(0, 0, 1, 1)(0.3), 0.3, 1e-5)
  && near(bezier(0.25, 0.1, 0.25, 1)(0.5), 0.8024033877399112, 1e-4));
check('getEase resolves names/arrays and rejects junk', () => {
  let threw = false;
  try { getEase('nope'); } catch (_) { threw = true; }
  return getEase('outCubic') === ease.outCubic && near(getEase([0, 0, 1, 1])(0.5), 0.5, 1e-5) && threw;
});
check('scalar helpers', () => clamp(2) === 1 && lerp(0, 10, 0.25) === 2.5 && mix([0, 0], [2, 4], 0.5).join() === '1,2'
  && smoothstep(0, 1, 0.5) === 0.5 && remap(5, 0, 10, 0, 100) === 50 && remap(20, 0, 10, 0, 100) === 100
  && remap(20, 0, 10, 0, 100, false) === 200 && near(fract(-0.25), 0.75));
check('seg', () => seg(0.5, 0, 1) === 0.5 && seg(-1, 0, 1) === 0 && seg(2, 0, 1) === 1 && near(seg(0.5, 0, 1, 'inQuad'), 0.25));
check('spring critically damped: monotone, settles, no overshoot', () => {
  let prev = -1, mono = true;
  for (let t = 0; t <= 2; t += 0.01) { const v = spring(t, { freq: 2 }); mono = mono && v >= prev - 1e-12 && v <= 1 + 1e-9; prev = v; }
  return mono && near(spring(3, { freq: 2 }), 1, 1e-4) && spring(-1, { from: 5, to: 9 }) === 5;
});
check('spring underdamped overshoots, arrays work', () => {
  const peak = Math.max(...Array.from({ length: 200 }, (_, i) => spring(i / 100, { freq: 2, damp: 0.3 })));
  const a = spring(10, { from: [0, 10], to: [1, 20] });
  return peak > 1.2 && near(a[0], 1, 1e-3) && near(a[1], 20, 1e-3);
});
check('keys', () => keys(1.5, [[0, 0], [1, 10], [2, 20]]) === 15 && keys(-1, [[0, 3], [1, 4]]) === 3
  && keys(5, [[0, 3], [1, 4]]) === 4 && keys(0.5, [[0, [0, 0]], [1, [10, 20]]]).join() === '5,10'
  && near(keys(0.5, [[0, 0, 'inQuad'], [1, 1]]), 0.25));
check('shake decays and is zero before t0', () => {
  const s0 = shake(0.5, { t0: 1 });
  const big = Math.hypot(...shake(1.03, { t0: 1, amp: 10 }).slice(0, 2));
  const small = Math.hypot(...shake(3, { t0: 1, amp: 10 }).slice(0, 2));
  return s0.every((v) => v === 0) && small < 0.1 && big > 0.5 && shake(1.2, { seed: 3 }).join() === shake(1.2, { seed: 3 }).join();
});
check('path pchip passes points without overshoot', () => {
  const p = path([[0, 0], [1, 1], [2, 1], [3, 0]]);
  let maxY = 0;
  for (let u = 0; u <= 1; u += 0.005) maxY = Math.max(maxY, p.at(u)[1]);
  return p.at(0).join() === '0,0' && p.at(1).join() === '3,0' && near(p.at(1 / 3)[1], 1) && maxY <= 1 + 1e-9;
});
check('path catmull/linear, tangent unit, 3D', () => {
  const c = path([[0, 0, 0], [1, 2, 3], [2, 0, 6]], { kind: 'catmull' });
  const l = path([[0, 0], [10, 0]], { kind: 'linear' });
  const tg = c.tangent(0.5);
  return near(Math.hypot(...tg), 1) && l.at(0.5).join() === '5,0' && near(l.length, 10, 1e-6) && c.at(0.5).join() === '1,2,3';
});
check('film normalise + live set with transitions', () => {
  const f = normalizeFilm({ dur: 10, size: [1920, 1080], shots: [
    { id: 'a', t0: 0, t1: 6, scene: 'kit:x/a' }, { id: 'b', t0: 4, t1: 10, scene: 'kit:x/b' }],
  transitions: [{ from: 'a', to: 'b', type: 'crossfade', t: 5, dur: 1 }] });
  const ids = (t) => liveAt(f, t).shots.map((s) => s.id).join();
  const tr = liveAt(f, 5.5).transitions;
  return ids(4.5) === 'a' && ids(5.5) === 'a,b' && ids(6.5) === 'b' && tr.length === 1 && near(tr[0].u, 0.5)
    && f.shots[1].z > f.shots[0].z && clampTime(f, 99) < 10 && clampTime(f, -1) === 0;
});
check('film errors are clear', () => {
  try { normalizeFilm({ dur: 1, shots: [{ id: 'a', t0: 1, t1: 0, scene: 'kit:x/y' }] }); } catch (e) {
    return /shots\[0\]: t1 \(0\) must be greater than t0 \(1\)/.test(e.message);
  }
  return false;
});
check('default safe areas scale', () => {
  const v = defaultSafe(1080, 1920), h = defaultSafe(1280, 720);
  return v.b === 420 && v.t === 220 && h.l === 64 && h.b === 80;
});
check('frame paths and indices', () => framePath('assets/car/%06d.jpg', 12) === 'assets/car/000012.jpg'
  && frameIndex(1.0, 30, 24, true) === 6 && frameIndex(5, 30, 24, false) === 23 && frameIndex(-0.1, 10, 5, true) === 4);

console.log(JSON.stringify(out));
