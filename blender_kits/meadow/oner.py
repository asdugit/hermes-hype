"""Act 2 meadow oner: ONE continuous smooth camera move around a lone figure while red cars fly around her.

Anime sunset meadow (painterly sky, mauve mountains, wind-blown wildflowers, drifting petals). The camera starts
low behind the figure (backlit against the sun), dollies in, cranes and arcs around her left side to a
three-quarter front, then pushes into a hero close-up of the hovering car (light sweep across the paint, rims
spinning). Six cars, never in formation: one dives in from the left and banks out, one climbs on the right, one
drives over the hill crest and lifts off over the camera, one floats and hovers (the hero), one passes close to
the lens, one arcs across far behind. Rack focus between the figure and the cars; her head follows the pass-by.

Shot-local time t = t_offset + (frame - 1) / fps. A transition shot (transitions/petal_reveal) renders the first
seconds with the petal sheet; this scene then continues with ``t_offset`` so the camera never stops.
"""
from __future__ import annotations

import math

PARAMS = {
    "time_of_day": {"type": "enum", "values": ["sunset", "golden", "dawn"], "default": "sunset",
                    "doc": "sky palette"},
    "t_offset": {"type": "float", "default": 0.0, "doc": "start this many seconds into the oner (continuation shots)"},
    "density": {"type": "float", "default": 1.0, "doc": "meadow density multiplier (0.3 = sparse/fast)"},
    "figure": {"type": "bool", "default": True, "doc": "the lone figure in the middle"},
    "petals": {"type": "float", "default": 1.0, "doc": "ambient drifting petals amount"},
    "hero_at": {"type": "float", "default": 19.5, "doc": "when the camera arrives at the hero close-up (s)"},
    "length": {"type": "float", "default": 25.4, "doc": "designed length of the whole move (s)"},
    "reveal": {"type": "bool", "default": False,
               "doc": "open focused on an image plane 1 m from the lens (set by transitions/petal_reveal)"},
}
DESCRIBE = ("Anime sunset flower meadow; a lone figure in a white dress watches red cars fly around her "
            "(dive, climb, drive-over-hill lift-off, hover, close pass-by, far arc); one continuous crane/arc "
            "camera with rack focus, ending in a hero close-up of the hovering car with a light sweep.")

SUN = (15.0, 7.5)          # azimuth (deg from +Y toward +X), elevation
WIND = (1.0, 0.35)


def _p(sc, k):
    v = sc.params.get(k, PARAMS[k]["default"])
    return v


