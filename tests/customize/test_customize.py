"""Preset customization: knob parsing, routing (slash/tool/CLI/API), spec validation + repair with fake weak
models, the theme layer and the timeline/film edits. Slow: theme overrides reach the rendered page (Chromium)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from showreel_core.commands import parse
from showreel_core.config import Options, style_ids
from showreel_core.customize import apply as A
from showreel_core.customize.apply import CUTIN_MAX_S, CUTIN_MIN_S
from showreel_core.customize import command as C
from showreel_core.customize import knobs as K
from showreel_core.customize import spec as S
from showreel_core.customize import theme as TH
from showreel_core.customize import vocab as V
from showreel_core.customize.llm import customize_spec
from showreel_core.customize.route import route
from showreel_core.film.quick import film_from_timeline
from showreel_core.film.schema import errors_of, validate_film

ROOT = Path(__file__).resolve().parents[2]
STYLES = set(style_ids())


def _tl(**kw):
    from tests.kits.test_quick import _timeline
    return _timeline(**kw)


def _media():
    from tests.kits.test_quick import MEDIA_MAP
    return MEDIA_MAP


# ------------------------------------------------------------------------------------------- knobs

def test_extract_knobs_with_quotes_aliases_and_unknown_keys():
    ex = K.extract('pixel accent=#00e5ff energy=high title="ORBIT QUEST" colour=pink bogus=1 --seconds=45 60')
    assert ex.knobs == {"accent": "pink", "energy": "high", "title": "ORBIT QUEST"}   # colour= aliases accent (last wins)
    assert ex.unknown == ["bogus"]
    assert ex.rest == "pixel --seconds=45 60"          # passthrough keys stay for the base parser
    assert K.extract("directed launch pink").force == "directed"
    assert K.extract("see https://x.dev/?a=b now").knobs == {}


def test_normalise_values_and_friendly_problems(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n")
    out, probs = K.normalise({"accent": "hot pink", "bg": "#123", "font": "bangers", "music": "playful",
                              "energy": "faster", "narration": "off", "voice": "whispered", "voice_speed": "1.2x",
                              "title": "  ORBIT   QUEST ", "logo": str(logo), "captions": "big", "transitions": "whip",
                              "length": "45s", "aspect": "both", "language": "Spanish", "palette": "cyberpunk"})
    assert probs == []
    assert out["accent"] == V.COLOURS["hotpink"] and out["bg"] == "#112233" and out["font"] == "Bangers"
    assert out["music"].startswith("comic_") and out["energy"] == "high" and out["narration"] is False
    assert out["voice"] == "whisper" and out["voice_speed"] == 1.2 and out["title"] == "ORBIT QUEST"
    assert out["captions"] == "bold" and out["transitions"] == "punchy" and out["length"] == 45
    assert out["aspect"] == ["16:9", "9:16"] and out["language"] == "es" and out["palette"] == "neon"
    bad, probs = K.normalise({"accent": "blurple", "font": "Comic Sans", "music": "polka", "logo": "x.txt",
                              "language": "klingon", "nope": 1})
    assert bad == {}
    assert len(probs) == 6 and any("Valid settings" in p for p in probs) and any("available:" in p for p in probs)


def test_every_kit_font_is_offered_and_resolvable():
    fams = {r["family"] for r in V.fonts().values()}
    for want in ("Geist", "Bangers", "Fraunces", "VT323", "Space Grotesk", "Cormorant Garamond", "Silkscreen", "Caveat"):
        assert want in fams
        files = V.fonts()[want.lower()]["files"]
        assert files and all((ROOT / f["src"]).is_file() for f in files)
    assert V.font("plex") == "IBM Plex Mono" or V.font("plex").startswith("IBM Plex")


def test_music_moods_resolve_to_real_beds():
    beds = V.beds()
    for mood, ids in V.MOODS.items():
        assert V.music(mood) in beds, mood
        assert all(i in beds for i in ids), mood
    assert V.music("none") == "none" and V.music("comic") == "comic_a" and V.music("Kapow!") == "comic_b"


# ------------------------------------------------------------------------------------------- routing

@pytest.mark.parametrize("raw,route_,style", [
    ("pixel make the boss a giant bug and use neon colours", "customize", "pixel"),
    ("launch pink and playful with a punchier ending", "customize", "launch"),
    ("terminal green phosphor hacker vibe, faster", "customize", "terminal"),
    ("cinematic moody blue night, slower, whispered narration", "customize", "cinematic"),
    ("lore but in pink and playful", "customize", "launch"),
    ("make it pink and playful", "directed", "launch"),
    ("pixel but transition into a different style mid way through, goal is to sell the product", "directed", "pixel"),
    ("pixel, then bloom into anime, sell it", "directed", "pixel"),
    ("pixel and then cinematic for the ending", "directed", "pixel"),
    ("launch with a comic font", "customize", "launch"),
    ("directed launch pink and playful", "directed", "launch"),
    ("customize make it pink", "customize", "launch"),
])
def test_routing_rule(raw, route_, style):
    cmd = parse(raw, styles=STYLES)
    o = cmd.options
    assert o.style == style
    cz = o.hints.get("customize") or {}
    if route_ == "customize":
        assert not o.directed and cz.get("route") == "customize" and cz.get("text")
        assert not cz["text"].lower().startswith(style + " ")          # preset word stripped from the request
    else:
        assert o.directed and cz.get("route") in (None, "directed")


def test_knobs_only_keeps_the_quick_preset_and_maps_options():
    cmd = parse('pixel accent=#00e5ff energy=high title="ORBIT QUEST" narration=off length=45 aspect=vertical',
                styles=STYLES)
    o = cmd.options
    assert o.style == "pixel" and not o.directed and o.voice is False and o.seconds == 45 and o.aspects == ["9:16"]
    cz = o.hints["customize"]
    assert cz["knobs"] == {"accent": "#00E5FF", "energy": "high", "title": "ORBIT QUEST", "narration": False,
                           "length": 45, "aspect": ["9:16"]} and cz["route"] == "quick"
    assert any(m.startswith("Settings:") for m in cmd.messages)
    # knobs survive the job round trip (job.json options)
    assert Options.from_dict(o.to_dict()).hints["customize"] == cz


def test_plain_commands_are_unchanged():
    for raw in ("", "pixel 60 vertical", "lore 30", "speedrun terminal both mute", "status", "revise slower start"):
        cmd = parse(raw, styles=STYLES)
        assert "customize" not in cmd.options.hints, raw


def test_unknown_knob_message_lists_valid_keys():
    cmd = parse("comic colr=red", styles=STYLES)
    assert cmd.options.style == "comic" and not cmd.options.directed
    assert any("Unknown setting 'colr'" in m and "accent" in m for m in cmd.messages)


def test_route_function_reasons():
    assert route(text="", preset_named=True)[0] == "quick"
    assert route(text="pink", preset_named=False)[0] == "directed"
    assert route(text="pink", preset_named=True, preset="launch")[0] == "customize"
    assert route(text="pink", preset_named=False, force="customize")[0] == "customize"


def test_tool_cli_and_api_entry_points():
    o = C.from_tool_args(Options(style="terminal"), {"style": "terminal", "customize": "green phosphor, faster",
                                                      "knobs": {"music": "dark"}})
    cz = o.hints["customize"]
    assert cz["text"] == "green phosphor, faster" and cz["knobs"]["music"] == "terminal_a" and not o.directed
    schema = {"name": "x", "parameters": {"type": "object", "properties": {}}}
    C.extend_schema(schema)
    assert {"customize", "knobs"} <= set(schema["parameters"]["properties"])
    import argparse
    ap = argparse.ArgumentParser()
    C.add_cli_args(ap)
    args = ap.parse_args(["--customize", "pink and playful", "--set", "accent=#ff00aa", "--set", "energy=high"])
    o = C.from_cli_args(Options(style="launch"), args)
    assert o.hints["customize"]["knobs"] == {"accent": "#FF00AA", "energy": "high"}
    opts, msgs, status = C.from_request(Options(style="comic").to_dict(), {"text": "neon villain", "knobs": {"accent": "cyan"}})
    assert status == 200 and opts["hints"]["customize"]["route"] == "customize"
    _o, msgs, status = C.from_request(Options().to_dict(), {"knobs": {"colr": "red"}})
    assert status == 400 and "Valid settings" in msgs[0]


def test_cli_set_keeps_spaces_in_one_value(capsys):
    """`--set "title=TEMPO QUEST"` keeps both words (it used to be cut at the space, silently)."""
    import argparse
    ap = argparse.ArgumentParser()
    C.add_cli_args(ap)
    args = ap.parse_args(["--set", "title=TEMPO QUEST", "--set", "cta=Start focusing now",
                          "--set", "accent=#ff00aa energy=high", "--set", "nonsense"])
    o = C.from_cli_args(Options(style="pixel"), args)
    knobs = o.hints["customize"]["knobs"]
    assert knobs["title"] == "TEMPO QUEST"
    assert knobs["cta"] == "Start focusing now"
    assert knobs["accent"] == "#FF00AA" and knobs["energy"] == "high"   # several knobs in one item still work
    assert "--set expects key=value" in capsys.readouterr().out       # a malformed item is reported, not dropped
    # the slash form keeps quoted values whole too
    ex = K.extract('pixel title="TEMPO QUEST" energy=high')
    assert ex.knobs["title"] == "TEMPO QUEST" and ex.rest == "pixel"


# ------------------------------------------------------------------------------------------- spec + weak models

SHOTS = [{"id": "s00_hook", "type": "HOOK", "scene": "kit:pixel/HOOK", "t0": 0, "t1": 2},
         {"id": "s01_title", "type": "TITLE", "scene": "kit:pixel/TITLE", "t0": 2, "t1": 5},
         {"id": "s02_feature", "type": "FEATURE", "scene": "kit:pixel/FEATURE", "t0": 5, "t1": 9},
         {"id": "s03_stats", "type": "STATS", "scene": "kit:pixel/STATS", "t0": 9, "t1": 12},
         {"id": "s04_screen", "type": "SCREEN", "scene": "kit:pixel/SCREEN", "t0": 12, "t1": 15},
         {"id": "s05_end", "type": "END", "scene": "kit:pixel/END", "t0": 15, "t1": 18}]


def test_validate_repairs_weak_model_output():
    raw = {"palette": "neon", "accent": "hot pink", "energy": "FAST", "music": "chiptune", "voice": "whispered",
           "mood": "x", "transitions": "whip", "captions": "subtle",
           "text": {"title": "ORBIT QUEST", "slogan": "x"},
           "shots": [{"id": "FEATURE", "text": {"headline": "A GIANT BUG APPEARS"}, "params": {"_mute": 1, "zoom": 2}},
                     {"id": "s01_title", "remove": True}, {"id": "nonsense"}, "junk",
                     {"id": "s03_stats", "text": {"value": "999", "label": "bugs squashed"}},
                     {"id": "ending", "hold": 9}],
           "order": ["s05_end", "s02_feature"]}
    spec, fixes = S.validate(raw, SHOTS, catalog={"kit:pixel/FEATURE": ["zoom"]}, style="pixel")
    assert spec["theme"] == {"palette": "neon", "accent": V.COLOURS["hotpink"]}
    assert spec["energy"] == "high" and spec["music"].startswith("pixel_") and spec["voice"] == {"style": "whisper"}
    assert spec["transitions"] == "punchy" and spec["captions"] == "minimal" and spec["text"] == {"title": "ORBIT QUEST"}
    by = {s["id"]: s for s in spec["shots"]}
    assert by["s02_feature"] == {"id": "s02_feature", "params": {"zoom": 2}, "text": {"headline": "A GIANT BUG APPEARS"}}
    assert "s01_title" not in by                                     # TITLE is never removed
    assert by["s03_stats"]["text"] == {"label": "bugs squashed"}     # numbers on STATS are facts
    assert by["s05_end"]["hold"] == S.MAX_HOLD
    assert spec["order"][-1] == "s05_end" and spec["order"][0] == "s02_feature"
    assert any("mood" in f for f in fixes) and any("nonsense" in f for f in fixes)
    assert S.validate("nope", SHOTS)[0] == {}


@pytest.mark.parametrize("text", [
    '```json\n{"theme": {"accent": "#FF4FA3"}, "energy": "high",}\n```',
    'Sure! Here is the customization: {"theme": {"palette": "pastel"}, "summary": "soft"} hope it helps',
    "{'energy': 'calm', 'music': 'calm'}",
    '{"theme": {"accent": "#00E5FF"}, "shots": [{"id": "s00_hook", "text": {"label": "GO"}}',   # truncated
])
def test_parse_json_tolerates_sloppy_replies(text):
    obj, err = S.parse_json(text)
    assert isinstance(obj, dict) and err == ""


class _Reply(SimpleNamespace):
    pass


def _fake(text=None, exc=None, error=""):
    calls = []

    def call(**kw):
        calls.append(kw)
        if exc:
            raise exc
        return _Reply(text=text or "", error=error, model="fake", parsed=None)
    call.calls = calls
    return call


def _pixel_film():
    tl = _tl(style="pixel")
    return film_from_timeline(tl, style="pixel", media_map=_media())["film"]


@pytest.mark.parametrize("fake,source", [
    (_fake('{"theme": {"palette": "neon"}, "shots": [{"id": "s00_hook", "text": {"label": "A GIANT BUG!"}}], '
           '"summary": "neon bug"}'), "llm"),
    (_fake('here: {"theme": {"palette": "neon", "font": "Comic Sans"}, "shots": [{"id": "HOOK", '
           '"params": {"made_up": 1}}],}'), "repaired"),
    (_fake("I cannot help with that."), "keywords"),
    (_fake(exc=TimeoutError("slow model")), "keywords"),
    (_fake("", error="hermes chat exit 1"), "keywords"),
    (None, "keywords"),
])
def test_customize_spec_always_yields_a_usable_spec(fake, source):
    film = _pixel_film()
    res = customize_spec("make the boss a giant bug and use neon colours", film, style="pixel", llm_call=fake)
    assert res["source"] == source
    assert res["spec"]["theme"]["palette"] == "neon"                # the keyword floor always holds
    if fake is not None and fake.calls:
        kw = fake.calls[0]
        assert kw["schema_name"] == "hype_customize" and "s00_hook" in kw["input_text"]
        assert "kit:pixel/HOOK" in kw["input_text"]                # the scene catalog for the used scenes


@pytest.mark.parametrize("text,style,check", [
    ("pink and playful with a punchier ending", "launch",
     lambda s: s["theme"]["accent"] == V.COLOURS["pink"] and s["music"].startswith(("comic", "ink")) and
     s["shots"][0]["id"] == "s06_end" and s["transitions"] == "punchy"),
    ("green phosphor hacker vibe, faster", "terminal",
     lambda s: s["theme"]["accent"] == V.COLOURS["phosphor"] and s["energy"] == "high"),
    ("the villain is a swarm of bugs, neon palette", "comic", lambda s: s["theme"]["palette"] == "neon"),
    ("moody blue night, slower, whispered narration", "cinematic",
     lambda s: s["energy"] == "calm" and s["voice"]["style"] == "whisper" and s["theme"]["bg"] and
     s["music"].startswith("cinematic")),
    ("warm narration please", "ink", lambda s: "palette" not in s.get("theme", {})),
])
def test_keyword_reader_for_the_demo_requests(text, style, check):
    rows = A.shot_rows(_tl(style=style))
    spec, _ = S.validate(S.keywords(text, rows, style=style), rows, style=style)
    assert check(spec), spec


# ------------------------------------------------------------------------------------------- theme + apply

def test_theme_tokens_map_onto_every_kit_family():
    tokens = TH.resolve({"palette": "neon", "font": "Bangers"}, None)
    v = TH.css_vars(tokens)
    for var in ("--sr-accent", "--sr-stage", "--sr-fg", "--ph", "--glass", "--sheet", "--cyan", "--cx-red",
                "--cx-paper", "--ik-terra", "--ik-paper", "--sr-f-display", "--cx-display", "--ik-title"):
        assert var in v, var
    pal = TH.kit_palettes(tokens)
    assert set(pal) == {"pixel", "comic", "ink"} and pal["pixel"]["gold"] == tokens["accent"]
    assert TH.terminal_phosphor({"accent": "#4BFF86"}) == "p1" and TH.terminal_phosphor({"accent": "#FFB13B"}) == "p3"
    assert TH.terminal_phosphor({"accent": "#00E5FF"}) == "#00E5FF"
    assert TH.font_faces(tokens)[0]["src"].startswith("kits/comic/fonts/")


@pytest.mark.parametrize("style", ["launch", "cinematic", "pixel", "terminal", "blueprint", "comic", "ink"])
def test_apply_film_stays_valid_for_every_preset(style, tmp_path):
    logo = ROOT / "tests" / "kits" / "fixtures" / "media" / "focusfox_home.png"
    tl = _tl(style=style)
    knobs, _ = K.normalise({"palette": "candy", "font": "Bangers", "energy": "high", "captions": "boxed",
                            "title": "ORBIT QUEST", "cta": "Try it today", "logo": str(logo), "music": "playful"},
                           style=style)
    spec = {"shots": [{"id": "s04_feature", "text": {"feature": "Neon mode"}}, {"id": "s02_code", "remove": True}]}
    _n, idmap = A.apply_timeline(tl, spec, energy="high")
    assert idmap["s04_feature"] == "s03_feature" and "s02_code" not in idmap
    spec = A.remap(spec, idmap)
    made = film_from_timeline(tl, style=style, media_map=_media())
    film = made["film"]
    notes = A.apply_film(film, made["assets"], style=style, knobs=knobs, spec=spec,
                         wrapped=style == "pixel", kit={})
    assert errors_of(validate_film(film)) == [], style
    assert film["theme"]["vars"]["--sr-accent"] == V.PALETTES["candy"]["accent"]
    assert film["music"][0]["bed"].startswith(("comic_", "ink_")) and film["caption_style"]["bg"].startswith("rgba(")
    assert any(f["family"] == "Bangers" for f in film["fonts"])
    assert any(o["scene"] == "kit:brand/logo" for o in film["overlays"]) and "brand_logo" in made["assets"]
    assert [s["id"] for s in film["shots"]][2] == "s02_terminal"
    words = json.dumps([s["params"] for s in film["shots"]])
    assert "ORBIT QUEST" in words and "Try it today" in words and "Neon mode" in words
    assert notes


def test_apply_timeline_keeps_narration_and_cues_with_their_shots():
    tl = _tl()
    feature = next(s for s in tl.scenes if s.type.value == "FEATURE")
    click = next(c for c in tl.cues if c.sfx == "click")
    off = click.t - feature.t0
    notes, _ids = A.apply_timeline(tl, {"shots": [{"id": "s02_code", "remove": True}, {"id": "s01_title", "hold": 1.0}]})
    assert [s.type.value for s in tl.scenes] == ["HOOK", "TITLE", "TERMINAL", "FEATURE", "STATS", "END"]
    assert tl.scenes[1].t1 - tl.scenes[1].t0 == pytest.approx(4.0)
    assert all(a.t1 == pytest.approx(b.t0) for a, b in zip(tl.scenes, tl.scenes[1:]))
    assert click.t - feature.t0 == pytest.approx(off)                 # the click moved with its shot
    assert tl.scenes[1].captions[0].t0 >= tl.scenes[1].t0
    assert tl.dur == pytest.approx(25.0 - 5.0 + 1.0) and any("dropped s02_code" in n for n in notes)
    tl2 = _tl()
    A.apply_timeline(tl2, {"order": ["s04_feature", "s00_hook"]})  # (notes, idmap)
    assert [s.type.value for s in tl2.scenes][:2] == ["FEATURE", "HOOK"] and tl2.dur == pytest.approx(25.0)


def test_transition_families():
    film = film_from_timeline(_tl(), media_map=_media())["film"]
    for fam, want in (("cut", set()), ("soft", {"crossfade"}), ("fade", {"dip-black"}), ("punchy", {"whip"})):
        f = copy.deepcopy(film)
        A.apply_film(f, {}, style="launch", knobs={"transitions": fam}, spec={})
        assert {t["type"] for t in f["transitions"]} == want, fam
        assert errors_of(validate_film(f)) == []
        if fam == "cut":
            assert all(a["t1"] == b["t0"] for a, b in zip(f["shots"], f["shots"][1:]))


def test_product_name_and_captions_off():
    film = film_from_timeline(_tl(), media_map=_media())["film"]
    A.apply_film(film, {}, style="launch", knobs={"product": "Orbit Notes", "captions": "off"}, spec={})
    assert "Focusfox" not in json.dumps([s["params"] for s in film["shots"]])
    assert film["captions"] == [] and not any("_captions" in s["params"] for s in film["shots"])


def test_model_cta_never_prints_code_or_a_new_command():
    """The customize model may reword the END as words, never as a line of code / a command the product never ran
    (W5 polish-2); the user's own cta= knob always wins."""
    def end_cta(f):
        return next(s["params"].get("cta") for s in f["shots"] if s["id"].endswith("_end"))
    film = film_from_timeline(_tl(), media_map=_media())["film"]
    before = end_cta(film)
    for bad in ("from patchlib import patch", "npm run dev", "Open it at localhost:5173"):
        f = copy.deepcopy(film)
        notes = A.apply_film(f, {}, style="launch", knobs={}, spec={"text": {"cta": bad}})
        assert end_cta(f) == before and any("not the product's own command" in n for n in notes), bad
    f = copy.deepcopy(film)
    A.apply_film(f, {}, style="launch", knobs={}, spec={"text": {"cta": "Grab it today"}})
    assert end_cta(f) == "Grab it today"
    f = copy.deepcopy(film)
    A.apply_film(f, {}, style="launch", knobs={"cta": "npm run dev"}, spec={"text": {"cta": "from x import y"}})
    assert end_cta(f) == "npm run dev"


