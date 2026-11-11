"""Render look: EEVEE settings per tier + the anime grade compositor (bloom, shoulder, split-tone, vignette, CA).

    look.setup(sc, tier)                    # engine, samples, motion blur, colour management ("Standard")
    g = look.grade(sc, preset="anime_sunset")  # compositor; returns {"amount": socket, ...} for keying

Colour management is "Standard" on purpose: emissive image planes (handoff stills, screenshots) then reproduce
their sRGB pixels exactly when the grade ``amount`` is 0; highlights get a soft tanh shoulder in the compositor
instead of a view transform. Film grain is left to the browser finish pass (film.json ``finish``).
"""
from __future__ import annotations

import math

from .nodes import NodeGraph, hex_rgb

TIERS = {
    # samples, motion blur, raytracing, shadow quality, volumetric samples
    "preview": {"samples": 12, "motion_blur": False, "raytrace": False, "shadow_rays": 1, "fast_gi": False},
    "final": {"samples": 40, "motion_blur": True, "raytrace": True, "shadow_rays": 2, "fast_gi": True},
    "max": {"samples": 96, "motion_blur": True, "raytrace": True, "shadow_rays": 3, "fast_gi": True},
}

PRESETS = {
    "anime_sunset": {"bloom": 0.55, "bloom_threshold": 0.92, "bloom_size": 0.75, "shoulder": 0.78,
                     "lift": "#7E6FA8", "lift_amt": 0.02, "gain": "#FFE7D2", "gain_amt": 1.0, "sat": 1.16,
                     "vignette": 0.30, "dispersion": 0.010, "contrast": 1.10},
    "studio": {"bloom": 0.25, "bloom_threshold": 1.0, "bloom_size": 0.6, "shoulder": 0.8, "lift": "#202028",
               "lift_amt": 0.0, "gain": "#FFFFFF", "gain_amt": 1.0, "sat": 1.0, "vignette": 0.22, "dispersion": 0.0,
               "contrast": 1.0},
}


def _try(obj, attr: str, value) -> bool:
    try:
        setattr(obj, attr, value)
        return True
    except (AttributeError, TypeError, ValueError) as ex:
        print(f"WARN look: {type(obj).__name__}.{attr}: {ex}")
        return False


def setup(sc, tier: str = "preview", *, exposure: float = 0.0, transparent: bool = False) -> dict:
    """Engine + tier settings. ``sc`` = SceneCtx (uses sc.res) or a bpy Scene."""
    import bpy  # noqa: PLC0415
    s = bpy.context.scene
    cfg = TIERS.get(tier, TIERS["preview"])
    s.render.engine = "BLENDER_EEVEE"
    ee = s.eevee
    _try(ee, "taa_render_samples", cfg["samples"])
    _try(ee, "use_raytracing", cfg["raytrace"])
    _try(ee, "use_fast_gi", cfg["fast_gi"])
    _try(ee, "shadow_ray_count", cfg["shadow_rays"])
    _try(ee, "use_shadows", True)
    s.render.use_motion_blur = cfg["motion_blur"]
    s.render.motion_blur_shutter = 0.5
    _try(ee, "motion_blur_steps", 1)
    s.render.film_transparent = transparent
    s.view_settings.view_transform = "Standard"
    _try(s.view_settings, "look", "None")
    s.view_settings.exposure = exposure
    s.view_settings.gamma = 1.0
    s.render.use_compositing = True
    s.render.dither_intensity = 1.0
    return cfg


