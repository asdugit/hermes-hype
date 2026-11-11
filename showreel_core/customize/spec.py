"""The customization spec: what a free-text request may change on a preset, its JSON schema, validation with
auto-repair, and the deterministic keyword reader that makes weak (or no) models still succeed.

Spec (every key optional; small on purpose)::

    {"theme": {"accent": "#FF4FA3", "accent2": "...", "accent3": "...", "bg": "...", "text": "...",
               "palette": "neon", "font": "Bangers"},
     "energy": "calm|normal|high", "music": "<bed id or mood>", "transitions": "auto|kit|cut|soft|punchy|fade",
     "captions": "on|off|bold|minimal|boxed", "voice": {"style": "whisper", "speed": 0.95},
     "text": {"title": "...", "tagline": "...", "cta": "...", "product": "..."},
     "shots": [{"id": "s03_feature", "params": {...kit params from KIT.md...}, "text": {"<field>": "..."},
                "hold": 0.8, "remove": false}],
     "order": ["s00_hook", "s01_title", ...],
     "restructure": false, "summary": "pink, playful, punchier ending"}
"""
from __future__ import annotations

import copy
import difflib
import json
import re
from typing import Any

from . import vocab as V

TOP = ("theme", "energy", "music", "transitions", "captions", "voice", "text", "shots", "order", "restructure",
       "summary")
TEXT_FIELDS = ("title", "tagline", "cta", "product")
#: shot data fields whose words a customization may rewrite (everything else is session fact).
SHOT_TEXT_FIELDS = ("title", "tagline", "label", "headline", "feature", "caption", "cta", "text", "sub", "eyebrow",
                    "boss_name", "pick_text", "say", "callout", "note", "kicker")
#: storyboard types that hold session facts: their numbers/code/verbatim text are never rewritten.
FACT_TYPES = ("STATS", "CODE", "DIFF", "TERMINAL", "PROBLEM", "CALLOUT")
MAX_SHOTS_PATCHED = 12
MAX_STR = 160
MAX_HOLD = 2.5

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "theme": {"type": "object", "additionalProperties": False, "properties": {
            "accent": {"type": "string"}, "accent2": {"type": "string"}, "accent3": {"type": "string"},
            "bg": {"type": "string"}, "text": {"type": "string"}, "palette": {"type": "string"},
            "font": {"type": "string"}}},
        "energy": {"type": "string", "enum": list(V.ENERGIES)},
        "music": {"type": "string"},
        "transitions": {"type": "string", "enum": list(V.TRANSITION_FAMILIES)},
        "captions": {"type": "string", "enum": list(V.CAPTION_STYLES)},
        "voice": {"type": "object", "additionalProperties": False, "properties": {
            "style": {"type": "string"}, "speed": {"type": "number"}}},
        "text": {"type": "object", "additionalProperties": False,
                 "properties": {k: {"type": "string"} for k in TEXT_FIELDS}},
        "shots": {"type": "array", "maxItems": MAX_SHOTS_PATCHED, "items": {
            "type": "object", "required": ["id"], "additionalProperties": False, "properties": {
                "id": {"type": "string"}, "params": {"type": "object"}, "text": {"type": "object"},
                "hold": {"type": "number"}, "remove": {"type": "boolean"}}}},
        "order": {"type": "array", "items": {"type": "string"}},
        "restructure": {"type": "boolean"},
        "summary": {"type": "string"},
    },
}


# ------------------------------------------------------------------------------------------- parsing

def parse_json(text: str) -> tuple[dict[str, Any] | None, str]:
    """The first JSON object in a model reply (code fences, prose and trailing commas tolerated)."""
    s = str(text or "")
    s = re.sub(r"```(?:json)?", "", s)
    start = s.find("{")
    if start < 0:
        return None, "no JSON object in the reply"
    stack: list[str] = []
    end, instr, esc = -1, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
            if not stack:
                end = i
                break
    # a reply cut off mid-object (token limit) is closed in reverse bracket order
    body = s[start:end + 1] if end > 0 else s[start:].rstrip().rstrip(",") + "".join(reversed(stack))
    for attempt in (body, re.sub(r",\s*([}\]])", r"\1", body), body.replace("'", '"')):
        try:
            obj = json.loads(attempt)
            if isinstance(obj, dict):
                return obj, ""
        except ValueError:
            continue
    return None, "the reply's JSON could not be parsed"


