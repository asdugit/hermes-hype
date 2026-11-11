"""Find the user's Blender (BLENDER.md "Detection").

Order: ``HYPE_BLENDER`` env -> plugin config ``blender_path`` -> ``blender`` on PATH -> standard install
locations (incl. where the official Hermes ``blender`` plugin installs it). Requires Blender >= 4.2 (EEVEE Next);
the version comes from ``blender --version``. Never raises: :func:`locate` returns :class:`BlenderFound` or
:class:`BlenderMissing` (both have ``ok`` and ``to_dict()``), and ``BlenderMissing.message`` is user-facing.
Finding never downloads anything; ``install.py`` installs Blender only when the user says yes.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_VERSION = (4, 2, 0)
ENV_VAR = "HYPE_BLENDER"
VERSION_TIMEOUT_S = 60.0
_VERSION_RE = re.compile(r"Blender\s+(\d+)\.(\d+)(?:\.(\d+))?")
_cache: dict[tuple[str, int, int], tuple[tuple[int, int, int], str] | None] = {}

INSTALL_HINT = (
    "Run `hermes hype install-blender` (asks first, then downloads the official Blender LTS from "
    "download.blender.org, checksum-verified, per-user, no admin), or install Blender 4.2+ from blender.org "
    "yourself, or point Hype at an existing Blender: set HYPE_BLENDER=<path to the blender executable> or the "
    "Hype setting `blender_path`.")


@dataclass(frozen=True)
class BlenderFound:
    """A usable Blender."""

    path: Path
    version: tuple[int, int, int]
    version_string: str
    source: str                    # env, config, path or standard
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"ok": True, "path": str(self.path), "version": list(self.version),
                "version_string": self.version_string, "source": self.source}


@dataclass(frozen=True)
class BlenderMissing:
    """No usable Blender; ``message`` is safe to show the user, ``reason`` is machine-readable."""

    reason: str                    # not_found | too_old | unrunnable | bad_path
    message: str
    tried: tuple[str, ...] = ()
    rejected: tuple[tuple[str, str], ...] = field(default=())   # (path, why)
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "reason": self.reason, "message": self.message, "tried": list(self.tried),
                "rejected": [list(r) for r in self.rejected]}


def parse_version(text: str) -> tuple[tuple[int, int, int], str] | None:
    """``(major, minor, patch), "5.2.3"`` from ``blender --version`` output (None when absent)."""
    m = _VERSION_RE.search(text or "")
    if not m:
        return None
    v = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    return v, f"{v[0]}.{v[1]}.{v[2]}"


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def child_env() -> dict[str, str]:
    """Environment for a Blender child: never leak our Python's path settings into Blender's own Python."""
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"):
        env.pop(k, None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def probe_version(path: Path, timeout_s: float = VERSION_TIMEOUT_S) -> tuple[tuple[int, int, int], str] | None:
    """Run ``blender --version`` (cached by path + mtime + size). None if it does not run or prints no version."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), int(st.st_mtime), int(st.st_size))
    if key in _cache:
        return _cache[key]
    try:
        out = subprocess.run([str(path), "--factory-startup", "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout_s, env=child_env(),
                             creationflags=_no_window(), stdin=subprocess.DEVNULL)
        parsed = parse_version((out.stdout or "") + "\n" + (out.stderr or ""))
    except (OSError, subprocess.SubprocessError):
        parsed = None
    _cache[key] = parsed
    return parsed


def standard_locations(platform: str | None = None, environ: dict[str, str] | None = None,
                       home: Path | None = None) -> list[Path]:
    """Existing Blender executables in the usual install places, newest-looking first."""
    platform = platform or sys.platform
    env = os.environ if environ is None else environ
    home = home or Path.home()
    pats: list[str] = []
    if platform == "win32":
        for base in (env.get("LOCALAPPDATA"), env.get("ProgramFiles"), env.get("ProgramW6432"),
                     env.get("ProgramFiles(x86)")):
            if base:
                pats += [str(Path(base) / "Programs" / "Blender Foundation" / "*" / "blender.exe"),
                         str(Path(base) / "Programs" / "Blender Foundation" / "*" / "*" / "blender.exe"),
                         str(Path(base) / "Blender Foundation" / "*" / "blender.exe"),
                         str(Path(base) / "Blender Foundation" / "*" / "*" / "blender.exe"),
                         str(Path(base) / "Steam" / "steamapps" / "common" / "Blender" / "blender.exe")]
    elif platform == "darwin":
        pats += ["/Applications/Blender*.app/Contents/MacOS/Blender",
                 str(home / "Applications" / "Blender*.app" / "Contents" / "MacOS" / "Blender"),
                 str(home / "Applications" / "*" / "Blender*.app" / "Contents" / "MacOS" / "Blender")]
    else:
        pats += [str(home / ".local" / "opt" / "blender*" / "blender"),
                 str(home / ".local" / "opt" / "*" / "blender*" / "blender"),
                 "/opt/blender*/blender", "/usr/local/bin/blender", "/usr/bin/blender", "/snap/bin/blender",
                 str(home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.blender.Blender"),
                 "/var/lib/flatpak/exports/bin/org.blender.Blender",
                 str(home / ".steam" / "steam" / "steamapps" / "common" / "Blender" / "blender")]
    found: list[Path] = []
    for pat in pats:
        for hit in sorted(glob.glob(pat), reverse=True):
            p = Path(hit)
            if p.is_file() and p not in found:
                found.append(p)
    return found


def _explicit(value: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(value.strip().strip('"'))))
    if p.is_dir():
        for name in ("blender.exe", "blender", "Contents/MacOS/Blender"):
            if (p / name).is_file():
                return p / name
    return p


def locate(config_path: str | None = None, *, environ: dict[str, str] | None = None,
           search_standard: bool = True) -> BlenderFound | BlenderMissing:
    """Find a Blender >= 4.2. Explicit choices (env, config) that are broken return an error (not a silent
    fallback) so the user learns their setting is wrong."""
    env = os.environ if environ is None else environ
    tried: list[str] = []
    rejected: list[tuple[str, str]] = []

    def check(p: Path, source: str) -> BlenderFound | str:
        tried.append(str(p))
        if not p.is_file():
            return "does not exist"
        parsed = probe_version(p)
        if parsed is None:
            return "did not run (`blender --version` printed no version)"
        v, vs = parsed
        if v < MIN_VERSION:
            return f"is Blender {vs}; Hype needs 4.2 or newer"
        return BlenderFound(path=p, version=v, version_string=vs, source=source)

    for source, value in (("env", env.get(ENV_VAR)), ("config", config_path)):
        if value and str(value).strip():
            p = _explicit(str(value))
            got = check(p, source)
            if isinstance(got, BlenderFound):
                return got
            label = ENV_VAR if source == "env" else "the Hype setting blender_path"
            reason = "too_old" if "needs 4.2" in got else ("bad_path" if got == "does not exist" else "unrunnable")
            return BlenderMissing(reason, f"Blender from {label} ({p}) {got}. {INSTALL_HINT}", tuple(tried),
                                  ((str(p), got),))

    cands: list[tuple[Path, str]] = []
    which = shutil.which("blender")
    if which:
        cands.append((Path(which), "path"))
    if search_standard:
        cands += [(p, "standard") for p in standard_locations(environ=dict(env))]
    best: BlenderFound | None = None
    for p, source in cands:
        if str(p) in tried:
            continue
        got = check(p, source)
        if isinstance(got, BlenderFound):
            if source == "path":
                return got
            if best is None or got.version > best.version:
                best = got
        else:
            rejected.append((str(p), got))
    if best:
        return best
    if rejected and any("needs 4.2" in why for _, why in rejected):
        old = "; ".join(f"{p} {why}" for p, why in rejected)
        return BlenderMissing("too_old", f"Found only an old Blender ({old}). {INSTALL_HINT}", tuple(tried),
                              tuple(rejected))
    return BlenderMissing("not_found", f"Blender was not found. {INSTALL_HINT}", tuple(tried), tuple(rejected))
