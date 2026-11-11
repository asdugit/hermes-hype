"""kits/launch: the product becomes the hero after the headline reads (handoff timing, camera blend, feature copy)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def test_launch_handoff_helpers() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    p = subprocess.run([node, str(HERE / "launch_handoff.test.mjs")], capture_output=True, text=True,
                       encoding="utf-8", timeout=60, check=False)
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout.strip().splitlines()[-1])
    assert len(res) >= 5
    assert {k: v for k, v in res.items() if v is not True} == {}


def test_launch_media_scenes_use_the_handoff_and_story_labels() -> None:
    """FEATURE/HOOK hand the frame to the product; SCREEN/TERMINAL/MONTAGE/CODE/DIFF show the story label."""
    kit = HERE.parents[1] / "kits" / "launch"
    media = (kit / "scenes-media.js").read_text(encoding="utf-8")
    panels = (kit / "scenes-panels.js").read_text(encoding="utf-8")
    assert media.count("handoff(F, dur") >= 2 and "featureCopy(p.feature, p.label)" in media
    assert media.count("cornerLabel(F, p.label") >= 2          # SCREEN + MONTAGE
    assert panels.count("cornerLabel(F, p.label") >= 3         # CODE, DIFF, TERMINAL
