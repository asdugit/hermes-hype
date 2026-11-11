"""product_hero — a 3D product revealed in a premium studio: light sweep, slow orbit / dolly / turntable / macro."""
from __future__ import annotations

import math

from mathutils import Vector

from ..lib import studio
from . import _common as cm

PARAMS = {
    "model": {"type": "asset", "default": None,
              "doc": "3D model asset name or path (glb/gltf/obj/fbx/stl/ply/usd/usdz/blend); default = the job "
                     "product. 2D media falls back to an exact-colour card"},
    "move": {"type": "enum", "values": ["orbit", "dolly", "turntable", "macro"], "default": "orbit",
             "doc": "orbit = slow eased arc; dolly = straight push-in; turntable = product turns, camera nearly "
                    "still; macro = close detail pass along the surface with shallow focus"},
    "env": {"type": "enum", "values": ["studio", "light", "sunset", "accent", "noir"], "default": "studio",
            "doc": "stage preset: dark graphite cyc | bright white | warm sunset | cyc pooled in the accent colour | noir = night: one hard spot key, venetian-blind light through haze, wet mirror floor"},
    "accent": {"type": "color", "default": None, "doc": "accent colour for env=accent"},
    "floor": {"type": "enum", "values": ["reflective", "matte"], "default": "reflective",
              "doc": "glossy floor with a soft reflection, or matte"},
    "reveal": {"type": "bool", "default": True,
               "doc": "lights come up from darkness (rims first: silhouette) while a strip light sweeps the body"},
    "yaw": {"type": "float", "default": -35.0, "min": -180.0, "max": 180.0,
            "doc": "camera start angle around the product (0 = model front / -Y side, negative = from the left)"},
    "orbit_deg": {"type": "float", "default": 30.0, "min": 0.0, "max": 120.0, "doc": "camera arc (orbit/dolly)"},
    "turn_deg": {"type": "float", "default": 70.0, "min": 0.0, "max": 720.0, "doc": "product rotation (turntable)"},
    "pitch": {"type": "float", "default": 10.0, "min": -5.0, "max": 60.0, "doc": "camera elevation (degrees)"},
    "fill": {"type": "float", "default": 0.72, "min": 0.3, "max": 0.98,
             "doc": "product size in frame (fraction of width; 9:16 frames the height)"},
    "wheel_rps": {"type": "float", "default": 0.0, "min": -5.0, "max": 5.0,
                  "doc": "wheel spin (rev/s) when wheels are detected; 0 = parked"},
    "paint": {"type": "color", "default": None,
              "doc": "recolour the body paint (largest non-glass material), e.g. '#b5121b'; default keeps the model's"},
    "exposure": {"type": "float", "default": -0.6, "min": -3.0, "max": 2.0,
                 "doc": "exposure (EV); the default keeps saturated paints deep under AgX (at 0 a red washed to salmon)"},
    "clearcoat": {"type": "enum", "values": ["auto", "on", "off"], "default": "auto",
                  "doc": "add a clear coat to the body paint (auto: vehicles, i.e. wheels detected)"},
    "haze": {"type": "float", "default": 1.0, "min": 0.0, "max": 2.5,
             "doc": "env=noir: smoke/haze density (beams visible); 0 = clear air"},
    "view": {"type": "enum", "values": ["agx", "standard", "filmic"], "default": "agx",
             "doc": "tone mapping: agx (soft highlight roll-off, best for 3D) | standard (exact colours)"},
    "size_m": {"type": "float", "default": None, "doc": "force the product's largest dimension (m); default keeps "
                                                      "real-world size when plausible"},
}
DESCRIBE = ("3D product hero in a premium studio: from darkness the rims draw the silhouette, a strip light sweeps "
            "across the body, key + top fill come up; slow eased camera orbit (or dolly / turntable / macro detail "
            "pass) on a reflective cyc with a soft floor reflection; clear-coated paint, wheels parked or spinning.")


