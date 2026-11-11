"""Safe focus crops for pictures that are not web pages (game/app screenshots, renders, image files).

A web capture has real DOM rects to push into. A picture does not: a crop picked by an edge window or by a
model can be a thin strip (a row of character heads cut at the eyes). Every crop of a picture made here keeps
a sane shape and most of the picture:

- crop aspect (in pixels) within ``ASPECT_RANGE`` (0.75 .. 1.8), and
- at least ``MIN_AREA`` (55 %) of the picture's area,
- centred on salient content (edge density, blended toward the centre: faces are unknown, the centre is the
  safest guess), or the whole picture when no crop can satisfy both rules.

Returned boxes are ``[x, y, w, h]`` image fractions, the Ken-Burns end frame of a ``card`` shot.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

ASPECT_RANGE = (0.75, 1.8)
MIN_AREA = 0.55
#: default crop area when the picture's own aspect is allowed (a gentle ~1.28x push)
DEFAULT_AREA = 0.62
WHOLE = [0.0, 0.0, 1.0, 1.0]


def saliency_centre(path: str | None, *, centre_pull: float = 0.5) -> tuple[float, float]:
    """Edge-density centroid of a picture (fractions), pulled toward the middle by ``centre_pull``; (0.5, 0.5)
    when the picture cannot be read."""
    try:
        from PIL import Image, ImageFilter  # lazy: Pillow is a Hermes core dependency
        with Image.open(str(path)) as im:
            g = im.convert("L")
        g.thumbnail((64, 64))
        e = g.filter(ImageFilter.FIND_EDGES)
        w, h = e.size
        px = list(e.tobytes())
        tot = sx = sy = 0.0
        for y in range(1, h - 1):           # the 1 px frame of FIND_EDGES is noise
            for x in range(1, w - 1):
                v = px[y * w + x]
                if v > 24:
                    tot += v
                    sx += v * (x + 0.5)
                    sy += v * (y + 0.5)
        if tot <= 0:
            return 0.5, 0.5
        cx, cy = sx / tot / w, sy / tot / h
        return 0.5 + (cx - 0.5) * (1 - centre_pull), 0.5 + (cy - 0.5) * (1 - centre_pull)
    except Exception:  # noqa: BLE001 - unreadable picture: the centre
        return 0.5, 0.5


def is_safe(box: Sequence[float], w: float, h: float) -> bool:
    """True when ``box`` (fractions) obeys the aspect and area rules for a w x h picture (or is the whole)."""
    try:
        x, y, bw, bh = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    if bw >= 0.999 and bh >= 0.999:
        return True
    if bw <= 0 or bh <= 0 or x < -1e-6 or y < -1e-6 or x + bw > 1.0001 or y + bh > 1.0001:
        return False
    a = (bw * w) / max(1e-6, bh * h)
    return ASPECT_RANGE[0] - 1e-3 <= a <= ASPECT_RANGE[1] + 1e-3 and bw * bh >= MIN_AREA - 1e-3


def safe_crop(w: Any, h: Any, *, centre: tuple[float, float] = (0.5, 0.5), want: Sequence[float] | None = None,
              area: float = DEFAULT_AREA) -> list[float]:
    """A crop of a w x h picture that obeys the rules, centred near ``centre`` (or the centre of a requested
    ``want`` box). Returns the whole picture when no allowed crop exists (a strip, a tiny picture)."""
    try:
        W, H = float(w), float(h)
    except (TypeError, ValueError):
        return list(WHOLE)
    if W <= 0 or H <= 0:
        return list(WHOLE)
    cx, cy = centre
    if want is not None:
        try:
            wx, wy, ww, wh = (float(v) for v in want)
            if ww > 0 and wh > 0:
                cx, cy = wx + ww / 2, wy + wh / 2
        except (TypeError, ValueError):
            pass
    A = W / H
    lo, hi = ASPECT_RANGE
    area = max(MIN_AREA, min(1.0, area))
    if lo <= A <= hi:
        s = math.sqrt(area)                       # same shape as the picture
        bw, bh = s, s
    else:
        a = min(hi, max(lo, A))                   # the closest allowed shape, as big as it fits
        if A > hi:
            bh, bw = 1.0, a / A
        else:
            bw, bh = 1.0, A / a
        if bw * bh < MIN_AREA:
            return list(WHOLE)                    # a strip: show all of it, never a sliver
    x = min(max(cx - bw / 2, 0.0), 1.0 - bw)
    y = min(max(cy - bh / 2, 0.0), 1.0 - bh)
    return [round(x, 4), round(y, 4), round(bw, 4), round(bh, 4)]


def picture_crop(img: dict[str, Any], want: Sequence[float] | None = None) -> list[float]:
    """The Ken-Burns end frame for a picture dict ``{path, w, h}`` (see module doc)."""
    w, h = img.get("w"), img.get("h")
    if not w or not h:
        try:
            from PIL import Image
            with Image.open(str(img.get("path") or "")) as im:
                w, h = im.size
        except Exception:  # noqa: BLE001
            return list(WHOLE)
    centre = saliency_centre(str(img.get("path") or "")) if want is None else (0.5, 0.5)
    box = safe_crop(w, h, centre=centre, want=want)
    return box if is_safe(box, float(w), float(h)) else list(WHOLE)
