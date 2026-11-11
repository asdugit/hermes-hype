"""Chromium resolution, launch flags, launch and clean shutdown.

Resolution order: ``HYPE_CHROMIUM`` env -> Hermes ``pm`` Chromium (lazy import) -> system
Chrome / Chromium / Edge / Brave at well-known per-OS paths and on PATH. Every candidate is
returned so a launch failure (e.g. missing Linux shared libraries) can fall through to the next.

Transport: ``--remote-debugging-port=0``. The DevTools URL is read from Chrome's stderr
("DevTools listening on ws://...") with ``DevToolsActivePort`` as fallback; stderr works even for
sandboxed Snap builds whose private /tmp hides the profile dir. Pipe mode is not used because
Python cannot hand Chrome the fd 3/4 pipes on Windows.

Shutdown kills only the process tree of the ``Popen`` we started (psutil children of our own
PID, captured before the parent exits), never anything matched by name.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import RenderError
from .ffmpeg import NO_WINDOW, _pm_binary

ENV_VAR = "HYPE_CHROMIUM"
PROFILE_PREFIX = "sr-chrome-"

# Playwright 1.64 chromiumSwitches() disabled features (packages/playwright-core/src/server/chromium/
# chromiumSwitches.ts), minus Edge/Mac-only entries that are harmless either way.
DISABLED_FEATURES = (
    "AvoidUnnecessaryBeforeUnloadCheckSync", "DestroyProfileOnBrowserClose", "DialMediaRouteProvider",
    "GlobalMediaControls", "HttpsUpgrades", "LensOverlay", "MediaRouter", "PaintHolding",
    "ThirdPartyStoragePartitioning", "Translate", "AutoDeElevate", "OptimizationHints",
    "NetworkTimeServiceQuerying", "AimEnabled", "msForceBrowserSignIn", "msEdgeUpdateLaunchServicesPreferredVersion",
)

# Playwright's default switches + its headless extras (same source file and chromium.ts defaultArgs).
PLAYWRIGHT_SWITCHES = (
    "--disable-field-trial-config", "--disable-background-networking", "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows", "--disable-back-forward-cache", "--disable-breakpad",
    "--disable-client-side-phishing-detection", "--disable-component-extensions-with-background-pages",
    "--disable-component-update", "--no-default-browser-check", "--disable-default-apps",
    "--disable-dev-shm-usage", "--disable-edgeupdater", "--disable-extensions",
    "--disable-features=" + ",".join(DISABLED_FEATURES), "--enable-features=CDPScreenshotNewSurface",
    "--allow-pre-commit-input", "--disable-hang-monitor", "--disable-ipc-flooding-protection",
    "--disable-popup-blocking", "--disable-prompt-on-repost", "--disable-renderer-backgrounding",
    "--disable-updater-scheduler", "--force-color-profile=srgb", "--metrics-recording-only", "--no-first-run",
    "--password-store=basic", "--use-mock-keychain", "--no-service-autorun",
    "--disable-search-engine-choice-screen", "--unsafely-disable-devtools-self-xss-warnings",
    "--edge-skip-compat-layer-relaunch", "--disable-infobars", "--disable-sync", "--enable-unsafe-swiftshader",
    "--hide-scrollbars", "--mute-audio",
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4",
    # Playwright's chromiumSandbox defaults to false. We only load our own local pages with network
    # blocked, and the sandbox fails outright as root/in containers and with some ACL'd install dirs.
    "--no-sandbox",
)

# Ours: deterministic, frame-exact capture. Measured (research/wp-a-renderer.md): Playwright's
# CDPScreenshotNewSurface feature is worth ~+25 % fps. --disable-frame-rate-limit made seeks 3x
# faster but hung Page.captureScreenshot on Chromium 145 (software and GPU), so it is NOT used.
RENDER_SWITCHES = (
    "--headless=new", "--run-all-compositor-stages-before-draw", "--disable-checker-imaging",
    "--font-render-hinting=none", "--disable-lcd-text", "--disable-gpu-vsync",
    # Defence in depth next to per-page Fetch blocking: no hostname resolves (loopback IPs need none).
    "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1 , EXCLUDE localhost",
)

LINUX_LIBS_HINT = ("Chromium is missing system libraries. On Debian/Ubuntu: `sudo apt-get install -y libnss3 "
                   "libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 "
                   "libgbm1 libpango-1.0-0 libcairo2 libasound2` (Fedora: `sudo dnf install -y nss atk at-spi2-atk "
                   "cups-libs libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm pango cairo alsa-lib`).")
NO_BROWSER_HINT = ("Run `hermes pm install chromium`, install Google Chrome / Chromium / Microsoft Edge, "
                   "or set HYPE_CHROMIUM to a Chromium-based browser executable.")


# ----------------------------------------------------------------------------- resolve

@dataclass(frozen=True)
class BrowserCandidate:
    """A Chromium-family executable we may launch."""
    path: str
    source: str        # "env" | "pm" | "system"
    name: str          # "chromium" | "chrome" | "edge" | "brave" | "custom"


def _is_exe(p: str | Path) -> bool:
    path = Path(p)
    return path.is_file() and os.access(path, os.X_OK)


def system_browser_paths(platform: str, env: Mapping[str, str], home: Path) -> list[tuple[str, str]]:
    """Well-known install locations as (name, path), most preferred first."""
    out: list[tuple[str, str]] = []
    if platform.startswith("win"):
        roots = [env.get("PROGRAMFILES", r"C:\Program Files"), env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 env.get("LOCALAPPDATA", str(home / "AppData" / "Local"))]
        rel = [("chrome", r"Google\Chrome\Application\chrome.exe"), ("chromium", r"Chromium\Application\chrome.exe"),
               ("edge", r"Microsoft\Edge\Application\msedge.exe"),
               ("brave", r"BraveSoftware\Brave-Browser\Application\brave.exe")]
        for name, r in rel:
            out += [(name, str(Path(root) / r)) for root in roots if root]
    elif platform == "darwin":
        apps = [("chrome", "Google Chrome.app/Contents/MacOS/Google Chrome"),
                ("chromium", "Chromium.app/Contents/MacOS/Chromium"),
                ("edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                ("brave", "Brave Browser.app/Contents/MacOS/Brave Browser")]
        for name, a in apps:
            out += [(name, f"/Applications/{a}"), (name, str(home / "Applications" / a))]
    else:
        out += [("chrome", "/opt/google/chrome/chrome"), ("chrome", "/usr/bin/google-chrome"),
                ("chrome", "/usr/bin/google-chrome-stable"), ("chromium", "/usr/bin/chromium"),
                ("chromium", "/usr/bin/chromium-browser"), ("edge", "/usr/bin/microsoft-edge"),
                ("edge", "/opt/microsoft/msedge/msedge"), ("brave", "/usr/bin/brave-browser"),
                ("chromium", "/snap/bin/chromium")]
    return out


WHICH_NAMES = (("chrome", "google-chrome"), ("chrome", "google-chrome-stable"), ("chromium", "chromium"),
               ("chromium", "chromium-browser"), ("edge", "microsoft-edge"), ("edge", "msedge"),
               ("brave", "brave-browser"), ("chrome", "chrome"))


def browser_candidates(env: Mapping[str, str] | None = None, *, platform: str = sys.platform,
                       home: Path | None = None,
                       pm_lookup: Callable[[str], Path | None] = _pm_binary,
                       which: Callable[[str], str | None] = shutil.which,
                       is_exe: Callable[[str], bool] = _is_exe) -> list[BrowserCandidate]:
    """All usable browsers in preference order. Raises ``bad_env_browser`` for a broken override."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    override = env.get(ENV_VAR, "").strip()
    if override:
        if not is_exe(override):
            raise RenderError("bad_env_browser", f"{ENV_VAR}={override!r} is not an executable file",
                              hint=f"Fix or unset {ENV_VAR}.")
        return [BrowserCandidate(override, "env", "custom")]
    out: list[BrowserCandidate] = []
    seen: set[str] = set()

    def add(path: str, source: str, name: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen and is_exe(path):
            seen.add(key)
            out.append(BrowserCandidate(path, source, name))

    pm_path = pm_lookup("chromium")
    if pm_path is not None:
        add(str(pm_path), "pm", "chromium")
    for name, p in system_browser_paths(platform, env, home):
        add(p, "system", name)
    for name, exe in WHICH_NAMES:
        if w := which(exe):
            add(w, "system", name)
    return out


def resolve_chromium(env: Mapping[str, str] | None = None, **kw) -> BrowserCandidate:
    """The preferred browser. Raises :class:`RenderError` ``no_browser`` with an install hint."""
    cands = browser_candidates(env, **kw)
    if not cands:
        raise RenderError("no_browser", "no Chromium-based browser found", hint=NO_BROWSER_HINT)
    return cands[0]


# ------------------------------------------------------------------------------- flags

def build_flags(*, gpu: bool, window_size: tuple[int, int], user_data_dir: Path,
                extra: Sequence[str] = ()) -> list[str]:
    """Full Chromium argument list (without the executable)."""
    w, h = window_size
    flags = [*PLAYWRIGHT_SWITCHES, *RENDER_SWITCHES, f"--window-size={w},{h}", "--remote-debugging-port=0",
             f"--user-data-dir={user_data_dir}"]
    if not gpu:
        flags.append("--disable-gpu")
    flags += list(extra)
    flags.append("about:blank")
    return flags


# ------------------------------------------------------------------------------ launch

_LIVE: set[LaunchedBrowser] = set()
_LIVE_LOCK = threading.Lock()
_WS_RE = re.compile(r"DevTools listening on (ws://\S+)")


@dataclass(eq=False)
class LaunchedBrowser:
    """A running browser we own. Always call :meth:`kill` (idempotent) when done."""
    candidate: BrowserCandidate
    proc: subprocess.Popen[bytes]
    ws_url: str
    profile_dir: Path
    gpu: bool
    flags: list[str]
    _stderr: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    _kids: set[Any] = field(default_factory=set)      # psutil.Process snapshots of our descendants
    _killed: bool = False

    @property
    def pid(self) -> int:
        return self.proc.pid

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stderr_tail(self, n: int = 20) -> str:
        return "\n".join(list(self._stderr)[-n:])

    def remember_children(self) -> None:
        """Snapshot our descendants (used at kill time even if the parent already died)."""
        import psutil

        try:
            self._kids.update(psutil.Process(self.proc.pid).children(recursive=True))
        except psutil.Error:
            pass

    def kill(self, wait_s: float = 0.0) -> None:
        """Stop our browser tree and delete the profile dir. ``wait_s``: grace after ``Browser.close``."""
        if self._killed:
            return
        self._killed = True
        with _LIVE_LOCK:
            _LIVE.discard(self)
        self.remember_children()
        kill_tree(self.proc, self._kids, wait_s=wait_s)
        for _ in range(10):  # Windows keeps files locked briefly after exit
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            if not self.profile_dir.exists():
                break
            time.sleep(0.2)


def kill_tree(proc: subprocess.Popen[bytes], kids: Iterable[Any] = (), *, wait_s: float = 0.0) -> None:
    """Terminate ``proc`` and the given descendants (all captured from our own Popen PID)."""
    import psutil

    kids = list(kids)
    if proc.poll() is None:
        try:
            kids += psutil.Process(proc.pid).children(recursive=True)
        except psutil.Error:
            pass
        try:
            proc.wait(timeout=wait_s) if wait_s > 0 else None
        except subprocess.TimeoutExpired:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    # psutil.Process.kill() re-checks create_time, so a recycled PID is never signalled.
    alive = []
    for k in {k.pid: k for k in kids}.values():
        try:
            k.kill()
            alive.append(k)
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=5)


