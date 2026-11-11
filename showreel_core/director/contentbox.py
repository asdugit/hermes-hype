"""Content box of a product picture: where the product actually is inside its capture.

A game or app capture is often a small canvas in the middle of a big flat page (Brickfall: the neon canvas inside a
black page), so the "whole picture" shot showed the product at ~40 % of the frame width however large the card was.
The engine measures the region that differs from the picture's own border colour and points the shot's focus box
at it, so the Ken-Burns / push-in lands on the product, not on the margins. Pure PIL (optional: None without it).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DIFF = 26            # per-channel distance from the border colour that counts as content
MAX_SHARE = 0.62     # only refocus when the content covers less than this share of the picture
PAD = 0.04           # margin kept around the content (share of the picture)


@lru_cache(maxsize=64)
def content_box(path: str) -> tuple[float, float, float, float] | None:
    """[x, y, w, h] (fractions) of the content inside a flat border, or None when the picture fills itself / is
    unreadable / PIL is missing."""
    try:
        from PIL import Image, ImageChops
        im = Image.open(Path(path)).convert("RGB")
    except Exception:  # noqa: BLE001 - optional measurement
        return None
    w, h = im.size
    if w < 64 or h < 64:
        return None
    small = im.resize((160, max(16, round(160 * h / w))))
    sw, sh = small.size
    edge = [small.getpixel((x, 0)) for x in range(sw)] + [small.getpixel((x, sh - 1)) for x in range(sw)] + \
        [small.getpixel((0, y)) for y in range(sh)] + [small.getpixel((sw - 1, y)) for y in range(sh)]
    bg = tuple(sorted(c[i] for c in edge)[len(edge) // 2] for i in range(3))
    # the border must be one flat colour for this to mean anything (a page with content to its edges: no box)
    flat = sum(1 for c in edge if max(abs(c[i] - bg[i]) for i in range(3)) <= DIFF) / len(edge)
    if flat < 0.9:
        return None
    diff = ImageChops.difference(small, Image.new("RGB", small.size, bg)).convert("L")
    mask = diff.point(lambda v: 255 if v > DIFF else 0)
    bb = mask.getbbox()
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    share = ((x1 - x0) * (y1 - y0)) / float(sw * sh)
    if share >= MAX_SHARE or (x1 - x0) < sw * 0.08 or (y1 - y0) < sh * 0.08:
        return None
    fx0, fy0 = max(0.0, x0 / sw - PAD), max(0.0, y0 / sh - PAD)
    fx1, fy1 = min(1.0, x1 / sw + PAD), min(1.0, y1 / sh + PAD)
    return (round(fx0, 3), round(fy0, 3), round(fx1 - fx0, 3), round(fy1 - fy0, 3))
