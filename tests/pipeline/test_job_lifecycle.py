"""Job lifecycle edge cases: a full disk mid-film, the end-of-job writes failing, crash/reboot leftovers and the
second copy of ``showreel_core`` that the Desktop API loads in the same process."""
from __future__ import annotations

import errno
import importlib
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import showreel_core.jobs as jobs_mod
from showreel_core import handlers
from showreel_core.config import Options
from showreel_core.jobs import JobStore, live_ids, process_started
from showreel_core.llm import Host
from showreel_core.pipeline import DISK_FULL_ERROR, disk_full, run_job, running_ids

from .conftest import Recorder, make_deps

ROOT = Path(__file__).resolve().parents[2]


def _job(store: JobStore, **opts: Any) -> dict[str, Any]:
    return store.create("sess-1", Options(**opts).normalised().to_dict())


def _host() -> Host:
    return Host(dispatch=lambda name, args, **k: "{}")


def _enospc(*_a: Any, **_k: Any) -> Any:
    raise OSError(errno.ENOSPC, "No space left on device", "C:/Users/someone/huge/frame_0001.jpg")


def test_disk_full_mid_film_fails_with_clear_advice(env: dict[str, Any]) -> None:
    store = env["store"]
    job = _job(store, seconds=30)
    final = run_job(job["id"], _host(), store=store, deps=make_deps(Recorder(), solve=_enospc))
    assert final["stage"] == "failed"
    assert final["error"]["code"] == "disk_full"
    assert final["error"]["message"] == DISK_FULL_ERROR["message"] and "Free" in final["error"]["hint"]
    assert "someone" not in final["error"]["message"]          # no machine path in what the user reads
    assert store.load(job["id"])["stage"] == "failed"
    assert job["id"] not in running_ids() and job["id"] not in live_ids()


