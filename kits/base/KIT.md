# Base kit (`kit:base/*`) — style-neutral scenes for every storyboard type

DOM scenes for all 15 Quick-mode scene types, driven **only by theme tokens** (`--sr-*` CSS custom properties).
Any style re-skins every scene with CSS alone; style kits (e.g. `kits/launch`) may additionally override single
types. Every scene is a pure function of `t` (no clocks, no CSS transitions/animations), re-lays out natively for
9:16 (not a crop), keeps text inside the safe area, uses DOM text (QA-measurable, >= 22 px at 1080p), enters in
0.4-0.6 s with outQuint-like curves (rise + unblur, never a bare fade) and never parks (hand-held drift).

## Using it
- **Quick mode** (`showreel_core/film/quick.py`): each `TimelineScene` becomes a shot `kit:<style>/<TYPE>` when the
  style kit lists that type in its `kit.json` `"scenes"`, else `kit:base/<TYPE>` with `params.theme = <style>`.
  `TimelineScene.data` (research/wp-e-story.md §2) is passed through as the params (flat), images get an `asset`
  name. Styles without a kit (terminal, blueprint, comic, ink) use the starter themes below.
- **Directed films**: use any `kit:base/<TYPE>` as a shot with the params in the table; set `theme`.
- Common params on every scene: `theme` ("base") · `accent` ("" — project `#RRGGBB`, overrides `--sr-accent` and
  derives `--sr-accent-ink/-hl/-glow`) · `label` (storyboard label; HOOK/FEATURE show it as the headline).
  Adapter-internal: `_captions` (captions are up: content lifts clear of the caption band, END moves its credit
  into the lockup), `_sync` (`{click, pass}` shot-local seconds: the FEATURE click / test-pass badge land on
  the beat-aligned timeline cue), `_mute` (sfx roles the shot must not emit; the timeline already places them).

## Data shapes (TimelineScene.data, verbatim content)
| type | data |
|---|---|
| HOOK | `{hero: {kind: image\|terminal\|diff\|code, ...}, label}` |
| TITLE | `{title, tagline, product, one_liner, hero?}` |
| PROBLEM | `{text, who?}` — the ask, typed into a chat bubble |
| PLAN | `{items: [{text, status: completed\|in_progress\|pending}], total}` |
| CODE | `{path, lang, lines, start, focus: [a, b], total_lines, new_file}` |
| DIFF | `{path, lang, hunks: [{header, lines: [[op, text]]}], adds, dels, truncated}` |
| TERMINAL | `{cmd, output: [str], exit_code, elapsed_s?, tests_passed?, tests_failed?}` |
| MONTAGE | `{items: [{id, t, kind, tool, arg, clipped}]}` (3-16) |
| SCREEN / FEATURE / SCROLL | `{image: {asset\|path, w, h, url, page_title, full_page}, bbox, click (FEATURE), feature (FEATURE), scroll (SCROLL)}` |
| STATS | `{stats: [{key, value, label, display}]}` |
| BEFORE_AFTER | `{before: content, after: content}` (content = HOOK hero shape) |
| CALLOUT | `{text, who}` |
| END | `{title, cta, url, credit, pb?: {time, label}}` (speedrun adds the PB) |

