# Hype Scene SDK (condensed reference for the Director)

## film.json (what the film step writes)
```jsonc
{
  "version": 1, "fps": 30, "size": [1920, 1080], "dur": 45.0, "seed": 7, "title": "Red Car", "background": "#000",
  "assets": {"car": {"type": "frames"}},          // names come from the asset list; never invent assets
  "shots": [                                      // back-to-back, cover 0..dur; overlap only inside a transition window
    {"id": "walk", "t0": 0, "t1": 5, "scene": "kit:pixel/dungeon-walk", "res": [480, 270], "params": {"party": ["knight", "mage", "rogue"]}},
    {"id": "boss", "t0": 5, "t1": 21.5, "scene": "custom:boss-battle", "res": [480, 270], "params": {"boss_media": "car"}},
    {"id": "field", "t0": 21.5, "t1": 45, "scene": "kit:nature/flower-field", "res": null, "params": {"flyers": [{"media": "car", "path": "descend"}]}}
  ],
  "transitions": [{"from": "boss", "to": "field", "type": "kit:transitions/petal-bloom", "t": 21.0, "dur": 1.4, "params": {}}],
  "overlays": [{"id": "title", "t0": 40, "t1": 45, "scene": "kit:type/title", "params": {"text": "RED CAR"}}],
  "finish": {"grain": 0.04, "vignette": 0.25, "bloom": 0.0},
  "cues": [{"t": 8.1, "sfx": "hit", "gain_db": 0}],
  "music": [{"bed": "pixel_a", "t0": 0, "t1": 22.5}, {"sting": "riser", "t": 21.2}, {"bed": "cinematic_a", "t0": 22.5, "t1": 45}],
  "captions": [{"t0": 1.0, "t1": 3.2, "text": "Every hero has a boss."}],
  "safe": {"l": 96, "r": 96, "t": 64, "b": 120}
}
```
- `scene` ids: `kit:<kit>/<name>` (built-in kit scene), `lib:<name>` (user library), `custom:<name>` (a scene you specify and
  that gets coded for this film). `res` = drawing surface size; null = film size. A shot whose res is smaller than the
  film is upscaled nearest-neighbour (pixel art) unless `"upscale": "smooth"`. `z` orders simultaneous shots.
- A transition window `[t, t+dur]` must contain the cut (from.t1 == to.t0). Built-in transition types: cut, crossfade,
  dip-black, dip-white, push-left, push-right, push-up, whip, zoom-through, iris, wipe, glitch, pixelate, film-burn,
  ink-bleed, page-turn, plus kit transitions listed in the catalog (e.g. `kit:transitions/petal-bloom`).
- Overlays render above shots (titles, lower thirds, CTA); captions render above overlays.
- `music`: beds play `t0..t1` (fitted to bars automatically); `sting` = one sound at `t`. `cues` = sound effects at `t`.
  Only ids from the catalog.

## Scene modules (what the scene-code step writes; one file per custom scene)
```js
import { sr } from '../runtime/showreel.js';
sr.defineScene('custom:boss-battle', {
  layer: '2d',                    // '2d' | 'three' | 'webgl' | 'dom'
  describe: 'Pixel boss battle where the product is the boss; party attacks, boss counters, cursor picks BUY.',
  params: {                       // documented defaults (the film's shot params override them)
    boss_media: { type: 'asset',  default: null,   doc: 'product media shown as the boss' },
    boss_name:  { type: 'string', default: 'BOSS', doc: '<= 14 chars' }
  },
  async setup(ctx, p) {},         // once per shot instance: build sprites/meshes, precompute layouts, register cues
  render(ctx, t, p) {},           // REQUIRED. Draw the state at shot-local time t (0..ctx.dur). PURE function of t.
  cues(ctx, p) { return [{ t: 3.1, sfx: 'hit' }]; },   // optional, shot-local seconds
  dispose(ctx) {}                 // optional
});
```
PURE-FUNCTION RULE: `render(ctx, t, p)` must produce identical pixels for the same t regardless of call order (frames
are rendered out of order, in parallel). No accumulation across frames, no physics stepping, no state mutated in
render. Derive everything from t: analytic motion, keyframes, seeded randomness created in setup or re-created per call.

