"""device_trio — multi-device composition (laptop + phone [+ tablet]) all showing the product, slow orbit."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..lib import studio
from . import _common as cm

PARAMS = {
    "media": {"type": "asset", "default": None, "doc": "laptop / tablet screen (default: desktop capture)"},
    "mobile": {"type": "asset", "default": None,
               "doc": "phone screen (default: mobile capture; without one the phone shows the whole desktop "
                      "capture letterboxed, never a cropped column)"},
    "devices": {"type": "enum", "values": ["laptop+phone", "laptop+phone+tablet", "laptop+tablet", "monitor+phone"],
                "default": "laptop+phone", "doc": "which devices share the frame"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent"], "default": "studio",
            "doc": "stage preset"},
    "accent": {"type": "color", "default": None, "doc": "accent colour for env=accent"},
    "orbit_deg": {"type": "float", "default": 16.0, "min": 0.0, "max": 50.0, "doc": "camera arc"},
    "push": {"type": "float", "default": 0.1, "min": 0.0, "max": 0.4, "doc": "dolly-in amount"},
    "reveal": {"type": "bool", "default": False, "doc": "lights come up from darkness"},
    "side": {"type": "enum", "values": ["left", "right"], "default": "left", "doc": "orbit direction"},
}
DESCRIBE = ("Device family shot: a laptop with a phone standing in front-right (optionally a tablet behind-left), "
            "each screen showing the matching real capture (desktop / mobile) in exact colours; slow eased orbit + "
            "push, soft floor reflections. 9:16 stacks them: phone in front, laptop behind and above.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    names = p["devices"].split("+")
    desk = cm.media(s, "media", want="desktop")
    mob = cm.media(s, "mobile", want="mobile")
    sgn = -1.0 if p["side"] == "left" else 1.0
    devs = {}
    for kind in names:
        m = mob if kind == "phone" and mob else desk
        devs[kind] = cm.make(s, kind, m, name=f"{kind}_t", open_deg=106.0)
    main = devs.get("laptop") or devs.get("monitor")
    if "laptop" in devs:
        devs["laptop"].root.location = (-0.03, -0.06, 0)
        devs["laptop"].root.rotation_euler.z = math.radians(8)
    if "monitor" in devs:
        devs["monitor"].root.location = (-0.12, 0.12, 0)
    v = s.vertical
    if "phone" in devs:
        ph = devs["phone"]
        ph.root.location = (0.20, -0.17, ph.size[1] / 2 + 0.012) if not v else (0.09, -0.19, ph.size[1] / 2 + 0.012)
        ph.root.rotation_euler = (math.radians(-4), 0, math.radians(-18))
    if "tablet" in devs:
        tb = devs["tablet"]
        tb.root.location = (-0.31, 0.05, tb.size[1] / 2 + 0.02) if not v else (-0.13, 0.12, tb.size[1] / 2 + 0.25)
        tb.root.rotation_euler = (math.radians(-6), 0, math.radians(22))
    bpy.context.view_layer.update()
    center = Vector((-0.02, 0.0, 0.09)) if not v else Vector((0.0, -0.02, 0.12))
    radius = 0.32
    lens = 45.0
    w_fit, h_fit = (0.78 if "tablet" in devs else 0.6), 0.3
    if v:
        w_fit, h_fit = 0.42, 0.4
    dist = studio.fit_distance(w_fit, h_fit, lens, s.aspect, 0.86)
    # aim so the devices actually built get equal margins left and right as seen from the camera (the phone
    # stands closer to the lens and looks wider, so the old fixed aim left it at - or cut by - the frame edge)
    pts = _group_xy(set(d.root for d in devs.values()))
    if pts:
        center.x = balanced_x(pts, center.y - dist)
    st = cm.setup(s, preset=p["env"], center=tuple(center), radius=radius, key_side=sgn, cam_dist=dist)
    D = s.dur
    if p["reveal"]:
        studio.animate_reveal(s, st, t0=-0.1, t1=D * 0.5, from_level=0.05)
    arc = p["orbit_deg"]
    pitch0, pitch1 = (14, 10) if not v else (24, 19)
    tgt = tuple(center)
    beats = [studio.Beat(0.0, studio.look_from(tgt, sgn * arc * 0.6, pitch0, dist * (1 + p["push"])), tgt, lens),
             studio.Beat(D, studio.look_from(tgt, -sgn * arc * 0.4, pitch1, dist), tgt, lens)]
    focus = (main.screen.obj.matrix_world @ Vector((0, 0, 0))) if main else Vector(tgt)
    if "phone" in devs:
        focus = focus.lerp(devs["phone"].screen.obj.matrix_world @ Vector((0, 0, 0)), 0.5)
    studio.CameraRig(beats, end_speed=0.8, handheld=0.04, fstop=max(3.5, studio.dof_fstop(radius)), seed=s.seed,
                     focus=lambda t, pos, tg: (focus - Vector(pos)).length).build(s)
    studio.finalize(s)


def _group_xy(roots: set) -> list:
    """World (x, y) of the bounding-box corners of every mesh under the given device roots."""
    pts = []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        r = ob
        while r.parent is not None:
            r = r.parent
        if r in roots:
            for c in ob.bound_box:
                w = ob.matrix_world @ Vector(c)
                pts.append((w.x, w.y))
    return pts


def balanced_x(pts: list, cam_y: float) -> float:
    """Aim x for a camera at y = ``cam_y`` looking +Y: the widest projected extent left of the aim equals the one
    right of it (perspective: x offset / depth). Bisection; the plain bbox middle when depths are degenerate."""
    lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
    deps = [(x, max(1e-3, y - cam_y)) for x, y in pts]

    def skew(c: float) -> float:
        return max((x - c) / d for x, d in deps) - max((c - x) / d for x, d in deps)

    a, b = lo, hi
    for _ in range(40):
        m = (a + b) / 2
        if skew(m) > 0:
            a = m
        else:
            b = m
    return (a + b) / 2


def cues(sc) -> list:
    return [{"t": 0.0, "sfx": "whoosh_soft"}]
