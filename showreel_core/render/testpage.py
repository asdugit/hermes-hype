"""Built-in test page implementing ``window.__sr`` (selftest, GPU probe, integration tests).

The static files live in ``render/selftest_page/``; :func:`write_test_page` copies them into a job
dir and generates the binary assets with Pillow (a checker PNG and, when Pillow's FreeType build
is available, its embedded Aileron font for an ``@font-face`` load check). Nothing binary ships.
"""
from __future__ import annotations

import shutil
from pathlib import Path

STATIC_DIR = Path(__file__).with_name("selftest_page")
STATIC_FILES = ("index.html", "page.css", "sr.mjs", "rng.mjs")
FONT_FILE = "srtest.ttf"


def _font_bytes() -> bytes | None:
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(16)
    except Exception:
        return None
    data = getattr(font, "font_bytes", None)
    return data if isinstance(data, bytes) and data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true") else None


def write_test_page(dest: Path, *, dur: float = 6.0, fps: float = 30.0, with_font: bool = True) -> str:
    """Populate ``dest`` and return the page path (relative, with query) to render."""
    from PIL import Image

    dest.mkdir(parents=True, exist_ok=True)
    for name in STATIC_FILES:
        shutil.copyfile(STATIC_DIR / name, dest / name)
    checker = Image.new("RGB", (8, 8))
    checker.putdata([(201, 242, 92) if (x + y) % 2 else (20, 21, 26) for y in range(8) for x in range(8)])
    checker.save(dest / "checker.png", "PNG")
    query = f"dur={dur:g}&fps={fps:g}"
    if with_font and (fb := _font_bytes()):
        (dest / FONT_FILE).write_bytes(fb)
        query += f"&font={FONT_FILE}"
    return f"index.html?{query}"
