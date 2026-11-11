# Comic kit (`kit:comic/*`) — the session as an issue of a motion comic

Every Quick-mode scene is a **page of ink-bordered panels** printed on warm newsprint: 8 px ink borders, hard
offset shadows (never blur), true halftone (Ben-Day dots computed per panel, not a CSS pattern), turning sunbursts,
speech balloons with tails, yellow caption boxes, Bangers lettering with the ink stroke behind the fill, and
onomatopoeia bursts on every hit. Product screenshots are *printed* into the panels: a coarse colour halftone first,
then the real pixels grow in through the dot screen (a faint screen stays on). All 15 types are overridden; the kit
also registers the `comic` theme (replacing the kits/base starter), so `kit:base/<TYPE>` with `theme: "comic"`
gets the palette and fonts on a flat stage.

Motion grammar (all from `t`, seeded, no CSS animation):
- **Pages assemble**: panels wipe in from the reading side and pop 0.96 → 1 (`panelIn`); captions drop in; the
  camera moves *panel to panel* (PCHIP camera keys on panel rects, always clamped inside the page).
- **Balloons pop** 0.85 → 1.04 → 1 in 0.2 s, the lettering lands phrase by phrase, one stressed word in red.
- **Hits slam**: onomatopoeia / bursts 1.6 → 1 in 4 frames + a 2-frame page shake (BOOM!, TAK TAK!, PASS!, SHNK!,
  KRAK!, CLICK!, LOOK!). Every hit has a matching `hit` / `pass` cue.
- **Splash pages** (HOOK, TITLE cover, END back cover, TERMINAL pass panel): full-bleed sunburst + giant burst.
- **9:16** pages restack as vertical tiers; landscape screenshots get an *establishing panel + close-up panel*
  (the focus area re-printed big with coarser dots) instead of a camera push that would crop the width.
- Transitions: `page-turn` (the page lifts at the corner and turns), `splat-iris` (the next page bursts through a
  jagged ink-rimmed explosion), `panel-glide` (camera crosses the gutter).

Theme metadata (kit.json `style`): palette ink #14110F / paper #F4EAD2 / cyan #29B6E3 / magenta #E33D7F /
yellow #FFD23A / red #E2392B / blue #1D5FC2 / green #2FAE4F; fonts Bangers (display), Comic Neue Bold +
Bold Italic (lettering), Space Mono Bold (code) — all SIL OFL, licences in `fonts/`; bpm 112–126; beds
`comic_a`, `comic_b`; voice_speed 1.0; captions Comic Neue 700 44 px on a yellow caption plate.

See RECIPES.md for when to use which page.

## Scenes
Same params as `kit:base/<TYPE>` (data shapes in kits/base/KIT.md); `theme` defaults to `comic`.
<!-- scenes:begin -->
| id | what it shows | params (default) |
|---|---|---|
| `kit:comic/BEFORE_AFTER` | The money shot as a split page: BEFORE in grey dots (desaturated), then a lightning-bolt gutter cracks open (KRAK!) and the AFTER panel slams in full colour over a sunburst. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `before` — — {kind: image\|terminal\|diff\|code, ...} · `after` — — {kind: image\|terminal\|diff\|code, ...} |
| `kit:comic/CALLOUT` | One quotable line in a big speech balloon (a jagged shout balloon for exclamations or test results) from a small speaker silhouette; the balloon pops and the words land phrase by phrase, one stressed word in red. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `text` "" — verbatim quote (<= 12 words ideal) · `who` "agent" — user \| agent \| test · `ref` "" — event id |
| `kit:comic/CODE` | Two-panel page: the agent hammers the keyboard (TAK TAK TAK!) while the real file streams into an inked editor panel; the camera glides to the editor and pushes onto the focus lines, which get a yellow marker. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `path` "" — file path · `lang` "" — language id · `lines` [] — <= 18 verbatim lines · `start` 1 — first line number · `focus` [1, 1] — [a, b] focus line numbers |
| `kit:comic/DIFF` | Diff page: rows ink in, deletions get a red-pen strike-through, additions a green fill with a SHNK! on the first add; a +N/-N burst slams; the camera pushes onto the change. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `path` "" — file path · `lang` "" — language id · `hunks` [] — [{header, lines:[[op, text]]}] <= 24 rows · `adds` 0 — lines added · `dels` 0 — lines removed |
| `kit:comic/END` | Back cover / thumbnail: big masthead title and tagline, a dashed TRY IT TODAY! coupon stamped on with the CTA command and repo URL, the "made with Hermes · Hype" credit; the hero stands on the right over a blue sunburst. Speedrun adds a PB burst. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `title` "" — product name · `cta` "" — command or link to try it · `url` "" — repo / site URL · `credit` "made with Hermes · Hype" — small credit line · `tagline` "" — optional line under the title · `pb_display` "" — speedrun final time (shown as PB) |
| `kit:comic/FEATURE` | One feature as a two-panel page: the feature name in display lettering beside the hero; the printed product shot in the big panel, the camera pushes in, the cursor arrives, pauses and clicks with a CLICK! burst and speed lines, a yellow marker ring circles the feature. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `feature` "" — feature name (<= 6 words), shown as the headline · `bbox` [0.1, 0.1, 0.8, 0.8] — feature region [x,y,w,h] (image fractions) · `click` [0.5, 0.5] — click point [x,y] (image fractions) |
| `kit:comic/HOOK` | Splash page scroll-stopper: the best real artefact (printed screenshot, green test run, diff) inside a giant burst over a red sunburst, a <= 6 word headline in display lettering and one onomatopoeia; page shake on the slam. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `hero` — — {kind: image\|terminal\|diff\|code, ...block data} |
| `kit:comic/MONTAGE` | Breadth of the agent's work as a strip being inked: one tiny panel per real tool call (icon, tool name in display lettering, the argument in mono, session clock) fills in on every half-beat while the camera tracks the row. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `items` [] — [{id, t, kind, tool, arg, clipped}] 3-16 tool calls |
| `kit:comic/PLAN` | The agent's plan as caption boxes stacked down a page: done items get a green check stamp with an ink splat on the beat, the active item gets a red marker ring and a NOW! burst, the hero points at the list. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `items` [] — [{text, status}] <= 6 (status: completed\|in_progress\|pending) · `more` 0 — hidden items count |
| `kit:comic/PROBLEM` | The ask as a comic page: "MEANWHILE, IN A HERMES SESSION..." caption, the user's verbatim prompt pops in a speech balloon phrase by phrase, then the camera pulls back as the agent reads it and gets to work (TAK TAK!). | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `text` "" — verbatim prompt (redacted) · `truncated` false — adds an ellipsis |
| `kit:comic/SCREEN` | The real screenshot printed into a big panel (colour halftone develops into the real pixels) with a caption; the camera establishes, then pushes onto the focus box (9:16: a close-up panel prints the focus area big), which a yellow marker ring circles with a LOOK! burst. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `bbox` [0.1, 0.1, 0.8, 0.8] — focus box [x,y,w,h] as image fractions |
| `kit:comic/SCROLL` | A full-page capture printed in an inked browser frame scrolls top to bottom inside a blue sunburst panel; white motion streaks rush past and a SWOOSH! lands as the scroll starts. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `scroll` [0, 1] — [from, to] scroll fractions |
| `kit:comic/STATS` | "BY THE NUMBERS!" splash page: each real session number slams in its own burst on the beat and counts up, with a caption label; page shake on the drop. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `stats` [] — [{key, label, value, display}] 1-3, computed from the session (never invented) |
| `kit:comic/TERMINAL` | The frame-B page: the agent at the keyboard, the real command types and its output streams in an inked terminal, then the splash panel slams PASS! (tests) / DONE! (exit 0) / FAIL! with the key number in a burst; Z-path camera glide, page shake on the hit. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `cmd` "" — command line · `output` [] — <= 12 output lines · `truncated_top` false — output was cut at the top · `exit_code` — — exit code · `elapsed_s` — — runtime seconds · `ok` true — run succeeded · `tests_passed` false — PASS! splash + chime |
| `kit:comic/TITLE` | Cover page: the title drops in letter by letter as a masthead over a turning sunburst and magenta halftone, the tagline ribbon wipes on, a NEW ISSUE burst slams, the agent hero stands over a code-tower skyline. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `title` "" — product / film title · `tagline` "" — <= 10 words · `product` "" — product name (used when title is empty) · `one_liner` "" — unused on screen (VO material) · `hero` — — optional product visual {kind:image\|terminal\|code\|diff, ...} · `eyebrow` "Introducing" — strip under the masthead ("" hides it) |
<!-- scenes:end -->

