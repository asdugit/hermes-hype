"""Product media for the Director: probe size/duration, make thumbnails, collect media from a session bundle."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .types import MediaAsset

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi", ".gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def asset_name(path: str | Path, taken: set[str]) -> str:
    """A short, unique, JS-friendly asset name from a file name (``car.mp4`` -> ``car``)."""
    base = re.sub(r"[^a-z0-9]+", "_", Path(path).stem.lower()).strip("_")[:24] or "media"
    if base[0].isdigit():
        base = f"m_{base}"
    name, i = base, 2
    while name in taken:
        name, i = f"{base}_{i}", i + 1
    taken.add(name)
    return name


def probe_asset(path: str | Path, *, name: str = "", out_dir: Path | None = None, description: str = "",
                product: bool = True) -> MediaAsset:
    """MediaAsset for a local file: dimensions, duration/fps (videos) and a poster thumbnail. Never raises."""
    p = Path(path)
    kind = "video" if p.suffix.lower() in VIDEO_EXT else "image"
    a = MediaAsset(name=name or asset_name(p, set()), type=kind, path=str(p.resolve()), description=description,
                   product=product)
    try:
        if kind == "image":
            from PIL import Image
            with Image.open(p) as im:
                a.w, a.h = im.size
            a.thumbnail = a.path
            return a
        from ..render.ffmpeg import extract_frame, media_info, resolve_ffmpeg
        ff = resolve_ffmpeg().path
        info = media_info(ff, p)
        a.w, a.h = info.width, info.height
        a.dur, a.fps = float(info.duration_s or 0.0), float(info.fps or 0.0)
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            thumb = out_dir / f"{a.name}-poster.png"
            extract_frame(ff, p, min(a.dur * 0.4, 2.0) if a.dur else 0.0, thumb)
            if thumb.is_file():
                a.thumbnail = str(thumb)
    except Exception as exc:  # noqa: BLE001 - probing is best effort; the build stage re-checks the file
        log.debug("probe of %s failed: %s", p, exc)
    return a


def assets_from_bundle(bundle: Any, out_dir: Path | None = None, limit: int = 6) -> list[MediaAsset]:
    """Product media from a session bundle: product captures, video/image artifacts, screenshots (best first)."""
    events = list(getattr(bundle, "events", None) or [])
    order = {"product_capture": 0, "artifact": 1, "image_generated": 2, "screenshot": 3}
    cands = []
    for e in events:
        kind = getattr(e, "kind", "")
        data = getattr(e, "data", None) or {}
        path = data.get("preview_path") or data.get("path") if isinstance(data, dict) else None
        if kind not in order or not path or not Path(str(path)).is_file():
            continue
        if Path(str(path)).suffix.lower() not in VIDEO_EXT | IMAGE_EXT:
            continue
        cands.append((order[kind], -float(getattr(e, "weight", 0.0) or 0.0), str(path), str(getattr(e, "summary", ""))))
    cands.sort()
    taken: set[str] = set()
    out, seen = [], set()
    for _o, _w, path, summary in cands:
        if path in seen:
            continue
        seen.add(path)
        out.append(probe_asset(path, name=asset_name(path, taken), out_dir=out_dir, description=summary[:120]))
        if len(out) >= limit:
            break
    return out
