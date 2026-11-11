"""Shared plumbing for the device kit scenes (media resolution, device choice, stage, framing)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

from ..lib import device as dv
from ..lib import materials, studio

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")

# Shared PARAMS fragments are duplicated literally in each scene (the Director parses PARAMS statically).


def _asset_dict(s: studio.Shot, ref: Any) -> dict | None:
    """Normalise a media reference (asset name | path | {asset|path, w, h, ...}) to {kind, path, frames_dir, w, h}."""
    if ref is None or ref == "":
        return None
    if isinstance(ref, dict):
        name = ref.get("asset")
        base = dict(s.assets.get(name, {})) if name else {}
        base.update({k: v for k, v in ref.items() if v is not None and k != "asset"})
        if not base.get("path") and not base.get("frames_dir"):
            return None
        return _kinded(base)
    ref = str(ref)
    if ref in s.assets:
        return _kinded(dict(s.assets[ref]))
    if Path(ref).exists():
        return _kinded({"path": ref})
    return None


def _kinded(d: dict) -> dict:
    p = str(d.get("path") or "")
    if not d.get("kind"):
        d["kind"] = "frames" if d.get("frames_dir") else ("video" if p.lower().endswith(VID_EXT) else "image")
    if d["kind"] == "model":
        return d
    if d["kind"] == "video" and d.get("frames_dir"):
        d["kind"] = "frames"
    return d


def _is_tall(d: dict) -> bool:
    w, h = d.get("w"), d.get("h")
    if not (w and h) and d.get("kind") == "image" and d.get("path"):
        try:
            img = bpy.data.images.load(d["path"], check_existing=True)
            w, h = img.size[:]
        except RuntimeError:
            return False
    return bool(w and h and h > w * 1.4)


def media(s: studio.Shot, *keys: str, want: str = "desktop") -> dict | None:
    """First usable media among the given params keys; else a matching job asset.

    ``want``: 'desktop' (wide UI capture), 'mobile' (portrait capture), 'full' (long page).
    Matching fallback by asset name (desktop/mobile/full/mobile_full) then by shape; then ``sc.product`` when it is 2D.
    """
    for k in keys:
        d = _asset_dict(s, s.params.get(k))
        if d:
            return d
    names = {"desktop": ("desktop", "screen", "capture", "image", "hero"), "mobile": ("mobile",),
             "full": ("full", "page", "scroll")}[want]
    cands = [(n, _kinded(dict(a))) for n, a in s.assets.items() if a.get("kind") in ("image", "video", "frames")]
    if want == "mobile":
        cands = [c for c in cands if "full" not in c[0]] + [c for c in cands if "full" in c[0]]
    elif want == "desktop":
        cands = [c for c in cands if "mobile" not in c[0] and "full" not in c[0]]
    elif want == "full":
        cands = [c for c in cands if "mobile" not in c[0]]
    for n, d in cands:   # pipeline asset names carry prefixes/suffixes: m3_mobile_390x844, cap_full_1440
        toks = n.replace("-", "_").split("_")
        if any(k == n or n.startswith(k) or k in toks for k in names):
            return d
    for n, d in cands:
        tall = _is_tall(d)
        if (want == "desktop" and not tall) or (want in ("mobile", "full") and tall):
            return d
    prod = s.product
    if want == "desktop" and isinstance(prod, dict) and prod.get("kind") in ("image", "video", "frames"):
        return _kinded(dict(prod))
    return None


def load(d: dict | None) -> tuple[Any, int, int]:
    """Blender image for a media dict -> (image, w, h)."""
    if not d:
        return None, 1, 1
    return dv.media_image(d.get("path"), video=d.get("kind") == "video",
                          frames_dir=d.get("frames_dir") if d.get("kind") == "frames" else None)


def accent(s: studio.Shot) -> str:
    """Product accent colour (param ``accent`` or asset theme colour) for the 'accent' stage preset."""
    a = s.params.get("accent")
    if a:
        return str(a)
    for d in s.assets.values():
        for k in ("accent", "theme_color"):
            if d.get(k):
                return str(d[k])
    return "#6d5df5"


def phone_media(given: dict | None, mobile: dict | None) -> dict | None:
    """Screen media for a phone: a portrait capture as given, else the mobile capture (a wide desktop capture
    cover-fitted into a phone crops the UI mid-word), else whatever was given."""
    if given and _is_tall(given):
        return given
    return mobile or given


def pick_kind(s: studio.Shot, requested: str, mobile: dict | None) -> str:
    """'auto' -> phone in 9:16 when a mobile capture exists, else laptop."""
    if requested and requested != "auto":
        return requested
    return "phone" if (s.vertical and mobile) else "laptop"


def make(s: studio.Shot, kind: str, d: dict | None, *, finish: str | None = None, name: str | None = None,
         open_deg: float = 108.0, glare: float = 0.0) -> dv.Device:
    """Build a device of ``kind`` showing media ``d`` (top-aligned cover fit)."""
    img, iw, ih = load(d)
    return dv.build(kind, image=img, iw=iw, ih=ih, finish=finish, name=name, open_deg=open_deg, glare=glare)


def setup(s: studio.Shot, *, preset: str, center, radius: float, floor: str = "reflective", sweep: bool = False,
          key_side: float = -1.0, cam_dist: float | None = None) -> studio.Stage:
    """Render settings (Standard view: UI-exact screens) + stage. Call BEFORE building devices."""
    studio.setup_render(s, view="standard")
    return studio.stage(s, preset=preset, center=center, radius=radius, accent=accent(s), floor=floor,
                        sweep=sweep, key_side=key_side, cam_dist=cam_dist)


def screen_rect_world(dev: dv.Device) -> tuple[Vector, float, float]:
    """Display centre (world) and size (m)."""
    bpy.context.view_layer.update()
    return dev.screen.obj.matrix_world @ Vector((0, 0, 0)), dev.screen.w, dev.screen.h


def front_pos(center: Vector, normal: Vector, dist: float, yaw_deg: float = 0.0, pitch_deg: float = 0.0
              ) -> tuple[float, float, float]:
    """Point at ``dist`` along ``normal`` from ``center``, rotated by yaw (about world Z) and pitch (about the
    screen's horizontal axis)."""
    n = normal.normalized()
    side = n.cross(Vector((0, 0, 1)))
    if side.length < 1e-6:
        side = Vector((1, 0, 0))
    side.normalize()
    from mathutils import Matrix

    v = Matrix.Rotation(math.radians(pitch_deg), 3, side) @ n
    v = Matrix.Rotation(math.radians(yaw_deg), 3, "Z") @ v
    p = center + v * dist
    return (p.x, p.y, p.z)


def keyed_screen_power(dev: dv.Device, s: studio.Shot, t0: float, t1: float) -> None:
    """Screen fades on over [t0, t1] (eased), every frame keyed."""
    for f in s.frames():
        materials.set_power(dev.screen.mat, studio.window(s.t(f), t0, t1), frame=f)


def float_bob(root: bpy.types.Object, s: studio.Shot, base: Vector, amp: float, seed: int) -> None:
    """Gentle hover (float scenes): z bob + tiny roll/pitch, deterministic."""
    for f in s.frames():
        t = s.t(f)
        root.location = (base.x, base.y, base.z + studio.wobble(t, seed, amp, (0.21, 0.37)))
        root.keyframe_insert("location", frame=f)
