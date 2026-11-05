"""GPU probe: render reference frames with the GPU and with ``--disable-gpu`` and compare.

The GPU path is used only when Chrome reports GPU compositing enabled, the GPU frames are not
blank, and they match the software reference within tolerance (anti-aliasing differs slightly
between rasterizers; a broken driver produces gross mismatches or black frames). Results can be
cached in a JSON file keyed by the browser binary (path, size, mtime) and probe size.
"""
from __future__ import annotations

import asyncio
import io
import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .cdp import CDPConnection
from .chromium import BrowserCandidate, launch
from .errors import RenderError
from .page import RenderPage
from .serve import PageServer
from .testpage import write_test_page

PROBE_SIZE = (960, 540)
PROBE_TIMES = (1.0, 2.5)
# Tolerances (0..255 scale). Measured GPU-vs-software on healthy GPUs: see research/wp-a-renderer.md.
MAX_MEAN_DIFF = 4.0          # mean absolute per-channel difference
MAX_BIG_DIFF_FRAC = 0.02     # fraction of pixels whose max channel diff exceeds BIG_DIFF
BIG_DIFF = 48
BLANK_STDDEV = 2.0
PROBE_VERSION = 1


@dataclass
class GPUProbe:
    """Outcome of :func:`probe_gpu`; ``use_gpu`` is the decision."""
    use_gpu: bool
    reason: str
    browser: str = ""
    version: str = ""
    gpu_status: dict[str, str] = field(default_factory=dict)
    gpu_device: str = ""
    mean_diff: float | None = None
    big_diff_frac: float | None = None
    seconds: float = 0.0
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Capture:
    pngs: list[bytes]
    status: dict[str, str]
    device: str
    version: str


async def _capture(cand: BrowserCandidate, *, gpu: bool, server: PageServer, rel: str, size: tuple[int, int],
                   profile_root: Path | None, timeout: float) -> _Capture:
    b = await asyncio.to_thread(launch, cand, gpu=gpu, window_size=size, profile_root=profile_root)
    try:
        conn = await CDPConnection.connect(b.ws_url, default_timeout=timeout)
        try:
            version = (await conn.send("Browser.getVersion"))["product"]
            info = (await conn.send("SystemInfo.getInfo"))["gpu"]
            status = {k: str(v) for k, v in info.get("featureStatus", {}).items()
                      if k in ("gpu_compositing", "rasterization", "webgl", "webgl2", "2d_canvas")}
            dev = info.get("devices", [{}])[0] if info.get("devices") else {}
            device = " ".join(str(dev.get(k, "")) for k in ("vendorString", "deviceString")).strip()
            page = await RenderPage.open(conn, w=size[0], h=size[1], allow_prefixes=(server.base_url,))
            await page.goto(server.url(rel), timeout=timeout)
            await page.wait_contract(timeout=timeout)
            pngs = []
            for t in PROBE_TIMES:
                await page.seek(t)
                pngs.append(await page.capture("png"))
            try:
                await conn.send("Browser.close", timeout=5)
            except RenderError:
                pass
            return _Capture(pngs, status, device, version)
        finally:
            await conn.close()
    finally:
        await asyncio.to_thread(b.kill, 2.0)


def compare_frames(a: bytes, b: bytes) -> tuple[float, float, bool]:
    """(mean abs diff, fraction of pixels with a channel diff > BIG_DIFF, a_is_blank) for two PNGs."""
    from PIL import Image, ImageChops, ImageStat

    ia = Image.open(io.BytesIO(a)).convert("RGB")
    ib = Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return 255.0, 1.0, False
    diff = ImageChops.difference(ia, ib)
    mean = sum(ImageStat.Stat(diff).mean) / 3.0
    r, g, b_ = diff.split()
    peak = ImageChops.lighter(ImageChops.lighter(r, g), b_)          # per-pixel max channel diff
    big = ImageStat.Stat(peak.point([255 if v > BIG_DIFF else 0 for v in range(256)])).mean[0] / 255.0
    blank = max(ImageStat.Stat(ia.convert("L")).stddev) < BLANK_STDDEV
    return mean, big, blank


async def probe_gpu_async(cand: BrowserCandidate, *, size: tuple[int, int] = PROBE_SIZE,
                          profile_root: Path | None = None, timeout: float = 60.0) -> GPUProbe:
    """Run the probe (two short browser launches). Never raises; failures mean ``use_gpu=False``."""
    st = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sr-probe-") as tmp:
        rel = write_test_page(Path(tmp), dur=4, fps=30, with_font=False)
        with PageServer(Path(tmp)) as server:
            def done(use: bool, reason: str, **kw: Any) -> GPUProbe:
                return GPUProbe(use, reason, browser=cand.path, seconds=round(time.monotonic() - st, 2), **kw)
            try:
                g = await _capture(cand, gpu=True, server=server, rel=rel, size=size, profile_root=profile_root,
                                   timeout=timeout)
            except RenderError as e:
                return done(False, f"GPU launch/render failed: {e.message}")
            meta = {"version": g.version, "gpu_status": g.status, "gpu_device": g.device}
            if g.status.get("gpu_compositing") != "enabled":
                return done(False, f"GPU compositing unavailable ({g.status.get('gpu_compositing', '?')})", **meta)
            try:
                s = await _capture(cand, gpu=False, server=server, rel=rel, size=size, profile_root=profile_root,
                                   timeout=timeout)
            except RenderError as e:
                # Software is the fallback; if even it fails the render will report it. Keep GPU.
                return done(True, f"software reference failed ({e.message}); GPU frames used unchecked", **meta)
            means, bigs = [], []
            for a, b in zip(g.pngs, s.pngs):
                mean, big, blank = compare_frames(a, b)
                if blank:
                    return done(False, "GPU frame is blank", **meta)
                means.append(mean)
                bigs.append(big)
            meta.update(mean_diff=round(max(means), 3), big_diff_frac=round(max(bigs), 5))
            if max(means) > MAX_MEAN_DIFF or max(bigs) > MAX_BIG_DIFF_FRAC:
                return done(False, "GPU frames differ from the software reference", **meta)
            return done(True, "GPU frames match the software reference", **meta)


def _cache_key(cand: BrowserCandidate, size: tuple[int, int]) -> str:
    try:
        st = Path(cand.path).stat()
        stamp = f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        stamp = "?"
    return f"v{PROBE_VERSION}|{cand.path}|{stamp}|{size[0]}x{size[1]}"


async def probe_gpu_cached_async(cand: BrowserCandidate, *, cache_path: Path | None = None,
                                 size: tuple[int, int] = PROBE_SIZE, profile_root: Path | None = None,
                                 refresh: bool = False) -> GPUProbe:
    """:func:`probe_gpu_async` with an optional JSON cache keyed by browser binary and probe size."""
    key = _cache_key(cand, size)
    cache: dict[str, Any] = {}
    if cache_path is not None and Path(cache_path).is_file():
        try:
            cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        if not refresh and isinstance(cache.get(key), dict):
            try:
                return GPUProbe(**{**cache[key], "cached": True})
            except TypeError:
                pass
    res = await probe_gpu_async(cand, size=size, profile_root=profile_root)
    if cache_path is not None:
        cache[key] = {**res.to_dict(), "cached": False}
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps(cache, indent=1), encoding="utf-8")
        except OSError:
            pass
    return res


def probe_gpu(cand: BrowserCandidate, **kw: Any) -> GPUProbe:
    """Synchronous :func:`probe_gpu_cached_async` (call it outside any running event loop)."""
    return asyncio.run(probe_gpu_cached_async(cand, **kw))
