# Pixel kit (`kit:pixel/*`) — 16-bit RPG world for Hype

Original 16-bit art (CC0, made for Hype): one palette ("Dusk 32"), one pixel size, crisp 1-bit text, motion on
twos. The game world is always 480×270 (16:9) or 270×480 (9:16). Two ways to put it on screen:
- **`res` = the film size** (`[1920, 1080]` / `[1080, 1920]`, recommended for hero shots): the kit upscales its own
  world through a **camera** — integer pixel sizes (4 px = whole world, 8/10/12 px = close-ups), zooms stepped on
  twos, punches on hits — and draws the UI (menus, dialogs, HP) on a separate unzoomed layer at 4 px.
- `res: [480, 270]` / `[270, 480]`: the runtime upscales nearest-neighbour ×4; cameras floor to whole crops.
Every scene is a pure function of t, palette-locked, safe-area aware (text stays inside `film.safe`), and emits SFX
cues from `assets/audio/sfx`. Proven shot recipes: **RECIPES.md** (copy them).

## Hero recipe: "the product is the boss" → BUY → petal bloom
```jsonc
"assets": {"car": {"type": "frames", "src": "car.mp4", "cutout": "car_alpha/"}},   // cutout optional, looks best
"shots": [
  {"id": "walk", "t0": 0,   "t1": 6.9,  "scene": "kit:pixel/dungeon-walk", "res": [1920, 1080], "params": {"door_label": "LOCKED BOSS"}},
  {"id": "boss", "t0": 6.4, "t1": 19.6, "scene": "kit:pixel/boss-battle",  "res": [1920, 1080],
   "params": {"boss_media": "car", "boss_name": "RED CAR", "boss_level": "99", "pick": "BUY", "pick_text": "Make it yours.",
              "timings": {"click": 11.4}}},
  {"id": "field", "t0": 18.1, "t1": 45, "scene": "kit:nature/flower-field"}],
"transitions": [
  {"from": "walk", "to": "boss",  "type": "kit:pixel/battle-swirl", "t": 6.4,  "dur": 0.7},
  {"from": "boss", "to": "field", "type": "kit:pixel/petal-bloom",  "t": 18.1, "dur": 1.5, "params": {"origin": [0.108, 0.815]}}],
"music": [{"bed": "pixel_boss", "t0": 0, "t1": 18.6}, {"sting": "bloom_riser", "t": 18.6}, {"bed": "dream", "t0": 18.6, "t1": 45}]
```
The full hand-directed film (both aspects, every number) is `RECIPES.md` → "Red Car hero film".
- Start the petal-bloom ~0.3 s after the boss shot's `timings.click` (shot-local) so the click reads.
- `origin` = where BUY sits: `[0.108, 0.815]` (16:9) / `[0.215, 0.19]` (9:16) with the default safe area and menu;
  `ctx.kit('pixel').pickOrigin(aspect, params, safe)` computes it for other menus.
- The 9:16 version is the same film with `res: [1080, 1920]` (or `[270, 480]`).
- The bloom_riser sting's impact goes ~0.5 s into the petal-bloom (as the field resolves); the dream bed starts there.

