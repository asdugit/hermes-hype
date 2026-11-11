"""device_end — END: a calm device lockup with clean space for the browser text overlay (title / CTA / URL)."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..lib import studio
from . import _common as cm

PARAMS = {
    "media": {"type": "asset", "default": None, "doc": "screen content (default: the desktop capture)"},
    "device": {"type": "enum", "values": ["auto", "laptop", "phone", "tablet", "monitor"], "default": "auto",
               "doc": "auto = laptop (16:9); phone in 9:16 when a mobile capture exists"},
    "space": {"type": "enum", "values": ["auto", "left", "right", "top", "bottom", "none"], "default": "auto",
              "doc": "where the overlay text goes; the device sits on the other side (auto: left in 16:9, top in "
                     "9:16)"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent"], "default": "studio",
            "doc": "stage preset"},
    "accent": {"type": "color", "default": None, "doc": "accent colour for env=accent"},
    "size": {"type": "float", "default": 0.46, "min": 0.2, "max": 0.8,
             "doc": "device width as a fraction of the frame width (16:9) / height (9:16)"},
    "push": {"type": "float", "default": 0.05, "min": 0.0, "max": 0.3, "doc": "slow dolly-in amount"},
    "dim_bg": {"type": "float", "default": 0.0, "min": 0.0, "max": 0.8,
               "doc": "darken the stage towards the end (fraction) so overlay text pops"},
    "defocus": {"type": "float", "default": 0.0, "min": 0.0, "max": 1.0,
                "doc": "end-card backdrop: the device melts into a soft bokeh glow behind a CENTRED lockup "
                       "(0 = sharp; 1 = fully soft; use with space none)"},
}
DESCRIBE = ("END lockup: the device rests 3/4 to camera on the stage, screen showing the product, on one side of the "
            "frame; the other side stays clean, dark and evenly lit for the browser title / CTA / URL overlay; near-"
            "still camera with a slow push that settles (no motion at the last frame); defocus turns the device into a soft "
            "bokeh glow behind a centred lockup.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    mobile = cm.media(s, want="mobile")
    kind = cm.pick_kind(s, p["device"], mobile)
    m = cm.media(s, "media", want="desktop")
    if kind == "phone":
        m = cm.phone_media(m if p.get("media") else None, mobile) or m
    dev = cm.make(s, kind, m, open_deg=106.0)
    space = p["space"]
    if space == "auto":
        space = "top" if s.vertical else "left"
    if kind == "laptop":
        dev.root.location = (0, -0.125, 0)
        center, radius, wd, ht = Vector((0, 0.02, 0.09)), 0.2, 0.33, 0.25
    elif kind == "monitor":
        center, radius, wd, ht = Vector((0, 0, 0.36)), 0.36, 0.64, 0.6
    else:
        dev.root.location = (0, 0, dev.size[1] / 2 + 0.03)
        center, radius = Vector((0, 0, dev.size[1] / 2 + 0.03)), dev.size[1] * 0.62
        wd, ht = dev.size[0] * 1.3, dev.size[1] * 1.08
    sgn = 1.0 if space == "left" else -1.0  # device turns toward the text side
    dev.root.rotation_euler.z = math.radians(-14.0 * sgn) if space in ("left", "right") else math.radians(-10)
    bpy.context.view_layer.update()
    lens = 50.0
    size = p["size"]
    if s.vertical:
        dist = studio.fit_distance(wd, ht, lens, s.aspect, 1.0) * (0.8 / max(size, 0.2))
    else:
        dist = studio.fit_distance(wd, ht, lens, s.aspect, 1.0) * (1.0 / max(size, 0.1)) * 0.9
    st = cm.setup(s, preset=p["env"], center=tuple(center), radius=radius, key_side=-sgn, cam_dist=dist)
    # shift the aim so the device lands in the non-text part of the frame
    hf = studio.fov(lens)
    half_w = dist * math.tan(hf / 2)
    half_h = half_w / s.aspect
    off = {"left": Vector((-half_w * 0.42, 0, 0)), "right": Vector((half_w * 0.42, 0, 0)),
           "top": Vector((0, 0, half_h * 0.36)), "bottom": Vector((0, 0, -half_h * 0.36)),
           "none": Vector((0, 0, 0))}[space]
    tgt = center + off
    D = s.dur
    beats = [studio.Beat(0.0, studio.look_from(tgt, 6 * sgn, 9, dist * (1 + p["push"])), tuple(tgt), lens),
             studio.Beat(D, studio.look_from(tgt, 2 * sgn, 8, dist), tuple(tgt), lens)]
    focus_pt = center.copy()
    dfc = float(p.get("defocus") or 0.0)
    fstop = max(2.8, studio.dof_fstop(radius))
    if dfc > 0:   # focus slides from the device to well in front of it: sharp start, soft glow at the end
        fstop = studio.lerp(fstop, 1.0, dfc)

    def focus(t: float, pos, tg) -> float:
        d0 = (focus_pt - Vector(pos)).length
        if dfc <= 0:
            return d0
        return d0 * (1.0 - 0.6 * dfc * studio.window(t, 0.0, min(D * 0.4, 1.6)))

    studio.CameraRig(beats, end_speed=0.0, handheld=0.0, fstop=fstop, seed=s.seed, focus=focus).build(s)
    if p["dim_bg"] > 0:
        for name, ob in st.lights.items():
            for f in s.frames():
                k = 1.0 - p["dim_bg"] * studio.window(s.t(f), D * 0.4, D)
                ob.data.energy = st.energies[name] * (k if name in ("bg", "top") else 1.0)
                ob.data.keyframe_insert("energy", frame=f)
    studio.finalize(s)


def cues(sc) -> list:
    return [{"t": 0.0, "sfx": "resolve"}]
