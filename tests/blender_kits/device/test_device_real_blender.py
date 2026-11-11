"""REAL Blender smoke renders of every device scene (opt in: ``pytest --runslow tests/blender_kits``).

Each scene renders 2 frames (first + last) at a tiny preview resolution in both aspects on synthetic UI captures
(PIL-drawn): the build must not raise, frames must decode and not be blank,
and device screens must show the capture's exact colours in the frame (Standard view, no tone shift).
Needs Blender >= 4.2 (HYPE_BLENDER or the usual locations; skipped otherwise). Dev-PC locks: devguard.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kitcheck as kc  # noqa: E402

kc.blender_dev_env()
from devguard import dev_lock, min_free_gb  # noqa: E402

from showreel_core.blender import locate as loc  # noqa: E402
from showreel_core.blender import runner  # noqa: E402

pytestmark = pytest.mark.slow
RES = {"16:9": (256, 144), "9:16": (144, 256)}


@pytest.fixture(scope="module")
def blender():
    found = loc.locate()
    if not found.ok:
        pytest.skip(found.message)
    return found


@pytest.fixture(scope="module")
def ui_assets(tmp_path_factory):
    d = tmp_path_factory.mktemp("ui")
    return {"desktop": {"kind": "image", "path": str(kc.synth_ui(d / "desktop_1440x900.png")),
                        "theme_color": "#7c3aed"},
            "mobile": {"kind": "image", "path": str(kc.synth_ui(d / "mobile_390x844.png", 390, 844))},
            "full": {"kind": "image", "path": str(kc.synth_ui(d / "full_1440.png", tall=True))}}


def _pixels(im) -> list:
    flat = getattr(im, "get_flattened_data", None)   # Pillow >= 12.1 (getdata is deprecated)
    return list(flat() if flat else im.getdata())


def _render(blender, tmp_path, scene: str, aspect: str, assets: dict, product: str, params: dict | None = None,
            dur: float = 2.0):
    job = runner.make_job(kc.KITS / f"{scene}.py", tmp_path / scene.replace("/", "_") / aspect.replace(":", "x"),
                          dur=dur, fps=30, res=RES[aspect], params=params or {}, tier="preview",
                          frames=[1, int(dur * 30)], assets=assets, product=product)
    r = runner.run_job(job, blender, lock=lambda: dev_lock("hype-kit-tests"), min_free_gb=min_free_gb(),
                       timeout_s=300)
    assert r.ok, (r.error, r.traceback[-2000:] if r.traceback else "", r.log)
    return [runner.frame_path(job, f) for f in (1, int(dur * 30))]


DEVICE = ["device/device_hero", "device/device_feature", "device/device_scroll", "device/device_end",
          "device/device_trio"]


@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
@pytest.mark.parametrize("scene", DEVICE)
def test_device_scene_renders(blender, tmp_path, ui_assets, scene, aspect):
    params = {"bbox": [0.3, 0.38, 0.4, 0.3], "click": [0.5, 0.62]} if scene.endswith("feature") else {}
    files = _render(blender, tmp_path, scene, aspect, ui_assets, "desktop", params)
    from PIL import Image

    last = Image.open(files[-1]).convert("RGB")
    px = _pixels(last)
    assert max(sum(p) for p in px) > 120, "last frame is black"
    # the capture is on screen: its violet hero or its near-white page (the stage itself is dark graphite)
    ui = sum(1 for r, g, b in px if (b > 150 and r > 60 and g < r + 30 and b > g + 60) or min(r, g, b) > 200)
    assert ui > len(px) * 0.01, f"no UI colours on screen in {files[-1]}"



def test_space_left_keeps_the_left_third_clean(blender, tmp_path, ui_assets):
    """device_hero with space=left (Quick TITLE/HOOK): the device sits right; the left third stays dark stage."""
    files = _render(blender, tmp_path, "device/device_hero", "16:9", ui_assets, "desktop",
                    {"space": "left", "side": "right"}, dur=3.0)
    from PIL import Image

    im = Image.open(files[-1]).convert("L")
    w, h = im.size
    left = [im.getpixel((x, y)) for x in range(0, w // 3) for y in range(0, h, 2)]
    right = [im.getpixel((x, y)) for x in range(w // 2, w) for y in range(0, h, 2)]
    assert max(left) < 120 and sum(left) / len(left) < 40, "something bright in the text third"
    assert max(right) > 150, "device not on the right"
