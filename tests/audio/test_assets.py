"""Shipped audio assets: bars.json / sfx.json consistency and size budget."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from showreel_core.audio.music import ASSETS, all_beds, load_beds, pick_bed, resolve_bed
from showreel_core.audio.sfx import SYNC_POINTS, load_kit

STYLES = ("launch", "pixel", "cinematic", "terminal", "blueprint")
FAMILIES = ("dream", "pixel_boss", "comic", "ink")
KIT_NAMES = ("bloom_riser", "buy", "sword_slash", "blade_spin", "damage", "footstep", "door_rumble", "chain_break",
             "menu_move", "menu_confirm", "petal_burst", "level_up", "switch_whoosh")


@pytest.mark.parametrize("style", STYLES + FAMILIES)
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
        assert [s["name"] for s in b.sections] == ["intro", "A", "build", "drop", "B", "outro", "end"]
        assert b.section("drop")[0] == b.drop_bar and b.section("end")[0] == b.end_bar == b.total_bars - 1
        assert abs(b.bar_s - 60.0 * b.beats_per_bar / b.bpm) < 1e-5
        assert -16.6 <= b.lufs <= -15.4


def test_wave3_beds_meet_brief():
    """Tempo ranges, keys and gates from the wave-3 brief (bars.json carries the measured numbers)."""
    rng = {"dream": (72, 90), "pixel_boss": (150, 170), "comic": (110, 125), "ink": (100, 115)}
    for fam, (lo, hi) in rng.items():
        data = json.loads((ASSETS / "beds" / fam / "bars.json").read_text(encoding="utf-8"))
        assert len(data["beds"]) == 2
        for b in data["beds"]:
            assert lo <= b["bpm"] <= hi and b["family"] == fam
            assert b["true_peak_db"] <= -1.5 and b["phone_band"] >= 0.5 and b["lr_corr"] > 0.3
            assert b["mono_fold_db"] >= -3.0 and b["decoded_samples_match"]
            if fam == "dream":
                assert b["key"].endswith("major")
            if fam == "pixel_boss":
                assert b["key"].endswith("minor") and b["cadence_to"].endswith("major")


def test_pixel_boss_cadences_pair_with_dream_keys():
    dream_keys = {b.key for b in load_beds("dream")}
    for b in load_beds("pixel_boss"):
        assert b.cadence_to in dream_keys
        assert resolve_bed("dream", 3, prefer_key=b.cadence_to).key == b.cadence_to


def test_pick_bed_is_deterministic_and_falls_back():
    a, b = pick_bed("pixel", 7), pick_bed("pixel", 7)
    assert a is not None and a.id == b.id and a.family == "pixel"
    fb = pick_bed("no-such-style", 1)
    assert fb is not None and fb.style == "launch"
    assert pick_bed("nature", 1).family == "dream" and pick_bed("newspaper", 1).family == "ink"
    assert pick_bed("pixel", 0, "dream_a").id == "dream_a"          # explicit ids resolve across families
    assert pick_bed("comic", 2).family == "comic"


def test_resolve_bed_by_id_family_and_unknown():
    ids = {b.id for b in all_beds()}
    assert {"dream_a", "dream_b", "pixel_boss_a", "pixel_boss_b", "comic_a", "comic_b", "ink_a", "ink_b"} <= ids
    assert resolve_bed("pixel_boss_a").id == "pixel_boss_a"
    assert resolve_bed("pixel_boss", 1).family == "pixel_boss"
    assert resolve_bed("no_such_bed") is None


def test_sfx_kit_files_and_sync_points():
    kit = load_kit()
    assert kit is not None and len(kit.sounds) >= 30
    for s in kit.sounds.values():
        assert s.cls in ("hero", "foley") and s.sync in SYNC_POINTS
        for v in s.variants:
            assert (kit.root / v["file"]).is_file()
            assert 0.0 <= v["onset"] <= v["peak"] <= v["dur"] and v["end"] <= v["dur"]
            if s.sync == "hit":
                assert 0.0 < v["hit"] < v["dur"] and abs(v["hit_measured"] - v["hit"]) < 0.02
    for style in STYLES + ("pixel_boss", "comic", "ink", "dream", "nature", "newspaper"):
        for role, name in kit.styles[style].items():
            assert name in kit.sounds, (style, role, name)


def test_kit_names_requested_by_other_packages_resolve():
    kit = load_kit()
    assert kit is not None
    for name in KIT_NAMES:
        assert name in kit.sounds, name
    # ISSUES.md #6 names: aliases, never broken names
    assert kit.resolve("slash").name == "sword_slash" and kit.resolve("throw").name == "blade_spin"
    assert kit.resolve("chains").name == "chain_break" and kit.resolve("menu_select").name == "menu_confirm"
    assert kit.resolve("whoosh", "launch").name == "whoosh_short" and kit.resolve("whoosh", "blueprint").name == "paper"
    assert kit.resolve("tick", "terminal").name == "key" and kit.resolve("split", "pixel").name == "coin"
    assert kit.resolve("buy", "launch").name == "buy" and kit.resolve("purchase", "ink").name == "cash"
    assert kit.resolve("switch", "dream").name == "bloom_riser"
    keys = {v["key"] for v in kit.sounds["bloom_riser"].variants}
    assert keys == {b.key for b in load_beds("dream")}


def test_total_audio_assets_stay_small():
    total = sum(p.stat().st_size for p in Path(ASSETS).rglob("*") if p.is_file())
    assert total < 25e6
    assert json.loads((ASSETS / "sfx" / "sfx.json").read_text(encoding="utf-8"))["version"] == 1
