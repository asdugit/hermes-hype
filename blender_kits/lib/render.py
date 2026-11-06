"""Render settings per tier + the frame loop (runs INSIDE Blender's Python).

Tiers (BLENDER.md): ``preview`` = EEVEE, low samples, no motion blur, no ray tracing (the runner passes a
960x540 / 540x960 ``res``); ``final`` = EEVEE at full res with motion blur and ray tracing (DOF comes from the
camera rig); ``max`` = Cycles on the GPU when one is available, else CPU.

``setup(sc)`` runs BEFORE the scene's ``build(sc)`` so ``lib.look`` can refine it; ``enforce(sc)`` runs AFTER and
restores what the host relies on (resolution, fps, frame range, output format, transparency). Frames are saved one
by one as ``<out_dir>/<f:06d>.<ext>`` via a ``.part`` file + atomic rename, so a crash never leaves a truncated
frame under the final name (the runner's resume and verification depend on that).
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import bpy

from . import compat

TIERS: dict[str, dict[str, Any]] = {
    "preview": {"engine": "eevee", "samples": 16, "motion_blur": False, "raytracing": False},
    "final": {"engine": "eevee", "samples": 64, "motion_blur": True, "raytracing": True},
    "max": {"engine": "cycles", "samples": 128, "motion_blur": True, "raytracing": True},
}


def tier_settings(tier: str) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r} (preview|final|max)")
    return TIERS[tier]


def setup(sc: Any) -> dict[str, Any]:
    """Base render settings for ``sc.tier``; returns ``{"engine": id, "device": str}``."""
    scene = sc.scene
    cfg = tier_settings(sc.tier)
    _frame_settings(sc)
    engine = compat.set_engine(scene, cfg["engine"])
    device = "GPU (EEVEE)"
    if cfg["engine"] == "eevee":
        compat.set_eevee_samples(scene, cfg["samples"])
        compat.set_eevee_raytracing(scene, cfg["raytracing"])
    else:
        device = compat.enable_cycles_gpu(scene)
        scene.cycles.samples = int(cfg["samples"])
        scene.cycles.use_denoising = True
        scene.render.use_persistent_data = True
    compat.set_motion_blur(scene, cfg["motion_blur"])
    compat.image_format(scene, sc.job.get("out_ext") or ("png" if sc.alpha else "jpg"), sc.alpha)
    return {"engine": engine, "device": device}


def _frame_settings(sc: Any) -> None:
    scene = sc.scene
    r = scene.render
    r.resolution_x, r.resolution_y = int(sc.res[0]), int(sc.res[1])
    r.resolution_percentage = 100
    r.pixel_aspect_x = r.pixel_aspect_y = 1.0
    r.fps, r.fps_base = int(sc.fps), 1.0
    scene.frame_start, scene.frame_end = 1, max(1, int(sc.frames))
    r.use_file_extension = True


def enforce(sc: Any) -> None:
    """Re-apply the host-owned settings after ``build`` (scenes must not change res/fps/frames/format)."""
    _frame_settings(sc)
    compat.image_format(sc.scene, sc.job.get("out_ext") or ("png" if sc.alpha else "jpg"), sc.alpha)
    if sc.scene.camera is None:
        raise RuntimeError("the scene has no active camera after build() (set sc.scene.camera)")


def frame_path(out_dir: Path, f: int, ext: str) -> Path:
    return Path(out_dir) / f"{int(f):06d}.{ext}"


def render_frames(sc: Any, frames: Iterable[int], on_frame: Callable[[int, float], None] | None = None) -> list[float]:
    """Render ``frames`` one by one to ``<out_dir>/<f:06d>.<ext>``; returns per-frame seconds."""
    scene = sc.scene
    ext = sc.job.get("out_ext") or ("png" if sc.alpha else "jpg")
    out_dir = Path(sc.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    times: list[float] = []
    for f in frames:
        t0 = time.perf_counter()
        scene.frame_set(int(f))
        bpy.ops.render.render()
        final = frame_path(out_dir, f, ext)
        part = final.with_name(final.stem + ".part." + ext)
        result = bpy.data.images["Render Result"]
        result.save_render(filepath=str(part), scene=scene)
        if not part.is_file() or part.stat().st_size == 0:
            raise RuntimeError(f"frame {f}: Blender wrote no image to {part}")
        os.replace(part, final)
        dt = time.perf_counter() - t0
        times.append(dt)
        if on_frame:
            on_frame(int(f), dt)
    return times


def say(line: str) -> None:
    """A protocol line on stdout (flushed: the host parses it live)."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
