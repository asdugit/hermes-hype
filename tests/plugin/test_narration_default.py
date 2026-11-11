"""Films are music-only by default; narration is opt-in (setting, knob, flag, words in a direction, the tool)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from showreel_core.commands import describe, narration_requested, parse
from showreel_core.config import Options, Settings, load_settings

STYLES = ["launch", "pixel", "comic"]


def test_defaults_are_music_only() -> None:
    assert Options().voice is False
    assert Settings().narration is False
    assert Settings().options().voice is False
    assert load_settings(lambda key, default=None: default).options().voice is False
    assert parse("", styles=STYLES).options.voice is False
    assert parse("launch 30", styles=STYLES).options.voice is False
    assert describe(Options()).endswith("music only")


def test_plugin_yaml_default_is_off() -> None:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "plugin.yaml").read_text(encoding="utf-8")
    block = text.split("  narration:\n", 1)[1].split("\n  narration_speed:", 1)[0]
    assert "default: false" in block


@pytest.mark.parametrize("raw", ["launch narrated", "narrated", "--narrate", "pixel 30 voice", "launch narration",
                                 "comic with narration", "launch 60 with a narrator", "launch with voiceover"])
def test_narration_on_request(raw: str) -> None:
    o = parse(raw, styles=STYLES).options
    assert o.voice is True, raw
    assert not o.directed, raw                        # an option, not a direction


@pytest.mark.parametrize("text,want", [
    ("a slow noir teaser with narration over the city", True),
    ("make it narrated, like a nature documentary", True),
    ("a fast vhs edit, no narration", False),
    ("calm keynote without a voiceover", False),
    ("a fast vhs edit about the narrator's game", None),
    ("pink and playful", None),
])
def test_direction_words(text: str, want: bool | None) -> None:
    assert narration_requested(text) is want


def test_directed_film_picks_narration_from_its_text() -> None:
    o = parse("a slow noir teaser with narration over the rainy city", styles=STYLES).options
    assert o.directed and o.voice is True
    o = parse("a slow noir teaser over the rainy city", styles=STYLES).options
    assert o.directed and o.voice is False


def test_setting_on_still_narrates_and_mute_wins() -> None:
    base = Settings(narration=True).options()
    assert parse("launch", styles=STYLES, base=base).options.voice is True
    assert parse("launch mute", styles=STYLES, base=base).options.voice is False


def test_cli_narrate_flag() -> None:
    import argparse

    from showreel_core.handlers import cli_setup
    p = argparse.ArgumentParser()
    cli_setup(p)
    a = p.parse_args(["render", "--session", "x", "--narrate"])
    assert a.narrate is True and a.no_voice is False
    a = p.parse_args(["render", "--session", "x"])
    assert a.narrate is False
