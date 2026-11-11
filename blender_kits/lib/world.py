"""Painterly anime world: gradient sunset sky with stylised clouds, sun + glow, layered mauve mountains, haze.

    world.sky(sc, palette="sunset", sun=(az_deg, el_deg), clock=clock_socket_owner)
    sun = world.sun_light(az_deg, el_deg)
    world.mountains(center=(0, 0, 0), seed=7)
    haze = world.haze_group()       # shader group: Color -> Color mixed toward the horizon haze by view distance

Palettes follow research/ref-flowerfield.md (AoT 'paths' sunset + the Pinterest meadow painting).
Everything is deterministic from the seed; clouds drift with a frame-keyed clock.
"""
from __future__ import annotations

import math
import random

from .nodes import NodeGraph, hex_rgb

PALETTES = {
    "sunset": {
        "sky": [(0.00, "#FCE6CF"), (0.06, "#FAD3B0"), (0.16, "#F4B9A6"), (0.30, "#EAA8BE"), (0.50, "#CBB1E0"),
                (0.75, "#A9A6DA"), (1.00, "#8C93CF")],
        "sky_away": [(0.00, "#F3D9D6"), (0.10, "#E9C1CC"), (0.30, "#D4B2D8"), (0.60, "#AFA6D9"), (1.00, "#8E93CC")],
        "sun": "#FFE6B8", "cloud_lit": "#FFE3DA", "cloud_mid": "#F0B9C9", "cloud_shade": "#A596CC",
        "haze": "#E8C4D2", "mountains": ["#7A62A8", "#9580BE", "#B6A3D2"], "ambient": 0.55,
    },
    "golden": {
        "sky": [(0.00, "#FFF0C8"), (0.08, "#FFD99A"), (0.22, "#F8C08E"), (0.45, "#E4B6C4"), (1.00, "#9DA8D8")],
        "sky_away": [(0.00, "#F6E4C8"), (0.20, "#E8CDC0"), (0.60, "#B9B4D8"), (1.00, "#93A0D2")],
        "sun": "#FFE9B0", "cloud_lit": "#FFF1DC", "cloud_mid": "#F6CDB4", "cloud_shade": "#AFA2C8",
        "haze": "#F1D9C6", "mountains": ["#7D6AA0", "#9886B8", "#BBAED0"], "ambient": 0.6,
    },
    "dawn": {
        "sky": [(0.00, "#F9E4E6"), (0.10, "#F3C9D8"), (0.30, "#D9B7E2"), (0.60, "#AEB4E4"), (1.00, "#8FA2D8")],
        "sky_away": [(0.00, "#EEDDE6"), (0.30, "#CDBCE0"), (1.00, "#8EA0D4")],
        "sun": "#FFF0E0", "cloud_lit": "#FFF0F2", "cloud_mid": "#EBC6DA", "cloud_shade": "#A0A2CF",
        "haze": "#E6D2E2", "mountains": ["#6F6AA6", "#8E8BC0", "#B3B2D8"], "ambient": 0.55,
    },
}


def sun_vector(az_deg: float, el_deg: float) -> tuple[float, float, float]:
    """Direction TO the sun. Azimuth 0 = +Y, 90 = +X."""
    a, e = math.radians(az_deg), math.radians(el_deg)
    return (math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))