# ------------------------------------------------------------------------------------------- validation

def _str(v: Any, n: int = MAX_STR) -> str:
    return " ".join(str(v).split())[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _match_shot(ref: str, shots: list[dict[str, Any]]) -> str:
    """Shot id from an exact id, a scene type (``FEATURE``), a scene id or a near miss."""
    ids = [s["id"] for s in shots]
    if ref in ids:
        return ref
    r = str(ref or "").strip().lower()
    for s in shots:
        typ = str(s.get("type") or s["id"].split("_", 1)[-1]).lower()
        if r in (typ, str(s.get("scene", "")).lower(), str(s.get("scene", "")).split("/")[-1].lower()):
            return s["id"]
    if r in ("first", "opening", "intro", "start", "hook"):
        return ids[0] if ids else ""
    if r in ("last", "ending", "end", "finale", "outro", "closing"):
        return ids[-1] if ids else ""
    hit = difflib.get_close_matches(r, [i.lower() for i in ids], n=1, cutoff=0.75)
    return next((i for i in ids if i.lower() == hit[0]), "") if hit else ""


def _clean_params(params: Any, allowed: list[str] | None) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(params, dict):
        return {}, ["params must be an object"]
    out: dict[str, Any] = {}
    dropped: list[str] = []
    for k, v in params.items():
        k = str(k)
        if k.startswith("_") or k in ("theme", "data", "image", "image2", "media", "asset", "backdrop", "path"):
            dropped.append(k)
            continue
        if allowed is not None and k not in allowed and k not in ("accent", "phosphor"):
            dropped.append(k)
            continue
        if isinstance(v, str):
            v = v[:MAX_STR]
        elif isinstance(v, (list, dict)) and len(json.dumps(v, default=str)) > 1200:
            dropped.append(k)
            continue
        out[k] = v
    return out, dropped


def validate(raw: Any, shots: list[dict[str, Any]], *, catalog: dict[str, list[str]] | None = None,
             style: str = "") -> tuple[dict[str, Any], list[str]]:
    """A clean spec + the repairs made. Never raises; anything unusable is dropped with a note.

    ``shots`` = ``[{id, type, scene, t0, t1}]`` of the preset film; ``catalog`` = scene id -> declared params.
    """
    fixes: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["the customization was not an object; ignored"]
    spec: dict[str, Any] = {}
    for k in raw:
        if k not in TOP:
            fixes.append(f"dropped unknown key {k!r}")
    th = raw.get("theme") if isinstance(raw.get("theme"), dict) else {}
    if raw.get("palette") and "palette" not in th:            # weak models put it at the top level
        th = {**th, "palette": raw["palette"]}
        fixes.append("moved palette into theme")
    for k in ("accent", "bg", "font"):
        if raw.get(k) and k not in th:
            th = {**th, k: raw[k]}
            fixes.append(f"moved {k} into theme")
    theme: dict[str, Any] = {}
    for k, v in th.items():
        if k in ("accent", "accent2", "accent3", "bg", "text"):
            c = V.colour(v)
            if c:
                theme[k] = c
            else:
                fixes.append(f"theme.{k} {v!r} is not a colour; dropped")
        elif k == "palette":
            name = V.palette_name(v)
            if name:
                theme["palette"] = name
            elif V.palette(v):
                theme.update({kk: vv for kk, vv in V.palette(v).items() if kk not in theme})
            else:
                fixes.append(f"theme.palette {v!r} unknown; dropped")
        elif k == "font":
            f = V.font(v) or V.font(V.FONT_MOODS.get(V._key(v), ""))
            if f:
                theme["font"] = f
            else:
                fixes.append(f"theme.font {v!r} is not in the kits' font set; dropped")
        else:
            fixes.append(f"dropped theme.{k}")
    if theme:
        spec["theme"] = theme
    for key, allowed, aliases in (("energy", V.ENERGIES, V.ENERGY_ALIASES),
                                  ("transitions", V.TRANSITION_FAMILIES, V.TRANSITION_ALIASES),
                                  ("captions", V.CAPTION_STYLES, V.CAPTION_ALIASES)):
        if raw.get(key) not in (None, ""):
            val = V.choice(raw[key], allowed, aliases)
            if val:
                spec[key] = val
            else:
                fixes.append(f"{key} {raw[key]!r} not one of {list(allowed)}; dropped")
    if raw.get("music") not in (None, ""):
        bed = V.music(raw["music"], style=style)
        if bed:
            spec["music"] = bed
        else:
            fixes.append(f"music {raw['music']!r} is not a bed or mood; dropped")
    vo = raw.get("voice")
    if isinstance(vo, str):
        vo = {"style": vo}
        fixes.append("voice given as a string; read as voice.style")
    if isinstance(vo, dict):
        v2: dict[str, Any] = {}
        st = V.choice(vo.get("style"), tuple(V.VOICE_STYLES), V.VOICE_STYLE_ALIASES) if vo.get("style") else ""
        if st:
            v2["style"] = st
        try:
            if vo.get("speed") not in (None, ""):
                v2["speed"] = round(min(1.6, max(0.7, float(vo["speed"]))), 3)
        except (TypeError, ValueError):
            fixes.append("voice.speed is not a number; dropped")
        if v2:
            spec["voice"] = v2
    tx = raw.get("text") if isinstance(raw.get("text"), dict) else {}
    text = {k: _str(tx[k], 90) for k in TEXT_FIELDS if _str(tx.get(k), 90)}
    if text:
        spec["text"] = text
    # shots
    by_id = {s["id"]: s for s in shots}
    out_shots: list[dict[str, Any]] = []
    seen: set[str] = set()
    removed = 0
    for i, sp in enumerate(raw.get("shots") or [] if isinstance(raw.get("shots"), list) else []):
        if not isinstance(sp, dict):
            fixes.append(f"shots[{i}] is not an object; dropped")
            continue
        sid = _match_shot(str(sp.get("id") or sp.get("shot") or sp.get("type") or ""), shots)
        if not sid:
            fixes.append(f"shots[{i}] id {sp.get('id')!r} matches no shot; dropped")
            continue
        if sid != sp.get("id"):
            fixes.append(f"shots[{i}] id {sp.get('id')!r} read as {sid}")
        if sid in seen:
            fixes.append(f"shots[{i}] repeats {sid}; merged into the first")
        seen.add(sid)
        shot = by_id[sid]
        typ = str(shot.get("type") or "")
        clean: dict[str, Any] = {"id": sid}
        if sp.get("remove") is True:
            if typ in ("TITLE", "END") or removed + 1 > max(0, len(shots) - 4):
                fixes.append(f"kept {sid}: the title/end shots and at least 4 shots always stay")
            else:
                clean["remove"] = True
                removed += 1
        allowed = (catalog or {}).get(str(shot.get("scene") or "")) if catalog is not None else None
        params, dropped = _clean_params(sp.get("params") or {}, allowed)
        if dropped:
            fixes.append(f"{sid}: dropped params {dropped} (not in the scene's KIT.md params)")
        if params:
            clean["params"] = params
        st = sp.get("text") if isinstance(sp.get("text"), dict) else {}
        stext = {k: _str(v) for k, v in st.items() if k in SHOT_TEXT_FIELDS and _str(v)}
        if typ in FACT_TYPES:
            stext = {k: v for k, v in stext.items() if k in ("label", "headline", "caption", "kicker")}
        if stext:
            clean["text"] = stext
        if sp.get("hold") not in (None, ""):
            try:
                h = float(sp["hold"])
                if abs(h) > 0.05:
                    clean["hold"] = round(max(-0.6 * (float(shot["t1"]) - float(shot["t0"])), min(MAX_HOLD, h)), 3)
            except (TypeError, ValueError):
                fixes.append(f"{sid}: hold is not a number; dropped")
        if len(clean) > 1:
            out_shots.append(clean)
    if out_shots:
        spec["shots"] = out_shots[:MAX_SHOTS_PATCHED]
    order = raw.get("order")
    if isinstance(order, list) and order:
        ids = [_match_shot(str(x), shots) for x in order]
        ids = [i for i in dict.fromkeys(ids) if i]
        rest = [s["id"] for s in shots if s["id"] not in ids]
        full = ids + rest
        ends = [s["id"] for s in shots if s.get("type") == "END"]
        full = [i for i in full if i not in ends] + ends            # the end card stays last
        if full != [s["id"] for s in shots]:
            spec["order"] = full
    if raw.get("restructure") is True:
        spec["restructure"] = True
    if _str(raw.get("summary")):
        spec["summary"] = _str(raw.get("summary"), 200)
    return spec, fixes


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """``over`` wins key by key (theme/text/voice merge; shots merge by id)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in ("theme", "text", "voice") and isinstance(v, dict):
            out[k] = {**(out.get(k) or {}), **v}
        elif k == "shots":
            cur = {s["id"]: s for s in out.get("shots") or []}
            for s in v:
                cur[s["id"]] = {**cur.get(s["id"], {}), **s}
            out["shots"] = list(cur.values())
        else:
            out[k] = copy.deepcopy(v)
    return out


# ------------------------------------------------------------------------------------------- keywords

_FASTER = r"\b(faster|fast[- ]paced|quick(er)?|snappy|punchy|punchier|energetic|high[- ]energy|hype|intense|frantic)\b"
_SLOWER = r"\b(slower|slow|calm(er)?|chill|relaxed|gentle|laid[- ]back|unhurried|meditative)\b"
_ENDING = r"\b(ending|end card|finale|outro|last shot|close|finish)\b"


def keywords(text: str, shots: list[dict[str, Any]] | None = None, *, style: str = "") -> dict[str, Any]:
    """A spec read straight from the words (colours, palettes, energy, music mood, voice, captions, ending).

    It is the fallback when there is no model, and the floor the model's spec merges over.
    """
    t = " " + str(text or "").lower() + " "
    spec: dict[str, Any] = {}
    theme: dict[str, Any] = {}
    # palettes: strong names alone ("neon colours"), common words only with a noun ("warm palette")
    strong = {"neon", "neons", "cyberpunk", "synthwave", "vaporwave", "pastel", "pastels", "noir", "monochrome", "candy",
              "sunset"}
    for name in sorted(set(V.PALETTES) | set(V.PALETTE_ALIASES), key=len, reverse=True):
        pat = (rf"\b{re.escape(name)}\b" if name in strong else
               rf"\b{re.escape(name)}\s+(palette|colou?rs?|colou?r scheme|theme|tones?)\b")
        if re.search(pat, t):
            theme["palette"] = V.palette_name(name)
            break
    if "green phosphor" in t or "phosphor green" in t or re.search(r"\bhacker\b", t):
        theme["accent"] = V.COLOURS["phosphor"]
        theme.pop("palette", None) if style == "terminal" else None
    colour_hits = []
    for name in sorted(V.COLOURS, key=len, reverse=True):
        spaced = re.sub(r"(neon|hot|electric|sky|phosphor)(?=[a-z])", r"\1[ -]?", name)
        m = re.search(rf"\b{spaced}\b", t)
        if m and not any(m.start() >= a and m.end() <= b for a, b, _ in colour_hits):
            colour_hits.append((m.start(), m.end(), name))
    colour_hits.sort()
    named = [n for _, _, n in colour_hits if n not in ("night", "ocean", "forest", "midnight")]
    if named and "accent" not in theme:
        theme["accent"] = V.COLOURS[named[0]]
        if len(named) > 1:
            theme["accent2"] = V.COLOURS[named[1]]
    if re.search(r"\b(night|midnight|dark blue|nocturnal)\b", t) and "bg" not in theme:
        theme["bg"] = "#070B1A"
        if "accent" not in theme and "blue" in t:
            theme["accent"] = "#6FA8FF"
    if re.search(r"\b(light|bright|white) (background|bg|stage)\b", t):
        theme["bg"] = "#F7F5F0"
    for mood, fam in V.FONT_MOODS.items():
        if re.search(rf"\b{mood}\s+(font|type|typeface|lettering|titles?)\b", t):
            theme["font"] = fam
            break
    if theme:
        spec["theme"] = theme
    if re.search(_FASTER, t):
        spec["energy"] = "high"
    elif re.search(_SLOWER, t):
        spec["energy"] = "calm"
    for mood in sorted(V.MOODS, key=len, reverse=True):
        if re.search(rf"\b{mood}\b", t):
            spec["music"] = V.music(mood, style=style)
            break
    if re.search(r"\b(moody|brooding)\b", t) and "music" not in spec:
        spec["music"] = V.music("moody", style=style)
    voice_words = [(w, w) for w in V.VOICE_STYLES] + list(V.VOICE_STYLE_ALIASES.items())
    for word, st in sorted(voice_words, key=lambda x: len(x[0]), reverse=True):
        near = rf"\b{re.escape(word)}\b\W+(\w+\W+)?(narration|voice|vo|voiceover|narrator|delivery|read)"
        if re.search(near, t) or (st == "whisper" and word != "soft" and re.search(rf"\b{re.escape(word)}\b", t)):
            spec["voice"] = {"style": st}
            break
    if re.search(r"\b(no|without) (captions|subtitles)\b", t):
        spec["captions"] = "off"
    elif re.search(r"\b(big|bold|loud) (captions|subtitles)\b", t):
        spec["captions"] = "bold"
    if re.search(r"\b(hard cuts|no transitions|just cuts)\b", t):
        spec["transitions"] = "cut"
    elif re.search(r"\b(smooth|soft|dreamy) (transitions|cuts)\b", t):
        spec["transitions"] = "soft"
    if shots and re.search(_ENDING, t) and re.search(r"\b(punch|punchy|punchier|bigger|stronger|harder|louder|bang)", t):
        end = next((s for s in reversed(shots) if s.get("type") == "END"), shots[-1])
        spec["shots"] = [{"id": end["id"], "hold": -0.4}]
        spec.setdefault("transitions", "punchy")
    m = re.search(r"\btitle[d]?\s*(?:it|to|as|:)?\s*[\"\u201c']([^\"\u201d']{2,48})[\"\u201d']", str(text or ""), re.I)
    if m:
        spec["text"] = {"title": m.group(1)}
    if re.search(r"\b(playful|fun|cheerful|whimsical)\b", t) and "music" not in spec:
        spec["music"] = V.music("playful", style=style)
    return spec


def describe(spec: dict[str, Any]) -> str:
    """Short human summary of a spec (for progress lines and the result panel)."""
    bits: list[str] = []
    th = spec.get("theme") or {}
    if th.get("palette"):
        bits.append(f"{th['palette']} palette")
    for k in ("accent", "bg"):
        if th.get(k):
            bits.append(f"{k} {th[k]}")
    if th.get("font"):
        bits.append(f"font {th['font']}")
    for k in ("energy", "music", "transitions", "captions"):
        if spec.get(k):
            bits.append(f"{k} {spec[k]}")
    if (spec.get("voice") or {}).get("style"):
        bits.append(f"{spec['voice']['style']} voice")
    if spec.get("text"):
        bits.append("text: " + ", ".join(f"{k}={v!r}" for k, v in spec["text"].items()))
    n = len(spec.get("shots") or [])
    if n:
        bits.append(f"{n} shot edit(s)")
    if spec.get("order"):
        bits.append("reordered")
    return "; ".join(bits) or "no changes"
