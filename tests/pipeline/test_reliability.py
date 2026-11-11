"""Pipeline reliability fixes from the e2e audit: honest notes when the model is rate-limited (E3) or every Directed
call failed (E8), no trailer for a chat that built nothing (E9), no retry noise in a delivered film's notes (E14),
no duplicate copy of each film (E17), a tighter evidence filter (C18) and a Directed ETA that fits the model (E16)."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from showreel_core import llm as L
from showreel_core.config import Options
from showreel_core.contracts import Event
from showreel_core.deliver import done_text, failed_text
from showreel_core.llm import Host, JsonModeLlm
from showreel_core.pipeline import (
    DIRECTOR_COMPOSE_ESTIMATE_S,
    built_anything,
    director_path,
    initial_estimates,
    own_output_event,
    run_job,
)

from .conftest import FakeRender, Recorder, load_bundle, make_deps


class RateLimitError(Exception):
    status_code = 429


class BusyLlm:
    """A model route that answers every call with HTTP 429 (Anthropic during the audit)."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_structured(self, **kwargs: Any) -> Any:
        self.calls += 1
        raise RateLimitError("Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error'}, "
                             "'request_id': 'req_011Cgw'}")


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(L, "RETRY_DELAYS_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(JsonModeLlm, "plain_only", False)


def _job(store: Any, session: str = "sess-1", **opts: Any) -> dict[str, Any]:
    return store.create(session, Options(**opts).normalised().to_dict())


def _host(llm: Any = None) -> Host:
    return Host(llm=llm, dispatch=lambda name, args, **k: "{}")


def test_a_rate_limited_storyboard_says_so_and_was_retried(env: dict[str, Any]) -> None:
    store, busy = env["store"], BusyLlm()
    final = run_job(_job(store, seconds=30)["id"], _host(busy), store=store, deps=make_deps(Recorder()))
    assert final["stage"] == "done" and final["storyboard_source"] == "heuristic"
    assert busy.calls >= 1 + len(L.RETRY_DELAYS_S)            # the first call was retried, not re-sent 0.1 s later
    text = done_text(final, media=False)
    assert "rate-limited" in text and "own storyboard" in text
    assert "could not be used" not in text and "req_" not in text


def _chat_only() -> Any:
    b = load_bundle()
    b.events = [Event(id="e1", t=0.0, kind="user_prompt", tool="", summary="", title="What's a good name for a cat?"),
                Event(id="e2", t=4.0, kind="final_answer", tool="", summary="", title="How about Miso, Pixel or Biscuit?")]
    b.product_detected = False
    return b


def test_a_chat_that_built_nothing_gets_one_friendly_line_and_no_render(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=15)["id"], _host(), store=store, deps=make_deps(rec, bundle=_chat_only()))
    assert final["stage"] == "failed" and final["error"]["code"] == "nothing_built"
    assert rec.n("render") == 0 and rec.n("capture") == 0
    text = failed_text(final)
    assert "hasn't built anything" in text and "/hype lore" in text and "failed" not in text


def test_lore_or_a_direction_still_films_a_chat(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    final = run_job(_job(store, seconds=15, mode="lore")["id"], _host(), store=store,
                    deps=make_deps(rec, bundle=_chat_only()))
    assert final["stage"] == "done", final.get("error")


def test_a_debugging_session_is_filmable() -> None:
    events = [Event(id="e1", t=0, kind="user_prompt", tool="", summary="", title="fix the crash"),
              Event(id="e2", t=1, kind="file_patch", tool="", summary="", title="app.py"),
              Event(id="e3", t=2, kind="terminal", tool="", summary="", title="pytest")]
    assert built_anything(events) and built_anything(load_bundle().events)
    assert not built_anything(events[:1])


def _directed_film() -> dict[str, Any]:
    return {"version": 1, "fps": 30, "size": [1920, 1080], "dur": 12.0, "title": "Tempo",
            "shots": [{"id": "a", "t0": 0, "t1": 12, "scene": "kit:base/card"}]}


def test_a_directed_film_whose_model_calls_all_failed_carries_a_warning(env: dict[str, Any]) -> None:
    store = env["store"]

    def director(*, llm: Any, job_dir: Path, **_: Any) -> dict[str, Any]:
        for purpose in ("pick", "words", "critic"):        # the engine degrades per call, as the real one does
            try:
                llm.complete_structured(instructions=purpose, input=[], json_mode=True, timeout=60)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "status": "done", "film": _directed_film(), "job_dir": str(job_dir)}

    final = run_job(_job(store, seconds=15, direction="a 1980s VHS infomercial", effort="quick")["id"],
                    _host(BusyLlm()), store=store, deps=make_deps(Recorder(), director=director))
    assert final["stage"] == "done"
    assert "rate-limited for every call" in final["model_note"] and "default plan" in final["model_note"]
    assert "⚠" in done_text(final, media=False)


