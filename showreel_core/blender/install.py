"""Optional Blender install for the ``blender`` 3D engine (asks first, never runs unattended).

Runs only after the user says yes: ``hermes hype install-blender``, the y/N question in an interactive
``hermes hype doctor``, or the Desktop pane's Install button. It downloads one official Blender LTS build from
https://download.blender.org/release/, checks it against the SHA-256 pinned in :data:`BUILDS` (copied from that
release's ``.sha256`` file), and unpacks it per-user without admin rights into the folders ``locate.py``
searches:

- Windows: ``%LOCALAPPDATA%\\Programs\\Blender Foundation\\Blender <major.minor>\\blender.exe``
- macOS:   ``~/Applications/Blender <major.minor>.app`` (the .dmg is attached read-only, copied, detached)
- Linux:   ``~/.local/opt/blender-<version>/blender``

It never writes over an existing folder. The download and the unpacked tree stay in a hidden staging folder
next to the target, and the finished tree is renamed into place in one step, so a cancelled or failed run
leaves no half-installed Blender behind. The new Blender must answer ``blender --version`` before the
install counts. Only the standard library is used: urllib honours the usual proxy variables.
"""
from __future__ import annotations

import hashlib
import os
import platform as _platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

RELEASE_BASE = "https://download.blender.org/release"
CHUNK = 1 << 20
NET_TIMEOUT_S = 60.0
PROMPT_TIMEOUT_S = 60.0
#: Unpacked Blender needs about this many times the download size on disk (plus the download itself).
UNPACK_FACTOR = 3.2


@dataclass(frozen=True)
class Build:
    """One official Blender release archive for one platform."""

    key: str            # windows-x64 | windows-arm64 | macos-arm64 | macos-x64 | linux-x64
    version: str        # "5.2.4"
    file: str           # archive file name on download.blender.org
    sha256: str         # from the release's blender-<version>.sha256
    size: int           # bytes (Content-Length), for the question and the disk check
    url: str = ""

    @property
    def href(self) -> str:
        return self.url or f"{RELEASE_BASE}/Blender{_series(self.version)}/{self.file}"

    @property
    def kind(self) -> str:
        return "zip" if self.file.endswith(".zip") else "dmg" if self.file.endswith(".dmg") else "tar.xz"

    @property
    def size_mb(self) -> int:
        return int(round(self.size / 1e6))

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "version": self.version, "url": self.href, "sha256": self.sha256,
                "size": self.size, "size_mb": self.size_mb}


def _series(version: str) -> str:
    return ".".join(version.split(".")[:2])


#: Blender 5.2 LTS (the engine is developed and tested on 5.2). Blender 5.x has no Intel-Mac build, so Intel
#: Macs get 4.5 LTS, the last LTS with one (the engine supports Blender 4.2+). Checksums: blender-5.2.4.sha256
#: and blender-4.5.9.sha256 from download.blender.org, fetched 2026-11-11.
BUILDS: dict[str, Build] = {b.key: b for b in (
    Build("windows-x64", "5.2.4", "blender-5.2.4-windows-x64.zip",
          "bbd78f8931dc940444da4ff2983374930f9f5c092ae0e330588e9760bb9d967c", 405779142),
    Build("windows-arm64", "5.2.4", "blender-5.2.4-windows-arm64.zip",
          "7e5227cbea71e06dd19b1b564640768d4517b097a3115d800c92eccaae39a992", 274057139),
    Build("macos-arm64", "5.2.4", "blender-5.2.4-macos-arm64.dmg",
          "e73d564f97061b2496ccc5a0bd738937d2d3d0acae23621a00bbc7534dfd135f", 346299398),
    Build("macos-x64", "4.5.9", "blender-4.5.9-macos-x64.dmg",
          "00c8a433504291374bfa045c0c2d708a779f8abc8400b4718fdd11c117486fa4", 335828094),
    Build("linux-x64", "5.2.4", "blender-5.2.4-linux-x64.tar.xz",
          "2fd14c50987426897ba60237ee996edf2b4151f4b1a72a460ca20be58c1d2d86", 385047680),
)}


class InstallError(Exception):
    """A user-facing reason the install did not happen (nothing was left behind)."""


class InstallCancelled(InstallError):
    pass