def sky(palette: str = "sunset", sun: tuple[float, float] = (15.0, 7.0), seed: int = 7, fps: float = 30,
        frames: int = 300, t_offset: float = 0.0, cloud_cover: float = 0.55, cloud_scale: float = 1.0,
        ambient: float | None = None):
    """World shader: elevation gradient (warm toward the sun, lavender away), sun disc + glow, painterly clouds.
    ``ambient`` overrides the palette's ambient bounce strength (lighting only; the camera still sees the sky)."""
    import bpy  # noqa: PLC0415
    P = PALETTES[palette]
    w = bpy.data.worlds.new("sr_sky")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    g = NodeGraph(nt)
    sv = sun_vector(*sun)
    tc = g.node("ShaderNodeTexCoord")
    d = g.vmath("NORMALIZE", tc.outputs["Generated"])
    dx, dy, dz = g.sep(d)
    # elevation 0..1 (sqrt spreads the warm band near the horizon)
    el = g.math("SQRT", g.math("MAXIMUM", dz, 0.0))
    toward = g.ramp(el, [(p, hex_rgb(c)) for p, c in P["sky"]])
    away = g.ramp(el, [(p, hex_rgb(c)) for p, c in P["sky_away"]])
    # horizontal sun-facing factor
    sh = (sv[0], sv[1], 0.0)
    n = math.hypot(sh[0], sh[1]) or 1
    hd = g.vmath("NORMALIZE", g.xyz(dx, dy, 0.0))
    face = g.vmath("DOT_PRODUCT", hd, (sh[0] / n, sh[1] / n, 0.0))
    face01 = g.map_range(face, -1.0, 1.0, 0.0, 1.0)
    face_s = g.math("POWER", face01, 1.6)
    col = g.mix_rgb(face_s, away, toward)
    # sun glow + disc
    cosang = g.vmath("DOT_PRODUCT", d, sv)
    c0 = g.math("MAXIMUM", cosang, 0.0)
    glow = g.math("ADD", g.math("MULTIPLY", g.math("POWER", c0, 900.0), 2.2),
                  g.math("MULTIPLY", g.math("POWER", c0, 24.0), 0.45))
    glow = g.math("ADD", glow, g.math("MULTIPLY", g.math("POWER", c0, 4.0), 0.12))
    disc = g.map_range(cosang, math.cos(math.radians(1.25)), math.cos(math.radians(0.95)), 0.0, 9.0)
    sun_c = hex_rgb(P["sun"])
    col = g.mix_rgb(g.math("MINIMUM", glow, 1.0), col, sun_c, "ADD")
    # clouds: project onto a high plane; clock drifts them
    clock = g.node("ShaderNodeValue", label="clock")
    clock.outputs[0].default_value = t_offset
    from .nodes import keyed_time  # noqa: PLC0415
    keyed_time(clock.outputs[0], "default_value", fps, frames, t_offset)
    zc = g.math("ADD", g.math("MAXIMUM", dz, 0.0), 0.075)
    rng = random.Random(seed)
    ox, oy = rng.uniform(-50, 50), rng.uniform(-50, 50)
    u = g.math("ADD", g.math("DIVIDE", dx, zc), g.math("ADD", g.math("MULTIPLY", clock.outputs[0], 0.006), ox))
    v = g.math("ADD", g.math("DIVIDE", dy, zc), g.math("ADD", g.math("MULTIPLY", clock.outputs[0], 0.0025), oy))
    uv = g.xyz(g.math("MULTIPLY", u, 0.55 * cloud_scale), g.math("MULTIPLY", v, 1.1 * cloud_scale), rng.uniform(0, 9))
    nz = g.node("ShaderNodeTexNoise", {"Vector": uv, "Scale": 1.0, "Detail": 7.0, "Roughness": 0.58,
                                       "Distortion": 0.35}, noise_dimensions="3D")
    nz2 = g.node("ShaderNodeTexNoise", {"Vector": uv, "Scale": 6.0, "Detail": 3.0, "Roughness": 0.5},
                 noise_dimensions="3D")
    dens = g.map_range(nz.outputs["Factor"], 1.0 - cloud_cover * 0.9, 1.0 - cloud_cover * 0.62, 0.0, 1.0,
                       interp="SMOOTHSTEP")
    band = g.map_range(dz, 0.015, 0.11, 0.0, 1.0, interp="SMOOTHSTEP")      # thin out at the horizon
    top = g.map_range(dz, 0.55, 0.95, 1.0, 0.45, interp="SMOOTHSTEP")
    dens = g.math("MULTIPLY", g.math("MULTIPLY", dens, band), top)
    # cloud colour: warm lit undersides toward the sun / near the horizon, lavender shade elsewhere
    lit = g.math("ADD", g.math("MULTIPLY", face_s, 0.75), g.math("MULTIPLY", g.math("SUBTRACT", 0.5, dz), 0.6))
    lit = g.math("ADD", lit, g.math("MULTIPLY", g.math("SUBTRACT", nz2.outputs["Factor"], 0.5), 0.7))
    cc = g.ramp(g.math("MINIMUM", g.math("MAXIMUM", lit, 0.0), 1.0),
                [(0.0, hex_rgb(P["cloud_shade"])), (0.55, hex_rgb(P["cloud_mid"])), (1.0, hex_rgb(P["cloud_lit"]))])
    # rim glow on clouds near the sun
    rim = g.math("MULTIPLY", g.math("POWER", c0, 10.0), 1.4)
    cc = g.mix_rgb(g.math("MINIMUM", rim, 1.0), cc, sun_c, "ADD")
    col = g.mix_rgb(g.math("MULTIPLY", dens, 0.93), col, cc)
    col = g.mix_rgb(g.math("MULTIPLY", disc, g.math("SUBTRACT", 1.0, dens)), col, sun_c, "ADD")
    # camera sees the painted sky; lighting gets a dimmer ambient
    lp = g.node("ShaderNodeLightPath")
    bg_cam = g.node("ShaderNodeBackground", {"Color": col, "Strength": 1.0})
    bg_amb = g.node("ShaderNodeBackground", {"Color": col, "Strength": P["ambient"] if ambient is None else ambient})
    mix = g.node("ShaderNodeMixShader")
    g.link(lp.outputs["Is Camera Ray"], mix.inputs[0])
    g.link(bg_amb.outputs[0], mix.inputs[1])
    g.link(bg_cam.outputs[0], mix.inputs[2])
    out = g.node("ShaderNodeOutputWorld")
    g.link(mix.outputs[0], out.inputs["Surface"])
    return w


