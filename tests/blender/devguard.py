"""Dev-machine etiquette for REAL Blender runs in tests and dev scripts (not shipped runtime code).

* ``AUTEUR_DEV_BLENDER_LOCK``: path of a one-Blender-at-a-time lock file (O_EXCL create, "<who> <pid> <iso>").
* ``AUTEUR_DEV_GPULOCK_DIR``: directory holding a ``gpulock.py`` exposing ``gpu(who)`` (the dev PC's GPU lock).
* ``AUTEUR_DEV_MIN_FREE_GB``: free RAM required before starting Blender (default 3.5).
All optional: unset = no extra locking (CI / other machines).
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import importlib
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path


def min_free_gb() -> float:
    return float(os.environ.get("AUTEUR_DEV_MIN_FREE_GB", "3.5"))


@contextlib.contextmanager
def blender_lock(who: str = "auteur-A", poll_s: float = 0.5, stale_s: float = 3 * 3600) -> Iterator[None]:
    path = os.environ.get("AUTEUR_DEV_BLENDER_LOCK")
    if not path:
        yield
        return
    p = Path(path)
    while True:
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{who} {os.getpid()} {_dt.datetime.now().isoformat(timespec='seconds')}".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - p.stat().st_mtime > stale_s:
                    p.unlink()
                    continue
            except OSError:
                continue
            time.sleep(poll_s)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            p.unlink()


@contextlib.contextmanager
def gpu_lock(who: str = "auteur-A") -> Iterator[None]:
    d = os.environ.get("AUTEUR_DEV_GPULOCK_DIR")
    if not d:
        yield
        return
    if d not in sys.path:
        sys.path.insert(0, d)
    gpulock = importlib.import_module("gpulock")
    with gpulock.gpu(who):
        yield


@contextlib.contextmanager
def dev_lock(who: str = "auteur-A") -> Iterator[None]:
    """Both locks (Blender first, then the GPU) for one real Blender run."""
    with blender_lock(who), gpu_lock(who):
        yield
