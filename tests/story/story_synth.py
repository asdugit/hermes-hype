"""Synthetic Hermes sessions for story-stage tests (no real session content).

Run ``python tests/story/story_synth.py`` to (re)write the JSON fixtures used by the dev
harness (``python -m showreel_core.story.try --fixture ...``).
"""
from __future__ import annotations

import json
import random
import sys
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from showreel_core.contracts import Event, Stats

PARSER_PY = '''"""Parse bank CSV exports into transactions."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Transaction:
    day: date
    description: str
    amount: Decimal
    category: str = "uncategorized"


def parse_amount(raw: str) -> Decimal:
    """Turn '1,234.50' or '(12.50)' into a signed Decimal."""
    text = raw.strip().replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        return -Decimal(text[1:-1])
    return Decimal(text)


def parse_file(path: Path) -> list[Transaction]:
    """Read one export; skips blank rows and the bank's footer."""
    rows: list[Transaction] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("Date"):
                continue
            rows.append(Transaction(
                day=date.fromisoformat(row["Date"]),
                description=row["Description"].strip(),
                amount=parse_amount(row["Amount"]),
            ))
    return rows
'''.splitlines()

CATEGORIZE_PY = '''"""Map transactions to spending categories."""
from __future__ import annotations

from .parser import Transaction

RULES = {
    "groceries": ("market", "grocer", "bakery"),
    "transport": ("metro", "fuel", "taxi"),
    "dining": ("cafe", "pizza", "restaurant"),
}


def categorize(tx: Transaction) -> Transaction:
    """Return a copy of ``tx`` with its category filled in."""
    text = tx.description.lower()
    for category, words in RULES.items():
        if any(w in text for w in words):
            return Transaction(tx.day, tx.description, tx.amount, category)
    return tx
'''.splitlines()

TEST_PY = '''from decimal import Decimal

from tally.parser import parse_amount


def test_plain_amount():
    assert parse_amount("12.50") == Decimal("12.50")


def test_thousands_separator():
    assert parse_amount("1,234.50") == Decimal("1234.50")


def test_refund_nets_out():
    assert parse_amount("(12.50)") + Decimal("12.50") == 0
'''.splitlines()

REPORT_PY = '''"""Render the monthly summary as a self-contained HTML page."""
from __future__ import annotations

from html import escape

from .summary import MonthRow


def render(rows: list[MonthRow]) -> str:
    """One table row per month, one column per category."""
    head = "".join(f"<th>{escape(c)}</th>" for c in rows[0].columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in row.cells) + "</tr>" for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"
'''.splitlines()

CLI_PY = '''"""tally command line."""
import argparse

from . import report, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tally")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    s.add_argument("folder")
    r = sub.add_parser("report")
    r.add_argument("folder")
    r.add_argument("-o", "--out", default="report.html")
    args = ap.parse_args(argv)
    rows = summary.monthly(args.folder)
    if args.cmd == "summary":
        print(summary.table(rows))
    else:
        Path(args.out).write_text(report.render(rows), encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0
'''.splitlines()


def _ev(i: int, t: float, kind: str, title: str, summary: str, data: dict[str, Any] | None = None, *,
        tool: str = "", ok: bool = True, weight: float = 0.0) -> Event:
    return Event(id=f"e{i}", t=t, kind=kind, tool=tool, title=title, summary=summary, data=data or {}, ok=ok,
                 weight=weight)


