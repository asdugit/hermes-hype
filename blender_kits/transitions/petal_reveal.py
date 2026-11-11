"""Petal reveal: the previous shot's last frame peels away as petals and blows past the camera, revealing a 3D scene
whose camera is already moving.

The handoff still (``sc.handoff["still"]``, captured by the host from ``params.from_shot``) is mapped 1:1 onto a
grid of square cells on a plane 1 m in front of the lens (nearest-neighbour sampling keeps pixel art crisp; the grade
is keyed off for the first frames so frame 1 equals the still). Cells peel in a wave from ``origin`` (e.g. the BUY
button that was clicked), flip to petal-pink backs, morph into petal silhouettes and fly toward and past the camera
with motion blur, while focus racks from the plane to the scene behind.

The scene behind is any Blender scene module (default ``meadow/oner``) built with ``reveal=True``; continue it in
the next shot with ``t_offset`` = this shot's duration so the camera never stops.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

PARAMS = {
    "under": {"type": "str", "default": "meadow/oner", "doc": "scene revealed behind the petals (<kit>/<scene>)"},
    "under_params": {"type": "dict", "default": {}, "doc": "params for the revealed scene"},
    "origin": {"type": "list", "default": [0.5, 0.5], "doc": "peel origin (u, v from the top-left), e.g. the clicked button"},
    "spread": {"type": "float", "default": 0.95, "doc": "seconds for the peel wave to cross the frame"},
    "start": {"type": "float", "default": 0.12, "doc": "first cell lets go at this time (s)"},
    "cell_px": {"type": "int", "default": 30, "doc": "cell size in output pixels"},
    "from_shot": {"type": "str", "default": "", "doc": "shot whose last frame is the handoff still (host captures it)"},
}
DESCRIBE = ("Transition: the previous frame breaks into petals that peel from the clicked point and blow past the "
            "camera, revealing a Blender scene (default the anime meadow) with its camera already moving.")


def _p(sc, k):
    return sc.params.get(k, PARAMS[k]["default"])


def _under_module(sc, name: str):
    root = Path(getattr(sc, "kit_root", None) or Path(__file__).resolve().parents[1])
    path = root / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"sr_under_{name.replace('/', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(sc) -> None:
    import bpy

    from blender_kits.lib import look, petals
    from blender_kits.lib.camera import linearize, smootherstep
    under = _under_module(sc, str(_p(sc, "under")))
    params = dict(sc.params)
    sub = dict(_p(sc, "under_params") or {})
    sub.setdefault("reveal", True)
    schema = getattr(under, "PARAMS", {})
    sc.params = {k: v["default"] for k, v in schema.items()} | sub
    try:
        under.build(sc)
    finally:
        sc.params = params
    still = (sc.handoff or {}).get("still")
    cam = sc.scene.camera if getattr(sc, "scene", None) is not None else bpy.context.scene.camera
    if not still or not Path(still).is_file():
        print("WARN petal_reveal: no handoff still; using a flat petal-pink card")
        img = bpy.data.images.new("handoff", 16, 16)
        img.generated_color = (0.95, 0.72, 0.8, 1.0)
        still = str(Path(sc.out_dir) / "_handoff_fallback.png")
        img.filepath_raw = still
        img.file_format = "PNG"
        img.save()
    fps = sc.fps
    t0 = float(getattr(sc, "t_start", 0.0))
    lens_fc = None
    ad = cam.data.animation_data
    if ad and ad.action:
        from blender_kits.lib.camera import fcurves
        lens_fc = next((fc for fc in fcurves(ad.action) if fc.data_path == "lens"), None)
    lens0 = lens_fc.evaluate(1) if lens_fc else cam.data.lens
    sheet = petals.sheet(cam, still, sc.res, dist=1.0, cell_px=int(_p(sc, "cell_px")),
                         t_start=float(_p(sc, "start")), spread=float(_p(sc, "spread")),
                         origin=tuple(_p(sc, "origin")), seed=sc.seed, t_offset=t0, lens=lens0)
    # keep the sheet filling the frame while the lens drifts (the camera is already moving)
    for f in range(1, sc.frames + 1):
        k = lens0 / (lens_fc.evaluate(f) if lens_fc else lens0)
        sheet.scale = (k, k, 1.0)
        sheet.keyframe_insert("scale", frame=f)
    linearize(sheet)
    # grade off while the still is intact, then fade in as the petals clear
    g = getattr(sc, "_grade", None)
    if g:
        a0 = float(_p(sc, "start"))
        for f in range(1, sc.frames + 1):
            t = t0 + (f - 1) / fps
            g["amount"].default_value = smootherstep((t - a0) / 0.9)
            g["amount"].keyframe_insert("default_value", frame=f)
    del look


def cues(sc) -> list[dict]:
    t0 = float(getattr(sc, "t_start", 0.0))
    out = [{"t": round(t0 + float(_p(sc, "start")), 3), "sfx": "petal_burst", "gain_db": -2.0}]
    under = _under_module(sc, str(_p(sc, "under")))
    if hasattr(under, "cues"):
        params = dict(sc.params)
        sub = dict(_p(sc, "under_params") or {})
        sub.setdefault("reveal", True)
        sc.params = {k: v["default"] for k, v in getattr(under, "PARAMS", {}).items()} | sub
        try:
            out += [c for c in under.cues(sc) if c.get("sfx") != "chime"]
        finally:
            sc.params = params
    return sorted(out, key=lambda c: c["t"])
