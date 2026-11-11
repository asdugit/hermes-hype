"""A lone figure standing in the meadow: anime-styled girl in a white sundress and a straw hat with a red ribbon.

Self-made (CC0) stylised mesh built from code: skin-modifier body, lofted dress and hair, hat + ribbon; cel shading
(sr_toon) with a warm rim; hair, dress hem and ribbon tails sway in frame-driven wind (geometry nodes); the head
(and a little of the torso) turns to follow a subject with eased, clamped yaw.

    fig = figure.build(location=(0, 0, z), facing_deg=20, wind=(1, 0.35))
    figure.look_at(fig, fn=car_pos, t0=11.5, t1=15.0, fps=30, frames=600)   # head follows a passing car
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

from .nodes import NodeGraph

SKIN = "#F7D8C9"
HAIR = "#3A2834"
HAIR_SHADE = "#1F1424"
DRESS = "#FBF7F3"
DRESS_SHADE = "#B4A6D6"
STRAW = "#F2DFB0"
RIBBON = "#D7263D"

Vec = tuple[float, float, float]


def _toon(name, color, shade=None, rim=0.6, soft=0.08, translucent=0.0):
    from .world import toon_material  # noqa: PLC0415
    m, _, _ = toon_material(name, color, shade, rim=rim, haze=0.3, soft=soft, translucent=translucent)
    return m


def _loft(name: str, rings: Sequence[Sequence[Vec]], closed: bool = True, cap_top: bool = False):
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    bm = bmesh.new()
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(rings[0])
    span = n if closed else n - 1
    for i in range(len(rings) - 1):
        for j in range(span):
            j2 = (j + 1) % n
            f = bm.faces.new((vs[i][j], vs[i][j2], vs[i + 1][j2], vs[i + 1][j]))
            f.smooth = True
    if cap_top and closed:
        bm.faces.new(vs[0]).smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _ellipse(z: float, rx: float, ry: float, n: int = 24, cy: float = 0.0, wave: float = 0.0, k: int = 7,
             a0: float = 0.0, a1: float = 2 * math.pi) -> list[Vec]:
    out = []
    full = abs(a1 - a0 - 2 * math.pi) < 1e-6
    for i in range(n):
        a = a0 + (a1 - a0) * i / (n if full else n - 1)
        w = 1.0 + wave * math.sin(k * a + 0.7)
        out.append((rx * w * math.sin(a), cy - ry * w * math.cos(a), z))
    return out


def _obj(name, me, mat, parent=None, coll=None):
    import bpy  # noqa: PLC0415
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def _body_mesh():
    import bpy  # noqa: PLC0415
    V = [(0, 0, 0.90), (0, 0, 1.04), (0, 0.005, 1.20), (0, 0, 1.36), (0, 0.006, 1.44)]
    R = [(0.115, 0.085), (0.088, 0.066), (0.105, 0.08), (0.045, 0.045), (0.036, 0.036)]
    E = [(0, 1), (1, 2), (2, 3), (3, 4)]
    for sx, fwd in ((-1, 0.03), (1, -0.02)):
        b = len(V)
        V += [(sx * 0.072, 0, 0.86), (sx * 0.078, fwd + 0.01, 0.48), (sx * 0.08, fwd, 0.075), (sx * 0.08, fwd + 0.11, 0.03)]
        R += [(0.066, 0.066), (0.042, 0.042), (0.03, 0.03), (0.026, 0.026)]
        E += [(0, b), (b, b + 1), (b + 1, b + 2), (b + 2, b + 3)]
    for sx in (-1, 1):
        b = len(V)
        V += [(sx * 0.145, 0, 1.33), (sx * 0.19, 0.015, 1.105), (sx * 0.205, 0.045, 0.885), (sx * 0.21, 0.055, 0.83)]
        R += [(0.04, 0.04), (0.03, 0.03), (0.023, 0.023), (0.028, 0.02)]
        E += [(2, b), (b, b + 1), (b + 1, b + 2), (b + 2, b + 3)]
    me = bpy.data.meshes.new("fig_body")
    me.from_pydata(V, E, [])
    return me, R


def build(location: Vec = (0, 0, 0), facing_deg: float = 0.0, wind: tuple = (1.0, 0.35), t_offset: float = 0.0,
          scale: float = 1.0):
    """Build the figure. Returns dict(root, neck, objects). ``facing_deg`` = yaw of her front (0 = +Y)."""
    import bpy  # noqa: PLC0415
    coll = bpy.data.collections.new("figure")
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new("figure", None)
    coll.objects.link(root)
    root.location = location
    root.rotation_euler = (0, 0, -math.radians(facing_deg))
    root.scale = (scale,) * 3
    skin = _toon("fig_skin", SKIN, "#D79A93", rim=0.7)
    hair = _toon("fig_hair", HAIR, HAIR_SHADE, rim=1.2, soft=0.05)
    dress = _toon("fig_dress", DRESS, DRESS_SHADE, rim=0.9, translucent=0.25)
    straw = _toon("fig_straw", STRAW, "#B79A7C", rim=0.8)
    ribbon = _toon("fig_ribbon", RIBBON, "#7A1630", rim=0.8, translucent=0.3)
    # body (skin modifier)
    me, radii = _body_mesh()
    body = _obj("fig_body", me, skin, root, coll)
    sk = body.modifiers.new("skin", "SKIN")
    sk.use_smooth_shade = True
    for v, r in zip(me.skin_vertices[0].data, radii):
        v.radius = r
    me.skin_vertices[0].data[0].use_root = True
    sub = body.modifiers.new("sub", "SUBSURF")
    sub.levels = sub.render_levels = 2
    # dress (lofted, flared, wavy hem) + straps
    rings = [_ellipse(1.31, 0.118, 0.088), _ellipse(1.20, 0.122, 0.092), _ellipse(1.06, 0.098, 0.074),
             _ellipse(0.95, 0.15, 0.12), _ellipse(0.76, 0.215, 0.185, wave=0.03), _ellipse(0.56, 0.27, 0.24, wave=0.06)]
    dr = _obj("fig_dress", _loft("fig_dress", rings), dress, root, coll)
    sol = dr.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.008
    s2 = dr.modifiers.new("sub", "SUBSURF")
    s2.levels = s2.render_levels = 2
    # neck pivot (head group)
    neck = bpy.data.objects.new("fig_neck", None)
    coll.objects.link(neck)
    neck.parent = root
    neck.location = (0, 0, 1.42)
    neck.rotation_mode = "XYZ"
    import bmesh  # noqa: PLC0415
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.1)
    for v in bm.verts:
        v.co.x *= 0.9
        v.co.z *= 1.08
        if v.co.z < -0.03 and v.co.y > 0:
            v.co.y *= 0.85     # jaw toward the chin
    me = bpy.data.meshes.new("fig_head")
    bm.to_mesh(me)
    bm.free()
    head = _obj("fig_head", me, skin, neck, coll)
    head.location = (0, 0.012, 0.115)
    for p in head.data.polygons:
        p.use_smooth = True
    # hair: scalp cap + long back curtain (a lofted half-shell) — local to the neck pivot
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.108)
    for v in list(bm.verts):
        v.co.x *= 0.95
        v.co.z *= 1.06
        if v.co.y > 0.05 and v.co.z < 0.03:
            bm.verts.remove(v)            # open the face
    me = bpy.data.meshes.new("fig_scalp")
    bm.to_mesh(me)
    bm.free()
    scalp = _obj("fig_scalp", me, hair, neck, coll)
    scalp.location = (0, 0.006, 0.122)
    for p in scalp.data.polygons:
        p.use_smooth = True
    half = (math.radians(-118), math.radians(118))
    hr = [(0.17, 0.104, 0.098), (0.06, 0.118, 0.11), (-0.06, 0.13, 0.115), (-0.18, 0.15, 0.12), (-0.30, 0.16, 0.115),
          (-0.40, 0.15, 0.10)]
    rings = [_ellipse(z, rx, ry, n=18, cy=0.0, wave=0.05 if z < -0.2 else 0.0, k=9, a0=half[0], a1=half[1])
             for z, rx, ry in hr]
    long_hair = _obj("fig_hair", _loft("fig_hair", rings, closed=False), hair, neck, coll)
    long_hair.location = (0, -0.01, 0.0)
    sol = long_hair.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.018
    s3 = long_hair.modifiers.new("sub", "SUBSURF")
    s3.levels = s3.render_levels = 2
    # straw hat: brim (droopy disc) + crown + red ribbon band and tails
    bm = bmesh.new()
    rings_b = []
    for r, dz in ((0.10, 0.0), (0.16, -0.008), (0.22, -0.022), (0.27, -0.045)):
        rings_b.append([bm.verts.new((r * math.cos(2 * math.pi * i / 40), r * math.sin(2 * math.pi * i / 40), dz))
                        for i in range(40)])
    for i in range(len(rings_b) - 1):
        for j in range(40):
            j2 = (j + 1) % 40
            bm.faces.new((rings_b[i][j], rings_b[i][j2], rings_b[i + 1][j2], rings_b[i + 1][j])).smooth = True
    crown = bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.112)
    for v in crown["verts"]:
        v.co.z = max(v.co.z, -0.01) * 0.82 + 0.01
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new("fig_hat")
    bm.to_mesh(me)
    bm.free()
    hat = _obj("fig_hat", me, straw, neck, coll)
    hat.location = (0, 0.0, 0.2)
    hat.rotation_euler = (math.radians(-9), 0, 0)
    sol = hat.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.006
    band_r = [_ellipse(z, 0.114, 0.114, n=32) for z in (0.0, 0.028)]
    band = _obj("fig_band", _loft("fig_band", band_r), ribbon, hat, coll)
    band.location = (0, 0, 0.004)
    tails = []
    for sx in (-1, 1):
        pts = []
        for k in range(6):
            u = k / 5
            pts.append([(sx * (0.025 + 0.02 * u) + w, -0.112 - 0.05 * u, 0.02 - 0.28 * u) for w in (-0.016, 0.016)])
        tails.append(_obj("fig_tail", _loft("fig_tail", pts, closed=False), ribbon, hat, coll))
    for o in (body, dr, head, scalp, long_hair, hat, band, *tails):
        o.visible_shadow = True
    # wind (object-local), strongest on the hem / hair tips / ribbon tails
    a = math.radians(facing_deg)
    wl = math.hypot(*wind) or 1.0
    wx, wy = wind[0] / wl, wind[1] / wl
    lw = (wx * math.cos(a) + wy * math.sin(a), -wx * math.sin(a) + wy * math.cos(a))
    _wind_mod(dr, "dress", lw, z_top=1.0, z_bot=0.55, amp=0.05, ripple=0.012, t_offset=t_offset)
    _wind_mod(long_hair, "hair", lw, z_top=0.1, z_bot=-0.42, amp=0.07, ripple=0.01, t_offset=t_offset)
    for i, tl in enumerate(tails):
        _wind_mod(tl, f"tail{i}", lw, z_top=0.02, z_bot=-0.26, amp=0.11, ripple=0.03, t_offset=t_offset + i * 0.37)
    return {"root": root, "neck": neck, "objects": [body, dr, head, scalp, long_hair, hat, band, *tails],
            "head_height": 1.55 * scale}


def wave(fig: dict, beats: Sequence[tuple[float, float]], fps: float, frames: int, t_offset: float = 0.0,
         amp_deg: float = 132.0, wave_deg: float = 11.0, wave_hz: float = 1.7, ease: float = 0.55,
         side: int = 1) -> None:
    """She raises her arm and waves over each ``beats`` window [(t_start, t_end), ...] (move time, seconds).

    The arm is lifted by rotating the arm-chain vertices of the body mesh about the shoulder **before** the Skin
    modifier builds the limb, so the whole arm follows; the mask fades out at the shoulder so the joint bends
    smoothly. Deterministic from Scene Time (no keys, any frame renders identically)."""
    import bpy  # noqa: PLC0415

    body = fig["objects"][0]
    ng = bpy.data.node_groups.new("fig_wave", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g = NodeGraph(ng)
    gi, go = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    pos = g.node("GeometryNodeInputPosition").outputs[0]
    x, _y, z = g.sep(pos)
    st = g.node("GeometryNodeInputSceneTime")
    t = g.math("ADD", st.outputs["Seconds"], t_offset)
    w = None
    for (a, b) in beats:
        up = g.map_range(g.math("DIVIDE", g.math("SUBTRACT", t, a), ease), 0.0, 1.0, 0.0, 1.0,
                         interp="SMOOTHSTEP")
        dn = g.map_range(g.math("DIVIDE", g.math("SUBTRACT", t, b), ease), 0.0, 1.0, 0.0, 1.0,
                         interp="SMOOTHSTEP")
        v = g.math("MULTIPLY", up, g.math("SUBTRACT", 1.0, dn))
        w = v if w is None else g.math("ADD", w, v)
    w = g.math("MINIMUM", w, 1.0)
    ang = g.math("MULTIPLY", w, math.radians(-amp_deg * side))
    wob = g.math("MULTIPLY", g.math("MULTIPLY", w, math.radians(wave_deg)),
                 g.math("SINE", g.math("MULTIPLY", t, 2 * math.pi * wave_hz)))
    ang = g.math("ADD", ang, wob)
    c, s = g.math("COSINE", ang), g.math("SINE", ang)
    sx, sz = 0.145 * side, 1.33
    dx, dz = g.math("SUBTRACT", x, sx), g.math("SUBTRACT", z, sz)
    dx2 = g.math("ADD", g.math("MULTIPLY", dx, c), g.math("MULTIPLY", dz, s))
    dz2 = g.math("SUBTRACT", g.math("MULTIPLY", dz, c), g.math("MULTIPLY", dx, s))
    m = g.map_range(g.math("MULTIPLY", x, side), 0.100, 0.160, 0.0, 1.0, interp="SMOOTHSTEP")
    nx = g.mix_float(m, dx, dx2)
    nz = g.mix_float(m, dz, dz2)
    off = g.xyz(g.math("SUBTRACT", g.math("ADD", nx, sx), x), 0.0,
                g.math("SUBTRACT", g.math("ADD", nz, sz), z))
    sp = g.node("GeometryNodeSetPosition", {"Geometry": gi.outputs[0], "Offset": off})
    g.link(sp.outputs[0], go.inputs[0])
    mod = body.modifiers.new("wave", "NODES")
    mod.node_group = ng
    _move_first(body, "wave")


def _wind_mod(ob, name: str, wind_local: tuple, z_top: float, z_bot: float, amp: float, ripple: float,
              t_offset: float) -> None:
    """GN deform: offset downwind ∝ ((z_top - z)/(z_top - z_bot))^1.5 with gusts + ripple, from Scene Time."""
    import bpy  # noqa: PLC0415
    ng = bpy.data.node_groups.new(f"wind_{name}", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g = NodeGraph(ng)
    gi, go = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    pos = g.node("GeometryNodeInputPosition").outputs[0]
    px, py, pz = g.sep(pos)
    w = g.map_range(pz, z_top, z_bot, 0.0, 1.0)
    w = g.math("POWER", w, 1.5)
    st = g.node("GeometryNodeInputSceneTime")
    t = g.math("ADD", st.outputs["Seconds"], t_offset)
    nz = g.node("ShaderNodeTexNoise", {"W": g.math("MULTIPLY", t, 0.45), "Scale": 1.0, "Detail": 1.0},
                noise_dimensions="1D")
    gust = g.math("ADD", 0.55, g.math("MULTIPLY", g.math("SUBTRACT", nz.outputs["Factor"], 0.5), 1.6))
    ang = g.math("ADD", g.math("MULTIPLY", t, 5.0), g.math("MULTIPLY", g.math("ADD", px, py), 18.0))
    rip = g.math("MULTIPLY", g.math("SINE", g.math("SUBTRACT", ang, g.math("MULTIPLY", pz, 14.0))), ripple)
    k = g.math("MULTIPLY", w, g.math("MULTIPLY", gust, amp))
    off = g.xyz(g.math("ADD", g.math("MULTIPLY", k, wind_local[0]), g.math("MULTIPLY", rip, -wind_local[1])),
                g.math("ADD", g.math("MULTIPLY", k, wind_local[1]), g.math("MULTIPLY", rip, wind_local[0])),
                g.math("MULTIPLY", g.math("MULTIPLY", k, k), 1.5))
    off = g.vmath("MULTIPLY", off, g.xyz(w, w, w))
    sp = g.node("GeometryNodeSetPosition", {"Geometry": gi.outputs[0], "Offset": off})
    g.link(sp.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("wind", "NODES")
    mod.node_group = ng
    # keep wind before subdivision for smooth results
    _move_first(ob, "wind")


def _move_first(ob, name: str) -> None:
    mods = ob.modifiers
    i = mods.find(name)
    if i > 0:
        mods.move(i, 0)


def look_at(fig: dict, keys: Sequence[tuple[float, float, Callable[[float], Vec] | None]], fps: float, frames: int,
            t_offset: float = 0.0, max_yaw: float = 70.0, body_share: float = 0.25, smooth: float = 0.35) -> None:
    """Key the head yaw: keys = [(t_start, t_end, subject_fn|None), ...]; between keys the head eases back to 0.

    Yaw is the subject's bearing in figure space (clamped), low-passed with a critically-damped follower
    (``smooth`` s) so it never snaps; a share of it turns the torso too.
    """
    from mathutils import Matrix, Vector  # noqa: PLC0415

    from .camera import linearize, smootherstep  # noqa: PLC0415
    root, neck = fig["root"], fig["neck"]
    inv = root.matrix_world.inverted() if root.parent is None else Matrix.Identity(4)
    base_inv = (Matrix.Translation(root.location) @ root.rotation_euler.to_matrix().to_4x4()).inverted()
    del inv
    yaw = 0.0
    vel = 0.0
    dt = 1.0 / fps
    w = 2.0 / max(0.05, smooth)
    for f in range(1, frames + 1):
        t = t_offset + (f - 1) * dt
        target = 0.0
        for (a, b, fn) in keys:
            if fn is None or t < a - 0.6 or t > b + 0.8:
                continue
            p = base_inv @ Vector(fn(t))
            bearing = math.degrees(math.atan2(-p.x, p.y))
            bearing = max(-max_yaw, min(max_yaw, bearing))
            k = smootherstep((t - (a - 0.6)) / 0.6) * (1 - smootherstep((t - b) / 0.8))
            target = target * (1 - k) + bearing * k
        # critically damped spring toward target
        acc = w * w * (target - yaw) - 2 * w * vel
        vel += acc * dt
        yaw += vel * dt
        neck.rotation_euler = (math.radians(-4), 0, math.radians(yaw * (1 - body_share)))
        neck.keyframe_insert("rotation_euler", frame=f)
    linearize(neck)
