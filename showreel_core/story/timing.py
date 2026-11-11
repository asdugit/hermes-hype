"""Timing solver: storyboard + voice clip lengths -> beat-locked :class:`Timeline` with verbatim data.

Each scene lasts ``max(type min, narration + pads, reading budget)`` capped at the type
max (narration is never cut, so only a too-long clip can exceed it), snapped to half-bars
of the style's BPM grid, so every cut lands on a half-bar. The total is then fitted to
the target within one bar: flexible scenes grow or shrink a half-bar at a time (order
depends on the film mode) and the weakest scenes are dropped if the film is still too
long; the film always ends on a whole bar. Scene ``data`` is resolved VERBATIM from the
referenced events (code windows, diff hunks, terminal tails, quotes, images) and stats.
Transitions, SFX cues and, for speedruns, the split timer are derived from the result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..contracts import (
    SCENE_RULES,
    Caption,
    Cue,
    Event,
    SceneType,
    Split,
    Stats,
    Storyboard,
    StoryScene,
    Timeline,
    TimelineScene,
)
from .facts import (
    STAT_LABELS,
    SessionFacts,
    code_lines,
    data_get,
    diff_rows,
    image_of,
    is_stub,
    is_test_cmd,
    looks_like_test_pass,
    portrait_twin,
    terminal_ok,
)
from .rules import (
    CAPTION_PHRASE_PAD,
    CAPTION_WORDS_PER_SECOND,
    DROP_PRIORITY,
    GROW_ORDER,
    SHRINK_ORDER,
    SPLIT_CHARS,
    film_mode,
)
from ..session.textutil import is_local_path
from .onscreen import (
    ELLIPSIS,
    display_cmd,
    display_path,
    display_text_paths,
    ellipsize,
    has_loopback,
    scrub_cmd,
    scrub_value,
)
from .text import phrases, syllables, word_count
from .validate import scene_role

T = SceneType
EPS = 1e-6
CODE_WINDOW = 18
DIFF_WINDOW = 24
TERMINAL_LINES = 12
PROBLEM_WORDS = 60
PLAN_ITEMS = 6
CREDIT = "made with Hermes \u00b7 Hype"
PAD_IN, PAD_OUT, HOOK_PAD_IN = 0.3, 0.4, 0.15
#: Drop-priority bonuses when a film is too long (see rules.DROP_PRIORITY for the base order).
PRODUCT_BEAT_BONUS, NARRATED_BONUS = 2.5, 1.0
#: A film with too few scenes may hold its end card this many bars past END's max: none - a short film ends
#: shorter instead of holding a 9-10 s end card (gauntlet: gitpulse/Shortly/patience END holds read as dead time)
END_HOLD_BARS = 0
#: ...and before that, let these hold-friendly scenes run up to STRETCH x their max (a longer push-in,
#: scroll or montage reads better than a film that stops short).
STRETCH = 1.3
STRETCH_TYPES = (T.MONTAGE, T.SCROLL, T.SCREEN, T.FEATURE, T.BEFORE_AFTER)


@dataclass
class _Plan:
    src: int
    scene: StoryScene
    type: SceneType
    data: dict[str, Any]
    lo: float
    hi: float
    need: float
    want: float
    vo_dur: float
    pad_in: float
    priority: float
    dur: float = 0.0
    base: float = 0.0


def solve_timeline(storyboard: Storyboard, events: list[Event], stats: Stats | None,
                   voice_durations: dict[int, float], style_bpm: float, target_seconds: float, aspect: str,
                   fps: int, w: int, h: int, seed: int, style: str = "") -> Timeline:
    """Solve scene timing on the beat grid and resolve verbatim scene data.

    ``voice_durations`` maps storyboard scene index -> narration clip seconds; scenes
    with narration but no clip are timed for captions only. Scenes whose content cannot
    be resolved are skipped. ``TimelineScene.data["story_index"]`` points back at the
    storyboard scene (for the narration clip path).
    """
    mode = film_mode(getattr(storyboard, "mode", None))
    facts = SessionFacts(events, stats, timestamps=(mode == "speedrun"))
    bpm = float(style_bpm) if style_bpm and style_bpm > 0 else 120.0
    beat = 60.0 / bpm
    hb, bar = 2 * beat, 4 * beat
    target = max(bar, float(target_seconds or 60.0))

    portrait = int(h) > int(w)
    if str(getattr(getattr(storyboard, "product", None), "kind", "") or "") == "game":
        # a browser game is a game, not a web page: whole picture on a card, no address bar / cursor / focus ring
        for ev in facts.events:
            if ev.data is not None and image_of(ev) is not None:
                ev.data["frame_hint"] = "card"
    plans: list[_Plan] = []
    for i, scene in enumerate(storyboard.scenes):
        plan = _plan_scene(i, scene, storyboard, facts, voice_durations, beat, mode, portrait)
        if plan is not None:
            plans.append(plan)
    for p in plans:
        p.base = _snap(max(p.want, p.need), p.lo, p.hi, p.need, hb)
    plans = _fit(plans, target, hb, bar, mode)

    scenes: list[TimelineScene] = []
    t = 0.0
    for k, p in enumerate(plans):
        t0, t1 = _r(t), _r(t + p.dur)
        vo_t0 = _r(t0 + p.pad_in) if p.vo_dur > 0 else t0
        captions = _captions(p.scene.vo, vo_t0, p.vo_dur) if p.vo_dur > 0 else []
        p.data["story_index"] = p.src
        scenes.append(TimelineScene(i=k, type=p.type, t0=t0, t1=t1, data=p.data, label=p.scene.label,
                                    vo_t0=vo_t0, captions=captions))
        t += p.dur
    _transitions(scenes, plans)
    dur = _r(t)
    splits = _splits(plans, scenes, facts, beat) if mode == "speedrun" else []
    cues = _cues(scenes, beat, dur, mode, splits)
    return Timeline(style=style, aspect=aspect, fps=int(fps), w=int(w), h=int(h), dur=dur, bpm=bpm, seed=int(seed),
                    scenes=scenes, cues=cues, title=storyboard.title, accent=storyboard.accent_hint,
                    mode=mode, splits=splits)  # type: ignore[arg-type]


# ------------------------------------------------------------------------ planning

def _r(x: float) -> float:
    return round(x + 0.0, 6)


def _plan_scene(i: int, scene: StoryScene, sb: Storyboard, facts: SessionFacts, voice: dict[int, float],
                beat: float, mode: str, portrait: bool = False) -> _Plan | None:
    st = SceneType(scene.type)
    data = resolve_scene_data(scene, sb, facts, portrait=portrait)
    if data is None:
        return None
    lo, hi, _ = SCENE_RULES[st]
    pad_in = HOOK_PAD_IN if st == T.HOOK else PAD_IN
    vo_dur = 0.0
    if scene.vo.strip():
        spoken = voice.get(i)
        if spoken and spoken > 0:
            vo_dur = float(spoken)
        else:  # captions only: SPEC 5 reading pace
            n_phr = max(1, len(phrases(scene.vo)))
            vo_dur = word_count(scene.vo) / CAPTION_WORDS_PER_SECOND + CAPTION_PHRASE_PAD * n_phr
    need = vo_dur + pad_in + PAD_OUT if vo_dur > 0 else 0.0
    reading = reading_budget(st, data, scene.label, beat)
    if mode == "speedrun" and st not in (T.END, T.TITLE):
        reading *= 0.8  # time-lapse pacing
    want = min(max(lo, reading), hi)
    prio = DROP_PRIORITY[mode][st] + (10 if scene.extra.get("split") else 0)
    if mode == "product" and scene_role(scene, facts, sb.product) == "product":
        prio += PRODUCT_BEAT_BONUS  # a CLI's demo run outranks the build story in a product film
    if scene.vo.strip():
        prio += NARRATED_BONUS  # dropping a narrated scene loses a line of the script
    if scene.refs:
        ev = facts.get(scene.refs[0])
        prio += ev.weight * 0.5 if ev is not None else 0.0
    return _Plan(i, scene, st, data, lo, hi, need, want, vo_dur, pad_in, prio)


def reading_budget(st: SceneType, data: dict[str, Any], label: str, beat: float) -> float:
    """Seconds a viewer needs to take in the scene's on-screen content."""
    words = word_count
    base = {
        T.HOOK: 1.5, T.TITLE: 1.2 + (words(data.get("title", "")) + words(data.get("tagline", ""))) / 3.5,
        T.PROBLEM: 1.0 + min(words(data.get("text", "")), 40) / 4.0,
        T.PLAN: 1.0 + 0.55 * len(data.get("items", [])),
        T.CODE: 1.6 + 0.14 * len(data.get("lines", [])),
        T.DIFF: 1.4 + 0.12 * sum(len(h["lines"]) for h in data.get("hunks", [])),
        T.TERMINAL: 1.4 + 0.15 * len(data.get("output", [])),
        T.MONTAGE: 0.8 + len(data.get("items", [])) * beat / 2,
        T.SCREEN: 2.5, T.FEATURE: 2.8, T.SCROLL: 4.5,
        T.STATS: 1.2 + 0.8 * len(data.get("stats", [])),
        T.BEFORE_AFTER: 3.5,
        T.CALLOUT: 1.2 + words(data.get("text", "")) / 3.0,
        T.END: 3.5,
    }[st]
    if label and st not in (T.TITLE, T.END):
        n = words(label)
        digits = 0.3 if any(ch.isdigit() for ch in label) else 0.0
        base = max(base, 0.5 + max(0.8, n / 3.5) + digits + 0.3)
    return base


