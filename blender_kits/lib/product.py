"""Import + normalise any user 3D product; find its wheels; present 2D product media (inside Blender >= 4.2).

``load(path)`` -> ``Product``: imports glb/gltf/obj/fbx/stl/ply/usd(a|c|z)/blend, drops imported cameras + lights,
normalises (up axis, real-world size kept when plausible, bbox centred on the origin, sitting on z=0) under two
empties: ``pivot`` (animate this: turntable / float / drive) -> ``root`` (normalisation) -> imported objects.

Wheels: name match (wheel / tire / tyre / rim, + common non-English words) clustered by position, else a geometry
heuristic: >= 2 (usually 4) similar near-cylindrical parts touching the ground near the bbox corners. Each wheel
gets a pivot empty at its hub with the axle axis known, so ``spin_wheels`` can roll them.

2D fallback (``present``): image / video / frames on a card (exact UI colours), framed print, poster or a device
screen. UI screenshots are never mirrored or chroma-keyed.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix, Vector

from . import materials

MODEL_EXT = (".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply", ".usd", ".usda", ".usdc", ".usdz", ".blend")
WHEEL_RX = re.compile(r"(wheel|tire|tyre|rim\b|rims|_rim|rim_|felge|reifen|rueda|roue|pneu|llanta|hub)", re.IGNORECASE)
NOT_WHEEL_RX = re.compile(r"(steer|spare|lenkrad|volant|trim)", re.IGNORECASE)
KEEP_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "EMPTY", "ARMATURE", "CURVES", "POINTCLOUD", "VOLUME"}


class ProductError(RuntimeError):
    """The model could not be imported (unsupported format, empty file, importer failure)."""


@dataclass
class Wheel:
    """A wheel: pivot empty at the hub (rotate about ``axis``), radius (m), member objects."""
    pivot: bpy.types.Object
    center: Vector
    radius: float
    axis: int  # 0 = X, 1 = Y (world axle direction after normalisation)
    objects: list = field(default_factory=list)


@dataclass
class Product:
    """A normalised product in the scene."""
    pivot: bpy.types.Object
    root: bpy.types.Object
    objects: list
    size: tuple  # x, y, z (m) after normalisation
    scale: float
    wheels: list = field(default_factory=list)
    source: str = ""

    @property
    def radius(self) -> float:
        """Bounding-sphere radius (m)."""
        return 0.5 * math.sqrt(sum(v * v for v in self.size))

    @property
    def center(self) -> Vector:
        """Bbox centre in world space at rest (x=y=0, z=half height)."""
        return Vector((0.0, 0.0, self.size[2] / 2))

    @property
    def length_axis(self) -> int:
        """0 if the product is longest along X, else 1."""
        return 0 if self.size[0] >= self.size[1] else 1


def import_model(path: str | Path) -> list:
    """Import a model file; returns the NEW objects (cameras/lights removed). Raises ProductError."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in MODEL_EXT:
        raise ProductError(f"unsupported model format {ext!r} (supported: {', '.join(MODEL_EXT)})")
    if not p.is_file():
        raise ProductError(f"model file not found: {p}")
    before = set(bpy.data.objects)
    fp = str(p)
    try:
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=fp)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=fp)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=fp)
        elif ext == ".stl":
            bpy.ops.wm.stl_import(filepath=fp)
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=fp)
        elif ext in (".usd", ".usda", ".usdc", ".usdz"):
            bpy.ops.wm.usd_import(filepath=fp)
        else:
            _append_blend(fp)
    except (RuntimeError, AttributeError, TypeError) as exc:
        raise ProductError(f"import of {p.name} failed: {exc}") from exc
    new = [o for o in bpy.data.objects if o not in before]
    for o in list(new):
        if o.type not in KEEP_TYPES:
            new.remove(o)
            bpy.data.objects.remove(o, do_unlink=True)
    if not any(o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT") for o in new):
        raise ProductError(f"{p.name} contains no geometry")
    return new


def _append_blend(fp: str) -> None:
    with bpy.data.libraries.load(fp, link=False) as (src, dst):
        dst.objects = list(src.objects)
    coll = bpy.context.scene.collection
    for o in dst.objects:
        if o is not None and o.type in KEEP_TYPES and o.name not in coll.objects:
            coll.objects.link(o)


def world_bbox(objs: Sequence[Any]) -> tuple[Vector, Vector]:
    """World-space AABB of the given objects' geometry (bound_box corners; fast, deterministic)."""
    bpy.context.view_layer.update()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for o in objs:
        if o.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    if lo.x == math.inf:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return lo, hi


def load(path: str | Path, *, size: float | str = "auto", up: str = "auto", yaw_deg: float = 0.0,
         name: str = "product", detect: bool = True) -> Product:
    """Import + normalise a model (see module doc). ``size``: 'auto' keeps real-world metres when the largest
    dimension is plausible (0.02..60 m) else scales it to 1 m; a number forces the largest dimension (m).
    ``up``: 'auto' (trust the importer: glTF/OBJ/FBX/USD convert to Z-up) | 'z' | 'y' | 'x'."""
    objs = import_model(path)
    pivot = bpy.data.objects.new(f"{name}_pivot", None)
    root = bpy.data.objects.new(f"{name}_root", None)
    coll = bpy.context.scene.collection
    coll.objects.link(pivot)
    coll.objects.link(root)
    root.parent = pivot
    top = [o for o in objs if o.parent is None or o.parent not in objs]
    for o in top:
        mw = o.matrix_world.copy()
        o.parent = root
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_world = mw
    rot = {"y": (math.pi / 2, 0, 0), "x": (0, -math.pi / 2, 0)}.get(up.lower() if isinstance(up, str) else "", None)
    if rot:
        root.rotation_euler = rot
    root.rotation_euler.z += math.radians(yaw_deg)
    lo, hi = world_bbox(objs)
    dims = hi - lo
    big = max(dims) if max(dims) > 0 else 1.0
    if isinstance(size, (int, float)) and size > 0:
        s = float(size) / big
    else:
        s = 1.0 if 0.02 <= big <= 60.0 else 1.0 / big
    root.scale = (s, s, s)
    bpy.context.view_layer.update()
    lo, hi = world_bbox(objs)
    c = (lo + hi) / 2
    root.location = (root.location.x - c.x, root.location.y - c.y, root.location.z - lo.z)
    bpy.context.view_layer.update()
    lo, hi = world_bbox(objs)
    prod = Product(pivot=pivot, root=root, objects=objs, size=tuple(hi - lo), scale=s, source=str(path))
    if detect:
        prod.wheels = detect_wheels(prod)
    return prod


# ---------------------------------------------------------------------------------------------------- wheels


def _mesh_parts(prod: Product) -> list:
    return [o for o in prod.objects if o.type == "MESH" and len(o.data.vertices) > 0]


def _names(o: Any) -> str:
    out = [o.name, getattr(o.data, "name", "") if o.data else ""]
    p = o.parent
    while p is not None:
        out.append(p.name)
        p = p.parent
    return " ".join(out)


def _cluster(items: list[tuple[Any, Vector, Vector]], tol: float) -> list[list]:
    """Group (obj, lo, hi) by bbox-centre proximity."""
    groups: list[list] = []
    for it in items:
        c = (it[1] + it[2]) / 2
        for g in groups:
            gc = sum(((x[1] + x[2]) / 2 for x in g), Vector()) / len(g)
            if (gc - c).length < tol:
                g.append(it)
                break
        else:
            groups.append([it])
    return groups


def wheel_candidates(parts: list[tuple[Any, Vector, Vector]], size: Sequence[float], *, by_name: bool
                     ) -> list[dict]:
    """Pure geometry filter on (obj, lo, hi) world bboxes -> wheel dicts {objs, center, radius, axis}.

    A wheel is roughly a disc: two bbox dims ~equal (the diameter, one of them vertical), the third (axle) smaller;
    it touches the ground (bottom < 8 % of the height); diameter 8-60 % of the product length; centre away from
    the product's middle (at the corners). Name-matched parts only need the disc + ground test.
    """
    length = max(size[0], size[1], 1e-6)
    height = max(size[2], 1e-6)
    out = []
    for g in _cluster(parts, tol=length * 0.06):
        lo = Vector(map(min, *[x[1] for x in g])) if len(g) > 1 else g[0][1]
        hi = Vector(map(max, *[x[2] for x in g])) if len(g) > 1 else g[0][2]
        d = hi - lo
        c = (lo + hi) / 2
        axis = 0 if d.x < d.y else 1
        diam_h = d[1 - axis]
        diam_v = d.z
        width = d[axis]
        if diam_v <= 0 or diam_h <= 0:
            continue
        disc = abs(diam_h - diam_v) / max(diam_h, diam_v) < 0.18 and width < 0.85 * diam_v
        ground = lo.z < height * 0.08
        sized = 0.08 * length <= diam_v <= 0.6 * length
        corner = abs(c[1 - axis]) > size[1 - axis] * 0.18 and abs(c[axis]) > size[axis] * 0.12
        if disc and ground and sized and (by_name or corner):
            out.append({"objs": [x[0] for x in g], "center": c, "radius": diam_v / 2, "axis": axis})
    if not by_name:  # geometry-only: need >= 2 similar wheels, keep the dominant size class
        if len(out) < 2:
            return []
        out.sort(key=lambda w: w["radius"])
        med = out[len(out) // 2]["radius"]
        out = [w for w in out if abs(w["radius"] - med) / med < 0.2]
        if len(out) < 2:
            return []
    return out


def detect_wheels(prod: Product) -> list[Wheel]:
    """Find wheels by name, else by geometry; create hub pivots (see module doc)."""
    parts = _mesh_parts(prod)
    boxes = [(o, *world_bbox([o])) for o in parts]
    named = [b for b in boxes if WHEEL_RX.search(_names(b[0])) and not NOT_WHEEL_RX.search(_names(b[0]))]
    found = wheel_candidates(named, prod.size, by_name=True) if named else []
    if not found:
        found = wheel_candidates(boxes, prod.size, by_name=False)
    if len(found) > 8 or len(parts) - sum(len(w["objs"]) for w in found) < 1:
        return []  # implausible (everything is a "wheel")
    wheels = []
    for i, w in enumerate(found):
        piv = bpy.data.objects.new(f"sr_wheel_{i}", None)
        bpy.context.scene.collection.objects.link(piv)
        piv.parent = prod.pivot
        piv.location = w["center"]
        bpy.context.view_layer.update()
        for o in w["objs"]:
            mw = o.matrix_world.copy()
            o.parent = piv
            o.matrix_parent_inverse = Matrix.Identity(4)
            o.matrix_world = mw
        wheels.append(Wheel(pivot=piv, center=w["center"].copy(), radius=w["radius"], axis=w["axis"],
                            objects=w["objs"]))
    bpy.context.view_layer.update()
    return wheels


def spin_wheels(prod: Product, frames: Sequence[int], angle_at: Any) -> None:
    """Key every wheel pivot: ``angle_at(frame, wheel) -> radians`` about the wheel's axle."""
    for w in prod.wheels:
        for f in frames:
            e = [0.0, 0.0, 0.0]
            e[w.axis] = angle_at(f, w)
            w.pivot.rotation_euler = e
            w.pivot.keyframe_insert("rotation_euler", frame=f)


# ---------------------------------------------------------------------------------------------------- 2D media


def present(image: Any, iw: int, ih: int, *, style: str = "card", height: float = 0.5, name: str = "media",
            exact: bool = True) -> bpy.types.Object:
    """Show 2D product media standing upright facing -Y, bottom on z=0. Returns the root empty.

    style: 'card' (rounded slab, image edge to edge; exact colours via the screen material), 'print' (paper with a
    white border, lit like paper), 'poster' (black frame + white mat), 'screen' is handled by lib.device.
    ``exact`` keeps UI/screenshot pixels exact (emissive); False = lit print (photos).
    """
    from . import device as dv

    aspect = iw / max(ih, 1)
    h = height
    w = h * aspect
    root = bpy.data.objects.new(f"{name}_root", None)
    bpy.context.scene.collection.objects.link(root)
    axis = bpy.data.objects.new(f"{name}_axis", None)
    bpy.context.scene.collection.objects.link(axis)
    axis.parent = root
    axis.rotation_euler = (math.pi / 2, 0, 0)
    border = {"card": 0.0, "print": 0.06, "poster": 0.08}.get(style, 0.0) * h
    frame_t = 0.012 * h if style == "poster" else 0.004 * h
    W, H = w + 2 * border, h + 2 * border
    if style == "poster":
        frm = dv.slab(f"{name}_frame", W + 0.03 * h, H + 0.03 * h, 0.002, frame_t, bevel=0.002 * h,
                      mats=[materials.matte_plastic("#111114", f"{name}_framemat", roughness=0.35)], parent=axis)
        frm.location = (0, H / 2, -frame_t)
    back_mat = materials.principled(f"{name}_paper", (0.86, 0.86, 0.84), roughness=0.55)
    back = dv.slab(f"{name}_back", W, H, 0.01 * h if style == "card" else 0.0005, frame_t * 0.6,
                   bevel=0.0008 * h, mats=[back_mat], parent=axis)
    back.location = (0, H / 2, -frame_t * 0.6)
    if exact:
        mat = materials.screen(f"{name}_img", image)
    else:
        mat = materials.principled(f"{name}_img", (1, 1, 1), roughness=0.45)
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    face = dv.flat_face(f"{name}_face", w, h, 0.01 * h if style == "card" else 0.0, mat, parent=axis)
    face.location = (0, H / 2, 0.0004)
    return root