def _kill_all_live() -> None:
    with _LIVE_LOCK:
        live = list(_LIVE)
    for b in live:
        try:
            b.kill()
        except Exception:
            pass


atexit.register(_kill_all_live)


def prune_stale_profiles(root: Path, max_age_s: float = 6 * 3600) -> None:
    """Remove our own leftover profile dirs (prefix ``sr-chrome-``) older than ``max_age_s``."""
    try:
        entries = list(root.glob(PROFILE_PREFIX + "*"))
    except OSError:
        return
    now = time.time()
    for p in entries:
        try:
            if p.is_dir() and now - p.stat().st_mtime > max_age_s:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def _launch_hint(stderr: str) -> str:
    if "error while loading shared libraries" in stderr or "cannot open shared object" in stderr:
        return LINUX_LIBS_HINT
    if "Missing X server" in stderr or "cannot open display" in stderr:
        return "Chromium tried to open a display; make sure it supports --headless=new (Chrome >= 112)."
    return "Try another browser via HYPE_CHROMIUM, or `hermes pm install chromium`."


def launch(candidate: BrowserCandidate, *, gpu: bool, window_size: tuple[int, int] = (1920, 1080),
           profile_root: Path | None = None, timeout_s: float = 45.0,
           extra_flags: Sequence[str] = ()) -> LaunchedBrowser:
    """Start ``candidate`` headless with an isolated temp profile; return once DevTools is listening."""
    root = Path(profile_root) if profile_root else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    prune_stale_profiles(root)
    profile = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX, dir=root))
    flags = build_flags(gpu=gpu, window_size=window_size, user_data_dir=profile, extra=extra_flags)
    try:
        proc = subprocess.Popen([candidate.path, *flags], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    except OSError as e:
        shutil.rmtree(profile, ignore_errors=True)
        raise RenderError("browser_launch", f"cannot start {candidate.path}: {e}", hint=_launch_hint(str(e))) from e
    browser = LaunchedBrowser(candidate, proc, "", profile, gpu, flags)
    with _LIVE_LOCK:
        _LIVE.add(browser)
    found = threading.Event()

    def pump() -> None:
        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            browser._stderr.append(line)
            if not found.is_set() and (m := _WS_RE.search(line)):
                browser.ws_url = m.group(1)
                found.set()

    threading.Thread(target=pump, name=f"chrome-stderr-{proc.pid}", daemon=True).start()
    deadline = time.monotonic() + timeout_s
    port_file = profile / "DevToolsActivePort"
    while not found.wait(0.05):
        if proc.poll() is not None:
            time.sleep(0.2)  # let the pump collect the last lines
            tail = browser.stderr_tail()
            browser.kill()
            raise RenderError("browser_launch", f"{candidate.name} exited during startup (code {proc.returncode})",
                              hint=_launch_hint(tail), browser=candidate.path, stderr=tail[-1500:])
        if port_file.exists():
            try:
                port, path = port_file.read_text(encoding="utf-8").split()[:2]
                browser.ws_url = f"ws://127.0.0.1:{port}{path}"
                break
            except (OSError, ValueError):
                pass
        if time.monotonic() > deadline:
            tail = browser.stderr_tail()
            browser.kill()
            raise RenderError("browser_launch", f"{candidate.name} did not open DevTools within {timeout_s:.0f}s",
                              hint=_launch_hint(tail), browser=candidate.path, stderr=tail[-1500:])
    return browser


def launch_any(candidates: Iterable[BrowserCandidate], **kw) -> LaunchedBrowser:
    """Launch the first candidate that starts; raise the last error with all attempts listed."""
    errors: list[dict] = []
    last: RenderError | None = None
    for c in candidates:
        try:
            return launch(c, **kw)
        except RenderError as e:
            errors.append({"browser": c.path, **e.to_dict()})
            last = e
    if last is None:
        raise RenderError("no_browser", "no Chromium-based browser found", hint=NO_BROWSER_HINT)
    raise RenderError("browser_launch", f"no browser could be launched ({len(errors)} tried)",
                      hint=last.hint, attempts=errors)
