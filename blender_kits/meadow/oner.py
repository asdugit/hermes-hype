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
    "crowd": {"type": "float", "default": 1.0, "doc": "how many cars fill the sky (1 = ~60 cars; 0.3 = a few)"},
    "reveal": {"type": "bool", "default": False,
               "doc": "open focused on an image plane 1 m from the lens (set by transitions/petal_reveal)"},
}
DESCRIBE = ("Anime sunset flower meadow; a lone figure in a white dress watches red cars fly around her "
            "(dive, climb, drive-over-hill lift-off, hover, close pass-by, far arc); one continuous crane/arc "
            "camera with rack focus, ending in a hero close-up of the hovering car with a light sweep.")

SUN = (15.0, 7.5)          # azimuth (deg from +Y toward +X), elevation
WIND = (1.0, 0.35)
# terrain: her knoll, the crest the "drive" car comes down (front-right), the hill the "climb" car rises behind
# (front-left), far rolling hills
HILLS = [(0.0, 0.0, 1.0, 16.0), (22.0, 30.0, 3.2, 9.0), (-26.0, 34.0, 2.6, 10.0), (-70.0, 95.0, 5.0, 30.0),
         (60.0, 80.0, 4.0, 24.0), (20.0, -60.0, 1.6, 22.0)]
# far bird-like streams circling the meadow: (radius, height, start az, deg/s, members, undulation, phase)
RINGS = [(62.0, 6.0, 282.0, 13.0, 10, 5.0, 0.0), (86.0, 12.0, 40.0, -11.0, 10, 6.0, 1.7),
         (108.0, 8.0, 264.0, 8.5, 9, 6.5, 3.1), (46.0, 9.0, 325.0, -15.0, 8, 4.0, 4.4),
         (74.0, 17.0, 240.0, 10.0, 8, 6.0, 5.2), (34.0, 5.0, 14.0, 18.0, 7, 2.5, 2.3)]


def _p(sc, k):
    v = sc.params.get(k, PARAMS[k]["default"])
    return v


