# Device kit (`blender:device/*`) — software products on premium 3D hardware (Blender)

The most common Hermes product is software (web app, dashboard, CLI with a UI). In Blender mode this kit puts the
product's REAL captures (screenshots, capture video, full-page captures from the capture stage) on procedural,
logo-free slim-bezel devices — laptop, phone, tablet, monitor — in a dark product studio, with smooth C2 camera
splines (position, velocity and acceleration continuous; frame 1 is already moving) and focus riding the screen.

**Screens are UI-exact.** Device scenes render with the Standard view transform and a screen material whose
texture colourspace matches the view (`lib.materials.screen`, re-synced by `studio.finalize`). Measured on a
24-patch UI chart (EEVEE): Standard Δ = 0.0/255 (exact); AgX would shift white to 197 and saturated accents by up
to 141, so never switch a device scene to AgX. Screens have no glossy coat by default (`glare` 0): a reflection
on a Standard-view screen clips to magenta/white. Captures are cover-fit top-aligned, never mirrored, never keyed.

Media resolution (every scene): explicit param (asset name, path or the story's `{asset|path,w,h,...}` image dict)
→ job asset named `desktop*`/`screen*`/`capture*`/`image*`/`hero*` (wide) or `mobile*` (portrait) or `full*`
(long page) → shape match → the job's 2D product. Theme colour (`theme_color`/`accent` on any asset) drives
`env: accent` and the click ripple.

## Scenes
| id | Quick type | what it shows | key params (default) |
|---|---|---|---|
| `blender:device/device_hero` | TITLE / HOOK | Out of darkness the laptop lid opens (phone: rises + turns) and the screen lights up with the real UI; rims first, a strip light sweeps the aluminium; eased arc + dolly. | `media` · `mobile` · `device` auto · `entrance` auto(open/rise/turn) · `env` studio · `reveal` true · `screen_on` 0.42 · `orbit_deg` 18 · `push` 0.16 · `fill` 0.62 · `side` left |
| `blender:device/device_feature` | FEATURE / SCREEN | Whole device → one eased push that lands EXACTLY on the feature rect (screenshot px → world), slow drift after; optional cursor glide + click ripple in the accent. | `image` · `bbox` [x,y,w,h] fractions · `click` [x,y] or null · `fill` 0.62 · `angle` 14 · `push_at` 0.62 · `click_at` 0.7 · `device` auto · `env` · `side` |
| `blender:device/device_scroll` | SCROLL | A full-page capture scrolls (trackpad ease, holds at both ends) on the laptop / phone while the camera drifts in a slow arc. | `image` · `scroll` [0,1] · `hold` 0.12 · `drift_deg` 14 · `fill` 0.78 · `device` auto · `env` · `side` |
| `blender:device/device_trio` | MONTAGE / HOOK alt | Laptop + phone (+ tablet / monitor) family shot, each screen with the matching capture (desktop / mobile); slow orbit + push. | `devices` laptop+phone · `media` · `mobile` · `orbit_deg` 16 · `push` 0.1 · `reveal` false · `env` |
| `blender:device/device_end` | END | Calm lockup: device 3/4 on one side, the other side clean and dark for the browser title / CTA / URL overlay; push settles to a stop on the last frame. | `space` auto(left in 16:9, top in 9:16) · `size` 0.46 · `push` 0.05 · `dim_bg` 0 · `media` · `device` auto · `env` |

Common: `env` = `studio` (graphite cyc, soft floor reflection) | `light` (bright white) | `sunset` (warm) |
`accent` (dark cyc pooled in the product's theme colour). `device: auto` = laptop in 16:9; phone in 9:16 when a
mobile capture exists (else a closer, higher laptop framing). Every scene has its own 9:16 framing, `cues()`,
deterministic animation (seeded handheld drift only), and runs at any tier (`preview` EEVEE 24 spp, `final`
64 spp + motion blur, `max` = host's Cycles).

## Director notes
- Overlay text (titles, captions, CTA) is the browser's job: put `kit:type/*` overlays over these shots; leave
  `device_end.space` free for the lockup.
- For FEATURE use the capture whose aspect matches the device (1440×900 = 16:10 laptop screen exactly); `bbox`
  from the story is in image fractions; features below the fold of a tall capture are scrolled into view.
- `fill` 0.55-0.7 keeps context around a feature; > 0.8 reads as a flat screenshot (loses the 3D point).
- Timings: see research/w4-blender-studio.md (preview ~0.3 s/frame at 960×540 on an RX 6800 XT).