def build(sc) -> None:
    s = studio.shot(sc, PARAMS)
    p = s.params
    studio.setup_render(s, view=p["view"], look="punchy", exposure=float(p.get("exposure") or 0.0))
    sub = cm.load_subject(s)
    cm.upgrade_paint(sub, p["clearcoat"], p.get("paint"))
    r = sub.radius
    c = sub.center
    D = s.dur
    lens = 50.0 if p["move"] != "macro" else 65.0
    # framing: fit the product's projected extent (diagonal-ish for 3/4 views)
    w_fit = max(sub.size[0], sub.size[1]) * 0.92 + min(sub.size[0], sub.size[1]) * 0.35
    h_fit = sub.size[2] * 1.15
    if s.vertical:
        w_fit *= 0.62
    dist = studio.fit_distance(w_fit, h_fit, lens, s.aspect, p["fill"])
    st = studio.stage(s, preset=p["env"], center=tuple(c), radius=r, accent=str(p.get("accent") or "#ff5a3c"),
                      floor=p["floor"], sweep=bool(p["reveal"]), key_side=-1.0 if p["yaw"] <= 0 else 1.0,
                      cam_dist=dist, haze=float(p.get("haze") or 0.0))
    if p["reveal"]:
        # starts ahead of the cut: frame 1 already shows the rim-lit silhouette (a film never opens on black)
        studio.animate_reveal(s, st, t0=-min(1.2, D * 0.15), t1=D * 0.55, from_level=0.12)
        studio.animate_sweep(s, st, t0=D * 0.08, t1=D * 0.75, center=tuple(c), radius=r, energy=420.0,
                             height=0.9)
    yaw, pitch, arc = p["yaw"], p["pitch"], p["orbit_deg"]
    tgt = (c.x, c.y, c.z * 0.85)
    move = p["move"]
    if move == "turntable":
        for f in s.frames():
            sub.pivot.rotation_euler = (0, 0, math.radians(p["turn_deg"]) * studio.ease(s.t(f) / D, "inout", 0.5))
            sub.pivot.keyframe_insert("rotation_euler", frame=f)
        beats = [studio.Beat(0, studio.look_from(tgt, yaw, pitch + 2, dist * 1.04), tgt, lens),
                 studio.Beat(D, studio.look_from(tgt, yaw + 4, pitch, dist), tgt, lens)]
        fstop = studio.dof_fstop(r * 2.2)
    elif move == "dolly":
        beats = [studio.Beat(0, studio.look_from(tgt, yaw, pitch + 3, dist * 1.35), tgt, lens * 0.9),
                 studio.Beat(D, studio.look_from(tgt, yaw + arc * 0.25, pitch, dist * 0.95), tgt, lens)]
        fstop = studio.dof_fstop(r * 2.0)
    elif move == "macro":
        beats, fstop = _macro_beats(sub, D, yaw, lens)
    else:  # orbit
        beats = [studio.Beat(0, studio.look_from(tgt, yaw, pitch + 4, dist * 1.08), tgt, lens),
                 studio.Beat(D * 0.5, studio.look_from(tgt, yaw + arc * 0.5, pitch + 2, dist * 1.03), tgt, lens),
                 studio.Beat(D, studio.look_from(tgt, yaw + arc, pitch, dist), tgt, lens)]
        fstop = studio.dof_fstop(r * 2.0)
    cm.spin(sub, s, p["wheel_rps"])
    studio.CameraRig(beats, end_speed=0.7, handheld=0.04 if move != "macro" else 0.08, fstop=fstop,
                     seed=s.seed).build(s)
    studio.finalize(s)


def _macro_beats(sub: cm.Subject, D: float, yaw: float, lens: float) -> tuple[list, float]:
    """Close pass along the camera-facing flank at ~55 % height, focus riding the surface."""
    sx, sy, sz = sub.size
    along = 0 if sx >= sy else 1  # long axis
    half_l = (sx if along == 0 else sy) / 2
    half_w = (sy if along == 0 else sx) / 2
    side = -1.0  # camera on the -Y (or -X) flank
    z = sz * 0.55
    d = max(sz * 0.55, 0.06)

    def pt(u: float, off: float) -> tuple:
        a = half_l * u
        b = side * (half_w + off)
        return (a, b, z) if along == 0 else (b, a, z)

    beats = [studio.Beat(0, pt(0.78, d), pt(0.55, 0), lens),
             studio.Beat(D * 0.5, pt(0.45, d * 0.9), pt(0.2, 0), lens),
             studio.Beat(D, pt(0.12, d), pt(-0.12, 0), lens)]
    _ = Vector, yaw
    return beats, max(1.4, 2.0 * (sz / 1.4) ** 0.5)


def cues(sc) -> list:
    s = studio.shot(sc, PARAMS)
    out = []
    if s.params.get("reveal"):
        out += [{"t": 0.0, "sfx": "riser"}, {"t": round(s.dur * 0.42, 3), "sfx": "whoosh_soft"}]
    return out
