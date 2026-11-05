"""Bar-fit planning and splice rendering (pure Python, synthetic bed)."""
from __future__ import annotations

import math
from array import array

import pytest

from showreel_core.audio.ffmpeg_io import SR
from showreel_core.audio.music import MIN_RING_S, PRE_S, XFADE_S, _runs, _tail_cycle, plan_bars, render_plan

from .conftest import make_bed


def test_tail_cycle_ends_on_last_bar():
    assert _tail_cycle([4, 5, 6, 7], 2) == [6, 7]
    assert _tail_cycle([4, 5, 6, 7], 6) == [6, 7, 4, 5, 6, 7]
    assert _tail_cycle([], 3) == []


def test_runs_group_consecutive_source_bars():
    assert _runs([0, 1, 2, 10, 11, 4]) == [(0, 0, 3), (3, 10, 2), (5, 4, 1)]


@pytest.mark.parametrize("duration", [8.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0, 120.0])
def test_plan_fills_whole_bars_and_rings(duration):
    bed = make_bed()
    p = plan_bars(bed, duration)
    assert len(p.source_bars) == p.n_bars == len(p.labels)
    end = p.n_bars * bed.bar_s
    assert end <= duration - MIN_RING_S + 1e-9          # final hit leaves room to ring
    assert duration - end < MIN_RING_S + bed.bar_s      # ...but never more than one extra bar
    if p.n_bars >= 2:
        assert p.labels[p.drop_bar] == "drop"
        assert all(lab in ("intro", "A", "build") for lab in p.labels[: p.drop_bar])
        assert p.labels[p.drop_bar - 1] == "build"


def test_drop_lands_on_requested_bar():
    bed = make_bed()
    p = plan_bars(bed, 75.0, drop_time=30.0)
    assert p.drop_bar == round(30.0 / bed.bar_s)
    assert p.source_bars[p.drop_bar] == 16              # first bar of the drop section


def test_long_film_starts_with_intro_and_ends_with_outro():
    bed = make_bed()
    p = plan_bars(bed, 90.0)
    assert p.labels[0] == "intro" and p.labels[-1] == "outro"
    assert p.source_bars[-1] == 33                       # last outro bar flows into the end hit
    assert "B" in p.labels


def test_last_word_pushes_end_hit_later():
    bed = make_bed()                                     # bar = 2.0 s
    p1 = plan_bars(bed, 31.0)                            # floor((31-1.2)/2) = 14 bars -> hit at 28 s
    assert p1.n_bars == 14
    p2 = plan_bars(bed, 31.0, last_word_time=29.5)       # needs the hit after 29.5 -> 15 bars (ring 1.0 s)
    assert p2.n_bars == 15 and not p2.warnings
    p3 = plan_bars(bed, 31.0, last_word_time=30.9)
    assert p3.warnings


def test_tiny_durations_do_not_crash():
    bed = make_bed()
    assert plan_bars(bed, 1.0).n_bars == 0
    p = plan_bars(bed, 3.5)
    assert p.n_bars == 1 and p.labels == ["drop"]


def _bar_valued_source(bed, extra_s=3.0):
    """Stereo source where every sample equals its (bar index + 1): splices become measurable."""
    n = int(round((bed.total_bars * bed.bar_s + extra_s) * SR))
    src = array("f", bytes(8 * n))
    for i in range(n):
        v = float(int(i / (bed.bar_s * SR)) + 1)
        src[2 * i] = v
        src[2 * i + 1] = v
    return src


def test_render_plan_maps_bars_and_finishes_crossfade_before_downbeat():
    bed = make_bed(bpm=240.0)                            # 1 s bars keep the synthetic source small
    src = _bar_valued_source(bed)
    dur = 20.0
    p = plan_bars(bed, dur, drop_time=8.0)
    out = render_plan(src, bed, p, dur)
    assert len(out) == 2 * int(round(dur * SR))
    for k, sb in enumerate(p.source_bars):
        mid = int((k + 0.5) * bed.bar_s * SR)
        assert out[2 * mid] == pytest.approx(sb + 1, abs=1e-5)
    # the splice is over before each downbeat: from PRE_S before it only the incoming run plays
    # (its own source pre-roll, then its downbeat at full level)
    for k in range(1, len(p.source_bars)):
        if p.source_bars[k] == p.source_bars[k - 1] + 1:
            continue
        d = int(round(k * bed.bar_s * SR))
        pre_val = float(p.source_bars[k]) if p.source_bars[k] > 0 else 0.0   # value of the bar before it
        assert out[2 * d] == pytest.approx(p.source_bars[k] + 1, abs=1e-4)
        assert out[2 * (d - int(0.001 * SR))] == pytest.approx(pre_val, abs=1e-4)
        # mid-window: equal-power blend of the outgoing bar and the incoming pre-roll
        mid = d - int(round((PRE_S + XFADE_S / 2) * SR))
        g = math.sqrt(0.5)
        assert out[2 * mid] == pytest.approx(g * (p.source_bars[k - 1] + 1) + g * pre_val, rel=0.02)


def test_render_plan_end_hit_plays_end_section():
    bed = make_bed(bpm=240.0)
    src = _bar_valued_source(bed)
    dur = 12.0
    p = plan_bars(bed, dur)
    out = render_plan(src, bed, p, dur)
    hit = int(round(p.n_bars * bed.bar_s * SR)) + int(0.1 * SR)
    assert out[2 * hit] == pytest.approx(bed.end_bar + 1, abs=1e-4)
