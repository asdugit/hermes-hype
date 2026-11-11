"""Pipeline end to end with fakes (no Chromium, no ffmpeg): story + timing are the real modules."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from showreel_core.config import Options
from showreel_core.llm import Host
from showreel_core.pipeline import (
    Reporter,
    cancel_all,
    run_job,
    start_background,
    words_per_minute,
)

from .conftest import FakeRender, Recorder, load_bundle, make_deps


class Handle:
    ok = True

    def __init__(self) -> None:
        self.texts: list[str] = []

    def edit(self, text: str) -> None:
        self.texts.append(text)


def _job(store: Any, **opts: Any) -> dict[str, Any]:
    return store.create("sess-1", Options(**opts).normalised().to_dict())


def _host(**kw: Any) -> tuple[Host, list[tuple[str, dict[str, Any]]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    host = Host(dispatch=lambda name, args, **k: "{}", broadcast=lambda e, p: events.append((e, p)), **kw)
    return host, events


def test_quick_film_end_to_end_to_a_fake_mp4(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    job = _job(store, style="launch", seconds=30, aspects=["16:9"])
    host, events = _host()
    handle = Handle()
    final = run_job(job["id"], host, store=store, deps=make_deps(rec), handle=handle)
    assert final["stage"] == "done", final.get("error")
    assert final["pct"] == 1.0
    out = Path(final["outputs"]["16:9"])
    assert out.is_file() and out.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
    delivered = Path(final["delivered"]["16:9"])
    assert delivered.parent == env["videos"] and delivered.read_bytes() == out.read_bytes()
    assert delivered.name.startswith("showreel-") and delivered.name.endswith("-16x9.mp4")
    assert final["storyboard_source"] == "heuristic"          # no model: heuristic storyboard
    assert final["storyboard"]["scenes"] and final["title"]
    assert set(final["stages"]) >= {"reading", "storyboard", "voice", "layout", "render", "mix", "qa"}
    assert final["contact_sheet"].endswith("contact_16x9.png")
    assert final["thumbs"] and final["duration_s"] > 0
    assert Path(final["timeline_paths"]["16:9"]).is_file()
    # the real timing solver drove the fakes: frames = dur * fps
    assert rec.calls["check_video"][0]["frames"] == round(final["duration_s"] * 30)
    # narration: one TTS call per narrated scene, placed in the mix
    assert rec.n("tts") >= 1 and rec.calls["mix"][0]["voices"] == rec.n("tts")
    assert rec.calls["mix"][0]["sfx"] > 0          # timeline cues + the page cue
    # progress fan-out: plugin events with increasing pct, the status message edited, final text has the title
    pcts = [p["pct"] for e, p in events if e == "job.progress" and p.get("pct") is not None]
    assert pcts and pcts == sorted(pcts) and pcts[-1] == 1.0
    assert any("render" in t for t in handle.texts) and final["title"] in handle.texts[-1]
    # job dir artefacts
    jd = store.job_dir(job["id"])
    for name in ("storyboard.json", "session.json", "qa_report.json", "layout_report.json", "voice/voice.json"):
        assert (jd / name).is_file(), name
    assert not list(jd.glob("chunks_*"))       # work dirs pruned


def test_both_aspects_render_and_share_one_mix(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    job = _job(store, seconds=30, aspects=["16:9", "9:16"])
    final = run_job(job["id"], _host()[0], store=store, deps=make_deps(rec))
    assert final["stage"] == "done"
    assert set(final["delivered"]) == {"16:9", "9:16"}
    sizes = {(r["w"], r["h"]) for r in rec.calls["render"]}
    assert sizes == {(1920, 1080), (1080, 1920)}
    assert rec.n("mix") == 1          # same timing and cues: the audio is mixed once


def test_preview_preset(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30, preview=True)["id"], _host()[0], store=store, deps=make_deps(rec))
    assert final["stage"] == "done"
    assert rec.calls["render"][0] == {"gpu": "auto", "workers": None, "w": 960, "h": 540, "fps": 15.0}


def test_tts_failure_degrades_to_captions_only(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, tts_fail=True))
    assert final["stage"] == "done"
    assert any("captions only" in w for w in final["warnings"])
    assert rec.calls["mix"][0]["voices"] == 0


def test_no_tts_service_and_voice_off(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], Host(), store=store, deps=make_deps(rec))
    assert final["stage"] == "done" and rec.n("tts") == 0
    assert any("text_to_speech is unavailable" in w for w in final["warnings"])
    rec2 = Recorder()
    final2 = run_job(_job(store, seconds=30, voice=False)["id"], _host()[0], store=store, deps=make_deps(rec2))
    assert final2["stage"] == "done" and rec2.n("tts") == 0


def test_render_failure_retries_in_software_mode(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, render_fail=1))
    assert final["stage"] == "done"
    assert [(r["gpu"], r["workers"]) for r in rec.calls["render"]] == [("auto", None), ("off", 1)]
    assert any("software mode" in w for w in final["warnings"])


def test_render_failing_twice_fails_the_job_with_the_error(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, render_fail=2))
    assert final["stage"] == "failed"
    assert final["error"]["code"] == "chunk_failed"


def test_mix_failures_fall_back_without_sfx(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, mix_fail=1))
    assert final["stage"] == "done"
    assert rec.calls["mix"][1]["sfx"] == 0
    assert any("without SFX" in w for w in final["warnings"])


def test_audio_that_cannot_be_mixed_still_delivers_a_silent_film(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, mix_fail=9))
    assert final["stage"] == "done" and rec.n("mux") == 0
    assert Path(final["outputs"]["16:9"]).is_file()
    assert any("silent" in w for w in final["warnings"])


def test_broken_style_falls_back_to_launch(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, style="pixel", seconds=30)["id"], _host()[0], store=store,
                    deps=make_deps(rec, broken_styles=("pixel",)))
    assert final["stage"] == "done" and final["style_used"] == "launch"
    assert [c["style"] for c in rec.calls["quick_film"]] == ["pixel", "launch"]


def test_missing_film_runtime_fails_cleanly(env: dict[str, Any]) -> None:
    from showreel_core.pipeline import StageError

    def missing(*a: Any, **k: Any) -> Any:
        raise StageError("film_runtime_missing", "the film runtime is not in this build")
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, quick_film=missing))
    assert final["stage"] == "failed" and final["error"]["code"] == "film_runtime_missing"
    assert rec.n("render") == 0


def test_empty_session_is_a_friendly_failure(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    empty = load_bundle()
    empty.events = []
    final = run_job(_job(store)["id"], _host()[0], store=store, deps=make_deps(rec, bundle=empty))
    assert final["stage"] == "failed" and final["error"]["code"] == "empty_session"
    assert "nothing to film" in final["error"]["message"]


def test_product_brief_overrides_the_inferred_product(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    job = _job(store, seconds=30, brief={"name": "Pomodorable", "features": ["Focus timer"], "url": "http://127.0.0.1:5173/"})
    final = run_job(job["id"], _host()[0], store=store, deps=make_deps(rec))
    assert final["stage"] == "done"
    assert final["product"]["name"] == "Pomodorable"
    assert final["product"]["features"][0] == "Focus timer"
    assert "http://127.0.0.1:5173/" in final["product"]["urls"]


def test_cancel_during_render(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    job = _job(store, seconds=30)

    def on_render(spec: Any, progress: Any, cancel: Any) -> None:
        store.request_cancel(job["id"])
        time.sleep(0.55)              # the cancel token polls the flag file at most every 0.5 s
        progress(1, 10, None)

    final = run_job(job["id"], _host()[0], store=store, deps=make_deps(rec, on_render=on_render))
    assert final["stage"] == "cancelled"
    assert rec.n("mix") == 0 and not final.get("delivered")


def test_cancel_all_stops_a_background_job(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    job = _job(store, seconds=30)
    started = []

    def on_render(spec: Any, progress: Any, cancel: Any) -> None:
        started.append(1)
        cancel.wait(5.0)

    th = start_background(job["id"], _host()[0], store=store, deps=make_deps(rec, on_render=on_render))
    for _ in range(100):
        if started:
            break
        time.sleep(0.05)
    assert cancel_all(wait_s=5.0) == [job["id"]]
    th.join(5.0)
    assert store.load(job["id"])["stage"] == "cancelled"


def test_directed_without_director_falls_back_to_quick_with_a_note(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    job = _job(store, seconds=30, style="pixel", direction="pixel but bloom into anime, sell it")
    final = run_job(job["id"], _host()[0], store=store, deps=make_deps(rec))
    assert final["stage"] == "done"
    assert any("Directed mode isn't in this build" in w for w in final["warnings"])
    assert rec.calls["quick_film"][0]["style"] == "pixel"


def test_directed_film_from_the_director(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    seen: dict[str, Any] = {}

    def director(*, direction: str, job_dir: Path, progress: Any, cancel: Any, seconds: int, **_: Any) -> dict:
        seen.update(direction=direction, seconds=seconds)
        progress("treatment", 0.5, "writing the treatment")
        film = {"version": 1, "fps": 30, "size": [1920, 1080], "dur": 12.0, "title": "Red Car",
                "shots": [{"id": "a", "t0": 0, "t1": 6, "scene": "kit:pixel/x"},
                          {"id": "b", "t0": 6, "t1": 12, "scene": "kit:nature/y"}],
                "music": [{"bed": "pixel_b", "t0": 0, "t1": 12}, {"sting": "riser", "t": 5.5}],
                "cues": [{"t": 3.0, "sfx": "hit"}]}
        return {"ok": True, "status": "done", "film": film, "job_dir": str(job_dir)}

    job = _job(store, seconds=45, direction="sell the red car as a boss fight")
    final = run_job(job["id"], _host()[0], store=store, deps=make_deps(rec, director=director))
    assert final["stage"] == "done", final.get("error")
    assert seen == {"direction": "sell the red car as a boss fight", "seconds": 45}
    assert final["title"] == "Red Car" and final["duration_s"] == 12.0
    assert rec.n("quick_film") == 0 and rec.n("tts") == 0
    assert rec.calls["place_sfx"][0] == 3       # explicit cue + sting + the page cue


def test_director_failure_falls_back_to_quick(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()

    def director(**_: Any) -> dict:
        return {"ok": False, "status": "failed", "fallback": "quick", "quick_style": "terminal", "error": "no bar"}

    final = run_job(_job(store, seconds=30, direction="make it moody")["id"], _host()[0], store=store,
                    deps=make_deps(rec, director=director))
    assert final["stage"] == "done"
    assert rec.calls["quick_film"][0]["style"] == "terminal"
    assert any("could not finish" in w for w in final["warnings"])


def test_rerender_reuses_the_storyboard_and_evidence_without_a_model_call(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    first = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec))
    sb = first["storyboard"]
    sb["scenes"][0]["vo"] = "An edited first line."

    calls: list[Any] = []

    def llm(**kw: Any) -> Any:
        calls.append(kw)
        raise AssertionError("no model call on a re-render")

    child = store.create("sess-1", Options(seconds=30, aspects=["9:16"]).to_dict(), parent=first["id"])
    store.update(child["id"], reuse_storyboard=sb)
    rec2 = Recorder()
    final = run_job(child["id"], Host(story_llm=llm, dispatch=lambda *a, **k: "{}"), store=store,
                    deps=make_deps(rec2))
    assert final["stage"] == "done" and final["storyboard_source"] == "reused"
    assert rec2.n("read_session") == 0 and not calls
    assert rec2.n("capture") == 0                         # captures come back with the saved evidence
    assert any(c["text"] == "An edited first line." for c in rec2.calls["tts"])


def _with_product() -> Any:
    from showreel_core.contracts import Product

    b = load_bundle()
    b.product = Product(name="Focusfox", kind="web_app", urls=["http://localhost:3000/"])
    b.product_detected = True
    return b


def test_product_capture_events_join_the_evidence(env: dict[str, Any]) -> None:
    from showreel_core.contracts import Event

    store, rec = env["store"], Recorder()
    shot = Path(env["tmp"]) / "cap.png"
    shot.write_bytes(b"\x89PNGfake")

    def capture(product: Any, events: list[Any], out_dir: Path, **kw: Any) -> list[Any]:
        rec.add("capture", len(events))
        assert kw["budget_s"] > 0 and kw["cancel"] is not None
        kw["progress"](1, 2, "desktop")
        return [Event("e900", 1.0, "product_capture", "showreel_capture", "Focusfox home", "captured",
                      {"path": str(shot), "url": "http://localhost:3000/", "viewport": [1920, 1080],
                       "full_page": False, "page_title": "Focusfox", "kind": "viewport"}, True, 0.95)]

    digests: list[int] = []
    deps = make_deps(rec, bundle=_with_product(), capture=capture,
                     digest=lambda b: digests.append(len(b.events)) or "DIGEST+CAPTURE")
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=deps)
    assert final["stage"] == "done" and rec.n("capture") == 1
    assert final["product"]["hero_event_ids"][0] == "e900"
    assert digests and digests[0] == rec.calls["capture"][0] + 1
    saved = json.loads((store.job_dir(final["id"]) / "session.json").read_text(encoding="utf-8"))
    assert saved["digest"] == "DIGEST+CAPTURE" and any(e["kind"] == "product_capture" for e in saved["events"])
    assert any("product capture: 1 shot" in str(e.get("msg", "")) for e in final.get("log", []))


def test_product_capture_failure_only_warns(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()

    def capture(*a: Any, **k: Any) -> list[Any]:
        raise RuntimeError("no chromium")

    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store,
                    deps=make_deps(rec, bundle=_with_product(), capture=capture))
    assert final["stage"] == "done"
    assert any("product capture failed" in str(e.get("msg", "")) for e in final.get("log", []))


def test_style_voice_speed_reaches_tts_and_wpm_is_logged(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, style="cinematic", seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec))
    assert final["stage"] == "done"
    assert {c["speed"] for c in rec.calls["tts"]} == {1.13}
    job = store.load(final["id"])
    msgs = [e["msg"] for e in job["log"]]
    assert any(m.startswith("narration pace x1.13 (style cinematic)") for m in msgs)
    assert any(" wpm" in m and m.startswith("narration scene") for m in msgs)
    assert job["narration"]["speed"] == 1.13 and job["narration"]["wpm"] == 156.0   # fake clips speak 2.6 w/s
    manifest = json.loads((store.job_dir(final["id"]) / "voice" / "voice.json").read_text(encoding="utf-8"))
    assert all(v["wpm"] == 156.0 and v["speed"] == 1.13 for v in manifest.values())


def test_launch_passes_no_speed_and_override_wins(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    run_job(_job(store, style="launch", seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec))
    assert {c["speed"] for c in rec.calls["tts"]} == {None}
    rec2 = Recorder()
    run_job(_job(store, style="cinematic", seconds=30, voice_speed=0.9)["id"], _host()[0], store=store,
            deps=make_deps(rec2))
    assert {c["speed"] for c in rec2.calls["tts"]} == {0.9}


def test_speed_refused_retries_at_normal_pace_and_conflicts_are_logged(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    deps = make_deps(rec, speed_check=lambda s: "tts.edge.speed=1.0 in config.yaml overrides the per-call speed")
    inner = deps.tts

    def picky(dispatch: Any, text: str, out: Path, speed: float | None = None) -> Any:
        return None if speed else inner(dispatch, text, out, None)
    deps.tts = picky
    final = run_job(_job(store, style="cinematic", seconds=30)["id"], _host()[0], store=store, deps=deps)
    assert final["stage"] == "done"
    assert any("overrides the per-call speed" in w for w in final["warnings"])
    assert any("refused speed x1.13" in w for w in final["warnings"])


def test_words_per_minute() -> None:
    assert words_per_minute("one two three four five six", 2.0) == 180.0
    assert words_per_minute("", 2.0) is None and words_per_minute("a b", 0) is None


def test_reporter_never_double_counts_a_reentered_stage(env: dict[str, Any]) -> None:
    store = env["store"]
    job = _job(store)
    rep = Reporter(store, job["id"], Host(), write_every=0.0)
    rep.stage("reading")
    rep.stage("storyboard")
    rep.stage("storyboard")
    rep.stage("voice")
    rep.progress(0.5, force=True)
    assert abs(store.load(job["id"])["pct"] - (0.04 + 0.14 + 0.04)) < 1e-6


def test_internal_errors_are_caught_and_logged(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()

    def boom(*a: Any, **k: Any) -> Any:
        raise ZeroDivisionError("kaboom")
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=make_deps(rec, solve=boom))
    assert final["stage"] == "failed"
    assert final["error"]["message"]
    assert FakeRender(True).ok


def test_post_plan_moves_the_finish_to_ffmpeg_and_keeps_style_chains() -> None:
    from showreel_core.pipeline import post_plan

    page, post, params = post_plan({"finish": {"grain": 0.035, "vignette": 0.22}})
    assert page == "stage.html?finish=post" and post == "grain_vignette" and params["grain_vignette"]["vignette"] == 0.22
    page, post, params = post_plan({"finish": {"grain": 0.03}, "render": {"post": "crt", "post_params": {"crt": {"glow": 0.6}}}},
                                   "stage.html?finish=page")
    assert page == "stage.html?finish=post" and post == "crt+grain_vignette" and params["crt"] == {"glow": 0.6}
    assert post_plan({"finish": {}})[1] == "none"


def test_directed_cue_sheet_narration_and_gpu_reach_the_back_half(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    seen: dict[str, Any] = {}
    vo = Path(env["tmp"]) / "vo.wav"
    vo.write_bytes(b"RIFFvo")

    def director(*, job_dir: Path, gpu: Any = None, voice_speed: Any = None, **_: Any) -> dict:
        seen.update(gpu=gpu, voice_speed=voice_speed)
        film = {"version": 1, "fps": 30, "size": [1920, 1080], "dur": 20.0, "title": "Red Car",
                "shots": [{"id": "a", "t0": 0, "t1": 10, "scene": "kit:pixel/x"},
                          {"id": "b", "t0": 10, "t1": 20, "scene": "kit:nature/y"}],
                "music": [{"bed": "pixel_b", "t0": 0, "t1": 10}, {"bed": "dream_a", "t0": 10, "t1": 20},
                          {"sting": "riser", "t": 9.5}],
                "narration": [{"path": str(vo), "start": 12.0, "duration": 4.5, "text": "Now it is real."}]}
        return {"ok": True, "status": "done", "film": film, "job_dir": str(job_dir)}

    fits: list[dict[str, Any]] = []

    def fit_music(bed: Any, duration: float, out: Path, drop: Any, last: Any) -> Any:
        fits.append({"dur": duration, "drop": drop, "last": last})
        out.write_bytes(b"RIFFmusic")
        return type("Fitted", (), {"path": out, "bed_id": bed.id, "bpm": bed.bpm, "warnings": []})()

    job = _job(store, seconds=30, direction="pixel boss fight then a meadow", voice_speed=1.1)
    final = run_job(job["id"], _host()[0], store=store, deps=make_deps(rec, director=director, fit_music=fit_music))
    assert final["stage"] == "done", final.get("error")
    assert seen == {"gpu": True, "voice_speed": 1.1}
    assert [round(f["dur"], 2) for f in fits] == [10.6, 10.0]           # first segment carries the crossfade
    assert fits[-1]["last"] == pytest.approx(6.5)                        # last word 16.5 s, in the 2nd segment
    assert rec.calls["join_music"] == [{"parts": 2, "xfade": 0.6}]
    assert any("music cue sheet" in str(e.get("msg", "")) for e in final.get("log", []))


def _stalling_layout(deps: Any, fatal: list[dict[str, Any]]) -> list[int]:
    """Wrap deps.layout_qa: the first len(fatal) calls return those fatals, then the real fake answers."""
    calls: list[int] = []
    real = deps.layout_qa

    def layout_qa(built: Any, times: list[float], thumbs_dir: Any) -> dict[str, Any]:
        calls.append(1)
        if len(calls) <= len(fatal):
            return {"fatal": fatal[len(calls) - 1]}
        return real(built, times, thumbs_dir)
    deps.layout_qa = layout_qa
    return calls


STALL = {"code": "cdp_timeout", "message": "Page.captureScreenshot timed out after 60s"}


def test_layout_qa_stall_is_retried_with_a_fresh_browser(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    deps = make_deps(rec)
    calls = _stalling_layout(deps, [STALL])
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=deps)
    assert final["stage"] == "done" and len(calls) == 2 and final["thumbs"]
    assert not any("skipped" in w for w in final.get("warnings") or [])


def test_layout_qa_stalling_twice_is_skipped_and_the_film_still_renders(env: dict[str, Any]) -> None:
    """Real E2E (pixel 30 both, busy machine): one capture stall in layout QA failed the whole film."""
    store, rec = env["store"], Recorder()
    deps = make_deps(rec)
    calls = _stalling_layout(deps, [STALL, STALL])
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=deps)
    assert final["stage"] == "done", final.get("error")
    assert len(calls) == 2 and rec.n("render") >= 1
    assert any("layout QA 16:9 skipped" in w for w in final["warnings"])


def test_a_page_that_cannot_load_still_fails(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    deps = make_deps(rec)
    _stalling_layout(deps, [{"code": "page_load", "message": "ReferenceError: __sr is not defined"}])
    final = run_job(_job(store, seconds=30)["id"], _host()[0], store=store, deps=deps)
    assert final["stage"] == "failed" and final["error"]["code"] == "page_broken"
