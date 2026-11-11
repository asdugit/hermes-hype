"""Parallel, chunked, resumable frame capture: N Chromium workers -> ffmpeg chunk encodes -> concat.

Each worker owns one browser (one tab). Frames ``i`` in ``[0, N)`` are rendered at ``t = i / fps``:
``await __sr.seek(t)`` then ``Page.captureScreenshot`` (JPEG q92, exact clip), piped straight into
an ffmpeg process per ~5 s chunk (image2pipe -> post chain -> libx264 veryfast crf 18, yuv420p,
BT.709). Chunks are verified by encoded frame count, renamed atomically and described by a
sidecar JSON, so an interrupted render resumes by skipping finished chunks. A worker that times
out or crashes is restarted and its chunk redone; the final MP4 is a stream-copy concat.

Public entry points never raise: they return :class:`RenderResult` with ``error`` set.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .cdp import CDPConnection
from .chromium import NO_BROWSER_HINT, BrowserCandidate, LaunchedBrowser, browser_candidates, launch_any
from .errors import RenderError
from .ffmpeg import (
    NO_WINDOW,
    capabilities,
    chunk_encode_cmd,
    concat,
    count_frames,
    encoder_spec,
    parse_progress,
    pick_encoder,
    resolve_ffmpeg,
)
from .page import PageInfo, RenderPage
from .post import REQUIRED_FILTERS, build_post, chain_seed, parse_spec
from .probe import GPUProbe, probe_gpu_cached_async
from .serve import PageServer

GiB = 1024 ** 3
WORKER_RAM = 0.7 * GiB
RAM_HEADROOM = 1.0 * GiB
MAX_CHUNK_ATTEMPTS = 3
WARMUP_TIMEOUT_S = 8.0
NON_RETRYABLE = frozenset({"page_contract", "post", "no_encoder", "no_ffmpeg", "no_browser", "bad_env_browser"})
BROWSER_FAULTS = frozenset({"cdp", "cdp_timeout", "cdp_closed", "page_load", "browser_launch"})

ProgressCB = Callable[[int, int, "float | None"], None]


# ------------------------------------------------------------------------------ specs

@dataclass
class RenderSpec:
    """What to render. Sizes are device pixels; ``out_size`` defaults to ``(w, h)``.

    ``page`` is the entry page relative to ``page_dir`` (may carry a ``?query``). ``duration_s``
    None means "ask the page" (``__sr.dur``). ``gpu``: ``"auto"`` (probe), ``"on"`` or ``"off"``.
    """
    page_dir: Path
    out_path: Path
    w: int = 1920
    h: int = 1080
    fps: float = 30.0
    page: str = "index.html"
    duration_s: float | None = None
    out_size: tuple[int, int] | None = None
    dpr: float = 1.0
    post: str = "none"
    post_params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    seed: int = 0
    chunk_s: float = 5.0
    workers: int | None = None
    gpu: str = "auto"
    capture_format: str = "jpeg"            # "png" for a lossless master
    jpeg_quality: int = 92
    encoder: str | None = None
    crf: int = 18
    preset: str = "veryfast"
    work_dir: Path | None = None            # chunk dir; default <out_dir>/<stem>.chunks
    keep_chunks: bool = False
    fingerprint: str | None = None          # resume key; default = content hash of page_dir
    timeout_s: float = 60.0                 # CDP calls, page load, __sr.ready
    frame_timeout_s: float = 20.0           # one seek or one capture; a hang costs at most this
    browser: BrowserCandidate | None = None
    ffmpeg: str | None = None
    profile_root: Path | None = None
    gpu_cache: Path | None = None           # JSON cache for the GPU probe


@dataclass
class RenderResult:
    """Outcome of :func:`render_video` (JSON-able via :meth:`to_dict`)."""
    ok: bool = False
    out_path: str | None = None
    frames: int = 0
    fps: float = 0.0
    duration_s: float = 0.0
    size: tuple[int, int] = (0, 0)
    wall_s: float = 0.0
    capture_s: float = 0.0
    render_fps: float = 0.0                 # frames captured this run / capture wall time
    workers: int = 0
    gpu: bool = False
    gpu_reason: str = ""
    browser: str = ""
    browser_version: str = ""
    encoder: str = ""
    post: str = "none"
    chunks_total: int = 0
    chunks_rendered: int = 0
    chunks_skipped: int = 0
    restarts: int = 0
    warnings: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    blocked_urls: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Chunk:
    index: int
    f0: int
    f1: int

    @property
    def frames(self) -> int:
        return self.f1 - self.f0


def frames_for(duration_s: float, fps: float) -> int:
    """Frame count for a duration (rounded to the nearest frame, at least 1)."""
    return max(1, int(round(duration_s * fps + 1e-9)))


def plan_chunks(total_frames: int, fps: float, chunk_s: float = 5.0) -> list[Chunk]:
    """Split ``[0, total)`` into chunks of ~``chunk_s`` seconds (last chunk may be shorter)."""
    size = max(1, int(round(chunk_s * fps)))
    return [Chunk(i, f0, min(total_frames, f0 + size)) for i, f0 in enumerate(range(0, total_frames, size))]


def auto_workers(gpu: bool, available_bytes: int | None = None) -> int:
    """min(3 if GPU else 2, floor((free RAM - 1 GiB) / 0.7 GiB)), at least 1."""
    if available_bytes is None:
        import psutil
        available_bytes = int(psutil.virtual_memory().available)
    by_ram = int((available_bytes - RAM_HEADROOM) // WORKER_RAM)
    return max(1, min(3 if gpu else 2, by_ram))


def dir_fingerprint(root: Path, exclude: Sequence[Path] = ()) -> str:
    """sha256 over relative paths + contents of every file under ``root`` (minus ``exclude`` trees)."""
    root = Path(root).resolve()
    excl = [Path(e).resolve() for e in exclude]
    h = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for p in files:
        rp = p.resolve()
        if any(rp == e or e in rp.parents for e in excl):
            continue
        h.update(p.relative_to(root).as_posix().encode("utf-8") + b"\0")
        with open(p, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        h.update(b"\0")
    return h.hexdigest()[:24]


# ------------------------------------------------------------------------ the context

class _Cancelled(Exception):
    pass


class _Ctx:
    """Shared state for one render (all access happens on the event loop thread)."""

    def __init__(self, spec: RenderSpec, res: RenderResult, cancel: threading.Event) -> None:
        self.spec = spec
        self.res = res
        self.cancel = cancel
        self.candidates: list[BrowserCandidate] = []
        self.gpu = False
        self.url = ""
        self.allow: tuple[str, ...] = ()
        self.ffmpeg = ""
        self.enc = encoder_spec("libx264", spec.w, spec.h, spec.fps)
        self.out_size = spec.out_size or (spec.w, spec.h)
        self.chunks_dir = Path()
        self.key = ""
        self.post = "none"
        self.queue: deque[Chunk] = deque()
        self.attempts: dict[int, int] = {}
        self.failure: RenderError | None = None
        self.frames_done = 0
        self.frames_this_run = 0
        self.capture_t0: float | None = None
        self.capture_t1: float | None = None
        self.live_workers = 0

    def warn(self, msg: str) -> None:
        if len(self.res.warnings) < 100:
            self.res.warnings.append(msg)

    def fail(self, err: RenderError) -> None:
        if self.failure is None:
            self.failure = err

    def chunk_path(self, c: Chunk) -> Path:
        return self.chunks_dir / f"chunk_{c.index:04d}.{self.enc.container}"

    def chunk_key(self, c: Chunk) -> str:
        return hashlib.sha256(f"{self.key}|{c.f0}|{c.f1}".encode()).hexdigest()[:24]


# ------------------------------------------------------------------------- the worker

class _Worker:
    def __init__(self, idx: int, ctx: _Ctx) -> None:
        self.idx = idx
        self.ctx = ctx
        self.gpu = ctx.gpu
        self.browser: LaunchedBrowser | None = None
        self.conn: CDPConnection | None = None
        self.page: RenderPage | None = None
        self.info: PageInfo | None = None
        self.failures = 0

    async def start(self) -> None:
        ctx, spec = self.ctx, self.ctx.spec
        css = (round(spec.w / spec.dpr), round(spec.h / spec.dpr))
        self.browser = await asyncio.to_thread(launch_any, ctx.candidates, gpu=self.gpu, window_size=css,
                                               profile_root=spec.profile_root)
        if len(ctx.candidates) > 1:  # every worker must use the same browser build
            ctx.candidates = [self.browser.candidate]
        self.conn = await CDPConnection.connect(self.browser.ws_url, default_timeout=spec.timeout_s)
        if not ctx.res.browser_version:
            ctx.res.browser_version = (await self.conn.send("Browser.getVersion")).get("product", "")
            ctx.res.browser = self.browser.candidate.path
        self.page = await RenderPage.open(self.conn, w=spec.w, h=spec.h, dpr=spec.dpr, allow_prefixes=ctx.allow)
        await self.page.goto(ctx.url, timeout=spec.timeout_s)
        self.info = await self.page.wait_contract(timeout=spec.timeout_s)
        # Warm-up frame with a short timeout: on this PC Chromium 145 in software mode occasionally
        # never answers one of the first captureScreenshot calls after load (not reproducible on
        # demand; see research/wp-a-renderer.md). Failing fast here restarts the browser cheaply.
        await self.page.seek(0.0, timeout=spec.frame_timeout_s)
        await self.page.capture(spec.capture_format, spec.jpeg_quality, timeout=WARMUP_TIMEOUT_S)
        self.browser.remember_children()

    async def stop(self, graceful: bool = True) -> None:
        if self.page is not None:
            res = self.ctx.res
            for e in self.page.errors:
                if e not in res.page_errors and len(res.page_errors) < 20:
                    res.page_errors.append(e)
            for u in self.page.blocked:
                if u not in res.blocked_urls and len(res.blocked_urls) < 20:
                    res.blocked_urls.append(u)
        if self.conn is not None:
            if graceful and not self.conn.closed:
                with contextlib.suppress(RenderError):
                    await self.conn.send("Browser.close", timeout=5)
            await self.conn.close()
        if self.browser is not None:
            await asyncio.to_thread(self.browser.kill, 3.0 if graceful else 0.0)
        self.browser = self.conn = self.page = None

    async def run(self) -> None:
        ctx = self.ctx
        try:
            while ctx.queue and ctx.failure is None and not ctx.cancel.is_set():
                chunk = ctx.queue.popleft()
                try:
                    if self.page is None:
                        await self.start()
                    await self._encode_chunk(chunk)
                    ctx.res.chunks_rendered += 1
                    self.failures = 0
                except _Cancelled:
                    return
                except RenderError as e:
                    n = ctx.attempts[chunk.index] = ctx.attempts.get(chunk.index, 0) + 1
                    ctx.warn(f"worker {self.idx}: chunk {chunk.index} attempt {n} failed: [{e.code}] {e.message}")
                    if e.code in BROWSER_FAULTS:  # an ffmpeg failure leaves the browser usable
                        self.failures += 1
                        await self.stop(graceful=False)
                    if e.code in NON_RETRYABLE or n >= MAX_CHUNK_ATTEMPTS:
                        ctx.fail(RenderError("chunk_failed", f"chunk {chunk.index} failed: {e.message}",
                                             hint=e.hint, cause=e.to_dict()))
                        return
                    ctx.res.restarts += 1
                    ctx.queue.appendleft(chunk)
                    if self.gpu and self.failures >= 2:
                        self.gpu = False
                        ctx.warn(f"worker {self.idx}: switching to software rendering after repeated failures")
                    if self.failures >= MAX_CHUNK_ATTEMPTS and ctx.live_workers > 1:
                        ctx.warn(f"worker {self.idx}: giving up; other workers continue")
                        return
        finally:
            ctx.live_workers -= 1
            await self.stop(graceful=True)

    async def _encode_chunk(self, chunk: Chunk) -> None:
        ctx, spec = self.ctx, self.ctx.spec
        assert self.page is not None
        final = ctx.chunk_path(chunk)
        part = final.with_name(final.stem + ".part" + final.suffix)
        post = build_post(ctx.post, in_size=(spec.w, spec.h), out_size=ctx.out_size,
                          seed=chain_seed(spec.seed, chunk.index), params=spec.post_params, work_dir=ctx.chunks_dir,
                          image_codec="mjpeg" if spec.capture_format == "jpeg" else "png")
        cmd = chunk_encode_cmd(ctx.ffmpeg, fps=spec.fps, out_path=part, enc=ctx.enc, filter_graph=post.graph,
                               extra_inputs=post.extra_inputs,
                               image_codec="mjpeg" if spec.capture_format == "jpeg" else "png")
        proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                    creationflags=NO_WINDOW)
        assert proc.stdin and proc.stdout and proc.stderr
        out_task = asyncio.ensure_future(proc.stdout.read())
        err_task = asyncio.ensure_future(proc.stderr.read())
        written = 0
        drain: asyncio.Future[None] | None = None
        try:
            for i in range(chunk.f0, chunk.f1):
                if ctx.cancel.is_set():
                    raise _Cancelled()
                await self.page.seek(i / spec.fps, timeout=spec.frame_timeout_s)
                data = await self.page.capture(spec.capture_format, spec.jpeg_quality, timeout=spec.frame_timeout_s)
                if ctx.capture_t0 is None:
                    ctx.capture_t0 = time.monotonic()
                if drain is not None:
                    await drain
                proc.stdin.write(data)
                drain = asyncio.ensure_future(proc.stdin.drain())  # overlaps the next seek/capture
                written += 1
                ctx.frames_done += 1
                ctx.frames_this_run += 1
            if drain is not None:
                await drain
            proc.stdin.close()
            rc = await asyncio.wait_for(proc.wait(), timeout=300)
            out = (await out_task).decode("utf-8", "replace")
            err = (await err_task).decode("utf-8", "replace")
            if rc != 0:
                raise RenderError("ffmpeg", f"chunk {chunk.index} encode failed (exit {rc})", stderr=err[-1500:])
            got = parse_progress(out).get("frame", "")
            if not got.isdigit() or int(got) != chunk.frames:
                raise RenderError("ffmpeg", f"chunk {chunk.index}: encoded {got or '?'} of {chunk.frames} frames",
                                  stderr=err[-800:])
            os.replace(part, final)
            final.with_suffix(".json").write_text(json.dumps({"key": ctx.chunk_key(chunk), "frames": chunk.frames}),
                                                  encoding="utf-8")
            ctx.capture_t1 = time.monotonic()
        except (ConnectionError, BrokenPipeError) as e:
            ctx.frames_done -= written
            ctx.frames_this_run -= written
            err = await _finish(proc, err_task)
            raise RenderError("ffmpeg", f"ffmpeg stopped reading frames: {e}", stderr=err[-1500:]) from e
        except BaseException:
            ctx.frames_done -= written
            ctx.frames_this_run -= written
            await _finish(proc, err_task)
            raise
        finally:
            for t in (drain, out_task, err_task):
                if t is not None and not t.done():
                    t.cancel()
            part.unlink(missing_ok=True)


async def _finish(proc: asyncio.subprocess.Process, err_task: asyncio.Future[bytes]) -> str:
    """Kill an ffmpeg we started (if still running) and return its stderr tail."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 10)
    with contextlib.suppress(Exception):
        return (await asyncio.wait_for(err_task, 5)).decode("utf-8", "replace")
    return ""


