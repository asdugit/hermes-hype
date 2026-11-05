"""capture_product end to end without a browser: refusals, unreachable targets, media-only, robustness."""
from __future__ import annotations

import json
import socket
from pathlib import Path

from synth import car_frame

from showreel_core.capture import capture_product, capture_product_report
from showreel_core.contracts import Event, Product


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_nothing_capturable_returns_empty_and_writes_report(tmp_path):
    evs = capture_product(Product(name="cli tool", kind="cli"), [], tmp_path / "cap")
    assert evs == []
    rep = json.loads((tmp_path / "cap" / "capture.json").read_text(encoding="utf-8"))
    assert rep["ok"] is False and rep["error"] is None and "network_policy" in rep


def test_unreachable_url_gives_no_events_and_a_reason(tmp_path):
    url = f"http://localhost:{free_port()}/"
    rep = capture_product_report(Product(urls=[url]), [], tmp_path / "cap", budget_s=10)
    assert rep.events == [] and rep.web == [] and rep.error is None
    assert [(s.source, s.reason) for s in rep.plan.skipped] == [(url, "unreachable")]


def test_public_url_refused_without_allow_network(tmp_path):
    evs = [Event("e0", 0, "final_answer", "", "", "", {"text": "deployed: https://orbit-notes.vercel.app/"})]
    rep = capture_product_report(Product(urls=["https://orbit-notes.vercel.app/"]), evs, tmp_path / "cap")
    assert rep.events == [] and rep.plan.skipped[0].reason == "refused_public" and not rep.allow_network


def test_media_only_capture_numbers_events_after_the_session(tmp_path):
    img = tmp_path / "proj" / "car.png"
    img.parent.mkdir()
    car_frame()[0].save(img)
    session = [Event("e0", 0.0, "user_prompt", "", "", "", {"text": "render my car"}),
               Event("e1", 3.0, "artifact", "", "car.png", "", {"path": str(img), "kind": "image", "delivered": True}),
               Event("e9", 12.5, "final_answer", "", "", "", {"text": "done"})]
    seen = []
    evs = capture_product(Product(kind="media"), session, tmp_path / "cap", progress=lambda *a: seen.append(a))
    [ev] = evs
    assert ev.id == "e10" and ev.t == 12.5 and ev.kind == "product_capture" and ev.tool == "showreel_capture"
    d = ev.data
    assert d["kind"] == "image" and d["target_kind"] == "image" and d["viewport"] == [960, 540]
    assert d["full_page"] is False and d["page_title"] == "car.png" and d["source_ids"] == ["e1"]
    assert Path(d["path"]).is_file() and d["cutout"]["grade"] == "good" and Path(d["cutout"]["path"]).is_file()
    assert ev.weight > 0.85 and seen and seen[-1][2].startswith("captured 1")


def test_garbage_inputs_never_raise(tmp_path):
    evs = capture_product({"name": "x", "urls": ["notaurl", "ftp://x"], "bogus": 1},
                          [{"id": "e1", "t": 0, "kind": "artifact", "tool": "", "title": "", "summary": "",
                            "data": {"path": "/definitely/missing.mp4", "kind": "video"}}, {"weird": True}, 42],
                          tmp_path / "cap", budget_s=5)
    assert evs == []
    rep = capture_product_report(None, None, tmp_path / "cap2")       # type: ignore[arg-type]
    assert rep.error is None and rep.events == []


def test_unwritable_out_dir_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    rep = capture_product_report(Product(), [], blocker / "sub")
    assert rep.error is not None and rep.events == []
