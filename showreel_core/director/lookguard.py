"""Look guard: engine-enforced exposure / contrast on what the viewer will actually see.

The mood grade (noir: black and white + hard contrast + rain; VHS tape...) runs over every frame, and a dark-theme
product inside a dark world (Tempo's dark timer UI in the cinematic noir room) came out grey-on-grey and murky: the
product barely separated from the room, the whites never reached white. Prompts cannot fix that and weak models never
notice it, so the engine measures the GRADED keyframes and sets the grade's ``levels`` ([black, white, gamma],
render/post.py ``levels_curve``) so that, across the film:

- highlights reach near-white (white point = the measured median p99 of the content frames, gain capped);
- lifted, milky blacks go black (black point from the measured p1, capped) - noir stays inky, never grey;
- the product's mid-tones come up to a mood-dependent floor (noir may stay darker than a keynote, never murky).

Pure measurement + arithmetic (PIL when present; no PIL -> no change). One film-wide setting, so shots stay matched.
"""
from __future__ import annotations

import io
import math
from collections.abc import Sequence
from typing import Any

WHITE_TARGET = 240.0        # 0..255: where the film's typical highlight should land
MAX_GAIN = 1.45             # never stretch the highlights more than this (noise, banding)
BLACK_LIFTED = 18.0         # a typical p1 above this reads as milky blacks
MAX_BLACK = 34.0            # never crush more than this
MAX_GAMMA = 1.7             # never lift the mids more than this
DARK_FRAME_P99 = 28.0       # a keyframe whose p99 is below this is a dip / black card: not measured
MID_TARGET = {"noir": 0.17, "default": 0.27}   # floor for the product frames' median luma (0..1) after levels


def luma_stats(img: bytes) -> dict[str, float] | None:
    """Luma (0..255) percentiles of a keyframe at low resolution: p1/p5/p50/p95/p99/p995 + mean over the frame,
    and ``mid`` = the median of the centre (where the product sits: the middle 60 % x 70 %), so a big black room
    around a product does not read as a dark product. None when unreadable."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(img)).convert("L").resize((160, 90))
    except Exception:  # noqa: BLE001 - PIL missing or an undecodable frame
        return None

    def pcts(hist: list[int], qs: Sequence[float]) -> list[float]:
        n = float(sum(hist)) or 1.0
        out = []
        for q in qs:
            acc = 0.0
            val = 255.0
            for i, c in enumerate(hist):
                acc += c
                if acc >= q * n:
                    val = float(i)
                    break
            out.append(val)
        return out
    hist = im.histogram()
    n = float(sum(hist)) or 1.0
    p1, p5, p50, p95, p99, p995 = pcts(hist, (0.01, 0.05, 0.5, 0.95, 0.99, 0.995))
    mid = pcts(im.crop((32, 13, 128, 76)).histogram(), (0.5,))[0]
    mean = sum(i * c for i, c in enumerate(hist)) / n
    return {"p1": p1, "p5": p5, "p50": p50, "p95": p95, "p99": p99, "p995": p995, "mid": mid, "mean": mean}


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def plan_levels(stats: Sequence[dict[str, float] | None], product: Sequence[bool] = (), *,
                mood: str = "") -> tuple[list[float] | None, dict[str, Any]]:
    """Film-wide ``[black, white, gamma]`` from per-keyframe stats (None = leave the grade alone) + a report.

    ``product``: per keyframe, True when the product is meant to be on screen (its mids get the floor)."""
    rows = [(s, (product[i] if i < len(product) else True)) for i, s in enumerate(stats)
            if s is not None and s["p99"] >= DARK_FRAME_P99]
    report: dict[str, Any] = {"frames": len(rows)}
    if len(rows) < 2:
        return None, {**report, "why": "too few lit keyframes to measure"}
    w = _median([s.get("p995", s["p99"]) for s, _ in rows])
    b = _median([s["p1"] for s, _ in rows])
    mids = [s.get("mid", s["p50"]) for s, p in rows if p] or [s.get("mid", s["p50"]) for s, _ in rows]
    m = _median(mids)
    report.update(white_p99=round(w, 1), black_p1=round(b, 1), product_mid=round(m, 1))
    gain = max(1.0, min(MAX_GAIN, WHITE_TARGET / max(w, 1.0)))
    white = 1.0 / gain
    black = 0.0
    if b > BLACK_LIFTED:
        black = min(b, MAX_BLACK) * 0.85 / 255.0
    mid = max(1e-3, min(1.0, (m / 255.0 - black) / max(1e-3, white - black)))
    target = MID_TARGET["noir" if mood == "noir" else "default"]
    gamma = 1.0
    if mid < target:
        gamma = max(1.0, min(MAX_GAMMA, math.log(mid) / math.log(target)))
    report.update(gain=round(gain, 3), mid_after=round(mid ** (1.0 / gamma), 3), target_mid=target)
    if gain < 1.04 and black < 0.01 and gamma < 1.04:
        return None, {**report, "why": "exposure already fine"}
    return [round(black, 3), round(white, 3), round(gamma, 3)], report


def apply_levels(film: dict[str, Any], levels: list[float] | None) -> bool:
    """Put ``levels`` into the film's grade (adding the ``grade`` post chain when the film has none)."""
    rend: dict[str, Any] = film["render"] if isinstance(film.get("render"), dict) else {}
    pp: dict[str, Any] = dict(rend.get("post_params") or {})
    grade: dict[str, Any] = dict(pp.get("grade") or {})
    if levels is None:
        if "levels" not in grade:
            return False
        grade.pop("levels")
    else:
        grade["levels"] = list(levels)
    pp["grade"] = grade
    chains = [c for c in str(rend.get("post") or "").split("+") if c and c != "none"]
    if levels is not None and "grade" not in chains:
        chains.append("grade")
    film["render"] = {**rend, "post": "+".join(chains) or "none", "post_params": pp}
    return True