def coding_session() -> tuple[list[Event], Stats]:
    """A believable build session: plan, code, a failing test, a fix, a passing run, a report screenshot."""
    prompt = ("Build me a small Python CLI called tally that reads my bank's CSV exports and shows monthly "
              "spending by category. Refunds should net out against purchases. Add tests and an HTML report "
              "I can open in the browser.")
    todo_items = ["Parse bank CSV exports", "Categorize transactions", "Monthly summary table", "HTML report",
                  "Tests"]

    def todo(statuses: list[str]) -> dict[str, Any]:
        return {"items": [{"text": t, "status": s} for t, s in zip(todo_items, statuses)]}

    ev = [
        _ev(0, 0, "user_prompt", "user", prompt[:150], {"text": prompt}, weight=0.5),
        _ev(1, 6, "assistant_note", "assistant", "Plan first, then parser, categorizer, report, tests.",
            {"text": "I'll plan the work first, then build the parser, the categorizer and the report, with "
                     "tests along the way."}, weight=0.1),
        _ev(2, 10, "todo", "todo", "5 items", todo(["in_progress", "pending", "pending", "pending", "pending"]),
            tool="todo", weight=0.3),
        _ev(3, 20, "terminal", "ls samples", "ls samples", {"cmd": "ls samples", "output_lines": [
            "checking-2026-07.csv", "checking-2026-08.csv", "checking-2026-09.csv"], "exit_code": 0,
            "elapsed_s": 0.1}, tool="terminal", weight=0.05),
        _ev(4, 25, "file_read", "samples/checking-2026-09.csv", "read samples/checking-2026-09.csv",
            {"path": "samples/checking-2026-09.csv"}, tool="read_file", weight=0.02),
        _ev(5, 60, "file_write", "tally/parser.py", f"+{len(PARSER_PY)} in tally/parser.py",
            {"path": "tally/parser.py", "lang": "python", "lines": PARSER_PY, "new_file": True},
            tool="write_file", weight=0.6),
        _ev(6, 120, "file_write", "tally/categorize.py", f"+{len(CATEGORIZE_PY)} in tally/categorize.py",
            {"path": "tally/categorize.py", "lang": "python", "lines": CATEGORIZE_PY, "new_file": True},
            tool="write_file", weight=0.45),
        _ev(7, 170, "file_write", "tests/test_parser.py", f"+{len(TEST_PY)} in tests/test_parser.py",
            {"path": "tests/test_parser.py", "lang": "python", "lines": TEST_PY, "new_file": True},
            tool="write_file", weight=0.35),
        _ev(8, 200, "terminal", "python -m pytest -q", "1 failed, 13 passed", {
            "cmd": "python -m pytest -q", "output_lines": [
                "....F.........",
                "FAILED tests/test_parser.py::test_refund_nets_out - assert Decimal('-25.00') == 0",
                "1 failed, 13 passed in 0.38s"], "exit_code": 1, "elapsed_s": 1.2},
            tool="terminal", ok=False, weight=0.5),
        _ev(9, 240, "file_patch", "tally/parser.py", "+3 -1 in tally/parser.py", {
            "path": "tally/parser.py", "lang": "python", "adds": 3, "dels": 1, "hunks": [{
                "header": "@@ -22,6 +22,8 @@ def parse_amount(raw: str) -> Decimal:",
                "lines": [[" ", '    text = raw.strip().replace(",", "")'],
                          ["-", '    if text.startswith("(") and text.endswith(")"):'],
                          ["+", '    negative = text.startswith("(") and text.endswith(")")'],
                          ["+", "    if negative:"],
                          ["+", "        text = text[1:-1]"],
                          [" ", "        return -Decimal(text[1:-1])"],
                          [" ", "    return Decimal(text)"]]}]},
            tool="patch", weight=0.55),
        _ev(10, 255, "terminal", "python -m pytest -q", "14 passed", {
            "cmd": "python -m pytest -q", "output_lines": ["..............", "14 passed in 0.41s"],
            "exit_code": 0, "elapsed_s": 1.1}, tool="terminal", weight=0.8),
        _ev(11, 260, "todo", "todo", "5 items, 3 done",
            todo(["completed", "completed", "in_progress", "pending", "completed"]), tool="todo", weight=0.2),
        _ev(12, 320, "file_write", "tally/report.py", f"+{len(REPORT_PY)} in tally/report.py",
            {"path": "tally/report.py", "lang": "python", "lines": REPORT_PY, "new_file": True},
            tool="write_file", weight=0.4),
        _ev(13, 380, "file_write", "tally/cli.py", f"+{len(CLI_PY)} in tally/cli.py",
            {"path": "tally/cli.py", "lang": "python", "lines": CLI_PY, "new_file": True},
            tool="write_file", weight=0.35),
        _ev(14, 400, "terminal", "python -m tally summary samples/", "monthly table", {
            "cmd": "python -m tally summary samples/", "output_lines": [
                "Month     Groceries  Transport  Dining   Total",
                "2026-07      412.80      96.00  151.25  660.05",
                "2026-08      389.15     112.40   98.70  600.25",
                "2026-09      401.60      88.00  175.10  664.70"], "exit_code": 0, "elapsed_s": 0.3},
            tool="terminal", weight=0.6),
        _ev(15, 420, "terminal", "python -m tally report samples/ -o report.html", "wrote report.html", {
            "cmd": "python -m tally report samples/ -o report.html",
            "output_lines": ["Wrote report.html"], "exit_code": 0, "elapsed_s": 0.4}, tool="terminal",
            weight=0.3),
        _ev(16, 430, "browser_nav", "report.html", "opened report.html", {"url": "file:///~/projects/tally/report.html"},
            tool="browser_navigate", weight=0.1),
        _ev(17, 435, "screenshot", "Tally report", "Tally report: monthly spending by category", {
            "path": "assets/shot_017.png", "w": 1280, "h": 800, "url": "file:///~/projects/tally/report.html"},
            tool="browser_screenshot", weight=0.85),
        _ev(18, 440, "todo", "todo", "5 items, all done", todo(["completed"] * 5), tool="todo", weight=0.25),
        _ev(19, 450, "final_answer", "assistant", "Tally is ready.", {"text": (
            "Tally is ready. Run python -m tally summary <folder> for the table, or python -m tally report "
            "<folder> -o report.html for the HTML report. Refunds now net out against purchases. "
            "All 14 tests pass.")}, weight=0.4),
        _ev(20, 452, "product_capture", "Tally report", "Auteur capture of report.html (full page)", {
            "path": "assets/capture_report_full.png", "url": "file:///~/projects/tally/report.html",
            "viewport": [1280, 800], "full_page": True, "page_title": "Tally - Monthly spending"}, weight=0.8),
        _ev(21, 453, "product_capture", "Tally report", "Auteur capture of report.html", {
            "path": "assets/capture_report.png", "url": "file:///~/projects/tally/report.html",
            "viewport": [1280, 800], "full_page": False, "page_title": "Tally - Monthly spending"}, weight=0.9),
    ]
    stats = Stats(duration_s=452, turns=1, tool_calls=17,
                  tool_kinds={"terminal": 5, "write_file": 5, "patch": 1, "todo": 3, "read_file": 1,
                              "browser_navigate": 1, "browser_screenshot": 1},
                  files_created=5, files_modified=1, lines_added=sum(len(x) for x in
                                                                     (PARSER_PY, CATEGORIZE_PY, TEST_PY, REPORT_PY,
                                                                      CLI_PY)) + 3,
                  lines_removed=1, commands_run=5, commands_failed_then_fixed=1, tests_passed=14, screenshots=1,
                  subagents=0, model="synthetic-model")
    return ev, stats


