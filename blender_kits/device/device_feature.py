"""device_feature — FEATURE: the camera pushes from the whole device into one feature of the real UI."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..lib import device as dv
from ..lib import studio
from . import _common as cm

PARAMS = {
    "image": {"type": "asset", "default": None,
              "doc": "the capture showing the feature: asset name / path / {asset|path,w,h,...} (FEATURE data image)"},
    "feature": {"type": "string", "default": "", "doc": "feature name (for the overlay / docs; not drawn in 3D)"},
    "bbox": {"type": "list", "default": [0.1, 0.1, 0.8, 0.8],
             "doc": "feature rect [x, y, w, h] as fractions of the image (top-left origin); the push lands on it"},
    "click": {"type": "list", "default": None,
              "doc": "click point [x, y] (image fractions); null = no cursor/click"},
    "device": {"type": "enum", "values": ["auto", "laptop", "phone", "tablet", "monitor"], "default": "auto",
               "doc": "auto = laptop for wide captures, phone for portrait (mobile) captures"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent"], "default": "studio",
            "doc": "stage preset"},
    "accent": {"type": "color", "default": None, "doc": "click ripple / accent colour (default capture theme)"},
    "fill": {"type": "float", "default": 0.62, "min": 0.25, "max": 0.95,
             "doc": "how much of the frame the feature rect fills at the end of the push"},
    "angle": {"type": "float", "default": 20.0, "min": 0.0, "max": 40.0,
              "doc": "final camera angle off the screen normal (degrees; 0 = flat-on, more = more depth)"},
    "push_at": {"type": "float", "default": 0.62, "min": 0.2, "max": 0.95,
                "doc": "fraction of the shot where the push lands on the rect (then a slow drift)"},
    "click_at": {"type": "float", "default": 0.7, "min": 0.3, "max": 0.95, "doc": "click time (fraction)"},
    "side": {"type": "enum", "values": ["left", "right"], "default": "left", "doc": "camera approach side"},
}
DESCRIBE = ("FEATURE close-up on a device: starts on the whole laptop (or phone) showing the real capture, then one "
            "smooth eased push lands exactly on the feature rect (screenshot px mapped to world space) with focus "
            "riding the screen; optional cursor glides in and clicks with an accent ripple.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    m = cm.media(s, "image", "media", want="desktop")
    if m is None:
        m = cm.media(s, "image", want="mobile")
    img, iw, ih = cm.load(m)
    kind = p["device"]
    if kind == "auto":
        kind = "phone" if ih > iw * 1.4 else "laptop"
    sgn = -1.0 if p["side"] == "left" else 1.0
    dev = dv.build(kind, image=img, iw=iw, ih=ih, finish=None, open_deg=106.0)
    bbox = [float(v) for v in (p["bbox"] or [0.1, 0.1, 0.8, 0.8])][:4]
    dev.screen.show(**dict(zip(("x0", "y0", "sx", "sy"), dv.window_showing(dev.screen, bbox))))
    if kind == "laptop":
        dev.root.location = (0, -0.125, 0)
        center, radius = Vector((0, 0.02, 0.09)), 0.2
    elif kind == "monitor":
        center, radius = Vector((0, 0, 0.36)), 0.36
    else:
        dev.root.location = (0, 0, dev.size[1] / 2 + 0.03)
        center, radius = Vector((0, 0, dev.size[1] / 2 + 0.03)), dev.size[1] * 0.62
    dev.root.rotation_euler.z = math.radians(-8.0 * sgn)
    bpy.context.view_layer.update()
    lens = 50.0
    scr_c, sw, sh = cm.screen_rect_world(dev)
    n = dev.screen.normal()
    rect_c, rw, rh = dv.rect_world(dev, bbox)
    d_wide = studio.fit_distance(sw * 1.25, sh * 1.45, lens, s.aspect, 0.86 if s.vertical else 0.7)
    d_rect = studio.fit_distance(rw, rh, lens, s.aspect, p["fill"])
    # never closer than the whole screen at ~1.15 frame widths: the device edge / bezel stays in the picture so
    # the push keeps reading as 3D (a full-frame flat screenshot loses the point of a device shot)
    d_rect = max(d_rect, studio.fit_distance(sw, sh, lens, s.aspect, 1.15), 0.06)
    st = cm.setup(s, preset=p["env"], center=tuple(center), radius=radius, key_side=sgn, cam_dist=d_wide)
    D = s.dur
    t_push = D * p["push_at"]
    ang = p["angle"]
    wide_tgt = tuple(scr_c + Vector((0, 0, -sh * 0.12)))
    beats = [
        studio.Beat(0.0, cm.front_pos(scr_c, n, d_wide, yaw_deg=sgn * (ang + 12), pitch_deg=6), wide_tgt, lens),
        studio.Beat(t_push, cm.front_pos(rect_c, n, d_rect, yaw_deg=sgn * ang, pitch_deg=3), tuple(rect_c), lens),
        studio.Beat(D, cm.front_pos(rect_c, n, d_rect * 0.94, yaw_deg=sgn * (ang - 3), pitch_deg=2), tuple(rect_c),
                    lens),
    ]
    studio.CameraRig(beats, end_speed=0.45, handheld=0.05, fstop=7.0,
                     seed=s.seed).build(s)
    if p.get("click"):
        _cursor_and_click(s, dev, [float(v) for v in p["click"]][:2], bbox, cm.accent(s))
    studio.finalize(s)
    _ = st


def _cursor_and_click(s: studio.Shot, dev: dv.Device, click: list, bbox: list, accent: str) -> None:
    scr = dev.screen
    D = s.dur
    t_click = D * float(s.params["click_at"])
    cu, cv = scr.px_to_screen_uv(click[0] * scr.img_w, click[1] * scr.img_h)
    end = scr.uv_to_local(cu, cv)
    start = scr.uv_to_local(min(0.98, cu + 0.16), max(0.02, cv - 0.14))
    cur = dv.cursor(dev)
    ring, rmat = dv.ripple(dev, accent)
    ring.location.x, ring.location.y = end.x, end.y
    mix = rmat.node_tree.nodes["sr_alpha"]
    for f in s.frames():
        t = s.t(f)
        u = studio.window(t, D * 0.18, t_click - 0.12, "inout")
        pos = start.lerp(end, u)
        cur.location = (pos.x, pos.y, 0.0)
        press = 1.0 - 0.14 * math.exp(-((t - t_click) / 0.07) ** 2)
        appear = studio.window(t, D * 0.08, D * 0.22)
        cur.scale = (press * appear,) * 3
        cur.keyframe_insert("location", frame=f)
        cur.keyframe_insert("scale", frame=f)
        k = studio.clamp((t - t_click) / 0.55)
        sc_r = 0.2 + 1.3 * studio.ease(k, "out")
        ring.scale = (sc_r, sc_r, 1.0)
        ring.keyframe_insert("scale", frame=f)
        mix.inputs[0].default_value = (1.0 - k) * 0.9 if t >= t_click else 0.0
        mix.inputs[0].keyframe_insert("default_value", frame=f)


def cues(sc) -> list:
    s = studio.shot(sc, PARAMS)
    out = [{"t": 0.0, "sfx": "whoosh_soft"}]
    if s.params.get("click"):
        out.append({"t": round(s.dur * float(s.params["click_at"]), 3), "sfx": "click"})
    return out
