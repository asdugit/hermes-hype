"""Hello-world Blender scene: the smallest scene module that exercises the whole protocol.

A turntable cube on a ground plane under a sun, a smooth dolly camera keyed with ease-in-out, an optional product
image on a card (when the job has an ``image`` product), and one audio cue. Used by tests (160x90, 3 frames) and as
the placeholder Quick mapping target until the studio/device scenes land.
"""
from __future__ import annotations

import math

import bpy

PARAMS = {
    "color": {"type": "color", "default": "#E5484D", "doc": "cube colour (#RRGGBB)"},
    "spin": {"type": "float", "default": 90.0, "min": 0.0, "max": 720.0, "doc": "cube rotation over the shot (deg)"},
    "label": {"type": "string", "default": "", "doc": "unused text (param plumbing test)"},
}
DESCRIBE = "Test scene: a spinning cube on a plane, smooth dolly camera, product image on a card if available."


def _hex(c: str) -> tuple[float, float, float, float]:
    c = c.lstrip("#")
    srgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in srgb]
    return (lin[0], lin[1], lin[2], 1.0)


def _material(name: str, color: tuple[float, float, float, float], rough: float = 0.4) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    return mat


def _ease_keys(obj: bpy.types.Object, path: str, keys: list[tuple[float, object]]) -> None:
    for frame, value in keys:
        setattr(obj, path, value)
        obj.keyframe_insert(data_path=path, frame=frame)


def build(sc) -> None:
    scene = sc.scene
    world = bpy.data.worlds.new("SR World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.05, 0.06, 0.09, 1.0)
    scene.world = world

    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0, 0, 0))
    bpy.context.object.data.materials.append(_material("Ground", (0.18, 0.2, 0.22, 1.0), 0.8))

    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1.0))
    cube = bpy.context.object
    cube.data.materials.append(_material("Cube", _hex(str(sc.params["color"]))))
    first, last = 1, max(2, sc.frames)
    _ease_keys(cube, "rotation_euler", [(first, (0.0, 0.0, 0.0)),
                                        (last, (0.0, 0.0, math.radians(float(sc.params["spin"]))))])

    if sc.product and sc.product.get("kind") == "image" and sc.product.get("path"):
        bpy.ops.mesh.primitive_plane_add(size=3.0, location=(-3.2, 1.5, 1.6), rotation=(math.radians(90), 0, 0))
        card = bpy.context.object
        mat = bpy.data.materials.new("Product card")
        mat.use_nodes = True
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(sc.product["path"]))
        mat.node_tree.links.new(tex.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        card.data.materials.append(mat)

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 35.0 if not sc.portrait else 24.0
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    target = bpy.data.objects.new("Target", None)
    target.location = (0, 0, 1.0)
    scene.collection.objects.link(target)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    _ease_keys(cam, "location", [(first, (7.0, -9.0, 4.0)), (last, (4.0, -7.0, 2.6))])
    for fc in _fcurves(cam) + _fcurves(cube):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.easing = "AUTO"

    if sc.tier != "preview":   # exercise the 4.x/5.x compositor shim (Render Layers -> output + a glare node)
        tree, rl, out = sc.lib.compat.compositor_passthrough(scene)
        glare = tree.nodes.new("CompositorNodeGlare")
        tree.links.new(rl.outputs["Image"], glare.inputs["Image"])
        tree.links.new(glare.outputs["Image"], out)
        sc.lib.compat.set_compositing(scene, True)

    sc.cue(0.5, "appear")


def _fcurves(obj: bpy.types.Object) -> list:
    """F-curves of an object's action (4.4+ slotted actions keep them in layers/strips/channelbags)."""
    act = obj.animation_data.action if obj.animation_data else None
    if act is None:
        return []
    if bpy.app.version >= (4, 4, 0) and getattr(act, "is_action_layered", False):
        slot = obj.animation_data.action_slot
        return [fc for layer in act.layers for strip in layer.strips
                for fc in strip.channelbag(slot).fcurves] if slot else []
    return list(act.fcurves)


def cues(sc) -> list[dict]:
    return [{"t": max(0.0, sc.dur - 0.2), "sfx": "hit"}]
