"""Narration via Hermes ``text_to_speech`` (injected ``dispatch`` callable), normalised for the mix.

``synthesize`` never raises: it returns a :class:`VoiceClip` or ``None`` (the caller then falls back to
captions-only). The clip is converted to 48 kHz mono float WAV, edge silence is trimmed (edges only),
and it is level-matched to -20 dBFS active RMS. Never time-stretched or pitch-shifted.
"""
from __future__ import annotations

import json
import logging
import math
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

from .ffmpeg_io import SR, AudioError, require_ffmpeg, run, write_wav_f32

log = logging.getLogger(__name__)

Dispatch = Callable[..., Any]
TARGET_RMS_DB = -20.0
MAX_GAIN_DB = 24.0
EDGE_TRIM = ("silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.03:detection=peak,"
             "areverse,silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.08:detection=peak,areverse")


@dataclass
class VoiceClip:
    """A narration clip ready for the mix."""
    path: Path
    duration: float
    text: str
    provider: str = ""
    source_files: list[str] = field(default_factory=list)
    gain_db: float = 0.0
    active_rms_db: float = -99.0

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["path"] = str(self.path)
        return d


def parse_envelope(raw: Any) -> tuple[list[str], str, str]:
    """Parse the text_to_speech result envelope -> (file_paths, provider, error). Never raises."""
    data: Any = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return [], "", f"unparseable TTS result: {raw[:120]!r}"
    if not isinstance(data, dict):
        return [], "", "TTS result is not an object"
    if not data.get("success"):
        return [], str(data.get("provider", "")), str(data.get("error") or "TTS failed")
    files = data.get("file_paths") or ([data["file_path"]] if data.get("file_path") else [])
    files = [str(f) for f in files if isinstance(f, str) and f]
    if not files:
        return [], str(data.get("provider", "")), "TTS returned no file"
    return files, str(data.get("provider", "")), ""


def active_rms_db(mono: array, frame: int = 960, floor_db: float = -50.0, rel_db: float = 30.0) -> float:
    """RMS (dBFS) over frames that carry speech: above ``floor_db`` and within ``rel_db`` of the loudest frame."""
    frames = []
    for i in range(0, len(mono) - frame + 1, frame):
        seg = mono[i:i + frame]
        e = sum(x * x for x in seg) / frame
        frames.append(e)
    if not frames:
        return -99.0
    top = 10 * math.log10(max(max(frames), 1e-20))
    gate = max(floor_db, top - rel_db)
    act = [e for e in frames if 10 * math.log10(max(e, 1e-20)) > gate]
    if not act:
        return -99.0
    return 10 * math.log10(sum(act) / len(act))


def _concat_filter(n: int) -> str:
    pre = "".join(f"[{i}:a]" for i in range(n))
    return f"{pre}concat=n={n}:v=0:a=1,aformat=sample_fmts=flt:channel_layouts=mono,aresample={SR},{EDGE_TRIM}"


def normalise_clip(files: list[str], out_path: Path, ffmpeg: str | None = None,
                   target_rms_db: float = TARGET_RMS_DB) -> tuple[float, float, float]:
    """Concatenate TTS chunk files -> 48 kHz mono, trim edges, level-match. Returns (duration, gain_db, rms_db)."""
    exe = require_ffmpeg(ffmpeg)
    args = [exe, "-hide_banner", "-nostdin", "-loglevel", "error"]
    for f in files:
        args += ["-i", f]
    args += ["-filter_complex", _concat_filter(len(files)), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    raw = run(args).stdout
    mono = array("f")
    mono.frombytes(raw[: len(raw) - len(raw) % 4])
    if len(mono) < int(0.05 * SR):
        raise AudioError("TTS clip is silent after trimming")
    rms = active_rms_db(mono)
    gain = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, target_rms_db - rms))
    g = 10 ** (gain / 20.0)
    out = array("f", (x * g for x in mono))
    write_wav_f32(out_path, out, 1)
    return len(out) / SR, gain, rms


def synthesize(dispatch: Dispatch, text: str, out_path: str | Path, *, ffmpeg: str | None = None,
               speed: float | None = None, target_rms_db: float = TARGET_RMS_DB) -> VoiceClip | None:
    """Speak ``text`` with Hermes TTS and return a mix-ready :class:`VoiceClip` (``None`` on any failure).

    ``dispatch`` is ``ctx.dispatch_tool`` (or a fake in tests): ``dispatch("text_to_speech", args) -> str``.
    The provider output is forced to ``<out>.tts.mp3`` so messaging platforms never switch it to Opus.
    """
    text = (text or "").strip()
    if not text:
        return None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    args: dict[str, Any] = {"text": text, "output_path": str(out.with_name(out.stem + ".tts.mp3"))}
    if speed:
        args["speed"] = speed
    try:
        raw = dispatch("text_to_speech", args)
    except Exception as e:  # noqa: BLE001 - provider/plugin errors must never kill the render
        log.warning("showreel tts dispatch failed: %s", e)
        return None
    files, provider, err = parse_envelope(raw)
    files = [f for f in files if Path(f).is_file()]
    if err or not files:
        log.warning("showreel tts unavailable: %s", err or "files missing")
        return None
    try:
        dur, gain, rms = normalise_clip(files, out, ffmpeg, target_rms_db)
    except (AudioError, OSError) as e:
        log.warning("showreel tts normalise failed: %s", e)
        return None
    return VoiceClip(path=out, duration=round(dur, 4), text=text, provider=provider, source_files=files,
                     gain_db=round(gain, 2), active_rms_db=round(rms, 2))


__all__ = ["VoiceClip", "synthesize", "parse_envelope", "active_rms_db", "normalise_clip"]