def sun_light(az_deg: float = 15.0, el_deg: float = 7.0, color: str = "#FFD9B0", strength: float = 3.2,
              angle_deg: float = 2.0):
    """Sun lamp shining FROM (az, el)."""
    import bpy  # noqa: PLC0415
    from mathutils import Vector  # noqa: PLC0415
    ld = bpy.data.lights.new("sun", "SUN")
    ld.energy = strength
    ld.color = hex_rgb(color)
    ld.angle = math.radians(angle_deg)
    ob = bpy.data.objects.new("sun", ld)
    bpy.context.scene.collection.objects.link(ob)
    to_sun = Vector(sun_vector(az_deg, el_deg))
    ob.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    return ob


def haze_group(color: str = "#E8C4D2", start: float = 40.0, half: float = 320.0, max_amt: float = 0.8):
    """Shader node group 'sr_haze': mixes a colour toward ``color`` by camera distance (aerial perspective)."""
    import bpy  # noqa: PLC0415
    if "sr_haze" in bpy.data.node_groups:
        return bpy.data.node_groups["sr_haze"]
    ng = bpy.data.node_groups.new("sr_haze", "ShaderNodeTree")
    ng.interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
    ng.interface.new_socket("Amount", in_out="INPUT", socket_type="NodeSocketFloat").default_value = 1.0
    ng.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    g = NodeGraph(ng)
    gi = g.node("NodeGroupInput")
    go = g.node("NodeGroupOutput")
    cam = g.node("ShaderNodeCameraData")
    dist = g.math("MAXIMUM", g.math("SUBTRACT", cam.outputs["View Distance"], start), 0.0)
    # 1 - 2^(-d/half)
    f = g.math("SUBTRACT", 1.0, g.math("POWER", 2.0, g.math("DIVIDE", g.math("MULTIPLY", dist, -1.0), half)))
    f = g.math("MULTIPLY", g.math("MULTIPLY", f, max_amt), gi.outputs[1])
    col = g.mix_rgb(f, gi.outputs[0], hex_rgb(color))
    g.link(col, go.inputs[0])
    return ng


def toon_group():
    """Shader group 'sr_toon': cel-shaded emission (lit/shade colours from one base) with sun-rim and haze."""
    import bpy  # noqa: PLC0415
    if "sr_toon" in bpy.data.node_groups:
        return bpy.data.node_groups["sr_toon"]
    ng = bpy.data.node_groups.new("sr_toon", "ShaderNodeTree")
    for name, typ, dv in (("Color", "NodeSocketColor", None), ("Shade", "NodeSocketColor", None),
                          ("Rim", "NodeSocketFloat", 0.0), ("Haze", "NodeSocketFloat", 1.0),
                          ("Soft", "NodeSocketFloat", 0.12), ("Translucent", "NodeSocketFloat", 0.0)):
        s = ng.interface.new_socket(name, in_out="INPUT", socket_type=typ)
        if dv is not None:
            s.default_value = dv
    ng.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    g = NodeGraph(ng)
    gi = g.node("NodeGroupInput")
    go = g.node("NodeGroupOutput")
    diff = g.node("ShaderNodeBsdfDiffuse", {"Color": (1, 1, 1)})
    s2r = g.node("ShaderNodeShaderToRGB")
    g.link(diff.outputs[0], s2r.inputs[0])
    lum = g.node("ShaderNodeRGBToBW")
    g.link(s2r.outputs[0], lum.inputs[0])
    lo = g.math("SUBTRACT", 0.32, gi.outputs["Soft"])
    hi = g.math("ADD", 0.32, gi.outputs["Soft"])
    mr = g.node("ShaderNodeMapRange", {"Value": lum.outputs[0], "From Min": lo, "From Max": hi},
                interpolation_type="SMOOTHSTEP")
    lit = g.mix_rgb(mr.outputs[0], gi.outputs["Shade"], gi.outputs["Color"])
    # backlit translucency (petals/grass glow when the sun is behind them) + fresnel rim
    lw = g.node("ShaderNodeLayerWeight", {"Blend": 0.35})
    rim = g.math("MULTIPLY", lw.outputs["Fresnel"], gi.outputs["Rim"])
    lit = g.mix_rgb(g.math("MINIMUM", rim, 1.0), lit, (1.0, 0.86, 0.72), "ADD")
    tr = g.math("MULTIPLY", g.math("SUBTRACT", 1.0, mr.outputs[0]), gi.outputs["Translucent"])
    lit = g.mix_rgb(g.math("MINIMUM", tr, 1.0), lit, (1.0, 0.75, 0.6), "SCREEN")
    hz = g.node("ShaderNodeGroup")
    hz.node_tree = haze_group()
    g.link(lit, hz.inputs[0])
    g.link(gi.outputs["Haze"], hz.inputs[1])
    em = g.node("ShaderNodeEmission", {"Strength": 1.0})
    g.link(hz.outputs[0], em.inputs[0])
    g.link(em.outputs[0], go.inputs[0])
    return ng


