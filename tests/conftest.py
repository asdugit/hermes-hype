"""Shared pytest setup: import path for ``showreel_core`` and the opt-in ``slow`` marker.

Slow tests launch Chromium + ffmpeg; run them with ``pytest --runslow`` (or ``-m slow --runslow``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--runslow", action="store_true", default=False, help="run tests marked slow")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: launches a browser and ffmpeg (opt in with --runslow)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="slow: pass --runslow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
