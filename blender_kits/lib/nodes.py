"""Tiny node-graph builder shared by the scene-craft modules (shader, geometry and compositor trees).

    g = NodeGraph(material.node_tree)
    n = g.node("ShaderNodeTexNoise", {"Scale": 4.0, "Vector": some_socket}, noise_dimensions="4D")
    v = g.math("MULTIPLY", n.outputs["Factor"], 2.0)

Inputs are matched by name among *available* sockets (Blender keeps hidden sockets for other data types on
nodes like Mix / Switch), or by integer index. A socket value links; anything else sets ``default_value``.
"""
from __future__ import annotations

from typing import Any


def _available(sock) -> bool:
    if getattr(sock, "is_unavailable", False):
        return False
    return getattr(sock, "enabled", True)


def sock_in(node, key):
    """Input socket by index or (first available) name."""
    if isinstance(key, int):
        return node.inputs[key]
    for s in node.inputs:
        if s.name == key and _available(s):
            return s
    for s in node.inputs:
        if s.identifier == key:
            return s
    raise KeyError(f"{node.bl_idname} has no available input {key!r}: {[s.name for s in node.inputs]}")


def sock_out(node, key=0):
    """Output socket by index or (first available) name."""
    if isinstance(key, int):
        outs = [s for s in node.outputs if _available(s)]
        return outs[key] if key < len(outs) else node.outputs[key]
    for s in node.outputs:
        if s.name == key and _available(s):
            return s
    raise KeyError(f"{node.bl_idname} has no available output {key!r}: {[s.name for s in node.outputs]}")


class NodeGraph:
    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links

    def node(self, bl_idname: str, inputs: dict | None = None, **props: Any):
        n = self.nodes.new(bl_idname)
        for k, v in props.items():
            setattr(n, k, v)
        for k, v in (inputs or {}).items():
            self.set(n, k, v)
        return n

    def set(self, node, key, value) -> None:
        s = sock_in(node, key)
        if hasattr(value, "is_output") or hasattr(value, "links"):
            self.links.new(value if hasattr(value, "is_output") else sock_out(value), s)
        elif hasattr(value, "outputs") and not isinstance(value, (tuple, list)):
            self.links.new(sock_out(value), s)
        else:
            if isinstance(value, (tuple, list)) and len(value) == 3 and getattr(s, "type", "") == "RGBA":
                value = (*value, 1.0)
            try:
                s.default_value = value
            except (TypeError, ValueError):
                s.default_value = value if not isinstance(value, (int, float)) else (value,) * len(s.default_value)

    def link(self, a, b) -> None:
        self.links.new(a if hasattr(a, "is_output") else sock_out(a), b)

    # shorthand ----------------------------------------------------------------------------------------------
    def math(self, op: str, a, b=None, c=None, clamp: bool = False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.set(n, i, v)
        return n.outputs[0]

    def vmath(self, op: str, a, b=None, scale=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        if a is not None:
            self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        if scale is not None:
            self.set(n, "Scale", scale)
        out = "Value" if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else "Vector"
        return sock_out(n, out)

    def mix_rgb(self, fac, a, b, blend: str = "MIX"):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self.set(n, 0, fac)
        self.set(n, 6, a)
        self.set(n, 7, b)
        return n.outputs[2]

    def mix_float(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="FLOAT")
        self.set(n, 0, fac)
        self.set(n, 2, a)
        self.set(n, 3, b)
        return n.outputs[0]

    def mix_vec(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="VECTOR")
        self.set(n, 0, fac)
        self.set(n, 4, a)
        self.set(n, 5, b)
        return n.outputs[1]

    def ramp(self, fac, stops: list[tuple[float, tuple]], interp: str = "LINEAR"):
        n = self.node("ShaderNodeValToRGB")
        n.color_ramp.interpolation = interp
        els = n.color_ramp.elements
        while len(els) < len(stops):
            els.new(0.5)
        for el, (pos, col) in zip(els, stops):
            el.position = pos
            el.color = (*col, 1.0) if len(col) == 3 else col
        self.set(n, 0, fac)
        return n.outputs[0]

    def map_range(self, v, a0, a1, b0=0.0, b1=1.0, clamp: bool = True, interp: str = "LINEAR"):
        n = self.node("ShaderNodeMapRange", clamp=clamp, interpolation_type=interp)
        for k, x in zip(("Value", "From Min", "From Max", "To Min", "To Max"), (v, a0, a1, b0, b1)):
            self.set(n, k, x)
        return n.outputs[0]

    def xyz(self, x=0.0, y=0.0, z=0.0):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.set(n, i, v)
        return n.outputs[0]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.set(n, 0, v)
        return n.outputs[0], n.outputs[1], n.outputs[2]


def hex_rgb(h: str) -> tuple[float, float, float]:
    """'#F6C38E' -> linear RGB floats (sRGB decode)."""
    h = h.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2])


def keyed_time(owner, path: str, fps: float, frames: int, t_offset: float = 0.0) -> None:
    """Key ``owner.<path>`` = seconds linearly over the shot (frame-driven clock usable in any node tree)."""
    from .camera import linearize  # noqa: PLC0415
    setattr(owner, path, t_offset)
    owner.keyframe_insert(path, frame=1)
    setattr(owner, path, t_offset + (frames - 1) / fps)
    owner.keyframe_insert(path, frame=frames)
    idb = owner.id_data
    linearize(idb)
