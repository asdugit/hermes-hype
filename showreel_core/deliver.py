"""Delivery: copy finished films where Hermes can send them, and build the user-facing replies.

Masters stay in the job directory (plugin data). Copies go to ``$HERMES_HOME/cache/generated/videos``,
the media root that video providers use: it passes strict MEDIA delivery and is not swept.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

ASPECT_TAGS = {"16:9": "16x9", "9:16": "9x16", "1:1": "1x1"}


def videos_dir() -> Path | None:
    """``<HERMES_HOME>/cache/generated/videos`` (created), ``$HYPE_VIDEOS_DIR``, or ``None`` outside Hermes."""
    env = os.environ.get("HYPE_VIDEOS_DIR", "").strip()
    if env:
        root = Path(env)
    else:
        try:
            from hermes_constants import get_hermes_home  # public, lazy
        except Exception:  # noqa: BLE001 - not inside Hermes
            return None
        root = Path(get_hermes_home()) / "cache" / "generated" / "videos"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return root


def slug(text: str, limit: int = 40) -> str:
    """ASCII file-name slug (``"Focusfox: timer!"`` -> ``focusfox-timer``)."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:limit].rstrip("-")) or "film"


def deliver(master: Path, *, title: str, job_id: str, aspect: str, dest: Path | None = None) -> Path:
    """Put ``master`` at the deliverable name; returns the master itself when no media root exists.

    A hard link when the media root is on the same drive (the usual case: both live under Hermes' home), so a
    finished job does not keep a second copy of every film (20-45 MB per 18 s film, 20 jobs kept); a copy
    otherwise. Deleting either name later leaves the other intact."""
    root = dest or videos_dir()
    if root is None:
        return Path(master)
    out = root / f"hype-{slug(title)}-{job_id[-4:]}-{ASPECT_TAGS.get(aspect, 'film')}{Path(master).suffix}"
    with contextlib.suppress(OSError):
        if out.exists() or out.is_symlink():
            out.unlink()
    try:
        os.link(master, out)
        return out
    except (OSError, NotImplementedError, AttributeError):
        pass                                          # another drive / no hard links (FAT, some shares): copy
    shutil.copy2(master, out)
    return out


def media_lines(paths: dict[str, str]) -> str:
    """``MEDIA:<path>`` lines (one per aspect) for the gateway's native upload."""
    return "\n".join(f"MEDIA:{p}" for p in paths.values() if p)


def done_text(job: dict[str, Any], *, media: bool = True) -> str:
    """Final reply: title, length, where the files are, warnings, then the MEDIA lines."""
    title = job.get("title") or "Your film"
    dur = job.get("duration_s")
    files = job.get("delivered") or job.get("outputs") or {}
    lines = [f"🎬 {title}" + (f" ({dur:.0f}s)" if isinstance(dur, (int, float)) else "")]
    for aspect, path in files.items():
        lines.append(f"  {aspect}: {path}")
    story_note = str(job.get("storyboard_note") or "")
    if job.get("storyboard_source") == "heuristic":
        failed = any("model's storyboard was unusable" in str(w) for w in job.get("warnings") or [])
        if story_note and not failed:
            lines.append(f"  Storyboard: {story_note[:1].upper()}{story_note[1:]}.")
        else:
            lines.append("  Storyboard: the model's reply could not be used, so the built-in storyboard was used."
                         if failed else "  Storyboard: built without the model (none was available).")
    model_note = str(job.get("model_note") or "")
    if model_note:
        lines.append(f"  ⚠ {model_note}")
    notes = [w for w in (job.get("warnings") or []) if w and w not in (story_note, model_note)
             and "model's storyboard was unusable" not in str(w)][:4]
    if notes:
        lines.append("  Notes: " + "; ".join(notes))
    if media and files:
        lines.append(media_lines(files))
    return "\n".join(lines)


def failed_text(job: dict[str, Any]) -> str:
    err = job.get("error") or {}
    msg = err.get("message") if isinstance(err, dict) else str(err)
    hint = err.get("hint") if isinstance(err, dict) else ""
    if isinstance(err, dict) and err.get("code") in FRIENDLY_CODES:
        return f"🎬 {msg}" + (f"\n  {hint}" if hint else "")      # not a failure of Hype: nothing to film yet
    text = f"🎬 Hype {job.get('id', '')} failed: {msg or 'unknown error'}"
    return text + (f"\n  Hint: {hint}" if hint else "")


#: Job error codes that explain why there is no film rather than report a failure.
FRIENDLY_CODES = frozenset({"nothing_built", "empty_session"})


def progress_text(job: dict[str, Any]) -> str:
    """One status line: stage, percent and ETA (an estimate, labelled as such)."""
    stage = job.get("stage", "queued")
    if stage == "done":
        return done_text(job, media=False)
    if stage == "failed":
        return failed_text(job)
    if stage == "cancelled":
        return f"🎬 Hype {job.get('id', '')} cancelled."
    pct = round(float(job.get("pct") or 0) * 100)
    eta = job.get("eta_s")
    eta_txt = f" · ~{_fmt_eta(eta)} left" if isinstance(eta, (int, float)) and eta > 0 else ""
    note = f" · {job['note']}" if job.get("note") else ""
    return f"🎬 Hype · {stage} · {pct}%{eta_txt}{note}"


def _fmt_eta(seconds: float) -> str:
    s = round(seconds)
    return f"{s}s" if s < 90 else f"{(s + 30) // 60} min"
