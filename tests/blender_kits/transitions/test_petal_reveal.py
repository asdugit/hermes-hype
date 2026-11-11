"""Pure-Python tests for transitions/petal_reveal (no Blender): params schema, cue timing, under-scene cue merge."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from blender_kits.transitions import petal_reveal as pr  # noqa: E402


def _sc(**params):
    return SimpleNamespace(params=params, fps=30, frames=54, aspect="16:9", seed=7, t_start=0.0,
                           kit_root=str(ROOT / "blender_kits"))


def test_params_schema():
    for k in ("under", "under_params", "origin", "spread", "start", "cell_px", "from_shot"):
        assert k in pr.PARAMS and "default" in pr.PARAMS[k] and pr.PARAMS[k].get("doc")


def test_petal_burst_cue_at_start():
    cues = pr.cues(_sc(start=0.2, under_params={"crowd": 0.3}))
    assert cues[0] == {"t": 0.2, "sfx": "petal_burst", "gain_db": -2.0}
    assert all(c["sfx"] != "chime" for c in cues)          # the under scene's hero chime belongs to the oner shot
    assert cues == sorted(cues, key=lambda c: c["t"])


def test_params_restored_after_cues():
    sc = _sc(start=0.1)
    pr.cues(sc)
    assert sc.params == {"start": 0.1}
