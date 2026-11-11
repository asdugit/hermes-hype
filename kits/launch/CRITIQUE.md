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

## Launch, 9:16 round 1
- Re-layout reads native (panels stacked / standing, headline bands at the bottom of the centre band).
- Fixed after the look: portrait terminals wrapped tabular output -> font fits the longest output line
  (>= 22 px) else wraps at 24; TITLE without hero sat high -> centred lower (top 700); PLAN card filled
  only 80 % of the width -> 94 %.
- FEATURE 9:16: headline band + scrim readable over the bright UI; END/STATS/CALLOUT centred and strong.

## Type kit, round 1 -> 2 (overlays over a bright product screen, 16:9 + 9:16)
- Round 1: white type straight over light UI was unreadable (title, kinetic); HUD timer too small.
- Round 2: per-overlay `scrim` (radial / left / bottom gradient of the stage colour, animated with the
  type, default 0.62) -> all lines legible in both aspects; timer HUD 76 px on a dark plate; lower third
  on a bottom gradient. Accent falls back to the base blue when the style kit isn't loaded (in Quick films
  the style kit is always present, so overlays pick up the style accent).

## Theme proofs (kits/base re-skinned with CSS only, 16:9)
- terminal: phosphor green on black, all-mono, glow — coherent, every scene legible.
- blueprint: white linework on blue grid, outlined sheets, yellow accent — coherent, reads as drafting.
- comic: cream halftone, 5 px outlines + hard offset shadows, heavy uppercase display, red accent — strongest
  departure from the default; still legible.
- ink: rice paper, serif-italic display, vermilion seal — calm editorial; numerals in serif italic read well.
- Product screenshots keep their own colours in every theme (correct: never re-tint the product).

## Quick-mode sample film (webapp fixture, 26 s target -> 25.2 s, launch)
- 16:9 keyframes: HOOK/TITLE/FEATURE x2/SCROLL/STATS/END all read; push-left transitions slide both DOM
  shots; captions sit in their band (END moves its credit into the lockup when captions are up).
- Fixed after the look: TITLE eyebrow crowded the title (QA overlap) -> eyebrow gap scales with title size;
  END credit outside the runtime safe area -> safe area now max(kit, runtime) (16:9 bottom 120, 9:16 sides 120);
  9:16 headlines at x=110 -> text columns 840 wide inside the 120 px sides.

## Final pass (both aspects, all 15 types, launch + base)
- Secondary chrome raised (bars 27-28 px, chips/badges/meta 25-26 px, gutter .92 em, tags 26 px) so held
  frames pass the 22 px projected rule; remaining small_text flags are establishing frames during the
  0.5 s entrance (chrome while the camera is wide) — accepted, the push brings them to 26-40 px.
- MONTAGE (launch): cards were small with a grey slab of the previous card intruding after a closer fit ->
  spacing cw + 320, closer fit (1.8 card widths), cards more than two behind fade out. Now one centred card,
  the next one peeking in.
- Remaining `clip` QA flags are by design: partially typed rows (width reveal) and pushed-in long code lines
  running off the frame edge.

## W3 integration, look 1 — first real Quick film through the pipeline (Hype session, LLM storyboard, 30 s)
Real pipeline: capture (6 media shots) -> hermes-cli storyboard (8 scenes, repaired) -> edge TTS -> launch, both
aspects. Rendered fine (0 page errors, video QA ok). 16:9 ~6.5/10, 9:16 ~5.5/10.
- Browser chrome shows local file paths as the URL ("~/showreel-work/research/wp-k1-pixel/rend...", ".../board_1.png")
  -> clip + safe QA flags and it reads like a dev screenshot. Show a host/title, never a filesystem path.
- 9:16: big dark voids above/below every panel (HOOK, TITLE, SCREEN, END); the table world is mostly an empty
  dark plane. END lockup is a small island in a black frame; credit tiny.
- 9:16 FEATURE: headline sits on top of the bottom edge of the media; STATS stack runs past the bottom safe line.
- 16:9 STATS reads well now (516 / 29 / 12) but static; END/TITLE are word + wires on a dark table: template feel.
- SCREEN (product image) is the strongest frame: full-bleed product. More of the product, bigger, everywhere.
- Backgrounds: flat graphite + thin lime wires on every type scene -> needs depth (light pool, haze, bokeh,
  product echo) so type scenes don't feel empty.

## W3 look 2 — after backdrop + count-up + address-bar fixes (re-shot from the real timeline, 16:9)
- TITLE now uses the film's product image as its hero (left lockup + tilted product panel): no more word-on-black.
- STATS/END/CALLOUT: product image lies on the table under the type as a defocused echo (blur 7-9 px, op ~0.5,
  radial scrim) -> frames feel full; numerals and lockup still read cleanly. Count-up mid frame now reads "417 15"
  (same digit count, 15 Hz steps) instead of "10 1".
- Found a hard dark vertical band left of TITLE: the lens shift translated the whole view and uncovered the stage.
  Fixed by shifting world origin + perspective-origin together (exact 2D shift, nothing uncovered).
- Address bars show page title / file stem ("preview", "board_1"), never "~/showreel-work/...".

## W3 look 3 — 9:16
- TITLE: product panel on top, lockup below (was: panel at the bottom under the caption band).
- SCREEN/FEATURE push in by height (crop the landscape screenshot's sides) -> product fills the frame at the push.
- HOOK still leaves the lower third dark (platform UI zone, acceptable); STATS stack now fits the safe area.
- product_scale (Director knob) verified at 1.6 on HOOK/TITLE/SCREEN: product clearly larger; at > 1.4 the HOOK
  headline starts to overlap the product (the Director's call).

## W3 look 4 — gallery of all 15 types (G1 fixtures + backdrop), 16:9 and 9:16
- 16:9 strong: HOOK, TITLE (product hero), PLAN, TERMINAL, SCREEN, STATS (echo), CALLOUT (echo), FEATURE.
- MONTAGE was one small card in a void -> tight conveyor (3 cards in frame), centred on the standing card, trailing
  cards fade before they leave the frame.
- Table: added an accent practical spill (far left) + cool fill (right) -> the graphite reads as a lit surface.
- 9:16 PROBLEM/PLAN: a wide card in a tall frame left 40 % dark above it -> the product echo now lies on the table
  behind/above the card (flat, no scrim; scrim is screen-space and washed the world card grey on the first try).
- GOTCHA: a node at z <= 0 (coplanar with / under the table) made Chromium's 3D plane sorting hang
  Page.captureScreenshot (> 60 s). Keep world nodes at z >= 1.
- END credit now sits 18 px above the safe line (the glyph box overhang tripped safe-area QA).
