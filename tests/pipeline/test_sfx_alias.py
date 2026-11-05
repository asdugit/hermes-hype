"""Story cue names are mapped to SFX kit roles at the integration point (real kit, no ffmpeg needed)."""
from __future__ import annotations

from showreel_core.pipeline import SFX_ALIASES, _d_place_sfx
from showreel_core.story.timing import solve_timeline  # noqa: F401 - the module that emits these names


def test_story_cue_names_all_resolve() -> None:
    cues = [{"t": 1.0 + i, "sfx": n, "gain_db": -8.0, "align": "auto"}
            for i, n in enumerate(["whoosh", "type", "pass", "riser", "hit", "tick", "click", "split"])]
    for style in ("launch", "pixel", "terminal", "blueprint", "cinematic"):
        placed, warnings = _d_place_sfx(cues, 20.0, style, 30)
        assert not [w for w in warnings if "unknown sfx" in w], (style, warnings)
        assert len(placed) == len(cues)
    assert set(SFX_ALIASES) == {"whoosh", "tick", "split"}
