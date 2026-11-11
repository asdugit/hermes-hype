"""Hype dashboard API: ``/api/plugins/hype/*`` for the Desktop pane (SPEC 3.9).

Hermes imports this file on its own (not as part of the plugin package), so the core package and the
pane read models (``pane_data.py`` beside this file) are loaded by path under private module names.
Job state is shared with the plugin's own threads through files in the plugin data dir
(``jobs/<id>/job.json`` plus side files). Handlers never block the event loop: request bodies are
read with a size cap, everything else runs in the thread pool.

Routes
  GET  /health                         {ok, api}: the pane's "is the backend on" probe
  GET  /styles                         styles in roster order + preview availability (small ones inline)
  GET  /customize                      knob vocabulary for preset customization (palettes, moods, fonts, ...)
  GET  /styles/{id}/preview            {kind, mime, url}: one style's looping preview as a data URL
  GET  /jobs?session_id=&limit=        jobs, newest first (log tails only)
  GET  /jobs/active                    running jobs of every session + ones that just finished (status chip)
  GET  /jobs/latest?session_id=        newest job of the session, or {"stage": "none"}
  POST /jobs                           {session_id, options, customize?: {text, knobs}} -> start a film (409 while
                                       one is running; 400 for unknown knobs)
  GET  /jobs/{id}                      one job
  POST /jobs/{id}/cancel               raise the cancel flag
  GET  /jobs/{id}/storyboard           {storyboard, edited}: the pane's edit if saved, else the job's own
  PUT  /jobs/{id}/storyboard           {storyboard} pane edits (used by the next rerender)
  POST /jobs/{id}/rerender             {aspects?, options?} new job from the (edited) storyboard, no LLM call
  POST /jobs/{id}/revise               {notes, options?} new job: same film options + notes (Directed: revise pass)
  GET  /jobs/{id}/thumbs               scene thumbnails + contact sheet as data URLs
  GET  /jobs/{id}/director-log?since=  Director live log from line `since`, treatment, versions, scores, usage
  GET  /jobs/{id}/director/image?v=&name=&w=   one contact sheet / keyframe, downscaled, as a data URL
  GET  /jobs/{id}/director/scene?v=&name=      one custom scene's code (read-only peek)
  GET  /jobs/{id}/post-text            {text}: a ready-to-post caption for the finished film
  GET  /library                        the user's saved scenes/worlds with thumbnails
  GET  /blender                        {found, version, path, message, offer, install}: is Blender there, what an
                                       install would fetch (version, size, url) and the running install's progress
  POST /blender/install                {confirm: true} -> start the user-confirmed Blender install (background
                                       thread; poll GET /blender). Only the pane's Install button sends it.
  POST /blender/install/cancel         stop a running install (nothing is left behind)
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
CORE_NAME = "_hype_dashboard_core"
PANE_NAME = "_hype_pane_data"
API_VERSION = 2
BODY_LIMIT = 512 * 1024
THUMB_LIMIT = 600 * 1024
NOTES_LIMIT = 2000
#: Extra preview folder the integration build fills (``assets/previews/<style>.webp|mp4``); a kit or style
#: pack's own ``preview.*`` wins over it.
PREVIEW_DIRS = (ROOT / "assets" / "previews",)


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


def _pane() -> Any:
    """``pane_data.py`` (read models for the pane), loaded by path like the core."""
    if PANE_NAME in sys.modules:
        return sys.modules[PANE_NAME]
    path = Path(__file__).resolve().parent / "pane_data.py"
    spec = importlib.util.spec_from_file_location(PANE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PANE_NAME] = module
    spec.loader.exec_module(module)
    return module


router = APIRouter()
_CACHES: dict[str, Any] = {}


def _job_cache() -> Any:
    if "jobs" not in _CACHES:
        _CACHES["jobs"] = _pane().JobCache()
    return _CACHES["jobs"]


def _image_cache() -> Any:
    if "images" not in _CACHES:
        _CACHES["images"] = _pane().ImageCache()
    return _CACHES["images"]


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _reply(result: tuple[int, dict[str, Any]]) -> JSONResponse:
    status, payload = result
    return JSONResponse(payload, status_code=status)


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


def _job_or_404(job_id: str) -> tuple[Any, dict[str, Any] | None]:
    store = _store()
    if not _sub("jobs").valid_id(job_id):
        return store, None
    return store, store.load(job_id)


def _directed(job: dict[str, Any]) -> bool:
    return job.get("kind") == "directed" or bool(str((job.get("options") or {}).get("direction") or "").strip())


@router.get("/health")
async def health() -> Any:
    return {"ok": True, "api": API_VERSION}


# --------------------------------------------------------------------------- styles

def _style_dicts() -> list[dict[str, Any]]:
    return [s.to_dict() for s in _sub("config").discover_styles().values()]


@router.get("/styles")
async def get_styles() -> Any:
    def go() -> list[dict[str, Any]]:
        return _pane().style_rows(_style_dicts(), list(PREVIEW_DIRS))
    return {"styles": await run_in_threadpool(go)}


@router.get("/styles/{style_id}/preview")
async def style_preview(style_id: str) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        sid = style_id.strip().lower()
        if not sid.replace("-", "").replace("_", "").isalnum():
            return 404, {"error": "unknown style"}
        declared = next((str(s.get("preview") or "") for s in _style_dicts() if s.get("id") == sid), "")
        payload = _pane().preview_payload(sid, declared, list(PREVIEW_DIRS))
        return (200, payload) if payload else (404, {"error": "no preview for this style yet"})
    return _reply(await run_in_threadpool(go))


# ----------------------------------------------------------------------------- jobs

def _start(session_id: str, options: dict[str, Any], *, parent: str = "", reuse: dict[str, Any] | None = None,
           ) -> tuple[int, dict[str, Any]]:
    cfg, jobs, llm, pipeline = _sub("config"), _sub("jobs"), _sub("llm"), _sub("pipeline")
    store = jobs.JobStore()
    # No ``active_ids`` here: this module's pipeline copy only knows the jobs it started itself, so a film the
    # plugin's own copy runs in this same process (slash command, tool) would look orphaned during a long
    # model call. Dead runner processes and hour-long silence still mark a job stale.
    store.mark_stale()
    busy = store.running(session_id)
    if busy:
        return 409, {"error": "a film is already rendering for this session", "job": jobs.public_view(busy[0])}
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
    if body.get("customize") is not None:            # preset customization: {text, knobs} (docs/CUSTOMIZE.md)
        opts, msgs, status = _sub("customize.command").from_request(opts, body.get("customize"))
        if status != 200:
            return _err(status, " ".join(msgs))
    return _reply(await run_in_threadpool(_start, sid, opts))


@router.get("/customize")
async def customize_vocab() -> Any:
    """What the Make tab's knobs offer: palettes, energies, music moods + beds, fonts, voice styles, ..."""
    def go() -> dict[str, Any]:
        v, k = _sub("customize.vocab"), _sub("customize.knobs")
        return {"knobs": {name: help_ for name, (_kind, help_) in k.KNOBS.items()},
                "palettes": v.PALETTES, "energies": list(v.ENERGIES), "moods": sorted(v.MOODS),
                "beds": sorted(v.beds().values(), key=lambda b: (b["family"], b["id"])),
                "fonts": sorted(r["family"] for r in v.fonts().values()), "voices": list(v.VOICE_STYLES),
                "captions": list(v.CAPTION_STYLES), "transitions": list(v.TRANSITION_FAMILIES),
                "languages": {c: row[1] for c, row in v.LANGUAGES.items()}}
    return await run_in_threadpool(go)