def _snap(x: float, lo: float, hi: float, need: float, hb: float) -> float:
    """Smallest half-bar multiple >= x; falls back to the largest one <= hi when that still fits."""
    d = math.ceil(x / hb - EPS) * hb
    if d > hi + EPS and need <= hi + EPS:
        down = math.floor(hi / hb + EPS) * hb
        if down >= max(lo, need) - EPS:
            d = down
    return max(d, hb)


def _floor_ok(p: _Plan, hb: float) -> bool:
    """True when the scene can give back one half-bar and stay within its rules."""
    return p.dur - hb >= max(p.lo, p.need) - EPS and p.dur - hb >= hb - EPS


def _fit(plans: list[_Plan], target: float, hb: float, bar: float, mode: str) -> list[_Plan]:
    """Fit the total to ``target`` +/- one bar; re-fit without the weakest scene while it stays too long."""
    plans = list(plans)
    while True:
        for p in plans:
            p.dur = p.base
        _fit_once(plans, target, hb, bar, mode)
        if sum(p.dur for p in plans) <= target + bar + EPS:
            return plans
        cands = [p for p in plans if p.type not in (T.END, T.HOOK, T.TITLE)]
        if not cands:
            return plans
        plans.remove(min(cands, key=lambda p: (p.priority, -p.src)))