## Scenes
| id | what it shows | params (default) |
|---|---|---|
| `kit:pixel/dungeon-walk` | Party (knight, mage, rogue, carrying a lantern glow) walks a torch-lit corridor (lighting pass, flicker, pilasters, banners) to a sealed door with chains + padlock and a plaque; leader "!" emote; rumble, chains snap, door swings open on red fog + glowing eyes. Follow camera: close on the party, pulls back to reveal the door, leans in as it rumbles, dives into the doorway. | `party` [knight,mage,rogue] · `door_label` "LOCKED BOSS" · `open` true · `open_at` dur-2.0 · `speed` 44 px/s · `caption` "" · `fade_in` true · `camera` follow\|wide · `zoom` 2.5 |
| `kit:pixel/boss-battle` | **The product is the boss**: media palette-quantised in a horned gold frame (cutout → floats in a "lair" with turning rays), name plate `NAME  LV n`, HP bar. Intro message; the boss revs (shake + exhaust puffs), winds up (charge glow, push-in), throws a spinning blade on a screen-wide arc with a tapering swoosh trail through the party (hit-stop per hit, white+red flash, camera punch, scale-2 damage numbers, HP drain with lag chunk); command menu opens, cursor walks (hesitation overshoot) to the pick, sell line, click (selection bar, coins, sparkles), the camera pushes in on the prize. `camera: cinematic` = close on the boss, whip to the party on the hits, wide for the menu, push on the prize. | `boss_media` asset · `boss_name` "BOSS" · `boss_level` "99" · `party` · `party_hp` [220,140,160] · `attacks` [{by:"boss",kind:"blade",move:"SPINNING BLADE",dmg:[48,52,61]}] (hero kinds: `slash`, `spell`, dmg number or "MISS") · `menu` [FIGHT,ITEM,BUY,RUN] · `pick` "BUY" · `pick_text` "Make it yours." · `cursor_path` null · `intro_text` "{boss} blocks the way!" · `taunt` · `prompt` "Command?" · `timings` {drop, intro, menu, click} · `palette` null · `dither` 28 · `fit` cover · `backdrop` auto\|media |
| `kit:pixel/title-screen` | Parallax world, banded gold logo drops in with bounce + shine sweep, tagline types, product on a stone podium (or the party), blinking PRESS START, footer. | `title` (film title) · `tagline` · `press` "PRESS START" · `world` overworld\|night\|castle · `media` · `party` · `footer` |
| `kit:pixel/item-get` | Product as a LEGENDARY ITEM: chest shakes, bursts open with a beam and turning rays, product rises in sparkles, ITEM GET! ribbon, rarity/name/description dialog, hero cheers. | `media` · `name` · `desc` · `rarity` "LEGENDARY" · `banner` "ITEM GET!" · `hero` "knight" · `icon` "star" |
| `kit:pixel/shop` | Item shop: product on a velvet cushion with a price tag, shelves of goods under a lamp, merchant, shopkeeper line, BUY/SELL/EXIT, cursor clicks BUY, coins fly, "Thank you!". | `media` · `name` · `price` (verbatim) · `line` "{name}! Finest in the land. {price}." · `menu` · `pick` · `thanks` |
| `kit:pixel/quest-log` | QUEST LOG window over a world; checks stamp in one by one (coin cue each), active item pulses. | `title` · `items` [{text,status:done\|active\|todo}] · `world` night |
| `kit:pixel/score-tally` | Rows with dotted leaders, numbers roll up (tick cues), last row flashes gold, stars hop in. | `title` "RESULTS" · `rows` [{label,value,display?}] · `world` castle · `stars` 3 |

