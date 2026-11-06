# Kit `cinematic` — "evidence becomes a world"

The session's real captures (code, diff, terminal, screenshots, plan, prompt, tool calls) are emissive glass cards
floating at different depths in a dark room. A heavy camera travels between them and racks focus; dust becomes
bokeh; one warm amber accent; 2.39 letterbox with the **session-clock rail** in the bottom bar; Cormorant Garamond
titles (caps, wide tracking) and italic captions, Geist labels, Geist Mono CTA. Ported from the approved style frames
(styleframes/cinematic). All scenes are `layer: 'three'`, pure functions of t. Requires kits `base` (fonts, media
helper) and `three`. Strings come verbatim from the scene data; ambient "ghost" cards are abstract (no fake text).

## Scenes — the 15 Quick-mode types (`kit:cinematic/<TYPE>`, params = TimelineScene.data shapes, wp-e-story §2)
| id | look and move |
|---|---|
| `kit:cinematic/HOOK` | `{hero:{kind: image\|terminal\|diff\|code, ...}, label}` — hero capture lit and close; log-space push through near motes, focus pulls mote → card; ≤ 6-word italic label |
| `kit:cinematic/TITLE` | `{title, tagline, product, one_liner}` — corridor of cards on both walls; wide-tracked title + italic tagline; slow creep forward |
| `kit:cinematic/PROBLEM` | `{text, truncated}` — the prompt card alone, emission fades up; near-static |
| `kit:cinematic/PLAN` | `{items:[{text,status}], more}` — plan card, active item glows; lateral truck past a constellation |
| `kit:cinematic/CODE` | `{path, lang, lines, start, focus}` — 3/4 code card, amber focus gutter; rack focus then push ×1.4 to the focus lines |
| `kit:cinematic/DIFF` | `{path, hunks, adds, dels}` — `−` dim + struck, `+` warm with amber gutter; slow 8° orbit |
| `kit:cinematic/TERMINAL` | `{cmd, output, exit_code, ok}` — lone terminal; push then hold; PASS/✓ line ramps 1→2.4× so it blooms |
| `kit:cinematic/MONTAGE` | `{items:[{tool, arg}]}` — tool chips at many depths; fast lateral dolly, focus snaps chip to chip |
| `kit:cinematic/SCREEN` | `{image, bbox}` — screenshot card 3/4 → frontal swing, ×1.15 push to the bbox; kicker · italic caption (label) · URL |
| `kit:cinematic/FEATURE` | `{image, feature, bbox, click}` — as SCREEN with the feature line as caption |
| `kit:cinematic/SCROLL` | `{image, scroll:[from,to]}` — tall capture scrolls inside its card |
| `kit:cinematic/STATS` | `{stats:[{label, display}]}` (≤ 4) — huge Cormorant numbers between two defocused cards; no counting |
| `kit:cinematic/BEFORE_AFTER` | `{before, after}` (content dicts) — before far/cold, after near/warm; focus racks with one light flare |
| `kit:cinematic/CALLOUT` | `{text, who}` — centred italic quote, faint source glow behind; longest hold |
| `kit:cinematic/END` | `{title, cta, url, credit}` — pull back out of the corridor; title, CTA pill, URL, credit |

Extra scenes: `kit:cinematic/card-field` (`{cards:[{kind, ...data}], hero, move: dolly|truck|orbit, title?, tagline?}` —
any real content as a world) and `kit:cinematic/screen-push` (`{image, bbox, caption, kicker, url}`).

Common params: `label`, `quality` (`auto` = half-res plate + 12-tap DOF on SwiftShader), `rail` (`{from, to, ticks, label}`
— session progress 0..1 over the shot; omit to hide), `register` (show `● CAPTURED · SESSION`, default true).

### Overlay: `kit:cinematic/lockup` (end title over any picture, transparent)
Product name in wide-tracked Cormorant caps rising letter by letter with a light sweep, accent hairline, italic tagline,
CTA pill with an arrow; soft plum scrim for bright pictures. Params: `title` · `tagline` · `cta` · `eyebrow` ·
`at` upper\|center\|lower · `cta_at` stack\|bottom (bottom: the product sits between title and CTA) · `accent`
(product colour) · `scrim` 0.5 · `hold`. Put it in `film.overlays` over `kit:nature/product-hero` (`title: "top"`).
Recipe: kits/nature/RECIPES.md §5.

## Building blocks — `ctx.kit('cinematic')`
`cards` (painters: `codeCard, diffCard, terminalCard, planCard, promptCard, screenshotCard, chipCard, ghostCard,
mediaCard`), `makeCine(ctx, {items, cam(t), focus(t), overlay(g,t,F), overlayKey(t), flare(t), ...})` (the world),
`rig(keys, t)` (keyed camera with breathing), `type` (`title, italic, label, register, rail, stats, cta`).

## Performance (i5-14490F + RX 6800 XT, 1080p, real runtime, 8 s CODE+SCREEN clip = 240 frames)
GPU: 14.7 s video render (17.0 s total); SwiftShader (`--disable-gpu`, auto low tier, 0.67 plate): 38.7 s (40.7 s total).

## Notes
- Type is painted into an overlay texture (not registered with the runtime's text QA); sizes follow the style
  guide (title 132 px, captions ≥ 52 px at 1080p).
- Use `dip-black` (0.5 s) between acts; this kit's `finish` is built in (grain/vignette in-scene), so keep the film
  finish at 0 for these shots.
