"""Anime flower meadow: terrain + geometry-nodes grass and wildflowers with frame-driven wind.

    hf = meadow.Terrain(seed=7)                 # pure-Python height field (hf(x, y) -> z), also for flyers
    meadow.terrain_object(hf)                   # the ground mesh with a painterly meadow shader
    meadow.scatter(hf, center=(0, 0), radius=34, density=1.0)   # GN grass clumps + flowers, wind by frame
    meadow.foreground(hf, points=[(x, y), ...]) # tall DOF blossoms along the camera path

Wind = rolling gusts: a noise field advected along the wind direction drives each instance's tilt, plus a fast
per-instance flutter; all from the scene frame (Scene Time), so any frame renders identically in isolation.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .nodes import NodeGraph, hex_rgb

FLOWERS = {
    # name: (petal colour, centre colour, petal count, petal length, stem height range, head tilt)
    "daisy": ("#FBF7EF", "#F2C94C", 10, 0.055, (0.18, 0.42)),
    "cosmos": ("#F49AC0", "#F6D36B", 8, 0.075, (0.34, 0.72)),
    "pink": ("#F7B3CC", "#F7E3A0", 6, 0.052, (0.16, 0.44)),
    "butter": ("#F6D55C", "#E9A93A", 5, 0.040, (0.15, 0.35)),
    "lilac": ("#B08BE6", "#E8DDF8", 0, 0.0, (0.30, 0.64)),        # lupine spike (petals=0)
    "white": ("#FFFFFF", "#F3E9B5", 5, 0.034, (0.10, 0.28)),
    "rose": ("#E9799F", "#F6D36B", 7, 0.058, (0.24, 0.56)),
}


@dataclass
class Terrain:
    """Smooth deterministic height field: a gentle rise under the figure, named hills, rolling noise, far bowl."""
    seed: int = 7
    hills: list = field(default_factory=lambda: [
        (0.0, 0.0, 1.0, 16.0),        # the figure's knoll
        (-30.0, 40.0, 3.0, 15.0),     # crest for drive-over-hill
        (48.0, 62.0, 3.6, 20.0),      # right hill (climb_right rises from behind it)
        (-70.0, 95.0, 5.0, 30.0),
        (20.0, -60.0, 1.6, 22.0),
    ])

    def __post_init__(self) -> None:
        r = random.Random(self.seed * 7919 + 3)
        self.waves = [(r.uniform(0.03, 0.09), r.uniform(0.03, 0.09), r.uniform(0, 6.28), r.uniform(0.12, 0.35))
                      for _ in range(4)]

    def __call__(self, x: float, y: float) -> float:
        z = 0.0
        for hx, hy, hh, hs in self.hills:
            z += hh * math.exp(-((x - hx) ** 2 + (y - hy) ** 2) / (2 * hs * hs))
        for fx, fy, ph, amp in self.waves:
            z += amp * math.sin(fx * x + ph) * math.sin(fy * y + ph * 0.7)
        r = math.hypot(x, y)
        u = min(1.0, max(0.0, (r - 90.0) / 400.0))
        z += 14.0 * u * u * (3 - 2 * u)
        return z


def terrain_object(hf: Terrain, size: float = 520.0, step: float = 2.0, palette: str = "sunset"):
    """Ground mesh (size x size m at ``step`` m) + a far ring to the horizon, with the meadow ground shader."""
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    n = int(size / step)
    bm = bmesh.new()
    vs = []
    for j in range(n + 1):
        row = []
        y = -size / 2 + j * step
        for i in range(n + 1):
            x = -size / 2 + i * step
            row.append(bm.verts.new((x, y, hf(x, y))))
        vs.append(row)
    for j in range(n):
        for i in range(n):
            f = bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
            f.smooth = True
    # far skirt: a ring out to 4 km at the far-bowl height
    edge_z = hf(size, 0)
    ring_in, ring_out = [], []
    for k in range(128):
        a = 2 * math.pi * k / 128
        c, s = math.cos(a), math.sin(a)
        rr = size * 0.5 / max(abs(c), abs(s))
        ring_in.append(bm.verts.new((rr * c, rr * s, hf(rr * c, rr * s) - 0.05)))
        ring_out.append(bm.verts.new((4000 * c, 4000 * s, edge_z + 10)))
    for k in range(128):
        k2 = (k + 1) % 128
        bm.faces.new((ring_in[k], ring_out[k], ring_out[k2], ring_in[k2]))
    me = bpy.data.meshes.new("terrain")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("terrain", me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(ground_material(palette))
    return ob


def ground_material(palette: str = "sunset"):
    """Painterly meadow ground: green base, drifts of flower colour, fine flower speckle; toon-lit + haze."""
    import bpy  # noqa: PLC0415

    from .world import toon_group  # noqa: PLC0415
    m = bpy.data.materials.new("meadow_ground")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    g = NodeGraph(nt)
    geo = g.node("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    big = g.node("ShaderNodeTexNoise", {"Vector": pos, "Scale": 0.021, "Detail": 3.0})
    mid = g.node("ShaderNodeTexNoise", {"Vector": pos, "Scale": 0.13, "Detail": 2.0})
    base = g.ramp(big.outputs["Factor"], [(0.28, hex_rgb("#7FA64F")), (0.5, hex_rgb("#9CC262")),
                                          (0.72, hex_rgb("#BFCE7E"))])
    drift = g.ramp(mid.outputs["Factor"], [(0.28, (0, 0, 0)), (0.48, (1, 1, 1))])
    drift_c = g.ramp(big.outputs["Factor"], [(0.28, hex_rgb("#F3A8C2")), (0.42, hex_rgb("#F6E7D2")),
                                             (0.56, hex_rgb("#C4A6E4")), (0.68, hex_rgb("#F5D772")),
                                             (0.82, hex_rgb("#EE9BBB"))], interp="CONSTANT")
    c = g.mix_rgb(g.math("MULTIPLY", drift, 0.62), base, drift_c)
    vor = g.node("ShaderNodeTexVoronoi", {"Vector": pos, "Scale": 15.0})
    speck = g.map_range(vor.outputs["Distance"], 0.10, 0.19, 1.0, 0.0)
    sc_c = g.ramp(g.math("FRACT", g.math("MULTIPLY", vor.outputs["Color"], 1.0)),
                  [(0.0, hex_rgb("#FFFFFF")), (0.3, hex_rgb("#F7BFD2")), (0.55, hex_rgb("#F6D55C")),
                   (0.8, hex_rgb("#B79BE6"))], interp="CONSTANT")
    c = g.mix_rgb(g.math("MULTIPLY", speck, 0.85), c, sc_c)
    grp = g.node("ShaderNodeGroup")
    grp.node_tree = toon_group()
    g.link(c, grp.inputs["Color"])
    sh = g.mix_rgb(1.0, c, hex_rgb("#7C6FA8"), "MULTIPLY")
    g.link(sh, grp.inputs["Shade"])
    g.set(grp, "Soft", 0.2)
    out = g.node("ShaderNodeOutputMaterial")
    g.link(grp.outputs[0], out.inputs["Surface"])
    return m


# ------------------------------------------------------------------------------------------- instance meshes
def _blade_clump(rng: random.Random, name: str, blades: int = 7, h: tuple = (0.32, 0.62)):
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    for _ in range(blades):
        a = rng.uniform(0, 2 * math.pi)
        r0 = rng.uniform(0.0, 0.05)
        bx, by = r0 * math.cos(a), r0 * math.sin(a)
        H = rng.uniform(*h)
        lean = rng.uniform(0.15, 0.45)
        la = a + rng.uniform(-0.6, 0.6)
        w = rng.uniform(0.012, 0.022)
        seg = 4
        left, right = [], []
        for k in range(seg + 1):
            u = k / seg
            off = lean * H * u * u
            cx, cy, cz = bx + off * math.cos(la), by + off * math.sin(la), H * u * (1 - 0.15 * u * u)
            ww = w * (1 - u) ** 0.8 + 0.0008
            px, py = -math.sin(la) * ww, math.cos(la) * ww
            left.append(bm.verts.new((cx + px, cy + py, cz)))
            right.append(bm.verts.new((cx - px, cy - py, cz)))
        for k in range(seg):
            f = bm.faces.new((left[k], right[k], right[k + 1], left[k + 1]))
            for lo, (uu, vv) in zip(f.loops, ((0, k / seg), (1, k / seg), (1, (k + 1) / seg), (0, (k + 1) / seg))):
                lo[uv].uv = (uu, vv)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _flower(rng: random.Random, kind: str):
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    petal_c, centre_c, n, plen, hr = FLOWERS[kind]
    bm = bmesh.new()
    H = rng.uniform(*hr)
    # stem (thin quad ribbon, mat 0)
    for side in (0, 1):
        a = side * math.pi / 2
        dx, dy = 0.004 * math.cos(a), 0.004 * math.sin(a)
        vs = [bm.verts.new((-dx, -dy, 0)), bm.verts.new((dx, dy, 0)), bm.verts.new((dx, dy, H)),
              bm.verts.new((-dx, -dy, H))]
        bm.faces.new(vs).material_index = 0
    if n == 0:
        # lupine spike: stacked small blobs
        rings = 9
        for k in range(rings):
            u = k / (rings - 1)
            z = H * (0.55 + 0.45 * u)
            rad = 0.045 * (1 - 0.7 * u) + 0.008
            g = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rad)
            bmesh.ops.translate(bm, verts=g["verts"], vec=(0, 0, z))
            for f in {f for v in g["verts"] for f in v.link_faces}:
                f.material_index = 1
    else:
        tilt = rng.uniform(0.2, 0.7)
        c, s = math.cos(tilt), math.sin(tilt)

        def T(x, y, z):  # tilt the head about X, place at stem top
            return (x, y * c - z * s, H + y * s + z * c)
        for k in range(n):
            a = 2 * math.pi * (k + rng.uniform(-0.1, 0.1)) / n
            ca, sa = math.cos(a), math.sin(a)
            L = plen * rng.uniform(0.85, 1.1)
            wv = L * (0.38 if n <= 6 else 0.28)
            pts = [(0.004, 0.0, 0.0), (L * 0.5, wv, 0.006), (L, 0.0, 0.012 + 0.008 * rng.random()), (L * 0.5, -wv, 0.006)]
            vs = [bm.verts.new(T(px * ca - py * sa, px * sa + py * ca, pz)) for px, py, pz in pts]
            bm.faces.new(vs).material_index = 1
        g = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=plen * 0.28 + 0.003)
        for v in g["verts"]:
            v.co = T(v.co.x, v.co.y, v.co.z * 0.6 + 0.006)
        for f in {f for v in g["verts"] for f in v.link_faces}:
            f.material_index = 2
    me = bpy.data.meshes.new(f"flower_{kind}")
    bm.to_mesh(me)
    bm.free()
    return me


def instance_collection(seed: int = 7, scale: float = 1.0):
    """Hidden collection of grass clumps + flowers with toon materials. Returns (collection, weights)."""
    import bpy  # noqa: PLC0415

    from .world import toon_material  # noqa: PLC0415
    rng = random.Random(seed * 101 + 1)
    coll = bpy.data.collections.new("meadow_instances")
    bpy.context.scene.collection.children.link(coll)
    coll.hide_render = True
    coll.hide_viewport = True
    grass_m, _, _ = toon_material("grass", "#9CC25E", "#4F6E46", rim=0.25, translucent=0.35, soft=0.18)
    _grass_gradient(grass_m)
    stem_m, _, _ = toon_material("stem", "#7FA552", "#466340", soft=0.18)
    objs, weights = [], []
    for k in range(5):
        me = _blade_clump(rng, f"clump{k}", blades=rng.randint(6, 9), h=(0.16 + 0.03 * k, 0.30 + 0.05 * k))
        me.materials.append(grass_m)
        ob = bpy.data.objects.new(f"clump{k}", me)
        coll.objects.link(ob)
        objs.append(ob)
        weights.append(1.0)
    mats = {}
    for kind, w, nvar in (("daisy", 4.4, 3), ("cosmos", 4.0, 3), ("pink", 4.6, 3), ("butter", 2.4, 2),
                          ("lilac", 0.9, 2), ("white", 4.4, 3), ("rose", 2.6, 2)):
        pc, cc = FLOWERS[kind][0], FLOWERS[kind][1]
        if kind not in mats:
            pm, _, _ = toon_material(f"petal_{kind}", pc, rim=0.35, translucent=0.5, soft=0.2)
            cm, _, _ = toon_material(f"centre_{kind}", cc, soft=0.2)
            mats[kind] = (pm, cm)
        for v in range(nvar):
            me = _flower(rng, kind)
            me.materials.append(stem_m)
            me.materials.append(mats[kind][0])
            me.materials.append(mats[kind][1])
            ob = bpy.data.objects.new(f"fl_{kind}{v}", me)
            coll.objects.link(ob)
            objs.append(ob)
            weights.append(w / nvar)
    return coll, objs, weights


def _grass_gradient(m) -> None:
    """Blade colour from dark root to sunlit tip (UV v)."""
    nt = m.node_tree
    g = NodeGraph(nt)
    grp = [n for n in nt.nodes if n.bl_idname == "ShaderNodeGroup"][0]
    uvn = g.node("ShaderNodeUVMap")
    _, v, _ = g.sep(uvn.outputs[0])
    attr = g.node("ShaderNodeAttribute", attribute_type="INSTANCER", attribute_name="rnd")
    tip = g.ramp(attr.outputs["Fac"], [(0.0, hex_rgb("#A8C964")), (0.5, hex_rgb("#C2D06E")), (1.0, hex_rgb("#8DBA62"))])
    col = g.mix_rgb(g.math("POWER", v, 0.7), hex_rgb("#4E7A45"), tip)
    g.link(col, grp.inputs["Color"])
    g.link(g.mix_rgb(1.0, col, hex_rgb("#6E64A0"), "MULTIPLY"), grp.inputs["Shade"])


# ---------------------------------------------------------------------------------------------------- scatter
def wind_rotation(g: NodeGraph, pos, rnd, t, amp: float = 0.28, gust: float = 0.18, flutter: float = 0.05,
                  wind_dir: tuple = (1.0, 0.35), speed: float = 2.4):
    """Euler (x, y, 0) socket: rolling gusts (noise advected along wind_dir) + per-instance flutter."""
    wl = math.hypot(*wind_dir)
    wx, wy = wind_dir[0] / wl, wind_dir[1] / wl
    adv = g.xyz(g.math("MULTIPLY", t, -speed * wx), g.math("MULTIPLY", t, -speed * wy), g.math("MULTIPLY", t, 0.15))
    p = g.vmath("ADD", g.vmath("SCALE", pos, scale=1.0), adv)
    nz = g.node("ShaderNodeTexNoise", {"Vector": p, "Scale": 0.06, "Detail": 2.0})
    gst = g.math("MULTIPLY", g.math("SUBTRACT", nz.outputs["Factor"], 0.42), 2.2)
    fl = g.math("SINE", g.math("ADD", g.math("MULTIPLY", t, 5.2), g.math("MULTIPLY", rnd, 40.0)))
    tilt = g.math("ADD", g.math("ADD", gust, g.math("MULTIPLY", gst, amp)), g.math("MULTIPLY", fl, flutter))
    # tilt about the axis perpendicular to the wind (blades lean downwind)
    ex = g.math("MULTIPLY", tilt, -wy)
    ey = g.math("MULTIPLY", tilt, wx)
    return g.xyz(g.math("MULTIPLY", ex, -1.0), ey, 0.0)


def scatter_tree(name: str, coll, weights: list[float], density: float, center=(0.0, 0.0), radius: float = 34.0,
                 falloff: float = 10.0, seed: int = 7, scale: tuple = (0.6, 1.45), t_offset: float = 0.0,
                 amp: float = 0.28):
    """GN tree: distribute on the input mesh (density falls off past ``radius``), pick weighted instances,
    random yaw/scale, wind rotation, 'rnd' instance attribute for shader variation."""
    import bpy  # noqa: PLC0415
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g = NodeGraph(ng)
    gi = g.node("NodeGroupInput")
    go = g.node("NodeGroupOutput")
    pos = g.node("GeometryNodeInputPosition").outputs[0]
    px, py, _ = g.sep(pos)
    r = g.math("SQRT", g.math("ADD", g.math("POWER", g.math("SUBTRACT", px, center[0]), 2.0),
                              g.math("POWER", g.math("SUBTRACT", py, center[1]), 2.0)))
    fall = g.map_range(r, radius, radius + falloff, 1.0, 0.0, interp="SMOOTHSTEP")
    dist = g.node("GeometryNodeDistributePointsOnFaces", {"Mesh": gi.outputs[0], "Seed": seed},
                  distribute_method="RANDOM")
    g.set(dist, "Density", g.math("MULTIPLY", fall, density))
    # weighted pick: cumulative weights over a random 0..1
    total = sum(weights)
    rv = g.node("FunctionNodeRandomValue", {"Min": 0.0, "Max": 1.0, "Seed": seed + 11}, data_type="FLOAT")
    idx = None
    acc = 0.0
    for i, w in enumerate(weights[:-1]):
        acc += w / total
        step = g.math("GREATER_THAN", _rv_out(rv), acc)
        idx = step if idx is None else g.math("ADD", idx, step)
    ci = g.node("GeometryNodeCollectionInfo", {"Separate Children": True, "Reset Children": True},
                transform_space="ORIGINAL")
    ci.inputs["Collection"].default_value = coll
    yaw = g.node("FunctionNodeRandomValue", {"Min": 0.0, "Max": 6.2832, "Seed": seed + 3}, data_type="FLOAT")
    scl = g.node("FunctionNodeRandomValue", {"Min": scale[0], "Max": scale[1], "Seed": seed + 5}, data_type="FLOAT")
    rot = g.node("FunctionNodeEulerToRotation", {"Euler": g.xyz(0.0, 0.0, _rv_out(yaw))})
    iop = g.node("GeometryNodeInstanceOnPoints", {"Points": dist.outputs["Points"], "Instance": ci.outputs[0],
                                                  "Pick Instance": True, "Instance Index": idx,
                                                  "Rotation": rot.outputs[0], "Scale": _rv_out(scl)})
    # rnd attribute + wind
    rnd = g.node("FunctionNodeRandomValue", {"Min": 0.0, "Max": 1.0, "Seed": seed + 17}, data_type="FLOAT")
    store = g.node("GeometryNodeStoreNamedAttribute", {"Geometry": iop.outputs[0], "Name": "rnd",
                                                       "Value": _rv_out(rnd)}, data_type="FLOAT", domain="INSTANCE")
    st = g.node("GeometryNodeInputSceneTime")
    t = g.math("ADD", st.outputs["Seconds"], t_offset)
    ipos = g.node("GeometryNodeInputPosition").outputs[0]
    eul = wind_rotation(g, ipos, _rv_out(rnd), t, amp=amp)
    wrot = g.node("FunctionNodeEulerToRotation", {"Euler": eul})
    # rotate about each instance's own origin in world axes (pivot = instance position)
    ri = g.node("GeometryNodeRotateInstances", {"Instances": store.outputs[0], "Rotation": wrot.outputs[0],
                                                "Pivot Point": ipos, "Local Space": False})
    g.link(ri.outputs[0], go.inputs[0])
    return ng


def _rv_out(node):
    for s in node.outputs:
        if s.name == "Value" and getattr(s, "enabled", True) and s.type == "VALUE":
            return s
    return node.outputs[1]


def scatter(hf: Terrain, center=(0.0, 0.0), radius: float = 34.0, density: float = 14.0, seed: int = 7,
            step: float = 1.0, coll_weights=None, falloff: float = 12.0, name: str = "meadow_scatter",
            t_offset: float = 0.0):
    """A hidden patch mesh following the terrain + a GN modifier that instances the meadow on it."""
    import bmesh  # noqa: PLC0415
    import bpy  # noqa: PLC0415
    coll, objs, weights = coll_weights or instance_collection(seed)
    R = radius + falloff
    n = int(2 * R / step)
    bm = bmesh.new()
    vs = []
    for j in range(n + 1):
        row = []
        for i in range(n + 1):
            x, y = center[0] - R + i * step, center[1] - R + j * step
            row.append(bm.verts.new((x, y, hf(x, y) - 0.02)))
        vs.append(row)
    for j in range(n):
        for i in range(n):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("scatter", "NODES")
    mod.node_group = scatter_tree(name + "_gn", coll, weights, density, center, radius, falloff, seed,
                                  t_offset=t_offset)
    return ob, (coll, objs, weights)


def foreground(hf: Terrain, points: list[tuple[float, float]], seed: int = 7, scale: tuple = (1.1, 2.0),
               t_offset: float = 0.0):
    """Tall blossoms at given ground points (near the camera path) for foreground depth-of-field framing."""
    import bpy  # noqa: PLC0415
    rng = random.Random(seed * 13 + 9)
    coll = bpy.data.collections.new("fg_instances")
    bpy.context.scene.collection.children.link(coll)
    coll.hide_render = True
    coll.hide_viewport = True
    from .world import toon_material  # noqa: PLC0415
    stem_m, _, _ = toon_material("fg_stem", "#7FA552", "#466340", soft=0.2)
    objs, weights = [], []
    for kind in ("cosmos", "daisy", "pink", "rose", "white", "cosmos"):     # no lupine cones in front of the lens
        pm, _, _ = toon_material(f"fg_petal_{kind}", FLOWERS[kind][0], rim=0.4, translucent=0.6, soft=0.2)
        cm, _, _ = toon_material(f"fg_centre_{kind}", FLOWERS[kind][1], soft=0.2)
        me = _flower(rng, kind)
        for m in (stem_m, pm, cm):
            me.materials.append(m)
        ob = bpy.data.objects.new(f"fg_{kind}", me)
        coll.objects.link(ob)
        objs.append(ob)
        weights.append(1.0)
    me = bpy.data.meshes.new("fg_points")
    me.from_pydata([(x, y, hf(x, y)) for x, y in points], [], [])
    ob = bpy.data.objects.new("fg_points", me)
    bpy.context.scene.collection.objects.link(ob)
    ng = bpy.data.node_groups.new("fg_gn", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g = NodeGraph(ng)
    gi, go = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    ci = g.node("GeometryNodeCollectionInfo", {"Separate Children": True, "Reset Children": True},
                transform_space="ORIGINAL")
    ci.inputs["Collection"].default_value = coll
    idx = g.node("FunctionNodeRandomValue", {"Min": 0, "Max": len(objs) - 1, "Seed": seed}, data_type="INT")
    yaw = g.node("FunctionNodeRandomValue", {"Min": 0.0, "Max": 6.2832, "Seed": seed + 1}, data_type="FLOAT")
    scl = g.node("FunctionNodeRandomValue", {"Min": scale[0], "Max": scale[1], "Seed": seed + 2}, data_type="FLOAT")
    rot = g.node("FunctionNodeEulerToRotation", {"Euler": g.xyz(0.0, 0.0, _rv_out(yaw))})
    iv = [s for s in idx.outputs if s.type == "INT"][0]
    iop = g.node("GeometryNodeInstanceOnPoints", {"Points": gi.outputs[0], "Instance": ci.outputs[0],
                                                  "Pick Instance": True, "Instance Index": iv,
                                                  "Rotation": rot.outputs[0], "Scale": _rv_out(scl)})
    st = g.node("GeometryNodeInputSceneTime")
    t = g.math("ADD", st.outputs["Seconds"], t_offset)
    rnd = g.node("FunctionNodeRandomValue", {"Min": 0.0, "Max": 1.0, "Seed": seed + 4}, data_type="FLOAT")
    eul = wind_rotation(g, g.node("GeometryNodeInputPosition").outputs[0], _rv_out(rnd), t, amp=0.16, gust=0.1,
                        flutter=0.04)
    wrot = g.node("FunctionNodeEulerToRotation", {"Euler": eul})
    ri = g.node("GeometryNodeRotateInstances", {"Instances": iop.outputs[0], "Rotation": wrot.outputs[0],
                                                "Pivot Point": g.node("GeometryNodeInputPosition").outputs[0],
                                                "Local Space": False})
    g.link(ri.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("fg", "NODES")
    mod.node_group = ng
    return ob
