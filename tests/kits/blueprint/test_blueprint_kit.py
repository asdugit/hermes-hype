"""kits/blueprint: lint, purity, imports, catalog coverage, fonts + licences, style metadata (beds, SFX roles, post,
voice_speed 1.0), the Quick adapter mapping, and an opt-in runtime render of all 15 types in both aspects with the
kit's transitions (``pytest --runslow``)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "terminal"))
from stylekit import (  # noqa: E402
    TYPES, code, dry_run, forbidden_hits, import_problems, kit_dir, meta,
    registered_ids, sources, style_problems)

KIT = "blueprint"


def test_runtime_lint_is_clean():
    from showreel_core.film.lint import lint_paths
    bad = {k: [str(i) for i in v if i.severity == "error"] for k, v in lint_paths([kit_dir(KIT)]).items()}
    assert not {k: v for k, v in bad.items() if v}


def test_no_forbidden_apis_or_wall_clock_css():
    assert forbidden_hits(KIT) == []


def test_imports_are_relative_and_declared():
    assert import_problems(KIT) == []


def test_lf_line_endings():
    files = sources(KIT, (".js", ".css", ".json", ".md"))
    assert files and [p.name for p in files if b"\r\n" in p.read_bytes()] == []


def test_every_type_is_registered_listed_and_documented():
    ids = registered_ids(KIT)
    md = (kit_dir(KIT) / "KIT.md").read_text(encoding="utf-8")
    assert meta(KIT)["scenes"] == TYPES
    for t in TYPES:
        assert f"kit:{KIT}/{t}" in ids, t
        assert f"`kit:{KIT}/{t}`" in md, t
    for tr in meta(KIT)["transitions_defined"]:
        assert tr in ids and tr in md, tr
    assert (kit_dir(KIT) / "RECIPES.md").is_file()


def test_fonts_and_licences_ship():
    m = meta(KIT)
    for f in m["fonts"]:
        assert (kit_dir(KIT) / f["src"]).is_file(), f["src"]
    for lic in m["licenses"]:
        assert "Open Font License" in (kit_dir(KIT) / lic).read_text(encoding="utf-8", errors="replace"), lic
    assert {"Space Grotesk", "IBM Plex Mono"} <= {f["family"] for f in m["fonts"]}


def test_style_metadata_matches_assets():
    assert style_problems(KIT) == []


def test_redline_is_reserved_for_revisions():
    """Only clouds, deltas, strikes, REV letters and the FAIL stamp may use the redline colour."""
    css = (kit_dir(KIT) / "theme.css").read_text(encoding="utf-8")
    users = [u.strip() for u in re.findall(r"([^{}]+)\{[^{}]*var\(--redline\)[^{}]*\}",
                                            re.sub(r"/\*.*?\*/", "", css, flags=re.S))]
    users = [u for u in users if u != ".sr-theme-blueprint"]          # the token block (--sr-fail: var(--redline))
    allowed = ("cloud", ".red", ".rev", ".add .g", ".del .g", "fail", "stamp")
    assert users and all(any(a in u for a in allowed) for u in users), users


def test_theme_tokens_replace_the_starter():
    css = (kit_dir(KIT) / "theme.css").read_text(encoding="utf-8")
    for tok in ["--sr-stage", "--sr-fg", "--sr-accent", "--sr-accent-ink", "--sr-paper", "--sr-ink", "--sr-term",
                "--sr-scrim-rgb", "--sr-panel-edge", "--sr-panel-shadow"]:
        assert f"{tok}:" in css, tok
    sels = [s.strip() for s in re.findall(r"([^{}]+)\{[^{}]*\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))]
    assert sels and all(all(part.strip().startswith(".sr-theme-blueprint") for part in s.split(",")) for s in sels)
    assert "registerTheme('blueprint'" in code(kit_dir(KIT) / "kit.js")


def test_quick_adapter_uses_the_kit():
    from showreel_core.film.quick import kit_meta, scene_id
    for t in TYPES:
        assert scene_id(KIT, t) == f"kit:{KIT}/{t}"
    km = kit_meta(KIT)
    assert km["transitions"]["push"][0] == "kit:blueprint/sheet-slide"
    assert km["transitions"]["cut"] is None, "blueprint never crossfades; hard cuts inside acts"


@pytest.mark.slow
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_every_scene_renders_clean(tmp_path, aspect):
    r = dry_run(KIT, aspect, tmp_path)
    assert r.ready_error == "" and r.error is None, r.summary()
    assert r.scene_errors == [] and r.page_errors == [], r.summary()
    assert all(s.deterministic is not False for s in r.shots), r.summary()
    sfx = {c["sfx"] for c in r.cues}
    assert {"type", "pass", "hit", "click"} <= sfx, sfx
