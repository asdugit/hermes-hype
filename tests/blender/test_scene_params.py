"""Scene params from a Director film are coerced to the scene's PARAMS schema before the scene code sees them.

Regression: ``studio.shot`` passed values through untouched, so ``"fill": "0.7"`` (a number written as a string)
crashed device_hero (``fill * 0.74``: TypeError) and ``"device": "Laptop"`` crashed in ``SPECS[kind]`` (KeyError);
the Director then re-rendered the shot and finally swapped it for a browser stand-in.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "blender_kits"))
import kitcheck as kc  # noqa: E402

kc.lib_importable()
from blender_kits.lib import studio  # noqa: E402

HERO = kc.static_module(kc.KITS / "device" / "device_hero.py")["PARAMS"]


def test_numbers_as_strings_become_clamped_numbers():
    p = studio.coerce_params({"fill": "0.7", "orbit_deg": 500, "push": "-3", "screen_on": "nan"}, HERO)
    assert p["fill"] == 0.7 and isinstance(p["fill"], float)
    assert p["orbit_deg"] == HERO["orbit_deg"]["max"]
    assert p["push"] == HERO["push"]["min"]
    assert p["screen_on"] == HERO["screen_on"]["default"]          # NaN / junk -> default


def test_enums_and_bools():
    p = studio.coerce_params({"device": "Laptop", "env": "spaceship", "reveal": "false", "side": " RIGHT "}, HERO)
    assert p["device"] == "laptop" and p["env"] == HERO["env"]["default"] and p["reveal"] is False
    assert p["side"] == "right"
    assert studio.coerce_params({"reveal": "yes"}, HERO)["reveal"] is True


def test_valid_and_unknown_params_pass_through_unchanged():
    given = {"media": "m0_desktop_1920x1080", "side": "left", "space": "left", "reveal": False, "fill": 0.62,
             "product": "m0_desktop_1920x1080", "_alpha": True, "from_shot": "a"}
    p = studio.coerce_params(given, HERO)
    assert all(p[k] == v for k, v in given.items())
    assert p["orbit_deg"] == HERO["orbit_deg"]["default"]
