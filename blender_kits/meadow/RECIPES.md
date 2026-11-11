# blender_kits/meadow — recipes

## Hero film v2: pixel boss -> petal reveal -> "heaven of red cars" oner -> lockup (43.5 s)
Built by `hero/v2/build_hero_v2.py` (16:9 + 9:16 film.json). Timeline (film seconds):

| span | shot | notes |
|---|---|---|
| 0-6.9 | `kit:pixel/dungeon-walk` | party walks to the LOCKED BOSS door; battle-swirl at 6.4 |
| 6.4-18.1 | `kit:pixel/boss-battle` | `boss_media` = the 3D car's own studio loop (`car.mp4` + `car_alpha/`), BUY clicked at 17.8 |
| 18.1-19.9 | `blender:transitions/petal_reveal` | `from_shot: boss`, `origin` = the BUY row (u, v), `start 0.1`, `spread 0.95`, `under_params` = the oner's params + `reveal: true` |
| 19.9-43.5 | `blender:meadow/oner` | same params + `t_offset` = reveal length (1.8) so the camera never stops; `hero_at 19.5`, `crowd 1.0` |
| 38.7-43.5 | overlay `kit:cinematic/lockup` | RED CAR / Beauty, unlocked. / MAKE IT YOURS, lands on the dream bed's end hit |

Music: `pixel_boss` bed -> `bloom_riser` sting at the petal burst (18.6) -> `dream` bed. SFX: `switch_whoosh` at the
cut into the reveal, `petal_burst` (reveal cue), whooshes at each named car's closest pass (oner cues), `chime` +
`pop` on the lockup.

Render (dev, with the machine locks): `python hero/v2/render_v2.py hero/v2/hero_v2.json OUT.mp4 --tier final
--job DIR` (Blender pass -> browser pass -> audio -> mux). Keyframes first: `--keyframes 18.15,18.6,19.3,25,39.5`.

## Tuning the oner without rendering
`python hero/v2/dev/frameqa.py 16:9 0 25.4 --every 0.5` prints per half-second: the figure's height/position, how
many cars are on screen (groups/streams), each named car's width % with flags (C = cut by the edge, F = fast, H =
behind the terrain), plus camera smoothness, flyer validation (never dying, no ground clipping, >= 2.8 m from the
lens, >= 4 m from her head) and the readable-car share. Iterate there; render 10-14 keyframes to judge looks and a
480x270 motion test (`mkjob.py ... res=480x270`) to judge motion with 8-frame strips.

## Pitfalls
- Key visibility (root scale) every frame: a two-key ramp with LINEAR extrapolation runs negative -> giant cars.
- Screen anchors are evaluated on the aim-free move; keep aim weights partial (<= 0.6) or anchored cars drift out.
- Screen-anchored keys give uneven world speeds while the camera cranes/rotates: `_fla` retimes keys toward
  constant speed (`even`); formation members may only peel forward/sideways (falling back reads as stalling).
- Backlit cars go black against the sunset: keep the shadowless fill sun from the camera side.
- Large lupine spikes as foreground blossoms read as purple cones at a low camera; fg uses round blossoms only.
