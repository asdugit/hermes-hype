"""Regenerate the scene tables in kits/{comic,ink}/KIT.md from the live registry (``__sr.scenes()``).

    python tests/kits/comic/gen_catalog.py [comic] [ink]

Same format as tests/kits/gen_kit_catalog.py (which covers base/launch/type): loads the kits through a tiny job and
rewrites the block between ``<!-- scenes:begin -->`` and ``<!-- scenes:end -->`` (the rest of KIT.md is hand-written).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "kits"))

from gen_kit_catalog import BEGIN, END, table  # noqa: E402
from showreel_core.film.page import build_job  # noqa: E402
from showreel_core.film.preview import render_slot  # noqa: E402
from showreel_core.render.workers import page_session  # noqa: E402


async def read_scenes(kits: list[str]) -> list[dict]:
    shots = [{"id": f"s{i}", "t0": i, "t1": i + 1, "scene": f"kit:{k}/TITLE", "params": {"title": "x"}}
             for i, k in enumerate(kits)]
    film = {"version": 1, "fps": 30, "size": [640, 360], "dur": len(kits), "seed": 1, "shots": shots}
    with tempfile.TemporaryDirectory() as td:
        job = build_job(film, Path(td) / "job")
        async with page_session(job, "stage.html", w=640, h=360) as p:
            return await p.evaluate("window.__sr.scenes()")


def main(argv: list[str]) -> int:
    kits = argv or ["comic", "ink"]
    with render_slot(os.environ.get("SHOWREEL_RENDER_SLOT_DIR"), "gen-comic-ink-catalog"):
        scenes = asyncio.run(read_scenes(kits))
    for kit in kits:
        md = ROOT / "kits" / kit / "KIT.md"
        text = md.read_text(encoding="utf-8")
        a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
        text = text[:a] + "\n" + table(scenes, kit) + "\n" + text[b:]
        md.write_bytes(text.encode("utf-8"))
        print(md, sum(1 for s in scenes if s["id"].startswith(f"kit:{kit}/")), "scenes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
