"""Long product names and non-web pictures in the 2D style kits (audit-render).

* A product name at the story's 40-character cap ran off the frame in launch TITLE/END (one-line size floor), comic
  9:16 TITLE/END (masthead floor), ink END, and wrapped over the tagline/CTA in terminal TITLE/END. Titles now wrap to
  two balanced lines (or shrink) inside the frame.
* A game/app screenshot (``image.frame == 'card'``) got web framing in comic (address caption with the file name,
  mouse cursor + CLICK!), terminal (url in the pane title / status bar, pointer), blueprint (url in the header) and
  ink (url luggage tag, cursor): none of it may reach the screen.

Slow: real Chromium keyframes (``pytest --runslow``).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from showreel_core.contracts import Caption, Cue, SceneType, Timeline, TimelineScene
from showreel_core.film.page import build_job
from showreel_core.film.quick import film_from_timeline
from showreel_core.story.schema import TITLE_CHARS

from tests.kits.test_quick import MEDIA_MAP

LONG = "Northwind Ledger Reconciliation Studio X"
assert len(LONG) == TITLE_CHARS


def _scene(i, typ, t0, t1, data):
    return TimelineScene(i=i, type=SceneType(typ), t0=t0, t1=t1, data=data, label="", transition_in="cut",
                         captions=list[Caption]())


def _timeline(style: str, aspect: Any, title: str, card: bool) -> Timeline:
    img = {"kind": "image", "path": "assets/capture_home.png", "w": 1440, "h": 900,
           "url": "https://northwind.example.com/ledger"}
    if card:
        img = {"kind": "image", "path": "assets/capture_home.png", "w": 1440, "h": 900,
               "url": "shots/game_capture_01.png", "page_title": "", "frame": "card"}
    w, h = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    scenes = [
        _scene(0, "HOOK", 0.0, 3.0, {"hero": dict(img), "label": title, "story_index": 0}),
        _scene(1, "TITLE", 3.0, 7.0, {"title": title, "tagline": "Every ledger, every team, one calm place",
                                      "story_index": 1}),
        _scene(2, "FEATURE", 7.0, 12.0, {"image": {**img, "path": "assets/capture_dark.png"}, "feature": "Auto match",
                                         "bbox": [0.1, 0.1, 0.8, 0.8], "click": [0.5, 0.5]}),
        _scene(3, "SCREEN", 12.0, 16.0, {"image": dict(img), "bbox": [0.2, 0.2, 0.6, 0.6]}),
        _scene(4, "END", 16.0, 20.0, {"title": title, "cta": "npx northwind-ledger", "url": ""}),
    ]
    return Timeline(style=style, aspect=aspect, fps=30, w=w, h=h, dur=20.0, bpm=120.0, seed=3, scenes=scenes,
                    cues=[Cue(3.0, "cut", -8, "peak")], title=title, accent="", mode="product", splits=[])


async def _look(job, film, times):
    """Layout QA + the visible text of the page at each time, and the film's merged SFX cues."""
    from showreel_core.render.workers import page_session
    w, h = film["size"]
    out = []
    async with page_session(job, "stage.html", w=w, h=h) as page:
        for t in times:
            await page.seek(t)
            qa = await page.evaluate(f"window.__sr.qa({float(t)!r})") or []
            text = await page.evaluate("document.body.innerText") or ""
            out.append((t, qa, text))
        cues = json.loads(await page.evaluate("JSON.stringify(window.__sr.cues || [])") or "[]")
    return out, cues


def _film(style, aspect, title, card, tmp_path):
    made = film_from_timeline(_timeline(style, aspect, title, card), style=style, media_map=MEDIA_MAP)
    film = made["film"]
    return film, build_job(film, tmp_path / "job", assets=made["assets"])


def _mid(film, kind):
    s = next(s for s in film["shots"] if s["scene"].endswith("/" + kind))
    return round(float(s["t0"]) + 0.72 * (float(s["t1"]) - float(s["t0"])), 2)


@pytest.mark.slow
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
@pytest.mark.parametrize("style", ["launch", "comic", "ink", "terminal"])
def test_a_40_char_title_stays_inside_the_frame(style, aspect, tmp_path):
    film, job = _film(style, aspect, LONG, False, tmp_path)
    looks, _ = asyncio.run(_look(job, film, [_mid(film, "TITLE"), _mid(film, "END")]))
    bad = [(t, q) for t, qa, _ in looks for q in qa if q.get("kind") in ("clip", "overlap")]
    assert bad == [], bad[:6]


@pytest.mark.slow
@pytest.mark.parametrize("style,aspect", [("comic", "16:9"), ("comic", "9:16"), ("terminal", "16:9"),
                                          ("blueprint", "16:9"), ("ink", "16:9")])
def test_a_card_picture_gets_no_web_framing(style, aspect, tmp_path):
    film, job = _film(style, aspect, "Casefile", True, tmp_path)
    times = [_mid(film, k) for k in ("HOOK", "FEATURE", "SCREEN")]
    looks, cues = asyncio.run(_look(job, film, times))
    for t, _, text in looks:
        assert "game_capture" not in text, (t, text[:400])
    if style in ("comic", "ink", "terminal"):     # no mouse click on a game/app picture
        feat = next(s for s in film["shots"] if s["scene"].endswith("/FEATURE"))
        clicks = [c for c in cues if c.get("sfx") == "click" and feat["t0"] <= c["t"] <= feat["t1"]]
        assert clicks == [], clicks
