"""Runtime pure modules (rand, noise, ease, motion, film timeline, frame math) checked under Node, if installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _results() -> dict[str, object]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    p = subprocess.run([node, str(HERE / "pure.test.mjs")], capture_output=True, text=True, encoding="utf-8",
                       timeout=60, check=False)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_runtime_pure_modules():
    res = _results()
    failures = {k: v for k, v in res.items() if v is not True}
    assert len(res) >= 18
    assert failures == {}
