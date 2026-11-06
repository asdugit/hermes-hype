# Kit `blueprint` — "the session as an engineering drawing"

A cyanotype sheet (`#0D3A66`, fine + major grid) with a zoned border and a title block that stamps its REV. Object
lines are white, dimensions / leaders / construction are cyan, and redline (`#FF8E6E`) is reserved for revisions
(clouds, deltas, strikes, REV letters, FAIL). Every stroke is an SVG path drawn on by a plotter pen at constant pen
speed (time follows path length) with pen-up travel between strokes; fills pop when their outline lands; lettering
(Space Grotesk titles, IBM Plex Mono notes) is revealed left to right with the pen riding the edge. Product captures
are dimensioned views: the frame plots with the real pixel size, the pen traces the page as Sobel line art, then it
"develops" cyanotype blue and lands as the real capture. The camera is orthographic and calm (1–2 % drift, pans,
detail zooms into DETAIL circles) — never hand-held. Ported from the approved style frames `styleframes/blueprint`
(frame A general arrangement, frame B revision, frame V vertical). All scenes are DOM + inline SVG, pure functions
of the shot time `t`; heavy work (edge plates) in setup. Requires kit `base`. Strings verbatim from the scene data.

## Scenes — the 15 Quick-mode types (`kit:blueprint/<TYPE>`, params = TimelineScene.data shapes, wp-e-story §2)
| id | look and move |
|---|---|
| `kit:blueprint/HOOK` | `{hero:{kind: image\|terminal\|diff\|code, ...}, label, product_scale}` — hero plotted fast as a dimensioned view (image: frame → line-art trace → develops → real; text: listing lettered), PASS/OK stamp for runs, ≤ 6-word label lettered on top |
| `kit:blueprint/TITLE` | `{title, tagline, product, one_liner}` — general arrangement: big lettered title + tagline, exploded plate stack on a centre line with balloons 1–3 calling out the verbatim strings, title block lands |
| `kit:blueprint/PROBLEM` | `{text, truncated}` — REQUIREMENT box, the prompt lettered in Plex Mono; a dashed "TO BE DESIGNED" part outline on a leader |
| `kit:blueprint/PLAN` | `{items:[{text,status}], more}` — process boxes on a centre line with flow arrows; balloons per step; DONE gets a check, IN PROGRESS a cyan dashed box, pending hidden-line dashes |
| `kit:blueprint/CODE` | `{path, lang, lines, start, focus, new_file, total_lines}` — annotated listing with gutter numbers; the focus lines get a vertical dimension (`L19–25`) and notes on leaders; calm detail push |
| `kit:blueprint/DIFF` | `{path, hunks, adds, dels, lang}` — frame B: deletions struck in redline, a revision cloud on the changed rows, delta B, rev table A/B, WAS/NOW notes on dog-leg leaders, `+n / −m` dimension |
| `kit:blueprint/TERMINAL` | `{cmd, output, exit_code, ok, tests_passed, elapsed_s, truncated_top}` — run listing next to a gauge drawing (dial, ticks, needle sweeps to the pass ratio), readouts, PASS / FAIL stamp |
| `kit:blueprint/MONTAGE` | `{items:[{tool, arg}]}` — detail circles, each with a line-art part per tool kind (read/edit/run/search/browse), and a ballooned parts list |
| `kit:blueprint/SCREEN` | `{image, bbox, product_scale}` — capture as View A: frame + pixel dims, trace, develop; DETAIL C circle on the bbox and a detail zoom (≥ 1.15×, fits circle + label) |
| `kit:blueprint/FEATURE` | `{image, feature, bbox, click, product_scale}` — as SCREEN, then a pen-down crosshair + construction rings at the click and a FEATURE callout on a plate beside the view (below on 9:16) |
| `kit:blueprint/SCROLL` | `{image, scroll:[from,to]}` — full page as a long elevation, full-height pixel dimension; camera pans down with a section line A riding the view |
| `kit:blueprint/STATS` | `{stats:[{label, display}]}` (≤ 4) — MEASUREMENTS: big numerals count up between extension lines, dimension arrows grow, labels lettered |
| `kit:blueprint/BEFORE_AFTER` | `{before, after}` (content dicts) — REV A then REV B beside it (below on 9:16); REV B gets the revision cloud + delta; title block stamps REV B |
| `kit:blueprint/CALLOUT` | `{text, who, ref}` — a NOTE box on the sheet, the quote lettered in Space Grotesk, `— who` on a leader; longest hold |
| `kit:blueprint/END` | `{title, cta, url, credit, tagline, pb_display}` — the sheet is signed: final title block with the CTA/URL, signature line, RELEASED stamp |

Common params (all scenes): `theme` (`blueprint`), `rev` (REV letter in the title block; default A, B for diffs),
`dwg` (drawing number; default from the scene data).

## Transitions
- `kit:blueprint/sheet-slide` (0.55 s) — the next sheet slides over the old one with a hairline edge shadow; the old
  sheet shifts 12 % and dims. Quick adapter `push`.
- `kit:blueprint/plot-wipe` (0.45–0.5 s) — a vertical pen line sweeps across, revealing the next sheet (`match`,
  `wipe`).
- `cut` is a hard cut. Never crossfade: drawings are replaced, not dissolved.

## Building blocks — `ctx.kit('blueprint')`
`draw` (`stroke`, `line`, `rectD`, `circleD`, `dimension`, `balloon`, `cloudD`, `delta`, `arrow`, `leader`,
`checkD`, oblique-projection helpers `P`, `platePts`), `plot` (`plotter(svg)` → `add`/`letter`/`pop`/`plan` at
constant pen speed, `dashUpTo`), `sheet` (`bpScene`, `BCOMMON`, `listing`, `codeHtml`), `media` (`mediaPlates`
trace/develop/real), `parts` (`header`, `note`, `stamp`, `frameDims`, `leaderTo`).

## Style metadata (`kit.json` `style`)
Fonts Space Grotesk (variable 300–700) + IBM Plex Mono 400/500/600 (OFL files in `fonts/`); palette sheet
`#0D3A66`, line `#EEF6FF`, cyan `#79D3FF`, redline `#FF8E6E`; bpm 100–112; beds `blueprint_a` (110), `blueprint_b` (108); SFX roles
cut/move = paper, type = plotter, appear/hit = stamp, pass = chime; `voice_speed` 1.0; post `grain_vignette`
(paper grain 0.03, no vignette).

## Notes
- Drafting grammar: object 2.4 px, thin 1.4 px, hidden `9 6`, centre `26 7 4 7`, construction `4 5`, 16 px filled
  arrowheads, unidirectional lettering, text ≥ 22 px at 1080p.
- 25 s Quick sample (16:9, bed + SFX): `w3-harness/quick_sample.py blueprint 16:9 26`.
