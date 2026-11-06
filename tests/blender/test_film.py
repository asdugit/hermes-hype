"""Blender pass of a film.json with a FAKE Blender: rewrite to kit:frames/play, handles, cues, cache, handoff, times."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from showreel_core.blender import film as bfilm
from showreel_core.blender import runner
from showreel_core.film.schema import errors_of, validate_film

FAKE = Path(__file__).with_name("fake_blender.py")


def cmd(job_path: Path) -> list[str]:
    return [sys.executable, str(FAKE), "--", str(job_path)]


def make_film(**over) -> dict:
    film = {
        "version": 1, "fps": 30, "size": [320, 180], "dur": 3.0, "seed": 7, "title": "t",
        "assets": {"shot": {"type": "image"}},
        "shots": [
            {"id": "intro", "t0": 0.0, "t1": 1.2, "scene": "kit:base/TITLE", "params": {"title": "Hi"}},
            {"id": "car", "t0": 1.0, "t1": 2.2, "scene": "blender:_test/hello", "params": {"color": "#FF0000",
                                                                                         "from_shot": "intro"}},
            {"id": "end", "t0": 2.2, "t1": 3.0, "scene": "blender:_test/hello", "params": {"from_shot": "car",
                                                                                         "media": "shot"}},
        ],
        "transitions": [{"from": "intro", "to": "car", "type": "crossfade", "t": 1.0, "dur": 0.2},
                        {"from": "car", "to": "end", "type": "crossfade", "t": 2.1, "dur": 0.3}],
        "cues": [{"t": 0.1, "sfx": "cut"}],
    }
    film.update(over)
    return film


def handoff_stub(calls):
    def fn(film, shot_id, t, res, out_png):
        from PIL import Image
        calls.append((shot_id, round(t, 3), tuple(res)))
        out_png.parent.mkdir(parents=True, exist_ok=True)
        Image.linear_gradient("L").resize(res).save(out_png)
        return out_png
    return fn


@pytest.fixture
def media(tmp_path):
    from PIL import Image
    p = tmp_path / "shot.png"
    Image.linear_gradient("L").resize((40, 30)).save(p)
    return {"shot": {"src": str(p), "type": "image"}}


def run_pass(tmp_path, film, media, **kw):
    calls: list = []
    kw.setdefault("handoff", handoff_stub(calls))
    bp = bfilm.render_film_shots(film, tmp_path / "job", blender=Path("unused"), tier="preview", assets=media,
                                 command=cmd, **kw)
    return bp, calls


def test_handles_and_res():
    film = make_film()
    assert bfilm.handles_for(film, film["shots"][1]) == (0.0, 0.2)          # car->end window ends 2.4 > t1 2.2
    assert bfilm.handles_for(film, film["shots"][2]) == (0.1, 0.0)          # window starts 2.1 < t0 2.2
    assert bfilm.render_res([1920, 1080], None, "preview") == (960, 540)
    assert bfilm.render_res([1080, 1920], None, "preview") == (540, 960)
    assert bfilm.render_res([1920, 1080], None, "final") == (1920, 1080)


def test_scene_ids():
    assert bfilm.scene_file("blender:_test/hello").is_file()
    for bad in ("blender:lib/entry", "blender:../x", "kit:base/TITLE", "blender:_test/../../x"):
        with pytest.raises(ValueError):
            bfilm.scene_file(bad)
    assert "blender:_test/hello" in bfilm.available_scenes(include_test=True)
    assert "blender:_test/hello" not in bfilm.available_scenes()
    info = bfilm.scene_info(bfilm.scene_file("blender:_test/hello"))
    assert info["params"]["spin"]["default"] == 90.0 and "cube" in info["describe"]


def test_schema_accepts_blender_shots_and_models():
    film = make_film(assets={"car3d": {"type": "model"}})
    assert not errors_of(validate_film(film))


def test_pass_rewrites_shots_merges_cues_and_hands_off(tmp_path, media):
    events = []
    bp, calls = run_pass(tmp_path, make_film(), media, progress=events.append)
    assert bp.ok, bp.errors
    shots = {s["id"]: s for s in bp.film["shots"]}
    assert shots["intro"]["scene"] == "kit:base/TITLE"
    assert shots["car"]["scene"] == bfilm.FRAMES_SCENE and shots["car"]["params"]["asset"] == "bl_car"
    assert shots["end"]["params"]["offset"] == 0.1
    man = bp.manifest["bl_end"]
    assert man["type"] == "frames" and man["count"] == round(0.9 * 30) and man["w"] == 320
    assert (tmp_path / "job" / "assets" / "bl_end" / "000001.jpg").is_file()
    assert bp.film["assets"]["bl_car"] == {"type": "frames"}
    # handoff: intro is a browser shot -> stub capture at its end; end <- car's last Blender frame
    assert calls == [("intro", round(1.2 - 0.5 / 30, 3), (320, 180))]
    end_job = json.loads((Path(bp.film["meta"]["blender"]["shots"]["end"]["hash"] and
                               tmp_path / "job" / "_blender" / bp.film["meta"]["blender"]["shots"]["end"]["hash"]
                               / "job.json")).read_text(encoding="utf-8"))
    assert end_job["handoff"]["from_shot"] == "car" and end_job["handoff"]["still"].endswith(".jpg")
    assert end_job["assets"]["shot"]["kind"] == "image"            # referenced by params.media
    # scene cue t=0.25 shot-local -> film time t0 + 0.25
    assert {"t": 1.25, "sfx": "whoosh", "gain_db": 0.0, "align": "auto"} in bp.film["cues"]
    assert {"t": 2.45, "sfx": "whoosh", "gain_db": 0.0, "align": "auto"} in bp.film["cues"]
    assert bp.eta_s is not None
    msgs = [e.get("message", "") for e in events]
    assert any(m.startswith("Blender shots: ~") for m in msgs)
    assert any(m.startswith("Blender: shot 2/2, frame") for m in msgs)
    assert not errors_of(validate_film(bp.film))


def test_cache_reuses_unchanged_shots(tmp_path, media):
    bp1, _ = run_pass(tmp_path, make_film(), media)
    calls_file = tmp_path / "job" / "_blender" / "fake_calls.txt"
    n1 = len(calls_file.read_text().splitlines())
    bp2, _ = run_pass(tmp_path, make_film(), media)
    assert bp2.ok and len(calls_file.read_text().splitlines()) == n1
    assert all(s["cached"] for s in bp2.shots) and "cache" in bp2.message
    film = make_film()
    film["shots"][2]["params"]["spin"] = 45                              # only "end" changes
    bp3, _ = run_pass(tmp_path, film, media)
    new = calls_file.read_text().splitlines()[n1:]
    end_hash = bp3.shots[1]["hash"]
    assert bp3.ok and [s["cached"] for s in bp3.shots] == [True, False]
    assert new and all(line.startswith(end_hash) for line in new)          # benchmark + rest of "end" only


def test_keyframe_times_render_only_needed_frames(tmp_path, media):
    bp, _ = run_pass(tmp_path, make_film(), media, times=[1.5, 2.5], benchmark=False)
    assert bp.ok
    car = sorted(p.name for p in (tmp_path / "job" / "assets" / "bl_car").iterdir())
    # car: t0=1.0, no pre handle -> t=1.5 is index 15 -> frame 16 (+ frame 1 for the poster)
    assert car == ["000001.jpg", "000016.jpg"]
    assert bfilm.frames_for_times({"t0": 2.2}, [2.5], 30, 0.1, 27) == [1, 13]


def test_failure_and_missing_blender(tmp_path, media):
    film = make_film()
    film["shots"][1]["params"]["_fake"] = "crash_exit0"
    bp, _ = run_pass(tmp_path, film, media)
    assert not bp.ok and "car" in bp.message and "traceback" in bp.message.lower()
    film = make_film()
    film["shots"][1]["scene"] = "blender:_test/nope"
    bp, _ = run_pass(tmp_path, film, media)
    assert not bp.ok and "not found" in bp.message
    missing = bfilm.render_film_shots(make_film(), tmp_path / "j2", config_path=str(tmp_path / "no-blender.exe"))
    assert not missing.ok and missing.missing and "hermes plugins install blender" in missing.message


def test_model_assets_go_to_blender_only(tmp_path, media):
    car = tmp_path / "car.glb"
    car.write_bytes(b"glTF" + b"\0" * 64)
    film = make_film(assets={"shot": {"type": "image"}, "car3d": {"type": "model"}})
    film["shots"][1]["params"]["product"] = "car3d"
    bp, _ = run_pass(tmp_path, film, {**media, "car3d": {"src": str(car), "type": "model"}})
    assert bp.ok
    assert "car3d" not in bp.film["assets"] and "car3d" not in bp.browser_assets
    h = bp.film["meta"]["blender"]["shots"]["car"]["hash"]
    job = json.loads((tmp_path / "job" / "_blender" / h / "job.json").read_text(encoding="utf-8"))
    assert job["product"] == "car3d" and job["assets"]["car3d"]["kind"] == "model"


def test_no_blender_shots_is_a_noop(tmp_path):
    film = {"version": 1, "fps": 30, "size": [320, 180], "dur": 1, "shots": [
        {"id": "a", "t0": 0, "t1": 1, "scene": "kit:base/TITLE", "params": {}}]}
    bp = bfilm.render_film_shots(film, tmp_path)
    assert bp.ok and bp.film["shots"] == film["shots"] and not bp.manifest


def test_runner_bench_frames_reused(tmp_path, media):
    bp, _ = run_pass(tmp_path, make_film(), media)
    calls = (tmp_path / "job" / "_blender" / "fake_calls.txt").read_text().splitlines()
    first = [c for c in calls if c.startswith(bp.shots[0]["hash"])]
    assert len(first) == 2 and json.loads(first[0].split(" ", 1)[1]) == runner.bench_frames(42)
    assert 1 not in (json.loads(first[1].split(" ", 1)[1]) or [])           # resume skipped benchmark frames
