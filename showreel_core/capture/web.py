"""Capture a web product with Showreel's own headless Chromium.

Per page (a reachable URL, or a local HTML file served read-only over loopback):

1. desktop viewports (1920x1080 = 16:9 film size, then 1440x900 = the layout used below);
2. full page at the layout width (pre-scrolled so lazy images / reveal-on-scroll content appear,
   then ``captureBeyondViewport``; height capped, default 12000 px) for SCROLL scenes;
3. feature element crops: CSS selectors or text queries (storyboard/Director, or the product's
   feature names), expanded to their card, captured at 2x with padding; plus auto-detected
   feature cards when there are few queries;
4. a mobile viewport (390x844 CSS px at DPR 2, touch, Android Chrome UA) + a short mobile full page;
5. a small interaction sequence as numbered stills (scroll positions, hover on the primary CTA, and
   only when asked: click/type on a selector - destructive-looking controls are refused).

Waits for network idle + fonts + decoded images + a settle delay, dismisses cookie banners, flags
dev-server error overlays and blank pages, and records page title, theme colour, accent and favicon.
Network policy: see :mod:`.policy`.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import re
import shutil
import threading
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from ..render.errors import RenderError
from ..render.serve import PageServer
from . import pagejs
from .browser import CaptureBrowser, CapturePage
from .colors import choose_accent, dominant_accent, luminance_stats, palette
from .media import pdf_info
from .policy import NetPolicy, origin_of
from .targets import CaptureTarget

DESTRUCTIVE_RE = re.compile(
    r"\b(delete|remove|erase|destroy|drop|reset|clear all|wipe|purge|unsubscribe|log ?out|sign ?out|pay|"
    r"purchase|buy now|checkout|place order|submit order|confirm|send|transfer|deploy|publish|uninstall)\b", re.I)
SELECTOR_RE = re.compile(r"^\s*(?:[#.\[]|[a-z][\w-]*(?:[#.\[:]|\s*[>+~]\s*)|\*)", re.I)

ProgressCB = Callable[[int, int, str], None]


# ----------------------------------------------------------------------------- inputs

@dataclass
class FeatureQuery:
    """An element to crop: a CSS ``selector`` and/or ``text`` to find; ``label`` names the crop."""
    selector: str = ""
    text: str = ""
    label: str = ""
    pad: int = 24
    expand: bool = True

    @classmethod
    def coerce(cls, q: Any) -> FeatureQuery | None:
        """From a string (selector if it looks like one, else text) or a dict."""
        if isinstance(q, FeatureQuery):
            return q
        if isinstance(q, str):
            s = q.strip()
            if not s:
                return None
            return cls(selector=s, label=s) if looks_like_selector(s) else cls(text=s, label=s)
        if isinstance(q, dict):
            sel, txt = str(q.get("selector") or ""), str(q.get("text") or q.get("query") or "")
            if not (sel or txt):
                return None
            return cls(sel, txt, str(q.get("label") or txt or sel), int(q.get("pad", 24)), bool(q.get("expand", True)))
        return None

    def js(self) -> dict[str, Any]:
        return {"selector": self.selector, "text": self.text, "expand": self.expand}


def looks_like_selector(s: str) -> bool:
    """``#id``, ``.class``, ``[attr]``, ``tag.class``, ``nav > a`` ... (plain words are text queries)."""
    return bool(SELECTOR_RE.match(s))


@dataclass
class WebPlan:
    """What to capture per page. Defaults follow SPEC §1 / WP-J."""
    desktop: tuple[tuple[int, int], ...] = ((1920, 1080), (1440, 900))
    layout: tuple[int, int] = (1440, 900)          # full page, elements and interactions use this
    desktop_dpr: float = 1.0
    mobile: tuple[int, int] | None = (390, 844)
    mobile_dpr: float = 2.0
    mobile_full_screens: float = 4.0
    full_page: bool = True
    full_page_max_h: int = 12000
    element_scale: float = 2.0
    element_max_h_screens: float = 2.5
    features: list[FeatureQuery] = field(default_factory=list)
    auto_features: int = 4                          # top up with detected feature cards up to this many crops
    max_elements: int = 6
    interactions: list[dict[str, Any]] | None = None  # None -> scroll stills + CTA hover
    settle_ms: int = 600
    idle_ms: int = 500
    load_timeout_s: float = 20.0
    allow_third_party: bool = False
    allow_writes: bool = False
    dismiss_banners: bool = True
    pdf_pages: int = 2


