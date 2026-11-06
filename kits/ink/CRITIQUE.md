# Ink kit — critique log

Reviewed with vision against the approved style frames (`styleframes/ink/frame_a|b|v.png`) as keyframes rendered
through the real runtime (`showreel_core.film.preview`, `w3-harness/gallery.py`) and as Quick films
(`w3-harness/quick_sample.py`). Notes are written straight after each look.

## Round 1 — story pages, 16:9 (gallery `ink1`: TITLE, PROBLEM, PLAN, STATS, CALLOUT, END, END speedrun)
- Overall: the look already reads as frame A/B — warm mottled paper, seeded rough outlines offset from the fills,
  flat offset shadows, peach backdrop discs, the cast is recognisable (glasses + teal sweater, cream screen-face robot).
- **Font shorthand bug:** every class using `font: ... var(--ik-*)` rendered in the fallback face at ~16 px (note
  numbers "01", the kicker "STEP 4 OF 6", the END credit, URL). QA flagged the note numbers at 16.4 px. Fix: longhand
  font properties everywhere in theme.css.
- **PLAN:** very close to frame B — notes slap on, teal ticks, terracotta double loop around the active note, the
  presenter's telescoping pointer lands inside the loop, robot perched on the board. Only the number labels (bug above).
- **PROBLEM:** the bubble is fixed-height, so a 200-char prompt fills only its top half; the user bust sits too low
  (chin near the frame edge), the "you" note and THE ASK kicker sit outside the safe area (QA). Fix: bubble height
  from the measured line count, bust raised, labels inside the safe area, smaller camera push.
- **STATS:** painted numerals + swashes + underlines read well; the robot on the hero number is small; the centred
  peach disc behind the middle stat looks arbitrary.
- **CALLOUT:** clean; the bubble is roomy for a 9-word quote — fine. Underline lands on "undo." as intended.
- **END:** good lockup; the film strip under the title reads as the motif; credit/URL too small (font bug).

## Round 2 — all 15 types, 16:9 (gallery `ink2`)
- All 15 types render with 0 scene/page errors; cues cover type/appear/move/click/pass/fail/hit.
- **Good:** TITLE (reads as frame A), PLAN (frame B), TERMINAL (machine + flag robot + PASS seal), SCREEN (taped
  capture, marker loop on the table, luggage tag), BEFORE_AFTER (both variants: cross on the before, arrow, teal tick),
  CALLOUT, END, END speedrun (PB sticky note), SCROLL (scrollbar thumb + "scroll" note).
- **MONTAGE broken:** cards tiny on one line in the top third, args unreadable, robot drifting at the right edge.
  Cause: the camera clamp kept the view inside a W-wide sheet, so the pan never moved while the robot followed the
  unclamped target. Fix: `P.bounds()` grows the paper; two clotheslines, 540x330 cards, 54 px tool / 30 px args.
- **HOOK:** label clipped at the top-left (outside safe), robot cut at the corner, camera too tight (1.08). Fix: left
  column = label + robot inside the safe area, shot on the right, camera 1.05 -> 1.0.
- **HOOK terminal / TERMINAL:** the machine was a fixed 780 px tall, so 2-4 output lines left a big empty screen.
  Fix: machine height follows the rows. Seal said PASS for any exit 0 — now PASS only with tests_passed, else "exit 0".
- **CODE / DIFF:** the focus push cropped the gutter/left margin. Fix: the push keeps the pad's left edge in view.
- **STATS:** centred disc looked arbitrary -> disc now sits behind the hero number.

## Round 3 — all 15 types, 9:16 (gallery `ink3`)
- **Good:** TITLE (illustration in the lower half, title block on top), PROBLEM, PLAN (= frame V: 2 columns, bust
  pointing up through the column gap), STATS (stacked), CALLOUT, BEFORE_AFTER (stacked, arrow down), SCROLL.
- **END:** the CTA tag collides with the credit line; URL drops into the bottom UI zone. Fix: re-stacked column.
- **FEATURE:** the push centres between box and note but zooms too far: the note leaves the frame. Fix: zoom to the
  union of the box and the note.
- **SCREEN:** min zoom 1.4 crops a wide bbox off both sides in portrait. Fix: portrait zoom fits the bbox width.
- **MONTAGE:** cards cut at the left, robot overlaps the lower card row. Fix: camera centres the current card, robot
  walks in the bottom band.
- **HOOK / DIFF / TERMINAL:** content sits in the top half with empty paper below. Fix: centre vertically, push in.
- **TITLE:** "your agent" note runs off the right edge — dropped in portrait (the "you" note stays).

## Round 4 — determinism (stylekit dry run, both aspects)
- 16:9 dry run flagged `end_speedrun` as NOT deterministic (max diff 3, 0.2 % of pixels). Reproduced with
  `w3-harness/ink_det2.py` (purge + seek t vs seek other -> seek t0 -> seek t): the diff was the CTA luggage tag
  (END had the same latent diff; the dry run's seek order just missed it). Ruled out: the PB note, the tag rotation,
  text-overflow, the camera roll, mix-blend-mode. Fixed by drawing the tag's string inside its SVG box (no SVG
  overflow to the left) and revealing the CTA with a clip write-on instead of a transform/opacity entrance.
  Kept from the hunt: no camera roll (translation drift only), no blend modes (textures are alpha-only).
- After the fix: 0 non-deterministic shots in 16:9 and 9:16.
