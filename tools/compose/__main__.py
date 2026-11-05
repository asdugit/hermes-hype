"""CLI: ``python -m tools.compose --all | --beds id[,id] | --sfx`` (see package docstring)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import beds
from .encode import decode, encode, render_lock, spectrogram_png

REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / "assets" / "audio"


def build_bed(style: str, variant: str, out_root: Path, spectro: Path | None = None) -> dict:
    """Compose, master, encode one bed and return its bars.json entry (+ timing)."""
    t0 = time.perf_counter()
    song = beds.module(style).compose(variant)
    t1 = time.perf_counter()
    y, rep = song.render(-16.0)
    t2 = time.perf_counter()
    rel = f"{song.id}.ogg"
    path = out_root / "beds" / style / rel
    encode(y, path, "opus", "96k")
    dec = decode(path)
    entry = song.bars_json(rel, rep)
    entry["decoded_samples_match"] = int(dec.shape[-1]) == int(y.shape[-1])
    entry["bytes"] = path.stat().st_size
    entry["bands"] = rep.get("bands")
    entry["mono_fold_db"] = rep.get("mono_fold_db")
    entry["section_lufs"] = rep.get("section_lufs")
    entry["lowshelf_db"] = rep.get("lowshelf_db")
    entry["section_lift_db"] = rep.get("section_lift_db")
    entry["render_s"] = {"compose": round(t1 - t0, 2), "mix_master": round(t2 - t1, 2),
                         "encode": round(time.perf_counter() - t2, 2)}
    if spectro:
        spectrogram_png(y, spectro / f"spec_{song.id}.png")
    return entry


def write_bars(out_root: Path, style: str, entries: list[dict]) -> None:
    """Merge entries into ``beds/<style>/bars.json`` (sorted by id)."""
    p = out_root / "beds" / style / "bars.json"
    data = {"style": style, "beds": []}
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
    keep = {b["id"]: b for b in data.get("beds", [])}
    for e in entries:
        keep[e["id"]] = e
    data["beds"] = [keep[k] for k in sorted(keep)]
    data["generator"] = "tools/compose (procedural, original; regenerate with python -m tools.compose --all)"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.compose")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--beds", default="")
    ap.add_argument("--sfx", action="store_true")
    ap.add_argument("--out", type=Path, default=ASSETS)
    ap.add_argument("--spectro", type=Path, default=None, help="write debug spectrogram PNGs here")
    a = ap.parse_args(argv)
    todo = beds.all_beds() if a.all else [tuple(b.split("_", 1)) for b in a.beds.split(",") if b]
    with render_lock():
        by_style: dict[str, list[dict]] = {}
        for style, variant in todo:
            e = build_bed(style, variant, a.out, a.spectro)
            by_style.setdefault(style, []).append(e)
            print(f"{e['id']:<14} {e['duration_s']:6.1f}s  LUFS {e['lufs']}  TP {e['true_peak_db']}  "
                  f"phone {e['phone_band']}  corr {e['lr_corr']}  {e['bytes'] / 1e6:.2f} MB  {e['render_s']}",
                  flush=True)
        for style, entries in by_style.items():
            write_bars(a.out, style, entries)
        if a.all or a.sfx:
            from .sfx import build_kit
            build_kit(a.out / "sfx")
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    sys.exit(main())
