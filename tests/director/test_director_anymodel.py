"""Any-model engine: weak/broken model output is repaired or falls back to the engine floor (fake models)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from director_fakes import FILM, TREATMENT, FakeLlm, FakeRenderer, critique, png

from showreel_core.contracts import Product
from showreel_core.director import compose, measured, repair, tiers
from showreel_core.director.catalog import build_catalog
from showreel_core.director.checks import (
    blender_product_shot,
    check_film,
    product_share,
)
from showreel_core.director.engine import run
from showreel_core.director.llm import LlmReply
from showreel_core.director.sheet import Frame
from showreel_core.director.types import Brief, Capabilities, MediaAsset

# ------------------------------------------------------------------------------------ repair


def test_lenient_json_repairs_common_breakage() -> None:
    cases = [
        'Sure! Here is the plan:\n```json\n{"a": 1, "b": [1, 2,],}\n```\nHope it helps.',
        "{'a': 1, 'b': [1, 2]}",
        '{"a": 1, // the count\n "b": [1, 2] /* list */}',
        '{"a": True, "b": [1, 2], "c": None}',
        '{"a": 1, "b": [1, 2], "c": {"d": "cut off mid',
    ]
    for text in cases:
        obj, fixes = repair.loads_lenient(text)
        assert isinstance(obj, dict) and obj["a"] in (1, True) and obj["b"] == [1, 2], (text, obj, fixes)
    assert repair.loads_lenient("no json here at all")[0] is None


def test_coerce_fixes_types_lists_enums_and_defaults() -> None:
    schema = {"type": "object", "properties": {
        "t": {"type": "number"}, "ok": {"type": "boolean"}, "tags": {"type": "array", "items": {"type": "string"}},
        "items": {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "number"}}}},
        "mode": {"type": "string", "enum": ["none", "sparse", "narrated"], "default": "sparse"},
        "name": {"type": "string"}, "req": {"type": "string", "default": "d"}}, "required": ["req"]}
    obj, fixes = repair.coerce({"T": "3.5 s", "ok": "yes", "tags": "a\nb", "items": {"x": "2"}, "mode": "Narrated",
                                "name": 7}, schema)
    assert obj["t"] == 3.5 and obj["ok"] is True and obj["tags"] == ["a", "b"]
    assert obj["items"] == [{"x": 2.0}] and obj["mode"] == "narrated" and obj["name"] == "7" and obj["req"] == "d"
    assert fixes
    obj, _ = repair.coerce({"mode": "shouting"}, schema)
    assert obj["mode"] == "sparse"


def test_snap_maps_hallucinated_ids_but_not_nonsense() -> None:
    scenes = ["kit:nature/flower-field", "kit:nature/sky-reveal", "kit:pixel/boss-battle", "kit:type/end-lockup"]
    assert repair.snap_scene("kit:natur/flower_field", scenes) == "kit:nature/flower-field"
    assert repair.snap_scene("kit:nature/flowerfield", scenes) == "kit:nature/flower-field"
    assert repair.snap_scene("flower-field", scenes) == "kit:nature/flower-field"
    assert repair.snap_scene("kit:pixel/boss_battle", scenes) == "kit:pixel/boss-battle"
    assert repair.snap_scene("kit:type/endlockup", scenes) == "kit:type/end-lockup"
    assert repair.snap_scene("kit:fake/does-not-exist", scenes) is None
    assert repair.snap("Pixel_Boss_B", ["pixel_boss_b", "dream_b"]) == "pixel_boss_b"


def test_fit_words_never_cuts_mid_phrase() -> None:
    assert repair.fit_words("Short line.", 5) == "Short line."
    assert repair.fit_words("First sentence here. Second one is long and more.", 4) == "First sentence here."
    assert repair.fit_words("Fast offline notes, with sync everywhere you go", 4) == "Fast offline notes"
    assert repair.fit_words("one two three four five six seven", 3) == ""


def test_snap_film_ids_in_place(env: dict[str, Any]) -> None:
    obj = json.loads(json.dumps(FILM))
    obj["film"]["shots"][2]["scene"] = "kit:fake/feild"
    obj["film"]["transitions"][0]["type"] = "kit:fake/petal_bloom"
    obj["film"]["music"][0]["bed"] = "pixel-a"
    obj["film"]["shots"][0]["params"]["media"] = "the car"
    fixes = repair.snap_film_ids(obj, env["catalog"], ["car"])
    f = obj["film"]
    assert f["shots"][2]["scene"] == "kit:fake/field" and f["transitions"][0]["type"] == "kit:fake/petal-bloom"
    assert f["music"][0]["bed"] == "pixel_a" and f["shots"][0]["params"]["media"] == "car" and len(fixes) >= 4


# ------------------------------------------------------------------------------------ tiers


def test_tier_detection() -> None:
    assert tiers.detect("claude-haiku-4-5").name == "weak"
    assert tiers.detect("claude-haiku-4-5").path == "compose"
    assert tiers.detect("claude-opus-5-5").name == "strong"
    assert tiers.detect("claude-fable-5-2").custom_scenes == 3
    assert tiers.detect("deepseek-v4.1-flash-fast").vision is False
    assert tiers.detect("gemma-3-12b").context < 60_000
    assert tiers.detect("some-new-model").name == "standard"
    assert tiers.detect("some-new-model").custom_scenes == 0
    assert tiers.detect("claude-opus-5-5", configured="weak").name == "weak"
    assert tiers.detect("claude-haiku-4-5", vision="false").vision is False
    assert tiers.detect("").name == "strong"


# ------------------------------------------------------------------------------------ compose steps (real catalog)

CAP = [("desktop_1920x1080", 1920, 1080), ("element_04_instant_searc", 792, 450),
       ("element_02_offline_first", 792, 450), ("mobile_390x844", 780, 1688)]


def _screen_brief(tmp: Path, direction: str, *, blender: bool = False) -> Brief:
    assets = []
    for name, w, h in CAP:
        p = tmp / f"{name}.png"
        p.write_bytes(png(size=(64, 36)))
        assets.append(MediaAsset(name, "image", str(p), w, h, thumbnail=str(p)))
    return Brief(direction, product=Product(name="Orbit Notes", one_liner="Fast offline notes with sync.",
                                            features=["Offline first", "Instant search"]),
                 assets=assets, seconds=30.0, capabilities=Capabilities(blender=blender))


def _car_brief(tmp: Path, direction: str, *, blender: bool = False) -> Brief:
    thumb = tmp / "car.png"
    thumb.write_bytes(png())
    assets = [MediaAsset("car", "video", str(tmp / "car.mp4"), 1280, 720, 6.0, 30.0, str(thumb), "a red car")]
    if blender:
        (tmp / "car.glb").write_bytes(b"glTF")
        assets.append(MediaAsset("car3d", "model", str(tmp / "car.glb")))
    return Brief(direction, product=Product(name="Red Car", one_liner="A glossy red car."), assets=assets,
                 seconds=25.0, capabilities=Capabilities(blender=blender))


def test_pick_repairs_malformed_and_hallucinated(tmp_path: Path) -> None:
    b = _screen_brief(tmp_path, "a 1980s VHS infomercial")
    bps = compose.blueprints(catalog=build_catalog(assets=b.assets))
    text = ("Great choice! ```json\n{'blueprint': 'Screen_Terminal', 'time': 'Night', 'voice': 1, "
            "'accent': 'red', 'tagline': 'Your notes, in orbit, forever and ever and ever and ever and ever', "
            "'cta': 'Call now',}\n```")
    pick, fixes = compose.check_pick(text, bps, b)
    assert pick["blueprint"] == "screen-terminal" and pick["time"] == "night"
    assert pick["voice"] in compose.VOICES and pick["accent"].startswith("#") and pick["cta"] == "Call now"
    assert fixes
    pick, _ = compose.check_pick({"blueprint": "kit:nature/space-opera-9000"}, bps, b)
    assert pick["blueprint"] in {x.id for x in bps}                    # unknown -> engine default
    pick, _ = compose.check_pick(None, bps, b)
    assert pick["blueprint"] == "screen-terminal"                      # direction keywords still decide


def test_words_repair_and_budgets(tmp_path: Path) -> None:
    b = _screen_brief(tmp_path, "noir detective trailer")
    bps = compose.blueprints(catalog=build_catalog(assets=b.assets))
    bp = next(x for x in bps if x.id == "screen-cinematic")
    pick = dict(compose.default_pick(bps, b), voice="sparse")
    slots = compose.slots(bp, b)
    key = next(k for k in slots if k.startswith("hook."))
    reply = {"text": {key: "The city never sleeps. Neither do your notes, kid, not ever again, not tonight.",
                      "nonsense.slot": "x", "quote.text": ["She", "never", "forgot", "a", "thing."]},
             "voiceover": ["The rain had a story.", {"id": "w9", "text": "Every note left a trace."}, 42]}
    texts, voice, _fixes = compose.check_words(reply, bp, b, pick, 30.0)
    assert texts[key] == "The city never sleeps." and texts["quote.text"] == "She never forgot a thing."
    assert "nonsense.slot" not in texts and voice and all(isinstance(v["t"], float) for v in voice)
    obj = compose.assemble(b, bp, pick, texts, voice)
    chk = check_film(obj, b, build_catalog(assets=b.assets), max_custom=0)
    assert chk.value is not None, chk.errors
    film, plan = chk.value
    assert film["render"]["post"] == "crt" if bp.id == "screen-terminal" else True
    assert {s["scene"].split("/")[0] for s in film["shots"]} == {"kit:cinematic"}
    assert plan["voiceover"] and not any("<" in json.dumps(s["params"]) for s in film["shots"])


def test_floor_makes_valid_films_for_any_direction(tmp_path: Path) -> None:
    for direction in ("", "a 1980s VHS infomercial", "make it like a comic book", "blueprint style please",
                      "something nobody has ever asked for"):
        b = _screen_brief(tmp_path, direction)
        cat = build_catalog(assets=b.assets)
        bp, _pick, obj = compose.floor(b, compose.blueprints(catalog=cat))
        chk = check_film(obj, b, cat, max_custom=0)
        assert chk.value is not None, (direction, bp.id, chk.errors)
    b = _car_brief(tmp_path, "an Apple keynote reveal", blender=True)
    cat = build_catalog(assets=b.assets, capabilities=b.capabilities)
    bp, _pick, obj = compose.floor(b, compose.blueprints(catalog=cat, blender=True))
    assert bp.id == "studio-reveal"
    chk = check_film(obj, b, cat, max_custom=0)
    assert chk.value is not None, chk.errors
    film, _ = chk.value
    assert film["assets"]["car3d"] == {"type": "model"} and film["meta"]["product_asset"] == "car3d"
    assert all(blender_product_shot(s) for s in film["shots"]) and product_share(film, {"car", "car3d"})[0] == 1.0


def test_blender_scenes_in_catalog_only_with_blender() -> None:
    assert not [s for s in build_catalog().scenes() if s.startswith("blender:")]
    sc = build_catalog(capabilities=Capabilities(blender=True)).scenes()
    assert "blender:studio/product_hero" in sc and "fill" in sc["blender:studio/product_hero"].params


# ------------------------------------------------------------------------------------ engine end to end


def _engine(tmp: Path, brief: Brief, llm: Any, renderer: FakeRenderer | None = None, **kw: Any) -> Any:
    return run(brief, llm=llm, renderer=renderer or FakeRenderer(), effort="quick", job_dir=tmp / "job",
               library_dir=tmp / "lib", catalog=build_catalog(assets=brief.assets, capabilities=brief.capabilities),
               **kw)


def test_weak_model_composes_with_broken_replies_and_no_vision(tmp_path: Path) -> None:
    b = _screen_brief(tmp_path, "a 1980s VHS infomercial")
    llm = FakeLlm({"pick": ["ok so i think ```{\"blueprint\": \"terminal\", \"voice\": \"Sparse\", \"tagline\": 5,}```"],
                   "words": [LlmReply(text="{\"text\": {\"hook.label\": \"BUT WAIT, THERE IS MORE\"}, "
                                           "\"voiceover\": \"Tired of losing notes?\"")]})
    res = _engine(tmp_path, b, llm, tier=tiers.detect("deepseek-v4.1-flash-fast"))
    assert res.ok, res.error
    assert res.tier["name"] == "weak" and res.tier["path"] == "compose" and not res.tier["vision"]
    assert llm.purposes() == ["pick", "words"]                       # no treatment, no film, no critic call
    assert all(s["scene"].startswith("kit:terminal/") for s in res.film["shots"])
    assert res.scores and "measured" in res.scores[0].verdict
    state = json.loads((tmp_path / "job" / "director" / "state.json").read_text(encoding="utf-8"))
    assert state["tier"]["path"] == "compose"


def test_weak_model_with_vision_gets_the_critic(tmp_path: Path) -> None:
    b = _screen_brief(tmp_path, "noir detective trailer")
    llm = FakeLlm({"pick": [{"blueprint": "screen-cinematic", "time": "night", "voice": "sparse",
                             "tagline": "Every note leaves a trace.", "cta": "Open the case"}],
                   "words": [{"text": {}, "voiceover": []}], "critic": [critique(6.5)]})
    res = _engine(tmp_path, b, llm, tier=tiers.detect("claude-haiku-4-5"))
    assert res.ok and llm.purposes()[:2] == ["pick", "words"] and "critic:r1" in llm.purposes()
    assert res.scores[0].mean == 6.5 and res.film["title"] == "Orbit Notes"


def test_free_path_failure_falls_to_compose(tmp_path: Path) -> None:
    b = _screen_brief(tmp_path, "anime opening credits")
    llm = FakeLlm({"treatment": ["I cannot write JSON today."], "pick": [{"blueprint": "screen-comic"}],
                   "words": ["{}"], "critic": [critique(6.0)]})
    res = _engine(tmp_path, b, llm, tier=tiers.detect("claude-opus-5-5"))
    assert res.ok and res.tier["path"] == "compose"
    assert llm.purposes().count("treatment") == 2 and "pick" in llm.purposes()
    assert all(s["scene"].startswith("kit:comic/") for s in res.film["shots"])


def test_offline_model_still_gets_the_engine_floor_film(tmp_path: Path) -> None:
    b = _car_brief(tmp_path, "pixel boss battle")
    llm = FakeLlm({})                                  # every call errors
    res = _engine(tmp_path, b, llm)
    assert res.ok and res.tier["path"] == "floor"
    assert {s["scene"] for s in res.film["shots"]} >= {"kit:pixel/boss-battle"}


def test_product_facts_flow_without_direction(tmp_path: Path) -> None:
    b = _screen_brief(tmp_path, "")
    llm = FakeLlm({"pick": ["{}"], "words": ["{}"]})
    res = _engine(tmp_path, b, llm, tier=tiers.detect("tiny-local-3b"))
    assert res.ok and res.film["title"] == "Orbit Notes"
    shown = json.dumps(res.film)
    assert "desktop_1920x1080" in shown and "Offline first" in shown
    pick_prompt = next(c for c in llm.calls if c["purpose"] == "pick")["text"]
    assert "Orbit Notes" in pick_prompt and "Instant search" in pick_prompt


def test_strong_path_snaps_hallucinated_kit_ids_without_a_reask(env: dict[str, Any]) -> None:
    bad = json.loads(json.dumps(FILM))
    bad["film"]["shots"][2]["scene"] = "kit:fake/feild"
    bad["film"]["shots"][0]["scene"] = "fake/walk"
    llm = FakeLlm({"treatment": [TREATMENT], "film": [bad], "scene": ["```js\n" + _GOOD + "```"],
                   "critic": [critique(9.0)]})
    res = run(env["brief"], llm=llm, renderer=FakeRenderer(), effort="quick", job_dir=env["job"],
              library_dir=env["library"], catalog=env["catalog"], tier=tiers.detect("claude-opus-5-5"))
    assert res.ok and llm.purposes().count("film") == 1
    assert res.film["shots"][0]["scene"] == "kit:fake/walk"


_GOOD = """import { sr } from '../runtime/showreel.js';
sr.defineScene('custom:boss-battle', { layer: '2d', describe: 'b', params: {},
  render(ctx, t, p) { ctx.g.fillRect(0, 0, ctx.w, ctx.h); } });
