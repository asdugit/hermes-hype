"""Showreel dashboard API: ``/api/plugins/showreel/*`` for the Desktop pane (SPEC 3.9).

Hermes imports this file on its own (not as part of the plugin package), so the core package is
loaded by path under a private module name. Job state is shared with the plugin's own threads through
files in the plugin data dir (``jobs/<id>/job.json``). Handlers never block the event loop: request
bodies are read with a size cap, everything else runs in the thread pool.

Routes
  GET  /styles                      styles + small preview data URLs
  GET  /jobs?session_id=            jobs, newest first (log tails only)
  POST /jobs                        {session_id, options} -> start a film
  GET  /jobs/latest?session_id=     newest job of the session, or {"stage": "none"}
  GET  /jobs/{id}                   one job
  POST /jobs/{id}/cancel            raise the cancel flag
  PUT  /jobs/{id}/storyboard        {storyboard} pane edits (used by the next rerender)
  POST /jobs/{id}/rerender          {aspects?, options?} new job from the (edited) storyboard, no LLM call
  GET  /jobs/{id}/thumbs            scene thumbnails + contact sheet as data URLs
"""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
CORE_NAME = "_showreel_dashboard_core"
BODY_LIMIT = 512 * 1024
THUMB_LIMIT = 600 * 1024
PREVIEW_LIMIT = 400 * 1024
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def _load_core() -> Any:
    """Import ``showreel_core`` from this plugin's folder under a private name (relative imports work)."""
    if CORE_NAME in sys.modules:
        return sys.modules[CORE_NAME]
    init = ROOT / "showreel_core" / "__init__.py"
    spec = importlib.util.spec_from_file_location(CORE_NAME, init, submodule_search_locations=[str(init.parent)])
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {init}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[CORE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _sub(name: str) -> Any:
    _load_core()
    return importlib.import_module(f"{CORE_NAME}.{name}")


router = APIRouter()


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _data_url(path: str | Path, limit: int) -> str:
    p = Path(path)
    mime = MIME.get(p.suffix.lower())
    try:
        if not mime or not p.is_file() or p.stat().st_size > limit:
            return ""
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return ""


async def _json_body(request: Request) -> dict[str, Any] | None:
    """The JSON object body, or None when missing, too big (> BODY_LIMIT) or not an object."""
    stated = request.headers.get("content-length")
    if stated is not None and (not stated.isdigit() or int(stated) > BODY_LIMIT):
        return None
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > BODY_LIMIT:
            return None
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _store() -> Any:
    return _sub("jobs").JobStore()


def _view(job: dict[str, Any]) -> dict[str, Any]:
    return _sub("jobs").public_view(job)


# --------------------------------------------------------------------------- styles

def _styles() -> list[dict[str, Any]]:
    cfg = _sub("config")
    out = []
    for s in cfg.discover_styles().values():
        d = s.to_dict()
        d["preview_url"] = _data_url(s.preview, PREVIEW_LIMIT) if s.preview else ""
        d.pop("preview", None)
        out.append(d)
    return sorted(out, key=lambda d: (not d["ready"], d["id"]))


@router.get("/styles")
async def get_styles() -> Any:
    return {"styles": await run_in_threadpool(_styles)}


# ----------------------------------------------------------------------------- jobs

def _start(session_id: str, options: dict[str, Any], *, parent: str = "", reuse: dict[str, Any] | None = None,
           ) -> tuple[int, dict[str, Any]]:
    cfg, jobs, llm, pipeline = _sub("config"), _sub("jobs"), _sub("llm"), _sub("pipeline")
    store = jobs.JobStore()
    store.mark_stale(active_ids=set(pipeline.running_ids()))
    busy = store.running(session_id)
    if busy:
        return 409, {"error": "a showreel is already rendering for this session", "job": jobs.public_view(busy[0])}
    base = cfg.settings_from_hermes_config().options().to_dict()
    opts = cfg.Options.from_dict({**base, **(options or {})})
    job = store.create(session_id, opts.to_dict(), kind="directed" if opts.directed else "quick", surface="desktop",
                       parent=parent)
    if reuse:
        store.update(job["id"], reuse_storyboard=reuse)
    pipeline.start_background(job["id"], llm.standalone_host(), store=store)
    return 200, jobs.public_view(store.load(job["id"]) or job)


@router.post("/jobs")
async def post_job(request: Request) -> Any:
    body = await _json_body(request)
    if body is None:
        return _err(400, "expected a JSON object body under 512 KB")
    sid = str(body.get("session_id") or "").strip()
    if not sid:
        return _err(400, "session_id is required")
    raw = body.get("options")
    opts: dict[str, Any] = raw if isinstance(raw, dict) else {}
    status, payload = await run_in_threadpool(_start, sid, opts)
    return JSONResponse(payload, status_code=status)


@router.get("/jobs")
async def list_jobs(session_id: str = "", limit: int = 20) -> Any:
    def go() -> list[dict[str, Any]]:
        return [_view(j) for j in _store().list(session_id or None, limit=max(1, min(100, limit)))]
    return {"jobs": await run_in_threadpool(go)}


@router.get("/jobs/latest")
async def latest_job(session_id: str = "") -> Any:
    def go() -> dict[str, Any]:
        job = _store().latest(session_id or None)
        return _view(job) if job else {"stage": "none", "session_id": session_id}
    return await run_in_threadpool(go)


def _job_or_404(job_id: str) -> tuple[Any, dict[str, Any] | None]:
    store = _store()
    jobs = _sub("jobs")
    if not jobs.valid_id(job_id):
        return store, None
    return store, store.load(job_id)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Any:
    _, job = await run_in_threadpool(_job_or_404, job_id)
    return _view(job) if job else _err(404, "not found")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        ok = store.request_cancel(job_id)
        pipeline = _sub("pipeline")
        with pipeline._RUNNING_GUARD:
            tok = pipeline._RUNNING.get(job_id)
        if tok is not None:
            tok.set()
        return 200, {"ok": ok, "id": job_id}
    status, payload = await run_in_threadpool(go)
    return JSONResponse(payload, status_code=status)


def _check_storyboard(sb: Any) -> str:
    """'' when the edited storyboard has the right shape (the pipeline validates the rest)."""
    if not isinstance(sb, dict):
        return "storyboard must be an object"
    scenes = sb.get("scenes")
    if not isinstance(scenes, list) or not scenes or len(scenes) > 60:
        return "storyboard.scenes must be a list of 1-60 scenes"
    for k, s in enumerate(scenes):
        if not isinstance(s, dict) or not isinstance(s.get("type"), str):
            return f"scene {k} needs a type"
        if not isinstance(s.get("refs", []), list) or not isinstance(s.get("vo", ""), str):
            return f"scene {k}: refs must be a list and vo a string"
    return ""


@router.put("/jobs/{job_id}/storyboard")
async def put_storyboard(job_id: str, request: Request) -> Any:
    body = await _json_body(request)
    if body is None:
        return _err(400, "expected a JSON object body under 512 KB")
    sb = body.get("storyboard", body)
    problem = _check_storyboard(sb)
    if problem:
        return _err(400, problem)

    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        path = store.save_storyboard_edit(job_id, sb)
        return 200, {"ok": True, "path": str(path)}
    status, payload = await run_in_threadpool(go)
    return JSONResponse(payload, status_code=status)


@router.post("/jobs/{job_id}/rerender")
async def rerender(job_id: str, request: Request) -> Any:
    body = await _json_body(request)
    if body is None:
        return _err(400, "expected a JSON object body under 512 KB")

    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        sb = store.storyboard_edit(job_id) or job.get("storyboard")
        if not sb:
            return 409, {"error": "this job has no storyboard to re-render (it never got that far)"}
        opts = dict(job.get("options") or {})
        if isinstance(body.get("options"), dict):
            opts.update(body["options"])
        if body.get("aspects"):
            opts["aspects"] = body["aspects"]
        opts["direction"] = ""          # re-render the storyboard as is: Quick back half, no model call
        return _start(job.get("session_id") or "", opts, parent=job_id, reuse=sb)
    status, payload = await run_in_threadpool(go)
    return JSONResponse(payload, status_code=status)


@router.get("/jobs/{job_id}/thumbs")
async def thumbs(job_id: str) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        _, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        urls = [_data_url(p, THUMB_LIMIT) for p in (job.get("thumbs") or [])[:40]]
        sheet = _data_url(job["contact_sheet"], 4 * THUMB_LIMIT) if job.get("contact_sheet") else ""
        return 200, {"thumbs": urls, "contact_sheet": sheet}
    status, payload = await run_in_threadpool(go)
    return JSONResponse(payload, status_code=status)
