"""Stand-ins for shots whose scene cannot be drawn: one broken shot never sinks a whole film.

A kit scene can still throw in ``setup()`` on the final, strict page (a param it cannot read, an asset the job does
not have); before this, the page refused to load and the whole job failed (``page_broken``, FAILURES #31: a 32 min
Directed game film died on one ``kit:pixel/FEATURE`` shot). The engine instead swaps that shot for a safe card:

- the product picture the shot meant to show (else the film's first picture), whole on the base kit's borderless
  card (``kit:base/SCREEN``, ``frame: card``), themed like the shot's kit where the base kit has that theme;
- else a type card with the film's title (``kit:type/title``);
- else nothing: the caller drops the shot and lets its neighbour hold.

Pure functions on dicts (no I/O); callers say which kits the page has and which assets it carries.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

WHOLE_BBOX = [0.03, 0.03, 0.94, 0.94]
BASE_THEMES = ("terminal", "blueprint", "comic", "ink", "launch", "noir", "anime")
CARD_SCENE = "kit:base/SCREEN"
TYPE_SCENE = "kit:type/title"
#: "shot 'feat-paddle' (kit:pixel/FEATURE): setup() threw: ..." (runtime.js ``_create`` on a strict page)
BROKEN_RE = re.compile(r"\b(shot|overlay) '([^']+)' \(([^)\s]+)\): (.*)", re.DOTALL)
_REF_KEYS = ("asset", "id", "name", "src", "path")


def broken_item(message: str) -> tuple[str, str, str, str] | None:
    """``(kind, id, scene, why)`` of the shot/overlay a strict page names in its load error, else None."""
    m = BROKEN_RE.search(str(message or ""))
    return (m.group(1), m.group(2), m.group(3), m.group(4).strip()) if m else None


def _names_in(v: Any, out: list[str]) -> None:
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, Mapping):
        for k in _REF_KEYS:
            if isinstance(v.get(k), str):
                out.append(v[k])
        for x in v.values():
            if isinstance(x, (Mapping, list)):
                _names_in(x, out)
    elif isinstance(v, list):
        for x in v:
            _names_in(x, out)


def picture_of(shot: Mapping[str, Any], pictures: Sequence[str]) -> str:
    """The picture the shot meant to show (the first of ``pictures`` its params name), else the first picture."""
    found: list[str] = []
    _names_in(shot.get("params") or {}, found)
    return next((n for n in found if n in pictures), pictures[0] if pictures else "")


def stand_in(shot: Mapping[str, Any], *, pictures: Sequence[str], kits: Iterable[str], title: str = ""
             ) -> dict[str, Any] | None:
    """A copy of ``shot`` drawn by a safe kit scene (same id and timing), or None when the page has no such kit."""
    kits = set(kits)
    scene = str(shot.get("scene") or "")
    kit = scene.split(":", 1)[1].split("/")[0] if scene.startswith("kit:") else ""
    pic = picture_of(shot, pictures)
    out = {k: copy.deepcopy(v) for k, v in shot.items() if k not in ("params", "res", "upscale")}
    if pic and "base" in kits:
        p: dict[str, Any] = {"image": {"asset": pic, "frame": "card"}, "bbox": list(WHOLE_BBOX)}
        if kit in BASE_THEMES:
            p["theme"] = kit
        out.update(scene=CARD_SCENE, params=p)
        return out
    if title.strip() and "type" in kits:
        out.update(scene=TYPE_SCENE, params={"text": title.strip()})
        return out
    return None


def drop_shot(film: dict[str, Any], sid: str) -> bool:
    """Remove shot ``sid`` IN PLACE: its neighbour holds over its time (the previous shot runs on, or the next one
    starts early) and transitions through it join the neighbours. False when it is the only shot."""
    shots = film.get("shots") or []
    i = next((k for k, s in enumerate(shots) if isinstance(s, dict) and str(s.get("id")) == sid), None)
    if i is None or len(shots) < 2:
        return False
    gone = shots.pop(i)
    if i > 0:
        prev = shots[i - 1]
        prev["t1"] = max(float(prev.get("t1", 0)), float(gone.get("t1", 0)))
        keep = str(prev.get("id"))
    else:
        nxt = shots[0]
        nxt["t0"] = min(float(nxt.get("t0", 0)), float(gone.get("t0", 0)))
        keep = str(nxt.get("id"))
    trans = []
    for tr in film.get("transitions") or []:
        if not isinstance(tr, dict):
            continue
        a, b = str(tr.get("from")), str(tr.get("to"))
        if sid not in (a, b):
            trans.append(tr)
        elif i > 0 and a == sid and b != keep:          # broken -> next becomes previous -> next
            trans.append({**tr, "from": keep})
    film["transitions"] = trans
    return True
