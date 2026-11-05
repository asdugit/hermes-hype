"""Quick-mode adapter (showreel_core/film/quick.py): Timeline -> film.json for the scene kits."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.contracts import Caption, Cue, SceneType, Split, Timeline, TimelineScene
from showreel_core.film.quick import (CLAIMS, film_from_timeline, kit_meta, readable_accent, scene_id,
                                      timeline_to_film)
from showreel_core.film.schema import errors_of, validate_film

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "tests" / "kits" / "fixtures" / "media"


def _scene(i, typ, t0, t1, data, tr="cut", caps=()):
    return TimelineScene(i=i, type=SceneType(typ), t0=t0, t1=t1, data=data, label="", transition_in=tr,
                         captions=[Caption(*c) for c in caps])


def _timeline(mode="product", style="launch", aspect="16:9", accent="") -> Timeline:
    img = {"kind": "image", "path": "assets/capture_home.png", "w": 1440, "h": 900, "url": "http://localhost:3000"}
    w, h = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    scenes = [
        _scene(0, "HOOK", 0.0, 2.0, {"hero": dict(img), "label": "Focusfox", "story_index": 0}),
        _scene(1, "TITLE", 2.0, 5.0, {"title": "Focusfox", "tagline": "A focus timer", "story_index": 1}, tr="push",
               caps=[(2.3, 4.0, "Meet Focusfox.")]),
        _scene(2, "CODE", 5.0, 10.0, {"path": "app.js", "lang": "js", "lines": ["const a = 1;"], "focus": [0, 0]}),
        _scene(3, "TERMINAL", 10.0, 14.0, {"cmd": "npm test", "output": ["12 passed"], "exit_code": 0, "tests_passed": 12}),
        _scene(4, "FEATURE", 14.0, 19.0, {"image": {**img, "path": "assets/capture_dark.png"}, "feature": "Dark mode",
                                          "bbox": [0.1, 0.1, 0.8, 0.8], "click": [0.5, 0.5]}, tr="match"),
        _scene(5, "STATS", 19.0, 22.0, {"stats": [{"key": "t", "value": 12, "label": "tests", "display": "12"}]}),
        _scene(6, "END", 22.0, 25.0, {"title": "Focusfox", "cta": "npx serve focusfox", "url": ""}, tr="push"),
    ]
    cues = [Cue(2.0, "whoosh", -8, "peak"), Cue(6.0, "type", -16, "onset"), Cue(12.4, "pass", -6, "onset"),
            Cue(16.25, "click", -10, "onset"), Cue(19.0, "riser", -10, "end"), Cue(19.0, "hit", -3, "onset")]
    splits = [Split("tests green", "e3", 1650.0, 12.4), Split("shipped", "e9", 2843.0, 21.0)] if mode == "speedrun" else []
    return Timeline(style=style, aspect=aspect, fps=30, w=w, h=h, dur=25.0, bpm=120.0, seed=3, scenes=scenes,
                    cues=cues, title="Focusfox", accent=accent, mode=mode, splits=splits)


MEDIA_MAP = {"assets/capture_home.png": str(MEDIA / "focusfox_home.png"),
             "assets/capture_dark.png": str(MEDIA / "focusfox_dark.png")}


def test_launch_film_is_valid_and_uses_launch_scenes():
    made = film_from_timeline(_timeline(), media_map=MEDIA_MAP)
    film = made["film"]
    assert errors_of(validate_film(film)) == []
    assert [s["scene"] for s in film["shots"]] == [f"kit:launch/{t}" for t in
                                                   ("HOOK", "TITLE", "CODE", "TERMINAL", "FEATURE", "STATS", "END")]
    assert all(s["params"]["theme"] == "launch" for s in film["shots"])
    assert "launch" in film["kits"]
    assert film["dur"] == 25.0 and film["size"] == [1920, 1080]
    assert made["scenes"] == {}
    assert timeline_to_film is film_from_timeline


def test_transitions_overlap_neighbours_centred_on_the_cut():
    film = film_from_timeline(_timeline(), media_map=MEDIA_MAP)["film"]
    trs = {(t["from"], t["to"]): t for t in film["transitions"]}
    by_id = {s["id"]: s for s in film["shots"]}
    assert set(t["type"] for t in trs.values()) == {"push-left", "crossfade"}
    for (a, b), t in trs.items():
        assert by_id[a]["t1"] == pytest.approx(t["t"] + t["dur"])
        assert by_id[b]["t0"] == pytest.approx(t["t"])
    # cut transitions leave shots butted
    assert by_id["s02_code"]["t1"] == by_id["s03_terminal"]["t0"] == 14.0 - 4.0


def test_media_registered_as_assets_with_names_in_params():
    made = film_from_timeline(_timeline(), media_map=MEDIA_MAP)
    film, assets = made["film"], made["assets"]
    hero = film["shots"][0]["params"]["hero"]
    feat = film["shots"][4]["params"]["image"]
    assert hero["asset"] in assets and feat["asset"] in assets and hero["asset"] != feat["asset"]
    assert Path(assets[hero["asset"]]["src"]).is_file()
    assert film["assets"][hero["asset"]] == {"type": "image"}
    assert film["meta"]["warnings"] == []


def test_missing_media_warns_and_keeps_meta(tmp_path):
    made = film_from_timeline(_timeline(), job_dir=tmp_path)
    assert made["assets"] == {}
    assert any("capture_home.png" in w for w in made["film"]["meta"]["warnings"])
    assert "asset" not in made["film"]["shots"][0]["params"]["hero"]


def test_cues_claimed_by_scenes_and_synced():
    tl = _timeline()
    film = film_from_timeline(tl, media_map=MEDIA_MAP)["film"]
    kept = {(c["t"], c["sfx"]) for c in film["cues"]}
    assert (16.25, "click") not in kept and (6.0, "type") not in kept and (12.4, "pass") not in kept
    assert {(2.0, "whoosh"), (19.0, "hit"), (19.0, "riser")} <= kept
    shots = {s["id"]: s for s in film["shots"]}
    assert shots["s04_feature"]["params"]["_sync"] == {"click": 2.25}
    assert shots["s03_terminal"]["params"]["_sync"] == {"pass": 2.4}
    assert shots["s05_stats"]["params"]["_mute"] == ["hit"]
    # the dataclass timeline's cues lose the claimed ones too (the pipeline mixes timeline + page cues)
    assert {(c.t, c.sfx) for c in tl.cues} == {(c["t"], c["sfx"]) for c in film["cues"]}
    assert film["meta"]["claimed_cues"] == 3


def test_claim_false_leaves_timeline_untouched():
    tl = _timeline()
    film_from_timeline(tl, media_map=MEDIA_MAP, claim=False)
    assert len(tl.cues) == 6


def test_captions_flag_their_shots():
    film = film_from_timeline(_timeline(), media_map=MEDIA_MAP)["film"]
    assert film["captions"] == [{"t0": 2.3, "t1": 4.0, "text": "Meet Focusfox."}]
    assert film["shots"][1]["params"]["_captions"] is True
    assert "_captions" not in film["shots"][0]["params"]
    assert film["caption_style"]["font"] == "Geist" and film["caption_style"]["size"] >= 42


def test_base_fallback_styles_reskin_base_scenes():
    for style in ("terminal", "blueprint", "comic", "ink"):
        film = film_from_timeline(_timeline(style=style), media_map=MEDIA_MAP)["film"]
        assert errors_of(validate_film(film)) == []
        assert all(s["scene"].startswith("kit:base/") for s in film["shots"]), style
        assert all(s["params"]["theme"] == style for s in film["shots"])
        assert all("accent" not in s["params"] for s in film["shots"])   # these styles keep their own accent


def test_unknown_style_falls_back_to_launch():
    film = film_from_timeline(_timeline(style="vaporwave"), media_map=MEDIA_MAP)["film"]
    assert film["meta"]["style"] == "launch"
    assert film["shots"][0]["scene"] == "kit:launch/HOOK"


def test_pixel_style_wraps_data_and_sets_res():
    film = film_from_timeline(_timeline(style="pixel", aspect="9:16"), aspect="9:16", media_map=MEDIA_MAP)["film"]
    assert errors_of(validate_film(film)) == []
    s0 = film["shots"][0]
    assert s0["scene"] == "kit:pixel/HOOK" and s0["res"] == [270, 480]
    assert set(s0["params"]) >= {"data", "image"} and s0["params"]["image"] == s0["params"]["data"]["hero"]["asset"]
    assert all(t["type"].startswith("kit:pixel/") for t in film["transitions"])


def test_project_accent_only_for_opt_in_kits_and_lifted_when_dark():
    assert readable_accent("#C9F25C") == "#C9F25C"
    assert readable_accent("0af") == "#00AAFF"
    dark = readable_accent("#1E3A8A")
    assert dark != "#1E3A8A" and dark.startswith("#")
    assert readable_accent("not a colour") == ""
    film = film_from_timeline(_timeline(accent="#1E3A8A"), media_map=MEDIA_MAP)["film"]
    assert {s["params"]["accent"] for s in film["shots"]} == {dark}


def test_speedrun_adds_the_timer_overlay_until_the_end_card():
    film = film_from_timeline(_timeline(mode="speedrun"), media_map=MEDIA_MAP)["film"]
    assert errors_of(validate_film(film)) == []
    (hud,) = film["overlays"]
    assert hud["scene"] == "kit:type/speedrun-timer" and hud["t0"] == 0.0 and hud["t1"] == 22.0
    assert [s["label"] for s in hud["params"]["splits"]] == ["tests green", "shipped"]
    assert hud["params"]["total_s"] == 2843.0


def test_dict_timeline_accepted():
    film = film_from_timeline(_timeline().to_dict(), media_map=MEDIA_MAP)["film"]
    assert len(film["shots"]) == 7


def test_scene_id_rules():
    assert scene_id("launch", "SCROLL") == "kit:launch/SCROLL"
    assert scene_id("terminal", "SCROLL") == "kit:base/SCROLL"
    assert scene_id("base", "HOOK") == "kit:base/HOOK"
    assert kit_meta("launch")["accent"] == "project"
    assert set(CLAIMS) <= {t.value for t in SceneType}
