"""kits/comic: lint, purity, imports, catalog coverage, fonts + licences, style metadata (beds, SFX roles, post,
voice_speed 1.0), the Quick adapter mapping, comic-specific invariants (hard shadows only, seeded art), and an
opt-in runtime render of all 15 types in both aspects with the kit's transitions (``pytest --runslow``)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "terminal"))
from stylekit import (  # noqa: E402
    KITS, TYPES, code, dry_run, forbidden_hits, kit_dir, meta, registered_ids, sources, style_problems)

KIT = "comic"


def import_problems(kit: str) -> list[str]:
    """Every import is a relative path that resolves inside this kit or inside a kit listed in kit.json requires
    (nested lib/ folders allowed, unlike stylekit's flat check)."""
    allowed = {kit, *meta(kit)["requires"]}
    bad = []
    for p in sources(kit, (".js",)):
        for spec in re.findall(r"""(?:from|import)\s+['"]([^'"]+)['"]""", p.read_text(encoding="utf-8")):
            if not spec.startswith("."):
                bad.append(f"{p.name} imports {spec!r}")
                continue
            target = (p.parent / spec).resolve()
            try:
                owner = target.relative_to(KITS.resolve()).parts[0]
            except ValueError:
                owner = "<outside kits>"
            if owner not in allowed:
                bad.append(f"{p.name} imports {spec!r} from {owner!r} (not in requires)")
            elif not target.is_file():
                bad.append(f"{p.name} imports missing {spec!r}")
    return bad


def test_runtime_lint_is_clean():
    from showreel_core.film.lint import lint_paths
    bad = {k: [str(i) for i in v if i.severity == "error"] for k, v in lint_paths([kit_dir(KIT)]).items()}
    assert not {k: v for k, v in bad.items() if v}


def test_no_forbidden_apis_or_wall_clock_css():
    assert forbidden_hits(KIT) == []


def test_imports_are_relative_and_declared():
    assert import_problems(KIT) == []


def test_lf_line_endings():
    files = sources(KIT, (".js", ".css", ".json", ".md")) + sorted((kit_dir(KIT) / "fonts").glob("*.txt"))
    assert files and [p.name for p in files if b"\r\n" in p.read_bytes()] == []


def test_every_type_is_registered_listed_and_documented():
    ids = registered_ids(KIT)
    md = (kit_dir(KIT) / "KIT.md").read_text(encoding="utf-8")
    assert meta(KIT)["scenes"] == TYPES
    for t in TYPES:
        assert f"kit:{KIT}/{t}" in ids, t
        assert f"`kit:{KIT}/{t}`" in md, t
    for tr in meta(KIT)["transitions_defined"]:
        assert tr in ids and f"`{tr}`" in md, tr
    for v in meta(KIT)["transitions"].values():
        assert v is None or v[0] in meta(KIT)["transitions_defined"], v
    assert (kit_dir(KIT) / "RECIPES.md").is_file()


def test_catalog_parser_sees_scenes_and_transitions():
    from showreel_core.director.catalog import parse_kit
    info = parse_kit(kit_dir(KIT))
    ids = {s.id for s in info.scenes}
    assert {f"kit:{KIT}/{t}" for t in TYPES} <= ids, sorted(ids)
    assert set(meta(KIT)["transitions_defined"]) <= set(info.transitions), info.transitions


def test_fonts_and_licences_ship():
    m = meta(KIT)
    for f in m["fonts"]:
        assert (kit_dir(KIT) / f["src"]).is_file(), f["src"]
    for lic in m["licenses"]:
        assert "Open Font License" in (kit_dir(KIT) / lic).read_text(encoding="utf-8", errors="replace"), lic
    assert {"Bangers", "Comic Neue", "Space Mono"} <= {f["family"] for f in m["fonts"]}


def test_style_metadata_matches_assets():
    assert style_problems(KIT) == []


def test_theme_tokens_replace_the_starter():
    css = (kit_dir(KIT) / "theme.css").read_text(encoding="utf-8")
    for tok in ["--sr-stage", "--sr-fg", "--sr-accent", "--sr-accent-ink", "--sr-paper", "--sr-ink", "--sr-term",
                "--sr-scrim-rgb", "--sr-panel-edge", "--sr-panel-shadow"]:
        assert f"{tok}:" in css, tok
    assert "registerTheme('comic'" in code(kit_dir(KIT) / "kit.js")


def test_hard_shadows_only():
    """Comic ink never blurs: every box-shadow / drop-shadow / text-shadow has a 0 blur radius."""
    bad = []
    for p in sources(KIT):
        for m in re.finditer(r"(?:box-shadow|text-shadow|boxShadow|textShadow)\s*[:=]\s*([^;\n]+)", code(p)):
            for part in re.split(r",(?![^(]*\))", m.group(1)):
                bare = re.sub(r"#[0-9A-Fa-f]{3,8}|\w+\([^)]*\)|\$\{[^}]*\}", " ", part)
                nums = re.findall(r"(?<![\w.])(-?\d+(?:\.\d+)?)(?:px)?(?![\w.])", bare)
                if len(nums) >= 3 and "inset" not in part and float(nums[2]) != 0:
                    bad.append(f"{p.name}: {part.strip()[:60]}")
        if re.search(r"filter\s*:\s*[^;]*blur\(", code(p)):
            bad.append(f"{p.name}: blur filter")
    assert bad == []


def test_art_is_seeded():
    """Bursts, rays and splats take explicit seeds (deterministic shapes, no hidden randomness)."""
    src = "".join(code(p) for p in sources(KIT, (".js",)))
    assert "rng(" in code(kit_dir(KIT) / "lib" / "art.js")
    for call in re.findall(r"\bburst\(P\.doc,\s*\{[^}]*\}", src):
        assert "seed" in call, call


def test_quick_adapter_uses_the_kit():
    from showreel_core.film.quick import kit_meta, scene_id
    for t in TYPES:
        assert scene_id(KIT, t) == f"kit:{KIT}/{t}"
    km = kit_meta(KIT)
    assert km["transitions"]["push"][0] == "kit:comic/page-turn"
    assert km["transitions"]["wipe"][0] == "kit:comic/splat-iris"


@pytest.mark.slow
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_every_scene_renders_clean(tmp_path, aspect):
    r = dry_run(KIT, aspect, tmp_path)
    assert r.ready_error == "" and r.error is None, r.summary()
    assert r.scene_errors == [] and r.page_errors == [], r.summary()
    assert all(s.deterministic is not False for s in r.shots), r.summary()
    sfx = {c["sfx"] for c in r.cues}
    assert {"type", "pass", "hit", "click"} <= sfx, sfx