class Layout:
    """All world-space choreography for one aspect (16:9 or 9:16). Pure Python (testable without Blender).

    Named flights near her and the lens are *screen-anchored*: each key says where the car is in the frame at a
    moment of the move (NDC x/y + depth, or camera-local metres for flights from behind the lens), so the cars stay
    big and framed in both aspects; positions between keys are a C2 spline in time (smooth, no stalls). Loose
    groups follow a leader and break apart; far streams circle the meadow like birds (dozens of cars).
    """

    def __init__(self, aspect: str = "16:9", seed: int = 7, hero_at: float = 19.5, length: float = 25.4,
                 reveal: bool = False, crowd: float = 1.0):
        from blender_kits.lib import camera as C
        from blender_kits.lib import flyers as Fl
        from blender_kits.lib import meadow as M
        self.C, self.Fl = C, Fl
        self.v = aspect == "9:16"
        self.aspect = 9 / 16 if self.v else 16 / 9
        self.seed = seed
        self.crowd = crowd
        self.hf = M.Terrain(seed=seed, hills=[tuple(h) for h in HILLS])
        hf = self.hf
        self.F = (0.0, 0.0, hf(0.0, 0.0))
        F = self.F
        self.head = (F[0], F[1], F[2] + 1.55)
        self.hero_at = hero_at
        self.length = length
        self.reveal = reveal

        def P(az, r, h):
            a = math.radians(az)
            x, y = F[0] + r * math.sin(a), F[1] + r * math.cos(a)
            return (x, y, hf(x, y) + h)
        self.P = P
        T = self.T
        v = self.v
        self.H = (F[0] + 5.6, F[1] - 9.6, F[2] + 2.3)        # hero hover spot behind her (sun-lit side)
        H = self.H
        rk = 1.12 if v else 1.0                     # portrait: a touch further back
        lz = 0.8 if v else 1.0                      # portrait: wider lens (sensor fits the height)
        # hero close-up: 3/4 front of the whole car, slow push + orbit; the camera sits between her and the car
        cd = (-0.848, 0.53)                         # unit ground direction from the car toward the camera
        d0, d1 = (12.2, 10.8) if not v else (13.2, 11.8)
        hero_cam = (H[0] + cd[0] * d0, H[1] + cd[1] * d0, H[2] + (0.9 if not v else 1.4))
        hero_tgt = (H[0], H[1], H[2] + (0.7 if not v else 1.5))
        side = (-cd[1], cd[0])
        hero_cam2 = (H[0] + cd[0] * d1 + side[0] * 1.6, H[1] + cd[1] * d1 + side[1] * 1.6,
                     H[2] + (0.8 if not v else 1.3))
        self.hero_heading = math.degrees(math.atan2(cd[0], cd[1])) + 38.0
        B = C.Beat
        beats = [
            # behind her, low: she is big and backlit; the camera is already moving as the petals clear
            B(0.0, P(197, 6.4 * rk, 1.2), T(1.4, 9, 1.9), 35 * lz, 2.8),
            # sweeping crane up and back: the sky full of red cars above the meadow
            B(3.8, P(188, 9.2 * rk, 4.3), T(0.4, 14, 3.3), 30 * lz, 5.6),
            # swoop down into the flowers: low hero angle under a car flying overhead
            B(6.4, P(206, 8.0 * rk, 0.7), T(-1.0, 8, 6.0), 26 * lz, 4.0),
        ]
        # flight alongside: the "wing" car circles her while the camera flies with it on a wider circle
        self.wing_az = lambda t: 215.0 + 25.0 * (t - 8.4)      # noqa: E731
        for t in (8.4, 9.55, 10.7, 11.85, 13.0):
            w = self._wing_pt(t)
            cam = P(self.wing_az(t) - 13.0, 19.0 * rk, 0.0)
            cam = (cam[0], cam[1], max(cam[2] + 1.5, w[2] + 1.3))
            tgt = C._lerp(C._add(w, (0, 0, 0.6)), (F[0], F[1], F[2] + 1.2), 0.36)
            beats.append(B(t, cam, tgt, 28 * lz, 4.0))
        beats += [
            # settle at her front-left three-quarter: cars cross close in front, focus racks through them to her
            B(15.0, P(332, 9.5 * rk, 1.45), T(0.6, -1.0, 1.3), 40 * lz, 2.0),
            B(17.3, P(282, 5.8 * rk, 1.7), C._lerp(T(0.0, 0.0, 1.4), H, 0.55), 44 * lz, 2.4),
            # final push into the hero close-up (light sweep, rims spinning)
            B(hero_at, hero_cam, hero_tgt, 46 * (1.0 if not v else 0.8), 2.8),
            B(length, hero_cam2, hero_tgt, 50 * (1.0 if not v else 0.8), 2.8),
        ]
        self.beats = beats
        self.move = C.Move(self.beats, v0=(0.10, 0.55, 0.15))
        self.base = C.Move(self.beats, v0=(0.10, 0.55, 0.15))   # aim-free copy: screen anchors
        self.flights = self._flights()
        self.poses_cache: dict = {}

    def T(self, dx, dy, dz):
        F = self.F
        return (F[0] + dx, F[1] + dy, F[2] + dz)

    def _wing_pt(self, t: float):
        """The tracked car: spirals in from high on the right, circles her at 11 m, climbs away after 13 s."""
        a = math.radians(self.wing_az(t))
        r = 11.0 + 2.6 * max(0.0, 8.4 - t) + 2.4 * max(0.0, t - 13.0) ** 1.5
        h = 3.0 + 2.8 * max(0.0, 8.4 - t) + 1.6 * max(0.0, t - 13.0) ** 2
        x, y = self.F[0] + r * math.sin(a), self.F[1] + r * math.cos(a)
        return (x, y, max(self.hf(x, y) + 2.2, self.F[2] + h))

    # ------------------------------------------------------------------------------------------- anchors
    def _basis(self, t: float):
        C = self.C
        s = self.base.eval(t)
        fwd = s.fwd
        right = C._norm((fwd[1], -fwd[0], 0.0))
        up = (right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2],
              right[0] * fwd[1] - right[1] * fwd[0])
        half = 18.0 / s.lens
        th, tv = (half, half / self.aspect) if self.aspect >= 1 else (half * self.aspect, half)
        return s, fwd, right, up, th, tv

    def S(self, t: float, sx: float, sy: float | None, d: float, alt: float = 1.0):
        """World point that the camera (aim-free move) sees at NDC (sx, sy) and depth d at move time t.
        ``sy=None`` puts it on the ground; flying points keep >= ``alt`` m above the terrain."""
        C = self.C
        s, fwd, right, up, th, tv = self._basis(t)
        p = C._add(C._add(s.pos, C._mul(fwd, d)), C._mul(right, sx * th * d))
        if sy is None:
            return (p[0], p[1], self.hf(p[0], p[1]))
        p = C._add(p, C._mul(up, sy * tv * d))
        return (p[0], p[1], max(p[2], self.hf(p[0], p[1]) + alt))

    def K(self, t: float, rx: float, uy: float, fz: float):
        """World point in camera-local metres (right, up, forward) at move time t (keys behind the lens)."""
        C = self.C
        s, fwd, right, up, _, _ = self._basis(t)
        return C._add(C._add(C._add(s.pos, C._mul(right, rx)), C._mul(up, uy)), C._mul(fwd, fz))

    def _fl(self, name: str, keys, **kw):
        times = [k[0] for k in keys]
        pts = [k[1] for k in keys]
        return self.Fl.Flight(name, pts, times[0], times[-1], times=times, **kw)

    def _fla(self, name: str, anchors, even: float = 0.65, **kw):
        """Flight through screen anchors [(t, ("S", sx, sy, d[, alt]) | ("K", rx, uy, fz))]; key times are pulled
        toward constant speed (chord-length timing, ``even`` 0..1) and the anchors re-evaluated at the new times."""
        ts = [a[0] for a in anchors]

        def pts_at(times):
            out = []
            for t, (_, a) in zip(times, anchors):
                out.append(self.S(t, *a[1:]) if a[0] == "S" else self.K(t, *a[1:]) if a[0] == "K"
                           else self.T(*a[1:]))
            return out
        t0, t1 = ts[0], ts[-1]
        times = list(ts)
        for _ in range(3):
            pts = pts_at(times)
            ch = [0.0]
            for i in range(1, len(pts)):
                ch.append(ch[-1] + math.dist(pts[i], pts[i - 1]))
            times = [t0 + (t1 - t0) * ((1 - even) * (ts[i] - t0) / (t1 - t0) + even * ch[i] / ch[-1])
                     for i in range(len(ts))]
        return self.Fl.Flight(name, pts_at(times), t0, t1, times=times, **kw)

    def _flights(self):
        S, K, H, T = self.S, self.K, self.H, self.T
        Fl = self.Fl
        fl = []
        # 1 "coming down": dives in from the upper left as the petals clear, banks across in front of her
        fl.append(self._fla("dive", [(0.5, ("S", -1.4, 0.95, 34)), (1.9, ("S", -0.65, 0.5, 23)),
                                     (3.3, ("S", -0.15, 0.10, 20)), (4.6, ("S", 0.38, 0.02, 19)),
                                     (5.9, ("S", 0.95, 0.30, 23)), (7.1, ("S", 1.5, 0.7, 32))], bank=1.3))
        # 2 "driving down": over the front-right crest, down the slope, lifts off to the left
        fl.append(self._fla("drive", [(1.2, ("S", 1.4, None, 36)), (2.6, ("S", 0.85, None, 31)),
                                      (4.0, ("S", 0.35, None, 27)), (5.4, ("S", -0.1, None, 24)),
                                      (6.6, ("S", -0.5, 0.05, 23, 0.6)), (7.8, ("S", -0.95, 0.35, 27)),
                                      (9.0, ("S", -1.5, 0.7, 35))],
                           mode="drive", drive_until=5.0, lift=1.3, bank=0.8))
        # 3 "going up": rises from behind the front-left hill and climbs across the sun
        fl.append(self._fla("climb", [(3.0, ("S", -1.4, 0.1, 33, 3.0)), (4.4, ("S", -0.8, 0.12, 29)),
                                      (5.8, ("S", -0.3, 0.45, 28)), (7.2, ("S", 0.2, 0.85, 30)),
                                      (8.6, ("S", 0.65, 1.3, 36))], bank=0.9))
        # 4 flies over the low camera from behind and climbs away into the frame
        fl.append(self._fla("over", [(5.0, ("K", 0.6, 3.6, -16.0)), (5.9, ("K", 0.2, 3.9, -3.5)),
                                     (6.6, ("S", -0.3, 0.55, 8.5)), (7.4, ("S", -0.5, 0.6, 17)),
                                     (8.3, ("S", -0.75, 0.7, 29))], bank=1.0))
        # 5 the tracked "wing" car: the camera flies alongside it around her
        wk = [(t, self._wing_pt(t)) for t in [6.4 + 0.5 * k for k in range(18)]]
        fl.append(self._fl("wing", wk, bank=1.1))
        # 6/7 cross close in front of the lens (out of focus) while the focus racks through them to her
        cx, cy = (1.0, 1.0) if not self.v else (1.8, 0.55)     # portrait: wider sweep in NDC, flatter
        fl.append(self._fla("cross1", [(12.4, ("S", -1.9 * cx, -0.5 * cy, 5.4)), (13.3, ("S", -0.1, -0.55 * cy, 5.0)),
                                       (14.2, ("S", 1.7 * cx, -0.5 * cy, 5.4)), (15.1, ("S", 3.0 * cx, -0.3, 6.8))],
                            bank=1.0, even=0.9))
        fl.append(self._fla("cross2", [(13.4, ("S", 2.4 * cx, -0.3 * cy, 5.8)), (14.1, ("S", 1.0 * cx, -0.5 * cy, 4.8)),
                                       (14.8, ("S", -0.6 * cx, -0.55 * cy, 4.6)), (15.5, ("S", -2.2 * cx, -0.4 * cy, 5.2))],
                            bank=1.0, even=0.9))
        # 8 the hero, "just floating": drifts in high on the left, hovers with wheels spinning, settles at H
        t_h = self.hero_at - 0.6
        fl.append(self._fl("hero", [(9.0, T(-20, -27, 10.0)), (11.5, T(-9, -24, 7.0)), (14.0, T(1.5, -16.5, 4.6)),
                                    (16.5, T(4.6, -11.6, 3.0)), (t_h, H),
                                    (self.length + 2.0, (H[0] + 0.5, H[1] + 0.2, H[2] + 0.1))],
                           mode="hover", bob=0.09, yaw_rate=4.0,
                           yaw0=self.hero_heading - 4.0 * (self.hero_at + 1.5 - 9.0), spin_rps=1.15))
        # loose groups that fly in formation and break apart (mid distance)
        groups = [
            ("g0", 2.6, [(0.0, ("S", 1.7, 0.75, 44)), (1.6, ("S", 0.7, 0.62, 38)), (3.2, ("S", -0.3, 0.6, 36)),
                         (4.8, ("S", -1.3, 0.75, 40)), (6.0, ("S", -2.0, 0.9, 46))]),
            ("g1", 5.0, [(1.6, ("W", 34, 34, 12)), (3.6, ("W", 12, 41, 10)), (5.6, ("W", -10, 41, 11)),
                         (7.6, ("W", -30, 33, 13)), (9.4, ("W", -45, 21, 15))]),
            ("g2", 11.6, [(9.0, ("S", -1.6, 0.45, 40)), (11.0, ("S", -0.5, 0.35, 37)),
                          (13.0, ("S", 0.5, 0.45, 37)), (15.0, ("S", 1.6, 0.7, 42))]),
            ("g4", 16.0, [(13.4, ("W", 40, -28, 12)), (15.0, ("W", 18, -36, 10)), (16.6, ("W", -4, -38, 11)),
                          (18.2, ("W", -24, -32, 13)), (19.4, ("W", -38, -20, 15))]),
            ("g3", 21.0, [(17.0, ("S", -1.7, 0.55, 48)), (19.5, ("S", -0.7, 0.5, 42)),
                          (22.0, ("S", 0.3, 0.55, 42)), (24.5, ("S", 1.3, 0.65, 46)),
                          (26.5, ("S", 2.0, 0.8, 52))]),
        ]
        slots = [(0.0, 0.0, 0.0), (-3.2, 0.8, 3.5), (3.4, -0.4, 4.0), (-6.2, 1.3, 7.5), (6.6, 0.4, 8.0)]
        import random as _r
        rng = _r.Random(self.seed * 31 + 5)
        for gname, t_break, keys in groups:
            lead = self._fla(gname, keys, even=0.9)
            for i, sl in enumerate(slots[: max(2, int(round(len(slots) * min(1.0, self.crowd))))]):
                peel = (rng.uniform(-1, 1), rng.uniform(-0.6, 1.0), rng.uniform(-0.6, 0.0))   # never falls back
                k = rng.uniform(1.2, 2.4)
                ph = rng.uniform(0, 6.28)

                def off(t, sl=sl, peel=peel, k=k, ph=ph, tb=t_break):
                    u = max(0.0, t - tb)
                    q = u * min(u, 2.0) * 0.8                 # peel-off: eases in, then a steady drift apart
                    s = 1.0 + 0.15 * u
                    w = 0.35 * math.sin(1.3 * t + ph)
                    return (sl[0] * s + peel[0] * k * q + w, sl[1] * s + peel[1] * k * q * 0.6 + w * 0.5,
                            sl[2] + peel[2] * k * q)
                fl.append(Fl.follow(lead, f"{gname}_{i}", lag=0.12 * i, offset=off, t0=keys[0][0] - 1.0,
                                    t1=keys[-1][0] + 1.0, step=0.5, ground=self.hf, alt=3.0,
                                    bank=rng.uniform(0.9, 1.4), scale=rng.uniform(0.92, 1.08),
                                    meta={"group": gname}))
        # far streams circling the meadow like flocks of birds
        for ri, (R, h, a0, om, n, und, ph) in enumerate(RINGS):
            lead = Fl.ring(f"ring{ri}", self.F, R, h, a0, om, -4.0, self.length + 4.0, undulate=und, phase=ph)
            n = max(2, int(round(n * self.crowd)))
            lag = 0.0
            for i in range(n):
                p1, p2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
                lat, ver = rng.uniform(-7.0, 7.0), rng.uniform(-3.5, 3.5)
                f1, f2 = rng.uniform(0.35, 0.8), rng.uniform(0.5, 1.1)

                def off(t, p1=p1, p2=p2, lat=lat, ver=ver, f1=f1, f2=f2):
                    return (lat + 2.6 * math.sin(f1 * t + p1), ver + 1.6 * math.sin(f2 * t + p2), 0.0)
                fl.append(Fl.follow(lead, f"s{ri}_{i}", lag=lag, offset=off,
                                    t0=-3.0, t1=self.length + 3.0, step=0.8, ground=self.hf, alt=4.0,
                                    bank=rng.uniform(0.8, 1.6), scale=rng.uniform(0.9, 1.1), meta={"stream": ri}))
                lag += rng.uniform(0.22, 0.75)
        return fl

    def poses(self, fps: float, frames: int, t_offset: float):
        key = (fps, frames, t_offset)
        if key not in self.poses_cache:
            self.poses_cache[key] = [self.Fl.plan(f, fps, frames, t_offset, ground=self.hf) for f in self.flights]
        return self.poses_cache[key]

    def pos_fn(self, name: str):
        """Smooth position function of a flyer (for aim / focus / head-follow): car centre."""
        f = [x for x in self.flights if x.name == name][0]
        sp = self.Fl.timed_spline(f)

        def fn(t: float):
            p = sp(t)
            return (p[0], p[1], p[2] + 0.6)
        return fn

    def named(self):
        return [f for f in self.flights if not ({"group", "stream"} & set(f.meta))]

    def framing(self, fps: float = 30.0, t0: float = 0.0, t1: float | None = None, step: int = 1,
                occlusion: bool = True) -> list[dict]:
        """Per-frame screen framing (pure Python): each car's visible box (fraction of the frame width/height,
        cut by the frame edge, hidden behind the terrain), the figure's box, the readable cars (>= 12 % wide,
        fully inside the frame or a fast pass-by) — the QA the oner's choreography is tuned against."""
        C, Fl = self.C, self.Fl
        t1 = self.length if t1 is None else t1
        aspect = 9 / 16 if self.v else 16 / 9
        mv = self.rig()
        frames = int(round((t1 - t0) * fps)) + 1
        poses = self.poses(fps, frames, t0)
        hw, hl, _, top = Fl.CAR_HALF
        out = []
        prev_x: dict = {}
        for i in range(0, frames, step):
            t = t0 + i / fps
            s = mv.eval(t)
            row = {"t": round(t, 3), "cars": {}, "readable": []}
            F = self.F
            fig = C.screen_box(s, [(F[0] + dx, F[1] + dy, F[2] + dz) for dx in (-0.3, 0.3) for dy in (-0.3, 0.3)
                                   for dz in (0.0, 1.78)], aspect)
            row["fig"] = fig
            for f, ps in zip(self.flights, poses):
                p = ps[i]
                right = C._norm(Fl._cross(p.fwd, p.up))
                cs = [C._add(C._add(C._add(p.pos, C._mul(right, sx * hw)), C._mul(p.fwd, sy * hl)), C._mul(p.up, z))
                      for sx in (-1, 1) for sy in (-1, 1) for z in (0.0, top)]
                b = C.screen_box(s, cs, aspect)
                if b is None or not b["visible"]:
                    prev_x.pop(f.name, None)
                    continue
                cx = (b["x0"] + b["x1"]) / 2
                b["vx"] = abs(cx - prev_x[f.name]) * fps / step if f.name in prev_x else 0.0   # NDC/s
                prev_x[f.name] = cx
                b["hidden"] = occlusion and self._occluded(s.pos, C._add(p.pos, C._mul(p.up, 0.6)))
                row["cars"][f.name] = b
                fast = b["vx"] > 1.2
                if b["w"] >= 0.12 and not b["hidden"] and (b["inside"] or fast or b["w"] > 0.5):
                    row["readable"].append(f.name)
            out.append(row)
        return out

    def _occluded(self, a, b, n: int = 16) -> bool:
        for k in range(1, n):
            u = k / n
            x, y, z = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
            if self.hf(x, y) + 0.25 > z:
                return True
        return False

    def windows(self, fps: float, frames: int, t_offset: float) -> list[tuple[int, int]]:
        """Per flight, the rendered-frame index range [a, b] in which the car exists: it appears / vanishes only
        on a frame where it is off-screen (named cars and groups); far streams are always there."""
        rows = self.framing(fps, t_offset, t_offset + (frames - 1) / fps, occlusion=False)
        out = []
        for f in self.flights:
            if "stream" in f.meta:
                out.append((0, frames - 1))
                continue
            on = [f.name in r["cars"] for r in rows]
            i0 = max(0, min(frames - 1, int(round((f.t0 - t_offset) * fps))))
            i1 = max(0, min(frames - 1, int(round((f.t1 - t_offset) * fps))))
            a = i0
            while a > 0 and on[a]:
                a -= 1
            b = i1
            while b < frames - 1 and on[b]:
                b += 1
            out.append((a, b))
        return out

    def rig(self):
        """Camera move with aim windows (partial follow of the car in play) and rack focus."""
        mv = self.move
        mv._aims.clear()
        w = 0.45 if self.v else 0.28
        mv.aim(1.6, 2.8, 4.4, 5.8, self.pos_fn("dive"), w)
        mv.aim(5.6, 6.3, 6.9, 7.8, self.pos_fn("over"), w * 0.6)
        mv.aim(16.0, 17.6, 30.0, 31.0, self.pos_fn("hero"), 0.6 if not self.v else 0.7)
        first = [(0.0, 1.0), (0.45, self.head)] if self.reveal else [(0.0, self.head)]
        mv.focus_on([*first, (2.4, self.pos_fn("dive")), (4.6, self.head), (6.0, self.pos_fn("over")),
                     (7.6, self.pos_fn("wing")), (12.6, self.pos_fn("cross1")), (13.7, self.head),
                     (14.6, self.pos_fn("cross2")), (15.6, self.head), (16.8, self.pos_fn("hero"))], dur=0.8)
        return mv