def tiny_chat() -> tuple[list[Event], Stats]:
    """Two turns, no tools."""
    answer = ("Lists are mutable, so you can add, remove or change items after you create them. Tuples are "
              "immutable, which makes them hashable and safe to use as dictionary keys. Use a list for a "
              "collection that changes and a tuple for a fixed record.")
    ev = [
        _ev(0, 0, "user_prompt", "user", "What's the difference between a list and a tuple in Python?",
            {"text": "What's the difference between a list and a tuple in Python?"}, weight=0.4),
        _ev(1, 9, "final_answer", "assistant", answer[:150], {"text": answer}, weight=0.5),
    ]
    return ev, Stats(duration_s=12, turns=1, model="synthetic-model")


def browsing_session() -> tuple[list[Event], Stats]:
    """Research with web search, page visits and screenshots; no files."""
    ev = [
        _ev(0, 0, "user_prompt", "user", "Which open-source TTS models allow commercial use?", {"text": (
            "Find out which open-source text-to-speech models allow commercial use, and summarize their "
            "licences for me.")}, weight=0.5),
        _ev(1, 5, "web_search", "open source TTS commercial license", "search", {
            "query": "open source TTS model commercial license", "titles": [
                "Kokoro-82M model card", "Piper TTS", "Coqui XTTS licence FAQ"]}, tool="web_search", weight=0.2),
        _ev(2, 15, "browser_nav", "example.org/models/kokoro", "opened model card",
            {"url": "https://example.org/models/kokoro"}, tool="browser_navigate", weight=0.15),
        _ev(3, 18, "screenshot", "Kokoro model card", "Model card showing the Apache-2.0 licence", {
            "path": "assets/shot_003.png", "w": 1366, "h": 768, "url": "https://example.org/models/kokoro"},
            tool="browser_screenshot", weight=0.6),
        _ev(4, 30, "web_extract", "example.org/piper", "Piper licence page", {"url": "https://example.org/piper"},
            tool="web_extract", weight=0.2),
        _ev(5, 40, "browser_nav", "example.org/piper", "opened Piper", {"url": "https://example.org/piper"},
            tool="browser_navigate", weight=0.1),
        _ev(6, 44, "screenshot", "Piper voices", "Piper voice list with licence column", {
            "path": "assets/shot_006.png", "w": 1366, "h": 768, "url": "https://example.org/piper"},
            tool="browser_screenshot", weight=0.55),
        _ev(7, 60, "web_search", "XTTS licence non-commercial", "search", {
            "query": "XTTS licence non-commercial", "titles": ["Coqui Public Model License"]},
            tool="web_search", weight=0.15),
        _ev(8, 70, "web_extract", "example.org/xtts-license", "XTTS licence text",
            {"url": "https://example.org/xtts-license"}, tool="web_extract", weight=0.2),
        _ev(9, 80, "browser_nav", "example.org/compare", "comparison table", {"url": "https://example.org/compare"},
            tool="browser_navigate", weight=0.1),
        _ev(10, 84, "screenshot", "Licence comparison", "Comparison table of TTS licences", {
            "path": "assets/shot_010.png", "w": 1366, "h": 768, "url": "https://example.org/compare"},
            tool="browser_screenshot", weight=0.7),
        _ev(11, 100, "final_answer", "assistant", "Kokoro and Piper allow commercial use; XTTS does not.", {
            "text": ("Kokoro and Piper both allow commercial use under permissive licences. XTTS uses a "
                     "non-commercial licence, so avoid it for paid products. Check each voice's own licence "
                     "before you ship.")}, weight=0.5),
    ]
    stats = Stats(duration_s=105, turns=1, tool_calls=10,
                  tool_kinds={"web_search": 2, "web_extract": 2, "browser_navigate": 3, "browser_screenshot": 3},
                  screenshots=3, model="synthetic-model")
    return ev, stats


