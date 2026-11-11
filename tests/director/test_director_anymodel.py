"""Any-model engine: weak/broken model output is repaired or falls back to the engine floor (fake models)."""
from __future__ import annotations

import dataclasses
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
from showreel_core.director.types import EFFORTS, Brief, Capabilities, MediaAsset

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


def test_strip_captures_never_carry_the_hero(tmp_path: Path) -> None:
    """A real keynote film opened on a 2096x136 footer strip (a text-matched crop) because it out-ranked the
    1920x1080 desktop capture; strips rank last and never fill the hero, screen or feature slots."""
    caps = [("element_02_stats_8648ae", 2096, 136), ("element_01_tasks_994a93", 924, 152),
            ("desktop_1920x1080", 1920, 1080), ("element_03_timer_1a2b3c", 488, 668), ("mobile_390x844", 780, 1688)]
    assets = []
    for name, w, h in caps:
        f = tmp_path / f"{name}.png"
        f.write_bytes(png(size=(64, 36)))
        assets.append(MediaAsset(name, "image", str(f), w, h, thumbnail=str(f)))
    b = Brief("an Apple keynote", product=Product(name="Tempo", features=["Timer", "Tasks", "Stats"]),
              assets=assets, seconds=30.0)
    ranked = compose._rank_screens(b)
    assert ranked[0] == "desktop_1920x1080" and set(ranked[-2:]) == {"element_02_stats_8648ae",
                                                                     "element_01_tasks_994a93"}
    v = compose.facts(b)
    assert v["asset1"] == "desktop_1920x1080"
    assert v["asset2"] == "element_03_timer_1a2b3c"          # name match on a real card
    assert v["asset3"] not in ("element_02_stats_8648ae", "element_01_tasks_994a93")  # 'Tasks' crop is a strip
    bp = next(x for x in compose.blueprints(catalog=build_catalog(assets=b.assets)) if x.id == "screen-launch")
    film = compose.assemble(b, bp, {"blueprint": bp.id})["film"]
    used = json.dumps(film["shots"])
    assert "element_02_stats" not in used and "element_01_tasks" not in used
    quote = next(s for s in film["shots"] if s["id"] == "quote")
    assert quote["params"]["who"] != "user"                   # kits print 'user' as 'You asked'


def test_narration_retries_transient_tts_failures(tmp_path: Path) -> None:
    """Edge TTS answers 'NoAudioReceived' now and then: a line is retried (a documentary lost 2 of 7 lines),
    but when TTS is simply down (nothing has spoken) each line gets one try, so the film is not delayed."""
    from showreel_core.director import voice

    class Clip:
        def __init__(self, path: Path) -> None:
            self.path, self.duration = path, 1.5
    tries: dict[str, int] = {}

    def flaky(_d: Any, text: str, out: Path, speed: Any = None) -> Any:
        tries[text] = tries.get(text, 0) + 1
        if text == "Two." and tries[text] < 3:
            raise RuntimeError("NoAudioReceived: No audio was received.")
        return Clip(out)
    slept: list[float] = []
    lines = [{"t": 1.0, "text": "One."}, {"t": 5.0, "text": "Two."}, {"t": 9.0, "text": "Three."}]
    out, warns = voice.synthesize(lines, dispatch=None, out_dir=tmp_path / "vo", dur=20.0, pace=lambda t: 1.0,
                                  tts=flaky, sleep=slept.append)
    assert [o["text"] for o in out] == ["One.", "Two.", "Three."] and tries["Two."] == 3 and slept == [1.5, 4.0]
    assert any("try 3" in w for w in warns)
    tries.clear()
    slept.clear()
    out, warns = voice.synthesize(lines, dispatch=None, out_dir=tmp_path / "vo2", dur=20.0, pace=lambda t: 1.0,
                                  tts=lambda *a, **k: None, sleep=slept.append)
    assert out == [] and len(slept) == 2 and len([w for w in warns if "could not be spoken" in w]) == 3


def test_lock_waits_do_not_spend_the_effort_clock(tmp_path: Path) -> None:
    """A keynote run waited ~40 min for other jobs' Blender (GPU lock) and the engine then skipped its vision critic
    as 'late': waits measured by the renderer are subtracted from the effort's wall clock."""
    import contextlib
    import time as _time

    from showreel_core.director import engine
    from showreel_core.director.backend import RuntimeRenderer

    rr = RuntimeRenderer(job_dir=tmp_path)

    @contextlib.contextmanager
    def slow_lock() -> Any:
        _time.sleep(0.05)
        yield
    with rr._timed(slow_lock)():
        pass
    assert rr.waited_s >= 0.04 and rr._timed(None) is None

    class R:
        budget = dataclasses.replace(EFFORTS["standard"], deadline_s=100.0)
        effort = "standard"
        t0 = _time.monotonic() - 90.0
        renderer = rr
    assert engine._late(R, 0.5)                      # 90 s of 100 s spent
    rr.waited_s = 60.0
    assert not engine._late(R, 0.5)                  # 60 s of it was waiting for someone else's Blender


