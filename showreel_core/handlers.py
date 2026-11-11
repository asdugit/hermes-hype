"""Hermes-facing handlers: the ``/auteur`` command, the agent tools, the CLI and unload.

Imported by ``register()``; it only pulls in light stdlib modules at import time. The pipeline,
session reader, renderer and audio stack are imported when a film is actually made.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .blender.trigger import blender_requested
from .commands import HELP, Command, describe, parse, styles_text
from .config import (
    MAX_SECONDS,
    MIN_SECONDS,
    Options,
    Settings,
    discover_styles,
    load_settings,
    norm_aspects,
    norm_mode,
    style_ids,
)
from .jobs import TERMINAL, JobStore, public_view
from .customize import command as _cz  # W5 preset customization: knobs + text (docs/CUSTOMIZE.md)

log = logging.getLogger(__name__)

#: Surfaces whose slash-command RPC must answer within ~30 s: render in the background there.
BACKGROUND_SURFACES = frozenset({"desktop", "tui", "acp"})
TOOL_WAIT_S = 270.0                 # the tool deadline is 420 s; keep a margin for delivery and the reply
TOOL_WAIT_MAX_S = 330.0

RENDER_SCHEMA: dict[str, Any] = {
    "name": "auteur_render",
    "description": (
        "Make a finished, narrated promo video of what was built in this session (a launch trailer for the "
        "product, with real code, terminal output, screenshots and stats from the session as proof). Use it when "
        "the user asks for a video, trailer, demo reel or showreel of the work. Presets: mode x style (7 styles). "
        "To change a preset use customize/knobs; for a film unlike any preset use direction (the Director). "
        "Returns JSON with media_tag (MEDIA:<path>) when the film is ready; long renders return status "
        "'rendering' and a job_id for auteur_status. Runs locally (Chromium + ffmpeg); a 30-60 s preset takes "
        "2-8 minutes, a Directed film 5-30."),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["product", "lore", "speedrun"],
                     "description": "product = launch trailer (default); lore = making-of story; "
                                    "speedrun = the build as a speedrun with split timer."},
            "style": {"type": "string",
                      "description": "Preset look: launch (default), cinematic, pixel, terminal, blueprint, comic, "
                                     "ink. auteur_status styles=true lists what this build has."},
            "seconds": {"type": "integer", "minimum": MIN_SECONDS, "maximum": MAX_SECONDS,
                        "description": "Target length in seconds (30, 60 or 90 work best)."},
            "aspect": {"type": "string", "enum": ["16:9", "9:16", "both", "1:1"],
                       "description": "16:9 (default), 9:16 vertical, or both."},
            "voice": {"type": "boolean", "description": "Narrate with Hermes TTS (default true); false = captions only."},
            "direction": {"type": "string",
                          "description": "Optional free-text creative direction (\"pixel art that blooms into an "
                                         "anime flower field, sell the product\"). Makes a Directed film; a "
                                         "style given too seeds it."},
            "product": {
                "type": "object",
                "description": "Optional product brief when the session alone does not say what was built.",
                "properties": {
                    "name": {"type": "string"},
                    "one_liner": {"type": "string", "description": "What it does, <= 90 characters."},
                    "url": {"type": "string", "description": "A running local URL (start the app first) or a "
                                                              "public URL that appeared in this session."},
                    "features": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "kind": {"type": "string", "description": "web_app, cli, library, api, game, doc, media..."},
                },
            },
            "preview": {"type": "boolean", "description": "Fast 540p preview instead of the 1080p final."},
            "engine_3d": {"type": "string", "enum": ["browser", "blender", "auto"],
                          "description": "3D shots: browser (default, three.js, no install), blender (the "
                                         "user's installed Blender: 3D device/product shots, nicer, much slower; "
                                         "set when the user asks for Blender) or auto (Blender when installed)."},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": int(TOOL_WAIT_MAX_S),
                             "description": "How long to wait for the film before returning a job id "
                                            f"(default {int(TOOL_WAIT_S)})."},
        },
        "additionalProperties": False,
    },
}

_cz.extend_schema(RENDER_SCHEMA)  # adds `customize` (free text) + `knobs` (W5)

STATUS_SCHEMA: dict[str, Any] = {
    "name": "auteur_status",
    "description": ("Check an Auteur film job: stage, progress, ETA, and media_tag (MEDIA:<path>) once it is done. "
                    "Without job_id it reports this session's latest film. styles=true lists the 7 styles (launch, "
                    "cinematic, pixel, terminal, blueprint, comic, ink) with their blurbs."),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Job id from auteur_render (optional)."},
            "styles": {"type": "boolean", "description": "Also list the available styles."},
        },
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------- helpers

def _settings(ctx: Any) -> Settings:
    get = getattr(ctx, "get_config", None)
    return load_settings(get if callable(get) else None)


def _surface(ctx: Any, platform: str = "") -> str:
    try:
        surface = str(ctx.session_surface() or "")
    except Exception:  # noqa: BLE001 - older hosts / isolation
        surface = ""
    return (surface or platform or "").lower()


def _post(ctx: Any, text: str) -> Any:
    try:
        return ctx.post_message(text)
    except Exception:  # noqa: BLE001 - post_message is optional (isolation: host)
        return None


def _store() -> JobStore:
    store = JobStore()
    try:
        from .pipeline import running_ids
        store.mark_stale(active_ids=set(running_ids()))
    except Exception as exc:  # noqa: BLE001
        log.debug("auteur stale-job sweep failed: %s", exc)
    return store


def _host(ctx: Any, surface: str) -> Any:
    from .llm import host_from_ctx
    return host_from_ctx(ctx, surface=surface)


def _media(job: dict[str, Any]) -> dict[str, str]:
    files = job.get("delivered") or job.get("outputs") or {}
    return {a: str(p) for a, p in files.items() if p}


def _cancel_job(job_id: str, store: JobStore) -> bool:
    from .pipeline import _RUNNING, _RUNNING_GUARD
    ok = store.request_cancel(job_id)
    with _RUNNING_GUARD:
        tok = _RUNNING.get(job_id)
    if tok is not None:
        tok.set()
        ok = True
    return ok


# ------------------------------------------------------------------------- slash command

def make_slash_handler(ctx: Any) -> Any:
    """The ``/auteur`` handler (sync; gets ``session_id``/``platform`` through ``**kwargs``)."""
    def auteur(raw_args: str = "", **kwargs: Any) -> str:
        try:
            return slash(ctx, raw_args, **kwargs)
        except Exception as exc:
            log.exception("auteur command failed")
            return f"🎬 Auteur hit an internal error: {type(exc).__name__}: {exc}"
    return auteur


def slash(ctx: Any, raw_args: str = "", *, session_id: str = "", platform: str = "", **_: Any) -> str:
    """Handle one ``/auteur`` invocation and return the reply text."""
    settings = _settings(ctx)
    cmd = parse(raw_args, styles=style_ids(), base=settings.options())
    prefix = "".join(f"{m}\n" for m in cmd.messages)
    if cmd.action == "help":
        return HELP
    if cmd.action == "styles":
        return styles_text(discover_styles())
    store = _store()
    if cmd.action == "status":
        return prefix + _status_text(store, cmd.job_ref, session_id)
    if cmd.action == "cancel":
        return prefix + _cancel_text(store, cmd.job_ref, session_id)
    if not session_id:
        return "🎬 Nothing to film yet: chat with Hermes first (build something), then run /auteur."
    busy = [j for j in store.running(session_id) if j.get("stage") not in TERMINAL]
    if busy:
        from .deliver import progress_text
        return (f"🎬 A film is already in progress ({busy[0]['id']}):\n{progress_text(busy[0])}\n"
                "Use /auteur status or /auteur cancel.")
    opts, parent = cmd.options, ""
    if cmd.action == "revise":
        last = next((j for j in store.list(session_id) if j.get("stage") == "done"), None)
        if last is None:
            return prefix + "🎬 There is no finished film in this session to revise yet. Run /auteur first."
        notes = opts.notes
        opts = Options.from_dict(last.get("options"))
        opts.notes = notes
        parent = last["id"]
    surface = _surface(ctx, platform)
    return prefix + start_film(ctx, store, session_id, opts, surface=surface, parent=parent)


def start_film(ctx: Any, store: JobStore, session_id: str, opts: Options, *, surface: str, parent: str = "") -> str:
    """Create the job and run it: background on Desktop/TUI/ACP, blocking (then MEDIA lines) elsewhere."""
    from .deliver import done_text, failed_text
    from .pipeline import run_job, start_background
    job = store.create(session_id, opts.to_dict(), kind="directed" if opts.directed else "quick", surface=surface,
                       parent=parent)
    handle = _post(ctx, f"🎬 Auteur {job['id']}: starting · {describe(opts)}")
    host = _host(ctx, surface)
    if surface in BACKGROUND_SURFACES:
        start_background(job["id"], host, store=store, handle=handle)
        where = "the Auteur pane" if surface == "desktop" else "the status line"
        return (f"🎬 Making your film ({describe(opts)}). Progress shows in {where}; "
                f"/auteur status any time, /auteur cancel to stop. Job {job['id']}.")
    final = run_job(job["id"], host, store=store, handle=handle)
    if final.get("stage") == "done":
        return done_text(final, media=True)
    if final.get("stage") == "cancelled":
        return f"🎬 Auteur {job['id']} cancelled."
    return failed_text(final)


def _status_text(store: JobStore, ref: str, session_id: str) -> str:
    from .deliver import done_text, progress_text
    job = store.find(ref, session_id or None)
    if job is None:
        return "🎬 No film yet in this session. Run /auteur to make one."
    text = done_text(job, media=False) if job.get("stage") == "done" else progress_text(job)
    return f"{text}\n  job {job['id']} · {describe(Options.from_dict(job.get('options')))}"


def _cancel_text(store: JobStore, ref: str, session_id: str) -> str:
    targets = [store.find(ref, session_id or None)] if ref else store.running(session_id or None)
    targets = [j for j in targets if j and j.get("stage") not in TERMINAL]
    if not targets:
        return "🎬 Nothing to cancel: no film is rendering."
    done = [j["id"] for j in targets if _cancel_job(j["id"], store)]
    return f"🎬 Cancelling {', '.join(done)}…" if done else "🎬 Could not cancel (already finished?)."


# --------------------------------------------------------------------------------- tools

def _tool_options(ctx: Any, args: dict[str, Any]) -> Options:
    opts = _settings(ctx).options()
    if args.get("mode"):
        opts.mode = norm_mode(args["mode"])
    if args.get("style"):
        opts.style = str(args["style"]).strip().lower()
    if args.get("seconds"):
        opts.seconds = args["seconds"]
    if args.get("aspect"):
        opts.aspects = norm_aspects(args["aspect"])
    if isinstance(args.get("voice"), bool):
        opts.voice = args["voice"]
    if isinstance(args.get("preview"), bool):
        opts.preview = args["preview"]
    if args.get("direction"):
        opts.direction = str(args["direction"])
        wants = blender_requested(opts.direction)
        if wants is not None and not args.get("engine_3d"):
            opts.engine_3d = "blender" if wants else "browser"
    if args.get("engine_3d"):
        opts.engine_3d = str(args["engine_3d"])
    if isinstance(args.get("product"), dict):
        opts.brief = {k: v for k, v in args["product"].items() if v}
    opts = _cz.from_tool_args(opts, args)  # W5 preset customization
    return opts.normalised()


def _result(job: dict[str, Any], **extra: Any) -> dict[str, Any]:
    media = _media(job)
    first = next(iter(media.values()), "")
    out: dict[str, Any] = {"success": job.get("stage") not in ("failed", "cancelled"), "job_id": job.get("id"),
                           "status": job.get("stage"), "pct": job.get("pct"), "eta_s": job.get("eta_s"),
                           "title": job.get("title"), "duration_s": job.get("duration_s")}
    if job.get("stage") == "done" and first:
        out.update(file_path=first, media_tag=f"MEDIA:{first}", outputs=media,
                   storyboard_source=job.get("storyboard_source"), contact_sheet=job.get("contact_sheet"))
    if job.get("error"):
        out["error"] = job["error"]
    if job.get("warnings"):
        out["warnings"] = list(job["warnings"])[:6]
    out.update(extra)
    return out


def render_tool(ctx: Any, args: dict[str, Any] | None, **kwargs: Any) -> str:
    """``auteur_render`` handler: start a film, wait up to the budget, return JSON (never raises)."""
    try:
        args = args if isinstance(args, dict) else {}
        session_id = str(kwargs.get("session_id") or "")
        if not session_id:
            return json.dumps({"success": False, "error": "auteur_render needs a session (none was given)."})
        store = _store()
        busy = store.running(session_id)
        if busy:
            return json.dumps(_result(busy[0], success=False,
                                      error="A film is already rendering for this session; use auteur_status."))
        opts = _tool_options(ctx, args)
        job = store.create(session_id, opts.to_dict(), kind="directed" if opts.directed else "quick",
                           surface="tool")
        done = threading.Event()
        from .pipeline import start_background
        handle = _post(ctx, f"🎬 Auteur {job['id']}: starting · {describe(opts)}")
        start_background(job["id"], _host(ctx, "tool"), store=store, handle=handle, on_done=lambda _f: done.set())
        try:
            wait = float(args.get("wait_seconds", TOOL_WAIT_S))
        except (TypeError, ValueError):
            wait = TOOL_WAIT_S
        wait = max(0.0, min(TOOL_WAIT_MAX_S, wait))
        done.wait(wait)
        final = store.load(job["id"]) or job
        if final.get("stage") not in TERMINAL and wait > 0 and (
                final.get("stage") in ("mix", "qa") or float(final.get("pct") or 0) >= 0.9):
            # Nearly there (real E2E: QA ended 3 s after the 270 s budget): use the rest of the tool budget.
            done.wait(max(0.0, TOOL_WAIT_MAX_S - wait))
            final = store.load(job["id"]) or final
        if final.get("stage") in TERMINAL:
            return json.dumps(_result(final), default=str)
        return json.dumps(_result(final, message=(
            f"Still rendering ({round(100 * float(final.get('pct') or 0))}%). It keeps going in the background; "
            f"call auteur_status with job_id={job['id']} to get the MEDIA path when it is done.")), default=str)
    except Exception as exc:
        log.exception("auteur_render failed")
        return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})


def status_tool(ctx: Any, args: dict[str, Any] | None, **kwargs: Any) -> str:
    """``auteur_status`` handler (never raises)."""
    try:
        args = args if isinstance(args, dict) else {}
        out: dict[str, Any] = {}
        if args.get("styles"):
            out["styles"] = [s.to_dict() for s in discover_styles().values()]
        store = _store()
        job = store.find(str(args.get("job_id") or ""), str(kwargs.get("session_id") or "") or None)
        if job is None:
            out.update(success=bool(out), status="none", message="No film job found for this session.")
        else:
            out.update(_result(job))
            out["log"] = [e.get("msg") for e in public_view(job, 8)["log"]]
        return json.dumps(out, default=str)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})


# ----------------------------------------------------------------------------------- CLI

def cli_setup(parser: Any) -> None:
    """``hermes auteur render|styles|doctor|status`` argument tree."""
    sub = parser.add_subparsers(dest="auteur_cmd")
    r = sub.add_parser("render", help="make a film of a session")
    r.add_argument("--session", default="latest", help="session id, prefix or 'latest'")
    r.add_argument("--style", default=None)
    r.add_argument("--seconds", type=int, default=None)
    r.add_argument("--aspect", default=None, help="16:9 | 9:16 | both | 1:1")
    r.add_argument("--mode", default=None, help="product | lore | speedrun")
    r.add_argument("--no-voice", action="store_true")
    r.add_argument("--preview", action="store_true")
    r.add_argument("--direction", default="", help="free-text direction (Directed mode)")
    r.add_argument("--effort", default=None, choices=("quick", "standard", "max"))
    r.add_argument("--engine-3d", dest="engine_3d", default=None, choices=("browser", "blender", "auto"),
                   help="3D shots: browser (default) or your installed Blender")
    r.add_argument("--blender", action="store_true", help="same as --engine-3d blender")
    r.add_argument("--json", action="store_true")
    _cz.add_cli_args(r)  # W5: --customize TEXT, --set KEY=VALUE
    sub.add_parser("styles", help="list styles")
    d = sub.add_parser("doctor", help="check Chromium, ffmpeg, assets and the runtime")
    d.add_argument("--json", action="store_true")
    s = sub.add_parser("status", help="show a job (latest by default)")
    s.add_argument("job", nargs="?", default="")


def make_cli_handler(ctx: Any) -> Any:
    def handler(args: Any, **_: Any) -> int:
        try:
            return cli(ctx, args)
        except KeyboardInterrupt:
            from .pipeline import cancel_all
            cancel_all(wait_s=5.0)
            print("cancelled")
            return 130
    return handler


def cli(ctx: Any, args: Any) -> int:
    """Run one CLI subcommand; returns the process exit code."""
    which = getattr(args, "auteur_cmd", None) or "help"
    if which == "styles":
        print(styles_text(discover_styles()))
        return 0
    if which == "doctor":
        from .doctor import doctor_report, format_report
        rep = doctor_report(ctx)
        print(json.dumps(rep, indent=1, default=str) if getattr(args, "json", False) else format_report(rep))
        return 0 if rep.get("ok") else 1
    store = _store()
    if which == "status":
        print(_status_text(store, getattr(args, "job", ""), ""))
        return 0
    if which != "render":
        print("usage: hermes auteur render|styles|doctor|status  (hermes auteur render --help)")
        return 2
    from .session import resolve_session_ref
    sid = resolve_session_ref(args.session) or ""
    if not sid:
        print(f"no session matches {args.session!r}")
        return 1
    opts = _settings(ctx).options()
    for key in ("style", "seconds", "mode", "effort"):
        if getattr(args, key, None):
            setattr(opts, key, getattr(args, key))
    if args.aspect:
        opts.aspects = norm_aspects(args.aspect)
    opts.voice = opts.voice and not args.no_voice
    opts.preview, opts.direction = bool(args.preview), args.direction or ""
    engine = "blender" if getattr(args, "blender", False) else getattr(args, "engine_3d", None)
    if not engine and opts.direction:
        wants = blender_requested(opts.direction)          # "use blender" in the direction, as in the tool
        engine = None if wants is None else ("blender" if wants else "browser")
    if engine:
        opts.engine_3d = engine
    opts = _cz.from_cli_args(opts, args)  # W5 preset customization
    opts = opts.normalised()
    _ensure_builtin_tools()
    job = store.create(sid, opts.to_dict(), kind="directed" if opts.directed else "quick", surface="cli")
    print(f"auteur {job['id']}: {describe(opts)} (session {sid})", flush=True)

    class _Echo:
        ok = True

        def edit(self, text: str) -> None:
            print(text, flush=True)

    from .pipeline import run_job
    t0 = time.monotonic()
    final = run_job(job["id"], _host(ctx, "cli"), store=store, handle=_Echo())
    if args.json:
        print(json.dumps(_result(final, wall_s=round(time.monotonic() - t0, 1)), indent=1, default=str))
    elif final.get("stage") == "done":
        from .deliver import done_text
        print(done_text(final, media=True))
    return 0 if final.get("stage") == "done" else 1


def _ensure_builtin_tools() -> None:
    """The bare ``hermes auteur`` CLI has no agent loaded; make ``text_to_speech`` dispatchable."""
    try:
        from tools.registry import discover_builtin_tools  # public, lazy
        discover_builtin_tools()
    except Exception as exc:  # noqa: BLE001 - narration then falls back to captions
        log.debug("auteur: builtin tool discovery failed: %s", exc)


# -------------------------------------------------------------------------------- unload

def on_unload() -> None:
    """Cancel this process's renders (their browsers and ffmpeg children stop with them)."""
    try:
        from .pipeline import cancel_all
        ids = cancel_all(wait_s=3.0)
        if ids:
            log.info("auteur: cancelled %s on unload", ", ".join(ids))
    except Exception as exc:  # noqa: BLE001
        log.debug("auteur unload: %s", exc)


def skill_path() -> Path:
    return Path(__file__).resolve().parents[1] / "skills" / "auteur" / "SKILL.md"


__all__ = ["RENDER_SCHEMA", "STATUS_SCHEMA", "Command", "cli", "cli_setup", "make_cli_handler",
           "make_slash_handler", "on_unload", "render_tool", "skill_path", "slash", "start_film", "status_tool"]
