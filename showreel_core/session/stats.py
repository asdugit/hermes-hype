"""Session statistics (SPEC 3.2). Computed from events + rows; never produced by an LLM."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from ..contracts import Event, Stats

# Gaps longer than this between consecutive rows count as idle time, not work.
IDLE_GAP_S = 600.0

_PYTEST_RE = re.compile(
    r"^=*\s*(?P<body>(?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)"
    r"(?:, )?)+)\s+in [\d.]+s", re.M)
_PYTEST_PART_RE = re.compile(r"(\d+) (passed|failed|errors?)")
_JEST_RE = re.compile(r"^Tests:\s+(?:(\d+) failed, )?(?:\d+ skipped, )?(?:\d+ todo, )?(\d+) passed, (\d+) total", re.M)
_VITEST_RE = re.compile(r"^\s*Tests\s+(?:(\d+) failed \| )?(\d+) passed(?: \| \d+ \w+)*\s+\((\d+)\)", re.M)
_CARGO_RE = re.compile(r"^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed", re.M)
_GO_PASS_RE = re.compile(r"^\s*--- PASS: ", re.M)
_GO_FAIL_RE = re.compile(r"^\s*--- FAIL: ", re.M)
_GO_PKG_RE = re.compile(r"^(ok|FAIL)\s+\S+\s+(?:[\d.]+s|\(cached\))", re.M)
_UNITTEST_RE = re.compile(r"^Ran (\d+) tests? in [\d.]+s\s*\n+\s*(OK|FAILED)(?: \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?)?", re.M)


def parse_test_summary(text: str) -> dict[str, Any] | None:
    """Parse the LAST test-runner summary in ``text``.

    Supports pytest, jest, vitest, cargo test, go test (-v counts, else package lines) and
    unittest. Returns ``{"framework", "passed", "failed"}`` or None when no summary is present.
    """
    if not text:
        return None
    found: list[tuple[int, dict[str, Any]]] = []
    for m in _PYTEST_RE.finditer(text):
        parts = {k.rstrip("s") if k.startswith("error") else k: int(n) for n, k in _PYTEST_PART_RE.findall(m.group("body"))}
        if "passed" in parts or "failed" in parts or "error" in parts:
            found.append((m.start(), {"framework": "pytest", "passed": parts.get("passed", 0),
                                      "failed": parts.get("failed", 0) + parts.get("error", 0)}))
    for m in _JEST_RE.finditer(text):
        found.append((m.start(), {"framework": "jest", "passed": int(m.group(2)), "failed": int(m.group(1) or 0)}))
    for m in _VITEST_RE.finditer(text):
        found.append((m.start(), {"framework": "vitest", "passed": int(m.group(2)), "failed": int(m.group(1) or 0)}))
    cargo = list(_CARGO_RE.finditer(text))
    if cargo:   # cargo prints one line per test binary: sum them
        found.append((cargo[-1].start(), {"framework": "cargo", "passed": sum(int(m.group(1)) for m in cargo),
                                          "failed": sum(int(m.group(2)) for m in cargo)}))
    for m in _UNITTEST_RE.finditer(text):
        failed = int(m.group(3) or 0) + int(m.group(4) or 0)
        found.append((m.start(), {"framework": "unittest", "passed": int(m.group(1)) - failed, "failed": failed}))
    go_pkgs = list(_GO_PKG_RE.finditer(text))
    if go_pkgs:
        passes, fails = len(_GO_PASS_RE.findall(text)), len(_GO_FAIL_RE.findall(text))
        if passes or fails:
            found.append((go_pkgs[-1].start(), {"framework": "go", "passed": passes, "failed": fails}))
        else:
            found.append((go_pkgs[-1].start(), {"framework": "go", "unit": "packages",
                                                "passed": sum(1 for m in go_pkgs if m.group(1) == "ok"),
                                                "failed": sum(1 for m in go_pkgs if m.group(1) == "FAIL")}))
    if not found:
        return None
    return max(found, key=lambda x: x[0])[1]


def active_duration(timestamps: Iterable[float | None], idle_gap_s: float = IDLE_GAP_S) -> float:
    """Sum of gaps between consecutive timestamps, ignoring gaps longer than ``idle_gap_s``."""
    ts = sorted(t for t in timestamps if t is not None)
    return float(sum(b - a for a, b in zip(ts, ts[1:]) if 0 <= b - a <= idle_gap_s))


def compute_stats(events: list[Event], rows: list[dict[str, Any]] | None = None,
                  meta: dict[str, Any] | None = None) -> Stats:
    """Compute :class:`Stats` from extracted events (and rows/meta for time and model).

    Definitions (documented because they end up on screen):
      duration_s     active time: row-to-row gaps summed, idle gaps > 10 min ignored
      turns          genuine user prompts (mid-turn steers excluded)
      tool_calls     every tool invocation (``tool_call`` wrappers count their inner calls)
      files_created  distinct paths first written in this session (write_file, V4A Add File)
      files_modified distinct pre-existing paths patched or overwritten
      lines_added/removed  successful patches + new-file lines (+ overwrites diffed against a
                     version seen earlier in the session)
      commands_run   terminal commands (incl. background starts)
      commands_failed_then_fixed  command families that failed and later succeeded
      tests_passed   passed count of the largest fully green run; else of the last run; else None
      screenshots    distinct images captured/inspected (screenshot events, by source path)
      subagents      delegated goals
    """
    rows = rows or []
    meta = meta or {}
    st = Stats()
    st.duration_s = round(active_duration(r.get("timestamp") for r in rows), 1)
    st.model = str(meta.get("model") or "")
    kinds: Counter[str] = Counter()
    created: set[str] = set()
    modified: set[str] = set()
    shots: set[str] = set()
    runs: list[dict[str, Any]] = []
    for ev in events:
        d = ev.data or {}
        if ev.kind == "user_prompt" and not d.get("steer") and not d.get("synthetic"):
            st.turns += 1
        if ev.tool and not d.get("notification"):
            kinds[ev.tool] += 1
        if d.get("stub_only"):
            continue
        if ev.kind == "file_write" and ev.ok:
            key = d.get("path_key") or d.get("path", "")
            if d.get("new_file"):
                created.add(key)
            elif key not in created:
                modified.add(key)
            st.lines_added += int(d.get("adds") or 0)
            st.lines_removed += int(d.get("dels") or 0)
        elif ev.kind == "file_patch" and ev.ok:
            key = d.get("path_key") or d.get("path", "")
            if d.get("action") == "add" and d.get("new_file", True):
                created.add(key)
            elif key not in created:
                modified.add(key)
            st.lines_added += int(d.get("adds") or 0)
            st.lines_removed += int(d.get("dels") or 0)
        elif ev.kind == "terminal":
            if ev.tool == "terminal":
                st.commands_run += 1
            if d.get("fixed"):
                st.commands_failed_then_fixed += 1
            if d.get("tests"):
                runs.append(d["tests"])
        elif ev.kind == "screenshot":
            shots.add(str(d.get("src_key") or d.get("src") or d.get("url") or ev.id))
        elif ev.kind == "delegate" and not d.get("completed"):
            st.subagents += int(d.get("count") or len(d.get("goals") or []))
    st.tool_calls = sum(kinds.values())
    st.tool_kinds = dict(kinds.most_common())
    st.files_created = len(created)
    st.files_modified = len(modified)
    st.screenshots = len(shots)
    tests = [r for r in runs if r.get("unit") != "packages"]
    green = [r for r in tests if r.get("failed", 0) == 0 and r.get("passed", 0) > 0]
    if green:
        st.tests_passed = max(r["passed"] for r in green)
    elif tests:
        st.tests_passed = tests[-1].get("passed", 0)
    return st
