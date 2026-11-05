"""Chromium resolution, flags, launch failure handling and own-tree shutdown."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from showreel_core.render import chromium as cr
from showreel_core.render.errors import RenderError


def _resolver(**over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = dict(env={}, platform="linux", home=Path("/home/u"), pm_lookup=lambda name: None,
              which=lambda name: None, is_exe=lambda p: False)
    kw.update(over)
    return kw


def test_env_override_wins():
    cands = cr.browser_candidates(**_resolver(env={cr.ENV_VAR: "/opt/my chrome/chrome"},
                                              pm_lookup=lambda n: Path("/pm/chrome"), is_exe=lambda p: True))
    assert [(c.path, c.source) for c in cands] == [("/opt/my chrome/chrome", "env")]


def test_env_override_invalid_is_an_error():
    with pytest.raises(RenderError) as ei:
        cr.browser_candidates(**_resolver(env={cr.ENV_VAR: "/nope"}))
    assert ei.value.code == "bad_env_browser"


def test_pm_before_system_and_dedupe():
    existing = {"/pm/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"}
    cands = cr.browser_candidates(**_resolver(
        pm_lookup=lambda n: Path("/pm/chrome") if n == "chromium" else None,
        which=lambda n: "/usr/bin/chromium" if n == "chromium" else None,
        is_exe=lambda p: Path(p).as_posix() in existing))
    assert [Path(c.path).as_posix() for c in cands] == ["/pm/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"]
    assert [c.source for c in cands] == ["pm", "system", "system"]


def test_pm_import_absent_is_tolerated(monkeypatch):
    monkeypatch.setitem(sys.modules, "pm", None)  # import pm -> ImportError
    from showreel_core.render.ffmpeg import _pm_binary
    assert _pm_binary("chromium") is None


@pytest.mark.parametrize("platform,needle", [
    ("win32", r"Google\Chrome\Application\chrome.exe"),
    ("win32", r"Microsoft\Edge\Application\msedge.exe"),
    ("darwin", "Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("linux", "/usr/bin/chromium-browser"),
])
def test_system_paths_per_os(platform, needle):
    env = {"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
           "LOCALAPPDATA": r"C:\Users\ü s\AppData\Local"}
    paths = [p for _, p in cr.system_browser_paths(platform, env, Path("/Users/u"))]
    assert any(needle in p for p in paths)


def test_no_browser_error_has_hint():
    with pytest.raises(RenderError) as ei:
        cr.resolve_chromium(**_resolver())
    assert ei.value.code == "no_browser"
    assert "hermes pm install chromium" in ei.value.hint


def test_build_flags():
    f = cr.build_flags(gpu=False, window_size=(1080, 1920), user_data_dir=Path("/tmp/p q"))
    for flag in ("--headless=new", "--run-all-compositor-stages-before-draw", "--force-color-profile=srgb",
                 "--hide-scrollbars", "--font-render-hinting=none", "--disable-lcd-text", "--mute-audio",
                 "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--enable-unsafe-swiftshader",
                 "--enable-features=CDPScreenshotNewSurface", "--remote-debugging-port=0", "--disable-gpu",
                 "--window-size=1080,1920", "--no-sandbox"):
        assert flag in f, flag
    assert f"--user-data-dir={Path('/tmp/p q')}" in f
    assert f[-1] == "about:blank"
    assert "--disable-frame-rate-limit" not in f  # hangs captureScreenshot on Chromium 145
    assert any(x.startswith("--disable-features=") and "PaintHolding" in x for x in f)
    assert "--disable-gpu" not in cr.build_flags(gpu=True, window_size=(1, 1), user_data_dir=Path("x"))


def test_host_resolver_rule_keeps_loopback():
    rule = next(f for f in cr.RENDER_SWITCHES if f.startswith("--host-resolver-rules="))
    assert "EXCLUDE 127.0.0.1" in rule


def test_launch_hint_for_missing_libs():
    assert "apt-get" in cr._launch_hint("chrome: error while loading shared libraries: libatk-1.0.so.0")


def test_launch_failure_is_structured(tmp_path):
    # The Python interpreter rejects Chrome's flags and exits: a stand-in for a broken browser.
    cand = cr.BrowserCandidate(sys.executable, "env", "custom")
    with pytest.raises(RenderError) as ei:
        cr.launch(cand, gpu=False, window_size=(64, 64), profile_root=tmp_path, timeout_s=20)
    assert ei.value.code == "browser_launch"
    assert not list(tmp_path.glob(cr.PROFILE_PREFIX + "*"))  # profile cleaned up


def test_launch_any_reports_all_attempts(tmp_path):
    cand = cr.BrowserCandidate(sys.executable, "env", "custom")
    with pytest.raises(RenderError) as ei:
        cr.launch_any([cand, cand], gpu=False, window_size=(64, 64), profile_root=tmp_path, timeout_s=20)
    assert ei.value.code == "browser_launch"
    assert len(ei.value.details["attempts"]) == 2


def test_kill_tree_kills_only_our_descendants():
    import psutil

    code = ("import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)")
    parent = subprocess.Popen([sys.executable, "-c", code])
    try:
        deadline = time.time() + 10
        kids = []
        while time.time() < deadline and not kids:
            kids = psutil.Process(parent.pid).children(recursive=True)
            time.sleep(0.1)
        assert kids, "child did not start"
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        cr.kill_tree(parent)
        assert parent.poll() is not None
        assert all(not k.is_running() or k.status() == psutil.STATUS_ZOMBIE for k in kids)
        assert bystander.poll() is None  # not ours to kill
    finally:
        for p in (parent,):
            if p.poll() is None:
                p.kill()
        bystander.kill()


def test_prune_stale_profiles_only_touches_our_prefix(tmp_path):
    import os

    ours = tmp_path / (cr.PROFILE_PREFIX + "old")
    other = tmp_path / "someone-else"
    ours.mkdir()
    other.mkdir()
    old = time.time() - 10 * 3600
    os.utime(ours, (old, old))
    os.utime(other, (old, old))
    cr.prune_stale_profiles(tmp_path)
    assert not ours.exists() and other.exists()
