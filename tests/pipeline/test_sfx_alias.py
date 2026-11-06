"""Story cue names are SFX kit roles, resolved to a sound per style at the integration point (real kit, no ffmpeg)."""
from __future__ import annotations

import re
from pathlib import Path

from showreel_core.audio.sfx import load_kit
from showreel_core.pipeline import SFX_ALIASES, _d_place_sfx, sfx_for_style

ROOT = Path(__file__).resolve().parents[2]
STYLES = ("launch", "pixel", "terminal", "blueprint", "cinematic", "comic", "ink")


def _timing_names() -> set[str]:
    src = (ROOT / "showreel_core" / "story" / "timing.py").read_text(encoding="utf-8")
    return set(re.findall(r'Cue\([^,]+,\s*"([a-z_]+)"', src))


def test_timing_emits_only_role_names() -> None:
    kit = load_kit()
    assert kit is not None
    names = _timing_names()
    assert names and names <= set(kit.styles["launch"]), names - set(kit.styles["launch"])


def test_story_cue_names_all_resolve_in_every_style() -> None:
    names = sorted(_timing_names() | set(SFX_ALIASES))
    cues = [{"t": 1.0 + i, "sfx": n, "gain_db": -8.0, "align": "auto"} for i, n in enumerate(names)]
    for style in STYLES:
        placed, warnings = _d_place_sfx(cues, 40.0, style, 30)
        assert not [w for w in warnings if "unknown" in w], (style, warnings)
        assert len(placed) == len(cues), (style, warnings)


def test_style_roles_win_over_same_named_sounds() -> None:
    kit = load_kit()
    sounds = set(kit.sounds)
    assert sfx_for_style("hit", "pixel", kit.styles, sounds) == kit.styles["pixel"]["hit"]
    assert sfx_for_style("click", "pixel", kit.styles, sounds) == kit.styles["pixel"]["click"]
    assert sfx_for_style("build", "blueprint", kit.styles, sounds) == kit.styles["blueprint"]["build"]
    assert sfx_for_style("whoosh", "terminal", kit.styles, sounds) == kit.styles["terminal"]["cut"]   # legacy
    assert sfx_for_style("chime", "pixel", kit.styles, sounds) == "chime"                            # a sound
    assert sfx_for_style("cut", "comic", kit.styles, sounds) == kit.styles["launch"]["cut"]          # no map yet
