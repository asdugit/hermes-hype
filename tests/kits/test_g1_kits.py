"""kits/base, kits/launch, kits/type: static checks (lint, purity, catalog coverage, themes, line endings) and an
opt-in runtime dry-run of every scene type in both aspects (``pytest --runslow``)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from showreel_core.film.lint import lint_paths

ROOT = Path(__file__).resolve().parents[2]
KITS = ROOT / "kits"
TYPES = ["HOOK", "TITLE", "PROBLEM", "PLAN", "CODE", "DIFF", "TERMINAL", "MONTAGE", "SCREEN", "STATS",
         "BEFORE_AFTER", "CALLOUT", "END", "FEATURE", "SCROLL"]
MINE = ("base", "launch", "type")
FIX = ROOT / "tests" / "kits" / "fixtures"


def _files(kit: str, exts=(".js", ".css", ".json", ".md")) -> list[Path]:
    return [p for p in (KITS / kit).rglob("*") if p.suffix in exts and "fonts" not in p.parts]


def _code(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", " ", src)


@pytest.mark.parametrize("kit", MINE)
def test_lint_clean(kit):
    issues = [i for v in lint_paths([KITS / kit]).values() for i in v]
    assert [i for i in issues if getattr(i, "severity", "error") == "error"] == []


@pytest.mark.parametrize("kit", MINE)
def test_pure_of_t(kit):
    bad = re.compile(r"\bMath\.random\b|\bDate\b|\bperformance\.now\b|\bsetTimeout\b|\brequestAnimationFrame\b|"
                     r"\btransition\s*:|\banimation\s*:|@keyframes")
    hits = [f"{p.name}: {m.group(0)}" for p in _files(kit, (".js", ".css")) for m in bad.finditer(_code(p))]
    assert hits == []


@pytest.mark.parametrize("kit", MINE)
def test_lf_line_endings(kit):
    assert [p.name for p in _files(kit) if b"\r\n" in p.read_bytes()] == []


def test_base_and_launch_define_every_type():
    base = "".join(p.read_text(encoding="utf-8") for p in (KITS / "base").glob("scenes-*.js"))
    launch = "".join(p.read_text(encoding="utf-8") for p in (KITS / "launch").glob("scenes-*.js"))
    for t in TYPES:
        assert re.search(rf"'kit:base/{t}'", base), t
        assert re.search(rf"launchScene\('kit:launch/{t}'", launch), t
    for kit in ("base", "launch"):
        meta = json.loads((KITS / kit / "kit.json").read_text(encoding="utf-8"))
        assert meta["scenes"] == TYPES


def test_kit_md_catalogs_cover_every_scene():
    for kit, ids in (("base", [f"kit:base/{t}" for t in TYPES]), ("launch", [f"kit:launch/{t}" for t in TYPES]),
                     ("type", [f"kit:type/{n}" for n in json.loads((KITS / "type" / "kit.json").read_text())["scenes"]])):
        md = (KITS / kit / "KIT.md").read_text(encoding="utf-8")
        assert "<!-- scenes:begin -->" in md and "<!-- scenes:end -->" in md
        missing = [i for i in ids if f"`{i}`" not in md]
        assert missing == [], (kit, missing)


TOKENS = ["--sr-stage", "--sr-fg", "--sr-accent", "--sr-accent-ink", "--sr-paper", "--sr-ink", "--sr-term",
          "--sr-scrim-rgb", "--sr-panel-edge", "--sr-panel-shadow"]


@pytest.mark.parametrize("theme", ["terminal", "blueprint", "comic", "ink"])
def test_starter_themes_are_token_only_reskins(theme):
    css = (KITS / "base" / "themes" / f"{theme}.css").read_text(encoding="utf-8")
    assert css.lstrip().startswith("/*") and f".sr-theme-{theme} {{" in css
    for tok in TOKENS:
        assert f"{tok}:" in css, (theme, tok)
    # every selector is scoped to the theme (no global leakage)
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    sels = [s.strip() for s in re.findall(r"([^{}]+)\{[^{}]*\}", bare)]
    assert sels and all(all(part.strip().startswith(f".sr-theme-{theme}") for part in s.split(",")) for s in sels), sels
    assert theme in json.loads((KITS / "base" / "kit.json").read_text())["themes"]


def test_tokens_documented():
    md = (KITS / "base" / "KIT.md").read_text(encoding="utf-8")
    base = (KITS / "base" / "base.css").read_text(encoding="utf-8")
    decl = set(re.findall(r"(--sr-[a-z0-9-]+)\s*:", base.split("}")[0]))
    undocumented = [t for t in sorted(decl) if t not in md]
    assert undocumented == []


def test_no_newspaper_theme():
    assert not (KITS / "base" / "themes" / "newspaper.css").exists()
    assert "newspaper" not in (KITS / "base" / "kit.json").read_text()


# ------------------------------------------------------------------------------------------- runtime dry-run

def _gallery(kit: str, aspect: str, theme: str) -> tuple[dict, dict]:
    samples = json.loads((FIX / "scene_samples.json").read_text(encoding="utf-8"))
    dur = {"HOOK": 2.5, "TITLE": 3.5, "PROBLEM": 4.5, "PLAN": 4.5, "CODE": 5, "DIFF": 5, "TERMINAL": 4.5, "MONTAGE": 5,
           "SCREEN": 5, "STATS": 3.5, "BEFORE_AFTER": 5, "CALLOUT": 3.5, "END": 4, "FEATURE": 5, "SCROLL": 5.5}
    shots, t = [], 0.0
    for key, data in samples.items():
        if key.startswith("_"):
            continue
        typ = "BEFORE_AFTER" if key.startswith("BEFORE_AFTER") else key.split("_")[0]
        if typ not in dur:
            continue
        shots.append({"id": key.lower(), "t0": t, "t1": t + dur[typ], "scene": f"kit:{kit}/{typ}", "params": {**data, "theme": theme}})
        t += dur[typ]
    media = FIX / "media"
    assets = {n: {"src": str(media / f"{f}.png"), "type": "image"} for n, f in
              [("home", "focusfox_home"), ("dark", "focusfox_dark"), ("full", "focusfox_full"), ("tally", "tally_report")]}
    film = {"version": 1, "fps": 30, "size": [960, 540] if aspect == "16:9" else [540, 960], "dur": t, "seed": 7,
            "shots": shots, "assets": {n: {"type": "image"} for n in assets},
            "overlays": [{"id": "ov", "t0": 0.5, "t1": 2.5, "scene": "kit:type/title", "params": {"text": "Ship it tonight", "theme": theme}}]}
    return film, assets


@pytest.mark.slow
@pytest.mark.parametrize("kit,theme", [("base", "base"), ("base", "comic"), ("launch", "launch")])
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_every_scene_renders_clean(tmp_path, kit, theme, aspect):
    from showreel_core.film.dryrun import dryrun
    from showreel_core.film.page import build_job
    from showreel_core.film.preview import render_slot

    film, assets = _gallery(kit, aspect, theme)
    job = build_job(film, tmp_path / "job", assets=assets)
    with render_slot(os.environ.get("AUTEUR_RENDER_SLOT_DIR"), "pytest-kits-g1"):
        r = dryrun(job, per_shot=2)
    assert r.ready_error == "" and r.error is None, r.summary()
    assert r.scene_errors == [] and r.page_errors == [], r.summary()
    assert all(s.deterministic is not False for s in r.shots), r.summary()
    cues = {c["sfx"] for c in r.cues}
    assert cues, "scenes emit cues"
