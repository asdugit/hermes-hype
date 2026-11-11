"""Procedural premium devices (laptop, phone, tablet, monitor) with UI-exact screens (inside Blender >= 4.2).

Conventions: metres, Z up, devices FACE -Y (the camera usually sits at -Y). Every device has a ``root`` empty (move /
rotate / rise it) and one screen (``Screen``) whose UV (0..1, v up) maps onto the shown image through a
fit window (cover when it trims little, else contain: never magnified past the bezel); ``Screen.px_to_world`` maps screenshot pixels (top-left origin) to world space so a camera can
land exactly on a feature rect. No logos, no brand shapes (generic slim-bezel hardware).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

try:  # pure helpers (rounded_rect, window maths) stay importable without Blender (tests)
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
except ImportError:  # pragma: no cover - outside Blender
    bmesh = bpy = None  # type: ignore[assignment]
    Matrix = Vector = None  # type: ignore[assignment,misc]

from . import materials

SPECS = {  # w, h (screen-face plane), thickness, corner radius, display w, display h, display corner radius
    "laptop": {"w": 0.3126, "d": 0.2212, "base_t": 0.0098, "lid_t": 0.0052, "r": 0.011,
               "disp_w": 0.2960, "disp_h": 0.1850, "disp_r": 0.006, "chin": 0.0105},
    "phone": {"w": 0.0716, "h": 0.1476, "t": 0.0080, "r": 0.0110, "disp_w": 0.0668, "disp_h": 0.1428,
              "disp_r": 0.0092},
    "tablet": {"w": 0.2478, "h": 0.1785, "t": 0.0064, "r": 0.0150, "disp_w": 0.2360, "disp_h": 0.1668,
               "disp_r": 0.0110},
    "monitor": {"w": 0.6220, "h": 0.3700, "t": 0.0110, "r": 0.0080, "disp_w": 0.6060, "disp_h": 0.3409,
                "disp_r": 0.0020},
}
FINISHES = {"silver": (0.80, 0.81, 0.83), "space": (0.13, 0.135, 0.145), "midnight": (0.035, 0.045, 0.07),
            "titanium": (0.42, 0.40, 0.37), "starlight": (0.86, 0.82, 0.75)}


def rounded_rect(w: float, h: float, r: float, seg: int = 10) -> list[tuple[float, float]]:
    """CCW outline of a w x h rounded rectangle centred at the origin (corner radius r, seg per corner)."""
    r = max(0.0, min(r, w / 2 - 1e-6, h / 2 - 1e-6))
    pts = []
    corners = [(w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180),
               (w / 2 - r, -h / 2 + r, 270)]
    for cx, cy, a0 in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _link(ob: bpy.types.Object, parent: bpy.types.Object | None = None) -> bpy.types.Object:
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def slab(name: str, w: float, h: float, r: float, t: float, *, bevel: float, mats: Sequence[Any],
         top_mat: int = 0, seg: int = 12, parent=None) -> bpy.types.Object:
    """Rounded-rect prism from z=0 to z=t; material slot ``top_mat`` on the +Z face, slot 0 elsewhere.

    Bevelled edges (angle-limited, so the rounded corners stay smooth) with hardened normals: flat faces read
    flat, edges catch a thin highlight like milled aluminium.
    """
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, 0.0)) for x, y in rounded_rect(w, h, r, seg)]
    bottom = bm.faces.new(list(reversed(vs)))
    ext = bmesh.ops.extrude_face_region(bm, geom=[bottom])
    top_verts = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, t), verts=top_verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    for f in bm.faces:
        f.smooth = True
        f.material_index = top_mat if f.normal.z > 0.9 else 0
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = _link(bpy.data.objects.new(name, me), parent)
    if bevel > 0:
        md = ob.modifiers.new("bevel", "BEVEL")
        md.width = bevel
        md.segments = 4
        md.limit_method = "ANGLE"
        md.angle_limit = math.radians(40)
        md.harden_normals = True
        md.profile = 0.6
    return ob


def flat_face(name: str, w: float, h: float, r: float, mat: Any, *, seg: int = 10, parent=None
              ) -> bpy.types.Object:
    """Rounded-rect face at z=0 facing +Z with UVs spanning its bounding box (u right, v up)."""
    bm = bmesh.new()
    pts = rounded_rect(w, h, r, seg)
    vs = [bm.verts.new((x, y, 0.0)) for x, y in pts]
    face = bm.faces.new(vs)
    bmesh.ops.triangulate(bm, faces=[face])
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            co = lp.vert.co
            lp[uv].uv = ((co.x + w / 2) / w, (co.y + h / 2) / h)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    return _link(bpy.data.objects.new(name, me), parent)


@dataclass
class Screen:
    """A device display: object (local plane z=0, centred, facing +Z), size, material, current image window."""
    obj: bpy.types.Object
    w: float
    h: float
    mat: bpy.types.Material
    img_w: float = 1.0
    img_h: float = 1.0
    window: tuple = (0.0, 0.0, 1.0, 1.0)  # x0, y0, sx, sy in image UV (y up)

    def uv_to_local(self, u: float, v: float) -> Vector:
        """Screen UV (0..1, v up) -> local point."""
        return Vector(((u - 0.5) * self.w, (v - 0.5) * self.h, 0.0002))

    def px_to_screen_uv(self, px: float, py: float, window: tuple | None = None) -> tuple[float, float]:
        """Image pixel (top-left origin) -> screen UV under the (given or current) window."""
        x0, y0, sx, sy = window or self.window
        ui, vi = px / self.img_w, 1.0 - py / self.img_h
        return (ui - x0) / sx, (vi - y0) / sy

    def px_to_world(self, px: float, py: float, window: tuple | None = None) -> Vector:
        """Image pixel -> world point (uses the object's current matrix_world)."""
        u, v = self.px_to_screen_uv(px, py, window)
        return self.obj.matrix_world @ self.uv_to_local(u, v)

    def normal(self) -> Vector:
        """World-space facing direction of the display."""
        return (self.obj.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()

    def axes(self) -> tuple[Vector, Vector]:
        """World-space unit vectors of screen right (+u) and up (+v)."""
        m3 = self.obj.matrix_world.to_3x3()
        return (m3 @ Vector((1, 0, 0))).normalized(), (m3 @ Vector((0, 1, 0))).normalized()

    def show(self, *, x0: float, y0: float, sx: float, sy: float, frame: int | None = None) -> None:
        """Set (and optionally key) the shown image window. A window reaching past the image (contain fit)
        switches the texture to CLIP so the letterbox shows the page colour, never smeared edge pixels."""
        self.window = (x0, y0, sx, sy)
        materials.set_window(self.mat, x0=x0, y0=y0, sx=sx, sy=sy, frame=frame)
        eps = 1e-6
        materials.set_clip(self.mat, x0 < -eps or y0 < -eps or x0 + sx > 1 + eps or y0 + sy > 1 + eps)


@dataclass
class Device:
    """A built device: root empty, kind, screen, extra pivots (laptop lid hinge)."""
    kind: str
    root: bpy.types.Object
    screen: Screen
    size: tuple  # overall w, h, depth (metres) for framing
    parts: dict = field(default_factory=dict)

    @property
    def radius(self) -> float:
        """Bounding radius (metres)."""
        return 0.5 * math.sqrt(sum(v * v for v in self.size))


def media_image(path: str | None, *, video: bool = False, frames_dir: str | None = None) -> tuple[Any, int, int]:
    """Load a screenshot / capture video / frame sequence as a Blender image -> (image, w, h)."""
    if not path and not frames_dir:
        return None, 1, 1
    if frames_dir:
        import os

        files = sorted(f for f in os.listdir(frames_dir) if f.lower().endswith((".png", ".jpg", ".jpeg")))
        img = materials.load_image(os.path.join(frames_dir, files[0]), sequence=True) if files else None
    else:
        img = materials.load_image(path)
        if video:
            img.source = "MOVIE"
    if img is None:
        return None, 1, 1
    w, h = img.size[:]
    return img, max(1, w), max(1, h)


def edge_fill_image(img: Any, *, max_px: int = 16_000_000) -> Any:
    """1x1 image of the most common border colour of ``img`` (the page background around a UI capture) for the
    letterbox of a contain-fitted screen; None for movies / sequences / huge images (they letterbox in black)."""
    try:
        if img is None or img.source not in ("FILE", "GENERATED") or img.is_float:
            return None  # float buffers are linear: their raw values would not round-trip through a byte fill
        w, h = img.size[:]
        if not w or not h or w * h > max_px:
            return None
        import numpy as np

        n = len(img.pixels)
        ch = n // (w * h)
        if ch < 3:
            return None
        buf = np.empty(n, dtype=np.float32)
        img.pixels.foreach_get(buf)
        a = buf.reshape(h, w, ch)[:, :, :3]
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        q = np.clip(np.round(edge * 255.0), 0, 255).astype(np.int64)
        keys = q[:, 0] * 65536 + q[:, 1] * 256 + q[:, 2]
        vals, counts = np.unique(keys, return_counts=True)
        k = int(vals[int(counts.argmax())])
    except (RuntimeError, ValueError, AttributeError, ImportError):
        return None
    fill = bpy.data.images.new(f"{img.name}_fill", 1, 1, alpha=False)
    fill.pixels[:] = (((k >> 16) & 255) / 255.0, ((k >> 8) & 255) / 255.0, (k & 255) / 255.0, 1.0)
    try:   # a GENERATED image is regenerated (black) when its buffer is reloaded for the render: pack the pixels
        fill.pack()
    except RuntimeError:
        pass
    return fill


def _screen(kind: str, name: str, disp_w: float, disp_h: float, disp_r: float, image, iw: int, ih: int,
            parent, *, glare: float, align: str, fit: str = "auto") -> Screen:
    mat = materials.screen(f"{name}_mat", image, glare=glare)
    ob = flat_face(f"{name}_display", disp_w, disp_h, disp_r, mat, parent=parent)
    scr = Screen(obj=ob, w=disp_w, h=disp_h, mat=mat, img_w=iw, img_h=ih)
    (x0, y0, sx, sy), used = materials.fit_window(iw, ih, disp_w, disp_h, align=align, fit=fit)
    if used == "contain":
        materials.set_fill(mat, edge_fill_image(image))
    scr.show(x0=x0, y0=y0, sx=sx, sy=sy)
    return scr


def finish_rgb(finish: str | Sequence[float]) -> tuple:
    """Device body colour from a finish name or rgb."""
    if isinstance(finish, str):
        if finish.startswith("#"):
            return materials.hex_rgb(finish)
        return FINISHES.get(finish, FINISHES["silver"])
    return tuple(finish)[:3]


def laptop(name: str = "laptop", *, image=None, iw: int = 1440, ih: int = 900, finish="silver",
           open_deg: float = 108.0, glare: float = 0.0, align: str = "top", fit: str = "auto") -> Device:
    """Slim aluminium laptop. ``root`` sits at the base's front-centre-bottom (z=0 is the desk).

    Lid hinge pivot = ``parts['hinge']`` (rotation_euler.x = -radians(open_deg)); keyboard well + trackpad inset.
    """
    sp = SPECS["laptop"]
    w, d, bt, lt = sp["w"], sp["d"], sp["base_t"], sp["lid_t"]
    alu = materials.aluminium(f"{name}_alu", finish_rgb(finish), roughness=0.42)  # bead-blasted
    dark = materials.matte_plastic("#070709", f"{name}_keys", roughness=0.42)
    bezel = materials.black_glass(f"{name}_bezel")
    root = _link(bpy.data.objects.new(f"{name}_root", None))
    root.empty_display_size = 0.05
    base = slab(f"{name}_base", w, d, sp["r"], bt, bevel=0.0011, mats=[alu], parent=root)
    base.location = (0, d / 2, 0)  # front edge at y=0
    # keyboard well (inset dark keys area) + trackpad
    kb = slab(f"{name}_kbd", w * 0.86, d * 0.40, 0.004, 0.0004, bevel=0.0002, mats=[dark], parent=root)
    kb.location = (0, d * 0.66, bt - 0.00025)
    _keys(f"{name}_keycaps", w * 0.84, d * 0.38, (0, d * 0.66, bt + 0.0001), dark, root)
    tp = slab(f"{name}_trackpad", w * 0.40, d * 0.27, 0.005, 0.0003, bevel=0.0002,
              mats=[materials.aluminium(f"{name}_tp", tuple(c * 0.96 for c in finish_rgb(finish)), roughness=0.45,
                                        brushed=0.0)], parent=root)
    tp.location = (0, d * 0.20, bt - 0.0001)
    hinge = _link(bpy.data.objects.new(f"{name}_hinge", None), root)
    hinge.location = (0, d - 0.004, bt)
    lid = slab(f"{name}_lid", w, d - 0.006, sp["r"], lt, bevel=0.0009, mats=[alu, bezel], top_mat=1, seg=12,
               parent=hinge)
    # lid built lying closed: spans y in [-(d-0.006), 0] from the hinge, display face on +Z -> flip to face down
    lid.rotation_euler = (math.pi, 0, 0)
    lid.location = (0, -(d - 0.006) / 2, lt)
    # display: on the lid's inner (+Z before flip) face; in hinge space the inner face is at z=0 facing -Z
    # in hinge space the open screen's TOP is the far (-Y) end: display +v -> -Y, +u -> +X, normal -> -Z
    disp_parent = _link(bpy.data.objects.new(f"{name}_disp_frame", None), hinge)
    lid_h = d - 0.006
    top_bezel = (w - sp["disp_w"]) / 2
    disp_parent.location = (0, -(top_bezel + sp["disp_h"] / 2) - (lid_h - sp["disp_h"] - 2 * top_bezel), -0.00005)
    disp_parent.rotation_euler = (math.pi, 0, 0)
    scr = _screen("laptop", name, sp["disp_w"], sp["disp_h"], sp["disp_r"], image, iw, ih, disp_parent,
                  glare=glare, align=align, fit=fit)
    hinge.rotation_euler = (-math.radians(open_deg), 0, 0)
    dev = Device("laptop", root, scr, (w, d, d * 0.95), {"hinge": hinge, "base": base, "lid": lid})
    return dev


def _keys(name: str, w: float, h: float, loc, mat, parent) -> None:
    """Key caps as one mesh: 6 rows of rounded squares (generic layout, no legends)."""
    bm = bmesh.new()
    rows = [14, 14, 13, 12, 12, 0]
    kh = h / 6.2
    gap = kh * 0.18
    for ri, cnt in enumerate(rows):
        y = h / 2 - (ri + 0.5) * (h / 6)
        if cnt == 0:  # bottom row: modifiers + space bar
            sizes = [1, 1, 1, 1.3, 5.2, 1.3, 1, 1, 1]
        else:
            sizes = [1.0] * cnt
            if ri in (2, 3):
                sizes[0] = sizes[-1] = 1.6 if ri == 2 else 2.1
        unit = (w - gap * (len(sizes) - 1)) / sum(sizes)
        x = -w / 2
        for s in sizes:
            kw = unit * s
            top_h = kh * (0.62 if ri == 0 else 1.0)
            pts = rounded_rect(kw - gap * 0.2, top_h - gap * 0.6, min(kw, top_h) * 0.14, 3)
            vs = [bm.verts.new((x + kw / 2 + px, y + py, 0)) for px, py in pts]
            f = bm.faces.new(vs)
            ext = bmesh.ops.extrude_face_region(bm, geom=[f])
            bmesh.ops.translate(bm, vec=(0, 0, 0.0007),
                                verts=[e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)])
            x += kw + gap
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = _link(bpy.data.objects.new(name, me), parent)
    ob.location = loc


def handheld_device(kind: str, name: str | None = None, *, image=None, iw: int = 390, ih: int = 844,
                    finish="space", glare: float = 0.0, align: str = "top", camera_bump: bool = True,
                    fit: str = "auto") -> Device:
    """Phone or tablet standing upright, display facing -Y. ``root`` at the device centre."""
    sp = SPECS[kind]
    name = name or kind
    w, h, t = sp["w"], sp["h"], sp["t"]
    frame_mat = materials.aluminium(f"{name}_frame", finish_rgb(finish), roughness=0.22, brushed=0.2)
    front = materials.black_glass(f"{name}_front")
    back = materials.principled(f"{name}_back", tuple(c * 0.9 for c in finish_rgb(finish)), metallic=0.3,
                                roughness=0.42, coat=0.6, coat_roughness=0.25)
    root = _link(bpy.data.objects.new(f"{name}_root", None))
    root.empty_display_size = 0.03
    body_axis = _link(bpy.data.objects.new(f"{name}_body", None), root)
    body_axis.rotation_euler = (math.pi / 2, 0, 0)  # local +Z (display) -> world -Y
    body = slab(f"{name}_shell", w, h, sp["r"], t, bevel=min(0.0024, t * 0.3), mats=[frame_mat, front],
                top_mat=1, parent=body_axis)
    body.location = (0, 0, -t / 2)
    body.data.materials.append(back)
    for poly in body.data.polygons:
        if poly.normal.z < -0.9:
            poly.material_index = 2
    disp_frame = _link(bpy.data.objects.new(f"{name}_disp_frame", None), body_axis)
    disp_frame.location = (0, 0, t / 2 + 0.00006)
    scr = _screen(kind, name, sp["disp_w"], sp["disp_h"], sp["disp_r"], image, iw, ih, disp_frame, glare=glare,
                  align=align, fit=fit)
    if kind == "phone":
        cam_dot = flat_face(f"{name}_frontcam", 0.002, 0.002, 0.001, materials.black_glass(f"{name}_fc"),
                            parent=disp_frame)
        cam_dot.location = (0, sp["disp_h"] / 2 - 0.006, 0.0003)
    if camera_bump:
        _camera_bump(name, kind, w, h, t, body_axis, frame_mat)
    return Device(kind, root, scr, (w, h, t))


def _camera_bump(name: str, kind: str, w: float, h: float, t: float, parent, frame_mat) -> None:
    s = 0.034 if kind == "phone" else 0.03
    bump = slab(f"{name}_bump", s, s, s * 0.26, 0.0012, bevel=0.0005,
                mats=[materials.principled(f"{name}_bumpglass", (0.02, 0.02, 0.025), roughness=0.08, coat=1)],
                parent=parent)
    bump.rotation_euler = (math.pi, 0, 0)
    bump.location = (w / 2 - s / 2 - 0.006 if kind == "phone" else -w / 2 + s / 2 + 0.008,
                     h / 2 - s / 2 - 0.006, -t / 2 + 0.00005)
    lens_mat = materials.black_glass(f"{name}_lens", roughness=0.02)
    ring = materials.chrome(f"{name}_ring", roughness=0.12)
    offs = [(-0.0075, 0.0075), (-0.0075, -0.0075), (0.0075, 0.0)] if kind == "phone" else [(0.0, 0.0)]
    for i, (ox, oy) in enumerate(offs):
        rr = slab(f"{name}_lensring{i}", 0.0128, 0.0128, 0.0064, 0.0011, bevel=0.0003, mats=[ring, lens_mat],
                  top_mat=1, seg=10, parent=bump)
        rr.location = (ox, oy, 0.0011)


def monitor(name: str = "monitor", *, image=None, iw: int = 1920, ih: int = 1080, finish="silver",
            glare: float = 0.0, align: str = "top", fit: str = "auto") -> Device:
    """Thin aluminium display on a stand; ``root`` on the desk under the stand, display centre ~0.36 m up."""
    sp = SPECS["monitor"]
    w, h, t = sp["w"], sp["h"], sp["t"]
    alu = materials.aluminium(f"{name}_alu", finish_rgb(finish), roughness=0.42)  # bead-blasted
    bezel = materials.black_glass(f"{name}_bezel")
    root = _link(bpy.data.objects.new(f"{name}_root", None))
    panel_axis = _link(bpy.data.objects.new(f"{name}_panel", None), root)
    panel_axis.location = (0, 0, 0.36)
    panel_axis.rotation_euler = (math.pi / 2 - math.radians(4), 0, 0)
    panel = slab(f"{name}_shell", w, h, sp["r"], t, bevel=0.002, mats=[alu, bezel], top_mat=1, parent=panel_axis)
    panel.location = (0, 0, -t / 2)
    disp_frame = _link(bpy.data.objects.new(f"{name}_disp_frame", None), panel_axis)
    disp_frame.location = (0, (h - sp["disp_h"]) / 2 - 0.006, t / 2 + 0.00006)
    scr = _screen("monitor", name, sp["disp_w"], sp["disp_h"], sp["disp_r"], image, iw, ih, disp_frame,
                  glare=glare, align=align, fit=fit)
    neck = slab(f"{name}_neck", 0.11, 0.30, 0.01, 0.012, bevel=0.002, mats=[alu], parent=root)
    neck.rotation_euler = (math.pi / 2 - math.radians(12), 0, 0)
    neck.location = (0, 0.06, 0.155)
    foot = slab(f"{name}_foot", 0.22, 0.17, 0.02, 0.006, bevel=0.0015, mats=[alu], parent=root)
    foot.location = (0, 0.03, 0)
    return Device("monitor", root, scr, (w, 0.2, 0.36 + h / 2))


def build(kind: str, *, image=None, iw: int = 1440, ih: int = 900, finish: str | None = None, name: str | None
          = None, glare: float = 0.0, open_deg: float = 108.0, align: str = "top", fit: str = "auto") -> Device:
    """Build a device by kind ('laptop' | 'phone' | 'tablet' | 'monitor'). ``fit``: auto (cover when it trims
    <= 12 %, else contain = the whole capture inside the bezel) | cover (scrolling pages) | contain."""
    if kind == "laptop":
        return laptop(name or "laptop", image=image, iw=iw, ih=ih, finish=finish or "silver", open_deg=open_deg,
                      glare=glare, align=align, fit=fit)
    if kind == "monitor":
        return monitor(name or "monitor", image=image, iw=iw, ih=ih, finish=finish or "silver", glare=glare,
                       align=align, fit=fit)
    return handheld_device(kind, name, image=image, iw=iw, ih=ih, finish=finish or "space", glare=glare,
                           align=align, fit=fit)


def screen_center_world(dev: Device) -> Vector:
    """Display centre in world space (current frame)."""
    bpy.context.view_layer.update()
    return dev.screen.obj.matrix_world @ Vector((0, 0, 0))


def rect_world(dev: Device, bbox_frac: Sequence[float], window: tuple | None = None) -> tuple[Vector, float, float]:
    """Centre (world) + width/height (metres) of an image-fraction rect [x, y, w, h] (top-left origin) on screen."""
    scr = dev.screen
    x, y, w, h = bbox_frac
    c = scr.px_to_world((x + w / 2) * scr.img_w, (y + h / 2) * scr.img_h, window)
    x0, y0, sx, sy = window or scr.window
    return c, w / sx * scr.w, h / sy * scr.h


ARROW = [(0.0, 0.0), (0.0, -17.0), (4.2, -13.2), (7.0, -19.6), (9.8, -18.4), (7.1, -12.2), (12.4, -12.2)]


def _poly_obj(name: str, pts: Sequence[tuple[float, float]], scale: float, mat, parent, z: float,
              grow: float = 0.0) -> bpy.types.Object:
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    bm = bmesh.new()
    vs = [bm.verts.new((((x - cx) * (1 + grow) + cx) * scale, ((y - cy) * (1 + grow) + cy) * scale, 0.0))
          for x, y in pts]
    bm.faces.new(vs)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = _link(bpy.data.objects.new(name, me), parent)
    ob.location.z = z
    return ob


def cursor(dev: Device, *, size_px: float = 34.0) -> bpy.types.Object:
    """Pointer arrow lying on the display (white fill, dark outline, emissive = exact). Returns an empty whose
    local XY is the display's local plane: put its location at ``screen.uv_to_local`` of the tip."""
    scr = dev.screen
    holder = _link(bpy.data.objects.new("sr_cursor", None), scr.obj)
    px_m = scr.w / max(scr.img_w * scr.window[2], 1.0)  # metres per image pixel on this display
    s = size_px * px_m / 20.0
    white = materials.emissive("sr_cursor_white", (1, 1, 1), 1.0)
    black = materials.emissive("sr_cursor_black", (0.0, 0.0, 0.0), 1.0)
    _poly_obj("sr_cursor_outline", ARROW, s, black, holder, 0.0004, grow=0.22)
    _poly_obj("sr_cursor_fill", ARROW, s, white, holder, 0.0007)
    return holder


def ripple(dev: Device, color=(1, 1, 1), *, radius_px: float = 40.0) -> tuple[bpy.types.Object, Any]:
    """Click ripple ring on the display: returns (object, material); animate scale + material 'sr_alpha'."""
    scr = dev.screen
    px_m = scr.w / max(scr.img_w * scr.window[2], 1.0)
    r = radius_px * px_m
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=False, radius=r, segments=48)
    inner = [bm.verts.new((v.co.x * 0.82, v.co.y * 0.82, 0)) for v in bm.verts[:]]
    outer = bm.verts[:48]
    for i in range(48):
        j = (i + 1) % 48
        bm.faces.new((outer[i], outer[j], inner[j], inner[i]))
    me = bpy.data.meshes.new("sr_ripple")
    bm.to_mesh(me)
    bm.free()
    mat = bpy.data.materials.new("sr_ripple")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (*(materials.hex_rgb(color) if isinstance(color, str) else color), 1.0)
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.name = "sr_alpha"
    mix.inputs[0].default_value = 0.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    try:
        mat.surface_render_method = "BLENDED"
    except AttributeError:
        pass
    me.materials.append(mat)
    ob = _link(bpy.data.objects.new("sr_ripple", me), scr.obj)
    ob.location.z = 0.0009
    return ob, mat


def window_showing(scr: Screen, bbox_frac: Sequence[float]) -> tuple:
    """Shift the current cover window (same scale) so the image rect [x,y,w,h] (top-left fractions) is inside it,
    centred when it has to move (feature below the fold on a tall capture)."""
    x0, y0, sx, sy = scr.window
    x, y, w, h = bbox_frac
    vx0, vx1 = x, x + w
    vy0, vy1 = 1 - (y + h), 1 - y  # to UV (v up)
    if vx0 < x0 or vx1 > x0 + sx:
        x0 = min(max((vx0 + vx1) / 2 - sx / 2, 0.0), max(0.0, 1 - sx))
    if vy0 < y0 or vy1 > y0 + sy:
        y0 = min(max((vy0 + vy1) / 2 - sy / 2, 0.0), max(0.0, 1 - sy))
    return x0, y0, sx, sy


def matrix_at(ob: bpy.types.Object, frame: int) -> Matrix:
    """World matrix of ``ob`` at ``frame`` (evaluates animation)."""
    bpy.context.scene.frame_set(frame)
    return ob.matrix_world.copy()