def test_no_loopback_address_on_screen_and_no_title_over_the_product(tmp_path: Path) -> None:
    """ISSUES #56: a real END printed '127.0.0.1:8765' and laid the name across the app's timer ring."""
    b = _screen_brief(tmp_path, "an Apple keynote")
    b.product.urls = ["http://127.0.0.1:8765/", "orbitnotes.app"]
    obj = {"film": {"shots": [
        {"id": "f", "t0": 0, "t1": 5, "scene": "kit:launch/FEATURE",
         "params": {"image": {"asset": "desktop_1920x1080", "url": "127.0.0.1:8765"}, "feature": "Sync"}},
        {"id": "end", "t0": 5, "t1": 9, "scene": "custom:keynote-stage",
         "params": {"product": "desktop_1920x1080", "title": "Orbit Notes", "cta": "Open http://localhost:8765"}}],
        "overlays": [{"id": "o", "t0": 1, "t1": 2, "scene": "kit:type/lower-third",
                      "params": {"title": "Live at 127.0.0.1:8765", "sub": ""}}]},
        "plan": {"custom_scenes": [{"name": "keynote-stage", "spec": "x"}]}}
    url = repair.public_url(b.product.urls)
    fixes = repair.scrub_loopback(obj["film"], name="Orbit Notes", url=url)
    cat = build_catalog(assets=b.assets)
    fixes += repair.lockup_end(obj, cat, [a.name for a in b.assets], name="Orbit Notes", tagline="Notes in orbit",
                               url=url)
    text = json.dumps(obj)
    assert "127.0.0.1" not in text and "localhost" not in text and len(fixes) >= 4
    assert obj["film"]["shots"][0]["params"]["image"]["url"] == "orbitnotes.app"
    end = obj["film"]["shots"][-1]
    assert end["scene"] == "kit:launch/END" and end["params"]["title"] == "Orbit Notes"
    assert "desktop_1920x1080" not in json.dumps(end) and obj["plan"]["custom_scenes"] == []
    # the brief the model reads never offers the dev server
    from showreel_core.director import prompts
    txt = prompts._product_text(b)
    assert "orbitnotes.app" in txt and "127.0.0.1" not in txt
    # composed films too
    bp = next(x for x in compose.blueprints(catalog=cat) if x.id == "screen-launch")
    assert "127.0.0.1" not in json.dumps(compose.assemble(b, bp, {"blueprint": bp.id})["film"])


def test_mood_grade_changes_the_whole_look(tmp_path: Path) -> None:
    """Noir = black and white with the product's own colour held + rain; VHS keeps the kit CRT and adds chroma
    shift + tracking wobble; the grade is a post chain over every frame (product media and kit scenes alike)."""
    from showreel_core.render.post import build_post
    film: dict[str, Any] = {"render": {"post": "crt", "post_params": {"crt": {"glow": 0.4}}}, "finish": {}}
    assert compose.mood_look(film, "a 1980s VHS infomercial") == ["vhs"]
    assert film["render"]["post"] == "crt+grade" and film["render"]["post_params"]["crt"] == {"glow": 0.4}
    assert film["render"]["post_params"]["grade"]["shift"] > 0 and film["render"]["post_params"]["grade"]["wobble"]
    noir: dict[str, Any] = {}
    compose.mood_look(noir, "a noir detective trailer", hold="#c8102e")
    g = noir["render"]["post_params"]["grade"]
    assert g["hold"] == "#c8102e" and g["contrast"] > 1.2 and g["rain"] > 0 and noir["finish"]["grain"] >= 0.1
    compose.mood_look(noir, "a noir detective trailer", hold="#c8102e")       # idempotent
    assert noir["render"]["post"] == "grade"
    flat: dict[str, Any] = {}
    compose.mood_look(flat, "noir", hold="")
    assert "hold" not in flat["render"]["post_params"]["grade"] and flat["render"]["post_params"]["grade"]["mono"] == 1
    key: dict[str, Any] = {"finish": {"grain": 0.05}}
    compose.mood_look(key, "an Apple keynote reveal")
    assert key["finish"]["grain"] <= 0.012
    pc = build_post("grade+grain_vignette", in_size=(320, 180), out_size=(320, 180), seed=1, work_dir=tmp_path,
                    params={"grade": g, "grain_vignette": {"grain": 10, "vignette": 0.5}})
    assert "colorhold=color=0xc8102e" in pc.graph and "curves" in pc.graph and "overlay" in pc.graph
    assert any("rain_" in x for x in pc.extra_inputs)
    vhs = build_post("grade", in_size=(320, 180), out_size=(320, 180), params={"grade": {"shift": 4, "wobble": 3,
                                                                                         "mono": 0.2}})
    assert "rgbashift=rh=-4:bh=4" in vhs.graph and "crop=w=iw-6" in vhs.graph and "colorchannelmixer" in vhs.graph


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
    assert all(blender_product_shot(s) for s in film["shots"] if s["scene"].startswith("blender:"))
    assert product_share(film, {"car", "car3d"})[0] >= 0.75
    assert film["shots"][0]["params"]["text"] == "Red Car"            # unfilled teaser -> the product name


