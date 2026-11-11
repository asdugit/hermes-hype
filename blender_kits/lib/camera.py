"""Smooth cinematic camera rigs for Hype Blender scenes (runs inside Blender; the math is pure Python).

Model: a move is a list of **beats** (time, position, target, lens, f-stop, roll). Every channel is a C2 cubic
spline in *time* through its beats (continuous velocity AND acceleration), so the camera never pops at a beat.
Optional per-move time warp eases the whole move. Aim and focus can blend smoothly onto moving subjects (follow /
rack focus) with smootherstep windows, so blends never introduce a velocity jump either.

    from blender_kits.lib import camera
    rig = camera.Move([camera.Beat(0, (0, -16, 1.2), (0, 0, 1.4), lens=32), camera.Beat(6, ...)], v0=(0, 1.2, 0))
    rig.aim(t0=4, t1=5, t2=8, t3=9, fn=car_pos)          # follow a subject for a while
    rig.focus_on([(0, figure_pos), (4.5, car_pos)], dur=0.8)   # rack focus
    samples = rig.sample(fps=30, frames=600, t_offset=0)
    camera.apply(cam_obj, samples)                      # keys every frame (LINEAR)
    report = camera.smoothness([s.pos for s in samples], [s.fwd for s in samples])

Presets (crane / dolly / orbit / push) return beat lists; ``smoothness`` reports velocity / acceleration
discontinuities and pan speed (tests enforce it on every preset and on the meadow oner).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

Vec = tuple[float, float, float]
VecFn = Callable[[float], Vec]


# ----------------------------------------------------------------------------------------------------- math utils
def _add(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Sequence[float], k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def _len(a: Sequence[float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _norm(a: Sequence[float]) -> Vec:
    n = _len(a) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _lerp(a: Sequence[float], b: Sequence[float], u: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u)


def smootherstep(u: float) -> float:
    """C2 ease 0..1 (6u^5 - 15u^4 + 10u^3); zero velocity and acceleration at both ends."""
    u = min(1.0, max(0.0, u))
    return u * u * u * (u * (u * 6 - 15) + 10)


def ease(kind: str, u: float) -> float:
    """Named eases: linear, in_out (smootherstep), in, out, sine."""
    u = min(1.0, max(0.0, u))
    if kind == "linear":
        return u
    if kind == "in":
        return u * u * u
    if kind == "out":
        return 1 - (1 - u) ** 3
    if kind == "sine":
        return 0.5 - 0.5 * math.cos(math.pi * u)
    return smootherstep(u)


def window(t: float, t0: float, t1: float, t2: float, t3: float) -> float:
    """Smooth 0→1→0 weight: ramps up over [t0,t1], holds, ramps down over [t2,t3] (C2 everywhere)."""
    if t <= t0 or t >= t3:
        return 0.0
    if t < t1:
        return smootherstep((t - t0) / max(1e-6, t1 - t0))
    if t <= t2:
        return 1.0
    return 1.0 - smootherstep((t - t2) / max(1e-6, t3 - t2))


class Spline1D:
    """C2 cubic spline y(t) through (t_i, y_i). Ends: clamped to a given slope, else natural.

    Outside [t_0, t_n] it extrapolates linearly with the end slope (continuous velocity past the ends).
    """

    def __init__(self, ts: Sequence[float], ys: Sequence[float], v0: float | None = None, v1: float | None = None):
        n = len(ts)
        if n < 2:
            ts, ys = [ts[0], ts[0] + 1.0], [ys[0], ys[0]]
            n = 2
        self.t = list(ts)
        self.y = list(ys)
        h = [self.t[i + 1] - self.t[i] for i in range(n - 1)]
        if any(x <= 0 for x in h):
            raise ValueError("beat times must increase strictly")
        # tridiagonal system for second derivatives M
        a = [0.0] * n
        b = [0.0] * n
        c = [0.0] * n
        d = [0.0] * n
        if v0 is None:
            b[0], d[0] = 1.0, 0.0
        else:
            b[0], c[0] = 2 * h[0], h[0]
            d[0] = 6 * ((self.y[1] - self.y[0]) / h[0] - v0)
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            d[i] = 6 * ((self.y[i + 1] - self.y[i]) / h[i] - (self.y[i] - self.y[i - 1]) / h[i - 1])
        if v1 is None:
            b[-1], d[-1] = 1.0, 0.0
        else:
            a[-1], b[-1] = h[-1], 2 * h[-1]
            d[-1] = 6 * (v1 - (self.y[-1] - self.y[-2]) / h[-1])
        for i in range(1, n):
            m = a[i] / b[i - 1]
            b[i] -= m * c[i - 1]
            d[i] -= m * d[i - 1]
        M = [0.0] * n
        M[-1] = d[-1] / b[-1]
        for i in range(n - 2, -1, -1):
            M[i] = (d[i] - c[i] * M[i + 1]) / b[i]
        self.M = M
        self.h = h

    def _seg(self, t: float) -> int:
        lo, hi = 0, len(self.t) - 2
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.t[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def __call__(self, t: float) -> float:
        if t <= self.t[0]:
            return self.y[0] + self.d(self.t[0]) * (t - self.t[0])
        if t >= self.t[-1]:
            return self.y[-1] + self.d(self.t[-1]) * (t - self.t[-1])
        i = self._seg(t)
        h, M = self.h[i], self.M
        A = (self.t[i + 1] - t) / h
        B = (t - self.t[i]) / h
        return (A * self.y[i] + B * self.y[i + 1]
                + ((A ** 3 - A) * M[i] + (B ** 3 - B) * M[i + 1]) * h * h / 6.0)

    def d(self, t: float) -> float:
        t = min(max(t, self.t[0]), self.t[-1])
        i = self._seg(t)
        h, M = self.h[i], self.M
        A = (self.t[i + 1] - t) / h
        B = (t - self.t[i]) / h
        return ((self.y[i + 1] - self.y[i]) / h
                + (-(3 * A * A - 1) * M[i] + (3 * B * B - 1) * M[i + 1]) * h / 6.0)


class Spline3D:
    """Three Spline1D channels sharing knots."""

    def __init__(self, ts: Sequence[float], pts: Sequence[Sequence[float]], v0: Sequence[float] | None = None,
                 v1: Sequence[float] | None = None):
        self.ch = [Spline1D(ts, [p[k] for p in pts], None if v0 is None else v0[k], None if v1 is None else v1[k])
                   for k in range(3)]

    def __call__(self, t: float) -> Vec:
        return (self.ch[0](t), self.ch[1](t), self.ch[2](t))

    def d(self, t: float) -> Vec:
        return (self.ch[0].d(t), self.ch[1].d(t), self.ch[2].d(t))


# ------------------------------------------------------------------------------------------------------- moves
@dataclass
class Beat:
    """A camera key: at time ``t`` (s) be at ``pos`` looking at ``target`` with ``lens`` mm, ``fstop``, ``roll`` deg."""
    t: float
    pos: Vec
    target: Vec
    lens: float = 35.0
    fstop: float = 4.0
    roll: float = 0.0


@dataclass
class Sample:
    t: float
    pos: Vec
    target: Vec
    fwd: Vec
    lens: float
    fstop: float
    focus: float
    roll: float


@dataclass
class Move:
    beats: list[Beat]
    v0: Vec | None = None          # start velocity (m/s) — e.g. the camera is "already moving"
    v1: Vec | None = None          # end velocity (m/s); None = natural (coasting)
    warp: Callable[[float], float] | None = None
    _aims: list = field(default_factory=list)
    _focus: list = field(default_factory=list)
    _focus_dur: float = 0.8

    def __post_init__(self) -> None:
        bs = sorted(self.beats, key=lambda b: b.t)
        ts = [b.t for b in bs]
        self.pos = Spline3D(ts, [b.pos for b in bs], self.v0, self.v1)
        self.tgt = Spline3D(ts, [b.target for b in bs])
        self.lens = Spline1D(ts, [b.lens for b in bs], 0.0, 0.0)
        self.fstop = Spline1D(ts, [b.fstop for b in bs], 0.0, 0.0)
        self.roll = Spline1D(ts, [b.roll for b in bs], 0.0, 0.0)

    def aim(self, t0: float, t1: float, t2: float, t3: float, fn: VecFn, weight: float = 1.0) -> "Move":
        """Blend the look-at onto ``fn(t)`` (a moving subject) with a smooth window; ``weight`` < 1 = partial."""
        self._aims.append((t0, t1, t2, t3, fn, weight))
        return self

    def focus_on(self, keys: Sequence[tuple[float, VecFn | Vec | float]], dur: float = 0.8) -> "Move":
        """Rack focus: at each key time start a ``dur``-second smootherstep pull to that subject (point or fn)."""
        self._focus = sorted(keys, key=lambda k: k[0])
        self._focus_dur = dur
        return self

    def eval(self, t: float) -> Sample:
        s = self.warp(t) if self.warp else t
        pos = self.pos(s)
        tgt = self.tgt(s)
        for (t0, t1, t2, t3, fn, w) in self._aims:
            k = window(t, t0, t1, t2, t3) * w
            if k > 0:
                tgt = _lerp(tgt, fn(t), k)
        fwd = _norm(_sub(tgt, pos))
        focus = _len(_sub(tgt, pos))
        if self._focus:
            def dist(subj) -> float:
                if isinstance(subj, (int, float)):
                    return float(subj)          # a fixed focus distance (e.g. an image plane at 1 m)
                p = subj(t) if callable(subj) else subj
                # focus distance is measured along the view axis (what the lens focuses on)
                return max(0.3, sum((p[i] - pos[i]) * fwd[i] for i in range(3)))
            focus = dist(self._focus[0][1])
            for i in range(1, len(self._focus)):
                tk, subj = self._focus[i]
                if t <= tk:
                    break
                u = smootherstep((t - tk) / self._focus_dur)
                focus = focus + (dist(subj) - focus) * u
        return Sample(t, pos, tgt, fwd, self.lens(s), self.fstop(s), focus, self.roll(s))

    def sample(self, fps: float, frames: int, t_offset: float = 0.0) -> list[Sample]:
        """Per-frame samples for shot-local frames 1..frames (t = t_offset + (f-1)/fps)."""
        return [self.eval(t_offset + (f - 1) / fps) for f in range(1, frames + 1)]


# ------------------------------------------------------------------------------------------------------ presets
def crane(t0: float, t1: float, base: Vec, target: Vec, rise: float = 3.0, push: float = 2.0, lens: float = 32,
          fstop: float = 4.0) -> list[Beat]:
    """Crane up while pushing toward ``target`` (start low, end high)."""
    d = _norm(_sub(target, base))
    end = _add(_add(base, _mul(d, push)), (0, 0, rise))
    mid = _add(_lerp(base, end, 0.5), (0, 0, rise * 0.1))
    tm = (t0 + t1) / 2
    return [Beat(t0, base, target, lens, fstop), Beat(tm, mid, target, lens, fstop), Beat(t1, end, target, lens, fstop)]


def dolly(t0: float, t1: float, start: Vec, end: Vec, target: Vec, lens: float = 35, fstop: float = 4.0) -> list[Beat]:
    """Straight dolly from ``start`` to ``end`` looking at ``target``."""
    return [Beat(t0, start, target, lens, fstop), Beat(t1, end, target, lens, fstop)]


def orbit(t0: float, t1: float, center: Vec, radius: float, a0: float, a1: float, height: float,
          lens: float = 35, fstop: float = 4.0, n: int = 5, look: Vec | None = None) -> list[Beat]:
    """Orbit ``center`` from angle a0 to a1 (degrees, 0 = -Y side) at ``radius`` and ``height``."""
    out = []
    for i in range(n):
        u = i / (n - 1)
        a = math.radians(a0 + (a1 - a0) * u)
        p = (center[0] + radius * math.sin(a), center[1] - radius * math.cos(a), center[2] + height)
        out.append(Beat(t0 + (t1 - t0) * u, p, look or center, lens, fstop))
    return out


def push(t0: float, t1: float, start: Vec, target: Vec, dist_end: float, lens0: float = 35, lens1: float = 50,
         fstop: float = 2.8) -> list[Beat]:
    """Push in toward ``target`` ending ``dist_end`` metres away while the lens lengthens."""
    d = _sub(target, start)
    L = _len(d)
    end = _add(start, _mul(_norm(d), max(0.0, L - dist_end)))
    mid = _lerp(start, end, 0.55)
    return [Beat(t0, start, target, lens0, fstop), Beat((t0 + t1) / 2, mid, target, (lens0 + lens1) / 2, fstop),
            Beat(t1, end, target, lens1, fstop)]


# --------------------------------------------------------------------------------------------------- smoothness
def smoothness(pos: Sequence[Sequence[float]], fwd: Sequence[Sequence[float]] | None = None, *,
               vel_jump: float = 0.2, acc_jump: float = 0.06, pan_max_deg: float = 3.0,
               pan_acc_deg: float = 0.5) -> dict:
    """Per-frame smoothness report for a sampled path (positions; optional forward unit vectors).

    Units are per frame. A *velocity discontinuity* is a one-frame velocity change > ``vel_jump`` x top speed;
    an *acceleration discontinuity* is a one-frame acceleration change > ``acc_jump`` x top speed. Pan speed is
    the angle between consecutive forward vectors (deg/frame; > 3 deg/frame strobes at 30 fps); a pan
    discontinuity is a one-frame change of angular velocity > ``pan_acc_deg``.
    """
    n = len(pos)
    v = [_sub(pos[i + 1], pos[i]) for i in range(n - 1)]
    a = [_sub(v[i + 1], v[i]) for i in range(len(v) - 1)]
    j = [_sub(a[i + 1], a[i]) for i in range(len(a) - 1)]
    vmax = max((_len(x) for x in v), default=0.0)
    scale = max(vmax, 1e-4)
    vel_bad = [i + 1 for i, x in enumerate(a) if _len(x) > vel_jump * scale]
    acc_bad = [i + 2 for i, x in enumerate(j) if _len(x) > acc_jump * scale]
    rep = {"frames": n, "max_speed": vmax, "max_accel": max((_len(x) for x in a), default=0.0),
           "max_jerk": max((_len(x) for x in j), default=0.0), "vel_jumps": vel_bad[:20],
           "acc_jumps": acc_bad[:20]}
    if fwd:
        w = []
        for i in range(len(fwd) - 1):
            c = max(-1.0, min(1.0, sum(fwd[i][k] * fwd[i + 1][k] for k in range(3))))
            w.append(math.degrees(math.acos(c)))
        dw = [abs(w[i + 1] - w[i]) for i in range(len(w) - 1)]
        rep["max_pan_deg"] = max(w, default=0.0)
        rep["pan_fast"] = [i + 1 for i, x in enumerate(w) if x > pan_max_deg][:20]
        rep["pan_jumps"] = [i + 1 for i, x in enumerate(dw) if x > pan_acc_deg][:20]
    rep["ok"] = not (rep["vel_jumps"] or rep["acc_jumps"] or rep.get("pan_fast") or rep.get("pan_jumps"))
    return rep


# ---------------------------------------------------------------------------------------------- screen framing
def project(s: Sample, p: Sequence[float], aspect: float, sensor: float = 36.0) -> tuple[float, float, float]:
    """NDC (x, y in -1..1 inside the frame) and view depth of world point ``p`` for camera sample ``s``.

    Matches Blender's ``sensor_fit='AUTO'``: the sensor width spans the longer image side (``aspect`` = w / h).
    Depth <= 0 means behind the camera.
    """
    fwd = s.fwd
    right = _norm((fwd[1], -fwd[0], 0.0)) if abs(fwd[2]) < 0.999 else (1.0, 0.0, 0.0)
    up = (right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2],
          right[0] * fwd[1] - right[1] * fwd[0])
    if s.roll:
        r = math.radians(s.roll)
        c, si = math.cos(r), math.sin(r)
        right, up = _add(_mul(right, c), _mul(up, si)), _add(_mul(up, c), _mul(right, -si))
    d = _sub(p, s.pos)
    z = sum(d[k] * fwd[k] for k in range(3))
    if z <= 1e-6:
        return (0.0, 0.0, z)
    half = sensor / 2.0 / s.lens                     # tan(half fov) along the longer side
    th, tv = (half, half / aspect) if aspect >= 1 else (half * aspect, half)
    return (sum(d[k] * right[k] for k in range(3)) / z / th, sum(d[k] * up[k] for k in range(3)) / z / tv, z)


def screen_box(s: Sample, corners: Sequence[Sequence[float]], aspect: float) -> dict | None:
    """Screen-space box of a set of world points: {x0, x1, y0, y1 (NDC), w, h (visible fraction of the frame),
    cut (partly outside), inside (fully inside), depth}. None if any point is behind the camera."""
    pts = [project(s, c, aspect) for c in corners]
    if any(p[2] <= 0.3 for p in pts):
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    vx0, vx1, vy0, vy1 = max(-1.0, x0), min(1.0, x1), max(-1.0, y0), min(1.0, y1)
    vis = vx1 > vx0 and vy1 > vy0
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "w": (vx1 - vx0) / 2 if vis else 0.0,
            "h": (vy1 - vy0) / 2 if vis else 0.0, "visible": vis,
            "inside": x0 >= -1 and x1 <= 1 and y0 >= -1 and y1 <= 1,
            "cut": vis and not (x0 >= -1 and x1 <= 1 and y0 >= -1 and y1 <= 1),
            "depth": min(p[2] for p in pts)}


# ------------------------------------------------------------------------------------------------- Blender side
def look_quat(pos: Vec, target: Vec, roll_deg: float = 0.0):
    """Camera orientation (mathutils.Quaternion) looking from pos at target, world-up Z, plus roll."""
    from mathutils import Quaternion, Vector  # noqa: PLC0415 - Blender-only
    d = Vector(target) - Vector(pos)
    q = d.to_track_quat("-Z", "Y")
    if roll_deg:
        q = q @ Quaternion((0, 0, 1), math.radians(roll_deg))
    return q


def make_camera(name: str = "cam", sensor: float = 36.0):
    """Create a camera object (DOF on) and make it the scene camera."""
    import bpy  # noqa: PLC0415
    cd = bpy.data.cameras.new(name)
    cd.sensor_width = sensor
    cd.dof.use_dof = True
    cd.clip_start = 0.05
    cd.clip_end = 6000.0
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    ob.rotation_mode = "QUATERNION"
    return ob


def apply(cam, samples: Sequence[Sample], frame_start: int = 1, sensor_fit: str | None = None) -> None:
    """Key every frame: location, rotation (hemisphere-continuous quaternions), lens, focus distance, f-stop."""
    cam.rotation_mode = "QUATERNION"
    if sensor_fit:
        cam.data.sensor_fit = sensor_fit
    prev = None
    for i, s in enumerate(samples):
        f = frame_start + i
        q = look_quat(s.pos, s.target, s.roll)
        if prev is not None and prev.dot(q) < 0:
            q.negate()
        prev = q
        cam.location = s.pos
        cam.rotation_quaternion = q
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        cam.data.lens = s.lens
        cam.data.dof.focus_distance = s.focus
        cam.data.dof.aperture_fstop = s.fstop
        cam.data.keyframe_insert("lens", frame=f)
        cam.data.dof.keyframe_insert("focus_distance", frame=f)
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)
    linearize(cam)
    linearize(cam.data)


def linearize(idblock) -> None:
    """Set every key of an ID's action to LINEAR with linear extrapolation (per-frame keys, no overshoot)."""
    ad = getattr(idblock, "animation_data", None)
    if not ad or not ad.action:
        return
    for fc in fcurves(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.extrapolation = "LINEAR"


def fcurves(action) -> list:
    """F-curves of an action (Blender < 4.4 flat list, or 4.4+/5.x layered actions)."""
    try:
        return list(action.fcurves)
    except AttributeError:
        out = []
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    out.extend(bag.fcurves)
        return out


def sample_object(obj, frames: Sequence[int]) -> tuple[list[Vec], list[Vec]]:
    """Evaluated world positions and forward (-Z) vectors of ``obj`` at the given frames (for smoothness QA)."""
    import bpy  # noqa: PLC0415
    sc = bpy.context.scene
    ps, fs = [], []
    for f in frames:
        sc.frame_set(f)
        m = obj.matrix_world
        ps.append(tuple(m.translation))
        z = m.col[2]
        fs.append(_norm((-z[0], -z[1], -z[2])))
    return ps, fs
