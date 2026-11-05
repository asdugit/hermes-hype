"""film.finish -> ffmpeg post chains, and the RenderSpec built for a job."""
from __future__ import annotations

from pathlib import Path

from showreel_core.film.page import build_job
from showreel_core.film.render import post_for_finish, render_spec


def test_post_for_finish():
    assert post_for_finish(None) == ("none", {})
    assert post_for_finish({"grain": 0.04, "vignette": 0.25}) == (
        "grain_vignette", {"grain_vignette": {"grain": 7, "vignette": 0.25}})
    chain, params = post_for_finish({"bloom": 0.5, "vignette": 0.3})
    assert chain == "bloom+grain_vignette" and params["bloom"] == {"amount": 0.5}
    assert params["grain_vignette"]["grain"] == 0


def test_render_spec_moves_finish_to_post(demo, tmp_path: Path):
    film, assets, kits = demo
    job = build_job(film, tmp_path / "job", kits_root=kits, assets=assets)
    spec = render_spec(job, tmp_path / "out.mp4", gpu="off")
    assert spec.page == "stage.html?finish=post" and spec.post == "grain_vignette"
    assert (spec.w, spec.h, spec.fps, spec.duration_s, spec.seed) == (1920, 1080, 30.0, 8.0, 7)
    page_spec = render_spec(job, tmp_path / "out.mp4", finish="page", size=(960, 540))
    assert page_spec.page == "stage.html" and page_spec.post == "none" and page_spec.w == 960
