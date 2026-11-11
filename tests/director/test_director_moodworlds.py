"""Mood-owned screen worlds: a noir / keynote / documentary ask on a web app gets its own film, for any model."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.director import compose, moods, tiers
from showreel_core.director.catalog import build_catalog

T = pytest.importorskip("test_director_audit")

ASKS = {"a noir detective trailer": "screen-noir", "make it feel like an Apple keynote": "screen-keynote",
        "a nature documentary narrated by a hushed voice": "screen-documentary"}


@pytest.mark.parametrize("direction,bp_id", list(ASKS.items()))
def test_engine_default_and_model_pick_land_on_the_moods_world(tmp_path: Path, direction: str, bp_id: str) -> None:
    b = T._screen_brief(tmp_path, direction)
    bps = compose.blueprints()
    assert compose.default_pick(bps, b)["blueprint"] == bp_id
    # a weak model that picks the generic launch film is overruled by the mood
    pick, fixes = compose.check_pick({"blueprint": "screen-launch", "time": "night", "voice": "none",
                                      "tagline": "x", "cta": "Try it"}, bps, b)
    assert pick["blueprint"] == bp_id and any("world" in f for f in fixes)
    bp = next(x for x in bps if x.id == bp_id)
    shots = compose._layout_shots(bp, 30.0, b)
    prod = sum(s["t1"] - s["t0"] for s in shots if s["product"])
    assert prod / 30.0 >= 0.6                                  # the engine's product-share bar
    assert all(not s["scene"].startswith(("kit:launch/", "kit:cinematic/")) for s in shots)


def test_a_pick_inside_the_moods_own_list_is_kept(tmp_path: Path) -> None:
    b = T._screen_brief(tmp_path, "a noir detective trailer")
    pick, _ = compose.check_pick({"blueprint": "screen-cinematic", "voice": "none", "tagline": "x", "cta": "y",
                                  "time": "night"}, compose.blueprints(), b)
    assert pick["blueprint"] == "screen-cinematic"


def test_no_mood_keeps_the_models_choice(tmp_path: Path) -> None:
    b = T._screen_brief(tmp_path, "make it pink and playful")
    pick, _ = compose.check_pick({"blueprint": "screen-comic", "voice": "none", "tagline": "x", "cta": "y",
                                  "time": "golden"}, compose.blueprints(), b)
    assert pick["blueprint"] == "screen-comic"
    assert moods.preferred("make it pink and playful", {"screen-noir"}) == ""


def test_default_pick_never_falls_back_onto_a_forbidden_world(tmp_path: Path) -> None:
    # documentary forbids kit:launch; with no keyword winner the house default used to be screen-launch
    b = T._screen_brief(tmp_path, "hushed wildlife")
    bps = [x for x in compose.blueprints() if x.id != "screen-documentary"]
    pick = compose.default_pick(bps, b)
    bp = next(x for x in bps if x.id == pick["blueprint"])
    assert not any(s["scene"].startswith("kit:launch/") for s in bp.shots)


@pytest.mark.parametrize("direction", list(ASKS))
def test_mood_films_validate_and_render_through_the_engine(tmp_path: Path, direction: str) -> None:
    from director_fakes import FakeLlm

    from showreel_core.director.engine import run
    b = T._screen_brief(tmp_path, direction)
    cat = build_catalog(assets=b.assets, capabilities=b.capabilities)
    llm = FakeLlm({"pick": [{"blueprint": "screen-launch", "voice": "none"}],
                   "words": [{"text": {"open.text": "Nobody clocks out clean.", "case.title": "EXHIBIT A"}}]})
    res = run(b, llm=llm, renderer=T.FakeRenderer(), effort="quick", budget=T.FREE_QUICK, job_dir=tmp_path / "job",
              library_dir=tmp_path / "lib", catalog=cat, tier=tiers.detect("deepseek-v4.1-flash"))
    assert res.ok, res.error
    scenes = [s["scene"] for s in res.film["shots"]]
    assert "kit:base/SCREEN" in scenes and scenes[-1] == "kit:type/end-lockup"
    if "noir" in direction:
        g = res.film["render"]["post_params"]["grade"]
        assert g["mono"] == 1.0
        assert all((s.get("params") or {}).get("theme") == "noir" for s in res.film["shots"])


def test_pictures_are_cards_and_web_pages_keep_the_browser_frame(tmp_path: Path) -> None:
    from showreel_core.director.media import frame_of
    assert frame_of("product_capture", {}, "x/desktop_1920x1080.png") == "browser"
    assert frame_of("product_capture", {}, "x/element_01_timer.png") == "card"
    assert frame_of("screenshot", {}, "x/shot.png") == "card"
    assert frame_of("artifact", {"image": {"frame": "browser"}}, "x/page.png") == "browser"
    b = T._screen_brief(tmp_path, "a noir detective trailer")
    for a in b.assets[1:]:
        a.frame = "card"
    bps = compose.blueprints()
    bp = next(x for x in bps if x.id == "screen-noir")
    film = compose.assemble(b, bp, compose.default_pick(bps, b))["film"]
    imgs = {s["id"]: s["params"].get("image") for s in film["shots"] if s["params"].get("image")}
    assert imgs["feature1"]["frame"] == "card" and imgs["feature2"]["frame"] == "card"
