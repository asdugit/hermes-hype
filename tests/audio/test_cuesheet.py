"""Cue-sheet music: join design (pure), rendering on synthetic beds/stings, and a film.json end-to-end mix."""
from __future__ import annotations

import json
import math
from array import array
from pathlib import Path

import pytest

from showreel_core.audio.cuesheet import STING_GAP_S, fit_cue_sheet, parse_cue_sheet, plan_cue_sheet, plan_open
from showreel_core.audio.ffmpeg_io import SR, decode_f32, wav_info, write_wav_f32
from showreel_core.audio.music import PRE_S, Bed

LAYOUT = [("intro", 4), ("A", 8), ("build", 4), ("drop", 8), ("B", 8), ("outro", 2), ("end", 1)]
SDK_EXAMPLE = [{"bed": "pixel_boss", "t0": 0, "t1": 22.5}, {"sting": "bloom_riser", "t": 21.2},
               {"bed": "dream", "t0": 22.5, "t1": 45}]


def bed(bid: str, family: str, bpm: float, key: str = "", cadence_to: str = "", path: Path | None = None) -> Bed:
    secs, b = [], 0
    for name, n in LAYOUT:
        secs.append({"name": name, "start_bar": b, "bars": n, "energy": 0.5})
        b += n
    return Bed(id=bid, style=family, path=path or Path("missing.ogg"), bpm=bpm, beats_per_bar=4, bar_s=240.0 / bpm,
               sections=secs, drop_bar=16, end_bar=34, total_bars=35, tail_s=2.0, key=key, family=family,
               cadence_to=cadence_to)


BEDS = {"pixel_boss_a": bed("pixel_boss_a", "pixel_boss", 160, "A minor", "C major"),
        "pixel_boss_b": bed("pixel_boss_b", "pixel_boss", 168, "E minor", "G major"),
        "dream_a": bed("dream_a", "dream", 80, "C major"), "dream_b": bed("dream_b", "dream", 88, "G major"),
        "launch_a": bed("launch_a", "launch", 124, "D major")}


def resolver(ref, seed, key):  # noqa: ANN001, ANN201 - test double for resolve_bed
    if ref in BEDS:
        return BEDS[ref]
    fam = [b for b in BEDS.values() if b.family == ref]
    if key:
        fam = [b for b in fam if b.key == key] or fam
    return fam[seed % len(fam)] if fam else None


# ------------------------------------------------------------------------------- planning

def test_parse_clamps_sorts_and_skips():
    beds, stings, warns = parse_cue_sheet([{"bed": "x", "t0": 5, "t1": 99}, {"bed": "y", "t0": -1, "t1": 5},
                                           {"bed": "tiny", "t0": 3, "t1": 3.2}, {"sting": "s", "t": 50},
                                           {"sting": "s", "t": 4}, "junk"], 30.0)
    assert beds == [("y", 0.0, 5.0), ("x", 5.0, 30.0)]
    assert [s.t for s in stings] == [4.0]
    assert len(warns) == 2


def test_sdk_example_designs_a_sting_join_with_key_pairing():
    cp = plan_cue_sheet(SDK_EXAMPLE, 45.0, resolver, seed=1, last_word_time=41.0)
    a, b = cp.segments
    assert a.bed.family == "pixel_boss" and b.bed.key == a.bed.cadence_to          # dream in the cadence key
    assert (a.join_out, b.join_in) == ("sting", "sting") and a.sting is not None and a.sting.t == 21.2
    assert a.end <= 21.2 - STING_GAP_S + 1e-9 and a.fade_out_s > 0.5                # suck-out under the riser
    assert b.anchor == 22.5 and b.closed and b.join_out == "final"
    end_hit = b.anchor + b.plan.n_bars * b.bed.bar_s
    assert 41.0 <= end_hit <= 45.0 - 0.6                                           # after the last word, rings
    assert not a.closed and 34 not in a.plan.source_bars                           # outgoing never plays its end hit
    assert a.plan.labels[-1] == "outro" or a.plan.labels[-2] == "outro"


