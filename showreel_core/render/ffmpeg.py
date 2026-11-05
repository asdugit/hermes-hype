"""ffmpeg resolution, capability probing, command builders and probes that need no ffprobe.

Resolution order: ``SHOWREEL_FFMPEG`` / ``FFMPEG_PATH`` env -> Hermes ``pm`` (lazy import)
-> ``shutil.which("ffmpeg")`` -> :class:`RenderError` with an install hint.

Everything that inspects media parses ``ffmpeg -i`` / ``-progress`` output, because ffprobe
is missing from Hermes's macOS ffmpeg build.
"""
from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import RenderError

ENV_VARS = ("SHOWREEL_FFMPEG", "FFMPEG_PATH")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Output colour tags written on every encode (sRGB page -> BT.709 limited range).
BT709_TAGS = ("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv")


# ----------------------------------------------------------------------------- resolve

@dataclass(frozen=True)
class FFmpegInfo:
    """A resolved ffmpeg binary."""
    path: str
    source: str            # "env" | "pm" | "path"


def _pm_binary(name: str) -> Path | None:
    """Binary of a Hermes pm package, or None when pm is unavailable/not installed."""
    try:
        import pm  # type: ignore[import-not-found]  # Hermes-only, lazy
        inst = pm.installed_package(name)
    except Exception:
        return None
    binary = getattr(inst, "binary", None) if inst else None
    return Path(binary) if binary and Path(binary).is_file() else None


def _is_exe(p: str | Path) -> bool:
    path = Path(p)
    return path.is_file() and os.access(path, os.X_OK)


def resolve_ffmpeg(env: Mapping[str, str] | None = None, *,
                   pm_lookup: Callable[[str], Path | None] = _pm_binary,
                   which: Callable[[str], str | None] = shutil.which) -> FFmpegInfo:
    """Find ffmpeg. Raises :class:`RenderError` (``bad_env_ffmpeg`` / ``no_ffmpeg``)."""
    env = os.environ if env is None else env
    for var in ENV_VARS:
        val = env.get(var, "").strip()
        if val:
            if _is_exe(val):
                return FFmpegInfo(str(Path(val)), "env")
            raise RenderError("bad_env_ffmpeg", f"{var}={val!r} is not an executable file",
                              hint=f"Fix or unset {var}.")
    found = pm_lookup("ffmpeg")
    if found is not None:
        return FFmpegInfo(str(found), "pm")
    w = which("ffmpeg")
    if w:
        return FFmpegInfo(str(Path(w)), "path")
    raise RenderError("no_ffmpeg", "ffmpeg was not found",
                      hint="Run `hermes pm install ffmpeg`, install ffmpeg on PATH, or set SHOWREEL_FFMPEG.")


# ------------------------------------------------------------------------ capabilities

_ENC_RE = re.compile(r"^\s*V[\w.]{5}\s+(\S+)", re.MULTILINE)
_FILT_RE = re.compile(r"^\s*[TSC.]{2,3}\s+(\S+)\s+\S*->\S*[VN]", re.MULTILINE)  # video or dynamic outputs


def parse_encoders(text: str) -> frozenset[str]:
    """Video encoder names from ``ffmpeg -encoders`` output."""
    return frozenset(_ENC_RE.findall(text))


def parse_filters(text: str) -> frozenset[str]:
    """Video filter names (output V or dynamic N) from ``ffmpeg -filters`` output."""
    return frozenset(_FILT_RE.findall(text))


