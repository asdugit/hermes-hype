"""Bed registry: style -> composition module with ``VARIANTS`` and ``compose(variant)``."""
from __future__ import annotations

import importlib
from types import ModuleType

STYLES = ("launch", "pixel", "cinematic", "terminal", "blueprint")
FAMILIES = ("dream", "pixel_boss", "comic", "ink")      # wave 3: mood beds and the comic/ink styles


def module(style: str) -> ModuleType:
    return importlib.import_module(f"{__name__}.{style}")


def all_beds() -> list[tuple[str, str]]:
    """[(style, variant)] for every composed bed."""
    out = []
    for st in STYLES + FAMILIES:
        try:
            mod = module(st)
        except ModuleNotFoundError:
            continue
        out += [(st, v) for v in mod.VARIANTS]
    return out