## Transitions
| id | what it shows | params (default) |
|---|---|---|
| `kit:comic/page-turn` | The page lifts at the bottom-right corner and turns over to the left; the newsprint back and a hard curl shadow are painted on the overlay; the next page is underneath. kit.json `push`, 0.7 s. | `kind` css |
| `kit:comic/splat-iris` | The next page bursts open through a jagged explosion balloon with a heavy ink rim (seeded spikes). kit.json `wipe`, 0.5 s. | `kind` css |
| `kit:comic/panel-glide` | The camera glides across an ink gutter to the next page (both pages slide). kit.json `match`, 0.5 s. | `kind` css |

## Blocks — `ctx.kit('comic')` / `import … from '../comic/lib/*.js'`
- `page.js`: `comicScene(id, def)` (defineDomScene wrapper: `build(ctx, p, F, P)` gets a page `P`),
  `P.panel(rect, {bg, rays:[fx,fy], seed, spin})` with backgrounds `white cyan magenta action splash sun blue grey
  paper`, `P.panelIn(pn, t, t0, dir)`, `P.track([[t, rect|'page'|[cx,cy,z]], …], pad, zmax)` → `cam(t)`,
  `P.camera(t, [cx,cy,z], {shakes:[t…], amp, drift})`, `P.spinRays(t)`, `P.svg(w, h, inner)`, `P.grid(rows)`,
  `snapIn(el, t, t0, {rise, from, rot})`.
- `letter.js`: `caption(text, {x, y, white, mono, wrap, maxW, size})`, `balloon(doc, parent, text, {x, y, w, h,
  size, tail:[x,y], maxWords})` (+ `.shout`), `fitBalloon(text, maxW, maxH, max, min, minW)`, `sfx(word, {x, y,
  size, color, rot})`, `masthead(text, {x, y, size})`, `headline(text, {x, y, w, lines, max, min})`, `pop`, `slam`,
  `pageShake`.
- `art.js`: palette `C`, `halftone(doc, w, h, {cell, angle, color, f})`, `rays`, `speedLines`, `burst(doc, {w, h,
  spikes, depth, fill, seed, shadow, text, size})`, `burstClip`, `tail`, characters `agentSvg({pose: hero | point |
  type | bust, rim, cape})`, `userSvg`, `figure(markup, x, y, w)`, `skyline`, `checkSvg`, `CURSOR_SVG`.
- `print.js`: `printShot(ctx, img, w, h, {crop, cell})` (`.update(t, t0, dur)`, `.pt`, `.rect`), `comicBrowser`,
  `scrollBrowser` (`.setScroll(f)`), `heroBlock(ctx, content, o)` (image | terminal | diff | code).
