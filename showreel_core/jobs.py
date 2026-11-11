"""Persisted job state (SPEC 3.8): ``<plugin data>/jobs/<id>/job.json`` plus a ``cancel`` flag file.

Stdlib only and free of package-relative imports, so ``dashboard/plugin_api.py`` (imported
standalone by Hermes) and the plugin's own threads share one implementation. One process runs a
job and is the only writer of its ``job.json``; other contexts (the pane, another surface) talk to
it through side files: ``cancel`` (flag) and ``storyboard.edit.json`` (pane edits). Writes are
atomic (temp file + ``os.replace``, retried on Windows sharing errors).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

PLUGIN = "hype"
STAGES = ("queued", "reading", "storyboard", "voice", "layout", "render", "mix", "qa", "done")
TERMINAL = frozenset({"done", "failed", "cancelled"})
LOG_CAP = 400
_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def data_root() -> Path:
    """``<HERMES_HOME>/plugin-data/hype`` (profile-following); ``$HYPE_DATA_DIR`` overrides it.

    Outside Hermes (tests, dev tools) it falls back to ``<temp>/hype-data`` so nothing is
    written into a Hermes home that is not there.
    """
    env = os.environ.get("HYPE_DATA_DIR", "").strip()
    if env:
        root = Path(env)
    else:
        try:
            from plugins.plugin_storage import (
                plugin_data_dir,  # Hermes public module, lazy
            )
            return Path(plugin_data_dir(PLUGIN))
        except Exception:  # noqa: BLE001 - not inside Hermes
            try:
                from hermes_constants import get_hermes_home
                root = Path(get_hermes_home()) / "plugin-data" / PLUGIN
            except Exception:  # noqa: BLE001
                import tempfile
                root = Path(tempfile.gettempdir()) / "hype-data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_job_id(now: float | None = None) -> str:
    """Sortable, path-safe id: ``YYYYMMDD-HHMMSS-xxxx`` (UTC)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(time.time() if now is None else now))
    return f"{stamp}-{secrets.token_hex(2)}"


def valid_id(job_id: Any) -> bool:
    return isinstance(job_id, str) and bool(_ID_RE.match(job_id))


