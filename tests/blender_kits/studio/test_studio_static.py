"""Studio kit + camera maths — static contract + pure maths (no Blender needed)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kitcheck as kc

kc.lib_importable()

SCENES = kc.scene_files("studio")


def test_all_studio_scenes_exist():
    assert {p.stem for p in SCENES} == {"product_hero", "product_float"}


@pytest.mark.parametrize("path", SCENES, ids=lambda p: p.stem)
def test_scene_static_contract(path):
    assert kc.check_scene(path) == []


def test_spline_path_hits_keys_and_is_c2_smooth():
    from blender_kits.lib.studio import smoothness, spline_path

    times = [0.0, 1.1, 2.0, 4.0]  # deliberately uneven beat spacing
    vals = [(0, 0, 0), (1.0, 0.5, 0.2), (1.4, 1.2, 0.3), (3.0, 1.0, 0.0)]
    f = spline_path(times, vals, end_speed=0.6)
    for t, v in zip(times, vals):
        assert all(abs(a - b) < 1e-9 for a, b in zip(f(t), v))
    fps = 30
    samples = [f(i / fps) for i in range(int(4.0 * fps) + 1)]
    assert smoothness(samples, fps)["jerk_ratio"] < 0.1
    # velocity just before/after an inner key matches (C1)
    eps = 1e-4
    for tk in times[1:-1]:
        v1 = [(a - b) / eps for a, b in zip(f(tk), f(tk - eps))]
        v2 = [(a - b) / eps for a, b in zip(f(tk + eps), f(tk))]
        assert max(abs(a - b) for a, b in zip(v1, v2)) < 1e-2


def test_smoothness_flags_a_velocity_kink():
    from blender_kits.lib.studio import smoothness

    fps = 30
    kink = [(i / fps if i < 60 else 2.0 + (i - 60) / fps * 2.0, 0.0, 0.0) for i in range(120)]
    assert smoothness(kink, fps)["jerk_ratio"] > 5.0


def test_ease_and_window():
    from blender_kits.lib.studio import ease, window

    assert ease(0) == 0 and ease(1) == 1 and abs(ease(0.5) - 0.5) < 1e-9
    assert window(-1, 0, 2) == 0 and window(3, 0, 2) == 1
    # k < 1 keeps some speed at the ends (frame 0 already in motion)
    d0 = (ease(0.01, "inout", 0.6) - ease(0.0, "inout", 0.6)) / 0.01
    assert d0 > 0.35


def test_fit_distance_frames_the_rect():
    from blender_kits.lib.studio import fit_distance, fov

    d = fit_distance(0.3, 0.1, 50.0, 16 / 9, fill=0.8)
    half = d * math.tan(fov(50.0) / 2)
    assert abs(0.3 / (2 * half) - 0.8) < 1e-9


def test_wobble_is_deterministic_and_small():
    from blender_kits.lib.studio import wobble

    a = [wobble(t / 30, 7, 0.1) for t in range(300)]
    b = [wobble(t / 30, 7, 0.1) for t in range(300)]
    assert a == b and max(abs(x) for x in a) <= 0.1 + 1e-9


def test_dof_fstop_scales_with_subject():
    from blender_kits.lib.studio import dof_fstop

    assert dof_fstop(0.3) < dof_fstop(4.5) <= 22