def huge_session(n: int = 600, seed: int = 7) -> tuple[list[Event], Stats]:
    """A long session with every kind of event, compaction stubs and seeded weights."""
    rng = random.Random(seed)
    ev: list[Event] = []
    t = 0.0
    files_created = lines_added = commands = shots = 0
    for i in range(n):
        t += rng.uniform(2, 30)
        roll = i % 12
        w = round(rng.random() * 0.9, 3)
        if i % 100 == 0:
            text = f"Next step {i // 100}: extend the importer to handle source number {i // 100}."
            ev.append(_ev(i, t, "user_prompt", "user", text, {"text": text}, weight=0.4))
        elif i % 97 == 5:
            ev.append(_ev(i, t, "tool_other", "compacted", "earlier work was compacted", {"stub": True},
                          tool="patch", weight=0.0))
        elif roll in (0, 1):
            lines = [f"def step_{i}_{k}(x):" if k % 6 == 0 else f"    return x + {k}" for k in range(rng.randint(8, 60))]
            files_created += 1
            lines_added += len(lines)
            ev.append(_ev(i, t, "file_write", f"importer/mod_{i}.py", f"+{len(lines)} in importer/mod_{i}.py",
                          {"path": f"importer/mod_{i}.py", "lang": "python", "lines": lines, "new_file": True},
                          tool="write_file", weight=w))
        elif roll == 2:
            ev.append(_ev(i, t, "file_patch", f"importer/mod_{i - 2}.py", "+2 -1", {
                "path": f"importer/mod_{i - 2}.py", "lang": "python", "adds": 2, "dels": 1, "hunks": [{
                    "header": "@@ -1,3 +1,4 @@", "lines": [[" ", "import os"], ["-", "x = 1"], ["+", "x = 2"],
                                                           ["+", "y = 3"]]}]}, tool="patch", weight=w))
        elif roll in (3, 4):
            commands += 1
            passed = rng.randint(5, 300)
            ok = rng.random() > 0.15
            out = [f"{passed} passed in {rng.uniform(0.1, 9):.2f}s"] if ok else ["1 failed", "Error: boom"]
            ev.append(_ev(i, t, "terminal", "pytest -q", out[-1], {"cmd": "pytest -q", "output_lines": out,
                                                                  "exit_code": 0 if ok else 1, "elapsed_s": 2.0},
                          tool="terminal", ok=ok, weight=w))
        elif roll == 5 and i % 48 == 5:
            shots += 1
            ev.append(_ev(i, t, "screenshot", f"page {i}", "dashboard view", {
                "path": f"assets/shot_{i}.png", "w": 1280, "h": 720, "url": f"http://localhost:8000/p{i}"},
                tool="browser_screenshot", weight=w))
        elif roll == 6:
            ev.append(_ev(i, t, "todo", "todo", "items", {"items": [
                {"text": f"task {k}", "status": rng.choice(["completed", "pending", "in_progress"])}
                for k in range(rng.randint(3, 9))]}, tool="todo", weight=w))
        elif roll == 7:
            ev.append(_ev(i, t, "web_search", f"query {i}", "search", {"query": f"importer format {i}"},
                          tool="web_search", weight=w))
        elif roll == 8:
            ev.append(_ev(i, t, "assistant_note", "assistant", "progress", {
                "text": f"The importer now handles batch {i} without dropping rows."}, weight=w))
        else:
            ev.append(_ev(i, t, "file_read", f"importer/mod_{max(0, i - 5)}.py", "read",
                          {"path": f"importer/mod_{max(0, i - 5)}.py"}, tool="read_file", weight=w))
    ev.append(_ev(n, t + 10, "final_answer", "assistant", "done", {
        "text": "The importer handles every source now and the full suite passes."}, weight=0.5))
    stats = Stats(duration_s=t + 10, turns=6, tool_calls=n - 7, files_created=files_created, files_modified=40,
                  lines_added=lines_added, lines_removed=40, commands_run=commands, commands_failed_then_fixed=9,
                  tests_passed=300, screenshots=shots, subagents=2, model="synthetic-model")
    return ev, stats