def test_late_sting_moves_the_incoming_downbeat_onto_the_impact():
    cp = plan_cue_sheet([{"bed": "pixel_boss_a", "t0": 0, "t1": 20}, {"sting": "bloom_riser", "t": 20.6},
                         {"bed": "dream_a", "t0": 20, "t1": 40}], 40.0, resolver)
    a, b = cp.segments
    assert b.anchor == pytest.approx(20.6) and a.end <= 20.0 - STING_GAP_S + 1e-9
    assert any("starts on the sting impact" in w for w in cp.warnings)


def test_downbeat_crossfade_without_a_sting():
    cp = plan_cue_sheet([{"bed": "launch_a", "t0": 0, "t1": 13.0}, {"bed": "dream_b", "t0": 13.0, "t1": 30}], 30.0,
                        resolver)
    a, b = cp.segments
    assert (a.join_out, b.join_in) == ("crossfade", "crossfade") and b.anchor == 13.0
    beat = a.bed.bar_s / 4
    assert 13.0 - beat - PRE_S - 1e-9 <= a.end <= 13.0 - PRE_S + 1e-9 and a.fade_out_s <= min(beat, 0.5) + 1e-9
    bar = a.bed.bar_s
    assert plan_open(a.bed, a.end - a.anchor).n_bars * bar >= a.end - a.anchor     # bars cover the segment


def test_crossfade_stops_on_a_bar_line_just_before_the_switch():
    bar = BEDS["launch_a"].bar_s
    switch = 6 * bar + 0.05                                                       # 50 ms after a bar line
    cp = plan_cue_sheet([{"bed": "launch_a", "t0": 0, "t1": switch}, {"bed": "dream_a", "t0": switch, "t1": 30}],
                        30.0, resolver)
    assert cp.segments[0].end == pytest.approx(6 * bar - PRE_S)


def test_gap_join_lets_the_outgoing_bed_end_on_its_hit():
    cp = plan_cue_sheet([{"bed": "launch_a", "t0": 0, "t1": 12}, {"bed": "dream_a", "t0": 14, "t1": 30}], 30.0, resolver)
    a, b = cp.segments
    assert (a.join_out, b.join_in) == ("gap", "gap") and a.closed and a.end == 14.0 and b.anchor == 14.0
    assert a.plan.n_bars * a.bed.bar_s <= 12.0 + 1e-9


def test_overlaps_unknown_beds_and_extension():
    cp = plan_cue_sheet([{"bed": "launch_a", "t0": 0, "t1": 12}, {"bed": "nope", "t0": 5, "t1": 9},
                         {"bed": "dream_a", "t0": 10, "t1": 25}], 30.0, resolver)
    assert [s.bed.id for s in cp.segments] == ["launch_a", "dream_a"]
    assert cp.segments[0].end <= 10.0 and cp.segments[1].t1 == 30.0
    assert any("unknown music bed 'nope'" in w for w in cp.warnings) and any("extended" in w for w in cp.warnings)
    fb = plan_cue_sheet([{"bed": "nope", "t0": 0, "t1": 30}], 30.0, resolver, fallback="dream_b")
    assert [s.bed.id for s in fb.segments] == ["dream_b"] and fb.segments[0].closed


def test_single_segment_matches_the_plain_bar_fit():
    from showreel_core.audio.music import plan_bars
    cp = plan_cue_sheet([{"bed": "launch_a", "t0": 0, "t1": 30}], 30.0, resolver, drop_times=[12.0],
                        last_word_time=27.0)
    (s,) = cp.segments
    ref = plan_bars(BEDS["launch_a"], 30.0, 12.0, 27.0)
    assert s.plan.source_bars == ref.source_bars and s.plan.n_bars == ref.n_bars


# ------------------------------------------------------------------------------- rendering

def _tone(path: Path, seconds: float, freq: float, amp: float) -> Path:
    per = int(SR / freq)
    one = array("f")
    for i in range(per):
        v = amp * math.sin(2 * math.pi * i / per)
        one += array("f", [v, v])
    reps = int(seconds * SR) // per + 1
    return write_wav_f32(path, one * reps, 2)


