"""Dry-run a built job: load it, seek a set of times, collect errors, QA issues, timings and a determinism probe.

This is the Director's feedback loop (STUDIO.md "Quality lock" (b)): every scene must dry-run without console
errors and give identical pixels for the same t regardless of seek order and instance cache.

    python -m showreel_core.film.dryrun JOB_DIR [--per-shot 3] [--size 960x540] [--no-determinism] [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any


ERR_OWNER_RE = re.compile(r"^(shot|overlay) ([^\s:]+)")


@dataclass
class ShotReport:
    """Per-shot findings."""
    id: str
    kind: str
    scene: str
    layer: str | None = None
    times: list[float] = field(default_factory=list)
    seek_ms: list[float] = field(default_factory=list)
    setup_ms: float | None = None
    render_ms_avg: float | None = None
    render_ms_max: float | None = None
    errors: list[str] = field(default_factory=list)
    qa: list[dict[str, Any]] = field(default_factory=list)
    deterministic: bool | None = None
    probe: dict[str, Any] = field(default_factory=dict)


@dataclass
class DryRunReport:
    """Whole-job findings; ``ok`` = loads, no scene/page errors, every probed shot deterministic."""
    ok: bool = False
    ready_error: str = ""
    scene_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    qa: list[dict[str, Any]] = field(default_factory=list)
    shots: list[ShotReport] = field(default_factory=list)
    cues: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """Short plain-text digest for an LLM prompt or a log line."""
        lines = [f"dry-run {'OK' if self.ok else 'FAILED'}"]
        if self.ready_error:
            lines.append(f"page did not load: {self.ready_error}")
        lines += [f"scene error: {e}" for e in self.scene_errors[:20]]
        lines += [f"page error: {e}" for e in self.page_errors[:10]]
        for s in self.shots:
            if s.deterministic is False:
                lines.append(f"shot {s.id}: NOT deterministic (same t gave different pixels: {s.probe.get('why', '')})")
            for q in s.qa[:6]:
                lines.append(f"shot {s.id} t={q.get('t', 0):.2f} {q['kind']}: {q['msg']}")
        return "\n".join(lines)


RASTER_JITTER = 2          # max channel difference tolerated between two renders of the same t (GPU raster paths)
RASTER_JITTER_FRAC = 0.02  # ... on at most this fraction of pixels


def pixel_hash(png: bytes) -> str:
    """Hash of decoded RGB pixels (independent of PNG encoder details)."""
    from PIL import Image

    with Image.open(BytesIO(png)) as im:
        return hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()[:16]


def pixel_diff(a: bytes, b: bytes) -> tuple[int, float]:
    """(max channel difference, fraction of pixels that differ at all) between two PNG captures."""
    from PIL import Image, ImageChops

    with Image.open(BytesIO(a)) as ia, Image.open(BytesIO(b)) as ib:
        if ia.size != ib.size:
            return 255, 1.0
        d = ImageChops.difference(ia.convert("RGB"), ib.convert("RGB"))
    mx = max(hi for _, hi in d.getextrema())
    if mx == 0:
        return 0, 0.0
    hist = d.convert("L").histogram()
    return mx, 1.0 - hist[0] / max(1, sum(hist))


def same_pixels(a: bytes, b: bytes) -> tuple[bool, int, float]:
    """Equal up to raster jitter (Chromium may rasterise a just-shown layer through a different path: <= 1-2/255)."""
    mx, frac = pixel_diff(a, b)
    return (mx <= RASTER_JITTER and frac <= RASTER_JITTER_FRAC), mx, frac


def _windows(film: dict[str, Any]) -> list[tuple[float, float]]:
    out = []
    for tr in film.get("transitions") or []:
        d = float(tr.get("dur") or 0)
        if d > 0 and tr.get("t") is not None:
            out.append((float(tr["t"]), float(tr["t"]) + d))
    return out


def sample_times(t0: float, t1: float, k: int, avoid: Sequence[tuple[float, float]] = ()) -> list[float]:
    """``k`` evenly spaced times inside [t0, t1), nudged out of transition windows when possible."""
    out = []
    for i in range(max(1, k)):
        t = t0 + (t1 - t0) * (i + 0.5) / max(1, k)
        for a, b in avoid:
            if a <= t < b:
                left, right = a - 0.05, b + 0.05
                t = right if right < t1 else (left if left >= t0 else t)
        out.append(round(t, 4))
    return sorted(set(out))


async def _run(job: Path, *, per_shot: int, times: Sequence[float] | None, w: int, h: int, gpu: bool,
               determinism: bool, page: str, rep: DryRunReport) -> None:
    from ..render.errors import RenderError
    from ..render.workers import page_session

    film = json.loads((job / "film.json").read_text(encoding="utf-8"))
    wins = _windows(film)
    t_load = time.perf_counter()
    try:
        async with page_session(job, page, w=w, h=h, gpu=gpu) as p:
            rep.timings["load_s"] = round(time.perf_counter() - t_load, 3)
            items = [*(("shot", s) for s in film.get("shots") or []), *(("overlay", o) for o in film.get("overlays") or [])]
            by_id: dict[tuple[str, str], ShotReport] = {}
            for kind, s in items:
                r = ShotReport(id=str(s.get("id")), kind=kind, scene=str(s.get("scene")))
                by_id[(kind, r.id)] = r
                rep.shots.append(r)
                if kind == "shot":
                    r.times = list(times) if times else sample_times(float(s["t0"]), float(s["t1"]), per_shot, wins)
                    r.times = [t for t in r.times if float(s["t0"]) <= t < float(s["t1"])] or r.times
            seen_err = 0
            for r in rep.shots:
                for t in r.times:
                    a = time.perf_counter()
                    await p.seek(t)
                    r.seek_ms.append(round((time.perf_counter() - a) * 1000, 2))
                    qa = await p.evaluate(f"window.__sr.qa({float(t)!r})") or []
                    for q in qa:
                        q["t"] = t
                        target = by_id.get(("shot", q.get("shot"))) or by_id.get(("overlay", q.get("shot"))) or r
                        if q not in target.qa:
                            target.qa.append(q)
                    errs = await p.evaluate("window.__sr.errors.slice()") or []
                    for e in errs[seen_err:]:
                        m = ERR_OWNER_RE.match(e)
                        owner = by_id.get((m.group(1), m.group(2)), r) if m else r
                        owner.errors.append(e)
                    seen_err = len(errs)
            if determinism:
                for r in rep.shots:
                    if r.kind != "shot" or not r.times:
                        continue
                    t = r.times[len(r.times) // 2]
                    other = next((x.times[0] for x in rep.shots if x is not r and x.times), None)
                    await p.seek(t)
                    c1 = await p.capture("png")
                    if other is not None:
                        await p.seek(other)
                    await p.seek(r.times[0] if r.times[0] != t else r.times[-1])
                    await p.seek(t)
                    c2 = await p.capture("png")
                    await p.evaluate("window.__sr.purge()")
                    await p.seek(t)
                    c3 = await p.capture("png")
                    ok12, mx12, f12 = same_pixels(c1, c2)
                    ok13, mx13, f13 = same_pixels(c1, c3)
                    r.probe = {"t": t, "hashes": [pixel_hash(c) for c in (c1, c2, c3)],
                               "max_diff": max(mx12, mx13), "changed_frac": round(max(f12, f13), 5)}
                    r.deterministic = ok12 and ok13
                    if not r.deterministic:
                        r.probe["why"] = ("render() depends on call order / accumulated state" if not ok12
                                          else "setup() is not deterministic (a fresh instance draws differently)")
            stats = await p.evaluate("window.__sr.shots()") or []
            for st in stats:
                r = by_id.get((st.get("kind"), st.get("id")))
                if r:
                    r.layer = st.get("layer")
                    r.setup_ms = st.get("setup_ms")
                    r.render_ms_avg = st.get("render_ms_avg")
                    r.render_ms_max = st.get("render_ms_max")
            rep.scene_errors = await p.evaluate("window.__sr.errors.slice()") or []
            rep.cues = await p.evaluate("window.__sr.cues") or []
            rep.page_errors = [e for e in p.errors if "[showreel]" not in e]
            rep.blocked = list(p.blocked)
    except RenderError as e:
        if e.code in ("page_contract", "page_load"):
            rep.ready_error = e.message
        else:
            rep.error = e.to_dict()


def dryrun(job_dir: Path, *, per_shot: int = 3, times: Sequence[float] | None = None,
           size: tuple[int, int] | None = None, determinism: bool = True, gpu: bool = False,
           lenient: bool = True) -> DryRunReport:
    """Dry-run ``job_dir`` (built by ``build_job``). Never raises; see :class:`DryRunReport`.

    ``lenient`` loads the page with ``?lenient=1`` so every broken scene is reported in one pass instead of the
    first failure rejecting ``__sr.ready``.
    """
    rep = DryRunReport()
    t0 = time.perf_counter()
    job = Path(job_dir)
    try:
        film = json.loads((job / "film.json").read_text(encoding="utf-8"))
        fw, fh = (int(v) for v in film.get("size", [1920, 1080]))
        w, h = size or (fw // 2, fh // 2)
        page = "stage.html?lenient=1" if lenient else "stage.html"
        from ..render.workers import _run_sync

        _run_sync(lambda: _run(job, per_shot=per_shot, times=times, w=w, h=h, gpu=gpu, determinism=determinism,
                               page=page, rep=rep))
        for s in rep.shots:
            rep.qa += [{**q, "shot": q.get("shot") or s.id} for q in s.qa]
        rep.ok = (not rep.ready_error and not rep.error and not rep.scene_errors and not rep.page_errors
                  and all(s.deterministic is not False for s in rep.shots))
    except Exception as e:  # noqa: BLE001  # never raise out of the entry point
        rep.error = {"code": "internal", "message": f"{type(e).__name__}: {e}"}
    rep.timings["total_s"] = round(time.perf_counter() - t0, 3)
    return rep


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.film.dryrun", description="Dry-run a built job.")
    ap.add_argument("job", type=Path)
    ap.add_argument("--per-shot", type=int, default=3)
    ap.add_argument("--times", default="", help="comma-separated times (default: per-shot samples)")
    ap.add_argument("--size", default="", help="WxH (default: half the film size)")
    ap.add_argument("--no-determinism", action="store_true")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--strict", action="store_true", help="load without ?lenient=1 (first failure rejects ready)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    times = [float(x) for x in a.times.split(",") if x.strip()] or None
    size = (int(a.size.lower().split("x")[0]), int(a.size.lower().split("x")[1])) if a.size else None
    r = dryrun(a.job, per_shot=a.per_shot, times=times, size=size, determinism=not a.no_determinism, gpu=a.gpu,
               lenient=not a.strict)
    if a.json:
        print(json.dumps(r.to_dict(), indent=1))
    else:
        print(r.summary())
        for s in r.shots:
            if s.times:
                print(f"  {s.kind} {s.id:<14} {s.layer or '?':<5} setup {s.setup_ms} ms, render avg {s.render_ms_avg} "
                      f"max {s.render_ms_max} ms, seek {sum(s.seek_ms) / max(1, len(s.seek_ms)):.1f} ms, "
                      f"deterministic={s.deterministic}")
        print("timings: " + ", ".join(f"{k}={v}" for k, v in r.timings.items()))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
