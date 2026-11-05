"""CDP client against an in-process fake DevTools websocket server."""
from __future__ import annotations

import asyncio
import json

import pytest

from showreel_core.render.cdp import CDPClosed, CDPConnection, CDPError, CDPTimeout


async def _fake_devtools(ws) -> None:
    async for raw in ws:
        msg = json.loads(raw)
        method, mid, sid = msg["method"], msg["id"], msg.get("sessionId")
        if method == "Echo":
            await ws.send(json.dumps({"id": mid, "result": msg["params"], **({"sessionId": sid} if sid else {})}))
        elif method == "Fail":
            await ws.send(json.dumps({"id": mid, "error": {"code": -32000, "message": "nope"}}))
        elif method == "Hang":
            pass
        elif method == "Emit":
            await ws.send(json.dumps({"method": "Page.loadEventFired", "params": {"n": 1}, "sessionId": "S1"}))
            await ws.send(json.dumps({"method": "Page.loadEventFired", "params": {"n": 2}, "sessionId": "S2"}))
            await ws.send(json.dumps({"id": mid, "result": {}}))
        elif method == "Close":
            await ws.close()
            return


def _run(coro):
    return asyncio.run(coro)


async def _with_server(fn):
    from websockets.asyncio.server import serve

    async with serve(_fake_devtools, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        conn = await CDPConnection.connect(f"ws://127.0.0.1:{port}/devtools/browser/x", default_timeout=5)
        try:
            return await fn(conn)
        finally:
            await conn.close()


def test_send_and_session_routing():
    async def fn(conn):
        assert await conn.send("Echo", {"a": 1}) == {"a": 1}
        s = conn.session("S9")
        assert await s.send("Echo", {"b": 2}) == {"b": 2}
        results = await asyncio.gather(*(conn.send("Echo", {"i": i}) for i in range(20)))
        assert [r["i"] for r in results] == list(range(20))
    _run(_with_server(fn))


def test_error_and_timeout():
    async def fn(conn):
        with pytest.raises(CDPError) as ei:
            await conn.send("Fail")
        assert ei.value.code == "cdp" and "nope" in ei.value.message
        with pytest.raises(CDPTimeout) as et:
            await conn.send("Hang", timeout=0.2)
        assert et.value.code == "cdp_timeout"
        assert await conn.send("Echo", {"still": "alive"}) == {"still": "alive"}
    _run(_with_server(fn))


def test_events_filtered_by_session():
    async def fn(conn):
        seen = []
        conn.on("Page.loadEventFired", lambda m: seen.append(("any", m["params"]["n"])))
        conn.session("S2").on("Page.loadEventFired", lambda m: seen.append(("s2", m["params"]["n"])))
        waiter = asyncio.ensure_future(conn.session("S2").wait_for("Page.loadEventFired"))
        await asyncio.sleep(0)
        await conn.send("Emit")
        assert (await waiter) == {"n": 2}
        assert ("s2", 2) in seen and ("s2", 1) not in seen and ("any", 1) in seen and ("any", 2) in seen
    _run(_with_server(fn))


def test_close_fails_pending_and_future_calls():
    async def fn(conn):
        pending = asyncio.ensure_future(conn.send("Hang", timeout=5))
        waiter = asyncio.ensure_future(conn.wait_for("Never.happens", timeout=5))
        await asyncio.sleep(0.05)
        with pytest.raises(CDPClosed):
            await conn.send("Close")
        with pytest.raises(CDPClosed):
            await pending
        with pytest.raises(CDPClosed):
            await waiter
        assert conn.closed
        with pytest.raises(CDPClosed):
            await conn.send("Echo")
    _run(_with_server(fn))


def test_connect_failure_is_cdp_closed():
    with pytest.raises(CDPClosed):
        _run(CDPConnection.connect("ws://127.0.0.1:9/devtools/browser/none", timeout=2))
