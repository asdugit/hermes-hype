"""Blender host engine: locate the user's Blender, run ``blender:`` shots headlessly, feed frames to the film.

Public API (see BLENDER.md):

* :func:`locate.locate` -> ``BlenderFound | BlenderMissing``
* :func:`runner.make_job` / :func:`runner.run_job` / :func:`runner.benchmark` (job.json protocol v1)
* :func:`film.render_film_shots` (Blender pass of a film.json) and ``python -m showreel_core.blender.render_film``
"""
from __future__ import annotations

from .locate import BlenderFound, BlenderMissing, locate

__all__ = ["BlenderFound", "BlenderMissing", "locate"]
