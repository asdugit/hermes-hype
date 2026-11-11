"""Feature crops find the feature, not a sentence that mentions it (ISSUES #51).

Real E2E (Tempo focus timer): the feature "Stats" is a ``section.card.stats`` named by a visually hidden
``<h2 class="sr-only">``; the crop matched the footer sentence "Your tasks and stats stay in this browser",
a 1000x20 strip that filmed as an empty dark frame. "Tasks" cropped only its ``header.card__head`` row.
The slow test runs Chromium on a page with the same structure.
"""
from __future__ import annotations

import pytest
from conftest import FixtureServer

from showreel_core.capture import capture_product_report
from showreel_core.capture.web import WebPlan, strip_crop
from showreel_core.contracts import Event, Product
from showreel_core.story.facts import image_of, portrait_twin

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Tempo — focus timer</title>
<style>
body { margin: 0; background: #121014; color: #eee; font: 16px system-ui; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.layout { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; max-width: 1000px; margin: 40px auto; }
.card { background: #1d1a20; border: 1px solid #333; border-radius: 16px; padding: 24px; min-height: 260px; }
.card__head { display: flex; justify-content: space-between; }
.stats { grid-column: 1 / -1; display: flex; gap: 40px; }
.stat__value { font-size: 64px; }
.footer { text-align: center; color: #888; margin: 24px; }
</style></head><body>
<main class="layout">
  <section class="card timer" aria-labelledby="timer-heading"><h2 class="sr-only" id="timer-heading">Timer</h2>
    <div style="font-size:72px">25:00</div><button>Start</button></section>
  <section class="card tasks" aria-labelledby="tasks-heading">
    <header class="card__head"><h2 id="tasks-heading">Tasks</h2><span>2 open</span></header>
    <ul><li>Outline the report</li><li>Review pull requests</li></ul></section>
  <section class="card stats" aria-labelledby="stats-heading"><h2 class="sr-only" id="stats-heading">Stats</h2>
    <div class="stat"><span>Focus today</span><div class="stat__value">50</div></div>
    <div class="stat"><span>Sessions</span><div class="stat__value">2</div></div></section>
</main>
<footer class="footer"><p>Your tasks and stats stay in this browser. Nothing is sent anywhere.</p></footer>
</body></html>"""


def test_strip_crop_rule():
    assert strip_crop(1000, 20)            # the footer sentence
    assert strip_crop(462, 60)             # a bare heading row
    assert not strip_crop(1000, 265)       # the stats card
    assert not strip_crop(488, 668)        # a feature card
    assert not strip_crop(200, 60)         # a small boxy element is not a strip
    assert not strip_crop("x", None)  # type: ignore[arg-type]


def test_element_crop_shape_comes_from_its_pixels():
    ev = Event("e44", 1.0, "product_capture", "showreel_capture", "Tempo · Stats", "", {
        "path": "x/element_02_stats.png", "url": "http://127.0.0.1:8765/", "viewport": [1440, 900],
        "kind": "element", "size": [2096, 626], "dpr": 2.0})
    img = image_of(ev)
    assert img is not None and (img["w"], img["h"]) == (2096, 626)


def test_portrait_twin_is_the_phone_capture_of_the_same_page():
    def cap(i, kind, size, url="http://127.0.0.1:8765/"):
        return Event(f"e{i}", 1.0, "product_capture", "showreel_capture", kind, "", {
            "path": f"x/{kind}_{i}.png", "url": url, "kind": kind, "size": size})
    desk, full, elem = cap(1, "viewport", [1440, 900]), cap(2, "full", [1440, 2400]), cap(3, "element", [976, 1336])
    mob, mob_full = cap(4, "mobile", [780, 1688]), cap(5, "mobile_full", [780, 3200])
    other = cap(6, "mobile", [780, 1688], url="http://127.0.0.1:9999/")
    events = [desk, full, elem, other, mob, mob_full]
    assert portrait_twin(desk, events) is mob
    assert portrait_twin(full, events) is mob_full
    assert portrait_twin(elem, events) is None            # crops keep their own picture
    assert portrait_twin(mob, events) is None


@pytest.mark.slow
@pytest.mark.usefixtures("has_browser", "render_slot")
def test_feature_crops_on_a_tempo_like_page(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")
    with FixtureServer(site) as srv:
        plan = WebPlan(desktop=((1440, 900),), mobile=None, full_page=False, interactions=[], auto_features=0)
        rep = capture_product_report(Product(urls=[srv.url]), [], tmp_path / "cap", budget_s=60, web_plan=plan,
                                     features=["Timer", "Tasks", "Stats", "anywhere"])
    crops = {e.data["label"]: e.data for e in rep.events if e.data["kind"] == "element"}
    assert set(crops) == {"Timer", "Tasks", "Stats"}, crops.keys()     # "anywhere" is only in the footer
    for label, d in crops.items():
        x, y, w, h = d["bbox"]
        assert h >= 200 and not strip_crop(w, h), (label, d["bbox"])    # whole cards, not text rows
    assert crops["Stats"]["bbox"][2] > crops["Tasks"]["bbox"][2]        # the full-width stats card
