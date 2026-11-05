"""Video QA without ffprobe: decoded frame count, duration, black segments, frame-0 luminance, contact sheet.

One decode pass (``blackdetect`` + ``-progress``) yields the frame count and the black segments.
Public entry points never raise; failures land in ``VideoQAReport.error``.
"""
from __future__ import annotations

import io
import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..render.errors import RenderError
from ..render.ffmpeg import NO_WINDOW, extract_frame, media_info, parse_progress, resolve_ffmpeg

_BLACK_RE = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)\s+black_duration:\s*([\d.]+)")

FRAME0_MIN_LUMA = 16.0      # frame 0 is the thumbnail: it must not be (near) black
BLACK_MIN_S = 0.5           # blackdetect minimum segment length
BLACK_PIX_TH = 0.10         # blackdetect pixel threshold (fraction of range)


@dataclass
class VideoQAReport:
    """Result of :func:`check_video`. ``ok`` is False when any ``error``-severity issue exists."""
    ok: bool = False
    path: str = ""
    frames: int | None = None
    expected_frames: int | None = None
    duration_s: float | None = None
    expected_duration_s: float | None = None
    width: int = 0
    height: int = 0
    fps: float | None = None
    video_codec: str = ""
    color: str = ""
    audio_codec: str = ""
    black_segments: list[tuple[float, float]] = field(default_factory=list)
    black_total_s: float = 0.0
    frame0_luma: float | None = None
    contact_sheet: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def issue(self, kind: str, msg: str, severity: str = "error") -> None:
        self.issues.append({"kind": kind, "severity": severity, "msg": msg})


def parse_blackdetect(text: str) -> list[tuple[float, float]]:
    """``[(start, end), ...]`` from blackdetect log lines."""
    return [(float(a), float(b)) for a, b, _ in _BLACK_RE.findall(text)]