def test_blender_scenes_in_catalog_only_with_blender() -> None:
    assert not [s for s in build_catalog().scenes() if s.startswith("blender:")]
    sc = build_catalog(capabilities=Capabilities(blender=True)).scenes()
    assert "blender:studio/product_hero" in sc and "fill" in sc["blender:studio/product_hero"].params


# ------------------------------------------------------------------------------------ engine end to end


FREE_QUICK = dataclasses.replace(EFFORTS["quick"], path="", deadline_s=0.0, max_custom=2)


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
    res = _engine(tmp_path, b, llm, tier=tiers.detect("claude-opus-5-5"), budget=FREE_QUICK)
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
              library_dir=env["library"], catalog=env["catalog"], tier=tiers.detect("claude-opus-5-5"),
              budget=FREE_QUICK)
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


def test_blender_product_shots_need_no_product_param() -> None:
    from showreel_core.director import prominence as pm
    film = {"shots": [{"id": "m", "t0": 0, "t1": 10, "scene": "blender:meadow/oner", "params": {"t_offset": 0}}]}
    errs, _ = pm.static_check(film, {"shots": [{"id": "m", "product_visible": True}]}, {"car", "car3d"}, "16:9")
    assert errs == []


# --- scene lint: the bracket check must understand JS (a real job lost a valid scene to "unbalanced `}`")
def test_balance_ignores_regex_literals_strings_and_templates() -> None:
    from showreel_core.director import checks
    ok = ("const f = (s) => { if (/geist/i.test(s) && !/var\\(|^\\s*\\d/.test(s)) { return s; } };\n"
          "const url = '//127.0.0.1:8765/'; const half = w / 2 / 3;\n"
          "const t = `a ${b ? `x{` : `}`} c ${ {k: 1}.k }`; const r = /[}/]/g;\n")
    assert checks._balance(checks.strip_comments(ok)) == ""


def test_balance_still_catches_truncated_and_broken_code(monkeypatch) -> None:
    import shutil

    from showreel_core.director import checks
    assert "unclosed" in checks._balance("sr.defineScene('x', { render(ctx, t, p) { if (t) {")
    assert "unbalanced" in checks._balance("const a = [1, 2); }")
    monkeypatch.setattr(shutil, "which", lambda _n: None)        # no node: the heuristic decides
    errs, _ = checks.lint_scene("import * as sr from '../runtime/showreel.js';\n"
                                "sr.defineScene('x', { layer: '2d', render(ctx, t, p) { ctx.x(); } } });", "x")
    assert any(e.startswith("syntax:") for e in errs)


def test_quick_effort_is_kit_first_and_time_boxed(tmp_path: Path) -> None:
    """quick = engine-assembled from blueprints even for a strong model: no treatment/film/scene-code calls, one
    critique, no revision (a real quick job on the free path took 27 min of model thinking)."""
    b = _car_brief(tmp_path, "make it feel like an Apple keynote")
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "pick": [{"blueprint": "launch-keynote"}],
                   "words": ["{}"], "critic": [critique(5.0)]})
    res = run(b, llm=llm, renderer=FakeRenderer(), effort="quick", job_dir=tmp_path / "job",
              library_dir=tmp_path / "lib", catalog=build_catalog(assets=b.assets, capabilities=b.capabilities),
              tier=tiers.detect("claude-fable-5-2"))
    assert res.ok and res.tier["path"] == "compose", res.error
    assert not {"treatment", "film", "revise-film"} & set(llm.purposes())
    assert not any(p.startswith("scene") for p in llm.purposes()) and len(res.scores) == 1
