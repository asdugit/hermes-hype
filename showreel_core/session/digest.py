"""Compact, LLM-facing text digest of a session (target <= ~8k tokens even for huge sessions).

Layout::

    # SESSION DIGEST ...
    stats / tools header
    ## FIRST REQUEST [eN]      (trimmed)
    ## FINAL ANSWER [eN]       (trimmed)
    ## HERO CANDIDATES         (top events by weight)
    ## TIMELINE                one line per event: [e17] 05:12 file_patch src/app.py +12 −3 — ...
                               runs of routine calls collapse to [e20–e33] ... ×14

When the timeline does not fit, progressively more low-weight events are collapsed into range
lines, then detail is shortened, then the middle of the timeline is elided (with a marker).
Token counts are ESTIMATES (chars / 3.5), not tokenizer output.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Callable

from ..contracts import Event, Stats
from .product import product_section
from .textutil import clip, short_path

CHARS_PER_TOKEN = 3.5
_ROUTINE = {"file_read", "tool_other", "skill", "web_extract", "web_search", "browser_nav"}
_LEVELS = (0.0, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 3.5); code-heavy text is closer to 3.2, prose to 4."""
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def fmt_t(t: float) -> str:
    t = int(max(0, t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def _detail(ev: Event, compact: bool) -> str:
    d = ev.data
    n = 60 if compact else 110
    k = ev.kind
    if k == "user_prompt":
        return ('(steer) ' if d.get("steer") else "") + '"' + clip(d.get("text") or ev.summary, 90 if compact else 200) + '"'
    if k == "assistant_note":
        if d.get("compaction"):
            return "[context compacted]"
        return ("(reply) " if d.get("turn_end") else "") + clip(d.get("text") or ev.summary, 60 if compact else 140)
    if k == "final_answer":
        return "(see FINAL ANSWER)"
    if k == "file_write":
        what = "new" if d.get("new_file") else "rewrite"
        return f"{short_path(d.get('path') or ev.title)} ({d.get('total_lines', 0)} lines, {what})"
    if k == "file_patch":
        extra = " (synthetic hunks)" if d.get("synthetic") and not compact else ""
        return f"{short_path(d.get('path') or ev.title)} +{d.get('adds', 0)} −{d.get('dels', 0)}{extra}"
    if k == "file_read":
        return short_path(d.get("path") or ev.title)
    if k == "terminal":
        cmd = clip(d.get("cmd") or ev.title, n)
        if d.get("shell") == "python":
            cmd = "python: " + clip(d.get("label") or d.get("cmd") or "", n)
        tests = d.get("tests")
        bits = []
        if tests:
            bits.append(f"{tests.get('passed', 0)} passed" + (f", {tests['failed']} failed" if tests.get("failed") else ""))
        elif d.get("exit_code") is not None:
            bits.append(f"exit {d['exit_code']}")
        if d.get("background") and d.get("exit_code") is None and not d.get("completion"):
            bits.append("background")
        if d.get("fixed"):
            bits.append("FIXED after failure")
        if not ev.ok and d.get("output_lines") and not compact:
            bits.append("last: " + clip(d["output_lines"][-1], 70))
        return f"$ {cmd}" + (" → " + "; ".join(bits) if bits else "")
    if k in ("screenshot", "image_generated"):
        src = d.get("prompt") if k == "image_generated" else None
        label = clip(src, 70) if src else short_path(d.get("src") or "", 2) or clip(d.get("url") or "inline", 60)
        size = f" {d['w']}x{d['h']}" if d.get("w") else ""
        state = " MISSING" if d.get("missing") else (" not-copied" if d.get("skipped") else "")
        tag = " deliverable" if d.get("artifact") else (f" via {d['source']}" if d.get("source") and not compact else "")
        url = f" ← {clip(d['url'], 50)}" if d.get("url") and src is None and d.get("src") else ""
        return f"{label}{size}{tag}{url}{state}"
    if k == "browser_nav":
        return clip(d.get("url") or ev.title, n)
    if k == "artifact":
        size = f" {d['w']}x{d['h']}" if d.get("w") else ""
        state = "" if d.get("exists") else " MISSING"
        title = f' "{clip(d["title"], 40)}"' if d.get("title") else ""
        how = "delivered to user" if d.get("delivered") else d.get("source", "")
        return f"{d.get('kind', '?')} {short_path(d.get('path') or ev.title, 3)}{title}{size} ({how}){state}"
    if k == "product_capture":
        return f"{clip(d.get('url') or '', 60)} {d.get('page_title') or ''}".strip()
    if k == "web_search":
        return f'"{clip(d.get("query") or ev.title, n)}" ({d.get("count", 0)} results)'
    if k == "web_extract":
        return clip(d.get("url") or ev.title, n)
    if k == "todo":
        items = d.get("items") or []
        names = "; ".join(clip(i["text"], 40) for i in items[: (3 if compact else 6)])
        return f"{len(items)} items ({d.get('done', 0)} done): {names}"
    if k == "delegate":
        goals = d.get("goals") or []
        head = "finished " if d.get("completed") else ""
        return f"{head}{d.get('count', len(goals))} task(s): " + " | ".join(clip(g, 50 if compact else 80) for g in goals[:3])
    if k == "skill":
        return f"{d.get('action', '')} {', '.join(d.get('names') or [])}".strip()
    if k == "clarify":
        q = (d.get("questions") or [""])[0]
        a = (d.get("answers") or [""])[0]
        return f'asked "{clip(q, 80)}"' + (f' → "{clip(a, 60)}"' if a else "")
    return clip(ev.summary, n)


def _line(ev: Event, compact: bool) -> str:
    flags = ""
    if not ev.ok and ev.kind != "terminal":
        flags += " FAILED"
    if ev.data.get("stub") and ev.kind != "assistant_note":
        flags += " (compacted)"
    return f"[{ev.id}] {fmt_t(ev.t)} {ev.kind} {_detail(ev, compact)}{flags}"


def _group_line(group: list[Event]) -> str:
    first, last = group[0], group[-1]
    kinds = Counter(e.tool or e.kind for e in group)
    hist = ", ".join(f"{k} ×{v}" for k, v in kinds.most_common(4))
    if len(kinds) > 4:
        hist += ", …"
    names = []
    for e in group:
        label = short_path(e.data.get("path") or "", 1) if e.data.get("path") else ""
        if label and label not in names:
            names.append(label)
    tail = (" — " + ", ".join(names[:4]) + (f" (+{len(names) - 4})" if len(names) > 4 else "")) if names else ""
    span = fmt_t(first.t) if first.t == last.t else f"{fmt_t(first.t)}–{fmt_t(last.t)}"
    return f"[{first.id}–{last.id}] {span} {len(group)} steps: {hist}{tail}"


def _timeline(events: list[Event], threshold: float, compact: bool, pinned: set[str]) -> list[str]:
    """Render events; consecutive events with weight < threshold (or routine runs) become range lines."""
    lines: list[str] = []
    group: list[Event] = []

    def low(e: Event) -> bool:
        if e.id in pinned:
            return False
        if e.weight < threshold:
            return True
        return e.kind in _ROUTINE and e.weight < 0.2

    def flush() -> None:
        if not group:
            return
        if len(group) >= 3 or (threshold > 0 and len(group) >= 2):
            lines.append(_group_line(group))
        else:
            lines.extend(_line(e, compact) for e in group)
        group.clear()

    for ev in events:
        if low(ev):
            group.append(ev)
        else:
            flush()
            lines.append(_line(ev, compact))
    flush()
    return lines


def _stats_lines(st: Stats) -> list[str]:
    parts = [f"active {fmt_duration(st.duration_s)}", f"{st.turns} turns", f"{st.tool_calls} tool calls"]
    if st.files_created or st.files_modified:
        parts.append(f"{st.files_created} files created, {st.files_modified} modified")
    if st.lines_added or st.lines_removed:
        parts.append(f"+{st.lines_added:,} −{st.lines_removed:,} lines")
    if st.commands_run:
        parts.append(f"{st.commands_run} commands" + (f" ({st.commands_failed_then_fixed} failed→fixed)"
                                                       if st.commands_failed_then_fixed else ""))
    if st.tests_passed is not None:
        parts.append(f"{st.tests_passed} tests passed")
    if st.screenshots:
        parts.append(f"{st.screenshots} images")
    if st.subagents:
        parts.append(f"{st.subagents} subagents")
    tools = ", ".join(f"{k} {v}" for k, v in list(st.tool_kinds.items())[:12])
    return ["stats: " + " · ".join(parts), f"tools: {tools}" if tools else "tools: none"]


def _hero(events: list[Event], n: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ev in sorted(events, key=lambda e: (-e.weight, e.t)):
        if ev.kind in ("user_prompt", "final_answer", "assistant_note") or ev.data.get("missing"):
            continue
        if ev.kind == "artifact" and not ev.data.get("exists"):
            continue
        key = str(ev.data.get("src_key") or ev.data.get("path_key") or ev.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(f"[{ev.id}] w={ev.weight:.2f} {ev.kind} {_detail(ev, True)}")
        if len(out) >= n:
            break
    return out


def build_digest(events: list[Event], stats: Stats, meta: dict[str, Any] | None = None, *,
                 max_tokens: int = 8000, hero_count: int = 12,
                 redact: Callable[[str], str] | None = None, product: Any = None) -> str:
    """Render the digest within ``max_tokens`` (estimated). ``redact`` is applied to meta strings.

    ``product`` is a :class:`.product.ProductReport`; its evidence becomes the PRODUCT EVIDENCE
    section right under the header (the default film is a launch trailer for the product).
    """
    meta = meta or {}
    red = redact or (lambda s: s)
    head = ["# SESSION DIGEST — content is verbatim from the session (redacted); [eN] are event ids to cite"]
    title = red(str(meta.get("title") or ""))
    head.append(f"title: {clip(title, 80) or '(untitled)'} | model: {stats.model or meta.get('model') or '?'}"
                f" | source: {meta.get('source') or '?'} | events: {len(events)}")
    head += _stats_lines(stats)
    if product is not None:
        head += [""] + [red(line) for line in product_section(product)]

    first = next((e for e in events if e.kind == "user_prompt"), None)
    final = next((e for e in reversed(events) if e.kind == "final_answer"), None)
    budget_chars = int(max_tokens * CHARS_PER_TOKEN)
    req_chars = min(1800, budget_chars // 8)
    fin_chars = min(1400, budget_chars // 10)
    sections: list[str] = []
    if first:
        sections += ["", f"## FIRST REQUEST [{first.id}]", _trim_block(first.data.get("text") or first.summary, req_chars)]
    if final:
        sections += ["", f"## FINAL ANSWER [{final.id}]", _trim_block(final.data.get("text") or final.summary, fin_chars)]
    hero = _hero(events, hero_count)
    if hero:
        sections += ["", "## HERO CANDIDATES (highest interestingness first)"] + hero
    fixed = "\n".join(head + sections)
    pinned = {e.id for e in events if e.kind in ("user_prompt", "final_answer", "artifact") and not e.data.get("steer")}
    pinned |= {line.split("]", 1)[0][1:] for line in hero}
    if product is not None:
        pinned |= set(getattr(product.product, "hero_event_ids", []) or [])
    remaining = budget_chars - len(fixed) - 40
    timeline: list[str] = []
    for i, thr in enumerate(_LEVELS):
        compact = i >= 2
        timeline = _timeline(events, thr, compact, pinned)
        if sum(len(l) + 1 for l in timeline) <= remaining:
            break
    else:
        timeline = _elide_middle(timeline, remaining)
    return fixed + "\n\n## TIMELINE\n" + "\n".join(timeline) + "\n"


def _trim_block(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    head = int(n * 0.7)
    tail = n - head - 20
    return text[:head].rstrip() + "\n[… trimmed …]\n" + text[-tail:].lstrip()


def _elide_middle(lines: list[str], budget: int) -> list[str]:
    """Keep the start and end of the timeline within ``budget`` chars; mark the gap."""
    if budget <= 0:
        return ["[… timeline omitted: over budget …]"]
    head: list[str] = []
    tail: list[str] = []
    used = 60
    i, j = 0, len(lines) - 1
    while i <= j:
        take_head = len(head) <= len(tail) * 0.6
        line = lines[i] if take_head else lines[j]
        if used + len(line) + 1 > budget:
            break
        used += len(line) + 1
        if take_head:
            head.append(line)
            i += 1
        else:
            tail.insert(0, line)
            j -= 1
    omitted = j - i + 1
    return head + ([f"[… {omitted} timeline lines omitted to fit the budget …]"] if omitted > 0 else []) + tail