def platform_key(system: str | None = None, machine: str | None = None) -> str | None:
    """``windows-x64`` etc. for this machine, or None when Blender ships no build for it."""
    system = (system or _platform.system()).lower()
    machine = (machine or _platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64", "armv8", "armv8l") else (
        "x64" if machine in ("x86_64", "amd64", "x64") else "")
    os_ = {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(system, "")
    key = f"{os_}-{arch}" if os_ and arch else ""
    return key if key in BUILDS else None


def build_for(key: str | None = None) -> Build | None:
    key = key or platform_key()
    return BUILDS.get(key) if key else None


def default_parent(build: Build, environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """Where the official Blender plugin and ``locate.py`` look: per-user, no admin rights needed."""
    env = os.environ if environ is None else environ
    home = home or Path.home()
    if build.key.startswith("windows"):
        base = env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "Programs" / "Blender Foundation"
    if build.key.startswith("macos"):
        return home / "Applications"
    return home / ".local" / "opt"


def target_name(build: Build) -> str:
    if build.key.startswith("windows"):
        return f"Blender {_series(build.version)}"
    if build.key.startswith("macos"):
        return f"Blender {_series(build.version)}.app"
    return f"blender-{build.version}"


def executable_in(target: Path, build: Build) -> Path:
    if build.key.startswith("windows"):
        return target / "blender.exe"
    if build.key.startswith("macos"):
        return target / "Contents" / "MacOS" / "Blender"
    return target / "blender"


def question(build: Build | None = None) -> str:
    build = build or build_for()
    if build is None:
        return ""
    return (f"Install Blender {build.version} now? It's an optional ~{build.size_mb} MB download from "
            f"download.blender.org, checksum-verified, installed for this user only (no admin). [y/N] ")


# ------------------------------------------------------------------------------------------- prompting

_UNATTENDED_ENV = ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER", "TF_BUILD",
                   "HERMES_NONINTERACTIVE", "HERMES_CRON_SESSION", "HERMES_GATEWAY_SESSION", "HERMES_SERVE_HEADLESS",
                   "HYPE_NO_PROMPT")


def can_prompt(stdin: Any = None, stdout: Any = None, environ: dict[str, str] | None = None) -> bool:
    """True only for a person at a terminal: stdin and stdout are TTYs and nothing says CI/cron/gateway."""
    env = os.environ if environ is None else environ
    for name in _UNATTENDED_ENV:
        if str(env.get(name, "")).strip().lower() not in ("", "0", "false", "no"):
            return False
    source = str(env.get("HERMES_SESSION_SOURCE", "") or "").strip().lower()
    if source and source not in ("cli", "tui", "terminal"):
        return False
    for stream in (stdin if stdin is not None else sys.stdin, stdout if stdout is not None else sys.stdout):
        try:
            if stream is None or not stream.isatty():
                return False
        except (AttributeError, ValueError, OSError):
            return False
    return True


def ask_yes_no(prompt: str, *, timeout_s: float = PROMPT_TIMEOUT_S, read: Callable[[], str] | None = None,
               write: Callable[[str], Any] | None = None) -> bool | None:
    """Ask ``prompt``; True for y/yes, False for anything else, None when nobody answered in ``timeout_s``.

    The default is No. The answer is read on a daemon thread so the timeout also works on Windows consoles
    (a timed-out reader is left behind, so callers must not ask again in the same process after None).
    """
    out: Callable[[str], Any] = write or (lambda s: (sys.stdout.write(s), sys.stdout.flush()))
    rd: Callable[[], str] = read or sys.stdin.readline
    box: dict[str, str] = {}

    def reader() -> None:
        try:
            box["a"] = rd() or ""
        except Exception:  # noqa: BLE001 - EOF/closed stdin = no
            box["a"] = ""

    out(prompt)
    t = threading.Thread(target=reader, name="hype-prompt", daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        out(f"\n(no answer in {int(timeout_s)} s: no)\n")
        return None
    return box.get("a", "").strip().lower() in ("y", "yes")


# --------------------------------------------------------------------------------------------- install

Progress = Callable[[str, int, int], None]      # (stage, done, total): download | verify | unpack | check


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:  # some Python builds (python.org macOS) ship without a CA bundle; certifi rides along with Hermes
        import certifi  # type: ignore[import-not-found]
        ctx.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001 - the system store is enough elsewhere
        pass
    return ctx


def _urlopen(req: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def download(build: Build, dest: Path, *, progress: Progress | None = None, cancel: threading.Event | None = None,
             opener: Callable[..., Any] | None = None, timeout_s: float = NET_TIMEOUT_S) -> str:
    """Stream ``build`` to ``dest``; returns the SHA-256 hex digest of what arrived."""
    from .. import __version__
    req = urllib.request.Request(build.href, headers={"User-Agent": f"hermes-hype/{__version__} (Blender install)"})
    h = hashlib.sha256()
    done = total = 0
    try:
        with (opener or _urlopen)(req, timeout_s) as resp, open(dest, "wb") as fh:
            try:
                total = int(resp.headers.get("Content-Length") or build.size)
            except (TypeError, ValueError, AttributeError):
                total = build.size
            while True:
                if cancel is not None and cancel.is_set():
                    raise InstallCancelled("cancelled")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress("download", done, total)
    except InstallError:
        raise
    except Exception as exc:  # noqa: BLE001 - network errors become one clear message
        raise InstallError(f"download of {build.href} failed: {type(exc).__name__}: {exc}. Check the network or "
                           "proxy (HTTPS_PROXY), then try again.") from exc
    if total and done < total:
        raise InstallError(f"download of {build.file} stopped at {done} of {total} bytes; try again.")
    return h.hexdigest()


def _safe_member(name: str) -> bool:
    p = name.replace("\\", "/")
    return bool(p) and not p.startswith("/") and ":" not in p.split("/")[0] and ".." not in p.split("/")


def _unzip(archive: Path, into: Path, cancel: threading.Event | None, progress: Progress | None) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        for k, info in enumerate(infos):
            if cancel is not None and cancel.is_set():
                raise InstallCancelled("cancelled")
            if not _safe_member(info.filename):
                raise InstallError(f"refusing an unsafe path in the archive: {info.filename!r}")
            zf.extract(info, into)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                os.chmod(into / info.filename, mode)
            if progress and (k % 200 == 0 or k == len(infos) - 1):
                progress("unpack", k + 1, len(infos))


def _untar(archive: Path, into: Path, cancel: threading.Event | None, progress: Progress | None) -> None:
    with tarfile.open(archive, mode="r:xz") as tf:
        members = tf.getmembers()
        for k, m in enumerate(members):
            if cancel is not None and cancel.is_set():
                raise InstallCancelled("cancelled")
            if not _safe_member(m.name) or m.isdev():
                raise InstallError(f"refusing an unsafe path in the archive: {m.name!r}")
            if hasattr(tarfile, "data_filter"):
                tf.extract(m, into, filter="data")
            else:  # pragma: no cover - Python < 3.11.4
                tf.extract(m, into)
            if progress and (k % 200 == 0 or k == len(members) - 1):
                progress("unpack", k + 1, len(members))


def _undmg(archive: Path, into: Path, cancel: threading.Event | None, progress: Progress | None,
           run: Callable[..., Any] = subprocess.run) -> None:
    mnt = into / "mnt"
    mnt.mkdir(parents=True)
    out = run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mnt), str(archive)],
              capture_output=True, text=True, timeout=300)
    if getattr(out, "returncode", 1) != 0:
        raise InstallError(f"could not open the Blender disk image: {(out.stderr or out.stdout or '').strip()}")
    try:
        apps = sorted(mnt.glob("*.app"))
        if not apps:
            raise InstallError("the Blender disk image has no .app inside")
        if cancel is not None and cancel.is_set():
            raise InstallCancelled("cancelled")
        if progress:
            progress("unpack", 0, 1)
        cp = run(["ditto", str(apps[0]), str(into / "app" / apps[0].name)], capture_output=True, text=True,
                 timeout=1800)
        if getattr(cp, "returncode", 1) != 0:
            raise InstallError(f"copying Blender.app failed: {(cp.stderr or '').strip()}")
        if progress:
            progress("unpack", 1, 1)
    finally:
        run(["hdiutil", "detach", str(mnt), "-force"], capture_output=True, text=True, timeout=120)


