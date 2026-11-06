"""Blender 4.2 LTS .. 5.x compatibility shim (runs INSIDE Blender's Python).

Every difference is an explicit version branch. Nothing here swallows errors: when an API we rely on is missing
we raise :class:`CompatError` with the Blender version and what was expected, so a 4.x/5.x mismatch fails loudly
instead of rendering a silently degraded film.

Known differences handled here:

* EEVEE engine id: ``BLENDER_EEVEE_NEXT`` in 4.2-4.4, ``BLENDER_EEVEE`` again from 5.0.
* Compositor: 4.x uses ``scene.use_nodes`` + ``scene.node_tree`` with a ``CompositorNodeComposite`` output;
  5.x removed ``scene.node_tree`` and uses ``scene.compositing_node_group`` (a ``CompositorNodeTree`` node group
  whose ``NodeGroupOutput`` "Image" socket is the result).
* Motion blur: 4.2+ EEVEE Next and Cycles both read ``scene.render.use_motion_blur`` / ``motion_blur_shutter``.
* Cycles GPU: compute backend per platform (OPTIX/CUDA/HIP/METAL/ONEAPI), enabled through the Cycles add-on prefs
  without saving preferences (we always run with ``--factory-startup``).
"""
from __future__ import annotations

from typing import Any

import bpy

MIN_VERSION = (4, 2, 0)


class CompatError(RuntimeError):
    """A Blender API this film needs is missing or behaves differently than expected."""


def version() -> tuple[int, int, int]:
    """Running Blender version as ``(major, minor, patch)``."""
    return tuple(int(x) for x in bpy.app.version[:3])  # type: ignore[return-value]


def version_string() -> str:
    return bpy.app.version_string


def at_least(major: int, minor: int = 0) -> bool:
    return version()[:2] >= (major, minor)


def require_min() -> None:
    """Raise unless Blender >= 4.2 (EEVEE Next, the 4.x Principled BSDF names, slotted actions are optional)."""
    if version() < MIN_VERSION:
        raise CompatError(f"Blender {version_string()} is too old: Showreel needs Blender 4.2 or newer")


def _engine_items() -> set[str]:
    return {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}


def eevee_engine_id() -> str:
    """The EEVEE (Next) render engine identifier of this Blender."""
    ident = "BLENDER_EEVEE" if at_least(5, 0) else "BLENDER_EEVEE_NEXT"
    if ident not in _engine_items():
        raise CompatError(f"Blender {version_string()}: render engine {ident!r} not available "
                          f"(engines: {sorted(_engine_items())})")
    return ident


def set_engine(scene: Any, engine: str) -> str:
    """Set ``scene.render.engine`` to ``'eevee'`` or ``'cycles'`` (or a raw id); returns the id used."""
    ident = {"eevee": eevee_engine_id(), "cycles": "CYCLES"}.get(engine, engine)
    if ident not in _engine_items():
        raise CompatError(f"Blender {version_string()}: render engine {ident!r} not available")
    scene.render.engine = ident
    return ident


# ------------------------------------------------------------------------------------------- compositor

def compositor_tree(scene: Any, create: bool = True) -> Any:
    """The scene's compositor node tree (created when ``create``), or None.

    4.x: ``scene.node_tree`` after ``scene.use_nodes = True``.
    5.x: ``scene.compositing_node_group`` (a CompositorNodeTree data-block assigned to the scene).
    """
    if at_least(5, 0):
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new(f"SR Compositor {scene.name}", "CompositorNodeTree")
            scene.compositing_node_group = tree
        return tree
    if create and not scene.use_nodes:
        scene.use_nodes = True
    return scene.node_tree


def compositor_input(tree: Any) -> Any:
    """The Render Layers node of a compositor tree (created if missing)."""
    for node in tree.nodes:
        if node.bl_idname == "CompositorNodeRLayers":
            return node
    return tree.nodes.new("CompositorNodeRLayers")