def _fit_once(plans: list[_Plan], target: float, hb: float, bar: float, mode: str) -> None:
    total = lambda: sum(p.dur for p in plans)
    # shrink flexible scenes
    order = SHRINK_ORDER[mode]
    changed = True
    while total() > target + hb / 2 + EPS and changed:
        changed = False
        for st in order:
            for p in [q for q in plans if q.type == st]:
                if total() <= target + hb / 2 + EPS:
                    break
                if _floor_ok(p, hb):
                    p.dur -= hb
                    changed = True
    # drop the weakest scenes while still more than a bar too long
    while total() > target + bar + EPS and len(plans) > 3:
        cands = [p for p in plans if p.type not in (T.END, T.HOOK, T.TITLE)]
        if not cands:
            break
        weakest = min(cands, key=lambda p: (p.priority, -p.src))
        plans.remove(weakest)
    # grow flexible scenes (HOOK never grows)
    order = GROW_ORDER[mode]
    changed = True
    while total() < target - hb / 2 - EPS and changed:
        changed = False
        for st in order:
            for p in [q for q in plans if q.type == st]:
                if total() >= target - hb / 2 - EPS:
                    break
                if p.dur + hb <= p.hi + EPS:
                    p.dur += hb
                    changed = True
    # still short (too few scenes for the target): stretch the holds, then hold the end card
    changed = True
    while total() < target - bar + EPS and changed:
        changed = False
        for st in order:
            if st not in STRETCH_TYPES:
                continue
            for p in [q for q in plans if q.type == st]:
                if total() >= target - hb / 2 - EPS:
                    break
                if p.dur + hb <= p.hi * STRETCH + EPS:
                    p.dur += hb
                    changed = True
    ends = [p for p in plans if p.type == T.END]
    if ends:
        cap = ends[-1].hi + END_HOLD_BARS * bar
        while total() < target - bar + EPS and ends[-1].dur + hb <= cap + EPS:
            ends[-1].dur += hb
    # end on a whole bar
    n_half = round(total() / hb)
    if n_half % 2:
        _whole_bar(plans, hb, bar, target, total())


def _whole_bar(plans: list[_Plan], hb: float, bar: float, target: float, total: float) -> None:
    ends = [p for p in plans if p.type == T.END]
    grow_first = total < target
    candidates = ends + [p for p in plans if p.type not in (T.END, T.HOOK)]
    for want_grow in (grow_first, not grow_first):
        for p in candidates:
            if want_grow and p.dur + hb <= p.hi + EPS and total + hb <= target + bar + EPS:
                p.dur += hb
                return
            if not want_grow and _floor_ok(p, hb) and total - hb >= target - bar - EPS:
                p.dur -= hb
                return
    # nothing fits inside the rules: extend the end card (a held last frame is always safe)
    (ends[-1] if ends else plans[-1]).dur += hb


# ----------------------------------------------------------------------- captions

