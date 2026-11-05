"""Target planning: URL policy, reachability probes, local HTML files, media artifacts (no browser)."""
from __future__ import annotations

import socket
from pathlib import Path

import pytest
from conftest import FixtureServer

from showreel_core.capture.targets import (
    classify_host,
    file_url_to_path,
    inspect_html,
    parse_url,
    plan_targets,
    probe_url,
    referenced_files,
    session_urls,
    too_broad_to_serve,
)
from showreel_core.contracts import Event, Product


def ev(i: int, kind: str = "terminal", **data) -> Event:
    return Event(f"e{i}", float(i), kind, "", "", "", data)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize(("host", "cls"), [
    ("localhost", "loopback"), ("127.0.0.1", "loopback"), ("127.8.9.1", "loopback"), ("::1", "loopback"),
    ("[::1]", "loopback"), ("0.0.0.0", "loopback"), ("app.localhost", "loopback"),
    ("192.168.1.20", "lan"), ("10.0.0.5", "lan"), ("172.16.3.4", "lan"), ("169.254.1.1", "lan"),
    ("100.64.1.2", "lan"), ("fd12::1", "lan"), ("printer.local", "lan"), ("raspberrypi", "lan"),
    ("nas.home.arpa", "lan"), ("example.com", "public"), ("8.8.8.8", "public"), ("my-app.vercel.app", "public"),
    ("", "invalid"), ("bad host!", "invalid"),
])
def test_classify_host(host, cls):
    assert classify_host(host) == cls


def test_parse_url_normalises():
    p = parse_url("http://0.0.0.0:5173")
    assert p and p.url == "http://127.0.0.1:5173/" and p.host_class == "loopback" and p.port == 5173
    q = parse_url("http://localhost:5173/#/dashboard")
    assert q and q.path == "/#/dashboard" and q.key == "http://loopback:5173/#/dashboard"
    assert parse_url("http://[::1]:8080/x?y=1").netloc == "[::1]:8080"
    site = parse_url("https://site.example/")
    assert site and site.port == 443 and site.netloc == "site.example"
    assert parse_url("ftp://x/") is None and parse_url("not a url") is None
    assert parse_url("http://localhost:3000/").key == parse_url("http://127.0.0.1:3000").key


def test_file_url_to_path():
    assert file_url_to_path("file:///C:/proj/index.html") == Path("C:/proj/index.html")
    assert file_url_to_path("file:///home/a/My%20Site/index.html") == Path("/home/a/My Site/index.html")
    assert file_url_to_path("http://x/") is None


def test_session_urls_scans_nested_data():
    events = [ev(0, cmd="npm run dev", output_lines=["  Local:   http://localhost:5173/", "ready"]),
              ev(1, "browser_nav", url="http://192.168.1.9:8000/app"),
              ev(2, "final_answer", text="Deployed to https://orbit.vercel.app/ (done).")]
    urls = session_urls(events)
    assert urls["http://localhost:5173/"] == ["e0"]
    assert "http://192.168.1.9:8000/app" in urls and "https://orbit.vercel.app/" in urls


def test_unreachable_loopback_url_is_skipped():
    url = f"http://127.0.0.1:{free_port()}/"
    plan = plan_targets(Product(urls=[url]), [], probe_timeout_s=0.5)
    assert plan.targets == []
    assert [(s.source, s.reason) for s in plan.skipped] == [(url, "unreachable")]
    assert "refused" in plan.skipped[0].detail or "answer" in plan.skipped[0].detail


def test_reachable_loopback_url_found_with_title(site_server):
    events = [ev(3, server_urls=[site_server.url])]
    plan = plan_targets(Product(urls=[site_server.url]), events)
    [t] = plan.targets
    assert t.kind == "url" and t.host_class == "loopback" and t.status == 200
    assert t.title == "Orbit Notes" and t.event_ids == ["e3"] and t.content_type == "text/html"
    assert site_server.methods() == {"GET"}


def test_loopback_spellings_are_one_target(site_server):
    port = site_server.url.rsplit(":", 1)[1].strip("/")
    plan = plan_targets(Product(urls=[site_server.url, f"http://localhost:{port}", f"http://0.0.0.0:{port}/"]), [])
    assert len(plan.of("url")) == 1
    assert [s.reason for s in plan.skipped] == ["duplicate", "duplicate"]


def test_public_url_refused_without_allow_network():
    events = [ev(0, "final_answer", text="live at https://orbit.vercel.app/")]
    plan = plan_targets(Product(urls=["https://orbit.vercel.app/"]), events, probe=False)
    assert not plan.targets and plan.skipped[0].reason == "refused_public"
    assert "allow_network" in plan.skipped[0].detail


