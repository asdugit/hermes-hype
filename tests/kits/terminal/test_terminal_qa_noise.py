"""Layout-QA noise in terminal films (ISSUES #57): box-drawn rules, zoomed picture frames, odometer reels and the
block scrollbar are decoration (data-qa="off"); the real text (status line, headlines, numbers via a transparent
proxy) is still measured. Real E2E run 9 reported 200 issues (331 rules outside the safe area) on a clean film.
Slow: seeks the fixture Quick film every second in both aspects and expects a clean report."""
from __future__ import annotations

import asyncio

import pytest

from showreel_core.film.page import build_job
from showreel_core.film.quick import film_from_timeline


@pytest.mark.slow
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_terminal_quick_film_layout_qa_is_clean(aspect, tmp_path):
    from showreel_core.film.preview import capture_keyframes
    from tests.kits.test_quick import MEDIA_MAP, _timeline

    tl = _timeline(style="terminal", aspect=aspect)
    made = film_from_timeline(tl, style="terminal", media_map=MEDIA_MAP)
    film = made["film"]
    job = build_job(film, tmp_path / "job", assets=made["assets"])
    w, h = film["size"]
    times = [round(0.5 + k * 1.0, 2) for k in range(int(film["dur"]))]
    stills, info = asyncio.run(capture_keyframes(job, times, w=w, h=h))
    assert not info["errors"], info["errors"]
    issues = [dict(q, t=s.t) for s in stills for q in s.qa]
    assert issues == [], issues[:6]
    # the numbers are still measured (the odometer's QA proxy): a STATS frame reports its text boxes
    assert any(s.qa == [] for s in stills)


def test_box_rules_are_decorative_but_titles_are_text():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[3] / "kits" / "terminal" / "crt.js").read_text(encoding="utf-8")
    assert "data-qa=\"off\"" in src and "rule(edge, " in src and "sp(titleCls, T)" in src
    pane = (Path(__file__).resolve().parents[3] / "kits" / "terminal" / "pane.js").read_text(encoding="utf-8")
    assert "drum.dataset.qa = 'off'" in pane and "tm-odo-qa" in pane
