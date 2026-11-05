// check.mjs — pure-logic checks of the nature kit (no browser): flyer paths, camera rigs, presets, quality.
// usage: node tests/kits/nature/node/check.mjs  → prints a JSON report (consumed by test_nature_kit.py)
import { flyerPose, resolveFlyer, PATHS } from '../../../../kits/nature/lib/flyers.js';
import { cameraPose, terrainHeight, catmull, mulberry32 } from '../../../../kits/nature/lib/math.js';
import { PRESETS } from '../../../../kits/nature/lib/presets.js';
import { isSoftwareGL, TIERS } from '../../../../kits/nature/lib/quality.js';

const SLOPE = { hill: { x: 20, d: 46, h: 4.2, rx: 22, rd: 18 }, a: [33, -57], b: [4, -27] };
const env = { dur: 15, slope: { a: SLOPE.a, b: SLOPE.b }, terrain: { hills: [SLOPE.hill] } };
const report = { errors: [], paths: PATHS.length };
const fail = (m) => report.errors.push(m);

// 1) every path: deterministic, finite, continuous (no jumps > 0.25 NDC/frame)
for (const path of PATHS) {
  const s = resolveFlyer({ media: 'car', path, at: path === 'hero' ? [0, -20] : undefined }, 0, 15, 7);
  let prev = null;
  for (let f = 0; f <= 450; f++) {
    const t = f / 30;
    const a = flyerPose(s, t, env), b = flyerPose(s, t, env);
    if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${path}: not deterministic at t=${t}`);
    if (!a.visible) { prev = null; continue; }
    const vals = a.world ? a.world : [a.sx, a.sy, a.d];
    if (vals.some((v) => !Number.isFinite(v))) fail(`${path}: non-finite pose at t=${t}`);
    if (prev && !a.world) { const j = Math.hypot(a.sx - prev.sx, a.sy - prev.sy); if (j > 0.25) fail(`${path}: jump ${j.toFixed(3)} at t=${t}`); }
    if (prev && a.world) { const j = Math.hypot(...a.world.map((v, i) => v - prev.world[i])); if (j > 1.5) fail(`${path}: world jump ${j.toFixed(2)} at t=${t}`); }
    prev = a;
  }
}

// 2) the default squadron is NOT a formation: distinct depths, start times, and screen positions
const squad = ['descend', 'rise', 'drive-slope', 'float'].map((p, i) => resolveFlyer({ media: 'car', path: p }, i, 15, 7));
const t0s = squad.map((s) => s.t0.toFixed(2));
if (new Set(t0s).size < 3) fail(`start times too uniform: ${t0s}`);
const depths = squad.filter((s) => s.d).map((s) => s.d);
if (new Set(depths).size !== depths.length) fail(`equal depths: ${depths}`);
let minSep = 9;
for (let f = 15; f <= 450; f += 15) {
  const P = squad.map((s) => flyerPose(s, f / 30, env)).filter((p) => p.visible && !p.world);
  for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) minSep = Math.min(minSep, Math.hypot(P[i].sx - P[j].sx, P[i].sy - P[j].sy));
}
report.minSeparation = +minSep.toFixed(3);
if (minSep < 0.12) fail(`flyers overlap on screen (min NDC separation ${minSep.toFixed(3)})`);
// product in frame early: the descending hero is inside the frame (sy <= 1.05) by 0.7 s
const hero = flyerPose(squad[0], 0.7, env);
if (!(hero.visible && hero.sy <= 1.05)) fail(`hero not in frame by 0.7 s (sy=${hero.sy})`);

// 3) drive-slope stays on the ground
const ds = squad[2];
for (let f = 0; f <= 450; f += 10) {
  const p = flyerPose(ds, f / 30, env);
  if (!p.visible) continue;
  const gap = p.world[1] - terrainHeight(p.world[0], p.world[2], env.terrain);
  if (gap < 0.0 || gap > 0.12) fail(`drive-slope off the ground by ${gap.toFixed(3)} at t=${f / 30}`);
}

// 4) camera rigs: deterministic, continuous, finite for every move
for (const move of ['drift', 'push', 'crane-up', 'tilt-down', 'pan', 'static', 'hero-arc']) {
  const base = { pos: [0, 1.45, 0], yaw: 0, pitch: 0.08, fov: 34, target: [0, 0, -30] };
  let prev = null;
  for (let f = 0; f <= 450; f++) {
    const p = cameraPose(move, f / 30, 15, base, 1);
    if ([...p.pos, p.yaw, p.pitch].some((v) => !Number.isFinite(v))) fail(`${move}: non-finite at f=${f}`);
    if (prev) {
      const dp = Math.hypot(...p.pos.map((v, i) => v - prev.pos[i]));
      if (dp > 0.25) fail(`${move}: camera jump ${dp.toFixed(3)} m at f=${f}`);
      if (Math.abs(p.pitch - prev.pitch) > 0.02 || Math.abs(p.yaw - prev.yaw) > 0.02) fail(`${move}: rotation jump at f=${f}`);
    }
    prev = p;
  }
}

// 5) presets: required keys, ascending sky stops, valid hex colours
const HEX = /^#[0-9A-Fa-f]{6}$/;
for (const [name, P] of Object.entries(PRESETS)) {
  for (const k of ['sky', 'sun', 'clouds', 'mountains', 'haze', 'grass', 'light', 'ambient', 'flowers']) if (P[k] == null) fail(`${name}: missing ${k}`);
  const els = P.sky.map((s) => s[0]);
  if (els.some((e, i) => i && e <= els[i - 1])) fail(`${name}: sky stops not ascending`);
  if (P.sky.length > 8) fail(`${name}: > 8 sky stops`);
  const cols = [...P.sky.map((s) => s[1]), P.haze, P.light, P.ambient, ...Object.values(P.grass), ...P.mountains.map((m) => m.col)];
  for (const c of cols) if (!HEX.test(c)) fail(`${name}: bad colour ${c}`);
}
report.presets = Object.keys(PRESETS).length;

// 6) quality detection + misc
if (!isSoftwareGL('ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)')) fail('SwiftShader not detected');
if (isSoftwareGL('ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)')) fail('GPU detected as software');
if (!(TIERS.low.field < TIERS.high.field && TIERS.low.scale < TIERS.high.scale)) fail('low tier is not cheaper');
const r1 = mulberry32(5), r2 = mulberry32(5);
if (r1() !== r2()) fail('rng not deterministic');
const c = catmull([[0, 0], [1, 1], [2, 0]]);
if (Math.abs(c.at(0.5)[0] - 1) > 1e-9) fail('catmull midpoint');

console.log(JSON.stringify(report));
