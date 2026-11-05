"""film.json schema: precise error paths, coverage/overlap rules, normalisation."""
from __future__ import annotations

import copy
from typing import Any

import pytest

from showreel_core.film.schema import (
    errors_of,
    normalize_film,
    scene_ids,
    validate_film,
)

BASE: dict[str, Any] = {
    "version": 1, "fps": 30, "size": [1920, 1080], "dur": 10.0, "seed": 3,
    "shots": [
        {"id": "a", "t0": 0, "t1": 5.2, "scene": "kit:pixel/walk", "res": [480, 270]},
        {"id": "b", "t0": 4.8, "t1": 10, "scene": "custom:field"},
    ],
    "transitions": [{"from": "a", "to": "b", "type": "crossfade", "t": 4.8, "dur": 0.4}],
}


def film(**changes: Any) -> dict[str, Any]:
    f = copy.deepcopy(BASE)
    f.update(changes)
    return f


def paths(issues) -> list[str]:
    return [i.path for i in errors_of(issues)]


def test_valid_film_has_no_errors():
    assert errors_of(validate_film(film())) == []


def test_sdk_example_shape_is_valid():
    f = film(dur=45.0, shots=[
        {"id": "walk", "t0": 0, "t1": 21.5, "scene": "kit:pixel/dungeon-walk", "res": [480, 270], "params": {"p": 1}, "z": 0},
        {"id": "field", "t0": 21.5, "t1": 45, "scene": "kit:nature/flower-field", "res": None},
    ], transitions=[{"from": "walk", "to": "field", "type": "kit:transitions/petal-bloom", "t": 21.0, "dur": 1.4}],
        overlays=[{"id": "title", "t0": 40, "t1": 45, "scene": "kit:type/title", "params": {"text": "RED CAR"}}],
        finish={"grain": 0.04, "vignette": 0.25, "bloom": 0.0}, cues=[{"t": 8.1, "sfx": "slash", "gain_db": 0}],
        music=[{"bed": "pixel_boss", "t0": 0, "t1": 22.5}, {"sting": "bloom_riser", "t": 21.2}],
        captions=[{"t0": 1.0, "t1": 3.2, "text": "Every hero has a boss."}], safe={"l": 96, "r": 96, "t": 64, "b": 120},
        fonts=[{"family": "Geist", "src": "kits/launch/fonts/Geist-Regular.woff2", "weight": 400}],
        assets={"car": {"type": "frames"}}, title="Red Car", background="#000")
    assert errors_of(validate_film(f)) == []


@pytest.mark.parametrize(("change", "path"), [
    ({"fps": 0}, "fps"),
    ({"size": [1921, 1080]}, "size"),
    ({"dur": -1}, "dur"),
    ({"version": 2}, "version"),
    ({"fonts": [{"family": "X", "src": "https://cdn.example/x.woff2"}]}, "fonts[0].src"),
    ({"fonts": [{"family": "X", "src": "../x.ttf"}]}, "fonts[0].src"),
    ({"finish": {"grain": 2}}, "finish.grain"),
    ({"cues": [{"t": 99, "sfx": "hit"}]}, "cues[0].t"),
    ({"cues": [{"t": 1, "sfx": "hit", "align": "middle"}]}, "cues[0].align"),
    ({"caption_style": {"size": 30}}, "caption_style.size"),
    ({"safe": {"l": 1000, "r": 1000}}, "safe"),
    ({"assets": {"Car!": {"type": "image"}}}, "assets.Car!"),
    ({"music": [{"t": 1}]}, "music[0]"),
])
def test_field_errors_have_precise_paths(change, path):
    assert path in paths(validate_film(film(**change)))


def test_shot_errors():
    f = film()
    f["shots"][1]["scene"] = "field"
    f["shots"][0]["t1"] = 0
    f["shots"][0]["res"] = [480]
    p = paths(validate_film(f))
    assert "shots[1].scene" in p and "shots[0].t1" in p and "shots[0].res" in p


def test_duplicate_ids_and_past_end():
    f = film()
    f["shots"][1]["id"] = "a"
    f["shots"][1]["t1"] = 11
    p = paths(validate_film(f))
    assert "shots[1].id" in p and "shots[1].t1" in p


def test_gap_is_an_error():
    f = film(transitions=[])
    f["shots"][1]["t0"] = 6.0
    msgs = [str(i) for i in errors_of(validate_film(f))]
    assert any("no shot covers 5.200-6.000" in m for m in msgs)


def test_tail_gap_is_an_error():
    f = film()
    f["shots"][1]["t1"] = 9.0
    assert any("no shot covers 9.000-10.000" in str(i) for i in validate_film(f))


def test_overlap_outside_transition_is_an_error():
    f = film(transitions=[])
    assert "shots[1]" in paths(validate_film(f))


def test_overlap_inside_transition_is_fine():
    assert "shots[1]" not in paths(validate_film(film()))


def test_transition_references_and_window():
    f = film(transitions=[{"from": "a", "to": "zz", "type": "crossfade", "t": 4.8, "dur": 0.4},
                          {"from": "a", "to": "b", "type": "sparkle", "t": 4.8, "dur": 0.4},
                          {"from": "a", "to": "b", "type": "crossfade", "t": 1.0, "dur": 0.4}])
    p = paths(validate_film(f))
    assert "transitions[0].to" in p and "transitions[1].type" in p and "transitions[2]" in p


def test_known_scene_sets_turn_unknowns_into_errors():
    issues = validate_film(film(), known_scenes={"kit:pixel/walk"})
    assert paths(issues) == ["shots[1].scene"]


def test_unknown_keys_are_warnings_not_errors():
    f = film(style="pixel")
    f["shots"][0]["colour"] = "red"
    issues = validate_film(f)
    assert errors_of(issues) == []
    assert {i.path for i in issues if i.severity == "warning"} >= {"style", "shots[0].colour"}


def test_captions_overlap_and_reading_speed():
    f = film(captions=[{"t0": 0, "t1": 2, "text": "one two"},
                       {"t0": 1.5, "t1": 1.8, "text": "far too many words for this tiny window"}])
    issues = validate_film(f)
    assert "captions[1].t0" in paths(issues)
    assert any(i.severity == "warning" and i.path == "captions[1]" for i in issues)


def test_not_an_object():
    assert paths(validate_film([])) == [""]


def test_normalize_fills_defaults():
    n = normalize_film({"dur": 3, "shots": [{"id": "a", "t0": 0, "t1": 3, "scene": "kit:x/y"}],
                        "transitions": [{"from": "a", "to": "a"}]})
    assert n["fps"] == 30 and n["size"] == [1920, 1080] and n["overlays"] == []
    assert n["shots"][0]["res"] is None and n["shots"][0]["params"] == {}
    assert n["transitions"][0]["type"] == "cut" and n["transitions"][0]["dur"] == 0


def test_scene_ids_includes_custom_transitions():
    f = film(transitions=[{"from": "a", "to": "b", "type": "kit:transitions/petal-bloom", "t": 4.8, "dur": 0.4}])
    assert scene_ids(f) == {"kit:pixel/walk", "custom:field", "kit:transitions/petal-bloom"}