def _captions(vo: str, t0: float, dur: float) -> list[Caption]:
    """Phrase captions spread over the clip by syllable weight."""
    chunks = phrases(vo)
    if not chunks:
        return []
    weights = [sum(syllables(w) for w in c.split()) + 1 for c in chunks]
    total = float(sum(weights))
    out: list[Caption] = []
    t = t0
    for chunk, wgt in zip(chunks, weights):
        span = dur * wgt / total
        out.append(Caption(t0=_r(t), t1=_r(t + span), text=chunk))
        t += span
    return out


# ---------------------------------------------------------------------- resolution

#: a terminal panel's command line (longer commands are ellipsized at a word boundary)
CMD_CHARS = 64
#: a MONTAGE card's argument
ARG_CHARS = 40


def resolve_scene_data(scene: StoryScene, sb: Storyboard, facts: SessionFacts,
                       portrait: bool = False) -> dict[str, Any] | None:
    """Verbatim content for a scene's template (as the screen shows it: project-relative paths, commands without
    shell noise, no loopback address), or None when its refs cannot supply it."""
    data = _resolve_scene_data(scene, sb, facts, portrait)
    if data is None:
        return None
    product = getattr(sb, "product", None)
    name = str(getattr(product, "name", "") or getattr(sb, "title", "") or "")
    return screen_text(data, facts.project_root, name)


def screen_text(data: Any, root: str, name: str = "") -> Any:
    """Scene data as the film shows it (a copy): terminal commands via :func:`display_cmd` (no ``cd X &&``, no
    ``VAR=...``, interpreter paths as names, ellipsized), code/diff/output paths project-relative, a local page
    address project-relative, no loopback address anywhere (output lines naming one are dropped). Picture file
    paths (``image.path``) stay untouched - they load the asset."""
    def walk(o: Any, key: str = "") -> Any:
        if isinstance(o, dict):
            is_pic = o.get("kind") == "image" or ("w" in o and "h" in o and "asset" not in o and "lines" not in o
                                                   and "hunks" not in o and "cmd" not in o) or key == "image"
            out: dict[str, Any] = {}
            for k, v in o.items():
                if is_pic and k == "path":
                    out[k] = v
                elif k == "cmd" and isinstance(v, str):
                    out[k] = display_cmd(v, root, CMD_CHARS)
                elif k == "path" and isinstance(v, str):
                    out[k] = display_path(v, root, 3)
                elif k == "url" and isinstance(v, str) and is_local_path(v):
                    out[k] = display_path(v, root, 3)
                elif k == "output" and isinstance(v, list):        # terminal output lines (code stays verbatim)
                    out[k] = [display_text_paths(x, root) if isinstance(x, str) else x for x in v]
                elif k in ("header", "text") and isinstance(v, str):   # diff header, a quoted prompt / plan item
                    out[k] = display_text_paths(v, root)             # ("...in the current folder (~/work/app)")
                elif isinstance(v, (dict, list)):
                    out[k] = walk(v, k)
                else:
                    out[k] = v
            return out
        if isinstance(o, list):
            return [walk(v, key) for v in o]
        return o
    return scrub_value(walk(data), name=name)


