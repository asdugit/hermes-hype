// nature kit · world assembly: builds the whole anime meadow world for a shot and renders it at time t.
// Used by the kit's scenes (flower-field, sky-reveal, product-hero) and exposed as a building block.
import { resolvePreset, FLOWERS, lin3 } from './presets.js';
import { resolveQuality } from './quality.js';
import { cameraPose, clamp, lerp, hashStr } from './math.js';
import { makeSky } from './sky.js';
import { makeMountains } from './mountains.js';
import { makeTerrain } from './terrain.js';
import { makeAtlas } from './atlas.js';
import { makeMeadow, makePetals } from './sprites.js';
import { makeFlyers, flyerPose, resolveFlyer } from './flyers.js';
import { makePost } from './post.js';

const D2R = Math.PI / 180;

/** Default drive-slope hill + its descent line (world metres, camera base at the origin looking -z): the car comes
 *  over the crest and drives down toward the camera, the way the clip's 3/4-front view faces. 9:16 has its own. */
export const SLOPE = { hill: { x: 20, d: 46, h: 4.2, rx: 22, rd: 18 }, a: [20, -48], b: [6, -22] };
export const SLOPE_V = { hill: { x: 8, d: 44, h: 4.0, rx: 15, rd: 16 }, a: [8, -46], b: [2.2, -20] };

/** Keep flyers out of the reserved title area (pure; returns a new spec). */
export function avoidTitle(spec, title) {
  const s = { ...spec };
  if (title === 'top') { for (const k of ['y0', 'y1']) if (s[k] != null && s[k] > 0.35 && s[k] < 1.2) s[k] = 0.32; }
  if (title === 'center') { for (const k of ['x0', 'x1']) if (s[k] != null && Math.abs(s[k]) < 0.45 && s.path !== 'arc' && s.path !== 'cross') s[k] = (s[k] < 0 ? -1 : 1) * 0.5; }
  if (title === 'left') { for (const k of ['x0', 'x1']) if (s[k] != null && s[k] < -0.1 && s[k] > -1.1) s[k] = 0.1 + (s[k] + 1) * 0.3; }
  if (title === 'right') { for (const k of ['x0', 'x1']) if (s[k] != null && s[k] > 0.1 && s[k] < 1.1) s[k] = -0.1 - (1 - s[k]) * 0.3; }
  return s;
}

/**
 * Build a world. ctx = SDK ctx ('three' layer). o = {
 *   time, palette, flyers, camera, cameraAmount, title, quality, seed, focus, wind, petals, flowers, pitch, yaw,
 *   base (camera pose for flyer NDC), laneTall (petal lanes for tilting shots), hills (extra) }
 */
