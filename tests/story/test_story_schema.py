"""Storyboard JSON schema, the hand-written validator and JSON conversions."""
import copy
import json

import pytest

from showreel_core.contracts import SceneType
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.options import StoryOptions
from showreel_core.story.schema import (STORYBOARD_SCHEMA, parse_json_text, storyboard_from_json, storyboard_to_json,
                                        transport_schema, validate_schema)


@pytest.fixture
def valid(coding):
    events, stats = coding
    return storyboard_to_json(build_heuristic_storyboard(events, stats, StoryOptions(seconds=60)))


def paths(obj):
    return {e.path: e.message for e in validate_schema(obj)}


def test_valid_storyboard_passes(valid):
    assert validate_schema(valid) == []


def test_missing_and_extra_top_level_fields(valid):
    bad = copy.deepcopy(valid)
    del bad["title"]
    bad["bogus"] = 1
    errs = paths(bad)
    assert errs["$.title"] == "is required"
    assert errs["$.bogus"] == "is not an allowed property"


def test_scene_errors_have_precise_paths(valid):
    bad = copy.deepcopy(valid)
    bad["scenes"][1]["type"] = "INTRO"
    bad["scenes"][0]["vo"] = " ".join(["word"] * 29)
    bad["scenes"][0]["label"] = "one two three four five six seven"
    bad["scenes"][2]["extra"] = {"focus_lines": [3], "bbox": [0.1, 1.5, 0.2, 0.2], "stat_keys": ["lines_written"],
                                 "foo": True}
    errs = paths(bad)
    assert "is not one of" in errs["$.scenes[1].type"]
    assert errs["$.scenes[0].vo"] == "is 29 words; max 28"
    assert errs["$.scenes[0].label"] == "is 7 words; max 6"
    assert "needs at least 2" in errs["$.scenes[2].extra.focus_lines"]
    assert "above maximum" in errs["$.scenes[2].extra.bbox[1]"]
    assert "is not one of" in errs["$.scenes[2].extra.stat_keys[0]"]
    assert errs["$.scenes[2].extra.foo"] == "is not an allowed property"


def test_product_is_required_and_typed(valid):
    bad = copy.deepcopy(valid)
    bad["product"]["kind"] = "spaceship"
    bad["product"]["features"] = ["fine", "x " * 10]
    errs = paths(bad)
    assert "is not one of" in errs["$.product.kind"]
    assert "words; max 6" in errs["$.product.features[1]"]
    del bad["product"]
    assert paths(bad)["$.product"] == "is required"


def test_type_errors_stop_descent():
    errs = validate_schema({"title": 5, "tagline": "", "cta": "", "product": {}, "scenes": "nope"})
    got = {e.path: e.message for e in errs}
    assert got["$.title"] == "expected string, got integer"
    assert got["$.scenes"] == "expected array, got string"
    assert validate_schema([]) [0].message == "expected object, got array"


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_transport_schema_is_portable(valid):
    ts = transport_schema()
    banned = {"minLength", "maxLength", "pattern", "minimum", "maximum", "maxItems", "uniqueItems"}
    for node in _walk(ts):
        assert not banned & set(node), node
        assert not any(k.startswith("x-") for k in node)
        assert node.get("minItems", 0) <= 1
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
    assert validate_schema(valid, ts) == []
    assert set(SceneType.__members__) == set(ts["properties"]["scenes"]["items"]["properties"]["type"]["enum"])
    json.dumps(ts)  # serialisable for the provider
    assert STORYBOARD_SCHEMA["properties"]["title"]["maxLength"] == 40  # the full schema keeps its limits


def test_parse_json_text_tolerates_fences_and_prose(valid):
    text = "Here you go:\n```json\n" + json.dumps(valid) + "\n```\nEnjoy!"
    obj, err = parse_json_text(text)
    assert err == "" and obj == valid
    obj, err = parse_json_text("Sure! " + json.dumps(valid) + " Hope that helps.")
    assert obj == valid
    obj, err = parse_json_text('{"title": "x",')
    assert obj is None and err.startswith("invalid JSON")
    assert parse_json_text("")[1] == "empty response"


def test_roundtrip(valid):
    sb = storyboard_from_json(valid, mode="lore")
    assert sb.mode == "making_of"
    assert sb.product.name == valid["product"]["name"]
    back = storyboard_to_json(sb)
    assert back["scenes"] == valid["scenes"]
    assert back["product"] == valid["product"]
