"""Dev harness for the Director (not used by the plugin).

    python -m showreel_core.director.try --direction "pixel but ..." --media C:/path/car.mp4 \\
        [--cutout C:/path/car_alpha] [--media-desc "a red sports car"] [--name "Red Car"] [--one-liner "..."] \\
        [--feature "..."]* [--digest-file F] [--seconds 45] [--aspect 16:9] [--effort quick|standard|max] \\
        [--job OUT] [--until treatment|film|scenes|all] [--slots DIR] [--library DIR] \\
        [--gpu] [--tts edge] [--render OUT.mp4]
    python -m showreel_core.director.try --revise PARENT_JOB --notes "make the field pinker" --job OUT [--render ...]
    python -m showreel_core.director.try --render-only JOB --render OUT.mp4 [--slots ...]

``--until treatment|film|scenes`` stops early (no browser needed until ``all``); ``scenes`` codes and lints every
custom scene. ``--slots`` holds one of the dev machine's render slot files around each browser launch.
``--tts edge`` speaks narration through edge-tts (Hermes' default provider) like ``text_to_speech`` would.
``--render`` renders the final page at 1080p and mixes music (the film's bed cue sheet), SFX, stings and narration.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..contracts import Product
from .backend import RuntimeRenderer, render_slot
from .catalog import build_catalog, load_beds
from .engine import _film, _realise, _setup, _treatment, revise, run
from .llm import hermes_cli_llm
from .media import probe_asset
from .types import EFFORTS, Brief

# list rates of the dev model (hermes agent/usage_pricing.py), $ per 1M tokens
RATES = {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0}


def _print(**ev: Any) -> None:
    if ev.get("level") == "debug":
        return
    mark = {"warning": "!", "error": "X"}.get(str(ev.get("level")), "-")
    print(f"  {mark} [{ev.get('stage', '')}] {ev.get('note', '')}", flush=True)


def cost_of(calls_dir: Path) -> dict[str, Any]:
    """Tokens and list-rate cost from every ``calls/*.meta.json`` (input tokens include cache reads/writes)."""
    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "calls": 0, "seconds": 0.0}
    for p in sorted(calls_dir.glob("*.meta.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        u = m.get("usage") or {}
        tot["calls"] += 1
        tot["seconds"] += float(m.get("seconds") or 0)
        tot["input"] += int(u.get("input_tokens") or 0)
        tot["output"] += int(u.get("output_tokens") or 0)
        tot["cache_read"] += int(u.get("cache_read_tokens") or 0)
        tot["cache_write"] += int(u.get("cache_write_tokens") or 0)
    fresh = max(0, tot["input"] - tot["cache_read"] - tot["cache_write"])
    usd = (fresh * RATES["input"] + tot["output"] * RATES["output"] + tot["cache_read"] * RATES["cache_read"]
           + tot["cache_write"] * RATES["cache_write"]) / 1e6
    return {**tot, "seconds": round(tot["seconds"], 1), "usd": round(usd, 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.director.try")
    ap.add_argument("--direction", default="")
    ap.add_argument("--media", action="append", default=[])
    ap.add_argument("--cutout", default="")
    ap.add_argument("--media-desc", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--one-liner", default="")
    ap.add_argument("--feature", action="append", default=[])
    ap.add_argument("--url", default="")
    ap.add_argument("--digest-file", default="")
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--aspect", default="16:9", choices=("16:9", "9:16"))
    ap.add_argument("--effort", default="standard", choices=tuple(EFFORTS))
    ap.add_argument("--reasoning", default=None)
    ap.add_argument("--job", default="")
    ap.add_argument("--until", default="all", choices=("treatment", "film", "scenes", "all"))
    ap.add_argument("--slots", default="")
    ap.add_argument("--library", default="")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--tts", default="none", choices=("none", "edge"))
    ap.add_argument("--treatment", default="", help="reuse a saved treatment.json (skips the treatment call)")
    ap.add_argument("--film", default="", help="dir with film.json + plan.json: resume from a scripted v1")
    ap.add_argument("--revise", default="", help="parent job dir to revise with --notes")
    ap.add_argument("--notes", default="")
    ap.add_argument("--render", default="", help="render the result (1080p + audio) to this MP4")
    ap.add_argument("--render-only", default="", help="job dir whose page to render (no model calls)")
    ap.add_argument("--rounds", type=int, default=0, help="override the effort's critique rounds (1 = critique only)")
    args = ap.parse_args(argv)

    lock = (lambda: render_slot(Path(args.slots), who="w3-director")) if args.slots else None
    if args.render_only:
        out = render_job(Path(args.render_only), Path(args.render), slots=Path(args.slots) if args.slots else None)
        print(json.dumps(out, indent=1, default=str))
        return 0 if out.get("ok") else 1
    job = Path(args.job or f"director-job-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    job.mkdir(parents=True, exist_ok=True)
    renderer = RuntimeRenderer(lock=lock, gpu=args.gpu)
    dispatch = None
    if args.tts == "edge":
        from ..llm import edge_tts_dispatch
        dispatch = edge_tts_dispatch()
    llm = hermes_cli_llm(reasoning=args.reasoning)
    lib = Path(args.library).resolve() if args.library else job / "library"
    t0 = time.monotonic()
    if args.revise:
        res = revise(Path(args.revise).resolve(), args.notes, llm=llm, renderer=renderer, effort=args.effort,
                     progress=_print, job_dir=job, library_dir=lib, dispatch=dispatch)
        return _done(res, job, t0, args)
    assets = [probe_asset(m, out_dir=job / "director" / "media", description=args.media_desc) for m in args.media]
    if assets and args.cutout:
        assets[0].cutout = str(Path(args.cutout).resolve())
    product = (Product(name=args.name, one_liner=args.one_liner, features=list(args.feature),
                       urls=[args.url] if args.url else []) if args.name else None)
    digest = Path(args.digest_file).read_text(encoding="utf-8") if args.digest_file else ""
    brief = Brief(direction=args.direction, assets=assets, seconds=args.seconds, aspect=args.aspect,
                  product=product, digest=digest)
    brief.capabilities.gpu = args.gpu
    print(f"job: {job}\nmedia: {[a.to_dict() for a in assets]}", flush=True)
    if args.until == "all" and args.film:
        from .engine import Version, _finish, _produce
        cat = build_catalog(library_dir=lib, assets=assets, capabilities=brief.capabilities)
        r = _setup(brief, llm, renderer, args.effort, _print, None, job, lib, cat)
        if args.rounds:
            r.budget = dataclasses.replace(r.budget, rounds=args.rounds)
        r.dispatch = dispatch
        r.treatment = json.loads(Path(args.treatment).read_text(encoding="utf-8")) if args.treatment else {}
        r.save("treatment.json", r.treatment)
        fd = Path(args.film)
        from .checks import check_film
        chk = check_film({"film": json.loads((fd / "film.json").read_text(encoding="utf-8")),
                          "plan": json.loads((fd / "plan.json").read_text(encoding="utf-8"))},
                         brief, cat, max_custom=r.budget.max_custom)
        for w in chk.errors + chk.warnings:
            print(f"  ! [film] {w}")
        if chk.value is None:
            return 1
        v1 = Version(1, *chk.value)
        return _done(_finish(r, _produce(r, first=v1), True, t0), job, t0, args)
    if args.until == "all":
        res = run(brief, llm=llm, renderer=renderer, effort=args.effort, progress=_print, job_dir=job,
                  library_dir=lib, dispatch=dispatch)
        return _done(res, job, t0, args)
    cat = build_catalog(library_dir=lib, assets=assets, capabilities=brief.capabilities)
    r = _setup(brief, llm, renderer, args.effort, _print, None, job, lib, cat)
    if args.treatment:
        r.treatment = json.loads(Path(args.treatment).read_text(encoding="utf-8"))
        r.save("treatment.json", r.treatment)
    else:
        r.treatment = _treatment(r)
    if not r.treatment or args.until == "treatment":
        _summary(job, t0)
        return 0 if r.treatment else 1
    v = _film(r)
    if v is None or args.until == "film":
        if v is not None:
            r.save("v1/film.json", v.film)
            r.save("v1/plan.json", v.plan)
        _summary(job, t0)
        return 0 if v else 1
    r.save("v1/film.json", v.film)
    r.save("v1/plan.json", v.plan)

    class _NoDryRun(RuntimeRenderer):
        def build(self, *a: Any, **k: Any) -> list[str]:
            return ["--until scenes: no build"]

    r.renderer = _NoDryRun()
    _realise(r, v, code=list(v.customs))
    for name, code in v.scenes.items():
        r.save(f"v1/scenes/{name}.js", code)
    print(f"scenes: { {n: 'ok' for n in v.scenes} | {n: 'fallback:' + k for n, k in v.fallbacks.items()} }")
    _summary(job, t0)
    return 0


def _done(res: Any, job: Path, t0: float, args: argparse.Namespace) -> int:
    print(json.dumps({k: v for k, v in res.to_dict().items() if k not in ("log", "film", "treatment")},
                     indent=1, default=str))
    _summary(job, t0)
    if res.ok and args.render:
        out = render_job(job, Path(args.render), slots=Path(args.slots) if args.slots else None)
        print(json.dumps(out, indent=1, default=str))
    return 0 if res.ok else 1


def _summary(job: Path, t0: float) -> None:
    print(json.dumps({"wall_s": round(time.monotonic() - t0, 1), "cost": cost_of(job / "director" / "calls")},
                     indent=1))


# ------------------------------------------------------------------------------------ dev render + mix

def render_job(job: Path, out: Path, *, slots: Path | None = None, gpu: str = "auto") -> dict[str, Any]:
    """Render ``job/page`` at film size and mix the film's audio (bed cue sheet, SFX, stings, narration)."""
    from ..film.render import render_spec
    from ..render.workers import render_video

    film = json.loads((job / "film.json").read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    silent = out.with_name(out.stem + "-silent.mp4")
    spec = render_spec(job / "page", silent, gpu=gpu, work_dir=job / "render-chunks")
    t0 = time.monotonic()
    if slots is not None:
        with render_slot(slots, who="w3-director-render"):
            res = render_video(spec)
    else:
        res = render_video(spec)
    report: dict[str, Any] = {"render_s": round(time.monotonic() - t0, 1), "ok": bool(getattr(res, "ok", False)),
                              "error": getattr(res, "error", None)}
    if not report["ok"]:
        return report
    report.update(mix_job(job, film, silent, out))
    return report


def mix_job(job: Path, film: dict[str, Any], video: Path, out: Path) -> dict[str, Any]:
    """Music (each bed of the cue sheet fitted to its segment, crossfaded at the joins) + SFX + narration."""
    from .. import pipeline as pl
    dur = float(film["dur"])
    mdir = job / "mix"
    mdir.mkdir(parents=True, exist_ok=True)
    music = dev_music(film, mdir)
    cues = [c for c in film.get("cues") or [] if isinstance(c, dict)]
    cues += [{"t": m["t"], "sfx": m["sting"]} for m in film.get("music") or [] if isinstance(m, dict) and "sting" in m]
    style = next((m["bed"].split("_")[0] for m in film.get("music") or [] if m.get("bed")), "launch")
    sfx, warns = pl._d_place_sfx(cues, dur, style, int(film.get("fps", 30)))
    voices = [v for v in film.get("narration") or [] if v.get("path")]
    res = pl._d_mix(mdir / "mix.wav", dur, music=music, voices=voices, sfx=sfx, work_dir=mdir)
    pl._d_mux(video, Path(getattr(res, "path", mdir / "mix.wav")), out, dur)
    return {"out": str(out), "music": str(music) if music else None, "sfx": len(sfx), "voices": len(voices),
            "sfx_warnings": warns[:4]}


def dev_music(film: dict[str, Any], mdir: Path, xfade: float = 0.6) -> Path | None:
    """Fit every bed segment of ``film.music`` with the audio module and crossfade them (dev stand-in for the
    pipeline's cue-sheet fitting)."""
    import subprocess

    from ..audio.music import fit_bed, pick_bed
    from ..render.ffmpeg import resolve_ffmpeg

    beds = {b.id: b.style for b in load_beds(Path(__file__).resolve().parents[2] / "assets" / "audio" / "beds")}
    segs = [m for m in film.get("music") or [] if isinstance(m, dict) and m.get("bed")]
    if not segs:
        return None
    parts: list[Path] = []
    for i, m in enumerate(segs):
        bed = pick_bed(beds.get(m["bed"], "launch"), 7, m["bed"])
        if bed is None:
            continue
        seg = float(m["t1"]) - float(m["t0"]) + (xfade if i < len(segs) - 1 else 0.0)
        fitted = fit_bed(bed, seg, mdir / f"music_{i}.wav")
        parts.append(Path(fitted.path))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    ff = resolve_ffmpeg().path
    cmd = [ff, "-y", "-v", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    chain, last = [], "[0:a]"
    for k in range(1, len(parts)):
        tag = f"[x{k}]"
        chain.append(f"{last}[{k}:a]acrossfade=d={xfade}:c1=tri:c2=tri{tag}")
        last = tag
    out = mdir / "music.wav"
    cmd += ["-filter_complex", ";".join(chain), "-map", last, "-c:a", "pcm_f32le", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    sys.exit(main())
