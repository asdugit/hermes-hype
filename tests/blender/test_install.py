"""Optional Blender install (showreel_core/blender/install.py + the doctor/CLI offers): no real downloads here.

Fake archives with matching checksums go through the real download/verify/unpack/rename path, served by a
monkeypatched opener or a real loopback HTTP server. The one real download of the pinned build is a dev-machine
run (research/w5-blender-install.md), never part of the suite.
"""
from __future__ import annotations

import hashlib
import http.server
import io
import os
import tarfile
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from showreel_core import doctor
from showreel_core.blender import install as bi
from showreel_core.blender import locate as loc

VER = "9.9.9"


def _zip(top: str = f"blender-{VER}-windows-x64", extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{top}/blender.exe", b"MZ fake blender")
        zf.writestr(f"{top}/9.9/scripts/startup/x.py", b"print('hi')\n")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def _tar_xz(top: str = f"blender-{VER}-linux-x64") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name, data, mode in ((f"{top}/blender", b"#!/bin/sh\necho Blender 9.9.9\n", 0o755),
                                 (f"{top}/9.9/scripts/x.py", b"x = 1\n", 0o644)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _build(data: bytes, key: str = "windows-x64", *, sha: str | None = None, url: str = "") -> bi.Build:
    ext = ".zip" if key.startswith("windows") else ".tar.xz"
    return bi.Build(key, VER, f"blender-{VER}-{key}{ext}", sha or hashlib.sha256(data).hexdigest(), len(data),
                    url=url or f"https://example.invalid/blender-{VER}-{key}{ext}")


class _Resp(io.BytesIO):
    def __init__(self, data: bytes, length: int | None = None) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


def _opener(data: bytes, length: int | None = None, calls: list[str] | None = None) -> Any:
    def go(req: Any, timeout: float) -> _Resp:
        if calls is not None:
            calls.append(req.full_url)
        return _Resp(data, length)
    return go


def _probe(exe: Path) -> str | None:
    return VER if exe.is_file() else None


def _kw(**extra: Any) -> dict[str, Any]:
    return {"probe": _probe, "disk_free": lambda p: 10 ** 12, **extra}


def _leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".hype-blender-"))


# ---------------------------------------------------------------------------------------- pins + layout

def test_pinned_builds_are_official_lts_with_checksums() -> None:
    assert set(bi.BUILDS) == {"windows-x64", "windows-arm64", "macos-arm64", "macos-x64", "linux-x64"}
    for b in bi.BUILDS.values():
        assert b.href.startswith("https://download.blender.org/release/Blender") and b.href.endswith(b.file)
        assert len(b.sha256) == 64 and int(b.sha256, 16) >= 0
        assert b.size > 100_000_000 and b.version.rsplit(".", 1)[0] in ("5.2", "4.5")   # LTS series only
        assert b.file.startswith(f"blender-{b.version}-{b.key}")
    assert bi.BUILDS["macos-x64"].version.startswith("4.5")      # Blender 5.x has no Intel-Mac build


@pytest.mark.parametrize(("system", "machine", "key"), [
    ("Windows", "AMD64", "windows-x64"), ("Windows", "ARM64", "windows-arm64"), ("Darwin", "arm64", "macos-arm64"),
    ("Darwin", "x86_64", "macos-x64"), ("Linux", "x86_64", "linux-x64"), ("Linux", "aarch64", None),
    ("FreeBSD", "amd64", None)])
def test_platform_key(system: str, machine: str, key: str | None) -> None:
    assert bi.platform_key(system, machine) == key


@pytest.mark.parametrize(("key", "platform"), [("windows-x64", "win32"), ("macos-arm64", "darwin"),
                                               ("linux-x64", "linux")])
def test_install_target_is_where_locate_looks(tmp_path: Path, key: str, platform: str) -> None:
    b = bi.BUILDS[key]
    env, home = {"LOCALAPPDATA": str(tmp_path / "Local")}, tmp_path / "home"
    exe = bi.executable_in(bi.default_parent(b, env, home) / bi.target_name(b), b)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    found = loc.standard_locations(platform, env, home=home)
    found = [p for p in found if str(p).startswith(str(tmp_path))]   # not the runner's own /Applications, /opt, ...
    assert found == [exe]


def test_question_names_version_size_and_source() -> None:
    q = bi.question(bi.BUILDS["windows-x64"])
    assert "Blender 5.2.4" in q and "~406 MB" in q and "download.blender.org" in q and "checksum" in q
    assert q.rstrip().endswith("[y/N]")


