"""Colour helpers: palette/dominant colour of a capture and the film accent choice (Pillow only)."""
from __future__ import annotations

import colorsys
import re
from typing import Any

from PIL import Image

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    m = HEX_RE.match((h or "").strip())
    if not m:
        return None
    v = m.group(1)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[int, ...]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(c))):02x}" for c in rgb[:3])


def sat_val(rgb: tuple[int, int, int]) -> tuple[float, float]:
    """HSV saturation and value (0..1)."""
    _, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return s, v


def is_accent_like(rgb: tuple[int, int, int] | None, *, min_sat: float = 0.3) -> bool:
    """Saturated and neither near-black nor near-white: usable as a brand/film accent."""
    if rgb is None:
        return False
    s, v = sat_val(rgb)
    return s >= min_sat and 0.25 <= v <= 0.99


def palette(img: Image.Image, n: int = 6) -> list[dict[str, Any]]:
    """Top ``n`` colours (median cut on a thumbnail) with their share of the image, largest first."""
    im = img.convert("RGB")
    im.thumbnail((160, 160))
    q = im.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    total = im.width * im.height or 1
    out = []
    for count, idx in sorted(q.getcolors() or [], reverse=True)[:n]:
        i = int(idx)  # type: ignore[arg-type]  # "P" images report palette indices
        rgb = (pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2])
        s, v = sat_val(rgb)
        out.append({"hex": rgb_to_hex(rgb), "share": round(count / total, 4), "sat": round(s, 3), "val": round(v, 3)})
    return out


def dominant_accent(pal: list[dict[str, Any]]) -> str:
    """Most prominent saturated colour of a palette (share x saturation), or ""."""
    best, score = "", 0.0
    for c in pal:
        rgb = hex_to_rgb(c["hex"])
        if c["share"] >= 0.004 and is_accent_like(rgb, min_sat=0.35):
            sc = c["share"] ** 0.5 * c["sat"]
            if sc > score:
                best, score = c["hex"], sc
    return best


def choose_accent(candidates: list[tuple[str, str | None]]) -> tuple[str, str]:
    """First accent-like colour of ``[(source, hex), ...]`` -> (hex, source); ("", "") if none."""
    for source, h in candidates:
        if h and is_accent_like(hex_to_rgb(h)):
            return h.lower(), source
    return "", ""


def luminance_stats(img: Image.Image) -> tuple[float, float]:
    """(mean, stddev) of luma on a thumbnail: blank-page / black-frame detection."""
    from PIL import ImageStat

    im = img.convert("L")
    im.thumbnail((256, 256))
    st = ImageStat.Stat(im)
    return st.mean[0], st.stddev[0]