# ------------------------------------------------------------------------------------------- pipeline hook

def test_hook_wraps_deps_and_caches_the_spec(tmp_path):
    from showreel_core.customize import hook as H
    from showreel_core.pipeline import Deps
    opts = Options(style="launch")
    opts, _ = C.set_customize(opts, text="pink and playful with a punchier ending, whispered narration",
                              knobs={"title": "ORBIT"}, preset_named=True)
    logs, tts_args, beds = [], [], []
    fake = _fake('{"theme": {"accent": "#FF4FA3", "accent2": "#FFD23A"}, "summary": "pink"}')
    store = SimpleNamespace(update=lambda *a, **k: None, job_dir=lambda j: tmp_path / j)
    run = SimpleNamespace(opts=opts, deps=Deps(), job_dir=tmp_path, job={}, job_id="j1", store=store,
                          host=SimpleNamespace(story_call=lambda: fake),
                          rep=SimpleNamespace(progress=lambda *a, **k: None), info=lambda m, **k: logs.append(m),
                          warn=lambda m: logs.append("WARN " + m))
    run.deps.tts = lambda dispatch, text, out, speed=None: dispatch("text_to_speech", {"text": text})
    run.deps.pick_bed = lambda style, seed, bed_id=None: beds.append(bed_id) or SimpleNamespace(bpm=120, id=bed_id)
    run.deps.quick_film = lambda tl, **kw: film_from_timeline(tl, style=kw["style"], media_map=_media())
    plan = H.install(run)
    assert plan and plan["plan"].get("style") == "whisper"
    assert run.opts.voice_speed == pytest.approx(0.94)        # whisper pace; "punchier ending" is not global energy
    assert "punchier ending" in run.opts.notes and "ORBIT" in run.opts.notes
    run.deps.tts(lambda name, args: tts_args.append(args), "hello", tmp_path / "a.wav")
    assert "instructions" in tts_args[0] and "whisper" in tts_args[0]["instructions"]
    run.deps.pick_bed("launch", 1)
    assert beds[-1].startswith(("comic", "ink"))                                 # playful bed before the film
    tl = _tl()
    made = run.deps.quick_film(tl, style="launch", aspect="16:9")
    assert made["film"]["theme"]["tokens"]["accent"] == "#FF4FA3" and len(fake.calls) == 1
    made2 = run.deps.quick_film(_tl(aspect="9:16"), style="launch", aspect="9:16")   # second aspect: no new call
    assert len(fake.calls) == 1 and made2["film"]["theme"]["tokens"]["accent"] == "#FF4FA3"
    saved = json.loads((tmp_path / "customize.json").read_text(encoding="utf-8"))
    assert saved["source"] == "llm" and saved["spec"]["theme"]["accent"] == "#FF4FA3"
    assert any(m.startswith("customization (llm") for m in logs)


