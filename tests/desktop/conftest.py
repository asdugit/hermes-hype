"""Shared fixtures for the Desktop pane tests: the dashboard API under a TestClient with a temp data dir."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
P = "/api/plugins/hype"


def load_api() -> Any:
    """``dashboard/plugin_api.py`` imported standalone, the way Hermes imports it."""
    name = "hype_plugin_api_desktop_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "dashboard" / "plugin_api.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("HYPE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HYPE_VIDEOS_DIR", str(tmp_path / "videos"))
    mod = load_api()
    previews = tmp_path / "previews"
    previews.mkdir()
    monkeypatch.setattr(mod, "PREVIEW_DIRS", (previews,))
    pipeline = mod._sub("pipeline")
    started: list[str] = []
    monkeypatch.setattr(pipeline, "start_background", lambda job_id, host, **kw: started.append(job_id))
    app = FastAPI()
    app.include_router(mod.router, prefix=P)
    return {"client": TestClient(app), "mod": mod, "started": started, "store": mod._sub("jobs").JobStore(),
            "previews": previews, "data": tmp_path / "data", "tmp": tmp_path}


def jpeg(path: Path, size: tuple[int, int] = (1600, 900)) -> Path:
    """A real JPEG (Pillow) so downscaling is exercised."""
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 90, 160)).save(path, "JPEG", quality=80)
    return path


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
