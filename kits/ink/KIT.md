# Ink kit (`kit:ink/*`) — hand-drawn illustrated explainer

A warm illustrated explainer (approved style frames: `styleframes/ink/frame_a|b|v`). Every Quick-mode scene type is a
page of warm paper where seeded Rough.js ink strokes draw on, **the user** (round glasses, teal sweater) and **the
robot helper** (cream body, screen face, antenna) act out the beat from a small pose library, sticky notes, arrows and
handwritten notes annotate it, and the real product captures are taped onto the page. The camera is hand-held
(gentle drift, slow PCHIP pushes, 2D transforms only). Registers theme `ink` (replaces the kits/base starter), the
15 scenes and two transitions.

## Using it
- **Quick mode:** `style: "ink"` maps every `TimelineScene` to `kit:ink/<TYPE>`; `TimelineScene.data` passes through as
  params (shapes: kits/base/KIT.md "Data shapes"). `_sync.click` / `_sync.pass` land the FEATURE click and the
  TERMINAL PASS seal on the beat; `_mute` drops cues the timeline already placed.
- **Directed films:** use any `kit:ink/<TYPE>` as a shot with the params below. Beats are authored for a 4 s shot
  and scale with the shot length (0.62x for 2.5 s .. 1.25x for 5 s+), so 3 s Quick shots land every beat.
- Common params (every scene): `theme` ("ink"), `label` (HOOK shows it handwritten), `accent` (unused: ink keeps
  terracotta), `_captions`, `_sync`, `_mute`, `backdrop` (kit.json `"backdrop": true`; reserved).

## Scenes
<!-- scenes:begin -->
| id | what it shows | params (default) |
|---|---|---|
| `kit:ink/BEFORE_AFTER` | The money shot: before and after as two paper panels on one page; the before lands with a terracotta cross, a hand-drawn arrow sweeps across, the after slaps on with a teal tick and sparkles; handwritten "before" / "after" labels. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `before` — — {kind: image\|terminal\|diff\|code, ...} · `after` — — {kind: image\|terminal\|diff\|code, ...} |
| `kit:ink/CALLOUT` | One quotable line, verbatim, in a hand-drawn speech bubble from the robot (or the user): Fraunces italic words appear one by one, then one word gets a terracotta underline; a handwritten attribution. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `text` "" — verbatim quote (<= 12 words ideal) · `who` "agent" — user \| agent \| test · `ref` "" — event id |
| `kit:ink/CODE` | The real file written out on a legal pad (ruled lines, terracotta margin) under a folded file tab: lines stream in like handwriting, a mustard highlighter swipes the focus lines, a handwritten note marks them and the camera pushes in; the robot presents from the corner. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `path` "" — file path · `lang` "" — language id · `lines` [] — <= 18 verbatim lines · `start` 1 — first line number · `focus` — — [a, b] focus line numbers · `new_file` — — file was created |
| `kit:ink/DIFF` | The real diff marked up on a legal pad: removed lines are struck through with a red pen and fade, added lines are written in teal with "+" margin marks, the "+n −m" tally is handwritten; the camera pushes to the change. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `path` "" — file path · `lang` "" — language id · `hunks` [] — [{header, lines:[[op, text]]}] <= 24 rows · `adds` 0 — lines added · `dels` 0 — lines removed |
| `kit:ink/END` | End card (thumbnail frame): the user and the robot wave side by side, the title lockup with the film strip running under it, the CTA command written on a paper luggage tag, the repo URL and the "made with Hermes · Showreel" credit; speedrun adds a PB sticky note. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `title` "" — product name · `cta` "" — command or link to try it · `url` "" — repo / site URL · `credit` "made with Hermes · Showreel" — small credit line · `tagline` "" — optional line under the title · `pb_display` "" — speedrun final time (shown as PB) |
| `kit:ink/FEATURE` | Product capture + one feature: the camera pushes to the region, a hand-drawn cursor arrives, pauses and clicks (ink ripple), a terracotta marker loop circles the feature and a sticky note with the feature name slaps on beside it with an arrow. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `feature` "" — feature name (<= 6 words), shown on the sticky note · `bbox` — — feature region [x,y,w,h] (image fractions) · `click` — — click point [x,y] (image fractions) |
| `kit:ink/HOOK` | Scroll-stopper: the best real artefact (product capture, green test run, diff) is slapped onto the page with masking tape, outline drawing on, a <= 6 word handwritten label with an arrow points at it, and the robot peeks in from the corner. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `hero` — — {kind: image\|terminal\|diff\|code, ...block data} |
| `kit:ink/MONTAGE` | Breadth of the agent's work: the real tool calls as index cards pegged on two clotheslines, each with a pictogram doodle and its argument; the camera pans along the lines card to card on the beat while the robot walks beneath. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `items` [] — [{id, t, kind, tool, arg, clipped}] 3-16 tool calls |
| `kit:ink/PLAN` | The plan (style frame B): numbered sticky notes slap onto a corkboard, done items get teal ticks, a terracotta marker loop circles the active note while the user points at it with a pointer; "3 of 6 done!" is handwritten under the title; the robot sits on the board. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `items` [] — [{text, status}] <= 6 (status: completed\|in_progress\|pending) · `more` 0 — hidden items count · `total` 0 — total items (else items + more) |
| `kit:ink/PROBLEM` | The ask: the user's verbatim request types into a paper speech bubble letter by letter (human cadence), the robot reads along and its antenna lights up on the last word. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `text` "" — verbatim prompt (redacted) · `truncated` — — adds an ellipsis |
| `kit:ink/SCREEN` | Real screenshot taped to the page with its URL on a luggage tag: establish wide, then the camera pushes 1.4-1.9x to the focus box while a terracotta marker loop draws around it. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `bbox` — — focus box [x,y,w,h] as image fractions |
| `kit:ink/SCROLL` | A full-page product capture taped onto the page as a long sheet: the page scrolls smoothly inside its frame while a hand-drawn scrollbar thumb travels down and a handwritten "scroll" note points the way. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `scroll` [0, 1] — [from, to] scroll fractions |
| `kit:ink/STATS` | Real session numbers as big painted Fraunces numerals: each wipes in with ink and counts up, a Caveat label writes under it, terracotta underlines draw on, and the robot cheers from the top of the hero number (the music drop). | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `stats` [] — [{key, label, value, display}] 1-3, computed from the session (never invented) |
| `kit:ink/TERMINAL` | The real command on the little illustrated terminal machine: the command types, output streams line by line in cream mono on ink; on success the robot raises a tick flag and a PASS seal stamps on (chime), on failure it scratches its head and a FAIL seal lands. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `cmd` "" — command line · `output` [] — <= 12 output lines · `truncated_top` — — output was cut at the top · `exit_code` — — exit code · `elapsed_s` — — runtime seconds · `ok` — — run succeeded · `tests_passed` — — shows the PASS seal + chime |
| `kit:ink/TITLE` | Title page (style frame A): the user at a laptop under a swinging lamp, the robot holds up the film strip as it unspools with scene pictograms; the title rises letter by letter in Fraunces, a terracotta brush underline draws on, an italic tagline and handwritten "you" / "your agent" notes. | `backdrop` — — the film's product image {kind:'image', asset, w, h} (Quick mode, type scenes): shown as a soft product echo behind the type · `title` "" — product / film title · `tagline` "" — <= 10 words · `product` "" — product name (used when title is empty) · `one_liner` "" — unused on screen (VO material) · `hero` — — optional product visual {kind:image\|terminal\|code\|diff, ...} · `eyebrow` "Introducing" — small kicker above the title ("" hides it) |
<!-- scenes:end -->

