"""Fixtures for the capture tests: a local fixture web app (served by the test), media, render slots."""
from __future__ import annotations

import contextlib
import datetime
import os
import shutil
import threading
import time
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from showreel_core.render.chromium import browser_candidates
from showreel_core.render.errors import RenderError
from showreel_core.render.ffmpeg import resolve_ffmpeg

HERE = Path(__file__).parent
SITE = HERE / "fixture_site"


def make_site(dest: Path) -> Path:
    """Copy the fixture app and generate its images (favicon, screenshot) with Pillow."""
    shutil.copytree(SITE, dest)
    fav = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(fav).ellipse([4, 4, 60, 60], fill=(124, 58, 237, 255))
    fav.save(dest / "favicon.png")
    shot = Image.new("RGB", (640, 360), (40, 30, 70))
    d = ImageDraw.Draw(shot)
    for i in range(6):
        d.rounded_rectangle([40, 40 + i * 50, 600, 70 + i * 50], radius=8, fill=(124 + i * 15, 58, 237 - i * 20))
    shot.save(dest / "assets" / "shot.png")
    return dest


class FixtureServer:
    """A stand-in for the user's dev server: serves a folder at ``/``, logs every request,
    answers POST/PUT/DELETE with 200 (so a leaked write would be visible), optional delay
    (``delay_s`` for paths starting with ``delay_prefix``)."""

    def __init__(self, root: Path, *, delay_s: float = 0.0, delay_prefix: str = "", redirect_to: str = "") -> None:
        self.root = root
        self.log: list[tuple[str, str]] = []
        log, delay, redirect = self.log, delay_s, redirect_to

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a: Any, **kw: Any) -> None:
                super().__init__(*a, directory=str(root), **kw)

            def _record(self) -> None:
                log.append((self.command, self.path))
                if delay and self.path.startswith(delay_prefix):
                    time.sleep(delay)

            def do_GET(self) -> None:
                self._record()
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                super().do_GET()

            def do_HEAD(self) -> None:
                self._record()
                super().do_HEAD()

            def _write(self) -> None:
                self._record()
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            do_POST = do_PUT = do_DELETE = do_PATCH = _write

            def log_message(self, *a: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def __enter__(self) -> FixtureServer:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def methods(self) -> set[str]:
        return {m for m, _ in self.log}


@pytest.fixture
def site(tmp_path: Path) -> Path:
    return make_site(tmp_path / "site")


@pytest.fixture
def site_server(site: Path) -> Iterator[FixtureServer]:
    with FixtureServer(site) as srv:
        yield srv


@pytest.fixture(scope="session")
def ffmpeg_bin() -> str:
    try:
        return resolve_ffmpeg().path
    except RenderError:
        w = shutil.which("ffmpeg")
        if not w:
            pytest.skip("ffmpeg not available")
        return w


@pytest.fixture(scope="session")
def has_browser() -> None:
    if not browser_candidates():
        pytest.skip("no Chromium-based browser available")


@contextlib.contextmanager
def _slot() -> Iterator[None]:
    """Honour the shared dev-machine render slots when SHOWREEL_RENDER_SLOTS_DIR is set."""
    root = os.environ.get("SHOWREEL_RENDER_SLOTS_DIR")
    if not root:
        yield
        return
    deadline = time.time() + 900
    while True:
        for i in (1, 2, 3):
            p = Path(root) / f"render.slot{i}"
            with contextlib.suppress(OSError):
                if p.exists() and time.time() - p.stat().st_mtime >= 900:
                    p.unlink()
            try:
                fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            os.write(fd, f"wp-j-capture-tests {os.getpid()} {datetime.datetime.now().isoformat()}".encode())
            os.close(fd)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    p.unlink()
            return
        if time.time() > deadline:
            raise TimeoutError("no free render slot")
        time.sleep(5)


@pytest.fixture
def render_slot() -> Iterator[None]:
    with _slot():
        yield
