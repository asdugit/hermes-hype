"""Shared checks for Blender kit scene modules (no bpy needed): static PARAMS / DESCRIBE parse, the same way the
Director's catalog reads them, plus helpers for the opt-in real-Blender tests."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KITS = REPO / "blender_kits"
TYPES = {"enum", "float", "int", "bool", "string", "color", "asset", "list"}


def scene_files(kit: str) -> list[Path]:
    """Scene modules of a kit (``_*.py`` are private helpers)."""
    return sorted(p for p in (KITS / kit).glob("*.py") if not p.name.startswith("_"))


def static_module(path: Path) -> dict:
    """PARAMS / DESCRIBE literals + top-level function names, without importing (no bpy)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict = {"functions": set()}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("PARAMS", "DESCRIBE"):
                out[name] = ast.literal_eval(node.value)
        elif isinstance(node, ast.FunctionDef):
            out["functions"].add(node.name)
    return out


def check_scene(path: Path) -> list[str]:
    """Problems with one scene module's static contract (empty list = good)."""
    errs = []
    try:
        m = static_module(path)
    except (ValueError, SyntaxError) as exc:
        return [f"{path.name}: PARAMS/DESCRIBE not literal: {exc}"]
    if "build" not in m["functions"]:
        errs.append(f"{path.name}: no build(sc)")
    if "cues" not in m["functions"]:
        errs.append(f"{path.name}: no cues(sc)")
    d = m.get("DESCRIBE")
    if not isinstance(d, str) or len(d) < 40:
        errs.append(f"{path.name}: DESCRIBE missing/short")
    params = m.get("PARAMS")
    if not isinstance(params, dict) or not params:
        return errs + [f"{path.name}: PARAMS missing"]
    for k, spec in params.items():
        if not isinstance(spec, dict):
            errs.append(f"{path.name}:{k}: spec is not a dict")
            continue
        if spec.get("type") not in TYPES:
            errs.append(f"{path.name}:{k}: bad type {spec.get('type')!r}")
        if "default" not in spec:
            errs.append(f"{path.name}:{k}: no default")
        if not isinstance(spec.get("doc"), str) or len(spec["doc"]) < 8:
            errs.append(f"{path.name}:{k}: doc missing")
        if spec.get("type") == "enum":
            vals = spec.get("values") or []
            if spec.get("default") not in vals:
                errs.append(f"{path.name}:{k}: enum default {spec.get('default')!r} not in {vals}")
        lo, hi, dv = spec.get("min"), spec.get("max"), spec.get("default")
        if isinstance(dv, (int, float)) and not isinstance(dv, bool):
            if (lo is not None and dv < lo) or (hi is not None and dv > hi):
                errs.append(f"{path.name}:{k}: default {dv} outside [{lo}, {hi}]")
    return errs


def lib_importable() -> None:
    """Put the repo on sys.path so ``blender_kits.lib.<pure helpers>`` import without Blender."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))


def blender_dev_env() -> None:
    """Dev-PC defaults for the shared locks (no-op elsewhere)."""
    sys.path.insert(0, str(REPO / "tests" / "blender"))
    os.environ.setdefault("SHOWREEL_DEV_MIN_FREE_GB", "3.5")


def synth_ui(path: Path, w: int = 1440, h: int = 900, tall: bool = False) -> Path:
    """Synthetic UI screenshot (header bar, hero gradient, cards, text-like bars) — repo fixtures stay synthetic."""
    from PIL import Image, ImageDraw

    H = h * 3 if tall else h
    im = Image.new("RGB", (w, H), (250, 248, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 64], fill=(255, 255, 255))
    d.rectangle([40, 22, 180, 42], fill=(124, 58, 237))
    for y in range(64, int(h * 0.75)):
        k = (y - 64) / (h * 0.75)
        d.line([(0, y), (w, y)], fill=(int(160 - 60 * k), int(130 - 80 * k), int(245 - 70 * k)))
    d.rectangle([w // 2 - 300, int(h * 0.42), w // 2 + 300, int(h * 0.42) + 48], fill=(255, 255, 255))
    d.rounded_rectangle([w // 2 - 70, int(h * 0.6), w // 2 + 70, int(h * 0.6) + 50], 10, fill=(124, 58, 237))
    for i in range(3):
        x = 170 + i * 376
        d.rounded_rectangle([x, int(h * 0.8), x + 348, int(h * 0.8) + 170], 14, fill=(255, 255, 255),
                            outline=(226, 232, 240), width=2)
    if tall:
        for j in range(12):
            y = h + 80 + j * 150
            d.rounded_rectangle([120, y, w - 120, y + 120], 12, fill=(255, 255, 255) if j % 2 else (237, 233, 254))
    im.save(path)
    return path
