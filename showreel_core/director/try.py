"""Dev harness for the Director (not used by the plugin).

    python -m showreel_core.director.try --direction "pixel but ..." --media C:/path/car.mp4 \\
        [--cutout C:/path/car_alpha] [--media-desc "a red sports car"] [--name "Red Car"] [--one-liner "..."] \\
        [--seconds 45] [--aspect 16:9] [--effort quick|standard|max] [--llm hermes-cli] [--job OUT] \\
        [--until treatment|film|scenes|all] [--slots C:/Users/2/showreel-work] [--library DIR]

``--until treatment|film|scenes`` stops early (no browser needed until ``all``); ``scenes`` codes and lints every
custom scene. ``--slots`` holds one of the dev machine's render slot files around each browser launch.
``--llm hermes-cli`` calls the user's default model through ``hermes chat`` (dev route, see llm.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..contracts import Product
from .backend import RuntimeRenderer, render_slot
from .catalog import build_catalog
from .engine import _film, _realise, _setup, _treatment, run
from .llm import hermes_cli_llm
from .media import probe_asset
from .types import EFFORTS, Brief


def _print(**ev: Any) -> None:
    if ev.get("level") == "debug":
        return
    mark = {"warning": "!", "error": "X"}.get(str(ev.get("level")), "-")
    print(f"  {mark} [{ev.get('stage', '')}] {ev.get('note', '')}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.director.try")
    ap.add_argument("--direction", required=True)
    ap.add_argument("--media", action="append", default=[])
    ap.add_argument("--cutout", default="")
    ap.add_argument("--media-desc", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--one-liner", default="")
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--aspect", default="16:9", choices=("16:9", "9:16"))
    ap.add_argument("--effort", default="standard", choices=tuple(EFFORTS))
    ap.add_argument("--llm", default="hermes-cli", choices=("hermes-cli",))
    ap.add_argument("--reasoning", default=None)
    ap.add_argument("--job", default="")
    ap.add_argument("--until", default="all", choices=("treatment", "film", "scenes", "all"))
    ap.add_argument("--slots", default="")
    ap.add_argument("--library", default="")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--treatment", default="", help="reuse a saved treatment.json (skips the treatment call)")
    ap.add_argument("--film", default="", help="dir with film.json + plan.json: resume from a scripted v1")
    args = ap.parse_args(argv)

    job = Path(args.job or f"director-job-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    job.mkdir(parents=True, exist_ok=True)
    assets = [probe_asset(m, out_dir=job / "director" / "media", description=args.media_desc) for m in args.media]
    if assets and args.cutout:
        assets[0].cutout = str(Path(args.cutout).resolve())
    brief = Brief(direction=args.direction, assets=assets, seconds=args.seconds, aspect=args.aspect,
                  product=Product(name=args.name, one_liner=args.one_liner) if args.name else None)
    brief.capabilities.gpu = args.gpu
    lib = Path(args.library).resolve() if args.library else job / "library"
    llm = hermes_cli_llm(reasoning=args.reasoning)
    lock = (lambda: render_slot(Path(args.slots))) if args.slots else None
    renderer = RuntimeRenderer(lock=lock)
    print(f"job: {job}\nmedia: {[a.to_dict() for a in assets]}", flush=True)
    t0 = time.monotonic()
    if args.until == "all" and args.film:
        from .engine import Version, _finish, _produce
        cat = build_catalog(library_dir=lib, assets=assets, capabilities=brief.capabilities)
        r = _setup(brief, llm, renderer, args.effort, _print, None, job, lib, cat)
        r.treatment = json.loads(Path(args.treatment).read_text(encoding="utf-8")) if args.treatment else {}
        r.save("treatment.json", r.treatment)
        fd = Path(args.film)
        v1 = Version(1, json.loads((fd / "film.json").read_text(encoding="utf-8")),
                     json.loads((fd / "plan.json").read_text(encoding="utf-8")))
        res = _finish(r, _produce(r, first=v1), True, t0)
        print(json.dumps({k: v for k, v in res.to_dict().items() if k not in ("log", "film", "treatment")},
                         indent=1, default=str))
        return 0 if res.ok else 1
    if args.until == "all":
        res = run(brief, llm=llm, renderer=renderer, effort=args.effort, progress=_print, job_dir=job,
                  library_dir=lib)
        print(json.dumps({k: v for k, v in res.to_dict().items() if k not in ("log", "film", "treatment")},
                         indent=1, default=str))
        return 0 if res.ok else 1
    cat = build_catalog(library_dir=lib, assets=assets, capabilities=brief.capabilities)
    r = _setup(brief, llm, renderer, args.effort, _print, None, job, lib, cat)
    if args.treatment:
        r.treatment = json.loads(Path(args.treatment).read_text(encoding="utf-8"))
        r.save("treatment.json", r.treatment)
    else:
        r.treatment = _treatment(r)
    if not r.treatment or args.until == "treatment":
        _summary(r, t0)
        return 0 if r.treatment else 1
    v = _film(r)
    if v is None or args.until == "film":
        if v is not None:
            r.save("v1/film.json", v.film)
            r.save("v1/plan.json", v.plan)
        _summary(r, t0)
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
    _summary(r, t0)
    return 0


def _summary(r: Any, t0: float) -> None:
    print(json.dumps({"seconds": round(time.monotonic() - t0, 1), "usage": r.ledger.totals()}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