def _run_text(cmd: Sequence[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                          timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)


# Fallback order (SPEC section 4). Platform-only encoders are skipped elsewhere.
ENCODER_ORDER = ("libx264", "libopenh264", "h264_mf", "h264_videotoolbox", "libvpx-vp9")
_PLATFORM_ONLY = {"h264_mf": "win32", "h264_videotoolbox": "darwin"}


@dataclass(frozen=True)
class Capabilities:
    """What an ffmpeg build can do. ``working`` lists encoders that passed a test encode."""
    path: str
    version: str
    encoders: frozenset[str]
    filters: frozenset[str]
    working: tuple[str, ...]

    def has_filters(self, *names: str) -> bool:
        return all(n in self.filters for n in names)


def _smoke_encode(ffmpeg: str, encoder: str) -> bool:
    """True when ``encoder`` really encodes 8 tiny frames (listed != usable, e.g. missing DLLs)."""
    spec = encoder_spec(encoder, 128, 72, 30)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi",
           "-i", "testsrc2=size=128x72:rate=30:duration=0.27", "-vf", "format=yuv420p",
           *spec.args, "-f", "null", "-"]
    try:
        return _run_text(cmd, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@functools.lru_cache(maxsize=8)
def _capabilities_cached(path: str, _mtime_ns: int, platform: str) -> Capabilities:
    ver = _run_text([path, "-hide_banner", "-version"]).stdout.splitlines()
    version = ver[0] if ver else ""
    enc = parse_encoders(_run_text([path, "-hide_banner", "-encoders"]).stdout)
    filt = parse_filters(_run_text([path, "-hide_banner", "-filters"]).stdout)
    working = []
    for name in ENCODER_ORDER:
        if name not in enc or _PLATFORM_ONLY.get(name, platform) != platform:
            continue
        if _smoke_encode(path, name):
            working.append(name)
            if name == "libx264":
                break  # the preferred encoder works: skip probing the fallbacks
    return Capabilities(path, version, enc, filt, tuple(working))


def capabilities(ffmpeg: str) -> Capabilities:
    """Probe (and cache per binary path+mtime) encoders, filters and working encoders."""
    try:
        mtime = Path(ffmpeg).stat().st_mtime_ns
    except OSError as e:
        raise RenderError("no_ffmpeg", f"ffmpeg not accessible: {e}") from e
    return _capabilities_cached(ffmpeg, mtime, sys.platform)


# ---------------------------------------------------------------------------- encoders

@dataclass(frozen=True)
class EncoderSpec:
    """Encoder name, output container and its ffmpeg output args (no pix_fmt/colour tags)."""
    name: str
    container: str                     # "mp4" | "webm"
    args: tuple[str, ...] = field(default_factory=tuple)


def _bitrate_k(w: int, h: int, fps: float) -> int:
    """Bitrate for encoders without CRF: ~0.2 bit/pixel/frame, i.e. ~12 Mb/s at 1080p30."""
    return max(800, int(w * h * fps * 0.2 / 1000))


def encoder_spec(name: str, w: int, h: int, fps: float, *, crf: int = 18, preset: str = "veryfast",
                 threads: int | None = None) -> EncoderSpec:
    """ffmpeg output args for ``name`` at the given size/fps."""
    thr = ("-threads", str(threads)) if threads else ()
    br = f"{_bitrate_k(w, h, fps)}k"
    if name == "libx264":
        return EncoderSpec(name, "mp4", ("-c:v", "libx264", "-preset", preset, "-crf", str(crf), *thr,
                                         "-pix_fmt", "yuv420p"))
    if name == "libopenh264":
        return EncoderSpec(name, "mp4", ("-c:v", "libopenh264", "-b:v", br, "-maxrate", br, *thr,
                                         "-pix_fmt", "yuv420p"))
    if name == "h264_mf":
        return EncoderSpec(name, "mp4", ("-c:v", "h264_mf", "-b:v", br, "-pix_fmt", "nv12"))
    if name == "h264_videotoolbox":
        return EncoderSpec(name, "mp4", ("-c:v", "h264_videotoolbox", "-b:v", br, "-pix_fmt", "yuv420p"))
    if name == "libvpx-vp9":
        return EncoderSpec(name, "webm", ("-c:v", "libvpx-vp9", "-crf", str(crf + 12), "-b:v", "0",
                                          "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", *thr,
                                          "-pix_fmt", "yuv420p"))
    raise ValueError(f"unknown encoder {name!r}")


@functools.lru_cache(maxsize=32)
def encoder_works(ffmpeg: str, encoder: str) -> bool:
    """Cached smoke encode of one encoder (listed in ``-encoders`` is not proof it works)."""
    return _smoke_encode(ffmpeg, encoder)


def pick_encoder(caps: Capabilities, preferred: str | None = None) -> str:
    """``preferred`` if it really encodes, else the first working encoder in fallback order."""
    if preferred and (preferred in caps.working or (preferred in caps.encoders and encoder_works(caps.path, preferred))):
        return preferred
    if caps.working:
        return caps.working[0]
    raise RenderError("no_encoder", f"no usable video encoder in {caps.path}",
                      hint="Install an ffmpeg build with libx264 (e.g. `hermes pm install ffmpeg`).",
                      tried=list(ENCODER_ORDER))


# -------------------------------------------------------------------- command builders

def chunk_encode_cmd(ffmpeg: str, *, fps: float, out_path: Path, enc: EncoderSpec,
                     filter_graph: str, extra_inputs: Sequence[str] = (), image_codec: str = "mjpeg",
                     progress: bool = True) -> list[str]:
    """Encode an image2pipe stream from stdin through ``filter_graph`` (labelled ``[0:v]``..``[vout]``).

    ``extra_inputs`` are additional ``-i`` arguments (e.g. a palette PNG) referenced by the graph.
    With ``progress`` the ``-progress pipe:1`` key=value stream is written to stdout.
    """
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats"]
    if progress:
        cmd += ["-progress", "pipe:1"]
    cmd += ["-f", "image2pipe", "-framerate", _num(fps), "-c:v", image_codec, "-i", "pipe:0", *extra_inputs,
            "-filter_complex", filter_graph, "-map", "[vout]", *enc.args, *BT709_TAGS, "-an"]
    if enc.container == "webm":
        cmd += ["-f", "webm"]
    else:
        cmd += ["-f", "mp4"]
    cmd += ["-y", str(out_path)]
    return cmd


def write_concat_list(paths: Iterable[Path], list_file: Path) -> Path:
    """Write an ffconcat list (UTF-8, quoted, forward slashes) for the concat demuxer."""
    lines = ["ffconcat version 1.0"]
    for p in paths:
        s = Path(p).resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{s}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_file


def concat_cmd(ffmpeg: str, list_file: Path, out_path: Path, *, container: str = "mp4") -> list[str]:
    """Stream-copy concat of chunk files listed in ``list_file`` (+faststart for MP4)."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-map", "0:v:0", "-c", "copy"]
    if container == "mp4":
        cmd += ["-movflags", "+faststart", "-f", "mp4"]
    else:
        cmd += ["-f", "webm"]
    return cmd + ["-y", str(out_path)]


def mux_cmd(ffmpeg: str, video: Path, audio: Path, out_path: Path, *, bitrate: str = "192k",
            duration_s: float | None = None) -> list[str]:
    """Copy video + encode audio (AAC for MP4, Opus for WebM), ``+faststart``."""
    webm = Path(out_path).suffix.lower() == ".webm"
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video), "-i", str(audio),
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
           "-c:a", "libopus" if webm else "aac", "-b:a", bitrate, "-ar", "48000"]
    if duration_s is not None:
        cmd += ["-t", _num(duration_s)]
    if not webm:
        cmd += ["-movflags", "+faststart"]
    return cmd + ["-y", str(out_path)]


def _num(x: float) -> str:
    """Compact decimal for ffmpeg args (30.0 -> '30', 29.97 -> '29.97')."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


# ------------------------------------------------------------------------------ runner

def run(cmd: Sequence[str], *, timeout: float = 600, what: str = "ffmpeg") -> subprocess.CompletedProcess[str]:
    """Run an ffmpeg command; raise ``RenderError('ffmpeg')`` with the stderr tail on failure."""
    try:
        p = _run_text(cmd, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RenderError("ffmpeg", f"{what} timed out after {timeout:.0f}s") from e
    except OSError as e:
        raise RenderError("ffmpeg", f"{what} could not start: {e}") from e
    if p.returncode != 0:
        raise RenderError("ffmpeg", f"{what} failed (exit {p.returncode})", stderr=p.stderr[-2000:])
    return p


def concat(ffmpeg: str, parts: Sequence[Path], out_path: Path, *, container: str = "mp4") -> Path:
    """Concatenate ``parts`` into ``out_path`` by stream copy (atomic rename)."""
    out_path = Path(out_path)
    lst = out_path.with_name(out_path.name + ".concat.txt")
    tmp = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    write_concat_list(parts, lst)
    try:
        run(concat_cmd(ffmpeg, lst, tmp, container=container), what="concat")
        os.replace(tmp, out_path)
    finally:
        lst.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return out_path


def mux(ffmpeg: str, video: Path, audio: Path, out_path: Path, *, bitrate: str = "192k",
        duration_s: float | None = None) -> Path:
    """Mux ``video`` (copied) with ``audio`` into ``out_path``."""
    run(mux_cmd(ffmpeg, video, audio, out_path, bitrate=bitrate, duration_s=duration_s), what="mux")
    return Path(out_path)


# ------------------------------------------------------------------------------ probes

@dataclass
class MediaInfo:
    """Container/stream facts parsed from ``ffmpeg -i`` (no ffprobe)."""
    duration_s: float | None = None
    video_codec: str = ""
    width: int = 0
    height: int = 0
    fps: float | None = None
    pix_fmt: str = ""
    color: str = ""                # e.g. "tv, bt709, progressive"
    audio_codec: str = ""
    sample_rate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VID_RE = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+)[^,]*,\s*(\w+)(?:\(([^)]*)\))?.*?,\s*(\d+)x(\d+)")