def decode_pass(ffmpeg: str, path: Path, *, black_min_s: float = BLACK_MIN_S,
                pix_th: float = BLACK_PIX_TH, timeout: float = 900) -> tuple[int, list[tuple[float, float]]]:
    """Decode every frame once: (decoded frame count, black segments)."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1", "-i", str(path), "-map", "0:v:0",
           "-vf", f"blackdetect=d={black_min_s:g}:pix_th={pix_th:g}", "-an", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                           timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        raise RenderError("ffmpeg", f"decode pass failed: {e}") from e
    if p.returncode != 0:
        raise RenderError("ffmpeg", f"decode pass failed (exit {p.returncode})", stderr=p.stderr[-1500:])
    frame = parse_progress(p.stdout).get("frame", "")
    if not frame.isdigit():
        raise RenderError("ffmpeg", "decode pass reported no frame count")
    return int(frame), parse_blackdetect(p.stderr)


def frame_luma(png: bytes) -> float:
    """Mean luminance (0..255) of an image."""
    from PIL import Image, ImageStat

    return float(ImageStat.Stat(Image.open(io.BytesIO(png)).convert("L")).mean[0])


def make_contact_sheet(ffmpeg: str, path: Path, times: Sequence[float], out_png: Path, *,
                       labels: Sequence[str] | None = None, thumb_w: int = 480, cols: int | None = None) -> Path:
    """One thumbnail per time (e.g. scene midpoints) in a labelled grid PNG. Raises RenderError."""
    from PIL import Image, ImageDraw, ImageFont

    if not times:
        raise RenderError("io", "contact sheet needs at least one time")
    thumbs = []
    for t in times:
        im = Image.open(io.BytesIO(extract_frame(ffmpeg, path, t))).convert("RGB")
        th = max(1, round(im.height * thumb_w / im.width))
        thumbs.append(im.resize((thumb_w, th), Image.Resampling.LANCZOS))
    n = len(thumbs)
    cols = cols or min(n, 4 if thumbs[0].width >= thumbs[0].height else 6)
    rows = (n + cols - 1) // cols
    pad, label_h = 12, 30
    cell_w, cell_h = thumb_w, max(t.height for t in thumbs)
    sheet = Image.new("RGB", (pad + cols * (cell_w + pad), pad + rows * (cell_h + label_h + pad)), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    try:
        font: Any = ImageFont.load_default(18)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    for i, (im, t) in enumerate(zip(thumbs, times)):
        r, c = divmod(i, cols)
        x, y = pad + c * (cell_w + pad), pad + r * (cell_h + label_h + pad)
        sheet.paste(im, (x, y))
        text = f"{i + 1}. {t:.2f}s" + (f"  {labels[i]}" if labels and i < len(labels) else "")
        draw.text((x + 2, y + cell_h + 5), text[:60], fill=(220, 220, 225), font=font)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png, "PNG")
    return out_png


def check_video(path: Path, *, expected_frames: int | None = None, expected_duration_s: float | None = None,
                fps: float | None = None, scene_times: Sequence[float] | None = None,
                scene_labels: Sequence[str] | None = None, contact_sheet: Path | None = None,
                ffmpeg: str | None = None, black_min_s: float = BLACK_MIN_S,
                allowed_black: Sequence[tuple[float, float]] = ()) -> VideoQAReport:
    """QA an encoded video. Never raises.

    Errors: unreadable file, frame-count mismatch, duration off by more than one frame.
    Warnings: black segments (outside ``allowed_black`` windows), dark frame 0, missing BT.709 tags.
    ``scene_times`` (e.g. scene midpoints) + ``contact_sheet`` path -> a contact sheet PNG.
    """
    rep = VideoQAReport(path=str(path), expected_frames=expected_frames, expected_duration_s=expected_duration_s)
    try:
        ff = ffmpeg or resolve_ffmpeg().path
        info = media_info(ff, Path(path))
        rep.duration_s, rep.width, rep.height, rep.fps = info.duration_s, info.width, info.height, info.fps
        rep.video_codec, rep.color, rep.audio_codec = info.video_codec, info.color, info.audio_codec
        rep.frames, rep.black_segments = decode_pass(ff, Path(path), black_min_s=black_min_s)
        rep.black_total_s = round(sum(b - a for a, b in rep.black_segments), 3)
        rate = fps or info.fps or 30.0
        if expected_frames is not None and rep.frames != expected_frames:
            rep.issue("frame_count", f"decoded {rep.frames} frames, expected {expected_frames}")
        if expected_duration_s is not None and rep.duration_s is not None \
                and abs(rep.duration_s - expected_duration_s) > 1.0 / rate + 1e-3:
            rep.issue("duration", f"duration {rep.duration_s:.3f}s, expected {expected_duration_s:.3f}s")
        for a, b in rep.black_segments:
            if not any(a >= lo - 1e-3 and b <= hi + 1e-3 for lo, hi in allowed_black):
                rep.issue("black", f"black from {a:.2f}s to {b:.2f}s", "warning")
        rep.frame0_luma = round(frame_luma(extract_frame(ff, Path(path), 0.0)), 2)
        if rep.frame0_luma < FRAME0_MIN_LUMA:
            rep.issue("frame0_dark", f"frame 0 mean luma {rep.frame0_luma:.1f} < {FRAME0_MIN_LUMA:g} (thumbnail)",
                      "warning")
        if rep.video_codec == "h264" and ("bt709" not in rep.color or "unknown" in rep.color):
            rep.issue("color_tags", f"stream colour tags are '{rep.color}', expected bt709", "warning")
        if scene_times and contact_sheet is not None:
            rep.contact_sheet = str(make_contact_sheet(ff, Path(path), scene_times, contact_sheet,
                                                       labels=scene_labels))
        rep.ok = not any(i["severity"] == "error" for i in rep.issues)
    except RenderError as e:
        rep.error = e.to_dict()
    except Exception as e:  # never raise out of QA
        rep.error = {"code": "internal", "message": f"{type(e).__name__}: {e}"}
    return rep
