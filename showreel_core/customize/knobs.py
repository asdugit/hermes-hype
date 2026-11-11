"""Deterministic customization knobs: ``key=value`` tokens, settings defaults, tool/API fields.

``extract(text)`` pulls every ``key=value`` token (quotes allowed: ``title="ORBIT QUEST"``) out of a
``/showreel`` argument string and returns the remaining text for the normal option parser. ``normalise``
turns raw values into canonical ones (``accent=pink`` -> ``#FF5FA2``, ``music=playful`` -> ``comic_b``) and
reports friendly problems instead of raising. No LLM is involved anywhere in this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import vocab as V

#: knob -> (kind, help). Kinds: colour, palette, font, music, energy, bool, voice, speed, text, path, captions,
#: transitions, seconds, aspect, language.
KNOBS: dict[str, tuple[str, str]] = {
    "accent": ("colour", "accent colour: #RRGGBB or a name (pink, cyan, neon-green, gold...)"),
    "palette": ("palette", "named palette (" + ", ".join(V.PALETTES) + ") or a comma list of colours"),
    "bg": ("colour", "background colour"),
    "text": ("colour", "text colour on the stage"),
    "font": ("font", "display font from the kits' OFL set (Bangers, Fraunces, VT323, Space Grotesk, ...)"),
    "music": ("music", "music bed id (launch_a, comic_b, ...), a mood (playful, dark, calm, epic, chiptune, "
                       "synthwave, ...) or none"),
    "energy": ("energy", "calm | normal | high (narration pace, holds, transitions, music tempo)"),
    "narration": ("bool", "on | off (off = captions only)"),
    "voice": ("voice", "narration voice: a style (whisper, warm, deep, bright, playful, serious) or an Edge "
                       "voice name (en-US-AvaMultilingualNeural)"),
    "voice_speed": ("speed", "narration pace multiplier 0.5-2.0 (default: the style's pace)"),
    "title": ("text", "on-screen title"),
    "tagline": ("text", "tagline under the title"),
    "cta": ("text", "call to action on the end card"),
    "product": ("text", "product name (on screen and in the narration)"),
    "logo": ("path", "path to a logo image (PNG/SVG/JPG/WebP), shown as a corner bug"),
    "captions": ("captions", "on | off | bold | minimal | boxed"),
    "transitions": ("transitions", "auto | kit | cut | soft | punchy | fade"),
    "length": ("seconds", "film length in seconds (15-180)"),
    "aspect": ("aspect", "16:9 | 9:16 | both | 1:1"),
    "language": ("language", "narration + on-screen text language (es, fr, de, ja, Spanish, ...)"),
}
ALIASES = {
    "color": "accent", "colour": "accent", "accent_color": "accent", "accentcolor": "accent", "highlight": "accent",
    "colors": "palette", "colours": "palette", "scheme": "palette", "background": "bg", "bgcolor": "bg",
    "background_color": "bg", "fg": "text", "textcolor": "text", "text_color": "text", "foreground": "text",
    "typeface": "font", "fonts": "font", "bed": "music", "mood": "music", "track": "music", "song": "music",
    "pace": "energy", "tempo": "energy", "vibe_energy": "energy", "vo": "narration", "voiceover": "narration",
    "narrate": "narration", "speed": "voice_speed", "voicespeed": "voice_speed", "rate": "voice_speed",
    "narrator": "voice", "name": "product", "product_name": "product", "headline": "title", "subtitle": "tagline",
    "call_to_action": "cta", "calltoaction": "cta", "transition": "transitions", "cuts": "transitions",
    "caption": "captions", "subs": "captions", "subtitles": "captions", "lang": "language", "locale": "language",
    "duration": "length", "secs": "length", "format": "aspect", "brand": "logo", "logo_path": "logo",
}
#: keys the base option parser already understands (left in the text for it): seconds=, style=, mode=, ...
PASSTHROUGH = {"seconds", "style", "mode", "effort", "engine", "engine_3d"}
TEXT_LIMITS = {"title": 48, "tagline": 90, "cta": 60, "product": 40}

_TOKEN_RE = re.compile(
    r"(?<!\S)(--)?([A-Za-z][A-Za-z0-9_\-]*)=(\"[^\"]*\"|'[^']*'|\u201c[^\u201d]*\u201d|\S+)")
_FORCE = {"directed": "directed", "--directed": "directed", "direct:": "directed", "customize": "customize",
          "--customize": "customize", "customise": "customize", "--customise": "customize"}


@dataclass
class Extracted:
    """Result of :func:`extract`."""
    knobs: dict[str, str] = field(default_factory=dict)    # canonical key -> raw value (unquoted)
    rest: str = ""                                          # the text without knob tokens
    unknown: list[str] = field(default_factory=list)        # unknown keys as typed
    force: str = ""                                         # "directed" | "customize" | ""


def canonical(key: str) -> str:
    k = str(key or "").strip().lower().lstrip("-").replace("-", "_")
    return k if k in KNOBS else ALIASES.get(k, ALIASES.get(k.replace("_", ""), ""))


def _unquote(v: str) -> str:
    v = v.strip()
    for a, b in (('"', '"'), ("'", "'"), ("\u201c", "\u201d")):
        if len(v) >= 2 and v.startswith(a) and v.endswith(b):
            return v[1:-1]
    return v.rstrip(",;")


def extract(text: str | None) -> Extracted:
    """Pull ``key=value`` knob tokens (and a leading/trailing ``directed``/``customize`` word) out of ``text``."""
    s = str(text or "")
    out = Extracted()
    keep: list[str] = []
    pos = 0
    for m in _TOKEN_RE.finditer(s):
        key = m.group(2)
        low = key.lower().replace("-", "_")
        if low in PASSTHROUGH:
            continue                      # the base parser handles it; leave it in place
        keep.append(s[pos:m.start()])
        pos = m.end()
        can = canonical(key)
        if can:
            out.knobs[can] = _unquote(m.group(3))
        else:
            out.unknown.append(key)
    keep.append(s[pos:])
    words = " ".join("".join(keep).split()).split(" ") if "".join(keep).strip() else []
    for edge in (0, -1):
        if words and words[edge].lower().strip(",.;!") in _FORCE:
            out.force = _FORCE[words[edge].lower().strip(",.;!")]
            words.pop(edge)
    out.rest = " ".join(words)
    return out


def help_text() -> str:
    """One line per knob (for error replies, docs and the tool schema)."""
    return "\n".join(f"  {k}=  {h}" for k, (_kind, h) in KNOBS.items())


def unknown_message(keys: list[str]) -> str:
    names = ", ".join(f"'{k}'" for k in keys)
    return (f"Unknown setting {names} (ignored). Valid settings: {', '.join(KNOBS)}. "
            "Example: /showreel pixel accent=#00e5ff energy=high title=\"ORBIT QUEST\"")


def _bool(v: Any) -> bool | None:
    k = V._key(v)
    if k in ("on", "yes", "true", "1", "y", "enabled"):
        return True
    if k in ("off", "no", "false", "0", "n", "none", "mute", "disabled"):
        return False
    return None


def normalise(raw: dict[str, Any] | None, *, style: str = "", kits_root: Path | None = None,
              check_files: bool = True) -> tuple[dict[str, Any], list[str]]:
    """Canonical knob values + friendly problems (unusable values are dropped, never raised)."""
    out: dict[str, Any] = {}
    problems: list[str] = []
    for key0, val in (raw or {}).items():
        key = canonical(key0)
        if not key:
            problems.append(unknown_message([str(key0)]))
            continue
        kind = KNOBS[key][0]
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        sval = str(val).strip()
        bad = f"{key}={sval!r} is not valid ({KNOBS[key][1]}); ignored."
        if kind == "colour":
            c = V.colour(sval)
            if c:
                out[key] = c
            else:
                problems.append(bad)
        elif kind == "palette":
            if isinstance(val, dict):
                pal = {k: V.colour(v) for k, v in val.items() if k in ("accent", "accent2", "accent3", "bg", "text")}
                pal = {k: v for k, v in pal.items() if v}
            else:
                pal = V.palette(sval)
            if pal:
                out[key] = V.palette_name(sval) or pal if not isinstance(val, dict) else pal
            else:
                problems.append(bad)
        elif kind == "font":
            f = V.font(sval, kits_root) or V.font(V.FONT_MOODS.get(V._key(sval), ""), kits_root)
            if f:
                out[key] = f
            else:
                problems.append(f"font {sval!r} is not in the kits' font set; available: "
                                f"{', '.join(sorted(r['family'] for r in V.fonts(kits_root).values()))}.")
        elif kind == "music":
            b = V.music(sval, style=style)
            if b:
                out[key] = b
            else:
                problems.append(f"music {sval!r} is not a bed or mood; moods: {', '.join(sorted(V.MOODS))}; "
                                f"beds: {', '.join(sorted(V.beds()))}.")
        elif kind == "energy":
            e = V.choice(sval, V.ENERGIES, V.ENERGY_ALIASES)
            if e:
                out[key] = e
            else:
                problems.append(bad)
        elif kind == "bool":
            b = val if isinstance(val, bool) else _bool(sval)
            if b is None:
                problems.append(bad)
            else:
                out[key] = b
        elif kind == "voice":
            st = V.choice(sval, tuple(V.VOICE_STYLES), V.VOICE_STYLE_ALIASES)
            if st:
                out[key] = st
            elif re.fullmatch(r"[a-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z]+Neural", sval):
                out[key] = sval
            else:
                problems.append(bad)
        elif kind == "speed":
            try:
                out[key] = round(min(2.0, max(0.5, float(sval.rstrip("x")))), 3)
            except ValueError:
                problems.append(bad)
        elif kind == "text":
            t = " ".join(sval.split())[:TEXT_LIMITS.get(key, 80)]
            if t:
                out[key] = t
        elif kind == "path":
            p = Path(sval.strip("\"'")).expanduser()
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".avif"):
                problems.append(f"logo {sval!r} must be an image file (png, svg, jpg, webp); ignored.")
            elif check_files and not p.is_file():
                problems.append(f"logo file {sval!r} was not found; ignored.")
            else:
                out[key] = str(p.resolve()) if p.is_file() else str(p)
        elif kind == "captions":
            c = V.choice(sval, V.CAPTION_STYLES, V.CAPTION_ALIASES)
            if c:
                out[key] = c
            else:
                problems.append(bad)
        elif kind == "transitions":
            t = V.choice(sval, V.TRANSITION_FAMILIES, V.TRANSITION_ALIASES)
            if t:
                out[key] = t
            else:
                problems.append(bad)
        elif kind == "seconds":
            m = re.fullmatch(r"(\d{1,3})\s*(s|sec|secs|seconds?)?", sval.lower())
            if m and 15 <= int(m.group(1)) <= 180:
                out[key] = int(m.group(1))
            else:
                problems.append(bad)
        elif kind == "aspect":
            a = {"vertical": ["9:16"], "9:16": ["9:16"], "portrait": ["9:16"], "16:9": ["16:9"], "wide": ["16:9"],
                 "landscape": ["16:9"], "horizontal": ["16:9"], "both": ["16:9", "9:16"], "1:1": ["1:1"],
                 "square": ["1:1"]}.get(sval.lower())
            if a:
                out[key] = a
            else:
                problems.append(bad)
        elif kind == "language":
            lang = V.language(sval)
            if lang:
                out[key] = lang
            else:
                problems.append(f"language {sval!r} is not supported; use one of {', '.join(V.LANGUAGES)}.")
    return out, problems


def from_settings(value: Any) -> dict[str, str]:
    """Knob defaults from the plugin setting ``customize`` (``"accent=#ff4fa3 energy=high"`` or a mapping)."""
    if isinstance(value, dict):
        return {canonical(k): str(v) for k, v in value.items() if canonical(k)}
    return extract(str(value or "")).knobs