def _layout(sc) -> "Layout":
    return Layout(sc.aspect, sc.seed, float(_p(sc, "hero_at")), float(_p(sc, "length")), bool(_p(sc, "reveal")),
                  crowd=float(_p(sc, "crowd")))


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
    meadow.scatter(L.hf, center=(0, 2), radius=36, density=17.0 * dens, seed=sc.seed, coll_weights=cw,
                   t_offset=t_off, falloff=16)
    # tall foreground blossoms along the camera path (ground points 1.2-3 m beside it)
    mv = L.rig()
    pts = []
    rng = sc.rng
    for i in range(0, 300):
        tt = L.length * i / 300
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
        Fig.look_at(fig, [(0.6, 4.8, L.pos_fn("dive")), (5.4, 7.8, L.pos_fn("over")),
                          (8.6, 12.8, L.pos_fn("wing")), (16.4, 40.0, L.pos_fn("hero"))], sc.fps, sc.frames,
                    t_offset=t_off)
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
    wins = L.windows(sc.fps, sc.frames, t_off)
    for f, ps, (a, b) in zip(L.flights, poses, wins):
        root, wheels = Fl.instance_car(src, f"car_{f.name}")
        Fl.apply(root, wheels, ps, scale=f.scale, visible=[a <= i <= b for i in range(len(ps))],
                 spin=not ("stream" in f.meta))
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
    from mathutils import Vector
    t0, t1 = L.hero_at - 1.5, L.hero_at + 3.8
    cam = L.move.eval(L.hero_at).pos
    vd = Vector((H[0] - cam[0], H[1] - cam[1], 0.0)).normalized()
    side = Vector((vd.y, -vd.x, 0.0))
    ob.rotation_mode = "QUATERNION"
    for f in range(1, sc.frames + 1):
        t = t_off + (f - 1) / sc.fps
        u = smootherstep((t - t0) / (t1 - t0))
        pos = Vector(H) + side * (-5.0 + 9.0 * u) - vd * 1.0 + Vector((0, 0, 3.4))
        ob.location = pos
        ob.rotation_quaternion = (Vector(H) - pos).to_track_quat("-Z", "Y")
        ob.keyframe_insert("rotation_quaternion", frame=f)
        ld.energy = 900.0 * math.sin(math.pi * u) ** 2 if 0 < u < 1 else 0.0
        ob.keyframe_insert("location", frame=f)
        ld.keyframe_insert("energy", frame=f)
    linearize(ob)
    linearize(ld)
    # a long soft strip above the hover spot: clean highlights along the shoulder and roof (camera-invisible)
    st = bpy.data.lights.new("strip", "AREA")
    st.shape, st.size, st.size_y, st.energy = "RECTANGLE", 9.0, 1.1, 420.0
    st.color = (1.0, 0.95, 0.92)
    so = bpy.data.objects.new("strip", st)
    bpy.context.scene.collection.objects.link(so)
    so.location = Vector(H) + Vector((0, 0, 4.2)) - vd * 0.8
    so.rotation_mode = "QUATERNION"
    so.rotation_quaternion = (Vector(H) - so.location).to_track_quat("-Z", "Y")


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
        if f.mode == "hover" or {"stream", "group"} & set(f.meta):
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
