"""Quick mode: Timeline -> film.json (SDK.md §2) using the scene kits.

Each :class:`TimelineScene` becomes one shot. The scene id is ``kit:<style>/<TYPE>`` when the style kit lists
that type in ``kits/<style>/kit.json`` ``"scenes"``, else ``kit:base/<TYPE>`` re-skinned with the style's theme
tokens (``params.theme = <style>``). ``TimelineScene.data`` is passed through as the shot params (the data
shapes of research/wp-e-story.md §2 are exactly what the kit scenes consume), plus:

* ``label`` (storyboard label), ``theme``, ``accent`` (project accent, only for kits that opt in with
  ``"accent": "project"`` in kit.json; too-dark accents are lifted until they read on a dark stage),
* ``_captions`` (captions are up during the shot: content lifts clear of the caption band),
* ``_sync`` (beat-aligned moments taken from the timeline cues, shot-local seconds: ``click``, ``pass``),
* ``_mute`` (sfx roles the shot must not emit because the timeline already places them on the beat).

Product media: every image dict in the data (``{path, w, h, ...}``) is registered as a film asset (``asset``
key added; ``path`` resolved against ``job_dir``) and returned as a source spec for ``build_job(assets=...)``.

Transitions: ``transition_in`` ``cut|match|push|wipe`` -> runtime transitions via kit.json ``"transitions"``
(``{"match": ["crossfade", 0.3], ...}``; null = hard cut). The two shots overlap by the transition window.

Cues: timeline cues are kept except those the kit scene emits itself in sync with its visuals (typing, the
FEATURE click, test passes, montage/plan ticks): those are *claimed* (dropped here) and, because the pipeline
mixes ``timeline.cues`` + page cues, also removed from ``timeline.cues`` when ``claim=True`` (the default).
The STATS drop ``hit`` stays on the timeline (music-synced); the scene's own hit is muted instead.

Speedrun mode adds the ``kit:type/speedrun-timer`` overlay (live session clock + splits) until the END shot.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
KITS_ROOT = REPO_ROOT / "kits"
DEFAULT_STYLE = "launch"
BASE_KIT = "base"
DEFAULT_TRANSITIONS: dict[str, Any] = {"cut": None, "match": ["crossfade", 0.3], "push": ["push-left", 0.5],
                                       "wipe": ["wipe", 0.6]}
DEFAULT_CAPTION_STYLE = {"font": "Geist", "size": 46, "weight": 600}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".avif"}
# timeline cue sfx the kit scenes emit themselves (frame-accurate), per scene type
CLAIMS: dict[str, set[str]] = {
    "CODE": {"type"}, "PROBLEM": {"type"}, "DIFF": {"type"},
    "TERMINAL": {"pass", "fail"}, "HOOK": {"type", "pass", "fail"}, "BEFORE_AFTER": {"pass", "fail"},
    "FEATURE": {"click"}, "PLAN": {"appear"}, "MONTAGE": {"type"}, "END": {"pass"},
}
# timeline cues that win over the scene's own (music-synced): the scene emits nothing for these
TIMELINE_WINS: dict[str, set[str]] = {"STATS": {"hit"}}
MIN_ACCENT_LUM = 0.2
ALL_TYPES = ["HOOK", "TITLE", "PROBLEM", "PLAN", "CODE", "DIFF", "TERMINAL", "MONTAGE", "SCREEN", "STATS",
             "BEFORE_AFTER", "CALLOUT", "END", "FEATURE", "SCROLL"]
# Built-in knowledge of kits that predate a kit.json "quick" block. kit.json {"quick": {...}} overrides these.
#   params: "flat" (data keys are the params; kits/base convention) | "wrapped" ({data, image, image2, media})
#   res: per-aspect drawing surface; claims: false = keep every timeline cue (the kit's own cues are unknown)
PROFILES: dict[str, dict[str, Any]] = {
    "pixel": {"scenes": ALL_TYPES, "params": "wrapped", "res": {"16:9": [480, 270], "9:16": [270, 480]},
              "claims": False, "background": "#0B0A12", "finish": {"grain": 0.0, "vignette": 0.12},
              "transitions": {"cut": None, "match": ["kit:pixel/screen-slide", 0.4], "push": ["kit:pixel/battle-swirl", 0.5],
                              "wipe": ["kit:pixel/iris", 0.6]},
              "caption_style": {"font": "Silkscreen", "size": 44, "weight": 400}},
}


# ----------------------------------------------------------------------------------------- helpers

def _as_dict(x: Any) -> dict[str, Any]:
    if isinstance(x, Mapping):
        return dict(x)
    if hasattr(x, "to_dict"):
        return x.to_dict()
    if is_dataclass(x) and not isinstance(x, type):
        return asdict(x)
    raise TypeError(f"expected a Timeline (dataclass or dict), got {type(x).__name__}")


def _type_name(t: Any) -> str:
    return str(getattr(t, "value", t))


def kit_meta(name: str, kits_root: Path | None = None) -> dict[str, Any]:
    """kits/<name>/kit.json merged over the built-in profile and its "quick" block ({} when unknown)."""
    p = Path(kits_root or KITS_ROOT) / name / "kit.json"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return {**PROFILES.get(name, {}), **meta, **(meta.get("quick") or {})}


def kit_exists(name: str, kits_root: Path | None = None) -> bool:
    return (Path(kits_root or KITS_ROOT) / name / "kit.js").is_file()


def scene_id(style: str, typ: str, kits_root: Path | None = None) -> str:
    """``kit:<style>/<TYPE>`` when the style kit defines the type, else ``kit:base/<TYPE>``."""
    meta = kit_meta(style, kits_root) if style != BASE_KIT else {}
    if typ in (meta.get("scenes") or []) and kit_exists(style, kits_root):
        return f"kit:{style}/{typ}"
    return f"kit:{BASE_KIT}/{typ}"


def _lum(hex6: str) -> float:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def readable_accent(value: str) -> str:
    """Normalise a project accent to #RRGGBB and lift it toward white until it reads on a dark stage."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", str(value or "").strip())
    if not m:
        return ""
    s = m.group(1)
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    rgb = [int(s[i:i + 2], 16) for i in (0, 2, 4)]
    for _ in range(12):
        hx = "".join(f"{c:02X}" for c in rgb)
        if _lum(hx) >= MIN_ACCENT_LUM:
            return "#" + hx
        rgb = [round(c + (255 - c) * 0.18) for c in rgb]
    return "#" + "".join(f"{c:02X}" for c in rgb)


