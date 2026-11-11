"""Frame 0 of every preset's Quick film is its thumbnail (Hermes' preview, the X autoplay poster): it must be lit.
Real E2E: the terminal tube powered on from black (frame-0 luma 3.8), pixel opened on a black CRT (10.2).
Slow: one Chromium keyframe per style and aspect (no post chain, so the bound is a little above QA's 16)."""
from __future__ import annotations

import asyncio
import io

import pytest

from showreel_core.film.page import build_job
from showreel_core.film.quick import film_from_timeline

STYLES = ["launch", "cinematic", "pixel", "terminal", "blueprint", "comic", "ink"]


@pytest.mark.slow
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
@pytest.mark.parametrize("style", STYLES)
def test_quick_frame0_is_lit(style, aspect, tmp_path):
    from PIL import Image, ImageStat

    from showreel_core.film.preview import capture_keyframes
    from tests.kits.test_quick import MEDIA_MAP, _timeline

    made = film_from_timeline(_timeline(style=style, aspect=aspect), style=style, media_map=MEDIA_MAP)
    film = made["film"]
    job = build_job(film, tmp_path / "job", assets=made["assets"])
    w, h = film["size"]
    stills, info = asyncio.run(capture_keyframes(job, [0.0], w=w, h=h))
    assert not info["errors"], info["errors"]
    luma = ImageStat.Stat(Image.open(io.BytesIO(stills[0].png)).convert("L")).mean[0]
    assert luma >= 20, f"{style} {aspect}: frame 0 mean luma {luma:.1f} (thumbnail would read black)"