@router.get("/jobs")
async def list_jobs(session_id: str = "", limit: int = 20) -> Any:
    def go() -> list[dict[str, Any]]:
        store, jobs = _store(), _sub("jobs")
        found = _job_cache().jobs(store.jobs_dir, jobs.valid_id, session_id or None, max(1, min(100, limit)))
        return [_view(j) for j in found]
    return {"jobs": await run_in_threadpool(go)}


@router.get("/jobs/active")
async def active_jobs() -> Any:
    def go() -> list[dict[str, Any]]:
        store, jobs = _store(), _sub("jobs")
        return _pane().active_jobs(_job_cache().jobs(store.jobs_dir, jobs.valid_id, None, 40), time.time())
    return {"jobs": await run_in_threadpool(go)}


@router.get("/jobs/latest")
async def latest_job(session_id: str = "") -> Any:
    def go() -> dict[str, Any]:
        job = _store().latest(session_id or None)
        return _view(job) if job else {"stage": "none", "session_id": session_id}
    return await run_in_threadpool(go)


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
    return _reply(await run_in_threadpool(go))


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


@router.get("/jobs/{job_id}/storyboard")
async def get_storyboard(job_id: str) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        edit = store.storyboard_edit(job_id)
        return 200, {"id": job_id, "storyboard": edit or job.get("storyboard"), "edited": edit is not None,
                     "source": job.get("storyboard_source") or ""}
    return _reply(await run_in_threadpool(go))


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
    return _reply(await run_in_threadpool(go))


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
            if _directed(job):
                return 409, {"error": "a Directed film has no storyboard to re-render: use Revise (for example "
                                      "'make a 9:16 version') to direct it again", "directed": True}
            return 409, {"error": "this job has no storyboard to re-render (it never got that far)"}
        opts = dict(job.get("options") or {})
        if isinstance(body.get("options"), dict):
            opts.update(body["options"])
        if body.get("aspects"):
            opts["aspects"] = body["aspects"]
        opts["direction"] = ""          # re-render the storyboard as is: Quick back half, no model call
        return _start(job.get("session_id") or "", opts, parent=job_id, reuse=sb)
    return _reply(await run_in_threadpool(go))


