"""Speedrun milestones: which real events make good splits, and what to call them."""
from __future__ import annotations

import os

from ..contracts import Event
from .facts import (
    SessionFacts,
    image_of,
    is_setup_cmd,
    is_stub,
    looks_like_failure,
    looks_like_test_pass,
)
from .rules import SPLIT_CHARS, SPLITS_MAX


def split_label(ev: Event, seen: set[str]) -> str:
    """A short split label (<= 18 chars) for a milestone event; ``seen`` avoids repeats."""
    if ev.kind == "user_prompt":
        base = ("Run start", "New request")
    elif ev.kind == "file_write":
        name = os.path.basename(str((ev.data or {}).get("path", ""))) or "file"
        base = ("First file", name[:SPLIT_CHARS], "More code")
    elif ev.kind == "file_patch":
        base = ("First fix", "Patched", "Another fix")
    elif ev.kind == "todo":
        base = ("Plan locked", "Plan updated")
    elif ev.kind == "terminal":
        if looks_like_failure(ev):
            base = ("First red", "Red again", "Still red")
        elif looks_like_test_pass(ev):
            base = ("Tests green", "Still green", "Green again")
        else:
            base = ("First run", "It runs", "Another run")
    elif image_of(ev) is not None:
        base = ("First screen", "On screen", "Looks right")
    elif ev.kind == "final_answer":
        base = ("Shipped", "Done")
    else:
        base = ("Checkpoint", "Progress", "Moving on")
    for label in base:
        if label not in seen:
            seen.add(label)
            return label[:SPLIT_CHARS]
    label = f"{base[0][:SPLIT_CHARS - 3]} {len(seen) + 1}"
    seen.add(label)
    return label[:SPLIT_CHARS]


def detect_milestones(facts: SessionFacts, max_n: int = SPLITS_MAX) -> list[tuple[str, Event]]:
    """Real milestone events in time order: first file, first run, first red, tests green, first screen, shipped."""
    evs = [e for e in facts.events if not is_stub(e)]
    picks: list[tuple[str, Event]] = []

    def first(pred: object, label: str) -> None:
        for e in evs:
            if pred(e):  # type: ignore[operator]
                if all(e.id != p.id for _, p in picks):
                    picks.append((label, e))
                return

    first(lambda e: e.kind == "file_write", "First file")
    first_run = next((e for e in evs if e.kind == "terminal"
                      and not is_setup_cmd(str((e.data or {}).get("cmd", "")))), None)
    if first_run is not None and not looks_like_failure(first_run):
        picks.append(("First run", first_run))
    first(looks_like_failure, "First red")
    reds = [e for e in evs if looks_like_failure(e)]
    if reds:
        first(lambda e: looks_like_test_pass(e) and e.t > reds[0].t, "Tests green")
    else:
        first(looks_like_test_pass, "Tests green")
    first(lambda e: image_of(e) is not None, "First screen")
    finals = [e for e in evs if e.kind == "final_answer"]
    if finals and all(finals[-1].id != p.id for _, p in picks):
        picks.append(("Shipped", finals[-1]))
    picks.sort(key=lambda p: (p[1].t, facts.order.get(p[1].id, 0)))
    out: list[tuple[str, Event]] = []
    for label, ev in picks:
        if out and ev.t <= out[-1][1].t:
            continue  # splits must strictly increase in session time
        out.append((label, ev))
    if len(out) > max_n:
        keep = [out[0]] + out[1:-1][: max_n - 2] + [out[-1]]
        out = keep
    return out
