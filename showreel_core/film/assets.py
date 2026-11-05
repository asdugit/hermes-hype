"""Product media for films: images resized, videos pre-extracted to frame sequences (never <video> seeking).

``prepare_asset(name, spec, job_dir, fps=30)`` writes files under ``job_dir/assets/<name>/`` and returns the
assets/manifest.json entry (SDK.md §1)::

    {"type": "image", "w", "h", "path"}                                         # stills
    {"type": "frames", "w", "h", "fps", "count", "dur", "pattern", "poster"?}   # videos / sequences
    ... + "cutout": {"path"} | {"pattern", ...}                                # optional alpha version

Spec keys: ``src`` (file or folder of images), ``type`` (image | video | frames; inferred), ``max_w`` (default
1920 for images, 960 for frames), ``fps`` (<= film fps), ``t0``/``t1`` (video trim, s), ``poster`` (time in s or
True = first frame), ``alpha`` (PNG frames keep transparency), ``cutout`` (path to an alpha image/video/folder).
"""
from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi", ".gif"}
FRAMES_MAX_W = 960
IMAGE_MAX_W = 1920
MAX_FRAMES = 3600


class AssetError(Exception):
    """Media could not be prepared (message names the asset and the cause)."""


def _kind(src: Path, spec: Mapping[str, Any]) -> str:
    t = spec.get("type")
    if t in ("image", "frames"):
        return t
    if t == "video":
        return "frames"
    if src.is_dir():
        return "frames"
    ext = src.suffix.lower()
    if ext in IMAGE_EXT and ext != ".gif":
        return "image"
    if ext in VIDEO_EXT:
        return "frames"
    raise AssetError(f"cannot tell the media type of {src.name}; set \"type\"")


def prepare_image(src: Path, out_dir: Path, *, max_w: int = IMAGE_MAX_W, stem: str = "image") -> dict[str, Any]:
    """Resize (never upscale) and re-encode one image; PNG if it has alpha, else JPEG q90."""
    from PIL import Image, ImageOps

    try:
        with Image.open(src) as im0:
            im = ImageOps.exif_transpose(im0)
            im.load()
    except (OSError, ValueError) as e:
        raise AssetError(f"cannot read image {src.name}: {e}") from e
    alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    im = im.convert("RGBA" if alpha else "RGB")
    if im.width > max_w:
        h = max(1, round(im.height * max_w / im.width))
        im = im.resize((max_w, h), Image.Resampling.LANCZOS)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (f"{stem}.png" if alpha else f"{stem}.jpg")
    if alpha:
        im.save(out, optimize=False)
    else:
        im.save(out, quality=90)
    return {"w": im.width, "h": im.height, "file": out}


def _rel(job: Path, p: Path) -> str:
    return p.resolve().relative_to(job.resolve()).as_posix()


def _resolve_ffmpeg(ffmpeg: str | None) -> str:
    if ffmpeg:
        return ffmpeg
    from ..render.errors import RenderError
    from ..render.ffmpeg import resolve_ffmpeg

    try:
        return resolve_ffmpeg().path
    except RenderError as e:
        raise AssetError(f"ffmpeg is needed for video assets: {e}") from e


def extract_frames(src: Path, out_dir: Path, *, fps: float, max_w: int = FRAMES_MAX_W, t0: float | None = None,
                   t1: float | None = None, alpha: bool = False, ffmpeg: str | None = None,
                   stem: str = "") -> dict[str, Any]:
    """Video -> numbered JPEG (or PNG with alpha) frames at <= ``fps`` and <= ``max_w`` px wide."""
    from ..render.errors import RenderError
    from ..render.ffmpeg import media_info, run

    ff = _resolve_ffmpeg(ffmpeg)
    try:
        info = media_info(ff, src)
    except RenderError as e:
        raise AssetError(f"cannot read video {src.name}: {e}") from e
    if not info.width:
        raise AssetError(f"{src.name} has no video stream")
    rate = min(float(fps), float(info.fps or fps))
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{stem}[0-9][0-9][0-9][0-9][0-9][0-9].*"):
        old.unlink()
    ext = "png" if alpha else "jpg"
    cmd = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if t0:
        cmd += ["-ss", f"{float(t0):.3f}"]
    cmd += ["-i", str(src)]
    if t1 is not None:
        cmd += ["-t", f"{max(0.04, float(t1) - float(t0 or 0)):.3f}"]
    vf = f"fps={rate:g},scale='min({int(max_w)},iw)':-2:flags=lanczos"
    cmd += ["-vf", vf, "-frames:v", str(MAX_FRAMES), "-an"]
    cmd += ["-pix_fmt", "rgba"] if alpha else ["-q:v", "3"]
    cmd += [str(out_dir / f"{stem}%06d.{ext}")]
    try:
        run(cmd, timeout=900, what=f"frame extraction ({src.name})")
    except RenderError as e:
        raise AssetError(f"frame extraction failed for {src.name}: {e}") from e
    frames = sorted(out_dir.glob(f"{stem}[0-9][0-9][0-9][0-9][0-9][0-9].{ext}"))
    if not frames:
        raise AssetError(f"no frames came out of {src.name}")
    from PIL import Image

    with Image.open(frames[0]) as im:
        w, h = im.size
    return {"w": w, "h": h, "fps": rate, "count": len(frames), "dur": round(len(frames) / rate, 4),
            "ext": ext, "first": frames[0]}