_FPS_RE = re.compile(r"([\d.]+)\s*fps")
_AUD_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\w+)[^,]*,\s*(\d+)\s*Hz")


def parse_media_info(text: str) -> MediaInfo:
    """Parse the stderr banner of ``ffmpeg -i FILE``."""
    info = MediaInfo()
    if m := _DUR_RE.search(text):
        h, mi, s = m.groups()
        info.duration_s = int(h) * 3600 + int(mi) * 60 + float(s)
    for line in text.splitlines():
        if not info.video_codec and (m := _VID_RE.search(line)):
            info.video_codec, info.pix_fmt = m.group(1), m.group(2)
            info.color = m.group(3) or ""
            info.width, info.height = int(m.group(4)), int(m.group(5))
            if f := _FPS_RE.search(line):
                info.fps = float(f.group(1))
        elif not info.audio_codec and (m := _AUD_RE.search(line)):
            info.audio_codec, info.sample_rate = m.group(1), int(m.group(2))
    return info


def media_info(ffmpeg: str, path: Path) -> MediaInfo:
    """Read duration, codecs, size, fps and colour tags of ``path``."""
    p = _run_text([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)], timeout=60)
    if "Duration:" not in p.stderr:
        raise RenderError("ffmpeg", f"cannot read media info of {path}", stderr=p.stderr[-1000:])
    return parse_media_info(p.stderr)


