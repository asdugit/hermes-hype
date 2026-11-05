"""SFX placement rules with a synthetic kit."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.audio.sfx import Kit, SfxSound, hero_times, place_cues
from showreel_core.contracts import Cue


def _kit() -> Kit:
    v = lambda f, peak=0.0, end=0.5: {"file": f, "dur": end + 0.02, "onset": 0.0, "peak": peak, "end": end}  # noqa: E731
    s = {
        "whoosh_short": SfxSound("whoosh_short", "foley", -10.0, "peak", [v("w1.ogg", 0.28), v("w2.ogg", 0.3)]),
        "riser": SfxSound("riser", "hero", -6.0, "end", [v("r1.ogg", 2.3, 2.4)]),
        "click": SfxSound("click", "foley", -14.0, "onset", [v("c1.ogg"), v("c2.ogg"), v("c3.ogg")]),
        "impact": SfxSound("impact", "hero", -3.0, "onset", [v("i1.ogg", 0.09, 2.1)]),
        "hit": SfxSound("hit", "hero", -6.0, "onset", [v("h1.ogg")]),
    }
    return Kit(Path("kit"), s, {"launch": {"cut": "whoosh_short"}})


def test_alignment_uses_natural_sync_one_frame_early():
    placed, warns = place_cues([{"t": 5.0, "sfx": "whoosh_short"}, {"t": 10.0, "sfx": "riser"},
                                Cue(t=12.0, sfx="click", align="onset")], _kit(), 30.0)
    by = {p.name: p for p in placed}
    assert by["whoosh_short"].start == pytest.approx(5.0 - 0.28 - 1 / 30, abs=1e-4)
    assert by["riser"].start == pytest.approx(10.0 - 2.4 - 1 / 30, abs=1e-4)
    assert by["click"].start == pytest.approx(12.0 - 1 / 30, abs=1e-4)
    assert not warns


def test_round_robin_and_alias():
    cues = [{"t": float(t), "sfx": "click"} for t in range(4)] + [{"t": 9.0, "sfx": "cut"}]
    placed, _ = place_cues(cues, _kit(), 30.0, style="launch")
    files = [p.file.name for p in placed if p.name == "click"]
    assert files == ["c1.ogg", "c2.ogg", "c3.ogg", "c1.ogg"]
    assert any(p.name == "whoosh_short" for p in placed)


def test_class_levels_are_clamped():
    placed, _ = place_cues([{"t": 1.0, "sfx": "click", "gain_db": 20.0}, {"t": 2.0, "sfx": "impact", "gain_db": -20.0}],
                           _kit(), 30.0)
    by = {p.name: p for p in placed}
    assert by["click"].gain_db == -8.0 and by["impact"].gain_db == -6.0


def test_one_hero_impact_and_max_three_per_frame():
    cues = [{"t": 3.0, "sfx": "impact"}, {"t": 20.0, "sfx": "impact"}] + [{"t": 7.0, "sfx": "click"}] * 5
    placed, warns = place_cues(cues, _kit(), 30.0)
    assert [p.name for p in placed if p.cls == "hero"] == ["impact", "hit"]
    assert sum(1 for p in placed if p.cue_t == 7.0) == 3
    assert any("replaced" in w for w in warns) and any("max 3" in w for w in warns)
    assert hero_times(placed) == [3.0, 20.0]


def test_head_trim_and_unknown_names():
    placed, warns = place_cues([{"t": 0.1, "sfx": "whoosh_short"}, {"t": 1.0, "sfx": "nope"}, {"t": 99.0, "sfx": "click"}],
                               _kit(), 30.0)
    assert len(placed) == 1 and placed[0].start == 0.0 and placed[0].skip == pytest.approx(0.28 + 1 / 30 - 0.1, abs=1e-4)
    assert any("unknown sfx 'nope'" in w for w in warns)
