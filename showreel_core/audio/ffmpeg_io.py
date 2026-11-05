"""ffmpeg + WAV plumbing for the audio stage (stdlib only; ffmpeg runs as a subprocess with argument lists).

Samples are handled as interleaved ``array('f')`` (float32) buffers at 48 kHz.
"""
from __future__ import annotations

import struct
import subprocess
import sys
from array import array
from pathlib import Path

SR = 48000


class AudioError(RuntimeError):
    """Raised inside the audio package; public entry points convert it into structured errors."""


def _resolve() -> tuple[str | None, str]:
    """(path, problem) from the renderer's resolver, the one ffmpeg lookup shared by every stage."""
    from ..render.errors import RenderError
    from ..render.ffmpeg import resolve_ffmpeg
    try:
        return resolve_ffmpeg().path, ""
    except RenderError as e:
        return None, (f"{e.message}. {e.hint}" if e.hint else e.message)


def find_ffmpeg() -> str | None:
    """$SHOWREEL_FFMPEG / $FFMPEG_PATH -> Hermes pm-managed ffmpeg -> PATH (``render.ffmpeg.resolve_ffmpeg``).

    Never installs anything; ``None`` when nothing usable is found.
    """
    return _resolve()[0]


def require_ffmpeg(ffmpeg: str | None = None) -> str:
    if ffmpeg:
        return ffmpeg
    exe, problem = _resolve()
    if not exe:
        raise AudioError(f"ffmpeg not found: {problem or 'run `hermes pm install ffmpeg` or set SHOWREEL_FFMPEG'}")
    return exe


def run(args: list[str], *, input_bytes: bytes | None = None, timeout: float = 300.0) -> subprocess.CompletedProcess:
    """Run ffmpeg (args[0]) and return the completed process; raise AudioError with the stderr tail on failure."""
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        cp = subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout, creationflags=flags,
                            check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AudioError(f"ffmpeg failed to run: {e}") from e
    if cp.returncode != 0:
        tail = cp.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise AudioError("ffmpeg error: " + " | ".join(tail))
    return cp


def decode_f32(path: str | Path, channels: int = 2, ffmpeg: str | None = None, filters: str = "",
               sr: int = SR) -> array:
    """Decode any audio file to interleaved float32 at ``sr`` (optionally through an -af chain)."""
    exe = require_ffmpeg(ffmpeg)
    args = [exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path)]
    if filters:
        args += ["-af", filters]
    args += ["-f", "f32le", "-acodec", "pcm_f32le", "-ac", str(channels), "-ar", str(sr), "-"]
    out = run(args).stdout
    a = array("f")
    a.frombytes(out[: len(out) - len(out) % 4])
    if sys.byteorder == "big":
        a.byteswap()
    return a


def write_wav_f32(path: str | Path, samples: array, channels: int) -> Path:
    """Write interleaved float32 samples as a 48 kHz IEEE-float WAV (stdlib only)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = samples
    if sys.byteorder == "big":
        data = array("f", samples)
        data.byteswap()
    raw = data.tobytes()
    block = 4 * channels
    hdr = b"RIFF" + struct.pack("<I", 4 + 26 + 12 + 8 + len(raw)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHHH", 18, 3, channels, SR, SR * block, block, 32, 0)
    fact = b"fact" + struct.pack("<II", 4, len(samples) // channels)
    with open(p, "wb") as f:
        f.write(hdr + fmt + fact + b"data" + struct.pack("<I", len(raw)))
        f.write(raw)
    return p


def wav_info(path: str | Path) -> tuple[int, int, int]:
    """(channels, sample_rate, frames) of a PCM/float WAV by parsing chunks (no ffprobe)."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise AudioError(f"not a WAV file: {path}")
        ch = sr = bits = 0
        while True:
            h = f.read(8)
            if len(h) < 8:
                raise AudioError(f"WAV without data chunk: {path}")
            cid, size = h[:4], struct.unpack("<I", h[4:])[0]
            if cid == b"fmt ":
                body = f.read(size)
                _tag, ch, sr = struct.unpack("<HHI", body[:8])
                bits = struct.unpack("<H", body[14:16])[0]
            elif cid == b"data":
                return ch, sr, size // max(1, ch * bits // 8)
            else:
                f.seek(size + (size & 1), 1)
