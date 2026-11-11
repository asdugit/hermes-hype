"""Renderer selftest: ``python -m showreel_core.render.selftest [--out DIR] [--small] [--json]``.

Builds the built-in ``window.__sr`` test page (animated text, gradient, moving 3D panel, seeded
noise canvas, WebGL, WAAPI, local image, ``@font-face``, ES modules), checks determinism (same t
twice -> identical PNG hash), renders a 6 s 1080p30 video and a 540p15 preview, runs video QA and
prints throughput plus the chosen browser / GPU mode / worker count. Exit code 0 when all pass.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..qa.video import check_video
from .chromium import browser_candidates
from .errors import RenderError
from .ffmpeg import capabilities, resolve_ffmpeg
from .probe import probe_gpu
from .testpage import write_test_page
from .workers import RenderSpec, page_session, render_video


def _determinism(page_dir: Path, page: str, w: int, h: int, gpu: bool) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with page_session(page_dir, page, w=w, h=h, gpu=gpu) as p:
            hashes = []
            for t in (1.5, 3.2, 1.5, 0.1, 1.5):
                await p.seek(t)
                png = await p.capture("png")
                if t == 1.5:
                    hashes.append(hashlib.sha256(png).hexdigest()[:16])
            return {"ok": len(set(hashes)) == 1, "hashes": hashes, "page_errors": p.errors[:5]}
    try:
        return asyncio.run(go())
    except RenderError as e:
        return {"ok": False, "error": e.to_dict()}


def _render(label: str, page_dir: Path, page: str, out: Path, *, w: int, h: int, fps: float, seconds: float,
            gpu: str, workers: int | None, post: str, gpu_cache: Path, quiet: bool) -> dict[str, Any]:
    last = [0.0]

    def progress(done: int, total: int, eta: float | None) -> None:
        now = time.monotonic()
        if not quiet and (now - last[0] > 2 or done == total):
            last[0] = now
            print(f"  [{label}] {done}/{total} frames" + (f", eta {eta:.0f}s" if eta is not None else ""), flush=True)

    spec = RenderSpec(page_dir=page_dir, page=page, out_path=out, w=w, h=h, fps=fps, duration_s=seconds,
                      gpu=gpu, workers=workers, post=post, gpu_cache=gpu_cache, seed=1234)
    res = render_video(spec, progress=progress)
    d: dict[str, Any] = {"render": res.to_dict()}
    if res.ok and res.out_path:
        mids = [seconds * k / 4 for k in (1, 2, 3)]
        qa = check_video(Path(res.out_path), expected_frames=res.frames, expected_duration_s=res.duration_s, fps=fps,
                         scene_times=mids, contact_sheet=out.with_suffix(".contact.png"))
        d["qa"] = qa.to_dict()
        d["ok"] = qa.ok
    else:
        d["ok"] = False
    return d


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(prog="python -m showreel_core.render.selftest", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, help="output directory (default: a temp dir)")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--size", default="1920x1080", help="final size WxH")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--preview-size", default="960x540")
    ap.add_argument("--preview-fps", type=float, default=15.0)
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--gpu", default="auto", choices=("auto", "on", "off"))
    ap.add_argument("--post", default="none")
    ap.add_argument("--small", action="store_true", help="tiny sizes for CI: 640x360@30 2 s + 320x180@15")
    ap.add_argument("--json", action="store_true", help="print the JSON summary only")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    if a.small:
        a.seconds, a.size, a.preview_size = 2.0, "640x360", "320x180"
    w, h = (int(v) for v in a.size.lower().split("x"))
    pw, ph = (int(v) for v in a.preview_size.lower().split("x"))
    out = a.out or Path(tempfile.mkdtemp(prefix="auteur-selftest-"))
    out.mkdir(parents=True, exist_ok=True)
    say = (lambda *x: None) if a.json else (lambda *x: print(*x, flush=True))
    summary: dict[str, Any] = {"out": str(out), "ok": False}
    try:
        ff = resolve_ffmpeg()
        caps = capabilities(ff.path)
        summary["ffmpeg"] = {"path": ff.path, "source": ff.source, "version": caps.version, "encoders": caps.working}
        say(f"ffmpeg : {ff.path} [{ff.source}] {caps.version[:40]} encoders={list(caps.working)}")
        cands = browser_candidates()
        if not cands:
            raise RenderError("no_browser", "no Chromium-based browser found")
        summary["browsers"] = [c.path for c in cands]
        say(f"browser: {cands[0].path} [{cands[0].source}] ({len(cands)} candidate(s))")
        if a.gpu == "auto":
            pr = probe_gpu(cands[0], cache_path=out / "gpu_probe.json")
            summary["gpu_probe"] = pr.to_dict()
            say(f"gpu    : use_gpu={pr.use_gpu} ({pr.reason}; device={pr.gpu_device or '?'}; "
                f"mean_diff={pr.mean_diff}; {pr.seconds}s)")
            gpu_on = pr.use_gpu
        else:
            gpu_on = a.gpu == "on"
        page_dir = out / "page"
        page = write_test_page(page_dir, dur=a.seconds, fps=a.fps)
        det = _determinism(page_dir, page, w, h, gpu_on)
        summary["determinism"] = det
        say(f"determinism: {'PASS' if det.get('ok') else 'FAIL'} {det.get('hashes', det.get('error'))}")
        runs = [("final", w, h, a.fps)] + ([] if a.no_preview else [("preview", pw, ph, a.preview_fps)])
        all_ok = bool(det.get("ok"))
        for label, rw, rh, rfps in runs:
            say(f"render {label}: {rw}x{rh}@{rfps:g} {a.seconds:g}s post={a.post}")
            run_page = write_test_page(page_dir, dur=a.seconds, fps=rfps)
            d = _render(label, page_dir, run_page, out / f"selftest_{label}.mp4", w=rw, h=rh, fps=rfps,
                        seconds=a.seconds, gpu="on" if gpu_on else "off", workers=a.workers, post=a.post,
                        gpu_cache=out / "gpu_probe.json", quiet=a.json)
            summary[label] = d
            r = d["render"]
            if r["ok"]:
                qa = d.get("qa", {})
                say(f"  -> {r['out_path']}\n     frames={r['frames']} workers={r['workers']} gpu={r['gpu']} "
                    f"encoder={r['encoder']} capture_fps={r['render_fps']} wall={r['wall_s']}s "
                    f"browser={r['browser_version']}\n     qa ok={qa.get('ok')} decoded={qa.get('frames')} "
                    f"dur={qa.get('duration_s')} color='{qa.get('color')}' frame0_luma={qa.get('frame0_luma')} "
                    f"issues={qa.get('issues')}")
            else:
                say(f"  -> FAILED: {r['error']}")
            for wmsg in r.get("warnings", []):
                say(f"     warning: {wmsg}")
            all_ok = all_ok and bool(d["ok"])
        summary["ok"] = all_ok
    except RenderError as e:
        summary["error"] = e.to_dict()
        say(f"FAILED: {e.to_dict()}")
    (out / "selftest.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    if a.json:
        print(json.dumps(summary, default=str))
    else:
        say(f"selftest: {'PASS' if summary['ok'] else 'FAIL'}  (summary: {out / 'selftest.json'})")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