"""


# ------------------------------------------------------------------------------------ measured review


def test_measured_review_scores_from_measurements() -> None:
    film = {"dur": 10.0, "shots": [{"id": "a", "t0": 0, "t1": 5, "scene": "kit:launch/HOOK"},
                                   {"id": "b", "t0": 5, "t1": 10, "scene": "kit:launch/END"}],
            "transitions": [], "overlays": []}
    plan = {"shots": [{"id": "a", "product_visible": True}, {"id": "b", "product_visible": True}]}
    frames = [Frame(1, "a", 1.0, 1.0, 5.0), Frame(2, "a", 4.0, 4.0, 5.0), Frame(3, "b", 8.0, 3.0, 5.0)]
    flat = png((10, 10, 10), (96, 54))
    crit = measured.review(film, plan, frames, [flat, flat, flat], qa=[{"kind": "clip", "msg": "x", "shot": "b"}])
    assert set(crit["scores"]) >= {"product_clarity", "legibility"} and crit["measured"]
    assert any("flat" in i["issue"] for i in crit["per_shot_issues"])
    assert crit["scores"]["legibility"] < 8


def test_custom_scene_used_only_as_an_overlay_is_kept(env: dict[str, Any]) -> None:
    obj = json.loads(json.dumps(FILM))
    obj["film"]["overlays"].append({"id": "vhs", "t0": 0, "t1": 45, "scene": "custom:vhs-deck", "params": {}})
    obj["plan"]["custom_scenes"].append(dict(obj["plan"]["custom_scenes"][0], name="vhs-deck"))
    chk = check_film(obj, env["brief"], env["catalog"], max_custom=3)
    assert chk.value is not None, chk.errors
    assert {c["name"] for c in chk.value[1]["custom_scenes"]} == {"boss-battle", "vhs-deck"}
