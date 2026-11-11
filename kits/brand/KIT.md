# kit `brand` — customization overlays

Added by `showreel_core/customize` (docs/CUSTOMIZE.md); not a style.

| Scene | What | Params |
|---|---|---|
| `kit:brand/logo` | The user's logo as a small corner bug above every shot (eases in/out, inside the safe area). | `asset` — logo image asset · `corner` "top-right" — top-right \| top-left \| bottom-right \| bottom-left · `size` 84 — height px at a 1080 short side (max 28 % of the width) · `opacity` 0.92 |

Quick films get it from the `logo=<path>` knob: the image becomes asset `brand_logo` and one overlay spans the film.
