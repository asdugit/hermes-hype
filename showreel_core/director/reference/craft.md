# Craft notes for scene code (read before writing a scene)

## Always
- Paint every pixel every frame: start render() by filling the background (or drawing the sky/backdrop).
- Build heavy things once in setup() (sprites, gradients you can cache as offscreen canvases, layouts, star/petal tables
  from a seeded rng). render() only reads them and derives positions from t.
- Time design: plan the shot as beats with shot-local times (e.g. 0.0-1.2 enter, 1.2-2.0 anticipation, 2.0 hit, ...).
  Use `ctx.seg(t, a, b, ctx.ease.outCubic)` per beat and combine. Every beat starts from where the last one ended.
- Animation principles: anticipation before big moves, overshoot/settle (`outBack`, `spring`), follow-through and
  secondary motion (hair, capes, petals, dust), holds of 0.3-0.6 s after a hit so the viewer can read it, ease in/out
  (never linear for characters/cameras). Impacts: 2-4 frame white/red flash, `ctx.shake` decaying over ~0.4 s,
  hit-stop (freeze 2-3 frames), particles that fly out and fall with gravity computed analytically from (t - t_hit).
- Depth: 3+ layers (far, mid, near) with parallax, atmospheric fade toward the horizon colour, a foreground element
  that frames the shot, light direction consistent across layers.
- The product is the hero: large (>= 30 % of frame height when it is the subject), well lit, never covered by text or
  UI, framed with breathing room, moving with intent. Draw the product media with `ctx.asset(name).frame(t)`; use the
  `cutout` when you need it without background. Never draw a fake substitute for the product.
- Text: few words, large, high contrast, inside `ctx.safe`, through `ctx.text`. Pixel text: integer sizes of the bitmap
  font, 1 px dark outline or shadow. HD text: >= 42 px at 1080p for anything the viewer must read. For a drop shadow
  or outline use `ctx.text`'s `shadow` / `stroke` options: drawing the same string twice registers two overlapping
  text boxes and fails layout QA.
- Colour: one clear palette per world (5-8 colours + 1 accent). Accent = the product's colour. Avoid pure #000/#fff
  except for flashes.
- Deterministic randomness: `const r = ctx.rng(17)` in setup to precompute tables; in render use those tables.

## Pixel art (res like 480x270 or 320x180)
- Integer coordinates only (`Math.round`), no rotation except 90 degree steps, no alpha blending except dithering or
  full-tile flashes, imageSmoothingEnabled stays false. 1 px dark outlines on characters. Limited palette.
- Sprites from strings via `ctx.pixel.sprite(rows, map)`; 2-4 frame walk/idle cycles chosen by
  `Math.floor(t * fps_of_cycle) % frames`.
- Pixelate the product media by drawing it into a small offscreen canvas (e.g. 96 px wide) and blitting it scaled up
  with smoothing off, then quantise/outline it so it sits in the pixel world.
- Battle UI: chunky bordered boxes (2 px border + 1 px inner highlight), bitmap font, blinking cursor (`Math.floor(t*4)%2`).

## Painterly / anime HD (res null = film size)
- Sky: vertical gradient with 3-5 stops, painterly cloud masses (fbm noise shaped by a soft threshold, lit from the
  sun side, darker undersides), sun with layered radial bloom.
- Mountains: 2-3 silhouettes from 1D fbm, each layer lighter and bluer/mauve with distance (aerial perspective).
- Meadow: thousands of small flowers drawn from a precomputed table (x, y, size, colour, sway phase), denser and
  smaller toward the horizon, sway with `sin(t*w + phase)`; big blurred blossoms in the foreground corners
  (draw with `ctx.g.filter = 'blur(6px)'` sparingly, or soft radial gradients).
- Petals: 100-300 petals with per-petal depth (size, speed, blur), drifting on analytic curves, rotating, wrapping
  with `fract`.
- Light: a warm rim on the product from the sun side, soft glow (`globalCompositeOperation = 'lighter'` with a
  radial gradient), subtle vignette.

## Three.js scenes
- Build meshes/materials in setup; in render set positions/rotations/camera from t only. Use `ctx.three.camera`.
- Product video/image as a texture: create the texture in setup, update its image from `ctx.asset(name).frame(t)` in
  render and set `needsUpdate = true`.
- Keep geometry modest (software rendering may be used): < 200k triangles, no shadows unless essential.