### Quick-mode types (`kit:pixel/<TYPE>`) — params `{data: TimelineScene.data, image, image2, media, world}`
`data` is the verbatim TimelineScene.data (research/wp-e-story.md §2). Image types take the asset name in `image`
(or `data.image.asset` / `data.hero.asset`).
| type | look |
|---|---|
| `kit:pixel/HOOK` | power-on line → product artifact glowing on a dimmed world, label in gold |
| `kit:pixel/TITLE` | the title screen fed by `{title, tagline, product, one_liner}` (+ `media`) |
| `kit:pixel/PROBLEM` | dialog with a "YOU" silhouette portrait, the ask typed with blips |
| `kit:pixel/PLAN` | quest log (todo statuses mapped: completed→done, in_progress→active) |
| `kit:pixel/CODE` | SPELLBOOK window: line numbers, focus band, lines stream in, soft-wrap with a continuation mark |
| `kit:pixel/DIFF` | +rows on green, −rows on maroon, hunk headers, +N/−N counters roll |
| `kit:pixel/TERMINAL` | `$ cmd` types, output streams, PASS!/FAIL banner, knight vs. monster |
| `kit:pixel/MONTAGE` | INVENTORY grid: an item icon per tool call + arg, COMBO ×N |
| `kit:pixel/SCREEN` | capture revealed by a 16→1 mosaic, focus brackets walk to `bbox` |
| `kit:pixel/FEATURE` | SCREEN + cursor click at `click` + the feature line in a dialog |
| `kit:pixel/SCROLL` | capture pans through `scroll:[from,to]` of a tall page |
| `kit:pixel/STATS` | score tally of `stats` (label/display) |
| `kit:pixel/BEFORE_AFTER` | LEVEL 1 (greyscale) vs LEVEL 2 + LEVEL UP! ribbon (images or terminal/diff dicts) |
| `kit:pixel/CALLOUT` | a hero's speech box, quote streams word by word, `— who` |
| `kit:pixel/END` | THANKS FOR PLAYING, title, PB (speedrun), CTA in a command window, URL, credit, party waves |

## Transitions
| id | kind | what |
|---|---|---|
| `kit:pixel/petal-bloom` | canvas | (emits petal_burst + switch_whoosh cues) radial wave from `origin` detaches the pixel picture: crisp blocks lift off, become soft HD petals that flutter (spin + 3D flip), ease into pastel petal colours and drift on `wind`; underneath, the next shot resolves from coarse blocks to full resolution with a light burst. Params: `origin` [0.5,0.55] · `cell` 0 (auto ≈120 petals across) · `density` 0.55 · `wind` [0.45,-1] · `wave` 0.55 · `pastel` true · `bloom` 0.55. 1.2–1.6 s. |
| `kit:pixel/battle-swirl` | canvas | RPG encounter: 3 over-bright flashes, a block spiral to black, stripes open on the next shot (0.5–0.7 s; never a grey wash). `band` 12 · `block` 16. Emits glitch + whoosh cues. |
| `kit:pixel/iris` | canvas | stair-stepped circle closes on `center`, holds `hold`, opens on the next shot |
| `kit:pixel/screen-slide` | canvas | next screen pushes the old one out in `steps` (4) stepped positions, `dir` left\|right\|up\|down |

