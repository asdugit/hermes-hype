"""Options/settings normalisation, style discovery and per-style narration pace."""
from __future__ import annotations

import json
from pathlib import Path

from showreel_core.config import (
    STYLE_VOICE_SPEED,
    Options,
    Settings,
    clamp_seconds,
    discover_styles,
    load_settings,
    norm_aspects,
    norm_mode,
    norm_speed,
    voice_speed,
)


def test_normalisation() -> None:
    o = Options(mode="lore", style=" Pixel ", seconds="500", aspects="both", effort="ultra", workers="99",
                voice_speed="9").normalised()
    assert (o.mode, o.style, o.seconds, o.aspects, o.effort, o.workers, o.voice_speed) == \
        ("making_of", "pixel", 180, ["16:9", "9:16"], "standard", 8, 4.0)
    assert clamp_seconds("x") == 60 and clamp_seconds(3) == 15
    assert norm_mode("any%") == "speedrun" and norm_mode("nonsense") == "product"
    assert norm_aspects(["9:16", "vertical", "16:9"]) == ["9:16", "16:9"] and norm_aspects(None) == ["16:9"]
    assert norm_speed("") is None and norm_speed(None) is None and norm_speed(True) is None
    assert norm_speed("1.13") == 1.13 and norm_speed(0.1) == 0.25 and norm_speed(-1) is None


def test_round_trip() -> None:
    o = Options(style="terminal", seconds=45, direction="make it moody", brief={"name": "X"}, voice_speed=1.2)
    assert Options.from_dict(o.to_dict()) == o.normalised()
    assert Options.from_dict({"unknown": 1, "seconds": 30}).seconds == 30


def test_settings_from_config() -> None:
    cfg = {"default_style": "pixel", "default_seconds": "90", "aspect": "both", "narration": "false",
           "redact": True, "effort": "max", "max_parallel_workers": 2, "narration_speed": ""}
    s = load_settings(lambda k, d: cfg.get(k, d))
    assert s == Settings("pixel", 90, "both", False, True, "max", 2, None)
    o = s.options()
    assert (o.style, o.seconds, o.aspects, o.voice, o.effort, o.workers, o.voice_speed) == \
        ("pixel", 90, ["16:9", "9:16"], False, "max", 2, None)
    s2 = load_settings(lambda k, d: {"narration_speed": 1.1}.get(k, d))
    assert s2.narration_speed == 1.1 and s2.options().voice_speed == 1.1


def test_settings_survive_a_broken_getter() -> None:
    def broken(key: str, default: object) -> object:
        raise RuntimeError("config unreadable")
    assert load_settings(broken) == Settings()
    assert load_settings(lambda k, d: {"default_seconds": "lots"}.get(k, d)).default_seconds == 60


def test_builtin_styles_always_known(tmp_path: Path) -> None:
    styles = discover_styles(tmp_path)
    assert set(styles) >= {"launch", "pixel", "terminal", "blueprint", "cinematic"}
    assert not any(s.ready for s in styles.values())


def test_kit_and_style_pack_discovery(tmp_path: Path) -> None:
    (tmp_path / "kits" / "pixel").mkdir(parents=True)
    (tmp_path / "kits" / "pixel" / "kit.json").write_text(json.dumps(
        {"style": {"id": "pixel", "name": "Pixel", "blurb": "16-bit", "voice_speed": 1.05}}), encoding="utf-8")
    (tmp_path / "kits" / "pixel" / "preview.webp").write_bytes(b"RIFF")
    (tmp_path / "kits" / "nature").mkdir(parents=True)
    (tmp_path / "kits" / "nature" / "kit.json").write_text(json.dumps({"styles": ["anime"]}), encoding="utf-8")
    (tmp_path / "styles" / "ink").mkdir(parents=True)
    (tmp_path / "styles" / "ink" / "style.json").write_text(json.dumps({"id": "ink", "voice": {"speed": 0.95}}),
                                                            encoding="utf-8")
    styles = discover_styles(tmp_path)
    assert styles["pixel"].ready and styles["pixel"].source == "kit:pixel" and styles["pixel"].preview
    assert styles["anime"].ready and styles["ink"].ready and not styles["launch"].ready
    assert styles["pixel"].voice_speed == 1.05 and styles["ink"].voice_speed == 0.95


def test_voice_speed_per_style_and_override(tmp_path: Path) -> None:
    assert STYLE_VOICE_SPEED == {"cinematic": 1.13}          # locked by the user's ear test
    assert voice_speed("cinematic", root=tmp_path) == 1.13
    assert voice_speed("launch", root=tmp_path) == 1.0
    assert voice_speed("unknown-style", root=tmp_path) == 1.0
    assert voice_speed("cinematic", 0.9, root=tmp_path) == 0.9
    assert voice_speed("cinematic", "", root=tmp_path) == 1.13
