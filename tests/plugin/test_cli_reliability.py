"""`hermes hype render` edge cases from the e2e audit: --json failures are JSON (E7), an unknown --style is refused
with the list (E10), an out-of-range --seconds is clamped with a note (E11), a second film of a session that is
already rendering is refused (C16); and the hype_render tool notes the same clamps."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from showreel_core import handlers
from showreel_core.jobs import JobStore

from .fakes import FakeCtx


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("HYPE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HYPE_VIDEOS_DIR", str(tmp_path / "videos"))
    import showreel_core.session as sess
    monkeypatch.setattr(sess, "resolve_session_ref", lambda ref: "" if ref == "nope" else "sess-1")
    monkeypatch.setattr(handlers, "_ensure_builtin_tools", lambda: None)
    seen: list[dict[str, Any]] = []

    def fake_run(job_id: str, host: Any, *, store: JobStore, handle: Any) -> dict[str, Any]:
        job = store.load(job_id)
        seen.append(job["options"])
        return store.update(job_id, stage="done", title="T", duration_s=15.0) or job
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "run_job", fake_run)
    return {"store": JobStore(tmp_path / "data"), "seen": seen}


def _args(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hermes hype")
    handlers.cli_setup(parser)
    return parser.parse_args(["render", *argv])


def test_json_failures_are_json(env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert handlers.cli(FakeCtx(), _args("--session", "nope", "--json")) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is False and "no session matches" in out["error"]


def test_unexpected_errors_are_json_too(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(handlers, "cli", lambda ctx, args: (_ for _ in ()).throw(RuntimeError("kaput")))
    assert handlers.make_cli_handler(FakeCtx())(_args("--json")) == 1
    assert json.loads(capsys.readouterr().out)["error"].endswith("kaput")


def test_unknown_style_is_refused_with_the_list(env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert handlers.cli(FakeCtx(), _args("--style", "vaporwave")) == 2
    out = capsys.readouterr().out
    assert "unknown style 'vaporwave'" in out and "launch" in out and "pixel" in out and "--direction" in out
    assert not env["seen"]                                  # nothing rendered
    assert handlers.cli(FakeCtx(), _args("--style", "Pixel")) == 0 and env["seen"][-1]["style"] == "pixel"


@pytest.mark.parametrize(("asked", "used"), [("0", 15), ("9999", 180), ("5", 15)])
def test_out_of_range_seconds_are_clamped_with_a_note(env: dict[str, Any], capsys: pytest.CaptureFixture[str],
                                                      asked: str, used: int) -> None:
    assert handlers.cli(FakeCtx(), _args("--seconds", asked)) == 0
    assert env["seen"][-1]["seconds"] == used
    assert f"note: length {asked} s is outside 15-180 s; using {used} s" in capsys.readouterr().out


def test_json_run_carries_the_notes(env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert handlers.cli(FakeCtx(), _args("--seconds", "9999", "--json")) == 0
    cap = capsys.readouterr()
    payload = json.loads(cap.out)                           # stdout is exactly one JSON object
    assert payload["notes"] == ["length 9999 s is outside 15-180 s; using 180 s"]
    assert "note: length 9999" in cap.err                   # progress and notes go to stderr


def test_cli_refuses_a_second_film_of_a_session_that_is_rendering(env: dict[str, Any],
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    running = env["store"].create("sess-1", {}, surface="desktop")
    env["store"].update(running["id"], stage="render")
    assert handlers.cli(FakeCtx(), _args("--seconds", "30")) == 1
    assert "already in progress" in capsys.readouterr().out and running["id"]
    assert not env["seen"]


def test_render_tool_notes_clamped_seconds_and_unknown_styles(env: dict[str, Any],
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl

    def start_background(job_id: str, host: Any, *, store: JobStore, handle: Any = None, on_done: Any = None,
                         **_: Any) -> None:
        final = store.update(job_id, stage="done", title="T")
        if on_done:
            on_done(final)
    monkeypatch.setattr(pl, "start_background", start_background)
    out = json.loads(handlers.render_tool(FakeCtx(), {"seconds": 0, "style": "vaporwave", "wait_seconds": 1},
                                          session_id="sess-t"))
    job = env["store"].latest("sess-t")
    assert job["options"]["seconds"] == 15 and job["options"]["style"] == "launch"
    assert any("outside 15-180" in n for n in out["notes"]) and any("vaporwave" in n for n in out["notes"])