# ---------------------------------------------------------------------------- outputs

@dataclass
class Shot:
    """One saved capture."""
    kind: str                       # viewport | full | mobile | mobile_full | element | interaction | pdf_page
    path: str
    url: str
    viewport: tuple[int, int]       # CSS px
    dpr: float
    size: tuple[int, int]           # image px
    full_page: bool = False
    label: str = ""
    selector: str = ""
    query: str = ""
    bbox: list[float] | None = None     # element rect in page CSS px at the layout width
    clip: list[float] | None = None     # captured rect (bbox + padding)
    step: int | None = None
    action: str = ""
    truncated: bool = False
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WebResult:
    """Everything captured from one web/PDF target (partial when time ran out)."""
    target: CaptureTarget
    url: str = ""
    ok: bool = False
    shots: list[Shot] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    blocked_writes: list[str] = field(default_factory=list)
    third_party: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    dialogs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    banner: dict[str, Any] | None = None
    quality: str = "ok"             # ok | blank | error_overlay
    timings_ms: dict[str, float] = field(default_factory=dict)
    timed_out: bool = False
    error: dict[str, Any] | None = None
    wall_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["target"] = self.target.to_dict()
        return d


def slug(text: str, n: int = 32) -> str:
    """Filesystem-safe ASCII slug + crc32 suffix (stable, collision-resistant)."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:n].strip("-") or "x"
    return f"{s}-{zlib.crc32(text.encode('utf-8')) & 0xFFFFFF:06x}"


def _img_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# ----------------------------------------------------------------------------- runner

class _Clock:
    def __init__(self, deadline: float, cancel: threading.Event | None) -> None:
        self.deadline = deadline
        self.cancel = cancel

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def ok(self, need: float = 0.0) -> bool:
        return not (self.cancel is not None and self.cancel.is_set()) and self.left() > need


class _WebJob:
    """Captures for one target; every step is isolated so a failure only loses that step."""

    def __init__(self, browser: CaptureBrowser, target: CaptureTarget, out_dir: Path, plan: WebPlan,
                 clock: _Clock, result: WebResult) -> None:
        self.b = browser
        self.t = target
        self.plan = plan
        self.clock = clock
        self.r = result
        self.dir = out_dir
        self.pages: list[CapturePage] = []
        self.title = ""

    async def step(self, name: str, need_s: float, fn: Callable[[], Any]) -> Any:
        if not self.clock.ok(need_s):
            self.r.timed_out = self.r.timed_out or not (self.clock.cancel and self.clock.cancel.is_set())
            self.r.warnings.append(f"{name}: skipped (time budget)" if self.clock.left() <= need_s
                                   else f"{name}: skipped (cancelled)")
            return None
        t0 = time.monotonic()
        try:
            return await asyncio.wait_for(fn(), timeout=max(1.0, self.clock.left()))
        except TimeoutError:
            self.r.timed_out = True
            self.r.warnings.append(f"{name}: ran out of time")
        except RenderError as e:
            self.r.warnings.append(f"{name}: {e.code}: {e.message}"[:300])
        except Exception as e:
            self.r.warnings.append(f"{name}: {type(e).__name__}: {e}"[:300])
        finally:
            self.r.timings_ms[name] = round((time.monotonic() - t0) * 1000, 1)
        return None

    def save(self, name: str, data: bytes, **kw: Any) -> Shot:
        p = self.dir / name
        p.write_bytes(data)
        shot = Shot(path=str(p), url=self.r.url, size=_img_size(data), **kw)
        self.r.shots.append(shot)
        return shot

    async def ready(self, page: CapturePage, *, settle_ms: int | None = None, timeout: float = 10.0) -> None:
        await page.ready(idle_ms=self.plan.idle_ms, settle_ms=self.plan.settle_ms if settle_ms is None else settle_ms,
                         timeout=min(timeout, max(1.0, self.clock.left())))

    async def open_page(self, policy: NetPolicy, url: str, *, w: int, h: int, dpr: float,
                        mobile: bool = False) -> CapturePage:
        page = await self.b.new_page(policy, w=w, h=h, dpr=dpr, mobile=mobile)
        self.pages.append(page)
        err = await page.goto(url, timeout=min(self.plan.load_timeout_s, max(2.0, self.clock.left())))
        if err:
            raise RenderError("page_load", f"navigation failed: {err}", url=url)
        await self.ready(page)
        if self.plan.dismiss_banners:
            banner = await page.eval(pagejs.BANNER_JS, timeout=8)
            if banner and banner.get("actions"):
                self.r.banner = banner if self.r.banner is None else self.r.banner
                await asyncio.sleep(0.25)
        return page

    # ------------------------------------------------------------------ desktop
    async def desktop(self, policy: NetPolicy) -> CapturePage | None:
        """Load the page at the first desktop size (or the layout size when no desktop shots are wanted)."""
        (w, h), dpr = (self.plan.desktop or (self.plan.layout,))[0], self.plan.desktop_dpr
        t0 = time.monotonic()
        page = await self.open_page(policy, self.r.url, w=w, h=h, dpr=dpr)
        state = await page.eval(pagejs.PAGE_STATE_JS) or {}
        if state.get("error_overlay"):
            self.r.quality = "error_overlay"
            self.r.warnings.append(f"the page shows a dev-server error overlay ({state['error_overlay']})")
        self.r.meta.update(await page.eval(pagejs.META_JS) or {})
        self.title = str(self.r.meta.get("title") or self.t.title or "")
        data = await page.shot()
        if self.plan.desktop:
            self.save(f"desktop_{w}x{h}.png", data, kind="viewport", viewport=(w, h), dpr=dpr,
                      label=f"desktop {w}x{h}", ms=_ms(t0))
        _mean, sd = luminance_stats(Image.open(io.BytesIO(data)))
        if sd < 2.0 and not state.get("media") and int(state.get("text_chars") or 0) < 3:
            self.r.quality = "blank" if self.r.quality == "ok" else self.r.quality
            self.r.warnings.append("the page looks blank (no text or media rendered)")
        return page

    async def other_desktops(self, page: CapturePage) -> None:
        for w, h in self.plan.desktop[1:]:
            if not self.clock.ok(1.5):
                self.r.timed_out = True
                break
            t0 = time.monotonic()
            await page.emulate(w, h, dpr=self.plan.desktop_dpr)
            await self.ready(page, settle_ms=350, timeout=4)
            data = await page.shot()
            self.save(f"desktop_{w}x{h}.png", data, kind="viewport", viewport=(w, h), dpr=self.plan.desktop_dpr,
                      label=f"desktop {w}x{h}", ms=_ms(t0))

    async def to_layout(self, page: CapturePage) -> None:
        w, h = self.plan.layout
        if (page.w, page.h, page.mobile) != (w, h, False):
            await page.emulate(w, h, dpr=self.plan.desktop_dpr)
            await self.ready(page, settle_ms=300, timeout=4)

    async def accent_and_favicon(self, page: CapturePage) -> None:
        layout_shot = next((s for s in self.r.shots if s.viewport == self.plan.layout and s.kind == "viewport"),
                           self.r.shots[0] if self.r.shots else None)
        pal: list[dict[str, Any]] = []
        if layout_shot is not None:
            with Image.open(layout_shot.path) as im:
                pal = palette(im)
        m = self.r.meta
        accent, source = choose_accent([("theme-color", m.get("theme_color")), ("primary button", m.get("cta_color")),
                                        ("dominant colour", dominant_accent(pal)),
                                        ("link colour", m.get("link_color"))])
        m.update(palette=pal, accent=accent, accent_source=source)
        fav = await page.eval(pagejs.FAVICON_JS, timeout=8)
        if fav and fav.get("data"):
            m["favicon"] = save_favicon(str(fav["data"]), self.dir)

    # ------------------------------------------------------------------ full page
    async def full(self, page: CapturePage, *, mobile: bool = False) -> None:
        cap = int(self.plan.mobile_full_screens * page.h) if mobile else self.plan.full_page_max_h
        t0 = time.monotonic()
        dims = await page.eval(pagejs.scroll_pass(cap), timeout=max(2.0, min(30.0, self.clock.left()))) or {}
        await self.ready(page, settle_ms=400, timeout=5)
        doc_h = int(dims.get("height") or page.h)
        w = page.w
        h = max(page.h, min(doc_h, cap))
        data = await page.shot(clip={"x": 0, "y": 0, "width": w, "height": h}, beyond=True, fmt="jpeg", quality=88,
                               timeout=max(5.0, min(45.0, self.clock.left())))
        name = f"mobile_full_{w}.jpg" if mobile else f"full_{w}.jpg"
        self.save(name, data, kind="mobile_full" if mobile else "full", viewport=(page.w, page.h), dpr=page.dpr,
                  full_page=True, truncated=doc_h > cap, label=f"full page {w}x{h}", ms=_ms(t0))
        await page.eval("window.scrollTo(0, 0)")

    # ------------------------------------------------------------------ elements
    async def find(self, page: CapturePage, q: FeatureQuery) -> dict[str, Any] | None:
        return await page.eval(pagejs.call("find", q.js()))

    async def elements(self, page: CapturePage) -> None:
        found: list[tuple[dict[str, Any], FeatureQuery | None]] = []
        seen: set[str] = set()
        for q in self.plan.features[: self.plan.max_elements]:
            hit = await self.find(page, q)
            if not hit:
                self.r.misses.append(q.label or q.text or q.selector)
                continue
            if hit["selector"] not in seen:
                seen.add(hit["selector"])
                found.append((hit, q))
        room = min(self.plan.auto_features, self.plan.max_elements) - len(found)
        if room > 0:
            for hit in await page.eval(pagejs.call("features", room + len(found))) or []:
                if hit["selector"] not in seen and len(found) < self.plan.max_elements and room > 0:
                    seen.add(hit["selector"])
                    found.append((hit, None))
                    room -= 1
        for i, (hit, q) in enumerate(found, 1):
            if not self.clock.ok(1.0):
                self.r.timed_out = True
                break
            await self.element_shot(page, i, hit, q)
        await page.eval("window.scrollTo(0, 0)")

    async def element_shot(self, page: CapturePage, i: int, hit: dict[str, Any], q: FeatureQuery | None) -> None:
        t0 = time.monotonic()
        sel = hit["selector"]
        await page.eval(pagejs.scroll_into_view(sel))
        await asyncio.sleep(0.35)
        await page.network_idle(idle_ms=200, timeout=1.5)
        r = await page.eval(pagejs.rect_of(sel))
        if not r:
            self.r.misses.append(q.label if q else hit.get("label", sel))
            return
        pad = q.pad if q else 24
        x0, y0 = max(0.0, r["x"] - pad), max(0.0, r["y"] - pad)
        x1 = min(float(r["doc_w"]), r["x"] + r["w"] + pad)
        y1 = min(float(r["doc_h"]), r["y"] + r["h"] + pad, y0 + self.plan.element_max_h_screens * r["vh"])
        cw, ch = max(8.0, x1 - x0), max(8.0, y1 - y0)
        beyond = ch > r["vh"] or cw > r["vw"]
        data = await page.shot(clip={"x": x0, "y": y0, "width": cw, "height": ch, "scale": self.plan.element_scale},
                               beyond=beyond)
        label = (q.label if q else "") or hit.get("label") or f"element {i}"
        self.save(f"element_{i:02d}_{slug(label, 24)}.png", data, kind="element", viewport=(page.w, page.h),
                  dpr=self.plan.element_scale, label=label, selector=(q.selector if q and q.selector else sel),
                  query=(q.text if q else ""), bbox=[round(r["x"], 1), round(r["y"], 1), round(r["w"], 1),
                                                     round(r["h"], 1)],
                  clip=[round(x0, 1), round(y0, 1), round(cw, 1), round(ch, 1)], ms=_ms(t0))

    # ------------------------------------------------------------------ mobile
    async def mobile(self, policy: NetPolicy) -> None:
        assert self.plan.mobile is not None
        w, h = self.plan.mobile
        t0 = time.monotonic()
        page = await self.open_page(policy, self.r.url, w=w, h=h, dpr=self.plan.mobile_dpr, mobile=True)
        data = await page.shot()
        self.save(f"mobile_{w}x{h}.png", data, kind="mobile", viewport=(w, h), dpr=self.plan.mobile_dpr,
                  label=f"mobile {w}x{h}", ms=_ms(t0))
        if self.plan.mobile_full_screens > 1 and self.clock.ok(3.0):
            await self.full(page, mobile=True)

    # ------------------------------------------------------------------ interactions
    def default_steps(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        if self.r.meta.get("cta_selector"):
            steps.append({"hover": {"selector": self.r.meta["cta_selector"]}, "label": "hover primary button"})
        sh, vh = float(self.r.meta.get("scroll_height") or 0), float(self.plan.layout[1])
        if sh > vh * 1.5:
            steps += [{"scroll": f, "label": f"scroll {int(f * 100)}%"} for f in (0.33, 0.66, 1.0)]
        return steps

    async def interactions(self, page: CapturePage) -> None:
        steps = self.plan.interactions if self.plan.interactions is not None else self.default_steps()
        n = 0
        for raw in steps[:12]:
            if not self.clock.ok(1.0):
                self.r.timed_out = True
                break
            if not isinstance(raw, dict):
                continue
            t0 = time.monotonic()
            action = await self.do_step(page, raw)
            if action is None or raw.get("capture") is False or action == "wait":
                continue
            n += 1
            data = await page.shot()
            label = str(raw.get("label") or action)
            self.save(f"step_{n:02d}_{slug(label, 20)}.png", data, kind="interaction", viewport=(page.w, page.h),
                      dpr=page.dpr, step=n, action=action, label=label, ms=_ms(t0))

    async def do_step(self, page: CapturePage, st: dict[str, Any]) -> str | None:
        """Perform one step; returns the action name, or None when it could not be done."""
        settle = int(st.get("settle_ms", 450))
        if "wait" in st:
            await asyncio.sleep(min(5.0, float(st["wait"]) / 1000))
            return "wait"
        if "scroll" in st:
            v = float(st["scroll"])
            await page.eval(pagejs.scroll_to(v, fraction=v <= 1.0))
            await asyncio.sleep(settle / 1000)
            await page.network_idle(idle_ms=200, timeout=1.5)
            return "scroll"
        for action in ("scroll_to", "hover", "click", "type"):
            if action not in st:
                continue
            q = FeatureQuery.coerce(st.get("into") if action == "type" else st[action])
            if q is None:
                return None
            q.expand = False
            hit = await self.find(page, q)
            if not hit:
                self.r.misses.append(f"{action}: {q.label}")
                return None
            sel = hit["selector"]
            await page.eval(pagejs.scroll_into_view(sel))
            await asyncio.sleep(0.2)
            r = await page.eval(pagejs.rect_of(sel))
            if not r:
                return None
            if action in ("click", "type") and DESTRUCTIVE_RE.search(f"{r.get('text', '')} {hit.get('label', '')}"):
                self.r.warnings.append(f"{action} on {r.get('text', '')[:40]!r} refused: looks destructive")
                return None
            if action == "hover":
                await page.mouse("mouseMoved", r["cx"], r["cy"])
            elif action == "click":
                before = await page.eval("location.href")
                await page.mouse("mouseMoved", r["cx"], r["cy"])
                await page.mouse("mousePressed", r["cx"], r["cy"], button="left", clicks=1)
                await page.mouse("mouseReleased", r["cx"], r["cy"], button="left", clicks=1)
                await asyncio.sleep(0.3)
                if await page.eval("location.href") != before:
                    await self.ready(page, settle_ms=settle, timeout=6)
            elif action == "type":
                await page.eval(pagejs.type_into(sel, str(st["type"])))
            await asyncio.sleep(settle / 1000)
            await page.network_idle(idle_ms=200, timeout=1.5)
            return action
        return None


def save_favicon(data_url: str, out_dir: Path) -> str:
    """Save a favicon data URL as PNG (ICO/bitmap) or SVG; returns the path or ""."""
    try:
        head, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64) if ";base64" in head else b64.encode("utf-8")
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return ""
    if "svg" in head or raw.lstrip()[:5] in (b"<svg ", b"<?xml"):
        p = out_dir / "favicon.svg"
        p.write_bytes(raw)
        return str(p)
    try:
        with Image.open(io.BytesIO(raw)) as im:   # ICO: Pillow loads the largest size
            p = out_dir / "favicon.png"
            im.convert("RGBA").save(p)
            return str(p)
    except (OSError, ValueError, SyntaxError):
        return ""


def stage_copy(target: CaptureTarget, dest: Path) -> Path:
    """Copy a page (+ the files it references) into ``dest`` for serving a too-broad folder safely."""
    src = Path(target.serve_root)
    for rel in [target.serve_rel, *target.stage_files]:
        s, d = src / rel, dest / rel
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        except OSError:
            continue
    return dest


def _ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 1)


# ------------------------------------------------------------------------ public API

async def capture_web_target(browser: CaptureBrowser, target: CaptureTarget, out_dir: Path, plan: WebPlan, *,
                             deadline: float, cancel: threading.Event | None = None,
                             result: WebResult | None = None) -> WebResult:
    """Capture one ``url``/``html`` target into ``out_dir`` (created). Never raises; may be partial."""
    res = result or WebResult(target)
    t_start = time.monotonic()
    clock = _Clock(deadline, cancel)
    out_dir.mkdir(parents=True, exist_ok=True)
    job = _WebJob(browser, target, out_dir, plan, clock, res)
    server: PageServer | None = None
    try:
        if target.kind == "html":
            root = stage_copy(target, out_dir / "_stage") if target.staged else Path(target.serve_root)
            server = PageServer(root).start()
            res.url = server.url(target.serve_rel)
            policy = NetPolicy.for_origin(origin_of(server.base_url), rewrite_prefix=server.base_url,
                                          third_party=plan.allow_third_party, writes=plan.allow_writes)
        else:
            res.url = target.url
            policy = NetPolicy.for_origin(target.origin, third_party=plan.allow_third_party, writes=plan.allow_writes)
        page = await job.step("desktop", 2.0, lambda: job.desktop(policy))
        if page is None:
            if not res.error:
                res.error = {"code": "page_load", "message": "; ".join(res.warnings[-1:]) or "page did not load"}
            return res
        res.ok = True
        await job.step("desktop_more", 1.5, lambda: job.other_desktops(page))
        await job.step("layout", 1.0, lambda: job.to_layout(page))
        await job.step("accent_favicon", 0.5, lambda: job.accent_and_favicon(page))
        if plan.full_page:
            await job.step("full_page", 2.0, lambda: job.full(page))
        if plan.max_elements > 0:
            await job.step("elements", 1.5, lambda: job.elements(page))
        if plan.mobile:
            await job.step("mobile", 3.0, lambda: job.mobile(policy))
        await job.step("interactions", 1.5, lambda: job.interactions(page))
    except asyncio.CancelledError:
        res.timed_out = True
        raise
    except Exception as e:
        res.error = {"code": "internal", "message": f"{type(e).__name__}: {e}"[:300]}
    finally:
        for p in job.pages:
            res.blocked += [u for u in p.blocked if u not in res.blocked][:100]
            res.blocked_writes += p.blocked_writes
            res.third_party += p.third_party
            res.page_errors += p.errors
            res.dialogs += p.dialogs
            with contextlib.suppress(Exception):
                await asyncio.shield(p.close())
        if server is not None:
            server.stop()
        res.wall_ms = _ms(t_start)
    return res


async def capture_pdf_target(browser: CaptureBrowser, target: CaptureTarget, out_dir: Path, plan: WebPlan, *,
                             deadline: float, cancel: threading.Event | None = None,
                             result: WebResult | None = None) -> WebResult:
    """First ``plan.pdf_pages`` pages of a PDF via Chromium's built-in viewer, cropped to the page."""
    res = result or WebResult(target)
    t_start = time.monotonic()
    clock = _Clock(deadline, cancel)
    out_dir.mkdir(parents=True, exist_ok=True)
    server: PageServer | None = None
    pages: list[CapturePage] = []
    try:
        root = stage_copy(target, out_dir / "_stage") if target.staged else Path(target.serve_root)
        server = PageServer(root).start()
        policy = NetPolicy.for_origin(origin_of(server.base_url), rewrite_prefix=server.base_url)
        total = pdf_info(Path(target.path)).pages or plan.pdf_pages
        prev = b""
        for n in range(1, max(1, min(plan.pdf_pages, total)) + 1):
            if not clock.ok(2.0):
                res.timed_out = True
                break
            t0 = time.monotonic()
            # a fresh tab per page: re-navigating one tab between PDF URLs keeps showing the first document view
            page = await browser.new_page(policy, w=900, h=1165, dpr=1.5)
            pages.append(page)
            res.url = server.url(f"{target.serve_rel}?p={n}") + f"#page={n}&toolbar=0&navpanes=0&view=Fit"
            err = await page.goto(res.url, timeout=min(15.0, max(2.0, clock.left())))
            if err:
                raise RenderError("page_load", f"PDF did not open: {err}")
            got = await _stable_page(page, min(8.0, max(1.0, clock.left())), avoid=prev)
            if got is None:
                res.warnings.append(f"page {n}: the viewer showed nothing new")
                break
            crop, prev = got
            p = out_dir / f"pdf_page_{n:02d}.png"
            crop.save(p, "PNG")
            res.shots.append(Shot(kind="pdf_page", path=str(p), url="", viewport=(900, 1165), dpr=1.5,
                                  size=crop.size, label=f"page {n}", step=n, ms=_ms(t0)))
            res.blocked += page.blocked
            await page.close()
        res.ok = bool(res.shots)
    except asyncio.CancelledError:
        res.timed_out = True
        raise
    except RenderError as e:
        res.error = e.to_dict()
    except Exception as e:
        res.error = {"code": "internal", "message": f"{type(e).__name__}: {e}"[:300]}
    finally:
        for page in pages:
            with contextlib.suppress(Exception):
                await asyncio.shield(page.close())
        if server is not None:
            server.stop()
        res.wall_ms = _ms(t_start)
    return res


