"""Blender pass of a film.json (BLENDER.md "film.json integration").

``render_film_shots(film, job_dir, ...)`` renders every ``"scene": "blender:<kit>/<scene>"`` shot with the user's
Blender into ``job_dir/assets/bl_<shot_id>/000001.jpg ...`` (film fps, the shot span + transition handles), adds
``frames`` manifest entries and returns a NEW film where each such shot is
``{"scene": "kit:frames/play", "params": {"asset": "bl_<id>", "offset": <pre handle s>, "fit": "cover"}}``; scene cues
are merged into the film cues. The browser pass then renders transitions/overlays/captions/finish unchanged.

* Cache: frames render into ``cache_dir/<content hash>/`` (scene module + every blender_kits/lib file + params +
  referenced assets + handoff still + tier/res/fps/frames/handles/seed + Blender version), then are hard-linked
  (copy fallback) into the job; an unchanged shot never re-renders, an interrupted one resumes.
* Handoff stills: a shot with ``params.from_shot`` gets the last frame of that shot as ``handoff.still`` (from its
  Blender frames, or captured from the browser film via the existing preview machinery).
* ETA: a 3-frame benchmark of the first uncached shot (into its cache dir, so the frames are reused) ->
  "Blender shots: ~9 min on your GPU" before the long render; live ETA while rendering.
* Keyframe mode: ``times=[film seconds]`` renders only the frames those times show (+ frame 1 for the poster).
Never raises: problems come back in :class:`BlenderPass` (``ok``, ``errors``, ``missing``, ``message``).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import os
import re
import shutil
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import runner
from .locate import BlenderFound, BlenderMissing, locate

PREFIX = "blender:"
FRAMES_SCENE = "kit:frames/play"
SCENE_RE = re.compile(r"^blender:([a-z0-9_-]+)/([a-z0-9_.-]+)$", re.IGNORECASE)
MODEL_EXT = {".glb", ".gltf", ".blend", ".fbx", ".obj", ".usdz", ".usd", ".usda", ".usdc", ".stl", ".ply"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".exr", ".hdr"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
PREVIEW_LONG_SIDE = 960

ProgressCB = Callable[[dict[str, Any]], None]
HandoffFn = Callable[[dict[str, Any], str, float, tuple[int, int], Path], Path | None]


# ------------------------------------------------------------------------------------------- scene ids / files

def is_blender_shot(shot: Any) -> bool:
    return isinstance(shot, Mapping) and str(shot.get("scene") or "").startswith(PREFIX)


def blender_shots(film: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [s for s in film.get("shots") or [] if is_blender_shot(s)]


def scene_file(scene_id: str, kit_root: Path | None = None) -> Path:
    """``blender:<kit>/<scene>`` -> ``<kit_root>/<kit>/<scene>.py`` (ValueError on a malformed id)."""
    m = SCENE_RE.match(str(scene_id))
    if not m or m.group(1) == "lib" or ".." in m.group(2):
        raise ValueError(f"bad Blender scene id {scene_id!r} (expected 'blender:<kit>/<scene>')")
    return Path(kit_root or runner.KIT_ROOT) / m.group(1) / f"{m.group(2)}.py"


def available_scenes(kit_root: Path | None = None, *, include_test: bool = False) -> list[str]:
    """Every ``blender:<kit>/<scene>`` id under ``kit_root`` (kits ``lib`` and private ``_x`` files excluded)."""
    root = Path(kit_root or runner.KIT_ROOT)
    out: list[str] = []
    for kit in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        if kit.name in ("lib", "__pycache__") or (kit.name.startswith("_") and not include_test):
            continue
        out += [f"{PREFIX}{kit.name}/{f.stem}" for f in sorted(kit.glob("*.py")) if not f.name.startswith("_")]
    return out


def scene_info(path: Path) -> dict[str, Any]:
    """``{"params": PARAMS, "describe": DESCRIBE}`` by a static parse (no bpy needed; Director catalog)."""
    info: dict[str, Any] = {"params": {}, "describe": ""}
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("PARAMS", "DESCRIBE"):
                try:
                    info["params" if name == "PARAMS" else "describe"] = ast.literal_eval(node.value)
                except ValueError:
                    info.setdefault("warnings", []).append(f"{name} is not a literal")
    return info


# ------------------------------------------------------------------------------------------- planning helpers

def handles_for(film: Mapping[str, Any], shot: Mapping[str, Any]) -> tuple[float, float]:
    """Seconds needed before t0 / after t1 by transitions whose window reaches outside the shot."""
    t0, t1 = float(shot["t0"]), float(shot["t1"])
    pre = post = 0.0
    for tr in film.get("transitions") or []:
        if not isinstance(tr, Mapping) or "t" not in tr:
            continue
        a, b = float(tr["t"]), float(tr["t"]) + float(tr.get("dur") or 0.0)
        if tr.get("to") == shot.get("id") and a < t0:
            pre = max(pre, t0 - a)
        if tr.get("from") == shot.get("id") and b > t1:
            post = max(post, b - t1)
    return round(pre, 4), round(post, 4)


def render_res(film_size: Sequence[int], shot_res: Sequence[int] | None, tier: str) -> tuple[int, int]:
    """Final/max: the shot ``res`` or the film size. Preview: that, scaled to <= 960 px on the long side (even)."""
    w, h = (int(shot_res[0]), int(shot_res[1])) if shot_res else (int(film_size[0]), int(film_size[1]))
    if tier == "preview":
        s = min(1.0, PREVIEW_LONG_SIDE / max(w, h))
        w, h = max(2, int(round(w * s / 2)) * 2), max(2, int(round(h * s / 2)) * 2)
    return w, h


def blender_asset(name: str, spec: Mapping[str, Any], job_dir: Path | None = None) -> dict[str, Any] | None:
    """A job.json asset ``{kind, path, frames_dir?, fps?, poster?, cutout?}`` from a film asset spec (source
    ``src`` or a prepared manifest entry inside ``job_dir``); None when the media is not on disk."""
    src = spec.get("src") or spec.get("path")
    if spec.get("pattern") and job_dir is not None:
        frames_dir = (Path(job_dir) / str(spec["pattern"])).parent
        out = {"kind": "frames", "path": str(frames_dir), "frames_dir": str(frames_dir),
               "pattern": Path(str(spec["pattern"])).name, "fps": spec.get("fps"), "count": spec.get("count")}
        if spec.get("poster"):
            out["poster"] = str(Path(job_dir) / str(spec["poster"]))
        return out
    if not src:
        return None
    p = Path(str(src))
    if not p.is_absolute() and job_dir is not None:
        p = Path(job_dir) / p
    if not p.exists():
        return None
    typ = str(spec.get("type") or "")
    ext = p.suffix.lower()
    if typ == "model" or ext in MODEL_EXT:
        kind = "model"
    elif p.is_dir() or typ == "frames" and p.is_dir():
        kind = "frames"
    elif ext in VIDEO_EXT or typ == "video":
        kind = "video"
    else:
        kind = "image"
    out = {"kind": kind, "path": str(p.resolve())}
    if kind == "frames":
        out["frames_dir"] = str(p.resolve())
    if spec.get("fps"):
        out["fps"] = spec["fps"]
    cut = spec.get("cutout")
    if isinstance(cut, (str, Path)) or isinstance(cut, Mapping) and cut.get("src"):
        cp = Path(str(cut if not isinstance(cut, Mapping) else cut["src"]))
        cp = cp if cp.is_absolute() or job_dir is None else Path(job_dir) / cp
        if cp.exists():
            out["cutout"] = str(cp.resolve())
    return out


def _strings(x: Any) -> set[str]:
    if isinstance(x, str):
        return {x}
    if isinstance(x, Mapping):
        return set().union(*(_strings(v) for v in x.values())) if x else set()
    if isinstance(x, (list, tuple)):
        return set().union(*(_strings(v) for v in x)) if x else set()
    return set()


def _file_digest(p: Path, h: Any, *, content: bool) -> None:
    try:
        st = p.stat()
    except OSError:
        h.update(f"missing:{p}".encode())
        return
    if content and p.is_file() and st.st_size < 64 * 2 ** 20:
        h.update(p.read_bytes())
    else:
        h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())


def shot_hash(job: Mapping[str, Any], *, blender_version: str = "") -> str:
    """Content hash deciding whether a shot's frames can be reused."""
    h = hashlib.sha256()
    scene = Path(job["scene"])
    kit_root = Path(job["kit_root"])
    h.update(b"sr-blender-v1")
    for p in [scene, *sorted((kit_root / "lib").glob("*.py")), *sorted(p for p in scene.parent.glob("*.py") if p != scene)]:
        h.update(str(p.name).encode())
        _file_digest(p, h, content=True)
    for name, a in sorted((job.get("assets") or {}).items()):
        h.update(name.encode())
        h.update(json.dumps({k: v for k, v in a.items() if k not in ("path", "frames_dir", "poster", "cutout")},
                            sort_keys=True).encode())
        for key in ("path", "cutout", "poster"):
            if a.get(key):
                pth = Path(a[key])
                if pth.is_dir():
                    files = sorted(pth.iterdir())
                    h.update(f"dir:{len(files)}".encode())
                    for f in files[:: max(1, len(files) // 16)]:
                        _file_digest(f, h, content=False)
                else:
                    _file_digest(pth, h, content=False)
    if job.get("handoff") and job["handoff"].get("still"):
        _file_digest(Path(job["handoff"]["still"]), h, content=True)
    keys = {k: job.get(k) for k in ("params", "seed", "fps", "res", "aspect", "dur", "frame_count", "handles", "tier",
                                    "alpha", "product", "out_ext", "version")}
    h.update(json.dumps(keys, sort_keys=True, default=str).encode())
    h.update(blender_version.encode())
    return h.hexdigest()[:20]


def _shot_seed(film: Mapping[str, Any], shot: Mapping[str, Any]) -> int:
    if shot.get("seed") is not None:
        return int(shot["seed"])
    return (int(film.get("seed") or 1) * 1000003 + zlib.crc32(str(shot.get("id")).encode("utf-8"))) % (2 ** 31)


def frames_for_times(shot: Mapping[str, Any], times: Sequence[float], fps: int, pre: float, count: int) -> list[int]:
    """Rendered frame numbers the browser will show at film ``times`` (same rounding as kit:frames/play)."""
    out = {1}
    t0 = float(shot["t0"])
    for t in times:
        i = math.floor((float(t) - t0 + pre) * fps + 0.5 + 1e-6)
        if 0 <= i < count:
            out.add(i + 1)
    return sorted(out)


def _materialize(src_dir: Path, dst_dir: Path, ext: str) -> int:
    """Hard-link (copy fallback) ``src_dir/*.ext`` frames into a fresh ``dst_dir``; returns the count."""
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    n = 0
    for f in sorted(src_dir.glob(f"[0-9][0-9][0-9][0-9][0-9][0-9].{ext}")):
        target = dst_dir / f.name
        try:
            os.link(f, target)
        except OSError:
            shutil.copy2(f, target)
        n += 1
    return n


# ------------------------------------------------------------------------------------------- result

@dataclass
class BlenderPass:
    ok: bool
    film: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, dict[str, Any]] = field(default_factory=dict)       # bl_<id> -> frames manifest entry
    browser_assets: dict[str, Any] = field(default_factory=dict)            # input specs minus model-only assets
    shots: list[dict[str, Any]] = field(default_factory=list)              # per-shot report
    cues_added: list[dict[str, Any]] = field(default_factory=list)
    eta_s: float | None = None
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: dict[str, Any] | None = None                                    # BlenderMissing.to_dict()
    cancelled: bool = False
    message: str = ""                                                         # one user-facing line

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("film", None)
        return d


@dataclass
class _Plan:
    shot: dict[str, Any]
    sid: str
    scene: Path
    job: dict[str, Any]
    cache: Path
    asset: str
    pre: float
    post: float
    from_shot: str | None = None
    report: dict[str, Any] = field(default_factory=dict)


def _emit(progress: ProgressCB | None, **kw: Any) -> None:
    if progress:
        try:
            progress({"stage": "blender", **kw})
        except Exception:   # a broken progress sink must never break the render
            return


def progress_message(shot_k: int, shots: int, frame: int, frames: int, eta_s: float | None) -> str:
    """'Blender: shot k/n, frame f/N, ETA ~m' (the job pane line)."""
    eta = f", ETA {runner.human_eta(eta_s)}" if eta_s is not None else ""
    return f"Blender: shot {shot_k}/{shots}, frame {frame}/{frames}{eta}"


def _product_name(film: Mapping[str, Any], shot: Mapping[str, Any], assets: Mapping[str, dict[str, Any]]) -> str | None:
    p = (shot.get("params") or {}).get("product")
    if isinstance(p, str) and p in assets:
        return p
    meta_p = (film.get("meta") or {}).get("product_asset")
    if isinstance(meta_p, str) and meta_p in assets:
        return meta_p
    models = [n for n, a in assets.items() if a.get("kind") == "model"]
    return models[0] if models else None


# ------------------------------------------------------------------------------------------- main entry

def render_film_shots(film: Mapping[str, Any], job_dir: Path | str, *, blender: BlenderFound | Path | str | None = None,
                      config_path: str | None = None, tier: str = "preview", assets: Mapping[str, Any] | None = None,
                      progress: ProgressCB | None = None, cancel: runner.Cancel = None,
                      kit_root: Path | None = None, cache_dir: Path | None = None, times: Sequence[float] | None = None,
                      benchmark: bool = True, handoff: HandoffFn | None = None,
                      lock: Callable[[], Any] | None = None, min_free_gb: float = 0.0,
                      scenes: Mapping[str, Any] | None = None,
                      command: Callable[[Path], list[str]] | None = None) -> BlenderPass:
    """Blender pass (see module doc). ``assets`` = the film's asset specs (``{"src": ...}``) and/or prepared
    manifest entries (resolved against ``job_dir``); ``scenes`` = the film's custom scene sources (only needed to
    capture handoff stills from custom browser shots). ``command(job_path)`` overrides the Blender command line
    (tests: fake Blender). Never raises."""
    t_start = time.monotonic()
    job_dir = Path(job_dir).resolve()
    out = BlenderPass(ok=False, film=copy.deepcopy(dict(film)))
    specs = dict(assets or {})
    film_assets = dict(film.get("assets") or {})
    model_names = {n for n, a in {**film_assets, **specs}.items()
                   if isinstance(a, Mapping) and (a.get("type") == "model"
                                                  or Path(str(a.get("src") or "")).suffix.lower() in MODEL_EXT)}
    out.browser_assets = {n: s for n, s in specs.items() if n not in model_names}
    out.film["assets"] = {n: a for n, a in film_assets.items() if n not in model_names}
    shots = blender_shots(film)
    if not shots:
        out.ok = True
        return out
    try:
        return _render(film, job_dir, out, shots, specs, model_names, blender=blender, config_path=config_path,
                       tier=tier, progress=progress, cancel=cancel, kit_root=Path(kit_root or runner.KIT_ROOT),
                       cache_dir=Path(cache_dir).resolve() if cache_dir else job_dir / "_blender", times=times,
                       benchmark=benchmark, handoff=handoff, lock=lock, min_free_gb=min_free_gb, command=command,
                       scenes=scenes, t_start=t_start)
    except Exception as exc:  # noqa: BLE001  # never raise out of the entry point
        out.ok = False
        out.errors.append(f"Blender pass failed: {type(exc).__name__}: {exc}")
        out.message = out.errors[-1]
        out.elapsed_s = round(time.monotonic() - t_start, 2)
        return out


def _render(film: Mapping[str, Any], job_dir: Path, out: BlenderPass, shots: list[dict[str, Any]],
            specs: dict[str, Any], model_names: set[str], *, blender: Any, config_path: str | None, tier: str,
            progress: ProgressCB | None, cancel: runner.Cancel, kit_root: Path, cache_dir: Path,
            times: Sequence[float] | None, benchmark: bool, handoff: HandoffFn | None, lock: Any,
            min_free_gb: float, command: Callable[[Path], list[str]] | None, scenes: Mapping[str, Any] | None,
            t_start: float) -> BlenderPass:
    if tier not in runner.TIERS:
        out.errors.append(f"unknown Blender tier {tier!r}")
        return out
    # 1. Blender itself
    if blender is None:
        found = locate(config_path)
        if isinstance(found, BlenderMissing):
            out.missing = found.to_dict()
            out.message = found.message
            out.errors.append(found.message)
            return out
        blender = found
    version = blender.version_string if isinstance(blender, BlenderFound) else ""
    _emit(progress, phase="locate", message=f"Blender {version or str(blender)}", eta_s=None)

    # 2. plan every shot
    fps = int(film.get("fps") or 30)
    size = film.get("size") or [1920, 1080]
    all_assets: dict[str, dict[str, Any]] = {}
    for name, spec in {**{n: a for n, a in (film.get("assets") or {}).items() if isinstance(a, Mapping)},
                       **specs}.items():
        a = blender_asset(name, spec, job_dir) if isinstance(spec, Mapping) else None
        if a:
            all_assets[name] = a
    plans: list[_Plan] = []
    for shot in shots:
        sid = str(shot.get("id"))
        try:
            scene = scene_file(str(shot["scene"]), kit_root)
        except ValueError as exc:
            out.errors.append(f"shot {sid}: {exc}")
            continue
        if not scene.is_file():
            known = ", ".join(available_scenes(kit_root)) or "none installed"
            out.errors.append(f"shot {sid}: Blender scene {shot['scene']} not found ({scene}); available: {known}")
            continue
        params = dict(shot.get("params") or {})
        refs = _strings(params)
        product = _product_name(film, shot, all_assets)
        used = {n: a for n, a in all_assets.items() if n in refs or n == product}
        pre, post = handles_for(film, shot)
        res = render_res(size, shot.get("res"), tier)
        alpha = bool(params.get("_alpha"))
        job = runner.make_job(scene, cache_dir / "pending", dur=float(shot["t1"]) - float(shot["t0"]), fps=fps,
                              res=res, params=params, seed=_shot_seed(film, shot), tier=tier, alpha=alpha,
                              assets=used, product=product, handles=(pre, post), kit_root=kit_root)
        plans.append(_Plan(shot=shot, sid=sid, scene=scene, job=job, cache=cache_dir, asset=f"bl_{sid}"[:48],
                           pre=pre, post=post, from_shot=params.get("from_shot") or None))
    if out.errors:
        out.message = out.errors[0]
        return out
    order = {p.sid: k for k, p in enumerate(plans)}
    all_ids = [str(s.get("id")) for s in film.get("shots") or []]
    for p in plans:
        if p.from_shot and p.from_shot not in all_ids:
            out.errors.append(f"shot {p.sid}: from_shot {p.from_shot!r} is not a shot of this film")
        elif p.from_shot in order and order[p.from_shot] >= order[p.sid]:
            out.errors.append(f"shot {p.sid}: from_shot {p.from_shot!r} must come before it")
    if out.errors:
        out.message = out.errors[0]
        return out

    # 3. handoff stills from browser shots (captured before any Blender work; Blender sources come later)
    still_dir = cache_dir / "handoff"
    for p in plans:
        if p.from_shot and p.from_shot not in order:
            src = next(s for s in film.get("shots") or [] if str(s.get("id")) == p.from_shot)
            t = float(src["t1"]) - 0.5 / fps
            target = still_dir / f"{p.from_shot}.png"
            try:
                if handoff is not None:
                    still = handoff(dict(film), p.from_shot, t, tuple(p.job["res"]), target)
                else:
                    still = browser_handoff(dict(film), p.from_shot, t, tuple(p.job["res"]), target,
                                            assets=out.browser_assets, scenes=scenes)
            except Exception as exc:  # noqa: BLE001  # a failed capture degrades the transition, not the film
                out.warnings.append(f"shot {p.sid}: handoff capture from {p.from_shot} failed ({exc})")
                still = None
            if still is None or not Path(still).is_file():
                out.warnings.append(f"shot {p.sid}: no handoff still from {p.from_shot} (scene gets none)")
            else:
                p.job["handoff"] = {"from_shot": p.from_shot, "still": str(Path(still).resolve())}

    # 4. hashes, frames to render, cache state
    def finalize(p: _Plan) -> None:
        h = shot_hash(p.job, blender_version=version)
        p.cache = cache_dir / h
        for key in ("out_dir",):
            p.job[key] = str(p.cache)
        p.job["cues_out"] = str(p.cache / "cues.json")
        p.job["stats_out"] = str(p.cache / "stats.json")
        if times is not None:
            p.job["frames"] = frames_for_times(p.shot, times, fps, p.pre, int(p.job["frame_count"]))
        p.report = {"id": p.sid, "scene": p.shot["scene"], "hash": h, "res": p.job["res"],
                    "frames": len(runner.requested_frames(p.job)), "frame_count": p.job["frame_count"],
                    "handles": [p.pre, p.post]}

    def remaining(p: _Plan) -> list[int]:
        exp = (int(p.job["res"][0]), int(p.job["res"][1]))
        return [f for f in runner.requested_frames(p.job) if not runner.verify_frame(runner.frame_path(p.job, f),
                                                                                       expect=exp).ok]

    for p in plans:      # shots handed off from an earlier Blender shot are finalized once that shot is rendered
        if not (p.from_shot and p.from_shot in order):
            finalize(p)

    # 5. benchmark -> ETA (the frames land in the shot's cache dir and are reused)
    per_frame: float | None = None
    bench_px: int | None = None
    build_s = 0.0
    first = next((p for p in plans if p.report and remaining(p)), None)
    if benchmark and first is not None:
        _emit(progress, phase="benchmark", message="Blender: timing 3 frames for an estimate", eta_s=None)
        bench_job = dict(first.job)
        bench_job["frames"] = [f for f in runner.bench_frames(int(first.job["frame_count"]))
                               if f in set(runner.requested_frames(first.job))] or runner.requested_frames(first.job)[:1]
        r = runner.run_job(bench_job, blender, cancel=cancel, lock=lock, min_free_gb=min_free_gb,
                           command=command(Path(first.job["out_dir"]) / "job.json") if command else None)
        if r.cancelled:
            return _cancelled(out, t_start)
        if not r.ok:
            return _fail(out, first, r, t_start)
        fs = [float(x) for x in r.stats.get("frame_s") or []]
        per_frame = (sum(fs[1:]) / len(fs[1:])) if len(fs) > 1 else (fs[0] if fs else r.mean_frame_s or 0.0)
        build_s = float(r.build_s or 0.0) + (max(0.0, fs[0] - per_frame) if fs else 0.0)
        bench_px = int(first.job["res"][0]) * int(first.job["res"][1])
    eta = None
    if per_frame is not None:
        eta = 0.0
        for p in plans:
            n = len(remaining(p)) if p.report else len(runner.requested_frames(p.job))
            if n:
                eta += runner.estimate_s(build_s, per_frame, n, pixels=int(p.job["res"][0]) * int(p.job["res"][1]),
                                         bench_pixels=bench_px)
        out.eta_s = round(eta, 1)
        _emit(progress, phase="eta", eta_s=eta, message=f"Blender shots: {runner.human_eta(eta)} on your GPU")

    # 6. render shots in order
    ext = "png"
    rendered_by_id: dict[str, _Plan] = {}
    for k, p in enumerate(plans, 1):
        if not p.report:          # handoff from an earlier Blender shot: its last frame is on disk now
            src = rendered_by_id.get(str(p.from_shot))
            if src is not None:
                last = runner.frame_path(src.job, int(src.job["frame_count"]))
                if not last.is_file():
                    cands = sorted(runner.iter_existing(src.job))
                    last = cands[-1] if cands else last
                p.job["handoff"] = {"from_shot": p.from_shot, "still": str(last.resolve())}
            finalize(p)
        todo = remaining(p)
        total = len(runner.requested_frames(p.job))
        p.report["cached"] = not todo
        t_shot = time.monotonic()
        if todo:
            done_before = total - len(todo)

            def on(ev: dict[str, Any], p: _Plan = p, k: int = k, total: int = total, base: int = done_before) -> None:
                if ev.get("phase") in ("frame", "build"):
                    done = base + int(ev.get("done") or 0)
                    eta_now = ev.get("eta_s")
                    rest = sum(len(runner.requested_frames(q.job)) for q in plans[k:])
                    if per_frame is not None and eta_now is not None:
                        eta_now = float(eta_now) + per_frame * rest + build_s * (len(plans) - k)
                    _emit(progress, phase="frame", shot=k, shots=len(plans), frame=done, frames=total, eta_s=eta_now,
                          message=progress_message(k, len(plans), done, total, eta_now))

            _emit(progress, phase="shot", shot=k, shots=len(plans), frame=done_before, frames=total, eta_s=None,
                  message=progress_message(k, len(plans), done_before, total, None))
            r = runner.run_job(p.job, blender, progress=on, cancel=cancel, lock=lock, min_free_gb=min_free_gb,
                               command=command(Path(p.job["out_dir"]) / "job.json") if command else None)
            if r.cancelled:
                return _cancelled(out, t_start)
            if not r.ok:
                return _fail(out, p, r, t_start)
            p.report.update({"render_s": round(time.monotonic() - t_shot, 2), "build_s": r.build_s,
                             "mean_frame_s": r.mean_frame_s, "peak_rss_mb": r.peak_rss_mb,
                             "blank_frames": r.blank[:20]})
            cues = r.cues
        else:
            cues = _read_json_list(Path(p.job["cues_out"]))
        ext = str(p.job.get("out_ext") or "jpg")
        n = _materialize(p.cache, job_dir / "assets" / p.asset, ext)
        rendered_by_id[p.sid] = p
        count = int(p.job["frame_count"])
        w, h = int(p.job["res"][0]), int(p.job["res"][1])
        out.manifest[p.asset] = {"type": "frames", "w": w, "h": h, "fps": fps, "count": count,
                                 "dur": round(count / fps, 4), "pattern": f"assets/{p.asset}/%06d.{ext}",
                                 "poster": f"assets/{p.asset}/000001.{ext}"}
        p.report["materialized"] = n
        _rewrite_shot(out.film, p, fps)
        t0 = float(p.shot["t0"])
        for c in cues or []:
            try:
                t = t0 + float(c["t"])
            except (KeyError, TypeError, ValueError):
                out.warnings.append(f"shot {p.sid}: ignored malformed cue {c!r}")
                continue
            if t0 - p.pre - 1e-6 <= t <= float(p.shot["t1"]) + p.post + 1e-6 and 0 <= t <= float(film.get("dur") or t):
                cue = {"t": round(t, 4), "sfx": str(c.get("sfx")), "gain_db": float(c.get("gain_db", 0.0)),
                       "align": str(c.get("align") or "auto")}
                out.cues_added.append(cue)
        out.shots.append(p.report)
    out.film["cues"] = sorted([*(out.film.get("cues") or []), *out.cues_added], key=lambda c: float(c["t"]))
    out.film.setdefault("assets", {})
    for name in out.manifest:
        out.film["assets"][name] = {"type": "frames"}
    meta = out.film.setdefault("meta", {})
    meta["blender"] = {"tier": tier, "version": version, "shots": {p.sid: p.report for p in plans},
                       "eta_s": out.eta_s, "keyframes_only": times is not None}
    out.ok = True
    out.elapsed_s = round(time.monotonic() - t_start, 2)
    rendered = sum(1 for s in out.shots if not s.get("cached"))
    out.message = (f"Blender rendered {rendered} of {len(plans)} shot(s) in {runner.human_eta(out.elapsed_s)[1:]}"
                   if rendered else f"Blender shots reused from cache ({len(plans)})")
    _emit(progress, phase="done", eta_s=0.0, message=out.message)
    return out


def _read_json_list(p: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def _rewrite_shot(film: dict[str, Any], p: _Plan, fps: int) -> None:
    for s in film.get("shots") or []:
        if str(s.get("id")) == p.sid:
            s["scene"] = FRAMES_SCENE
            s["params"] = {"asset": p.asset, "offset": p.pre, "fps": fps, "fit": "cover",
                           "alpha": bool(p.job.get("alpha"))}
            s.pop("res", None)
            return


def _cancelled(out: BlenderPass, t_start: float) -> BlenderPass:
    out.cancelled = True
    out.ok = False
    out.message = "Blender render cancelled"
    out.errors.append(out.message)
    out.elapsed_s = round(time.monotonic() - t_start, 2)
    return out


def _fail(out: BlenderPass, p: _Plan, r: runner.RunResult, t_start: float) -> BlenderPass:
    out.ok = False
    out.errors.append(f"shot {p.sid} ({p.shot['scene']}): {r.error}")
    out.message = out.errors[-1]
    out.shots.append({**p.report, "error": r.error, "traceback": r.traceback[-4000:], "log": r.log})
    out.elapsed_s = round(time.monotonic() - t_start, 2)
    return out


# ------------------------------------------------------------------------------------------- handoff (browser)

def browser_handoff(film: dict[str, Any], shot_id: str, t: float, res: tuple[int, int], out_png: Path,
                    *, assets: Mapping[str, Any] | None = None, scenes: Mapping[str, Any] | None = None,
                    gpu: bool = False) -> Path | None:
    """Capture the browser frame of ``shot_id`` at film time ``t`` (its end) as a PNG via the preview machinery
    (one temporary job with only that shot; takes a render slot when AUTEUR_RENDER_SLOT_DIR is set).

    The mini film starts at the source shot: it is moved to t0 = 0 and the film lasts exactly the shot (shot-local
    timings are unchanged). Keeping the film's ``dur`` and the shot's ``t0`` made ``build_job`` reject the mini film
    ("no shot covers 0.000-6.400 s") whenever the source shot was not the first, and the reveal got no still."""
    import asyncio

    from ..film.page import build_job
    from ..film.preview import capture_keyframes, render_slot

    src = next((dict(s) for s in film.get("shots") or [] if str(s.get("id")) == shot_id), None)
    if src is None or is_blender_shot(src):
        return None
    refs = _strings(src.get("params") or {})
    mini = {k: v for k, v in film.items() if k not in ("shots", "transitions", "overlays", "captions", "cues",
                                                       "narration", "music")}
    t0 = float(src.get("t0") or 0.0)
    dur = max(1e-3, float(src.get("t1") or 0.0) - t0)
    src["t0"], src["t1"] = 0.0, round(dur, 6)
    mini["dur"] = round(dur, 6)
    fps = float(film.get("fps") or 30.0)
    t_local = min(max(0.0, float(t) - t0), dur - 0.5 / fps)
    mini["shots"] = [src]
    mini["assets"] = {n: a for n, a in (film.get("assets") or {}).items() if n in refs}
    specs = {n: s for n, s in (assets or {}).items() if n in mini["assets"]}
    job = out_png.parent / f"_job_{shot_id}"
    build_job(mini, job, assets=specs, scenes=scenes or {})
    with render_slot(os.environ.get("AUTEUR_RENDER_SLOT_DIR")):
        stills, _info = asyncio.run(capture_keyframes(job, [t_local], w=int(res[0]), h=int(res[1]), gpu=gpu))
    if not stills:
        return None
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.write_bytes(stills[0].png)
    return out_png
