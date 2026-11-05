"""Regenerate the scene tables in kits/{base,launch,type}/KIT.md from the live registry (``__sr.scenes()``).

    python tests/kits/gen_kit_catalog.py

Builds a tiny job that loads the three kits, reads every scene's id/describe/params from the page and rewrites
the block between ``<!-- scenes:begin -->`` and ``<!-- scenes:end -->`` in each KIT.md (the rest is hand-written).
Takes a render slot when SHOWREEL_RENDER_SLOT_DIR is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from showreel_core.film.page import build_job  # noqa: E402
from showreel_core.film.preview import render_slot  # noqa: E402
from showreel_core.render.workers import page_session  # noqa: E402

KITS = ("base", "launch", "type")
BEGIN, END = "<!-- scenes:begin -->", "<!-- scenes:end -->"
HIDDEN = {"_captions", "_sync", "_mute"}   # adapter-internal params, documented once in prose


def _fmt_default(v) -> str:
    if v is None:
        return "—"
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 40 else s[:37] + "…"


def table(scenes: list[dict], kit: str) -> str:
    rows = ["| id | what it shows | params (default) |", "|---|---|---|"]
    for sc in sorted((s for s in scenes if s["id"].startswith(f"kit:{kit}/")), key=lambda s: s["id"]):
        ps = []
        for name, d in (sc.get("params") or {}).items():
            if name in HIDDEN or name in ("theme", "accent", "label"):
                continue
            doc = str((d or {}).get("doc", "")).replace("|", "\\|")
            ps.append(f"`{name}` {_fmt_default((d or {}).get('default'))}" + (f" — {doc}" if doc else ""))
        desc = str(sc.get("describe", "")).replace("|", "\\|")
        rows.append(f"| `{sc['id']}` | {desc} | {' · '.join(ps) or '—'} |")
    return "\n".join(rows)


async def read_scenes() -> list[dict]:
    film = {"version": 1, "fps": 30, "size": [640, 360], "dur": 2, "seed": 1,
            "shots": [{"id": "a", "t0": 0, "t1": 1, "scene": "kit:base/TITLE", "params": {"title": "x"}},
                      {"id": "b", "t0": 1, "t1": 2, "scene": "kit:launch/TITLE", "params": {"title": "x"}}],
            "overlays": [{"id": "o", "t0": 0, "t1": 2, "scene": "kit:type/title", "params": {"text": "x"}}]}
    with tempfile.TemporaryDirectory() as td:
        job = build_job(film, Path(td) / "job")
        async with page_session(job, "stage.html", w=640, h=360) as p:
            return await p.evaluate("window.__sr.scenes()")


def main() -> int:
    with render_slot(os.environ.get("SHOWREEL_RENDER_SLOT_DIR"), "gen-kit-catalog"):
        scenes = asyncio.run(read_scenes())
    for kit in KITS:
        md = ROOT / "kits" / kit / "KIT.md"
        text = md.read_text(encoding="utf-8")
        a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
        text = text[:a] + "\n" + table(scenes, kit) + "\n" + text[b:]
        md.write_bytes(text.encode("utf-8"))
        print(md, sum(1 for s in scenes if s["id"].startswith(f"kit:{kit}/")), "scenes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
