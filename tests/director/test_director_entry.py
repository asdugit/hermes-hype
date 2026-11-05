"""Pipeline-facing entry details: brief from keywords, model resolution, style guess."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from showreel_core.contracts import Product
from showreel_core.director import brief_from_kwargs, guess_style, run
from showreel_core.director.types import MediaAsset


class _Opts:
    direction = "make it cinematic, then pixel"
    seconds = 30
    aspects = ("9:16",)
    notes = "slower"
    effort = "max"


def test_brief_from_pipeline_keywords(tmp_path: Path) -> None:
    car = MediaAsset("car", "video", str(tmp_path / "car.mp4"), 1280, 720, 5.0, 30.0)
    b = brief_from_kwargs({"options": _Opts(), "product": Product(name="Red Car"), "digest": "d", "seed": 9,
                           "fps": 30, "assets": [car, {"name": "logo", "type": "image", "path": "x.png"}]}, tmp_path)
    assert b.direction == "make it cinematic, then pixel" and b.seconds == 30 and b.aspect == "9:16"
    assert b.size == (1080, 1920) and b.preview_size == (540, 960)
    assert b.notes == "slower" and b.seed == 9 and [a.name for a in b.assets] == ["car", "logo"]
    assert b.product is not None and b.product.name == "Red Car"
    b2 = brief_from_kwargs({"direction": "x", "size": (1080, 1920)}, tmp_path)
    assert b2.aspect == "9:16" and b2.seconds == 45


def test_missing_model_falls_back_to_quick(tmp_path: Path) -> None:
    res = run(direction="pixel please", llm=None, job_dir=tmp_path / "j", library_dir=tmp_path / "lib")
    assert not res.ok and res.fallback == "quick" and res.quick_style == "pixel" and "model" in res.error


def test_host_llm_is_used(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    class Ctx:
        def complete_structured(self, **kw: Any) -> Any:
            calls.append(kw)
            raise RuntimeError("offline")

    class Host:
        llm = Ctx()

    res = run(direction="a film", host=Host(), job_dir=tmp_path / "j", library_dir=tmp_path / "lib")
    assert not res.ok and calls and calls[0]["purpose"] == "showreel.treatment"


def test_guess_style() -> None:
    assert guess_style("Pixel but transition into a different style") == "pixel"
    assert guess_style("make it pretty") == ""
