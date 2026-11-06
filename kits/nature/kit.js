// Showreel kit · nature — anime meadow worlds (sky, mountains, meadow, petals, light) with the PRODUCT flying
// through them. Registers building blocks (ctx.kit('nature')) and three scenes. See KIT.md for the catalog.
import { sr } from '../../runtime/showreel.js';
import { buildWorld, SLOPE } from './lib/world.js';
import { PRESETS, resolvePreset } from './lib/presets.js';
import { PATHS, flyerPose, resolveFlyer, makeFlyers } from './lib/flyers.js';
import { makeSky } from './lib/sky.js';
import { makeMountains } from './lib/mountains.js';
import { makeTerrain } from './lib/terrain.js';
import { makeMeadow, makePetals } from './lib/sprites.js';
import { makeAtlas } from './lib/atlas.js';
import { makePost } from './lib/post.js';
import { resolveQuality, TIERS } from './lib/quality.js';
import { cameraPose } from './lib/math.js';

const TIMES = Object.keys(PRESETS).filter((k) => k !== 'golden-hour');

const blocks = {
  world: (ctx, o) => buildWorld(ctx, o),
  sky: (ctx, o) => makeSky(ctx.THREE, ctx.three.renderer, { ...o, preset: resolvePreset(o.time || o.preset) }),
  mountains: (ctx, o) => makeMountains(ctx.THREE, { ...o, preset: resolvePreset(o.time || o.preset) }),
  terrain: (ctx, o) => makeTerrain(ctx.THREE, { ...o, preset: resolvePreset(o.time || o.preset) }),
  meadow: (ctx, o) => makeMeadow(ctx.THREE, { ...o, preset: resolvePreset(o.time || o.preset) }),
  petals: (ctx, o) => makePetals(ctx.THREE, { ...o, preset: resolvePreset(o.time || o.preset) }),
  atlas: (ctx, seed) => makeAtlas(ctx.THREE, seed),
  flyers: (ctx, o) => makeFlyers(ctx.THREE, o),
  light: (ctx, o) => makePost(ctx.THREE, ctx.three.renderer, o),
  quality: (ctx, q) => resolveQuality(q, ctx.three.renderer),
  presets: PRESETS, paths: PATHS, tiers: TIERS, flyerPose, resolveFlyer, cameraPose, slope: SLOPE,
};
if (typeof sr.defineKit === 'function') sr.defineKit('nature', blocks);
else { sr.kits = sr.kits || {}; sr.kits.nature = blocks; }

/** Default non-uniform squadron when only `product` is given: one descends, one rises, one drives down the slope, one floats. */
export function defaultFlyers(media, n = 4) {
  const all = [{ media, path: 'descend' }, { media, path: 'rise' }, { media, path: 'drive-slope' }, { media, path: 'float' },
    { media, path: 'arc' }, { media, path: 'orbit' }];
  return all.slice(0, Math.max(0, Math.min(n, all.length)));
}

const COMMON = {
  time: { type: 'enum', values: TIMES, default: 'sunset', doc: 'time-of-day preset (sky, sun, palette, light)' },
  palette: { type: 'object', default: null, doc: 'preset overrides, e.g. {"sky": [[0,"#FFF0D2"],[20,"#E9A2B4"]], "light": "#FFD7A6"}' },
  product: { type: 'asset', default: null, doc: 'product media; with no `flyers`, 4 copies fly non-uniformly (descend, rise, drive-slope, float)' },
  count: { type: 'int', default: 4, doc: 'how many product flyers to auto-place (1–6) when `flyers` is empty' },
  flyers: { type: 'array', default: [], doc: `[{media, path: ${PATHS.join('|')}, d?, x0?, x1?, y0?, y1?, t0?, t1? (s), size? (m), facing?: right|left, heading?, clipRate?, clipOffset?, streaks? (0-1), wake? (0-1), cutout?: bool, key?: bool}]` },
  camera: { type: 'enum', values: ['drift', 'push', 'crane-up', 'crane-dolly', 'sweep', 'tilt-down', 'pan', 'static', 'hero-arc'], default: 'drift', doc: 'slow camera move (crane-dolly: rise + dolly in; sweep: lateral truck with counter-pan = strong parallax)' },
  cameraAmount: { type: 'number', default: 1, doc: 'scale of the camera travel (0 = locked off, 1 = default, 2 = bold)' },
  title: { type: 'enum', values: ['none', 'top', 'center', 'left', 'right'], default: 'none', doc: 'reserve this area for an overlay title (flyers keep out)' },
  quality: { type: 'enum', values: ['auto', 'high', 'medium', 'low'], default: 'auto', doc: 'auto = low on software GL (SwiftShader), high on GPU' },
  wind: { type: 'number', default: 1, doc: 'wind strength (grass sway, petal drift)' },
  petals: { type: 'number', default: 1, doc: 'petal density multiplier (0 = none)' },
  flowers: { type: 'number', default: 1, doc: 'meadow density multiplier' },
  focus: { type: 'any', default: 'auto', doc: '"auto" = rack to the first flyer, or a distance in metres' },
  rack: { type: 'array', default: null, doc: 'rack focus keys [[t, flyerIndex | {m: metres}], ...]: eased pulls between targets (e.g. hold the far cars, pull to the pass-by)' },
  focusOn: { type: 'int', default: 0, doc: 'flyer index that focus "auto" follows' },
  dof: { type: 'number', default: 1, doc: 'depth-of-field strength' },
  flare: { type: 'number', default: null, doc: 'lens flare strength (ghosts + anamorphic streak from the sun; preset default, 0 = off)' },
  variant: { type: 'string', default: '', doc: 'any string → a different (deterministic) arrangement of clouds/flowers' },
};

