"""``hermes hype doctor``: can this machine make a film?

The checks are read-only. Only at an interactive terminal (never in CI, cron, the gateway or with ``--json``)
the doctor then offers y/N installs for what is missing (default No, 60 s timeout = No): Blender via
``showreel_core.blender.install`` (checksum-pinned official build), ffmpeg/Chromium via ``hermes pm install``.
"""
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
               else "not in this build", "update the plugin (hermes plugins update hype)"),
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
    out.append(_check("storyboard model", llm_ok, "ctx.llm available (task 'hype')" if llm_ok
                      else "unavailable", "storyboards fall back to the built-in heuristic", False))
    tts = False
    try:
        from tools.registry import registry  # public, lazy
        tts = registry.get_entry("text_to_speech") is not None
        if not tts:   # the bare `hermes hype` CLI has no agent: discover the built-ins like `render` does
            from tools.registry import discover_builtin_tools  # public, lazy
            discover_builtin_tools()
            tts = registry.get_entry("text_to_speech") is not None
    except Exception:  # noqa: BLE001
        tts = False
    out.append(_check("narration (text_to_speech)", tts, "registered" if tts else "not registered here",
                      "only matters for narrated films (narration is off by default): they fall back to music and "
                      "on-screen type; Edge TTS needs the edge-tts extra", False))
    if tts:
        from .llm import edge_tts_problem
        problem = edge_tts_problem()
        if problem:
            out.append(_check("narration (edge-tts version)", False, problem.split(";")[0],
                              "narration fails, films are captions-only until Hermes is updated "
                              "(Hype never changes packages in the Hermes environment)", False))
    return out


def _blender() -> list[dict[str, Any]]:
    """Optional: the user's Blender for the ``blender`` 3D engine (never required)."""
    from .blender.locate import locate
    from .config import settings_from_hermes_config

    found = locate(settings_from_hermes_config().blender_path or None)
    if found.ok:
        return [_check("blender", True, f"Blender {found.version_string} at {found.path} ({found.source})",
                       required=False)]
    return [_check("blender", False, "not found (optional: only for the 'blender' 3D engine)", found.message,
                   required=False) | {"reason": getattr(found, "reason", "")}]


def doctor_report(ctx: Any = None) -> dict[str, Any]:
    """All checks as JSON; ``ok`` is False only when a required check fails."""
    checks: list[dict[str, Any]] = [
        _check("python", sys.version_info >= (3, 11), platform.python_version(), "Hype needs Python 3.11+"),
    ]
    for fn in (_ffmpeg, lambda: [_chromium()], _assets, _storage, lambda: _services(ctx), _blender):
        try:
            checks += fn()
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed check, not a crash
            checks.append(_check(getattr(fn, "__name__", "check"), False, f"{type(exc).__name__}: {exc}"))
    ok = all(c["ok"] for c in checks if c["required"])
    return {"ok": ok, "version": __version__, "platform": f"{platform.system()} {platform.machine()}",
            "plugin_dir": str(REPO_ROOT), "pid": os.getpid(), "checks": checks}


