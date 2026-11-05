"""Slow integration: the Director's RuntimeRenderer on the real runtime (build_job + Chromium dry run + keyframes).

Run with ``pytest tests/director --runslow``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from director_fakes import png

from showreel_core.director.backend import RuntimeRenderer
from showreel_core.director.types import MediaAsset

SCENE = """import { sr } from '../runtime/showreel.js';
sr.defineScene('custom:probe', {
  layer: '2d',
  describe: 'probe',
  params: { media: { type: 'asset', default: null, doc: 'm' }, boom: { type: 'number', default: 99, doc: 'throw after' } },
  render(ctx, t, p) {
    const g = ctx.g;
    g.fillStyle = '#20263a'; g.fillRect(0, 0, ctx.w, ctx.h);
    const a = ctx.asset(p.media);
    g.drawImage(a.frame(t), ctx.w * 0.2 + Math.sin(t) * 40, ctx.h * 0.3, ctx.w * 0.6, ctx.h * 0.4);
    ctx.text(g, 'PROBE', { x: ctx.w / 2, y: ctx.h * 0.15, size: 64, color: '#fff', align: 'center' });
    if (t > p.boom) { const o = null; o.crash(); }
  }
});
"""


@pytest.mark.slow
def test_runtime_renderer_build_dry_run_and_keyframes(tmp_path: Path) -> None:
    img = tmp_path / "product.png"
    img.write_bytes(png(size=(640, 360)))
    film = {"version": 1, "fps": 30, "size": [1920, 1080], "dur": 4.0, "seed": 7, "title": "probe",
            "assets": {"product": {"type": "image"}},
            "shots": [{"id": "a", "t0": 0, "t1": 2, "scene": "custom:probe", "res": None,
                       "params": {"media": "product"}},
                      {"id": "b", "t0": 2, "t1": 4, "scene": "custom:probe", "res": None,
                       "params": {"media": "product", "boom": 1.0}}],
            "transitions": [{"from": "a", "to": "b", "type": "crossfade", "t": 1.8, "dur": 0.4}]}
    r = RuntimeRenderer()
    page = tmp_path / "page"
    assert r.build(film, page, scenes={"probe": SCENE}, assets=[MediaAsset("product", "image", str(img))],
                   library_dir=None) == []
    assert (page / "stage.html").is_file() and (page / "scenes" / "probe.js").is_file()
    pv = r.preview(page, probe_times=[0.5, 1.5, 2.5, 3.5], capture_times=[0.5, 3.0], size=(960, 540),
                   film_size=(1920, 1080), shots=film["shots"], determinism_times=[1.0])
    assert pv.ok, pv.load_error
    assert len(pv.images) == 2 and all(i[:4] == b"\x89PNG" for i in pv.images)
    shots = {e.shot for e in pv.errors}
    assert shots == {"b"} and any("crash" in e.msg for e in pv.errors)
    assert not any(e.kind == "determinism" for e in pv.errors)
