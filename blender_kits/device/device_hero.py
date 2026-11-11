"""device_hero — TITLE / HOOK: the product's UI comes to life on a premium device out of darkness."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..lib import studio
from . import _common as cm

PARAMS = {
    "media": {"type": "asset", "default": None,
              "doc": "screen content: asset name / path / {asset|path,w,h} (screenshot, capture video or frames); "
                     "default = the job's desktop capture (phone: mobile capture)"},
    "mobile": {"type": "asset", "default": None, "doc": "portrait capture for a phone (default: asset named mobile*)"},
    "device": {"type": "enum", "values": ["auto", "laptop", "phone", "tablet", "monitor"], "default": "auto",
               "doc": "auto = laptop in 16:9; phone in 9:16 when a mobile capture exists, else laptop"},
    "entrance": {"type": "enum", "values": ["auto", "open", "rise", "turn"], "default": "auto",
                 "doc": "laptop lid opens (open) | device rises into place (rise) | slow turn only (turn); "
                        "auto = open for laptops, rise for the rest"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent"], "default": "studio",
            "doc": "stage preset: dark graphite studio | bright white | warm sunset | cyc lit in the product accent"},
    "accent": {"type": "color", "default": None, "doc": "accent for env=accent (default: capture theme colour)"},
    "finish": {"type": "enum", "values": ["auto", "silver", "space", "midnight", "starlight", "titanium"],
               "default": "auto", "doc": "device body finish (auto: silver laptop/monitor, space phone/tablet)"},
    "reveal": {"type": "bool", "default": True, "doc": "lights come up from darkness + a light sweep crosses"},
    "screen_on": {"type": "float", "default": 0.42, "min": 0.0, "max": 0.9,
                  "doc": "fraction of the shot where the screen turns on (0 = on from the start)"},
    "orbit_deg": {"type": "float", "default": 18.0, "min": 0.0, "max": 60.0, "doc": "camera arc across the shot"},
    "push": {"type": "float", "default": 0.16, "min": 0.0, "max": 0.5, "doc": "dolly-in amount (fraction)"},
    "fill": {"type": "float", "default": 0.62, "min": 0.3, "max": 0.95,
             "doc": "device size in frame at the end (fraction of frame width; 9:16 uses height for phones)"},
    "side": {"type": "enum", "values": ["left", "right"], "default": "left",
             "doc": "camera travels from this side toward the front"},
    "space": {"type": "enum", "values": ["none", "left", "right"], "default": "none",
              "doc": "keep this side of the frame clean for overlay text (the device sits on the other side, a bit "
                     "smaller); none = device centred"},
}
DESCRIBE = ("Device hero for TITLE/HOOK: out of darkness a slim aluminium laptop opens (or a phone rises and turns) "
            "and its screen lights up with the product's real UI, exact colours; rims light first, a strip light "
            "sweeps the aluminium; slow eased camera arc + dolly with focus on the screen. 9:16 uses a phone when a "
            "mobile capture exists.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    mobile = cm.media(s, "mobile", want="mobile")
    kind = cm.pick_kind(s, p["device"], mobile)
    m = mobile if kind == "phone" and mobile else cm.media(s, "media", "image", want="desktop")
    if kind == "phone" and p.get("media") and not p.get("mobile"):
        m = cm.media(s, "media", want="desktop")
    finish = None if p["finish"] == "auto" else p["finish"]
    entrance = p["entrance"] if p["entrance"] != "auto" else ("open" if kind == "laptop" else "rise")
    D = s.dur
    sgn = -1.0 if p["side"] == "left" else 1.0

    dev = cm.make(s, kind, m, finish=finish, open_deg=108.0)
    turn = bpy.data.objects.new("sr_turn", None)
    bpy.context.scene.collection.objects.link(turn)
    if kind == "laptop":
        dev.root.parent = turn
        dev.root.location = (0, -0.125, 0)
        center = Vector((0, 0.02, 0.085))
        radius = 0.2
    elif kind == "monitor":
        dev.root.parent = turn
        center = Vector((0, 0, 0.36))
        radius = 0.36
    else:
        dev.root.parent = turn
        center = Vector((0, 0, dev.size[1] / 2 + 0.035))
        radius = dev.size[1] * 0.62

    lens0, lens1 = (40.0, 46.0) if not s.vertical else (38.0, 42.0)
    if kind == "laptop":
        w_fit, h_fit = 0.34, 0.26
    elif kind == "monitor":
        w_fit, h_fit = 0.66, 0.6
    else:
        w_fit, h_fit = dev.size[0] * 1.6, dev.size[1] * 1.05
    fill = p["fill"]
    if s.vertical and kind == "laptop":
        fill = min(0.95, fill + 0.28)
    space = p.get("space") or "none"
    if s.vertical or space not in ("left", "right"):
        space = "none"
    if space != "none":
        fill *= 0.8
    dist = studio.fit_distance(w_fit, h_fit, lens1, s.aspect, fill)
    st = cm.setup(s, preset=p["env"], center=tuple(center), radius=radius, sweep=bool(p["reveal"]),
                  key_side=sgn, cam_dist=dist)

    # ---- device motion
    hinge = dev.parts.get("hinge")
    yaw0, yaw1 = (-36.0 * -sgn, -14.0 * -sgn) if kind == "laptop" else (52.0 * -sgn, 9.0 * -sgn)
    if entrance == "turn":
        yaw0 = yaw1 + (yaw0 - yaw1) * 0.5
    for f in s.frames():
        t = s.t(f)
        u = studio.ease(t / D, "inout", 0.8)
        yaw = studio.lerp(yaw0, yaw1, u)
        if kind in ("phone", "tablet"):
            rise = studio.window(t, -0.2, D * 0.62, "out") if entrance == "rise" else 1.0
            turn.location = (0, 0, center.z + (rise - 1.0) * radius * 0.42)
            turn.rotation_euler = (math.radians(studio.lerp(-6, 3, u)), math.radians(studio.lerp(6, 2, u)) * -sgn,
                                   math.radians(yaw))
        else:
            turn.rotation_euler = (0, 0, math.radians(yaw))
            turn.location = (0, 0, 0)
        turn.keyframe_insert("location", frame=f)
        turn.keyframe_insert("rotation_euler", frame=f)
        if hinge is not None:
            ang = studio.lerp(3.0, 108.0, studio.window(t, D * 0.04, D * 0.62, "inout")) if entrance == "open" \
                else 108.0
            hinge.rotation_euler = (-math.radians(ang), 0, 0)
            hinge.keyframe_insert("rotation_euler", frame=f)
    on0 = D * p["screen_on"]
    cm.keyed_screen_power(dev, s, on0 - 0.05 if on0 > 0 else -1.0, on0 + 0.45 if on0 > 0 else -0.5)

    # ---- lights
    if p["reveal"]:
        studio.animate_reveal(s, st, t0=-0.1, t1=D * 0.5, from_level=0.04)
        studio.animate_sweep(s, st, t0=D * 0.12, t1=D * 0.8, center=tuple(center), radius=radius,
                             energy=650.0, height=1.0)

    # ---- camera
    pitch0, pitch1 = (17.0, 9.0) if kind in ("laptop", "monitor") else (7.0, 3.0)
    if s.vertical and kind == "laptop":
        pitch0, pitch1 = 26.0, 18.0
    orbit = p["orbit_deg"]
    tgt0 = center + Vector((0, 0, -0.01))
    tgt1 = center.copy()
    # (yaw, pitch, distance, lens) per beat; with ``space`` the aim moves sideways (camera-right axis) so the
    # device lands in the other part of the frame and the text side stays clean
    plan = [(0.0, tgt0, sgn * orbit * 0.8, pitch0, dist * (1 + p["push"]), lens0),
            (D * 0.55, tgt1, sgn * orbit * 0.25, (pitch0 + pitch1) / 2, dist * (1 + p["push"] * 0.4),
             (lens0 + lens1) / 2),
            (D, tgt1, -sgn * orbit * 0.2, pitch1, dist, lens1)]
    beats = []
    for t_b, tg, yaw, pitch, dd, ln in plan:
        if space != "none":
            right = Vector((math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0.0))
            half_w = dd * 18.0 / ln     # half frame width at the subject (36 mm sensor)
            tg = tg + right * (half_w * 0.34 * (-1.0 if space == "left" else 1.0))
        pos = Vector(studio.look_from(tuple(tg), yaw, pitch, dd))
        beats.append(studio.Beat(t_b, tuple(pos), tuple(tg), ln))
    scr_c = _screen_centres(dev, s)
    rig = studio.CameraRig(beats, end_speed=0.6, handheld=0.06, fstop=studio.dof_fstop(radius * 1.3, 1.0),
                           seed=s.seed,
                           focus=lambda t, pos, tg: (Vector(scr_c[min(len(scr_c) - 1, max(0, round((t - s.t_start)
                                                                                                    * s.fps)))])
                                                     - Vector(pos)).length)
    rig.build(s)
    studio.finalize(s)


def _screen_centres(dev, s: studio.Shot) -> list:
    """World display centre per frame (evaluates the device animation once)."""
    out = []
    scn = bpy.context.scene
    for f in s.frames():
        scn.frame_set(f)
        out.append(tuple(dev.screen.obj.matrix_world @ Vector((0, 0, 0))))
    scn.frame_set(1)
    return out


def cues(sc) -> list:
    s = studio.shot(sc, PARAMS)
    on = s.dur * float(s.params.get("screen_on") or 0)
    out = [{"t": 0.0, "sfx": "whoosh_soft"}]
    if on > 0:
        out.append({"t": round(on + 0.1, 3), "sfx": "ui_on"})
    return out