export function buildWorld(ctx, o) {
  const THREE = ctx.THREE, { renderer, scene, camera } = ctx.three;
  const W = ctx.w, H = ctx.h, dur = ctx.dur;
  const preset = resolvePreset(o.time || 'sunset', o.palette || null);
  const Q = resolveQuality(o.quality || 'auto', renderer);
  const seed = ((ctx.seed || 0) * 31 + hashStr(o.variant || ctx.id || 'field')) >>> 0;
  const flowerColors = { ...FLOWERS, ...(o.flowerColors || {}) };
  const portrait = H > W;
  const fovV = o.fov || (portrait ? 58 : 34);
  const tanV = Math.tan(fovV * D2R / 2), tanH = tanV * W / H;
  camera.fov = fovV; camera.aspect = W / H; camera.near = 0.15; camera.far = 6000; camera.updateProjectionMatrix();
  const move = o.camera || 'drift', amt = o.cameraAmount ?? 1;
  const basePose = { pos: [0, 1.45, 0], yaw: (o.yaw || 0) * D2R, pitch: (o.pitch ?? (portrait ? 9 : 4.6)) * D2R, fov: fovV, target: o.target };
  const poseAt = (t) => cameraPose(move, t, dur, basePose, amt);

  // view frame for flyer NDC placement + petal lanes
  const ref = o.base === 'start' ? poseAt(0) : o.base === 'end' ? poseAt(dur) : poseAt(dur * 0.5);
  const fwd = new THREE.Vector3(Math.sin(ref.yaw) * Math.cos(ref.pitch), Math.sin(ref.pitch), -Math.cos(ref.yaw) * Math.cos(ref.pitch));
  const right = new THREE.Vector3(Math.cos(ref.yaw), 0, Math.sin(ref.yaw));
  const up = new THREE.Vector3().crossVectors(right, fwd).normalize();
  let travel = 0;
  const p0 = poseAt(0).pos, p1 = poseAt(dur).pos;
  travel = Math.hypot(p1[0] - p0[0], p1[2] - p0[2]) + 1;
  const view = { base: ref.pos, fwd, right, up, tanH, tanV, travel };

  // sky region = union of what the camera sees over the shot (+ margins and cloud drift)
  let azMin = 1e9, azMax = -1e9, elMin = 1e9, elMax = -1e9;
  const hf = Math.atan(tanH) / D2R, vf = Math.atan(tanV) / D2R;
  for (let i = 0; i <= 12; i++) {
    const ps = poseAt((dur * i) / 12);
    azMin = Math.min(azMin, ps.yaw / D2R - hf); azMax = Math.max(azMax, ps.yaw / D2R + hf);
    elMin = Math.min(elMin, ps.pitch / D2R - vf); elMax = Math.max(elMax, ps.pitch / D2R + vf);
  }
  const drift = o.cloudDrift ?? 0.22;
  const sky = makeSky(THREE, renderer, { preset, seed, drift, texelsPerDeg: Q.skyTpd,
    region: { azMin: azMin - 6 - drift * dur, azMax: azMax + 6, elMin: Math.max(-3, elMin - 3), elMax: Math.min(86, elMax + 6) } });
  scene.add(sky.mesh);

  const hills = [...(o.hills || [])];
  const flyerSpecs = (o.flyers || []).map((f) => avoidTitle(f, o.title));
  const SL = o.slope || (portrait ? SLOPE_V : SLOPE);
  if (flyerSpecs.some((f) => f.path === 'drive-slope') || o.slopeHill) hills.push(SL.hill);
  const terrainOpt = { hills };
  const mountains = makeMountains(THREE, { preset, base: [0, 1.45, 0], azMin: azMin - 10, azMax: azMax + 10, seed, sunDir: sky.sunDir });
  scene.add(mountains.group);
  const terrain = makeTerrain(THREE, { preset, hills, sunDir: sky.sunDir, flowerColors, nx: Q.terrain[0], nz: Q.terrain[1], flowerAmt: o.flowers ?? 1 });
  scene.add(terrain.mesh);

  const atlas = makeAtlas(THREE, seed);
  const pxScale = (H / 2) / tanV;
  const cocK = (o.dof ?? 1) * 64 * (H / 1080) * (portrait ? 0.8 : 1);
  const focus0 = typeof o.focus === 'number' ? o.focus : 26;
  const dens = o.flowers ?? 1;
  const mOpt = { preset, flowerColors, hills, sunDir: sky.sunDir, seed, atlas, pxScale, cocK, focus: focus0, wind: o.wind ?? 1 };
  const meadow = makeMeadow(THREE, { ...mOpt, view: { base: [0, 1.45, 0], tanH, tanV, travel }, counts: { field: Math.round(Q.field * dens) } });
  scene.add(meadow.mesh);
  // near band + framing blossoms ride with the camera (follow 0.75 → slow parallax, never passed by a dolly)
  const start = poseAt(0).pos;
  const near = makeMeadow(THREE, { ...mOpt, hills: [], seed: seed + 3, view: { base: [start[0], 1.45, start[2]], tanH, tanV, travel: 0 },
    counts: { fg: Math.round(Q.fg * Math.min(dens, 1.5)), frame: o.frame === false ? 0 : Q.frame } });
  near.mesh.renderOrder = 30;
  scene.add(near.mesh);
  const FOLLOW = o.follow ?? 0.9;
  const petals = (o.petals ?? 1) > 0 && !preset.fireflies
    ? makePetals(THREE, { preset, flowerColors, seed, sunDir: sky.sunDir, atlas, pxScale, cocK, focus: focus0, wind: o.wind ?? 1, count: Math.round(Q.petals * (o.petals ?? 1)),
      view: { ...view, tanV: tanV * (o.laneTall || 1) } }) : null;
  if (petals) scene.add(petals.mesh);
  const flies = preset.fireflies ? makePetals(THREE, { preset, flowerColors, seed: seed + 5, sunDir: sky.sunDir, atlas, pxScale, cocK, focus: focus0, wind: 0.3,
    count: Math.round(preset.fireflies * (Q.tier === 'low' ? 0.6 : 1)), fireflies: true, view }) : null;
  if (flies) scene.add(flies.mesh);

  const env = { slope: { a: SL.a, b: SL.b }, terrain: terrainOpt };
  /** The live camera frame at t (for camera-relative flyers such as the pass-by). */
  const viewAt = (t) => {
    const ps = poseAt(t), cy = Math.cos(ps.yaw), sy = Math.sin(ps.yaw), cp = Math.cos(ps.pitch), sp = Math.sin(ps.pitch);
    const f = [sy * cp, sp, -cy * cp], r = [cy, 0, sy];
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    return { base: ps.pos, fwd: f, right: r, up: u };
  };
  const flyers = makeFlyers(THREE, { specs: flyerSpecs, assets: (n) => ctx.asset(n), preset, sunDir: sky.sunDir, dur, quality: Q, env, seed, view, rim: o.rim ?? 1,
    portrait, flowerColors, viewAt });
  scene.add(flyers.group);

  const post = makePost(THREE, renderer, { w: W, h: H, scale: Q.scale, samples: Q.samples, raySamples: Q.raySamples, rays: Q.rays && preset.rays > 0, ca: (preset.ca ?? 1) * Q.ca,
    grade: { bloom: preset.bloom, rays: preset.rays, mist: preset.mist, exposure: preset.exposure, vignette: o.vignette ?? 0.2, flare: o.flare ?? preset.flare ?? 0 } });
  ctx.three.manual = true;

  const sunV = new THREE.Vector3();
  const resolved = flyerSpecs.map((f, i) => resolveFlyer(f, i, dur, seed, portrait));
  /** Focus distance (m) on flyer i at time t (null when it is not visible). */
  function distTo(i, t) {
    const hero = resolved[i];
    if (!hero) return null;
    const pz = flyerPose(hero, t, { dur, slope: env.slope, terrain: terrainOpt });
    if (!pz.visible) return null;
    const p = flyers.posOf(pz, t);
    const ps = poseAt(t).pos;
    return clamp(Math.hypot(p[0] - ps[0], p[1] - ps[1], p[2] - ps[2]), 4, 200);
  }
  const target = (k, t) => (typeof k === 'number' && Number.isInteger(k) && k >= 0 && k < resolved.length ? (distTo(k, t) ?? focus0)
    : k && typeof k === 'object' && Number.isFinite(k.m) ? k.m : focus0);
  // rack focus: o.rack = [[t, flyerIndex | {m: metres}], ...] — eased pulls between targets (each tracked live)
  const rack = Array.isArray(o.rack) && o.rack.length ? [...o.rack].sort((a, b) => a[0] - b[0]) : null;
  function focusAt(t) {
    if (typeof o.focus === 'number') return o.focus;
    if (rack) {
      if (t <= rack[0][0]) return target(rack[0][1], t);
      for (let i = 1; i < rack.length; i++) {
        const [t1, k1] = rack[i];
        if (t <= t1) {
          const [t0, k0] = rack[i - 1], pull = Math.min(0.9, (t1 - t0));
          const u = clamp((t - (t1 - pull)) / pull), e = u * u * (3 - 2 * u);
          const a = target(k0, t), b = target(k1, t);
          return 1 / lerp(1 / a, 1 / b, e);                // pull in diopters (how a focus puller moves)
        }
      }
      return target(rack[rack.length - 1][1], t);
    }
    return distTo(o.focusOn ?? 0, t) ?? focus0;
  }

  const skip = new Set(o.skip || []);   // dev profiling: ['sky','mountains','terrain','meadow','near','petals','flyers']
  sky.mesh.visible = !skip.has('sky'); mountains.group.visible = !skip.has('mountains'); terrain.mesh.visible = !skip.has('terrain');
  meadow.mesh.visible = !skip.has('meadow'); near.mesh.visible = !skip.has('near'); if (petals) petals.mesh.visible = !skip.has('petals');
  function render(t) {
    const ps = poseAt(t);
    camera.position.set(...ps.pos);
    camera.rotation.set(ps.pitch, -ps.yaw, ps.roll, 'YXZ');
    camera.updateMatrixWorld(true);
    const focus = focusAt(t);
    sky.update(t, camera); terrain.update(t); meadow.update(t, focus);
    near.update(t, focus, [(ps.pos[0] - start[0]) * FOLLOW, (ps.pos[1] - start[1]) * FOLLOW, (ps.pos[2] - start[2]) * FOLLOW]);
    if (petals) petals.update(t, focus);
    if (flies) flies.update(t, focus);
    flyers.update(t, camera, { cocK, focus, pxScale, hpx: H / 2 });
    renderer.setRenderTarget(post.target);
    renderer.setClearColor(0x000000, 1);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    sunV.copy(camera.position).addScaledVector(sky.sunDir, 3000).project(camera);
    post.render(sunV.z < 1 ? [sunV.x, sunV.y] : null, t);
  }
  return {
    render, preset, quality: Q, flyers, view, poseAt, focusAt,
    info: () => ({ tier: Q.tier, gl: Q.gl, internal: [post.iw, post.ih], meadow: meadow.count + near.count, petals: petals ? petals.count : 0,
      flyers: flyers.flyers.map((f) => ({ media: f.s.media, path: f.s.path, mode: ['cutout', 'key', 'card'][f.mode] })) }),
  };
}

export { lin3 };
