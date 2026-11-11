"""Make the self-made CC0 test car (dev/test fixture): a simple coupe with 4 separate wheels, exported as GLB.

    blender -b --factory-startup --python-exit-code 1 -P make_testcar.py -- OUT_DIR

Writes testcar.glb (wheels named Wheel_FL/FR/RL/RR -> name detection) and testcar_anon.glb (same car, wheel
objects renamed Part_* -> geometry detection). Front = +X, metres, Z up. Provenance: generated here, CC0.
"""
import math
import sys
from pathlib import Path

import bpy

out = Path(sys.argv[sys.argv.index("--") + 1])
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)


def mat(name, rgb, metallic=0.0, rough=0.4, coat=0.0, alpha=1.0, transmission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Transmission Weight"].default_value = transmission
    return m


paint = mat("paint", (0.45, 0.01, 0.015), 0.5, 0.3, coat=1.0)
glass = mat("glass", (0.02, 0.025, 0.03), 0.0, 0.05, coat=1.0)
rubber = mat("rubber", (0.015, 0.015, 0.016), 0.0, 0.8)
alloy = mat("alloy", (0.8, 0.8, 0.82), 1.0, 0.18)
light = mat("lamp", (1.0, 0.95, 0.9), 0.0, 0.1)
tail = mat("tail", (0.6, 0.0, 0.0), 0.0, 0.2)


def box(name, size, loc, bevel, m, seg=5):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    md = o.modifiers.new("b", "BEVEL")
    md.width = bevel
    md.segments = seg
    o.data.materials.append(m)
    bpy.ops.object.shade_smooth()
    return o


body = box("Body", (4.4, 1.82, 0.62), (0, 0, 0.62), 0.22, paint, 6)
# taper the nose: move front-top verts down
for v in body.data.vertices:
    if v.co.x > 1.4 and v.co.z > 0.8:
        v.co.z -= 0.12 * (v.co.x - 1.4) / 0.8
cabin = box("Cabin", (2.1, 1.56, 0.52), (-0.25, 0, 1.12), 0.2, glass, 6)
for v in cabin.data.vertices:
    if v.co.z > 1.2:
        v.co.x *= 0.82
roof = box("Roof", (1.5, 1.5, 0.06), (-0.35, 0, 1.37), 0.03, paint, 3)
for side in (-1, 1):
    box(f"Headlight_{'L' if side < 0 else 'R'}", (0.06, 0.42, 0.1), (2.18, side * 0.6, 0.78), 0.03, light, 3)
    box(f"Taillight_{'L' if side < 0 else 'R'}", (0.05, 0.5, 0.08), (-2.19, side * 0.58, 0.84), 0.02, tail, 3)

R, W = 0.34, 0.24
for nm, x, y in (("FL", 1.42, 0.84), ("FR", 1.42, -0.84), ("RL", -1.38, 0.84), ("RR", -1.38, -0.84)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=R, depth=W, location=(x, y, R),
                                        rotation=(math.pi / 2, 0, 0))
    t = bpy.context.object
    t.name = f"Wheel_{nm}"
    md = t.modifiers.new("b", "BEVEL")
    md.width = 0.06
    md.segments = 4
    t.data.materials.append(rubber)
    bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=R * 0.62, depth=0.02,
                                        location=(x, y + (0.115 if y > 0 else -0.115), R), rotation=(math.pi / 2, 0, 0))
    rim = bpy.context.object
    rim.name = f"Rim_{nm}"
    rim.data.materials.append(alloy)
    for k in range(5):  # spokes so spinning reads
        a = k * 2 * math.pi / 5
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x + math.cos(a) * R * 0.3, y + (0.128 if y > 0 else -0.128),
                                                          R + math.sin(a) * R * 0.3), rotation=(0, -a, 0))
        sp = bpy.context.object
        sp.scale = (R * 0.6, 0.012, 0.05)
        sp.name = f"Spoke_{nm}_{k}"
        sp.data.materials.append(rubber)
    # join rim + spokes into the rim object (one hub part)
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.data.objects:
        if o.name.startswith(f"Spoke_{nm}_") or o.name == f"Rim_{nm}":
            o.select_set(True)
    bpy.context.view_layer.objects.active = rim
    bpy.ops.object.join()

bpy.ops.export_scene.gltf(filepath=str(out / "testcar.glb"), export_format="GLB", export_apply=True)
for i, o in enumerate(sorted(bpy.data.objects, key=lambda o: o.name)):
    o.name = o.data.name = f"Part_{i:03d}"  # no names at all -> geometry detection only
bpy.ops.export_scene.gltf(filepath=str(out / "testcar_anon.glb"), export_format="GLB", export_apply=True)
print("B2: wrote", out)
