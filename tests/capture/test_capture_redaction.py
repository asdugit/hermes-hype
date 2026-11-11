"""Capture events get the session's redaction pass (audit 2026-11-11): they are created after the session events
were redacted, and the digest rebuilt after capture sends their page titles/URLs to the storyboard LLM."""
from showreel_core.capture.capture import CaptureReport, _events
from showreel_core.capture.targets import CaptureTarget
from showreel_core.capture.web import Shot, WebResult
from showreel_core.contracts import Event


def test_capture_events_are_redacted():
    tok = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    tgt = CaptureTarget("url", f"http://localhost:5173/?access_token={tok}", "product url",
                        url=f"http://localhost:5173/?access_token={tok}", host="localhost")
    wr = WebResult(tgt, meta={"title": "Dashboard — jane.doe@corp-mail.com"})
    shot_path = "/tmp/job/capture/web/url_01/viewport.png"
    wr.shots.append(Shot("viewport", shot_path, tgt.url, (1440, 900), 1.0, (1440, 900)))
    rep = CaptureReport(web=[wr])
    out = _events(rep, [Event(id="e3", t=1.0, kind="user_prompt", tool="", title="", summary="", data={})])
    ev = out[0]
    blob = ev.title + ev.summary + str(ev.data)
    assert "jane.doe@corp-mail.com" not in blob and tok not in blob
    assert ev.data["page_title"].startswith("Dashboard") and ev.data["path"] == shot_path   # our file stays usable
    assert ev.id == "e4" and ev.kind == "product_capture"