APP_JS = '''// Focusfox: a minimal pomodoro timer.
const WORK = 25 * 60, BREAK = 5 * 60;
let remaining = WORK, onBreak = false, timer = null;

export function tick(state) {
  if (state.remaining > 0) return { ...state, remaining: state.remaining - 1 };
  const onBreak = !state.onBreak;
  chime();
  return { onBreak, remaining: onBreak ? BREAK : WORK };
}

export function addTask(tasks, text) {
  const clean = text.trim();
  return clean ? [...tasks, { text: clean, done: false }] : tasks;
}

export function toggleTheme(root) {
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("focusfox-theme", root.dataset.theme);
}
'''.splitlines()

INDEX_HTML = '''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Focusfox</title><link rel="stylesheet" href="style.css"></head>
<body>
  <main class="timer"><h1 id="clock">25:00</h1><button id="start">Start</button></main>
  <section class="tasks"><input id="task" placeholder="What are you focusing on?"><ul id="list"></ul></section>
  <button id="theme">Dark mode</button>
  <script type="module" src="app.js"></script>
</body>
</html>
'''.splitlines()


def webapp_session() -> tuple[list[Event], Stats]:
    """A small web app with Auteur product captures (the product-first happy path)."""
    prompt = ("Make me a minimal pomodoro timer web app called Focusfox with a 25 and 5 minute cycle, a task "
              "list, and a dark mode toggle.")
    items = ["Timer with start and pause", "Task list", "Dark mode toggle", "Chime when a session ends", "Tests"]
    ev = [
        _ev(0, 0, "user_prompt", "user", prompt[:150], {"text": prompt}, weight=0.5),
        _ev(1, 8, "todo", "todo", "5 items", {"items": [{"text": t, "status": "pending"} for t in items]},
            tool="todo", weight=0.3),
        _ev(2, 40, "file_write", "focusfox/index.html", "+11 in focusfox/index.html", {
            "path": "focusfox/index.html", "lang": "html", "lines": INDEX_HTML, "new_file": True},
            tool="write_file", weight=0.4),
        _ev(3, 90, "file_write", "focusfox/app.js", "+22 in focusfox/app.js", {
            "path": "focusfox/app.js", "lang": "javascript", "lines": APP_JS, "new_file": True},
            tool="write_file", weight=0.6),
        _ev(4, 130, "file_write", "focusfox/style.css", "+40 in focusfox/style.css", {
            "path": "focusfox/style.css", "lang": "css", "lines": [":root { --bg: #fff8f0; --accent: #ff7a3d; }",
                                                                   "[data-theme=dark] { --bg: #1b1b22; }"],
            "new_file": True}, tool="write_file", weight=0.2),
        _ev(5, 170, "terminal", "npm test", "1 failed, 11 passed", {"cmd": "npm test", "output_lines": [
            "FAIL tests/timer.test.js", "  x tick switches to a break when the work session ends",
            "Tests: 1 failed, 11 passed, 12 total"], "exit_code": 1, "elapsed_s": 2.1}, tool="terminal", ok=False,
            weight=0.45),
        _ev(6, 200, "file_patch", "focusfox/app.js", "+1 -1 in focusfox/app.js", {
            "path": "focusfox/app.js", "lang": "javascript", "adds": 1, "dels": 1, "hunks": [{
                "header": "@@ -6,4 +6,4 @@ export function tick(state) {",
                "lines": [[" ", "export function tick(state) {"],
                          ["-", "  if (state.remaining >= 0) return { ...state, remaining: state.remaining - 1 };"],
                          ["+", "  if (state.remaining > 0) return { ...state, remaining: state.remaining - 1 };"],
                          [" ", "  const onBreak = !state.onBreak;"]]}]}, tool="patch", weight=0.5),
        _ev(7, 215, "terminal", "npm test", "12 passed", {"cmd": "npm test", "output_lines": [
            "PASS tests/timer.test.js", "Tests: 12 passed, 12 total"], "exit_code": 0, "elapsed_s": 1.9},
            tool="terminal", weight=0.7),
        _ev(8, 230, "terminal", "npx serve focusfox", "serving", {"cmd": "npx serve focusfox", "output_lines": [
            "Serving!", "Local: http://localhost:3000"], "exit_code": 0, "elapsed_s": None}, tool="terminal",
            weight=0.3),
        _ev(9, 240, "browser_nav", "localhost:3000", "opened app", {"url": "http://localhost:3000"},
            tool="browser_navigate", weight=0.1),
        _ev(10, 245, "screenshot", "Focusfox", "Focusfox timer running", {
            "path": "assets/shot_010.png", "w": 1280, "h": 800, "url": "http://localhost:3000", "product_shot": True},
            tool="browser_screenshot", weight=0.7),
        _ev(11, 250, "todo", "todo", "all done", {"items": [{"text": t, "status": "completed"} for t in items]},
            tool="todo", weight=0.2),
        _ev(12, 260, "final_answer", "assistant", "Focusfox is ready.", {"text": (
            "Focusfox is ready at http://localhost:3000. The timer runs 25 minute focus sessions with 5 minute "
            "breaks, tasks stay in the list, and the dark mode toggle remembers your choice. All 12 tests pass.")},
            weight=0.4),
        _ev(13, 262, "product_capture", "Focusfox", "Auteur capture: timer", {
            "path": "assets/capture_home.png", "url": "http://localhost:3000", "viewport": [1440, 900],
            "full_page": False, "page_title": "Focusfox"}, weight=0.95),
        _ev(14, 263, "product_capture", "Focusfox", "Auteur capture: full page", {
            "path": "assets/capture_full.png", "url": "http://localhost:3000", "viewport": [1440, 900],
            "full_page": True, "page_title": "Focusfox"}, weight=0.8),
        _ev(15, 264, "product_capture", "Focusfox dark", "Auteur capture: dark mode", {
            "path": "assets/capture_dark.png", "url": "http://localhost:3000/?theme=dark", "viewport": [1440, 900],
            "full_page": False, "page_title": "Focusfox"}, weight=0.85),
    ]
    stats = Stats(duration_s=265, turns=1, tool_calls=12, files_created=3, files_modified=1, lines_added=73,
                  lines_removed=1, commands_run=3, commands_failed_then_fixed=1, tests_passed=12, screenshots=1,
                  model="synthetic-model")
    return ev, stats


