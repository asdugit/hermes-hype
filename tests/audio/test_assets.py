"""Shipped audio assets: bars.json / sfx.json consistency and size budget."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from showreel_core.audio.music import ASSETS, load_beds, pick_bed
from showreel_core.audio.sfx import load_kit

STYLES = ("launch", "pixel", "cinematic", "terminal", "blueprint")


@pytest.mark.parametrize("style", STYLES)
def test_beds_have_consistent_bar_maps(style):
    beds = load_beds(style)
    assert len(beds) >= 2
    for b in beds:
        assert b.path.is_file() and b.path.stat().st_size < 1.5e6 * (b.total_bars * b.bar_s + b.tail_s) / 60 + 1
        start = 0
        for s in b.sections:
            assert s["start_bar"] == start
            start += s["bars"]
        assert start == b.total_bars
        assert b.section("drop")[0] == b.drop_bar and b.section("end")[0] == b.end_bar == b.total_bars - 1
        assert abs(b.bar_s - 60.0 * b.beats_per_bar / b.bpm) < 1e-5
        assert -16.6 <= b.lufs <= -15.4


def test_pick_bed_is_deterministic_and_falls_back():
    a, b = pick_bed("pixel", 7), pick_bed("pixel", 7)
    assert a is not None and a.id == b.id
    fb = pick_bed("no-such-style", 1)
    assert fb is not None and fb.style == "launch"


def test_sfx_kit_files_and_sync_points():
    kit = load_kit()
    assert kit is not None and len(kit.sounds) >= 20
    for s in kit.sounds.values():
        assert s.cls in ("hero", "foley") and s.sync in ("onset", "peak", "end")
        for v in s.variants:
            assert (kit.root / v["file"]).is_file()
            assert 0.0 <= v["onset"] <= v["peak"] <= v["dur"] and v["end"] <= v["dur"]
    for style in STYLES:
        for role, name in kit.styles[style].items():
            assert name in kit.sounds, (style, role, name)


def test_total_audio_assets_stay_small():
    total = sum(p.stat().st_size for p in Path(ASSETS).rglob("*") if p.is_file())
    assert total < 25e6
    assert json.loads((ASSETS / "sfx" / "sfx.json").read_text(encoding="utf-8"))["version"] == 1
