"""Render a built job to video with the film's finish moved to ffmpeg post (cheaper than in-page compositing).

Measured on the demo film at 1080p (research/wp-d-runtime.md): in-page grain costs +10..90 ms per frame and
backdrop-filter bloom +200 ms in software mode, while the equivalent ffmpeg post chains cost ~1-5 % end to end.
So final renders load ``stage.html?finish=post`` and pass ``post``/``post_params`` built here; previews keep the
in-page finish (one capture per keyframe, cost irrelevant).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

GRAIN_TO_STRENGTH = 175.0   # film grain 0.04 -> ffmpeg noise strength 7 (the grain_vignette default look)


def post_for_finish(finish: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """film.json ``finish`` -> (render post chain spec, post_params) for ``RenderSpec``."""
    f = dict(finish or {})
    grain = max(0.0, min(1.0, float(f.get("grain") or 0)))
    vignette = max(0.0, min(1.0, float(f.get("vignette") or 0)))
    bloom = max(0.0, min(1.0, float(f.get("bloom") or 0)))
    chains: list[str] = []
    params: dict[str, Any] = {}
    if bloom > 0:
        chains.append("bloom")
        params["bloom"] = {"amount": round(bloom, 3)}
    if grain > 0 or vignette > 0:
        chains.append("grain_vignette")
        params["grain_vignette"] = {"grain": round(grain * GRAIN_TO_STRENGTH), "vignette": round(vignette, 3)}
    return ("+".join(chains) or "none"), params


def render_spec(job_dir: Path, out_path: Path, *, size: tuple[int, int] | None = None, fps: float | None = None,
                finish: str = "post", gpu: str = "auto", **kw: Any) -> Any:
    """A ``showreel_core.render.workers.RenderSpec`` for a job built by ``build_job``.

    ``finish``: "post" (ffmpeg chains, page finish off), "page" (in-page CSS/canvas finish), "none".
    ``size`` defaults to the film size; other keyword arguments pass through to RenderSpec.
    """
    from ..render.workers import RenderSpec

    job = Path(job_dir)
    film = json.loads((job / "film.json").read_text(encoding="utf-8"))
    fw, fh = (int(v) for v in film.get("size", [1920, 1080]))
    w, h = size or (fw, fh)
    page = "stage.html" if finish == "page" else f"stage.html?finish={finish}"
    post, params = post_for_finish(film.get("finish")) if finish == "post" else ("none", {})
    return RenderSpec(page_dir=job, out_path=Path(out_path), w=w, h=h, fps=float(fps or film.get("fps", 30)),
                      duration_s=float(film["dur"]), page=page, post=post, post_params=params,
                      seed=int(film.get("seed", 0)), gpu=gpu, **kw)
