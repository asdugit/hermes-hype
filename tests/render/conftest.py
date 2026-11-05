"""Fixtures for the renderer tests."""
from __future__ import annotations

import shutil

import pytest

from showreel_core.render.errors import RenderError
from showreel_core.render.ffmpeg import resolve_ffmpeg


@pytest.fixture(scope="session")
def ffmpeg_path() -> str:
    """Path of a usable ffmpeg, or skip the test."""
    try:
        return resolve_ffmpeg().path
    except RenderError:
        w = shutil.which("ffmpeg")
        if not w:
            pytest.skip("ffmpeg not available")
        return str(w)
