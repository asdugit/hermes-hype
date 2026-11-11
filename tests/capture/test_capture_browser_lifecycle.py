"""Capture browser lifecycle without Chromium: a cancel while Chromium is starting, or during shutdown, must still
kill the browser (audit 2026-11-11: a cancelled capture used to leave a headless Chromium + temp profile running
until the host process exited)."""
import asyncio
import time

import pytest

from showreel_core.capture import browser as cb


class FakeLaunched:
    def __init__(self, log):
        self.ws_url = "ws://127.0.0.1:9/devtools/browser/x"
        self.log = log

    def kill(self, wait_s=0.0):
        self.log.append("kill")


def _slow_launcher(log, delay):
    def launch_any(cands, **kw):
        time.sleep(delay)
        log.append("started")
        return FakeLaunched(log)
    return launch_any


@pytest.mark.parametrize("cancel_after", [0.05, 0.4])   # mid-launch, and right after the launch returned
def test_cancel_during_launch_kills_the_browser(monkeypatch, cancel_after):
    log: list[str] = []
    monkeypatch.setattr(cb, "launch_any", _slow_launcher(log, 0.3))

    async def connect_forever(*a, **kw):
        await asyncio.sleep(30)
    monkeypatch.setattr(cb.CDPConnection, "connect", staticmethod(connect_forever))

    async def main():
        async def use():
            async with cb.CaptureBrowser(browser=object()):
                await asyncio.sleep(30)
        t = asyncio.ensure_future(use())
        await asyncio.sleep(cancel_after)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        await asyncio.sleep(0.6)            # the launch thread finishes
    asyncio.run(main())
    assert log.count("started") == 1 and log.count("kill") == 1


def test_cancel_during_shutdown_still_kills(monkeypatch):
    log: list[str] = []

    class StallConn:
        async def send(self, method, params=None, timeout=None):
            await asyncio.sleep(30)          # Browser.close never answers

        async def close(self):
            log.append("conn_closed")

    async def main():
        b = cb.CaptureBrowser(browser=object())
        b.conn, b.launched = StallConn(), FakeLaunched(log)
        t = asyncio.ensure_future(b._shutdown())
        await asyncio.sleep(0.1)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    asyncio.run(main())
    assert log == ["conn_closed", "kill"]
