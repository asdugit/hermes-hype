"""Apply a resolved customization to a preset's Quick timeline and film.json (pure functions, no I/O but logo
lookups). ``apply_timeline`` does the structural edits (drop / reorder / re-time shots, energy holds) on the
Timeline *before* the film is built, so narration, captions, cues, splits and the music fit all follow;
``apply_film`` does the look (theme block, fonts, per-shot params, words, transitions, captions, music, logo).
"""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any

from . import theme as TH
from . import vocab as V
from .spec import SHOT_TEXT_FIELDS

MIN_SHOT_S = 1.2
LOGO_ASSET = "brand_logo"


def _tname(t: Any) -> str:
    return str(getattr(t, "value", t))


def shot_rows(timeline: Any) -> list[dict[str, Any]]:
    """``[{id, type, t0, t1}]`` in Quick's shot-id scheme (``s{k:02d}_{type}``) for a Timeline or its dict."""
    scenes = timeline["scenes"] if isinstance(timeline, dict) else timeline.scenes
    out = []
    for k, sc in enumerate(scenes):
        get = sc.get if isinstance(sc, dict) else lambda a, d=None, sc=sc: getattr(sc, a, d)
        typ = _tname(get("type"))
        out.append({"id": f"s{k:02d}_{typ.lower()}", "type": typ, "t0": float(get("t0")), "t1": float(get("t1"))})
    return out


# ------------------------------------------------------------------------------------------- timeline

def _shift_scene(sc: Any, dt: float) -> None:
    sc.t0 = round(sc.t0 + dt, 4)
    sc.t1 = round(sc.t1 + dt, 4)
    if sc.vo_t0:
        sc.vo_t0 = round(sc.vo_t0 + dt, 4)
    for c in sc.captions or []:
        c.t0, c.t1 = round(c.t0 + dt, 4), round(c.t1 + dt, 4)


def _speech_end(sc: Any) -> float:
    return max([float(c.t1) for c in sc.captions or []] + [float(sc.t0)])


#: shot types whose picture can carry a cut-in (a closer framing of the same product capture)
CUTIN_FROM = ("FEATURE", "SCREEN", "SCROLL", "HOOK")
CUTIN_MIN_S, CUTIN_MAX_S = 1.4, 2.6


def _cutin_image(sc: Any) -> dict[str, Any] | None:
    data = sc.data if isinstance(getattr(sc, "data", None), dict) else {}
    img = data.get("hero") if _tname(sc.type) == "HOOK" else data.get("image")
    if not isinstance(img, dict) or not (img.get("path") or img.get("asset")):
        return None
    if _tname(sc.type) == "HOOK" and str(img.get("kind") or "image") != "image":
        return None
    return img


def _cutin(sc: Any, dur: float) -> Any:
    """A closer framing of ``sc``'s product picture: a SCREEN push-in on (a tighter box around) the feature region,
    no narration. High-energy films cut on the picture instead of holding dead air after the line."""
    img = dict(_cutin_image(sc) or {})
    img.pop("kind", None)
    data = sc.data if isinstance(sc.data, dict) else {}
    bb = data.get("bbox")
    bb = bb if isinstance(bb, list) and len(bb) == 4 else [0.1, 0.1, 0.8, 0.8]
    x, y, w, h = (float(v) for v in bb)
    cw, ch = max(0.28, w * 0.62), max(0.28, h * 0.62)
    cx, cy = x + w / 2, y + h / 2
    box = [round(min(max(0.0, cx - cw / 2), 1 - cw), 4), round(min(max(0.0, cy - ch / 2), 1 - ch), 4),
           round(cw, 4), round(ch, 4)]
    new = copy.copy(sc)
    new.type = type(sc.type)("SCREEN") if hasattr(sc.type, "value") else "SCREEN"
    new.data = {"image": img, "bbox": box, "cutin": True,
                **({"story_index": data["story_index"]} if "story_index" in data else {})}
    new.label = str(getattr(sc, "label", "") or data.get("feature") or "")
    new.vo_path, new.vo_t0, new.captions = "", 0.0, []
    new.transition_in = "cut"
    new.t0, new.t1 = 0.0, round(dur, 4)
    return new