class Layout:
    """All world-space choreography for one aspect (16:9 or 9:16). Pure Python (testable without Blender)."""

    def __init__(self, aspect: str = "16:9", seed: int = 7, hero_at: float = 19.5, length: float = 25.4,
                 reveal: bool = False):
        from blender_kits.lib import camera as C
        from blender_kits.lib import flyers as Fl
        from blender_kits.lib import meadow as M
        self.C, self.Fl = C, Fl
        self.v = aspect == "9:16"
        self.hf = M.Terrain(seed=seed)
        hf = self.hf
        self.F = (0.0, 0.0, hf(0.0, 0.0))
        F = self.F
        self.head = (F[0], F[1], F[2] + 1.55)
        self.hero_at = hero_at
        self.length = length
        self.reveal = reveal

        def P(az, r, h, look_h=None):
            a = math.radians(az)
            x, y = F[0] + r * math.sin(a), F[1] + r * math.cos(a)
            return (x, y, hf(x, y) + h)
        v = self.v
        # hero hover spot (in front-left of her, a little above head height)
        self.H = (F[0] + 2.6, F[1] + 11.2, F[2] + 2.3)
        H = self.H
        rk = 1.12 if v else 1.0                     # portrait: a touch further back
        lz = 0.8 if v else 1.0                      # portrait: wider lens (sensor fits the height)
        sky_t = (F[0] + 6, F[1] + 22, F[2] + 4.2)   # look past her toward the sun
        mid_t = (F[0] - 2.0, F[1] + 4.0, F[2] + 2.6)
        # hero close-up: 3/4 front of the car from ~9 m (whole car in frame), then a slow push to ~7.5 m;
        # the camera sits between her and the car looking toward the warm side of the sky
        cd = (-0.52, -0.855)                      # unit ground direction from the car toward the camera
        d0, d1 = (9.6, 8.0) if not v else (10.5, 9.0)
        hero_cam = (H[0] + cd[0] * d0, H[1] + cd[1] * d0, H[2] + (0.9 if not v else 1.5))
        hero_tgt = (H[0], H[1], H[2] + (0.75 if not v else 1.6))
        side = (-cd[1], cd[0])                    # orbit a little while pushing
        hero_cam2 = (H[0] + cd[0] * d1 + side[0] * 1.6, H[1] + cd[1] * d1 + side[1] * 1.6, H[2] + (0.8 if not v else 1.4))
        self.hero_heading = math.degrees(math.atan2(cd[0], cd[1])) + 38.0
        B = C.Beat
        self.beats = [
            B(0.0, P(196, 8.6 * rk, 1.3), (F[0] + 0.6, F[1] + 6, F[2] + 2.2), 35 * lz, 4.0),
            B(4.6, P(204, 7.0 * rk, 1.55), sky_t, 32 * lz, 4.0),
            B(9.0, P(232, 9.6 * rk, 2.7), mid_t, 30 * lz, 3.5),
            B(13.4, P(272, 8.6 * rk, 2.1), (F[0] - 1.5, F[1] + 2.5, F[2] + 2.3), 32 * lz, 3.2),
            B(16.6, P(318, 8.6 * rk, 1.8), (F[0] + 0.4, F[1] + 3.0, F[2] + 2.0), 35 * lz, 3.0),
            B(hero_at, hero_cam, hero_tgt, 50 * (1.0 if not v else 0.75), 2.8),
            B(length, hero_cam2, hero_tgt, 55 * (1.0 if not v else 0.75), 2.8),
        ]
        # the camera is already moving when the petals clear (no start from rest); coasts out at the end
        self.move = C.Move(self.beats, v0=(0.08, 0.7, 0.05))
        self.flights = self._flights()
        self.poses_cache: dict = {}

    def _flights(self):
        Fl, hf, F, H = self.Fl, self.hf, self.F, self.H
        g = lambda x, y, dz: (x, y, hf(x, y) + dz)      # noqa: E731
        fl = []
        # 1 dive in from the upper left, bank across in front of her (against the sun), exit up-right
        fl.append(Fl.Flight("dive", [(-72, 70, 46), (-30, 34, 16), (-8, 16, 5.0), (14, 18, 6.5), (40, 26, 17),
                                     (70, 30, 34)], 0.6, 7.2, bank=1.3, meta={"ratio": (1.0, 1.25)}))
        # 2 climbs out from behind the right hill and away
        fl.append(Fl.Flight("climb", [g(34, 48, 3.0), g(42, 58, 7), (50, 74, 26), (56, 104, 62)], 3.6, 10.8,
                            bank=0.7, meta={"ratio": (0.65, 1.4)}))
        # 3 drives over the crest toward camera-left, lifts off and flies over the camera
        fl.append(Fl.Flight("drive", [g(-40, 64, 0), g(-30, 41, 0), g(-23, 25, 0), g(-18, 13, 0.3), (-15, 0, 8.0),
                                      (-10, -16, 15.0), (-2, -36, 22.0)], 3.4, 12.6, mode="drive",
                            drive_until=4.6, lift=1.6, bank=0.8, meta={"ratio": (0.8, 1.35)}))
        # 4 the hero: floats in, hovers with wheels spinning, settles into the close-up spot turning slowly
        fl.append(Fl.Flight("hero", [(-26, 30, F[2] + 10.0), (-5, 18, F[2] + 4.6), (H[0], H[1], H[2])], 7.8,
                            self.hero_at - 0.6, mode="hover", bob=0.09, yaw_rate=4.0,
                            yaw0=self.hero_heading - 4.0 * (self.hero_at + 1.5 - 7.8),
                            spin_rps=1.15, meta={"ratio": (0.9, 0.12)}))
        # 5 passes close to the lens, out over the meadow past her
        fl.append(Fl.Flight("pass", [(-34, -9, F[2] + 3.6), (-17, -3.6, F[2] + 3.7), (-8.5, 3.4, F[2] + 3.6),
                                     (6, 9, F[2] + 4.6), (30, 18, F[2] + 9), (60, 26, F[2] + 18)], 10.6, 15.6,
                            bank=1.1, meta={"ratio": (1.0, 1.1)}))
        # 6 a far arc across the sky behind the close-up (out of focus, colour and life)
        fl.append(Fl.Flight("arc", [(-120, 40, 22), (-70, 95, 40), (0, 120, 44), (70, 100, 34), (120, 50, 20)],
                            13.0, 26.0, bank=1.2, meta={"ratio": (0.95, 1.05)}))
        if self.v:
            fl = [self._squeeze(f) for f in fl]
        return fl

    def _squeeze(self, f):
        """Portrait: pull each control point toward the camera's view axis (x0.62) and stretch it up (x1.12)."""
        C = self.C
        n = len(f.points)
        pts = []
        for i, p in enumerate(f.points):
            t = f.t0 + (f.t1 - f.t0) * i / max(1, n - 1)
            s = self.move.eval(min(max(t, 0.0), self.length))
            fwd = s.fwd
            right = C._norm((fwd[1], -fwd[0], 0.0))
            up = (0.0, 0.0, 1.0)
            d = C._sub(p, s.pos)
            r = sum(d[k] * right[k] for k in range(3))
            u = d[2]
            q = C._add(s.pos, C._add(C._mul(right, r * 0.62), C._mul(up, u * 1.12)))
            q = C._add(q, C._mul((fwd[0], fwd[1], 0.0), sum(d[k] * fwd[k] for k in (0, 1))))
            alt = p[2] - self.hf(p[0], p[1])
            if f.mode == "drive" and alt < 0.5:
                q = (q[0], q[1], self.hf(q[0], q[1]))
            else:
                q = (q[0], q[1], max(q[2], self.hf(q[0], q[1]) + max(2.0, alt * 0.8)))
            pts.append(q)
        f.points = pts
        return f

    def poses(self, fps: float, frames: int, t_offset: float):
        key = (fps, frames, t_offset)
        if key not in self.poses_cache:
            self.poses_cache[key] = [self.Fl.plan(f, fps, frames, t_offset, ground=self.hf) for f in self.flights]
        return self.poses_cache[key]

    def pos_fn(self, name: str):
        """Smooth position function of a flyer (for aim / focus / head-follow)."""
        f = [x for x in self.flights if x.name == name][0]
        path = self.Fl._Path(f.points)
        Fl = self.Fl

        def fn(t: float):
            s, _ = Fl._distance(f, path.length, t)
            p, _ = path.at(s)
            return (p[0], p[1], p[2] + 0.6)
        if "ratio" in f.meta:
            T = f.t1 - f.t0
            f.v0, f.v1 = f.meta["ratio"][0] * path.length / T, f.meta["ratio"][1] * path.length / T
        return fn

    def rig(self):
        """Camera move with aim windows and rack focus."""
        mv = self.move
        mv._aims.clear()
        w = 0.6 if self.v else 0.32
        mv.aim(4.0, 5.6, 8.2, 9.6, self.pos_fn("drive"), w * 0.8)
        mv.aim(11.6, 12.4, 13.0, 14.2, self.pos_fn("pass"), w)
        mv.aim(14.6, 16.0, 30.0, 31.0, self.pos_fn("hero"), 0.55 if not self.v else 0.7)
        first = [(0.0, 1.0), (0.45, self.head)] if self.reveal else [(0.0, self.head)]
        mv.focus_on([*first, (5.4, self.pos_fn("drive")), (9.0, self.head),
                     (12.1, self.pos_fn("pass")), (13.5, self.head), (16.2, self.pos_fn("hero"))], dur=0.85)
        return mv


