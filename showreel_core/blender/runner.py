"""Run one Blender scene module headlessly via the job.json protocol (BLENDER.md "Runner" / "job.json").

    blender -b --factory-startup --python-exit-code 1 -P blender_kits/lib/entry.py -- <job.json>

* Our own ``Popen`` (argument list, no shell); cancel kills ONLY that process tree (psutil children of the PID
  we spawned, checked against the creation time we recorded) — never anything matched by name.
* Progress from the ``SR_*`` protocol lines (``SR_BUILD_DONE``, ``SR_FRAME f s``, ``SR_DONE``, ``SR_ERROR``).
* Failure detection does not trust the exit code: Blender can exit 0 after a script crash, so the output is
  scanned for Python tracebacks and a missing ``SR_DONE`` is an error too.
* Every frame is verified (exists, decodes, not blank) and runs are resumable: verified frames are skipped.
* ``frames=[...]`` renders only those frames (keyframes for critique, the 3-frame benchmark).
Zero third-party runtime deps beyond Hermes core (psutil/Pillow are used when importable).
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .locate import BlenderFound, child_env

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = REPO_ROOT / "blender_kits"
ENTRY = KIT_ROOT / "lib" / "entry.py"
TIERS = ("preview", "final", "max")
PROTOCOL_VERSION = 1
STALL_S = 900.0                      # no output line for this long = hung Blender
_LINE_RE = re.compile(r"^SR_(START|BUILD_DONE|FRAME|DONE|ERROR)\b\s*(.*)$")
_TRACEBACK = "Traceback (most recent call last)"

ProgressCB = Callable[[dict[str, Any]], None]
Cancel = Callable[[], bool] | threading.Event | None


# ------------------------------------------------------------------------------------------- job.json

def make_job(scene: Path | str, out_dir: Path | str, *, dur: float, fps: int = 30, res: Sequence[int] = (1920, 1080),
             params: dict[str, Any] | None = None, seed: int = 7, tier: str = "preview", frames: Sequence[int] | None = None,
             alpha: bool = False, assets: dict[str, dict[str, Any]] | None = None, product: str | None = None,
             handoff: dict[str, Any] | None = None, handles: Sequence[float] = (0.0, 0.0), aspect: str | None = None,
             out_ext: str | None = None, save_blend: bool = False, kit_root: Path | str | None = None) -> dict[str, Any]:
    """A job.json dict (protocol v1). ``frame_count`` covers ``handles[0] + dur + handles[1]`` at ``fps``."""
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
    out = Path(out_dir).resolve()
    w, h = int(res[0]), int(res[1])
    span = float(handles[0]) + float(dur) + float(handles[1])
    count = max(1, int(round(span * int(fps))))
    return {
        "version": PROTOCOL_VERSION, "scene": str(Path(scene).resolve()),
        "kit_root": str(Path(kit_root or KIT_ROOT).resolve()),
        "params": dict(params or {}), "seed": int(seed), "fps": int(fps), "res": [w, h],
        "aspect": aspect or ("9:16" if h > w else ("1:1" if h == w else "16:9")),
        "dur": round(float(dur), 6), "frame_count": count, "handles": [float(handles[0]), float(handles[1])],
        "frames": sorted({int(f) for f in frames}) if frames is not None else None,
        "tier": tier, "alpha": bool(alpha),
        "assets": {k: dict(v) for k, v in (assets or {}).items()}, "product": product,
        "handoff": dict(handoff) if handoff else None,
        "out_dir": str(out), "out_ext": out_ext or ("png" if alpha else "jpg"), "save_blend": bool(save_blend),
        "cues_out": str(out / "cues.json"), "stats_out": str(out / "stats.json"),
    }


def frame_path(job: dict[str, Any], f: int) -> Path:
    return Path(job["out_dir"]) / f"{int(f):06d}.{job.get('out_ext') or 'jpg'}"


def requested_frames(job: dict[str, Any]) -> list[int]:
    return list(job["frames"]) if job.get("frames") is not None else list(range(1, int(job["frame_count"]) + 1))


# ------------------------------------------------------------------------------------------- frame checks

@dataclass
class FrameCheck:
    ok: bool
    reason: str = ""
    blank: bool = False


def _header_ok(data: bytes, ext: str) -> str:
    if ext in ("jpg", "jpeg"):
        if not data.startswith(b"\xff\xd8"):
            return "not a JPEG (no SOI marker)"
        if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
            return "truncated JPEG (no EOI marker)"
    elif ext == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "not a PNG (bad signature)"
        if b"IEND" not in data[-16:]:
            return "truncated PNG (no IEND chunk)"
    return ""


def verify_frame(path: Path, *, expect: tuple[int, int] | None = None) -> FrameCheck:
    """Exists, decodes, size matches ``expect`` (w, h), not blank. Uses Pillow when importable (Hermes core dep),
    else a header/trailer check (blank detection then unavailable)."""
    try:
        data = path.read_bytes()
    except OSError:
        return FrameCheck(False, "missing")
    if len(data) < 64:
        return FrameCheck(False, "empty file")
    bad = _header_ok(data, path.suffix.lower().lstrip("."))
    if bad:
        return FrameCheck(False, bad)
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return FrameCheck(True)
    import io
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if expect and tuple(im.size) != tuple(expect):
                return FrameCheck(False, f"size {im.size[0]}x{im.size[1]} != {expect[0]}x{expect[1]}")
            thumb = im.convert("RGB").resize((32, 32))
    except (OSError, ValueError, SyntaxError) as exc:
        return FrameCheck(False, f"does not decode ({exc})")
    lo_hi = thumb.getextrema()
    spread = max(hi - lo for lo, hi in lo_hi)
    stdev = max(ImageStat.Stat(thumb).stddev)
    return FrameCheck(True, blank=spread <= 2 or stdev < 0.5)


# ------------------------------------------------------------------------------------------- result

@dataclass
class RunResult:
    ok: bool
    error: str = ""                       # one user-facing line
    traceback: str = ""
    exit_code: int | None = None
    cancelled: bool = False
    frames_rendered: list[int] = field(default_factory=list)
    frames_skipped: list[int] = field(default_factory=list)     # already verified (resume)
    frames_bad: list[tuple[int, str]] = field(default_factory=list)
    blank: list[int] = field(default_factory=list)
    build_s: float | None = None
    mean_frame_s: float | None = None
    elapsed_s: float = 0.0
    peak_rss_mb: float | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    cues: list[dict[str, Any]] = field(default_factory=list)
    log: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_line(line: str) -> dict[str, Any] | None:
    """Protocol event from one stdout line, e.g. ``{"ev": "FRAME", "frame": 3, "s": 0.71}`` (None if not SR_*)."""
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    ev, rest = m.group(1), m.group(2).strip()
    out: dict[str, Any] = {"ev": ev}
    if ev == "FRAME":
        parts = rest.split()
        try:
            out["frame"] = int(parts[0])
            out["s"] = float(parts[1]) if len(parts) > 1 else None
        except (ValueError, IndexError):
            return None
    elif ev == "ERROR":
        out["msg"] = rest
    else:
        for kv in rest.split():
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def _is_cancelled(cancel: Cancel) -> bool:
    if cancel is None:
        return False
    if isinstance(cancel, threading.Event):
        return cancel.is_set()
    return bool(cancel())


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class _Proc:
    """Our Blender child: PID + creation time recorded at spawn; kill/peak-RSS only ever touch that tree."""

    def __init__(self, popen: subprocess.Popen[str]):
        self.popen = popen
        self.ps = None
        self.created: float | None = None
        self.peak_rss = 0
        try:
            import psutil
            self.ps = psutil.Process(popen.pid)
            self.created = self.ps.create_time()
        except Exception:   # psutil missing or process already gone: fall back to Popen-only control
            self.ps = None

    def _ours(self) -> bool:
        if self.ps is None or self.created is None:
            return False
        try:
            return abs(self.ps.create_time() - self.created) < 0.01
        except Exception:   # gone
            return False

    def sample_rss(self) -> None:
        if not self._ours():
            return
        try:
            rss = self.ps.memory_info().rss + sum(c.memory_info().rss for c in self.ps.children(recursive=True))
            self.peak_rss = max(self.peak_rss, rss)
        except Exception:   # process exited between calls
            return

    def kill_tree(self) -> None:
        """Kill our child and its descendants (verified by PID + creation time); nothing else."""
        if self.popen.poll() is not None:
            return
        procs = []
        if self._ours():
            try:
                procs = self.ps.children(recursive=True)
            except Exception:
                procs = []
        for c in procs:
            try:
                c.kill()
            except Exception:   # already exited
                continue
        self.popen.kill()
        try:
            self.popen.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass


def wait_for_ram(min_free_gb: float, timeout_s: float = 600.0, cancel: Cancel = None) -> bool:
    """Wait until ``min_free_gb`` of RAM is available (psutil); True when it is (or psutil is missing)."""
    if min_free_gb <= 0:
        return True
    try:
        import psutil
    except ImportError:
        return True
    t0 = time.monotonic()
    while psutil.virtual_memory().available < min_free_gb * 2 ** 30:
        if time.monotonic() - t0 > timeout_s or _is_cancelled(cancel):
            return False
        time.sleep(5)
    return True


def blender_command(blender: Path | str, job_path: Path, entry: Path = ENTRY) -> list[str]:
    return [str(blender), "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(entry), "--", str(job_path)]


def run_job(job: dict[str, Any], blender: BlenderFound | Path | str, *, progress: ProgressCB | None = None,
            cancel: Cancel = None, resume: bool = True, job_path: Path | None = None, log_path: Path | None = None,
            stall_s: float = STALL_S, timeout_s: float | None = None,
            lock: Callable[[], AbstractContextManager[Any]] | None = None, min_free_gb: float = 0.0,
            entry: Path = ENTRY, command: list[str] | None = None) -> RunResult:
    """Render ``job`` with Blender; never raises. ``progress`` gets dicts with ``phase`` in
    start|build|frame|done|error plus ``done``, ``total``, ``frame``, ``frame_s``, ``build_s``, ``eta_s``.
    ``command`` overrides the full command line (tests run a fake Blender with it)."""
    t_start = time.monotonic()
    job = {**job, "out_dir": str(Path(job["out_dir"]).resolve())}
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    res = RunResult(ok=False)
    want = requested_frames(job)
    expect = (int(job["res"][0]), int(job["res"][1]))
    if resume:
        res.frames_skipped = [f for f in want if verify_frame(frame_path(job, f), expect=expect).ok]
    todo = [f for f in want if f not in set(res.frames_skipped)]
    if not todo:
        res.ok = True
        _finish_outputs(job, res)
        res.elapsed_s = round(time.monotonic() - t_start, 3)
        return res
    for f in todo:   # stale/partial files must not be mistaken for fresh output
        for p in (frame_path(job, f), frame_path(job, f).with_name(f"{int(f):06d}.part.{job.get('out_ext') or 'jpg'}")):
            if p.exists():
                p.unlink()
    run = dict(job)
    run["frames"] = todo if (job.get("frames") is not None or len(todo) != int(job["frame_count"])) else None
    job_path = Path(job_path or out_dir / "job.json").resolve()
    job_path.write_text(json.dumps(run, indent=1), encoding="utf-8")
    log_path = log_path or out_dir / "blender.log"
    res.log = str(log_path)
    if not wait_for_ram(min_free_gb, cancel=cancel):
        res.error = f"not enough free memory to start Blender (needs {min_free_gb:.1f} GB)"
        res.cancelled = _is_cancelled(cancel)
        return res
    blender_path = blender.path if isinstance(blender, BlenderFound) else Path(blender)
    cmd = command or blender_command(blender_path, job_path, entry)
    with (lock() if lock else nullcontext()):
        # the time limit counts Blender's own run time, not the wait for locks / free memory
        _spawn_and_watch(cmd, run, todo, res, progress, cancel, log_path, stall_s, timeout_s, time.monotonic())
    res.elapsed_s = round(time.monotonic() - t_start, 3)
    return res


def _emit(progress: ProgressCB | None, **kw: Any) -> None:
    if progress:
        try:
            progress(kw)
        except Exception:   # a broken progress sink must never break a render
            return


def _spawn_and_watch(cmd: list[str], job: dict[str, Any], todo: list[int], res: RunResult,
                     progress: ProgressCB | None, cancel: Cancel, log_path: Path, stall_s: float,
                     timeout_s: float | None, t_start: float) -> None:
    total = len(todo)
    lines: queue.Queue[str | None] = queue.Queue()
    tail: deque[str] = deque(maxlen=400)
    tb_lines: list[str] = []
    in_tb = False
    sr_error = ""
    done_seen = False
    rendered: list[int] = []
    frame_s: list[float] = []
    try:
        popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1, env=child_env(),
                                 cwd=str(Path(job["out_dir"])), creationflags=_no_window())
    except OSError as exc:
        res.error = f"could not start Blender: {exc}"
        _emit(progress, phase="error", error=res.error)
        return
    proc = _Proc(popen)

    def reader() -> None:
        assert popen.stdout is not None
        for line in popen.stdout:
            lines.put(line.rstrip("\r\n"))
        lines.put(None)

    th = threading.Thread(target=reader, name="blender-stdout", daemon=True)
    th.start()
    _emit(progress, phase="start", done=0, total=total, pid=popen.pid)
    last_line = time.monotonic()
    last_rss = 0.0
    eof = False
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        log.write("$ " + " ".join(cmd) + "\n")
        while True:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if line is None:          # reader hit EOF: the child closed stdout (it is exiting)
                eof = True
                line = ""
            now = time.monotonic()
            if line:
                last_line = now
                log.write(line + "\n")
                tail.append(line)
                if _TRACEBACK in line:
                    in_tb = True
                if in_tb:
                    tb_lines.append(line)
                    if len(tb_lines) > 200:
                        in_tb = False
                ev = parse_line(line)
                if ev:
                    in_tb = False if ev["ev"] in ("FRAME", "DONE") else in_tb
                    if ev["ev"] == "BUILD_DONE":
                        res.build_s = float(ev.get("s") or 0.0)
                        _emit(progress, phase="build", build_s=res.build_s, done=0, total=total,
                              eta_s=None)
                    elif ev["ev"] == "FRAME":
                        rendered.append(ev["frame"])
                        if ev.get("s") is not None:
                            frame_s.append(float(ev["s"]))
                        # the first frame carries shader compilation / scene sync: keep it out of the rate
                        steady = frame_s[1:] or frame_s
                        mean = sum(steady) / len(steady) if steady else None
                        eta = mean * (total - len(rendered)) if mean is not None else None
                        _emit(progress, phase="frame", frame=ev["frame"], frame_s=ev.get("s"), done=len(rendered),
                              total=total, eta_s=eta)
                    elif ev["ev"] == "DONE":
                        done_seen = True
                    elif ev["ev"] == "ERROR":
                        sr_error = sr_error or ev.get("msg", "")
            if _is_cancelled(cancel):
                proc.kill_tree()
                res.cancelled = True
                res.error = "cancelled"
                break
            if now - last_rss > 1.0:
                proc.sample_rss()
                last_rss = now
            if now - last_line > stall_s:
                proc.kill_tree()
                res.error = f"Blender printed nothing for {stall_s:.0f} s and was stopped"
                break
            if timeout_s and now - t_start > timeout_s:
                proc.kill_tree()
                res.error = f"Blender exceeded the {timeout_s:.0f} s time limit and was stopped"
                break
            if eof and lines.empty():
                break
    try:
        res.exit_code = popen.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill_tree()
        res.exit_code = popen.poll()
    th.join(timeout=5)
    res.peak_rss_mb = round(proc.peak_rss / 2 ** 20, 1) if proc.peak_rss else None
    res.frames_rendered = sorted(set(rendered))
    res.mean_frame_s = round(sum(frame_s) / len(frame_s), 4) if frame_s else None
    res.traceback = "\n".join(tb_lines[-120:])
    if not res.error:
        if sr_error:
            res.error = f"Blender scene failed: {sr_error}"
        elif tb_lines:
            last = next((l for l in reversed(tb_lines) if l.strip() and not l.startswith(" ")), "")
            res.error = f"Blender printed a Python traceback (exit code {res.exit_code}): {last.strip()[:300]}"
        elif res.exit_code not in (0, None):
            res.error = f"Blender exited with code {res.exit_code}: {(tail[-1] if tail else '')[:300]}"
        elif not done_seen:
            res.error = f"Blender stopped before finishing (no SR_DONE; last line: {(tail[-1] if tail else '')[:200]})"
    # verify everything this run was supposed to produce
    expect = (int(job["res"][0]), int(job["res"][1]))
    for f in todo:
        chk = verify_frame(frame_path(job, f), expect=expect)
        if not chk.ok:
            res.frames_bad.append((f, chk.reason))
        elif chk.blank:
            res.blank.append(f)
    if not res.error and res.frames_bad:
        f, why = res.frames_bad[0]
        res.error = f"{len(res.frames_bad)} frame(s) failed verification (frame {f}: {why})"
    if not res.error and todo and len(res.blank) == len(todo) and len(todo) > 1:
        res.error = "every rendered frame is blank (camera sees nothing / scene failed silently)"
    _finish_outputs(job, res)
    res.ok = not res.error
    _emit(progress, phase="done" if res.ok else "error", done=len(res.frames_rendered), total=total,
          error=res.error or None, eta_s=0.0)


def _finish_outputs(job: dict[str, Any], res: RunResult) -> None:
    for key, attr in (("stats_out", "stats"), ("cues_out", "cues")):
        p = job.get(key)
        if p and Path(p).is_file():
            try:
                setattr(res, attr, json.loads(Path(p).read_text(encoding="utf-8")))
            except ValueError:
                res.error = res.error or f"{Path(p).name} is not valid JSON"
    if res.build_s is None and res.stats.get("build_s") is not None:
        res.build_s = float(res.stats["build_s"])
    if res.mean_frame_s is None and res.stats.get("mean_frame_s") is not None:
        res.mean_frame_s = float(res.stats["mean_frame_s"])
    if res.peak_rss_mb is not None:
        res.stats["peak_rss_mb"] = res.peak_rss_mb


# ------------------------------------------------------------------------------------------- benchmark / ETA

def bench_frames(frame_count: int, n: int = 3) -> list[int]:
    """``n`` frames spread over the shot (first, middle, last for n=3)."""
    if frame_count <= n:
        return list(range(1, frame_count + 1))
    return sorted({1 + round(i * (frame_count - 1) / (n - 1)) for i in range(n)})


def benchmark(job: dict[str, Any], blender: BlenderFound | Path | str, **kw: Any) -> RunResult:
    """Render 3 representative frames of ``job`` INTO ITS OUT DIR (the full render later resumes past them)."""
    bench = dict(job)
    bench["frames"] = bench_frames(int(job["frame_count"]))
    return run_job(bench, blender, **kw)


def estimate_s(build_s: float, mean_frame_s: float, frames: int, *, pixels: int | None = None,
               bench_pixels: int | None = None) -> float:
    """Seconds for one shot: one scene build + ``frames`` frames (scaled by pixel count vs the benchmark)."""
    scale = (pixels / bench_pixels) if pixels and bench_pixels else 1.0
    return float(build_s) + float(mean_frame_s) * scale * int(frames)


def human_eta(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    if s < 90:
        return f"~{max(s, 1)} s"
    if s < 5400:
        return f"~{round(s / 60)} min"
    return f"~{s / 3600:.1f} h"


def iter_existing(job: dict[str, Any]) -> Iterable[Path]:
    ext = job.get("out_ext") or "jpg"
    return sorted(Path(job["out_dir"]).glob(f"[0-9][0-9][0-9][0-9][0-9][0-9].{ext}"))
