"""Audio QA (stdlib + ffmpeg): loudness / true peak / LRA (ebur128), speech-band SNR proxy on stems,
longest silence gap, clipping. ``audio_report`` returns a JSON-able dict with pass/fail gates (SPEC 7)."""
from __future__ import annotations

import math
import re
from array import array
from pathlib import Path
from typing import Any

from ..audio.ffmpeg_io import AudioError, decode_f32, require_ffmpeg, run

GATES = {"lufs": (-15.0, -13.0), "true_peak_max": -1.0, "snr_min": 10.0, "gap_max": 0.6}

_SUMMARY = re.compile(r"Summary:(.*)", re.S)
_I = re.compile(r"I:\s+(-?[\d.]+|-inf)\s+LUFS")
_LRA = re.compile(r"LRA:\s+(-?[\d.]+)\s+LU")
_PEAK = re.compile(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf)\s+dBFS", re.S)
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")


def _num(s: str) -> float:
    return -99.0 if s.startswith("-inf") else float(s)


def parse_ebur128(stderr: str) -> dict[str, float]:
    """Parse the ebur128 summary block -> {lufs_i, lra, true_peak_db}. Missing values -> -99."""
    m = _SUMMARY.search(stderr)
    block = m.group(1) if m else stderr
    out = {"lufs_i": -99.0, "lra": 0.0, "true_peak_db": -99.0}
    if (x := _I.search(block)):
        out["lufs_i"] = _num(x.group(1))
    if (x := _LRA.search(block)):
        out["lra"] = float(x.group(1))
    if (x := _PEAK.search(block)):
        out["true_peak_db"] = _num(x.group(1))
    return out


def measure_loudness(path: str | Path, ffmpeg: str | None = None) -> dict[str, float]:
    """Integrated LUFS, LRA and true peak (dBTP) of any media file via ffmpeg ebur128."""
    exe = require_ffmpeg(ffmpeg)
    cp = run([exe, "-hide_banner", "-nostdin", "-nostats", "-i", str(path), "-vn", "-af",
              "ebur128=peak=true:framelog=quiet", "-f", "null", "-"])
    return parse_ebur128(cp.stderr.decode("utf-8", "replace"))


def parse_silences(stderr: str, duration: float) -> list[tuple[float, float]]:
    """silencedetect log -> [(start, end)] (an unterminated silence runs to ``duration``)."""
    starts = [float(x) for x in _SIL_START.findall(stderr)]
    ends = [(float(e), float(d)) for e, d in _SIL_END.findall(stderr)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i][0] if i < len(ends) else duration
        out.append((max(0.0, s), min(duration, e)))
    return out


def silences(path: str | Path, duration: float, noise_db: float = -50.0, min_s: float = 0.3,
             ffmpeg: str | None = None) -> list[tuple[float, float]]:
    exe = require_ffmpeg(ffmpeg)
    cp = run([exe, "-hide_banner", "-nostdin", "-nostats", "-i", str(path), "-vn", "-af",
              f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"])
    return parse_silences(cp.stderr.decode("utf-8", "replace"), duration)


def _frames_db(mono: array, frame: int) -> list[float]:
    out = []
    for i in range(0, len(mono) - frame + 1, frame):
        seg = mono[i:i + frame]
        e = sum(x * x for x in seg) / frame
        out.append(10 * math.log10(e) if e > 1e-12 else -120.0)
    return out


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return -99.0
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def speech_snr(voice_stem: str | Path, bed_stem: str | Path, ffmpeg: str | None = None) -> dict[str, float]:
    """Speech-band (300-4000 Hz) SNR of the voice stem over the music+SFX stem on voiced 20 ms frames.

    Measure on PRE-loudnorm stems from the same mix (a post-norm mix vs a pre-norm stem is meaningless).
    """
    band = "highpass=f=300:poles=2,highpass=f=300:poles=2,lowpass=f=4000:poles=2,lowpass=f=4000:poles=2"
    v = decode_f32(voice_stem, 1, ffmpeg, band, sr=16000)
    b = decode_f32(bed_stem, 1, ffmpeg, band, sr=16000)
    fr = 320                                    # 20 ms at 16 kHz
    vd, bd = _frames_db(v, fr), _frames_db(b, fr)
    n = min(len(vd), len(bd))
    if n == 0:
        return {"snr_median_db": -99.0, "snr_p5_db": -99.0, "voiced_frames": 0}
    top = _pct(vd[:n], 95)
    gate = max(-55.0, top - 22.0)
    snr = [vd[i] - bd[i] for i in range(n) if vd[i] > gate]
    return {"snr_median_db": round(_pct(snr, 50), 2), "snr_p5_db": round(_pct(snr, 5), 2), "voiced_frames": len(snr)}


def clipping(path: str | Path, ffmpeg: str | None = None, ceiling: float = 0.9999) -> dict[str, float]:
    """Sample peak (dBFS) and the number of samples at/over full scale."""
    a = decode_f32(path, 2, ffmpeg)
    if not a:
        return {"sample_peak_db": -99.0, "clipped_samples": 0}
    pk = max(max(a), -min(a))
    clipped = 0 if pk < ceiling else sum(1 for x in a if x >= ceiling or x <= -ceiling)
    return {"sample_peak_db": round(20 * math.log10(max(pk, 1e-12)), 2), "clipped_samples": clipped}


def audio_report(final: str | Path, duration: float, *, voice_stem: str | Path | None = None,
                 bed_stem: str | Path | None = None, ffmpeg: str | None = None,
                 captions_only: bool = False) -> dict[str, Any]:
    """Run every audio gate on the final mix (+ stems if given). Never raises; errors land in ``errors``."""
    rep: dict[str, Any] = {"file": str(final), "duration": duration, "errors": []}
    try:
        rep.update(measure_loudness(final, ffmpeg))
        rep.update(clipping(final, ffmpeg))
        sil = silences(bed_stem or final, duration, ffmpeg=ffmpeg)
        internal = [(a, b) for a, b in sil if b < duration - 0.05 and a > 0.05]
        rep["longest_gap_s"] = round(max((b - a for a, b in internal), default=0.0), 3)
        rep["gaps"] = [[round(a, 2), round(b, 2)] for a, b in sil]
        if voice_stem and bed_stem and not captions_only:
            rep.update(speech_snr(voice_stem, bed_stem, ffmpeg))
            mv = measure_loudness(bed_stem, ffmpeg)["lufs_i"] - measure_loudness(voice_stem, ffmpeg)["lufs_i"]
            rep["music_minus_voice_lu"] = round(mv, 2)
    except AudioError as e:
        rep["errors"].append(str(e))
    lo, hi = GATES["lufs"]
    g = {
        "loudness": lo <= rep.get("lufs_i", -99) <= hi,
        "true_peak": rep.get("true_peak_db", 0.0) <= GATES["true_peak_max"],
        "no_clipping": rep.get("clipped_samples", 1) == 0,
        "no_gap": rep.get("longest_gap_s", 99.0) <= GATES["gap_max"],
    }
    if "snr_median_db" in rep:
        g["speech_snr"] = rep["snr_median_db"] >= GATES["snr_min"]
    rep["gates"] = g
    rep["pass"] = all(g.values()) and not rep["errors"]
    return rep
