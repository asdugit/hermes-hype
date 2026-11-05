"""Shared fixtures for the audio tests (synthetic data only)."""
from __future__ import annotations

import math
from array import array
from pathlib import Path

import pytest

from showreel_core.audio.ffmpeg_io import SR, find_ffmpeg, write_wav_f32
from showreel_core.audio.music import Bed

LAYOUT = [("intro", 4), ("A", 8), ("build", 4), ("drop", 8), ("B", 8), ("outro", 2), ("end", 1)]


def make_bed(path: Path | None = None, bpm: float = 120.0) -> Bed:
    """A Bed with the standard groove layout (35 bars) and no audio file unless ``path`` is given."""
    secs, b = [], 0
    for name, n in LAYOUT:
        secs.append({"name": name, "start_bar": b, "bars": n, "energy": 0.5})
        b += n
    return Bed(id="test_a", style="test", path=path or Path("missing.ogg"), bpm=bpm, beats_per_bar=4,
               bar_s=240.0 / bpm, sections=secs, drop_bar=16, end_bar=34, total_bars=35, tail_s=3.0)


@pytest.fixture(scope="session")
def ffmpeg() -> str:
    exe = find_ffmpeg()
    if not exe:
        pytest.skip("ffmpeg not available")
    return exe


def tone_wav(path: Path, seconds: float, freq: float = 220.0, amp: float = 0.1, lead: float = 0.0,
             tail: float = 0.0, channels: int = 1) -> Path:
    """Sine tone with optional leading/trailing digital silence, written as float WAV."""
    n_lead, n_tone, n_tail = int(lead * SR), int(seconds * SR), int(tail * SR)
    out = array("f", bytes(4 * channels * (n_lead + n_tone + n_tail)))
    for i in range(n_tone):
        v = amp * math.sin(2 * math.pi * freq * i / SR)
        for c in range(channels):
            out[(n_lead + i) * channels + c] = v
    return write_wav_f32(path, out, channels)
