"""REAL Blender (opt in: ``pytest --runslow tests/blender``): hello.py at 160x90, 3 frames, preview + final tiers,
and one keyframe-only film through Blender + Chromium.

Needs a Blender >= 4.2 (AUTEUR_BLENDER or the usual locations; skipped otherwise). On a shared dev PC set
AUTEUR_DEV_BLENDER_LOCK / AUTEUR_DEV_GPULOCK_DIR / AUTEUR_DEV_MIN_FREE_GB (see devguard.py) and
AUTEUR_RENDER_SLOT_DIR for the Chromium part.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from showreel_core.blender import locate as loc
from showreel_core.blender import runner

sys.path.insert(0, str(Path(__file__).parent))
from devguard import dev_lock, min_free_gb  # noqa: E402

pytestmark = pytest.mark.slow
SCENE = Path(__file__).resolve().parents[2] / "blender_kits" / "_test" / "hello.py"


@pytest.fixture(scope="module")
def blender():
    found = loc.locate()
    if not found.ok:
        pytest.skip(found.message)
    return found


@pytest.mark.parametrize("tier", ["preview", "final"])
def test_hello_renders(tmp_path, blender, tier):
    job = runner.make_job(SCENE, tmp_path / tier, dur=3 / 30, fps=30, res=(160, 90), tier=tier, seed=7,
                          params={"color": "#3E63DD", "spin": 45})
    events = []
    r = runner.run_job(job, blender, progress=events.append, lock=lambda: dev_lock("auteur-A-tests"),
                       min_free_gb=min_free_gb(), timeout_s=300)
    assert r.ok, (r.error, r.traceback[-2000:])
    assert r.frames_rendered == [1, 2, 3] and not r.blank and not r.frames_bad
    assert r.stats["engine"] in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT") and r.stats["res"] == [160, 90]
    assert r.stats["tier"] == tier and r.build_s is not None and r.mean_frame_s > 0
    assert {"t": 0.5, "sfx": "appear", "gain_db": 0.0, "align": "auto"} in r.cues
    assert [e["phase"] for e in events].count("frame") == 3
    # deterministic: same job, same pixels
    again = runner.run_job({**job, "out_dir": str(tmp_path / f"{tier}_2")}, blender, resume=False,
                           lock=lambda: dev_lock("auteur-A-tests"), min_free_gb=min_free_gb(), timeout_s=300)
    assert again.ok
    from PIL import Image, ImageChops
    a = Image.open(runner.frame_path(job, 2)).convert("RGB")
    b = Image.open(Path(tmp_path / f"{tier}_2" / "000002.jpg")).convert("RGB")
    assert max(hi for _, hi in ImageChops.difference(a, b).getextrema()) <= 8


def test_scene_error_is_reported(tmp_path, blender):
    bad = tmp_path / "bad_scene.py"
    bad.write_text("PARAMS = {}\ndef build(sc):\n    raise RuntimeError('scene exploded on purpose')\n", encoding="utf-8")
    job = runner.make_job(bad, tmp_path / "out", dur=0.1, fps=30, res=(160, 90))
    r = runner.run_job(job, blender, lock=lambda: dev_lock("auteur-A-tests"), min_free_gb=min_free_gb(),
                       timeout_s=300)
    assert not r.ok and "scene exploded on purpose" in r.error and "Traceback" in r.traceback


def test_film_keyframes_through_blender_and_browser(tmp_path, blender):
    from showreel_core.blender.render_film import render_film
    film = {"version": 1, "fps": 30, "size": [320, 180], "dur": 2.0, "seed": 7, "title": "t", "assets": {},
            "shots": [{"id": "a", "t0": 0, "t1": 1.1, "scene": "blender:_test/hello", "params": {}},
                      {"id": "b", "t0": 1.0, "t1": 2.0, "scene": "blender:_test/hello", "params": {"color": "#30A46C"}}],
            "transitions": [{"from": "a", "to": "b", "type": "crossfade", "t": 1.0, "dur": 0.1}],
            "overlays": [], "cues": []}
    fp = tmp_path / "film.json"
    fp.write_text(json.dumps(film), encoding="utf-8")
    r = render_film(fp, tmp_path / "out" / "kf.mp4", tier="preview", keyframes=[0.5, 1.5],
                    lock=lambda: dev_lock("auteur-A-tests"), min_free_gb=min_free_gb())
    assert r.ok, r.error
    assert len(r.stills) == 2 and all(Path(s).is_file() for s in r.stills)
    assert r.blender["shots"][0]["frames"] == 2          # frame 1 (poster) + the frame shown at t=0.5