## Scenes
<!-- scenes:begin -->
| id | what it shows | params (default) |
|---|---|---|
| `kit:base/BEFORE_AFTER` | The money shot: before and after in one frame; a handle wipes across to reveal the after state. | `before` — — {kind: image\|terminal\|diff\|code, ...} · `after` — — {kind: image\|terminal\|diff\|code, ...} |
| `kit:base/CALLOUT` | One quotable line, verbatim: emphasis-font quote words rise, accent rule, mono attribution; near-still camera. | `text` "" — verbatim quote (<= 12 words ideal) · `who` "agent" — user \| agent \| test · `ref` "" — event id |
| `kit:base/CODE` | Editor panel: the real file streams in word by word, then the camera pushes to the focus lines and holds. | `path` "" — file path · `lang` "" — language id · `lines` [] — <= 18 verbatim lines · `start` 1 — first line number · `focus` [1, 1] — [a, b] focus line numbers |
| `kit:base/DIFF` | Diff panel: rows wipe in, deletions strike through, additions sweep an accent highlighter; camera pushes to the change. | `path` "" — file path · `lang` "" — language id · `hunks` [] — [{header, lines:[[op, text]]}] <= 24 rows · `adds` 0 — lines added · `dels` 0 — lines removed |
| `kit:base/END` | End card (thumbnail frame): title lockup, CTA command pill, URL and the "made with Hermes · Hype" credit; speedrun adds the PB time. | `title` "" — product name · `cta` "" — command or link to try it · `url` "" — repo / site URL · `credit` "made with Hermes · Hype" — small credit line · `tagline` "" — optional line under the title · `pb_display` "" — speedrun final time (shown as PB) |
| `kit:base/FEATURE` | Product frame + one feature: push to the region, the cursor arrives, pauses, clicks (ripple), an accent ring and the feature name land. | `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `feature` "" — feature name (<= 6 words), shown as the headline · `bbox` [0.1, 0.1, 0.8, 0.8] — feature region [x,y,w,h] (image fractions) · `click` [0.5, 0.5] — click point [x,y] (image fractions) |
| `kit:base/HOOK` | Scroll-stopper: the best real artefact (product capture, green test run, diff) tilts up out of a blur with a <= 6 word headline. | `hero` — — {kind: image\|terminal\|diff\|code, ...block data} |
| `kit:base/MONTAGE` | Breadth of the agent's work: real tool calls as cards on a rail; the camera whips card to card on the beat. | `items` [] — [{id, t, kind, tool, arg, clipped}] 3-16 tool calls |
| `kit:base/PLAN` | The agent's plan as a checklist card: done items tick in, the active item spins with a highlighter sweep. | `items` [] — [{text, status}] <= 6 (status: completed\|in_progress\|pending) · `more` 0 — hidden items count |
| `kit:base/PROBLEM` | The user's request as a chat card; the prompt types in letter by letter (human input) under a slow push. | `text` "" — verbatim prompt (redacted) · `truncated` false — adds an ellipsis |
| `kit:base/SCREEN` | Real screenshot in a browser frame: establish wide, push to the focus box (>= 1.4x), hold with drift. | `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `bbox` [0.1, 0.1, 0.8, 0.8] — focus box [x,y,w,h] as image fractions |
| `kit:base/SCROLL` | Smooth scroll through a full-page product capture inside a browser frame. | `image` — — {asset, path, w, h, url, page_title, full_page} (asset = film asset name) · `scroll` [0, 1] — [from, to] scroll fractions |
| `kit:base/STATS` | Real session numbers only: 1-3 big numerals count up on the drop, mono labels, accent rule under the hero number. | `stats` [] — [{key, label, value, display}] 1-3, computed from the session (never invented) |
| `kit:base/TERMINAL` | Dark terminal panel: the command types, output streams line by line, a PASS / exit badge pops. | `cmd` "" — command line · `output` [] — <= 12 output lines · `truncated_top` false — output was cut at the top · `exit_code` — — exit code · `elapsed_s` — — runtime seconds · `ok` true — run succeeded · `tests_passed` false — shows the PASS badge + chime |
| `kit:base/TITLE` | Name + thesis: eyebrow, huge kinetic title, tagline with one emphasis word; optional product hero beside it. | `title` "" — product / film title · `tagline` "" — <= 10 words · `product` "" — product name (used when title is empty) · `one_liner` "" — unused on screen (VO material) · `eyebrow` "Introducing" — small mono line above the title ("" hides it) · `hero` — — optional product visual {kind:image\|terminal\|code\|diff, ...} |
<!-- scenes:end -->

## Cues emitted (role names, resolved per style by assets/audio/sfx/sfx.json)
`type` (key ticks while code/commands/chat type), `click` (FEATURE press, with the cursor dip), `pass` / `fail`
(test badge), `hit` (STATS numbers land), `appear` (cards, pills, headlines), `move` (camera pushes, whips).

## Theme tokens
Define these on `.sr-theme-<name>` (the scene root is `.srb.sr-theme-<name>`); defaults live in `base.css`
(`:where(.srb)`), so a theme only states what it changes. Register the stylesheet text with
`registerTheme(name, cssText)` from `kits/base/kit.js` (style kits: import `'../base/kit.js'`, declare
`"requires": ["base"]` in kit.json). Later registrations of the same name win.