## ctx (per shot instance)
- `ctx.w, ctx.h` surface px · `ctx.dur` shot length (s) · `ctx.film` {w,h,fps,dur,aspect} · `ctx.id` · `ctx.seed` ·
  `ctx.params` · `ctx.safe` {l,r,t,b} scaled to the surface.
- '2d': `ctx.g` CanvasRenderingContext2D (imageSmoothingEnabled=false when res < film size), `ctx.canvas`.
  Clear/paint the whole surface every render.
- 'three': `ctx.THREE` (r170), `ctx.three = {renderer, scene, camera}` (sRGB output, ACES tone mapping; the runtime calls
  `ctx.three.render()` after your render unless you set `ctx.three.manual = true` and render a composer yourself).
  `ctx.addons` = {EffectComposer, RenderPass, UnrealBloomPass, BokehPass, OutputPass, GLTFLoader}.
- 'webgl': `ctx.gl` WebGL2 context, `ctx.canvas`. 'dom': `ctx.root` (absolutely positioned div w x h; style only inside
  it), `ctx.css(text)` injects scoped CSS once.
- Math & motion: `ctx.rng(seed?)` -> () => [0,1) (seeded) · `ctx.noise2(x,y)`, `ctx.noise3(x,y,z)`, `ctx.fbm2(x,y,oct)` ·
  `ctx.ease.{linear,inQuad,outQuad,inOutQuad,inCubic,outCubic,inOutCubic,outQuint,outExpo,inOutExpo,outBack,outElastic}`,
  `ctx.ease.bezier(x1,y1,x2,y2)` · `ctx.lerp(a,b,u)`, `ctx.clamp(x,a,b)`, `ctx.smoothstep(a,b,x)`,
  `ctx.remap(x,a,b,c,d)`, `ctx.mix`, `ctx.fract` · `ctx.seg(t, t0, t1, ease?)` -> 0..1 progress ·
  `ctx.spring(t, {from, to, freq, damp})` analytic · `ctx.path(points, {kind:'pchip'|'catmull'|'linear'})` ->
  `{at(u) -> [x,y(,z)], tangent(u)}` · `ctx.keys(t, [[t0,v0],[t1,v1],...], ease?)` keyframes (numbers or arrays) ·
  `ctx.shake(t, {amp, freq, decay, t0, seed})` -> [dx, dy, rot].
- Assets: `ctx.asset(name)` -> `{type, w, h, fps, dur, count, image, frame(t, {loop:true}) -> drawable, cutout?}`
  (`cutout` has the same API with alpha when available). Frames for any t are decoded before render is called.
  `ctx.loadImage(path)` (setup only, relative to the scene dir).
- Text: `ctx.text(g, str, {x, y, font, size, color, align, baseline, maxWidth, lineHeight, shadow, stroke, pixel})`
  draws text AND registers its box for QA. ALWAYS use it for readable text (never raw fillText).
- Pixel: `ctx.pixel.palette(name|hexes)`, `ctx.pixel.sprite(rows: string[], map: {char: hex})` -> bitmap,
  `ctx.pixel.blit(g, sprite, x, y, {flip, scale})`, `ctx.pixel.font(name)`, `ctx.pixel.dither(g, ...)`.
- Kits: `ctx.kit('<kit>')` -> that kit's building blocks (see the kit catalog), e.g. `ctx.kit('nature').sky(ctx, {...})`.
- Sound: `ctx.cue(t, sfx, {gain_db})` in setup() only, or return cues from `cues()`.

## Forbidden (lint rejects the scene)
`Math.random`, `Date`, `performance.now`, `setTimeout`, `setInterval`, `requestAnimationFrame`, `fetch`,
`XMLHttpRequest`, `WebSocket`, `EventSource`, dynamic `import(`, any import other than the runtime line, `eval`,
`new Function`, `document.` / `window.` (except `window.devicePixelRatio`), external URLs, CSS animations/transitions on
wall-clock time.
