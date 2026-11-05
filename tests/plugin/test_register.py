"""register() against a fake ctx, manifest/registration parity, and the command/tool/CLI handlers."""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from showreel_core import handlers
from showreel_core.config import Settings
from showreel_core.jobs import JobStore

from .fakes import ROOT, FakeCtx, load_plugin

MANIFEST = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("SHOWREEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SHOWREEL_VIDEOS_DIR", str(tmp_path / "videos"))
    return {"store": JobStore(tmp_path / "data"), "tmp": tmp_path}


# ------------------------------------------------------------------------ registration

def test_register_registers_everything_quickly() -> None:
    plugin = load_plugin()
    ctx = FakeCtx()
    t0 = time.perf_counter()
    plugin.register(ctx)
    assert time.perf_counter() - t0 < 2.0
    assert set(ctx.commands) == {"showreel"}
    assert ctx.commands["showreel"]["argument_mode"] == "text" and ctx.commands["showreel"]["args_hint"]
    assert set(ctx.tools) == set(plugin.TOOLS) == {"showreel_render", "showreel_status"}
    assert all(t["toolset"] == "showreel" for t in ctx.tools.values())
    assert set(ctx.cli) == {"showreel"} and set(ctx.aux) == {"showreel"}
    assert ctx.aux["showreel"]["defaults"] == {"timeout": 120}
    assert ctx.skills["showreel"]["path"].is_file() and len(ctx.unload) == 1


