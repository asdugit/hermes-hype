# Pixel kit — proven recipes (copy these numbers)

Every recipe below is a shot from the hand-directed **Red Car hero film** (`hero/build_hero.py` in the dev workspace, not shipped
→ `hero.json` / `hero_916.json`, rendered to `previews/video/hero_16x9.mp4` / `hero_9x16.mp4`) and was checked
frame by frame (critique log: `hero/CRITIQUE.md`). Times are film seconds unless marked *shot-local*.

## 0. Ground rules that made it look right
- **Render pixel hero shots at the film size** (`"res": [1920, 1080]` or `[1080, 1920]`): the kit then owns the
  upscale and a real camera (8–12 px close-ups, 4 px wide), and the UI stays at 4 px on its own layer. At
  `res: [480, 270]` the camera can only crop by whole ×2 steps.
- Heroes must be ≥ 20 % of the frame height while they are the subject → `dungeon-walk` `zoom: 2.5` (the default).
- One big effect per beat: rev → windup → blade → hits → menu → click. Don't stack captions over the action.
- Let the transitions make the sound (battle-swirl and petal-bloom emit their own cues); film cues only for
  things the scenes don't know about.

## 1. "Locked boss" walk (6.9 s)
```json
{"id": "walk", "t0": 0, "t1": 6.9, "scene": "kit:pixel/dungeon-walk", "res": [1920, 1080],
 "params": {"door_label": "LOCKED BOSS", "zoom": 2.5}}
```
- What you get: 0–3.6 s follow cam on the party (lantern glow, footsteps every 0.25 s), 3.6–4.9 s pull back to reveal
  the sealed door + plaque, rumble at `open_at` (dur − 2.0), chains snap with a 2-frame flash + shake, door swings
  open on red fog and glowing eyes, the camera dives into the doorway for the swirl.
- 9:16: identical params with `res: [1080, 1920]` (same zoom; the party is framed mid-frame, the vault has chains).

## 2. Encounter swirl (0.7 s)
```json
{"from": "walk", "to": "boss", "type": "kit:pixel/battle-swirl", "t": 6.4, "dur": 0.7}
```
Start it 0.5 s before the walk ends (while the camera dives into the doorway). Cues: glitch at u=0, whoosh at 0.3.

## 3. The product is the boss (13.2 s)
```json
{"id": "boss", "t0": 6.4, "t1": 19.6, "scene": "kit:pixel/boss-battle", "res": [1920, 1080],
 "params": {"boss_media": "car", "boss_name": "RED CAR", "boss_level": "99", "pick": "BUY",
            "pick_text": "Make it yours.", "timings": {"click": 11.4}}}
```
- Beat map (shot-local): 0.5 boss drops in (impact) · 0.8–2.7 "RED CAR blocks the way!" · ~2.6 rev (power_up) ·
  3.5 SPINNING BLADE thrown (blade_spin) on a screen-wide arc · 3.9 / 4.2 / 4.6 hits on the party with hit-stop,
  camera punch, damage numbers 48 / 52 / 61 (hit + damage) · 6.0 menu opens (pop) · cursor walks
  FIGHT→ITEM→RUN→BUY (menu_move, the hesitation shows "Try to escape." on RUN) · 11.4 click (menu_confirm + buy) ·
  prize push-in on the car.
- `name` ≤ 10 chars caps, `level` "99" (it is the final boss), `pick_text` ≤ 4 words: it's the sell line.
- Use a cut-out (`car_alpha/`) — the boss then floats in the lair with turning rays instead of a framed photo.

## 4. BUY → petal bloom into the next world (1.5 s)
```json
{"from": "boss", "to": "open", "type": "kit:pixel/petal-bloom", "t": 18.1, "dur": 1.5,
 "params": {"origin": [0.108, 0.815]}}
```
- `t` = boss `t0` + `timings.click` + 0.3 (the click must read). `origin` = the BUY row: `[0.108, 0.815]` 16:9,
  `[0.215, 0.19]` 9:16 (default safe area/menu; else `px.pickOrigin`).
- Music: `{"bed": "pixel_boss", "t0": 0, "t1": T}`, `{"sting": "bloom_riser", "t": T}`, `{"bed": "dream", "t0": T, ...}`
  with **T = bloom t + 0.5** (the riser builds under the cursor's walk to BUY, its impact lands as the field resolves).

## 5. Timing that worked (the whole Act 1, 19.6 s)
| t | beat |
|---|---|
| 0.0 | fade in on the party walking (follow cam, zoom 2.5) |
| 3.6–4.9 | pull back: door + LOCKED BOSS plaque |
| 4.9 / 5.35 | rumble / chains snap |
| 6.4 | battle-swirl (0.7 s) |
| 6.9 | RED CAR drops in, intro text |
| ~9 / 9.9 | rev / blade thrown |
| 10.3–11.0 | three hits, damage numbers |
| 12.4 | menu |
| 17.8 | BUY clicked |
| 18.1 | petal bloom (sting impact 18.6) |

## Pitfalls seen in review
- A white overlay in a transition over a dark dungeon reads as a "grey wash" — use additive flashes, then black.
- `difference` flashes invert a dark frame into a pale cream frame: same wash. Don't.
- Damage numbers and the name plate can collide on 9:16 when the camera whips to the party; keep the boss name short.
- Captions over the walk hide the party: the dungeon-walk caption sits in the top band on the UI layer, keep it ≤ 30 chars.
