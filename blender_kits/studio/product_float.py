"""product_float — the product floats and slowly turns in a stylised studio; wheels spin when present."""
from __future__ import annotations

import math

from ..lib import studio
from . import _common as cm

PARAMS = {
    "model": {"type": "asset", "default": None,
              "doc": "3D model asset name or path; default = the job product (2D media -> exact-colour card)"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent"], "default": "accent",
            "doc": "stage preset (accent = dark cyc pooled in the product accent colour)"},
    "accent": {"type": "color", "default": None, "doc": "accent colour (default: warm red)"},
    "height": {"type": "float", "default": 0.32, "min": 0.05, "max": 1.5,
               "doc": "hover height as a fraction of the product height (its shadow on the floor sells the float)"},
    "turn_deg": {"type": "float", "default": 40.0, "min": -360.0, "max": 360.0,
                 "doc": "product rotation across the shot (eased)"},
    "yaw": {"type": "float", "default": -30.0, "min": -180.0, "max": 180.0, "doc": "camera angle around"},
    "pitch": {"type": "float", "default": 6.0, "min": -10.0, "max": 45.0, "doc": "camera elevation"},
    "bob": {"type": "float", "default": 0.03, "min": 0.0, "max": 0.2,
            "doc": "hover bob amplitude (fraction of product height)"},
    "wheel_rps": {"type": "float", "default": 0.6, "min": -5.0, "max": 5.0, "doc": "wheel spin when detected"},
    "fill": {"type": "float", "default": 0.66, "min": 0.3, "max": 0.98, "doc": "product size in frame"},
    "view": {"type": "enum", "values": ["agx", "standard", "filmic"], "default": "agx", "doc": "tone mapping"},
    "paint": {"type": "color", "default": None,
              "doc": "recolour the body paint (largest non-glass material), e.g. '#b5121b'; default keeps the model's"},
    "exposure": {"type": "float", "default": -0.6, "min": -3.0, "max": 2.0,
                 "doc": "exposure (EV); the default keeps saturated paints deep under AgX (at 0 a red washed to salmon)"},
    "clearcoat": {"type": "enum", "values": ["auto", "on", "off"], "default": "auto", "doc": "body paint clear coat"},
    "size_m": {"type": "float", "default": None, "doc": "force the largest dimension (m)"},
}
DESCRIBE = ("The product hovers above a dark cyc pooled in its accent colour, turning slowly and bobbing; its soft "
            "shadow on the floor sells the float; wheels spin; slow dolly with a gentle arc, rim lights trace the "
            "silhouette.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    studio.setup_render(s, view=p["view"], look="punchy", exposure=float(p.get("exposure") or 0.0))
    sub = cm.load_subject(s)
    cm.upgrade_paint(sub, p["clearcoat"], p.get("paint"))
    H = sub.size[2]
    lift = H * p["height"]
    c = sub.center
    c.z += lift
    r = sub.radius
    D = s.dur
    lens = 50.0
    w_fit = max(sub.size[0], sub.size[1]) * 0.9 + min(sub.size[0], sub.size[1]) * 0.35
    if s.vertical:
        w_fit *= 0.62
    dist = studio.fit_distance(w_fit, (H + lift) * 1.2, lens, s.aspect, p["fill"])
    studio.stage(s, preset=p["env"], center=tuple(c), radius=r, accent=str(p.get("accent") or "#ff4d2e"),
                 floor="matte", key_side=-1.0 if p["yaw"] <= 0 else 1.0, cam_dist=dist)
    for f in s.frames():
        t = s.t(f)
        u = studio.ease(t / D, "inout", 0.4)
        sub.pivot.location = (0, 0, lift + H * studio.wobble(t, s.seed, p["bob"], (0.18, 0.31)))
        sub.pivot.rotation_euler = (math.radians(studio.wobble(t, s.seed + 3, 1.2, (0.15, 0.27))),
                                    math.radians(studio.wobble(t, s.seed + 5, 1.0, (0.12, 0.23))),
                                    math.radians(p["turn_deg"]) * u)
        sub.pivot.keyframe_insert("location", frame=f)
        sub.pivot.keyframe_insert("rotation_euler", frame=f)
    cm.spin(sub, s, p["wheel_rps"])
    tgt = (c.x, c.y, c.z)
    yaw, pitch = p["yaw"], p["pitch"]
    beats = [studio.Beat(0.0, studio.look_from(tgt, yaw - 6, pitch + 3, dist * 1.12), tgt, lens),
             studio.Beat(D, studio.look_from(tgt, yaw + 6, pitch, dist), tgt, lens)]
    studio.CameraRig(beats, end_speed=0.9, handheld=0.05, fstop=studio.dof_fstop(r * 2.0), seed=s.seed).build(s)
    studio.finalize(s)


def cues(sc) -> list:
    return [{"t": 0.0, "sfx": "whoosh_soft"}]
