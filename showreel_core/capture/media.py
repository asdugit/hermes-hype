"""Media artifacts (images, videos, PDFs) -> capture-ready assets for ``product_capture`` events.

* images: a normalised copy (EXIF orientation applied; exotic formats converted to PNG), size,
  palette/accent, and a cutout attempt;
* videos: duration/size/fps (ffmpeg banner, no ffprobe), the most interesting frame as poster, and a
  cutout attempt: if the poster's backdrop is near-uniform, alpha PNG frames (``cutout/000001.png``
  ...) at a reduced rate/size plus a full-resolution poster cutout;
* PDFs: page count/title only (page images come from the browser, see ``web.capture_pdf_target``).

Cutouts are only produced when :func:`.cutout.fit_background` accepts the backdrop; their measured
quality travels with the asset so kits decide whether to use them. Frame sequences for the film
itself are extracted later by the film layer.
"""
from __future__ import annotations

import contextlib
import re
import shutil
import statistics
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageStat

from ..render.errors import RenderError
from ..render.ffmpeg import NO_WINDOW, parse_media_info, resolve_ffmpeg
from .colors import dominant_accent, palette
from .cutout import CutoutQuality, cutout, fit_background, model_fit

COPY_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}
ROTATE_RE = re.compile(r"(?:rotate\s*:\s*(-?\d+)|displaymatrix: rotation of (-?[\d.]+) degrees)")
SVG_SIZE_RE = re.compile(rb"<svg[^>]*?\bwidth=[\"']([\d.]+)(?:px)?[\"'][^>]*?\bheight=[\"']([\d.]+)(?:px)?[\"']",
                         re.I | re.S)
SVG_VIEWBOX_RE = re.compile(rb"viewBox=[\"'][\d.\-]+[\s,]+[\d.\-]+[\s,]+([\d.]+)[\s,]+([\d.]+)", re.I)


@dataclass
class MediaAsset:
    """A capture-ready media asset (paths are absolute)."""
    kind: str                        # image | video | pdf
    src: str                         # the original file (never modified)
    path: str = ""                   # still to show: image copy / video poster / "" for pdf
    w: int = 0
    h: int = 0
    format: str = ""
    animated: bool = False
    duration_s: float | None = None
    fps: float | None = None
    poster_t: float | None = None
    pages: int | None = None
    title: str = ""
    palette: list[dict[str, Any]] = field(default_factory=list)
    accent: str = ""
    cutout: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 1)


def _even(v: float) -> int:
    return max(2, round(v / 2) * 2)


def fit_size(w: int, h: int, max_side: int) -> tuple[int, int]:
    """Even dimensions with the long side <= ``max_side`` (aspect kept)."""
    s = min(1.0, max_side / max(w, h))
    return _even(w * s), _even(h * s)


# ------------------------------------------------------------------------------ images

def image_asset(src: Path, out_dir: Path, *, do_cutout: bool = True, cutout_max_side: int = 2048) -> MediaAsset:
    """Copy/normalise an image into ``out_dir`` (+ cutout attempt). Never raises."""
    t0 = time.monotonic()
    a = MediaAsset("image", str(src))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() == ".svg":
            return _svg_asset(src, out_dir, a, t0)
        with Image.open(src) as im:
            a.format = str(im.format or "")
            a.animated = bool(getattr(im, "is_animated", False))
            orient = im.getexif().get(0x0112, 1) if hasattr(im, "getexif") else 1
            if a.animated:
                im.seek(0)
                first = im.convert("RGBA")
                dest = out_dir / f"image{COPY_FORMATS.get(a.format, '.bin')}"
                shutil.copyfile(src, dest)
                poster = out_dir / "poster.png"
                first.save(poster)
                a.path = str(poster)
                still = first
            else:
                still = ImageOps.exif_transpose(im) if orient != 1 else im.copy()
                if a.format in COPY_FORMATS and orient == 1:
                    dest = out_dir / f"image{COPY_FORMATS[a.format]}"
                    shutil.copyfile(src, dest)
                else:
                    dest = out_dir / "image.png"
                    still.save(dest)
                a.path = str(dest)
            a.w, a.h = still.size
        a.palette = palette(still)
        a.accent = dominant_accent(a.palette)
        if do_cutout and not a.animated:
            a.cutout = _still_cutout(still, out_dir / "cutout.png", cutout_max_side)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
        a.error = {"code": "image", "message": f"cannot read image: {type(e).__name__}: {e}"[:300]}
    a.ms = _ms(t0)
    return a


def _svg_asset(src: Path, out_dir: Path, a: MediaAsset, t0: float) -> MediaAsset:
    data = src.read_bytes()[:200_000]
    dest = out_dir / "image.svg"
    shutil.copyfile(src, dest)
    a.path, a.format = str(dest), "SVG"
    m = SVG_SIZE_RE.search(data) or SVG_VIEWBOX_RE.search(data)
    if m:
        a.w, a.h = int(float(m.group(1))), int(float(m.group(2)))
    a.warnings.append("SVG: no cutout or palette (vector)")
    a.ms = _ms(t0)
    return a


