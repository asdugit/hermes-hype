"""FAILURES #31: a Directed game film died after 32 min (`page_broken`) because the model passed a media record
(``{"asset": "desktop_1920x1080"}``) as the ``image`` of ``kit:pixel/FEATURE``, which takes an asset NAME; the
runtime printed it as ``'[object Object]'`` and the strict final page refused to load. Two layers, synthetic data:

1. root cause: params a kit types 'asset'/'media' are normalised to the asset name before the page build;
2. resilience: a kit shot whose setup() still throws becomes a stand-in card (or is dropped), never a failed job.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from showreel_core.director import engine, repair
from showreel_core.director.backend import Preview, ShotError
from showreel_core.director.catalog import build_catalog
from showreel_core.film import standin

ASSETS = ["desktop_1920x1080", "desktop_1440x900", "mobile_390x844", "e15_shot"]


def _film(*shots: dict[str, Any]) -> dict[str, Any]:
    return {"film": {"shots": list(shots), "transitions": []}, "plan": {}}


def test_catalog_knows_which_kit_params_take_an_asset_name() -> None:
    cat = build_catalog()
    assert "image" in cat.asset_params("kit:pixel/FEATURE")          # pixel: image = asset name
    assert "boss_media" in cat.asset_params("kit:pixel/boss-battle")
    assert "image" not in cat.asset_params("kit:base/SCREEN")          # base/cinematic: image = media record
    assert "image" not in cat.asset_params("kit:cinematic/SCREEN")
    assert cat.asset_params("kit:nope/x") == [] and cat.asset_params("custom:cabinet") == []


def test_a_media_record_in_an_asset_name_param_becomes_the_name() -> None:
    cat = build_catalog()
    obj = _film(
        {"id": "feat-paddle", "t0": 8, "t1": 14, "scene": "kit:pixel/FEATURE",
         "params": {"image": {"asset": "desktop_1920x1080"}, "feature": "WIDE PADDLE"}},
        {"id": "feat-ball", "t0": 14, "t1": 20, "scene": "kit:pixel/FEATURE",
         "params": {"image": {"asset": "e15_shot", "frame": "card"}}},
        {"id": "path", "t0": 20, "t1": 24, "scene": "kit:pixel/SCREEN",
         "params": {"image": {"path": "assets/e15_shot/image.jpg", "id": "e15_shot"}}},
        {"id": "boss", "t0": 24, "t1": 30, "scene": "kit:pixel/boss-battle",
         "params": {"boss_media": {"name": "desktop_1440x90"}}},             # misspelt inside the record
        {"id": "real-a", "t0": 30, "t1": 35, "scene": "kit:cinematic/SCREEN",
         "params": {"image": {"asset": "desktop_1920x1080"}}},
    )
    fixes = repair.snap_film_ids(obj, cat, ASSETS)
    p = {s["id"]: s["params"] for s in obj["film"]["shots"]}
    assert p["feat-paddle"]["image"] == "desktop_1920x1080" and p["feat-paddle"]["feature"] == "WIDE PADDLE"
    assert p["feat-ball"]["image"] == "e15_shot"
    assert p["path"]["image"] == "e15_shot"
    assert p["boss"]["boss_media"] == "desktop_1440x900"
    assert p["real-a"]["image"] == {"asset": "desktop_1920x1080"}       # the cinematic kit takes the record
    assert sum("takes an asset name" in f for f in fixes) == 4


def test_a_record_that_names_no_asset_is_dropped_not_stringified() -> None:
    cat = build_catalog()
    obj = _film({"id": "f", "t0": 0, "t1": 5, "scene": "kit:pixel/FEATURE",
                 "params": {"image": {"frame": "card", "w": 1920}, "feature": "X"}})
    obj["film"]["overlays"] = [{"id": "o", "t0": 0, "t1": 5, "scene": "kit:pixel/HOOK",
                                "params": {"media": {"asset": "zzzz-unknown"}}}]
    fixes = repair.snap_film_ids(obj, cat, ASSETS)
    assert "image" not in obj["film"]["shots"][0]["params"]
    assert "media" not in obj["film"]["overlays"][0]["params"]
    assert any("named no asset" in f for f in fixes)
    assert "[object Object]" not in repr(obj)


def test_asset_name_params_snaps_to_the_jobs_assets_or_keeps_the_name_without_any() -> None:
    p = {"image": {"asset": "e15_shot"}, "media": "desktop_1920x1080"}
    assert repair.asset_name_params(p, ["image", "media"], set(ASSETS), "s")
    assert p == {"image": "e15_shot", "media": "desktop_1920x1080"}          # strings are left for the snapper
    q = {"image": {"asset": "logo"}}
    repair.asset_name_params(q, ["image"], [], "s")                         # no asset list: trust the record
    assert q == {"image": "logo"}


# ------------------------------------------------------------------------------------ stand-ins (pure)

def test_broken_item_reads_the_strict_page_error() -> None:
    msg = ("the film page failed to load: page script failed: Error: shot 'feat-paddle' (kit:pixel/FEATURE): "
           "setup() threw: param 'image' names asset 'x', which is not in assets/manifest.json (have: a)")
    kind, sid, scene, why = standin.broken_item(msg)
    assert (kind, sid, scene) == ("shot", "feat-paddle", "kit:pixel/FEATURE") and why.startswith("setup() threw")
    assert standin.broken_item("ReferenceError: __sr is not defined") is None
    assert standin.broken_item("overlay 'badge' (kit:type/lower): setup() threw: nope")[:2] == ("overlay", "badge")


def test_stand_in_is_the_product_card_else_a_title_card_else_none() -> None:
    shot = {"id": "feat-ball", "t0": 14, "t1": 20, "scene": "kit:pixel/FEATURE", "res": [1920, 1080],
            "params": {"image": {"asset": "e15_shot"}, "feature": "MULTI-BALL"}}
    card = standin.stand_in(shot, pictures=ASSETS, kits={"base", "pixel"}, title="Brickfall")
    assert card == {"id": "feat-ball", "t0": 14, "t1": 20, "scene": "kit:base/SCREEN",
                    "params": {"image": {"asset": "e15_shot", "frame": "card"}, "bbox": standin.WHOLE_BBOX}}
    other = standin.stand_in({**shot, "params": {"image": "gone"}}, pictures=ASSETS, kits={"base"}, title="")
    assert other["params"]["image"]["asset"] == "desktop_1920x1080"         # the film's first picture
    themed = standin.stand_in({**shot, "scene": "kit:comic/FEATURE"}, pictures=ASSETS, kits={"base"}, title="")
    assert themed["params"]["theme"] == "comic"
    typed = standin.stand_in(shot, pictures=[], kits={"base", "type"}, title="Brickfall")
    assert typed["scene"] == "kit:type/title" and typed["params"] == {"text": "Brickfall"}
    assert standin.stand_in(shot, pictures=ASSETS, kits={"pixel"}, title="Brickfall") is None
    assert shot["scene"] == "kit:pixel/FEATURE"                              # the input is not touched


def test_drop_shot_lets_the_neighbour_hold_and_rejoins_transitions() -> None:
    film = {"shots": [{"id": "a", "t0": 0, "t1": 5}, {"id": "b", "t0": 5, "t1": 9}, {"id": "c", "t0": 9, "t1": 12}],
            "transitions": [{"from": "a", "to": "b", "type": "crossfade", "t": 4.8, "dur": 0.4},
                            {"from": "b", "to": "c", "type": "wipe", "t": 8.8, "dur": 0.4}]}
    assert standin.drop_shot(film, "b")
    assert [(s["id"], s["t0"], s["t1"]) for s in film["shots"]] == [("a", 0, 9.0), ("c", 9, 12)]
    assert film["transitions"] == [{"from": "a", "to": "c", "type": "wipe", "t": 8.8, "dur": 0.4}]
    assert standin.drop_shot(film, "a") and film["shots"] == [{"id": "c", "t0": 0, "t1": 12}]
    assert film["transitions"] == []
    assert not standin.drop_shot(film, "c")                                  # never an empty film


# ------------------------------------------------------------------------------------ the Director's dry run

def _run(product: set[str]) -> Any:
    warned: list[str] = []
    cat = build_catalog()
    r = SimpleNamespace(product=product, catalog=cat, brief=SimpleNamespace(product=SimpleNamespace(name="Brickfall")),
                        warn=lambda step, msg: warned.append(msg))
    return r, warned


def _version(shots: list[dict[str, Any]]) -> Any:
    film = {"title": "BRICKFALL", "shots": shots, "transitions": [],
            "assets": {n: {"type": "image"} for n in ASSETS}}
    return SimpleNamespace(film=film, fallbacks={})


def test_dry_run_swaps_a_kit_shot_whose_setup_throws_for_the_product_card() -> None:
    r, warned = _run({"desktop_1920x1080", "e15_shot"})
    v = _version([{"id": "ignite", "t0": 0, "t1": 8, "scene": "custom:cabinet", "params": {}},
                  {"id": "feat-paddle", "t0": 8, "t1": 14, "scene": "kit:pixel/FEATURE",
                   "params": {"image": "nope", "feature": "WIDE PADDLE"}},
                  {"id": "end", "t0": 14, "t1": 20, "scene": "kit:cinematic/SCREEN", "params": {}}])
    pv = Preview(ok=True, errors=[
        ShotError("feat-paddle", 0.04, "shot feat-paddle: setup(): param 'image' names asset 'nope', which is not in "
                                       "assets/manifest.json"),
        ShotError("end", 3.0, "shot end t=17: a render() glitch")])          # render-time: not a setup failure
    assert engine._stand_in_kit_shots(r, v, pv)
    s = {x["id"]: x for x in v.film["shots"]}
    assert s["feat-paddle"]["scene"] == "kit:base/SCREEN"
    assert s["feat-paddle"]["params"]["image"] == {"asset": "desktop_1920x1080", "frame": "card"}
    assert s["end"]["scene"] == "kit:cinematic/SCREEN" and s["ignite"]["scene"] == "custom:cabinet"
    assert v.fallbacks == {"kit-shot:feat-paddle": "kit:base/SCREEN"} and "stand-in kit:base/SCREEN" in warned[0]
    # the stand-in throws too (second pass): the shot is left out, its neighbour holds
    pv2 = Preview(ok=True, errors=[ShotError("feat-paddle", 0.0, "shot feat-paddle: setup(): boom")])
    assert engine._stand_in_kit_shots(r, v, pv2)
    assert [x["id"] for x in v.film["shots"]] == ["ignite", "end"] and v.film["shots"][0]["t1"] == 14
    assert "left out" in warned[-1]


def test_dry_run_leaves_custom_scene_errors_and_clean_runs_alone() -> None:
    r, _ = _run({"desktop_1920x1080"})
    v = _version([{"id": "ignite", "t0": 0, "t1": 8, "scene": "custom:cabinet", "params": {}}])
    assert not engine._stand_in_kit_shots(r, v, Preview(ok=True))
    assert not engine._stand_in_kit_shots(r, v, Preview(ok=True, errors=[
        ShotError("ignite", 0.0, "shot ignite: setup(): custom code broke")]))  # custom scenes get code repairs
    assert v.film["shots"][0]["scene"] == "custom:cabinet"
