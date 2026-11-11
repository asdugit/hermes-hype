"""Director test fixtures (fakes live in director_fakes.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from director_fakes import env  # noqa: F401  (pytest fixture)


@pytest.fixture(autouse=True)
def _no_host_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the machine's Hermes config for the model id (CI and dev hosts differ)."""
    from showreel_core.director import tiers
    monkeypatch.setattr(tiers, "host_model", lambda: "")