def copy_sequence(src_dir: Path, out_dir: Path, *, max_w: int = FRAMES_MAX_W, stem: str = "") -> dict[str, Any]:
    """A folder of images (sorted by name) -> numbered frames, resized like videos."""
    files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() in IMAGE_EXT)
    if not files:
        raise AssetError(f"{src_dir.name}/ has no images")
    out_dir.mkdir(parents=True, exist_ok=True)
    first: dict[str, Any] | None = None
    ext = "jpg"
    for i, f in enumerate(files[:MAX_FRAMES], 1):
        r = prepare_image(f, out_dir, max_w=max_w, stem=f"{stem}{i:06d}")
        first = first or r
        ext = r["file"].suffix.lstrip(".")
    assert first is not None
    return {"w": first["w"], "h": first["h"], "count": min(len(files), MAX_FRAMES), "ext": ext, "first": first["file"]}


def prepare_asset(name: str, spec: Mapping[str, Any], job_dir: Path, *, fps: float = 30.0,
                  ffmpeg: str | None = None) -> dict[str, Any]:
    """Prepare one asset into ``job_dir/assets/<name>/``; returns its manifest entry. Raises :class:`AssetError`."""
    job = Path(job_dir)
    src = Path(str(spec.get("src", "")))
    if not str(spec.get("src", "")) or not src.exists():
        raise AssetError(f"asset '{name}': source {spec.get('src')!r} does not exist")
    out = job / "assets" / name
    if out.is_dir():
        shutil.rmtree(out)
    kind = _kind(src, spec)
    entry: dict[str, Any]
    if kind == "image":
        r = prepare_image(src, out, max_w=int(spec.get("max_w", IMAGE_MAX_W)))
        entry = {"type": "image", "w": r["w"], "h": r["h"], "path": _rel(job, r["file"])}
    else:
        rate = min(float(spec.get("fps", fps)), float(fps))
        max_w = min(int(spec.get("max_w", FRAMES_MAX_W)), 1920)
        if src.is_dir():
            r = copy_sequence(src, out, max_w=max_w)
            r["fps"] = rate
            r["dur"] = round(r["count"] / rate, 4)
        else:
            r = extract_frames(src, out, fps=rate, max_w=max_w, t0=spec.get("t0"), t1=spec.get("t1"),
                               alpha=bool(spec.get("alpha")), ffmpeg=ffmpeg)
        entry = {"type": "frames", "w": r["w"], "h": r["h"], "fps": r["fps"], "count": r["count"], "dur": r["dur"],
                 "pattern": f"assets/{name}/%06d.{r['ext']}"}
        poster = spec.get("poster")
        if poster is not None and poster is not False:
            idx = 1 if poster is True else max(1, min(r["count"], int(float(poster) * r["fps"]) + 1))
            src_frame = out / f"{idx:06d}.{r['ext']}"
            dst = out / f"poster.{r['ext']}"
            shutil.copyfile(src_frame, dst)
            entry["poster"] = _rel(job, dst)
    cut = spec.get("cutout")
    if cut:
        csrc = Path(str(cut))
        if not csrc.exists():
            raise AssetError(f"asset '{name}': cutout {cut!r} does not exist")
        cdir = out / "cutout"
        if entry["type"] == "image":
            r = prepare_image(csrc, cdir, max_w=int(entry["w"]))
            entry["cutout"] = {"path": _rel(job, r["file"])}
        elif csrc.is_dir():
            r = copy_sequence(csrc, cdir, max_w=int(entry["w"]))
            entry["cutout"] = {"pattern": f"assets/{name}/cutout/%06d.{r['ext']}", "count": r["count"]}
        else:
            r = extract_frames(csrc, cdir, fps=entry["fps"], max_w=int(entry["w"]), t0=spec.get("t0"),
                               t1=spec.get("t1"), alpha=True, ffmpeg=ffmpeg)
            entry["cutout"] = {"pattern": f"assets/{name}/cutout/%06d.png", "count": r["count"]}
    return entry


def prepare_assets(specs: Mapping[str, Mapping[str, Any]], job_dir: Path, *, fps: float = 30.0,
                   ffmpeg: str | None = None) -> dict[str, Any]:
    """Prepare several assets; returns the manifest dict. Raises :class:`AssetError` on the first failure."""
    return {name: prepare_asset(name, spec, job_dir, fps=fps, ffmpeg=ffmpeg) for name, spec in specs.items()}
