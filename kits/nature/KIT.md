# Kit `nature` — anime meadow worlds with the product flying through them

**Look** (refs: research/ref-flowerfield.md — AoT "paths" sunset, Sotiya pastel meadow, magenta→cyan edit): low
warm sun with bloom/halation and god rays; pastel gradient sky with painterly cloud masses lit from below; 2–4 hazy
mauve mountain/hill layers; dense wildflower meadow (9 species + grass, colour patches) with depth of field and big
out-of-focus blossoms framing the bottom corners; petals drifting at many depths; wind in the grass. The PRODUCT
(real media: video frames or images) is presented in 3D space: cut-out when an alpha version exists, auto-keyed when
the clip has a plain studio background, otherwise a soft glass card — graded into the scene light, warm sun-side
rim, halo, distance haze, DOF. All `layer: 'three'`; every frame is a pure function of t.

## Scenes

| id | what | key params |
|---|---|---|
| `kit:nature/flower-field` | THE hero world. Wide meadow, slow camera, product flyers moving non-uniformly. 12–25 s shots. | `product` (asset) → 4 flyers by default (descend, rise, drive-slope, float); `time`; `camera`; `title` |
| `kit:nature/sky-reveal` | Opens on the painted sky (a product arcs through, another descends), tilts down to reveal the field. Great first shot after a transition. 6–10 s. | `product`; `camera` default `tilt-down` |
| `kit:nature/product-hero` | The product on a meadow hilltop at golden hour, the sun right behind it (rim + halo), low camera pushing in; keeps the top free for a title. 5–10 s. | `product`; `time` default `golden`; `title` default `top` |

### Common params (all three scenes)
- `time`: `sunset` (default; AoT cream→peach→pink→lavender, sun on the horizon) · `golden` (golden hour, blue top) ·
  `dawn` (pink/lilac, cool) · `pastel` (Sotiya: lavender/pink/white, high soft sun) · `dream` (magenta→cyan, heavy
  glow + chromatic edge) · `night` (indigo, moon, stars, fireflies). `golden-hour` = `golden`.
- `palette`: preset overrides, e.g. `{"light": "#FFD7A6", "clouds": {"cover": 0.6, ...}}` (see lib/presets.js keys).
- `product`: asset name; with no `flyers`, `count` (1–6, default 4) copies fly: descend, rise, drive-slope, float, arc, orbit.
- `flyers`: explicit list `[{media, path, d?, x0?, x1?, y0?, y1?, t0?, t1? (seconds), size? (m), facing?, cutout?, key?, at?}]`.
  `x/y` are screen fractions in [-1, 1] at depth `d` metres (base camera); omit them to get the deliberately
  non-uniform default slot for that path (different depth, side, start time, speed — never a formation).
- `camera`: `drift` (default lateral truck + push) · `push` · `crane-up` · `tilt-down` · `pan` · `static` · `hero-arc`; `cameraAmount` 0–2.
- `title`: `none` · `top` · `center` · `left` · `right` — reserve space for an overlay title (flyers keep out).
- `quality`: `auto` (low on SwiftShader/llvmpipe, high on GPU) · `high` · `medium` · `low`.
- `wind` (1), `petals` (density ×, 0 = none), `flowers` (density ×), `focus` (`auto` = rack to the first flyer, or metres),
  `dof` (strength ×), `variant` (any string → different clouds/flower arrangement).

### Flyer paths (`lib/flyers.js`, pure `flyerPose(spec, t, env)`)
| path | motion | parks at end? |
|---|---|---|
| `descend` | enters from above the frame, eases down to a hover with a banking settle | yes |
| `rise` | emerges from behind the meadow (occluded by terrain), accelerates up and out of the top | no (exits) |
| `drive-slope` | drives down the grassy hill on the right into the meadow; wheels on the ground, rolls with the slope, contact shadow, grass in front | yes |
| `float` | drifts in from the left, hovers with a gentle bob while its wheels spin (the clip) | yes |
| `orbit` | circles in depth (scale changes), turns by squashing through edge-on | yes |
| `arc` | a long parabola across the whole sky, banking | no |
| `cross` | a straight glide across the frame with a slight wave | no |
| `hero` | fixed; with `at: [x, z]` it stands on the terrain (product-hero) | yes |
The car faces right in the source clip; flyers moving left are mirrored automatically (`facing: 'left'` if the media faces left).
Video media loop (`frame(t, {loop: true})`); each flyer gets its own clip offset so wheels never spin in sync.

## Building blocks — `ctx.kit('nature')`
| block | signature | notes |
|---|---|---|
| `world` | `(ctx, o)` → `{render(t), info(), poseAt(t), focusAt(t)}` | everything below assembled; `o` = scene params (+ `hills`, `pitch`, `yaw`, `base`, `laneTall`, `follow`) |
| `sky` | `(ctx, {time, region:{azMin,azMax,elMin,elMax} deg, texelsPerDeg, seed, drift})` | gradient dome + 2 baked painterly cloud layers + sun/moon halo + stars |
| `mountains` | `(ctx, {time, base, azMin, azMax, seed, sunDir})` | 4 hazy ridge layers (cylinder sections → real parallax) |
| `terrain` | `(ctx, {time, hills, sunDir, flowerColors, nx, nz})` | rolling meadow ground, wind sheen, footprint-LOD flower dabs, aerial perspective |
| `meadow` | `(ctx, {time, atlas, counts:{field, fg, frame}, view, ...})` | instanced grass + 9 flower species + framing blossoms, wind sway f(t), per-instance DOF |
| `petals` | `(ctx, {time, atlas, count, view, fireflies?})` | analytic drift in camera-base lanes, tumble, backlight; `fireflies: true` for night |
| `atlas` | `(ctx, seed)` | channel-packed sprite atlas (R petal, G stem, B centre) × 5 pre-blurred DOF rows |
| `flyers` | `(ctx, {specs, assets, preset, sunDir, dur, quality, env, view})` | product presentation + paths |
| `light` | `(ctx, {w, h, scale, samples, rays, ca, grade})` | post: mist (¼), bloom (⅛), god rays, CA, vignette, soft-shoulder tone curve |
| `quality` | `(ctx, 'auto'|tier)` | tier table (`tiers`) |
| `presets`, `paths`, `tiers`, `flyerPose`, `resolveFlyer`, `cameraPose`, `slope` | data/functions | pure, also usable from custom scenes |

## Performance (this PC, 1080p output, measured)
| | GPU RX 6800 XT (tier high) | CPU SwiftShader `--disable-gpu` (tier low: 960×540 internal) |
|---|---|---|
| world only (no flyers), ms/frame in-page | 2.7 | 247 (before tuning) → ~190 |
| flower-field + 4 car flyers, ms/frame in-page | ~40 (mostly per-frame PNG decode + upload of 4 cut-out frames in the dev shim) | 222 |
| 15 s flower-field video, real runtime (450 frames) | **29.4 s** render (46 s incl. 12.5 s asset prep) | **132.7 s** render (149 s total) |
Tier `high` on SwiftShader would be ~1.8 s/frame — always let `quality: auto` pick.

## Director tips
- Hero scenario (after a pixel boss battle): `sky-reveal` 6–8 s (or straight into) `flower-field` 15–25 s with
  `product`, then `product-hero` 6–8 s with `title: "top"` and an overlay title/CTA.
- The product must be visible ≥ 60 % of the time: the default squadron puts it in frame from ~0.5 s.
- Keep overlays out of the bottom 25 % (framing blossoms) or set `title` so flyers make room.
- Pair with `kit:transitions/petal-bloom` (pixel kit) into the field; music: dreamy pad bed.
