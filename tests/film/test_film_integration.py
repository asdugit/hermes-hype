"""Runtime integration (Chromium): demo film dry-run, QA detection, error capture, determinism probe, preview.

Opt in with ``pytest --runslow``. Set AUTEUR_RENDER_SLOT_DIR to share render slots on a busy machine.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from showreel_core.film.dryrun import dryrun
from showreel_core.film.page import build_job

pytestmark = pytest.mark.slow


def _job(tmp_path: Path, demo, shots, **extra) -> Path:
    _, assets, kits = demo
    f = {"version": 1, "fps": 30, "size": [1280, 720], "dur": shots[-1]["t1"], "seed": 5, "shots": shots, **extra}
    return build_job(f, tmp_path / "job", kits_root=kits, assets=assets if extra.get("assets") else None)


def test_demo_film_dryruns_clean(tmp_path: Path, demo, render_slot):
    film, assets, kits = demo
    job = build_job(film, tmp_path / "job", kits_root=kits, assets=assets)
    r = dryrun(job, per_shot=2)
    assert r.ready_error == "" and r.error is None, r.summary()
    assert r.scene_errors == [] and r.page_errors == [], r.summary()
    layers = {s.id: s.layer for s in r.shots}
    assert layers == {"intro": "2d", "card": "dom", "cube": "three", "px": "2d", "badge": "2d"}
    assert all(s.deterministic for s in r.shots if s.kind == "shot"), [s.probe for s in r.shots]
    assert [(c["t"], c["sfx"]) for c in r.cues] == [(0.1, "whoosh_short_1"), (3.9, "whoosh_short_2")]
    assert r.ok, r.summary()


def test_qa_flags_layout_problems(tmp_path: Path, demo, render_slot):
    job = _job(tmp_path, demo, [{"id": "bad", "t0": 0, "t1": 1, "scene": "kit:demo/qa-bad"},
                                {"id": "dom", "t0": 1, "t1": 2, "scene": "kit:demo/qa-dom"}])
    r = dryrun(job, per_shot=1, determinism=False)
    kinds = {s.id: {q["kind"] for q in s.qa} for s in r.shots}
    assert {"small_text", "safe", "clip", "overlap", "error"} <= kinds["bad"], r.qa
    assert {"small_text", "clip"} <= kinds["dom"], r.qa
    msgs = " ".join(q["msg"] for q in r.qa)
    assert "No Such Font" in msgs and "overflows its box" in msgs


def test_scene_exceptions_are_reported_with_shot_and_time(tmp_path: Path, demo, render_slot):
    job = _job(tmp_path, demo, [{"id": "ok", "t0": 0, "t1": 1, "scene": "kit:demo/bars"},
                                {"id": "boom", "t0": 1, "t1": 2, "scene": "kit:demo/throws"},
                                {"id": "nosetup", "t0": 2, "t1": 3, "scene": "kit:demo/setup-throws"}])
    r = dryrun(job, times=[0.5, 1.75, 2.5], determinism=False)
    errs = "\n".join(r.scene_errors)
    assert "shot boom t=1.750: boom at 0.75" in errs
    assert "shot nosetup: setup()" in errs and "setup exploded" in errs
    assert not r.ok
    boom = next(s for s in r.shots if s.id == "boom")
    assert any("boom at" in e for e in boom.errors)


def test_strict_load_rejects_ready_with_a_clear_message(tmp_path: Path, demo, render_slot):
    job = _job(tmp_path, demo, [{"id": "nosetup", "t0": 0, "t1": 1, "scene": "kit:demo/setup-throws"}])
    r = dryrun(job, lenient=False, determinism=False)
    assert "shot 'nosetup' (kit:demo/setup-throws): setup() threw: setup exploded (at kits/demo/kit.js:" in r.ready_error


def test_unknown_scene_lists_what_is_available(tmp_path: Path, demo, render_slot):
    job = _job(tmp_path, demo, [{"id": "x", "t0": 0, "t1": 1, "scene": "kit:demo/nope"}])
    r = dryrun(job, lenient=False, determinism=False)
    assert "unknown scene 'kit:demo/nope'" in r.ready_error and "kit:demo/bars" in r.ready_error


def test_determinism_probe(tmp_path: Path, demo, render_slot):
    job = _job(tmp_path, demo, [{"id": "impure", "t0": 0, "t1": 1, "scene": "kit:demo/impure"},
                                {"id": "sloppy", "t0": 1, "t1": 2, "scene": "kit:demo/sloppy"}])
    r = dryrun(job, per_shot=3)
    det = {s.id: s.deterministic for s in r.shots}
    assert det == {"impure": False, "sloppy": True}, [s.probe for s in r.shots]


def test_preview_writes_stills_and_contact_sheet(tmp_path: Path, demo, render_slot):
    from showreel_core.film.preview import preview

    film, assets, kits = demo
    for name, spec in assets.items():
        film["assets"][name] = {**film["assets"][name], **spec}
    fp = tmp_path / "film.json"
    fp.write_text(json.dumps(film), encoding="utf-8")
    r = preview(fp, tmp_path / "out", keyframes=[0.5, 3.0, 5.0, 7.0], size=(640, 360), kits_root=kits)
    assert r.ok, r.to_dict()
    assert len(r.stills) == 4 and Path(r.contact_sheet).is_file()


def test_sdk_additions_transition_cues_dom_height_qa_opt_out(tmp_path: Path, demo, render_slot):
    """Wave-3 SDK: transition cues(), ctx.h number + ctx.el + ctx.film.safe on DOM, data-qa="off", qaText on DOM."""
    job = _job(tmp_path, demo, [{"id": "probe", "t0": 0, "t1": 1.2, "scene": "kit:demo/probe"},
                                {"id": "dom", "t0": 0.8, "t1": 2, "scene": "kit:demo/qa-dom"}],
               transitions=[{"from": "probe", "to": "dom", "type": "kit:demo/flash", "t": 0.8, "dur": 0.4,
                             "params": {"sfx": "chime"}}])
    r = dryrun(job, times=[0.4, 1.6], determinism=False, lenient=False)
    assert r.ready_error == "" and r.scene_errors == [], r.summary()
    assert [(round(c["t"], 3), c["sfx"]) for c in r.cues] == [(0.8, "whoosh_short"), (1.0, "chime")]
    assert all(c["shot"] == "tx:0" for c in r.cues)
    msgs = " ".join(q["msg"] for q in r.qa)
    assert "texture text" in msgs                      # qaText from a DOM layer reaches QA
    assert "tiny dom text" in msgs and "decorative" not in msgs
