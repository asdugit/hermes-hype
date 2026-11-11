"""Free-text customization of a preset: one small LLM call -> a schema-validated spec (customize/spec.py).

The model sees the preset's Quick film as a shot list (ids, types, kit scene, the words on screen), the declared
params of exactly those kit scenes (from KIT.md / kit.js via director.catalog), and the closed vocabularies
(palettes, moods/beds, fonts, energies, transitions). It answers with JSON only. The reply is parsed tolerantly,
validated and repaired; the deterministic keyword spec is the floor it merges over, so a weak model, a broken
reply or no model at all still yields a customized film.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import spec as S
from . import vocab as V

TEMPERATURE = 0.3
MAX_TOKENS = 1800
TIMEOUT_S = 90.0

INSTRUCTIONS = """You customize a Showreel preset film. The film already exists (shot list below); the user asked for \
changes in their own words. Reply with ONE small JSON object that matches the schema: only the keys the request \
needs, nothing else.

Rules:
- Change the look and feel, not the facts: never invent numbers, features, code or quotes. Session facts (STATS, \
CODE, DIFF, TERMINAL, PROBLEM, CALLOUT words) stay as they are.
- Colours: hex (#RRGGBB) in "theme" (accent = the one hero colour; accent2/accent3 support; bg = stage; text = type), \
or a palette name.
- "energy": high = faster and punchier, calm = slower and gentler.
- "music": a bed id or a mood from the lists.
- "shots": edit at most a few shots by id: "params" only with names listed for that scene; "text" rewrites words on \
screen (headline/label/title/tagline/cta/feature/boss_name...); "hold" adds (+) or trims (-) seconds; "remove": true \
drops a shot (never the TITLE or END shot).
- Story requests ("the villain is a swarm of bugs", "make it a heist") must show on screen: rewrite the words of 2-4 non-fact shots (HOOK/FEATURE/SCREEN/BEFORE_AFTER labels and headlines, END tagline) so a viewer sees the idea without the narration; keep each line short and keep the product's real feature names.
- "order" only if the user asks to rearrange.
- Set "restructure": true ONLY if the request needs a different film than this preset can make (another style or world \
midway, totally new scenes); then the user is offered a Directed film.
- "summary": one short line saying what you changed.
Answer directly with the JSON object only (no prose, no code fences)."""


def film_summary(film: dict[str, Any], *, wrapped: bool = False) -> list[dict[str, Any]]:
    """The preset film as the model sees it: id, type, scene, seconds and the words on screen."""
    rows = []
    for s in film.get("shots") or []:
        p = s.get("params") or {}
        d = p.get("data") if wrapped and isinstance(p.get("data"), dict) else p
        words = {k: str(d[k])[:80] for k in S.SHOT_TEXT_FIELDS if isinstance(d.get(k), str) and d[k].strip()}
        rows.append({"id": s["id"], "type": s["id"].split("_", 1)[-1].upper(), "scene": s.get("scene"),
                     "seconds": round(float(s["t1"]) - float(s["t0"]), 2), "words": words})
    return rows


def scene_catalog(film: dict[str, Any], kits_root: Path | None = None) -> tuple[dict[str, list[str]], str]:
    """(scene id -> declared param names, prompt text with the params of the scenes the film uses)."""
    used = sorted({str(s.get("scene")) for s in film.get("shots") or []})
    names: dict[str, list[str]] = {}
    lines: list[str] = []
    try:
        from ..director.catalog import build_catalog
        cat = build_catalog(kits_dir=kits_root) if kits_root else build_catalog()
        scenes = cat.scenes()
    except Exception:  # noqa: BLE001 - no catalog: params are not validated by name (still type/size checked)
        return {}, "(scene params unavailable)"
    for sid in used:
        info = scenes.get(sid)
        if info is None:
            continue
        names[sid] = list(info.params)
        src = " ".join((info.params_src or "").split())[:700]
        lines.append(f"- `{sid}`: {(info.describe or '')[:200]}\n  params: {src or ', '.join(info.params) or '(none)'}")
    return names, "\n".join(lines) or "(no kit params)"


def vocab_text(style: str) -> str:
    beds = V.beds()
    return "\n".join([
        "Palettes: " + ", ".join(f"{k} ({v['accent']}/{v['bg']})" for k, v in V.PALETTES.items()),
        "Music moods: " + ", ".join(sorted(V.MOODS)) + "; beds: " + ", ".join(
            f"{b['id']} ({b['bpm']:.0f} bpm, {b['title']})" for b in beds.values()),
        "Fonts: " + ", ".join(sorted(r["family"] for r in V.fonts().values())),
        "Energy: calm | normal | high. Transitions: " + " | ".join(V.TRANSITION_FAMILIES) +
        ". Captions: " + " | ".join(V.CAPTION_STYLES) + ". Voice styles: " + ", ".join(V.VOICE_STYLES) + ".",
        f"Preset style: {style}.",
    ])


def build_prompt(request: str, film: dict[str, Any], style: str, *, wrapped: bool = False,
                 kits_root: Path | None = None) -> tuple[str, dict[str, list[str]]]:
    names, params_text = scene_catalog(film, kits_root)
    body = (f"# User request\n{request.strip()[:800]}\n\n# Preset film ({style}, {float(film.get('dur') or 0):.1f} s)\n"
            f"{json.dumps(film_summary(film, wrapped=wrapped), ensure_ascii=False)}\n\n"
            f"# Scene params (KIT.md)\n{params_text}\n\n# Vocabulary\n{vocab_text(style)}")
    return body, names


def customize_spec(request: str, film: dict[str, Any], *, style: str, llm_call: Any = None, wrapped: bool = False,
                   kits_root: Path | None = None, log: Any = None) -> dict[str, Any]:
    """``{"spec", "source": llm|repaired|keywords, "fixes", "model", "seconds", "error"}`` for a request.

    ``llm_call`` is a story ``LlmCall`` (``instructions, input_text, json_schema, schema_name, temperature,
    max_tokens, timeout`` -> reply with ``.text``/``.error``), e.g. ``Host.story_call()``; ``None`` = keywords only.
    """
    rows = [{"id": s["id"], "type": s["id"].split("_", 1)[-1].upper(), "scene": s.get("scene"),
             "t0": s["t0"], "t1": s["t1"]} for s in film.get("shots") or []]
    floor = S.keywords(request, rows, style=style)
    floor, _ = S.validate(floor, rows, catalog=None, style=style)
    out: dict[str, Any] = {"spec": floor, "source": "keywords", "fixes": [], "model": "", "seconds": 0.0, "error": ""}
    if llm_call is None:
        return out
    body, names = build_prompt(request, film, style, wrapped=wrapped, kits_root=kits_root)
    t0 = time.monotonic()
    try:
        reply = llm_call(instructions=INSTRUCTIONS, input_text=body, json_schema=S.SCHEMA,
                         schema_name="showreel_customize", temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
                         timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - model trouble never blocks the film
        out.update(error=f"{type(exc).__name__}: {exc}", seconds=round(time.monotonic() - t0, 1))
        return out
    out["seconds"] = round(time.monotonic() - t0, 1)
    text = str(getattr(reply, "text", reply if isinstance(reply, str) else "") or "")
    out["model"] = str(getattr(reply, "model", "") or "")
    err = str(getattr(reply, "error", "") or "")
    raw = getattr(reply, "parsed", None)
    if not isinstance(raw, dict):
        raw, perr = S.parse_json(text)
        err = err or perr if raw is None else ""
    if raw is None:
        out["error"] = err or "empty reply"
        return out
    clean, fixes = S.validate(raw, rows, catalog=names or None, style=style)
    out["fixes"] = fixes
    out["raw"] = raw
    out["spec"] = S.merge(floor, clean)
    out["source"] = "repaired" if fixes else "llm"
    if log is not None:
        for f in fixes[:8]:
            log(f"customize repair: {f}")
    return out
