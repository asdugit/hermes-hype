# kit:blueprint — critique log (written right after each look)

Reference: the approved style frames `styleframes/blueprint/frame_a|b|v.png` (cyanotype sheet, zoned border, title
block, white object lines, cyan dimensions/leaders, redline only for revisions, Space Grotesk + IBM Plex Mono).
Keyframes through the real runtime (`showreel_core.film.preview`, harness `w3-harness/gallery.py`), vision right after.

## Round 1 — all 15 types, 16:9, 960x540 keyframes (2 per shot)
Renders clean: 0 scene errors, 0 page errors; cues: appear, build, click, cut, hit, move, pass, type.
- HOOK (image): the pen-traced line art of the capture inside the dimensioned frame (1440 px / 900 px) reads as a
  drawing at 0.75 s; the real capture has developed by 2.25 s. Strong. HOOK (terminal): listing too small, sparse.
- TITLE: big lettered FOCUSFOX + tagline + rule; the exploded plate stack is small, crowded against the title block,
  and only balloon 1 had landed by 85 % of the shot (planned too late). Kick overlaps the title box (QA overlap).
- PROBLEM: REQUIREMENT box with the prompt typed in Plex Mono, TO BE DESIGNED part outline + leader. Good.
- PLAN: correct grammar (balloons, DONE checks, IN PROGRESS dashed, arrows on a centre line) but boxes and type are
  small for 1080p and the pending box outline (cyan construction) vanishes on the grid.
- CODE: annotated listing + L19–25 dimension + notes; the detail push cuts the listing's left edge.
- DIFF: closest to frame B: struck deletion in redline, cloud on row boundaries, delta B, rev table A/B, WAS/NOW
  notes on dog-leg leaders, +4 / −1 dimension. Notes show raw code fragments (verbatim, so acceptable).
- TERMINAL: run listing + gauge drawing (dial, ticks, needle on 100 %, TESTS PASSING, readouts) + PASS stamp. The
  listing is tiny for a 2-line output and floats at the top.
- MONTAGE: detail circles with line-art parts per tool kind + ballooned parts list: one of the best scenes.
- SCREEN: frame -> trace -> develop -> DETAIL C circle -> detail zoom works. FEATURE: zoom (2.8x) crops the callout
  box and the DETAIL C label off-frame.
- STATS: numerals count with units and labels, dimension arrows extend; plain but clean; numbers could be bigger.
- BEFORE_AFTER: image version (REV A / REV B + cloud + delta) good; terminal version small.
- CALLOUT / END / END speedrun: good; the end title block + signature + RELEASED stamp land.
- SCROLL: page column develops then the camera pans down the elevation with the A section line.

## Round 2 — fixes after the 1920x1080 look at TITLE, PLAN, DIFF, TERMINAL, STATS, FEATURE
- TITLE: plates 30 % bigger, re-centred in the right half (axis at 1010,800, -16 deg), planned to finish by ~1.5 s;
  title moved 12 px down (kick overlap).
- PLAN: boxes up to 330 x 250, 30 px lettering; pending boxes in hidden-line weight (white dashed) so they read.
- TERMINAL: 28 px listing vertically centred on the gauge.
- CODE: the detail push keeps the listing's left edge in frame.
- SCREEN / FEATURE: the detail zoom frames the union of the detail circle, its DETAIL C label and the FEATURE callout
  (zoom = fit, 1.15x..2.8x) instead of the circle alone.
- STATS: numerals 190-240 px.

## Round 3 — 1920x1080 TITLE, PLAN, CODE, TERMINAL, HOOK (terminal), SCREEN, STATS, FEATURE; all 15 types at 9:16
- TITLE: the plate stack now carries three balloons (NAME / PURPOSE / TAGLINE with the verbatim strings) in the
  right half and lands by ~1.5 s; reads as a general-arrangement sheet next to frame A.
- PLAN: boxes and 30 px lettering read at 1080p; DONE checks, IN PROGRESS dashed box, pending dashed white; good.
- CODE: the detail push keeps the gutter and focus lines in frame; notes + L19–25 dimension visible.
- TERMINAL: listing centred on the gauge; gauge + PASS stamp + readouts balanced.
- FEATURE: callout text over the white capture was illegible -> callout moved to the sheet beside the view (right
  column / below on 9:16) on a dark plate; DETAIL C label on a plate. Now legible; the zoom frames circle + callout.
- HOOK (terminal): listing at 34 px, centred; sparse but clean.
- 9:16: every type stays inside the border; the TITLE plate labels ran off the right edge -> labels in a column at
  x 620 with leaders from each plate. SCREEN's detail zoom crops the capture's left edge on 9:16 (acceptable: it is
  a detail view).
