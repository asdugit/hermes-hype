"""Patch-style revisions: targeted film.json edits (by shot id) and search/replace edits of scene code.

Whole-file rewrites fixed the critic's named issues and broke other things (t1, t3). Patches change only what
an issue needs, so every untouched shot and every untouched line of scene code stays byte-identical.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# ------------------------------------------------------------------------------------ film patches

LIST_KEYS = ("transitions", "overlays", "captions", "cues", "music")


def deep_merge(base: Any, patch: Any) -> Any:
    """``patch`` merged into ``base``: dicts merge recursively, ``None`` deletes a key, anything else replaces."""
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = dict(base)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def apply_film_patch(film: dict[str, Any], plan: dict[str, Any], patch: dict[str, Any]
                     ) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    """Apply a revision patch. Returns (film, plan, errors, touched shot ids).

    Patch shape (every key optional)::

        {"shots": [{"id": "field", "params": {"time": "pastel", "flyers": [...]}},          # deep-merged params
                   {"id": "boss", "params_replace": {...}},                                # params replaced
                   {"id": "walk", "t0": 0, "t1": 6.5},                                     # retimed
                   {"id": "old", "remove": true},
                   {"id": "new", "t0": 12, "t1": 15, "scene": "kit:...", "params": {...}}],   # added
         "transitions"|"overlays"|"captions"|"cues"|"music": [...full replacement list...],
         "finish": {...}, "title": "...",
         "plan_shots": [{"id", "intent", "product_visible", "beats"}], "custom_scenes": [{name, ...spec}],
         "voiceover": [{"t", "text"}]}
    """
    film = copy.deepcopy(film)
    plan = copy.deepcopy(plan)
    errors: list[str] = []
    touched: list[str] = []
    shots = {s["id"]: s for s in film.get("shots") or []}
    order = [s["id"] for s in film.get("shots") or []]
    for i, sp in enumerate(patch.get("shots") or []):
        if not isinstance(sp, dict) or not str(sp.get("id") or "").strip():
            errors.append(f"patch shots[{i}] needs an `id`")
            continue
        sid = str(sp["id"])
        if sp.get("remove"):
            if sid in shots:
                shots.pop(sid)
                order.remove(sid)
                touched.append(sid)
            continue
        cur = shots.get(sid)
        if cur is None:
            missing = [k for k in ("t0", "t1", "scene") if k not in sp]
            if missing:
                errors.append(f"new shot `{sid}` needs {missing} (or use an existing id: {order})")
                continue
            cur = {"id": sid, "t0": sp["t0"], "t1": sp["t1"], "scene": sp["scene"], "res": sp.get("res"),
                   "params": {}}
            shots[sid] = cur
            order.append(sid)
        for k in ("t0", "t1", "scene", "res", "z", "upscale"):
            if k in sp:
                cur[k] = copy.deepcopy(sp[k])
        if isinstance(sp.get("params_replace"), dict):
            cur["params"] = copy.deepcopy(sp["params_replace"])
        elif isinstance(sp.get("params"), dict):
            cur["params"] = deep_merge(cur.get("params") or {}, sp["params"])
        touched.append(sid)
    film["shots"] = sorted((shots[s] for s in order), key=lambda s: float(s.get("t0", 0)))
    for k in LIST_KEYS:
        if isinstance(patch.get(k), list):
            film[k] = copy.deepcopy(patch[k])
    if isinstance(patch.get("finish"), dict):
        film["finish"] = deep_merge(film.get("finish") or {}, patch["finish"])
    if str(patch.get("title") or "").strip():
        film["title"] = str(patch["title"])
    intents = {p.get("id"): p for p in plan.get("shots") or [] if isinstance(p, dict)}
    for p in patch.get("plan_shots") or []:
        if isinstance(p, dict) and p.get("id"):
            intents[p["id"]] = deep_merge(intents.get(p["id"]) or {"id": p["id"]}, p)
    plan["shots"] = [intents[s["id"]] for s in film["shots"] if s["id"] in intents]
    specs = {c.get("name"): c for c in plan.get("custom_scenes") or [] if isinstance(c, dict)}
    for c in patch.get("custom_scenes") or []:
        if isinstance(c, dict) and c.get("name"):
            specs[c["name"]] = deep_merge(specs.get(c["name"]) or {}, c)
    plan["custom_scenes"] = list(specs.values())
    if isinstance(patch.get("voiceover"), list):
        plan["voiceover"] = copy.deepcopy(patch["voiceover"])
    return film, plan, errors, touched


def shot_diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Shot ids whose definition differs between two films (added, removed or changed)."""
    a = {s["id"]: s for s in old.get("shots") or []}
    b = {s["id"]: s for s in new.get("shots") or []}
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


# ------------------------------------------------------------------------------------ code patches

_BLOCK_RE = re.compile(r"<{5,9} ?SEARCH[^\n]*\n(.*?)\n?={5,9}[^\n]*\n(.*?)\n?>{5,9} ?REPLACE", re.DOTALL)


def parse_blocks(text: str) -> list[tuple[str, str]]:
    """``<<<<<<< SEARCH / ======= / >>>>>>> REPLACE`` blocks from a model reply (in order)."""
    return [(m.group(1), m.group(2)) for m in _BLOCK_RE.finditer(text or "")]


def _norm(line: str) -> str:
    return line.rstrip()


def apply_blocks(code: str, blocks: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Apply search/replace blocks in order. Returns (new code, failures). Exact match first, then a
    line-by-line match that ignores trailing whitespace and indentation differences."""
    failures: list[str] = []
    for k, (search, replace) in enumerate(blocks):
        if not search.strip():
            failures.append(f"block {k + 1}: empty SEARCH")
            continue
        n = code.count(search)
        if n == 1:
            code = code.replace(search, replace, 1)
            continue
        if n > 1:
            failures.append(f"block {k + 1}: SEARCH matches {n} places; include more context lines")
            continue
        lines = code.split("\n")
        want = [_norm(x).strip() for x in search.split("\n")]
        while want and not want[-1]:
            want.pop()
        while want and not want[0]:
            want.pop(0)
        hits = [i for i in range(len(lines) - len(want) + 1)
                if [_norm(x).strip() for x in lines[i:i + len(want)]] == want] if want else []
        if len(hits) == 1:
            i = hits[0]
            lines[i:i + len(want)] = replace.split("\n")
            code = "\n".join(lines)
        elif hits:
            failures.append(f"block {k + 1}: SEARCH matches {len(hits)} places; include more context lines")
        else:
            first = next((x for x in search.split("\n") if x.strip()), "")[:100]
            failures.append(f"block {k + 1}: SEARCH text not found in the current code (starts: {first!r}); "
                            "copy the lines exactly")
    return code, failures