# --------------------------------------------------------------------------- the render

async def _decide_gpu(spec: RenderSpec, cand: BrowserCandidate) -> tuple[bool, str]:
    mode = (spec.gpu or "auto").lower()
    if mode in ("on", "gpu", "true"):
        return True, "forced on"
    if mode in ("off", "software", "false"):
        return False, "forced off"
    probe: GPUProbe = await probe_gpu_cached_async(cand, cache_path=spec.gpu_cache, profile_root=spec.profile_root)
    return probe.use_gpu, probe.reason + (" (cached)" if probe.cached else "")


async def _reporter(ctx: _Ctx, total: int, progress: ProgressCB | None, stop: asyncio.Event) -> None:
    if progress is None:
        return
    while True:
        eta: float | None = None
        if ctx.capture_t0 is not None and ctx.frames_this_run > 0:
            rate = ctx.frames_this_run / max(1e-3, time.monotonic() - ctx.capture_t0)
            eta = max(0.0, (total - ctx.frames_done) / rate)
        with contextlib.suppress(Exception):
            progress(max(0, ctx.frames_done), total, eta)
        try:
            await asyncio.wait_for(stop.wait(), 0.5)
            return
        except TimeoutError:
            pass


def _chunk_done(ctx: _Ctx, c: Chunk) -> bool:
    p = ctx.chunk_path(c)
    side = p.with_suffix(".json")
    if not (p.is_file() and side.is_file()):
        return False
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
        if meta.get("key") != ctx.chunk_key(c):
            return False
        return count_frames(ctx.ffmpeg, p, decode=True) == c.frames
    except (OSError, ValueError, RenderError):
        return False


