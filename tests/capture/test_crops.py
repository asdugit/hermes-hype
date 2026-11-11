"""Safe picture crops (capture.crops): never a strip, always >= 55 % of the picture, aspect 0.75-1.8."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.capture.crops import (ASPECT_RANGE, MIN_AREA, WHOLE, is_safe, picture_crop, safe_crop,
                                         saliency_centre)


def _aspect(box: list[float], w: float, h: float) -> float:
    return (box[2] * w) / (box[3] * h)


@pytest.mark.parametrize("w,h", [(1920, 1080), (1440, 1377), (1080, 1920), (1600, 1200), (1000, 1000)])
def test_crop_keeps_shape_and_area(w: int, h: int) -> None:
    for centre in ((0.5, 0.5), (0.05, 0.95), (0.9, 0.1)):
        box = safe_crop(w, h, centre=centre)
        assert is_safe(box, w, h)
        assert box[2] * box[3] >= MIN_AREA - 1e-3
        assert ASPECT_RANGE[0] - 1e-3 <= _aspect(box, w, h) <= ASPECT_RANGE[1] + 1e-3
        assert box[0] >= 0 and box[1] >= 0 and box[0] + box[2] <= 1.0001 and box[1] + box[3] <= 1.0001


def test_strip_pictures_are_shown_whole() -> None:
    # a 5:1 row of heads: any allowed crop would be < 55 % of it -> the whole picture, never a sliver
    assert safe_crop(1800, 360) == WHOLE
    assert safe_crop(360, 1800) == WHOLE
    # 2.2:1 still allows a full-height crop of 1.8:1 (82 % of the area)
    box = safe_crop(2200, 1000)
    assert box[3] == 1.0 and is_safe(box, 2200, 1000)


def test_a_requested_strip_becomes_a_safe_crop() -> None:
    # the model asked for a thin band at the eyes ([0.04, 0.4, 0.6, 0.6] of a strip, or a 0.9 x 0.15 band)
    box = safe_crop(1920, 1080, want=[0.05, 0.42, 0.9, 0.15])
    assert is_safe(box, 1920, 1080)
    assert abs((box[1] + box[3] / 2) - 0.495) < 0.25          # still near the band's centre
    assert not is_safe([0.05, 0.42, 0.9, 0.15], 1920, 1080)


def test_bad_input_is_the_whole_picture() -> None:
    assert safe_crop(None, 0) == WHOLE
    assert safe_crop("x", "y") == WHOLE
    assert picture_crop({"path": "missing.png"}) == WHOLE


def test_saliency_pulls_toward_detail(tmp_path: Path) -> None:
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 450), (20, 20, 24))
    d = ImageDraw.Draw(im)
    for k in range(40):                       # detail only in the right third
        x = 560 + (k * 37) % 220
        y = 40 + (k * 53) % 360
        d.rectangle([x, y, x + 18, y + 12], fill=(230, 120 + k * 3, 40))
    p = tmp_path / "right_detail.png"
    im.save(p)
    cx, cy = saliency_centre(str(p))
    assert cx > 0.6                           # toward the detail, pulled back toward the centre
    box = picture_crop({"path": str(p), "w": 800, "h": 450})
    assert is_safe(box, 800, 450) and box[0] > 0.1
