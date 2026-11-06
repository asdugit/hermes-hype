# kit:terminal — critique log (written right after each look)

Reference: the approved style frames `styleframes/terminal/frame_a|b|v.png` (P3 amber, Plex Mono grid, VT323 display,
box-drawn panes, odometer drums, CRT post). Keyframes are rendered through the real runtime
(`showreel_core.film.preview`, harness `w3-harness/gallery.py`) and looked at with vision right after each render.

## Round 1 — all 15 types, 16:9, 960x540 keyframes (2 per shot)
Renders clean: 0 scene errors, 0 page errors; cues: appear, click, cut, fail, hit, move, pass, type.
- TITLE: reads like frame A (boot log top-left, huge block-letter FOCUSFOX with the ░ shadow, VT323 tagline, `$ █`,
  inverse status tag bottom-left). QA flags the logo █ rows at 20 px as small_text (decorative) -> logo >= 22 px.
- TERMINAL: frame B grammar works (typed command, output, inverse PASS, odometer strip 14 / 0.41 with ghost digits).
  Pane was narrow (inner = content width) -> min inner 46 cols (frame B used 52). Bar right empty when no label.
- HOOK (image): ASCII plate at 0.75 s, real capture at 2.25 s inside a pane titled with the page title + URL. Good.
  HOOK (terminal): pane too small for a hero -> bigger grid font for terminal heroes.
- PROBLEM / PLAN / MONTAGE / DIFF: correct grammar (typed prompt with `typing` spinner -> `sent`; boot-log plan with
  OK / RUN / WAIT; session.log with newest line inverse; diff with struck deletions and hot additions).
- CODE: the zoom step at the end mis-places the pane (text runs off the left/right) -> check the zoom maths.
- SCREEN / FEATURE: zoom up to 2.6x overflows the tube completely (no pane edge left) -> cap at ~2.0x.
- STATS: drums mid-roll show plausible intermediate values (12, 38) then settle 14 / 5 / 47 min. Good.
- BEFORE_AFTER (terminal): panes small and short; (image) two panes side by side work, before dims.
- CALLOUT: hot `# comment`, cursor, `#   — agent`; a little small for the longest hold.
- END: `$ exit` -> logout -> logo -> `$ npx serve focusfox` + URL + credit; speedrun shows `PB 47:23`.
- SCROLL: first screen resolves, then pages down; block scrollbar on the pane edge visible.

## Round 2 — fixes + first production-path look (1920x1080 keyframes -> ffmpeg CRT chain of the style frames)
Fixed after round 1: zoomed panes are clipped to the content rows (CODE / SCREEN / FEATURE no longer run under
the status line); zoom caps 1.3x (CODE) and 2.0x (SCREEN/FEATURE); the ASCII/dither plates auto-invert light UIs
(the ink lights up, not the paper) with a chroma boost and a percentile contrast stretch -> the Focusfox timer ring
now reads in ASCII; the real plate is multiplied warm (#F2DEC4) so white pages sit in the amber glass instead of
blasting; 16:9 bottom margin 124 (runtime safe b=120).
Look (TITLE, DIFF, TERMINAL pass, MONTAGE, END, END speedrun, HOOK term, PLAN after post):
- TITLE / END / END speedrun: on par with frame A (rich halation on the block logo, curvature + black corners,
  boot log as texture, clear logo -> tagline -> prompt hierarchy). Logo ran to the curvature zone -> cap at 84 % W.
- TERMINAL pass: frame B grammar, PASS block + drums 14 / 0.41 with ghost digits; good.
- PLAN: boot-log rows at 40 px read well; RUN spinner block is the one lit thing; pane total said 3/5 while the
  status line said 3/6 -> both count the hidden items now.
- MONTAGE: session.log with times / tools / args reads as a real log; good.
- DIFF: text too small (pane sized to the single longest line) -> size to the 90th-percentile line, ellipsis the rest
  (same for CODE).
- HOOK terminal: pane had empty rows under PASS (rows reserved for a final prompt it never shows) -> trimmed.
- 9:16 (late keyframe per shot): layouts hold inside the 120..960 x 232..1500 band; CODE/DIFF are small (22 px, long
  lines) and the lower band is sparse on short content -> acceptable, revisit after blueprint.