def test_hook_is_a_no_op_without_customization(tmp_path, monkeypatch):
    from showreel_core.customize import hook as H
    monkeypatch.setattr(H, "settings_knobs", lambda: {})
    run = SimpleNamespace(opts=Options(style="pixel"), deps=object())
    assert H.install(run) is None and run.deps.__class__ is object


# ------------------------------------------------------------------------------------------- slow: real page

@pytest.mark.slow
@pytest.mark.parametrize("style,var,want", [
    ("launch", "--sr-accent", "#FF2BD6"), ("terminal", "--ph", "#FF2BD6"), ("blueprint", "--cyan", "#FF2BD6"),
    ("comic", "--cx-red", "#FF2BD6"), ("ink", "--ik-terra", "#FF2BD6"), ("cinematic", "--sr-accent", "#FF2BD6"),
])
def test_theme_vars_reach_the_rendered_page(style, var, want, tmp_path):
    import asyncio

    from showreel_core.film.page import build_job
    from showreel_core.render.workers import page_session
    tl = _tl(style=style)
    made = film_from_timeline(tl, style=style, media_map=_media())
    film = made["film"]
    A.apply_film(film, made["assets"], style=style, knobs={"palette": "neon", "accent": want}, spec={}, kit={})
    job = build_job(film, tmp_path / "job", assets=made["assets"])
    title = next(s for s in film["shots"] if s["id"].endswith("_title"))
    t = round((title["t0"] + title["t1"]) / 2, 2)

    async def go():
        async with page_session(job, "stage.html", w=960, h=540, gpu=False) as p:
            await p.seek(t)
            js = ("(() => { const el = document.querySelector('#sr-stage [class*=\"sr-theme-\"], #sr-stage .srb') || "
                  "document.querySelector('#sr-stage'); return getComputedStyle(el).getPropertyValue(%r).trim(); })()"
                  % var)
            return await p.evaluate(js), await p.evaluate("window.__sr.errors.slice()")
    val, errs = asyncio.run(go())
    assert val.upper() == want, (style, val)
    assert not errs, errs


