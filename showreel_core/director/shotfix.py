"""Engine shot fixes: a bounded, model-free revision of the WORST shots (any model, with or without vision).

Weak models' own free-form revisions made films worse in trials (noir: 5.7 -> 4.7, best-of kept v1), so weak tiers
used to get one critique and nothing else: the critique fixed nothing. This module turns the critique (the vision
critic's per-shot scores/issues, or the measured review) plus the engine's own measurements into a small set of
safe, deterministic edits on the 1-2 worst shots:

- the product reads small / missing in a screen-product shot drawn by a style kit -> the same capture on the base
  kit's large browser frame (``kit:base/SCREEN`` / ``FEATURE``: 1560 px wide, pushing in), themed like the film;
- text that the layout QA flags (clipped, overlapping, too small) or the critic calls hard to read -> the line is
  cut to its first words at a phrase boundary, a subtitle under it dropped, and a scrim put behind overlay type;
- a type card measured as one flat colour (an unfilled line) -> the product name.

Each fix is logged; the engine re-renders only the changed shots, measures and critiques once more, and best-of
keeps whichever version scored higher. Pure functions on dicts (no I/O).
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Sequence
from typing import Any

from .repair import fit_words

SMALL = 0.32                 # a product narrower than this (share of the frame width) reads small
TEXT_KEYS = ("text", "label", "tagline", "title", "sub", "feature", "caption", "line")
TEXT_WORDS = re.compile(r"\b(text|type|title|caption|label|legib|read|tiny|small font|overlap|clip|cut off|"
                        r"truncat|cramped)\w*", re.IGNORECASE)
PRODUCT_WORDS = re.compile(r"\b(product|app|ui|screen|interface|capture|screenshot)\b.*\b(small|tiny|lost|hard to "
                           r"see|barely|distant|far|cropped|cut off|unclear|dark|murky)|\b(small|tiny|barely|hard "
                           r"to see)\b.*\b(product|app|ui|screen|interface)", re.IGNORECASE)
CROP_WORDS = re.compile(r"\b(crop\w*|cut off|runs? off|off[- ]frame|off the (frame|edge)|edges?|bounded|breathing "
                        r"room|partial\w*|half[- ]visible|too tight|tight)\b", re.IGNORECASE)
WHOLE_BBOX = [0.03, 0.03, 0.94, 0.94]
BASE_THEMES = ("terminal", "blueprint", "comic", "ink", "launch", "noir", "anime")


def _kit(scene: str) -> str:
    return scene.split(":", 1)[1].split("/")[0] if scene.startswith("kit:") else ""


def _image_of(params: dict[str, Any], product: set[str]) -> Any:
    for k in ("image", "hero", "media", "product"):
        v = params.get(k)
        name = v.get("asset") if isinstance(v, dict) else v
        if isinstance(name, str) and (not product or name in product):
            return {"asset": name} if not isinstance(v, dict) else {"asset": name}
    return None


def worst_shots(film: dict[str, Any], critique: dict[str, Any] | None, per_shot: dict[str, dict[str, Any]],
                qa: Sequence[dict[str, Any]] = (), n: int = 2, cropped: Iterable[str] = ()) -> list[str]:
    """Shot ids ranked worst first: critic per-shot score, then issue severity, measured small product, QA text."""
    crit = critique or {}
    score = {str(s.get("id")): float(s.get("score") or 7.0) for s in crit.get("shots") or [] if isinstance(s, dict)}
    sev: dict[str, float] = {}
    for it in crit.get("per_shot_issues") or []:
        if isinstance(it, dict):
            sid = str(it.get("shot") or "")
            sev[sid] = sev.get(sid, 0.0) + float(it.get("severity") or 1)
    for q in qa:
        if str(q.get("kind")) in ("clip", "overlap", "small_text") and q.get("shot"):
            sev[str(q["shot"])] = sev.get(str(q["shot"]), 0.0) + 1.0
    for sid in cropped:
        sev[str(sid)] = sev.get(str(sid), 0.0) + 1.0
    rows = []
    for s in film.get("shots") or []:
        sid = str(s.get("id"))
        d = per_shot.get(sid) or {}
        small = 1.0 if d and d.get("visible") and float(d.get("max_width") or 1.0) < SMALL else 0.0
        bad = sev.get(sid, 0.0) + small
        if bad <= 0 and score.get(sid, 7.0) >= 6.5:
            continue
        rows.append((score.get(sid, 7.0) - 0.8 * bad, sid))
    rows.sort()
    return [sid for _, sid in rows[:n]]


def _issues_of(critique: dict[str, Any] | None, sid: str) -> list[str]:
    return [f"{it.get('issue', '')} {it.get('fix', '')}" for it in (critique or {}).get("per_shot_issues") or []
            if isinstance(it, dict) and str(it.get("shot")) == sid]


_WEAK_END = {"a", "an", "the", "of", "to", "and", "or", "in", "on", "for", "with", "that", "my", "your", "its",
             "their", "our", "at", "by", "from", "is", "are", "was", "be"}


def cut(text: str, words: int) -> str:
    """At most ``words`` words: a clean phrase boundary when there is one (repair.fit_words), else the first words
    without a dangling article/preposition at the end ('' when nothing sensible is left)."""
    nv = fit_words(text, words)
    if nv:
        return nv
    ws = text.split()[:words]
    while ws and ws[-1].lower() in _WEAK_END:
        ws.pop()
    return " ".join(ws).rstrip(",;:") if len(ws) >= 2 else ""


def _shorten(params: dict[str, Any], words: int = 4) -> list[str]:
    done = []
    for k in TEXT_KEYS:
        v = params.get(k)
        if isinstance(v, str) and len(v.split()) > words:
            nv = cut(v, words)
            if nv and nv != v:
                params[k] = nv
                done.append(f"{k} '{v[:40]}' -> '{nv}'")
    if params.get("sub") and isinstance(params.get("sub"), str) and len(params["sub"].split()) > 6:
        params.pop("sub")
        done.append("dropped the subtitle")
    return done


def fix_worst(film: dict[str, Any], plan: dict[str, Any], *, critique: dict[str, Any] | None,
              per_shot: dict[str, dict[str, Any]], qa: Sequence[dict[str, Any]] = (), product: Iterable[str] = (),
              screen: bool = True, theme: str = "", name: str = "", n: int = 2, cropped: Iterable[str] = ()
              ) -> tuple[dict[str, Any], list[str]]:
    """A copy of ``film`` with engine fixes on the worst shots, and what changed ([] = nothing to fix safely)."""
    prod = set(product)
    out = copy.deepcopy(film)
    changes: list[str] = []
    intents = {str(p.get("id")): p for p in plan.get("shots") or [] if isinstance(p, dict)}
    qa_by: dict[str, list[dict[str, Any]]] = {}
    for q in qa:
        if q.get("shot"):
            qa_by.setdefault(str(q["shot"]), []).append(q)
    by_id = {str(s.get("id")): s for s in out.get("shots") or []}
    crop = {str(x) for x in cropped}
    for sid in worst_shots(film, critique, per_shot, qa, n=n, cropped=crop):
        s = by_id.get(sid)
        if s is None:
            continue
        scene = str(s.get("scene", ""))
        p = s.setdefault("params", {})
        notes = " ".join(_issues_of(critique, sid))
        d = per_shot.get(sid) or {}
        wants = bool((intents.get(sid) or {}).get("product_visible"))
        small = bool(d) and (not d.get("visible") or float(d.get("max_width") or 0.0) < SMALL)
        img = _image_of(p, prod)
        kit = _kit(scene)
        bb = p.get("bbox")
        aimed = isinstance(bb, list) and len(bb) == 4 and float(bb[2]) < 0.9     # a deliberate push-in (content box)
        # measured edge contact is a crop only when the shot did not aim at a region on purpose; the critic's words
        # always count
        cut_off = (sid in crop and not aimed) or bool(CROP_WORDS.search(notes))
        if wants and img is not None and kit == "base" and cut_off and not (
                isinstance(p.get("image"), dict) and p["image"].get("frame") == "card"):
            # the base frame pushed the capture past the frame edges: show the picture whole on a card
            p["image"] = {**(p["image"] if isinstance(p.get("image"), dict) else img), "frame": "card"}
            p["bbox"] = list(WHOLE_BBOX)
            changes.append(f"{sid}: the product ran off the frame -> shown whole (card, no push past the edges)")
            continue
        if (screen and wants and img is not None and kit not in ("", "base", "type", "frames")
                and (small or cut_off or PRODUCT_WORDS.search(notes))):
            to = "kit:base/FEATURE" if p.get("feature") else "kit:base/SCREEN"
            np: dict[str, Any] = {"image": img}
            if p.get("feature"):
                np["feature"] = cut(str(p["feature"]), 5) or str(p["feature"])
            th = theme or (kit if kit in BASE_THEMES else "")
            if th:
                np["theme"] = th
            if cut_off:
                np["image"] = {**img, "frame": "card"}
                np["bbox"] = list(WHOLE_BBOX)
            s["scene"], s["params"] = to, np
            s.pop("res", None)
            changes.append(f"{sid}: {scene} -> {to} (the product read "
                           + (f"{float(d.get('max_width') or 0):.0%} wide" if d else "small") + ": shown large)")
            continue
        text_bad = [q for q in qa_by.get(sid, []) if str(q.get("kind")) in ("clip", "overlap", "small_text")]
        if text_bad or TEXT_WORDS.search(notes):
            done = _shorten(p)
            if done:
                changes.append(f"{sid}: text " + "; ".join(done))
        if scene.startswith("kit:type/") and not any(isinstance(p.get(k), str) and p[k].strip()
                                                     for k in ("text", "title")) and name:
            p["text" if scene == "kit:type/title" else "title"] = name
            changes.append(f"{sid}: empty type card -> '{name}'")
    for o in out.get("overlays") or []:
        if not isinstance(o, dict):
            continue
        bad = [q for q in qa_by.get(str(o.get("id")), []) if str(q.get("kind")) in ("clip", "overlap", "small_text")]
        if bad and str(o.get("scene", "")).startswith("kit:type/"):
            p = o.setdefault("params", {})
            done = _shorten(p, 3)
            if float(p.get("scrim") or 0.0) < 0.45:
                p["scrim"] = 0.55
                done.append("scrim 0.55")
            if done:
                changes.append(f"overlay {o.get('id')}: " + "; ".join(done))
    return out, changes
