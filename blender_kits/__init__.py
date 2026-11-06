"""Showreel Blender kits: scene modules + shared library that run INSIDE Blender's Python (see BLENDER.md).

Never imported by the host (showreel_core); ``blender_kits/lib/entry.py`` registers this package from its own
path inside Blender. Scene modules live at ``blender_kits/<kit>/<scene>.py`` and are addressed in film.json as
``"scene": "blender:<kit>/<scene>"``.
"""