def test_public_url_needs_session_mention_and_https():
    prod = Product(urls=["https://orbit.vercel.app/", "https://elsewhere.example/", "http://plain.example/"])
    events = [ev(0, "final_answer", text="https://orbit.vercel.app/ and http://plain.example/")]
    plan = plan_targets(prod, events, allow_network=True, probe=False)
    assert [t.url for t in plan.targets] == ["https://orbit.vercel.app/"]
    reasons = {s.source: s.reason for s in plan.skipped}
    assert reasons == {"https://elsewhere.example/": "refused_public", "http://plain.example/": "refused_http"}


def test_lan_host_only_when_used_in_session():
    prod = Product(urls=["http://192.168.1.9:8000/", "http://10.1.1.1:3000/"])
    events = [ev(0, "browser_nav", url="http://192.168.1.9:8000/app")]
    plan = plan_targets(prod, events, probe=False)
    assert [t.host for t in plan.targets] == ["192.168.1.9"]
    assert [(s.source, s.reason) for s in plan.skipped] == [("http://10.1.1.1:3000/", "refused_lan")]


def test_redirect_off_policy_is_refused(site):
    with FixtureServer(site, redirect_to="https://evil.example/") as srv:
        pr = probe_url(srv.url, allow=lambda p: p.host_class == "loopback")
        assert not pr.ok and "leaves the allowed hosts" in pr.error
        plan = plan_targets(Product(urls=[srv.url]), [])
        assert plan.skipped[0].reason == "http_error"


def test_http_error_status_is_skipped(site_server):
    plan = plan_targets(Product(urls=[site_server.url + "missing.html"]), [])
    assert plan.skipped[0].reason == "http_error" and "404" in plan.skipped[0].detail


def test_html_entry_files(tmp_path):
    proj = tmp_path / "proj"
    (proj / "css").mkdir(parents=True)
    (proj / "index.html").write_text('<title>Demo Page</title><link href="css/a.css" rel="stylesheet">'
                                     '<script src="https://cdn.example/x.js"></script>', encoding="utf-8")
    (proj / "css" / "a.css").write_text("body{background:url('../bg.png')}", encoding="utf-8")
    (proj / "bg.png").write_bytes(b"\x89PNG")
    (proj / "app.html").write_text('<script type="module" src="/src/main.tsx"></script>', encoding="utf-8")
    events = [Event("e5", 5, "artifact", "", "", "", {"path": str(proj / "index.html"), "kind": "web",
                                                         "delivered": True}),
              Event("e6", 6, "artifact", "", "", "", {"path": str(proj / "app.html"), "kind": "web"}),
              Event("e7", 7, "artifact", "", "", "", {"path": str(proj / "gone.html"), "kind": "web"})]
    plan = plan_targets(Product(entry_files=[str(proj / "index.html")]), events)
    [t] = plan.targets
    assert t.kind == "html" and t.title == "Demo Page" and t.serve_rel == "index.html" and not t.staged
    assert Path(t.serve_root) == proj.resolve() and t.event_ids == ["e5"] and t.delivered
    assert any("external resource" in n for n in t.notes)
    reasons = {Path(s.source).name: s.reason for s in plan.skipped}
    assert reasons == {"app.html": "needs_build", "gone.html": "not_found"}
    assert sorted(referenced_files(proj / "index.html")) == ["bg.png", "css/a.css"]
    assert inspect_html(proj / "app.html")[1]


def test_too_broad_folders():
    home = Path.home()
    assert too_broad_to_serve(home) and too_broad_to_serve(home / "Desktop") and too_broad_to_serve(Path(home.anchor))
    assert not too_broad_to_serve(home / "projects" / "site")


def test_media_targets_from_artifacts(tmp_path):
    for name in ("car.mp4", "shot.png", "doc.pdf"):
        (tmp_path / name).write_bytes(b"x")
    events = [Event(f"e{i}", i, "artifact", "", "", "", {"path": str(tmp_path / n), "kind": k})
              for i, (n, k) in enumerate([("car.mp4", "video"), ("shot.png", "image"), ("doc.pdf", "pdf"),
                                          ("lost.png", "image"), ("song.mp3", "audio")])]
    plan = plan_targets(Product(kind="media"), events)
    assert [t.kind for t in plan.targets] == ["video", "image", "pdf"]
    assert plan.of("pdf")[0].serve_rel == "doc.pdf"
    assert [s.reason for s in plan.skipped] == ["not_found"]