def parse_progress(text: str) -> dict[str, str]:
    """Last value of each key in an ffmpeg ``-progress`` key=value stream."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def null_pass_cmd(ffmpeg: str, path: Path, *, decode: bool = True, vf: str | None = None) -> list[str]:
    """Command that reads the first video stream to the null muxer, reporting ``-progress`` on stdout."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1", "-i", str(path),
           "-map", "0:v:0"]
    if not decode:
        cmd += ["-c", "copy"]
    elif vf:
        cmd += ["-vf", vf]
    return cmd + ["-f", "null", "-"]


def count_frames(ffmpeg: str, path: Path, *, decode: bool = True, timeout: float = 600) -> int:
    """Number of video frames (decoded, or packets with ``decode=False``) in ``path``."""
    p = run(null_pass_cmd(ffmpeg, path, decode=decode), timeout=timeout, what="frame count")
    frame = parse_progress(p.stdout).get("frame")
    if frame is None or not frame.isdigit():
        raise RenderError("ffmpeg", f"no frame count reported for {path}")
    return int(frame)


def extract_frame(ffmpeg: str, path: Path, t: float, out_png: Path | None = None) -> bytes:
    """Decode the frame at ``t`` seconds as PNG bytes (BT.709 limited -> sRGB); optionally save it."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{max(0.0, t):.4f}",
           "-i", str(path), "-frames:v", "1",
           "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
           "-f", "image2pipe", "-c:v", "png", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=120, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                           check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise RenderError("ffmpeg", f"frame extract failed: {e}") from e
    if p.returncode != 0 or not p.stdout:
        raise RenderError("ffmpeg", f"no frame at t={t:.3f}s in {path}",
                          stderr=p.stderr.decode("utf-8", "replace")[-1000:])
    if out_png is not None:
        Path(out_png).write_bytes(p.stdout)
    return p.stdout
