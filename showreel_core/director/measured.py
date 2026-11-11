"""Measured review: score a film from measurements when the model cannot see (or to back the critic).

Without vision the Director must not ask a model to judge pictures. Instead every rubric axis is estimated from
things the engine can measure in the keyframes and the film script:

- product_clarity   <- pixel-measured visibility, hero-size share and solidity of the product (prominence pass)
- composition       <- products cut by the frame edge, safe-area / overlap QA findings
- beauty_craft      <- runtime share on polished kit / Blender scenes vs first-draft custom code and fallbacks;
                       frames that are nearly flat (one colour) or frozen
- story_clarity     <- hook by 2 s, the film ends on a lockup / END card, a sensible shot rhythm
- legibility        <- layout QA (clipped / overlapping / too small text)
- style_coherence   <- number of distinct visual worlds (1-2 reads as one film; 4+ as a sampler)
- transition_quality<- act changes carried by real transitions (kit / motivated types) instead of hard cuts
plus a motion and variety check over consecutive keyframes (a shot whose keyframes do not change is a still).

The result is a normal critique dict (scores, per-shot issues with fixes, strengths, verdict) flagged
``measured: true``, so the rest of the engine (gate, revisions, best-of) works unchanged. Scores are
deliberately conservative: a measured 7 means "nothing measurably wrong", not "beautiful".
"""
from __future__ import annotations

import io
import itertools
from collections.abc import Sequence
from typing import Any

from .types import RUBRIC_KEYS

LOCKUP_SCENES = ("kit:type/end-lockup", "kit:cinematic/lockup", "kit:type/cta")


def _kit_of(scene: str) -> str:
    s = str(scene)
    if s.startswith(("kit:", "blender:")):
        return s.split(":", 1)[1].split("/")[0]
    return s.split(":", 1)[0]


