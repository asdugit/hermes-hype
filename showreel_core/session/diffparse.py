"""Patch parsing: unified diffs (Hermes ``patch`` results), V4A patches, replace-mode synthesis.

All functions return a list of ``FilePatch`` dicts::

    {"path": str, "hunks": [{"header": str, "lines": [[op, text], ...]}], "adds": int, "dels": int,
     "action": "update" | "add" | "delete" | "move", "move_to": str | None}

``op`` is one of ``"+"``, ``"-"``, ``" "``. Text is verbatim (no trailing newline).
"""
from __future__ import annotations

import difflib
import re
from typing import Any

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_V4A_FILE_RE = re.compile(r"^\*\*\* (Update|Add|Delete) File:\s*(.+?)\s*$")
_V4A_MOVE_RE = re.compile(r"^\*\*\* Move to:\s*(.+?)\s*$")


def _new_file(path: str, action: str = "update") -> dict[str, Any]:
    return {"path": path, "hunks": [], "adds": 0, "dels": 0, "action": action, "move_to": None}


def _count(fp: dict[str, Any]) -> dict[str, Any]:
    fp["adds"] = sum(1 for h in fp["hunks"] for op, _ in h["lines"] if op == "+")
    fp["dels"] = sum(1 for h in fp["hunks"] for op, _ in h["lines"] if op == "-")
    fp["hunks"] = [h for h in fp["hunks"] if h["lines"]]
    return fp


def _strip_prefix(path: str) -> str:
    path = path.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


_COUNTS_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def parse_unified(diff: str) -> list[dict[str, Any]]:
    """Parse a (possibly multi-file) unified diff.

    Hunk line counts from ``@@ -a,b +c,d @@`` decide where a hunk ends, so removed lines that
    themselves start with ``-- `` are never mistaken for a ``---`` file header.
    """
    files: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    hunk: dict[str, Any] | None = None
    old_left = new_left = 0
    counted = False
    pending_old: str | None = None
    for raw in (diff or "").replace("\r\n", "\n").split("\n"):
        in_hunk = hunk is not None and (old_left > 0 or new_left > 0 or not counted)
        if raw.startswith("--- ") and not (in_hunk and counted):
            pending_old = _strip_prefix(raw[4:])
            hunk = None
            continue
        if raw.startswith("+++ ") and pending_old is not None and hunk is None:
            new = _strip_prefix(raw[4:])
            path = pending_old if new == "/dev/null" else new
            action = "add" if pending_old == "/dev/null" else "delete" if new == "/dev/null" else "update"
            cur = _new_file(path, action)
            files.append(cur)
            pending_old = None
            continue
        if raw.startswith("@@") and not (in_hunk and counted):
            if cur is None:
                cur = _new_file("")
                files.append(cur)
            hunk = {"header": raw.strip(), "lines": []}
            cur["hunks"].append(hunk)
            m = _COUNTS_RE.match(raw)
            counted = bool(m)
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new_left = int(m.group(2)) if m.group(2) is not None else 1
            continue
        if hunk is None or raw.startswith("\\"):
            continue
        op = raw[:1] if raw[:1] in ("+", "-", " ") else (" " if raw == "" else None)
        if op is None:
            continue
        if counted and old_left <= 0 and new_left <= 0:
            continue
        hunk["lines"].append([op, raw[1:]])
        if op in ("-", " "):
            old_left -= 1
        if op in ("+", " "):
            new_left -= 1
    for fp in files:
        for h in fp["hunks"]:
            while h["lines"] and h["lines"][-1] == [" ", ""] and not _COUNTS_RE.match(h["header"]):
                h["lines"].pop()
    return [_count(f) for f in files]


def parse_v4a(patch: str) -> list[dict[str, Any]]:
    """Parse an OpenAI/Hermes V4A patch (``*** Begin Patch`` … ``*** End Patch``)."""
    files: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    hunk: dict[str, Any] | None = None
    for raw in (patch or "").replace("\r\n", "\n").split("\n"):
        if raw.startswith("*** Begin Patch") or raw.startswith("*** End Patch") or raw.startswith("*** End of File"):
            continue
        m = _V4A_FILE_RE.match(raw)
        if m:
            action = m.group(1).lower()
            cur = _new_file(m.group(2), action)
            files.append(cur)
            hunk = None
            if action == "add":
                hunk = {"header": "", "lines": []}
                cur["hunks"].append(hunk)
            continue
        m = _V4A_MOVE_RE.match(raw)
        if m and cur is not None:
            cur["move_to"] = m.group(1)
            cur["action"] = "move"
            continue
        if cur is None:
            continue
        if raw.startswith("@@"):
            hunk = {"header": raw.strip(), "lines": []}
            cur["hunks"].append(hunk)
            continue
        if raw.startswith(("+", "-", " ")):
            if hunk is None:
                hunk = {"header": "", "lines": []}
                cur["hunks"].append(hunk)
            hunk["lines"].append([raw[0], raw[1:]])
    return [_count(f) for f in files]


def synth_replace(path: str, old: str, new: str, context: int = 2) -> list[dict[str, Any]]:
    """Hunks for a replace-mode edit (old_string → new_string). Headers are blank: no file line numbers."""
    old_lines = (old or "").replace("\r\n", "\n").split("\n")
    new_lines = (new or "").replace("\r\n", "\n").split("\n")
    fp = _new_file(path)
    hunk: dict[str, Any] | None = None
    for line in difflib.unified_diff(old_lines, new_lines, n=context, lineterm=""):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            hunk = {"header": "", "lines": []}
            fp["hunks"].append(hunk)
            continue
        if hunk is not None and line[:1] in ("+", "-", " "):
            hunk["lines"].append([line[0], line[1:]])
    return [_count(fp)]