def grade(sc=None, preset: str = "anime_sunset", **over) -> dict:
    """Build the compositor grade. Returns sockets to key: amount (0 = untouched render), bloom, vignette."""
    import bpy  # noqa: PLC0415
    s = bpy.context.scene
    p = dict(PRESETS[preset], **over)
    ng = bpy.data.node_groups.new("sr_grade", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    if hasattr(s, "compositing_node_group"):
        s.compositing_node_group = ng
    g = NodeGraph(ng)
    rl = g.node("CompositorNodeRLayers")
    src = rl.outputs["Image"]
    # bloom (on linear scene values)
    gl = g.node("CompositorNodeGlare", {"Image": src})
    _menu(gl, "Type", ("Bloom", "BLOOM"))
    _menu(gl, "Quality", ("High", "HIGH"))
    for k, v in (("Threshold", p["bloom_threshold"]), ("Strength", p["bloom"]), ("Size", p["bloom_size"]),
                 ("Smoothness", 0.6)):
        try:
            g.set(gl, k, v)
        except KeyError:
            pass
    img = gl.outputs["Image"]
    # tanh highlight shoulder per channel: y = min(x,k) + (1-k) tanh(max(x-k,0)/(1-k))
    k = p["shoulder"]
    sp = g.node("CompositorNodeSeparateColor", {"Image": img})
    chans = []
    for i in range(3):
        x = sp.outputs[i]
        over_ = g.math("MAXIMUM", g.math("SUBTRACT", x, k), 0.0)
        t = g.math("TANH", g.math("DIVIDE", over_, 1 - k))
        chans.append(g.math("ADD", g.math("MINIMUM", x, k), g.math("MULTIPLY", t, 1 - k)))
    cb = g.node("CompositorNodeCombineColor")
    for i in range(3):
        g.set(cb, i, chans[i])
    g.set(cb, 3, sp.outputs[3])
    img = cb.outputs[0]
    # split tone: lilac lift in the shadows, warm gain in the highlights (offset/power/slope = ASC-CDL)
    lift = hex_rgb(p["lift"])
    cbal = g.node("CompositorNodeColorBalance", {"Image": img})
    _menu(cbal, "Type", ("Offset/Power/Slope (ASC-CDL)", "OFFSET_POWER_SLOPE", "Lift/Gamma/Gain", "LIFT_GAMMA_GAIN"))
    try:
        offs = [s_ for s_ in cbal.inputs if s_.name == "Offset" and s_.type == "RGBA"][0]
        offs.default_value = (*(c * p["lift_amt"] for c in lift), 1.0)
        slope = [s_ for s_ in cbal.inputs if s_.name == "Slope" and s_.type == "RGBA"]
        if slope:
            slope[0].default_value = (*hex_rgb(p["gain"]), 1.0)
    except (IndexError, AttributeError) as ex:
        print("WARN look: colour balance", ex)
    img = cbal.outputs[0]
    hs = g.node("CompositorNodeHueSat", {"Image": img, "Saturation": p["sat"]})
    img = hs.outputs[0]
    bc = g.node("CompositorNodeBrightContrast", {"Image": img, "Contrast": (p["contrast"] - 1) * 100})
    img = bc.outputs[0]
    # chromatic edge (aesthetic lens)
    if p["dispersion"] > 0:
        ld = g.node("CompositorNodeLensdist", {"Image": img, "Dispersion": p["dispersion"]})
        img = ld.outputs[0]
    # vignette: soft ellipse
    w, h = s.render.resolution_x, s.render.resolution_y
    em = g.node("CompositorNodeEllipseMask", {"Position": (0.5, 0.5), "Size": (0.92, 0.92)})
    try:
        g.set(em, "Value", 1.0)
    except KeyError:
        pass
    bl = g.node("CompositorNodeBlur", {"Image": em.outputs[0], "Size": (w * 0.22, h * 0.22)})
    vig_amt = g.node("ShaderNodeValue")
    vig_amt.outputs[0].default_value = p["vignette"]
    vig = g.math("ADD", g.math("MULTIPLY", g.math("SUBTRACT", 1.0, sock0(bl)), g.math("MULTIPLY", vig_amt.outputs[0], -1.0)), 1.0)
    mul = g.mix_rgb(1.0, img, (1, 1, 1), "MULTIPLY")
    # feed vignette value as colour B
    mnode = mul.node
    g.set(mnode, 7, _grey(g, vig))
    img = mul
    # amount: 0 = untouched render (used to land exactly on a handoff still), 1 = full grade
    amt = g.node("ShaderNodeValue")
    amt.outputs[0].default_value = 1.0
    out = g.mix_rgb(amt.outputs[0], src, img)
    go = g.node("NodeGroupOutput")
    g.link(out, go.inputs[0])
    return {"amount": amt.outputs[0], "vignette": vig_amt.outputs[0], "tree": ng}


def sock0(node):
    return node.outputs[0]


def _grey(g: NodeGraph, v):
    n = g.node("CompositorNodeCombineColor")
    for i in range(3):
        g.set(n, i, v)
    g.set(n, 3, 1.0)
    return n.outputs[0]


def _menu(node, name: str, options: tuple) -> None:
    sock = None
    for s_ in node.inputs:
        if s_.name == name:
            sock = s_
            break
    if sock is None:
        return
    for o in options:
        try:
            sock.default_value = o
            return
        except (TypeError, ValueError):
            continue
    print(f"WARN look: menu {name} none of {options}")


def key_value(sock, frames_values: list[tuple[int, float]]) -> None:
    """Key a Value-node socket at (frame, value) pairs, smooth (Bezier auto-clamped)."""
    for f, v in frames_values:
        sock.default_value = v
        sock.keyframe_insert("default_value", frame=f)


def lens_for(size: str) -> tuple[float, float]:
    """Lens table (Look v2): shot size -> (lens mm, f-stop)."""
    return {"ECU": (85, 2.0), "CU": (70, 2.2), "MCU": (60, 2.8), "MS": (50, 3.5), "MWS": (40, 4.0),
            "WS": (32, 5.6), "EWS": (24, 8.0)}.get(size, (35, 4.0))


def degrees(x: float) -> float:
    return math.degrees(x)
