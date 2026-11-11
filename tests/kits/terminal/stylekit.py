"""Shared checks for the wave-3 signature style kits (terminal, blueprint): static (lint, purity, imports, catalog,
fonts, style metadata vs the audio assets and post chains) and an opt-in runtime render of every scene type in
both aspects through the real runtime (``pytest --runslow``)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KITS = ROOT / "kits"
FIX = ROOT / "tests" / "kits" / "fixtures"
TYPES = ["HOOK", "TITLE", "PROBLEM", "PLAN", "CODE", "DIFF", "TERMINAL", "MONTAGE", "SCREEN", "STATS",
         "BEFORE_AFTER", "CALLOUT", "END", "FEATURE", "SCROLL"]
FORBIDDEN = [r"\bMath\.random\b", r"\bDate\b", r"\bperformance\.now\b", r"\bsetTimeout\b", r"\bsetInterval\b",
             r"\brequestAnimationFrame\b", r"\bfetch\s*\(", r"\bXMLHttpRequest\b", r"\bWebSocket\b", r"\bEventSource\b",
             r"\bimport\s*\(", r"\beval\s*\(", r"\bnew\s+Function\b", r"\bdocument\.", r"\bwindow\.",
             r"\btransition\s*:", r"\banimation\s*:", r"@keyframes"]
SVG_NS = "http://www.w3.org/2000/svg"


def kit_dir(kit: str) -> Path:
    return KITS / kit


def code(p: Path) -> str:
    """Source without comments (so docs may mention forbidden names)."""
    src = p.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", " ", src)


def sources(kit: str, exts: tuple[str, ...] = (".js", ".css")) -> list[Path]:
    return sorted(p for p in kit_dir(kit).rglob("*") if p.suffix in exts and "fonts" not in p.parts)


def meta(kit: str) -> dict:
    return json.loads((kit_dir(kit) / "kit.json").read_text(encoding="utf-8"))


def forbidden_hits(kit: str) -> list[str]:
    hits = []
    for p in sources(kit):
        c = code(p)
        for pat in FORBIDDEN:
            if re.search(pat, c):
                hits.append(f"{p.name}: {pat}")
        urls = [u for u in re.findall(r"https?://[^\s'\"`)]+", c) if not u.startswith(SVG_NS)]
        if urls:
            hits.append(f"{p.name}: external url {urls[:2]}")
    return hits


def import_problems(kit: str) -> list[str]:
    """Every import is relative: ./x.js inside the kit or ../<kit>/... for a kit listed in kit.json requires."""
    req = set(meta(kit)["requires"])
    bad = []
    for p in sources(kit, (".js",)):
        for spec in re.findall(r"""(?:from|import)\s+['"]([^'"]+)['"]""", p.read_text(encoding="utf-8")):
            m = re.match(r"\.\./([a-z0-9_-]+)/", spec)
            if m:
                if m.group(1) not in req:
                    bad.append(f"{p.name} imports kit {m.group(1)!r} not in requires")
            elif not spec.startswith("./"):
                bad.append(f"{p.name} imports {spec!r}")
    return bad


def registered_ids(kit: str) -> set[str]:
    out: set[str] = set()
    for p in sources(kit, (".js",)):
        out |= set(re.findall(rf"""['"](kit:{kit}/[A-Za-z_-]+)['"]""", p.read_text(encoding="utf-8")))
    return out


