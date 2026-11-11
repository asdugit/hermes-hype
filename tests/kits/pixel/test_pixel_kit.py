"""Pixel kit checks: lint (forbidden APIs), glyph table sanity, SFX names, KIT.md coverage, and the Node-driven
render checks (every scene x aspect x time: no exceptions, palette-only pixels, pure function of t, text inside the
safe area, valid cues) plus boss-battle schedule invariants. Node is optional: those tests skip without it."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KIT = ROOT / "kits" / "pixel"
NODE_DIR = Path(__file__).resolve().parent / "node"

FORBIDDEN = [r"\bMath\.random\b", r"\bDate\b", r"\bperformance\.now\b", r"\bsetTimeout\b", r"\bsetInterval\b",
             r"\brequestAnimationFrame\b", r"\bfetch\s*\(", r"\bXMLHttpRequest\b", r"\bWebSocket\b", r"\bEventSource\b",
             r"\bimport\s*\(", r"\beval\s*\(", r"\bnew\s+Function\b", r"\bdocument\.", r"\bwindow\.", r"https?://"]


def _code(path: Path) -> str:
    """JS source with comments and string literals blanked (so docs may mention forbidden names)."""
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"(?m)//.*$", " ", src)
    return src


def _js_files() -> list[Path]:
    return [p for p in KIT.rglob("*.js") if p.name != "glyphs.js"]


def test_kit_has_scenes_and_transitions():
    assert (KIT / "kit.js").is_file()
    assert len(_js_files()) >= 15


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_forbidden_apis(pattern):
    hits = [f"{p.relative_to(ROOT)}" for p in _js_files() if re.search(pattern, _code(p))]
    assert not hits, f"{pattern} used in {hits}"


def test_imports_stay_inside_the_kit():
    """Only kit.js may reach the runtime; sub-modules import siblings via './../' (page.py treats '../x/' as a kit)."""
    for p in _js_files():
        for spec in re.findall(r"""from\s+['"]([^'"]+)['"]""", p.read_text(encoding="utf-8")):
            if p.name == "kit.js" and spec == "../../runtime/showreel.js":
                continue
            assert spec.startswith("./"), f"{p.relative_to(ROOT)} imports {spec!r}"
            assert not re.match(r"\.\./[a-z0-9_-]+/", spec), spec


def _glyphs() -> dict:
    text = (KIT / "core" / "glyphs.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("{"):text.rindex(";")])


def test_glyph_tables_are_crisp():
    g = _glyphs()
    assert set(g) >= {"mono", "caps", "tiny"}
    for name, font in g.items():
        assert all(chr(c) in font["glyphs"] for c in range(32, 127)), name
        adv = {font["glyphs"][c][0] for c in "AMmwi0"}
        if name != "tiny":
            assert len(adv) == 1, f"{name} is not monospaced: {adv}"
    # the 'm' of the 11 px mono font must keep its 1-px stem gaps (the 1-bit threshold bug filled them)
    m = _glyphs()["mono"]["glyphs"]["m"]
    w, rows = m[3], m[5:]
    assert any(bin(r).count("1") < w for r in rows)


def test_sfx_intents_exist_in_the_sfx_kit():
    names = set(json.loads((ROOT / "assets/audio/sfx/sfx.json").read_text(encoding="utf-8"))["sounds"])
    src = (KIT / "cues.js").read_text(encoding="utf-8")
    used = re.findall(r":\s*\['([a-z_]+)',\s*-?\d", src)
    assert used and set(used) <= names, set(used) - names


def test_kit_md_documents_every_scene_and_transition():
    md = (KIT / "KIT.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"""['"](kit:pixel/[A-Za-z_-]+)['"]""", "".join(p.read_text(encoding="utf-8") for p in _js_files())))
    ids |= {f"kit:pixel/{t}" for t in ("HOOK", "TITLE", "PROBLEM", "PLAN", "CODE", "DIFF", "TERMINAL", "MONTAGE", "SCREEN",
                                        "STATS", "BEFORE_AFTER", "CALLOUT", "END", "FEATURE", "SCROLL")}
    missing = sorted(i for i in ids if i not in md)
    assert not missing, missing


NODE = shutil.which("node")


@pytest.fixture(scope="module")
def node_report() -> dict:
    node = NODE
    if not node:
        pytest.skip("node not installed")
    out = subprocess.run([node, str(NODE_DIR / "check.mjs")], capture_output=True, text=True, encoding="utf-8",
                         cwd=str(ROOT), timeout=300, check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_every_scene_renders(node_report):
    assert node_report["scenes"] >= 22
    assert not node_report["errors"], node_report["errors"][:5]


def test_quick_hook_opens_lit(node_report):
    """Frame 0 is the film's thumbnail: qa/video.py warns below mean luma 16 (a real E2E pixel film had 10.2)."""
    for size, luma in node_report["hookLuma"].items():
        assert luma >= 24, (size, luma)


def test_quick_title_press_start_clears_the_caption_band(node_report):
    """With captions up, PRESS START blinks under the tagline, not on the caption line (real 9:16 E2E film)."""
    for size, box in node_report["titlePress"].items():
        assert box is not None, size
        w, h = (int(v) for v in size.split("x"))
        assert box["y1"] <= h * (0.68 if h > w else 0.76), (size, box)


def test_palette_discipline(node_report):
    assert not node_report["offPalette"], node_report["offPalette"][:5]


def test_render_is_a_pure_function_of_t(node_report):
    assert not node_report["nondeterministic"], node_report["nondeterministic"][:5]


def test_text_inside_safe_area(node_report):
    assert not node_report["unsafeText"], node_report["unsafeText"][:5]


def test_cues_use_known_sounds(node_report):
    assert not node_report["badCues"], node_report["badCues"][:5]


def test_boss_schedule_walks_the_cursor_to_the_pick(node_report):
    s = node_report["schedule"]
    assert s["click"] == pytest.approx(12.4)
    ts = [m["t"] for m in s["moves"]]
    assert ts == sorted(ts) and ts[-1] < s["click"] - 0.5
    assert s["moves"][-1]["idx"] == s["pickIdx"] == 2
    assert s["hits"] == sorted(s["hits"]) and s["hits"][-1] < s["menuT"]


def test_frame_budget(node_report):
    """Scenes must stay cheap (Node, no GPU): <= 60 ms average per frame at game resolution.

    Shared CI runners are 2-5x slower and noisy (a windows-latest run measured 150 ms for a 40 ms scene), so on
    CI the budget only catches pathological regressions.
    """
    budget = 60 * (5 if os.environ.get("CI") else 1)
    slow = {k: v for k, v in node_report["ms"].items() if v > budget}
    assert not slow, slow