def toon_material(name: str, color: str | tuple, shade: str | tuple | None = None, rim: float = 0.0,
                  haze: float = 1.0, soft: float = 0.12, translucent: float = 0.0, color_socket=None):
    """Material using sr_toon. ``shade`` defaults to a darker, cooler version of ``color``."""
    import bpy  # noqa: PLC0415
    c = hex_rgb(color) if isinstance(color, str) else color
    if shade is None:
        sh = (c[0] * 0.42 + 0.03, c[1] * 0.38 + 0.025, c[2] * 0.5 + 0.06)
    else:
        sh = hex_rgb(shade) if isinstance(shade, str) else shade
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    g = NodeGraph(nt)
    grp = g.node("ShaderNodeGroup")
    grp.node_tree = toon_group()
    g.set(grp, "Color", c)
    g.set(grp, "Shade", sh)
    g.set(grp, "Rim", rim)
    g.set(grp, "Haze", haze)
    g.set(grp, "Soft", soft)
    g.set(grp, "Translucent", translucent)
    out = g.node("ShaderNodeOutputMaterial")
    g.link(grp.outputs[0], out.inputs["Surface"])
    return m, g, grp


def mountains(center=(0.0, 0.0, 0.0), palette: str = "sunset", seed: int = 7,
              layers: tuple = ((2600, 420, 0.9), (1700, 260, 0.75), (1050, 150, 0.6)), segs: int = 900):
    """Ring ridgelines (far → near) as flat painterly emission curtains with base mist."""
    import bpy  # noqa: PLC0415
    import bmesh  # noqa: PLC0415
    P = PALETTES[palette]
    rng = random.Random(seed * 31 + 5)
    objs = []
    cols = list(reversed(P["mountains"]))   # far = lightest
    for li, (R, H, rough) in enumerate(layers):
        waves = [(rng.randint(3, 6) * (k + 1) ** 1.35, rng.uniform(0, 6.283), 0.62 ** k) for k in range(6)]
        norm = sum(amp for _, _, amp in waves)
        bm = bmesh.new()
        top, bot = [], []
        for i in range(segs):
            a = 2 * math.pi * i / segs
            # ridged noise: sharp peaks, soft valleys
            hval = sum(amp * (1.0 - abs(math.sin(f * a * 0.5 + ph))) ** 2 for f, ph, amp in waves) / norm
            z = H * (0.18 + 0.95 * hval ** 1.35)
            x, y = center[0] + R * math.sin(a), center[1] + R * math.cos(a)
            top.append(bm.verts.new((x, y, center[2] + z)))
            bot.append(bm.verts.new((x, y, center[2] - 60.0)))
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((bot[i], bot[j], top[j], top[i]))
        me = bpy.data.meshes.new(f"mount{li}")
        bm.to_mesh(me)
        bm.free()
        m = bpy.data.materials.new(f"mount{li}")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        g = NodeGraph(nt)
        geo = g.node("ShaderNodeNewGeometry")
        _, _, pz = g.sep(geo.outputs["Position"])
        hz = g.map_range(pz, center[2] - 5, center[2] + H * 0.75, 0.0, 1.0, interp="SMOOTHSTEP")
        base_c = hex_rgb(cols[li])
        mist = hex_rgb(P["haze"])
        nb = g.node("ShaderNodeTexNoise", {"Vector": geo.outputs["Position"], "Scale": 0.02, "Detail": 4.0})
        tint = g.mix_rgb(g.math("MULTIPLY", g.math("SUBTRACT", nb.outputs["Factor"], 0.5), 0.35), base_c,
                         (base_c[0] * 1.25, base_c[1] * 1.1, base_c[2] * 1.15))
        c = g.mix_rgb(g.math("SUBTRACT", 1.0, hz), tint, mist)
        em = g.node("ShaderNodeEmission", {"Strength": 1.0})
        g.link(c, em.inputs[0])
        out = g.node("ShaderNodeOutputMaterial")
        g.link(em.outputs[0], out.inputs["Surface"])
        me.materials.append(m)
        ob = bpy.data.objects.new(f"mountains{li}", me)
        bpy.context.scene.collection.objects.link(ob)
        ob.visible_shadow = False
        objs.append(ob)
    return objs