@pytest.mark.slow
def test_pixel_palette_override_changes_the_drawn_pixels(tmp_path):
    import asyncio

    from showreel_core.film.dryrun import pixel_diff
    from showreel_core.film.page import build_job
    from showreel_core.render.workers import page_session
    pngs = []
    for k, knobs in enumerate(({}, {"palette": "neon"})):
        made = film_from_timeline(_tl(style="pixel"), style="pixel", media_map=_media())
        film = made["film"]
        if knobs:
            A.apply_film(film, made["assets"], style="pixel", knobs=knobs, spec={}, wrapped=True, kit={})
        job = build_job(film, tmp_path / f"job{k}", assets=made["assets"])

        async def go(job=job):
            async with page_session(job, "stage.html", w=960, h=540, gpu=False) as p:
                await p.seek(3.5)
                return await p.capture("png")
        pngs.append(asyncio.run(go()))
    changed, frac = pixel_diff(pngs[0], pngs[1])
    assert frac > 0.05, frac


def test_captions_follow_the_theme():
    term = {"font": "IBM Plex Mono", "color": "#FFB13B", "bg": "rgba(12,8,5,0.9)"}
    cs = A.theme_captions(term, {"accent": "#4BFF86", "bg": "#040905"}, "terminal")
    assert cs["color"] == "#4BFF86" and cs["bg"].startswith("rgba(")
    comic = A.theme_captions({"color": "#14110F", "bg": "#FFD23A"}, V.PALETTES["neon"], "comic")
    assert comic["bg"] == V.PALETTES["neon"]["accent3"] and comic["color"] in ("#0B0C10", "#FFFFFF")
    launch = A.theme_captions({"bg": "rgba(10,11,13,0.72)"}, {"bg": "#2A0E2E", "text": "#FFF4FB"}, "launch")
    assert launch["bg"] != "rgba(10,11,13,0.72)"
    assert A.theme_captions({"bg": "rgba(251,246,236,0.94)", "color": "#2B2622"}, {"bg": "#101010"}, "ink")["color"] == "#2B2622"


