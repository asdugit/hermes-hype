# Nature kit — proven recipes (copy these numbers)

Every recipe is a shot of the hand-directed **Red Car hero film** Act 2 (`hero/build_hero.py` in the dev workspace, not shipped
→ `hero.json` / `hero_916.json`; videos `previews/video/hero_16x9.mp4`, `hero_9x16.mp4`; critique log
`hero/CRITIQUE.md`). Shot times below are film seconds; flyer `t0/t1` are **shot-local seconds**. All shots use
`"time": "sunset"`, the car asset `{"type": "frames", "src": "car.mp4", "cutout": "car_alpha/"}`, and a distinct
`variant` per shot (different clouds/flowers so cuts don't look like the same plate).

## 0. Rules the review taught us
- **Never a formation.** Each flyer gets its own path, depth, start time, duration and size. The user's four:
  one **descends**, one **rises**, one **drives down the slope**, one **floats** with its wheels spinning.
- **Vary the pose.** Paths give each car a different attitude (nose-down descend, banked arc, nose-up rise, turning
  float, slope-pitched drive); `clipOffset` / `clipRate` pick different frames of the clip so wheels never sync.
- **One car in focus at a time**, and pull focus between them with `rack` (the eye follows the rack).
- **Move the camera** every shot (`crane-dolly`, `sweep`, `push`, `tilt-down`) — static plates look pasted.
- **Give the product a close moment**: the `pass` path (whips past ~4 m from the lens) and a showcase float at 12 m.
- 9:16 needs its own flyer x/y (the kit has portrait slots; override them when you place cars by hand).

## 1. Open: crane-dolly over the meadow, the four motions (6.5 s, film 18.1–24.6)
```json
{"id": "open", "scene": "kit:nature/flower-field",
 "params": {"time": "sunset", "camera": "crane-dolly", "cameraAmount": 1.0, "variant": "hero-a",
  "rack": [[0, 0], [3.4, 0], [4.6, 3]],
  "flyers": [
   {"media": "car", "path": "descend", "t0": 0.0, "t1": 3.0, "size": 5.2, "d": 17, "x0": -0.78, "x1": -0.38, "y0": 1.25, "y1": 0.18},
   {"media": "car", "path": "rise", "t0": 1.6, "t1": 6.5, "size": 6.0, "d": 58, "x0": 0.30, "x1": 0.06, "y0": -0.35, "y1": 1.45},
   {"media": "car", "path": "drive-slope", "t0": 0.4, "t1": 6.3, "size": 5.0},
   {"media": "car", "path": "float", "t0": 1.0, "t1": 6.5, "size": 5.6, "d": 34, "x0": 0.36, "x1": 0.44, "y0": 0.40, "y1": 0.46}]}}
```
9:16 slots: descend `d 15, x -0.25→0.05, y 1.2→0.38` · rise `d 56, x 0.45→0.2, y -0.3→1.3` · float
`d 30, x 0.05→0.12, y -0.12→-0.06` (drive-slope uses the portrait slope automatically).
Enters straight out of the petal-bloom; the hero car drops in first (in focus), focus racks to the float car at 4.6 s.

## 2. Sky: tilt down from the clouds (4.4 s, film 24.0–28.4)
```json
{"id": "sky", "scene": "kit:nature/sky-reveal",
 "params": {"time": "sunset", "cameraAmount": 0.5, "variant": "hero-s", "rack": [[0, 0], [1.6, 0], [2.8, 2]],
  "flyers": [
   {"media": "car", "path": "cross", "t0": 0.0, "t1": 2.8, "size": 5.6, "clipOffset": 1.9, "d": 26, "x0": 1.05, "x1": -1.45, "y0": 1.6, "y1": 1.35},
   {"media": "car", "path": "arc", "t0": 0.2, "t1": 4.4, "size": 6.2, "d": 46, "x0": -1.45, "x1": 1.45, "y0": 0.85, "y1": 0.55, "apex": 0.35},
   {"media": "car", "path": "descend", "t0": 1.0, "t1": 4.4, "size": 5.4, "d": 22, "x0": 0.55, "x1": 0.35, "y0": 1.7, "y1": 0.35}]}}
```
- A car must be in frame from frame 1 (the cross); spread heights so they never line up as a convoy.
- `cameraAmount` ≤ 0.5: a stronger tilt drags the painterly clouds into smeared veins.
- 9:16: cross `y 1.0→0.8, d 24` · arc `y 0.35→0.15, apex 0.25, d 44` · descend `y 1.4→-0.1, d 22`.
- Cut in with a 0.6 s crossfade. Wake defaults are lower on vertical/ground movers (descend/rise 0.6, drive-slope 0.4): a full wake reads as dotted rain.

## 3. Pass-by: sweep + the car whips past the lens (4.8 s, film 28.0–32.8)
```json
{"id": "pass", "scene": "kit:nature/flower-field",
 "params": {"time": "sunset", "camera": "sweep", "cameraAmount": 0.9, "variant": "hero-b",
  "rack": [[0, 2], [0.8, 2], [2.2, 0], [3.9, 0], [4.7, 2]],
  "flyers": [
   {"media": "car", "path": "pass", "t0": 0.8, "t1": 4.4, "size": 5.0},
   {"media": "car", "path": "arc", "t0": 0.0, "t1": 4.8, "size": 6.5, "clipOffset": 0.7, "d": 85, "x0": -1.4, "x1": 1.4, "y0": 0.45, "y1": 0.5, "apex": 0.35},
   {"media": "car", "path": "float", "t0": 0.0, "t1": 4.8, "size": 6.0, "clipOffset": 2.2, "d": 46, "x0": -0.45, "x1": -0.40, "y0": 0.30, "y1": 0.34}]}}
```
- `pass` is **camera-relative metres** (x0 6.5 → x1 -6, depth 19 → 4.2 m): it approaches out of the sun, grows to
  half the frame and whips off-screen with speed lines + petal wake + motion blur. Focus: hold the float car (2),
  pull to the pass car as it arrives (2.2), back to the float car after it leaves (4.7).
- Cut in with a 0.4 s `whip`; film cue `whoosh_short` at the whip, `whoosh_long` at the closest point (~2.2 s in).
- 9:16 uses the portrait `pass` preset automatically; arc `d 80, y 0.62→0.66, apex 0.25`, float `d 46, x -0.1, y 0.42`.

## 4. Showcase: one car hovers close, wheels spinning (4.6 s, film 32.2–36.8)
```json
{"id": "show", "scene": "kit:nature/flower-field",
 "params": {"time": "sunset", "camera": "push", "cameraAmount": 0.45, "variant": "hero-c", "focusOn": 0,
  "flyers": [
   {"media": "car", "path": "float", "t0": -1.2, "t1": 4.6, "size": 5.4, "clipRate": 1.6, "d": 12, "x0": -0.1, "x1": -0.02, "y0": 0.02, "y1": 0.06},
   {"media": "car", "path": "drive-slope", "t0": 0.0, "t1": 4.6, "size": 5.0, "clipOffset": 1.1},
   {"media": "car", "path": "orbit", "t0": 0.0, "t1": 4.6, "size": 5.8, "d": 50, "x0": -1.1, "x1": 0.95, "y0": 0.62, "y1": 0.58, "ad": 20}]}}
```
`t0: -1.2` = the float car is already in place on the first frame; `clipRate 1.6` spins the wheels faster (readable).

## 5. Hero + lockup (7.3 s, film 36.2–43.5)
```json
{"id": "hero", "scene": "kit:nature/product-hero",
 "params": {"time": "sunset", "product": "car", "title": "top", "cameraAmount": 0.2, "variant": "hero-d", "size": 6.0, "distance": 15}}
```
overlay:
```json
{"id": "lockup", "t0": 38.7, "t1": 43.5, "scene": "kit:cinematic/lockup",
 "params": {"title": "RED CAR", "tagline": "Beauty, unlocked.", "cta": "Make it yours", "at": "upper", "cta_at": "bottom", "accent": "#E8384A"}}
```
- `title: "top"` raises the camera pitch to 13° so the car sits in the lower-middle band between the title block and
  the CTA (`pitch` param overrides). 9:16: `size 5.6, distance 12`.
- Let the car breathe ~2.5 s before the title; the CTA pops at lockup t0 + 1.7 s — time it to the dream bed's end hit
  (a bar line; here 40.42 s) so the music resolves on the call to action.

## Music + SFX (Act 2)
`{"bed": "dream", "t0": <sting impact>, "t1": <film end>}` — 88 bpm, bars of 2.73 s; sections intro/build/drop/outro/end.
Film cues: `whoosh_long` −8 dB when the first car drops in, `whoosh_short` −10 dB on the sky cut, `whoosh_short` −4 dB
on the whip, `whoosh_long` 0 dB at the pass-by, `chime` −4 dB on the title, `pop` −12 dB on the CTA.

## Pitfalls seen in review
- Speed lines invisible: they need DoubleSide quads and must run along the SCREEN velocity (fixed in the kit).
- A car placed in base-camera NDC drifts out with a big camera move — use camera-relative paths (`pass`) or smaller
  `cameraAmount`.
- Speed lines on a car driving through grass get cut into dashes by the blades (they look like road markings):
  `drive-slope` defaults to `streaks: 0` (wake only).
- Crane moves that start below eye height fill the corners with huge blurry blossoms for the first second.
- Lockup over a bright sky needs the plum scrim (default 0.5) — white type on cream clouds disappears.