def compositor_output(tree: Any) -> tuple[Any, Any]:
    """``(node, image_input_socket)`` that defines the final composited image.

    4.x: the Composite node's "Image" input. 5.x: the group output's "Image" socket (interface socket created
    when the tree is new).
    """
    if at_least(5, 0):
        if not any(item.item_type == "SOCKET" and item.in_out == "OUTPUT" and item.name == "Image"
                   for item in tree.interface.items_tree):
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        out = next((n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"), None)
        if out is None:
            out = tree.nodes.new("NodeGroupOutput")
        return out, out.inputs["Image"]
    out = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeComposite"), None)
    if out is None:
        out = tree.nodes.new("CompositorNodeComposite")
    return out, out.inputs["Image"]


def compositor_passthrough(scene: Any) -> tuple[Any, Any, Any]:
    """A minimal working compositor: Render Layers -> output. Returns ``(tree, render_layers, output_socket)``."""
    tree = compositor_tree(scene, create=True)
    rl = compositor_input(tree)
    _, sock = compositor_output(tree)
    tree.links.new(rl.outputs["Image"], sock)
    return tree, rl, sock


def set_compositing(scene: Any, enabled: bool) -> None:
    """Enable/disable the compositor for renders."""
    scene.render.use_compositing = bool(enabled)
    if not at_least(5, 0):
        scene.use_nodes = bool(enabled) or scene.use_nodes


# ------------------------------------------------------------------------------------------- render settings

def set_motion_blur(scene: Any, enabled: bool, shutter: float = 0.5) -> None:
    """Motion blur for EEVEE Next (4.2+) and Cycles: both read the render settings."""
    scene.render.use_motion_blur = bool(enabled)
    scene.render.motion_blur_shutter = float(shutter)


def set_eevee_samples(scene: Any, samples: int) -> None:
    scene.eevee.taa_render_samples = int(samples)


def set_eevee_raytracing(scene: Any, enabled: bool) -> None:
    """Screen-space ray tracing (EEVEE Next, 4.2+)."""
    scene.eevee.use_raytracing = bool(enabled)


_GPU_BACKENDS = ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI")


def enable_cycles_gpu(scene: Any) -> str:
    """Use the first available Cycles GPU backend; fall back to CPU. Returns a device description.

    Preferences are changed in memory only (``use_preferences_save = False``); with ``--factory-startup`` the
    user's saved preferences are never read or written.
    """
    prefs = bpy.context.preferences
    prefs.use_preferences_save = False
    addon = prefs.addons.get("cycles")
    if addon is None:
        raise CompatError(f"Blender {version_string()}: the Cycles add-on is not available")
    cprefs = addon.preferences
    available = {item.identifier for item in cprefs.bl_rna.properties["compute_device_type"].enum_items}
    for backend in _GPU_BACKENDS:
        if backend not in available:
            continue
        cprefs.compute_device_type = backend
        cprefs.refresh_devices()
        gpus = [d for d in cprefs.devices if d.type == backend]
        if gpus:
            for d in cprefs.devices:
                d.use = d.type == backend
            scene.cycles.device = "GPU"
            return f"{backend}: " + ", ".join(d.name for d in gpus)
    cprefs.compute_device_type = "NONE"
    scene.cycles.device = "CPU"
    return "CPU"


def image_format(scene: Any, ext: str, alpha: bool, quality: int = 92) -> None:
    """Still-image output settings for ``jpg`` (RGB) or ``png`` (RGBA when ``alpha``)."""
    s = scene.render.image_settings
    if at_least(5, 0) and hasattr(s, "media_type"):
        s.media_type = "IMAGE"
    if ext == "png":
        s.file_format = "PNG"
        s.color_mode = "RGBA" if alpha else "RGB"
        s.color_depth = "8"
        s.compression = 15
    elif ext == "jpg":
        if alpha:
            raise CompatError("alpha output needs out_ext 'png' (JPEG has no alpha)")
        s.file_format = "JPEG"
        s.color_mode = "RGB"
        s.quality = int(quality)
    else:
        raise CompatError(f"unsupported out_ext {ext!r} (jpg|png)")
    scene.render.film_transparent = bool(alpha)
