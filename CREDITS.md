# Credits and third-party notices

Hype is © 2026 asdugit and the Hype contributors, licensed AGPL-3.0-or-later (see `LICENSE`).
Everything not listed below is original to this repository.

## Bundled third-party code

| Component | Version | Licence | Where | Licence file |
|---|---|---|---|---|
| three.js (core + a few `examples/jsm` modules, unmodified) | r170 (npm three@0.170.0) | MIT | `vendor/three/` | `vendor/three/LICENSE` |
| Rough.js (upstream IIFE bundle + an ES-module default export) | 4.6.6 | MIT | `kits/ink/vendor/rough.mjs` | `kits/ink/vendor/LICENSE-roughjs.txt` |

## Fonts (SIL Open Font License 1.1)

Each font ships next to its licence text (`OFL-<Family>.txt`) in the kit that uses it.

| Family | Kits |
|---|---|
| Geist, Geist Mono, Instrument Serif | `base` (shared by launch and the other kits) |
| IBM Plex Mono | `blueprint`, `cinematic`, `terminal` |
| Space Grotesk | `blueprint` |
| Cormorant Garamond | `cinematic` |
| Bangers, Comic Neue, Space Mono | `comic` |
| Caveat, Fraunces, Inter, JetBrains Mono | `ink` (JetBrains Mono also in `terminal`) |
| Departure Mono, Press Start 2P, Silkscreen | `pixel` |
| VT323 | `terminal` |

## Music and sound effects

All music beds and sound effects in `assets/audio/` are original works generated procedurally by this
repository's own code (`tools/compose/`, numpy + scipy at development time only). There are no samples,
recordings, sample libraries, AI-model outputs or third-party audio in them; see `assets/audio/LICENSE.md`.

Method credits (no code copied): the synthesis approach was informed by reading **mgaudio** (MIT,
© 2026 Vincentwei1021) and **claude-motion `sfx`** (MIT). The NES-style noise and triangle voices follow the
publicly documented behaviour of the 2A03 sound chip.

## Art

Pixel sprites, scene art, the ink robot, comic panels and every other visual in the kits are drawn in code in
this repository. Style previews (`assets/previews/`) and the README media (`docs/media/`, `docs/screenshots/`)
were rendered by Hype itself. The products shown in them are test media made for this project: the red car
is an original procedural three.js model, and "Focusfox" and "Tiny Todo" are synthetic sample apps.

## Runtime tools (not bundled)

Hype drives tools you already have: Chromium (Hermes-managed or your installed Chrome/Edge), ffmpeg
(Hermes-managed or yours) and, optionally, your own Blender. None of them is bundled or downloaded by the plugin.