def bugfix_session() -> tuple[list[Event], Stats]:
    """A short fix: failing test, one patch, passing suite; no new files and no visuals."""
    ev = [
        _ev(0, 0, "user_prompt", "user", "CSV export crashes on empty rows", {
            "text": "The CSV export crashes on empty rows. Can you fix it?"}, weight=0.5),
        _ev(1, 10, "file_read", "ledger/export.py", "read", {"path": "ledger/export.py"}, tool="read_file"),
        _ev(2, 30, "terminal", "pytest tests/test_export.py -q", "1 failed", {
            "cmd": "pytest tests/test_export.py -q", "output_lines": [
                "F......", "E   IndexError: list index out of range", "1 failed, 6 passed in 0.22s"],
            "exit_code": 1, "elapsed_s": 0.9}, tool="terminal", ok=False, weight=0.5),
        _ev(3, 70, "file_patch", "ledger/export.py", "+2 -0 in ledger/export.py", {
            "path": "ledger/export.py", "lang": "python", "adds": 2, "dels": 0, "hunks": [{
                "header": "@@ -40,6 +40,8 @@ def write_rows(rows, fh):",
                "lines": [[" ", "    for row in rows:"], ["+", "        if not row:"], ["+", "            continue"],
                          [" ", "        fh.write(format_row(row))"]]}]}, tool="patch", weight=0.6),
        _ev(4, 85, "terminal", "pytest tests/test_export.py -q", "7 passed", {
            "cmd": "pytest tests/test_export.py -q", "output_lines": [".......", "7 passed in 0.20s"],
            "exit_code": 0, "elapsed_s": 0.8}, tool="terminal", weight=0.7),
        _ev(5, 95, "terminal", "pytest -q", "37 passed", {"cmd": "pytest -q", "output_lines": [
            "....................................", "37 passed in 1.84s"], "exit_code": 0, "elapsed_s": 2.4},
            tool="terminal", weight=0.6),
        _ev(6, 100, "final_answer", "assistant", "Fixed.", {"text": (
            "Fixed: the exporter now skips empty rows instead of crashing. The new regression test and the "
            "full suite of 37 tests pass.")}, weight=0.4),
    ]
    stats = Stats(duration_s=104, turns=1, tool_calls=5, files_modified=1, lines_added=2, commands_run=3,
                  commands_failed_then_fixed=1, tests_passed=37, model="synthetic-model")
    return ev, stats


SESSIONS = {"coding": coding_session, "tiny": tiny_chat, "browsing": browsing_session, "huge": huge_session,
            "webapp": webapp_session, "bugfix": bugfix_session}


def dump(name: str, out_dir: Path) -> Path:
    """Write one synthetic session as a harness fixture JSON."""
    events, stats = SESSIONS[name]()
    path = out_dir / f"{name}_session.json"
    payload = {"synthetic": True, "events": [e.to_dict() for e in events], "stats": stats.to_dict()}
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def seed_of(name: str) -> int:
    """Stable seed for a fixture name."""
    return zlib.crc32(name.encode("utf-8")) & 0xFFFF


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "fixtures"
    target.mkdir(exist_ok=True)
    for key in SESSIONS:
        print(dump(key, target))
