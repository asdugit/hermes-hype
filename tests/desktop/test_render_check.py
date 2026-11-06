"""Runs render_check.mjs (desktop/plugin.js in jsdom with the real React + React Query) when it can.

Needs node and the test dependencies: ``cd tests/desktop && npm install`` (react, react-dom, jsdom and
@tanstack/react-query, pinned to the versions Hermes Desktop ships). Skipped otherwise.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def test_render_check() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    if not (HERE / "node_modules" / "react-dom").is_dir() or not (HERE / "node_modules" / "jsdom").is_dir():
        pytest.skip("run `npm install` in tests/desktop first")
    assert node is not None
    r = subprocess.run([node, str(HERE / "render_check.mjs")], cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    failed = [line for line in r.stdout.splitlines() if line.startswith("FAIL")]
    assert r.returncode == 0 and not failed, "\n".join(failed) + "\n" + r.stdout[-3000:] + r.stderr[-3000:]
    assert r.stdout.count("PASS") >= 40
