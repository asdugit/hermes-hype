"""Product capture stage entry point: Product + session events -> ``product_capture`` events.

``capture_product`` plans targets (:mod:`.targets`), photographs web targets and PDFs with one
headless Chromium (:mod:`.web`), turns image/video artifacts into assets (:mod:`.media`), and
returns one ``product_capture`` Event per saved capture. It never raises, never starts servers or
runs commands, and is time-boxed by ``budget_s`` (partial results are kept). A JSON report with
targets, skipped candidates (with reasons), timings, blocked requests and the network-policy
disclosure is written to ``<out_dir>/capture.json``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ..contracts import Event, Product
from ..render.errors import RenderError
from .media import MediaAsset, image_asset, pdf_info, video_asset
from .policy import POLICY_DISCLOSURE
from .targets import CaptureTarget, TargetPlan, plan_targets
from .web import FeatureQuery, Shot, WebPlan, WebResult, capture_web_targets, slug

ProgressCB = Callable[[int, int, str], None]

SHOT_WEIGHTS = {"viewport": 0.95, "full": 0.8, "element": 0.78, "mobile": 0.75, "mobile_full": 0.6,
                "interaction": 0.6, "pdf_page": 0.7}
MEDIA_WEIGHTS = {"video": 0.9, "image": 0.85}
QUALITY_FACTOR = {"ok": 1.0, "blank": 0.2, "error_overlay": 0.2}
TOOL = "showreel_capture"


@dataclass
class CaptureReport:
    """Everything the stage did (JSON-able via :meth:`to_dict`)."""
    ok: bool = False
    events: list[Event] = field(default_factory=list)
    plan: TargetPlan = field(default_factory=TargetPlan)
    web: list[WebResult] = field(default_factory=list)
    media: list[tuple[CaptureTarget, MediaAsset]] = field(default_factory=list)
    allow_network: bool = False
    budget_s: float = 0.0
    wall_s: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    browser: str = ""
    network_policy: str = POLICY_DISCLOSURE
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    report_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "allow_network": self.allow_network, "budget_s": self.budget_s, "wall_s": self.wall_s,
                "timed_out": self.timed_out, "cancelled": self.cancelled, "browser": self.browser,
                "network_policy": self.network_policy, "warnings": self.warnings, "error": self.error,
                "plan": self.plan.to_dict(), "web": [w.to_dict() for w in self.web],
                "media": [{"target": t.to_dict(), "asset": a.to_dict()} for t, a in self.media],
                "events": [e.to_dict() for e in self.events]}


def _run_async(fn: Callable[[], Awaitable[Any]]) -> Any:
    """Run a coroutine from sync code, even when this thread already runs an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fn())  # type: ignore[arg-type]
    box: list[Any] = []
    err: list[BaseException] = []

    def runner() -> None:
        try:
            box.append(asyncio.run(fn()))  # type: ignore[arg-type]
        except BaseException as e:
            err.append(e)
    t = threading.Thread(target=runner, name="showreel-capture")
    t.start()
    t.join()
    if err:
        raise err[0]
    return box[0] if box else None


def _coerce_product(product: Any) -> Product:
    if isinstance(product, Product):
        return product
    if isinstance(product, dict):
        names = {f.name for f in fields(Product)}
        return Product(**{k: v for k, v in product.items() if k in names})
    return Product()


def _coerce_events(events: Any) -> list[Event]:
    out = []
    names = {f.name for f in fields(Event)}
    for e in events or []:
        if isinstance(e, Event):
            out.append(e)
        elif isinstance(e, dict):
            with contextlib.suppress(TypeError):
                out.append(Event(**{k: v for k, v in e.items() if k in names}))
    return out


def _next_id(events: Sequence[Event]) -> int:
    n = -1
    for e in events:
        m = re.fullmatch(r"e(\d+)", str(e.id))
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


