# Kit `terminal` — "the session on an amber CRT"

Everything happens on one phosphor tube: the session's real captures are re-typed, printed and drawn in a
character grid (IBM Plex Mono, advance 0.6 em, line-height 1.3, so box-drawing and block glyphs join), VT323 for
display numerals and taglines. One phosphor per film (`p3` amber default, `p1` green swap). Product captures arrive
as an ASCII plate, resolve through a Bayer 4×4 dither and land as the real image tinted into the glass. The
"camera" is the terminal: whole-line scrolls, zoom in discrete font-size steps, the cursor as the attention point;
the tube breathes (2–3 % flicker + a slow roll bar) instead of camera moves. Halation, curvature and misconvergence
come from the `crt` post chain (`kit.json` `render.post`); scanlines live in CSS so they stay crisp. Ported from the
approved style frames `styleframes/terminal` (frame A boot + logo, frame B test run, frame V vertical).
All scenes are DOM (`layer: 'dom'`), pure functions of the shot time `t`; heavy work (dither plates) in setup.
Requires kit `base`. Strings come verbatim from the scene data.

## Scenes — the 15 Quick-mode types (`kit:terminal/<TYPE>`, params = TimelineScene.data shapes, wp-e-story §2)
| id | look and move |
|---|---|
| `kit:terminal/HOOK` | `{hero:{kind: image\|terminal\|diff\|code, ...}, label, product_scale}` — tube powers on (dot → line → picture, degauss wobble), hero arrives in a pane (capture: ASCII → dither → real; test run prints with its PASS block), ≤ 6-word headline typed in VT323 |
| `kit:terminal/TITLE` | `{title, tagline, product, one_liner}` — a short boot log prints at line rate, the name builds row by row as a block-letter logo with a phosphor drop shadow (VT323 fallback for glyphs outside the face), tagline in VT323, prompt cursor blinks |
| `kit:terminal/PROBLEM` | `{text, truncated}` — the user's request typed into the agent's prompt letter by letter (human cadence, key ticks) inside a box-drawn pane; long prompts scroll up in whole lines |
| `kit:terminal/PLAN` | `{items:[{text,status}], more}` — the plan as a boot log: one service line per item with dot leaders; done items flip to `[  OK  ]` on the beat (relay click), the active one runs in inverse with a spinner, pending ones `WAIT`; counter `k/n` in the pane title |
| `kit:terminal/CODE` | `{path, lang, lines, start, focus, new_file}` — box-drawn pane with line numbers; the file prints line by line, the page jumps to the focus range in whole-line steps, focus lines go hot (rest dims), zoom in font-size steps (≤ 1.3×) |
| `kit:terminal/DIFF` | `{path, hunks, adds, dels, lang}` — `diff -u` pane: hunks print one after another, `-` rows strike through and dim, `+` rows over-drive hot; the `+n −m` counters in the pane title roll up |
| `kit:terminal/TERMINAL` | `{cmd, output, exit_code, ok, tests_passed, elapsed_s, truncated_top}` — frame B: the command types at a human cadence, verbatim output streams line by line, the PASS line over-drives with an inverse block and a beep (FAIL lines likewise); test counts roll on odometer drums |
| `kit:terminal/MONTAGE` | `{items:[{tool, arg}]}` — tool calls as a scrolling session log (clock, tool, argument), lines on half-beats, the newest in inverse video, the log jumps up in whole lines |
| `kit:terminal/SCREEN` | `{image, bbox, product_scale}` — capture in a box-drawn pane: ASCII → phosphor dither → real with a raster sweep, then zooms to the bbox in discrete steps (1.4–2×) |
| `kit:terminal/FEATURE` | `{image, feature, bbox, click, product_scale}` — as SCREEN, then the pixel-art pointer arrives and clicks (inverse flash, relay click), a hot frame and the inverse feature tag type in |
| `kit:terminal/SCROLL` | `{image, scroll:[from,to]}` — full page: the first screen resolves dither → real, then it pages down like `less` in whole-line jumps; a block-character scrollbar rides the pane edge |
| `kit:terminal/STATS` | `{stats:[{label, display}]}` (≤ 4) — real numbers on VT323 odometer drums: roll from 0 with per-digit inertia (last digit spins longest), settle with a click, ghost neighbours; caps labels |
| `kit:terminal/BEFORE_AFTER` | `{before, after}` (content dicts) — two panes `before/` and `after/` (stacked on 9:16): before prints, after prints beside it, focus moves to after (before dims) |
| `kit:terminal/CALLOUT` | `{text, who, ref}` — one verbatim line as a hot `# comment` centred on the glass; prints in word chunks (typed letter by letter when the user said it), cursor at the end, attribution as a dim comment; longest hold |
| `kit:terminal/END` | `{title, cta, url, credit, tagline, pb_display}` — `$ exit` → `logout` → block-letter name, CTA as a hot prompt line, URL, credit (speedrun: the PB time); the tube switches off in the last 0.45 s |

Common params (all scenes): `theme` (`terminal`), `phosphor` (`p3` amber | `p1` green — keep one per film),
`power_on` / `power_off` (null = scene default: HOOK powers on, END powers off).

## Transitions
- `kit:terminal/channel-switch` (0.3 s) — between acts: horizontal tear, static burst, vertical-hold roll. The
  Quick adapter uses it for `push` / `wipe`.
- `kit:terminal/persist` (0.14 s) — hard cut with a 4-frame phosphor trail of the outgoing frame (`cut` / `match`).
- Never crossfade (a CRT redraws, it does not dissolve).

## Building blocks — `ctx.kit('terminal')`
`crt` (grid metrics `ADV`/`LH`, `PHOSPHOR`, `typing`, `printing`, `blink`, `cursor`, `spin`, `box`, `leader`, `wrap`,
`fit`, `logo`/`logoLines` block-letter face), `pane` (`termPane`, `codePane`, `diffPane`, `odometer`, `runNumbers`),
`phosphor` (`phosphorMedia` ASCII/dither/real plates, `pointer` sprite), `tube` (`tubeScene`, `TCOMMON`, `margins`).

## Style metadata (`kit.json` `style`)
Fonts IBM Plex Mono 400/500/600 + VT323 + JetBrains Mono (OFL files in `fonts/`); palette P3 amber `#FFB13B` on
glass `#0C0805`; bpm 100–114; beds `terminal_a` (110), `terminal_b` (114); SFX roles cut/move = glitch, type = key, click/hit =
relay, appear/pass = beep, hero = sub_drop, build = riser; `voice_speed` 1.0; post `crt` (glow 0.5, curvature 0.055, vignette 0.42, scanline 0 —
the CSS draws them).

## Notes
- Text sizes stay ≥ 22 px at 1080p (QA small_text); panes snap to whole character cells.
- Light UI captures auto-invert in the ASCII/dither stages so the ink lights up, not the paper; the real plate is
  multiplied by warm `#EAD5B8` so white pages sit inside the glass instead of glowing white.
- 25 s Quick sample (16:9, CRT post, bed + SFX): `w3-harness/quick_sample.py terminal 16:9 26`.
