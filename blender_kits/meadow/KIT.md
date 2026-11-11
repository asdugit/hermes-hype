# blender_kits/meadow — anime flower meadow (Blender)

Scenes run inside Blender (`blender:<kit>/<scene>` shots, see BLENDER.md). Library: `blender_kits/lib/`
(`camera`, `flyers`, `world`, `meadow`, `figure`, `petals`, `look`, `nodes`).

## Scenes

### `blender:meadow/oner`
One continuous camera move (no cuts) through an anime sunset meadow: a lone figure (white sundress, straw hat with a
red ribbon) stands mid-meadow; six copies of the product car fly around her, never in formation —
`dive` (from the upper left, banks across in front of her against the sun, exits up-right), `climb` (rises from
behind the right hill), `drive` (drives over the hill crest toward camera-left, lifts off and flies over the
camera), `hero` (floats in, hovers with wheels spinning, settles into the close-up spot turning slowly), `pass`
(passes ~4.7 m from the lens, her head follows it), `arc` (far arc across the sky, out of focus). The camera starts
low behind her (backlit by the sun), dollies in, cranes and arcs around her left side to a three-quarter front, then
pushes past her to a hero close-up of the hovering car (light sweep across the paint, rims spinning).

| param | type | default | doc |
|---|---|---|---|
| `time_of_day` | enum sunset/golden/dawn | sunset | sky palette |
| `t_offset` | float | 0 | start this many seconds into the move (continuation after a reveal shot) |
| `density` | float | 1.0 | meadow density multiplier (preview tier uses x0.55) |
| `figure` | bool | true | the lone figure |
| `petals` | float | 1.0 | ambient petals amount |
| `hero_at` | float | 19.5 | move time when the camera arrives at the hero close-up |
| `length` | float | 25.4 | designed length of the whole move; keep `t_offset + shot dur <= length` |
| `reveal` | bool | false | open focused on an image plane 1 m from the lens (set by `transitions/petal_reveal`) |
| `product` | asset | (film product) | a 3D model asset (`"type": "model"`, .blend/.glb); wheels = children named `wheel*` |

Cues (shot-local): `whoosh_long`/`whoosh_short` at each car's closest approach to the camera (gain by distance),
`chime` 0.4 s before the hero arrival.

Timing anchors (move time): dive 0.6-7.2, climb 3.6-10.8, drive 3.4-12.6 (lift-off 8.0), hero floats in from 7.8
and settles at `hero_at - 0.6`, pass 10.6-15.6 (closest ~11.8), arc 13-26; rack focus figure -> drive (5.4) ->
figure (9.0) -> pass (12.1) -> figure (13.5) -> hero (16.2). Head follow: dive (0-3.5), pass (11.2-15.2), hero.

Aspects: 16:9 and 9:16 have separate framing — portrait sits the camera 12 % further back on a wider lens, frames
the hero close-up taller, and squeezes every flight path toward the camera axis (x0.62 lateral, x1.12 vertical) so
cars stay in the narrow frame.

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