# ------------------------------------------------------------------------------------------------ install

def test_install_zip_verifies_unpacks_and_renames_in_one_step(tmp_path: Path) -> None:
    data = _zip()
    seen: list[tuple[str, int, int]] = []
    res = bi.install(build=_build(data), parent=tmp_path, opener=_opener(data),
                     progress=lambda s, d, t: seen.append((s, d, t)), **_kw())
    target = tmp_path / f"Blender {VER[:3]}"
    assert res == {"path": str(target / "blender.exe"), "version": VER, "target": str(target), "skipped": False}
    assert (target / "9.9" / "scripts" / "startup" / "x.py").is_file()
    assert _leftovers(tmp_path) == []
    stages = [s for s, _, _ in seen]
    assert stages.index("download") < stages.index("verify") < stages.index("unpack") < stages.index("check")
    assert ("download", len(data), len(data)) in seen


@pytest.mark.skipif(not hasattr(tarfile, "data_filter"), reason="needs tarfile filters (3.11.4+)")
def test_install_tar_xz_keeps_the_executable_bit(tmp_path: Path) -> None:
    data = _tar_xz()
    res = bi.install(build=_build(data, "linux-x64"), parent=tmp_path, opener=_opener(data), **_kw())
    exe = Path(res["path"])
    assert exe == tmp_path / f"blender-{VER}" / "blender" and exe.is_file()
    if os.name != "nt":
        assert os.access(exe, os.X_OK)


