"""Shared plumbing for the studio kit scenes (product loading, 2D fallback, material upgrades, framing)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

from ..lib import device as dv
from ..lib import materials, product, studio


def model_ref(s: studio.Shot, key: str = "model") -> dict | None:
    """The 3D product: param ``model`` (asset name / path) else ``sc.product`` / first model asset."""
    ref = s.params.get(key)
    if isinstance(ref, str) and ref:
        if ref in s.assets:
            return dict(s.assets[ref])
        if Path(ref).exists():
            return {"kind": "model" if ref.lower().endswith(product.MODEL_EXT) else "image", "path": ref}
    if isinstance(s.product, dict) and s.product.get("path"):
        return dict(s.product)
    for a in s.assets.values():
        if a.get("kind") == "model":
            return dict(a)
    for a in s.assets.values():
        if a.get("kind") in ("image", "video", "frames"):
            return dict(a)
    return None


class Subject:
    """What the studio camera looks at: a normalised 3D product, or 2D media presented on a card."""

    def __init__(self, pivot: Any, size: tuple, prod: product.Product | None = None) -> None:
        self.pivot = pivot
        self.size = size
        self.prod = prod

    @property
    def radius(self) -> float:
        return 0.5 * math.sqrt(sum(v * v for v in self.size))

    @property
    def center(self) -> Vector:
        return Vector((0, 0, self.size[2] / 2))

    @property
    def wheels(self) -> list:
        return self.prod.wheels if self.prod else []


def load_subject(s: studio.Shot, *, yaw_deg: float = 0.0, card_style: str = "card") -> Subject:
    """Load the product model (normalised) or present 2D media; raises product.ProductError if nothing usable."""
    ref = model_ref(s)
    if ref is None:
        raise product.ProductError("no product: pass params.model or a job product/model asset")
    kind = ref.get("kind") or "model"
    path = ref.get("path")
    if kind == "model" or (path and str(path).lower().endswith(product.MODEL_EXT)):
        prod = product.load(path, yaw_deg=yaw_deg, size=s.params.get("size_m") or "auto")
        return Subject(prod.pivot, prod.size, prod)
    img, iw, ih = dv.media_image(path, video=kind == "video",
                                 frames_dir=ref.get("frames_dir") if kind == "frames" else None)
    h = 0.42 if iw >= ih else 0.6
    root = product.present(img, iw, ih, style=card_style, height=h, name="media", exact=True)
    piv = bpy.data.objects.new("media_pivot", None)
    bpy.context.scene.collection.objects.link(piv)
    root.parent = piv
    return Subject(piv, (h * iw / ih, 0.02, h))


def upgrade_paint(sub: Subject, mode: str = "auto", paint: str | None = None) -> str | None:
    """Give the body paint a clear coat (vehicles: model has wheels; 'on' forces). Edits the Principled node of the
    material covering the most surface outside wheels/glass in place (keeps base colour + textures). Returns the
    material name or None. ``paint`` (hex) also recolours that material (models whose exported paint lost its
    node-driven colour import white)."""
    if sub.prod is None or (not paint and (mode == "off" or (mode == "auto" and not sub.prod.wheels))):
        return None
    wheel_objs = {o for w in sub.prod.wheels for o in w.objects}
    area: dict[str, float] = {}
    for o in sub.prod.objects:
        if o.type != "MESH" or o in wheel_objs:
            continue
        sx = max(o.matrix_world.to_scale())
        for poly in o.data.polygons:
            if poly.material_index < len(o.material_slots):
                m = o.material_slots[poly.material_index].material
                if m is not None:
                    area[m.name] = area.get(m.name, 0.0) + poly.area * sx * sx
    for name in sorted(area, key=lambda k: -area[k]):
        m = bpy.data.materials[name]
        b = next((n for n in (m.node_tree.nodes if m.use_nodes else []) if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        tw = b.inputs.get("Transmission Weight")
        if tw is not None and tw.default_value > 0.5:
            continue
        if paint:
            bc = b.inputs.get("Base Color")
            for lk in list(bc.links):
                m.node_tree.links.remove(lk)
            bc.default_value = (*materials.hex_rgb(paint), 1.0)
            rr = b.inputs.get("Roughness")   # crisp candy paint: drop node-driven roughness (washed the red out)
            for lk in list(rr.links):
                m.node_tree.links.remove(lk)
            rr.default_value = 0.2
            if b.inputs.get("Metallic") is not None:
                b.inputs["Metallic"].default_value = min(b.inputs["Metallic"].default_value, 0.3)
        if mode == "off" or (mode == "auto" and not sub.prod.wheels):
            return name
        for k, v in (("Coat Weight", 1.0), ("Coat Roughness", 0.03), ("Coat IOR", 1.5)):
            if b.inputs.get(k) is not None:
                b.inputs[k].default_value = v
        r = b.inputs.get("Roughness")
        if r is not None and not r.is_linked:
            r.default_value = min(r.default_value, 0.35)
        return name
    return None


def spin(sub: Subject, s: studio.Shot, rps: float, direction: float = 1.0) -> None:
    """Roll every detected wheel at ``rps`` revolutions/s (eased in over 0.4 s so the start is not a jolt)."""
    if not sub.wheels or not rps:
        return

    def ang(f: int, w: product.Wheel) -> float:
        t = s.t(f) - s.t_start
        ramp = min(t, 0.4) ** 2 / 0.8 if t < 0.4 else t - 0.2  # integral of a 0->1 ramp over 0.4 s
        return direction * rps * math.tau * ramp

    product.spin_wheels(sub.prod, list(s.frames()), ang)
