# Ink kit — recipes (Directed films and Quick tuning)

Short, tested patterns. All scenes are `kit:ink/<TYPE>`; params as in KIT.md. Shot lengths: 3–5 s per scene
(beats scale with the shot); END ≥ 3.5 s so the lockup holds (its last frame is the thumbnail).

## 1. The classic 30 s explainer arc
`HOOK` (2.5 s, product capture taped + label) → `TITLE` (3.5 s) → `PROBLEM` (3.5 s) → `PLAN` (3.5 s) →
`CODE` or `DIFF` (3.5 s) → `TERMINAL` with `tests_passed: true` (3 s) → `FEATURE` (3.5 s) → `STATS` (3 s, on the
music drop) → `END` (4 s). Transitions: `push` (paper-slide) between pages inside an act, `wipe` (ink-bleed) once or
twice at act changes (into PLAN and into FEATURE), `cut` on hard downbeats.

## 2. Land beats on the music
- TERMINAL: pass `_sync: {pass: s}` (shot-local seconds) and the PASS seal + chime + the robot's flag land there.
- FEATURE: `_sync: {click: s}` lands the cursor press, ink ripple and the marker loop.
- STATS lands its first number at ~0.25 × (shot/4 s): start the shot one beat before the drop.

## 3. Product first
- SCREEN with a real `bbox` pushes 1.4–1.9× and loops the region; a wide/default bbox means "no focus" (gentle
  push, no loop). FEATURE uses `feature` for the sticky note text (≤ 6 words).
- HOOK `hero.kind: image` is the strongest opener; `terminal` (green run) is the fallback for CLI products.
- BEFORE_AFTER takes two content blocks: a red→green test run reads as build proof; two captures read as the product
  change (the before is desaturated and crossed out).

## 4. Transitions in film.json
```json
{"from": "plan", "to": "code", "type": "kit:ink/paper-slide", "t": 10.2, "dur": 0.6, "params": {"dir": "left"}}
{"from": "title", "to": "problem", "type": "kit:ink/ink-bleed", "t": 6.4, "dur": 0.7, "params": {"x": 0.3, "y": 0.6}}
```
Put the ink-bleed origin on the outgoing scene's focal point (the robot, the active note) so the blot grows from it.

## 5. Vertical (9:16)
Every scene re-lays out natively: titles and notes sit in the top/centre band, the cast moves into the bottom
420 px UI zone (no text there), the corkboard reflows to 2 columns, BEFORE_AFTER stacks vertically with the arrow
pointing down. Captions stay legible over the paper (Inter 44 px on a cream chip, kit.json `caption_style`).

## 6. Don'ts
- Don't feed long prose into CALLOUT (≤ 12 words reads best; it clips at 160 chars) or PROBLEM (clips at 240).
- Don't stack two ink-bleeds back to back; the motif loses its weight. One per act change.
- Don't put the ink kit next to CRT/terminal shots in mixed films: its post chain is grain only.