def style_problems(kit: str) -> list[str]:
    """kit.json "style" metadata agrees with the shipped audio assets, sfx roles and render post chains."""
    from showreel_core.config import discover_styles
    from showreel_core.render.post import POST_CHAINS

    m = meta(kit)
    st = m.get("style") or {}
    bad = []
    if st.get("id") != kit:
        bad.append("style.id")
    if float(st.get("voice_speed", 0)) != 1.0:
        bad.append("voice_speed must be 1.0 (locked by the user)")
    beds = json.loads((ROOT / "assets" / "audio" / "beds" / kit / "bars.json").read_text(encoding="utf-8"))
    ids = {b["id"]: b for b in beds["beds"]}
    for b in st.get("music") or []:
        if b not in ids:
            bad.append(f"music bed {b} missing")
    lo, hi = st.get("bpm") or [0, 0]
    for b in st.get("music") or []:
        if b in ids and not lo <= float(ids[b]["bpm"]) <= hi:
            bad.append(f"bed {b} bpm {ids[b]['bpm']} outside {lo}-{hi}")
    sfx = json.loads((ROOT / "assets" / "audio" / "sfx" / "sfx.json").read_text(encoding="utf-8"))
    table = (sfx.get("styles") or {}).get(kit) or {}
    for role, name in (st.get("sfx") or {}).items():
        if table.get(role) != name:
            bad.append(f"style.sfx {role}={name} differs from sfx.json ({table.get(role)})")
    for name in str(st.get("post") or "none").split("+"):
        if name not in POST_CHAINS:
            bad.append(f"unknown post chain {name}")
    info = discover_styles(ROOT).get(kit)
    if info is None or not info.ready or info.source != f"kit:{kit}" or info.voice_speed != 1.0:
        bad.append(f"discover_styles: {info}")
    return bad


def gallery(kit: str, aspect: str) -> tuple[dict, dict]:
    """One shot per scene sample (all 15 types; TERMINAL / HOOK / BEFORE_AFTER variants), small film size."""
    samples = json.loads((FIX / "scene_samples.json").read_text(encoding="utf-8"))
    dur = {"HOOK": 2.5, "TITLE": 3.0, "PROBLEM": 3.5, "PLAN": 3.5, "CODE": 4, "DIFF": 4, "TERMINAL": 3.5, "MONTAGE": 3.5,
           "SCREEN": 3.5, "STATS": 3, "BEFORE_AFTER": 3.5, "CALLOUT": 3, "END": 3.5, "FEATURE": 3.5, "SCROLL": 4}
    shots, t = [], 0.0
    for key, data in samples.items():
        if key.startswith("_"):
            continue
        typ = "BEFORE_AFTER" if key.startswith("BEFORE_AFTER") else key.split("_")[0]
        if typ not in dur:
            continue
        shots.append({"id": key.lower(), "t0": round(t, 3), "t1": round(t + dur[typ], 3), "scene": f"kit:{kit}/{typ}",
                      "params": {**data, "theme": kit}})
        t += dur[typ]
    trs = meta(kit).get("transitions_defined") or []
    transitions = []
    if trs and len(shots) > 2:
        for i, name in enumerate(trs):
            a, b = shots[i], shots[i + 1]
            transitions.append({"from": a["id"], "to": b["id"], "type": name, "t": round(b["t0"] - 0.15, 3), "dur": 0.3})
            a["t1"] = round(b["t0"] + 0.15, 3)
            b["t0"] = round(b["t0"] - 0.15, 3)
    media = FIX / "media"
    assets = {n: {"src": str(media / f"{f}.png"), "type": "image"} for n, f in
              [("home", "focusfox_home"), ("dark", "focusfox_dark"), ("full", "focusfox_full"), ("tally", "tally_report")]}
    film = {"version": 1, "fps": 30, "size": [960, 540] if aspect == "16:9" else [540, 960], "dur": round(t, 3), "seed": 7,
            "kits": [kit], "shots": shots, "transitions": transitions, "assets": {n: {"type": "image"} for n in assets},
            "captions": [{"t0": 1.0, "t1": 2.2, "text": "Captions sit above the drawing."}]}
    return film, assets


def dry_run(kit: str, aspect: str, tmp: Path):
    from showreel_core.film.dryrun import dryrun
    from showreel_core.film.page import build_job
    from showreel_core.film.preview import render_slot

    film, assets = gallery(kit, aspect)
    job = build_job(film, tmp / "job", assets=assets)
    with render_slot(os.environ.get("HYPE_RENDER_SLOT_DIR"), f"pytest-kits-{kit}"):
        return dryrun(job, per_shot=2)