def capture_product(product: Product | dict[str, Any] | None, events: Sequence[Event], out_dir: str | Path, *,
                    allow_network: bool = False, budget_s: float = 60.0, progress: ProgressCB | None = None,
                    cancel: threading.Event | None = None, **kw: Any) -> list[Event]:
    """Capture the product; return ``product_capture`` events (empty if nothing was capturable).

    Never raises. See :func:`capture_product_report` for the keyword options and the full report.
    """
    return capture_product_report(product, events, out_dir, allow_network=allow_network, budget_s=budget_s,
                                  progress=progress, cancel=cancel, **kw).events


def capture_product_report(product: Product | dict[str, Any] | None, events: Sequence[Event], out_dir: str | Path,
                           *, allow_network: bool = False, budget_s: float = 60.0,
                           progress: ProgressCB | None = None, cancel: threading.Event | None = None,
                           features: Sequence[Any] | None = None, interactions: list[dict[str, Any]] | None = None,
                           web_plan: WebPlan | None = None, extra_urls: Sequence[str] = (), cutout: bool = True,
                           browser: Any = None, ffmpeg: str | None = None, probe_timeout_s: float = 1.5,
                           write_report: bool = True) -> CaptureReport:
    """Run the capture stage and return a :class:`CaptureReport` (``.events`` = product_capture events).

    ``features``: CSS selectors / text queries / dicts for element crops (default: the product's
    feature names). ``interactions``: explicit steps (``{"scroll": 0.5}``, ``{"hover": q}``,
    ``{"click": q}``, ``{"type": text, "into": q}``, ``{"wait": ms}``; default: CTA hover + scroll
    stills). ``allow_network``: public https URLs seen in the session may be captured and pages may
    load public CDN assets (GET only). ``extra_urls``: e.g. an agent-supplied product URL.
    """
    t0 = time.monotonic()
    deadline = t0 + max(1.0, float(budget_s))
    rep = CaptureReport(allow_network=allow_network, budget_s=float(budget_s))
    out = Path(out_dir)

    def tick(done: int, total: int, label: str) -> None:
        if progress is not None:
            with contextlib.suppress(Exception):
                progress(done, total, label)

    try:
        out.mkdir(parents=True, exist_ok=True)
        prod = _coerce_product(product)
        evs = _coerce_events(events)
        tick(0, 1, "finding capture targets")
        rep.plan = plan_targets(prod, evs, allow_network=allow_network, extra_urls=extra_urls,
                                probe_timeout_s=min(probe_timeout_s, max(0.3, budget_s / 10)))
        web_targets = rep.plan.of("url", "html", "pdf")
        media_targets = rep.plan.of("image", "video")
        total = len(web_targets) + len(media_targets)
        plan = web_plan or WebPlan(allow_third_party=allow_network)
        if web_plan is None or features is not None:
            raw = list(features) if features is not None else list(prod.features)
            plan.features = [q for q in (FeatureQuery.coerce(x) for x in raw) if q is not None]
        if interactions is not None:
            plan.interactions = interactions
        phases: list[str] = ["web", "media"] if prod.kind != "media" else ["media", "web"]
        phases = [p for p in phases if (web_targets if p == "web" else media_targets)]
        done = 0
        for i, phase in enumerate(phases):
            if cancel is not None and cancel.is_set():
                rep.cancelled = True
                break
            left = deadline - time.monotonic()
            if left <= 0.5:
                rep.timed_out = True
                rep.warnings.append(f"{phase}: skipped (time budget)")
                continue
            phase_deadline = deadline if i == len(phases) - 1 else time.monotonic() + left * 0.65
            if phase == "web":
                _web_phase(rep, web_targets, out / "web", plan, phase_deadline, cancel, browser,
                           lambda d, label, d0=done: tick(d0 + d, total, label))
                done += len(web_targets)
            else:
                _media_phase(rep, media_targets, out / "media", phase_deadline, cancel, cutout, ffmpeg,
                             lambda d, label, d0=done: tick(d0 + d, total, label))
                done += len(media_targets)
        rep.events = _events(rep, evs)
        rep.ok = bool(rep.events)
        rep.timed_out = rep.timed_out or any(w.timed_out for w in rep.web)
        rep.cancelled = rep.cancelled or bool(cancel is not None and cancel.is_set())
        tick(total, total, f"captured {len(rep.events)} image(s)")
    except Exception as e:
        rep.error = {"code": "internal", "message": f"{type(e).__name__}: {e}"[:400]}
    rep.wall_s = round(time.monotonic() - t0, 2)
    if write_report:
        with contextlib.suppress(OSError, TypeError, ValueError):
            p = out / "capture.json"
            p.write_text(json.dumps(rep.to_dict(), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            rep.report_path = str(p)
    return rep


def _web_phase(rep: CaptureReport, targets: list[CaptureTarget], out: Path, plan: WebPlan, deadline: float,
               cancel: threading.Event | None, browser: Any, tick: Callable[[int, str], None]) -> None:
    hosts = sorted({t.host for t in targets if t.kind == "url" and t.host})
    public = any(t.host_class == "public" for t in targets)
    ignore_cert = not public and any(t.url.startswith("https:") for t in targets)
    results: list[WebResult] = []
    rep.web = results

    async def go() -> None:
        task = asyncio.ensure_future(capture_web_targets(
            targets, out, plan, deadline=deadline, cancel=cancel, results=results,
            progress=lambda d, n, label: tick(d, label), allowed_hosts=hosts, open_dns=plan.allow_third_party,
            ignore_cert_errors=ignore_cert, browser=browser))
        hard = deadline + 8.0           # grace for closing pages and killing the browser
        while not task.done():
            if (cancel is not None and cancel.is_set()) or time.monotonic() > hard:
                task.cancel()
                break
            await asyncio.wait({task}, timeout=0.2)
        try:
            await task
        except asyncio.CancelledError:
            rep.timed_out = rep.timed_out or not (cancel is not None and cancel.is_set())
            for r in results:
                r.timed_out = True

    try:
        _run_async(go)
    except RenderError as e:
        hint = f" ({e.hint})" if e.hint else ""
        rep.warnings.append(f"web capture unavailable: {e.code}: {e.message}"[:300] + hint)
    for r in results:
        rep.browser = rep.browser or str(r.meta.get("browser") or "")
        if r.target.kind == "pdf":
            info = pdf_info(Path(r.target.path))
            r.meta.update(pages=info.pages, title=info.title or r.target.title)


def _media_phase(rep: CaptureReport, targets: list[CaptureTarget], out: Path, deadline: float,
                 cancel: threading.Event | None, cutout: bool, ffmpeg: str | None,
                 tick: Callable[[int, str], None]) -> None:
    for i, t in enumerate(targets):
        if cancel is not None and cancel.is_set():
            rep.cancelled = True
            break
        if time.monotonic() > deadline - 0.3:
            rep.timed_out = True
            rep.warnings.append(f"{t.kind} {Path(t.path).name}: skipped (time budget)")
            continue
        tick(i, f"preparing {Path(t.path).name}")
        sub = out / f"{t.kind}_{i + 1:02d}_{slug(Path(t.path).stem, 24)}"
        if t.kind == "image":
            a = image_asset(Path(t.path), sub, do_cutout=cutout)
        else:
            a = video_asset(Path(t.path), sub, ffmpeg=ffmpeg, do_cutout=cutout, deadline=deadline, cancel=cancel)
            if a.cutout and a.cutout.get("partial"):
                rep.warnings.append(f"video {Path(t.path).name}: cutout frames cover {a.cutout.get('covers_s')} s "
                                    f"of {a.duration_s} s")
        rep.media.append((t, a))


# ------------------------------------------------------------------------------ events

def _shot_event(eid: str, t: float, wr: WebResult, s: Shot, first_viewport: bool) -> Event:
    tgt = wr.target
    title = str(wr.meta.get("title") or tgt.title or "")
    url = tgt.url if tgt.kind == "url" else tgt.source
    weight = SHOT_WEIGHTS.get(s.kind, 0.5)
    if s.kind == "viewport" and not first_viewport:
        weight = 0.85
    if s.kind == "pdf_page" and (s.step or 1) > 1:
        weight = 0.6
    weight *= QUALITY_FACTOR.get(wr.quality, 1.0)
    data: dict[str, Any] = {
        "path": s.path, "url": url, "viewport": list(s.viewport), "full_page": s.full_page, "page_title": title,
        "kind": s.kind, "size": list(s.size), "dpr": s.dpr, "label": s.label, "target_kind": tgt.kind,
        "source_ids": tgt.event_ids, "quality": wr.quality, "ms": s.ms,
        "accent": wr.meta.get("accent", ""), "theme_color": wr.meta.get("theme_color"),
        "favicon": wr.meta.get("favicon", ""), "background": wr.meta.get("background"),
    }
    if s.selector:
        data["selector"] = s.selector
    if s.query:
        data["query"] = s.query
    if s.bbox:
        data["bbox"] = s.bbox
        data["clip"] = s.clip
        data["layout"] = list(s.viewport)
    if s.step is not None:
        data["step"] = s.step
    if s.action:
        data["action"] = s.action
    if s.truncated:
        data["truncated"] = True
    if tgt.kind == "pdf":
        data["pages"] = wr.meta.get("pages")
    what = s.label or s.kind
    where = url if len(url) <= 80 else url[:77] + "..."
    return Event(id=eid, t=t, kind="product_capture", tool=TOOL, title=f"{title or where} · {what}"[:120],
                 summary=f"Showreel capture of {where} ({what})"[:160], data=data, ok=True, weight=round(weight, 3))


def _media_event(eid: str, t: float, tgt: CaptureTarget, a: MediaAsset) -> Event:
    weight = MEDIA_WEIGHTS.get(a.kind, 0.7)
    cut = a.cutout or {}
    if cut.get("ok"):
        weight += 0.03
    data: dict[str, Any] = {
        "path": a.path, "url": tgt.source, "viewport": [a.w, a.h], "full_page": False,
        "page_title": a.title or Path(tgt.path).name, "kind": a.kind, "size": [a.w, a.h], "src": a.src,
        "target_kind": tgt.kind, "source_ids": tgt.event_ids, "format": a.format, "accent": a.accent,
        "palette": a.palette[:5], "ms": a.ms,
    }
    if a.kind == "video":
        data.update(duration_s=a.duration_s, fps=a.fps, poster=a.path, poster_t=a.poster_t)
    if a.animated:
        data["animated"] = True
    if cut:
        data["cutout"] = cut
    name = Path(tgt.path).name
    return Event(id=eid, t=t, kind="product_capture", tool=TOOL, title=f"{name} · {a.kind}"[:120],
                 summary=f"Showreel {a.kind} asset {name} ({a.w}x{a.h}"
                         f"{', cutout ' + str(cut.get('grade')) if cut else ''})"[:160],
                 data=data, ok=True, weight=round(min(1.0, weight), 3))


def _events(rep: CaptureReport, session_events: Sequence[Event]) -> list[Event]:
    n = _next_id(session_events)
    t = max((e.t for e in session_events), default=0.0)
    out: list[Event] = []
    for wr in rep.web:
        first = True
        for s in wr.shots:
            out.append(_shot_event(f"e{n}", t, wr, s, first_viewport=first or s.kind != "viewport"))
            if s.kind == "viewport":
                first = False
            n += 1
    for tgt, a in rep.media:
        if a.error or not a.path:
            continue
        out.append(_media_event(f"e{n}", t, tgt, a))
        n += 1
    return out
