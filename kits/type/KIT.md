# Type kit (`kit:type/*`) — overlay type above shots

Transparent, screen-space DOM overlays for `film.overlays` (they render above all shots, below captions). Theme
tokens come from the shot's style (`theme`, optional project `accent`), so the same overlay reads as launch,
terminal, blueprint, comic or ink. Each overlay enters with rise + unblur (outQuint, ~0.5 s, staggered words),
exits faster (0.3 s) before its `t1`, and lays out natively for 9:16 (centre safe band). Over bright pictures a
stage-coloured `scrim` (radial / left / bottom gradient, animated with the type) keeps every line legible.

## Recipes
```jsonc
"overlays": [
  {"id": "t", "t0": 3.0, "t1": 6.0, "scene": "kit:type/title", "params": {"text": "Ship the timer tonight", "eyebrow": "Focusfox", "theme": "launch"}},
  {"id": "who", "t0": 9.0, "t1": 12.0, "scene": "kit:type/lower-third", "params": {"title": "Hermes Agent", "sub": "wrote, tested and shipped it"}},
  {"id": "cta", "t0": 40.0, "t1": 45.0, "scene": "kit:type/cta", "params": {"text": "npx serve focusfox", "label": "Try it"}}
]
```
- Quick mode adds `kit:type/speedrun-timer` automatically in speedrun mode (until the END card).
- Keep overlays off shots that already carry a headline (HOOK/FEATURE/TITLE/END) — one message at a time.

## Scenes
<!-- scenes:begin -->
| id | what it shows | params (default) |
|---|---|---|
| `kit:type/cta` | Call-to-action pill: "$ command" (or a link) in mono with an accent caret, optional label above. | `text` "" — command or URL · `at` "bottom" — bottom \| center · `scrim` 0.62 — darkening behind the type for legibility over bright picture (0 = none) |
| `kit:type/end-lockup` | End lockup overlay: product name, tagline, CTA pill, URL and the small credit line (thumbnail frame). | `title` "" — product name · `tagline` "" — one line · `cta` "" — command / link · `url` "" — URL · `credit` "made with Hermes · Auteur" — credit line · `scrim` 0.55 — darkening of the picture behind (0..1) |
| `kit:type/kinetic` | Kinetic words: lines appear one at a time (each leaves before the next arrives); rise, blur or slam. | `lines` [] — lines (<= 7 words each); or use text · `text` "" — single line alternative to lines · `style` "rise" — rise \| blur \| slam · `emphasis` "auto" — 'auto', word index or -1 · `align` "center" — center \| left · `scrim` 0.62 — darkening behind the type for legibility over bright picture (0 = none) |
| `kit:type/lower-third` | Lower third: accent bar + name + one line, slides in at the bottom-left (bottom band on 9:16). | `title` "" — name / label (<= 5 words) · `sub` "" — detail line (<= 9 words) |
| `kit:type/speedrun-timer` | Speedrun HUD (compact corner plate): live session clock (time-lapse of the real session) and the latest split, which swaps in at its film time. | `splits` [] — [{label, session_t, film_t}] film_t relative to this overlay · `total_s` 0 — real session duration (final time) · `title` "" — run name (product) |
| `kit:type/title` | Kinetic title card over the picture: optional eyebrow, a big line (one emphasis word), optional sub line. | `text` "" — main line (<= 7 words) · `sub` "" — secondary line (<= 10 words) · `eyebrow` "" — small mono caps line above · `align` "center" — center \| left · `emphasis` "auto" — 'auto' (last long word), word index, or -1 for none · `size` 0 — font px at 1080p (0 = fit) · `scrim` 0.62 — darkening behind the type for legibility over bright picture (0 = none) |
<!-- scenes:end -->
