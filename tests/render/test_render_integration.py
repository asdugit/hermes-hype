"""Integration (slow): real Chromium + ffmpeg. Run with ``pytest --runslow``."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from showreel_core.render import selftest
from showreel_core.render.testpage import write_test_page
from showreel_core.render.workers import RenderSpec, capture_stills, render_video

pytestmark = pytest.mark.slow


def test_selftest_small(tmp_path):
    code = selftest.main(["--small", "--out", str(tmp_path), "--json"])
    summary = json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))
    assert code == 0, summary
    assert summary["determinism"]["ok"]
    for label, frames in (("final", 60), ("preview", 30)):
        r = summary[label]["render"]
        assert r["ok"] and r["frames"] == frames and r["render_fps"] > 0
        assert summary[label]["qa"]["frames"] == frames and "unknown" not in summary[label]["qa"]["color"]


def _spec(tmp_path: Path, page: str, **kw: Any) -> RenderSpec:
    base: dict[str, Any] = dict(page_dir=tmp_path / "page", page=page, out_path=tmp_path / "out" / "v.mp4", w=320, h=180, fps=15,
                duration_s=2.0, chunk_s=0.5, workers=2, gpu="off")
    base.update(kw)
    return RenderSpec(**base)


def test_resume_skips_finished_chunks(tmp_path):
    page = write_test_page(tmp_path / "page", dur=2, fps=15, with_font=False)
    first = render_video(_spec(tmp_path, page, keep_chunks=True))
    assert first.ok and first.chunks_total == 4 and first.chunks_rendered == 4, first.error
    again = render_video(_spec(tmp_path, page, keep_chunks=True))
    assert again.ok and again.chunks_skipped == 4 and again.chunks_rendered == 0 and again.workers == 0
    changed = render_video(_spec(tmp_path, page, keep_chunks=True, post="grain_vignette"))
    assert changed.ok and changed.chunks_skipped == 0  # different params -> different resume key


def test_duration_from_page_and_post_chain(tmp_path):
    page = write_test_page(tmp_path / "page", dur=1.2, fps=15)
    res = render_video(_spec(tmp_path, page, duration_s=None, post="crt", workers=1))
    assert res.ok, res.error
    assert res.frames == 18 and res.post == "crt"


def test_cancel(tmp_path):
    page = write_test_page(tmp_path / "page", dur=20, fps=15, with_font=False)
    cancel = threading.Event()
    seen = []

    def progress(done, total, eta):
        seen.append(done)
        if done > 0:
            cancel.set()

    res = render_video(_spec(tmp_path, page, duration_s=20.0, workers=1), progress=progress, cancel=cancel)
    assert not res.ok and res.error and res.error["code"] == "cancelled"
    assert not Path(tmp_path / "out" / "v.mp4").exists()


def test_capture_stills_and_page_errors_reported(tmp_path):
    page = write_test_page(tmp_path / "page", dur=2, fps=15, with_font=False)
    st = capture_stills(tmp_path / "page", page, [0.0, 1.0], w=320, h=180)
    assert st.ok and len(st.images) == 2 and st.images[0][:4] == b"\x89PNG"
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "index.html").write_text("<script>window.__sr = {ready: Promise.resolve(), dur: 1, fps: 15,"
                                    " seek(t) { throw new Error('boom ' + t); }};</script>", encoding="utf-8")
    res = render_video(RenderSpec(page_dir=bad, out_path=tmp_path / "o2" / "v.mp4", w=64, h=36, fps=15,
                                  duration_s=0.4, gpu="off", workers=1))
    assert not res.ok and res.error and res.error["code"] == "chunk_failed"
    assert "boom" in json.dumps(res.error)
