"""Blender host engine: locate the user's Blender, run ``blender:`` shots headlessly, feed frames to the film.

Modules (see BLENDER.md):

* ``locate``: ``locate(config_path)`` -> ``BlenderFound | BlenderMissing`` (user-facing message, never raises)
* ``runner``: ``make_job`` / ``run_job`` / ``benchmark`` (job.json protocol v1, SR_* progress, verify, resume)
* ``film``: ``render_film_shots`` (Blender pass of a film.json); ``render_film``: the CLI
  ``python -m showreel_core.blender.render_film FILM.json --out OUT.mp4``
* ``trigger``: ``blender_requested(text)`` ("use blender" in a direction)

Nothing is re-exported here on purpose: ``from showreel_core.blender import locate`` must stay the module.
"""