def _find_root(unpacked: Path, build: Build) -> Path:
    """The folder inside the unpacked tree that holds the Blender executable (or the .app)."""
    if build.kind == "dmg":
        apps = sorted((unpacked / "app").glob("*.app"))
        if apps:
            return apps[0]
        raise InstallError("Blender.app was not copied")
    for cand in [unpacked, *sorted(p for p in unpacked.iterdir() if p.is_dir())]:
        if executable_in(cand, build).is_file():
            return cand
    raise InstallError(f"the archive has no {executable_in(Path('.'), build).name} where Blender keeps it")


def _default_probe(exe: Path) -> str | None:
    from .locate import probe_version
    got = probe_version(exe)
    return got[1] if got else None


def install(*, build: Build | None = None, parent: Path | str | None = None, progress: Progress | None = None,
            cancel: threading.Event | None = None, opener: Callable[..., Any] | None = None,
            probe: Callable[[Path], str | None] | None = None,
            disk_free: Callable[[Path], int] | None = None) -> dict[str, Any]:
    """Download, verify, unpack and check one Blender build; returns ``{path, version, target, skipped}``.

    ``parent`` defaults to the per-user folder for this OS (``--dir`` on the CLI). An existing target folder is
    never touched: a working Blender there is returned with ``skipped=True``, anything else is an error.
    Raises :class:`InstallError` (or :class:`InstallCancelled`) with a user-facing message; nothing is left
    behind on failure. ``opener``/``probe``/``disk_free`` are test seams.
    """
    build = build or build_for()
    if build is None:
        raise InstallError(f"Blender publishes no build for {_platform.system()} {_platform.machine()}; "
                           "install it from blender.org and set HYPE_BLENDER.")
    probe = probe or _default_probe
    root = Path(parent).expanduser() if parent else default_parent(build)
    target = root / target_name(build)
    exe = executable_in(target, build)
    if target.exists():
        ver = probe(exe) if exe.is_file() else None
        if ver:
            return {"path": str(exe), "version": ver, "target": str(target), "skipped": True}
        raise InstallError(f"{target} already exists but holds no working Blender; Hype never writes over an "
                           "existing folder. Move it away, or point HYPE_BLENDER at a working blender.")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"cannot create {root}: {exc}") from exc
    need = int(build.size * (1 + UNPACK_FACTOR))
    free = (disk_free or (lambda p: shutil.disk_usage(p).free))(root)
    if free < need:
        raise InstallError(f"not enough disk space in {root}: Blender needs about {need // 1_000_000} MB free "
                           f"(download + unpack), {free // 1_000_000} MB are free.")
    stage = Path(tempfile.mkdtemp(prefix=f".hype-blender-{build.version}-", dir=root))
    try:
        archive = stage / build.file
        digest = download(build, archive, progress=progress, cancel=cancel, opener=opener)
        if progress:
            progress("verify", 1, 1)
        if digest.lower() != build.sha256.lower():
            raise InstallError(f"checksum mismatch for {build.file}: expected {build.sha256}, got {digest}. "
                               "Refused to install it (the file was deleted).")
        unpacked = stage / "unpacked"
        unpacked.mkdir()
        {"zip": _unzip, "tar.xz": _untar, "dmg": _undmg}[build.kind](archive, unpacked, cancel, progress)
        archive.unlink(missing_ok=True)
        src = _find_root(unpacked, build)
        if cancel is not None and cancel.is_set():
            raise InstallCancelled("cancelled")
        if target.exists():
            raise InstallError(f"{target} appeared while installing (another install?); left it alone.")
        os.replace(src, target)          # one step: the target is either absent or complete
        if progress:
            progress("check", 0, 1)
        ver = probe(exe)
        if not ver:
            shutil.rmtree(target, ignore_errors=True)
            raise InstallError(f"the new Blender at {exe} did not answer `blender --version`; removed it again.")
        if progress:
            progress("check", 1, 1)
        return {"path": str(exe), "version": ver, "target": str(target), "skipped": False}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ------------------------------------------------------------------------------------ background (Desktop)

