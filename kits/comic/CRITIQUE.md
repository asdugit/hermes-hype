# kits/comic — critique log (written right after each look at rendered keyframes)

Reference: the approved style frames `styleframes/comic/frame_a|b|v.png` (cover, 3-panel TERMINAL page, 9:16 page).
Renders go through the real runtime (`showreel_core.film.preview`, 960x540 / 540x960 keyframes unless noted).

## Round 1 — story pages, 16:9 (TITLE, PROBLEM, PLAN, STATS, CALLOUT, END)
- TITLE: reads as frame A in motion (masthead, No. 1 box, ribbon, hero on sunburst + magenta halftone, skyline).
  Flaws: NEW ISSUE burst sits on the hero's film reel; "Introducing" strip touches the ribbon (QA overlap);
  masthead glyph tops and the rotated ribbon start poke out of the 16:9 safe area; burst label lines and the
  corner "No."/"1" boxes overlap in QA (separate text blocks at tight leading).
- PROBLEM: close to frame B quality: cyan halftone panel, user bust with magenta rim, verbatim prompt at 42 px in
  the oval balloon, red stressed word, two agent panels (reads it / gets to work, TAK TAK!). Fine.
- PLAN: caption-box checklist reads, but the ink splat behind each check reads as a dirty smudge; the NOW! burst
  covers the previous row's check; the "3 of 6 DONE!" burst sits on the hero's head; the pointing arm is a stub.
- STATS: strong (red splash, yellow rays, three bursts, count-up). Keep.
- CALLOUT: balloon good; speaker silhouette is small and cropped at the panel corner.
- END: lockup too small for a thumbnail, big empty middle, cyan-on-blue halftone reads as noise, TRY IT! burst
  collides with the masthead. Plan: classic back-cover coupon (dashed border, TRY IT TODAY! header) holding the
  CTA + URL; bigger masthead; sparser halftone.

## Round 2 — all 15 types, 16:9 (5 review sheets, 38 keyframes)
- HOOK (image): splash + printed screenshot in a white burst works; the headline column collides with the burst
  ("TOMATO AT A" touches it) and BOOM! hangs off the frame edge. HOOK (terminal): the terminal is small inside a
  huge burst; needs bigger type for 2-3 line outputs.
- TITLE: NEW ISSUE burst still kisses the masthead X and the hero's reel.
- PROBLEM: the opening push crops the MEANWHILE caption (frame it with the balloon).
- PLAN: "3 of 6 DONE!" burst crowds the headline; move it under the list.
- CODE: glide P1 -> editor -> push onto the focus lines reads well; fine.
- DIFF: the establishing frame crops the caption and the +4/-1 burst; establish on the whole panel instead.
- TERMINAL: reads as frame B in motion (typing panel, terminal, PASS!/DONE! splash). The P3 mono caption shows a
  meaningless table row for non-test runs: show the "N passed" line, else the command.
- MONTAGE: row-following camera at zoom 1 leaves 2/3 of the frame as empty paper; tool names/args small.
  Plan: camera frames a 2x2 block around the current tile; bigger lettering.
- SCREEN: LOOK! burst falls outside the push framing; keep it at the ring's top-left inside the focus rect.
- STATS: labels sit under the bursts (z-order) and are too small.
- BEFORE_AFTER: before block small in a big grey page (no push); KRAK! partly under the gutter.
- CALLOUT: camera end key is an explicit [cx, cy, z] that bypassed the page clamp -> paper edge and stage show.
  Balloon is oversized for a short quote (fit the balloon to the text).
- SCROLL: the URL caption is hidden behind the browser frame.

## Round 3 — 16:9 re-check + first 9:16 pass (comic916_r1..r3)
- 16:9 after round-2 fixes: HOOK headline clear of the burst; TERMINAL caption now reads "37 passed in 1.84s" /
  "$ cmd"; MONTAGE camera frames 2x2 blocks with 64 px tool names; CALLOUT balloon hugs the quote and the camera
  stays on the page (camera views are now clamped inside the page for every key, explicit or rect).
- 9:16 first look: landscape screenshots left half of SCREEN/FEATURE empty, DIFF/CALLOUT/END top-heavy with an
  empty lower half, TITLE's NEW ISSUE burst hit the ribbon, PLAN's count burst hit the last row.
- Fixes: 9:16 SCREEN and FEATURE became close-up pages (establishing panel with a yellow inset box, then a
  close-up panel that prints the focus area big with coarser dots; FEATURE adds a headline strip and clicks in the
  close-up). DIFF centres the hunk and the hero points at it from below; CALLOUT gets a bigger balloon (min 820 px)
  and speaker; END centres its column above the hero; NEW ISSUE sits under the blurb, clear of the hero.
- 9:16 r3: all four re-rendered pages read cleanly; no QA overlaps/clips outside the safe-area advisories.
