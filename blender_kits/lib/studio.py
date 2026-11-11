"""Studio toolkit for product / device scenes (runs inside Blender >= 4.2; pure helpers are bpy-free).

- ``Shot``: normalised view of a SceneCtx (fps, frame count, size, tier, params merged with PARAMS defaults).
- ``setup_render``: EEVEE per tier, colour management (Standard for UI-exact screens, AgX for pure 3D).
- ``stage``: cyclorama + reflective floor + key/rim/top lights + world, presets studio | light | sunset | accent.
- ``CameraRig``: smooth camera from timed beats (clamped cubic spline in TIME: position, velocity and
  acceleration continuous through every beat), look-at target, per-frame lens + focus distance (DOF), deterministic subtle handheld; every frame keyed.
- Pure math (``spline_path``, ``smoothness``, ``ease``) has no bpy dependency and is unit-tested.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

try:  # pure helpers stay importable without Blender (tests)
    import bpy
    from mathutils import Euler, Vector
except ImportError:  # pragma: no cover - outside Blender
    bpy = None  # type: ignore[assignment]
    Vector = Euler = None  # type: ignore[assignment,misc]

Vec3 = tuple[float, float, float]

# --------------------------------------------------------------------------------------------- pure math


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    """Clamp x to [a, b]."""
    return a if x < a else min(x, b)


def ease(u: float, kind: str = "inout", k: float = 1.0) -> float:
    """Easing on [0,1]: 'inout' (smootherstep blended with linear by k), 'out', 'in', 'linear'."""
    u = clamp(u)
    if kind == "linear":
        return u
    if kind == "out":
        e = 1 - (1 - u) ** 3
    elif kind == "in":
        e = u ** 3
    else:
        e = u * u * u * (u * (u * 6 - 15) + 10)
    return (1 - k) * u + k * e


def window(t: float, t0: float, t1: float, kind: str = "inout") -> float:
    """Eased progress of t through [t0, t1] (0 before, 1 after)."""
    if t1 <= t0:
        return 1.0 if t >= t1 else 0.0
    return ease((t - t0) / (t1 - t0), kind)


def lerp(a: float, b: float, u: float) -> float:
    """Linear interpolation."""
    return a + (b - a) * u


def lerp3(a: Sequence[float], b: Sequence[float], u: float) -> Vec3:
    """Component-wise lerp of 3-vectors."""
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u)


def spline_path(times: Sequence[float], values: Sequence[Sequence[float]], *, end_speed: float = 0.6
                ) -> Callable[[float], tuple[float, ...]]:
    """C2 interpolant through timed keys: a clamped cubic spline parameterised by TIME.

    Position, velocity AND acceleration are continuous through every beat (no speed jumps, no acceleration kicks
    a viewer feels as a "bump"), whatever the beat spacing. End velocities are the one-sided key velocity scaled
    by ``end_speed`` (0 = ease from / to rest, 1 = keep moving: frame 0 is already in motion). Outside
    [t0, tN] the value holds.
    """
    n = len(times)
    if n == 0:
        raise ValueError("spline_path needs at least one key")
    vals = [tuple(float(x) for x in v) for v in values]
    dim = len(vals[0])
    if n == 1:
        return lambda t: vals[0]
    ts = [float(t) for t in times]
    h = [ts[i + 1] - ts[i] for i in range(n - 1)]
    if min(h) <= 0:
        raise ValueError("spline_path: key times must strictly increase")
    Ms = []
    for d in range(dim):
        y = [v[d] for v in vals]
        v0 = end_speed * (y[1] - y[0]) / h[0]
        vn = end_speed * (y[-1] - y[-2]) / h[-1]
        a = [0.0] * n  # sub-diagonal
        b = [0.0] * n  # diagonal
        c = [0.0] * n  # super-diagonal
        r = [0.0] * n
        b[0], c[0], r[0] = 2 * h[0], h[0], 6 * ((y[1] - y[0]) / h[0] - v0)
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            r[i] = 6 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1])
        a[-1], b[-1], r[-1] = h[-1], 2 * h[-1], 6 * (vn - (y[-1] - y[-2]) / h[-1])
        for i in range(1, n):  # Thomas algorithm
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            r[i] -= w * r[i - 1]
        m = [0.0] * n
        m[-1] = r[-1] / b[-1]
        for i in range(n - 2, -1, -1):
            m[i] = (r[i] - c[i] * m[i + 1]) / b[i]
        Ms.append(m)

    def f(t: float) -> tuple[float, ...]:
        if t <= ts[0]:
            return vals[0]
        if t >= ts[-1]:
            return vals[-1]
        i = 0
        while i < n - 2 and t > ts[i + 1]:
            i += 1
        hi = h[i]
        A, B = ts[i + 1] - t, t - ts[i]
        out = []
        for d in range(dim):
            m0, m1 = Ms[d][i], Ms[d][i + 1]
            y0, y1 = vals[i][d], vals[i + 1][d]
            out.append(m0 * A ** 3 / (6 * hi) + m1 * B ** 3 / (6 * hi) + (y0 / hi - m0 * hi / 6) * A
                       + (y1 / hi - m1 * hi / 6) * B)
        return tuple(out)

    return f


def smoothness(samples: Sequence[Sequence[float]], fps: float) -> dict[str, float]:
    """Velocity-discontinuity check on per-frame positions.

    Returns max speed, max |accel| and ``jerk_ratio`` = max |Δaccel| per frame / max speed. A velocity kink makes
    one Δaccel spike of ~Δv·fps (ratio >> 1); the C2 camera splines measure < 0.1.
    """
    if len(samples) < 4:
        return {"max_speed": 0.0, "max_accel": 0.0, "jerk_ratio": 0.0}
    vel = [[(b[d] - a[d]) * fps for d in range(len(a))] for a, b in zip(samples, samples[1:])]
    acc = [[(b[d] - a[d]) * fps for d in range(len(a))] for a, b in zip(vel, vel[1:])]
    jerk = [[(b[d] - a[d]) for d in range(len(a))] for a, b in zip(acc, acc[1:])]
    norm = lambda v: math.sqrt(sum(x * x for x in v))
    ms = max(norm(v) for v in vel)
    return {"max_speed": ms, "max_accel": max(norm(a) for a in acc),
            "jerk_ratio": (max(norm(j) for j in jerk) / ms) if ms > 1e-9 else 0.0}


def wobble(t: float, seed: int, amp: float, freqs: Sequence[float] = (0.13, 0.29, 0.53)) -> float:
    """Deterministic smooth noise (sum of sines with seeded phases), amplitude ~amp."""
    out = 0.0
    for i, fr in enumerate(freqs):
        ph = ((seed * 2654435761 + i * 40503) % 10007) / 10007.0 * math.tau
        out += math.sin(t * fr * math.tau + ph) / (i + 1)
    return amp * out / 1.83


def fov(lens_mm: float, sensor_mm: float = 36.0) -> float:
    """Horizontal field of view (radians) for a horizontal-fit sensor."""
    return 2 * math.atan(sensor_mm / 2 / lens_mm)


def fit_distance(w: float, h: float, lens_mm: float, aspect: float, fill: float = 0.8) -> float:
    """Camera distance at which a w x h (metres) rect facing the camera fills ``fill`` of the frame."""
    hf = fov(lens_mm)
    vf = 2 * math.atan(math.tan(hf / 2) / aspect)
    return max(w / (2 * math.tan(hf / 2) * fill), h / (2 * math.tan(vf / 2) * fill))


def dof_fstop(subject_size: float, softness: float = 1.0) -> float:
    """f-stop that keeps a subject of ``subject_size`` metres mostly sharp at product-shot distances while the
    background softens; scales linearly with size (a 0.3 m laptop ~ f/2.8, a 4.5 m car ~ f/11 at softness 1)."""
    return max(1.2, min(22.0, 2.8 * (subject_size / 0.3) ** 0.5 / max(softness, 0.05)))


# --------------------------------------------------------------------------------------------- shot / params


@dataclass
class Shot:
    """Normalised SceneCtx facts every studio/device scene needs."""
    fps: float
    n: int
    dur: float
    w: int
    h: int
    tier: str
    seed: int
    params: dict
    assets: dict
    product: Any
    sc: Any = None
    t_start: float = 0.0

    @property
    def vertical(self) -> bool:
        """True for portrait (9:16) framing."""
        return self.h > self.w

    @property
    def aspect(self) -> float:
        """Width / height."""
        return self.w / max(self.h, 1)

    def t(self, f: int) -> float:
        """Shot-local seconds of frame f (frame 1 = t_start, negative with a pre-handle)."""
        return (f - 1) / self.fps + self.t_start

    def u(self, f: int) -> float:
        """0..1 progress through the shot (outside in the handles)."""
        return self.t(f) / self.dur if self.dur > 0 else 0.0

    def frames(self) -> range:
        """All shot frames 1..n."""
        return range(1, self.n + 1)


def shot(sc: Any, params_schema: dict) -> Shot:
    """Build a ``Shot`` from a SceneCtx (A's ctx.py) or a dict-like stand-in; applies PARAMS defaults."""
    p = {k: v.get("default") for k, v in params_schema.items()}
    p.update({k: v for k, v in (getattr(sc, "params", None) or {}).items() if v is not None})
    fps = float(getattr(sc, "fps", 30) or 30)
    dur = float(getattr(sc, "dur", 4.0) or 4.0)
    n = getattr(sc, "frames", None)
    if not isinstance(n, int):
        n = max(1, round(dur * fps))
    w, h = tuple(getattr(sc, "res", (1920, 1080)) or (1920, 1080))
    return Shot(fps=fps, n=int(n), dur=dur, w=int(w), h=int(h), tier=str(getattr(sc, "tier", "preview")),
                seed=int(getattr(sc, "seed", 7) or 7), params=p, assets=dict(getattr(sc, "assets", None) or {}),
                product=getattr(sc, "product", None), sc=sc, t_start=float(getattr(sc, "t_start", 0.0) or 0.0))


# --------------------------------------------------------------------------------------------- render setup


def _try(obj: Any, attr: str, value: Any) -> bool:
    try:
        setattr(obj, attr, value)
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def eevee_id() -> str:
    """'BLENDER_EEVEE' on 5.x, 'BLENDER_EEVEE_NEXT' on 4.2-4.5."""
    ids = {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"


TIERS = {  # measured on RX 6800 XT, see research/w4-blender-studio.md
    "preview": {"samples": 24, "rt_scale": "2", "mblur": False, "shadow_rays": 1, "gi": True},
    "final": {"samples": 64, "rt_scale": "1", "mblur": True, "shadow_rays": 2, "gi": True},
    "max": {"samples": 128, "rt_scale": "1", "mblur": True, "shadow_rays": 3, "gi": True},
}


def setup_render(s: Shot, *, view: str = "standard", look: str = "None", exposure: float = 0.0,
                 transparent: bool = False, filter_px: float = 1.2) -> bpy.types.Scene:
    """EEVEE render settings for the shot's tier + colour management.

    ``view``: 'standard' (screens exact; use whenever UI pixels are on screen) or 'agx' / 'filmic' (pure 3D
    products: softer highlight roll-off). Frame range 1..n, fps, resolution from the shot.
    """
    scn = bpy.context.scene
    tier = TIERS.get(s.tier, TIERS["preview"])
    if s.tier == "max" and scn.render.engine == "CYCLES":  # host chose Cycles for max: keep it, only colour mgmt
        tier = dict(tier, samples=None)
    else:
        scn.render.engine = eevee_id()
    scn.render.resolution_x, scn.render.resolution_y = s.w, s.h
    scn.render.resolution_percentage = 100
    scn.frame_start, scn.frame_end = 1, s.n
    scn.render.film_transparent = transparent
    _try(scn.render, "filter_size", filter_px)
    ee = scn.eevee
    _try(ee, "taa_render_samples", tier["samples"])
    _try(ee, "use_raytracing", True)
    _try(ee, "ray_tracing_method", "SCREEN")
    rto = getattr(ee, "ray_tracing_options", None)
    if rto is not None:
        _try(rto, "resolution_scale", tier["rt_scale"])
        _try(rto, "use_denoise", True)
        _try(rto, "trace_max_roughness", 0.6)
    _try(ee, "use_fast_gi", tier["gi"])
    _try(ee, "use_shadows", True)
    _try(ee, "shadow_ray_count", tier["shadow_rays"])
    _try(ee, "shadow_step_count", 6)
    _try(ee, "use_volumetric_shadows", False)
    _try(scn.render, "use_motion_blur", tier["mblur"])
    _try(scn.render, "motion_blur_shutter", 0.35)
    _try(ee, "use_motion_blur", tier["mblur"])
    vt = {"standard": "Standard", "agx": "AgX", "filmic": "Filmic"}.get(view, "Standard")
    scn.view_settings.view_transform = vt
    if vt == "Standard" or not look or look == "None":
        _try(scn.view_settings, "look", "None")
    elif look == "punchy":   # 'AgX - Punchy' (4.x) / 'Punchy' (5.x): keeps saturated paints saturated
        for name in ("AgX - Punchy", "Punchy", "None"):
            if _try(scn.view_settings, "look", name):
                break
    else:
        _try(scn.view_settings, "look", look)
    scn.view_settings.exposure = exposure
    scn.view_settings.gamma = 1.0
    scn.display_settings.display_device = "sRGB"
    _try(bpy.context.preferences.system, "anisotropic_filter", "FILTER_16")
    return scn


# --------------------------------------------------------------------------------------------- animation keys


def key(owner: Any, path: str, frame: int, value: Any = None) -> None:
    """Set (optional) and keyframe a property."""
    if value is not None:
        setattr(owner, path, value)
    owner.keyframe_insert(path, frame=frame)


def linear_all() -> None:
    """Make every action in the file LINEAR (per-frame keys => exactly the computed values)."""
    from . import materials  # local: avoids bpy at import for tests

    for coll in (bpy.data.objects, bpy.data.cameras, bpy.data.lights, bpy.data.materials, bpy.data.worlds):
        for idb in coll:
            materials.linearize(idb)
            nt = getattr(idb, "node_tree", None)
            if nt is not None:
                materials.linearize(nt)


def finalize(s: Shot | None = None) -> None:
    """Call at the end of ``build``: re-sync screen texture colourspaces with the FINAL view transform (a screen
    built before ``setup_render`` would otherwise keep the inverse of the factory AgX view: oversaturated UI), then
    make every per-frame key LINEAR."""
    from . import materials

    materials.sync_screens(bpy.context.scene)
    linear_all()


# --------------------------------------------------------------------------------------------- camera


@dataclass
class Beat:
    """Camera beat: at time t (s) the camera is at pos, looks at target, with lens (mm)."""
    t: float
    pos: Vec3
    target: Vec3
    lens: float = 50.0
    roll: float = 0.0  # degrees


@dataclass
class CameraRig:
    """Smooth look-at camera keyed every frame from beats (see ``spline_path``)."""
    beats: list[Beat]
    end_speed: float = 0.55
    handheld: float = 0.0  # degrees of subtle drift (deterministic)
    fstop: float | None = 2.8
    focus: Callable[[float, Vec3, Vec3], float] | None = None  # (t, pos, target) -> focus distance
    seed: int = 7
    name: str = "sr_cam"
    samples: list = field(default_factory=list)

    def build(self, s: Shot) -> bpy.types.Object:
        """Create the camera, key every frame, make it the scene camera; returns the camera object."""
        cd = bpy.data.cameras.new(self.name)
        cd.sensor_fit = "HORIZONTAL"
        cd.sensor_width = 36.0
        cd.clip_start, cd.clip_end = 0.01, 400.0
        cam = bpy.data.objects.new(self.name, cd)
        bpy.context.scene.collection.objects.link(cam)
        bpy.context.scene.camera = cam
        ts = [b.t for b in self.beats]
        pos = spline_path(ts, [b.pos for b in self.beats], end_speed=self.end_speed)
        tgt = spline_path(ts, [b.target for b in self.beats], end_speed=self.end_speed)
        lens = spline_path(ts, [(b.lens, b.roll) for b in self.beats], end_speed=self.end_speed)
        if self.fstop:
            cd.dof.use_dof = True
            cd.dof.aperture_fstop = self.fstop
            cd.dof.aperture_blades = 0
        prev = None
        for f in s.frames():
            t = s.t(f)
            p, g = Vector(pos(t)), Vector(tgt(t))
            ln, roll = lens(t)
            d = g - p
            q = d.to_track_quat("-Z", "Y")
            e = q.to_euler("XYZ", prev) if prev is not None else q.to_euler("XYZ")
            if self.handheld:
                e.x += math.radians(wobble(t, self.seed, self.handheld))
                e.z += math.radians(wobble(t, self.seed + 1, self.handheld))
            if roll:
                e.rotate_axis("Z", math.radians(roll))
            prev = e.copy()
            cam.location = p
            cam.rotation_euler = e
            cam.keyframe_insert("location", frame=f)
            cam.keyframe_insert("rotation_euler", frame=f)
            cd.lens = ln
            cd.keyframe_insert("lens", frame=f)
            if self.fstop:
                fd = self.focus(t, tuple(p), tuple(g)) if self.focus else d.length
                cd.dof.focus_distance = max(0.01, fd)
                cd.dof.keyframe_insert("focus_distance", frame=f)
            self.samples.append(tuple(p))
        return cam


def look_from(target: Sequence[float], yaw_deg: float, pitch_deg: float, dist: float) -> Vec3:
    """Camera position at ``dist`` from target, yaw 0 = in front (-Y), positive yaw = camera moves to +X side,
    pitch positive = above."""
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    return (target[0] + dist * math.cos(p) * math.sin(y), target[1] - dist * math.cos(p) * math.cos(y),
            target[2] + dist * math.sin(p))


# --------------------------------------------------------------------------------------------- stage / lights

PRESETS = {
    # cyc base colour + backdrop GLOW (emissive radial gradient on the cyc behind the subject: art-directable,
    # independent of light energies, never a hot spot in reflections), floor roughness, world, light colours,
    # relative energies.
    "studio": {"cyc": "#0b0c0e", "glow": "#5a6070", "glow_e": 0.35, "rough": 0.2, "world": "#040405",
               "key": "#fff4e8", "rim": "#e4ecff", "top": "#ffffff", "key_e": 1.0, "rim_e": 1.0, "top_e": 0.5},
    "light": {"cyc": "#c9ccd1", "glow": "#ffffff", "glow_e": 0.25, "rough": 0.35, "world": "#b9bcc2",
              "key": "#ffffff", "rim": "#ffffff", "top": "#ffffff", "key_e": 0.8, "rim_e": 0.5, "top_e": 0.9},
    "sunset": {"cyc": "#140a0c", "glow": "#ff7a3d", "glow_e": 0.6, "rough": 0.25, "world": "#0c0608",
               "key": "#ffb070", "rim": "#8fb0ff", "top": "#ffd2b0", "key_e": 1.0, "rim_e": 1.1, "top_e": 0.3},
    "accent": {"cyc": "#0b0b0e", "glow": "@accent", "glow_e": 0.55, "rough": 0.22, "world": "#040406",
               "key": "#fff4ea", "rim": "#ffffff", "top": "#ffffff", "key_e": 1.0, "rim_e": 0.9, "top_e": 0.4},
    # film noir at night: black stage, ONE hard spot key, a cold rim, venetian-blind light on the wall through
    # haze, a wet (puddled) mirror floor; see _noir()
    "noir": {"cyc": "#060607", "glow": "#3a4150", "glow_e": 0.05, "rough": 0.04, "world": "#000000",
             "key": "#f6f1e6", "rim": "#a9bddc", "top": "#ffffff", "key_e": 1.0, "rim_e": 0.6, "top_e": 0.0},
}


def _area(name: str, size: tuple[float, float], color, energy: float, loc: Vec3, target: Vec3,
          spread_deg: float = 180.0, shadow: bool = True, spec: float = 1.0, diffuse: float = 1.0
          ) -> bpy.types.Object:
    from . import materials

    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = size
    ld.color = materials.hex_rgb(color) if isinstance(color, str) else color
    ld.energy = energy
    _try(ld, "spread", math.radians(spread_deg))
    _try(ld, "use_shadow", shadow)
    _try(ld, "specular_factor", spec)
    _try(ld, "diffuse_factor", diffuse)
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def card(name: str, size: tuple[float, float], loc: Vec3, target: Vec3, strength: float, color="#ffffff"
         ) -> bpy.types.Object:
    """Emissive softbox card: invisible to the camera and to shadows, seen only in reflections (gives aluminium /
    paint the long soft gradients of a real product studio)."""
    from . import materials

    bpy.ops.mesh.primitive_plane_add(size=1.0)
    ob = bpy.context.object
    ob.name = name
    ob.scale = (size[0], size[1], 1.0)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("Z", "Y").to_euler()
    ob.data.materials.append(materials.emissive(f"{name}_mat", color, strength))
    for attr in ("visible_camera", "visible_shadow", "visible_diffuse"):
        _try(ob, attr, False)
    return ob


def cyc_mesh(name: str, width: float, floor_front: float, floor_back: float, radius: float, height: float,
             seg: int = 16) -> bpy.types.Object:
    """Cyclorama: floor from y=-floor_front to y=floor_back, a quarter-circle cove of ``radius``, wall to height."""
    import bmesh

    prof = [(-floor_front, 0.0), (floor_back * 0.5, 0.0), (floor_back, 0.0)]
    for i in range(1, seg + 1):
        a = (i / seg) * (math.pi / 2)
        prof.append((floor_back + radius * math.sin(a), radius - radius * math.cos(a)))
    prof.append((floor_back + radius, height))
    bm = bmesh.new()
    left = [bm.verts.new((-width / 2, y, z)) for y, z in prof]
    right = [bm.verts.new((width / 2, y, z)) for y, z in prof]
    for i in range(len(prof) - 1):
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


@dataclass
class Stage:
    """Handles to the built stage (for reveal / sweep animation)."""
    lights: dict
    energies: dict
    world: Any
    world_strength: float
    cyc: Any = None
    sweep: Any = None


def backdrop_material(name: str, base: str, glow: str, strength: float, *, roughness: float, specular: float,
                      center: Vec3, radius: float) -> bpy.types.Material:
    """Cyc material: dark base + an emissive radial glow (object space) centred behind the subject, fading to
    the base colour; the floor part stays glossy for the subject's reflection."""
    from . import materials

    mat = materials.principled(name, base, roughness=roughness, specular=specular)
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    b = nodes.get("Principled BSDF")
    tc = nodes.new("ShaderNodeTexCoord")
    dist = nodes.new("ShaderNodeVectorMath")
    dist.operation = "DISTANCE"
    dist.inputs[1].default_value = center
    links.new(tc.outputs["Object"], dist.inputs[0])
    mr = nodes.new("ShaderNodeMapRange")
    mr.interpolation_type = "SMOOTHERSTEP"
    mr.inputs["From Min"].default_value = 0.0
    mr.inputs["From Max"].default_value = radius
    mr.inputs["To Min"].default_value = 1.0
    mr.inputs["To Max"].default_value = 0.0
    links.new(dist.outputs["Value"], mr.inputs["Value"])
    mul = nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.name = "sr_glow"
    mul.inputs[1].default_value = strength
    links.new(mr.outputs["Result"], mul.inputs[0])
    links.new(mul.outputs[0], b.inputs["Emission Strength"])
    b.inputs["Emission Color"].default_value = (*materials.hex_rgb(glow), 1.0)
    return mat


def stage(s: Shot, *, preset: str = "studio", center: Vec3 = (0, 0, 0), radius: float = 0.3,
          accent: str = "#7c3aed", floor: str = "reflective", cyc: bool = True, key_side: float = -1.0,
          sweep: bool = False, cam_dist: float | None = None, haze: float = 1.0,
          view_yaw: float | None = None) -> Stage:
    """Build a product stage scaled to the subject (``radius`` = bounding radius in metres).

    - Cyc with an emissive radial GLOW behind the subject (preset colour / the product accent), glossy floor
      (``floor='reflective'``: soft mirror via a planar probe) or matte.
    - KEY: big soft area front-high from ``key_side`` (-1 = camera-left). RIMS: two strips behind at subject
      height aimed slightly UP (edge light on silhouettes; their cones never pool on the floor in front).
      TOP: softbox above (fill + sheen on decks; light linking keeps it off the floor). Softbox CARD behind the camera for long
      reflections on surfaces facing the lens (its floor mirror image stays behind the lens).
    - Optional SWEEP strip (specular-mostly) for reveals: ``animate_sweep``. Energies scale with radius^2.
    """
    from . import materials

    pr = dict(PRESETS.get(preset, PRESETS["studio"]))
    if preset == "noir":
        floor = "reflective"                    # noir is a wet night: the floor always mirrors
    for k, v in list(pr.items()):
        if v == "@accent":
            pr[k] = accent
    cx, cy, cz = center
    r = max(radius, 0.02)
    e2 = r * r / 0.09  # energies tuned at r = 0.3 m
    scn = bpy.context.scene
    world = bpy.data.worlds.new("sr_world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*materials.hex_rgb(pr["world"]), 1.0)
    bg.inputs[1].default_value = 1.0
    scn.world = world
    cyc_ob = None
    if cyc:
        fb, cr = r * 6, r * 5
        cyc_ob = cyc_mesh("sr_cyc", width=r * 44, floor_front=r * 24, floor_back=fb, radius=cr, height=r * 22)
        cyc_ob.location = (cx, cy, 0.0)
        rough = pr["rough"] if floor == "reflective" else 0.75
        glow_c = (0.0, fb + cr, cz + r * 2.2)  # cyc-local: on the wall behind the subject
        mat = backdrop_material(f"sr_cyc_{preset}", pr["cyc"], pr["glow"], pr["glow_e"], roughness=rough,
                                specular=0.3 if floor == "reflective" else 0.12, center=glow_c, radius=r * 9.0)
        cyc_ob.data.materials.append(mat)
        if floor == "reflective":
            _planar_probe(r * 16, (cx, cy, 0.0))
    ks = key_side
    lights = {
        "key": _area("sr_key", (r * 3.0, r * 2.0), pr["key"], 150 * e2 * pr["key_e"],
                     (cx + ks * r * 2.6, cy - r * 3.0, cz + r * 3.4), (cx, cy, cz), spread_deg=70),
        "rim_l": _area("sr_rim_l", (r * 0.3, r * 2.4), pr["rim"], 120 * e2 * pr["rim_e"],
                       (cx - r * 3.2, cy + r * 2.8, cz + r * 0.25), (cx, cy, cz + r * 1.1), spread_deg=36),
        "rim_r": _area("sr_rim_r", (r * 0.3, r * 2.4), pr["rim"], 120 * e2 * pr["rim_e"],
                       (cx + r * 3.2, cy + r * 2.8, cz + r * 0.25), (cx, cy, cz + r * 1.1), spread_deg=36),
        "top": _area("sr_top", (r * 4.0, r * 4.0), pr["top"], 120 * e2 * pr["top_e"],
                     (cx, cy, cz + r * 5.0), (cx, cy, cz), spec=0.25, spread_deg=60),
    }
    cd = max(cam_dist or r * 3.0, r * 2.0)
    noir = preset == "noir"
    card("sr_card_front", (r * 7.0, r * 3.0), (cx + ks * r * 0.8, cy - cd * 1.35, cz + max(r * 3.5, cd * 0.9)),
         (cx, cy, cz), strength=(1.6 if preset != "light" else 2.4) * (0.35 if noir else 1.0))
    if not noir:
        card("sr_card_low", (r * 8.0, r * 1.2), (cx - ks * r * 1.0, cy - cd * 1.6, cz + cd * 0.25), (cx, cy, cz),
             strength=0.7)
    sweep_ob = None
    if sweep:
        sweep_ob = _area("sr_sweep", (r * 0.18, r * 6.0), "#ffffff", 0.0, (cx - r * 4, cy - r * 2.2, cz + r * 2.4),
                         (cx, cy, cz), shadow=False, diffuse=0.12)
        lights["sweep"] = sweep_ob
    if cyc_ob is not None:   # rims + sweep light the subject only: on the glossy floor they were huge white streaks
        exclude_receivers([lights["rim_l"], lights["rim_r"], lights["top"]] + ([sweep_ob] if sweep_ob else []),
                          [cyc_ob])
    if noir:
        _noir(lights, world, cyc_ob, center=(cx, cy, cz), r=r, e2=e2, ks=ks, haze=haze, view_yaw=view_yaw)
    energies = {k: ob.data.energy for k, ob in lights.items()}
    return Stage(lights=lights, energies=energies, world=world, world_strength=1.0, cyc=cyc_ob, sweep=sweep_ob)


def _spot(name: str, color: str, energy: float, loc: Vec3, target: Vec3, size_deg: float, blend: float,
          radius: float) -> bpy.types.Object:
    from . import materials

    ld = bpy.data.lights.new(name, "SPOT")
    ld.color = materials.hex_rgb(color)
    ld.energy = energy
    ld.spot_size = math.radians(size_deg)
    ld.spot_blend = blend
    _try(ld, "shadow_soft_size", radius)
    _try(ld, "use_shadow", True)
    _try(ld, "volume_factor", 1.0)
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def _noir(lights: dict, world: Any, cyc_ob: Any, *, center: Vec3, r: float, e2: float, ks: float,
          haze: float = 1.0, view_yaw: float | None = None) -> None:
    """Film-noir night: the soft key + top fill go; ONE hard spot key from high on the key side pools light on a
    wet floor; one cold rim from the far side; a narrow spot through venetian-blind slats throws striped light on
    the wall behind (and across the subject); a uniform haze makes the beams visible; the floor's roughness is
    puddled (mirror-wet patches)."""
    from . import materials

    cx, cy, cz = center
    for k in ("key", "top"):
        ob = lights.pop(k, None)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    near = "rim_l" if ks < 0 else "rim_r"           # the rim on the key's side would flatten the silhouette
    if near in lights:
        lights[near].data.energy *= 0.15
    for ob in lights.values():                      # only the key and the blinds may light the haze (a sweep
        _try(ob.data, "volume_factor", 0.0)         # strip scattering in it fogged the whole frame grey)
    lights["key"] = _spot("sr_key", "#f6f1e6", 1200 * e2, (cx + ks * r * 2.0, cy - r * 2.4, cz + r * 5.4),
                          (cx, cy + r * 0.25, cz), 36.0, 0.32, r * 0.02)
    # venetian blinds: a narrow spot through slats. Camera on the front (-Y) side: aimed at the wall behind the
    # subject. Camera on the open side (the wall is behind the lens): across the wet floor beyond the subject and
    # the body itself, from high above the camera side - the stripes must land in the frame
    a = math.radians(view_yaw or 0.0)
    if view_yaw is None or math.cos(a) > 0.6:
        wall = (cx - ks * r * 0.8, cy + r * 10.6, cz + r * 3.4)
        bl = (cx - ks * r * 5.5, cy - r * 3.2, cz + r * 6.8)
        e_bl = 2600 * e2
    else:
        bx, by = -math.sin(a), math.cos(a)                 # away from the camera
        wall = (cx + bx * r * 2.0, cy + by * r * 2.0, 0.0)
        bl = (cx - bx * r * 3.5 - by * ks * r * 1.5, cy - by * r * 3.5 + bx * ks * r * 1.5, cz + r * 7.5)
        e_bl = 1500 * e2
    blinds = _spot("sr_blinds", "#e8e2d6", e_bl, bl, wall, 22.0, 0.08, r * 0.003)
    lights["blinds"] = blinds
    piv = bpy.data.objects.new("sr_blinds_frame", None)
    bpy.context.scene.collection.objects.link(piv)
    piv.location = bl
    piv.rotation_euler = blinds.rotation_euler.copy()
    for i in range(-7, 8):
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        sl = bpy.context.object
        sl.name = f"sr_slat_{i + 7:02d}"
        sl.parent = piv
        sl.location = (0.0, i * r * 0.055, -r * 1.0)
        sl.scale = (r * 0.9, r * 0.024, r * 0.004)
        for attr in ("visible_camera", "visible_glossy", "visible_diffuse", "visible_transmission"):
            _try(sl, attr, False)
    # haze: a uniform world volume (optical depth ~0.25 across the stage) so the cones read
    nt = world.node_tree
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.021 * max(0.0, haze) / max(r, 0.05)
    _try(vol.inputs["Anisotropy"], "default_value", 0.35)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_WORLD"), None)
    if out is not None and haze > 0:
        nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
    ee = bpy.context.scene.eevee
    _try(ee, "use_volumetric_shadows", True)
    _try(ee, "volumetric_shadow_samples", 16)
    _try(ee, "volumetric_end", r * 60.0)
    _try(ee, "volumetric_tile_size", "8")
    # wet floor: roughness puddled by noise (mirror patches next to damp asphalt)
    if cyc_ob is not None and cyc_ob.data.materials:
        mat = cyc_ob.data.materials[0]
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        b = nodes.get("Principled BSDF")
        tc = nodes.new("ShaderNodeTexCoord")
        nz = nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = 0.55 / max(r, 0.05)
        nz.inputs["Detail"].default_value = 4.0
        links.new(tc.outputs["Object"], nz.inputs["Vector"])
        mr = nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = 0.46
        mr.inputs["From Max"].default_value = 0.56
        mr.inputs["To Min"].default_value = 0.02
        mr.inputs["To Max"].default_value = 0.38
        links.new(nz.outputs["Fac"], mr.inputs["Value"])
        # the cove and wall are matte grey plaster (the blinds' stripes need something to land on), the floor
        # stays black and wet: blend by height
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(tc.outputs["Object"], sep.inputs[0])
        wz = nodes.new("ShaderNodeMapRange")
        wz.inputs["From Min"].default_value = r * 0.35
        wz.inputs["From Max"].default_value = r * 1.8
        links.new(sep.outputs["Z"], wz.inputs["Value"])

        def mix(kind: str, a: Any, bb: Any) -> Any:
            mx = nodes.new("ShaderNodeMix")
            mx.data_type = kind
            ins = {i.identifier: i for i in mx.inputs}
            outs = {o.identifier: o for o in mx.outputs}
            links.new(wz.outputs["Result"], ins["Factor_Float"])
            suf = "Color" if kind == "RGBA" else "Float"
            for key, val in (("A", a), ("B", bb)):
                if hasattr(val, "is_linked"):
                    links.new(val, ins[f"{key}_{suf}"])
                else:
                    ins[f"{key}_{suf}"].default_value = val
            return outs[f"Result_{suf}"]
        links.new(mix("FLOAT", mr.outputs["Result"], 0.85), b.inputs["Roughness"])
        links.new(mix("RGBA", (*materials.hex_rgb("#050506"), 1.0), (*materials.hex_rgb("#4a4a4c"), 1.0)),
                  b.inputs["Base Color"])


def exclude_receivers(light_obs: Sequence[Any], objs: Sequence[Any], name: str = "sr_ll_exclude") -> bool:
    """Light linking: ``light_obs`` do not light ``objs`` (EEVEE Next / Cycles, Blender >= 4.2; no-op before)."""
    coll = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    for ob in objs:
        if ob.name not in coll.objects:
            coll.objects.link(ob)
    try:
        for co in coll.collection_objects:
            co.light_linking.link_state = "EXCLUDE"
        for lo in light_obs:
            lo.light_linking.receiver_collection = coll
    except (AttributeError, TypeError):
        return False
    return True


def _planar_probe(size: float, loc: Vec3) -> None:
    for kind in ("PLANE", "PLANAR"):
        try:
            pd = bpy.data.lightprobes.new("sr_floor_probe", kind)
        except TypeError:
            continue
        ob = bpy.data.objects.new("sr_floor_probe", pd)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = (loc[0], loc[1], loc[2] + 0.0005)
        ob.scale = (size / 2, size / 2, 1.0)
        return


def animate_reveal(s: Shot, st: Stage, *, t0: float = 0.0, t1: float = 1.6, from_level: float = 0.0,
                   order: Sequence[str] = ("rim_l", "rim_r", "key", "top")) -> None:
    """Lights come up from darkness, staggered (rims first = silhouette, then key + top), eased, every frame."""
    span = max(t1 - t0, 1e-3)
    for i, name in enumerate(order):
        ob = st.lights.get(name)
        if ob is None:
            continue
        a = t0 + span * 0.18 * i
        b = a + span * 0.55
        for f in s.frames():
            u = window(s.t(f), a, b)
            ob.data.energy = st.energies[name] * (from_level + (1 - from_level) * u)
            ob.data.keyframe_insert("energy", frame=f)
    bg = st.world.node_tree.nodes["Background"]
    glow = None
    if st.cyc is not None and st.cyc.data.materials:
        glow = st.cyc.data.materials[0].node_tree.nodes.get("sr_glow")
    g0 = glow.inputs[1].default_value if glow is not None else 0.0
    for f in s.frames():
        u = from_level + (1 - from_level) * window(s.t(f), t0 + span * 0.3, t1 + span * 0.2)
        bg.inputs[1].default_value = st.world_strength * u
        bg.inputs[1].keyframe_insert("default_value", frame=f)
        if glow is not None:
            glow.inputs[1].default_value = g0 * u
            glow.inputs[1].keyframe_insert("default_value", frame=f)


def animate_sweep(s: Shot, st: Stage, *, t0: float, t1: float, center: Vec3, radius: float,
                  energy: float = 900.0, height: float = 1.2) -> None:
    """A tall strip light slides left -> right in front of the subject: its reflection sweeps the surfaces."""
    ob = st.sweep
    if ob is None:
        return
    cx, cy, cz = center
    r = radius
    e2 = r * r / 0.09
    for f in s.frames():
        t = s.t(f)
        u = window(t, t0, t1, "inout")
        x = cx + lerp(-r * 4.0, r * 4.0, u)
        ob.location = (x, cy - r * 2.4, cz + r * height)
        ob.rotation_euler = (Vector((cx + (x - cx) * 0.15, cy, cz)) - Vector(ob.location)).to_track_quat(
            "-Z", "Y").to_euler()
        env = math.sin(math.pi * clamp((t - t0) / max(t1 - t0, 1e-3))) ** 1.5
        ob.data.energy = energy * e2 * env
        ob.keyframe_insert("location", frame=f)
        ob.keyframe_insert("rotation_euler", frame=f)
        ob.data.keyframe_insert("energy", frame=f)