def _resolve_scene_data(scene: StoryScene, sb: Storyboard, facts: SessionFacts,
                        portrait: bool = False) -> dict[str, Any] | None:
    """Verbatim content for a scene's template, or None when its refs cannot supply it.

    ``portrait`` (9:16 films): a landscape desktop capture is swapped for the phone capture of the same page
    (HOOK, SCREEN, FEATURE, SCROLL); its focus box is then measured on the phone picture.
    """
    st = SceneType(scene.type)
    ex = scene.extra or {}
    ev = facts.get(scene.refs[0]) if scene.refs else None
    if portrait and ev is not None and st in (T.HOOK, T.SCREEN, T.FEATURE, T.SCROLL):
        twin = portrait_twin(ev, facts.events)
        if twin is not None:
            ev = twin
            ex = {k: v for k, v in ex.items() if k not in ("bbox", "click", "scroll")}
    if ev is not None and is_stub(ev) and st != T.MONTAGE:
        return None
    product = getattr(sb, "product", None)
    if st == T.TITLE:
        return {"title": sb.title, "tagline": sb.tagline, "product": product.name if product else sb.title,
                "one_liner": product.one_liner if product else ""}
    if st == T.END:
        out: dict[str, Any] = {"title": sb.title, "cta": sb.cta, "url": sb.url, "credit": CREDIT}
        if not sb.cta and sb.tagline:
            out["tagline"] = sb.tagline     # no product command: the END is the name + tagline
        if film_mode(getattr(sb, "mode", None)) == "speedrun":
            total = float(facts.stats.duration_s or 0)
            out.update(pb_time_s=total, pb_display=_clock(total))
        return out
    if st == T.STATS:
        rows = []
        for key in ex.get("stat_keys") or []:
            value = facts.stat_value(key)
            if value is not None:
                rows.append({"key": key, "value": value, "label": STAT_LABELS.get(key, key),
                             "display": _stat_display(key, facts)})
        return {"stats": rows} if rows else None
    if st == T.MONTAGE:
        items = []
        for ref in ex.get("montage_refs") or scene.refs:
            m = facts.get(ref)
            if m is None:
                continue
            if has_loopback(str((m.data or {}).get("url") or "")) and not (m.data or {}).get("path"):
                continue            # a dev-server address is never on screen (and a card of '…' says nothing)
            arg, clipped = _verbatim_arg(m, root=facts.project_root)
            items.append({"id": m.id, "kind": m.kind, "tool": m.tool, "arg": arg, "clipped": clipped, "t": m.t})
        return {"items": items} if len(items) >= 3 else None
    if st == T.BEFORE_AFTER:
        before = facts.get(ex.get("before_ref") or (scene.refs[0] if scene.refs else ""))
        after = facts.get(ex.get("after_ref") or (scene.refs[1] if len(scene.refs) > 1 else ""))
        if before is None or after is None:
            return None
        b, a = _block(before), _block(after)
        return {"before": b, "after": a} if b and a else None
    if ev is None:
        return None
    if st == T.HOOK:
        hero = _block(ev, compact=True)
        return {"hero": hero, "label": scene.label} if hero else None
    if st == T.PROBLEM:
        text = str(data_get(ev, "text", ""))
        shown = _prefix_words(text, PROBLEM_WORDS)
        return {"text": shown, "truncated": len(shown) < len(text.strip())} if shown else None
    if st == T.PLAN:
        items = [{"text": str(it.get("text", "")), "status": str(it.get("status", ""))}
                 for it in data_get(ev, "items") or [] if isinstance(it, dict)]
        return {"items": items[:PLAN_ITEMS], "more": max(0, len(items) - PLAN_ITEMS)} if items else None
    if st == T.CODE:
        return _code_window(ev, ex.get("focus_lines"), CODE_WINDOW)
    if st == T.DIFF:
        return _diff_window(ev, ex.get("focus_lines"), DIFF_WINDOW)
    if st == T.TERMINAL:
        return _terminal(ev, TERMINAL_LINES)
    if st == T.CALLOUT:
        quote = str(ex.get("quote") or "")
        span = facts.find_quote(ev.id, quote) if quote else None
        if not span:
            cands = facts.quotable_sentences(ev)
            span = cands[0] if cands else None
        if not span:
            return None
        who = {"user_prompt": "user", "terminal": "test"}.get(ev.kind, "agent")
        return {"text": span, "who": who, "ref": ev.id}
    if st in (T.SCREEN, T.FEATURE, T.SCROLL):
        img = image_of(ev)
        if img is None:
            return None
        out = {"image": img}
        if img.get("frame") == "card" and st in (T.SCREEN, T.FEATURE):
            # a game/app screenshot, render or image file: no DOM rects, so no cursor, no focus ring and never
            # a strip crop. The box is the Ken-Burns end frame (>= 55 % of the picture, aspect 0.75-1.8).
            from ..capture.crops import picture_crop     # lazy: Pillow
            asked = ex.get("bbox") if st == T.FEATURE else None
            out["bbox"] = picture_crop(img, asked if isinstance(asked, (list, tuple)) and len(asked) == 4 else None)
            if st == T.FEATURE:
                b = out["bbox"]                 # kept for kits that ignore `frame`; no cursor is drawn on a card
                out.update(feature=str(ex.get("feature") or scene.label or ""),
                           click=[round(b[0] + b[2] / 2, 4), round(b[1] + b[3] / 2, 4)])
            return out
        if st == T.SCREEN:
            out["bbox"] = list(ex.get("bbox") or auto_bbox(img["path"]))
        elif st == T.FEATURE:
            bbox = list(ex.get("bbox") or auto_bbox(img["path"]))
            out.update(feature=str(ex.get("feature") or scene.label or ""), bbox=bbox,
                       click=list(ex.get("click") or [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2]))
        else:
            out["scroll"] = list(ex.get("scroll") or [0.0, 1.0])
        return out
    return None


def _block(ev: Event, compact: bool = False) -> dict[str, Any] | None:
    """A self-describing verbatim content block for HOOK / BEFORE_AFTER."""
    img = image_of(ev)
    if img is not None:
        return {"kind": "image", **img}
    if ev.kind == "terminal":
        term = _terminal(ev, 4 if compact else TERMINAL_LINES)
        return {"kind": "terminal", **term} if term else None
    if ev.kind == "file_patch":
        diff = _diff_window(ev, None, 10 if compact else DIFF_WINDOW)
        return {"kind": "diff", **diff} if diff else None
    if ev.kind == "file_write":
        code = _code_window(ev, None, 8 if compact else CODE_WINDOW)
        return {"kind": "code", **code} if code else None
    return None