class _Media:
    """Registers image dicts found in scene data as film assets."""

    def __init__(self, job_dir: Path | None, media_map: Mapping[str, str] | None):
        self.job_dir = Path(job_dir) if job_dir else None
        self.media_map = dict(media_map or {})
        self.by_src: dict[str, str] = {}
        self.assets: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []

    def _resolve(self, path: str) -> Path | None:
        if path in self.media_map:
            p = Path(self.media_map[path])
            return p if p.is_file() else None
        p = Path(path)
        cands = [p] if p.is_absolute() else ([self.job_dir / p] if self.job_dir else []) + [p]
        return next((c for c in cands if c.is_file()), None)

    def register(self, d: dict[str, Any]) -> dict[str, Any]:
        path = str(d.get("path") or "")
        if not path or d.get("asset"):
            return d
        src = self._resolve(path)
        if src is None:
            self.warnings.append(f"media not found: {path} (scene shows a placeholder)")
            return d
        key = str(src.resolve())
        name = self.by_src.get(key)
        if name is None:
            stem = re.sub(r"[^a-z0-9]+", "_", src.stem.lower()).strip("_")[:28] or "media"
            name = f"m{len(self.by_src)}_{stem}"
            self.by_src[key] = name
            self.assets[name] = {"src": key, "type": "image"}
        return {**d, "asset": name}

    def walk(self, x: Any) -> Any:
        if isinstance(x, dict):
            y = {k: self.walk(v) for k, v in x.items()}
            p = str(y.get("path") or "")
            if p and Path(p).suffix.lower() in IMAGE_EXT and y.get("kind", "image") == "image":
                y = self.register(y)
            return y
        if isinstance(x, list):
            return [self.walk(v) for v in x]
        return x


