"""Interestingness weights (0..1) for events, used by the digest and the heuristic storyboard.

The heuristic favours what makes a good promo shot. Product-first: deliverable artifacts and
screenshots of the product rank highest (0.9+), then the user's first request, big diffs, new
files with real code, green tests after red, other images, and the final answer. Routine reads,
searches and meta tools sink. Repeated looks at the same image decay.
"""
from __future__ import annotations

from ..contracts import Event
from .textutil import basename

_ARTIFACT_W = {"web": 0.97, "image": 0.93, "video": 0.93, "audio": 0.6, "pdf": 0.7, "doc": 0.55, "data": 0.5,
               "code": 0.55, "other": 0.6}
_CODE_LANGS = {"python", "javascript", "typescript", "tsx", "jsx", "rust", "go", "java", "kotlin", "c", "cpp",
               "csharp", "ruby", "php", "swift", "lua", "glsl", "html", "css", "scss", "vue", "svelte", "bash",
               "sql", "dart", "scala", "zig", "gdscript", "elixir", "powershell"}

_BASE = {
    "user_prompt": 0.4, "assistant_note": 0.12, "final_answer": 0.8, "file_write": 0.35, "file_patch": 0.3,
    "file_read": 0.04, "terminal": 0.15, "browser_nav": 0.25, "screenshot": 0.5, "image_generated": 0.8,
    "web_search": 0.12, "web_extract": 0.1, "todo": 0.35, "delegate": 0.45, "skill": 0.06, "clarify": 0.3,
    "tool_other": 0.04,
}


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def assign_weights(events: list[Event]) -> None:
    """Set ``event.weight`` in place."""
    first_prompt_done = False
    first_todo_done = False
    seen_images: dict[str, int] = {}
    for ev in events:
        d = ev.data
        w = _BASE.get(ev.kind, 0.05)
        if ev.kind == "user_prompt":
            if not first_prompt_done:
                w, first_prompt_done = 0.95, True
            elif d.get("steer"):
                w = 0.3
        elif ev.kind == "assistant_note":
            if d.get("turn_end"):
                w = 0.3
            if d.get("media"):
                w = max(w, 0.6)
        elif ev.kind == "final_answer":
            w = 0.95 if d.get("media") else 0.8
        elif ev.kind == "file_patch":
            size = int(d.get("adds") or 0) + int(d.get("dels") or 0)
            w = 0.3 + 0.5 * min(1.0, size / 60.0)
            if d.get("lang") in _CODE_LANGS:
                w += 0.05
        elif ev.kind == "file_write":
            n = int(d.get("total_lines") or 0)
            w = 0.3 + 0.4 * min(1.0, n / 150.0) + (0.1 if d.get("new_file") else 0.0)
            if d.get("lang") in _CODE_LANGS:
                w += 0.08
            elif d.get("lang") in ("markdown", "text", "json", ""):
                w -= 0.08
        elif ev.kind == "terminal":
            tests = d.get("tests")
            if tests and not tests.get("failed") and tests.get("passed"):
                w = 0.7
            elif tests:
                w = 0.35
            if d.get("fixed"):
                w = max(w, 0.75)
            if d.get("tests_green_after_red"):
                w = 0.9
            if not ev.ok:
                w = min(w, 0.25)
        elif ev.kind in ("screenshot", "image_generated"):
            key = str(d.get("src_key") or d.get("url") or ev.id)
            n = seen_images.get(key, 0)
            seen_images[key] = n + 1
            if d.get("artifact"):
                w = 0.9
            elif d.get("source") == "vision_analyze":
                w = 0.45
            w *= 0.5 ** n                      # the same image looked at again is less novel
        elif ev.kind == "todo":
            items = d.get("items") or []
            if not first_todo_done:
                w, first_todo_done = 0.5, True
            elif items and d.get("done") == len(items):
                w = 0.45
            else:
                w = 0.2
        elif ev.kind == "delegate":
            w = 0.5 if d.get("completed") else 0.45
        elif ev.kind == "artifact":
            w = _ARTIFACT_W.get(str(d.get("kind") or ""), 0.5)
            if basename(str(d.get("path") or "")).lower().startswith("readme"):
                w = 0.5
            if d.get("delivered"):
                w += 0.03
            if d.get("exists") is False:
                w *= 0.4
        elif ev.kind == "product_capture":
            w = 1.0
        if d.get("product_shot") and ev.kind in ("screenshot", "image_generated"):
            first_look = seen_images.get(str(d.get("src_key") or d.get("url") or ev.id), 1) <= 1
            w = max(w, 0.92 if first_look else 0.5)
        if d.get("stub"):
            w *= 0.5 if ev.kind in ("terminal", "file_read", "tool_other", "assistant_note") else 0.85
        if d.get("missing"):
            w *= 0.3
        if not ev.ok and ev.kind not in ("terminal",):
            w *= 0.5
        ev.weight = _clamp(w)
