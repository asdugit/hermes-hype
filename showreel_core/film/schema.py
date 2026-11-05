"""film.json schema (SDK.md §2): stdlib-only validator with precise error paths, plus normalisation.

``validate_film(film)`` returns a list of :class:`FilmIssue` (``severity`` = "error" | "warning"); a film is
renderable when no issue is an error. Paths look like ``shots[2].t1`` or ``transitions[0].to`` so the Director
can patch exactly the field that is wrong.
"""
from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, TypeGuard

SCENE_ID_RE = re.compile(r"^(kit:[a-z0-9_-]+/[a-z0-9_.-]+|lib:[a-z0-9_.-]+|custom:[a-z0-9_.-]+)$", re.IGNORECASE)
SHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
ASSET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
KIT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

BUILTIN_TRANSITIONS: frozenset[str] = frozenset({
    "cut", "crossfade", "dip-black", "dip-white", "push", "push-left", "push-right", "push-up", "push-down",
    "whip", "zoom-through", "iris", "wipe", "glitch", "pixelate", "film-burn", "ink-bleed", "page-turn",
})
CUE_ALIGN = ("auto", "onset", "peak", "end")
TOP_KEYS = frozenset({
    "version", "fps", "size", "dur", "seed", "title", "background", "fonts", "assets", "shots", "transitions",
    "overlays", "finish", "cues", "music", "captions", "caption_style", "safe", "kits", "qa", "meta",
})
ITEM_KEYS = frozenset({"id", "t0", "t1", "scene", "res", "params", "z", "upscale", "note"})
MIN_CAPTION_PX = 42
EPS = 1e-6


@dataclass(frozen=True)
class FilmIssue:
    """One validation finding."""
    path: str
    msg: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"{self.path}: {self.msg}" if self.path else self.msg

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _num(v: Any) -> TypeGuard[float]:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v: Any) -> TypeGuard[int]:
    return _num(v) and float(v).is_integer()


def _rel_path_problem(p: Any) -> str | None:
    if not isinstance(p, str) or not p.strip():
        return "must be a non-empty relative path"
    if re.match(r"^[a-z][a-z0-9+.-]*:", p, re.IGNORECASE) or p.startswith("//"):
        return "must be a job-relative path, not a URL"
    if p.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", p):
        return "must be relative to the job dir"
    if ".." in re.split(r"[\\/]", p):
        return "must not contain '..'"
    return None


class _V:
    def __init__(self) -> None:
        self.issues: list[FilmIssue] = []

    def err(self, path: str, msg: str) -> None:
        self.issues.append(FilmIssue(path, msg, "error"))

    def warn(self, path: str, msg: str) -> None:
        self.issues.append(FilmIssue(path, msg, "warning"))

    def unknown(self, path: str, obj: Mapping[str, Any], allowed: Iterable[str]) -> None:
        extra = sorted(set(obj) - set(allowed))
        for k in extra:
            self.warn(f"{path}.{k}" if path else k, f"unknown key (allowed: {', '.join(sorted(allowed))})")


def _validate_item(v: _V, it: Any, path: str, dur: float, size: tuple[int, int] | None,
                   known_scenes: set[str] | None) -> None:
    if not isinstance(it, Mapping):
        v.err(path, "must be an object")
        return
    v.unknown(path, it, ITEM_KEYS)
    sid = it.get("id")
    if not isinstance(sid, str) or not SHOT_ID_RE.match(sid):
        v.err(f"{path}.id", "required: 1-48 chars of letters, digits, '_' or '-' (starting with a letter/digit)")
    t0, t1 = it.get("t0"), it.get("t1")
    if not _num(t0) or t0 < 0:
        v.err(f"{path}.t0", f"must be a number >= 0 (got {t0!r})")
    if not _num(t1):
        v.err(f"{path}.t1", f"must be a number (got {t1!r})")
    if _num(t0) and _num(t1):
        if t1 <= t0 + EPS:
            v.err(f"{path}.t1", f"must be greater than t0 ({t0})")
        if dur and t1 > dur + EPS:
            v.err(f"{path}.t1", f"{t1} is past the film end (dur {dur})")
    scene = it.get("scene")
    if not isinstance(scene, str) or not SCENE_ID_RE.match(scene):
        v.err(f"{path}.scene", f"must be 'kit:<kit>/<name>', 'lib:<name>' or 'custom:<name>' (got {scene!r})")
    elif known_scenes is not None and scene not in known_scenes:
        v.err(f"{path}.scene", f"unknown scene {scene!r}")
    res = it.get("res")
    if res is not None:
        if not (isinstance(res, (list, tuple)) and len(res) == 2 and all(_int(x) and 16 <= x <= 7680 for x in res)):
            v.err(f"{path}.res", f"must be null or [w, h] integers in 16..7680 (got {res!r})")
        elif size:
            fa, ra = size[0] / size[1], res[0] / res[1]
            if abs(fa - ra) / fa > 0.02:
                v.warn(f"{path}.res", f"aspect {res[0]}x{res[1]} differs from the film {size[0]}x{size[1]}; it will be stretched")
    if "params" in it and not isinstance(it["params"], Mapping):
        v.err(f"{path}.params", "must be an object")
    if "z" in it and it["z"] is not None and not _num(it["z"]):
        v.err(f"{path}.z", "must be a number")
    if "upscale" in it and it["upscale"] not in ("pixel", "smooth"):
        v.err(f"{path}.upscale", "must be 'pixel' or 'smooth'")


