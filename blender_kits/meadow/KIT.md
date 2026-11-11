# blender_kits/meadow — anime flower meadow (Blender)

Scenes run inside Blender (`blender:<kit>/<scene>` shots, see BLENDER.md). Library: `blender_kits/lib/`
(`camera`, `flyers`, `world`, `meadow`, `figure`, `petals`, `look`, `nodes`).

## Scenes

### `blender:meadow/oner`
One continuous camera move (no cuts) through an anime sunset meadow — "a heaven of red cars": a lone figure (white
sundress, straw hat with a red ribbon) stands mid-meadow while ~85 linked copies of the product car fill the sky at
every depth, never uniform:
- **named flights near her and the lens** (screen-anchored, so they stay big in both aspects): `dive` (comes down
  from the upper left as the petals clear, banks across in front of her), `drive` (drives down the front-right
  crest, lifts off), `climb` (rises from behind the left hill across the sun), `over` (overtakes the low camera
  from behind, flies over the lens and away), `wing` (circles her; the camera flies alongside it), `cross1`/`cross2`
  (cross close in front of the lens, out of focus, while the focus racks through them to her), `hero` (floats in
  high, hovers with wheels spinning, settles into the close-up spot turning slowly);
- **formations that break apart** (`g0`..`g4`, 5 cars each: loose V, lag, wobble, then peel apart — they only ever
  drift forward/sideways, never fall back);
- **murmuration streams** (`RINGS`, 8 flocks of 7-11 cars circling the meadow at 34-155 m): every car has its own
  radius, altitude, angular speed and orbital phase (`flyers.murmur`), so spacing opens and closes and no flock
  is a level row (altitudes stagger 8-16 m per flock); the six mid-sky crossers `w0..w6` (`flyers.sway`, bowed
  left-to-right paths in their own directions) and each car's `yaw_off` ±10-55° with slow yaw/pitch/roll wander
  mean the flock turns across the view instead of showing identical side profiles (measured: bearings 2-175°,
  sd 42°, only 18 % flat side-on) — 3/4 front and rear views appear naturally.
- car materials get `_car_haze`: an aerial-perspective mix toward the sunset haze by camera distance (from 26 m,
  0.6 at 200 m), so distant cars fade into the air instead of reading as dark maroon; a shadowless camera-side fill
  and a high lavender sky fill keep the paint red with highlights at every depth.
Camera (one C2 spline through beats; smoothness checked): low behind her (big, backlit) -> sweeping crane up and back
(the sky full of cars) -> swoop down into the flowers, low angle under the `over` car -> flight alongside `wing`
around her (she is in the middle) -> settle at her front-left 3/4, `cross1`/`cross2` cross the lens, rack focus to
her and the hero hovering behind her -> push past her left shoulder into the hero close-up (sun-lit paint, light
sweep, top strip highlight, rims spinning).

| param | type | default | doc |
|---|---|---|---|
| `time_of_day` | enum sunset/golden/dawn | sunset | sky palette |
| `t_offset` | float | 0 | start this many seconds into the move (continuation after a reveal shot) |
| `density` | float | 1.0 | meadow density multiplier (preview tier uses x0.55) |
| `figure` | bool | true | the lone figure |
| `petals` | float | 1.0 | ambient petals amount |
| `crowd` | float | 1.0 | how many cars fill the sky (1 = ~85; 0.3 = named flights + a few) |
| `hero_at` | float | 19.5 | move time when the camera arrives at the hero close-up |
| `length` | float | 25.4 | designed length of the whole move; keep `t_offset + shot dur <= length` |
| `reveal` | bool | false | open focused on an image plane 1 m from the lens (set by `transitions/petal_reveal`) |
| `product` | asset | (film product) | a 3D model asset (`"type": "model"`, .blend/.glb); wheels = children named `wheel*` |

Cues (shot-local): `whoosh_long`/`whoosh_short` at each named car's closest approach to the camera (gain by
distance), `chime` 0.4 s before the hero arrival.

Timing (move time): dive 0.5-7.1, drive 1.2-9.0 (lift-off 6.2), climb 3.0-8.6, over 5.0-8.3 (over the lens ~5.9),
wing 6.4-14.9 (tracked 8.4-13.0), cross1 12.4-15.1, cross2 13.4-15.5, hero 9.0 -> settles at `hero_at - 0.6`;
rack focus dive (2.4) -> her (4.6) -> over (6.0) -> wing (7.6) -> cross1 (12.6) -> her (13.7) -> cross2 (14.6) ->
her (15.6) -> hero (16.8). Head follow: dive, over, wing, hero.

Visibility: every car exists only inside a window that opens and closes on frames where it is off-screen
(`Layout.windows`, keyed root scale), so extrapolated approach/exit paths never show as specks or clip the ground.

Framing QA (pure Python, `Layout.framing`): per frame each car's visible box, cut-by-edge, terrain occlusion and the
figure box. Tests require a readable car (>= 12 % of the frame width, inside or a fast pass-by) in > 88 % of frames
after the petals clear, a median of >= 12 cars on screen, and the figure > 40 % of the frame height at the start.

Aspects: 16:9 and 9:16 share the choreography; screen anchors adapt the named flights to each frame, portrait sits
the camera 12 % further back on a wider lens and frames the hero close-up taller.

### `blender:transitions/petal_reveal`
The previous shot's last frame (handoff still, `params.from_shot`) peels into petals from `origin` (e.g. the
clicked BUY row), flips to petal-pink backs and blows toward/past the camera with motion blur, revealing the
`under` scene (default `meadow/oner` with `reveal=true`) whose camera is already moving. Frame 1 equals the still
(nearest-neighbour sampling, grade keyed off until the peel starts). Continue with a `meadow/oner` shot whose
`t_offset` = this shot's duration: the camera never stops.

| param | default | doc |
|---|---|---|
| `from_shot` | "" | shot whose last frame is the still (the host captures it) |
| `under` / `under_params` | meadow/oner / {} | revealed scene + its params |
| `origin` | [0.5, 0.5] | peel origin (u, v from the top-left) |
| `start` / `spread` | 0.12 / 0.95 | first cell lets go at `start`; the wave crosses the frame in `spread` s |
| `cell_px` | 30 | cell size in output pixels |

Cue: `petal_burst` at `start` (+ the under scene's whooshes).

## Rules the library enforces (tests: `tests/blender_kits/meadow`)
- Camera: every channel is a C2 spline in time through beats (no velocity/acceleration pops at beats); aim/focus
  blends use smootherstep windows; `camera.smoothness()` must report ok (no pops, pan <= 3 deg/frame).
- Flyers never "die": no mid-flight slowdown below 35 % of peak, exits keep >= 60 % momentum, no sinking exits,
  no ground clipping (checked from 1 s before entry to 2 s after exit); before t0 / after t1 they keep moving along
  the end tangents. Wheel spin = distance travelled / radius, capped at 0.42 rad/frame so spokes never strobe.
- Determinism: everything from the seed and the frame number (Scene Time in geometry nodes, keyed clocks).
