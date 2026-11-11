"""Device kit — static contract + pure maths (no Blender needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kitcheck as kc

kc.lib_importable()

SCENES = kc.scene_files("device")


def test_all_device_scenes_exist():
    assert {p.stem for p in SCENES} == {"device_hero", "device_feature", "device_scroll", "device_trio",
                                        "device_end"}


@pytest.mark.parametrize("path", SCENES, ids=lambda p: p.stem)
def test_scene_static_contract(path):
    assert kc.check_scene(path) == []


def test_feature_scene_takes_story_feature_shape():
    m = kc.static_module(kc.KITS / "device" / "device_feature.py")
    assert {"image", "feature", "bbox", "click"} <= set(m["PARAMS"])
    m = kc.static_module(kc.KITS / "device" / "device_scroll.py")
    assert {"image", "scroll"} <= set(m["PARAMS"])


def test_cover_window_never_mirrors_and_keeps_aspect():
    from blender_kits.lib.materials import cover_window

    for iw, ih, sw, sh in [(1440, 900, 0.296, 0.185), (1920, 1080, 0.296, 0.185), (390, 844, 0.0668, 0.1428),
                           (1440, 2282, 0.296, 0.185), (780, 6484, 0.0668, 0.1428)]:
        x0, y0, sx, sy = cover_window(iw, ih, sw, sh, align="top")
        assert sx > 0 and sy > 0 and sx <= 1.0 + 1e-9 and sy <= 1.0 + 1e-9
        # shown image region has the screen's aspect: (sx*iw)/(sy*ih) == sw/sh
        assert abs((sx * iw) / (sy * ih) - sw / sh) < 1e-6
        if ih / iw > sh / sw:  # taller than the screen: top-aligned (web pages)
            assert abs(y0 + sy - 1.0) < 1e-9


def test_exact_16x10_capture_fills_laptop_screen():
    from blender_kits.lib.materials import cover_window

    x0, y0, sx, sy = cover_window(1440, 900, 0.296, 0.185)
    assert (round(x0, 6), round(y0, 6), round(sx, 6), round(sy, 6)) == (0.0, 0.0, 1.0, 1.0)


def test_hex_rgb_is_linear():
    from blender_kits.lib.materials import hex_rgb

    r, g, b = hex_rgb("#ffffff")
    assert (r, g, b) == (1.0, 1.0, 1.0)
    assert abs(hex_rgb("#808080")[0] - 0.2158605) < 1e-5


def test_window_showing_scrolls_feature_into_view():
    from blender_kits.lib import device as dv

    scr = dv.Screen(obj=None, w=0.296, h=0.185, mat=None, img_w=1440, img_h=2282)
    from blender_kits.lib.materials import cover_window

    scr.window = cover_window(1440, 2282, 0.296, 0.185)
    # a pricing row at 75 % of the page height is below the fold of a top-aligned window
    x0, y0, sx, sy = dv.window_showing(scr, [0.03, 0.74, 0.94, 0.03])
    v_top, v_bot = 1 - 0.74, 1 - 0.77
    assert y0 <= v_bot and v_top <= y0 + sy
    # px -> screen uv round trip lands inside 0..1 for the rect centre
    u, v = scr.px_to_screen_uv(0.5 * 1440, 0.755 * 2282, (x0, y0, sx, sy))
    assert 0 <= u <= 1 and 0 <= v <= 1


def test_rounded_rect_outline():
    from blender_kits.lib.device import rounded_rect

    pts = rounded_rect(0.3, 0.2, 0.01, 8)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert abs(max(xs) - 0.15) < 1e-9 and abs(min(ys) + 0.1) < 1e-9 and len(pts) == 36