def format_report(rep: dict[str, Any]) -> str:
    lines = [f"Hype {rep['version']} doctor · {rep['platform']}"]
    for c in rep["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["required"] else "warn")
        lines.append(f"  [{mark}] {c['name']}: {c['detail']}")
        if not c["ok"] and c["hint"]:
            lines.append(f"         -> {c['hint']}")
    lines.append("Ready to make films." if rep["ok"] else "Not ready: fix the FAIL lines above.")
    return "\n".join(lines)


# ------------------------------------------------------------------------- y/N install offers (people only)

#: Doctor items Hermes' own package manager can install (``hermes pm install NAME``).
PM_PACKAGES = {"ffmpeg": "ffmpeg", "chromium": "chromium"}


def hermes_command() -> list[str]:
    """How to call the public ``hermes`` CLI from here (the launcher on PATH, else this interpreter)."""
    import shutil
    exe = shutil.which("hermes")
    return [exe] if exe else [sys.executable, "-m", "hermes_cli.main"]


class CliProgress:
    """One self-rewriting progress line on stderr for the Blender install."""

    LABELS = {"download": "downloading", "verify": "verifying SHA-256", "unpack": "unpacking", "check": "checking"}

    def __init__(self, stream: Any = None) -> None:
        self.stream = stream or sys.stderr
        self.last = 0.0
        self.stage = ""

    def __call__(self, stage: str, done: int, total: int) -> None:
        import time
        now = time.monotonic()
        if stage == self.stage and now - self.last < 0.25 and done < total:
            return
        if self.stage and stage != self.stage:
            self.stream.write("\n")
        self.stage, self.last = stage, now
        label = self.LABELS.get(stage, stage)
        if stage == "download":
            text = f"  {label} {done / 1e6:6.0f} / {total / 1e6:.0f} MB ({100 * done // max(1, total)}%)"
        elif stage == "unpack":
            text = f"  {label} {done}/{total} files"
        else:
            text = f"  {label}…"
        self.stream.write("\r" + text)
        self.stream.flush()

    def end(self) -> None:
        if self.stage:
            self.stream.write("\n")
            self.stream.flush()
            self.stage = ""


def install_blender_cli(*, yes: bool = False, parent: str | None = None, out: Any = print,
                        ask: Any = None, prompt_ok: bool | None = None, installer: Any = None) -> int:
    """``hermes hype install-blender [--yes] [--dir PATH]``; returns the exit code."""
    from .blender import install as bi
    from .blender.locate import BlenderFound, locate
    from .config import settings_from_hermes_config

    build = bi.build_for()
    if build is None:
        out("Blender publishes no build for this machine; install it from https://www.blender.org/download/ "
            "and set HYPE_BLENDER to its blender executable.")
        return 1
    if not parent:
        found = locate(settings_from_hermes_config().blender_path or None)
        if isinstance(found, BlenderFound):
            out(f"Blender {found.version_string} is already installed at {found.path}; nothing to do.")
            return 0
        if _explicit_setting():
            out(f"Note: {found.message.split('. ')[0]}. Unset it after the install so Hype finds the new Blender.")
    if not yes:
        if not (bi.can_prompt() if prompt_ok is None else prompt_ok):
            out(f"Not asking without a terminal. To install Blender {build.version} (~{build.size_mb} MB from "
                "download.blender.org, checksum-verified) run: hermes hype install-blender --yes")
            return 2
        answer = (ask or bi.ask_yes_no)(bi.question(build))
        if not answer:
            out("Blender was not installed.")
            return 1
    where = parent or str(bi.default_parent(build))
    out(f"Installing Blender {build.version} from {build.href}\n  into {where} (SHA-256 {build.sha256[:16]}…)")
    bar = CliProgress()
    try:
        res = (installer or bi.install)(build=build, parent=parent, progress=bar)
    except (bi.InstallCancelled, KeyboardInterrupt):
        bar.end()
        out("Cancelled; nothing was installed.")
        return 130
    except bi.InstallError as exc:
        bar.end()
        out(f"Blender install failed: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - one clear line, not a traceback (nothing is left behind)
        bar.end()
        out(f"Blender install failed: {type(exc).__name__}: {exc}")
        return 1
    bar.end()
    if res.get("skipped"):
        out(f"Blender {res['version']} is already at {res['path']}; left it as it is.")
    else:
        out(f"Blender {res['version']} installed at {res['path']}")
    if parent:
        out(f"Hype searches the standard folders only; to use this one set HYPE_BLENDER={res['path']} "
            "(or the Hype setting blender_path).")
    else:
        out("Hype finds it automatically: try `/hype ... blender` or the Blender engine in the Desktop pane.")
    return 0


def _explicit_setting() -> bool:
    from .blender.locate import ENV_VAR
    from .config import settings_from_hermes_config
    try:
        return bool(os.environ.get(ENV_VAR, "").strip() or settings_from_hermes_config().blender_path)
    except Exception:  # noqa: BLE001
        return bool(os.environ.get(ENV_VAR, "").strip())


def offer_installs(rep: dict[str, Any], *, out: Any = print, ask: Any = None, prompt_ok: bool | None = None,
                   run: Any = None, install_blender: Any = None) -> bool:
    """After a doctor report: offer y/N installs for missing pieces, only to a person at a terminal.

    Blender: our checksum-pinned download (:mod:`showreel_core.blender.install`). ffmpeg/Chromium: Hermes' own
    package manager (``hermes pm install NAME``). Default No, 60 s timeout = No (and no further questions).
    Returns True when something was installed (the caller re-runs the checks).
    """
    import subprocess

    from .blender import install as bi
    if not (bi.can_prompt() if prompt_ok is None else prompt_ok):
        return False
    ask = ask or bi.ask_yes_no
    changed = False
    missing = {c["name"]: c for c in rep.get("checks", []) if not c.get("ok")}
    for name, pkg in PM_PACKAGES.items():
        if name not in missing:
            continue
        cmd = hermes_command() + ["pm", "install", pkg]
        answer = ask(f"{name} is missing. Install it now with Hermes' own installer (`hermes pm install {pkg}`)? "
                     "[y/N] ")
        if answer is None:
            return changed
        if not answer:
            out(f"  skipped; run `hermes pm install {pkg}` any time.")
            continue
        try:
            code = (run or subprocess.run)(cmd).returncode
        except (OSError, KeyboardInterrupt) as exc:
            code = 1
            out(f"  could not run `hermes pm install {pkg}`: {exc}")
        out(f"  hermes pm install {pkg}: {'done' if code == 0 else f'exit code {code}'}")
        changed = changed or code == 0
    blender = missing.get("blender")
    if blender and bi.build_for() is not None:
        if _explicit_setting():
            out("  Blender: HYPE_BLENDER / blender_path points at a Blender that does not work; fix or unset it "
                "(or run `hermes hype install-blender`).")
            return changed
        code = (install_blender or install_blender_cli)(ask=ask, prompt_ok=True, out=out)
        changed = changed or code == 0
    return changed


__all__ = ["doctor_report", "format_report", "install_blender_cli", "offer_installs"]
