# Launch kit (`kit:launch/*`) — the flagship launch-film style

Paper UI panels lying and standing on a lit graphite table, shot by a real look-at camera (one `matrix3d` per
frame from t), contact shadows projected on the table, thin connectors with travelling accent pulses, one lime
accent (or the project accent: `"accent": "project"`), Geist + one serif-italic emphasis word. All 15 Quick-mode
types are overridden; the kit also registers the `launch` theme, so `kit:base/<TYPE>` with `theme: "launch"`
matches the look on a flat stage.

Shot grammar (render-tech §C): establish wide >= 1 s, push 1.4-2.6x to the region that matters in 0.75 s
(outQuint-like PCHIP keys), hold with hand-held drift (no parked frames); read moments at <= 14° relative pitch
so type never looks italic; panels enter by rising off the table and unblurring before t = 0 (frame 0 is already
in motion); headlines >= 64 px; on 9:16 panels stack/stand and headlines move to a bottom band in the centre safe
area (with a stage-coloured scrim when over bright UI).

## Recipes
- Quick mode: `film_from_timeline(timeline, style="launch")` (kit.json: transitions match → crossfade 0.3,
  push → push-left 0.5, wipe → wipe 0.6; finish grain 0.035, vignette 0.22; captions Geist 600 46 px on a dark plate).
- Over-the-picture type: put `kit:type/*` overlays above launch shots (they pick up the launch tokens).
- Same params as `kit:base/<TYPE>` (see kits/base/KIT.md data shapes); `theme` defaults to `launch`.

## Scenes
<!-- scenes:begin -->
| id | what it shows | params (default) |
|---|---|---|
| `kit:launch/BEFORE_AFTER` | Before and after side by side on the table; a pulse carries across, the after panel lifts off the table and the camera trucks to it. | `before` — — {kind: image\|terminal\|diff\|code, ...} · `after` — — {kind: image\|terminal\|diff\|code, ...} |
| `kit:launch/CALLOUT` | One verbatim line in serif italic over the dim, defocused table; accent rule, mono attribution, near-still camera. | `text` "" — verbatim quote (<= 12 words ideal) · `who` "agent" — user \| agent \| test · `ref` "" — event id |
| `kit:launch/CODE` | Editor panel lying on the lit table; the file streams in, the camera dollies from a low angle onto the focus lines. | `path` "" — file path · `lang` "" — language · `lines` [] — <= 18 verbatim lines · `start` 1 — first line number · `focus` [1, 1] — [a, b] focus lines |
| `kit:launch/DIFF` | Diff on paper: rows wipe in, adds sweep the lime highlighter, deletions strike in grey; camera pushes onto the change, pulses carry it on. | `path` "" — file path · `lang` "" — language · `hunks` [] — [{header, lines:[[op,text]]}] <= 24 rows · `adds` 0 — lines added · `dels` 0 — lines removed |
| `kit:launch/END` | End card / thumbnail: camera pulls back to a near top-down table where every connector converges under the lockup; CTA pill, URL, credit. | `title` "" — product name · `cta` "" — command or link to try it · `url` "" — repo / site URL · `credit` "made with Hermes · Showreel" — small credit line · `tagline` "" — optional line under the title · `pb_display` "" — speedrun final time (shown as PB) |
| `kit:launch/FEATURE` | One product feature: push to its region, cursor arrives, pauses, clicks with a ripple, accent ring; feature name as headline. | `image` — — {asset, path, w, h, url, page_title, full_page} · `feature` "" — feature name (<= 6 words) · `bbox` [0.1, 0.1, 0.8, 0.8] — feature region (image fractions) · `click` [0.5, 0.5] — click point (image fractions) |
| `kit:launch/HOOK` | Scroll-stopper: the best real artefact hinges up off the table out of a blurred push-in, <= 6 word headline beside it. | `hero` — — {kind: image\|terminal\|diff\|code, ...} |
| `kit:launch/MONTAGE` | Breadth of the agent's work: real tool calls as cards along a wired path on the table; the camera whips card to card, each stands up as it arrives. | `items` [] — [{id, t, kind, tool, arg, clipped}] 3-16 |
| `kit:launch/PLAN` | Checklist card on the table: done items tick in on the beat, the active item spins; camera drifts down the list. | `items` [] — [{text, status}] <= 6 · `more` 0 — hidden items |
| `kit:launch/PROBLEM` | The user's prompt as a chat card on the table; letters type in (human input) while the camera pushes 1.0 -> 1.4x. | `text` "" — verbatim prompt · `truncated` false — ellipsis |
| `kit:launch/SCREEN` | Real screenshot in a paper browser frame lying on the table: establish wide, push to the focus box, hold. | `image` — — {asset, path, w, h, url, page_title, full_page} · `bbox` [0.1, 0.1, 0.8, 0.8] — focus box (image fractions) |
| `kit:launch/SCROLL` | Full-page capture in a browser frame standing on the table like a display; it scrolls top to bottom under a slow orbit. | `image` — — {asset, path, w, h, url, page_title, full_page} · `scroll` [0, 1] — [from, to] scroll fractions |
| `kit:launch/STATS` | Real numbers on the drop: big numerals count up over the table while connectors pulse into the hub; accent rule under the hero number. | `stats` [] — [{key, label, value, display}] 1-3, computed from the session (never invented) |
| `kit:launch/TERMINAL` | The one dark panel, tilted up off the table: command types, output streams, PASS badge pops with glow; slow 6-degree orbit. | `cmd` "" — command · `output` [] — <= 12 lines · `truncated_top` false — output cut at the top · `exit_code` — — exit code · `elapsed_s` — — seconds · `ok` true — succeeded · `tests_passed` false — PASS badge + chime |
| `kit:launch/TITLE` | Name + thesis: left lockup (eyebrow, huge title, tagline with one serif accent word) beside the product hero at a low angle; connectors pulse toward it. | `title` "" — product / film title · `tagline` "" — <= 10 words · `product` "" — product name (used when title is empty) · `one_liner` "" — unused on screen (VO material) · `eyebrow` "Introducing" — small mono line above the title ("" hides it) · `hero` — — optional product visual {kind:image\|terminal\|code\|diff, ...} |
<!-- scenes:end -->

## World blocks — `ctx.kit('launch').world` / `import { makeWorld } from '../launch/world.js'`
`makeWorld(F, {P})` → `W` with `node(el, {x, y, z, w, h, tilt})` (a panel on the table: x/y on the table plane,
z lift, tilt = hinge up about its bottom edge, degrees), `update(node, {tilt, z, op})`, `light(x, y, rx, ry)`
(light pool on the table), `wire(points, {pulseStart, every, speed, len, reverse, port, draw:[t0,t1]})`
(connector with pulses; `.set(t)`), `camera(t, {target:[x,y,z], dist, yaw, pitch, roll, shift:[dx,dy], lift})`,
`project(p)` → frame px, `nodePoint(node, x, y)`, `fitDist(w, h, fill, fillH)`.
`stage.js`: `launchScene(id, def)`, `camTrack(keys)` (PCHIP camera keys), `pushTrack(W, F, node, block, rect, o)`
(the establish → push → hold grammar), `panelWires`, `hubWires` (converging connectors under type), `fitRect`.

## Theme `launch` (tokens over kits/base)
stage #0A0B0D with a lit table (#25272D pool), paper #F6F5F1 panels, ink #141519, terminal #16171B, accent
#C9F25C (ink #11160A, highlighter #E4F7B0, glow rgba(201,242,92,.34)), chrome 28 px mono. See `theme.css`.
