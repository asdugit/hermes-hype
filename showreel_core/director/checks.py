"""Code-enforced quality gates for the Director: treatment/film validation with safe auto-fixes, the
product-visibility and hook measurements, beat snapping, and the scene-code extractor + static lint.

Errors go back to the model (repair call); warnings were fixed automatically and are logged.
"""
from __future__ import annotations

import copy
import itertools
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .catalog import Catalog, SceneInfo
from .types import PRODUCT_SHARE_BAR, Brief

SCENE_LAYERS = ("2d", "three", "webgl", "dom")
RUNTIME_IMPORT = "import { sr } from '../runtime/showreel.js';"
MAX_SCENE_BYTES = 80_000


@dataclass
class Checked:
    """Validation outcome: the (fixed) value, errors for the model, warnings/fixes for the log."""
    value: Any
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _num(x: Any, default: float | None = None) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _dict(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _slug(s: Any) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    return out[:40] or "x"


def references(obj: Any, names: set[str]) -> set[str]:
    """Asset names referenced anywhere in a params structure (string values equal to a name)."""
    found: set[str] = set()
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            if cur in names:
                found.add(cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return found


# ------------------------------------------------------------------------------------ treatment

def check_treatment(obj: Any, brief: Brief, catalog: Catalog) -> Checked:
    """Validate a treatment; rescale act durations to the film length when they are close."""
    if not isinstance(obj, dict):
        return Checked(obj, ["the treatment must be a JSON object"])
    t = copy.deepcopy(obj)
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("logline", "selling_point", "payoff", "cta"):
        if not str(t.get(key) or "").strip():
            errors.append(f"`{key}` is missing or empty")
    reqs = t.get("requirements")
    if not isinstance(reqs, list) or not [r for r in reqs if isinstance(r, dict) and str(r.get("text", "")).strip()]:
        errors.append("`requirements` must list every explicit requirement of the user's direction with how it is met")
    hook = _dict(t.get("hook"))
    ht = _num(hook.get("t"))
    if ht is None or not str(hook.get("what") or "").strip():
        errors.append("`hook` needs `t` (seconds) and `what`")
    elif ht > 2.0:
        errors.append(f"the hook lands at {ht:g} s; it must land within 2 s")
    acts = t.get("acts")
    if not isinstance(acts, list) or not acts:
        errors.append("`acts` must be a non-empty list")
        acts = []
    total = 0.0
    for i, a in enumerate(acts):
        if not isinstance(a, dict):
            errors.append(f"acts[{i}] must be an object")
            continue
        d = _num(a.get("duration"))
        if d is None or d <= 0:
            errors.append(f"acts[{i}] ({a.get('name', '?')}) needs a positive `duration`")
            continue
        total += d
        if not [b for b in a.get("beats") or [] if str(b).strip()]:
            errors.append(f"acts[{i}] ({a.get('name', '?')}) needs concrete `beats`")
        if not str(a.get("world") or "").strip():
            errors.append(f"acts[{i}] needs a `world`")
    if total > 0 and not errors:
        if abs(total - brief.seconds) > 0.15 * brief.seconds:
            errors.append(f"act durations add up to {total:g} s; the film is {brief.seconds:g} s")
        elif abs(total - brief.seconds) > 1e-6:
            k = brief.seconds / total
            for a in acts:
                a["duration"] = round(float(a["duration"]) * k, 2)
            warnings.append(f"rescaled act durations from {total:g} s to {brief.seconds:g} s")
    beds = {b.id for b in catalog.beds}
    if beds:
        mp = [m for m in t.get("music_plan") or [] if isinstance(m, dict)]
        bad = [m.get("bed") for m in mp if m.get("bed") not in beds]
        if bad:
            warnings.append(f"dropped unknown music beds {bad}")
            t["music_plan"] = [m for m in mp if m.get("bed") in beds]
    sfx = set(catalog.sfx)
    if sfx and isinstance(t.get("stings"), list):
        keep = [s for s in t["stings"] if isinstance(s, dict) and s.get("sting") in sfx]
        if len(keep) != len(t["stings"]):
            warnings.append("dropped unknown stings")
        t["stings"] = keep
    names = {a.name for a in brief.assets}
    plan = [p for p in t.get("asset_plan") or [] if isinstance(p, dict)]
    unknown = [p.get("asset") for p in plan if p.get("asset") not in names]
    if unknown:
        warnings.append(f"dropped asset_plan entries for unknown assets {unknown}")
        t["asset_plan"] = [p for p in plan if p.get("asset") in names]
    product_assets = {a.name for a in brief.assets if a.product}
    if product_assets and not ({p.get("asset") for p in t.get("asset_plan") or []} & product_assets):
        errors.append(f"`asset_plan` must plan the use of the product media ({sorted(product_assets)})")
    return Checked(t, errors, warnings)


# ------------------------------------------------------------------------------------ film

def check_film(obj: Any, brief: Brief, catalog: Catalog, *, max_custom: int) -> Checked:
    """Validate + normalise ``{"film": ..., "plan": ...}``. ``value`` is ``(film, plan)`` when usable."""
    if not isinstance(obj, dict) or not isinstance(obj.get("film"), dict):
        return Checked(None, ["the answer must be a JSON object with `film` and `plan`"])
    film = copy.deepcopy(obj["film"])
    plan = copy.deepcopy(_dict(obj.get("plan")))
    errors: list[str] = []
    warnings: list[str] = []
    dur = float(brief.seconds)
    w, h = brief.size
    film.update({"version": 1, "fps": brief.fps, "size": [w, h], "dur": dur, "seed": brief.seed})
    film.setdefault("title", brief.product.name if brief.product and brief.product.name else "Showreel")
    film.setdefault("background", "#000")

    shots = _check_shots(film, dur, errors, warnings)
    known = catalog.scenes()
    customs = _check_customs(plan, shots, catalog, brief, max_custom, errors, warnings)
    for s in shots:
        scene = s["scene"]
        if scene.startswith("custom:"):
            continue
        if scene not in known:
            choices = ", ".join(sorted(known)) or "(none installed: use custom scenes)"
            errors.append(f"shot `{s['id']}` uses unknown scene `{scene}`; choose from: {choices}")
            continue
        info = known[scene]
        if info.params:
            extra = [k for k in s["params"] if k not in info.params]
            if extra:
                warnings.append(f"shot `{s['id']}`: params {extra} are not declared by `{scene}`")
    _check_transitions(film, shots, catalog, errors, warnings)
    _check_overlays(film, dur, known, customs, errors, warnings)
    _check_audio(film, dur, catalog, errors, warnings)
    _check_captions(film, dur, errors, warnings)
    _check_finish(film)
    plan["shots"] = _check_plan_shots(plan, shots, warnings)
    plan["custom_scenes"] = list(customs.values())
    names = {a.name for a in brief.assets}
    used = set()
    for s in shots:
        used |= references(s["params"], names)
    for o in film.get("overlays") or []:
        used |= references(o.get("params") or {}, names)
    film["assets"] = {a.name: {"type": "frames" if a.type == "video" else "image"}
                      for a in brief.assets if a.name in used}
    product = {a.name for a in brief.assets if a.product}
    if product and shots:
        share, missing = product_share(film, product)
        if share + 1e-6 < PRODUCT_SHARE_BAR:
            errors.append(f"the product media is referenced in only {share:.0%} of the runtime (needs >= "
                          f"{PRODUCT_SHARE_BAR:.0%}); shots without it: {missing}. Put the product into more shots "
                          "(as hero, boss, flyer, screen, reflection...) or shorten the shots without it")
        first = first_product_time(film, product)
        if first is None:
            errors.append("no shot shows the product media")
        elif first > min(6.0, 0.25 * dur):
            errors.append(f"the product first appears at {first:g} s; show or tease it in the first 2 s")
        elif first > 2.0:
            warnings.append(f"the product first appears at {first:g} s (doctrine: by 2 s)")
    if not errors:
        warnings += snap_cuts_to_beats(film, catalog)
    return Checked((film, plan) if shots else None, errors, warnings)


def _check_shots(film: dict[str, Any], dur: float, errors: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    raw = film.get("shots")
    if not isinstance(raw, list) or not raw:
        errors.append("`film.shots` must be a non-empty list")
        film["shots"] = []
        return []
    shots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            errors.append(f"shots[{i}] must be an object")
            continue
        t0, t1 = _num(s.get("t0")), _num(s.get("t1"))
        if t0 is None or t1 is None or t1 - t0 < 0.5:
            errors.append(f"shots[{i}] (`{s.get('id')}`) needs numeric t0 < t1 (>= 0.5 s long)")
            continue
        sid = _slug(s.get("id") or f"shot{i + 1}")
        while sid in seen:
            sid += "-b"
        seen.add(sid)
        scene = str(s.get("scene") or "").strip()
        if not re.match(r"^(kit:[a-z0-9_-]+/[a-z0-9_.-]+|lib:[a-z0-9_.-]+|custom:[a-z0-9_.-]+)$", scene, re.IGNORECASE):
            errors.append(f"shot `{sid}` has an invalid scene id `{scene}`")
        res = s.get("res")
        if isinstance(res, list) and len(res) == 2 and all(_num(v) for v in res):
            res = [round(float(res[0])), round(float(res[1]))]
        else:
            res = None
        out = {"id": sid, "t0": round(t0, 3), "t1": round(t1, 3), "scene": scene, "res": res,
               "params": _dict(s.get("params"))}
        for k in ("z", "upscale"):
            if k in s:
                out[k] = s[k]
        shots.append(out)
    shots.sort(key=lambda s: s["t0"])
    if shots:
        if shots[0]["t0"] != 0:
            if shots[0]["t0"] <= 0.6:
                warnings.append(f"first shot moved to start at 0 (was {shots[0]['t0']:g})")
                shots[0]["t0"] = 0.0
            else:
                errors.append(f"the first shot starts at {shots[0]['t0']:g} s; shots must cover 0..{dur:g}")
        for a, b in itertools.pairwise(shots):
            gap = b["t0"] - a["t1"]
            if abs(gap) > 1e-6:
                if abs(gap) <= 0.6:
                    warnings.append(f"joined `{a['id']}`/`{b['id']}` at {b['t0']:g} s (gap {gap:+.2f} s)")
                    a["t1"] = b["t0"]
                else:
                    errors.append(f"`{a['id']}` ends at {a['t1']:g} s but `{b['id']}` starts at {b['t0']:g} s; "
                                  "shots must be back to back")
        last = shots[-1]
        if abs(last["t1"] - dur) > 1e-6:
            if abs(last["t1"] - dur) <= 1.0:
                warnings.append(f"last shot end moved from {last['t1']:g} to {dur:g} s")
                last["t1"] = dur
            else:
                errors.append(f"the last shot ends at {last['t1']:g} s; the film is {dur:g} s")
    film["shots"] = shots
    return shots


def _check_customs(plan: dict[str, Any], shots: list[dict[str, Any]], catalog: Catalog, brief: Brief,
                   max_custom: int, errors: list[str], warnings: list[str]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for c in plan.get("custom_scenes") or []:
        if isinstance(c, dict) and c.get("name"):
            name = _slug(c["name"])
            specs[name] = dict(c, name=name)
    used = []
    for s in shots:
        if s["scene"].startswith("custom:"):
            name = _slug(s["scene"].split(":", 1)[1])
            s["scene"] = f"custom:{name}"
            if name not in used:
                used.append(name)
    for name in list(specs):
        if name not in used:
            warnings.append(f"dropped unused custom scene spec `{name}`")
            specs.pop(name)
    if len(used) > max_custom:
        errors.append(f"{len(used)} custom scenes ({used}); at most {max_custom}: use kit scenes for the rest or "
                      "serve several shots with one custom scene through params")
    asset_names = {a.name for a in brief.assets}
    known = catalog.scenes()
    for name in used:
        spec = specs.get(name)
        if spec is None:
            errors.append(f"`custom:{name}` is used by a shot but has no entry in plan.custom_scenes")
            continue
        if spec.get("layer") not in SCENE_LAYERS:
            warnings.append(f"custom scene `{name}`: layer {spec.get('layer')!r} -> '2d'")
            spec["layer"] = "2d"
        if len(str(spec.get("spec") or "")) < 200:
            errors.append(f"custom scene `{name}`: `spec` is too vague (write the full animation brief: layers, "
                          "palette, product placement, beats with times, text, cues)")
        if not isinstance(spec.get("params"), dict):
            spec["params"] = {}
        for pname, pdef in spec["params"].items():
            if isinstance(pdef, dict) and pdef.get("type") == "asset":
                vals = [s["params"].get(pname) for s in shots if s["scene"] == f"custom:{name}"]
                bad = [v for v in vals if v is not None and v not in asset_names]
                if bad:
                    errors.append(f"custom scene `{name}` param `{pname}` refers to unknown assets {bad}; "
                                  f"assets: {sorted(asset_names)}")
        fb = str(spec.get("fallback") or "")
        if fb and fb not in known:
            warnings.append(f"custom scene `{name}`: fallback `{fb}` is not a known scene")
            spec["fallback"] = ""
        spec["kits"] = [str(k) for k in spec.get("kits") or [] if catalog.kit(str(k))]
    return {n: specs[n] for n in used if n in specs}


def _check_transitions(film: dict[str, Any], shots: list[dict[str, Any]], catalog: Catalog,
                       errors: list[str], warnings: list[str]) -> None:
    by_id = {s["id"]: s for s in shots}
    allowed = catalog.transitions()
    out = []
    for i, tr in enumerate(film.get("transitions") or []):
        if not isinstance(tr, dict):
            continue
        a, b = by_id.get(_slug(tr.get("from", ""))), by_id.get(_slug(tr.get("to", "")))
        if not a or not b:
            errors.append(f"transitions[{i}] refers to unknown shots {tr.get('from')!r} -> {tr.get('to')!r}")
            continue
        if abs(a["t1"] - b["t0"]) > 1e-6:
            errors.append(f"transitions[{i}]: `{a['id']}` and `{b['id']}` are not adjacent")
            continue
        typ = str(tr.get("type") or "cut")
        if typ not in allowed:
            warnings.append(f"transition type `{typ}` unknown -> crossfade")
            typ = "crossfade"
        d = min(3.0, max(0.1, _num(tr.get("dur"), 0.6) or 0.6))
        cut = a["t1"]
        t = _num(tr.get("t"), cut - d / 2)
        assert t is not None
        if not (t - 1e-6 <= cut <= t + d + 1e-6):
            warnings.append(f"transition {a['id']}->{b['id']} window re-centred on the cut at {cut:g} s")
            t = cut - d / 2
        t = max(0.0, t)
        out.append({"from": a["id"], "to": b["id"], "type": typ, "t": round(t, 3), "dur": round(d, 3),
                    "params": _dict(tr.get("params"))})
    film["transitions"] = out


def _check_overlays(film: dict[str, Any], dur: float, known: dict[str, SceneInfo], customs: dict[str, Any],
                    errors: list[str], warnings: list[str]) -> None:
    out = []
    for i, o in enumerate(film.get("overlays") or []):
        if not isinstance(o, dict):
            continue
        t0, t1 = _num(o.get("t0"), 0.0) or 0.0, _num(o.get("t1"), dur) or dur
        t0, t1 = max(0.0, t0), min(dur, t1)
        if t1 - t0 < 0.3:
            warnings.append(f"dropped overlay {i} (shorter than 0.3 s)")
            continue
        scene = str(o.get("scene") or "")
        if scene not in known and not (scene.startswith("custom:") and scene.split(":", 1)[1] in customs):
            errors.append(f"overlay `{o.get('id', i)}` uses unknown scene `{scene}`")
            continue
        out.append({"id": _slug(o.get("id") or f"overlay{i + 1}"), "t0": round(t0, 3), "t1": round(t1, 3),
                    "scene": scene, "params": _dict(o.get("params"))})
    film["overlays"] = out


def _check_audio(film: dict[str, Any], dur: float, catalog: Catalog, errors: list[str], warnings: list[str]) -> None:
    beds = {b.id for b in catalog.beds}
    sfx = set(catalog.sfx)
    music = []
    for m in film.get("music") or []:
        if not isinstance(m, dict):
            continue
        if m.get("bed"):
            if beds and m["bed"] not in beds:
                errors.append(f"music bed `{m['bed']}` does not exist; beds: {sorted(beds)}")
                continue
            t0, t1 = max(0.0, _num(m.get("t0"), 0.0) or 0.0), min(dur, _num(m.get("t1"), dur) or dur)
            if t1 - t0 >= 1.0:
                music.append({"bed": m["bed"], "t0": round(t0, 3), "t1": round(t1, 3)})
        elif m.get("sting"):
            if sfx and m["sting"] not in sfx:
                warnings.append(f"dropped unknown sting `{m['sting']}`")
                continue
            t = _num(m.get("t"))
            if t is not None and 0 <= t <= dur:
                music.append({"sting": m["sting"], "t": round(t, 3)})
    covered = sum(m["t1"] - m["t0"] for m in music if "bed" in m)
    if beds and covered < 0.8 * dur:
        warnings.append(f"music beds cover only {covered:.1f} of {dur:g} s")
    film["music"] = music
    cues = []
    for c in film.get("cues") or []:
        if not isinstance(c, dict):
            continue
        t = _num(c.get("t"))
        if t is None or not 0 <= t <= dur:
            continue
        if sfx and c.get("sfx") not in sfx:
            warnings.append(f"dropped cue with unknown sfx `{c.get('sfx')}`")
            continue
        cue = {"t": round(t, 3), "sfx": c.get("sfx")}
        g = _num(c.get("gain_db"))
        if g is not None:
            cue["gain_db"] = max(-24.0, min(6.0, g))
        cues.append(cue)
    film["cues"] = sorted(cues, key=lambda c: c["t"])


def _check_captions(film: dict[str, Any], dur: float, errors: list[str], warnings: list[str]) -> None:
    caps = []
    for c in film.get("captions") or []:
        if not isinstance(c, dict) or not str(c.get("text") or "").strip():
            continue
        t0, t1 = _num(c.get("t0")), _num(c.get("t1"))
        if t0 is None or t1 is None:
            continue
        t0, t1 = max(0.0, t0), min(dur, t1)
        text = " ".join(str(c["text"]).split())
        words = len(text.split())
        if words > 14:
            errors.append(f"caption {text!r} has {words} words; keep captions <= 8 words")
        elif words > 8:
            warnings.append(f"caption {text!r} has {words} words (doctrine: <= 8)")
        if t1 - t0 >= 0.6:
            caps.append({"t0": round(t0, 3), "t1": round(t1, 3), "text": text})
    caps.sort(key=lambda c: c["t0"])
    for a, b in itertools.pairwise(caps):
        if b["t0"] < a["t1"]:
            a["t1"] = b["t0"]
            warnings.append(f"trimmed caption {a['text']!r} so captions never overlap")
    film["captions"] = [c for c in caps if c["t1"] - c["t0"] >= 0.6]


def _check_finish(film: dict[str, Any]) -> None:
    f = _dict(film.get("finish"))
    limits = {"grain": 0.2, "vignette": 0.6, "bloom": 1.0}
    film["finish"] = {k: max(0.0, min(lim, _num(f.get(k), 0.0) or 0.0)) for k, lim in limits.items() if k in f}


def _check_plan_shots(plan: dict[str, Any], shots: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    given = {_slug(p.get("id")): p for p in plan.get("shots") or [] if isinstance(p, dict) and p.get("id")}
    out = []
    for s in shots:
        p = given.get(s["id"])
        if p is None:
            warnings.append(f"plan has no intent for shot `{s['id']}`")
            p = {"intent": "", "product_visible": False, "beats": []}
        out.append({"id": s["id"], "intent": str(p.get("intent", "")), "product_visible": bool(p.get("product_visible")),
                    "beats": p.get("beats") if isinstance(p.get("beats"), list) else []})
    return out


def product_share(film: dict[str, Any], product_assets: set[str]) -> tuple[float, list[str]]:
    """Share of the runtime whose shots (or overlays) reference product media, and the shot ids without it."""
    dur = float(film.get("dur") or 0) or 1.0
    covered: list[tuple[float, float]] = []
    missing = []
    for s in film.get("shots") or []:
        if references(s.get("params") or {}, product_assets):
            covered.append((s["t0"], s["t1"]))
        else:
            missing.append(s["id"])
    for o in film.get("overlays") or []:
        if references(o.get("params") or {}, product_assets):
            covered.append((o["t0"], o["t1"]))
    total, end = 0.0, -1.0
    for a, b in sorted(covered):
        a = max(a, end)
        if b > a:
            total += b - a
            end = b
    return min(1.0, total / dur), missing


def first_product_time(film: dict[str, Any], product_assets: set[str]) -> float | None:
    """Start of the first shot/overlay that references product media."""
    ts = [float(s["t0"]) for s in film.get("shots") or [] if references(s.get("params") or {}, product_assets)]
    ts += [float(o["t0"]) for o in film.get("overlays") or [] if references(o.get("params") or {}, product_assets)]
    return min(ts) if ts else None


def snap_cuts_to_beats(film: dict[str, Any], catalog: Catalog, *, tol: float = 0.18) -> list[str]:
    """Move shot boundaries within ``tol`` of a beat of the active bed onto the beat (music-led cutting)."""
    notes = []
    beds = [m for m in film.get("music") or [] if "bed" in m]
    shots = film.get("shots") or []
    for a, b in itertools.pairwise(shots):
        cut = b["t0"]
        bed = next((m for m in beds if m["t0"] <= cut < m["t1"]), None)
        info = catalog.bed(bed["bed"]) if bed else None
        if not info or info.bpm <= 0:
            continue
        beat = 60.0 / info.bpm
        snapped = round(bed["t0"] + round((cut - bed["t0"]) / beat) * beat, 3)
        delta = snapped - cut
        if 0.02 < abs(delta) <= tol and snapped - a["t0"] >= 0.5 and b["t1"] - snapped >= 0.5:
            a["t1"] = b["t0"] = snapped
            for tr in film.get("transitions") or []:
                if tr["from"] == a["id"] and tr["to"] == b["id"]:
                    tr["t"] = round(max(0.0, tr["t"] + delta), 3)
            notes.append(f"cut {a['id']}->{b['id']} snapped {cut:g}->{snapped:g} s (beat of {info.id})")
    return notes


# ------------------------------------------------------------------------------------ scene code

_FENCE_RE = re.compile(r"```(?:js|javascript|mjs|jsx)?[ \t]*\n(.*?)(?:```|\Z)", re.DOTALL | re.IGNORECASE)

FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"\bMath\s*\.\s*random\b", "Math.random is forbidden: use ctx.rng(seed) (create tables in setup)"),
    (r"\bDate\b", "Date is forbidden: derive everything from t"),
    (r"\bperformance\s*\.\s*now\b", "performance.now is forbidden: derive everything from t"),
    (r"\b(setTimeout|setInterval|requestAnimationFrame|requestIdleCallback)\b",
     "timers/requestAnimationFrame are forbidden: render(ctx, t, p) is called for every frame"),
    (r"\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b|\bnavigator\s*\.\s*sendBeacon\b",
     "network APIs are forbidden"),
    (r"\bimport\s*\(", "dynamic import() is forbidden"),
    (r"\beval\s*\(|\bnew\s+Function\b|\bFunction\s*\(", "eval / new Function are forbidden"),
    (r"\bdocument\s*\.", "document access is forbidden: draw on ctx.g / ctx.canvas (dom scenes: ctx.root)"),
    (r"\bwindow\s*\.(?!\s*devicePixelRatio\b)", "window access is forbidden (only window.devicePixelRatio)"),
    (r"\blocalStorage\b|\bsessionStorage\b|\bindexedDB\b", "storage APIs are forbidden"),
)


def extract_js(text: str) -> str:
    """The scene module from a model reply: the fenced block that defines a scene (or the bare code)."""
    if not text:
        return ""
    blocks = [m.group(1) for m in _FENCE_RE.finditer(text)]
    blocks = [b for b in blocks if "defineScene" in b] or blocks
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    i = min((p for p in (text.find("import "), text.find("sr.defineScene")) if p >= 0), default=-1)
    return text[i:].strip() + "\n" if i >= 0 else ""


def normalize_scene_code(code: str, scene_id: str) -> str:
    """Force the runtime import and the exact scene id (the model sometimes renames the scene)."""
    code = code.replace("\r\n", "\n")
    code = re.sub(r"""(sr\s*\.\s*defineScene\(\s*)(['"`])[^'"`]*\2""", lambda m: f"{m.group(1)}'{scene_id}'", code,
                  count=1)
    lines = code.split("\n")
    kept = [ln for ln in lines if not re.match(r"""\s*import\s*\{\s*sr\s*\}\s*from\s*['"][^'"]*['"]\s*;?\s*$""", ln)]
    return RUNTIME_IMPORT + "\n" + "\n".join(kept).lstrip("\n")


def strip_comments(code: str) -> str:
    """Remove // and /* */ comments, keeping string and template literals intact."""
    out: list[str] = []
    i, n = 0, len(code)
    quote = ""
    while i < n:
        c = code[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
        elif code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_strings(code: str) -> str:
    code = re.sub(r"`(?:\\.|[^`\\])*`", "''", code)
    return re.sub(r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*\"""", "''", code)


def _balance(code: str) -> str:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for c in _strip_strings(code):
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                return f"unbalanced `{c}`"
            stack.pop()
    return f"{len(stack)} unclosed bracket(s) (the code looks truncated)" if stack else ""


def lint_scene(code: str, scene_id: str) -> tuple[list[str], list[str]]:
    """Static checks for a scene module: (errors, warnings). Mirrors SDK section 7 + structural sanity."""
    errors: list[str] = []
    warnings: list[str] = []
    if not code.strip():
        return ["no JavaScript code found in the reply"], []
    if len(code.encode("utf-8")) > MAX_SCENE_BYTES:
        errors.append(f"the scene is {len(code) // 1000} KB; keep it under {MAX_SCENE_BYTES // 1000} KB")
    bare = strip_comments(code)
    for pat, msg in FORBIDDEN:
        if re.search(pat, _strip_strings(bare)):
            errors.append(msg)
    if re.search(r"""['"`]\s*(https?:)?//[a-z0-9.-]+\.[a-z]{2,}""", bare, re.IGNORECASE):
        errors.append("external URLs are forbidden")
    for m in re.finditer(r"""^\s*import\b[^;\n]*""", bare, re.MULTILINE):
        if "../runtime/showreel.js" not in m.group(0):
            errors.append(f"only the runtime import is allowed, found: {m.group(0).strip()[:80]}")
    ids = re.findall(r"""sr\s*\.\s*defineScene\(\s*['"`]([^'"`]+)['"`]""", bare)
    if not ids:
        errors.append("the module must call sr.defineScene('<id>', {...})")
    elif ids[0] != scene_id:
        errors.append(f"the scene id must be `{scene_id}` (found `{ids[0]}`)")
    if len(ids) > 1:
        errors.append("define exactly one scene per module")
    if not re.search(r"\brender\s*(\(|:)", bare):
        errors.append("the scene must define render(ctx, t, p)")
    if not re.search(r"""\blayer\s*:\s*['"`](2d|three|webgl|dom)['"`]""", bare):
        errors.append("the scene must declare layer: '2d' | 'three' | 'webgl' | 'dom'")
    bal = _balance(bare)
    if bal:
        errors.append(f"syntax: {bal}")
    if re.search(r"\.fillText\s*\(", bare):
        warnings.append("uses fillText: readable text should go through ctx.text (QA boxes)")
    return errors, warnings


def nearest_kit_scene(spec: dict[str, Any], catalog: Catalog, *, layer_bonus: float = 0.15) -> SceneInfo | None:
    """The kit scene closest to a custom scene spec (explicit fallback first, then word overlap)."""
    known = catalog.scenes()
    fb = str(spec.get("fallback") or "")
    if fb in known:
        return known[fb]
    words = set(re.findall(r"[a-z]{3,}", f"{spec.get('name', '')} {spec.get('describe', '')} "
                                          f"{spec.get('spec', '')}".lower()))
    kits = {str(k) for k in spec.get("kits") or []}
    best, best_score = None, 0.0
    for s in known.values():
        if not s.id.startswith("kit:") or s.kit == "transitions":
            continue
        cand = set(re.findall(r"[a-z]{3,}", f"{s.id} {s.describe}".lower()))
        score = len(words & cand) / (len(cand) ** 0.5 + 1)
        score += layer_bonus if s.layer and s.layer == spec.get("layer") else 0.0
        score += 0.5 if s.kit in kits else 0.0
        if score > best_score:
            best, best_score = s, score
    return best


def fallback_params(spec: dict[str, Any], shot_params: dict[str, Any], target: SceneInfo,
                    asset_names: set[str]) -> dict[str, Any]:
    """Carry over params the kit scene declares; map product media onto its first media-like param."""
    out = {k: v for k, v in shot_params.items() if k in target.params} if target.params else {}
    media = sorted(references(shot_params, asset_names))
    if media and not references(out, asset_names):
        slot = next((p for p in target.params if re.search(r"media|asset|image|product|hero|src", p)), None)
        if slot:
            out[slot] = media[0]
        elif not target.params:
            out["media"] = media[0]
    return out
