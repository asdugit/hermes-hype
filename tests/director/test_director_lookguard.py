"""Look guard: measured exposure levels on the graded keyframes (engine-enforced, any model)."""
from __future__ import annotations

import io

import pytest

from showreel_core.director import compose, lookguard
from showreel_core.render.post import build_post, levels_curve

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _png(level_bg: int, level_fg: int, *, fg_share: float = 0.3, white: int | None = None) -> bytes:
    im = Image.new("L", (160, 90), level_bg)
    w = int(160 * fg_share)
    for x in range(60, 60 + w):
        for y in range(20, 70):
            im.putpixel((x, y), level_fg)
    if white is not None:                    # ~2 % of the frame: a line of white type
        for x in range(10, 30):
            for y in range(4, 19):
                im.putpixel((x, y), white)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def test_dark_murky_film_gets_lifted_and_stretched():
    # Tempo noir: dark UI card (mid ~25) in a dark room (8), highlights only reach ~150
    frames = [_png(8, 25, white=150, fg_share=0.6) for _ in range(6)]
    stats = [lookguard.luma_stats(b) for b in frames]
    lv, rep = lookguard.plan_levels(stats, [True] * 6, mood="noir")
    assert lv is not None
    black, white, gamma = lv
    assert white < 0.9                       # highlights stretched toward white
    assert gamma > 1.0                       # murky mids lifted
    assert rep["mid_after"] >= lookguard.MID_TARGET["noir"] - 0.01


def test_well_exposed_film_is_left_alone():
    frames = [_png(10, 120, white=250, fg_share=0.5) for _ in range(5)]  # 2 % white text
    lv, rep = lookguard.plan_levels([lookguard.luma_stats(b) for b in frames], [True] * 5)
    assert lv is None and rep["why"] == "exposure already fine"


def test_milky_blacks_are_crushed_but_capped():
    frames = [_png(60, 140, white=250, fg_share=0.5) for _ in range(4)]
    lv, _ = lookguard.plan_levels([lookguard.luma_stats(b) for b in frames], [True] * 4)
    assert lv is not None and 0.05 < lv[0] <= lookguard.MAX_BLACK / 255 + 1e-6


def test_black_dips_and_too_few_frames_do_not_count():
    dips = [_png(2, 4) for _ in range(5)]
    lv, rep = lookguard.plan_levels([lookguard.luma_stats(b) for b in dips])
    assert lv is None and "too few" in rep["why"]
    assert lookguard.plan_levels([None, None])[0] is None


def test_gain_and_gamma_are_capped():
    frames = [_png(1, 3, white=40, fg_share=0.5) for _ in range(4)]
    lv, rep = lookguard.plan_levels([lookguard.luma_stats(b) for b in frames], [True] * 4)
    assert lv is not None
    assert lv[1] >= 1 / lookguard.MAX_GAIN - 1e-3 and lv[2] <= lookguard.MAX_GAMMA


def test_apply_levels_adds_grade_chain_and_mood_look_keeps_it():
    film = {"shots": [], "render": {"post": "crt", "post_params": {"crt": {"glow": 0.4}}}}
    assert lookguard.apply_levels(film, [0.02, 0.8, 1.3])
    assert film["render"]["post"] == "crt+grade"
    assert film["render"]["post_params"]["grade"]["levels"] == [0.02, 0.8, 1.3]
    compose.mood_look(film, "a noir detective trailer")
    g = film["render"]["post_params"]["grade"]
    assert g["mono"] == 1.0 and g["levels"] == [0.02, 0.8, 1.3]     # the re-look keeps the measured exposure
    film2 = {"shots": []}
    assert lookguard.apply_levels(film2, [0.0, 0.85, 1.0]) and film2["render"]["post"] == "grade"
    assert not lookguard.apply_levels({"shots": []}, None)


def test_levels_curve_points_are_monotonic_and_noop_is_empty():
    assert levels_curve(None) == "" and levels_curve([0, 1, 1]) == "" and levels_curve("x") == ""
    pts = [tuple(map(float, p.split("/"))) for p in levels_curve([0.05, 0.8, 1.4]).split()]
    xs = [x for x, _ in pts]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0)
    ys = [y for _, y in pts]
    assert ys == sorted(ys)


def test_grade_chain_with_levels_builds(tmp_path):
    pc = build_post("grade", in_size=(320, 180), out_size=(320, 180), seed=1,
                    params={"grade": {"mono": 1.0, "levels": [0.03, 0.75, 1.4]}}, work_dir=tmp_path)
    assert "curves=all=" in pc.graph
