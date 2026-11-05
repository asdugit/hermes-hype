"""End-to-end: bar-fit a shipped bed, mix with a synthetic 'voice' and SFX, run QA (needs ffmpeg)."""
from __future__ import annotations

import pytest

from showreel_core.audio.ffmpeg_io import SR, wav_info
from showreel_core.audio.mix import VoicePlacement, mix
from showreel_core.audio.music import fit_bed, pick_bed
from showreel_core.audio.sfx import hero_times, load_kit, place_cues
from showreel_core.qa.audio import audio_report

from .conftest import tone_wav


def test_fit_bed_exact_length_and_grid(tmp_path, ffmpeg):
    bed = pick_bed("launch", 0, "launch_a")
    assert bed is not None
    fm = fit_bed(bed, 12.0, tmp_path / "music.wav", drop_time=5.0, ffmpeg=ffmpeg)
    ch, sr, frames = wav_info(fm.path)
    assert (ch, sr, frames) == (2, SR, 12 * SR)
    assert fm.downbeats[0] == 0.0 and fm.end_time == fm.downbeats[-1] <= 12.0 - 1.2
    assert fm.drop_time == pytest.approx(round(5.0 / bed.bar_s) * bed.bar_s, abs=1e-3)


def test_mix_end_to_end_meets_gates(tmp_path, ffmpeg):
    bed = pick_bed("launch", 0, "launch_a")
    assert bed is not None
    dur = 10.0
    fm = fit_bed(bed, dur, tmp_path / "music.wav", drop_time=4.0, ffmpeg=ffmpeg)
    v = tone_wav(tmp_path / "vo.wav", 3.0, 300.0, 0.14)                      # ~ -20 dBFS RMS stand-in voice
    kit = load_kit()
    assert kit is not None
    placed, _ = place_cues([{"t": 1.0, "sfx": "whoosh_short"}, {"t": 4.0, "sfx": "impact"}], kit, dur)
    res = mix(tmp_path / "final.wav", dur, music=fm.path, voices=[VoicePlacement(v, 5.0, 3.0)], sfx=placed,
              hero_times=hero_times(placed), work_dir=tmp_path, ffmpeg=ffmpeg)
    assert wav_info(res.path)[2] == int(dur * SR)
    rep = audio_report(res.path, dur, voice_stem=res.voice_stem, bed_stem=res.bed_stem, ffmpeg=ffmpeg)
    assert rep["gates"]["loudness"] and rep["gates"]["true_peak"] and rep["gates"]["no_clipping"]
    assert rep["snr_median_db"] > 6.0                                         # a pure tone vs a full bed
