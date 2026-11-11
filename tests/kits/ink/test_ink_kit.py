"""kits/ink: lint, purity, imports, catalog coverage, fonts + licences, style metadata (beds, SFX roles, post,
voice_speed 1.0), the Quick adapter mapping, ink-specific invariants (seeded Rough.js only, flat shadows, bool params
default to null, vendored Rough.js licence), and an opt-in runtime render of all 15 types in both aspects with the
kit's transitions and a determinism probe (``pytest --runslow``)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "terminal"))
from stylekit import (  # noqa: E402
    KITS, TYPES, code, dry_run, forbidden_hits, kit_dir, meta, registered_ids, sources, style_problems)

KIT = "ink"


def import_problems(kit: str) -> list[str]:
    """Every import is a relative path that resolves inside this kit or inside a kit listed in kit.json requires."""
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
    files = sources(KIT, (".js", ".mjs", ".css", ".json", ".md")) + sorted((kit_dir(KIT) / "fonts").glob("*.txt"))
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
    assert (kit_dir(KIT) / "RECIPES.md").is_file() and (kit_dir(KIT) / "CRITIQUE.md").is_file()


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
        text = (kit_dir(KIT) / lic).read_text(encoding="utf-8", errors="replace")
        assert "Open Font License" in text or "MIT" in text, lic
    assert {"Fraunces", "Inter", "Caveat", "JetBrains Mono"} <= {f["family"] for f in m["fonts"]}


def test_vendored_rough_is_licensed_and_only_used_through_the_seeded_helper():
    vend = kit_dir(KIT) / "vendor"
    assert "MIT" in (vend / "LICENSE-roughjs.txt").read_text(encoding="utf-8")
    assert "4.6.6" in (vend / "rough.mjs").read_text(encoding="utf-8")[:400]
    users = [p.name for p in sources(KIT, (".js",)) if "rough.mjs" in p.read_text(encoding="utf-8")]
    assert users == ["ink.js"], users
    ink = code(kit_dir(KIT) / "lib" / "ink.js")
    assert "seed: seedOf(key)" in ink
    shapes = re.findall(r"GEN\.(?!toPaths)\w+\(", ink)
    seeded = re.findall(r"GEN\.(?!toPaths)\w+\([^;]*?\bopt\)", ink)
    assert shapes and len(seeded) == len(shapes), (shapes, seeded)


def test_style_metadata_matches_assets():
    assert style_problems(KIT) == []


def test_theme_tokens_replace_the_starter():
    css = (kit_dir(KIT) / "theme.css").read_text(encoding="utf-8")
    for tok in ["--sr-stage", "--sr-fg", "--sr-accent", "--sr-accent-ink", "--sr-paper", "--sr-ink", "--sr-term",
                "--sr-scrim-rgb", "--sr-panel-edge", "--sr-panel-shadow"]:
        assert f"{tok}:" in css, tok
    assert "registerTheme('ink'" in code(kit_dir(KIT) / "kit.js")
    assert re.search(r"\bfont\s*:", code(kit_dir(KIT) / "theme.css")) is None, "use longhand font properties"


def test_flat_shadows_only():
    """Ink shadows are flat offset shapes: no blurred box/text shadows and no blur filters."""
    bad = []
    for p in sources(KIT):
        c = code(p)
        for m in re.finditer(r"(?:box-shadow|text-shadow|boxShadow|textShadow)\s*[:=]\s*([^;\n]+)", c):
            for part in re.split(r",(?![^(]*\))", m.group(1)):
                bare = re.sub(r"#[0-9A-Fa-f]{3,8}|\w+\([^)]*\)|\$\{[^}]*\}", " ", part)
                nums = re.findall(r"(?<![\w.])(-?\d+(?:\.\d+)?)(?:px)?(?![\w.])", bare)
                if len(nums) >= 3 and "inset" not in part and float(nums[2]) != 0:
                    bad.append(f"{p.name}: {part.strip()[:60]}")
        if re.search(r"blur\(", c):
            bad.append(f"{p.name}: blur")
    assert bad == []


def test_optional_bools_default_to_null():
    """A false default masks the scene default once kits/base applies param defaults (hermes-auteur pitfall)."""
    hits = []
    for p in sources(KIT, (".js",)):
        hits += [f"{p.name}: {m}" for m in re.findall(r"type:\s*'bool',\s*default:\s*false", code(p))]
    assert hits == []


def test_quick_adapter_uses_the_kit():
    from showreel_core.film.quick import kit_meta, scene_id
    for t in TYPES:
        assert scene_id(KIT, t) == f"kit:{KIT}/{t}"
    km = kit_meta(KIT)
    assert km["transitions"]["push"][0] == "kit:ink/paper-slide"
    assert km["transitions"]["wipe"][0] == "kit:ink/ink-bleed"


@pytest.mark.slow
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_every_scene_renders_clean(tmp_path, aspect):
    r = dry_run(KIT, aspect, tmp_path)
    assert r.ready_error == "" and r.error is None, r.summary()
    assert r.scene_errors == [] and r.page_errors == [], r.summary()
    assert all(s.deterministic is not False for s in r.shots), r.summary()
    sfx = {c["sfx"] for c in r.cues}
    assert {"type", "pass", "hit", "click"} <= sfx, sfx
