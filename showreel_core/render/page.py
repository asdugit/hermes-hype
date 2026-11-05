"""One render page in a browser: open, block network, load, honour the ``window.__sr`` contract, capture.

Contract (``showreel_core.contracts``): ``__sr.ready`` (Promise), ``__sr.dur``, ``__sr.fps``,
``__sr.seek(t) -> Promise`` (pure function of t, resolves after one rAF), ``__sr.qa(t)``.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from .cdp import CDPConnection, CDPSession
from .errors import RenderError

READY_JS = """(async () => {
  const sr = window.__sr;
  await sr.ready;
  return {dur: Number(sr.dur), fps: Number(sr.fps), w: Number(sr.w || 0), h: Number(sr.h || 0),
          fonts: document.fonts ? document.fonts.status : 'n/a'};
})()"""
HAS_CONTRACT_JS = "!!(window.__sr && typeof window.__sr.seek === 'function' && window.__sr.ready)"


@dataclass
class PageInfo:
    """Values the page reported once ``__sr.ready`` resolved."""
    dur: float
    fps: float
    w: int = 0
    h: int = 0
    fonts: str = ""


@dataclass
class RenderPage:
    """A flattened CDP session on one tab sized exactly ``w`` x ``h`` device pixels."""
    conn: CDPConnection
    session: CDPSession
    target_id: str
    w: int
    h: int
    dpr: float = 1.0
    errors: list[str] = field(default_factory=list)      # console errors + uncaught exceptions
    blocked: list[str] = field(default_factory=list)     # URLs refused by the network guard
    allow_prefixes: tuple[str, ...] = ()

    @classmethod
    async def open(cls, conn: CDPConnection, *, w: int, h: int, dpr: float = 1.0,
                   allow_prefixes: tuple[str, ...] | None = None) -> RenderPage:
        """Create a tab, size it, and (if ``allow_prefixes`` is given) fail every other request."""
        tid = (await conn.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        sid = (await conn.send("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
        page = cls(conn, conn.session(sid), tid, w, h, dpr, allow_prefixes=tuple(allow_prefixes or ()))
        s = page.session
        s.on("Runtime.exceptionThrown", page._on_exception)
        s.on("Runtime.consoleAPICalled", page._on_console)
        await s.send("Page.enable")
        await s.send("Runtime.enable")
        if allow_prefixes is not None:
            s.on("Fetch.requestPaused", page._on_request)
            await s.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
        css_w, css_h = page.css_size
        await s.send("Emulation.setDeviceMetricsOverride",
                     {"width": css_w, "height": css_h, "deviceScaleFactor": dpr, "mobile": False})
        await s.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        return page

    @property
    def css_size(self) -> tuple[int, int]:
        return round(self.w / self.dpr), round(self.h / self.dpr)

    # ------------------------------------------------------------------ events
    def _on_exception(self, msg: dict[str, Any]) -> None:
        d = msg.get("params", {}).get("exceptionDetails", {})
        text = d.get("exception", {}).get("description") or d.get("text", "exception")
        self._note(f"exception: {text}")

    def _on_console(self, msg: dict[str, Any]) -> None:
        p = msg.get("params", {})
        if p.get("type") in ("error", "assert"):
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            self._note(f"console.{p.get('type')}: {args}")

    def _note(self, text: str) -> None:
        if len(self.errors) < 50:
            self.errors.append(text[:500])

    async def _on_request(self, msg: dict[str, Any]) -> None:
        p = msg.get("params", {})
        url = p.get("request", {}).get("url", "")
        try:
            if url.startswith(self.allow_prefixes) or url.startswith(("data:", "blob:")):
                await self.session.send("Fetch.continueRequest", {"requestId": p["requestId"]}, timeout=10)
            else:
                if len(self.blocked) < 50:
                    self.blocked.append(url[:300])
                await self.session.send("Fetch.failRequest", {"requestId": p["requestId"],
                                                              "errorReason": "BlockedByClient"}, timeout=10)
        except RenderError:
            pass  # page navigated away / closed

    # ---------------------------------------------------------------- loading
    async def goto(self, url: str, *, timeout: float = 60.0) -> None:
        """Navigate and wait for the load event."""
        import asyncio

        loaded = asyncio.ensure_future(self.session.wait_for("Page.loadEventFired", timeout=timeout))
        try:
            res = await self.session.send("Page.navigate", {"url": url}, timeout=timeout)
            if res.get("errorText"):
                raise RenderError("page_load", f"navigation failed: {res['errorText']}", url=url,
                                  blocked=self.blocked[:5])
            await loaded
        finally:
            if not loaded.done():
                loaded.cancel()

    async def wait_contract(self, *, timeout: float = 60.0) -> PageInfo:
        """Wait until ``window.__sr`` exists and ``__sr.ready`` resolves; return dur/fps/size."""
        import asyncio

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not await self.evaluate(HAS_CONTRACT_JS, await_promise=False):
            if loop.time() > deadline:
                raise RenderError("page_load", "window.__sr never appeared (missing runtime or script error)",
                                  errors=self.errors[:10], blocked=self.blocked[:10])
            await asyncio.sleep(0.05)
        try:
            v = await self.evaluate(READY_JS, timeout=max(1.0, deadline - loop.time()))
        except RenderError as e:
            if e.code == "cdp_timeout":
                raise RenderError("page_load", f"__sr.ready did not resolve within {timeout:.0f}s",
                                  errors=self.errors[:10], blocked=self.blocked[:10]) from e
            raise
        return PageInfo(float(v["dur"]), float(v["fps"]), int(v["w"]), int(v["h"]), str(v["fonts"]))

    # ---------------------------------------------------------------- per frame
    async def evaluate(self, expression: str, *, await_promise: bool = True, timeout: float | None = None) -> Any:
        """Evaluate JS and return its JSON value; page exceptions raise ``page_contract``."""
        res = await self.session.send("Runtime.evaluate", {"expression": expression, "awaitPromise": await_promise,
                                                           "returnByValue": True}, timeout=timeout)
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            text = d.get("exception", {}).get("description") or d.get("text", "")
            raise RenderError("page_contract", f"page script failed: {text[:400]}", expression=expression[:120])
        return res.get("result", {}).get("value")

    async def seek(self, t: float, *, timeout: float | None = None) -> None:
        """``await __sr.seek(t)``; ``repr(float)`` round-trips exactly into a JS double."""
        await self.evaluate(f"window.__sr.seek({float(t)!r}).then(() => 0)", timeout=timeout)

    async def capture(self, fmt: str = "jpeg", quality: int = 92, *, timeout: float | None = None) -> bytes:
        """Screenshot of exactly the w x h canvas (JPEG with ``optimizeForSpeed``, or PNG)."""
        css_w, css_h = self.css_size
        params: dict[str, Any] = {"format": fmt, "optimizeForSpeed": True, "captureBeyondViewport": False,
                                  "fromSurface": True,
                                  "clip": {"x": 0, "y": 0, "width": css_w, "height": css_h, "scale": 1}}
        if fmt == "jpeg":
            params["quality"] = int(quality)
        res = await self.session.send("Page.captureScreenshot", params, timeout=timeout)
        return base64.b64decode(res["data"])

    async def close(self) -> None:
        try:
            await self.conn.send("Target.closeTarget", {"targetId": self.target_id}, timeout=5)
        except RenderError:
            pass