def test_register_does_not_import_the_heavy_stack() -> None:
    import subprocess
    import sys
    code = ("import importlib.util,sys;"
            f"spec=importlib.util.spec_from_file_location('p',r'{ROOT / '__init__.py'}',"
            f"submodule_search_locations=[r'{ROOT}']);m=importlib.util.module_from_spec(spec);sys.modules['p']=m;"
            "spec.loader.exec_module(m);"
            "sys.path.insert(0, r'" + str(Path(__file__).parent) + "');from fakes import FakeCtx;m.register(FakeCtx());"
            "heavy=[n for n in sys.modules if n.startswith('p.showreel_core.') and n.split('.')[2] in "
            "('pipeline','session','story','render','audio','film','director','qa','capture')];print(heavy)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_manifest_matches_registrations() -> None:
    plugin = load_plugin()
    ctx = FakeCtx()
    plugin.register(ctx)
    assert MANIFEST["name"] == "showreel" and MANIFEST["manifest_version"] == 2
    assert sorted(MANIFEST["provides_tools"]) == sorted(ctx.tools)
    assert MANIFEST["provides_hooks"] == list(plugin.HOOKS) == []
    assert MANIFEST["requires_hermes"] == ">=0.22.5"
    assert MANIFEST["license"] == "AGPL-3.0-or-later"
    assert MANIFEST["homepage"] == "https://github.com/asdugit/hermes-showreel"
    assert isinstance(MANIFEST["version"], str)


def test_config_schema_matches_settings() -> None:
    schema = MANIFEST["config_schema"]
    assert set(schema) == set(Settings.__dataclass_fields__)
    for key, spec in schema.items():
        assert spec["type"] in ("str", "int", "float", "bool"), key
        if "default" in spec:
            assert spec["default"] == getattr(Settings(), key), key
    assert "default" not in schema["narration_speed"]          # empty = the style's pace


def test_dashboard_manifest_and_skill() -> None:
    dash = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    assert dash["name"] == MANIFEST["name"] and dash["version"] == MANIFEST["version"]
    assert (ROOT / "dashboard" / dash["api"]).is_file()
    skill = (ROOT / "skills" / "showreel" / "SKILL.md").read_text(encoding="utf-8")
    front = yaml.safe_load(skill.split("---")[1])
    assert front["name"] == "showreel" and front["description"].startswith("Use when")
    assert "showreel_render" in skill and "MEDIA:" in skill


def test_tool_schemas_are_valid_function_schemas() -> None:
    for schema in (handlers.RENDER_SCHEMA, handlers.STATUS_SCHEMA):
        assert re.fullmatch(r"[a-z_]+", schema["name"])
        assert schema["parameters"]["type"] == "object" and schema["description"]
        json.dumps(schema)


# ------------------------------------------------------------------------- slash command

def _fake_run(store: JobStore, stage: str = "done") -> Any:
    def run_job(job_id: str, host: Any, *, store: JobStore = store, deps: Any = None, handle: Any = None) -> dict:
        out = Path(store.job_dir(job_id)) / "showreel_16x9.mp4"
        out.write_bytes(b"fake")
        fields: dict[str, Any] = {"stage": stage, "title": "Focusfox", "duration_s": 30.0}
        if stage == "done":
            fields.update(outputs={"16:9": str(out)}, delivered={"16:9": str(out)})
        else:
            fields["error"] = {"code": "render", "message": "boom", "hint": "try again"}
        return store.update(job_id, **fields)
    return run_job


def test_slash_blocking_surfaces_reply_with_media(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "run_job", _fake_run(env["store"]))
    ctx = FakeCtx(surface="telegram")
    reply = handlers.make_slash_handler(ctx)("pixel 30 vertical", session_id="sess-9", platform="telegram")
    assert "Focusfox" in reply and re.search(r"^MEDIA:.+showreel_16x9\.mp4$", reply, re.MULTILINE)
    job = env["store"].latest("sess-9")
    assert job["options"]["style"] == "pixel" and job["options"]["aspects"] == ["9:16"]
    assert job["surface"] == "telegram" and ctx.posted and "starting" in ctx.posted[0].texts[0]


def test_slash_failure_text(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "run_job", _fake_run(env["store"], "failed"))
    reply = handlers.slash(FakeCtx(surface="cli"), "", session_id="s")
    assert "failed: boom" in reply and "Hint: try again" in reply and "MEDIA:" not in reply


@pytest.mark.parametrize("surface", ["desktop", "tui", "acp"])
def test_slash_background_surfaces_answer_immediately(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                                      surface: str) -> None:
    import showreel_core.pipeline as pl
    started: list[str] = []
    monkeypatch.setattr(pl, "start_background", lambda job_id, host, **kw: started.append(job_id))
    monkeypatch.setattr(pl, "run_job", lambda *a, **k: pytest.fail("must not block on " + surface))
    reply = handlers.slash(FakeCtx(surface=surface), "lore", session_id="s1")
    assert started and started[0] in reply and "Making your showreel" in reply


def test_slash_needs_a_session_and_refuses_a_second_render(env: dict[str, Any],
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "start_background", lambda *a, **k: None)
    assert "Nothing to film yet" in handlers.slash(FakeCtx(), "")
    handlers.slash(FakeCtx(surface="desktop"), "", session_id="s1")
    second = handlers.slash(FakeCtx(surface="desktop"), "pixel", session_id="s1")
    assert "already in progress" in second


def test_slash_actions(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeCtx()
    assert "Usage: /showreel" in handlers.slash(ctx, "help")
    assert "launch" in handlers.slash(ctx, "styles")
    assert "No showreel yet" in handlers.slash(ctx, "status", session_id="s1")
    assert "Nothing to cancel" in handlers.slash(ctx, "cancel", session_id="s1")
    assert "no finished showreel" in handlers.slash(ctx, "revise more product", session_id="s1")
    job = env["store"].create("s1", {"style": "pixel"})
    assert job["id"] in handlers.slash(ctx, "status", session_id="s1")
    assert "Cancelling" in handlers.slash(ctx, "cancel", session_id="s1")
    assert env["store"].cancel_requested(job["id"])


def test_revise_reruns_the_last_film_with_notes(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "run_job", _fake_run(env["store"]))
    first = env["store"].create("s1", {"style": "terminal", "seconds": 90})
    env["store"].update(first["id"], stage="done")
    handlers.slash(FakeCtx(surface="cli"), "revise slower start", session_id="s1")
    job = env["store"].latest("s1")
    assert job["parent"] == first["id"]
    assert job["options"]["style"] == "terminal" and job["options"]["notes"] == "slower start"


def test_slash_handler_never_raises(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "slash", lambda *a, **k: 1 / 0)
    assert "internal error" in handlers.make_slash_handler(FakeCtx())("")


def test_settings_feed_the_defaults(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "start_background", lambda *a, **k: None)
    ctx = FakeCtx(surface="desktop", config={"default_style": "blueprint", "default_seconds": 30,
                                              "narration": False, "narration_speed": 1.2})
    handlers.slash(ctx, "", session_id="s2")
    o = env["store"].latest("s2")["options"]
    assert (o["style"], o["seconds"], o["voice"], o["voice_speed"]) == ("blueprint", 30, False, 1.2)


# --------------------------------------------------------------------------------- tools

def test_render_tool_waits_and_returns_media(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    store = env["store"]
    fake = _fake_run(store)

    def start_background(job_id: str, host: Any, *, store: JobStore, handle: Any = None, on_done: Any = None,
                         **_: Any) -> None:
        on_done(fake(job_id, host, store=store))
    monkeypatch.setattr(pl, "start_background", start_background)
    out = json.loads(handlers.render_tool(FakeCtx(), {"style": "pixel", "aspect": "both", "product": {
        "name": "Focusfox", "features": ["Timer"]}, "direction": ""}, session_id="s1"))
    assert out["success"] and out["status"] == "done"
    assert out["media_tag"] == f"MEDIA:{out['file_path']}" and out["file_path"].endswith(".mp4")
    opts = store.latest("s1")["options"]
    assert opts["aspects"] == ["16:9", "9:16"] and opts["brief"]["name"] == "Focusfox"


def test_render_tool_returns_early_when_the_budget_runs_out(env: dict[str, Any],
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    monkeypatch.setattr(pl, "start_background", lambda *a, **k: None)
    t0 = time.monotonic()
    out = json.loads(handlers.render_tool(FakeCtx(), {"wait_seconds": 0}, session_id="s1"))
    assert time.monotonic() - t0 < 2.0
    assert out["success"] and out["status"] == "queued" and "showreel_status" in out["message"]
    st = json.loads(handlers.status_tool(FakeCtx(), {"job_id": out["job_id"]}))
    assert st["job_id"] == out["job_id"] and st["status"] == "queued"


def test_tools_never_raise(env: dict[str, Any]) -> None:
    assert json.loads(handlers.render_tool(FakeCtx(), None))["success"] is False      # no session
    assert json.loads(handlers.render_tool(FakeCtx(), "garbage", session_id=""))["success"] is False
    st = json.loads(handlers.status_tool(FakeCtx(), {"styles": True}, session_id="none"))
    assert st["status"] == "none" and any(s["id"] == "launch" for s in st["styles"])


# ----------------------------------------------------------------------------------- CLI

def test_cli_parser_and_styles(env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser(prog="hermes showreel")
    handlers.cli_setup(parser)
    args = parser.parse_args(["render", "--session", "latest", "--style", "pixel", "--seconds", "30",
                              "--aspect", "both", "--no-voice"])
    assert (args.showreel_cmd, args.style, args.seconds, args.aspect, args.no_voice) == \
        ("render", "pixel", 30, "both", True)
    assert handlers.make_cli_handler(FakeCtx())(parser.parse_args(["styles"])) == 0
    assert "Showreel styles" in capsys.readouterr().out
    assert handlers.cli(FakeCtx(), parser.parse_args(["status"])) == 0


def test_unload_cancels_running_jobs(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.pipeline as pl
    called: list[float] = []
    monkeypatch.setattr(pl, "cancel_all", lambda wait_s=0.0: called.append(wait_s) or [])
    handlers.on_unload()
    assert called == [3.0]
