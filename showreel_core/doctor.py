"""``hermes showreel doctor``: can this machine make a film? (read-only checks, nothing installed)."""
from __future__ import annotations

import os
import platform
import sys
import tempfile
from typing import Any

from . import __version__
from .config import REPO_ROOT, discover_styles


def _check(name: str, ok: bool, detail: str, hint: str = "", required: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "hint": hint, "required": required}


def _ffmpeg() -> list[dict[str, Any]]:
    from .render.errors import RenderError
    from .render.ffmpeg import capabilities, pick_encoder, resolve_ffmpeg
    try:
        info = resolve_ffmpeg()
    except RenderError as e:
        return [_check("ffmpeg", False, e.message, e.hint)]
    out = [_check("ffmpeg", True, f"{info.path} ({info.source})")]
    try:
        caps = capabilities(info.path)
        version = str(caps.version).split(" version ")[-1].split(" ")[0]
        out.append(_check("video encoder", True, f"{pick_encoder(caps)} (ffmpeg {version})"))
    except Exception as exc:  # noqa: BLE001
        out.append(_check("video encoder", False, f"{type(exc).__name__}: {exc}",
                          "Reinstall ffmpeg: hermes pm install ffmpeg"))
    return out


def _chromium() -> dict[str, Any]:
    from .render.chromium import resolve_chromium
    from .render.errors import RenderError
    try:
        cand = resolve_chromium()
    except RenderError as e:
        return _check("chromium", False, e.message, e.hint)
    return _check("chromium", True, f"{cand.path} ({cand.source})")


def _assets() -> list[dict[str, Any]]:
    beds = sorted(p.parent.name for p in (REPO_ROOT / "assets" / "audio" / "beds").glob("*/bars.json"))
    sfx = (REPO_ROOT / "assets" / "audio" / "sfx" / "sfx.json").is_file()
    runtime = (REPO_ROOT / "runtime").is_dir() and any((REPO_ROOT / "runtime").rglob("*.js"))
    try:
        from .film import page, quick  # noqa: F401 - import check only
        film = True
    except Exception:  # noqa: BLE001
        film = False
    ready = sorted(s.id for s in discover_styles().values() if s.ready)
    return [
        _check("music beds", bool(beds), ", ".join(beds) or "none", "the music falls back to silence", False),
        _check("sound effects", sfx, "sfx.json found" if sfx else "missing", "films are made without SFX", False),
        _check("film runtime", runtime and film, "runtime/ + film builder present" if runtime and film
               else "not in this build", "update the plugin (hermes plugins update showreel)"),
        _check("styles", bool(ready), ", ".join(ready) or "no style pack is ready yet", "", False),
    ]


def _storage() -> list[dict[str, Any]]:
    from .deliver import videos_dir
    from .jobs import data_root
    out = []
    try:
        root = data_root()
        with tempfile.NamedTemporaryFile(dir=root, prefix=".probe-", delete=True):
            pass
        out.append(_check("job storage", True, str(root)))
    except Exception as exc:  # noqa: BLE001
        out.append(_check("job storage", False, f"{type(exc).__name__}: {exc}"))
    vd = videos_dir()
    out.append(_check("video delivery folder", vd is not None, str(vd) if vd else "not inside Hermes",
                      "outside Hermes films stay in the job folder", False))
    return out


def _services(ctx: Any) -> list[dict[str, Any]]:
    out = []
    llm_ok = False
    try:
        llm_ok = ctx is not None and ctx.llm is not None
    except Exception:  # noqa: BLE001
        llm_ok = False
    out.append(_check("storyboard model", llm_ok, "ctx.llm available (task 'showreel')" if llm_ok
                      else "unavailable", "storyboards fall back to the built-in heuristic", False))
    tts = False
    try:
        from tools.registry import registry  # public, lazy
        tts = registry.get_entry("text_to_speech") is not None
    except Exception:  # noqa: BLE001
        tts = False
    out.append(_check("narration (text_to_speech)", tts, "registered" if tts else "not registered here",
                      "films get captions only; Edge TTS needs the edge-tts extra", False))
    return out


def doctor_report(ctx: Any = None) -> dict[str, Any]:
    """All checks as JSON; ``ok`` is False only when a required check fails."""
    checks: list[dict[str, Any]] = [
        _check("python", sys.version_info >= (3, 11), platform.python_version(), "Showreel needs Python 3.11+"),
    ]
    for fn in (_ffmpeg, lambda: [_chromium()], _assets, _storage, lambda: _services(ctx)):
        try:
            checks += fn()
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed check, not a crash
            checks.append(_check(getattr(fn, "__name__", "check"), False, f"{type(exc).__name__}: {exc}"))
    ok = all(c["ok"] for c in checks if c["required"])
    return {"ok": ok, "version": __version__, "platform": f"{platform.system()} {platform.machine()}",
            "plugin_dir": str(REPO_ROOT), "pid": os.getpid(), "checks": checks}


def format_report(rep: dict[str, Any]) -> str:
    lines = [f"Showreel {rep['version']} doctor · {rep['platform']}"]
    for c in rep["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["required"] else "warn")
        lines.append(f"  [{mark}] {c['name']}: {c['detail']}")
        if not c["ok"] and c["hint"]:
            lines.append(f"         -> {c['hint']}")
    lines.append("Ready to make films." if rep["ok"] else "Not ready: fix the FAIL lines above.")
    return "\n".join(lines)


__all__ = ["doctor_report", "format_report"]
