"""TTS envelope parsing and synthesize() with a fake dispatch."""
from __future__ import annotations

import json
import math
from array import array

import pytest

from showreel_core.audio.ffmpeg_io import SR, decode_f32, wav_info
from showreel_core.audio.tts import active_rms_db, parse_envelope, synthesize

from .conftest import tone_wav


def test_parse_envelope_success_variants():
    ok = {"success": True, "file_path": "a.mp3", "file_paths": ["a.mp3", "b.mp3"], "provider": "edge"}
    assert parse_envelope(json.dumps(ok)) == (["a.mp3", "b.mp3"], "edge", "")
    assert parse_envelope({"success": True, "file_path": "x.mp3"}) == (["x.mp3"], "", "")
    assert parse_envelope(json.dumps(ok).encode()) == (["a.mp3", "b.mp3"], "edge", "")


@pytest.mark.parametrize("raw", ['{"success": false, "error": "no provider"}', "not json", "[1,2]",
                                 '{"success": true}', None])
def test_parse_envelope_failures(raw):
    files, _prov, err = parse_envelope(raw)
    assert files == [] and err


def test_active_rms_ignores_silence():
    a = array("f", [0.0] * SR)                      # 1 s silence
    a.extend(0.1 * math.sin(2 * math.pi * 200 * i / SR) for i in range(SR))
    assert active_rms_db(a) == pytest.approx(20 * math.log10(0.1 / math.sqrt(2)), abs=0.2)


class FakeDispatch:
    def __init__(self, tmp, fail=False, raise_=False):
        self.tmp, self.fail, self.raise_, self.calls = tmp, fail, raise_, []

    def __call__(self, name, args, **kw):
        self.calls.append((name, args))
        if self.raise_:
            raise RuntimeError("boom")
        if self.fail:
            return json.dumps({"success": False, "error": "provider missing"})
        out = args["output_path"]
        tone_wav(self.tmp / "tts.wav", 2.0, 180.0, 0.05, lead=0.6, tail=0.9)
        (self.tmp / "tts.wav").replace(out)          # providers may write any container; ffmpeg probes content
        return json.dumps({"success": True, "file_path": out, "file_paths": [out], "provider": "fake"})


def test_synthesize_normalises_trims_and_measures(tmp_path, ffmpeg):
    d = FakeDispatch(tmp_path)
    clip = synthesize(d, "Hello there.", tmp_path / "vo_00.wav", ffmpeg=ffmpeg)
    assert clip is not None
    name, args = d.calls[0]
    assert name == "text_to_speech" and args["output_path"].endswith("vo_00.tts.mp3")
    assert clip.provider == "fake"
    # 2.0 s of tone + <= 0.03 s kept before + <= 0.08 s kept after; the 0.6 / 0.9 s edges are gone
    assert 2.0 <= clip.duration <= 2.15
    ch, sr, frames = wav_info(clip.path)
    assert (ch, sr) == (1, SR) and frames / SR == pytest.approx(clip.duration, abs=1e-3)
    assert active_rms_db(decode_f32(clip.path, 1, ffmpeg)) == pytest.approx(-20.0, abs=0.3)
    assert clip.gain_db == pytest.approx(-20.0 - 20 * math.log10(0.05 / math.sqrt(2)), abs=0.3)


def test_synthesize_returns_none_on_failure(tmp_path, ffmpeg):
    assert synthesize(FakeDispatch(tmp_path, fail=True), "Hi.", tmp_path / "a.wav", ffmpeg=ffmpeg) is None
    assert synthesize(FakeDispatch(tmp_path, raise_=True), "Hi.", tmp_path / "b.wav", ffmpeg=ffmpeg) is None
    assert synthesize(FakeDispatch(tmp_path), "   ", tmp_path / "c.wav", ffmpeg=ffmpeg) is None
