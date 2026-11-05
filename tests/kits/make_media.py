"""Capture the synthetic product pages (tests/kits/fixtures/product_app.html) into PNG fixtures.

Dev tool for kit tests and sample films: python tests/kits/make_media.py  (uses one render slot).
The pages describe fictional products; nothing here comes from a real session.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from showreel_core.render.workers import page_session  # noqa: E402

SHOTS = {  # name: (variant, w, h)
    "focusfox_home": ("home", 1440, 900),
    "focusfox_dark": ("dark", 1440, 900),
    "focusfox_full": ("full", 1440, 2240),
    "tally_report": ("tally", 1280, 800),
}


def _slot(work: Path) -> Path | None:
    if not work.is_dir():
        return None
    while True:
        for i in (1, 2, 3):
            p = work / f"render.slot{i}"
            try:
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"wp-g1 {os.getpid()} {datetime.now().isoformat()}".encode())
                os.close(fd)
                return p
            except FileExistsError:
                continue
        time.sleep(5)


async def _capture(page_dir: Path, out: Path) -> None:
    for name, (v, w, h) in SHOTS.items():
        async with page_session(page_dir, f"product_app.html?v={v}", w=w, h=h) as p:
            await p.seek(0)
            (out / f"{name}.png").write_bytes(await p.capture("png"))
            print("wrote", name)


def main() -> int:
    out = HERE / "fixtures" / "media"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        page_dir = Path(td)
        shutil.copy2(HERE / "fixtures" / "product_app.html", page_dir)
        shutil.copytree(REPO / "kits" / "base" / "fonts", page_dir / "fonts")
        slot = _slot(REPO.parent)
        try:
            asyncio.run(_capture(page_dir, out))
        finally:
            if slot:
                slot.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
