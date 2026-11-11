"""Fixtures for film-layer tests (schema, lint, job builder, assets, runtime integration)."""
from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


@pytest.fixture(scope="session")
def ffmpeg_path() -> str:
    """Path of a usable ffmpeg, or skip the test."""
    from showreel_core.render.errors import RenderError
    from showreel_core.render.ffmpeg import resolve_ffmpeg

    try:
        return resolve_ffmpeg().path
    except RenderError:
        w = shutil.which("ffmpeg")
        if not w:
            pytest.skip("ffmpeg not available")
        return str(w)


@pytest.fixture
def demo(tmp_path: Path):
    """(film, assets, kits_root) for the demo film, generated under tmp_path."""
    from demo_film import make_demo

    return make_demo(tmp_path / "demo")


@pytest.fixture(scope="session")
def render_slot() -> Iterator[None]:
    """Hold a shared render slot when AUTEUR_RENDER_SLOT_DIR is set (dev machines with several agents)."""
    from showreel_core.film.preview import render_slot as slot

    with slot(os.environ.get("AUTEUR_RENDER_SLOT_DIR"), "pytest-film"):
        yield