def _cue_like(cues: list[Any], t: float) -> Any:
    """A cut whoosh on the cut-in (same Cue class as the timeline's)."""
    if not cues:
        return None
    c = copy.copy(cues[0])
    c.t, c.sfx = round(t, 4), "cut"
    if hasattr(c, "gain_db"):
        c.gain_db = -12.0
    if hasattr(c, "align"):
        c.align = "onset"
    return c


def apply_timeline(tl: Any, spec: dict[str, Any], *, energy: str = "") -> tuple[list[str], dict[str, str]]:
    """Structural edits on a Timeline dataclass, in place: ``order``, ``remove``, ``hold`` (+/- seconds) and the
    ``high`` energy pacing. Returns (notes, old shot id -> new id): Quick numbers shots by position, so a drop, a
    reorder or an inserted cut-in renames the shots after it.

    High energy never shortens the film (users ask for "30"): the dead air after each narration line is cut and the
    time goes to more shots - a cut-in (a closer framing of the same product capture) after the product beats - and
    whatever is left holds the product beats. Narration is not sped up (customize.hook)."""
    notes: list[str] = []
    if not hasattr(tl, "scenes") or not tl.scenes:
        return notes, {}
    ids = [r["id"] for r in shot_rows(tl)]
    idx = {sid: k for k, sid in enumerate(ids)}
    edits = {s["id"]: s for s in spec.get("shots") or [] if s.get("id") in idx}
    blocks = []                      # (scene, cues inside it, splits inside it, id)
    for k, sc in enumerate(tl.scenes):
        t0, t1 = float(sc.t0), float(sc.t1)
        last = k == len(tl.scenes) - 1
        cues = [c for c in tl.cues if t0 <= float(c.t) < t1 or (last and float(c.t) >= t1)]
        splits = [s for s in getattr(tl, "splits", []) or [] if t0 <= float(getattr(s, "film_t", -1)) < t1]
        blocks.append([sc, cues, splits, ids[k]])
    order = [sid for sid in spec.get("order") or [] if sid in idx]
    if order:
        blocks.sort(key=lambda b: order.index(b[3]) if b[3] in order else len(order) + idx[b[3]])
        notes.append("shots reordered: " + " ".join(b[3] for b in blocks))
    kept = []
    for b in blocks:
        if edits.get(b[3], {}).get("remove"):
            notes.append(f"dropped {b[3]}")
            continue
        kept.append(b)
    # per-shot lengths: the requested holds first; high energy then trims the dead air after the line
    plan = []                        # [block, dur, base_want, want]
    for b in kept:
        sc, sid = b[0], b[3]
        dur = float(sc.t1) - float(sc.t0)
        speech = _speech_end(sc) - float(sc.t0)
        floor = max(MIN_SHOT_S, speech + 0.3 if speech > 0.05 else MIN_SHOT_S)
        base = max(floor, dur + float(edits.get(sid, {}).get("hold") or 0.0))
        want = base
        if energy == "high" and not edits.get(sid, {}).get("hold"):
            tail = dur - speech if speech > 0.05 else dur * 0.25
            if tail > 1.0:
                want = max(floor, dur - min(tail - 0.7, 0.35 * dur))
        plan.append([b, dur, base, want])
    # high energy: give the trimmed time back as cut-ins after the product beats, then as holds (same length)
    inserts: dict[int, float] = {}
    if energy == "high":
        freed = sum(p[2] - p[3] for p in plan)
        cands = [k for k, p in enumerate(plan) if _tname(p[0][0].type) in CUTIN_FROM and _cutin_image(p[0][0])
                 and k < len(plan) - 1]
        cands.sort(key=lambda k: (_tname(plan[k][0][0].type) == "HOOK", -(plan[k][2] - plan[k][3]), k))
        n = min(len(cands), int(freed // CUTIN_MIN_S))
        if n:
            each = min(CUTIN_MAX_S, freed / n)
            for k in sorted(cands[:n]):
                inserts[k] = round(each, 4)
            freed -= each * n
        if freed > 0.02:             # the rest holds the product beats (else every shot gets its trim back)
            holders = [k for k, p in enumerate(plan) if _tname(p[0][0].type) in CUTIN_FROM + ("END",)] or \
                list(range(len(plan)))
            give = [max(0.0, plan[k][2] - plan[k][3]) for k in holders]
            tot = sum(give)
            for k, g in zip(holders, give):
                plan[k][3] += freed * (g / tot if tot > 0 else 1.0 / len(holders))
    t = 0.0
    new_cues, new_scenes = [], []
    idmap: dict[str, str] = {}
    for k, (b, dur, _base, want) in enumerate(plan):
        sc, cues, splits, sid = b
        dt = t - float(sc.t0)
        for c in cues:
            c.t = round(float(c.t) + dt, 4)
        for s in splits:
            s.film_t = round(float(s.film_t) + dt, 4)
        _shift_scene(sc, dt)
        if abs(want - dur) > 0.02:
            sc.t1 = round(sc.t0 + want, 4)
            for c in cues:
                if float(c.t) > sc.t1:
                    c.t = round(sc.t1 - 0.05, 4)
            if abs(want - dur) > 0.15:
                notes.append(f"{sid} {'held' if want > dur else 'tightened'} {want - dur:+.2f}s")
        new_cues += cues
        idmap[sid] = f"s{len(new_scenes):02d}_{_tname(sc.type).lower()}"
        new_scenes.append(sc)
        t = float(sc.t1)
        if k in inserts:
            ci = _cutin(sc, inserts[k])
            _shift_scene(ci, t)
            new_scenes.append(ci)
            new_cues.append(_cue_like(tl.cues, t))
            notes.append(f"cut-in after {sid}: {inserts[k]:.2f}s closer on the product")
            t = float(ci.t1)
    for k, sc in enumerate(new_scenes):
        sc.i = k
    tl.scenes = new_scenes
    tl.cues = sorted([c for c in new_cues if c is not None], key=lambda c: float(c.t))
    tl.dur = round(max(t, 1.0), 4)
    return notes, idmap


def remap(spec: dict[str, Any], idmap: dict[str, str]) -> dict[str, Any]:
    """The spec with shot ids renamed after :func:`apply_timeline` (dropped shots leave it)."""
    if not idmap:
        return spec
    out = copy.deepcopy(spec)
    out["shots"] = [{**e, "id": idmap[e["id"]]} for e in out.get("shots") or [] if e.get("id") in idmap]
    out.pop("order", None)
    return out


# ------------------------------------------------------------------------------------------- film

def _text_targets(params: dict[str, Any], wrapped: bool) -> dict[str, Any]:
    return params["data"] if wrapped and isinstance(params.get("data"), dict) else params


def _jtype(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return "string" if isinstance(v, str) else "array" if isinstance(v, (list, tuple)) else \
        "object" if isinstance(v, dict) else "null" if v is None else "other"


def _finite(v: Any) -> bool:
    """No NaN/Infinity anywhere (Python's json accepts them in a model reply; the page's JSON.parse does not)."""
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, (list, tuple)):
        return all(_finite(x) for x in v)
    if isinstance(v, dict):
        return all(_finite(x) for x in v.values())
    return True


def _typed_params(new: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A model's shot params that keep the preset value's JSON type (a ``bbox`` list stays a list: the string
    ``"the toggle"`` would turn the kit's camera maths into NaN) and hold only finite numbers."""
    ok: dict[str, Any] = {}
    bad: list[str] = []
    for k, v in (new or {}).items():
        cur = current.get(k) if isinstance(current, dict) else None
        if not _finite(v) or (cur is not None and v is not None and _jtype(cur) != _jtype(v)):
            bad.append(str(k))
        else:
            ok[k] = v
    return ok, bad


def _replace_words(x: Any, old: str, new: str) -> Any:
    if isinstance(x, str):
        # whole words only: renaming "Arc" must not turn "Architecture" into "Orbithitecture"
        return re.sub(rf"(?<![\w]){re.escape(old)}(?![\w])", lambda _m: new, x) if old and old in x else x
    if isinstance(x, list):
        return [_replace_words(v, old, new) for v in x]
    if isinstance(x, dict):
        return {k: (v if k in ("path", "asset", "src", "url", "scene", "theme", "id") else _replace_words(v, old, new))
                for k, v in x.items()}
    return x


def _retime_transitions(film: dict[str, Any], family: str, energy: str, kit_table: dict[str, Any]) -> list[str]:
    """Rebuild the transition list for a family (cut/soft/punchy/fade/kit) and the energy scaling."""
    shots = film["shots"]
    if len(shots) < 2 or (family in ("", "auto", "kit") and energy in ("", "normal")):
        return []
    by_pair = {(tr["from"], tr["to"]): tr for tr in film.get("transitions") or []}
    out = []
    for a, b in zip(shots, shots[1:]):
        tr = by_pair.get((a["id"], b["id"]))
        cut = (float(tr["t"]) + float(tr["dur"]) / 2) if tr else float(b["t0"])
        a["t1"] = b["t0"] = round(cut, 4)
        typ, dur = (tr["type"], float(tr["dur"])) if tr else (None, 0.0)
        if family == "cut":
            typ = None
        elif family == "soft":
            typ, dur = "crossfade", 0.55
        elif family == "fade":
            typ, dur = "dip-black", 0.6
        elif family == "punchy":
            typ, dur = ("whip", 0.28) if typ else (None, 0.0)
        if typ and energy == "high" and family in ("", "auto", "kit"):
            dur = max(0.16, dur * 0.6)
        elif energy == "calm" and family in ("", "auto", "kit"):
            typ, dur = (typ or "crossfade"), min(0.9, max(dur, 0.4) * 1.4)
        if not typ:
            continue
        d = round(min(dur, 0.4 * (a["t1"] - a["t0"]), 0.4 * (b["t1"] - b["t0"])), 3)
        if d < 0.1:
            continue
        a["t1"] = round(cut + d / 2, 4)
        b["t0"] = round(cut - d / 2, 4)
        out.append({"from": a["id"], "to": b["id"], "type": typ, "t": round(cut - d / 2, 4), "dur": d})
    film["transitions"] = out
    _ = kit_table
    return [f"transitions: {family or 'kit'} ({len(out)} transitions{', ' + energy + ' energy' if energy else ''})"]


def caption_style(base: dict[str, Any], mode: str, tokens: dict[str, str]) -> dict[str, Any]:
    cs = dict(base or {})
    size = float(cs.get("size") or 46)
    if mode == "bold":
        cs.update(size=round(size * 1.22), weight=800)
    elif mode == "minimal":
        cs.update(size=round(max(42, size * 0.92)), bg="rgba(0,0,0,0)", weight=min(700, int(cs.get("weight") or 600) + 100))
    elif mode == "boxed":
        cs.update(bg=V.rgba(V.mix(tokens.get("bg") or "#000000", "#000000", 0.4), 0.9))
    if tokens.get("body_font"):
        cs["font"] = tokens["body_font"]
    return cs


def theme_captions(cs: dict[str, Any], tokens: dict[str, str], style: str) -> dict[str, Any]:
    """Caption plate/colour following the theme (kits hard-code theirs in kit.json ``caption_style``)."""
    import re
    cs = dict(cs or {})
    if not tokens:
        return cs
    if style == "terminal" and tokens.get("accent"):
        cs["color"] = tokens["accent"]
        cs["bg"] = V.rgba(V.mix(tokens.get("bg") or tokens["accent"], "#000000", 0.3 if tokens.get("bg") else 0.955), 0.9)
        return cs
    if style == "comic" and (tokens.get("accent3") or tokens.get("accent2")):
        plate = tokens.get("accent3") or tokens["accent2"]
        cs.update(bg=plate, color=V.ink_on(plate))
        return cs
    nums = re.findall(r"[\d.]+", str(cs.get("bg") or ""))
    plate_hex = V.colour(cs.get("bg")) or (V.hexof(*map(float, nums[:3])) if len(nums) >= 3 else "")
    dark_plate = bool(plate_hex) and V.lum(plate_hex) < 0.35
    if tokens.get("bg") and dark_plate and V.lum(tokens["bg"]) < 0.35:
        cs["bg"] = V.rgba(V.mix(tokens["bg"], "#000000", 0.35), 0.86)
        if cs.get("color") and tokens.get("text"):
            cs["color"] = tokens["text"]
    return cs


def _cta_ok(value: str, current: str) -> bool:
    """A model-written END CTA may be words ('Grab it today'), or the film's own product command - never a new
    command or a line of code (the user's own ``cta=`` knob always wins)."""
    from ..story.onscreen import command_key, has_loopback, looks_like_command
    if has_loopback(value):
        return False
    return not looks_like_command(value) or (bool(current) and command_key(value) == command_key(current))


def apply_film(film: dict[str, Any], assets: dict[str, Any], *, style: str, knobs: dict[str, Any],
               spec: dict[str, Any], wrapped: bool = False, kit: dict[str, Any] | None = None) -> list[str]:
    """Customize a Quick film in place (and its asset specs). Returns notes for the job log."""
    notes: list[str] = []
    spec = spec or {}
    kit = kit or {}
    tokens = TH.resolve(knobs, spec.get("theme"))
    block = TH.theme_block(tokens)
    if block:
        film["theme"] = block
        fonts = TH.font_faces(tokens)
        have = {(f.get("family"), f.get("src")) for f in film.get("fonts") or []}
        film["fonts"] = list(film.get("fonts") or []) + [f for f in fonts if (f["family"], f["src"]) not in have]
        if tokens.get("bg"):
            film["background"] = tokens["bg"]
        notes.append("theme: " + ", ".join(f"{k} {v}" for k, v in tokens.items()))
    meta = film.setdefault("meta", {})
    shots = film.get("shots") or []
    by_id = {s["id"]: s for s in shots}
    # per-shot colour params: base-frame accent (inline vars), cinematic accent, terminal phosphor
    phos = TH.terminal_phosphor(tokens) if (style == "terminal" or kit.get("theme") == "terminal") else ""
    for s in shots:
        p = s.setdefault("params", {})
        if wrapped and str(s.get("scene", "")).startswith(f"kit:{style}/"):
            continue
        if tokens.get("accent"):
            p["accent"] = tokens["accent"]
        if phos and str(s.get("scene", "")).startswith(("kit:terminal/", "kit:base/")):
            p["phosphor"] = phos
    for o in film.get("overlays") or []:
        if tokens.get("accent") and isinstance(o.get("params"), dict):
            o["params"]["accent"] = tokens["accent"]
    # global words: product name, title, tagline, cta
    model_text = dict(spec.get("text") or {})
    end_cta = next((str(_text_targets(s.get("params") or {}, wrapped).get("cta") or "") for s in shots
                    if s["id"].endswith("_end")), "")
    if model_text.get("cta") and not _cta_ok(str(model_text["cta"]), end_cta):
        notes.append(f"cta {model_text.pop('cta')!r} is not the product's own command; the film's END keeps its own")
    text = {**model_text, **{k: knobs[k] for k in ("title", "tagline", "cta", "product") if knobs.get(k)}}
    old_name = ""
    for s in shots:
        if s["id"].endswith("_title"):
            d = _text_targets(s.get("params") or {}, wrapped)
            old_name = str(d.get("title") or d.get("product") or "")
            break
    old_name = old_name or str(film.get("title") or "")
    if text.get("product") and old_name and text["product"] != old_name:
        for s in shots:
            s["params"] = _replace_words(s.get("params") or {}, old_name, text["product"])
        for o in film.get("overlays") or []:
            o["params"] = _replace_words(o.get("params") or {}, old_name, text["product"])
        film["captions"] = _replace_words(film.get("captions") or [], old_name, text["product"])
        notes.append(f"product name {old_name!r} -> {text['product']!r}")
    for s in shots:
        d = _text_targets(s.setdefault("params", {}), wrapped)
        typ = s["id"].split("_", 1)[-1].upper()
        if typ == "TITLE":
            if text.get("title"):
                d["title"] = text["title"]
            if text.get("tagline"):
                d["tagline"] = text["tagline"]
        if typ == "END":
            if text.get("title"):
                d["title"] = text["title"]
            if text.get("cta"):
                d["cta"] = text["cta"]
    if text.get("title"):
        film["title"] = text["title"]
        for o in film.get("overlays") or []:
            if o.get("id") == "speedrun_hud":
                continue
            if isinstance(o.get("params"), dict) and "title" in o["params"]:
                o["params"]["title"] = text["title"]
    if text:
        notes.append("text: " + ", ".join(f"{k}={v!r}" for k, v in text.items()))
    # per-shot params + words from the spec
    for e in spec.get("shots") or []:
        s = by_id.get(e.get("id"))
        if s is None or e.get("remove"):
            continue
        p = s.setdefault("params", {})
        if e.get("params"):
            from ..director.patches import deep_merge
            ok_params, bad = _typed_params(e["params"], p)
            if bad:
                notes.append(f"{s['id']}: dropped params {bad} (wrong type or not a finite number)")
            if wrapped and str(s.get("scene", "")).startswith(f"kit:{style}/"):
                p.update(deep_merge({k: p.get(k) for k in ok_params if k in p}, ok_params))
            else:
                s["params"] = deep_merge(p, ok_params)
            if ok_params:
                notes.append(f"{s['id']}: params {sorted(ok_params)}")
        for k, v in (e.get("text") or {}).items():
            if k == "cta" and not knobs.get("cta") and not _cta_ok(str(v), end_cta):
                notes.append(f"{s['id']}: cta {v!r} is not the product's own command; kept")
                continue
            d = _text_targets(s["params"], wrapped)
            if k in d or k in ("label", "headline", "title", "feature", "tagline", "cta", "boss_name", "pick_text"):
                d[k] = v
                notes.append(f"{s['id']}: {k} = {v!r}")
    # transitions (family + energy)
    energy = str(knobs.get("energy") or spec.get("energy") or "")
    family = str(knobs.get("transitions") or spec.get("transitions") or "")
    notes += _retime_transitions(film, family, energy, kit.get("transitions") or {})
    if energy == "high":
        fin = film.setdefault("finish", {})
        fin["vignette"] = round(float(fin.get("vignette") or 0.0) + 0.04, 3)
    # captions
    cap = str(knobs.get("captions") or spec.get("captions") or "")
    if cap == "off":
        film["captions"] = []
        for s in shots:
            (s.get("params") or {}).pop("_captions", None)
        notes.append("captions off")
    elif cap in ("bold", "minimal", "boxed") or tokens.get("body_font"):
        film["caption_style"] = caption_style(theme_captions(film.get("caption_style") or {}, tokens, style), cap, tokens)
        notes.append(f"captions {cap or 'restyled'}")
    elif tokens and film.get("captions"):
        film["caption_style"] = theme_captions(film.get("caption_style") or {}, tokens, style)
    # music (the pipeline's audio stage plays film.music[0].bed; "none" handled by the deps wrapper)
    bed = str(knobs.get("music") or spec.get("music") or "")
    if not bed and energy in ("calm", "high"):
        bed = V.bed_for_energy(style, energy)
    if bed and bed != "none":
        film["music"] = [{"bed": bed, "t0": 0.0, "t1": float(film["dur"])}]
        notes.append(f"music bed {bed}")
    # logo corner bug
    logo = str(knobs.get("logo") or "")
    if logo and Path(logo).is_file():
        assets[LOGO_ASSET] = {"src": str(Path(logo).resolve()), "type": "image"}
        film.setdefault("assets", {})[LOGO_ASSET] = {"type": "image"}
        film.setdefault("overlays", []).append({"id": "brand_logo", "t0": 0.0, "t1": float(film["dur"]),
                                                "scene": "kit:brand/logo", "params": {"asset": LOGO_ASSET}})
        if "brand" not in film.setdefault("kits", []):
            film["kits"].append("brand")
        notes.append(f"logo {Path(logo).name}")
    meta["customize"] = {"tokens": tokens, "energy": energy, "transitions": family, "captions": cap,
                         "music": bed, "text": text, "shots": [e.get("id") for e in spec.get("shots") or []],
                         "summary": spec.get("summary", "")}
    return notes


def copy_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(spec or {})


__all__ = ["apply_timeline", "remap", "apply_film", "shot_rows", "caption_style", "SHOT_TEXT_FIELDS"]
