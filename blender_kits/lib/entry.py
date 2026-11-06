"""Showreel Blender entry point (runs INSIDE Blender's Python).

    blender -b --factory-startup --python-exit-code 1 -P blender_kits/lib/entry.py -- <job.json>

Reads job.json (BLENDER.md), registers ``blender_kits`` as a package from ``job["kit_root"]``, resets to an empty
scene, loads the scene module by path, builds it with a :class:`SceneCtx`, then renders the requested frames one
by one. Protocol lines on stdout (each flushed):

    SR_START blender=<version> scene=<path>
    SR_BUILD_DONE s=<seconds>
    SR_FRAME <f> <seconds>          one per saved frame (shot-local frame number)
    SR_DONE frames=<n> mean=<seconds>
    SR_ERROR <one line>             followed by the traceback, then exit code 1

Deterministic: ``random`` (and numpy, if a scene uses it) are seeded from ``job["seed"]``; nothing reads the clock
except timing stats.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import random
import sys
import time
import traceback
import zlib
from pathlib import Path
from types import ModuleType
from typing import Any

PROTOCOL_VERSION = 1


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _job_path(argv: list[str]) -> Path:
    if "--" not in argv or argv.index("--") + 1 >= len(argv):
        raise SystemExit("usage: blender -b --factory-startup -P entry.py -- <job.json>")
    return Path(argv[argv.index("--") + 1])


def register_package(kit_root: Path) -> ModuleType:
    """Make ``import blender_kits.lib.<x>`` work from ``kit_root`` whatever the directory is called."""
    init = kit_root / "__init__.py"
    spec = importlib.util.spec_from_file_location("blender_kits", init, submodule_search_locations=[str(kit_root)])
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the blender_kits package from {kit_root}")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["blender_kits"] = pkg
    spec.loader.exec_module(pkg)
    return pkg


def load_scene(path: Path, kit_root: Path) -> ModuleType:
    """Import a scene module by path. Inside ``kit_root`` it becomes ``blender_kits.<kit>.<scene>`` (relative
    imports work); elsewhere ``sr_scene_<crc>``."""
    path = path.resolve()
    try:
        rel = path.relative_to(kit_root.resolve()).with_suffix("")
        name = "blender_kits." + ".".join(rel.parts)
        importlib.import_module("blender_kits." + ".".join(rel.parts[:-1])) if len(rel.parts) > 1 else None
    except ValueError:
        name = f"sr_scene_{zlib.crc32(str(path).encode('utf-8')):08x}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load scene module {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "build", None)):
        raise AttributeError(f"scene module {path.name} defines no build(sc)")
    return mod


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    if "numpy" in sys.modules or importlib.util.find_spec("numpy") is not None:
        import numpy
        numpy.random.seed(seed % (2 ** 32))


def _gpu_name() -> str:
    """Renderer string of the GPU backend (stats only)."""
    import gpu
    try:
        return f"{gpu.platform.vendor_get()} {gpu.platform.renderer_get()}".strip()
    except (RuntimeError, SystemError) as exc:   # no GPU context in this build/session
        return f"unknown ({exc})"


def run(job: dict[str, Any]) -> None:
    import bpy

    kit_root = Path(job["kit_root"])
    register_package(kit_root)
    from blender_kits.lib import compat, ctx as ctxmod, render as rmod

    compat.require_min()
    if int(job.get("version") or 1) != PROTOCOL_VERSION:
        raise ValueError(f"job.json version {job.get('version')} != {PROTOCOL_VERSION}")
    _say(f"SR_START blender={compat.version_string()} scene={job['scene']}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.use_preferences_save = False

    mod = load_scene(Path(job["scene"]), kit_root)
    sc = ctxmod.from_job(job, getattr(mod, "PARAMS", None))
    _seed_everything(sc.seed)
    sc.scene = bpy.context.scene
    sc.out_dir.mkdir(parents=True, exist_ok=True)
    info = rmod.setup(sc)

    t_build = time.perf_counter()
    mod.build(sc)
    rmod.enforce(sc)
    build_s = time.perf_counter() - t_build
    _say(f"SR_BUILD_DONE s={build_s:.3f}")

    cues = list(sc._cues)
    if callable(getattr(mod, "cues", None)):
        cues += [dict(c) for c in (mod.cues(sc) or [])]
    if job.get("cues_out"):
        Path(job["cues_out"]).write_text(json.dumps(cues, indent=1), encoding="utf-8")
    if job.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=str(sc.out_dir / "scene.blend"), copy=True)

    frames = [int(f) for f in job["frames"]] if job.get("frames") is not None else list(range(1, sc.frames + 1))
    bad = [f for f in frames if not 1 <= f <= sc.frames]
    if bad:
        raise ValueError(f"frames outside 1..{sc.frames}: {bad[:5]}")
    times = rmod.render_frames(sc, frames, on_frame=lambda f, dt: _say(f"SR_FRAME {f} {dt:.3f}"))
    mean = sum(times) / len(times) if times else 0.0
    device = info["device"] if info["engine"] == "CYCLES" else _gpu_name()
    if job.get("stats_out"):
        stats = {"build_s": round(build_s, 3), "mean_frame_s": round(mean, 4), "frames": len(times),
                 "frame_s": [round(x, 4) for x in times], "blender_version": compat.version_string(),
                 "engine": info["engine"], "device": device, "tier": sc.tier, "res": list(sc.res)}
        Path(job["stats_out"]).write_text(json.dumps(stats, indent=1), encoding="utf-8")
    _say(f"SR_DONE frames={len(times)} mean={mean:.3f}")


def main(argv: list[str]) -> int:
    try:
        job = json.loads(_job_path(argv).read_text(encoding="utf-8"))
        run(job)
        return 0
    except BaseException as exc:  # report every failure on the protocol channel, then exit non-zero
        if isinstance(exc, SystemExit) and not exc.code:
            return 0
        msg = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ")[:400]
        _say(f"SR_ERROR {msg}")
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        return 1


if __name__ == "__main__":
    code = main(sys.argv)
    if code:
        sys.exit(code)
