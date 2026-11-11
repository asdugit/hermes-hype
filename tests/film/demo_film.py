"""Demo film for runtime tests: 2d + dom + three + pixel shots, crossfade/iris/pixelate, a frames asset.

``make_demo(root)`` writes a kits folder (demo kit + a generated font), synthetic media and returns
``(film, assets, kits_root)`` ready for ``build_job``. Everything is generated (nothing binary in the repo).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"

DEMO_FILM: dict[str, Any] = {
    "version": 1, "fps": 30, "size": [1920, 1080], "dur": 8.0, "seed": 7, "title": "Runtime demo",
    "background": "#05060a",
    "assets": {"clip": {"type": "frames"}, "logo": {"type": "image"}},
    "shots": [
        {"id": "intro", "t0": 0.0, "t1": 2.2, "scene": "kit:demo/bars", "params": {"title": "Hype runtime", "clip": "clip"}},
        {"id": "card", "t0": 2.0, "t1": 4.2, "scene": "kit:demo/card", "params": {"title": "DOM shot"}},
        {"id": "cube", "t0": 4.0, "t1": 6.0, "scene": "kit:demo/cube", "params": {"image": "logo"}},
        {"id": "px", "t0": 5.8, "t1": 8.0, "scene": "kit:demo/pixel", "res": [480, 270]},
    ],
    "transitions": [
        {"from": "intro", "to": "card", "type": "crossfade", "t": 1.8, "dur": 0.6},
        {"from": "card", "to": "cube", "type": "iris", "t": 3.9, "dur": 0.5},
        {"from": "cube", "to": "px", "type": "pixelate", "t": 5.7, "dur": 0.5},
    ],
    "overlays": [{"id": "badge", "t0": 0.5, "t1": 7.5, "scene": "kit:demo/badge"}],
    "captions": [
        {"t0": 0.4, "t1": 1.7, "text": "A tiny demo film"},
        {"t0": 2.5, "t1": 3.8, "text": "DOM, canvas and three.js shots"},
    ],
    "finish": {"grain": 0.04, "vignette": 0.3},
    "cues": [{"t": 3.9, "sfx": "whoosh_short_2"}],
}


def _font_bytes() -> bytes:
    from PIL import ImageFont

    data = getattr(ImageFont.load_default(16), "font_bytes", None)
    if not data:
        raise RuntimeError("Pillow without an embedded default font (needs Pillow >= 10.1 with FreeType)")
    return bytes(data)


def make_media(root: Path) -> dict[str, dict[str, Any]]:
    """Synthetic product media: a 24-frame image sequence and a logo PNG."""
    from PIL import Image, ImageDraw

    seq = root / "media" / "clip"
    seq.mkdir(parents=True, exist_ok=True)
    for i in range(24):
        im = Image.new("RGB", (640, 360), (20, 24, 36))
        d = ImageDraw.Draw(im)
        x = 40 + i * 22
        d.rectangle([0, 300, 640, 360], fill=(40, 46, 70))
        d.rounded_rectangle([x, 230, x + 150, 300], radius=18, fill=(200, 40, 60))
        d.ellipse([x + 18, 285, x + 52, 319], fill=(12, 12, 16))
        d.ellipse([x + 98, 285, x + 132, 319], fill=(12, 12, 16))
        d.text((16, 14), f"frame {i + 1:02d}", fill=(220, 220, 230))
        im.save(seq / f"f{i:03d}.png")
    logo = root / "media" / "logo.png"
    im = Image.new("RGBA", (512, 512), (250, 197, 51, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([64, 64, 448, 448], radius=60, fill=(20, 24, 36, 255))
    d.ellipse([160, 160, 352, 352], fill=(47, 211, 192, 255))
    im.save(logo)
    return {"clip": {"src": str(seq), "type": "frames", "fps": 12}, "logo": {"src": str(logo)}}


def make_kits(root: Path) -> Path:
    """Copy the demo kit fixture and give it a font file + kit.json."""
    kits = root / "kits"
    if kits.exists():
        shutil.rmtree(kits)
    shutil.copytree(FIXTURES / "kits", kits)
    fonts = kits / "demo" / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    (fonts / "demo-sans.ttf").write_bytes(_font_bytes())
    (kits / "demo" / "kit.json").write_text(json.dumps({
        "name": "demo", "requires": [], "fonts": [{"family": "Demo Sans", "src": "fonts/demo-sans.ttf", "weight": 400}],
    }), encoding="utf-8")
    return kits


def make_demo(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Path]:
    """Everything build_job needs for the demo film, generated under ``root``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return json.loads(json.dumps(DEMO_FILM)), make_media(root), make_kits(root)
