"""Content box: the product inside a flat-margin capture gets the focus box (any model, engine-measured)."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.director import compose
from showreel_core.director.contentbox import content_box
from showreel_core.director.types import Brief, MediaAsset

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def _img(path: Path, box: tuple[int, int, int, int] | None, size=(1920, 1080), bg=(0, 0, 0)) -> str:
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    if box:
        d.rectangle(box, fill=(20, 200, 240))
        d.rectangle((box[0] + 40, box[1] + 40, box[0] + 200, box[1] + 90), fill=(255, 255, 255))
    else:
        for x in range(0, size[0], 97):
            d.rectangle((x, 0, x + 40, size[1]), fill=(200, 60, 60))
    im.save(path)
    return str(path)


def test_canvas_in_a_black_page_gets_a_box_and_a_full_page_none(tmp_path: Path) -> None:
    b = content_box(_img(tmp_path / "game.png", (560, 240, 1360, 840)))
    assert b is not None
    x, y, w, h = b
    assert 0.2 < x < 0.3 and 0.15 < y < 0.25 and 0.4 < w < 0.55 and 0.55 < h < 0.7
    assert content_box(_img(tmp_path / "page.png", None)) is None        # content to the edges: leave it
    assert content_box(str(tmp_path / "missing.png")) is None


def test_mood_film_focuses_the_game_canvas_and_uses_distinct_pictures(tmp_path: Path) -> None:
    desk = _img(tmp_path / "desktop_1920x1080.png", (560, 240, 1360, 840))
    d14 = _img(tmp_path / "desktop_1440x900.png", (380, 150, 1060, 750), size=(1440, 900))
    shot = _img(tmp_path / "e3_shot.png", None, size=(960, 700))
    assets = [MediaAsset("desktop_1920x1080", "image", desk, 1920, 1080, thumbnail=desk, frame="browser"),
              MediaAsset("desktop_1440x900", "image", d14, 1440, 900, thumbnail=d14, frame="browser"),
              MediaAsset("e3_shot", "image", shot, 960, 700, thumbnail=shot, frame="card")]
    b = Brief(direction="a noir detective trailer", assets=assets, seconds=30.0)
    bps = compose.blueprints()
    bp = next(x for x in bps if x.id == "screen-noir")
    film = compose.assemble(b, bp, compose.default_pick(bps, b))["film"]
    by = {s["id"]: s for s in film["shots"]}
    assert by["exhibit"]["params"]["bbox"][0] > 0.2                       # pushed onto the canvas
    assert by["feature1"]["params"]["image"]["asset"] == "e3_shot"        # the gameplay picture, not the page again
    assert by["feature1"]["params"]["image"]["frame"] == "card"


def test_feature_labels_describe_the_picture_under_them(tmp_path: Path) -> None:
    """Streaks: features 'Weekly completions' (no capture), 'Your habits' (a strip), 'New habit' (a button crop) -
    the film captioned the New habit button 'Weekly completions'. Labels now match their pictures."""
    def asset(name, w, h, frame):
        path = _img(tmp_path / f"{name}.png", None, size=(w, h))
        return MediaAsset(name, "image", path, w, h, thumbnail=path, frame=frame)
    from showreel_core.contracts import Product as ProductFacts
    assets = [asset("desktop_1920x1080", 1920, 1080, "browser"), asset("full_1440", 1440, 2400, "browser"),
              asset("element_02_your_habits_e", 1400, 120, "card"), asset("element_03_new_habit_ed5", 600, 300, "card"),
              asset("element_04_drink_water_0", 900, 400, "card")]
    b = Brief(direction="a nature documentary", assets=assets, seconds=30.0,
              product=ProductFacts(name="Streaks", features=["Weekly completions", "Your habits", "New habit"]))
    v = compose.facts(b)
    assert (v["feature1"], v["asset2"]) == ("New habit", "element_03_new_habit_ed5")
    assert (v["feature2"], v["asset3"]) == ("Drink water", "element_04_drink_water_0")
