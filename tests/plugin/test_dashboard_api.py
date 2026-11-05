"""dashboard/plugin_api.py routes (FastAPI TestClient; the core is loaded by path like Hermes does)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def _load_api() -> Any:
    name = "showreel_plugin_api_under_test"
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
    monkeypatch.setenv("SHOWREEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SHOWREEL_VIDEOS_DIR", str(tmp_path / "videos"))
    mod = _load_api()
    pipeline = mod._sub("pipeline")
    started: list[str] = []
    monkeypatch.setattr(pipeline, "start_background", lambda job_id, host, **kw: started.append(job_id))
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/showreel")
    return {"client": TestClient(app), "mod": mod, "started": started, "store": mod._sub("jobs").JobStore()}


P = "/api/plugins/showreel"


def test_core_is_loaded_by_path_under_a_private_name(api: dict[str, Any]) -> None:
    core = api["mod"]._load_core()
    assert core.__name__ == "_showreel_dashboard_core"
    assert Path(core.__file__).resolve() == (ROOT / "showreel_core" / "__init__.py").resolve()


def test_styles(api: dict[str, Any]) -> None:
    r = api["client"].get(f"{P}/styles")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["styles"]]
    assert "launch" in ids and all("preview_url" in s for s in r.json()["styles"])


def test_create_job_then_latest_get_cancel(api: dict[str, Any]) -> None:
    c = api["client"]
    r = c.post(f"{P}/jobs", json={"session_id": "s1", "options": {"style": "pixel", "seconds": 30,
                                                                    "aspects": ["9:16"]}})
    assert r.status_code == 200, r.text
    job = r.json()
    assert api["started"] == [job["id"]] and job["stage"] == "queued" and job["surface"] == "desktop"
    assert job["options"]["style"] == "pixel" and job["options"]["aspects"] == ["9:16"]
    assert c.post(f"{P}/jobs", json={"session_id": "s1"}).status_code == 409        # one at a time per session
    assert c.get(f"{P}/jobs/latest", params={"session_id": "s1"}).json()["id"] == job["id"]
    assert c.get(f"{P}/jobs/latest", params={"session_id": "other"}).json() == {"stage": "none",
                                                                                "session_id": "other"}
    assert c.get(f"{P}/jobs/{job['id']}").json()["id"] == job["id"]
    assert c.get(f"{P}/jobs", params={"session_id": "s1"}).json()["jobs"][0]["id"] == job["id"]
    assert c.post(f"{P}/jobs/{job['id']}/cancel").json() == {"ok": True, "id": job["id"]}
    assert api["store"].cancel_requested(job["id"])


def test_bad_requests(api: dict[str, Any]) -> None:
    c = api["client"]
    assert c.post(f"{P}/jobs", json={}).status_code == 400
    assert c.post(f"{P}/jobs", content=b"not json", headers={"content-type": "application/json"}).status_code == 400
    assert c.post(f"{P}/jobs", content=b"x" * (600 * 1024)).status_code == 400
    assert c.get(f"{P}/jobs/..%2F..%2Fetc").status_code == 404
    assert c.get(f"{P}/jobs/20200101-000000-dead").status_code == 404
    assert c.post(f"{P}/jobs/20200101-000000-dead/cancel").status_code == 404


def test_storyboard_edit_and_rerender_without_llm(api: dict[str, Any]) -> None:
    c, store = api["client"], api["store"]
    job = store.create("s1", {"style": "launch", "seconds": 30})
    store.update(job["id"], stage="done", storyboard={"title": "T", "scenes": [{"type": "TITLE", "refs": [], "vo": "x"}]})
    assert c.put(f"{P}/jobs/{job['id']}/storyboard", json={"storyboard": {"scenes": "nope"}}).status_code == 400
    assert c.put(f"{P}/jobs/{job['id']}/storyboard", json={"storyboard": {"scenes": [{"refs": []}]}}).status_code == 400
    edit = {"title": "T2", "scenes": [{"type": "TITLE", "refs": [], "vo": "edited"}]}
    assert c.put(f"{P}/jobs/{job['id']}/storyboard", json={"storyboard": edit}).json()["ok"]
    r = c.post(f"{P}/jobs/{job['id']}/rerender", json={"aspects": ["9:16"]})
    assert r.status_code == 200, r.text
    child = store.load(r.json()["id"])
    assert child["parent"] == job["id"] and child["options"]["aspects"] == ["9:16"]
    assert child["reuse_storyboard"] == edit and child["options"]["direction"] == ""
    assert api["started"][-1] == child["id"]


def test_rerender_needs_a_storyboard(api: dict[str, Any]) -> None:
    store = api["store"]
    job = store.create("s1", {})
    store.update(job["id"], stage="failed")
    assert api["client"].post(f"{P}/jobs/{job['id']}/rerender", json={}).status_code == 409


def test_thumbs_are_data_urls(api: dict[str, Any], tmp_path: Path) -> None:
    store = api["store"]
    job = store.create("s1", {})
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8\xff fake jpeg")
    sheet = tmp_path / "c.png"
    sheet.write_bytes(b"\x89PNG fake")
    store.update(job["id"], thumbs=[str(thumb), str(tmp_path / "missing.jpg")], contact_sheet=str(sheet))
    out = api["client"].get(f"{P}/jobs/{job['id']}/thumbs").json()
    assert out["thumbs"][0].startswith("data:image/jpeg;base64,") and out["thumbs"][1] == ""
    assert out["contact_sheet"].startswith("data:image/png;base64,")
