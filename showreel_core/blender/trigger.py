"""Does the user ask for Blender? (``/auteur ... blender`` args are parsed in commands.py; this reads free text.)

``blender_requested("make it cinematic, use blender")`` -> True; ``"no blender please"`` -> False; no mention -> None.
A kitchen/smoothie blender (the product, not the engine) does not count.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9'’]+")
_NEGATIONS = {"no", "not", "without", "don't", "dont", "don’t", "never", "skip", "avoid", "except", "nor", "w/o"}
_NOT_ENGINE = {"kitchen", "smoothie", "juice", "food", "portable", "hand", "immersion", "countertop", "protein",
               "shaker"}
_ENGINE_AFTER = {"render", "renders", "rendering", "engine", "3d", "scene", "scenes", "shots", "film", "style", "cycles",
                 "eevee"}


def blender_requested(text: str | None) -> bool | None:
    """True/False when the text asks for / against the Blender engine, None when it does not say."""
    words = _WORD.findall(str(text or "").lower())
    verdict: bool | None = None
    for i, w in enumerate(words):
        if w != "blender":
            continue
        before = words[max(0, i - 3):i]
        prev = words[i - 1] if i else ""
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if prev in _NOT_ENGINE and nxt not in _ENGINE_AFTER:
            continue
        if any(b in _NEGATIONS for b in before):
            return False
        verdict = True
    return verdict