def _code_window(ev: Event, focus: Any, size: int) -> dict[str, Any] | None:
    lines = code_lines(ev)
    n = len(lines)
    if not n:
        return None
    try:
        a, b = sorted((int(focus[0]), int(focus[1])))
    except (TypeError, ValueError, IndexError):
        first_def = next((k for k, ln in enumerate(lines) if ln.lstrip().startswith(
            ("def ", "class ", "function ", "export ", "async def ", "fn ", "func "))), 0)
        a, b = first_def + 1, min(n, first_def + 12)
    a, b = max(1, min(a, n)), max(1, min(b, n))
    span = b - a + 1
    if span >= size:
        start, b = a, a + size - 1
    else:
        start = max(1, min(a - (size - span) // 2, n - size + 1))
    end = min(n, start + size - 1)
    lang = str(data_get(ev, "lang", ""))
    if str(data_get(ev, "path", "")).lower().endswith((".md", ".markdown", ".rst")):
        # a usage block inside a README: highlight it in the fence's language, not as markdown
        fence = next((ln.strip()[3:].strip() for ln in reversed(lines[:a]) if ln.strip().startswith("```")), "")
        lang = fence or lang
    return {"path": str(data_get(ev, "path", ev.title)), "lang": lang,
            "lines": lines[start - 1:end], "start": start, "focus": [a, min(b, end)], "total_lines": n,
            "new_file": bool(data_get(ev, "new_file", True))}


def _diff_window(ev: Event, focus: Any, size: int) -> dict[str, Any] | None:
    if ev.kind == "file_write":
        rows = [(0, "+", ln) for ln in code_lines(ev)]
        headers = [f"new file {data_get(ev, 'path', ev.title)}"]
    else:
        rows = diff_rows(ev)
        headers = [str(h.get("header", "")) for h in data_get(ev, "hunks") or [] if isinstance(h, dict)]
    if not rows:
        return None
    n = len(rows)
    try:
        a = max(1, min(int(focus[0]), n))
        start = max(0, min(a - 1 - size // 4, n - size))
    except (TypeError, ValueError, IndexError):
        best, start = -1, 0
        for s in range(max(1, n - size + 1)):
            changed = sum(1 for _, op, _ in rows[s:s + size] if op in "+-")
            if changed > best:
                best, start = changed, s
    window = rows[start:start + size]
    hunks: list[dict[str, Any]] = []
    for hi, op, text in window:
        if not hunks or hunks[-1]["_h"] != hi:
            hunks.append({"_h": hi, "header": headers[hi] if hi < len(headers) else "", "lines": []})
        hunks[-1]["lines"].append([op, text])
    for hk in hunks:
        hk.pop("_h")
    adds = data_get(ev, "adds")
    dels = data_get(ev, "dels")
    return {"path": str(data_get(ev, "path", ev.title)), "lang": str(data_get(ev, "lang", "")), "hunks": hunks,
            "adds": adds if isinstance(adds, int) else sum(1 for _, op, _ in rows if op == "+"),
            "dels": dels if isinstance(dels, int) else sum(1 for _, op, _ in rows if op == "-"),
            "truncated": len(window) < n}


def _terminal(ev: Event, limit: int) -> dict[str, Any] | None:
    cmd = str(data_get(ev, "cmd", ""))
    if not cmd:
        return None
    out = [str(x) for x in data_get(ev, "output_lines") or []]
    while out and not out[-1].strip():
        out.pop()
    # a product run reads from the top (header, best rows); a test/build run is read at its summary (the tail)
    head = terminal_ok(ev) and not looks_like_test_pass(ev) and not is_test_cmd(cmd) and len(out) > limit
    if head:
        while out and not out[0].strip():
            out.pop(0)
    shown = out[:limit] if head else out[-limit:]
    return {"cmd": cmd, "output": shown, "truncated_top": not head and len(out) > len(shown),
            "exit_code": data_get(ev, "exit_code"), "elapsed_s": data_get(ev, "elapsed_s"), "ok": terminal_ok(ev),
            "tests_passed": looks_like_test_pass(ev)}


def _prefix_words(text: str, limit: int) -> str:
    """Verbatim prefix of ``text`` holding at most ``limit`` words, ending at a sentence end when possible."""
    text = text.strip()
    count, end, last_sentence = 0, len(text), 0
    in_word = False
    for k, ch in enumerate(text):
        if ch.isspace():
            in_word = False
            continue
        if not in_word:
            count += 1
            in_word = True
            if count > limit:
                end = k
                break
        if ch in ".!?":
            last_sentence = k + 1
    if end == len(text):
        return text
    cut = last_sentence if last_sentence > end // 2 else end
    return text[:cut].rstrip()


def _verbatim_arg(ev: Event, limit: int = ARG_CHARS, root: str = "") -> tuple[str, bool]:
    """A MONTAGE card's argument as the screen shows it: a path project-relative (``src/app.js``, never
    ``~/work/...`` running off the card), a command without shell noise, ellipsized at a word boundary."""
    data = ev.data or {}
    keys = ("path", "cmd", "url", "query")
    if data.get("asset") and data.get("src"):
        # a picture copied into the job: its own name, never Hype's asset path (`…/assets/e3_shot.png` on a card)
        data = {**data, "path": str(data["src"]).replace("\\", "/").rsplit("/", 1)[-1]}
    for key in keys:
        if data.get(key):
            raw = str(data[key])
            break
    else:
        key, raw = "", ev.title or ev.tool or ev.kind
    if key == "path" or (key == "url" and is_local_path(raw)):
        shown = display_path(raw, root, 3)
    elif key == "cmd":
        shown = display_cmd(raw, root)
    else:
        shown = raw.splitlines()[0] if raw.splitlines() else raw
        shown = scrub_cmd(shown)
    if len(shown) > limit:
        if key == "path" or (key == "url" and is_local_path(raw)):
            comps = shown.removeprefix(ELLIPSIS + "/").split("/")
            while len(comps) > 1 and len(ELLIPSIS + "/" + "/".join(comps)) > limit:
                comps = comps[1:]                       # whole folder names off the front: '…/blueprints/x.py'
            cut = ELLIPSIS + "/" + "/".join(comps)
            return (cut if len(cut) <= limit else ELLIPSIS + cut[-(limit - 1):]), True
        return ellipsize(shown, limit), True
    return shown, False


def _clock(seconds: float) -> str:
    s = round(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _stat_display(key: str, facts: SessionFacts) -> str:
    value = facts.stat_value(key)
    if value is None:
        return ""
    if key == "duration_s":
        mins = int(value)
        return f"{mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"{mins} min"
    return f"{int(value):,}"


def auto_bbox(path: str) -> list[float]:
    """Focus box for a picture: the 60 % window with the most edge detail (Pillow), else a centred box."""
    default = [0.1, 0.1, 0.8, 0.8]
    try:
        from PIL import Image, ImageFilter  # lazy: Pillow is a Hermes core dependency
        with Image.open(path) as im:
            small = im.convert("L").resize((48, 30)).filter(ImageFilter.FIND_EDGES)
        W, H = small.size
        px = list(small.tobytes())
        ww, wh = int(W * 0.6), int(H * 0.6)
        best, bx, by = -1.0, 0, 0
        for y in range(0, H - wh + 1, 2):
            for x in range(0, W - ww + 1, 2):
                s = float(sum(px[j * W + i] for j in range(y, y + wh, 2) for i in range(x, x + ww, 2)))
                if s > best:
                    best, bx, by = s, x, y
        return [round(bx / W, 4), round(by / H, 4), 0.6, 0.6]
    except Exception:  # noqa: BLE001 - missing file, unreadable image, no Pillow: keep a safe default
        return default


# --------------------------------------------------------------------- transitions

def _transitions(scenes: list[TimelineScene], plans: list[_Plan]) -> None:
    prev_push = False
    for k, (sc, p) in enumerate(zip(scenes, plans)):
        if k == 0:
            sc.transition_in = "cut"
            continue
        prev = scenes[k - 1]
        asked = p.scene.extra.get("transition")
        if asked in ("cut", "match", "push", "wipe"):
            choice = asked
        elif prev.type == T.HOOK and sc.type == T.TITLE or sc.type == T.END or prev.type == T.MONTAGE:
            choice = "push"
        elif sc.type == T.BEFORE_AFTER:
            choice = "wipe"
        elif _same_source(prev, sc) or (_is_card(prev) and _is_card(sc)):
            choice = "match"                    # picture to picture: a cross-dissolve on the beat
        else:
            choice = "cut"
        if choice == "push" and prev_push:
            choice = "cut"
        sc.transition_in = choice  # type: ignore[assignment]
        prev_push = choice == "push"


def _is_card(sc: TimelineScene) -> bool:
    """A shot that shows a non-web picture (card presentation, see facts.picture_frame)."""
    d = sc.data or {}
    img = d.get("image") or d.get("hero") or {}
    return isinstance(img, dict) and img.get("frame") == "card"


def _same_source(a: TimelineScene, b: TimelineScene) -> bool:
    return bool(_source_key(a)) and _source_key(a) == _source_key(b)


def _source_key(sc: TimelineScene) -> str:
    img = sc.data.get("image") or {}
    if sc.data.get("path"):
        return str(sc.data["path"])
    if img.get("url"):
        return str(img["url"])
    if img.get("source_kind") == "product_capture" and img.get("path"):   # one folder per captured page (a
        return str(img["path"]).replace("\\", "/").rsplit("/", 1)[0]     # dev-server url is not on screen)
    return ""


# ---------------------------------------------------------------------------- cues

def _grid(t: float, beat: float) -> float:
    step = beat / 2
    return _r(round(t / step) * step)


def _cues(scenes: list[TimelineScene], beat: float, dur: float, mode: str, splits: list[Split]) -> list[Cue]:
    """Beat-gridded SFX cues. Names are SFX-kit ROLES (assets/audio/sfx/sfx.json ``styles``: cut, move, click,
    type, appear, pass, fail, hit, hero, build, shot), resolved to a sound per style at mix time."""
    cues: list[Cue] = []
    hero_hit = False
    for k, sc in enumerate(scenes):
        span = sc.t1 - sc.t0
        if sc.transition_in == "push" and k > 0:
            cues.append(Cue(sc.t0, "cut", -8.0, "peak"))
        if sc.type in (T.CODE, T.PROBLEM):
            n = 8 if sc.type == T.CODE else 6
            t = sc.t0 + beat
            for _ in range(n):
                if t >= sc.t0 + span * 0.55:
                    break
                cues.append(Cue(_grid(t, beat), "type", -16.0, "onset"))
                t += beat / 2
        elif sc.type == T.TERMINAL and sc.data.get("tests_passed"):
            cues.append(Cue(_grid(sc.t0 + span * 0.6, beat), "pass", -6.0, "onset"))
        elif sc.type == T.STATS and not hero_hit:
            if k > 0:
                cues.append(Cue(sc.t0, "build", -10.0, "end"))
            cues.append(Cue(sc.t0, "hit", -3.0, "onset"))
            hero_hit = True
        elif sc.type == T.PLAN:
            for j in range(min(PLAN_ITEMS, len(sc.data.get("items", [])))):
                t = sc.t0 + beat * (j + 1)
                if t < sc.t1 - beat / 2:
                    cues.append(Cue(_grid(t, beat), "appear", -12.0, "onset"))
        elif sc.type == T.FEATURE and _is_card(sc):
            cues.append(Cue(_grid(sc.t0 + span * 0.3, beat), "appear", -14.0, "onset"))   # no cursor, no click
        elif sc.type == T.FEATURE:
            cues.append(Cue(_grid(sc.t0 + span * 0.45, beat), "click", -10.0, "onset"))
        elif sc.type == T.MONTAGE:
            n = len(sc.data.get("items", []))
            step = span / max(1, n)
            for j in range(n):
                cues.append(Cue(_grid(sc.t0 + j * step, beat), "type", -18.0, "onset"))
        elif sc.type == T.END and mode == "speedrun":
            cues.append(Cue(_grid(sc.t0 + beat, beat), "pass", -4.0, "onset"))
    for sp in splits:
        cues.append(Cue(sp.film_t, "appear", -8.0, "onset"))
    cues = [c for c in cues if 0 <= c.t < dur - EPS]
    cues.sort(key=lambda c: (c.t, c.sfx))
    return cues


# -------------------------------------------------------------------------- splits

def _splits(plans: list[_Plan], scenes: list[TimelineScene], facts: SessionFacts, beat: float) -> list[Split]:
    """Speedrun splits: one per scene with ``extra.split``, strictly increasing in both clocks."""
    out: list[Split] = []
    for p, sc in zip(plans, scenes):
        label = str(p.scene.extra.get("split") or "").strip()[:SPLIT_CHARS]
        ev = facts.get(p.scene.refs[0]) if p.scene.refs else None
        if not label or ev is None:
            continue
        film_t = _r(sc.t0 + beat)  # pops one beat after the cut, on the grid
        if out and (ev.t <= out[-1].session_t or film_t <= out[-1].film_t):
            continue
        out.append(Split(label=label, event_id=ev.id, session_t=float(ev.t), film_t=film_t))
    end = next((sc for sc in scenes if sc.type == T.END), None)
    total = float(facts.stats.duration_s or 0)
    if end is not None and facts.events and (not out or total > out[-1].session_t):
        film_t = _r(end.t0)
        if not out or film_t > out[-1].film_t:
            last = max(facts.events, key=lambda e: e.t)
            out.append(Split(label="Final time", event_id=last.id, session_t=max(total, last.t), film_t=film_t))
    return out
