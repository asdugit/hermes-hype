"""Runtime fit + contrast + caption typography passes (runtime/core/fit.js, contrast.js, typeset.js).

Slow: real Chromium (``pytest --runslow``). A camera that pushes long lines past the frame edge and holds there is
pulled back so no text is cut; a label that only crosses the edge during an entrance is left alone (motion, not a
defect); a layout that fits is untouched; dark type on a dark backdrop gets a halo, readable type does not;
caption markdown is typeset.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from showreel_core.film.page import build_job

PUSH = r"""
import { sr } from '../runtime/showreel.js';
sr.defineScene('custom:push', {
  layer: 'dom',
  setup(ctx) {
    const cam = ctx.el('div', { style: 'position:absolute;left:0;top:0;width:1920px;height:1080px;transform-origin:960px 540px;' });
    const card = ctx.el('div', { style: 'position:absolute;left:260px;top:300px;width:1400px;padding:30px;background:#f4f1ea;color:#111;font:34px monospace;' });
    for (let i = 0; i < 8; i++) card.append(ctx.el('div', { style: 'white-space:pre;' }, `${i}  attempts: Total number of attempts (the first call plus retries) ${i}`));
    cam.append(card);
    ctx.root.append(ctx.el('div', { style: 'position:absolute;inset:0;background:#0b0c10;' }), cam);
    ctx.state.cam = cam;
  },
  render(ctx, t) {
    const z = 1 + 0.8 * Math.min(1, Math.max(0, t / 0.8));
    ctx.state.cam.style.transform = `scale(${z})`;
  },
});
sr.defineScene('custom:enter', {
  layer: 'dom',
  setup(ctx) {
    ctx.root.append(ctx.el('div', { style: 'position:absolute;inset:0;background:#0b0c10;' }));
    const lab = ctx.el('div', { style: 'position:absolute;left:300px;top:480px;font:80px sans-serif;color:#fff;white-space:nowrap;' }, 'A headline that slides in');
    ctx.root.append(lab);
    ctx.state.lab = lab;
  },
  render(ctx, t) {
    const u = Math.min(1, Math.max(0, t / 0.3));
    ctx.state.lab.style.transform = `translateX(${(1 - u) * -900}px)`;
  },
});
sr.defineScene('custom:fits', {
  layer: 'dom',
  setup(ctx) {
    const cam = ctx.el('div', { style: 'position:absolute;inset:0;' });
    cam.append(ctx.el('div', { style: 'position:absolute;left:400px;top:400px;font:72px sans-serif;color:#fff;' }, 'Fits fine'));
    ctx.root.append(ctx.el('div', { style: 'position:absolute;inset:0;background:#0b0c10;' }), cam);
    ctx.state.cam = cam;
  },
  render(ctx, t) { ctx.state.cam.style.transform = `scale(${1 + 0.05 * t})`; },
});
sr.defineScene('custom:dark', {
  layer: 'dom',
  setup(ctx) {
    ctx.root.append(ctx.el('div', { style: 'position:absolute;inset:0;background:#1d1a22;' }));
    ctx.root.append(ctx.el('div', { id: 'dk', style: 'position:absolute;left:300px;top:300px;font:bold 120px sans-serif;color:#3b2f45;' }, 'Tempo'));
    ctx.root.append(ctx.el('div', { id: 'ok', style: 'position:absolute;left:300px;top:600px;font:bold 80px sans-serif;color:#ffffff;' }, 'Readable'));
  },
  render() {},
});
"""


def _film(shots, captions=()):
    t, out = 0.0, []
    for i, (scene, dur) in enumerate(shots):
        out.append({"id": f"s{i}", "scene": scene, "t0": t, "t1": t + dur, "params": {}})
        t += dur
    return {"version": 1, "fps": 30, "size": [1920, 1080], "dur": t, "seed": 7, "title": "fit", "background": "#000000",
            "shots": out, "captions": list(captions)}


async def _look(job, film, times, js=None):
    from showreel_core.render.workers import page_session
    w, h = film["size"]
    out = []
    async with page_session(job, "stage.html", w=w, h=h) as page:
        for t in times:
            await page.seek(t)
            qa = await page.evaluate(f"window.__sr.qa({float(t)!r})") or []
            extra = await page.evaluate(js) if js else None
            out.append((t, qa, extra))
        shots = json.loads(await page.evaluate("JSON.stringify(window.__sr.shots())"))
    return out, shots


@pytest.mark.slow
def test_held_push_is_pulled_back_entrances_and_fitting_layouts_untouched(tmp_path):
    film = _film([("custom:push", 3.0), ("custom:enter", 2.0), ("custom:fits", 2.0)])
    job = build_job(film, tmp_path / "job", scenes={"custom:push": PUSH, "custom:enter": PUSH, "custom:fits": PUSH})
    looks, shots = asyncio.run(_look(job, film, [2.5, 4.5, 6.0], "document.body.innerText.length"))
    clips = [(t, q["msg"]) for t, qa, _ in looks for q in qa if q.get("kind") == "clip"]
    assert clips == [], clips[:4]
    by = {s["id"]: s for s in shots}
    assert by["s0"]["fit"] >= 1           # the held push was corrected
    assert by["s1"]["fit"] == 0           # an entrance that crosses the edge for 0.3 s is motion, not a defect
    assert by["s2"]["fit"] == 0           # nothing cut -> no-op


@pytest.mark.slow
def test_without_the_fit_pass_the_push_clips(tmp_path):
    film = _film([("custom:push", 3.0)])
    film["qa"] = {"fit": False}
    job = build_job(film, tmp_path / "job", scenes={"custom:push": PUSH})
    looks, _ = asyncio.run(_look(job, film, [2.5]))
    assert any(q.get("kind") == "clip" for _, qa, _ in looks for q in qa)


@pytest.mark.slow
def test_dark_type_on_a_dark_backdrop_gets_a_halo(tmp_path):
    film = _film([("custom:dark", 2.0)])
    film["theme"] = {"tokens": {"text": "#3B2F45", "bg": "#FFF6FA"}, "vars": {"--sr-accent": "#FF5FA2"}}
    job = build_job(film, tmp_path / "job", scenes={"custom:dark": PUSH})
    js = ("JSON.stringify([...document.querySelectorAll('#dk,#ok')].map(e => "
          "[e.id, getComputedStyle(e).textShadow, e.dataset.srHalo || '']))")
    looks, _ = asyncio.run(_look(job, film, [1.5], js))
    got = {k: (sh, halo) for k, sh, halo in json.loads(looks[0][2])}
    assert got["dk"][1] and got["dk"][0] != "none"     # #3b2f45 on #1d1a22 is ~1.3:1 -> halo
    assert got["ok"] == ("none", "")                    # white on near-black reads already: untouched


@pytest.mark.slow
def test_caption_markdown_is_typeset(tmp_path):
    film = _film([("custom:fits", 2.0)], captions=[{"t0": 0.2, "t1": 1.8, "text": "Runs with `node --test` -- **fast**"}])
    job = build_job(film, tmp_path / "job", scenes={"custom:fits": PUSH})
    looks, _ = asyncio.run(_look(job, film, [1.0], "document.querySelector('.sr-captions-layer').innerText"))
    text = looks[0][2].replace("\u200c", "")
    assert "`" not in text and "**" not in text
    assert "node --test" in text and "—" in text


@pytest.mark.slow
def test_curated_palettes_are_never_haloed(tmp_path):
    """No customised palette -> the contrast pass does not run (kits' own looks, e.g. comic outlines, stay)."""
    film = _film([("custom:dark", 2.0)])
    job = build_job(film, tmp_path / "job", scenes={"custom:dark": PUSH})
    looks, _ = asyncio.run(_look(job, film, [1.5], "document.querySelector('#dk').dataset.srHalo || ''"))
    assert looks[0][2] == ""