def _asset_of(x: Any) -> str | None:
    return x.get("asset") if isinstance(x, dict) and x.get("asset") else None


#: scene types that may carry the film's product image as ``params.backdrop`` (kits opt in with kit.json
#: ``"backdrop": true``): type-led scenes would otherwise be words on an empty stage.
BACKDROP_TYPES = ("TITLE", "STATS", "END", "CALLOUT", "PROBLEM", "PLAN")
_BACKDROP_ORDER = ("HOOK", "SCREEN", "FEATURE", "SCROLL", "BEFORE_AFTER")


def _image_dicts(x: Any) -> list[dict[str, Any]]:
    """Registered image dicts (with an ``asset``) inside scene data, depth first."""
    if isinstance(x, dict):
        out = [x] if x.get("asset") and str(x.get("kind", "image")) == "image" else []
        for v in x.values():
            out += _image_dicts(v)
        return out
    if isinstance(x, list):
        return [d for v in x for d in _image_dicts(v)]
    return []


def pick_backdrop(datas: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    """The film's product image for type-scene backdrops: the HOOK's image, else SCREEN/FEATURE/... (landscape
    images preferred: they read as a product screen), as ``{kind: 'image', asset, w, h, url?, page_title?}``."""
    found: list[tuple[int, int, dict[str, Any]]] = []
    for k, (typ, data) in enumerate(datas):
        rank = _BACKDROP_ORDER.index(typ) if typ in _BACKDROP_ORDER else len(_BACKDROP_ORDER)
        for d in _image_dicts(data):
            found.append((rank, k, d))
    if not found:
        return None
    found.sort(key=lambda r: (r[0], 0 if float(r[2].get("w") or 16) >= float(r[2].get("h") or 9) else 1, r[1]))
    d = found[0][2]
    keep = {k: d[k] for k in ("asset", "w", "h", "url", "page_title") if d.get(k) not in (None, "")}
    return {"kind": "image", **keep}


def _wrapped_shot(k: int, typ: str, t0: float, t1: float, sid: str, data: dict[str, Any], kit: Mapping[str, Any],
                  aspect: str | None, media: str | None = None) -> dict[str, Any]:
    """Shot for kits whose Quick types take {data, image, image2, media} (pixel). Every image is an ASSET NAME;
    ``media`` is the film's product image (scenes without their own image can still show the product)."""
    params: dict[str, Any] = {"data": data}
    if media:
        params["media"] = media
    first = _asset_of(data.get("image")) or _asset_of(data.get("hero")) or _asset_of(data.get("before"))
    if first:
        params["image"] = first
    if _asset_of(data.get("after")):
        params["image2"] = _asset_of(data.get("after"))
    shot: dict[str, Any] = {"id": f"s{k:02d}_{typ.lower()}", "t0": round(t0, 4), "t1": round(t1, 4), "scene": sid,
                            "params": params}
    res = (kit.get("res") or {}).get(str(aspect or "16:9"))
    if res:
        shot["res"] = list(res)
    return shot


def _transition(kind: str, kit: Mapping[str, Any]) -> tuple[str, float] | None:
    table = {**DEFAULT_TRANSITIONS, **(kit.get("transitions") or {})}
    v = table.get(kind or "cut")
    if not v:
        return None
    if isinstance(v, str):
        return v, 0.4
    return str(v[0]), float(v[1])


# ----------------------------------------------------------------------------------------- adapter

def film_from_timeline(timeline: Any, *, style: str | None = None, aspect: str | None = None,
                       job_dir: Path | str | None = None, preview: bool = False,
                       kits_root: Path | str | None = None, media_map: Mapping[str, str] | None = None,
                       claim: bool = True, product: Any = None, **_: Any) -> dict[str, Any]:
    """Timeline (dataclass or dict) -> ``{"film": film.json dict, "assets": {name: spec}, "scenes": {}}``.

    ``job_dir`` resolves relative media paths in the scene data; ``media_map`` maps data paths to files
    explicitly (tests/fixtures). ``claim`` removes the cues the kit scenes emit themselves from
    ``timeline.cues`` (see module doc). ``aspect`` is informational (size comes from the timeline).
    """
    kits_root = Path(kits_root) if kits_root else KITS_ROOT
    tl = _as_dict(timeline)
    style = str(style or tl.get("style") or DEFAULT_STYLE)
    if style != BASE_KIT and not kit_exists(style, kits_root) and style not in base_themes(kits_root):
        style = DEFAULT_STYLE
    kit = kit_meta(style, kits_root) if style != BASE_KIT else {}
    theme = str(kit.get("theme") or style)
    accent = readable_accent(tl.get("accent", "")) if kit.get("accent") == "project" else ""
    w, h = int(tl.get("w") or 1920), int(tl.get("h") or 1080)
    dur = float(tl["dur"])
    media = _Media(Path(job_dir) if job_dir else None, media_map)
    scenes = list(tl.get("scenes") or [])
    cues_in = [dict(c) for c in tl.get("cues") or []]

    def scene_at(t: float) -> int:
        for k, sc in enumerate(scenes):
            if float(sc["t0"]) <= t < float(sc["t1"]):
                return k
        return len(scenes) - 1 if scenes and t >= float(scenes[-1]["t0"]) else -1

    # cues: claimed by scenes vs kept; beat-aligned sync points for the scenes
    sync: dict[int, dict[str, float]] = {}
    mute: dict[int, set[str]] = {}
    kept: list[dict[str, Any]] = []
    claimed = 0
    for c in cues_in:
        k = scene_at(float(c["t"]))
        typ = _type_name(scenes[k]["type"]) if k >= 0 else ""
        sfx = str(c.get("sfx"))
        if k >= 0 and kit.get("claims", True) and sfx in TIMELINE_WINS.get(typ, set()):
            mute.setdefault(k, set()).add(sfx)
        if k >= 0 and kit.get("claims", True) and sfx in CLAIMS.get(typ, set()):
            if sfx in ("click", "pass") and sfx not in sync.get(k, {}):
                sync.setdefault(k, {})[sfx] = round(float(c["t"]) - float(scenes[k]["t0"]), 3)
            claimed += 1
            continue
        kept.append(c)
    if claim and claimed and not isinstance(timeline, Mapping) and hasattr(timeline, "cues"):
        keep_ids = {(round(float(c["t"]), 4), str(c["sfx"])) for c in kept}
        timeline.cues = [c for c in timeline.cues if (round(float(c.t), 4), str(c.sfx)) in keep_ids]

    shots: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    datas = []
    for sc in scenes:
        d = media.walk(dict(sc.get("data") or {}))
        d.pop("story_index", None)
        datas.append((_type_name(sc["type"]), d))
    product_image = pick_backdrop(datas)
    backdrop = product_image if kit.get("backdrop") else None
    for k, sc in enumerate(scenes):
        typ = _type_name(sc["type"])
        t0, t1 = float(sc["t0"]), float(sc["t1"])
        data = datas[k][1]
        sid = scene_id(style, typ, kits_root)
        if kit.get("params") == "wrapped" and not sid.startswith(f"kit:{BASE_KIT}/"):
            shots.append(_wrapped_shot(k, typ, t0, t1, sid, data, kit, aspect or tl.get("aspect"),
                                       media=(product_image or {}).get("asset")))
            if sc.get("captions"):
                captions += [{"t0": round(float(c["t0"]), 3), "t1": round(float(c["t1"]), 3), "text": str(c["text"])}
                             for c in sc["captions"] if str(c.get("text", "")).strip()]
            continue
        params = data
        params["theme"] = theme
        if backdrop and typ in BACKDROP_TYPES and not _image_dicts(params):
            params["backdrop"] = dict(backdrop)
        if sc.get("label") and not params.get("label"):
            params["label"] = sc["label"]
        if accent:
            params["accent"] = accent
        caps = [c for c in sc.get("captions") or [] if str(c.get("text", "")).strip()]
        if caps:
            params["_captions"] = True
            captions += [{"t0": round(float(c["t0"]), 3), "t1": round(float(c["t1"]), 3), "text": str(c["text"])} for c in caps]
        if k in sync:
            params["_sync"] = sync[k]
        if k in mute:
            params["_mute"] = sorted(mute[k])
        shots.append({"id": f"s{k:02d}_{typ.lower()}", "t0": round(t0, 4), "t1": round(t1, 4),
                      "scene": sid, "params": params})
    # transitions: overlap neighbours by the window, centred on the cut
    for k in range(1, len(shots)):
        tr = _transition(str(scenes[k].get("transition_in") or "cut"), kit)
        if not tr:
            continue
        name, d = tr
        a, b = shots[k - 1], shots[k]
        cut = b["t0"]
        d = round(min(d, 0.4 * (a["t1"] - a["t0"]), 0.4 * (b["t1"] - b["t0"])), 3)
        if d < 0.1:
            continue
        a["t1"] = round(cut + d / 2, 4)
        b["t0"] = round(cut - d / 2, 4)
        transitions.append({"from": a["id"], "to": b["id"], "type": name, "t": round(cut - d / 2, 4), "dur": d})

    overlays: list[dict[str, Any]] = []
    splits = [dict(s) for s in tl.get("splits") or []]
    if str(tl.get("mode")) == "speedrun" and splits:
        end_t0 = next((float(s["t0"]) for s in scenes if _type_name(s["type"]) == "END"), dur)
        o_t1 = max(1.0, end_t0)
        overlays.append({"id": "speedrun_hud", "t0": 0.0, "t1": round(o_t1, 4), "scene": "kit:type/speedrun-timer",
                         "params": {"theme": theme, **({"accent": accent} if accent else {}),
                                    "title": str(tl.get("title") or "Any%"),
                                    "total_s": max(float(s.get("session_t") or 0) for s in splits),
                                    "splits": [{"label": s.get("label", ""), "session_t": float(s.get("session_t") or 0),
                                                "film_t": float(s.get("film_t") or 0)} for s in splits
                                               if float(s.get("film_t") or 0) < o_t1]}})

    kits = [kname for kname in (style,) if kname != BASE_KIT and kit_exists(kname, kits_root)]
    finish = dict(kit.get("finish") or {"grain": 0.03, "vignette": 0.2})
    if preview:
        finish["grain"] = 0.0
    film: dict[str, Any] = {
        "version": 1, "fps": int(tl.get("fps") or 30), "size": [w, h], "dur": round(dur, 4),
        "seed": int(tl.get("seed") or 1), "title": str(tl.get("title") or ""),
        "background": str(kit.get("background") or "#0A0B0D"),
        "fonts": [], "kits": kits,
        "assets": {n: {"type": spec["type"]} for n, spec in media.assets.items()},
        "shots": shots, "transitions": transitions, "overlays": overlays,
        "finish": finish,
        "cues": [{"t": round(float(c["t"]), 4), "sfx": str(c["sfx"]), "gain_db": float(c.get("gain_db", 0.0)),
                  "align": str(c.get("align") or "auto")} for c in kept],
        "captions": captions,
        "caption_style": dict(kit.get("caption_style") or DEFAULT_CAPTION_STYLE),
        "meta": {"mode": "quick", "style": style, "theme": theme, "film_mode": str(tl.get("mode") or "product"),
                 "aspect": aspect or tl.get("aspect"), "accent": accent, "claimed_cues": claimed,
                 "warnings": media.warnings},
    }
    render = kit.get("render")
    if isinstance(render, Mapping) and render.get("post"):
        # style post chain (e.g. terminal's CRT) -> pipeline RenderSpec(post=, post_params=)
        film["render"] = {"post": str(render["post"]), "post_params": dict(render.get("post_params") or {})}
    return {"film": film, "assets": media.assets, "scenes": {}}


def base_themes(kits_root: Path | str | None = None) -> list[str]:
    """Theme names kits/base registers itself (kits/base/kit.json "themes")."""
    return list(kit_meta(BASE_KIT, Path(kits_root) if kits_root else None).get("themes") or [])


# aliases the pipeline probes for
timeline_to_film = film_from_timeline
quick_film = film_from_timeline
