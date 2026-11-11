"""device_scroll — SCROLL: a long page scrolls on the device screen while the camera drifts."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..lib import device as dv
from ..lib import studio
from . import _common as cm

PARAMS = {
    "image": {"type": "asset", "default": None,
              "doc": "full-page capture (tall image): asset name / path / {asset|path,w,h}; default = asset named "
                     "full* (9:16 phone: mobile_full*)"},
    "scroll": {"type": "list", "default": [0.0, 1.0],
               "doc": "[from, to] scroll positions as fractions of the scrollable height (0 = top, 1 = bottom)"},
    "device": {"type": "enum", "values": ["auto", "laptop", "phone", "tablet", "monitor"], "default": "auto",
               "doc": "auto = laptop (16:9); phone in 9:16 when a mobile full-page capture exists"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent"], "default": "studio",
            "doc": "stage preset"},
    "accent": {"type": "color", "default": None, "doc": "accent colour for env=accent"},
    "hold": {"type": "float", "default": 0.12, "min": 0.0, "max": 0.4,
             "doc": "fraction of the shot held still at the start and (x0.8) at the end of the scroll"},
    "drift_deg": {"type": "float", "default": 14.0, "min": 0.0, "max": 40.0, "doc": "camera arc across the shot"},
    "fill": {"type": "float", "default": 0.55, "min": 0.4, "max": 0.98,
             "doc": "screen size in frame (fraction of frame height for laptops)"},
    "side": {"type": "enum", "values": ["left", "right"], "default": "left", "doc": "drift direction"},
}
DESCRIBE = ("SCROLL on a device: a full-page capture scrolls smoothly (trackpad-like ease, holds at both ends) on "
            "the laptop or phone screen with exact UI colours while the camera drifts in a slow arc and pushes "
            "slightly; focus on the screen.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    mob = cm.media(s, want="mobile") if s.vertical else None
    kind = p["device"]
    if kind == "auto":
        kind = "phone" if (s.vertical and mob and any("mobile_full" in n for n in s.assets)) else "laptop"
    if kind == "phone" and not p.get("image"):
        m = next((cm._kinded(dict(a)) for n, a in s.assets.items() if "mobile_full" in n), None) or mob
    else:
        m = cm.media(s, "image", want="full") or cm.media(s, "image", want="desktop")
    img, iw, ih = cm.load(m)
    sgn = -1.0 if p["side"] == "left" else 1.0
    dev = dv.build(kind, image=img, iw=iw, ih=ih, open_deg=104.0, fit="cover")  # the page scrolls under it
    scr = dev.screen
    x0, _y0, sx, sy = scr.window  # cover fit, top aligned
    if kind == "laptop":
        dev.root.location = (0, -0.125, 0)
        center, radius = Vector((0, 0.02, 0.09)), 0.2
    elif kind == "monitor":
        center, radius = Vector((0, 0, 0.36)), 0.36
    else:
        dev.root.location = (0, 0, dev.size[1] / 2 + 0.03)
        center, radius = Vector((0, 0, dev.size[1] / 2 + 0.03)), dev.size[1] * 0.62
    dev.root.rotation_euler.z = math.radians(-10.0 * sgn)
    bpy.context.view_layer.update()
    D = s.dur
    a, b = [float(v) for v in (p["scroll"] or [0, 1])][:2]
    hold = p["hold"]
    rng = max(0.0, 1.0 - sy)
    for f in s.frames():
        u = studio.window(s.t(f), D * hold, D * (1 - hold * 0.8), "inout")
        frac = studio.lerp(a, b, u)
        scr.show(x0=x0, y0=(1.0 - sy) - frac * rng, sx=sx, sy=sy, frame=f)
    scr_c, sw, sh = cm.screen_rect_world(dev)
    n = scr.normal()
    lens = 50.0
    fill = p["fill"]
    if kind == "laptop":
        d = studio.fit_distance(sw * 1.05, sh / fill * 0.86, lens, s.aspect, 0.98 if s.vertical else 0.92)
    else:
        d = studio.fit_distance(sw, sh, lens, s.aspect, fill)
    cm.setup(s, preset=p["env"], center=tuple(center), radius=radius, key_side=sgn, cam_dist=d)
    arc = p["drift_deg"]
    tgt = tuple(scr_c)
    beats = [studio.Beat(0.0, cm.front_pos(scr_c, n, d * 1.06, yaw_deg=sgn * (8 + arc * 0.5), pitch_deg=7), tgt,
                         lens),
             studio.Beat(D, cm.front_pos(scr_c, n, d * 0.98, yaw_deg=sgn * (8 - arc * 0.5), pitch_deg=4), tgt, lens)]
    studio.CameraRig(beats, end_speed=0.9, handheld=0.04, fstop=max(2.8, studio.dof_fstop(radius)),
                     seed=s.seed).build(s)
    studio.finalize(s)


def cues(sc) -> list:
    return [{"t": 0.25, "sfx": "scroll"}]