def _windows(film: Mapping[str, Any], shots: list[Mapping[str, Any]]) -> list[tuple[str, str, float, float]]:
    """(from, to, t, t1) of transitions with a valid window (defaults filled like the runtime does)."""
    by_id = {s.get("id"): s for s in shots if isinstance(s, Mapping)}
    out = []
    for tr in film.get("transitions") or []:
        if not isinstance(tr, Mapping):
            continue
        a, b = tr.get("from"), tr.get("to")
        if a not in by_id or b not in by_id:
            continue
        d = tr.get("dur", 0)
        d = float(d) if _num(d) and d >= 0 else 0.0
        t = tr.get("t")
        if not _num(t):
            to_t0 = by_id[b].get("t0")
            t = max(0.0, float(to_t0) - d / 2) if _num(to_t0) else 0.0
        out.append((a, b, float(t), float(t) + d))
    return out


def validate_film(film: Any, *, known_scenes: Iterable[str] | None = None,
                  known_transitions: Iterable[str] | None = None,
                  known_assets: Iterable[str] | None = None) -> list[FilmIssue]:
    """Validate a film dict. ``known_*`` (optional) turn unknown scene/transition/asset names into errors."""
    v = _V()
    if not isinstance(film, Mapping):
        v.err("", "film must be a JSON object")
        return v.issues
    scenes_set = set(known_scenes) if known_scenes is not None else None
    trans_set = set(known_transitions) if known_transitions is not None else None
    v.unknown("", film, TOP_KEYS)

    if film.get("version", 1) != 1:
        v.err("version", f"must be 1 (got {film.get('version')!r})")
    fps = film.get("fps", 30)
    if not _int(fps) or not 1 <= fps <= 120:
        v.err("fps", f"must be an integer 1..120 (got {fps!r})")
    size = film.get("size", [1920, 1080])
    size_ok = isinstance(size, (list, tuple)) and len(size) == 2 and all(_int(x) and 64 <= x <= 7680 for x in size)
    if not size_ok:
        v.err("size", f"must be [w, h] integers in 64..7680 (got {size!r})")
    elif size[0] % 2 or size[1] % 2:
        v.err("size", "width and height must be even (H.264 4:2:0)")
    wh = (int(size[0]), int(size[1])) if size_ok else None
    dur_raw = film.get("dur")
    dur = float(dur_raw) if _num(dur_raw) and 0 < dur_raw <= 1800 else 0.0
    if not dur:
        v.err("dur", f"must be a number in (0, 1800] seconds (got {dur_raw!r})")
    if "seed" in film and not _int(film["seed"]):
        v.err("seed", "must be an integer")
    if "title" in film and not isinstance(film["title"], str):
        v.err("title", "must be a string")
    if "background" in film and not isinstance(film["background"], str):
        v.err("background", "must be a CSS colour string")

    for i, f in enumerate(film.get("fonts") or []):
        p = f"fonts[{i}]"
        if not isinstance(f, Mapping):
            v.err(p, "must be an object {family, src, weight?, style?}")
            continue
        v.unknown(p, f, {"family", "src", "weight", "style", "stretch"})
        if not isinstance(f.get("family"), str) or not f.get("family", "").strip():
            v.err(f"{p}.family", "required non-empty string")
        prob = _rel_path_problem(f.get("src"))
        if prob:
            v.err(f"{p}.src", prob)
        wgt = f.get("weight")
        if wgt is not None and not (_int(wgt) and 1 <= wgt <= 1000) and not (isinstance(wgt, str) and re.match(r"^(\d{1,4})( \d{1,4})?$|^(normal|bold)$", wgt)):
            v.err(f"{p}.weight", f"must be 1..1000, 'normal', 'bold' or a range like '100 900' (got {wgt!r})")
        if f.get("style") not in (None, "normal", "italic", "oblique"):
            v.err(f"{p}.style", "must be normal, italic or oblique")
    if "fonts" in film and not isinstance(film["fonts"], list):
        v.err("fonts", "must be a list")

    assets = film.get("assets") or {}
    if not isinstance(assets, Mapping):
        v.err("assets", "must be an object {name: {type}}")
        assets = {}
    for name, a in assets.items():
        p = f"assets.{name}"
        if not ASSET_NAME_RE.match(str(name)):
            v.err(p, "asset names are lowercase letters, digits, '_' or '-' (max 48)")
        if not isinstance(a, Mapping):
            v.err(p, "must be an object")
            continue
        if a.get("type") not in ("image", "frames", "video"):
            v.err(f"{p}.type", f"must be image, frames or video (got {a.get('type')!r})")
    if known_assets is not None:
        missing = sorted(set(assets) - set(known_assets))
        for name in missing:
            v.err(f"assets.{name}", "no prepared media with this name")

    shots = film.get("shots")
    if not isinstance(shots, list) or not shots:
        v.err("shots", "must be a non-empty list")
        shots = []
    ids: dict[str, int] = {}
    for i, s in enumerate(shots):
        _validate_item(v, s, f"shots[{i}]", float(dur), wh, scenes_set)
        if isinstance(s, Mapping) and isinstance(s.get("id"), str):
            if s["id"] in ids:
                v.err(f"shots[{i}].id", f"duplicate id {s['id']!r} (also shots[{ids[s['id']]}])")
            ids.setdefault(s["id"], i)

    # transitions
    trs = film.get("transitions") or []
    if not isinstance(trs, list):
        v.err("transitions", "must be a list")
        trs = []
    by_id = {s["id"]: s for s in shots if isinstance(s, Mapping) and isinstance(s.get("id"), str)}
    for i, tr in enumerate(trs):
        p = f"transitions[{i}]"
        if not isinstance(tr, Mapping):
            v.err(p, "must be an object {from, to, type, t, dur, params}")
            continue
        v.unknown(p, tr, {"from", "to", "type", "t", "dur", "params", "note"})
        a, b = tr.get("from"), tr.get("to")
        if a not in by_id:
            v.err(f"{p}.from", f"{a!r} is not a shot id")
        if b not in by_id:
            v.err(f"{p}.to", f"{b!r} is not a shot id")
        if a == b and a is not None:
            v.err(p, "from and to must be different shots")
        typ = tr.get("type", "cut")
        if not isinstance(typ, str) or not typ:
            v.err(f"{p}.type", "must be a string")
        elif SCENE_ID_RE.match(typ):
            if trans_set is not None and typ not in trans_set:
                v.err(f"{p}.type", f"unknown transition {typ!r}")
        elif typ not in BUILTIN_TRANSITIONS:
            v.err(f"{p}.type", f"unknown built-in {typ!r} (built-ins: {', '.join(sorted(BUILTIN_TRANSITIONS))}; kits use 'kit:<kit>/<name>')")
        d = tr.get("dur", 0)
        if not _num(d) or d < 0 or d > 10:
            v.err(f"{p}.dur", f"must be a number in 0..10 s (got {d!r})")
            continue
        t = tr.get("t")
        if t is not None and (not _num(t) or t < 0):
            v.err(f"{p}.t", f"must be a number >= 0 (got {t!r})")
            continue
        if "params" in tr and not isinstance(tr["params"], Mapping):
            v.err(f"{p}.params", "must be an object")
        if a in by_id and b in by_id and a != b:
            fa, fb = by_id[a], by_id[b]
            if not all(_num(x) for x in (fa.get("t0"), fa.get("t1"), fb.get("t0"), fb.get("t1"))):
                continue
            t_ = float(t) if t is not None else max(0.0, fb["t0"] - d / 2)
            t1_ = t_ + d
            if dur and t1_ > dur + EPS:
                v.err(p, f"window {t_:.3f}-{t1_:.3f} s runs past the film end ({dur})")
            if d > 0 and (fa["t0"] > t_ + EPS or fa["t1"] < t_ - EPS):
                v.err(p, f"window {t_:.3f}-{t1_:.3f} s does not start inside shot {a!r} ({fa['t0']}-{fa['t1']})")
            if d > 0 and (fb["t1"] < t1_ - EPS or fb["t0"] > t1_ + EPS):
                v.err(p, f"window {t_:.3f}-{t1_:.3f} s does not end inside shot {b!r} ({fb['t0']}-{fb['t1']})")

    # coverage and overlaps
    wins = _windows(film, shots)
    spans = sorted((float(s["t0"]), float(s["t1"]), i) for i, s in enumerate(shots)
                   if isinstance(s, Mapping) and _num(s.get("t0")) and _num(s.get("t1")) and s["t1"] > s["t0"])
    cover = sorted([(a, b) for a, b, _ in spans] + [(w[2], w[3]) for w in wins if w[3] > w[2]])
    if dur and cover:
        fps_f = float(fps) if _num(fps) and fps > 0 else 30.0
        tol = 0.5 / fps_f
        reach = 0.0
        for a, b in cover:
            if a > reach + tol:
                v.err("shots", f"no shot covers {reach:.3f}-{a:.3f} s (frames there would be blank)")
            reach = max(reach, b)
        if reach < dur - tol:
            v.err("shots", f"no shot covers {reach:.3f}-{float(dur):.3f} s (frames there would be blank)")
    for x in range(len(spans)):
        for y in range(x + 1, len(spans)):
            a0, a1, i = spans[x]
            b0, b1, j = spans[y]
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo <= EPS:
                continue
            ia, ib = shots[i].get("id"), shots[j].get("id")
            inside = any({w[0], w[1]} == {ia, ib} and w[2] <= lo + EPS and w[3] >= hi - EPS for w in wins)
            if not inside:
                v.err(f"shots[{j}]", f"overlaps shots[{i}] ({ia!r}) at {lo:.3f}-{hi:.3f} s outside a transition window between them")

    ov = film.get("overlays") or []
    if not isinstance(ov, list):
        v.err("overlays", "must be a list")
        ov = []
    oids: set[str] = set()
    for i, o in enumerate(ov):
        _validate_item(v, o, f"overlays[{i}]", float(dur), wh, scenes_set)
        if isinstance(o, Mapping) and isinstance(o.get("id"), str):
            if o["id"] in oids:
                v.err(f"overlays[{i}].id", f"duplicate overlay id {o['id']!r}")
            oids.add(o["id"])

    fin = film.get("finish") or {}
    if not isinstance(fin, Mapping):
        v.err("finish", "must be an object {grain, vignette, bloom}")
    else:
        v.unknown("finish", fin, {"grain", "vignette", "bloom"})
        for k in ("grain", "vignette", "bloom"):
            if k in fin and (not _num(fin[k]) or not 0 <= fin[k] <= 1):
                v.err(f"finish.{k}", "must be a number in 0..1")

    for i, c in enumerate(film.get("cues") or []):
        p = f"cues[{i}]"
        if not isinstance(c, Mapping):
            v.err(p, "must be an object {t, sfx, gain_db?, align?}")
            continue
        v.unknown(p, c, {"t", "sfx", "gain_db", "align", "note"})
        if not _num(c.get("t")) or c["t"] < 0 or (dur and c["t"] > dur + EPS):
            v.err(f"{p}.t", f"must be a time within the film (got {c.get('t')!r})")
        if not isinstance(c.get("sfx"), str) or not c["sfx"]:
            v.err(f"{p}.sfx", "required sfx name")
        if "gain_db" in c and (not _num(c["gain_db"]) or not -40 <= c["gain_db"] <= 12):
            v.err(f"{p}.gain_db", "must be a number in -40..12")
        if c.get("align", "auto") not in CUE_ALIGN:
            v.err(f"{p}.align", f"must be one of {', '.join(CUE_ALIGN)}")

    for i, m in enumerate(film.get("music") or []):
        p = f"music[{i}]"
        if not isinstance(m, Mapping):
            v.err(p, "must be an object {bed, t0, t1} or {sting, t}")
            continue
        if "bed" in m:
            if not isinstance(m["bed"], str):
                v.err(f"{p}.bed", "must be a string")
            for k in ("t0", "t1"):
                if k in m and (not _num(m[k]) or m[k] < 0 or (dur and m[k] > dur + EPS)):
                    v.err(f"{p}.{k}", "must be a time within the film")
            if _num(m.get("t0")) and _num(m.get("t1")) and m["t1"] <= m["t0"]:
                v.err(f"{p}.t1", "must be greater than t0")
        elif "sting" in m:
            if not isinstance(m["sting"], str):
                v.err(f"{p}.sting", "must be a string")
            if not _num(m.get("t")) or m["t"] < 0 or (dur and m["t"] > dur + EPS):
                v.err(f"{p}.t", "must be a time within the film")
        else:
            v.err(p, "needs 'bed' (with t0/t1) or 'sting' (with t)")

    caps = film.get("captions") or []
    prev_end = -1.0
    for i, c in enumerate(caps if isinstance(caps, list) else []):
        p = f"captions[{i}]"
        if not isinstance(c, Mapping):
            v.err(p, "must be an object {t0, t1, text}")
            continue
        text = c.get("text")
        if not isinstance(text, str) or not text.strip():
            v.err(f"{p}.text", "required non-empty string")
        elif len(text) > 160:
            v.err(f"{p}.text", f"too long ({len(text)} chars, max 160); split it")
        t0, t1 = c.get("t0"), c.get("t1")
        if not (_num(t0) and _num(t1) and 0 <= t0 < t1 and (not dur or t1 <= dur + EPS)):
            v.err(p, f"t0/t1 must satisfy 0 <= t0 < t1 <= dur (got {t0!r}, {t1!r})")
            continue
        if t0 < prev_end - EPS:
            v.err(f"{p}.t0", f"overlaps the previous caption (ends {prev_end})")
        prev_end = float(t1)
        if isinstance(text, str):
            words = len(text.split())
            if words / max(t1 - t0, 1e-3) > 4.5:
                v.warn(p, f"{words} words in {t1 - t0:.2f} s is hard to read (> 4.5 words/s)")
    if "captions" in film and not isinstance(caps, list):
        v.err("captions", "must be a list")
    cs = film.get("caption_style")
    if cs is not None:
        if not isinstance(cs, Mapping):
            v.err("caption_style", "must be an object")
        else:
            v.unknown("caption_style", cs, {"font", "size", "weight", "color", "bg", "plate", "letterSpacing"})
            if "size" in cs and (not _num(cs["size"]) or cs["size"] < MIN_CAPTION_PX):
                v.err("caption_style.size", f"must be >= {MIN_CAPTION_PX} px (at a 1080 px short side)")

    safe = film.get("safe")
    if safe is not None:
        if not isinstance(safe, Mapping):
            v.err("safe", "must be an object {l, r, t, b}")
        else:
            for k in ("l", "r", "t", "b"):
                if k in safe and (not _num(safe[k]) or safe[k] < 0):
                    v.err(f"safe.{k}", "must be a number >= 0")
            if wh and all(_num(safe.get(k, 0)) for k in "lrtb") and (
                    safe.get("l", 0) + safe.get("r", 0) >= wh[0] or safe.get("t", 0) + safe.get("b", 0) >= wh[1]):
                v.err("safe", "leaves no usable area")
    kits = film.get("kits")
    if kits is not None and (not isinstance(kits, list) or not all(isinstance(k, str) and KIT_NAME_RE.match(k) for k in kits)):
        v.err("kits", "must be a list of kit names")
    qa = film.get("qa")
    if qa is not None and (not isinstance(qa, Mapping) or ("min_text_px" in qa and not _num(qa["min_text_px"]))):
        v.err("qa", "must be an object {min_text_px: number}")
    return v.issues