class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.data: dict[str, Any] = {"state": "idle"}


_STATE = _State()
_SPANS = {"download": (0, 80), "verify": (80, 82), "unpack": (82, 97), "check": (97, 100)}


def status() -> dict[str, Any]:
    with _STATE.lock:
        return dict(_STATE.data)


def start_background(**kw: Any) -> dict[str, Any]:
    """Start :func:`install` on a daemon thread (one at a time); poll :func:`status`."""
    with _STATE.lock:
        if _STATE.data.get("state") == "running":
            return dict(_STATE.data)
        build = kw.get("build") or build_for()
        _STATE.cancel = threading.Event()
        _STATE.data = {"state": "running", "stage": "download", "done": 0, "total": build.size if build else 0,
                       "pct": 0, "version": build.version if build else "", "started": time.time(), "message": ""}
        cancel = _STATE.cancel

    def progress(stage: str, done: int, total: int) -> None:
        with _STATE.lock:
            span = _SPANS.get(stage, (0, 100))
            frac = (done / total) if total else 0.0
            _STATE.data.update(stage=stage, done=done, total=total,
                               pct=int(span[0] + (span[1] - span[0]) * max(0.0, min(1.0, frac))))

    def go() -> None:
        try:
            res = install(progress=progress, cancel=cancel, **kw)
            upd = {"state": "done", "pct": 100, "stage": "done", **res,
                   "message": f"Blender {res['version']} is ready at {res['path']}"}
        except InstallCancelled:
            upd = {"state": "cancelled", "message": "Blender install cancelled; nothing was installed."}
        except InstallError as exc:
            upd = {"state": "failed", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - surface, never crash the dashboard thread
            upd = {"state": "failed", "message": f"{type(exc).__name__}: {exc}"}
        with _STATE.lock:
            _STATE.data.update(upd, finished=time.time())
        try:
            from . import locate as _locate
            _locate._cache.clear()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=go, name="hype-blender-install", daemon=True).start()
    return status()


def cancel_background() -> bool:
    with _STATE.lock:
        running = _STATE.data.get("state") == "running"
    if running:
        _STATE.cancel.set()
    return running


__all__ = ["BUILDS", "Build", "InstallCancelled", "InstallError", "ask_yes_no", "build_for", "can_prompt",
           "cancel_background", "default_parent", "download", "executable_in", "install", "platform_key", "question",
           "start_background", "status", "target_name"]
