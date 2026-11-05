"""Copy screenshots/images referenced by events into the job's asset dir.

Hermes sweeps ``cache/screenshots`` and ``cache/images`` after 24 h, so we copy what still exists
at extract time and mark the rest ``data.missing = True``. Inline (base64) images captured in the
transcript are written out too. Copies are capped (count and size) and prioritised by weight.

After collection, image events carry::

    data.path     absolute path of the copy inside ``assets_dir`` ("" if not copied);
                  for ``artifact`` events the copy goes to ``data.preview_path`` instead
    data.asset    True when ``path`` points at our copy (the redactor leaves it alone)
    data.w/h      pixel size from the file header (None if unknown)
    data.missing  True when the original no longer exists
    data.skipped  True when over the copy cap
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts import Event
from .weights import assign_weights

MAX_FILES = 48
MAX_BYTES = 25 * 1024 * 1024
_IMAGE_KINDS = ("screenshot", "image_generated")   # + artifact events of kind image


@dataclass
class AssetReport:
    copied: int = 0
    reused: int = 0
    missing: int = 0
    skipped: int = 0
    inline: int = 0
    errors: list[str] = field(default_factory=list)


def image_size(data: bytes) -> tuple[int | None, int | None]:
    """(width, height) from PNG/JPEG/GIF/WebP header bytes, else (None, None)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
            w, h = struct.unpack("<HH", data[6:10])
            return int(w), int(h)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                w = 1 + int.from_bytes(data[24:27], "little")
                h = 1 + int.from_bytes(data[27:30], "little")
                return w, h
            if chunk == b"VP8L":
                b = data[21:25]
                w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                return w, h
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return int(w), int(h)
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg
    except (struct.error, IndexError):
        pass
    return None, None


def _ext_for(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:3] == b"GIF":
        return ".gif"
    return ".bin"


def resolve_local(src: str, base_dir: str | Path | None = None) -> Path | None:
    """Best-effort conversion of a transcript path spelling into a local Path."""
    s = src.strip().strip("`'\"").replace("\\\\", "\\")
    if not s:
        return None
    if s.startswith("file://"):
        s = s[7:]
        if re.match(r"^/[A-Za-z]:", s):
            s = s[1:]
    if sys.platform == "win32" and re.match(r"^/[a-zA-Z]/", s):       # MSYS /c/Users/...
        s = f"{s[1].upper()}:{s[2:]}"
    p = Path(os.path.expanduser(s))
    if not p.is_absolute():
        if base_dir is None:
            return None
        p = Path(base_dir) / p
    return p


def _safe_name(eid: str, src: Path | None, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem if src else "inline")[:40].strip("._") or "image"
    return f"{eid}_{stem}{ext}"


def collect_assets(events: list[Event], assets_dir: str | Path | None, *, max_files: int = MAX_FILES,
                   max_bytes: int = MAX_BYTES, base_dir: str | Path | None = None) -> AssetReport:
    """Copy image files referenced by screenshot/image events into ``assets_dir`` (never raises).

    With ``assets_dir=None`` nothing is copied; existence is still checked so ``missing`` is set,
    and inline payloads are dropped from event data.
    """
    report = AssetReport()
    out_dir = Path(assets_dir) if assets_dir else None
    if out_dir is not None:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            report.errors.append(f"cannot create assets dir: {exc}")
            out_dir = None
    candidates = [e for e in events if e.kind in _IMAGE_KINDS
                  or (e.kind == "artifact" and e.data.get("kind") == "image")]
    order = sorted(candidates, key=lambda e: (-e.weight, -e.t))
    copied_by_src: dict[str, tuple[str, int | None, int | None]] = {}
    budget = max_files
    for ev in order:
        d = ev.data
        tkey = "preview_path" if ev.kind == "artifact" else "path"   # artifacts keep their original path
        inline = d.pop("_inline_b64", None)
        d.setdefault(tkey, "")
        if inline:
            if out_dir is None or budget <= 0:
                d["skipped"] = out_dir is not None
                continue
            try:
                raw = base64.b64decode(inline, validate=False)
                name = _safe_name(ev.id, None, _ext_for(raw))
                (out_dir / name).write_bytes(raw)
                d[tkey], d["asset"] = str((out_dir / name).resolve()), True
                d["w"], d["h"] = image_size(raw[:65536])
                report.inline += 1
                budget -= 1
            except (binascii.Error, ValueError, OSError) as exc:
                report.errors.append(f"{ev.id}: inline image: {exc}")
            continue
        src = str(d.get("src") or "")
        if not src:
            if not d.get("url"):
                d["missing"] = True
                report.missing += 1
            continue
        key = str(d.get("src_key") or src)
        if key in copied_by_src:
            d[tkey], d["w"], d["h"] = copied_by_src[key]
            d["asset"] = True
            report.reused += 1
            continue
        p = resolve_local(src, base_dir)
        try:
            exists = p is not None and p.is_file()
        except OSError:
            exists = False
        if p is None or not exists:
            d["missing"] = True
            report.missing += 1
            continue
        try:
            size = p.stat().st_size
            with open(p, "rb") as fh:
                head = fh.read(65536)
        except OSError as exc:
            report.errors.append(f"{ev.id}: {exc}")
            d["missing"] = True
            report.missing += 1
            continue
        d["w"], d["h"] = image_size(head)
        if out_dir is None:
            continue
        if budget <= 0 or size > max_bytes:
            d["skipped"] = True
            report.skipped += 1
            continue
        dest = out_dir / _safe_name(ev.id, p, p.suffix.lower() or _ext_for(head))
        try:
            shutil.copyfile(p, dest)
        except OSError as exc:
            report.errors.append(f"{ev.id}: copy failed: {exc}")
            continue
        d[tkey], d["asset"] = str(dest.resolve()), True
        copied_by_src[key] = (d[tkey], d["w"], d["h"])
        report.copied += 1
        budget -= 1
    # missing originals are less useful as hero shots: recompute weights with that knowledge
    assign_weights(events)
    return report