def test_a_directed_film_with_a_working_model_has_no_warning(env: dict[str, Any]) -> None:
    store = env["store"]

    class Fine:
        def complete_structured(self, **kwargs: Any) -> Any:
            return SimpleNamespace(text="{}", parsed={}, content_type="json")

    def director(*, llm: Any, job_dir: Path, **_: Any) -> dict[str, Any]:
        llm.complete_structured(instructions="pick", input=[], json_mode=True, timeout=60)
        return {"ok": True, "status": "done", "film": _directed_film(), "job_dir": str(job_dir)}

    final = run_job(_job(store, seconds=15, direction="noir")["id"], _host(Fine()), store=store,
                    deps=make_deps(Recorder(), director=director))
    assert final["stage"] == "done" and not final.get("model_note")


def test_a_director_flag_is_read_when_present(env: dict[str, Any]) -> None:
    store = env["store"]

    def director(*, job_dir: Path, **_: Any) -> dict[str, Any]:
        return {"ok": True, "status": "done", "film": _directed_film(), "job_dir": str(job_dir),
                "model_unavailable": True}

    final = run_job(_job(store, seconds=15, direction="noir")["id"], _host(), store=store,
                    deps=make_deps(Recorder(), director=director))
    assert final.get("model_note")


def test_a_render_chunk_retry_that_worked_is_not_a_user_note(env: dict[str, Any]) -> None:
    store = env["store"]

    def render(spec: Any, progress: Any, cancel: Any) -> Any:
        Path(spec.out_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        return FakeRender(True, str(spec.out_path), warnings=[
            "worker 1: chunk 1 attempt 1 failed: [cdp_timeout] Page.captureScreenshot timed out after 8s"])

    final = run_job(_job(store, seconds=15)["id"], _host(), store=store, deps=make_deps(Recorder(), render=render))
    assert final["stage"] == "done"
    assert not any("attempt 1 failed" in w for w in final["warnings"])
    assert "attempt 1 failed" not in done_text(final, media=False)


def test_the_delivered_film_is_not_a_second_copy(env: dict[str, Any]) -> None:
    from showreel_core.deliver import deliver
    master = env["tmp"] / "hype_16x9.mp4"
    master.write_bytes(b"x" * 4096)
    env["videos"].mkdir(exist_ok=True)
    out = deliver(master, title="Tempo", job_id="20261111-000000-abcd", aspect="16:9", dest=env["videos"])
    assert out.read_bytes() == master.read_bytes()
    assert os.path.samefile(out, master) and os.stat(master).st_nlink >= 2     # one file on disk, two names
    master.unlink()                                                              # pruning the job keeps the film
    assert out.read_bytes() == b"x" * 4096


def test_the_delivered_film_falls_back_to_a_copy(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from showreel_core import deliver as D
    master = env["tmp"] / "hype_9x16.mp4"
    master.write_bytes(b"y" * 128)
    env["videos"].mkdir(exist_ok=True)

    def no_link(*_a: Any) -> None:
        raise OSError(18, "Invalid cross-device link")
    monkeypatch.setattr(D.os, "link", no_link)
    out = D.deliver(master, title="Tempo", job_id="20261111-000000-abcd", aspect="9:16", dest=env["videos"])
    assert out.read_bytes() == b"y" * 128 and not os.path.samefile(out, master)


@pytest.mark.parametrize(("text", "dropped"), [
    ("Add a hype meter to the dashboard", False),
    ("The Hype Board shows trending posts", False),
    ("/hype pixel 30", True),
    ("Here is your hype trailer", True),
    ("hype_render finished: job 20261111-171905-b024", True),
    ("/showreel lore 60", True),
    ("Here's your Showreel film", True),
])
def test_only_talk_about_the_films_is_dropped_after_the_first_film(text: str, dropped: bool) -> None:
    ev = Event(id="e9", t=9.0, kind="user_prompt", tool="", summary="", title=text)
    assert own_output_event(ev, [], True) is dropped


def test_a_directed_eta_fits_a_small_model() -> None:
    """Real E2E: a haiku quick Directed film announced ~17 min and took 3-4."""
    opts = Options(seconds=20, direction="a 1980s VHS infomercial", effort="quick").normalised()
    assert director_path("claude-haiku-4-5") == "compose" and director_path("claude-opus-4-6") == "free"
    _, story = initial_estimates(opts, "compose")
    assert story == DIRECTOR_COMPOSE_ESTIMATE_S["quick"] <= 240


def test_the_directed_eta_follows_the_directors_pace(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from showreel_core import pipeline as P
    store = env["store"]
    job = _job(store, seconds=20, direction="noir", effort="quick")
    rep = P.Reporter(store, job["id"], Host())
    rep.storyboard_estimate_s = 840.0
    rep.stage("storyboard", "planning")
    rep.t_stage -= 60.0                                       # one minute in, the Director says it is half done
    assert rep._estimate(0.5) < rep._estimate(0.0) - 600
