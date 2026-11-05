"""The user's scene library: Director-invented scenes saved for reuse as ``lib:<name>``.

Layout: ``<library>/<name>/scene.js`` (calls ``sr.defineScene('lib:<name>', ...)``), ``meta.json``
(``{id, name, describe, layer, params, kits, tags, created_job, direction, scores, thumbnail}``) and
``thumb.jpg``. Folders are plain files users may copy or share; nothing here is fetched from the network.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .sheet import thumbnail


def default_library_dir() -> Path:
    """``<plugin data>/library`` (see :func:`showreel_core.jobs.data_root`)."""
    from ..jobs import data_root
    return data_root() / "library"


def _code_hash(code: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", code).encode("utf-8")).hexdigest()[:16]


def as_library_code(code: str, name: str) -> str:
    """Rewrite the scene id of a custom scene module to ``lib:<name>``."""
    return re.sub(r"""(sr\s*\.\s*defineScene\(\s*)(['"`])[^'"`]*\2""", lambda m: f"{m.group(1)}'lib:{name}'", code,
                  count=1)


def save_scene(library_dir: Path, name: str, code: str, meta: dict[str, Any],
               thumb: bytes | None = None) -> str | None:
    """Save one scene; returns its ``lib:`` id, or None when an identical scene already exists.

    Name clashes with different code get a numeric suffix (``boss-battle-2``); the library never
    overwrites a user's scene.
    """
    library_dir.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "scene"
    digest = _code_hash(as_library_code(code, base))
    for i in range(1, 100):
        cand = base if i == 1 else f"{base}-{i}"
        d = library_dir / cand
        if d.exists():
            existing = d / "meta.json"
            try:
                if json.loads(existing.read_text(encoding="utf-8")).get("code_hash") == digest:
                    return None
            except (OSError, ValueError):
                pass
            continue
        d.mkdir(parents=True)
        lib_code = as_library_code(code, cand)
        (d / "scene.js").write_text(lib_code, encoding="utf-8")
        out = dict(meta, id=f"lib:{cand}", name=cand, code_hash=digest)
        if thumb and thumbnail(thumb, d / "thumb.jpg"):
            out["thumbnail"] = "thumb.jpg"
        (d / "meta.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        return f"lib:{cand}"
    return None
