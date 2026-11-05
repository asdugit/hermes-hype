"""Mix filtergraph construction and expression math (no ffmpeg needed)."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.audio.mix import (MixSettings, VoicePlacement, build_graph, duck_threshold_db, merge_intervals,
                                     trapezoid_gain_expr)
from showreel_core.audio.sfx import PlacedSfx


def _eval(expr: str, t: float) -> float:
    env = {"clip": lambda x, a, b: max(a, min(b, x)), "min": min, "max": max, "t": t}
    return eval(expr, {"__builtins__": {}}, env)  # noqa: S307 - test-only evaluator for our own expression


def test_trapezoid_expression_values():
    e = trapezoid_gain_expr([(2.0, 2.3)], -6.0, 0.03, 0.25)
    g = 10 ** (-6 / 20)
    assert _eval(e, 0.0) == pytest.approx(1.0)
    assert _eval(e, 2.1) == pytest.approx(g, rel=1e-3)
    assert _eval(e, 2.3 + 0.125) == pytest.approx(1 - (1 - g) * 0.5, rel=1e-3)
    assert _eval(e, 3.0) == pytest.approx(1.0)
    assert trapezoid_gain_expr([], -6.0, 0.03, 0.25) == "1"


def test_trapezoid_overlaps_take_max_and_negative_starts_parse():
    e = trapezoid_gain_expr([(0.0, 1.0), (0.9, 2.0)], -4.0, 0.05, 0.15)
    assert "max(" in e and "(t-(-0.05))" in e
    assert _eval(e, 1.0) == pytest.approx(10 ** (-4 / 20), rel=1e-3)


def test_merge_intervals():
    assert merge_intervals([(5, 6), (0, 1), (1.1, 2)]) == [(0, 2), (5, 6)]


def test_duck_threshold_math():
    # voice detector at -15 dBFS RMS, 9 dB reduction at ratio 3.5 -> 12.6 dB over threshold
    assert duck_threshold_db(-15.0, 9.0, 3.5) == pytest.approx(-27.6, abs=0.01)


def _graph(voices=True, sfx=True, music=True):
    vs = [VoicePlacement(Path("vo_00.wav"), 1.0, 3.0), VoicePlacement(Path("vo_01.wav"), 5.5, 2.0)] if voices else []
    fx = [PlacedSfx("whoosh_short", Path("w.ogg"), 0.0, -10.0, "foley", 0.3, skip=0.2),
          PlacedSfx("impact", Path("i.ogg"), 4.0, -3.0, "hero", 4.0)] if sfx else []
    return build_graph(10.0, Path("m.wav") if music else None, vs, fx, -4.0, 5.0, MixSettings(), [4.0], -27.6)


def test_graph_structure_with_voice():
    g = _graph()
    assert len(g.inputs) == 1 + 2 + 2
    assert g.outputs == ["premix", "stemvo", "stembed"]
    gr = g.graph
    assert "acrossover=split=250 5000:order=4th[mlo][mmid][mhi]" in gr
    # only the mid band is compressed, keyed by the UNdelayed detector
    assert "[mmid][vdet]sidechaincompress=" in gr and "ratio=3.5" in gr and "attack=80" in gr and "release=450" in gr
    assert gr.count("sidechaincompress") == 1
    assert "[vp0]adelay=120:all=1" in gr and "adelay=120:all=1[mus]" in gr     # program delayed by the look-ahead
    assert "atrim=start=0.12:end=10.12" in gr                                   # ...and trimmed back
    assert "adelay=1000:all=1[v1]" in gr and "adelay=5500:all=1[v2]" in gr
    assert "atrim=start=0.2,asetpts=PTS-STARTPTS" in gr and "adelay=120:all=1[s3]" in gr  # sfx head trim + delay
    assert "volume='1-" in gr and ":eval=frame" in gr                            # hero dip + sfx-under-speech
    assert "threshold=0.041687" in gr                                             # 10^(-27.6/20)


def test_graph_captions_only_has_no_duck():
    g = _graph(voices=False)
    assert "sidechaincompress" not in g.graph and g.outputs == ["premix"]
    assert len(g.inputs) == 3


def test_graph_without_music_uses_silence_source():
    g = _graph(music=False, sfx=False)
    assert g.inputs[0][:2] == ["-f", "lavfi"] and "anullsrc" in g.inputs[0][-1]
