"""Loopback HTTP server for one job directory (read-only, GET/HEAD only).

Why not ``file://``: Chromium refuses ES module scripts from ``file://`` (opaque origin, CORS),
and style packs may import three.js r170 modules. A ``ThreadingHTTPServer`` bound to
``127.0.0.1:0`` gives the page a real origin; every URL lives under a random token prefix so
other local processes cannot guess paths while a render runs. No directory listings.
"""
from __future__ import annotations

import secrets
import socketserver
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

MIME = {
    ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".wasm": "application/wasm",
    ".css": "text/css", ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".avif": "image/avif", ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
    ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".mp3": "audio/mpeg", ".txt": "text/plain; charset=utf-8",
}


class _Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **MIME}
    token = ""

    def _strip_token(self) -> bool:
        prefix = f"/{self.token}/"
        if not self.path.startswith(prefix):
            self.send_error(404)
            return False
        self.path = "/" + self.path[len(prefix):]
        return True

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self._strip_token():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._strip_token():
            super().do_HEAD()

    def list_directory(self, path: Any) -> None:  # type: ignore[override]
        self.send_error(404)
        return None

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self) -> None:
        # HTTPServer.server_bind calls socket.getfqdn(), a reverse-DNS lookup that can stall for
        # seconds on some machines. We only ever serve 127.0.0.1.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Keep-alive connections are aborted whenever we kill a browser; the default handler
        # prints a traceback to stderr for each one.
        pass


class PageServer:
    """Serve ``root`` at ``http://127.0.0.1:<port>/<token>/``. Use as a context manager."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.token = secrets.token_hex(8)
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "PageServer":
        handler = type("Handler", (_Handler,), {"token": self.token})
        self._httpd = _Server(("127.0.0.1", 0), partial(handler, directory=str(self.root)))
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="showreel-page-server", daemon=True)
        self._thread.start()
        return self

    @property
    def port(self) -> int:
        assert self._httpd is not None, "server not started"
        return int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        """Origin + token prefix, with a trailing slash. Requests outside it are blocked by the page."""
        return f"http://127.0.0.1:{self.port}/{self.token}/"

    def url(self, rel: str) -> str:
        """URL of ``rel`` (POSIX relative path, optional ``?query``) inside the served root."""
        path, sep, query = rel.partition("?")
        return self.base_url + quote(path.lstrip("/")) + (sep + query if sep else "")

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "PageServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
