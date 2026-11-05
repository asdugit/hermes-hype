"""Nature kit checks: runtime lint, forbidden APIs, imports stay inside the kit, KIT.md coverage, Node-driven
pure-logic checks (flyer paths deterministic/continuous/non-uniform, drive-slope on the ground, camera rigs,
presets, quality tiers) and an opt-in slow render of every scene through the real runtime (--runslow)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KIT = ROOT / "kits" / "nature"
NODE_DIR = Path(__file__).resolve().parent / "node"
SCENES = ["kit:nature/flower-field", "kit:nature/sky-reveal", "kit:nature/product-hero"]
BLOCKS = ["world", "sky", "mountains", "terrain", "meadow", "petals", "atlas", "flyers", "light", "quality", "presets", "paths"]
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
    issues = {k: [i for i in v if i.severity == "error"] for k, v in lint_paths([KIT]).items()}
    bad = {k: [str(i) for i in v] for k, v in issues.items() if v}
    assert not bad, bad


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_forbidden_apis(pattern):
    hits = [str(p.relative_to(ROOT)) for p in _js() if re.search(pattern, _code(p))]
    assert not hits, f"{pattern} used in {hits}"


def test_imports_stay_inside_the_kit():
    for p in _js():
        for spec in re.findall(r"""from\s+['"]([^'"]+)['"]""", p.read_text(encoding="utf-8")):
            if p.name == "kit.js" and spec == "../../runtime/showreel.js":
                continue
            assert spec.startswith("./"), f"{p.relative_to(ROOT)} imports {spec!r}"


def test_kit_md_documents_scenes_blocks_and_params():
    md = (KIT / "KIT.md").read_text(encoding="utf-8")
    for s in SCENES:
        assert s in md, s
    for b in BLOCKS:
        assert re.search(rf"`{b}\b", md), b
    for path in ["descend", "rise", "drive-slope", "float", "orbit", "arc", "cross", "hero"]:
        assert path in md, path
    for t in ["sunset", "golden", "dawn", "pastel", "dream", "night"]:
        assert t in md, t


def test_scenes_are_registered_in_kit_js():
    src = (KIT / "kit.js").read_text(encoding="utf-8")
    for s in SCENES:
        assert f"sr.defineScene('{s}'" in src, s


@pytest.fixture(scope="module")
def node_report() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    out = subprocess.run([str(node), str(NODE_DIR / "check.mjs")], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_pure_logic_checks(node_report):
    assert node_report["paths"] == 8
    assert node_report["presets"] >= 6
    assert not node_report["errors"], node_report["errors"][:8]


def test_default_squadron_is_not_a_formation(node_report):
    assert node_report["minSeparation"] >= 0.12


@pytest.mark.slow
def test_every_scene_renders_through_the_runtime(tmp_path):
    """Build a film with a synthetic product cut-out and render one keyframe per scene (software GL)."""
    from PIL import Image, ImageDraw
    cut = tmp_path / "prod.png"
    im = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((110, 140, 530, 250), 40, fill=(196, 18, 30, 255))
    d.ellipse((160, 210, 240, 290), fill=(20, 20, 22, 255)); d.ellipse((400, 210, 480, 290), fill=(20, 20, 22, 255))
    im.save(cut)
    shots, t = [], 0.0
    for i, s in enumerate(SCENES):
        shots.append({"id": f"s{i}", "t0": t, "t1": t + 3.0, "scene": s, "params": {"product": "prod", "quality": "low"}})
        t += 3.0
    film = {"version": 1, "fps": 30, "size": [960, 540], "dur": t, "seed": 3, "assets": {"prod": {"type": "image", "src": str(cut)}},
            "shots": shots}
    fp = tmp_path / "film.json"
    fp.write_text(json.dumps(film), encoding="utf-8")
    out = subprocess.run([sys.executable, "-m", "showreel_core.film.preview", str(fp), "--keyframes", "1.5,4.5,7.5", "--size", "960x540",
                          "--gpu", "off", "--json", "--out", str(tmp_path / "out")], capture_output=True, text=True, encoding="utf-8",
                         cwd=ROOT, timeout=600)
    res = json.loads(out.stdout[out.stdout.index("{"):out.stdout.rindex("}") + 1])
    assert res["ok"], res.get("error")
    assert not res["errors"] and not res["page_errors"], (res["errors"], res["page_errors"])
    kfs = sorted((tmp_path / "out").glob("kf_*.png"))
    assert len(kfs) == 3, kfs
    for f in kfs:
        with Image.open(f) as k:
            g = k.convert("L").resize((64, 36))
            px = list(g.tobytes())
            assert sum(px) / len(px) > 40, f"{f.name} too dark"
            assert max(px) - min(px) > 40, f"{f.name} flat"