## Building blocks — `const px = ctx.kit('pixel')` (for Director-written pixel scenes)
```js
render(ctx, t, p) {
  const px = ctx.kit('pixel'), S = px.begin(ctx);          // Screen (index buffer) at ctx.w x ctx.h, cleared to ink
  px.worlds.overworld(S, t, {camX: t * 20});               // or px.dungeon.wall/floor/torch..., px.chamber(S, t, {...})
  const car = px.productSprite(ctx, ctx.asset('car').cutout || ctx.asset('car'), {w: 120, h: 68, t, fit: 'contain', outline: 'ink'});
  S.blit(car, 180, 120);
  S.blit(px.heroFrames('knight').win0, 100, 140, {flip: true});
  px.ui.dialog(S, 20, 200, 440, 50, 'The road is yours.', {t, t0: 0.5, say: (s, x, y, o) => px.say(ctx, S, s, x, y, o)});
  px.end(ctx, S);                                           // present to ctx.g (palette-locked)
}
```
- **Drawing** (`Screen`): `fill rect frame px line ellipse ring poly vbands dither blit(sprite,x,y,{flip,remap,solid,alpha,scale}) remap glow light(lights, levels) shift clip`. Colours are palette tokens only (`ink night navy royal blue sky ice white plumdk plum violet lilac rose forestdk forest green lime tealdk teal browndk brown tan peach cream gold amber maroon red coral greydk grey silver`); unknown names throw.
- **Sprites**: `Sprite.rows(rows, {char: token})`, `.outlined() .flipX() .rot90() .recolor() .solid() .scaled(k) .bounds()`.
- **Palette**: `PALETTE, RAMPS, REMAP` (`fade[0..4] white red grey night gold petal warm warm2 ember dusk lighter bloomA bloomB`), `quantize(rgba,w,h,{palette,dither})`.
- **Text**: `px.say(ctx, S, str, x, y, {font: 'mono'|'caps'|'tiny', scale, color|bands, outline, outline2, shadow:[dx,dy,c], highlight, align, chars})` (draws + registers QA), `measure wrap fit typed typedBlips`. Fonts: mono 11 px (body/code, 7 px advance), caps 8 px (menus, numbers), tiny 8 px (labels). Scale ≥ 2 only for re-detailed titles (`px.ui.title`).
- **Art**: `heroFrames(id)` → cels idle0/1 walk0-3 ready windup strike hurt win0/1 cast0/1 (32×36, foot anchor `HERO_ANCHOR` (16,35), face right); `walkCel idleCel`; heroes knight, mage, rogue · `monster(id, frame)` goo, bat, bones, wisp, mimic, golem, shroom (face left) · `item(id)` potion ether key gem sword shield scroll star crown heart bomb ring coin, `CHEST.closed/open` · `fx`: `EMOTE.bang/question/heart/sweat, puff, sparkle, burst, blade (8-angle spinning blade), slashArc, fade, flash, iris, debris`.
- **Product**: `productSprite(ctx, asset, {w,h,t,palette,dither,pop,fit,outline})`, `bossFrame(S, sprite, x, y, pw, ph, {name, level, hp, hpLag, t, gold, lair, say})`, `pickOrigin(aspect, params, safe)`.
- **Backgrounds**: `dungeon.wall/floor/torch/torchLights/DUNGEON_LEVELS/banner/chain/bones/bossDoor`, `chamber(S, t, {floorY, braziers, glow})`, `worlds.overworld/nightSky/castle/peaks/cloud/pine/stars/moon`.
- **UI**: `ui.win dialog menu bar damageNumber title ribbon cursorBob CURSOR COIN HEART CHECK`, `panels.questLog tally pressStart codeWindow wrapCode pictureWindow`.
- **Motion**: `motion.step(t,15)` (on twos), `seg stepSeg ease keys hop shakeAt hitstop flicker blink rand hash32`.
- **Camera** (hi-res surfaces): `px.game(ctx)` → world Screen, `px.uiScreen(ctx)` → UI Screen, `px.end(ctx, S, {ui, cam})` presents both; `px.camera.camAt(t, keys, ease)` keyframed `{zoom, x, y}` (zoom stepped on twos), `frameCam`, `punch(t, hits, amp, dur)`; `px.pixelScale(ctx)` = output px per game px.
- **Sound**: `cue(t, intent)` → `{t, sfx, gain_db}`, `txCue(u, intent)` for transitions; intents `blip emote footstep menu_open menu_move menu_select buy slash throw hit damage door_rumble chains door_open boss_appear coin item_get level_up power_up press_start tick whoosh error stamp encounter petal_burst bloom_whoosh` (`SFX` maps them to sfx.json names — footstep, sword_slash, blade_spin, damage, door_rumble, chain_break, buy, menu_confirm, menu_move, petal_burst, switch_whoosh are dedicated sounds; `MISSING_SFX` lists stand-ins).

## Rules the kit follows (keep them in custom pixel scenes)
One pixel size (no fractional positions, no smooth scaling, no rotation of pixel art except exact 90°) ·
palette tokens only · 1-bit text from the glyph tables · motion steps on twos, eases quantised · hit-stop on impacts ·
one big effect per beat · product visible and readable · real data verbatim.

Assets: glyph tables in `core/glyphs.js` are baked by `tools/bake_glyphs.py` from Departure Mono, Press Start 2P and
Silkscreen (OFL-1.1, licences in `fonts/`); all sprites, tiles and the Dusk 32 palette are original (CC0).
