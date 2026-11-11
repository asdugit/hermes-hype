"""Render a hand-built (or Director) film.json that may contain ``blender:`` shots, picture + audio:

    python -m showreel_core.blender.render_film FILM.json --out OUT.mp4 [--tier preview|final|max]
        [--aspect 16:9|9:16|1:1] [--job DIR] [--size WxH] [--gpu auto|on|off] [--style STYLE] [--no-audio]
        [--blender PATH] [--keyframes 0,2.5] [--json]

1. Blender pass (:func:`showreel_core.blender.film.render_film_shots`): ``blender:`` shots -> frames -> kit:frames/play.
2. Browser pass: ``film.page.build_job`` + ``render.workers.render_video`` with ``finish=post`` (``film.render.render_spec``).
3. Audio: the page's merged cues (explicit + scene + transition + Blender scene cues) ->
   ``audio.film_audio.render_film_audio`` (cue-sheet music + SFX + narration) -> ``render.ffmpeg.mux``.
Assets in film.json may carry ``"src"`` (relative to the film file), including 3D models (``"type": "model"``) that
only Blender shots use. Set ``AUTEUR_RENDER_SLOT_DIR`` to share Chromium render slots with other jobs.
``--keyframes`` renders only the Blender frames those film times show and writes PNG stills instead of a video.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import film as bfilm
from .locate import BlenderMissing, locate

ASPECT_SIZE = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


@dataclass
class FilmRender:
    ok: bool
    out: str = ""
    stills: list[str] = field(default_factory=list)
    job_dir: str = ""
    blender: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def with_aspect(film: dict[str, Any], aspect: str | None) -> dict[str, Any]:
    """Film resized to ``aspect`` at its own short side (shots and kits adapt to ctx.w/h)."""
    if not aspect:
        return film
    if aspect not in ASPECT_SIZE:
        raise ValueError(f"aspect must be one of {', '.join(ASPECT_SIZE)}")
    w, h = film.get("size") or [1920, 1080]
    short = min(int(w), int(h))
    aw, ah = ASPECT_SIZE[aspect]
    s = short / min(aw, ah)
    return {**film, "size": [int(round(aw * s / 2) * 2), int(round(ah * s / 2) * 2)]}


def render_film(film_path: Path, out: Path, *, tier: str = "preview", aspect: str | None = None,
                job_dir: Path | None = None, size: tuple[int, int] | None = None, gpu: str = "auto",
                style: str | None = None, audio: bool = True, blender: str | None = None,
                keyframes: Sequence[float] | None = None, progress: Callable[[dict[str, Any]], None] | None = None,
                cancel: Any = None, lock: Callable[[], Any] | None = None, min_free_gb: float = 0.0) -> FilmRender:
    """Blender pass -> browser pass -> audio -> mux. Never raises."""
    from ..film.page import JobError, build_job
    from ..film.preview import capture_keyframes, load_film_dir, render_slot

    res = FilmRender(ok=False)
    t0 = time.perf_counter()
    try:
        film, scenes, specs = load_film_dir(Path(film_path))
        film = with_aspect(film, aspect)
        job = Path(job_dir) if job_dir else out.parent / f"{out.stem}_job"
        job.mkdir(parents=True, exist_ok=True)
        res.job_dir = str(job)
        found = None
        if bfilm.blender_shots(film):
            found = locate(blender)
            if isinstance(found, BlenderMissing):
                res.error = found.message
                return res
        bp = bfilm.render_film_shots(film, job, blender=found, tier=tier, assets=specs, scenes=scenes,
                                     progress=progress, cancel=cancel, times=keyframes, lock=lock,
                                     min_free_gb=min_free_gb)
        res.blender = bp.to_dict()
        res.timings["blender_s"] = bp.elapsed_s
        res.warnings += bp.warnings
        if not bp.ok:
            res.error = bp.message or "; ".join(bp.errors)
            return res
        film2 = bp.film
        build_job(film2, job, scenes=scenes, assets={**bp.browser_assets, **bp.manifest})
        fw, fh = (int(v) for v in film2.get("size") or (1920, 1080))
        w, h = size or (fw, fh)
        slot = os.environ.get("AUTEUR_RENDER_SLOT_DIR")
        t1 = time.perf_counter()
        if keyframes:
            with render_slot(slot):
                stills, info = asyncio.run(capture_keyframes(job, list(keyframes), w=w, h=h, gpu=gpu == "on"))
            out.parent.mkdir(parents=True, exist_ok=True)
            for s in stills:
                p = out.parent / f"{out.stem}_kf_{s.t:07.3f}.png"
                p.write_bytes(s.png)
                res.stills.append(str(p))
            res.warnings += [str(e) for e in info.get("errors") or []]
            res.timings["stills_s"] = round(time.perf_counter() - t1, 2)
            res.ok = not info.get("errors")
            res.error = "; ".join(map(str, info.get("errors") or []))[:500]
            return res
        from ..film.render import render_spec
        from ..render.workers import render_video

        picture = job / "picture.mp4"
        with render_slot(slot):
            cues_probe = asyncio.run(capture_keyframes(job, [0.0], w=320, h=max(2, int(320 * h / w) // 2 * 2)))[1]
            spec = _film_post(render_spec(job, picture, size=(w, h), gpu=gpu, finish="post"), job)
            rv = render_video(spec)
        res.timings["picture_s"] = round(time.perf_counter() - t1, 2)
        if not rv.ok:
            res.error = f"browser render failed: {rv.error}"
            return res
        out.parent.mkdir(parents=True, exist_ok=True)
        if not audio:
            shutil.copyfile(picture, out)
        else:
            from ..audio.film_audio import render_film_audio
            from ..render.ffmpeg import mux, resolve_ffmpeg

            t2 = time.perf_counter()
            meta = film2.get("meta") or {}
            fa = render_film_audio(film2, job / "audio.wav", style=style or meta.get("style"),
                                   seed=int(film2.get("seed") or 7), fps=film2.get("fps", 30),
                                   cues=cues_probe.get("cues") or film2.get("cues") or [], work_dir=job / "audio_work")
            res.warnings += [f"audio: {w}" for w in (fa.warnings or [])][:12]
            if fa.ok and fa.path:
                mux(resolve_ffmpeg().path, picture, Path(fa.path), out, duration_s=float(film2["dur"]))
            else:
                shutil.copyfile(picture, out)
                res.warnings.append(f"delivered without audio ({fa.error})")
            res.timings["audio_s"] = round(time.perf_counter() - t2, 2)
        res.out = str(out)
        res.ok = True
    except JobError as exc:
        res.error = f"film job: {exc}"
    except Exception as exc:  # noqa: BLE001  # never raise out of the entry point
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        res.timings["total_s"] = round(time.perf_counter() - t0, 2)
    return res


def _print_progress(ev: dict[str, Any]) -> None:
    if ev.get("message"):
        print(ev["message"], file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.blender.render_film", description=__doc__.split("\n")[0])
    ap.add_argument("film", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tier", choices=["preview", "final", "max"], default="preview")
    ap.add_argument("--aspect", choices=list(ASPECT_SIZE))
    ap.add_argument("--job", type=Path)
    ap.add_argument("--size")
    ap.add_argument("--gpu", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--style")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--blender")
    ap.add_argument("--keyframes")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    size = tuple(int(x) for x in a.size.lower().split("x")) if a.size else None
    kf = [float(x) for x in a.keyframes.split(",")] if a.keyframes else None
    r = render_film(a.film, a.out, tier=a.tier, aspect=a.aspect, job_dir=a.job, size=size, gpu=a.gpu, style=a.style,
                    audio=not a.no_audio, blender=a.blender, keyframes=kf, progress=_print_progress)
    if a.json:
        print(json.dumps(r.to_dict(), indent=1, default=str))
    else:
        print(("OK " + (r.out or ", ".join(r.stills))) if r.ok else f"FAILED: {r.error}")
        for w in r.warnings[:10]:
            print("  warning:", w)
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


def _film_post(spec: Any, job: Path) -> Any:
    """The film's own ``render.post`` chain (a style kit's CRT, the Director's mood grade) on top of the finish
    chain, like the pipeline's ``post_plan`` for browser-only films (Blender films used to drop it)."""
    import dataclasses as dc
    try:
        film = json.loads((Path(job) / "film.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return spec
    render = film.get("render") if isinstance(film.get("render"), dict) else {}
    extra = [c for c in str(render.get("post") or "").split("+") if c and c != "none"]
    if not extra:
        return spec
    chains = [c for c in str(getattr(spec, "post", "") or "none").split("+") if c and c != "none"]
    params = dict(getattr(spec, "post_params", None) or {})
    chains = [*[c for c in extra if c not in chains], *chains]
    for k, v in (render.get("post_params") or {}).items():
        params.setdefault(k, v)
    try:
        return dc.replace(spec, post="+".join(chains), post_params=params)
    except (TypeError, ValueError):
        return spec
