# kits — critique log (WP-G1)

Notes written right after each look at rendered keyframes (vision results are not retained).
Harness: `g1-harness/run.py` (throwaway SDK-subset runtime) until WP-D's runtime lands.

## Base kit, round 1 (16:9, theme=base, 19 samples x 2 keyframes)

Everything renders, no page errors, CSS module scripts load fine over the loopback server.
- HOOK (image): headline left + browser right reads; browser a bit small. HOOK (terminal): the terminal is tiny
  (2 output lines at 24 px in a 1180 px panel) -> frame looks empty. Needs content-aware font size.
- TITLE: centred lockup clean; serif accent word works with the base (blue) accent.
- PROBLEM/PLAN: fine, cards centred; plan card could be larger.
- CODE: wide establish OK, push-in at 0.9 OK. DIFF: highlighter rows read well; long comment line runs off the
  right edge when pushed (accepted: left-anchored push, but QA flags `clip`).
- TERMINAL: same as hook - small panel in a big dark frame; badge small. Scale font by row count.
- MONTAGE: camera lags (current card left of centre), upcoming cards not yet visible -> right half empty;
  cards too small (560x210). Fix: centre current card, pre-reveal 2 cards ahead, bigger cards.
- SCREEN/SCROLL: fine. STATS: good. CALLOUT: good. END: good, pill reads.
- FEATURE: headline sits ON the screenshot, over the click target (cursor + Pause button) and on white UI ->
  unreadable + covers the action. Fix: landscape = label column on the stage (left), media anchored right;
  portrait = label band under the media.
- BEFORE_AFTER (terminal): small terminals again (same font fix).

## Base kit, round 2 (real WP-D runtime, 16:9)
- Switched from the throwaway harness to the real runtime (build_job + page_session): works after two
  fixes on my side: flattened kits/base (page.py reads `from '../x/'` as a kit reference) and a defensive
  `surfaceSize()` (the runtime's dom ctx exposes a DOM builder as `ctx.h`, shadowing the height).
- Terminals now content-sized (38 px type for 2-3 rows); montage cards bigger, current card centred, two
  cards pre-revealed; FEATURE has a headline column on the stage and the media in a lens-shifted region.
- QA noise fixed: mask padding for display glyphs, bar line-heights, BEFORE/AFTER hidden halves, quote mark
  drawn by ::before. Remaining QA flags are inherent: partially typed rows (width clip), pushed-in text
  crossing the frame edge.

## Launch kit, round 1 (16:9, all 15 types on the table world)
- The world works: look-at camera matrix3d, table + light pool + dot grid, projected contact shadows,
  connectors with travelling pulses, lens shift. Strongest frames: TERMINAL / terminal PASS (dark panel
  standing on the table, table receding), DIFF push (highlighter rows huge and crisp), CODE push, SCROLL
  (browser standing like a display), TITLE/STATS/END/CALLOUT (type over defocused converging wires).
- Problems:
  1. HOOK hero too small (~810 px wide) in its region; terminal hook small too -> closer camera, width = region.
  2. Flat paper panels at 20-26 deg read with an "italic" slant (vertical strokes converge) -> read moments
     at <= 14 deg relative pitch, establish at <= 22.
  3. MONTAGE cards overlap each other (640 px step for 700 px cards) -> step 820, smaller y swing.
  4. BEFORE_AFTER: tags not positioned (missing position:absolute, stuck top-left); the failing "before"
     is never readable (camera starts wide, trucks away) -> open close on BEFORE, then truck to AFTER.
  5. FEATURE: pushed media fills the frame behind the headline column -> white type over light UI.
     Add a stage-coloured scrim under the headline (left gradient / bottom gradient on 9:16).
  6. QA small_text on panel chrome in establishing shots (18-21 px) -> launch chrome at 28 px.
- Earlier fix (round 0): vignette on bright paper read as a grey haze -> lighter vignette (0.38 at the rim).