def test_high_energy_keeps_the_requested_length_with_cut_ins():
    """ISSUES #58: energy=high turned a requested 30 s film into 23.8 s. The dead air after each line now goes to
    cut-ins (closer framings of the product capture) and holds; the film keeps its length and stays valid."""
    from showreel_core.contracts import Caption
    tl = _tl()
    feature = next(s for s in tl.scenes if s.type.value == "FEATURE")
    feature.captions = [Caption(14.3, 15.5, "Dark mode, one tap.")]
    feature.vo_path, feature.vo_t0 = "voice/vo_04.wav", 14.3
    notes, idmap = A.apply_timeline(tl, {}, energy="high")
    assert tl.dur == pytest.approx(25.0, abs=0.01)
    types = [s.type.value for s in tl.scenes]
    assert types == ["HOOK", "TITLE", "CODE", "TERMINAL", "FEATURE", "SCREEN", "STATS", "END"], types
    cut = tl.scenes[5]
    assert cut.data["cutin"] is True and cut.data["image"]["path"] == feature.data["image"]["path"]
    assert not cut.vo_path and not cut.captions and CUTIN_MIN_S <= cut.t1 - cut.t0 <= CUTIN_MAX_S
    assert feature.t1 - feature.t0 < 5.0 and feature.captions[0].t1 <= feature.t1      # the dead air was cut
    assert all(a.t1 == pytest.approx(b.t0) for a, b in zip(tl.scenes, tl.scenes[1:]))
    assert idmap["s04_feature"] == "s04_feature" and idmap["s05_stats"] == "s06_stats"
    assert any("cut-in after s04_feature" in n for n in notes)
    assert any(c.sfx == "cut" and c.t == pytest.approx(cut.t0) for c in tl.cues)
    made = film_from_timeline(tl, media_map=_media())
    assert errors_of(validate_film(made["film"])) == []
    assert made["film"]["dur"] == pytest.approx(25.0, abs=0.01)