def _tar_xz_with_links(top: str = f"blender-{VER}-linux-x64") -> bytes:
    """Like the real Linux tarball: shared-library symlinks and a hard link, read back as one stream."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name, data, mode in ((f"{top}/blender", b"#!/bin/sh\necho Blender 9.9.9\n", 0o755),
                                 (f"{top}/lib/libx.so.1", b"ELF fake lib", 0o644)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
        sym = tarfile.TarInfo(f"{top}/lib/libx.so")
        sym.type, sym.linkname = tarfile.SYMTYPE, "libx.so.1"
        tf.addfile(sym)
        hard = tarfile.TarInfo(f"{top}/blender-softwaregl")
        hard.type, hard.linkname = tarfile.LNKTYPE, f"{top}/blender"
        tf.addfile(hard)
    return buf.getvalue()


@pytest.mark.skipif(os.name == "nt" or not hasattr(tarfile, "data_filter"),
                    reason="the Linux build is only installed on POSIX (symlinks); needs tarfile filters")
def test_install_tar_xz_streams_symlinks_and_hard_links_in_one_pass(tmp_path: Path) -> None:
    data = _tar_xz_with_links()
    seen: list[tuple[str, int, int]] = []
    res = bi.install(build=_build(data, "linux-x64"), parent=tmp_path, opener=_opener(data),
                     progress=lambda stage, done, total: seen.append((stage, done, total)), **_kw())
    target = Path(res["target"])
    assert (target / "lib" / "libx.so").is_symlink() and (target / "lib" / "libx.so").read_bytes() == b"ELF fake lib"
    assert (target / "blender-softwaregl").read_bytes() == (target / "blender").read_bytes()
    unpack = [(d, t) for s, d, t in seen if s == "unpack"]
    assert unpack and unpack[-1] == (len(data), len(data))           # progress = compressed bytes, ends at 100 %
    assert [d for d, _ in unpack] == sorted(d for d, _ in unpack)     # one forward pass, never back


def test_unsafe_tar_paths_are_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"pwned"))
    data = buf.getvalue()
    with pytest.raises(bi.InstallError, match="unsafe path"):
        bi.install(build=_build(data, "linux-x64"), parent=tmp_path / "in", opener=_opener(data), **_kw())
    assert not (tmp_path / "evil.txt").exists() and list((tmp_path / "in").iterdir()) == []


def test_checksum_mismatch_is_refused_and_leaves_nothing(tmp_path: Path) -> None:
    data = _zip()
    with pytest.raises(bi.InstallError, match="checksum mismatch"):
        bi.install(build=_build(data, sha="0" * 64), parent=tmp_path, opener=_opener(data), **_kw())
    assert list(tmp_path.iterdir()) == []


def test_staging_left_by_a_killed_install_is_swept(tmp_path: Path) -> None:
    """A killed install (power off, kill -9) never runs its finally: its ~400 MB staging folder stayed forever and
    every retry added another. Stale ones (a day old) go on the next install; fresh ones and strangers stay."""
    import os
    import time as _t

    stale = tmp_path / ".hype-blender-5.2.4-dead"
    (stale / "unpacked").mkdir(parents=True)
    (stale / "blender-5.2.4-windows-x64.zip").write_bytes(b"x" * 100)
    old = _t.time() - 2 * 86400
    os.utime(stale, (old, old))
    fresh = tmp_path / ".hype-blender-5.2.4-running"
    fresh.mkdir()
    other = tmp_path / "my-stuff"
    other.mkdir()
    os.utime(other, (old, old))
    data = _zip()
    res = bi.install(build=_build(data), parent=tmp_path, opener=_opener(data), **_kw())
    assert not res["skipped"]
    assert not stale.exists() and fresh.is_dir() and other.is_dir()


def test_existing_install_is_skipped_without_downloading(tmp_path: Path) -> None:
    data = _zip()
    exe = tmp_path / f"Blender {VER[:3]}" / "blender.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    calls: list[str] = []
    res = bi.install(build=_build(data), parent=tmp_path, opener=_opener(data, calls=calls), **_kw())
    assert res["skipped"] and res["path"] == str(exe) and calls == []


def test_an_existing_folder_without_blender_is_never_touched(tmp_path: Path) -> None:
    data = _zip()
    keep = tmp_path / f"Blender {VER[:3]}" / "notes.txt"
    keep.parent.mkdir()
    keep.write_text("mine")
    with pytest.raises(bi.InstallError, match="never writes over"):
        bi.install(build=_build(data), parent=tmp_path, opener=_opener(data), **_kw())
    assert keep.read_text() == "mine" and sorted(p.name for p in keep.parent.iterdir()) == ["notes.txt"]


def test_cancel_during_download_leaves_nothing(tmp_path: Path) -> None:
    data = _zip()
    stop = threading.Event()

    def progress(stage: str, done: int, total: int) -> None:
        stop.set()                     # the user pressed Cancel after the first chunk

    big = data + b"\0" * (3 * bi.CHUNK)
    with pytest.raises(bi.InstallCancelled):
        bi.install(build=_build(big), parent=tmp_path, opener=_opener(big), progress=progress, cancel=stop, **_kw())
    assert list(tmp_path.iterdir()) == []


def test_truncated_download_is_an_error(tmp_path: Path) -> None:
    data = _zip()
    with pytest.raises(bi.InstallError, match="stopped at"):
        bi.install(build=_build(data), parent=tmp_path, opener=_opener(data, length=len(data) + 999), **_kw())
    assert list(tmp_path.iterdir()) == []


def test_network_errors_read_as_one_clear_message(tmp_path: Path) -> None:
    def boom(req: Any, timeout: float) -> Any:
        raise OSError("Connection refused")
    with pytest.raises(bi.InstallError, match="Connection refused.*proxy"):
        bi.install(build=_build(b"x"), parent=tmp_path, opener=boom, **_kw())
    assert list(tmp_path.iterdir()) == []


def test_unsafe_archive_paths_are_refused(tmp_path: Path) -> None:
    data = _zip(extra={"../evil.txt": b"pwned"})
    with pytest.raises(bi.InstallError, match="unsafe path"):
        bi.install(build=_build(data), parent=tmp_path / "in", opener=_opener(data), **_kw())
    assert not (tmp_path / "evil.txt").exists() and list((tmp_path / "in").iterdir()) == []


def test_a_corrupt_archive_with_a_matching_checksum_is_a_clear_error(tmp_path: Path) -> None:
    data = b"PK\x03\x04 not really a zip" * 10
    with pytest.raises(bi.InstallError, match="unpacking .* failed"):
        bi.install(build=_build(data), parent=tmp_path, opener=_opener(data), **_kw())
    data = b"\xfd7zXZ\x00 not really xz" * 10
    with pytest.raises(bi.InstallError, match="unpacking .* failed"):
        bi.install(build=_build(data, "linux-x64"), parent=tmp_path, opener=_opener(data), **_kw())
    assert list(tmp_path.iterdir()) == []


def test_a_blender_that_does_not_run_is_removed_again(tmp_path: Path) -> None:
    data = _zip()
    with pytest.raises(bi.InstallError, match="did not answer"):
        bi.install(build=_build(data), parent=tmp_path, opener=_opener(data),
                   **_kw(probe=lambda exe: None))
    assert list(tmp_path.iterdir()) == []


def test_not_enough_disk_space_stops_before_the_download(tmp_path: Path) -> None:
    calls: list[str] = []
    with pytest.raises(bi.InstallError, match="disk space"):
        bi.install(build=_build(_zip()), parent=tmp_path, opener=_opener(b"", calls=calls),
                   **_kw(disk_free=lambda p: 1000))
    assert calls == []


def test_download_over_real_http_from_a_loopback_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _zip()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/blender.zip"
        res = bi.install(build=_build(data, url=url), parent=tmp_path, **_kw())
    finally:
        srv.shutdown()
    assert Path(res["path"]).is_file() and not res["skipped"]


def test_background_install_reports_progress_then_done(tmp_path: Path) -> None:
    data = _zip()
    bi._STATE.data = {"state": "idle"}
    first = bi.start_background(build=_build(data), parent=tmp_path, opener=_opener(data), **_kw())
    assert first["state"] in ("running", "done")
    st = bi.status()
    for _ in range(200):
        st = bi.status()
        if st["state"] != "running":
            break
        threading.Event().wait(0.02)
    assert st["state"] == "done" and st["pct"] == 100 and st["path"].endswith("blender.exe"), st
    bi._STATE.data = {"state": "idle"}


# ---------------------------------------------------------------------------------------------- prompting

class _Tty:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize(("env", "tty", "ok"), [
    ({}, True, True), ({}, False, False), ({"CI": "true"}, True, False), ({"GITHUB_ACTIONS": "true"}, True, False),
    ({"HERMES_CRON_SESSION": "1"}, True, False), ({"HERMES_GATEWAY_SESSION": "1"}, True, False),
    ({"HERMES_SESSION_SOURCE": "telegram"}, True, False), ({"HERMES_SESSION_SOURCE": "cli"}, True, True),
    ({"HERMES_SESSION_SOURCE": "desktop"}, True, True), ({"HERMES_SESSION_SOURCE": "kanban"}, True, False),
    ({"HYPE_NO_PROMPT": "1"}, True, False), ({"CI": "0"}, True, True)])
def test_can_prompt_only_for_a_person_at_a_terminal(env: dict[str, str], tty: bool, ok: bool) -> None:
    assert bi.can_prompt(_Tty(tty), _Tty(tty), env) is ok


def test_can_prompt_needs_both_streams_to_be_terminals() -> None:
    assert not bi.can_prompt(_Tty(True), _Tty(False), {}) and not bi.can_prompt(_Tty(False), _Tty(True), {})


@pytest.mark.parametrize(("answer", "want"), [("y\n", True), ("YES\n", True), ("\n", False), ("n\n", False),
                                              ("", False), ("maybe\n", False)])
def test_ask_yes_no_defaults_to_no(answer: str, want: bool) -> None:
    out: list[str] = []
    assert bi.ask_yes_no("Install? [y/N] ", read=lambda: answer, write=out.append) is want
    assert out == ["Install? [y/N] "]


def test_ask_yes_no_times_out_as_no_answer() -> None:
    hold = threading.Event()
    out: list[str] = []
    try:
        assert bi.ask_yes_no("Q? ", timeout_s=0.2, read=lambda: (hold.wait(5), "y\n")[1], write=out.append) is None
    finally:
        hold.set()
    assert "no answer" in out[-1]


# ------------------------------------------------------------------------------------- doctor + CLI offers

def _rep(*missing: str) -> dict[str, Any]:
    names = ("python", "ffmpeg", "chromium", "blender")
    return {"ok": not ({"ffmpeg", "chromium"} & set(missing)), "version": "0", "platform": "test",
            "checks": [{"name": n, "ok": n not in missing, "required": n != "blender", "detail": "", "hint": ""}
                       for n in names]}


def test_offer_installs_never_asks_without_a_terminal() -> None:
    def ask(q: str) -> bool:
        raise AssertionError("asked a question in an unattended run")
    assert doctor.offer_installs(_rep("ffmpeg", "blender"), prompt_ok=False, ask=ask) is False


def test_offer_installs_runs_hermes_pm_and_the_blender_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_explicit_setting", lambda: False)
    monkeypatch.setattr(doctor, "hermes_command", lambda: ["hermes"])
    asked: list[str] = []
    ran: list[list[str]] = []
    blender: list[dict[str, Any]] = []
    answers = iter([True, False])

    def ask(q: str) -> bool:
        asked.append(q)
        return next(answers)

    changed = doctor.offer_installs(
        _rep("ffmpeg", "chromium", "blender"), prompt_ok=True, ask=ask, out=lambda *a: None,
        run=lambda cmd: ran.append(cmd) or SimpleNamespace(returncode=0),
        install_blender=lambda **kw: blender.append(kw) or 0)
    assert changed and ran == [["hermes", "pm", "install", "ffmpeg"]]
    assert "hermes pm install ffmpeg" in asked[0] and "hermes pm install chromium" in asked[1]
    assert len(blender) == 1 and blender[0]["prompt_ok"] is True


def test_offer_installs_stops_asking_after_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_explicit_setting", lambda: False)
    asked: list[str] = []
    changed = doctor.offer_installs(_rep("ffmpeg", "chromium", "blender"), prompt_ok=True,
                                    ask=lambda q: asked.append(q), out=lambda *a: None,
                                    run=lambda cmd: pytest.fail("ran an install after a timeout"),
                                    install_blender=lambda **kw: pytest.fail("offered Blender after a timeout"))
    assert changed is False and len(asked) == 1


def _no_blender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loc, "locate", lambda *a, **k: loc.BlenderMissing("not_found", "Blender was not found."))
    monkeypatch.setattr(doctor, "_explicit_setting", lambda: False)


def test_install_blender_cli_without_a_terminal_prints_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_blender(monkeypatch)
    out: list[str] = []
    code = doctor.install_blender_cli(prompt_ok=False, out=out.append,
                                      installer=lambda **kw: pytest.fail("installed without asking"))
    assert code == 2 and "hermes hype install-blender --yes" in out[-1]


def test_install_blender_cli_no_means_no(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_blender(monkeypatch)
    out: list[str] = []
    code = doctor.install_blender_cli(prompt_ok=True, ask=lambda q: False, out=out.append,
                                      installer=lambda **kw: pytest.fail("installed after a no"))
    assert code == 1 and out[-1] == "Blender was not installed."


def test_install_blender_cli_yes_installs_into_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_blender(monkeypatch)
    got: list[dict[str, Any]] = []
    out: list[str] = []
    code = doctor.install_blender_cli(yes=True, parent=str(tmp_path), out=out.append,
                                      installer=lambda **kw: got.append(kw) or {
                                          "path": str(tmp_path / "b" / "blender.exe"), "version": VER,
                                          "skipped": False})
    assert code == 0 and got[0]["parent"] == str(tmp_path) and got[0]["build"] is bi.build_for()
    assert any("HYPE_BLENDER=" in line for line in out)


def test_install_blender_cli_with_blender_present_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    found = loc.BlenderFound(path=Path("C:/b/blender.exe"), version=(5, 2, 4), version_string="5.2.4", source="std")
    monkeypatch.setattr(loc, "locate", lambda *a, **k: found)
    out: list[str] = []
    assert doctor.install_blender_cli(yes=True, out=out.append,
                                      installer=lambda **kw: pytest.fail("reinstalled")) == 0
    assert "already installed" in out[-1]


def test_doctor_json_and_no_prompt_never_offer(monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    from showreel_core import handlers
    monkeypatch.setattr(doctor, "doctor_report", lambda ctx=None: _rep("blender"))
    monkeypatch.setattr(doctor, "offer_installs", lambda rep, **k: pytest.fail("offered installs"))
    for flags in ({"json": True, "no_prompt": False}, {"json": False, "no_prompt": True}):
        assert handlers.cli(None, SimpleNamespace(hype_cmd="doctor", **flags)) == 0
    capsys.readouterr()


def test_chat_blender_request_gets_one_line_hint_and_never_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    from showreel_core import handlers
    monkeypatch.setattr(loc, "locate", lambda *a, **k: loc.BlenderMissing("not_found", "Blender was not found."))
    line = handlers.blender_missing_line()
    assert line.count("\n") == 1 and "hermes hype install-blender" in line and "browser" in line
    found = loc.BlenderFound(path=Path("C:/b/blender.exe"), version=(5, 2, 4), version_string="5.2.4", source="std")
    monkeypatch.setattr(loc, "locate", lambda *a, **k: found)
    assert handlers.blender_missing_line() == ""


def test_the_install_hint_no_longer_claims_the_blender_plugin_installs_it() -> None:
    assert "hermes hype install-blender" in loc.INSTALL_HINT
    assert "plugins install blender" not in loc.INSTALL_HINT