def frame_stats(images: Sequence[bytes]) -> list[dict[str, float]]:
    """Per keyframe: luminance spread (flatness) and mean; [] when PIL is unavailable."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return []
    out = []
    for b in images:
        try:
            im = Image.open(io.BytesIO(b)).convert("L").resize((96, 54))
        except Exception:  # noqa: BLE001 - an undecodable frame counts as flat
            out.append({"std": 0.0, "mean": 0.0})
            continue
        st = ImageStat.Stat(im)
        out.append({"std": float(st.stddev[0]), "mean": float(st.mean[0])})
    return out


def frame_change(a: bytes, b: bytes) -> float | None:
    """Mean absolute difference (0..1) between two keyframes at low resolution."""
    try:
        from PIL import Image, ImageChops, ImageStat
        ia = Image.open(io.BytesIO(a)).convert("L").resize((96, 54))
        ib = Image.open(io.BytesIO(b)).convert("L").resize((96, 54))
        return float(ImageStat.Stat(ImageChops.difference(ia, ib)).mean[0]) / 255.0
    except Exception:  # noqa: BLE001
        return None


def review(film: dict[str, Any], plan: dict[str, Any], frames: Sequence[Any], images: Sequence[bytes], *,
           prom: Any = None, measures: Sequence[Any] = (), qa: Sequence[dict[str, Any]] = (),
           fallbacks: dict[str, str] | None = None, product: bool = True,
           requirements: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """A critique dict computed from measurements only (see module doc)."""
    shots = film.get("shots") or []
    dur = float(film.get("dur") or 1.0) or 1.0
    issues: list[dict[str, Any]] = []
    strengths: list[str] = []
    notes: dict[str, list[str]] = {}

    def issue(shot: str, sev: int, text: str, fix: str) -> None:
        issues.append({"shot": shot, "target": "film", "severity": sev, "issue": f"MEASURED: {text}", "fix": fix})
        notes.setdefault(shot, []).append(text)

    # product
    if product and prom is not None:
        vis, hero = float(prom.visible_share), float(prom.hero_share)
        clar = [float(d.get("clarity", 1.0)) for d in prom.per_shot.values() if d.get("visible")]
        c = sum(clar) / len(clar) if clar else 0.0
        pc = 2.0 + 4.0 * min(1.0, vis / 0.8) + 3.0 * min(1.0, hero / 0.5) + 1.0 * min(1.0, c / 0.7)
        for sid, d in prom.per_shot.items():
            if d.get("visible", 0) == 0 and any(p.get("id") == sid and p.get("product_visible")
                                                for p in plan.get("shots") or []):
                issue(sid, 3, f"the product is not on screen in shot {sid}", "pass the product media to the shot")
        if vis >= 0.75 and hero >= 0.4:
            strengths.append(f"product on screen in {vis:.0%} of keyframes, hero-sized in {hero:.0%}")
    elif product:
        pc = 6.0          # not measurable (e.g. all-3D film): neutral
    else:
        pc = 7.0
    # composition: edge crops + safe area / overlap QA
    kinds: dict[str, int] = {}
    for q in qa:
        kinds[str(q.get("kind"))] = kinds.get(str(q.get("kind")), 0) + 1
    crops = 0
    try:
        from . import prominence as pm
        crops = sum(n for _, n in pm.cropped(list(measures)).values()) if measures else 0
    except Exception:  # noqa: BLE001
        crops = 0
    comp = 8.0 - 0.6 * min(4, crops) - 0.5 * min(4, kinds.get("safe", 0) + kinds.get("overlap", 0))
    # craft: kit/blender share, custom code, fallbacks, flat or frozen frames
    t_kit = sum(float(s["t1"]) - float(s["t0"]) for s in shots if str(s["scene"]).startswith(("kit:", "blender:")))
    t_3d = sum(float(s["t1"]) - float(s["t0"]) for s in shots if str(s["scene"]).startswith("blender:"))
    craft = 5.0 + 2.0 * (t_kit / dur) + 0.6 * (t_3d / dur) - 0.7 * len(fallbacks or {})
    stats = frame_stats(images)
    flat = [f for f, s in zip(frames, stats, strict=False) if s["std"] < 6.0 and not getattr(f, "transition", False)]
    if flat:
        craft -= min(2.0, 0.5 * len(flat))
        for f in flat[:3]:
            issue(f.shot, 2, f"keyframe {f.cell} at {f.t:.1f}s is nearly one flat colour",
                  "check the shot renders its content at that time (asset loaded, not faded out)")
    by_shot: dict[str, list[int]] = {}
    for i, f in enumerate(frames):
        if not getattr(f, "transition", False):
            by_shot.setdefault(f.shot, []).append(i)
    frozen = []
    for sid, idx in by_shot.items():
        if len(idx) >= 2 and len(images) > max(idx):
            ch = [frame_change(images[a], images[b]) for a, b in itertools.pairwise(idx)]
            ch = [x for x in ch if x is not None]
            if ch and max(ch) < 0.004:
                frozen.append(sid)
    for sid in frozen[:3]:
        craft -= 0.5
        issue(sid, 1, f"shot {sid} barely moves between its keyframes", "add camera motion or animate the subject")
    # story
    first_t = None
    for s in shots:
        if any(p.get("id") == s["id"] and p.get("product_visible") for p in plan.get("shots") or []):
            first_t = float(s["t0"])
            break
    ends = any(str(o.get("scene")) in LOCKUP_SCENES and float(o.get("t1", 0)) >= dur - 0.5
               for o in film.get("overlays") or []) or (shots and str(shots[-1]["scene"]).endswith(("/END", "_end")))
    lens = [float(s["t1"]) - float(s["t0"]) for s in shots]
    story = 6.0 + (1.0 if first_t is not None and first_t <= 2.0 else -1.0) + (1.0 if ends else -1.5)
    if lens and (max(lens) > 0.7 * dur and len(lens) > 1 or min(lens) < 1.2):
        story -= 0.5
    met = [q for q in requirements if isinstance(q, dict)]
    if not ends:
        issue(shots[-1]["id"] if shots else "film", 2, "the film does not end on the product name + CTA",
              "add an end lockup overlay for the last 3-5 s")
    # legibility
    bad_text = kinds.get("clip", 0) + kinds.get("overlap", 0) + kinds.get("small_text", 0)
    leg = 8.0 - 0.6 * min(6, bad_text)
    if bad_text:
        q = next(x for x in qa if str(x.get("kind")) in ("clip", "overlap", "small_text"))
        issue(str(q.get("shot") or "film"), 2, f"{bad_text} layout QA text finding(s), e.g. {q.get('msg')}",
              "shorten the text or move it inside the safe area")
    # coherence
    worlds = {_kit_of(s["scene"]) for s in shots} - {"type"}
    coh = 8.0 - 0.8 * max(0, len(worlds) - 2)
    # transitions
    cuts = 0
    trans = {(t.get("from"), t.get("to")): t for t in film.get("transitions") or []}
    for a, b in itertools.pairwise(shots):
        if _kit_of(a["scene"]) != _kit_of(b["scene"]) and (a["id"], b["id"]) not in trans:
            cuts += 1
    kit_tr = sum(1 for t in trans.values() if str(t.get("type", "")).startswith("kit:"))
    tq = 6.5 + 0.4 * min(3, kit_tr) - 1.0 * cuts
    scores = {"product_clarity": pc, "composition": comp, "beauty_craft": craft, "story_clarity": story,
              "legibility": leg, "style_coherence": coh, "transition_quality": tq}
    scores = {k: round(max(1.0, min(8.5, float(scores[k]))), 1) for k in RUBRIC_KEYS}
    shot_rows = []
    for s in shots:
        n = notes.get(s["id"], [])
        shot_rows.append({"id": s["id"], "score": round(max(1.0, min(8.5, 7.0 - 1.2 * len(n))), 1),
                          "note": "; ".join(n)[:200]})
    if t_kit / dur >= 0.9:
        strengths.append("built from polished kit/3D scenes end to end")
    if ends:
        strengths.append("ends on the product name and call to action")
    return {"scores": scores, "shots": shot_rows, "frames": [], "requirements": list(met),
            "per_shot_issues": issues[:10], "strengths": strengths,
            "verdict": "measured review (no vision): " + ", ".join(f"{k} {v:g}" for k, v in scores.items()),
            "measured": True}
