"""Preset customization (docs/CUSTOMIZE.md): every preset reshaped by the user's request.

* ``knobs``   deterministic ``key=value`` settings (accent, palette, font, music, energy, voice, text, logo, ...)
* ``spec``    the small customization spec a model may write, its schema, validation/repair, keyword reader
* ``llm``     free text + the preset's Quick film -> spec (one call; weak-model and no-model fallbacks)
* ``route``   preset + text -> customize; no preset + text -> Directed; restructuring asks -> Directed
* ``theme``   the generic theme-override layer (film.json ``theme`` block -> every kit's tokens)
* ``apply``   spec + knobs -> Timeline edits and film.json edits
* ``command`` slash/tool/CLI/API entry points; ``hook`` the pipeline wiring (``install(run)``)

Submodules import lazily; this package imports nothing heavy.
"""
from __future__ import annotations

__all__ = ["apply", "command", "hook", "knobs", "llm", "route", "spec", "theme", "vocab"]