## Transitions
| id | look | LLM vocab (kit.json `transitions`) |
|---|---|---|
| `kit:ink/ink-bleed` | the next page bleeds in through an organic ink blot spreading from a point, wet ink rim + seeded droplets | `wipe` (0.7 s) |
| `kit:ink/paper-slide` | the next sheet is slid in over the current one by hand (slight turn that settles, flat edge shadow) | `push` (0.6 s), `match` (0.5 s) |
`cut` stays a hard cut (use it on downbeats). Params: ink-bleed `{x, y, seed}` (origin as frame fractions),
paper-slide `{dir: 'left' | 'up', turn}`.

## Cues emitted (role names; sfx.json `styles.ink` resolves them)
`type` → plotter (pencil / pen writing, typing, marker loops) · `appear` → pop (notes, cards, cast) · `move` →
paper (page slides, camera moves) · `click` → click (FEATURE) · `pass` → chime / `fail` → error (TERMINAL seal,
BEFORE_AFTER) · `hit` → stamp (STATS numbers, seals).

## Cast, poses and props (lib/, for new scenes)
- `cast.robot(key, {pose, face, arms: {l, r}, reach, lit})`, `cast.person(key, {variant: 'bust' | 'stand', pose,
  look, pointer})` → `{markup}` with handles `${key}-armL/-armR/-head/-bulb/-face-*`. Poses (`cast.POSES`): stand,
  wave, cheer, point (pointer stick), present, flag (tick flag), think, hold, type, shrug. Animate with
  `setArm(el, side, deg, kind)`, `blink(K, key, t)`, `face(K, key, name)`, `antenna(K, key, v)`.
- `props`: `note` (sticky note: number, check/tick, pin or tape), `tape`, `pin`, `tapedShot` (real capture on a cream
  mat with tape; `pt(fx, fy)`, `rect(bbox)`), `luggageTag`, `bubble`, `legalPad`, `fileTab`, `machine` (terminal box),
  `corkboard`, `indexCard`, `filmStrip` (the motif: unspools along a curve, pictograms ride the frames), `lamp`,
  `desk`, `laptop`, `mugBooks`.
- `ink`: palette `C`, `form` (fill + seeded rough outline offset by the −3/−2 px misregistration), `stroke`, `tube`,
  `arrow`, `loop` (terracotta marker loop), `tick`, `underline`, `sparkle`, pictograms `ICONS` / `toolIcon`, motion
  helpers `drawOn` (pathLength dash draw-on), `writeOn` (handwriting clip reveal), `popIn`, `settleIn`,
  `riseLetters`, `typeTo`. Every Rough.js call goes through `roughD(shape, key)`, which seeds from the key: same key,
  same wobble, no boil.
- `page`: `inkScene(id, {params, build(ctx, p, F, P)})` — P has the paper sheet, `content` / `top` layers, `track`
  (PCHIP camera keys), `camera(t, [cx, cy, z])`, `bounds()` (grow the paper for long pans).

## Look rules (keep them when adding scenes)
One outline weight (3.2 px warm ink), one misregistration offset, flat offset shadows (never blurred), 4 hues +
neutrals with terracotta as the single hero accent, peach backdrop disc behind the focal group, Fraunces display /
Fraunces italic taglines / Caveat handwriting / Inter labels / JetBrains Mono for verbatim code and output. Facts
(code, plan items, numbers, captures) stay verbatim and big; the illustration frames them.

Fonts: Fraunces, Inter, Caveat, JetBrains Mono (SIL OFL 1.1, `fonts/OFL-*.txt`). Rough.js 4.6.6 (MIT,
`vendor/LICENSE-roughjs.txt`). Paper textures are procedural (seeded value noise, encoded once per page size).
