# Showreel

Turn any Hermes Agent session into a finished promo video. Work in progress.

License: AGPL-3.0-or-later.

## Blender (optional 3D engine)

3D shots render in headless Chromium (three.js) by default. Add `blender` to `/showreel` (for example
`/showreel cinematic 60 blender`), say "use blender" in a free-text direction, or set the plugin setting
`engine_3d: blender` (or `auto`) to render them with **your own installed Blender 4.2+** instead: real 3D products,
smooth camera rigs, motion blur.

- **What runs:** Showreel starts your Blender as a subprocess, headless and with `--factory-startup` (your Blender
  preferences and add-ons are not loaded or changed), on a job file in the film's job folder. It renders frames into
  that folder; the browser renderer then composes them with the rest of the film. Cancelling a film stops only the
  Blender process Showreel started.
- **Finding Blender:** `SHOWREEL_BLENDER`, then the `blender_path` setting, then `blender` on PATH, then the usual
  install folders (including where the official Hermes `blender` plugin installs it). Showreel never downloads
  Blender. If none is found, the film falls back to the browser engine and the job log says so.
- **Time:** Blender is slower than the browser (about 0.5-1 s per 1080p frame with EEVEE on a desktop GPU); before
  the long render Showreel times 3 frames and shows the estimate. Rendered shots are cached by content, so a
  revision re-renders only the shots that changed.
- **Hand-built films:** `python -m showreel_core.blender.render_film FILM.json --out OUT.mp4 --tier final`
  renders a film.json whose shots use `"scene": "blender:<kit>/<scene>"` (scene modules in `blender_kits/`).