def _still_cutout(img: Image.Image, dest: Path, max_side: int) -> dict[str, Any]:
    work = img.convert("RGB")
    if max(work.size) > max_side:
        work = work.resize(fit_size(*work.size, max_side), Image.Resampling.LANCZOS)
    t0 = time.monotonic()
    rgba, q = cutout(work)
    info: dict[str, Any] = q.to_dict()
    if rgba is not None:
        rgba.save(dest, compress_level=6)
        info.update(path=str(dest), w=rgba.width, h=rgba.height)
    info["ms"] = _ms(t0)
    return info


# ------------------------------------------------------------------------------ videos

def probe_video(ffmpeg: str, src: Path) -> tuple[dict[str, Any], int]:
    """(media info dict, rotation in degrees) from the ``ffmpeg -i`` banner."""
    p = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(src)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW, check=False)
    if "Duration:" not in p.stderr:
        raise RenderError("ffmpeg", f"cannot read media info of {src.name}", stderr=p.stderr[-800:])
    info = parse_media_info(p.stderr).to_dict()
    rot = 0
    m = ROTATE_RE.search(p.stderr)
    if m:
        rot = round(float(m.group(1) or m.group(2))) % 360
    return info, rot


class FrameReader:
    """Raw RGB frames from an ffmpeg child process we own (killed on early exit / timeout)."""

    def __init__(self, ffmpeg: str, src: Path, size: tuple[int, int], *, fps: float | None = None,
                 start: float | None = None, max_frames: int | None = None) -> None:
        self.size = size
        vf = ([f"fps={fps:.6f}"] if fps else []) + [f"scale={size[0]}:{size[1]}:flags=area", "format=rgb24"]
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error"]
        if start:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(src), "-an", "-sn", "-vf", ",".join(vf)]
        if max_frames:
            cmd += ["-frames:v", str(max_frames)]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)

    def __iter__(self) -> Iterator[Image.Image]:
        n = self.size[0] * self.size[1] * 3
        assert self.proc.stdout is not None
        while True:
            buf = self.proc.stdout.read(n)
            if len(buf) < n:
                return
            yield Image.frombytes("RGB", self.size, buf)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=5)
        if self.proc.stdout is not None:
            self.proc.stdout.close()

    def __enter__(self) -> FrameReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def frame_interest(img: Image.Image) -> float:
    """Poster score: contrast + colourfulness, heavily penalising near-black/near-white frames."""
    st = ImageStat.Stat(img.convert("L"))
    mean, sd = st.mean[0], st.stddev[0]
    sat = ImageStat.Stat(img.convert("HSV").getchannel("S")).mean[0]
    score = sd + 0.5 * sat
    if mean < 25 or mean > 245 or sd < 4:
        score -= 100
    return score


def video_poster(ffmpeg: str, src: Path, dur: float, size: tuple[int, int], *, samples: int = 8,
                 timeout: float = 60.0) -> tuple[float, Image.Image | None]:
    """Pick the most interesting of ``samples`` evenly spaced frames; return (t, full-size frame)."""
    small = fit_size(*size, 192)
    k = samples / max(dur, 0.1)
    best_t, best = 0.0, -1e9
    end = time.monotonic() + timeout
    with FrameReader(ffmpeg, src, small, fps=k) as fr:
        for i, im in enumerate(fr):
            t = min(max(0.0, dur - 0.05), (i + 0.5) / k)
            s = frame_interest(im)
            if s > best:
                best_t, best = t, s
            if time.monotonic() > end or i > samples + 2:
                break
    with FrameReader(ffmpeg, src, size, start=best_t, max_frames=1) as fr:
        frame = next(iter(fr), None)
    if frame is None and best_t > 0:
        with FrameReader(ffmpeg, src, size, max_frames=1) as fr:
            frame = next(iter(fr), None)
        best_t = 0.0
    return best_t, frame


def video_asset(src: Path, out_dir: Path, *, ffmpeg: str | None = None, do_cutout: bool = True,
                cutout_fps: float = 15.0, cutout_max_side: int = 720, cutout_max_frames: int = 150,
                deadline: float | None = None, cancel: threading.Event | None = None) -> MediaAsset:
    """Poster + facts (+ cutout frames when the backdrop allows). Never raises; time-boxed by ``deadline``."""
    t0 = time.monotonic()
    a = MediaAsset("video", str(src))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        ff = ffmpeg or resolve_ffmpeg().path
        info, rot = probe_video(ff, src)
        w, h = int(info.get("width") or 0), int(info.get("height") or 0)
        if rot in (90, 270):
            w, h = h, w
        if not (w and h):
            raise RenderError("ffmpeg", "no video stream")
        a.w, a.h, a.format = w, h, str(info.get("video_codec") or "")
        a.duration_s, a.fps = info.get("duration_s"), info.get("fps")
        dur = float(a.duration_s or 0.0)
        a.poster_t, frame = video_poster(ff, src, dur, fit_size(w, h, 1920))
        if frame is None:
            raise RenderError("ffmpeg", "could not decode a frame")
        poster = out_dir / "poster.png"
        frame.save(poster, compress_level=6)
        a.path = str(poster)
        a.palette = palette(frame)
        a.accent = dominant_accent(a.palette)
        if do_cutout:
            a.cutout = _video_cutout(ff, src, out_dir, frame, dur, float(a.fps or 30.0), fps=cutout_fps,
                                     max_side=cutout_max_side, max_frames=cutout_max_frames, deadline=deadline,
                                     cancel=cancel)
    except RenderError as e:
        a.error = e.to_dict()
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        a.error = {"code": "video", "message": f"{type(e).__name__}: {e}"[:300]}
    a.ms = _ms(t0)
    return a


