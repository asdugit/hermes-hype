"""Cinematic kit checks: runtime lint, forbidden APIs, imports, KIT.md coverage of the 15 types, fonts + licences,
and an opt-in slow render of every scene with the synthetic scene samples through the real runtime (--runslow)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KIT = ROOT / "kits" / "cinematic"
TYPES = ["HOOK", "TITLE", "PROBLEM", "PLAN", "CODE", "DIFF", "TERMINAL", "MONTAGE", "SCREEN", "STATS",
         "BEFORE_AFTER", "CALLOUT", "END", "FEATURE", "SCROLL"]
EXTRA = ["card-field", "screen-push"]
FORBIDDEN = [r"\bMath\.random\b", r"\bDate\b", r"\bperformance\.now\b", r"\bsetTimeout\b", r"\bsetInterval\b",
             r"\brequestAnimationFrame\b", r"\bfetch\s*\(", r"\bXMLHttpRequest\b", r"\bWebSocket\b", r"\bEventSource\b",
             r"\bimport\s*\(", r"\beval\s*\(", r"\bnew\s+Function\b", r"\bdocument\.", r"\bwindow\.", r"https?://"]


def _js() -> list[Path]:
    return sorted(KIT.rglob("*.js"))


def _code(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"(?m)//.*$", " ", src)


def test_runtime_lint_is_clean():
    from showreel_core.film.lint import lint_paths
    bad = {k: [str(i) for i in v if i.severity == "error"] for k, v in lint_paths([KIT]).items()}
    assert not {k: v for k, v in bad.items() if v}


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_forbidden_apis(pattern):
    hits = [str(p.relative_to(ROOT)) for p in _js() if re.search(pattern, _code(p))]
    assert not hits, f"{pattern} used in {hits}"


def test_imports_are_declared():
    meta = json.loads((KIT / "kit.json").read_text(encoding="utf-8"))
    for p in _js():
        for spec in re.findall(r"""from\s+['"]([^'"]+)['"]""", p.read_text(encoding="utf-8")):
            if spec == "../../runtime/showreel.js":
                assert p.name == "kit.js"
                continue
            m = re.match(r"\.\./([a-z0-9_-]+)/", spec)
            if m and p.parent == KIT:
                assert m.group(1) in meta["requires"], f"{p.name} imports kit {m.group(1)!r} not in kit.json requires"
            else:
                assert spec.startswith("./"), f"{p.relative_to(ROOT)} imports {spec!r}"


def test_every_type_is_registered_and_documented():
    src = (KIT / "kit.js").read_text(encoding="utf-8")
    md = (KIT / "KIT.md").read_text(encoding="utf-8")
    meta = json.loads((KIT / "kit.json").read_text(encoding="utf-8"))
    for t in TYPES + EXTRA:
        assert f"'kit:cinematic/{t}'" in src, t
        assert f"kit:cinematic/{t}" in md, t
        assert t in meta["scenes"], t


def test_fonts_and_licences_ship():
    meta = json.loads((KIT / "kit.json").read_text(encoding="utf-8"))
    for f in meta["fonts"]:
        assert (KIT / f["src"]).is_file(), f["src"]
    for lic in meta["licenses"]:
        assert "Open Font License" in (KIT / lic).read_text(encoding="utf-8", errors="replace"), lic


@pytest.mark.slow
def test_every_scene_renders_through_the_runtime(tmp_path):
    samples = json.loads((ROOT / "tests" / "kits" / "fixtures" / "scene_samples.json").read_text(encoding="utf-8"))
    media = ROOT / "tests" / "kits" / "fixtures" / "media"
    assets = {p.stem.replace("focusfox_", ""): {"type": "image", "src": str(p)} for p in media.glob("*.png")}
    shots, t = [], 0.0
    for name in TYPES + EXTRA:
        p = dict(samples.get(name) or {})
        if name == "card-field":
            p = {"cards": [{"kind": "code", **samples["CODE"]}, {"kind": "terminal", **samples["TERMINAL"]}], "hero": 1}
        if name == "screen-push":
            p = dict(samples.get("SCREEN") or {})
        shots.append({"id": f"s{len(shots)}", "t0": t, "t1": t + 2.0, "scene": f"kit:cinematic/{name}", "params": {**p, "quality": "low"}})
        t += 2.0
    film = {"version": 1, "fps": 30, "size": [960, 540], "dur": t, "seed": 5, "assets": assets, "shots": shots}
    fp = tmp_path / "film.json"
    fp.write_text(json.dumps(film), encoding="utf-8")
    kfs = ",".join(f"{2.0 * i + 1.5:.1f}" for i in range(len(shots)))
    out = subprocess.run([sys.executable, "-m", "showreel_core.film.preview", str(fp), "--keyframes", kfs, "--size", "960x540",
                          "--gpu", "off", "--json", "--lenient", "--out", str(tmp_path / "out")], capture_output=True, text=True,
                         encoding="utf-8", cwd=ROOT, timeout=900)
    res = json.loads(out.stdout[out.stdout.index("{"):out.stdout.rindex("}") + 1])
    assert res["ok"], res.get("error")
    assert not res["errors"] and not res["page_errors"], (res["errors"][:5], res["page_errors"][:5])
    from PIL import Image
    files = sorted((tmp_path / "out").glob("kf_*.png"))
    assert len(files) == len(shots)
    for f in files:
        with Image.open(f) as k:
            px = list(k.convert("L").resize((96, 54)).tobytes())
            assert max(px) > 90, f"{f.name}: nothing lit"