def errors_of(issues: Iterable[FilmIssue]) -> list[FilmIssue]:
    """Only the issues that block rendering."""
    return [i for i in issues if i.severity == "error"]


def normalize_film(film: Mapping[str, Any]) -> dict[str, Any]:
    """Deep copy with defaults filled the way the runtime reads them (does not validate)."""
    f = copy.deepcopy(dict(film))
    f.setdefault("version", 1)
    f.setdefault("fps", 30)
    f.setdefault("size", [1920, 1080])
    f.setdefault("seed", 0)
    f.setdefault("background", "#000")
    for key in ("fonts", "shots", "transitions", "overlays", "cues", "music", "captions"):
        f.setdefault(key, [])
    f.setdefault("assets", {})
    f.setdefault("finish", {})
    for s in [*f["shots"], *f["overlays"]]:
        if isinstance(s, dict):
            s.setdefault("res", None)
            s.setdefault("params", {})
    for tr in f["transitions"]:
        if isinstance(tr, dict):
            tr.setdefault("type", "cut")
            tr.setdefault("dur", 0)
            tr.setdefault("params", {})
    return f


def scene_ids(film: Mapping[str, Any]) -> set[str]:
    """Scene ids used by shots and overlays, plus non-built-in transition types."""
    out = {s.get("scene") for s in [*(film.get("shots") or []), *(film.get("overlays") or [])] if isinstance(s, Mapping)}
    out |= {tr.get("type") for tr in film.get("transitions") or [] if isinstance(tr, Mapping)
            and isinstance(tr.get("type"), str) and SCENE_ID_RE.match(tr["type"])}
    return {x for x in out if isinstance(x, str)}