def _aspects_from_notes(notes: str) -> list[str] | None:
    """``['9:16']`` / ``['16:9']`` when revision notes ask for exactly one other shape ("make a 9:16 version",
    "vertical"); None otherwise. A Directed film renders ``aspects[0]`` only, so without this the pane's
    advice ("use Revise: make a 9:16 version") re-made the same 16:9 film."""
    hits = [a for a, rx in _ASPECT_NOTES if rx.search(notes)]
    return [hits[0]] if len(hits) == 1 else None


_ASPECT_NOTES = (("9:16", re.compile(r"\b9\s*[:x/]\s*16\b|\b(?:vertical|portrait)\b", re.I)),
                 ("16:9", re.compile(r"\b16\s*[:x/]\s*9\b|\b(?:horizontal|landscape|widescreen)\b", re.I)))


@router.post("/jobs/{job_id}/revise")
async def revise(job_id: str, request: Request) -> Any:
    body = await _json_body(request)
    if body is None:
        return _err(400, "expected a JSON object body under 512 KB")
    notes = str(body.get("notes") or "").strip()
    if not notes:
        return _err(400, "notes are required: say what should change")
    if len(notes) > NOTES_LIMIT:
        return _err(400, f"notes are limited to {NOTES_LIMIT} characters")

    def go() -> tuple[int, dict[str, Any]]:
        _, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        if job.get("stage") != "done":
            return 409, {"error": "only a finished film can be revised"}
        opts = dict(job.get("options") or {})
        asked = _aspects_from_notes(notes)
        if asked:
            opts["aspects"] = asked
        if isinstance(body.get("options"), dict):
            opts.update({k: v for k, v in body["options"].items() if k not in ("direction", "notes")})
        opts["notes"] = notes
        return _start(job.get("session_id") or "", opts, parent=job_id)
    return _reply(await run_in_threadpool(go))


@router.get("/jobs/{job_id}/thumbs")
async def thumbs(job_id: str) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        _, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        url = _pane().data_url
        urls = [url(p, THUMB_LIMIT) for p in (job.get("thumbs") or [])[:40]]
        sheet = url(job["contact_sheet"], 4 * THUMB_LIMIT) if job.get("contact_sheet") else ""
        return 200, {"thumbs": urls, "contact_sheet": sheet}
    return _reply(await run_in_threadpool(go))


