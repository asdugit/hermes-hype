"""Capture browser plumbing: one headless Chromium we own, isolated pages with a request policy.

Reuses the renderer's launcher and CDP client (``showreel_core.render``). Differences from a render
page: a real-looking user agent (``HeadlessChrome`` -> ``Chrome``), per-page browser contexts
(no shared cookies/storage), mobile emulation, request interception by :class:`NetPolicy` with
write blocking and root-path rewriting, network-idle tracking, auto-dismissed JS dialogs, denied
downloads, closed popups.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import re
import time
from pathlib import Path
from typing import Any

from ..render.cdp import CDPConnection, CDPSession
from ..render.chromium import NO_BROWSER_HINT, BrowserCandidate, LaunchedBrowser, browser_candidates, launch_any
from ..render.errors import RenderError
from .policy import NetPolicy, resolver_rules

STREAMING_TYPES = frozenset({"EventSource", "WebSocket", "Ping", "CSPViolationReport"})
LONG_REQUEST_S = 5.0      # requests pending longer than this (long polls) do not block "network idle"

READY_JS = """(async () => {
  const cap = (p, ms) => Promise.race([p, new Promise(r => setTimeout(r, ms))]);
  try { await cap(document.fonts ? document.fonts.ready : Promise.resolve(), 3000); } catch (e) {}
  const imgs = [...document.images].filter(i => { const r = i.getBoundingClientRect();
    return r.bottom > -50 && r.top < innerHeight * 2; });
  await cap(Promise.all(imgs.map(i => i.complete ? null : (i.decode ? i.decode().catch(() => null) : null))), 3000);
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return {fonts: document.fonts ? document.fonts.status : 'n/a', images: imgs.length, state: document.readyState};
})()"""


def mobile_user_agent(desktop_ua: str) -> str:
    """Chrome-on-Android UA with the same major version (the reduced UA Chrome itself sends)."""
    m = re.search(r"Chrome/(\d+)", desktop_ua)
    major = m.group(1) if m else "140"
    return (f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 "
            "Mobile Safari/537.36")


class CapturePage:
    """One tab in its own browser context, governed by a :class:`NetPolicy`."""

    def __init__(self, browser: CaptureBrowser, session: CDPSession, target_id: str, context_id: str,
                 policy: NetPolicy) -> None:
        self.browser = browser
        self.session = session
        self.target_id = target_id
        self.context_id = context_id
        self.policy = policy
        self.w = self.h = 0
        self.dpr = 1.0
        self.mobile = False
        self.blocked: list[str] = []
        self.blocked_writes: list[str] = []
        self.third_party: list[str] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self._inflight: dict[str, tuple[float, str]] = {}
        self._last_activity = time.monotonic()

    # ------------------------------------------------------------------ events
    async def _on_paused(self, msg: dict[str, Any]) -> None:
        p = msg.get("params", {})
        req = p.get("request", {})
        url, method = str(req.get("url", "")), str(req.get("method", "GET"))
        verdict, extra = self.policy.decide(url, method)
        try:
            if verdict == "continue":
                params: dict[str, Any] = {"requestId": p["requestId"]}
                if extra:
                    params["url"] = extra
                elif self.policy.third_party and not url.startswith(tuple(self.policy.origins)) \
                        and url.startswith("http") and len(self.third_party) < 100:
                    self.third_party.append(url[:300])
                await self.session.send("Fetch.continueRequest", params, timeout=10)
            else:
                bucket = self.blocked_writes if extra.startswith("write") else self.blocked
                if len(bucket) < 100:
                    bucket.append(f"{method} {url[:300]}" if bucket is self.blocked_writes else url[:300])
                await self.session.send("Fetch.failRequest", {"requestId": p["requestId"],
                                                              "errorReason": "BlockedByClient"}, timeout=10)
        except RenderError:
            pass  # navigated away or closed

    def _on_request(self, msg: dict[str, Any]) -> None:
        p = msg.get("params", {})
        if p.get("type") in STREAMING_TYPES:
            return
        self._inflight[p.get("requestId", "")] = (time.monotonic(), str(p.get("type", "")))
        self._last_activity = time.monotonic()

    def _on_done(self, msg: dict[str, Any]) -> None:
        self._inflight.pop(msg.get("params", {}).get("requestId", ""), None)
        self._last_activity = time.monotonic()

    def _on_exception(self, msg: dict[str, Any]) -> None:
        d = msg.get("params", {}).get("exceptionDetails", {})
        self._note(f"exception: {d.get('exception', {}).get('description') or d.get('text', '')}")

    def _on_console(self, msg: dict[str, Any]) -> None:
        p = msg.get("params", {})
        if p.get("type") in ("error", "assert"):
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            self._note(f"console.{p.get('type')}: {args}")

    def _note(self, text: str) -> None:
        if len(self.errors) < 40:
            self.errors.append(text[:300])

    async def _on_dialog(self, msg: dict[str, Any]) -> None:
        p = msg.get("params", {})
        self.dialogs.append(f"{p.get('type')}: {str(p.get('message', ''))[:120]}")
        with contextlib.suppress(RenderError):
            await self.session.send("Page.handleJavaScriptDialog", {"accept": p.get("type") == "beforeunload"},
                                    timeout=5)

    # ------------------------------------------------------------------ setup
    async def emulate(self, w: int, h: int, *, dpr: float = 1.0, mobile: bool = False) -> None:
        """Viewport ``w`` x ``h`` CSS px at ``dpr``; ``mobile`` adds touch, a mobile UA and mobile layout."""
        s = self.session
        await s.send("Emulation.setDeviceMetricsOverride",
                     {"width": w, "height": h, "deviceScaleFactor": dpr, "mobile": mobile,
                      "screenWidth": w, "screenHeight": h})
        if mobile != self.mobile or not self.w:
            await s.send("Emulation.setTouchEmulationEnabled",
                         {"enabled": mobile, "maxTouchPoints": 5 if mobile else 1})
            ua = mobile_user_agent(self.browser.user_agent) if mobile else self.browser.user_agent
            override: dict[str, Any] = {"userAgent": ua}
            if mobile:
                major = (re.search(r"Chrome/(\d+)", ua) or [None, "140"])[1]
                override["userAgentMetadata"] = {
                    "brands": [{"brand": "Chromium", "version": major}, {"brand": "Not.A/Brand", "version": "99"}],
                    "platform": "Android", "platformVersion": "10.0.0", "architecture": "", "model": "K",
                    "mobile": True}
            await s.send("Emulation.setUserAgentOverride", override)
        self.w, self.h, self.dpr, self.mobile = w, h, dpr, mobile

    async def goto(self, url: str, *, timeout: float = 20.0) -> str:
        """Navigate and wait for ``load`` (bounded). Returns "" or the navigation error text."""
        loaded = asyncio.ensure_future(self.session.wait_for("Page.loadEventFired", timeout=timeout))
        try:
            res = await self.session.send("Page.navigate", {"url": url}, timeout=timeout)
            if res.get("errorText"):
                return str(res["errorText"])
            try:
                await loaded
            except RenderError:
                return ""  # no load event in time (slow asset); capture what is there
            return ""
        finally:
            if not loaded.done():
                loaded.cancel()
                with contextlib.suppress(BaseException):
                    await loaded

    async def network_idle(self, *, idle_ms: int = 500, timeout: float = 8.0) -> bool:
        """True once no (non-streaming, < 5 s old) request was pending or finished for ``idle_ms``."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            now = time.monotonic()
            active = [r for r, (t0, _) in self._inflight.items() if now - t0 < LONG_REQUEST_S]
            if not active and now - self._last_activity >= idle_ms / 1000:
                return True
            await asyncio.sleep(0.05)
        return False

    async def ready(self, *, idle_ms: int = 500, settle_ms: int = 600, timeout: float = 10.0) -> dict[str, Any]:
        """Network idle + fonts + visible images decoded + two frames + a settle delay (animations)."""
        loop = asyncio.get_running_loop()
        t_end = loop.time() + timeout
        idle = await self.network_idle(idle_ms=idle_ms, timeout=max(0.5, timeout * 0.6))
        info: dict[str, Any] = {}
        with contextlib.suppress(RenderError):
            info = await self.eval(READY_JS, timeout=max(1.0, t_end - loop.time())) or {}
        await asyncio.sleep(max(0.0, min(settle_ms / 1000, t_end - loop.time())))
        info["network_idle"] = idle
        return info

    # ------------------------------------------------------------------ actions
    async def eval(self, expression: str, *, timeout: float = 10.0) -> Any:
        """Evaluate JS (promises awaited) and return its JSON value. Page exceptions -> None."""
        res = await self.session.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                           "returnByValue": True, "userGesture": True},
                                      timeout=timeout)
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            self._note(f"capture script: {d.get('exception', {}).get('description') or d.get('text', '')}")
            return None
        return res.get("result", {}).get("value")

    async def shot(self, *, clip: dict[str, float] | None = None, beyond: bool = False, fmt: str = "png",
                   quality: int = 90, timeout: float = 30.0) -> bytes:
        """``Page.captureScreenshot`` (viewport, or ``clip`` in page CSS px; ``beyond`` for off-screen areas)."""
        params: dict[str, Any] = {"format": fmt, "captureBeyondViewport": beyond, "fromSurface": True}
        if fmt == "jpeg":
            params["quality"] = int(quality)
        if clip is not None:
            params["clip"] = {"scale": 1, **clip}
        res = await self.session.send("Page.captureScreenshot", params, timeout=timeout)
        return base64.b64decode(res["data"])

    async def mouse(self, kind: str, x: float, y: float, *, button: str = "none", clicks: int = 0) -> None:
        await self.session.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": button,
                                                             "clickCount": clicks}, timeout=10)

    async def close(self) -> None:
        conn = self.browser.conn
        if conn is None:
            return
        with contextlib.suppress(RenderError):
            await conn.send("Target.closeTarget", {"targetId": self.target_id}, timeout=5)
        with contextlib.suppress(RenderError):
            await conn.send("Target.disposeBrowserContext", {"browserContextId": self.context_id}, timeout=5)


