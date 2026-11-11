"""Petals: ambient drifting petals (many depths, tumbling, wind-carried) and the image 'petal sheet' transition.

    petals.drift(center=(0, 0, 2), size=(70, 70, 14), count=1600, wind=(1.4, 0.5, 0.15), fps=30, dur=25)
    sheet = petals.sheet(cam, image_path, res=(1920, 1080), t_start=0.15, spread=0.9, origin=(0.11, 0.82))

The sheet tiles the camera frame with square cells that show the handoff still (nearest-neighbour sampling, so
pixel art stays crisp). Each cell peels after a delay that spreads out from ``origin`` (normalised frame coords,
e.g. the clicked BUY button), flips to show a petal-pink back, morphs to a petal silhouette and blows toward and
past the camera. All motion is computed in geometry nodes from Scene Time: deterministic, motion-blur friendly.
"""
from __future__ import annotations

import math
import random

from .nodes import NodeGraph, hex_rgb

PETAL_COLS = ["#F2A3B3", "#F7C6D4", "#FFF4F0", "#F6B48F", "#F2D35A", "#E7B7D2"]


def _petal_mesh(name: str = "petal", length: float = 0.055, width: float = 0.036):
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    bm = bmesh.new()
    pts = []
    n = 12
    for i in range(n):
        a = 2 * math.pi * i / n
        x = width * 0.5 * math.sin(a) * (1 - 0.25 * math.cos(a))
        y = length * 0.5 * math.cos(a)
        z = 0.012 * (x / (width * 0.5)) ** 2 - 0.006 * (y / length)
        pts.append(bm.verts.new((x, y, z)))
    bm.faces.new(pts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _clock(g: NodeGraph, t_offset: float):
    st = g.node("GeometryNodeInputSceneTime")
    return g.math("ADD", st.outputs["Seconds"], t_offset)


def drift(center=(0.0, 0.0, 2.0), size=(70.0, 70.0, 14.0), count: int = 1500, wind=(1.4, 0.5, 0.12),
          seed: int = 7, dur: float = 25.0, t_offset: float = 0.0, scale=(0.7, 1.4), near: tuple | None = None,
          near_count: int = 0, near_radius: float = 6.0):
    """Ambient petals. Start positions are spread upwind so the volume stays evenly filled for ``dur`` seconds.

    ``near`` = list of (x, y, z) points (e.g. the camera path) to seed ``near_count`` extra petals around, for
    big out-of-focus foreground petals.
    """
    import bpy  # noqa: PLC0415

    from .world import toon_material  # noqa: PLC0415
    rng = random.Random(seed * 977 + 13)
    pts, rnds = [], []
    for _ in range(count):
        p = [center[k] + rng.uniform(-0.5, 0.5) * size[k] for k in range(3)]
        p[2] = max(p[2], center[2] - size[2] * 0.4 + 0.3)
        pts.append(tuple(p[k] - wind[k] * dur * rng.uniform(0.0, 0.5) for k in range(3)))
        rnds.append(rng.random())
    for _ in range(near_count if near else 0):
        c = near[rng.randrange(len(near))]
        a = rng.uniform(0, 2 * math.pi)
        r = near_radius * math.sqrt(rng.random())
        p = (c[0] + r * math.cos(a), c[1] + r * math.sin(a), c[2] + rng.uniform(-1.2, 1.5))
        pts.append(tuple(p[k] - wind[k] * rng.uniform(0.0, 3.0) for k in range(3)))
        rnds.append(rng.random())
    me = bpy.data.meshes.new("petal_pts")
    me.from_pydata(pts, [], [])
    at = me.attributes.new("rnd", "FLOAT", "POINT")
    at.data.foreach_set("value", rnds)
    ob = bpy.data.objects.new("petals", me)
    bpy.context.scene.collection.objects.link(ob)
    # instance petal + material with per-instance colour
    pm = _petal_mesh()
    mat, g_m, grp = toon_material("petal", "#F2A3B3", rim=0.6, translucent=0.8, soft=0.25, haze=0.6)
    attr = g_m.node("ShaderNodeAttribute", attribute_type="INSTANCER", attribute_name="rnd")
    col = g_m.ramp(attr.outputs["Fac"], [(i / len(PETAL_COLS), hex_rgb(c)) for i, c in enumerate(PETAL_COLS)],
                   interp="CONSTANT")
    g_m.link(col, grp.inputs["Color"])
    g_m.link(g_m.mix_rgb(1.0, col, hex_rgb("#B497C8"), "MULTIPLY"), grp.inputs["Shade"])
    pm.materials.append(mat)
    src = bpy.data.objects.new("petal_src", pm)
    bpy.context.scene.collection.objects.link(src)
    src.hide_render = src.hide_viewport = True
    ng = bpy.data.node_groups.new("petal_drift", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g = NodeGraph(ng)
    gi, go = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    t = _clock(g, t_offset)
    rnd = g.node("GeometryNodeInputNamedAttribute", {"Name": "rnd"}, data_type="FLOAT").outputs[0]
    ph = g.math("MULTIPLY", rnd, 6.2832)
    spd = g.math("ADD", 0.75, g.math("MULTIPLY", rnd, 0.5))
    sw = g.xyz(g.math("MULTIPLY", g.math("SINE", g.math("ADD", g.math("MULTIPLY", t, 0.9), ph)), 0.8),
               g.math("MULTIPLY", g.math("COSINE", g.math("ADD", g.math("MULTIPLY", t, 0.7), g.math("MULTIPLY", ph, 1.3))), 0.8),
               g.math("MULTIPLY", g.math("SINE", g.math("ADD", g.math("MULTIPLY", t, 1.3), g.math("MULTIPLY", ph, 0.7))), 0.45))
    adv = g.vmath("SCALE", wind, scale=g.math("MULTIPLY", t, spd))
    off = g.vmath("ADD", adv, sw)
    sp = g.node("GeometryNodeSetPosition", {"Geometry": gi.outputs[0], "Offset": off})
    oi = g.node("GeometryNodeObjectInfo", {"As Instance": True})
    oi.inputs["Object"].default_value = src
    rx = g.math("ADD", g.math("MULTIPLY", t, g.math("ADD", 1.5, g.math("MULTIPLY", rnd, 3.0))), ph)
    ry = g.math("ADD", g.math("MULTIPLY", t, g.math("SUBTRACT", 2.2, g.math("MULTIPLY", rnd, 4.0))), g.math("MULTIPLY", ph, 2.0))
    rz = g.math("MULTIPLY", ph, 3.0)
    rot = g.node("FunctionNodeEulerToRotation", {"Euler": g.xyz(rx, ry, rz)})
    s = g.math("ADD", scale[0], g.math("MULTIPLY", g.math("FRACT", g.math("MULTIPLY", rnd, 7.13)), scale[1] - scale[0]))
    iop = g.node("GeometryNodeInstanceOnPoints", {"Points": sp.outputs[0], "Instance": oi.outputs["Geometry"],
                                                  "Rotation": rot.outputs[0], "Scale": s})
    store = g.node("GeometryNodeStoreNamedAttribute", {"Geometry": iop.outputs[0], "Name": "rnd", "Value": rnd},
                   data_type="FLOAT", domain="INSTANCE")
    g.link(store.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("drift", "NODES")
    mod.node_group = ng
    return ob


def frame_size(cam, res: tuple[int, int], dist: float) -> tuple[float, float]:
    """World size (w, h) of the camera frame at ``dist`` in front of the lens (sensor_fit AUTO)."""
    sensor = cam.data.sensor_width
    w_px, h_px = res
    if w_px >= h_px:
        w = dist * sensor / cam.data.lens
        return w, w * h_px / w_px
    h = dist * sensor / cam.data.lens
    return h * w_px / h_px, h


def sheet(cam, image_path: str, res: tuple[int, int], dist: float = 1.0, cell_px: int = 30, t_start: float = 0.1,
          spread: float = 0.95, origin: tuple[float, float] = (0.5, 0.5), seed: int = 7, t_offset: float = 0.0,
          lens: float | None = None):
    """Image petal sheet parented to ``cam`` (see module doc). ``origin`` = (u, v) with v measured from the TOP.

    Returns the sheet object. The camera's lens must stay fixed while the sheet is intact (pass ``lens`` if the
    camera's lens is keyed so the sheet is sized for the value at the start).
    """
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    rng = random.Random(seed * 31 + 77)
    if lens:
        cam.data.lens = lens
    W, H = frame_size(cam, res, dist)
    cols = max(4, round(res[0] / cell_px))
    rows = max(4, round(res[1] / cell_px))
    cw, ch = W / cols, H / rows
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    cuv = bm.loops.layers.uv.new("cell_uv")
    cen_l, del_l, rnd_l, ax_l = [], [], [], []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = -W / 2 + c * cw, H / 2 - (r + 1) * ch
            u0, v0 = c / cols, 1 - (r + 1) / rows
            vs = [bm.verts.new((x0, y0, -dist)), bm.verts.new((x0 + cw, y0, -dist)),
                  bm.verts.new((x0 + cw, y0 + ch, -dist)), bm.verts.new((x0, y0 + ch, -dist))]
            f = bm.faces.new(vs)
            for lo, (a, b) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                lo[uv].uv = (u0 + a / cols, v0 + b / rows)
                lo[cuv].uv = (a, b)
            # delay: wave from the origin (normalised distance, aspect-corrected) + jitter
            cu, cv = (c + 0.5) / cols, (r + 0.5) / rows
            dn = math.hypot((cu - origin[0]) * res[0] / max(res), (cv - origin[1]) * res[1] / max(res))
            d = t_start + spread * min(1.0, dn / 0.9) ** 0.85 + rng.uniform(0.0, 0.12)
            ax = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.3, 0.3))
            al = math.sqrt(sum(a * a for a in ax)) or 1.0
            for _ in range(4):
                cen_l.append((x0 + cw / 2, y0 + ch / 2, -dist))
                del_l.append(d)
                rnd_l.append(rng.random())
                ax_l.append(tuple(a / al for a in ax))
    me = bpy.data.meshes.new("petal_sheet")
    bm.to_mesh(me)
    bm.free()
    # bmesh created verts in face order, so per-vertex lists line up with vertex indices
    for name, typ, data, key in (("c", "FLOAT_VECTOR", cen_l, "vector"), ("dly", "FLOAT", del_l, "value"),
                                 ("rnd", "FLOAT", rnd_l, "value"), ("ax", "FLOAT_VECTOR", ax_l, "vector")):
        a = me.attributes.new(name, typ, "POINT")
        flat = [x for v in data for x in v] if typ == "FLOAT_VECTOR" else data
        a.data.foreach_set(key, flat)
    ob = bpy.data.objects.new("petal_sheet", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = cam
    ob.visible_shadow = False
    ob.data.materials.append(_sheet_material(image_path))
    ng = bpy.data.node_groups.new("petal_sheet", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g = NodeGraph(ng)
    gi, go = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    t = _clock(g, t_offset)

    def attr(name, typ="FLOAT"):
        n = g.node("GeometryNodeInputNamedAttribute", {"Name": name}, data_type=typ)
        return [s for s in n.outputs if s.name == "Attribute" and getattr(s, "enabled", True)][0]
    c = attr("c", "FLOAT_VECTOR")
    dly = attr("dly")
    rnd = attr("rnd")
    ax = attr("ax", "FLOAT_VECTOR")
    tau = g.math("MAXIMUM", g.math("SUBTRACT", t, dly), 0.0)
    pos = g.node("GeometryNodeInputPosition").outputs[0]
    rel = g.vmath("SUBTRACT", pos, c)
    # rotation eases in: angle = spin * tau^2 / (tau + 0.3)
    spin = g.math("ADD", 3.0, g.math("MULTIPLY", rnd, 5.0))
    ang = g.math("DIVIDE", g.math("MULTIPLY", spin, g.math("MULTIPLY", tau, tau)), g.math("ADD", tau, 0.3))
    vr = g.node("ShaderNodeVectorRotate", {"Vector": rel, "Axis": ax, "Angle": ang}, rotation_type="AXIS_ANGLE")
    # shrink toward petal size as it peels (cells are bigger than petals at the camera)
    shrink = g.map_range(tau, 0.0, 0.9, 1.0, 0.62, interp="SMOOTHSTEP")
    rel2 = g.vmath("SCALE", vr.outputs[0], scale=shrink)
    cx, cy, _ = g.sep(c)
    # flight: outward from the frame centre, sideways gust, toward/past the camera (+Z in camera space)
    out_k = g.math("ADD", 0.5, g.math("MULTIPLY", rnd, 0.9))
    tau2 = g.math("MULTIPLY", tau, tau)
    fx = g.math("ADD", g.math("MULTIPLY", g.math("MULTIPLY", cx, out_k), g.math("MULTIPLY", tau, 1.2)),
                g.math("MULTIPLY", tau2, g.math("ADD", 0.25, g.math("MULTIPLY", rnd, 0.35))))
    fy = g.math("ADD", g.math("MULTIPLY", g.math("MULTIPLY", cy, out_k), g.math("MULTIPLY", tau, 1.2)),
                g.math("MULTIPLY", tau2, 0.12))
    fz = g.math("ADD", g.math("MULTIPLY", tau, g.math("ADD", 0.25, g.math("MULTIPLY", rnd, 0.35))),
                g.math("MULTIPLY", tau2, g.math("ADD", 0.9, g.math("MULTIPLY", rnd, 1.1))))
    flight = g.xyz(fx, fy, fz)
    newp = g.vmath("ADD", g.vmath("ADD", c, rel2), flight)
    sp = g.node("GeometryNodeSetPosition", {"Geometry": gi.outputs[0], "Position": newp})
    peel = g.map_range(tau, 0.0, 0.35, 0.0, 1.0, interp="SMOOTHSTEP")
    store = g.node("GeometryNodeStoreNamedAttribute", {"Geometry": sp.outputs[0], "Name": "peel", "Value": peel},
                   data_type="FLOAT", domain="POINT")
    g.link(store.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("sheet", "NODES")
    mod.node_group = ng
    return ob


def _sheet_material(image_path: str):
    """Front = handoff still (Closest, emission 1:1); back = petal pink; silhouette morphs square -> petal."""
    import bpy  # noqa: PLC0415
    m = bpy.data.materials.new("petal_sheet")
    m.use_nodes = True
    try:
        m.surface_render_method = "DITHERED"
    except AttributeError:
        m.blend_method = "HASHED"
    m.use_backface_culling = False
    nt = m.node_tree
    nt.nodes.clear()
    g = NodeGraph(nt)
    img = bpy.data.images.load(image_path, check_existing=True)
    img.colorspace_settings.name = "sRGB"
    uvn = g.node("ShaderNodeUVMap", uv_map="UVMap")
    tex = g.node("ShaderNodeTexImage", {"Vector": uvn.outputs[0]}, interpolation="Closest", extension="EXTEND")
    tex.image = img
    geo = g.node("ShaderNodeNewGeometry")
    peel = g.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="peel").outputs["Fac"]
    back = g.mix_rgb(peel, tex.outputs["Color"], hex_rgb("#F4B3C6"))
    col = g.mix_rgb(geo.outputs["Backfacing"], tex.outputs["Color"], back)
    # front tints toward petal colour as it flies (keeps pixels readable for the first moments)
    col = g.mix_rgb(g.math("MULTIPLY", peel, 0.35), col, hex_rgb("#F7C6D4"))
    cuv = g.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="cell_uv").outputs["Vector"]
    ux, uy, _ = g.sep(cuv)
    # petal SDF: an ellipse narrowing toward one tip
    px = g.math("MULTIPLY", g.math("SUBTRACT", ux, 0.5), 2.0)
    py = g.math("MULTIPLY", g.math("SUBTRACT", uy, 0.5), 2.0)
    wy = g.math("ADD", 0.62, g.math("MULTIPLY", py, -0.28))
    e = g.math("ADD", g.math("POWER", g.math("DIVIDE", g.math("ABSOLUTE", px), wy), 2.0), g.math("POWER", g.math("ABSOLUTE", py), 2.0))
    inside = g.math("LESS_THAN", e, 1.0)
    alpha = g.mix_float(peel, 1.0, inside)
    em = g.node("ShaderNodeEmission", {"Color": col, "Strength": 1.0})
    tr = g.node("ShaderNodeBsdfTransparent")
    mix = g.node("ShaderNodeMixShader")
    g.link(alpha, mix.inputs[0])
    g.link(tr.outputs[0], mix.inputs[1])
    g.link(em.outputs[0], mix.inputs[2])
    out = g.node("ShaderNodeOutputMaterial")
    g.link(mix.outputs[0], out.inputs["Surface"])
    return m
