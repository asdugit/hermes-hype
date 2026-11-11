"""Routing: which engine a ``/auteur`` request goes to.

The rule (docs/CUSTOMIZE.md):

1. No free text -> the preset (Quick film); ``key=value`` knobs apply.
2. A preset named (a style or the lore/speedrun mode as an option word at the start or end) + free text -> **customize** that preset (small validated
   LLM patches over its Quick film) ...
3. ... unless the text clearly asks for a different film than the preset can make: another style or world
   midway ("transition into a different style mid way", "then bloom into anime"), new invented scenes, or the
   Director by name -> **Directed** with the preset as the starting style (the existing behaviour).
4. Free text without a preset -> **Directed** (free roam).
5. ``directed`` / ``customize`` as the first or last word forces the route; ``use blender`` keeps working on
   every route (engine_3d), knobs apply on every route (Directed gets them as hints).
"""
from __future__ import annotations

import re

from .vocab import PRESETS

#: Phrases that need more than one preset can make (-> Directed).
RESTRUCTURE = [
    r"\btransition(s|ing)? (in)?to (a |an )?(different|another|new|other)\b",
    r"\b(different|another|second|new) (style|look|world|aesthetic)\b",
    r"\b(switch(es|ing)?|change[sd]?|morph(s|ing)?|turn(s|ing)?|bloom(s|ing)?|evolve[sd]?|transform(s|ing)?) "
    r"(in)?to\b",
    r"\b(mid[- ]?way|half[- ]?way|midpoint|middle of the film|part way)\b",
    r"\b(then|and then) (becomes?|goes|turns|switches|blooms|morphs)\b",
    r"\b(anime|meadow|flower field|nature world|3d world|open world)\b",
    r"\bfrom scratch\b", r"\b(free[- ]?roam|the director|direct it|new scenes?|custom scenes?|invent)\b",
    r"\b(mix|blend|combine|mash ?up) (of |the )?(styles?|presets?|looks?)\b",
]
_RE = [re.compile(p, re.I) for p in RESTRUCTURE]


def restructure_reason(text: str, preset: str = "", styles: set[str] | None = None) -> str:
    """Why the text needs Directed ("" = it is a customization of the preset)."""
    t = str(text or "")
    for rx in _RE:
        m = rx.search(t)
        if m:
            return f"asks for {m.group(0)!r}"
    others = {s for s in (styles or set(PRESETS)) if s != preset}
    named = [s for s in others if re.search(rf"\b{re.escape(s)}\b", t, re.I)]
    # "launch ... with a comic font" is a customization; "pixel and then cinematic" is two styles
    named = [s for s in named if not re.search(rf"\b{re.escape(s)}[- ](font|type|lettering|colou?rs?|palette|music|"
                                               rf"bed|vibe|feel|energy|style captions)\b", t, re.I)]
    if named:
        return f"names another style ({', '.join(sorted(named))})"
    return ""


def route(*, text: str, preset_named: bool, preset: str = "", force: str = "", styles: set[str] | None = None
          ) -> tuple[str, str]:
    """(``"quick"|"customize"|"directed"``, reason)."""
    if not str(text or "").strip():
        return "quick", "no free text"
    if force in ("directed", "customize"):
        return force, f"forced by '{force}'"
    if not preset_named:
        return "directed", "free text without a preset"
    why = restructure_reason(text, preset, styles)
    if why:
        return "directed", why
    return "customize", f"preset {preset or '?'} + free text"
