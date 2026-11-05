"""Audio QA parsing + an end-to-end QA run on a synthetic file."""
from __future__ import annotations

import pytest

from showreel_core.qa.audio import audio_report, parse_ebur128, parse_silences

EBUR = """
[Parsed_ebur128_0 @ 000001] t: 4.9  TARGET:-23 LUFS    M: -14.1 S: -14.3     I: -14.2 LUFS       LRA:   2.1 LU
[Parsed_ebur128_0 @ 000001] Summary:

  Integrated loudness:
    I:         -14.1 LUFS
    Threshold: -24.4 LUFS

  Loudness range:
    LRA:         5.3 LU
    Threshold:  -34.5 LUFS
    LRA low:    -18.1 LUFS
    LRA high:   -12.8 LUFS

  True peak:
    Peak:       -1.6 dBFS
"""


def test_parse_ebur128_summary_only():
    assert parse_ebur128(EBUR) == {"lufs_i": -14.1, "lra": 5.3, "true_peak_db": -1.6}


def test_parse_ebur128_silence():
    s = "Summary:\n  Integrated loudness:\n    I:         -inf LUFS\n  True peak:\n    Peak:       -inf dBFS\n"
    r = parse_ebur128(s)
    assert r["lufs_i"] == -99.0 and r["true_peak_db"] == -99.0


def test_parse_silences_unterminated():
    log = ("[silencedetect @ 0] silence_start: 1.5\n[silencedetect @ 0] silence_end: 2.4 | silence_duration: 0.9\n"
           "[silencedetect @ 0] silence_start: 9.2\n")
    assert parse_silences(log, 10.0) == [(1.5, 2.4), (9.2, 10.0)]


def test_audio_report_on_tone(tmp_path, ffmpeg):
    from .conftest import tone_wav

    f = tone_wav(tmp_path / "t.wav", 4.0, 440.0, 0.25, tail=1.0, channels=2)
    rep = audio_report(f, 5.0, ffmpeg=ffmpeg)
    assert rep["lufs_i"] == pytest.approx(-12.7, abs=0.4)    # -12 dBFS sine on both channels: -15 + 3 - 0.7
    assert rep["clipped_samples"] == 0 and rep["sample_peak_db"] == pytest.approx(-12.04, abs=0.05)
    assert rep["longest_gap_s"] == 0.0                                    # the tail silence touches the end
    assert rep["gaps"] and rep["gaps"][-1][1] == pytest.approx(5.0, abs=0.05)
    assert set(rep["gates"]) == {"loudness", "true_peak", "no_clipping", "no_gap"}