def _lock(job_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(job_id, threading.Lock())


def write_json_atomic(path: Path, data: Any, retries: int = 8) -> None:
    """Write JSON so readers see the old or the new file, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    except BaseException:                # disk full / unwritable: never leave a half-written temp file behind
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # Windows: a reader holds the file open for a moment
            time.sleep(0.02 * (attempt + 1))
    with contextlib.suppress(OSError):
        tmp.unlink()
    raise PermissionError(f"could not replace {path}")


def read_json(path: Path, retries: int = 4) -> Any:
    """Read JSON, tolerating a concurrent atomic replace (``None`` if missing/unreadable)."""
    for attempt in range(retries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError):
            time.sleep(0.02 * (attempt + 1))
        except OSError:
            return None
    return None


def process_started(pid: int | None = None) -> float | None:
    """Start time of process ``pid`` (default: this one), or ``None`` when it cannot be read.

    Stored next to ``job.pid``: after a crash or a reboot the OS hands the old pid to an unrelated process, and a
    pid check alone kept such a job "running" (and every new ``/hype`` refused) for an hour.
    """
    try:
        import psutil  # Hermes core dependency
        return round(float(psutil.Process(os.getpid() if pid is None else int(pid)).create_time()), 3)
    except Exception:  # noqa: BLE001
        return None


def _same_start(pid: int, started: Any) -> bool:
    """False only when ``pid`` provably belongs to a process started at another time than ``started``."""
    try:
        want = float(started)
    except (TypeError, ValueError):
        return True                      # jobs written before pid_started existed: pid check only
    now = process_started(pid)
    return now is None or abs(now - want) <= 2.0


def _pid_alive(pid: Any, started: Any = None) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid == os.getpid():
        return _same_start(pid, started)
    try:
        import psutil  # Hermes core dependency
        return psutil.pid_exists(pid) and _same_start(pid, started)
    except Exception:  # noqa: BLE001
        return False


#: Job ids being run by ANY copy of this module in this process. Hermes loads ``showreel_core`` twice in the
#: gateway process (the plugin package, and ``dashboard/plugin_api.py`` under a private name), each copy with its
#: own pipeline registry, so the plugin's stale sweep took a running Desktop-pane film for an orphan. The set
#: lives in ``sys.modules`` so both copies see one registry.
_LIVE_KEY = "_hype_live_jobs"


def _live() -> tuple[set[str], threading.Lock]:
    holder = sys.modules.get(_LIVE_KEY)
    if holder is None:
        holder = sys.modules.setdefault(_LIVE_KEY, types.ModuleType(_LIVE_KEY))
    ids = holder.__dict__.setdefault("ids", set())
    guard = holder.__dict__.setdefault("guard", threading.Lock())
    return ids, guard


def mark_live(job_id: str) -> None:
    """This process is running ``job_id`` now (see :data:`_LIVE_KEY`)."""
    ids, guard = _live()
    with guard:
        ids.add(job_id)


def mark_not_live(job_id: str) -> None:
    ids, guard = _live()
    with guard:
        ids.discard(job_id)


def live_ids() -> set[str]:
    ids, guard = _live()
    with guard:
        return set(ids)


def shared_lock(name: str) -> threading.Lock:
    """A process-wide lock shared by every copy of this module (see :data:`_LIVE_KEY`)."""
    holder = sys.modules.get(_LIVE_KEY) or sys.modules.setdefault(_LIVE_KEY, types.ModuleType(_LIVE_KEY))
    return holder.__dict__.setdefault(f"lock_{name}", threading.Lock())


_CREATED_LOCK = threading.Lock()
_LAST_CREATED = 0.0


def _created_now() -> float:
    """``time.time()``, strictly increasing within this process.

    Windows clocks can tick in ~16 ms steps, so two jobs made back to back got the same ``created`` and
    "newest first" fell back to the random id suffix.
    """
    global _LAST_CREATED
    with _CREATED_LOCK:
        now = max(time.time(), _LAST_CREATED + 1e-6)
        _LAST_CREATED = now
        return now


class JobStore:
    """Job records under ``<root>/jobs``. Thread-safe within a process; see the module docstring."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else data_root()
        self.jobs_dir = self.root / "jobs"

    # -- paths -----------------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        if not valid_id(job_id):
            raise ValueError(f"invalid job id: {job_id!r}")
        return self.jobs_dir / job_id

    def _file(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    # -- create / read / write ----------------------------------------------------
    def create(self, session_id: str, options: dict[str, Any], *, kind: str = "quick", surface: str = "",
               parent: str = "", title: str = "") -> dict[str, Any]:
        """New job record in stage ``queued`` (its directory is created)."""
        now = _created_now()
        job_id = new_job_id(now)
        while self._file(job_id).exists():
            job_id = new_job_id(now)
        job = {
            "id": job_id, "session_id": session_id or "", "created": now, "updated": now, "finished": None,
            "kind": kind, "surface": surface, "parent": parent, "title": title, "pid": os.getpid(),
            "pid_started": process_started(),
            "options": dict(options), "stage": "queued", "stage_pct": 0.0, "pct": 0.0, "eta_s": None,
            "note": "", "error": None, "warnings": [], "storyboard": None, "storyboard_source": "",
            "timeline_paths": {}, "outputs": {}, "delivered": {}, "contact_sheet": "", "thumbs": [],
            "duration_s": None, "stages": {}, "qa": {}, "log": [],
        }
        self.job_dir(job_id).mkdir(parents=True, exist_ok=True)
        self.save(job)
        return job

    def load(self, job_id: str) -> dict[str, Any] | None:
        if not valid_id(job_id):
            return None
        data = read_json(self._file(job_id))
        return data if isinstance(data, dict) else None

    def save(self, job: dict[str, Any]) -> None:
        job["updated"] = time.time()
        with _lock(job["id"]):
            write_json_atomic(self._file(job["id"]), job)

    def update(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        """Merge ``fields`` into the record (read-modify-write under the per-job lock)."""
        with _lock(job_id):
            job = self.load(job_id)
            if job is None:
                return None
            job.update(fields)
            job["updated"] = time.time()
            write_json_atomic(self._file(job_id), job)
            return job

    def log(self, job_id: str, msg: str, level: str = "info", **extra: Any) -> None:
        """Append a log line (``level``: info | warn | error); warnings also land in ``job.warnings``."""
        with _lock(job_id):
            job = self.load(job_id)
            if job is None:
                return
            entry = {"t": round(time.time(), 3), "level": level, "msg": str(msg)[:2000], **extra}
            job["log"] = (job.get("log") or [])[-(LOG_CAP - 1):] + [entry]
            if level == "warn":
                job["warnings"] = (job.get("warnings") or [])[-49:] + [str(msg)[:500]]
            job["updated"] = time.time()
            write_json_atomic(self._file(job_id), job)

    # -- queries --------------------------------------------------------------------
    def list(self, session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Jobs newest first by creation time (optionally only one session's)."""
        if not self.jobs_dir.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for d in self.jobs_dir.iterdir():
            if not valid_id(d.name):
                continue
            job = self.load(d.name)
            if job is None or (session_id and job.get("session_id") != session_id):
                continue
            found.append(job)
        found.sort(key=lambda j: (float(j.get("created") or 0), j.get("id", "")), reverse=True)
        return found[:limit]

    def latest(self, session_id: str | None = None) -> dict[str, Any] | None:
        jobs = self.list(session_id, limit=1)
        return jobs[0] if jobs else None

    def find(self, ref: str, session_id: str | None = None) -> dict[str, Any] | None:
        """Job by full id, unique id prefix/suffix, or ``""``/``latest`` (the session's newest)."""
        ref = (ref or "").strip()
        if not ref or ref == "latest":
            return self.latest(session_id) or (self.latest() if session_id is None else None)
        if valid_id(ref):
            return self.load(ref)
        hits = [j for j in self.list(session_id, limit=500) if j["id"].startswith(ref) or j["id"].endswith(ref)]
        return hits[0] if len(hits) == 1 else None

    def running(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return [j for j in self.list(session_id, limit=100) if j.get("stage") not in TERMINAL]

    # -- cancel / storyboard edits ---------------------------------------------------
    def request_cancel(self, job_id: str) -> bool:
        """Raise the cancel flag (picked up by the runner within about a second)."""
        job = self.load(job_id)
        if job is None or job.get("stage") in TERMINAL:
            return False
        (self.job_dir(job_id) / "cancel").write_text(str(time.time()), encoding="utf-8")
        return True

    def cancel_requested(self, job_id: str) -> bool:
        return valid_id(job_id) and (self.job_dir(job_id) / "cancel").exists()

    def save_storyboard_edit(self, job_id: str, storyboard: dict[str, Any]) -> Path:
        """Store pane edits (narration/labels/drops/order) for the next re-render of this job."""
        path = self.job_dir(job_id) / "storyboard.edit.json"
        write_json_atomic(path, storyboard)
        return path

    def storyboard_edit(self, job_id: str) -> dict[str, Any] | None:
        data = read_json(self.job_dir(job_id) / "storyboard.edit.json") if valid_id(job_id) else None
        return data if isinstance(data, dict) else None

    # -- housekeeping ------------------------------------------------------------------
    def mark_stale(self, max_idle_s: float = 900.0, now: float | None = None,
                   active_ids: set[str] | list[str] | None = None) -> list[str]:
        """Fail jobs whose runner is gone. Returns the ids marked ``failed``.

        A job is stale when its owning process is dead (or its pid now belongs to another process: pid +
        ``pid_started``), when it belongs to this process but no copy of the pipeline here runs it (``active_ids``
        plus :func:`live_ids`; the plugin was reloaded), or when it has been silent for ``4 * max_idle_s``.
        Jobs younger than 30 s are left alone (they may be between ``create`` and their thread start).
        """
        now = time.time() if now is None else now
        marked = []
        live = live_ids()
        for job in self.running():
            idle = now - float(job.get("updated") or 0)
            if idle < 30.0:
                continue
            pid = job.get("pid")
            mine = pid == os.getpid() and _same_start(os.getpid(), job.get("pid_started"))
            orphan = mine and active_ids is not None and job["id"] not in set(active_ids) | live
            dead = not mine and not _pid_alive(pid, job.get("pid_started"))
            if not (orphan or dead or idle >= 4 * max_idle_s):
                continue
            self.update(job["id"], stage="failed", finished=now, error={"code": "interrupted",
                        "message": "The render stopped unexpectedly (Hermes restarted or the plugin unloaded)."})
            marked.append(job["id"])
        return marked

    def prune(self, keep: int = 20, max_age_days: float = 14.0, now: float | None = None) -> list[str]:
        """Delete finished jobs beyond the newest ``keep`` or older than ``max_age_days``.

        Running jobs are never touched. Delivered copies in ``cache/generated/videos`` are not ours
        to prune (Hermes keeps them); only the job directory goes.
        """
        now = time.time() if now is None else now
        removed: list[str] = []
        finished = [j for j in self.list(limit=10_000) if j.get("stage") in TERMINAL]
        for k, job in enumerate(finished):
            old = now - float(job.get("created") or now) > max_age_days * 86400
            if k >= keep or old:
                shutil.rmtree(self.job_dir(job["id"]), ignore_errors=True)
                removed.append(job["id"])
        return removed

    def prune_work(self, job_id: str) -> None:
        """Drop bulky intermediates of a finished job (render chunks, extracted frames, stems)."""
        d = self.job_dir(job_id)
        for pattern in ("chunks_*", "*.chunks", "frames_*"):
            for p in d.glob(pattern):
                shutil.rmtree(p, ignore_errors=True)
        for pattern in ("mix_stem_*.wav", "mix_premix.wav", "*.tts.mp3"):
            for p in d.rglob(pattern):
                with contextlib.suppress(OSError):
                    p.unlink()


def public_view(job: dict[str, Any], log_tail: int = 30) -> dict[str, Any]:
    """The job as shown to the pane/tools: everything but the long log (its tail only)."""
    view = {k: v for k, v in job.items() if k != "log"}
    view["log"] = (job.get("log") or [])[-log_tail:]
    return view