| token | role |
|---|---|
| `--sr-stage`, `--sr-stage-bg` | stage colour and its background image/gradient |
| `--sr-grid`, `--sr-grid-size` | background dot grid colour (transparent = none) and pitch |
| `--sr-vignette` | stage vignette gradient |
| `--sr-fg`, `--sr-fg-2`, `--sr-fg-3` | type on the stage: primary, secondary, tertiary |
| `--sr-accent` | THE one accent (rules, carets, emphasis word, add-highlighter edge, badges, rings) |
| `--sr-accent-ink`, `--sr-accent-hl`, `--sr-accent-glow` | text on accent fills; highlighter tint; glow |
| `--sr-paper`, `--sr-paper-2`, `--sr-rule` | panel surface, panel bars/chrome, hairlines |
| `--sr-ink`, `--sr-ink-2`, `--sr-ink-3`, `--sr-tone` | text on panels: primary, secondary, gutter/comments, strings |
| `--sr-term`, `--sr-term-2`, `--sr-term-rule`, `--sr-term-ink`, `--sr-term-dim` | the terminal panel |
| `--sr-del-hl`, `--sr-fail` | deleted-row tint; failure colour (fail badge, failing lines) |
| `--sr-plate`, `--sr-plate-ink` | small plates (tags, HUD) |
| `--sr-scrim-rgb` | stage colour as `R G B` for legibility scrims behind overlay type |
| `--sr-f-sans`, `--sr-f-mono`, `--sr-f-display`, `--sr-f-em` | font families: UI/body, code, display titles, emphasis word |
| `--sr-w-display`, `--sr-track-display`, `--sr-lead-display`, `--sr-case-display` | display title weight, tracking, leading, text-transform |
| `--sr-w-h1`, `--sr-track-h1` | headline weight, tracking |
| `--sr-em-style`, `--sr-em-weight`, `--sr-em-scale`, `--sr-em-color`, `--sr-em-track` | the single emphasis word |
| `--sr-label-track`, `--sr-w-num` | mono label tracking; numeral weight (STATS) |
| `--sr-r-panel`, `--sr-r-card`, `--sr-r-pill` | corner radii |
| `--sr-panel-edge`, `--sr-panel-shadow`, `--sr-term-edge`, `--sr-sheen` | panel edge ring, drop shadow, terminal edge, sheen sweep |

Component classes a theme may restyle further (keep sizes: layout is measured from them): `.srb-display`,
`.srb-h1`, `.srb-em`, `.srb-eyebrow`, `.srb-label`, `.srb-rule`, `.srb-panel`, `.srb-term`, `.srb-bar`,
`.srb-row(.add|.del|.focus|.hunk)`, `.tk-k/.tk-f/.tk-s/.tk-c/.tk-n` (syntax), `.srb-badge(.pass|.fail)`,
`.srb-chip(.add|.del)`, `.srb-pill`, `.srb-card`, `.srb-browser`, `.srb-urlbar`, `.srb-tag(.after)`,
`.srb-num`, `.srb-credit`, `.srb-urltext`.

### Starter themes (kits/base/themes/*.css, registered by kits/base)
| theme | look |
|---|---|
| `base` | neutral graphite stage, paper panels, cool blue accent (defaults) |
| `terminal` | phosphor green on black, every face mono, square corners, glow on type |
| `blueprint` | white linework on blueprint blue with a drafting grid, outlined translucent sheets, yellow pencil accent |
| `comic` | cream halftone stage, 5 px ink outlines with hard offset shadows, heavy uppercase display, red accent |
| `ink` | sumi ink on warm rice paper, serif-italic display, soft paper panels, vermilion seal accent |
Style owners can replace a starter theme by registering the same name from their kit.

## Building blocks — `ctx.kit('base')` / `import ... from '../base/kit.js'`
`blocks`: `codeBlock(data, {width, fontSize, reveal:[t0,t1], focusAt, wrap})`, `diffBlock(data, {...})`,
`pathBar(path, rightKids)`, `termBlock(data, {width, fontSize, typeAt, badgeAt, wrap})`, `termFont`, `termWidth`,
`browserBlock(ctx, img, {width, viewH, maxViewH})` (returns `{el, view, w, h, chromeH, rect(bbox), pt(x,y),
setScroll(u)}`), `deviceBlock`, `cursorBlock({from, to, arrive, press, travel})`, `ringBlock()`,
`chatBlock`, `planBlock`, `toolCard(item, {width, height})`, `kineticLine(text, {emphasis})` (`.update(t, t0,
{stagger, out})`), `kineticLetters`, `riseIn(el, t, t0, {out, rise})`, `statsBlock`, `ctaPill(cmd)`,
`contentBlock(ctx, content, {width, maxH, ...})` (image/terminal/diff/code hero), `panelIn`, `titleSize`.
`scene`: `defineDomScene(id, {params, build(ctx, p, F) -> {render(t), cues}})` (frame `F = {el, bg, cam, ov, W, H,
k, portrait, safe, theme, caps}` in reference px at a 1080 short side), `flatCam`, `centerBox`.
`motion`: `seg`, `ease.*` (outQuint = cubic-bezier(.22,1,.36,1)), `pchip`, `spring`, `drift`, `entrance`.
`dom`: `h`, `css`, `registerTheme`, `accentVars`, `fitSize`. `TITLE_DEF`/`STATS_DEF`/`CALLOUT_DEF`/`END_DEF`
(from `scenes-titles.js`) let a style reuse the type layouts over its own world (kits/launch does).

Fonts: Geist, Geist Mono, Instrument Serif Italic (OFL, `fonts/`), loaded through kit.json.