# --------------------------------------------------------------------------- the Director, live

def _score_bar() -> float:
    try:
        return float(_sub("director.types").SCORE_BAR)
    except Exception:  # noqa: BLE001 - the Director package is optional in a build
        return 8.0


@router.get("/jobs/{job_id}/director-log")
async def director_log(job_id: str, since: int = 0, limit: int = 400) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        payload = _pane().director_payload(store.job_dir(job_id), max(0, since), max(1, min(2000, limit)),
                                           _score_bar())
        payload.update(id=job_id, directed=_directed(job), direction=(job.get("options") or {}).get("direction", ""))
        return 200, payload
    return _reply(await run_in_threadpool(go))


@router.get("/jobs/{job_id}/director/image")
async def director_image(job_id: str, v: int = 1, name: str = "", w: int = 960) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        path = _pane().director_image_path(store.job_dir(job_id), v, name)
        if path is None:
            return 404, {"error": "no such image"}
        return 200, dict(_image_cache().get(path, max(160, min(1920, w))), v=v, name=name)
    return _reply(await run_in_threadpool(go))


@router.get("/jobs/{job_id}/director/scene")
async def director_scene(job_id: str, v: int = 1, name: str = "") -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        code = _pane().scene_code(store.job_dir(job_id), v, name)
        return (200, code) if code else (404, {"error": "no such scene"})
    return _reply(await run_in_threadpool(go))


# ------------------------------------------------------------------------- result helpers

@router.get("/jobs/{job_id}/post-text")
async def post_text(job_id: str) -> Any:
    def go() -> tuple[int, dict[str, Any]]:
        store, job = _job_or_404(job_id)
        if job is None:
            return 404, {"error": "not found"}
        sb = store.storyboard_edit(job_id) or job.get("storyboard") or {}
        tagline = str(sb.get("tagline") or "") if isinstance(sb, dict) else ""
        pane = _pane()
        treatment = pane.treatment_summary(store.job_dir(job_id) / "director") or {}
        return 200, {"id": job_id, "text": pane.post_text(job, tagline, treatment.get("logline", ""))}
    return _reply(await run_in_threadpool(go))


# --------------------------------------------------------------------------- Blender (optional 3D engine)

def _blender_state() -> dict[str, Any]:
    bi, loc, cfg = _sub("blender.install"), _sub("blender.locate"), _sub("config")
    found = loc.locate(cfg.settings_from_hermes_config().blender_path or None)
    build = bi.build_for()
    out: dict[str, Any] = {"found": bool(found.ok), "install": bi.status(),
                           "offer": build.to_dict() if build is not None else None}
    if found.ok:
        out.update(version=found.version_string, path=str(found.path), source=found.source)
    else:
        out.update(message=found.message, reason=found.reason)
    return out


@router.get("/blender")
async def blender_status() -> Any:
    return await run_in_threadpool(_blender_state)


@router.post("/blender/install")
async def blender_install(request: Request) -> Any:
    body = await _json_body(request)
    if body is None or body.get("confirm") is not True:
        return _err(400, "send {\"confirm\": true}: the install starts only after the user agreed")

    def go() -> tuple[int, dict[str, Any]]:
        state = _blender_state()
        if state["found"]:
            return 200, state
        if state["offer"] is None:
            return 409, dict(state, error="Blender publishes no build for this machine")
        _sub("blender.install").start_background()
        return 202, _blender_state()
    return _reply(await run_in_threadpool(go))


@router.post("/blender/install/cancel")
async def blender_install_cancel() -> Any:
    def go() -> dict[str, Any]:
        return {"cancelled": bool(_sub("blender.install").cancel_background()), **_blender_state()}
    return await run_in_threadpool(go)


@router.get("/library")
async def library() -> Any:
    def go() -> dict[str, Any]:
        lib = _sub("jobs").data_root() / "library"
        return {"dir": str(lib), "items": _pane().library_items(lib)}
    return await run_in_threadpool(go)
