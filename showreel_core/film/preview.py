"""Preview a film: keyframe stills + contact sheet (and optionally a short video) with QA and errors.

    python -m showreel_core.film.preview FILM.json --keyframes 0,2.5,5 --out DIR [--kits DIR] [--scenes DIR]
        [--size 960x540] [--per-shot 1] [--video] [--gpu auto|on|off] [--lenient] [--json]

``film.json`` assets may carry ``"src"`` (relative to the film file) and are prepared into the job; scenes are
read from ``--scenes`` (default: ``<film dir>/scenes``): ``X.js`` -> ``custom:X``, ``lib-X.js`` -> ``lib:X``.
Set ``SHOWREEL_RENDER_SLOT_DIR`` (or ``--slot-dir``) to share render slots with other jobs on one machine.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .page import KITS_ROOT, JobError, build_job


@dataclass
class Still:
    """One captured keyframe."""
    t: float
    png: bytes
    shots: list[str] = field(default_factory=list)
    qa: list[dict[str, Any]] = field(default_factory=list)
    seek_ms: float = 0.0
    capture_ms: float = 0.0


@dataclass
class PreviewResult:
    ok: bool
    job_dir: str = ""
    stills: list[str] = field(default_factory=list)
    contact_sheet: str = ""
    video: str = ""
    errors: list[str] = field(default_factory=list)        # scene exceptions (__sr.errors)
    page_errors: list[str] = field(default_factory=list)   # console errors / uncaught exceptions
    qa: list[dict[str, Any]] = field(default_factory=list)
    cues: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@contextlib.contextmanager
def render_slot(slot_dir: str | Path | None, who: str = "showreel-preview", *, stale_s: float = 900,
                wait_s: float = 600) -> Iterator[Path | None]:
    """Hold one of ``render.slot1..3`` in ``slot_dir`` (cooperative lock); no-op when ``slot_dir`` is None."""
    if not slot_dir:
        yield None
        return
    d = Path(slot_dir)
    deadline = time.monotonic() + wait_s
    while True:
        for i in (1, 2, 3):
            p = d / f"render.slot{i}"
            with contextlib.suppress(OSError):
                if p.exists() and time.time() - p.stat().st_mtime >= stale_s:
                    p.unlink()
            try:
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{who} {os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
            try:
                yield p
            finally:
                p.unlink(missing_ok=True)
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"no free render slot in {d} after {wait_s:.0f}s")
        time.sleep(5)


def load_film_dir(film_path: Path, scenes_dir: Path | None = None) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """Read film.json + scene sources + asset specs (``src`` resolved against the film's folder)."""
    film = json.loads(film_path.read_text(encoding="utf-8"))
    base = film_path.parent
    sdir = scenes_dir or base / "scenes"
    scenes: dict[str, str] = {}
    if sdir.is_dir():
        for p in sorted(sdir.glob("*.js")):
            sid = f"lib:{p.stem[4:]}" if p.stem.startswith("lib-") else f"custom:{p.stem}"
            scenes[sid] = p.read_text(encoding="utf-8")
    assets: dict[str, Any] = {}
    for name, spec in (film.get("assets") or {}).items():
        if isinstance(spec, dict) and spec.get("src"):
            src = Path(spec["src"])
            assets[name] = {**spec, "src": str(src if src.is_absolute() else (base / src).resolve())}
    return film, scenes, assets


def keyframes_for(film: dict[str, Any], per_shot: int) -> list[float]:
    """``per_shot`` evenly spaced times inside every shot (and the middle of every transition)."""
    out: list[float] = []
    for s in film.get("shots") or []:
        t0, t1 = float(s["t0"]), float(s["t1"])
        for k in range(per_shot):
            out.append(round(t0 + (t1 - t0) * (k + 0.5) / per_shot, 3))
    for tr in film.get("transitions") or []:
        if float(tr.get("dur", 0)) > 0 and tr.get("t") is not None:
            out.append(round(float(tr["t"]) + float(tr["dur"]) / 2, 3))
    return sorted(set(out))


async def capture_keyframes(job_dir: Path, times: Sequence[float], *, w: int, h: int, gpu: bool = False,
                            page: str = "stage.html") -> tuple[list[Still], dict[str, Any]]:
    """Seek + capture + QA each time in one browser session. Raises RenderError on load failures."""
    from ..render.workers import page_session

    stills: list[Still] = []
    async with page_session(job_dir, page, w=w, h=h, gpu=gpu) as p:
        for t in times:
            a = time.perf_counter()
            await p.seek(t)
            b = time.perf_counter()
            png = await p.capture("png")
            c = time.perf_counter()
            qa = await p.evaluate(f"window.__sr.qa({float(t)!r})") or []
            tt = repr(float(t))
            live = await p.evaluate(
                f"window.__sr.shots().filter(s => s.kind === 'shot' && s.t0 <= {tt} && {tt} < s.t1).map(s => s.id)")
            stills.append(Still(t, png, live or [], qa, (b - a) * 1000, (c - b) * 1000))
        info = {
            "errors": await p.evaluate("window.__sr.errors.slice()") or [],
            "cues": await p.evaluate("window.__sr.cues") or [],
            "page_errors": list(p.errors),
        }
    return stills, info


def contact_sheet(stills: Sequence[Still], out_png: Path, *, thumb_w: int = 480, cols: int = 4) -> Path:
    """Labelled grid of keyframes (t + live shots + QA count)."""
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    thumbs = []
    for s in stills:
        with Image.open(BytesIO(s.png)) as im:
            r = im.convert("RGB")
            th = r.resize((thumb_w, max(1, round(r.height * thumb_w / r.width))), Image.Resampling.LANCZOS)
            thumbs.append(th)
    if not thumbs:
        raise ValueError("no stills")
    cols = max(1, min(cols, len(thumbs)))
    rows = (len(thumbs) + cols - 1) // cols
    lab = 28
    th_h = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * 8, rows * (th_h + lab) + (rows + 1) * 8), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(15)
    for i, (s, th) in enumerate(zip(stills, thumbs, strict=True)):
        x = 8 + (i % cols) * (thumb_w + 8)
        y = 8 + (i // cols) * (th_h + lab + 8)
        sheet.paste(th, (x, y))
        issues = [q for q in s.qa if q.get("kind") != "safe"]
        label = f"t={s.t:.2f}  {'+'.join(s.shots)}" + (f"  qa:{len(issues)}" if issues else "")
        d.text((x + 2, y + th_h + 6), label, fill=(255, 120, 120) if issues else (220, 220, 230), font=font)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def preview(film_path: Path, out_dir: Path, *, keyframes: Sequence[float] | None = None, per_shot: int = 1,
            size: tuple[int, int] | None = None, kits_root: Path | None = None, scenes_dir: Path | None = None,
            video: bool = False, gpu: str = "off", lenient: bool = False, slot_dir: str | None = None) -> PreviewResult:
    """Build the job, capture keyframes (+ contact sheet) and optionally a video. Never raises."""
    res = PreviewResult(ok=False)
    t_start = time.perf_counter()
    try:
        film, scenes, assets = load_film_dir(Path(film_path), scenes_dir)
        job = build_job(film, out_dir / "job", kits_root=kits_root or KITS_ROOT, scenes=scenes, assets=assets)
        res.job_dir = str(job)
        res.timings["build_s"] = round(time.perf_counter() - t_start, 3)
        fw, fh = int(film.get("size", [1920, 1080])[0]), int(film.get("size", [1920, 1080])[1])
        w, h = size or (fw // 2, fh // 2)
        times = list(keyframes) if keyframes else keyframes_for(film, per_shot)
        page = "stage.html?lenient=1" if lenient else "stage.html"
        with render_slot(slot_dir):
            if times:
                t0 = time.perf_counter()
                stills, info = asyncio.run(capture_keyframes(job, times, w=w, h=h, gpu=gpu == "on", page=page))
                res.timings["stills_s"] = round(time.perf_counter() - t0, 3)
                res.timings["seek_ms_avg"] = round(sum(s.seek_ms for s in stills) / len(stills), 2)
                res.timings["capture_ms_avg"] = round(sum(s.capture_ms for s in stills) / len(stills), 2)
                for s in stills:
                    p = out_dir / f"kf_{s.t:07.3f}.png"
                    p.write_bytes(s.png)
                    res.stills.append(str(p))
                    res.qa += [{**q, "t": s.t} for q in s.qa]
                res.contact_sheet = str(contact_sheet(stills, out_dir / "contact.png"))
                res.errors, res.cues, res.page_errors = info["errors"], info["cues"], info["page_errors"]
            if video:
                from ..render.workers import RenderSpec, render_video

                t0 = time.perf_counter()
                rv = render_video(RenderSpec(page_dir=job, page=page, out_path=out_dir / "preview.mp4", w=w, h=h,
                                             fps=float(film.get("fps", 30)), gpu=gpu, seed=int(film.get("seed", 0))))
                res.timings["video_s"] = round(time.perf_counter() - t0, 3)
                if not rv.ok:
                    res.error = rv.error
                    return res
                res.video = str(rv.out_path)
                res.page_errors += list(rv.page_errors)
        res.ok = not res.errors
    except JobError as e:
        res.error = e.to_dict()
    except Exception as e:  # noqa: BLE001  # never raise out of the entry point
        from ..render.errors import RenderError

        res.error = e.to_dict() if isinstance(e, RenderError) else {"code": "internal", "message": f"{type(e).__name__}: {e}"}
    res.timings["total_s"] = round(time.perf_counter() - t_start, 3)
    return res


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.film.preview", description="Preview a film (keyframes, contact sheet, video).")
    ap.add_argument("film", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="output dir (default: <film dir>/preview)")
    ap.add_argument("--keyframes", default="", help="comma-separated times in seconds")
    ap.add_argument("--per-shot", type=int, default=1, help="keyframes per shot when --keyframes is not given")
    ap.add_argument("--size", default="", help="capture size WxH (default: half the film size)")
    ap.add_argument("--kits", type=Path, default=None, help="kits root (default: repo kits/)")
    ap.add_argument("--scenes", type=Path, default=None, help="custom scenes dir (default: <film dir>/scenes)")
    ap.add_argument("--video", action="store_true", help="also render preview.mp4 (at --size)")
    ap.add_argument("--gpu", default="off", choices=("auto", "on", "off"))
    ap.add_argument("--lenient", action="store_true", help="keep going past scene/setup errors (collect them all)")
    ap.add_argument("--slot-dir", default=os.environ.get("SHOWREEL_RENDER_SLOT_DIR"))
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    times = [float(x) for x in a.keyframes.split(",") if x.strip()] if a.keyframes else None
    size = tuple(int(v) for v in a.size.lower().split("x")) if a.size else None
    out = a.out or a.film.parent / "preview"
    out.mkdir(parents=True, exist_ok=True)
    r = preview(a.film, out, keyframes=times, per_shot=a.per_shot, size=size, kits_root=a.kits,  # type: ignore[arg-type]
                scenes_dir=a.scenes, video=a.video, gpu=a.gpu, lenient=a.lenient, slot_dir=a.slot_dir)
    if a.json:
        print(json.dumps(r.to_dict(), indent=1))
    else:
        print(f"{'OK' if r.ok else 'FAILED'}  job={r.job_dir}")
        if r.contact_sheet:
            print(f"contact sheet: {r.contact_sheet}")
        if r.video:
            print(f"video: {r.video}")
        for e in r.errors + r.page_errors:
            print(f"error: {e}")
        for q in r.qa:
            print(f"qa t={q['t']:.2f} {q['kind']}: {q['msg']}")
        if r.error:
            print(f"error: {r.error.get('message')}")
            for i in r.error.get("issues", []):
                print(f"  {i['path']}: {i['msg']}")
        print("timings: " + ", ".join(f"{k}={v}" for k, v in r.timings.items()))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
