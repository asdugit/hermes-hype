# Audio assets — provenance and licence

Every file under `assets/audio/` is an **original work generated procedurally by this repository's own
code** (`tools/compose/`, seeded and reproducible with `python -m tools.compose --all`, numpy + scipy,
dev-time only). There are **no samples, recordings, sample libraries, AI-model outputs or third-party
audio** in these files: every sound is synthesized from oscillators, noise and filters.

- `beds/<style>/<id>.ogg` — music beds (Opus in Ogg, 48 kHz stereo, ~96 kb/s), mastered to about −16 LUFS,
  true peak ≤ −1.5 dBTP. `beds/<style>/bars.json` holds the bar map (bpm, sections, drop/end bars) used by
  the runtime bar-fitter (`showreel_core/audio/music.py`).
- `sfx/*.ogg` + `sfx/sfx.json` — the SFX kit, loudness-normalised (−18 LUFS short-term max), with sync points.
- The acoustic/band voices of the dream, pixel_boss, comic and ink beds (piano, strings, choir, glockenspiel,
  harp, marimba, brass, slap bass, ukulele, pizzicato) are additive/subtractive/physical models in
  `tools/compose/orchestra.py` — synthesized like everything else, no sampled instruments.

Licence: same as the repository (see `LICENSE`), © the Auteur authors.

Method credits (no code copied): the synthesis approach (PolyBLEP oscillators, sync-point SFX placement,
loudness-normalised SFX, master chain with true-peak verification) was informed by reading **mgaudio**
(MIT, © 2026 Vincentwei1021, `mg-styles-15/lib/audio`) and **claude-motion `sfx`** (MIT). The NES-style
LFSR noise and 4-bit triangle follow the publicly documented behaviour of the 2A03 sound chip.
