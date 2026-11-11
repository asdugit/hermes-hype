"""Flying / driving product choreography (runs inside Blender; the planning math is pure Python).

A ``Flight`` is a path through control points, a time span and a speed profile. ``plan()`` turns it into
per-frame poses: position on a C2 spline at an eased arc-length, orientation from the path (pitch from slope,
bank from lateral acceleration), hover bob, and wheel spin from the distance travelled (capped so spokes read
as rotating instead of strobing). Before ``t0`` and after ``t1`` the car keeps moving along the end tangents at
the end speeds: **nothing ever stops at the edge of a shot**.

Choreography presets (``preset(name, ...)``): dive_in_left, climb_right, drive_over_hill_lift_off, float_hover,
pass_by_camera, arc_across. ``validate(poses, ...)`` enforces the no-dying rule: no unmotivated slowdown, exits
keep momentum, no sinking exit, no ground clipping. Tests run it on every preset.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .camera import Spline3D, _add, _len, _lerp, _mul, _norm, _sub, smootherstep

Vec = tuple[float, float, float]
Ground = Callable[[float, float], float]

CAR_HALF = (1.0, 2.35, 0.0, 1.2)        # half width, half length, bottom z, top z (car-local, metres)


@dataclass
class Flight:
    """One product flight. Speeds in m/s; ``mode``: fly | drive | hover. ``points`` in world metres."""
    name: str
    points: list[Vec]
    t0: float
    t1: float
    v0: float = 12.0
    v1: float = 14.0
    mode: str = "fly"
    bank: float = 1.0               # bank gain (1 = coordinated-turn bank)
    max_bank: float = 38.0          # degrees
    bob: float = 0.0                # hover bob amplitude (m)
    bob_hz: float = 0.32
    yaw_rate: float = 0.0           # hover: turntable yaw (deg/s)
    yaw0: float = 0.0               # hover: initial heading (deg, 0 = +Y)
    spin_cap: float = 0.42          # wheel spin cap, rad/frame
    spin_rps: float = 1.1           # hover wheel spin (rev/s)
    drive_until: float = -1.0       # drive mode: seconds after t0 when the car lifts off (-1 = never)
    lift: float = 1.2               # seconds over which the lift-off blends from ground-locked to free flight
    phase: float = 0.0
    scale: float = 1.0
    times: list | None = None       # timed flight: ``points[i]`` is reached at ``times[i]`` (C2 spline in time)
    # orientation wander: a car is not glued to its path tangent — it crabs a little, pitches and rolls on its own
    # slow beat, so a flock has no two identical headings (3/4 front and rear views instead of only side profiles)
    yaw_off: float = 0.0            # deg, constant heading offset from the path tangent (+ = nose left)
    yaw_wob: float = 0.0            # deg, slow heading wander amplitude
    yaw_hz: float = 0.11
    pitch_off: float = 0.0          # deg, constant nose-up (+)
    pitch_wob: float = 0.0
    pitch_hz: float = 0.09
    roll_off: float = 0.0           # deg, extra bank (+ = right wing down)
    roll_wob: float = 0.0
    roll_hz: float = 0.07
    wob_phase: float = 0.0          # per-car phase for the wander (0 = use ``phase``)
    meta: dict = field(default_factory=dict)


def timed_spline(fl: "Flight") -> Spline3D:
    """Position spline in time for a timed flight (natural ends -> straight extrapolation at the end speed)."""
    return Spline3D(list(fl.times or []), list(fl.points))


def follow(leader: "Flight", name: str, *, lag: float, offset: Callable[[float], tuple], t0: float, t1: float,
           step: float = 0.4, ground: "Ground | None" = None, alt: float = 2.0, **kw) -> "Flight":
    """A follower of a timed ``leader``: the leader's path ``lag`` s later plus an offset (right, up, back metres
    in the leader's frame) that varies smoothly with time — formations that loosen and break apart, bird-like
    streams with wobble. Returns a timed Flight (sampled every ``step`` s; C2 between samples)."""
    sp = timed_spline(leader)
    n = max(2, int(math.ceil((t1 - t0) / step)) + 1)
    times, pts = [], []
    for k in range(n):
        t = t0 + (t1 - t0) * k / (n - 1)
        tau = t - lag
        p = sp(tau)
        d = _norm(sp.d(tau))
        right = _norm(_cross(d, (0.0, 0.0, 1.0))) if abs(d[2]) < 0.98 else (1.0, 0.0, 0.0)
        up = _cross(right, d)
        o = offset(t)
        q = _add(_add(_add(p, _mul(right, o[0])), _mul(up, o[1])), _mul(d, -o[2]))
        if ground is not None:
            q = (q[0], q[1], max(q[2], ground(q[0], q[1]) + alt))
        times.append(t)
        pts.append(q)
    return Flight(name, pts, t0, t1, times=times, **kw)


def ring(name: str, center: Vec, radius: float, height: float, a0: float, omega: float, t0: float, t1: float, *,
         undulate: float = 3.0, und_hz: float = 0.07, phase: float = 0.0, rwave: float = 0.12,
         step: float = 0.8, **kw) -> "Flight":
    """A timed flight circling ``center`` (deg a0 at t0, ``omega`` deg/s; + = counter-clockwise seen from above)
    with a slow vertical undulation and a breathing radius — a leader for far bird-like streams."""
    n = max(3, int(math.ceil((t1 - t0) / step)) + 1)
    times, pts = [], []
    for k in range(n):
        t = t0 + (t1 - t0) * k / (n - 1)
        a = math.radians(a0 + omega * (t - t0))
        r = radius * (1.0 + rwave * math.sin(2 * math.pi * und_hz * 0.6 * t + phase * 1.3))
        z = center[2] + height + undulate * math.sin(2 * math.pi * und_hz * t + phase)
        times.append(t)
        pts.append((center[0] + r * math.sin(a), center[1] + r * math.cos(a), z))
    return Flight(name, pts, t0, t1, times=times, **kw)


def murmur(name: str, center: Vec, radius: float, height: float, a0: float, omega: float, t0: float, t1: float, *,
           d_r: float = 0.0, d_h: float = 0.0, d_omega: float = 0.0, undulate: float = 3.0, und_hz: float = 0.07,
           phase: float = 0.0, rwave: float = 0.12, step: float = 0.8, ground: "Ground | None" = None,
           alt: float = 4.0, **kw) -> "Flight":
    """One car of a murmuration: its own orbit around ``center`` with its own radius, height, angular speed and
    phase (``d_r``/``d_h``/``d_omega`` are per-car deltas). Nothing lines up with anybody else: the rings widen,
    breathe and drift apart, so a flock never reads as a row. Use with ``yaw_off``/``pitch_wob``/``roll_wob``."""
    n = max(3, int(math.ceil((t1 - t0) / step)) + 1)
    times, pts = [], []
    for k in range(n):
        t = t0 + (t1 - t0) * k / (n - 1)
        a = math.radians(a0 + (omega + d_omega) * (t - t0))
        r = (radius + d_r) * (1.0 + rwave * math.sin(2 * math.pi * und_hz * 0.6 * t + phase * 1.3))
        z = center[2] + height + d_h + undulate * math.sin(2 * math.pi * und_hz * t + phase)
        x, y = center[0] + r * math.sin(a), center[1] + r * math.cos(a)
        if ground is not None:
            z = max(z, ground(x, y) + alt)
        times.append(t)
        pts.append((x, y, z))
    return Flight(name, pts, t0, t1, times=times, **kw)


def sway(name: str, a: Vec, b: Vec, t0: float, t1: float, *, bow: float = 0.0, bow_axis: Vec | None = None,
         wander: float = 0.0, wander_hz: float = 0.08, phase: float = 0.0, step: float = 0.6,
         ground: "Ground | None" = None, alt: float = 4.0, **kw) -> "Flight":
    """A car crossing the meadow from ``a`` to ``b`` along a bowed path (``bow`` m sideways at the midpoint) with
    a slow lateral wander — the mid-sky crossers that show 3/4 front and rear views instead of side profiles.
    ``bow_axis`` defaults to the horizontal perpendicular of the path, so the bow never speeds the car up."""
    n = max(3, int(math.ceil((t1 - t0) / step)) + 1)
    if bow_axis is None:                     # sideways (perp to the path in plan view): constant speed
        d = _sub(b, a)
        bow_axis = (-d[1], d[0], 0.0)
    ax = _norm(bow_axis)
    times, pts = [], []
    for k in range(n):
        u = k / (n - 1)
        t = t0 + (t1 - t0) * u
        bend = math.sin(math.pi * u) * bow
        w = wander * math.sin(math.pi * u) ** 2 * math.sin(2 * math.pi * wander_hz * t + phase)
        p = _add(_lerp(a, b, u), _mul(ax, bend + w))
        if ground is not None:
            p = (p[0], p[1], max(p[2], ground(p[0], p[1]) + alt))
        pts.append(p)
        times.append(t)
    return Flight(name, pts, t0, t1, times=times, **kw)


@dataclass
class Pose:
    t: float
    pos: Vec
    fwd: Vec
    up: Vec
    speed: float
    wheel: float          # wheel angle (rad, rolling forward is negative about local X)
    grounded: bool


# ------------------------------------------------------------------------------------------- path + arc length
class _Path:
    def __init__(self, pts: Sequence[Vec]):
        pts = list(pts)
        if len(pts) == 2:
            pts = [pts[0], _lerp(pts[0], pts[1], 0.5), pts[1]]
        # chord-length knots
        ks = [0.0]
        for i in range(1, len(pts)):
            ks.append(ks[-1] + max(1e-3, _len(_sub(pts[i], pts[i - 1]))))
        self.sp = Spline3D(ks, pts)
        self.kmax = ks[-1]
        n = max(200, int(self.kmax * 4))
        self.table_k = [self.kmax * i / n for i in range(n + 1)]
        self.table_s = [0.0]
        prev = self.sp(0.0)
        for k in self.table_k[1:]:
            p = self.sp(k)
            self.table_s.append(self.table_s[-1] + _len(_sub(p, prev)))
            prev = p
        self.length = self.table_s[-1]

    def k_at(self, s: float) -> float:
        ts, tk = self.table_s, self.table_k
        if s <= 0:
            return 0.0
        if s >= self.length:
            return self.kmax
        lo, hi = 0, len(ts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if ts[mid] <= s:
                lo = mid
            else:
                hi = mid
        u = (s - ts[lo]) / max(1e-9, ts[hi] - ts[lo])
        return tk[lo] + (tk[hi] - tk[lo]) * u

    def at(self, s: float) -> tuple[Vec, Vec]:
        """Point and unit tangent at arc length s; beyond the ends: straight extrapolation along the tangent."""
        if s < 0:
            p, d = self.sp(0.0), _norm(self.sp.d(0.0))
            return _add(p, _mul(d, s)), d
        if s > self.length:
            p, d = self.sp(self.kmax), _norm(self.sp.d(self.kmax))
            return _add(p, _mul(d, s - self.length)), d
        k = self.k_at(s)
        return self.sp(k), _norm(self.sp.d(k))


def _distance(fl: Flight, L: float, t: float) -> tuple[float, float]:
    """Arc length and speed at time t: cubic Hermite s(u) with end speeds v0/v1; linear outside [t0, t1]."""
    T = max(1e-3, fl.t1 - fl.t0)
    a, b = fl.v0 * T / max(L, 1e-3), fl.v1 * T / max(L, 1e-3)
    # keep the Hermite monotone (Fritsch-Carlson bound)
    k = math.hypot(a, b)
    if k > 3:
        a, b = a * 3 / k, b * 3 / k
    if t <= fl.t0:
        return -fl.v0 * (fl.t0 - t) + 0.0, fl.v0
    if t >= fl.t1:
        return L + (t - fl.t1) * b * L / T, b * L / T
    u = (t - fl.t0) / T
    h10, h01, h11 = u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    s = h10 * a + h01 + h11 * b
    ds = (3 * u ** 2 - 4 * u + 1) * a + (-6 * u ** 2 + 6 * u) + (3 * u ** 2 - 2 * u) * b
    return s * L, ds * L / T


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _rot(v: Vec, axis: Vec, ang: float) -> Vec:
    """Rodrigues rotation of v about unit axis."""
    c, s = math.cos(ang), math.sin(ang)
    k = axis
    kv = _cross(k, v)
    kd = _dot(k, v)
    return (v[0] * c + kv[0] * s + k[0] * kd * (1 - c), v[1] * c + kv[1] * s + k[1] * kd * (1 - c),
            v[2] * c + kv[2] * s + k[2] * kd * (1 - c))


def plan(fl: Flight, fps: float, frames: int, t_offset: float = 0.0, ground: Ground | None = None,
         wheel_r: float = 0.362) -> list[Pose]:
    """Per-frame poses for shot-local frames 1..frames.

    ``fl.meta["ratio"] = (r0, r1)`` sets the entry/exit speeds relative to the mean speed (path length / span),
    which keeps the eased profile monotone whatever the path length.
    """
    path = _Path(fl.points)
    L = path.length
    if "ratio" in fl.meta and not fl.times:
        T = max(1e-3, fl.t1 - fl.t0)
        fl.v0, fl.v1 = fl.meta["ratio"][0] * L / T, fl.meta["ratio"][1] * L / T
    dt = 1.0 / fps
    # pass 1: raw positions/tangents/speeds at frame times plus half-frame neighbours for curvature
    raw = []
    if fl.times:
        sp = timed_spline(fl)
        fl.v0, fl.v1 = _len(sp.d(fl.times[0])), _len(sp.d(fl.times[-1]))
        s_acc, prev_p = 0.0, None
        for f in range(frames):
            t = t_offset + f * dt
            p, dv = sp(t), sp.d(t)
            if prev_p is not None:
                s_acc += _len(_sub(p, prev_p))
            prev_p = p
            raw.append((t, s_acc, _len(dv), p, _norm(dv)))
    for f in range(0 if not fl.times else frames, frames):
        t = t_offset + f * dt
        s, v = _distance(fl, L, t)
        p, d = path.at(s)
        raw.append((t, s, v, p, d))
    poses: list[Pose] = []
    wheel = 0.0
    prev_s = None
    for i, (t, s, v, p, d) in enumerate(raw):
        grounded = False
        if fl.mode == "hover":
            yaw = math.radians(fl.yaw0 + fl.yaw_rate * (t - fl.t0))
            fwd = (math.sin(yaw), math.cos(yaw), 0.0)
            bob = fl.bob * math.sin(2 * math.pi * fl.bob_hz * t + fl.phase)
            p = (p[0], p[1], p[2] + bob)
            # gentle wobble: pitch with the bob velocity, roll on a slower beat
            pitch = 0.035 * math.cos(2 * math.pi * fl.bob_hz * t + fl.phase)
            roll = 0.03 * math.sin(2 * math.pi * fl.bob_hz * 0.61 * t + fl.phase * 1.7)
            right = _norm(_cross(fwd, (0, 0, 1)))
            fwd = _norm(_rot(fwd, right, pitch))
            up = _norm(_cross(right, fwd))
            up = _norm(_rot(up, fwd, roll))
            wheel -= 2 * math.pi * fl.spin_rps * dt
            poses.append(Pose(t, p, fwd, up, v, wheel, False))
            continue
        # ground lock for drive mode (with a smooth lift-off)
        g_w = 0.0
        if fl.mode == "drive" and ground is not None:
            if fl.drive_until < 0:
                g_w = 1.0
            else:
                g_w = 1.0 - smootherstep((t - (fl.t0 + fl.drive_until)) / max(0.05, fl.lift))
            if g_w > 0:
                # a car bridges a crest: it sits on the highest terrain under its four wheels, never sunk into a hill
                gz = ground(p[0], p[1])
                rgt = _norm(_cross(d, (0.0, 0.0, 1.0))) if abs(d[2]) < 0.98 else (1.0, 0.0, 0.0)
                for a in (-0.8, 0.8):
                    for b in (-0.8, 0.8):
                        q = _add(_add(p, _mul(rgt, a * CAR_HALF[0])), _mul(d, b * CAR_HALF[1]))
                        gz = max(gz, ground(q[0], q[1]))
                p = (p[0], p[1], p[2] * (1 - g_w) + gz * g_w)
                grounded = g_w > 0.999
        fwd = d
        # bank from lateral acceleration (finite differences on the path tangents)
        j0, j1 = max(0, i - 1), min(len(raw) - 1, i + 1)
        d0, d1 = raw[j0][4], raw[j1][4]
        dtt = max(dt, (raw[j1][0] - raw[j0][0]))
        turn = _sub(d1, d0)
        lat = _mul(turn, v / dtt)                       # ≈ v * dT/dt = lateral acceleration
        right = _norm(_cross(fwd, (0, 0, 1))) if abs(fwd[2]) < 0.98 else (1.0, 0.0, 0.0)
        a_lat = _dot(lat, right)
        bank = math.atan2(a_lat, 9.81) * fl.bank * (1.0 - g_w)
        mb = math.radians(fl.max_bank)
        bank = mb * math.tanh(bank / mb)
        up0 = _norm(_cross(right, fwd))
        if g_w > 0 and ground is not None:
            # wheels follow the terrain normal while grounded
            e = 0.6
            nx = ground(p[0] - e, p[1]) - ground(p[0] + e, p[1])
            ny = ground(p[0], p[1] - e) - ground(p[0], p[1] + e)
            n_g = _norm((nx, ny, 2 * e))
            up0 = _norm(_lerp(up0, n_g, g_w))
            fwd = _norm(_sub(fwd, _mul(up0, _dot(fwd, up0))))
        up = _norm(_rot(up0, fwd, -bank))
        # per-car orientation wander (no two cars share a heading): yaw about the local up, then pitch, then roll
        if fl.yaw_off or fl.yaw_wob or fl.pitch_off or fl.pitch_wob or fl.roll_off or fl.roll_wob:
            ph = (fl.wob_phase or fl.phase)
            yaw = math.radians(fl.yaw_off + fl.yaw_wob * math.sin(2 * math.pi * fl.yaw_hz * t + ph))
            pit = math.radians(fl.pitch_off + fl.pitch_wob * math.sin(2 * math.pi * fl.pitch_hz * t + ph * 1.7))
            rol = math.radians(fl.roll_off + fl.roll_wob * math.sin(2 * math.pi * fl.roll_hz * t + ph * 0.6))
            fwd = _norm(_rot(fwd, up, yaw))
            right = _norm(_cross(fwd, up))
            up = _norm(_cross(right, fwd))
            fwd = _norm(_rot(fwd, right, pit))
            right = _norm(_cross(fwd, up))
            up = _norm(_cross(right, fwd))
            up = _norm(_rot(up, fwd, rol))
        if prev_s is None:
            prev_s = s
        dist = s - prev_s
        prev_s = s
        wheel -= max(-fl.spin_cap, min(fl.spin_cap, dist / wheel_r))
        poses.append(Pose(t, p, fwd, up, v, wheel, grounded))
    return poses


# ---------------------------------------------------------------------------------------------------- validate
def validate(fl: Flight, poses: Sequence[Pose], ground: Ground | None = None, *, min_speed_frac: float = 0.35,
             exit_frac: float = 0.6, clearance: float = -0.03, window: tuple = (1.0, 2.0)) -> list[str]:
    """No-dying rules. Returns a list of problems (empty = ok). Ground clearance is checked from
    ``window[0]`` s before t0 to ``window[1]`` s after t1 (entries/exits must happen off-screen beyond that)."""
    errs: list[str] = []
    if not poses:
        return ["no poses"]
    if fl.mode != "hover":
        vs = [p.speed for p in poses if fl.t0 <= p.t <= fl.t1]
        peak = max(vs, default=0.0)
        if peak <= 0.5:
            errs.append(f"{fl.name}: never moves")
        if vs and min(vs) < min_speed_frac * peak:
            errs.append(f"{fl.name}: slows to {min(vs):.1f} m/s (< {min_speed_frac:.0%} of {peak:.1f}) mid-flight")
        if fl.v1 < exit_frac * max(fl.v0, peak * 0.8):
            errs.append(f"{fl.name}: exits without momentum (v1 {fl.v1:.1f} vs peak {peak:.1f})")
        last = poses[-1]
        if last.fwd[2] < -0.45 and not last.grounded:
            errs.append(f"{fl.name}: exits sinking (fwd z {last.fwd[2]:.2f})")
    if ground is not None:
        worst = 9e9
        for p in poses:
            if not (fl.t0 - window[0] <= p.t <= fl.t1 + window[1]):
                continue                     # far off-screen approach/exit extrapolation
            right = _norm(_cross(p.fwd, p.up))
            for sx in (-1, 1):
                for sy in (-1, 1):
                    c = _add(_add(p.pos, _mul(right, sx * CAR_HALF[0] * 0.9)), _mul(p.fwd, sy * CAR_HALF[1] * 0.9))
                    c = _add(c, _mul(p.up, 0.12))
                    worst = min(worst, c[2] - ground(c[0], c[1]))
        if worst < clearance:
            errs.append(f"{fl.name}: clips the ground by {-worst:.2f} m")
    return errs


# ----------------------------------------------------------------------------------------------------- presets
def preset(name: str, *, t0: float, t1: float, origin: Vec = (0, 0, 0), heading: float = 0.0, side: int = 1,
           depth: float = 30.0, height: float = 6.0, ground: Ground | None = None, **kw) -> Flight:
    """Choreography presets in a frame looking down +Y from ``origin`` (rotated by ``heading`` deg about Z).

    ``side`` = +1 right / -1 left of the view axis; ``depth`` = distance down the view axis where the action
    happens; ``height`` = typical altitude above ``origin``. Extra kwargs override Flight fields.
    """
    hx = math.radians(heading)

    def W(x: float, y: float, z: float) -> Vec:
        c, s = math.cos(hx), math.sin(hx)
        return (origin[0] + x * c + y * s, origin[1] - x * s + y * c, origin[2] + z)

    D, H, S = depth, height, side
    if name == "dive_in_left":
        pts = [W(-S * 0.9 * D, D * 1.5, H * 3.2), W(-S * 0.35 * D, D * 1.05, H * 1.6), W(S * 0.05 * D, D * 0.8, H * 0.55),
               W(S * 0.45 * D, D * 0.75, H * 0.9), W(S * 0.95 * D, D * 0.95, H * 2.2)]
        fl = Flight(name, pts, t0, t1, bank=1.3, meta={"ratio": (1.05, 1.15)})
    elif name == "climb_right":
        pts = [W(S * 0.3 * D, D * 1.0, H * 0.5), W(S * 0.48 * D, D * 1.1, H * 1.1), W(S * 0.62 * D, D * 1.3, H * 2.6),
               W(S * 0.72 * D, D * 1.6, H * 5.5)]
        fl = Flight(name, pts, t0, t1, bank=0.8, meta={"ratio": (0.7, 1.35)})
    elif name == "drive_over_hill_lift_off":
        pts = [W(-S * 0.10 * D, D * 1.25, 0), W(-S * 0.2 * D, D * 0.95, 0), W(-S * 0.32 * D, D * 0.65, 0.3),
               W(-S * 0.48 * D, D * 0.45, H * 0.9), W(-S * 0.65 * D, D * 0.38, H * 2.4)]
        fl = Flight(name, pts, t0, t1, mode="drive", drive_until=(t1 - t0) * 0.5, lift=1.4, bank=0.9,
                    meta={"ratio": (0.8, 1.3)})
    elif name == "float_hover":
        p = W(S * 0.12 * D, D, H * 0.5)
        pts = [p, _add(p, (0.6 * S, -0.8, 0.25))]
        fl = Flight(name, pts, t0, t1, v0=0.25, v1=0.25, mode="hover", bob=0.12, yaw_rate=-9 * S, yaw0=110 * S)
    elif name == "pass_by_camera":
        pts = [W(S * 7.0, -9.0, H * 0.35), W(S * 3.2, 0.0, H * 0.22), W(-S * 0.6, D * 0.45, H * 0.4),
               W(-S * 3.0, D * 1.1, H * 1.0)]
        fl = Flight(name, pts, t0, t1, bank=1.1, meta={"ratio": (1.0, 1.08)})
    elif name == "arc_across":
        pts = [W(-S * 1.3 * D, D * 1.6, H * 1.6), W(-S * 0.4 * D, D * 1.75, H * 3.0), W(S * 0.4 * D, D * 1.7, H * 3.2),
               W(S * 1.3 * D, D * 1.5, H * 2.0)]
        fl = Flight(name, pts, t0, t1, bank=1.2, meta={"ratio": (0.95, 1.05)})
    else:
        raise KeyError(f"unknown flyer preset {name!r}")
    for k, v in kw.items():
        setattr(fl, k, v)
    return fl


PRESETS = ("dive_in_left", "climb_right", "drive_over_hill_lift_off", "float_hover", "pass_by_camera", "arc_across")


# ------------------------------------------------------------------------------------------------ Blender side
def load_car(path: str, name: str = "car_src"):
    """Load a product car: .blend (append the 'car' root + children) or .glb/.gltf (import). Returns the root,
    hidden from render (instances are copies). Wheels are children whose name contains 'wheel'."""
    import bpy  # noqa: PLC0415
    before = set(bpy.data.objects)
    if path.lower().endswith(".blend"):
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
        for o in dst.objects:
            if o is not None:
                coll.objects.link(o)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
        coll = None
    new = [o for o in bpy.data.objects if o not in before]
    roots = [o for o in new if o.parent is None and (o.name.startswith("car") or o.type == "EMPTY")]
    root = roots[0] if roots else new[0]
    for o in new:
        o.hide_render = True
        o.hide_viewport = True
    return root


def instance_car(src_root, name: str, coll=None):
    """Duplicate a car hierarchy (linked mesh data) → (root, [wheel objects]). Wheels found by name 'wheel'."""
    import bpy  # noqa: PLC0415
    coll = coll or bpy.context.scene.collection
    root = src_root.copy()
    root.name = name
    root.hide_render = root.hide_viewport = False
    coll.objects.link(root)
    wheels = []
    for ch in src_root.children:
        c = ch.copy()
        c.hide_render = c.hide_viewport = False
        c.parent = root
        c.matrix_parent_inverse = ch.matrix_parent_inverse.copy()
        coll.objects.link(c)
        for gch in ch.children:
            g = gch.copy()
            g.hide_render = g.hide_viewport = False
            g.parent = c
            g.matrix_parent_inverse = gch.matrix_parent_inverse.copy()
            coll.objects.link(g)
        if "wheel" in ch.name.lower():
            c.rotation_mode = "XYZ"
            wheels.append(c)
    return root, wheels


def apply(root, wheels: Sequence, poses: Sequence[Pose], frame_start: int = 1, scale: float = 1.0,
          visible: Sequence[bool] | None = None, spin: bool = True) -> None:
    """Key the root (location + quaternion from fwd/up) and wheel spin every frame (LINEAR). ``visible`` (per pose)
    keys the root scale to ~0 outside the car's on-screen window (children vanish with it)."""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    from .camera import linearize  # noqa: PLC0415
    root.rotation_mode = "QUATERNION"
    root.scale = (scale, scale, scale)
    prev = None
    base = {w.name: w.rotation_euler.copy() for w in wheels}
    for i, p in enumerate(poses):
        f = frame_start + i
        if visible is not None:
            k = scale if visible[i] else 1e-4
            root.scale = (k, k, k)
            root.keyframe_insert("scale", frame=f)       # every frame: LINEAR extrapolation can't run away
        fwd = Vector(p.fwd)
        up = Vector(p.up)
        right = fwd.cross(up).normalized()
        up = right.cross(fwd).normalized()
        m = Matrix((right, fwd, up)).transposed()      # columns: x=right, y=forward, z=up
        q = m.to_quaternion()
        if prev is not None and prev.dot(q) < 0:
            q.negate()
        prev = q
        root.location = p.pos
        root.rotation_quaternion = q
        root.keyframe_insert("location", frame=f)
        root.keyframe_insert("rotation_quaternion", frame=f)
        for w in wheels if spin else ():
            w.rotation_euler = (base[w.name].x + p.wheel, base[w.name].y, base[w.name].z)
            w.keyframe_insert("rotation_euler", index=0, frame=f)
    linearize(root)
    for w in wheels if spin else ():
        linearize(w)
