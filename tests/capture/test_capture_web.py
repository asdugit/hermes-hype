"""Web capture against the local fixture app (slow: launches Chromium). Run with ``pytest --runslow``."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from conftest import FixtureServer
from PIL import Image

from showreel_core.capture import capture_product_report
from showreel_core.capture.web import WebPlan
from showreel_core.contracts import Event, Product

pytestmark = [pytest.mark.slow, pytest.mark.usefixtures("has_browser", "render_slot")]


def by_kind(rep, kind):
    return [e for e in rep.events if e.data["kind"] == kind]


def test_capture_all_modes_on_fixture_app(tmp_path, site_server):
    session = [Event("e0", 0.0, "user_prompt", "", "", "", {"text": "build a notes app"}),
               Event("e7", 42.0, "terminal", "terminal", "npm run dev", "", {"cmd": "npm run dev",
                                                                             "server_urls": [site_server.url]})]
    prod = Product(name="Orbit Notes", kind="web_app", urls=[site_server.url], features=["Dark mode", "#pricing .pro"])
    t0 = time.monotonic()
    rep = capture_product_report(prod, session, tmp_path / "cap", budget_s=90)
    wall = time.monotonic() - t0
    assert rep.ok and rep.error is None and not rep.timed_out, rep.warnings
    [web] = rep.web
    assert web.ok and web.quality == "ok" and not web.warnings, web.warnings

    # every mode, at the right sizes
    vp = {tuple(e.data["size"]) for e in by_kind(rep, "viewport")}
    assert vp == {(1920, 1080), (1440, 900)}
    [full] = by_kind(rep, "full")
    assert full.data["full_page"] and 2000 < full.data["size"][1] <= 12000 and full.data["path"].endswith(".jpg")
    assert [tuple(e.data["size"]) for e in by_kind(rep, "mobile")] == [(780, 1688)]
    assert by_kind(rep, "mobile_full")[0].data["size"][0] == 780
    elements = by_kind(rep, "element")
    assert len(elements) >= 3
    assert len(by_kind(rep, "interaction")) == 4     # CTA hover + 3 scroll stills

    # event contract + numbering + weights
    assert [e.id for e in rep.events] == [f"e{i}" for i in range(8, 8 + len(rep.events))]
    for e in rep.events:
        assert e.kind == "product_capture" and e.t == 42.0 and Path(e.data["path"]).is_file()
        assert {"path", "url", "viewport", "full_page", "page_title", "kind"} <= set(e.data)
        assert e.data["url"] == site_server.url and e.data["page_title"] == "Orbit Notes"
    assert rep.events[0].weight == 0.95 and rep.events[0].data["source_ids"] == ["e7"]

    # page facts
    assert web.meta["accent"] == "#7c3aed" and web.meta["accent_source"] == "theme-color"
    assert Path(web.meta["favicon"]).is_file()

    # feature crops: text query found + expanded to the card; selector query found
    dark = next(e for e in elements if e.data.get("query") == "Dark mode")
    x, y, w, h = dark.data["bbox"]
    assert 200 < w < 500 and 120 < h < 300 and dark.data["size"][0] == round((w + 48) * 2)
    assert any(e.data.get("selector") == "#pricing .pro" for e in elements)

    # cookie banner dismissed (a #111 bar would sit at the bottom of the viewport)
    assert web.banner and web.banner["actions"][0] == {"action": "click", "text": "Accept all"}
    with Image.open(by_kind(rep, "viewport")[0].data["path"]) as im:
        assert sum(im.convert("RGB").getpixel((960, 1070))) > 200

    # reveal-on-scroll content is visible in the full page (card centre is white, not the section tint)
    with Image.open(full.data["path"]) as im:
        assert min(im.convert("RGB").getpixel((int(x + w / 2), int(y + h * 0.8)))) > 235

    # network policy: off-origin requests and writes blocked; the app never saw a write
    assert any("example-cdn.test" in u for u in web.blocked)
    assert any(b.startswith("POST ") and b.endswith("/api/track") for b in web.blocked_writes)
    assert site_server.methods() <= {"GET", "HEAD"}
    assert (tmp_path / "cap" / "capture.json").is_file()
    print(f"\nfixture capture: {len(rep.events)} images in {wall:.1f}s; timings {web.timings_ms}")


def test_explicit_interactions_and_destructive_guard(tmp_path, site_server):
    steps = [{"click": "#upgrade", "label": "upgrade"}, {"click": "Delete all notes"}, {"hover": "#nope"},
             {"scroll": 0.5, "label": "half"}]
    rep = capture_product_report(Product(urls=[site_server.url]), [], tmp_path / "cap", budget_s=60,
                                 interactions=steps, web_plan=None, features=[])
    [web] = rep.web
    stills = by_kind(rep, "interaction")
    assert [s.data["label"] for s in stills] == ["upgrade", "half"]
    with Image.open(stills[0].data["path"]) as im:     # the modal backdrop darkens the page
        assert sum(im.convert("RGB").getpixel((40, 450))) < 450
    assert any("looks destructive" in w for w in web.warnings)
    assert any("#nope" in m for m in web.misses)
    assert "DELETE" not in site_server.methods()


def test_html_entry_file_served_read_only_with_root_paths(tmp_path, site):
    art = Event("e3", 9.0, "artifact", "", "index.html", "", {"path": str(site / "index.html"), "kind": "web",
                                                                 "delivered": True})
    rep = capture_product_report(Product(), [art], tmp_path / "cap", budget_s=60)
    [web] = rep.web
    assert web.target.kind == "html" and web.ok
    first = rep.events[0]
    assert first.data["target_kind"] == "html" and first.data["url"] == str(site / "index.html")
    with Image.open(first.data["path"]) as im:    # /assets/site.css (root-absolute) loaded via the rewrite
        r, g, b = im.convert("RGB").getpixel((300, 300))
        assert b > 150 and r > 90 and g < 120, (r, g, b)


def test_pdf_first_pages(tmp_path):
    pdf = tmp_path / "doc" / "plan.pdf"
    pdf.parent.mkdir()
    p1 = Image.new("RGB", (850, 1100), "white")
    p1.paste((200, 30, 30), (100, 100, 750, 300))
    p1.save(pdf, save_all=True, append_images=[Image.new("RGB", (850, 1100), (30, 30, 200))])
    art = Event("e1", 1.0, "artifact", "", "plan.pdf", "", {"path": str(pdf), "kind": "pdf"})
    rep = capture_product_report(Product(kind="doc"), [art], tmp_path / "cap", budget_s=60)
    pages = by_kind(rep, "pdf_page")
    assert len(pages) == 2, rep.web[0].to_dict() if rep.web else rep.warnings
    assert pages[0].weight > pages[1].weight and pages[0].data["pages"] == 2
    with Image.open(pages[0].data["path"]) as im:
        w, h = im.size
        assert 1.2 < h / w < 1.4                      # cropped to the page (letter-ish), no viewer chrome
        assert im.convert("RGB").getpixel((w // 2, h // 2)) == (255, 255, 255)
    with Image.open(pages[1].data["path"]) as im:
        r, _, b = im.convert("RGB").getpixel((im.width // 2, im.height // 2))
        assert b > 150 and r < 80


def test_budget_timeout_returns_partial_without_raising(tmp_path, site):
    with FixtureServer(site, delay_s=4.0, delay_prefix="/assets") as slow:   # the page itself answers fast
        t0 = time.monotonic()
        rep = capture_product_report(Product(urls=[slow.url]), [], tmp_path / "cap", budget_s=6)
        wall = time.monotonic() - t0
    assert wall < 6 + 12, wall                        # budget + bounded clean-up grace
    assert rep.error is None and rep.timed_out
    assert rep.report_path and Path(rep.report_path).is_file()


def test_cancel_stops_quickly(tmp_path, site_server):
    cancel = threading.Event()

    def progress(done, total, label):
        if label.startswith("capturing"):
            cancel.set()

    t0 = time.monotonic()
    rep = capture_product_report(Product(urls=[site_server.url]), [], tmp_path / "cap", budget_s=60,
                                 progress=progress, cancel=cancel)
    assert time.monotonic() - t0 < 20 and rep.cancelled and rep.error is None


def test_crops_only_plan_for_on_demand_director_requests(tmp_path, site_server):
    plan = WebPlan(desktop=(), mobile=None, full_page=False, interactions=[], auto_features=0)
    rep = capture_product_report(Product(urls=[site_server.url]), [], tmp_path / "cap", budget_s=40, web_plan=plan,
                                 features=["Instant search", {"selector": "#pricing .plan.pro", "label": "Pro plan"}])
    assert [(e.data["kind"], e.data["label"]) for e in rep.events] == [("element", "Instant search"),
                                                                        ("element", "Pro plan")]


def test_app_shell_inner_scroller_is_scrolled_and_flagged(tmp_path, site_server):
    rep = capture_product_report(Product(urls=[site_server.url + "shell.html"]), [], tmp_path / "cap", budget_s=40,
                                 web_plan=WebPlan(mobile=None, desktop=((1440, 900),)))
    [web] = rep.web
    assert web.meta["inner_scroller"] and any("app-shell" in w for w in web.warnings)
    colours = []
    for e in by_kind(rep, "interaction"):
        with Image.open(e.data["path"]) as im:
            colours.append(im.convert("RGB").getpixel((900, 450)))
    assert len(colours) == 3 and len(set(colours)) == 3, colours     # 33 / 66 / 100 % show different blocks
