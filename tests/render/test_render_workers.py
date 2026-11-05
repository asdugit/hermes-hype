"""Worker planning, sizing, resume fingerprint and never-raise behaviour (no browser needed)."""
from __future__ import annotations

import sys

import pytest

from showreel_core.render import workers as W
from showreel_core.render.chromium import BrowserCandidate

GiB = 1024 ** 3


def test_frames_for_rounding():
    assert W.frames_for(6.0, 30) == 180
    assert W.frames_for(72.0, 30) == 2160
    assert W.frames_for(0.1 * 3, 10) == 3      # float noise does not drop a frame
    assert W.frames_for(0.0, 30) == 1


@pytest.mark.parametrize("total,fps,chunk_s,sizes", [
    (180, 30, 5.0, [150, 30]), (150, 30, 5.0, [150]), (90, 15, 5.0, [75, 15]), (10, 30, 5.0, [10]),
    (2250, 30, 5.0, [150] * 15),
])
def test_plan_chunks(total, fps, chunk_s, sizes):
    chunks = W.plan_chunks(total, fps, chunk_s)
    assert [c.frames for c in chunks] == sizes
    assert chunks[0].f0 == 0 and chunks[-1].f1 == total
    assert all(a.f1 == b.f0 for a, b in zip(chunks, chunks[1:]))
    assert [c.index for c in chunks] == list(range(len(chunks)))


@pytest.mark.parametrize("gpu,free_gb,expected", [
    (True, 16, 3), (False, 16, 2), (True, 2.5, 2), (True, 1.9, 1), (False, 0.5, 1), (True, 1.8, 1),
])
def test_auto_workers(gpu, free_gb, expected):
    assert W.auto_workers(gpu, int(free_gb * GiB)) == expected


def test_auto_workers_reads_psutil():
    assert 1 <= W.auto_workers(True) <= 3


def test_dir_fingerprint(tmp_path):
    (tmp_path / "a.html").write_text("x", encoding="utf-8")
    (tmp_path / "chunks").mkdir()
    fp1 = W.dir_fingerprint(tmp_path, [tmp_path / "chunks"])
    (tmp_path / "chunks" / "chunk_0000.mp4").write_bytes(b"ignored")
    assert W.dir_fingerprint(tmp_path, [tmp_path / "chunks"]) == fp1
    (tmp_path / "a.html").write_text("y", encoding="utf-8")
    assert W.dir_fingerprint(tmp_path, [tmp_path / "chunks"]) != fp1


def test_render_never_raises_without_ffmpeg(tmp_path):
    spec = W.RenderSpec(page_dir=tmp_path, out_path=tmp_path / "o.mp4", duration_s=1, ffmpeg=str(tmp_path / "nope"))
    res = W.render_video(spec)
    assert not res.ok and res.error and res.error["code"] == "no_ffmpeg"


def test_render_never_raises_with_broken_browser(tmp_path, ffmpeg_path):
    (tmp_path / "index.html").write_text("<p>x</p>", encoding="utf-8")
    spec = W.RenderSpec(page_dir=tmp_path, out_path=tmp_path / "out" / "o.mp4", w=64, h=36, duration_s=0.2,
                        gpu="off", browser=BrowserCandidate(sys.executable, "env", "custom"), ffmpeg=ffmpeg_path,
                        timeout_s=10)
    res = W.render_video(spec)
    assert not res.ok and res.error is not None
    assert res.error["code"] in ("chunk_failed", "browser_launch")
    assert not (tmp_path / "out" / "o.mp4").exists()


def test_render_result_is_json_able(tmp_path):
    import json
    json.dumps(W.RenderResult(error={"code": "x", "message": "y"}).to_dict())