async def render_video_async(spec: RenderSpec, *, progress: ProgressCB | None = None,
                             cancel: threading.Event | None = None) -> RenderResult:
    """Async :func:`render_video`. Never raises (``asyncio.CancelledError`` excepted)."""
    t_start = time.monotonic()
    res = RenderResult(fps=spec.fps, size=spec.out_size or (spec.w, spec.h), post=spec.post or "none")
    ctx = _Ctx(spec, res, cancel or threading.Event())
    server: PageServer | None = None
    workers: list[_Worker] = []
    try:
        # --- tools
        ctx.ffmpeg = spec.ffmpeg or resolve_ffmpeg().path
        caps = capabilities(ctx.ffmpeg)
        enc_name = pick_encoder(caps, spec.encoder)
        if spec.encoder and enc_name != spec.encoder:
            ctx.warn(f"encoder {spec.encoder} unavailable; using {enc_name}")
        threads = max(2, min(8, (os.cpu_count() or 4) // 2))
        ctx.enc = encoder_spec(enc_name, *ctx.out_size, spec.fps, crf=spec.crf, preset=spec.preset, threads=threads)
        res.encoder = enc_name
        ctx.post = spec.post or "none"
        try:
            need = {f for n in ["none", *parse_spec(ctx.post)] for f in REQUIRED_FILTERS[n]}
            missing = sorted(f for f in need if f not in caps.filters)
        except RenderError as e:
            missing = [e.message]
        if missing:
            ctx.warn(f"post chain {ctx.post!r} unusable ({', '.join(missing)}); rendering without post")
            ctx.post = res.post = "none"
        out_path = Path(spec.out_path)
        if ctx.enc.container == "webm" and out_path.suffix.lower() != ".webm":
            out_path = out_path.with_suffix(".webm")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.chunks_dir = Path(spec.work_dir) if spec.work_dir else out_path.with_name(out_path.stem + ".chunks")
        ctx.chunks_dir.mkdir(parents=True, exist_ok=True)

        cands = [spec.browser] if spec.browser else browser_candidates()
        if not cands:
            raise RenderError("no_browser", "no Chromium-based browser found", hint=NO_BROWSER_HINT)
        ctx.candidates = list(cands)
        ctx.gpu, res.gpu_reason = await _decide_gpu(spec, cands[0])
        res.gpu = ctx.gpu

        server = PageServer(Path(spec.page_dir)).start()
        ctx.url, ctx.allow = server.url(spec.page), (server.base_url,)

        # --- plan (ask the page for its duration if not given)
        first: _Worker | None = None
        duration = spec.duration_s
        if duration is None:
            first = _Worker(0, ctx)
            ctx.live_workers += 1
            for attempt in range(1, MAX_CHUNK_ATTEMPTS + 1):
                try:
                    await first.start()
                    break
                except RenderError as e:
                    await first.stop(graceful=False)
                    if e.code not in BROWSER_FAULTS or attempt == MAX_CHUNK_ATTEMPTS:
                        raise
                    ctx.warn(f"worker 0: start attempt {attempt} failed: [{e.code}] {e.message}")
                    res.restarts += 1
            assert first.info is not None
            duration = first.info.dur
        total = frames_for(duration, spec.fps)
        res.frames, res.duration_s = total, total / spec.fps
        ours = [ctx.chunks_dir, out_path, out_path.with_name(out_path.stem + ".part" + out_path.suffix),
                out_path.with_name(out_path.name + ".concat.txt")]
        fp = spec.fingerprint or await asyncio.to_thread(dir_fingerprint, Path(spec.page_dir), ours)
        ctx.key = hashlib.sha256(json.dumps(
            [fp, spec.page, spec.w, spec.h, list(ctx.out_size), spec.fps, spec.dpr, ctx.post,
             json.loads(json.dumps(spec.post_params, default=str)), spec.seed, enc_name, spec.crf, spec.preset,
             spec.capture_format, spec.jpeg_quality], sort_keys=True).encode()).hexdigest()
        chunks = plan_chunks(total, spec.fps, spec.chunk_s)
        res.chunks_total = len(chunks)
        done = [c for c in chunks if await asyncio.to_thread(_chunk_done, ctx, c)]
        res.chunks_skipped = len(done)
        ctx.frames_done = sum(c.frames for c in done)
        ctx.queue = deque(c for c in chunks if c not in done)

        # --- capture
        if ctx.queue:
            n = spec.workers or auto_workers(ctx.gpu)
            n = max(1, min(n, len(ctx.queue)))
            res.workers = n
            workers = [first] if first else []
            for i in range(len(workers), n):
                workers.append(_Worker(i, ctx))
                ctx.live_workers += 1
            stop_rep = asyncio.Event()
            rep = asyncio.ensure_future(_reporter(ctx, total, progress, stop_rep))
            try:
                await asyncio.gather(*(w.run() for w in workers))
            finally:
                stop_rep.set()
                await rep
        elif first is not None:
            ctx.live_workers -= 1
            await first.stop()
        if ctx.cancel.is_set():
            raise RenderError("cancelled", "render cancelled")
        if ctx.failure is not None:
            raise ctx.failure
        if ctx.queue:
            raise RenderError("chunk_failed", "workers stopped before all chunks were rendered")
        if ctx.capture_t0 is not None and ctx.frames_this_run:
            res.capture_s = round((ctx.capture_t1 or time.monotonic()) - ctx.capture_t0, 2)
            res.render_fps = round(ctx.frames_this_run / max(1e-3, res.capture_s), 2)

        # --- concat + verify
        parts = [ctx.chunk_path(c) for c in chunks]
        await asyncio.to_thread(concat, ctx.ffmpeg, parts, out_path, container=ctx.enc.container)
        n_out = await asyncio.to_thread(count_frames, ctx.ffmpeg, out_path, decode=False)
        if n_out != total:
            raise RenderError("ffmpeg", f"final video has {n_out} frames, expected {total}")
        res.out_path = str(out_path)
        res.ok = True
        if progress is not None:
            with contextlib.suppress(Exception):
                progress(total, total, 0.0)
        if not spec.keep_chunks and spec.work_dir is None:
            shutil.rmtree(ctx.chunks_dir, ignore_errors=True)
    except RenderError as e:
        res.error = e.to_dict()
    except Exception as e:  # never raise out of the public entry point
        res.error = {"code": "internal", "message": f"{type(e).__name__}: {e}"}
    finally:
        for w in workers:
            if w.browser is not None:
                with contextlib.suppress(Exception):
                    await w.stop(graceful=False)
        if server is not None:
            server.stop()
        res.wall_s = round(time.monotonic() - t_start, 2)
    return res


def _run_sync(coro_fn: Callable[[], Awaitable[Any]]) -> Any:
    """Run a coroutine to completion from sync code, even if this thread already runs a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn())  # type: ignore[arg-type]
    box: list[Any] = []
    t = threading.Thread(target=lambda: box.append(asyncio.run(coro_fn())), name="auteur-render")  # type: ignore[arg-type]
    t.start()
    t.join()
    return box[0]


def render_video(spec: RenderSpec, *, progress: ProgressCB | None = None,
                 cancel: threading.Event | None = None) -> RenderResult:
    """Render ``spec`` to a video file. Blocking; never raises; see :class:`RenderResult`.

    ``progress(frames_done, total, eta_s)`` is called ~2x per second from the render thread.
    Setting ``cancel`` stops within one frame and returns ``error.code == "cancelled"``.
    """
    return _run_sync(lambda: render_video_async(spec, progress=progress, cancel=cancel))


# ------------------------------------------------------------------- single-page helper

@contextlib.asynccontextmanager
async def page_session(page_dir: Path, page: str, *, w: int, h: int, dpr: float = 1.0, gpu: bool = False,
                       browser: BrowserCandidate | None = None, profile_root: Path | None = None,
                       timeout_s: float = 60.0) -> AsyncIterator[RenderPage]:
    """Serve ``page_dir``, launch one browser, load ``page`` and yield a ready :class:`RenderPage`.

    For stills, thumbnails and layout QA (``await page.seek(t); await page.evaluate("__sr.qa(t)")``).
    Raises :class:`RenderError`.
    """
    cands = [browser] if browser else browser_candidates()
    if not cands:
        raise RenderError("no_browser", "no Chromium-based browser found", hint=NO_BROWSER_HINT)
    css = (round(w / dpr), round(h / dpr))
    with PageServer(Path(page_dir)) as server:
        b = await asyncio.to_thread(launch_any, cands, gpu=gpu, window_size=css, profile_root=profile_root)
        conn: CDPConnection | None = None
        try:
            conn = await CDPConnection.connect(b.ws_url, default_timeout=timeout_s)
            p = await RenderPage.open(conn, w=w, h=h, dpr=dpr, allow_prefixes=(server.base_url,))
            await p.goto(server.url(page), timeout=timeout_s)
            await p.wait_contract(timeout=timeout_s)
            yield p
            with contextlib.suppress(RenderError):
                await conn.send("Browser.close", timeout=5)
        finally:
            if conn is not None:
                await conn.close()
            await asyncio.to_thread(b.kill, 2.0)


@dataclass
class StillsResult:
    ok: bool
    images: list[bytes] = field(default_factory=list)
    error: dict[str, Any] | None = None


def capture_stills(page_dir: Path, page: str, times: Sequence[float], *, w: int, h: int, fmt: str = "png",
                   gpu: bool = False, browser: BrowserCandidate | None = None) -> StillsResult:
    """Capture one image per time in ``times`` (thumbnails, contact sheets). Never raises."""
    async def go() -> StillsResult:
        try:
            async with page_session(page_dir, page, w=w, h=h, gpu=gpu, browser=browser) as p:
                out = []
                for t in times:
                    await p.seek(t)
                    out.append(await p.capture(fmt))
                return StillsResult(True, out)
        except RenderError as e:
            return StillsResult(False, error=e.to_dict())
        except Exception as e:
            return StillsResult(False, error={"code": "internal", "message": f"{type(e).__name__}: {e}"})
    return _run_sync(go)