def _video_cutout(ff: str, src: Path, out_dir: Path, poster: Image.Image, dur: float, src_fps: float, *,
                  fps: float, max_side: int, max_frames: int, deadline: float | None,
                  cancel: threading.Event | None) -> dict[str, Any]:
    t0 = time.monotonic()
    still = _still_cutout(poster, out_dir / "poster_cutout.png", 1920)
    if still.get("grade") == "none":
        return {**still, "frames": 0, "ms": _ms(t0)}
    size = fit_size(poster.width, poster.height, max_side)
    use_fps = min(fps, src_fps or fps)
    if dur * use_fps > max_frames:
        use_fps = max(8.0, max_frames / max(dur, 0.1))
    frames_dir = out_dir / "cutout"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    poster_model = fit_background(poster.resize(size, Image.Resampling.BOX))
    model = poster_model
    refits = 0
    scores: list[float] = []
    fgs: list[float] = []
    grades: dict[str, int] = {}
    count, partial = 0, False
    with FrameReader(ff, src, size, fps=use_fps, max_frames=max_frames) as fr:
        for im in fr:
            if (cancel is not None and cancel.is_set()) or (deadline is not None and time.monotonic() > deadline):
                partial = True
                break
            if model is None or model_fit(model, im) < 0.9:      # refit only when the backdrop changed
                model = fit_background(im) or poster_model
                refits += 1
            rgba, q = cutout(im, model=model) if model is not None else (None, CutoutQuality())
            count += 1
            if rgba is None:
                rgba = im.convert("RGBA")       # keep numbering contiguous; quality records the failure
            rgba.save(frames_dir / f"{count:06d}.png", compress_level=1)
            scores.append(q.score)
            fgs.append(q.fg_fraction)
            grades[q.grade] = grades.get(q.grade, 0) + 1
    if count >= max_frames and dur * use_fps > max_frames + 1:
        partial = True
    out: dict[str, Any] = {"still": still, "frames_dir": str(frames_dir), "pattern": "%06d.png", "count": count,
                           "fps": round(use_fps, 3), "w": size[0], "h": size[1], "partial": partial,
                           "covers_s": round(count / use_fps, 2) if use_fps else 0.0, "frame_grades": grades,
                           "model_refits": refits}
    if not scores:
        out.update(ok=False, grade="none", score=0.0, reason="no frames decoded", ms=_ms(t0))
        return out
    med = statistics.median(scores)
    mean_fg = statistics.fmean(fgs) or 1e-6
    wobble = statistics.pstdev(fgs) / mean_fg if len(fgs) > 1 else 0.0
    bad = sum(s < 0.5 for s in scores) / len(scores)
    score = med - max(0.0, wobble - 0.25) - max(0.0, bad - 0.1)
    grade = "good" if score >= 0.75 else "fair" if score >= 0.5 else "poor"
    out.update(ok=grade in ("good", "fair"), grade=grade, score=round(max(0.0, score), 3),
               median_frame_score=round(med, 3), min_frame_score=round(min(scores), 3),
               fg_wobble=round(wobble, 3), bad_frames=round(bad, 3), model=still.get("model", {}),
               reason={"good": "clean backdrop in every frame", "fair": "usable with care",
                       "poor": "matte unreliable across frames"}[grade], ms=_ms(t0))
    return out


# -------------------------------------------------------------------------------- pdfs

def pdf_info(src: Path, limit: int = 32 * 1024 * 1024) -> MediaAsset:
    """Page count and /Title of a PDF (cheap byte scan; page images come from the browser)."""
    t0 = time.monotonic()
    a = MediaAsset("pdf", str(src), format="PDF")
    try:
        with open(src, "rb") as fh:
            data = fh.read(limit)
        a.pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", data)) or None
        m = re.search(rb"/Title\s*\(((?:[^)\\]|\\.){1,400})\)", data, re.S)
        if m:
            raw = re.sub(rb"\\(.)", rb"\1", m.group(1))
            text = raw[2:].decode("utf-16-be", "replace") if raw.startswith(b"\xfe\xff") else raw.decode("latin-1")
            a.title = text.strip()[:200]
    except OSError as e:
        a.error = {"code": "pdf", "message": str(e)[:200]}
    a.ms = _ms(t0)
    return a
