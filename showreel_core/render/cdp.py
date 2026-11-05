"""A small asyncio Chrome DevTools Protocol client over ``websockets`` (no Playwright).

One :class:`CDPConnection` per browser (the browser-level websocket). Pages are driven through
flattened sessions (``Target.attachToTarget(flatten=True)``): every message carries a
``sessionId``, so one socket multiplexes the browser and all its pages.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Awaitable, Callable

from .errors import RenderError

DEFAULT_TIMEOUT_S = 60.0
MAX_MESSAGE = 512 * 1024 * 1024        # PNG screenshots of large frames can be tens of MB base64

EventHandler = Callable[[dict[str, Any]], Any]


class CDPError(RenderError):
    """Chrome answered a command with an error."""

    def __init__(self, method: str, error: dict[str, Any]) -> None:
        super().__init__("cdp", f"{method}: {error.get('message', error)}", cdp_code=error.get("code"),
                         data=error.get("data"))
        self.method = method


class CDPTimeout(RenderError):
    """A command got no answer within its timeout (hung renderer, swapping machine, ...)."""

    def __init__(self, method: str, timeout: float) -> None:
        super().__init__("cdp_timeout", f"{method} timed out after {timeout:.0f}s")
        self.method = method


class CDPClosed(RenderError):
    """The websocket closed (browser exited or crashed)."""

    def __init__(self, reason: str = "") -> None:
        super().__init__("cdp_closed", f"DevTools connection closed{': ' + reason if reason else ''}")


class CDPConnection:
    """Browser-level CDP connection. Use :meth:`connect`, then :meth:`send` / :meth:`on` / :meth:`wait_for`."""

    def __init__(self, ws: Any, default_timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._ws = ws
        self._ids = itertools.count(1)
        self._pending: dict[int, tuple[asyncio.Future[dict[str, Any]], str]] = {}
        self._handlers: dict[tuple[str, str | None], list[EventHandler]] = {}
        self._closed: CDPClosed | None = None
        self.default_timeout = default_timeout
        self._tasks: set[asyncio.Task[Any]] = set()   # strong refs for async event handlers
        self._reader = asyncio.get_running_loop().create_task(self._read_loop(), name="cdp-reader")

    @classmethod
    async def connect(cls, ws_url: str, *, timeout: float = 30.0,
                      default_timeout: float = DEFAULT_TIMEOUT_S) -> "CDPConnection":
        """Open the websocket (no compression, no keepalive pings, large frames allowed)."""
        from websockets.asyncio.client import connect

        try:
            ws = await asyncio.wait_for(
                connect(ws_url, max_size=MAX_MESSAGE, compression=None, ping_interval=None,
                        open_timeout=timeout, close_timeout=2, max_queue=None),
                timeout + 1)
        except (OSError, asyncio.TimeoutError, Exception) as e:  # websockets raises several types
            raise CDPClosed(f"cannot connect to {ws_url}: {e}") from e
        return cls(ws, default_timeout)

    @property
    def closed(self) -> bool:
        return self._closed is not None

    async def _read_loop(self) -> None:
        reason = ""
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid is not None:
                    entry = self._pending.pop(mid, None)
                    if entry and not entry[0].done():
                        fut, method = entry
                        if "error" in msg:
                            fut.set_exception(CDPError(method, msg["error"]))
                        else:
                            fut.set_result(msg.get("result", {}))
                    continue
                self._dispatch(msg)
        except Exception as e:  # ConnectionClosed and friends
            reason = str(e)
        finally:
            self._closed = CDPClosed(reason)
            for fut, _ in self._pending.values():
                if not fut.done():
                    fut.set_exception(CDPClosed(reason))
            self._pending.clear()
            self._dispatch({"method": "__closed__", "params": {"reason": reason}})

    def _dispatch(self, msg: dict[str, Any]) -> None:
        method = msg.get("method", "")
        sid = msg.get("sessionId")
        for key in ((method, sid), (method, None)) if sid else ((method, None),):
            for h in list(self._handlers.get(key, ())):
                try:
                    r = h(msg)
                    if asyncio.iscoroutine(r):
                        task = asyncio.ensure_future(r)
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
                except Exception:
                    pass  # handlers must not break the reader

    async def send(self, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = None,
                   timeout: float | None = None) -> dict[str, Any]:
        """Send a command and await its result. Raises CDPError / CDPTimeout / CDPClosed."""
        if self._closed:
            raise self._closed
        mid = next(self._ids)
        msg: dict[str, Any] = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[mid] = (fut, method)
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            self._pending.pop(mid, None)
            raise CDPClosed(str(e)) from e
        t = self.default_timeout if timeout is None else timeout
        try:
            return await asyncio.wait_for(fut, t)
        except asyncio.TimeoutError:
            self._pending.pop(mid, None)
            raise CDPTimeout(method, t) from None

    def on(self, method: str, handler: EventHandler, *, session_id: str | None = None) -> Callable[[], None]:
        """Register an event handler (sync or async). Returns an unsubscribe function."""
        key = (method, session_id)
        self._handlers.setdefault(key, []).append(handler)

        def off() -> None:
            lst = self._handlers.get(key, [])
            if handler in lst:
                lst.remove(handler)
        return off

    async def wait_for(self, method: str, *, session_id: str | None = None,
                       predicate: Callable[[dict[str, Any]], bool] | None = None,
                       timeout: float | None = None) -> dict[str, Any]:
        """Wait for the next matching event and return its ``params``."""
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        def h(msg: dict[str, Any]) -> None:
            if not fut.done() and (predicate is None or predicate(msg.get("params", {}))):
                fut.set_result(msg.get("params", {}))

        def closed(msg: dict[str, Any]) -> None:
            if not fut.done():
                fut.set_exception(CDPClosed(msg.get("params", {}).get("reason", "")))

        offs = [self.on(method, h, session_id=session_id), self.on("__closed__", closed)]
        t = self.default_timeout if timeout is None else timeout
        try:
            return await asyncio.wait_for(fut, t)
        except asyncio.TimeoutError:
            raise CDPTimeout(f"event {method}", t) from None
        finally:
            for off in offs:
                off()

    def session(self, session_id: str) -> "CDPSession":
        return CDPSession(self, session_id)

    async def close(self) -> None:
        """Close the websocket and stop the reader."""
        try:
            await self._ws.close()
        except Exception:
            pass
        self._reader.cancel()
        try:
            await self._reader
        except (asyncio.CancelledError, Exception):
            pass


class CDPSession:
    """A flattened target session on a :class:`CDPConnection`."""

    def __init__(self, conn: CDPConnection, session_id: str) -> None:
        self.conn = conn
        self.id = session_id

    def send(self, method: str, params: dict[str, Any] | None = None, *,
             timeout: float | None = None) -> Awaitable[dict[str, Any]]:
        return self.conn.send(method, params, session_id=self.id, timeout=timeout)

    def on(self, method: str, handler: EventHandler) -> Callable[[], None]:
        return self.conn.on(method, handler, session_id=self.id)

    def wait_for(self, method: str, *, predicate: Callable[[dict[str, Any]], bool] | None = None,
                 timeout: float | None = None) -> Awaitable[dict[str, Any]]:
        return self.conn.wait_for(method, session_id=self.id, predicate=predicate, timeout=timeout)
