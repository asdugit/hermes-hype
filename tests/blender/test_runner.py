"""Runner (job.json protocol host side) against a FAKE Blender: progress, traceback-on-exit-0, verify, resume, cancel."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from showreel_core.blender import runner

FAKE = Path(__file__).with_name("fake_blender.py")
SCENE = Path(__file__).resolve().parents[2] / "blender_kits" / "_test" / "hello.py"


def fake_cmd(job_path: Path) -> list[str]:
    return [sys.executable, str(FAKE), "-b", "--", str(job_path)]


def job_for(tmp_path: Path, mode: str = "ok", n: int = 6, **kw) -> dict:
    params = {"_fake": mode, **kw.pop("params", {})}
    return runner.make_job(SCENE, tmp_path / "out", dur=n / 30, fps=30, res=(64, 36), params=params, **kw)


def run(job: dict, **kw) -> runner.RunResult:
    return runner.run_job(job, "unused-blender", command=fake_cmd(Path(job["out_dir"]) / "job.json"), **kw)


def test_make_job_frame_count_and_handles(tmp_path):
    job = runner.make_job(SCENE, tmp_path, dur=2.0, fps=30, res=(1080, 1920), handles=(0.5, 0.25))
    assert job["frame_count"] == round(2.75 * 30)
    assert job["aspect"] == "9:16" and job["out_ext"] == "jpg" and job["frames"] is None
    assert runner.make_job(SCENE, tmp_path, dur=1, alpha=True)["out_ext"] == "png"
    with pytest.raises(ValueError):
        runner.make_job(SCENE, tmp_path, dur=1, tier="ultra")


def test_parse_line():
    assert runner.parse_line("SR_FRAME 12 0.731") == {"ev": "FRAME", "frame": 12, "s": 0.731}
    assert runner.parse_line("SR_BUILD_DONE s=1.5")["s"] == 1.5
    assert runner.parse_line("SR_ERROR KeyError: 'car'")["msg"] == "KeyError: 'car'"
    assert runner.parse_line("Fra:1 Mem:12M") is None


def test_ok_run_progress_stats_cues(tmp_path):
    events = []
    r = run(job_for(tmp_path), progress=events.append)
    assert r.ok, r.error
    assert r.frames_rendered == list(range(1, 7)) and not r.frames_bad
    assert r.cues == [{"t": 0.25, "sfx": "whoosh"}] and r.stats["engine"] == "FAKE"
    phases = [e["phase"] for e in events]
    assert phases[0] == "start" and "build" in phases and phases[-1] == "done"
    frames = [e for e in events if e["phase"] == "frame"]
    assert [e["done"] for e in frames] == list(range(1, 7)) and frames[-1]["eta_s"] == 0
    assert Path(r.log).read_text(encoding="utf-8").count("SR_FRAME") == 6


def test_traceback_with_exit_code_0_is_a_failure(tmp_path):
    r = run(job_for(tmp_path, "crash_exit0"))
    assert not r.ok and r.exit_code == 0
    assert "traceback" in r.error.lower() and "AttributeError" in r.traceback


def test_sr_error_reports_the_scene_error(tmp_path):
    r = run(job_for(tmp_path, "error"))
    assert not r.ok and r.exit_code == 1 and "bad param" in r.error


def test_missing_sr_done_is_a_failure(tmp_path):
    r = run(job_for(tmp_path, "nodone"))
    assert not r.ok and "SR_DONE" in r.error


def test_truncated_and_blank_frames(tmp_path):
    r = run(job_for(tmp_path / "a", "truncated"))
    assert not r.ok and r.frames_bad and "truncated" in r.frames_bad[0][1]
    r = run(job_for(tmp_path / "b", "blank"))
    assert not r.ok and "blank" in r.error and len(r.blank) == 6


def test_verify_frame(tmp_path):
    from PIL import Image
    good = tmp_path / "g.jpg"
    Image.linear_gradient("L").resize((64, 36)).save(good)
    assert runner.verify_frame(good, expect=(64, 36)).ok
    assert "size" in runner.verify_frame(good, expect=(32, 18)).reason
    assert runner.verify_frame(tmp_path / "missing.jpg").reason == "missing"
    flat = tmp_path / "f.png"
    Image.new("RGB", (64, 36), (9, 9, 9)).save(flat)
    chk = runner.verify_frame(flat)
    assert chk.ok and chk.blank


def test_partial_run_then_resume_renders_only_the_rest(tmp_path):
    job = job_for(tmp_path, "partial")
    r1 = run(job)
    assert not r1.ok and r1.frames_rendered == [1, 2]
    job["params"]["_fake"] = "ok"
    r2 = run(job)
    assert r2.ok, r2.error
    assert r2.frames_skipped == [1, 2] and r2.frames_rendered == [3, 4, 5, 6]
    r3 = run(job)
    assert r3.ok and r3.frames_rendered == [] and r3.frames_skipped == list(range(1, 7))


def test_keyframes_only(tmp_path):
    job = job_for(tmp_path, n=30, frames=[1, 15, 30])
    r = run(job)
    assert r.ok and r.frames_rendered == [1, 15, 30]
    assert sorted(p.name for p in runner.iter_existing(job)) == ["000001.jpg", "000015.jpg", "000030.jpg"]
    assert runner.bench_frames(30) == [1, 15, 30] and runner.bench_frames(2) == [1, 2]


def test_cancel_kills_only_our_child(tmp_path):
    import psutil
    bystander = psutil.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        stop = threading.Event()
        job = job_for(tmp_path, "slow", n=40, params={"_sleep": 0.3})
        seen = []

        def progress(ev):
            seen.append(ev)
            if ev["phase"] == "frame":
                stop.set()

        t0 = time.monotonic()
        r = run(job, progress=progress, cancel=stop)
        assert r.cancelled and not r.ok and time.monotonic() - t0 < 20
        pid = int((Path(job["out_dir"]) / "fake.pid").read_text())
        time.sleep(0.3)
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        assert bystander.is_running()
    finally:
        bystander.kill()


def test_eta_helpers():
    assert runner.estimate_s(2.0, 0.5, 100) == 52.0
    assert runner.estimate_s(0.0, 1.0, 10, pixels=4, bench_pixels=1) == 40.0
    assert runner.human_eta(30) == "~30 s" and runner.human_eta(540) == "~9 min" and runner.human_eta(9000) == "~2.5 h"