def test_run_job_never_raises_when_the_final_writes_fail(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The disk is so full that even job.json cannot be written at the end: no exception escapes, the caller still
    gets the failure, nothing stays registered as running, and the stale sweep can fail the record later."""
    store = env["store"]
    job = _job(store, seconds=30)
    real = jobs_mod.write_json_atomic
    broken = {"on": False}

    def maybe_full(path: Path, data: Any, retries: int = 8) -> None:
        if broken["on"]:
            _enospc()
        real(path, data, retries)

    def solve(*_a: Any, **_k: Any) -> Any:
        broken["on"] = True
        _enospc()

    monkeypatch.setattr(jobs_mod, "write_json_atomic", maybe_full)
    final = run_job(job["id"], _host(), store=store, deps=make_deps(Recorder(), solve=solve))
    assert final["stage"] == "failed" and final["error"]["code"] == "disk_full"
    assert job["id"] not in running_ids() and job["id"] not in live_ids()
    monkeypatch.setattr(jobs_mod, "write_json_atomic", real)
    assert store.load(job["id"])["stage"] not in ("done", "failed")     # the record could not be updated ...
    assert job["id"] in store.mark_stale(now=time.time() + 60, active_ids=set(running_ids()))   # ... the sweep fails it


def test_atomic_write_leaves_no_temp_file_when_the_disk_is_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "job.json"

    def full(self: Path, *_a: Any, **_k: Any) -> int:
        self.open("w").close()                                   # the temp file exists, then the write fails
        _enospc()
        return 0

    monkeypatch.setattr(Path, "write_text", full)
    with pytest.raises(OSError):
        jobs_mod.write_json_atomic(target, {"a": 1})
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_disk_full_detection() -> None:
    assert disk_full(OSError(errno.ENOSPC, "full"))
    try:
        try:
            _enospc()
        except OSError as inner:
            raise RuntimeError("render failed") from inner
    except RuntimeError as outer:
        assert disk_full(outer)
    assert not disk_full(OSError(errno.EACCES, "denied")) and not disk_full(ValueError("x")) and not disk_full(None)


def test_a_stage_reporting_no_space_as_text_gets_the_same_advice(env: dict[str, Any]) -> None:
    from showreel_core.pipeline import StageError

    def solve(*_a: Any, **_k: Any) -> Any:
        raise StageError("render", "ffmpeg: av_interleaved_write_frame(): No space left on device")
    store = env["store"]
    final = run_job(_job(store, seconds=30)["id"], _host(), store=store, deps=make_deps(Recorder(), solve=solve))
    assert final["stage"] == "failed" and final["error"]["code"] == "disk_full"


def test_user_facing_error_for_a_full_disk_has_no_traceback_or_path() -> None:
    text = handlers._error_text(OSError(errno.ENOSPC, "No space left on device", "C:/Users/someone/x.tmp"))
    assert "someone" not in text and "Free" in text


def test_cli_handler_turns_unexpected_errors_into_one_line(monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    def boom(_ctx: Any, _args: Any) -> int:
        _enospc()
        return 0
    monkeypatch.setattr(handlers, "cli", boom)
    code = handlers.make_cli_handler(object())(object())
    out = capsys.readouterr().out
    assert code == 1 and "Traceback" not in out and out.startswith("hype: ") and "someone" not in out


# ----------------------------------------------------------------------------------- crash / reboot leftovers

def test_job_whose_pid_was_reused_after_a_crash_is_stale(tmp_path: Path) -> None:
    """After a crash or reboot the OS hands the old pid to another process: the job must not block /hype for an
    hour (the pid alone said 'alive')."""
    if process_started() is None:
        pytest.skip("psutil unavailable")
    store = JobStore(tmp_path)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = store.create("s", {})
        # the record names a pid that is alive now, but that process started long after the job's runner did
        store.update(job["id"], stage="render", pid=other.pid, pid_started=(process_started(other.pid) or 0) - 3600)
        assert store.mark_stale(now=time.time() + 120, active_ids=set()) == [job["id"]]
        # a record written before pid_started existed keeps the old pid-only rule
        old = store.create("s2", {})
        store.update(old["id"], stage="render", pid=other.pid, pid_started=None)
        assert store.mark_stale(now=time.time() + 120, active_ids=set()) == []
    finally:
        other.kill()
        other.wait(10)


def test_own_pid_reused_by_a_new_process_is_stale_even_without_active_ids(tmp_path: Path) -> None:
    """The new Hermes process got the crashed one's pid: the dashboard's sweep (no active_ids) must still see it."""
    if process_started() is None:
        pytest.skip("psutil unavailable")
    store = JobStore(tmp_path)
    job = store.create("s", {})
    store.update(job["id"], stage="render", pid=os.getpid(), pid_started=(process_started() or 0) - 3600)
    assert store.mark_stale(now=time.time() + 120) == [job["id"]]


def test_new_jobs_record_their_process_start(tmp_path: Path) -> None:
    job = JobStore(tmp_path).create("s", {})
    assert job["pid"] == os.getpid() and job["pid_started"] == process_started()


def test_a_crashed_job_marked_stale_frees_its_render_chunks(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job = store.create("s", {})
    store.update(job["id"], stage="render", pid=2 ** 30)              # its process is gone
    chunks = store.job_dir(job["id"]) / "video_16x9.chunks"
    chunks.mkdir()
    (chunks / "chunk_0000.mp4").write_bytes(b"x" * 1024)
    assert store.mark_stale(now=time.time() + 60) == [job["id"]]
    assert not chunks.exists() and store.load(job["id"])["error"]["code"] == "interrupted"


# ------------------------------------------------------------------- two copies of showreel_core in one process

def _second_copy() -> Any:
    """``showreel_core`` loaded again under a private name, as ``dashboard/plugin_api.py`` does in the gateway."""
    name = "_hype_test_second_core"
    if name not in sys.modules:
        init = ROOT / "showreel_core" / "__init__.py"
        spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(init.parent)])
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module(f"{name}.jobs")


def test_plugin_sweep_keeps_a_film_the_desktop_copy_is_running(tmp_path: Path) -> None:
    other = _second_copy()
    assert other is not jobs_mod
    store = JobStore(tmp_path)
    job = store.create("s", {})
    store.update(job["id"], stage="storyboard")      # a quiet stage (one long model call): no progress writes
    other.mark_live(job["id"])                       # the Desktop API's copy of the pipeline runs it
    try:
        assert store.mark_stale(now=time.time() + 120, active_ids=set(running_ids())) == []
        assert store.load(job["id"])["stage"] == "storyboard"
    finally:
        other.mark_not_live(job["id"])
    assert store.mark_stale(now=time.time() + 120, active_ids=set(running_ids())) == [job["id"]]


def test_both_copies_share_one_render_lock() -> None:
    """One heavy render per process: a Desktop-pane film and a chat film must not render side by side."""
    from showreel_core import pipeline
    other = _second_copy()
    assert other.shared_lock("render") is pipeline._RENDER_LOCK is jobs_mod.shared_lock("render")