async def _stable_page(page: CapturePage, timeout: float, *, avoid: bytes = b"") -> tuple[Image.Image, bytes] | None:
    """Poll the viewer until two consecutive captures match, are not blank and show a page whose
    digest differs from ``avoid`` (the previous page); returns (cropped page, digest)."""
    end = time.monotonic() + timeout
    last = b""
    await asyncio.sleep(0.4)
    while time.monotonic() < end:
        data = await page.shot(timeout=10)
        if data == last:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            crop = crop_pdf_page(img)
            if crop.size != img.size:           # a page stands out from the viewer backdrop
                digest = zlib.crc32(crop.tobytes()).to_bytes(4, "big")
                if digest != avoid:
                    return crop, digest
        last = data
        await asyncio.sleep(0.3)
    return None


def crop_pdf_page(img: Image.Image, tol: int = 14) -> Image.Image:
    """Crop the page out of the viewer: bounding box of pixels that differ from the backdrop colour."""
    from PIL import ImageChops

    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, rgb.getpixel((2, 2)))
    diff = ImageChops.difference(rgb, bg).convert("L").point([255 if v > tol else 0 for v in range(256)])
    box = diff.getbbox()
    return rgb.crop(box) if box else rgb


async def capture_web_targets(targets: Sequence[CaptureTarget], out_dir: Path, plan: WebPlan, *, deadline: float,
                              cancel: threading.Event | None = None, results: list[WebResult] | None = None,
                              progress: ProgressCB | None = None, allowed_hosts: Sequence[str] = (),
                              open_dns: bool = False, ignore_cert_errors: bool = False,
                              browser: Any = None, profile_root: Path | None = None) -> list[WebResult]:
    """One browser for all web/PDF targets; per-target time shares; results appended as they finish.

    ``results`` (if given) is filled in place so a caller that times this coroutine out keeps the
    partial captures. Raises only ``RenderError`` for browser launch problems (caller reports them).
    """
    out = results if results is not None else []
    if not targets:
        return out
    async with CaptureBrowser(allowed_hosts=tuple(allowed_hosts), open_dns=open_dns,
                              ignore_cert_errors=ignore_cert_errors, browser=browser,
                              profile_root=profile_root) as b:
        for i, t in enumerate(targets):
            left = deadline - time.monotonic()
            if left <= 1.0 or (cancel is not None and cancel.is_set()):
                break
            share = left / (len(targets) - i)
            t_deadline = time.monotonic() + max(share, min(left, 12.0))
            sub = out_dir / f"{t.kind}_{i + 1:02d}_{slug(t.host or Path(t.path).stem or t.source, 24)}"
            res = WebResult(t)
            out.append(res)
            if progress is not None:
                with contextlib.suppress(Exception):
                    progress(i, len(targets), f"capturing {t.title or t.url or Path(t.path).name}")
            fn = capture_pdf_target if t.kind == "pdf" else capture_web_target
            await fn(b, t, sub, plan, deadline=min(t_deadline, deadline), cancel=cancel, result=res)
            res.meta.setdefault("browser", b.product)
            if b.popups_closed:
                res.warnings.append(f"{b.popups_closed} popup window(s) closed")
    return out