def _layout(sc) -> "Layout":
    return Layout(sc.aspect, sc.seed, float(_p(sc, "hero_at")), float(_p(sc, "length")), bool(_p(sc, "reveal")))


def _t0(sc) -> float:
    """Oner time of rendered frame 1 (t_offset + the shot's pre-handle)."""
    return float(_p(sc, "t_offset")) + float(getattr(sc, "t_start", 0.0))


def _model(sc) -> str | None:
    prod = sc.product
    if isinstance(prod, str):                       # scratch runners pass the asset name
        prod = {"name": prod, **sc.assets.get(prod, {})}
    if prod and prod.get("kind") == "model":
        return prod["path"]
    for a in (sc.assets or {}).values():
        if a.get("kind") == "model":
            return a["path"]
    return None


def build(sc) -> None:

    from blender_kits.lib import camera as C
    from blender_kits.lib import figure as Fig
    from blender_kits.lib import flyers as Fl
    from blender_kits.lib import look, meadow, petals, world
    t_off = _t0(sc)
    pal = _p(sc, "time_of_day")
    L = _layout(sc)
    sc._layout = L
    look.setup(sc, sc.tier)
    world.sky(pal, SUN, seed=sc.seed, fps=sc.fps, frames=sc.frames, t_offset=t_off)
    world.sun_light(*SUN, strength=3.4)
    world.mountains(center=(0, 0, L.F[2] - 3), palette=pal, seed=sc.seed)
    meadow.terrain_object(L.hf, palette=pal)
    dens = float(_p(sc, "density")) * (0.55 if sc.tier == "preview" else 1.0)
    cw = meadow.instance_collection(sc.seed)
    meadow.scatter(L.hf, center=(-3, 2), radius=30, density=16.0 * dens, seed=sc.seed, coll_weights=cw,
                   t_offset=t_off, falloff=14)
    # tall foreground blossoms along the camera path (ground points 1.2-3 m beside it)
    mv = L.rig()
    pts = []
    rng = sc.rng
    for i in range(0, 220):
        tt = L.length * i / 220
        s = mv.eval(tt)
        side = 1 if rng.random() < 0.5 else -1
        nx, ny = s.fwd[1] * side, -s.fwd[0] * side
        d = rng.uniform(1.4, 3.6)
        ahead = rng.uniform(1.5, 5.0)
        x, y = s.pos[0] + nx * d + s.fwd[0] * ahead, s.pos[1] + ny * d + s.fwd[1] * ahead
        if math.hypot(x - L.F[0], y - L.F[1]) > 2.2 and math.hypot(x - L.H[0], y - L.H[1]) > 3.0:
            pts.append((x, y))
    meadow.foreground(L.hf, pts, seed=sc.seed, t_offset=t_off)
    if _p(sc, "figure"):
        fig = Fig.build(location=L.F, facing_deg=SUN[0] - 8, wind=WIND, t_offset=t_off)
        Fig.look_at(fig, [(0.0, 3.5, L.pos_fn("dive")), (11.2, 15.2, L.pos_fn("pass")),
                          (16.5, 40.0, L.pos_fn("hero"))], sc.fps, sc.frames, t_offset=t_off)
    amt = float(_p(sc, "petals"))
    if amt > 0:
        cam_pts = [mv.eval(L.length * i / 12).pos for i in range(13)]
        petals.drift(center=(L.F[0], L.F[1] + 6, L.F[2] + 5), size=(80, 80, 14), count=int(1400 * amt),
                     wind=(1.3, 0.45, 0.1), seed=sc.seed, dur=L.length + 2, t_offset=t_off, near=cam_pts,
                     near_count=int(260 * amt), near_radius=5.0)
    # cars
    model = _model(sc)
    if model is None:
        raise RuntimeError("meadow/oner needs a 3D product model asset (kind=model)")
    src = Fl.load_car(model)
    poses = L.poses(sc.fps, sc.frames, t_off)
    for f, ps in zip(L.flights, poses):
        root, wheels = Fl.instance_car(src, f"car_{f.name}")
        Fl.apply(root, wheels, ps)
    # camera
    cam = C.make_camera("cam")
    samples = mv.sample(sc.fps, sc.frames, t_off)
    C.apply(cam, samples, sensor_fit="AUTO")
    # hero light sweep: a soft strip light gliding over the hero car during the close-up
    _light_sweep(L, sc, t_off)
    g = look.grade(sc, "anime_sunset")
    sc._grade = g
    sc._camera = cam


