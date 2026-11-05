"""Loopback page server: token prefix, MIME types, read-only, no listings, no traversal."""
from __future__ import annotations

import http.client
import urllib.error
import urllib.request

import pytest

from showreel_core.render.serve import PageServer


@pytest.fixture()
def site(tmp_path):
    (tmp_path / "sub dir").mkdir()
    (tmp_path / "index.html").write_text("<p>ü</p>", encoding="utf-8")
    (tmp_path / "m.mjs").write_text("export const x = 1;", encoding="utf-8")
    (tmp_path / "sub dir" / "f.woff2").write_bytes(b"wOF2....")
    with PageServer(tmp_path) as srv:
        yield srv


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, b""


def test_serves_under_token_with_mime(site):
    assert site.base_url.startswith("http://127.0.0.1:") and site.base_url.endswith(f"/{site.token}/")
    code, h, body = _get(site.url("index.html"))
    assert code == 200 and body.decode("utf-8") == "<p>ü</p>" and h["content-type"].startswith("text/html")
    code, h, _ = _get(site.url("m.mjs"))
    assert code == 200 and h["content-type"] == "text/javascript"
    code, h, _ = _get(site.url("sub dir/f.woff2"))
    assert code == 200 and h["content-type"] == "font/woff2"


def test_query_strings_survive(site):
    assert site.url("index.html?dur=6&fps=30").endswith("index.html?dur=6&fps=30")
    assert _get(site.url("index.html?dur=6"))[0] == 200


def test_rejects_without_token_listing_and_traversal(site):
    root = site.base_url[: -len(site.token) - 1]
    assert _get(root + "index.html")[0] == 404
    assert _get(site.url("sub dir/"))[0] == 404             # no directory listing
    conn = http.client.HTTPConnection("127.0.0.1", site.port, timeout=5)
    conn.request("GET", f"/{site.token}/../../../../etc/passwd")
    assert conn.getresponse().status == 404
    conn.close()


def test_read_only(site):
    req = urllib.request.Request(site.url("index.html"), data=b"x", method="POST")
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5)
    assert ei.value.code == 501


def test_stop_releases_port(tmp_path):
    srv = PageServer(tmp_path).start()
    port = srv.port
    srv.stop()
    import socket
    with socket.socket() as s:
        assert s.connect_ex(("127.0.0.1", port)) != 0