class CaptureBrowser:
    """A headless Chromium owned by one capture run. Use ``async with``; always killed on exit."""

    def __init__(self, *, allowed_hosts: tuple[str, ...] = (), open_dns: bool = False,
                 ignore_cert_errors: bool = False, browser: BrowserCandidate | None = None,
                 profile_root: Path | None = None, timeout_s: float = 30.0) -> None:
        self.allowed_hosts = allowed_hosts
        self.open_dns = open_dns
        self.ignore_cert_errors = ignore_cert_errors
        self.candidate = browser
        self.profile_root = profile_root
        self.timeout_s = timeout_s
        self.launched: LaunchedBrowser | None = None
        self.conn: CDPConnection | None = None
        self.user_agent = ""
        self.product = ""
        self.popups_closed = 0

    async def __aenter__(self) -> CaptureBrowser:
        cands = [self.candidate] if self.candidate else browser_candidates()
        if not cands:
            raise RenderError("no_browser", "no Chromium-based browser found", hint=NO_BROWSER_HINT)
        flags = [f"--host-resolver-rules={resolver_rules(self.allowed_hosts, open_dns=self.open_dns)}"]
        self.launched = await asyncio.to_thread(launch_any, cands, gpu=False, window_size=(1440, 900),
                                                profile_root=self.profile_root, extra_flags=flags)
        try:
            self.conn = await CDPConnection.connect(self.launched.ws_url, default_timeout=self.timeout_s)
            ver = await self.conn.send("Browser.getVersion")
            self.user_agent = str(ver.get("userAgent", "")).replace("HeadlessChrome", "Chrome")
            self.product = str(ver.get("product", ""))
            self.conn.on("Target.targetCreated", self._on_target)
            await self.conn.send("Target.setDiscoverTargets", {"discover": True})
            if self.ignore_cert_errors:
                await self.conn.send("Security.setIgnoreCertificateErrors", {"ignore": True})
        except BaseException:
            await self._shutdown()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._shutdown()

    async def _shutdown(self) -> None:
        if self.conn is not None:
            with contextlib.suppress(RenderError):
                await self.conn.send("Browser.close", timeout=3)
            await self.conn.close()
            self.conn = None
        if self.launched is not None:
            await asyncio.to_thread(self.launched.kill, 1.0)
            self.launched = None

    async def _on_target(self, msg: dict[str, Any]) -> None:
        info = msg.get("params", {}).get("targetInfo", {})
        if info.get("type") == "page" and info.get("openerId") and self.conn is not None:
            self.popups_closed += 1     # window.open / target=_blank from a captured page: never load it
            with contextlib.suppress(RenderError):
                await self.conn.send("Target.closeTarget", {"targetId": info["targetId"]}, timeout=5)

    async def new_page(self, policy: NetPolicy, *, w: int, h: int, dpr: float = 1.0,
                       mobile: bool = False) -> CapturePage:
        """A fresh tab in its own browser context with ``policy`` enforced from the first request."""
        assert self.conn is not None, "browser not started"
        conn = self.conn
        ctx = (await conn.send("Target.createBrowserContext", {"disposeOnDetach": True}))["browserContextId"]
        tid = (await conn.send("Target.createTarget", {"url": "about:blank", "browserContextId": ctx}))["targetId"]
        sid = (await conn.send("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
        page = CapturePage(self, conn.session(sid), tid, ctx, policy)
        s = page.session
        s.on("Fetch.requestPaused", page._on_paused)
        s.on("Network.requestWillBeSent", page._on_request)
        s.on("Network.loadingFinished", page._on_done)
        s.on("Network.loadingFailed", page._on_done)
        s.on("Runtime.exceptionThrown", page._on_exception)
        s.on("Runtime.consoleAPICalled", page._on_console)
        s.on("Page.javascriptDialogOpening", page._on_dialog)
        await s.send("Page.enable")
        await s.send("Runtime.enable")
        await s.send("Network.enable")
        with contextlib.suppress(RenderError):
            await s.send("Network.setBypassServiceWorker", {"bypass": True})
        await s.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
        with contextlib.suppress(RenderError):
            await conn.send("Browser.setDownloadBehavior", {"behavior": "deny", "browserContextId": ctx})
        await s.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        await page.emulate(w, h, dpr=dpr, mobile=mobile)
        return page