def _light_sweep(L, sc, t_off: float) -> None:
    import bpy

    from blender_kits.lib.camera import linearize, smootherstep
    H = L.H
    ld = bpy.data.lights.new("sweep", "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = 7.0, 0.35
    ld.energy = 0.0
    ld.color = (1.0, 0.93, 0.86)
    ob = bpy.data.objects.new("sweep", ld)
    bpy.context.scene.collection.objects.link(ob)
    t0, t1 = L.hero_at - 1.5, L.hero_at + 3.8
    for f in range(1, sc.frames + 1):
        t = t_off + (f - 1) / sc.fps
        u = smootherstep((t - t0) / (t1 - t0))
        ob.location = (H[0] - 5.0 + 9.0 * u, H[1] - 1.5 + 2.0 * u, H[2] + 3.4)
        ob.rotation_euler = (math.radians(-22), 0, math.radians(-60))
        ld.energy = 900.0 * math.sin(math.pi * u) ** 2 if 0 < u < 1 else 0.0
        ob.keyframe_insert("location", frame=f)
        ld.keyframe_insert("energy", frame=f)
    linearize(ob)
    linearize(ld)


def cues(sc) -> list[dict]:
    """Whoosh at each car's closest approach to the camera (shot-local seconds), chime on the hero arrival."""
    L = getattr(sc, "_layout", None) or _layout(sc)
    t_off = _t0(sc)
    t_shot0 = float(getattr(sc, "t_start", 0.0))
    mv = L.rig()
    out = []
    poses = L.poses(sc.fps, sc.frames, t_off)
    cams = [mv.eval(t_off + (f - 1) / sc.fps).pos for f in range(1, sc.frames + 1)]
    for f, ps in zip(L.flights, poses):
        if f.mode == "hover":
            continue
        best = min(range(len(ps)), key=lambda i: sum((ps[i].pos[k] - cams[i][k]) ** 2 for k in range(3)))
        d = math.sqrt(sum((ps[best].pos[k] - cams[best][k]) ** 2 for k in range(3)))
        if d < 30 and 2 < best < len(ps) - 3:
            t = t_shot0 + best / sc.fps - 0.35
            sfx = "whoosh_long" if d < 8 else "whoosh_short"
            out.append({"t": round(max(0.0, t), 3), "sfx": sfx, "gain_db": round(max(-14.0, -2.0 - d * 0.45), 1)})
    th = L.hero_at - 0.4 - t_off + t_shot0
    if t_shot0 < th < t_shot0 + sc.frames / sc.fps:
        out.append({"t": round(th, 3), "sfx": "chime", "gain_db": -9})
    return sorted(out, key=lambda c: c["t"])
