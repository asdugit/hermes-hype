"""Job builder: files laid out per SDK §1, kits/three only when needed, precise JobErrors."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from showreel_core.film.page import (
    JobError,
    _order_kits,
    build_job,
    film_kits,
    kits_referenced,
    scene_filename,
)

CUSTOM = """import { sr } from '../runtime/showreel.js';
sr.defineScene('custom:hello', { layer: '2d', render(ctx, t) { ctx.kit('demo'); } });
"""


def tiny_film(scene: str = "custom:hello", **kw) -> dict:
    f = {"version": 1, "fps": 30, "size": [640, 360], "dur": 2.0, "seed": 1,
         "shots": [{"id": "s", "t0": 0, "t1": 2, "scene": scene}]}
    f.update(kw)
    return f


def test_demo_job_layout(demo, tmp_path: Path):
    film, assets, kits = demo
    job = build_job(film, tmp_path / "job", kits_root=kits, assets=assets)
    for rel in ("stage.html", "film.json", "runtime/showreel.js", "runtime/core/runtime.js", "kits/demo/kit.js",
                "kits/demo/fonts/demo-sans.ttf", "assets/manifest.json", "vendor/three/build/three.module.min.js",
                "vendor/three/LICENSE"):
        assert (job / rel).is_file(), rel
    man = json.loads((job / "assets" / "manifest.json").read_text(encoding="utf-8"))
    assert man["clip"]["type"] == "frames" and man["clip"]["count"] == 24 and man["clip"]["fps"] == 12
    assert (job / man["clip"]["pattern"].replace("%06d", "000024")).is_file()
    assert man["logo"]["type"] == "image" and man["logo"]["path"].endswith(".png")
    html = (job / "stage.html").read_text(encoding="utf-8")
    assert '"three": "./vendor/three/build/three.module.min.js"' in html
    assert "kits/demo/kit.js" in html and "Demo Sans" in html
    saved = json.loads((job / "film.json").read_text(encoding="utf-8"))
    assert saved["overlays"][0]["res"] is None   # normalised


def test_three_only_when_needed(tmp_path: Path):
    job = build_job(tiny_film(kits=[]), tmp_path / "job", kits_root=tmp_path / "nokits", scenes={"custom:hello": CUSTOM.replace("ctx.kit('demo');", "")})
    assert not (job / "vendor").exists()
    assert "importmap" not in (job / "stage.html").read_text(encoding="utf-8")
    assert (job / "scenes" / "hello.js").is_file()


def test_custom_scene_pulls_referenced_kit(demo, tmp_path: Path):
    _, _, kits = demo
    job = build_job(tiny_film(), tmp_path / "job", kits_root=kits, scenes={"custom:hello": CUSTOM})
    assert (job / "kits" / "demo" / "kit.js").is_file()
    m = re.search(r"modules: (\[.*?\])", (job / "stage.html").read_text(encoding="utf-8"))
    assert m and json.loads(m.group(1)) == ["kits/demo/kit.js", "scenes/hello.js"]


def test_rebuild_removes_stale_scenes(tmp_path: Path):
    build_job(tiny_film(), tmp_path / "job", kits_root=tmp_path, scenes={"custom:hello": CUSTOM.replace("ctx.kit('demo');", ""), "custom:old": "x"})
    build_job(tiny_film(), tmp_path / "job", kits_root=tmp_path, scenes={"custom:hello": CUSTOM.replace("ctx.kit('demo');", "")})
    assert not (tmp_path / "job" / "scenes" / "old.js").exists()


def test_errors_are_collected(tmp_path: Path):
    f = tiny_film(scene="kit:nope/scene", assets={"car": {"type": "frames"}},
                  fonts=[{"family": "X", "src": "kits/nope/x.ttf"}])
    with pytest.raises(JobError) as ei:
        build_job(f, tmp_path / "job", kits_root=tmp_path)
    msgs = [str(i) for i in ei.value.issues]
    assert any("kit 'nope' not found" in m for m in msgs)
    assert any(m.startswith("assets.car") for m in msgs)
    assert any(m.startswith("fonts[0].src") for m in msgs)
    assert ei.value.to_dict()["code"] == "film_invalid"


def test_invalid_film_raises_with_paths(tmp_path: Path):
    with pytest.raises(JobError) as ei:
        build_job(tiny_film(fps=0), tmp_path / "job")
    assert [i.path for i in ei.value.issues] == ["fps"]


def test_missing_custom_scene_source(tmp_path: Path):
    with pytest.raises(JobError, match="custom:hello"):
        build_job(tiny_film(), tmp_path / "job", kits_root=tmp_path)


def test_prepared_asset_entries_must_exist(tmp_path: Path):
    f = tiny_film(assets={"shot": {"type": "image"}})
    with pytest.raises(JobError, match="not inside the job"):
        build_job(f, tmp_path / "job", kits_root=tmp_path, scenes={"custom:hello": "x"},
                  assets={"shot": {"type": "image", "path": "assets/shot/image.png"}})


def test_scene_filenames():
    assert scene_filename("custom:boss-battle") == "boss-battle.js"
    assert scene_filename("lib:flower") == "lib-flower.js"
    with pytest.raises(ValueError):
        scene_filename("kit:pixel/x")


def test_kit_reference_detection_and_order():
    js = ("ctx.kit('nature').sky(); sr.kit(\"type\"); import { a } from '../kits/pixel/core/gfx.js';"
          "import { sr } from '../runtime/showreel.js';")
    assert kits_referenced(js) == {"nature", "type", "pixel"}
    assert film_kits({"shots": [{"scene": "kit:pixel/walk"}], "transitions": [{"type": "kit:fx/burn"}],
                      "fonts": [{"src": "kits/launch/fonts/a.ttf"}], "kits": ["extra"]}) == {"pixel", "fx", "launch", "extra"}
    assert _order_kits({"a": {"b"}, "b": {"c"}, "c": set(), "d": {"a"}}) == ["c", "b", "a", "d"]
    assert set(_order_kits({"a": {"b"}, "b": {"a"}})) == {"a", "b"}   # cycles don't hang