def test_high_energy_does_not_speed_up_the_narration():
    assert V.ENERGY_VOICE["high"] == 1.0 and V.ENERGY_VOICE["calm"] < 1.0


def test_playful_springs_the_type_and_brings_the_candy_palette():
    """'pink and playful' read as barely different from the preset: playful now means bouncy type motion (the theme
    layer's motion token -> kits/base entrance overshoot) and, without a named palette, the candy palette."""
    sp = S.keywords("pink and playful with a punchier ending", None, style="launch")
    assert sp["theme"]["motion"] == "bouncy" and sp["theme"]["palette"] == "candy"
    assert sp["theme"]["accent"] == V.COLOURS["pink"] and "energy" not in sp          # the ending is not the film
    tokens = TH.resolve(None, sp["theme"])
    block = TH.theme_block(tokens)
    assert block["motion"] == "bouncy" and block["vars"]["--sr-accent"] == V.COLOURS["pink"]
    assert block["vars"]["--sr-stage"] == V.PALETTES["candy"]["bg"]
    assert S.keywords("neon palette, playful", None)["theme"]["palette"] == "neon"       # a named palette wins
    assert "motion" not in (S.keywords("calm and premium", None).get("theme") or {})
    src = (ROOT / "kits" / "base" / "motion.js").read_text(encoding="utf-8")
    assert "MOTION.bouncy" in src and "setMotion" in (ROOT / "kits" / "base" / "scene.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("style", ["launch", "pixel", "comic"])
def test_model_params_with_wrong_types_or_nan_never_reach_the_film(style):
    """Audit 2026-11-11: a reply such as {"bbox": "the toggle", "click": NaN} passed validation (Python's json reads
    NaN) and reached film.json: the page's JSON.parse rejects NaN and a string bbox turns the kit camera into NaN."""
    pre = film_from_timeline(_tl(style=style), style=style, media_map=_media())["film"]
    feat = next(s for s in pre["shots"] if s["id"].endswith("_feature"))
    reply = ('{"shots": [{"id": "%s", "params": {"bbox": "the dark mode toggle", "click": NaN, '
             '"feature": "Neon mode"}}]}' % feat["id"])
    res = customize_spec("zoom into the toggle", pre, style=style, llm_call=_fake(reply), wrapped=style == "pixel")
    tl = _tl(style=style)
    _n, idmap = A.apply_timeline(tl, res["spec"])
    spec = A.remap(res["spec"], idmap)
    made = film_from_timeline(tl, style=style, media_map=_media())
    film = made["film"]
    notes = A.apply_film(film, made["assets"], style=style, knobs={}, spec=spec, wrapped=style == "pixel", kit={})
    json.dumps(film, allow_nan=False)                              # strict JSON: no NaN/Infinity anywhere
    assert errors_of(validate_film(film)) == []
    shot = next(s for s in film["shots"] if s["id"] == feat["id"])
    bbox = shot["params"].get("bbox")
    assert bbox is None or isinstance(bbox, list)
    assert any("dropped params" in n for n in notes) or "bbox" not in json.dumps(res["spec"])


@pytest.mark.parametrize("text", ["neon colours on a light background", "noir, white background",
                                  "sunset palette with a bright background"])
def test_palette_text_stays_readable_on_a_background_from_elsewhere(text):
    """Audit 2026-11-11: a dark palette's near-white text kept on a light stage from the same request made every
    word on screen invisible (contrast ~1.0)."""
    spec, _ = S.validate(S.keywords(text, [], style="launch"), [], style="launch")
    tokens = TH.resolve({}, spec.get("theme"))
    assert V.contrast(tokens["bg"], tokens["text"]) >= 4.5, tokens
    knob_tokens = TH.resolve({"bg": "#FFFFFF"}, {"palette": "neon"})          # knob bg + a palette from free text
    assert V.contrast(knob_tokens["bg"], knob_tokens["text"]) >= 4.5
    assert TH.resolve({"bg": "#FFFFFF", "text": "#EEEEEE"}, {})["text"] == "#EEEEEE"   # an explicit choice is kept


@pytest.mark.parametrize("text,bg,accent", [
    ("pastel palette but on a black background please", "#0A0A0C", None),
    ("on a dark background, pink accents", "#0A0A0C", "pink"),
    ("a hot pink background with blue text", "pink", "blue"),
])
def test_a_colour_background_is_the_stage_not_the_accent(text, bg, accent):
    """Audit 2026-11-11: "on a black background" made black the ACCENT and kept the light pastel stage."""
    theme = S.keywords(text, [], style="launch")["theme"]
    assert theme["bg"] == V.COLOURS.get(bg, bg)
    assert theme.get("accent") == (V.COLOURS[accent] if accent else None)


def test_product_rename_replaces_whole_words_only():
    """Audit 2026-11-11: product=Orbit on a product called "Arc" wrote "Orbithitecture"; "Go" -> "Zoomogle"."""
    out = A._replace_words({"headline": "Architecture by Arc", "lines": ["Arc's timer"], "t": "Go faster. Google it."},
                           "Arc", "Orbit")
    assert out["headline"] == "Architecture by Orbit" and out["lines"] == ["Orbit's timer"]
    assert A._replace_words("Go faster with Go. Google it.", "Go", "Zoom") == "Zoom faster with Zoom. Google it."
    assert A._replace_words("Focus/Fox (C++)", "C++", "D") == "Focus/Fox (D)"