@pytest.fixture()
def assets(tmp_path: Path) -> Path:
    """Synthetic assets dir: two beds (240 / 120 BPM tones) and a sting whose impulse sits at 0.5 s."""
    root = tmp_path / "assets"
    for fam, bid, bpm, key, freq in (("boss", "boss_a", 240.0, "A minor", 240.0), ("calm", "calm_a", 120.0, "C major", 480.0)):
        d = root / "beds" / fam
        d.mkdir(parents=True)
        bar = 240.0 / bpm
        _tone(d / f"{bid}.wav", 35 * bar + 2.0, freq, 0.2)
        secs, b = [], 0
        for name, n in LAYOUT:
            secs.append({"name": name, "start_bar": b, "bars": n, "energy": 0.5})
            b += n
        meta = {"style": fam, "beds": [{"id": bid, "file": f"{bid}.wav", "bpm": bpm, "beats_per_bar": 4, "bar_s": bar,
                                        "key": key, "total_bars": 35, "tail_s": 2.0, "drop_bar": 16, "end_bar": 34,
                                        "sections": secs, "lufs": -16.0, "family": fam,
                                        "cadence_to": "C major" if fam == "boss" else ""}]}
        (d / "bars.json").write_text(json.dumps(meta), encoding="utf-8")
    s = root / "sfx"
    s.mkdir(parents=True)
    imp = array("f", bytes(4 * 2 * SR))
    k = int(0.5 * SR)
    imp[2 * k] = imp[2 * k + 1] = 0.5
    write_wav_f32(s / "sting_1.wav", imp, 2)
    kit = {"version": 1, "styles": {"launch": {}}, "aliases": {"bloom": "sting"}, "sounds": {"sting": {
        "class": "hero", "gain_db": -4.0, "sync": "hit", "tags": [],
        "variants": [{"file": "sting_1.wav", "dur": 1.0, "onset": 0.5, "peak": 0.5, "end": 0.5, "hit": 0.5,
                      "st_lufs": -18.0, "key": "C major"}]}}}
    (s / "sfx.json").write_text(json.dumps(kit), encoding="utf-8")
    return root


def test_fit_cue_sheet_renders_joins_and_lands_the_impact(tmp_path, assets, ffmpeg):
    dur = 12.0
    res = fit_cue_sheet([{"bed": "boss", "t0": 0, "t1": 6.0}, {"sting": "bloom", "t": 5.7},
                         {"bed": "calm", "t0": 6.0, "t1": dur}], dur, tmp_path / "m.wav", ffmpeg=ffmpeg, assets=assets)
    assert wav_info(res.path) == (2, SR, int(dur * SR))
    a, b = res.segments
    assert (a.bed_id, b.bed_id) == ("boss_a", "calm_a") and b.t0 == 6.0 and a.t1 <= 5.7 - STING_GAP_S + 1e-9
    assert a.downbeats[0] == 0.0 and b.downbeats[0] == 6.0 and b.end_time is not None and b.end_time <= dur - 0.6
    assert [s.name for s in res.stings] == ["sting"] and res.stings[0].join and res.consumed[0]["sting"] == "bloom"
    x = decode_f32(res.path, 2, ffmpeg)
    mono = [abs(x[2 * i]) for i in range(len(x) // 2)]

    def peak_at(t0: float, t1: float) -> tuple[int, float]:
        i0, i1 = int(t0 * SR), int(t1 * SR)
        seg = mono[i0:i1]
        k = max(range(len(seg)), key=seg.__getitem__)
        return i0 + k, seg[k]

    k, v = peak_at(5.6, 5.8)
    assert k == round(5.7 * SR) and v == pytest.approx(0.5 * 10 ** (3.0 / 20), rel=0.02)   # +3 dB over -18 LUFS st
    assert max(mono[int((5.7 - STING_GAP_S + 0.002) * SR):int(5.69 * SR)]) < 1e-6          # suck-out before the hit
    assert max(mono[int(5.71 * SR):int(5.99 * SR)]) < 1e-6                                 # only the sting rings
    assert max(mono[int(6.02 * SR):int(6.2 * SR)]) > 0.15                                   # the calm bed is in
    assert max(mono[int(1.0 * SR):int(4.0 * SR)]) > 0.15                                    # the boss bed played


def test_fit_film_music_without_beds_uses_the_style(tmp_path, assets, ffmpeg):
    from showreel_core.audio.cuesheet import fit_film_music
    res = fit_film_music({"dur": 5.0, "music": []}, tmp_path / "m.wav", style="calm", ffmpeg=ffmpeg, assets=assets)
    assert [s.bed_id for s in res.segments] == ["calm_a"] and res.segments[0].join_out == "final"
    assert wav_info(res.path)[2] == 5 * SR