function flyersFrom(p) {
  if (Array.isArray(p.flyers) && p.flyers.length) return p.flyers;
  return p.product ? defaultFlyers(p.product, p.count ?? 4) : [];
}

sr.defineScene('kit:nature/flower-field', {
  layer: 'three',
  describe: 'Anime flower field (refs: AoT sunset, pastel meadow): low sun with bloom and god rays, painterly clouds lit from below, hazy mauve mountains, dense wildflowers with depth of field and big blurred blossoms in the corners, drifting petals, wind. The product flies through the sky non-uniformly (descend/rise/drive-slope/float/orbit/arc).',
  params: COMMON,
  async setup(ctx, p) { ctx.state = buildWorld(ctx, { ...p, flyers: flyersFrom(p) }); ctx.info = () => ctx.state.info(); },
  render(ctx, t) { ctx.state.render(t); },
});

sr.defineScene('kit:nature/sky-reveal', {
  layer: 'three',
  describe: 'Opens on the painted sky (clouds, sun halo, a product arcing through), then tilts down to reveal the flower field. Great as the first shot after a transition.',
  params: { ...COMMON, camera: { ...COMMON.camera, default: 'tilt-down' }, flyers: { ...COMMON.flyers, default: [] } },
  async setup(ctx, p) {
    const fl = Array.isArray(p.flyers) && p.flyers.length ? p.flyers
      : p.product ? [{ media: p.product, path: 'arc', d: 46, x0: -1.4, x1: 1.4, y0: 1.5, y1: 0.9, apex: 0.8, t0: 0.0, t1: ctx.dur * 0.9 },
        { media: p.product, path: 'descend', d: 24, x0: 0.75, x1: 0.42, y0: 2.4, y1: 0.42, t0: ctx.dur * 0.25, t1: ctx.dur }] : [];
    const pr = resolvePreset(p.time, p.palette);
    const palette = { ...(p.palette || {}), clouds: { ...pr.clouds, band: [pr.clouds.band[0], 72], cover: Math.min(0.62, pr.clouds.cover + 0.04) } };
    ctx.state = buildWorld(ctx, { ...p, palette, flyers: fl, base: 'end', laneTall: 3, camera: p.camera || 'tilt-down', cameraAmount: p.cameraAmount ?? 0.8 });
    ctx.info = () => ctx.state.info();
  },
  render(ctx, t) { ctx.state.render(t); },
});

sr.defineScene('kit:nature/product-hero', {
  layer: 'three',
  describe: 'The product presented on a meadow hilltop at golden hour: sun behind it (warm rim light and halo), low camera slowly pushing in, grass and petals in the wind. Leaves the top for a title.',
  params: { ...COMMON, time: { ...COMMON.time, default: 'golden' }, camera: { ...COMMON.camera, default: 'push' },
    cameraAmount: { ...COMMON.cameraAmount, default: 0.35 }, title: { ...COMMON.title, default: 'top' },
    size: { type: 'number', default: 5.0, doc: 'product width in metres on the hilltop' },
    distance: { type: 'number', default: 19, doc: 'hilltop distance in metres (smaller = bigger in frame)' },
    heading: { type: 'number', default: 0.12, doc: 'product yaw in radians (+ = turned toward the camera)' },
    pitch: { type: 'number', default: null, doc: 'camera pitch in degrees (default 3.2; with title "top" 8.5 so the product sits in the lower half under the title)' },
    hill: { type: 'number', default: 2.0, doc: 'hilltop height in metres' } },
  async setup(ctx, p) {
    const preset = resolvePreset(p.time);
    const az = preset.sun.az, d = p.distance ?? 19;
    const x = Math.tan(az * Math.PI / 180) * d;
    const fl = Array.isArray(p.flyers) && p.flyers.length ? p.flyers : p.product ? [{ media: p.product, path: 'hero', at: [x, -d], size: p.size ?? 5.0, heading: p.heading ?? 0.12 }] : [];
    const pitch = p.pitch ?? (p.title === 'top' ? (ctx.h > ctx.w ? 13 : 13) : 3.2);
    ctx.state = buildWorld(ctx, { ...p, flyers: fl, pitch, yaw: az * 0.85, hills: [{ x, d, h: p.hill ?? 2.0, rx: 14, rd: 7 }], focus: p.focus === 'auto' ? d : p.focus });
    ctx.info = () => ctx.state.info();
  },
  render(ctx, t) { ctx.state.render(t); },
});
