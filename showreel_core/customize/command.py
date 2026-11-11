"""Customization on every surface: the ``/showreel`` parser hook, the ``showreel_render`` tool, the CLI and the
Desktop API all end in :func:`set_customize` on an ``Options`` (persisted in ``options.hints["customize"]``)::

    {"preset": "pixel", "text": "make the boss a giant bug", "knobs": {"accent": "#00E5FF", ...},
     "route": "customize" | "directed" | "quick", "why": "..."}

The pipeline hook (customize/hook.py) reads it back from the job.
"""
from __future__ import annotations

import json
from typing import Any

from . import knobs as K
from .route import route

HINT = "customize"
#: tool schema additions (merged into ``showreel_render``'s schema by :func:`extend_schema`)
TOOL_PROPS: dict[str, Any] = {
    "customize": {"type": "string", "description": (
        "Free-text customization of the chosen preset (style), e.g. 'pink and playful with a punchier ending'. "
        "Keeps the preset and changes its look, words, music and pacing. Use 'direction' instead for a film unlike "
        "any preset.")},
    "knobs": {"type": "object", "description": "Deterministic preset knobs (no model needed): " + "; ".join(
        f"{k}: {h}" for k, (_kind, h) in K.KNOBS.items()),
        "properties": {k: ({"type": "boolean"} if kind == "bool" else {"type": "number"} if kind in ("speed", "seconds")
                           else {"type": "string"}) for k, (kind, _h) in K.KNOBS.items()},
        "additionalProperties": False},
}


def get(opts: Any) -> dict[str, Any]:
    """The customization stored on an Options (``{}`` when none)."""
    h = getattr(opts, "hints", None) or {}
    c = h.get(HINT) if isinstance(h, dict) else None
    return dict(c) if isinstance(c, dict) else {}


def _store(opts: Any, data: dict[str, Any]) -> None:
    if not isinstance(opts.hints, dict):
        opts.hints = {}
    data = {k: v for k, v in data.items() if v not in (None, "", {}, [])}
    if data:
        opts.hints[HINT] = data
    else:
        opts.hints.pop(HINT, None)


def _explicit(opts: Any, name: str) -> None:
    if name not in opts.explicit:
        opts.explicit.append(name)


def apply_knobs(opts: Any, knobs: dict[str, Any]) -> None:
    """Knobs that map onto existing Options fields (length, aspect, narration, voice_speed, product, language)."""
    if "length" in knobs:
        opts.seconds = int(knobs["length"])
        _explicit(opts, "seconds")
    if "aspect" in knobs:
        opts.aspects = list(knobs["aspect"])
        _explicit(opts, "aspects")
    if "narration" in knobs:
        opts.voice = bool(knobs["narration"])
        _explicit(opts, "voice")
    if "voice_speed" in knobs:
        opts.voice_speed = float(knobs["voice_speed"])
    if knobs.get("product"):
        opts.brief = {**(opts.brief or {}), "name": knobs["product"]}
    if knobs.get("tagline") and not (opts.brief or {}).get("one_liner"):
        opts.brief = {**(opts.brief or {}), "one_liner": knobs["tagline"]}


def set_customize(opts: Any, *, text: str = "", knobs: dict[str, Any] | None = None, preset_named: bool | None = None,
                  force: str = "", styles: set[str] | None = None) -> tuple[Any, list[str]]:
    """Attach a customization (free text and/or raw knobs) to ``opts`` and route it. Returns (opts, messages).

    ``preset_named``: the user picked the preset explicitly (None = infer from ``opts.explicit``/hints).
    Free text that routes to Directed becomes ``opts.direction`` (with the preset as the starting style).
    """
    msgs: list[str] = []
    cur = get(opts)
    clean, problems = K.normalise(knobs or {}, style=opts.style)
    msgs += problems
    merged = {**(cur.get("knobs") or {}), **clean}
    apply_knobs(opts, clean)
    text = " ".join(str(text or "").split())
    if preset_named is None:                 # named = an option word at the edges, not a word inside the sentence
        preset_named = bool({"style", "mode"} & set(opts.explicit))
    data = {**cur, "preset": opts.style, "knobs": merged}
    if text:
        how, why = route(text=text, preset_named=bool(preset_named), preset=opts.style, force=force, styles=styles)
        if how == "customize":
            data.update(text=core_text(text, (styles or set()) | {opts.style}), route="customize", why=why)
            if opts.direction.strip() == text:
                opts.direction = ""
            _explicit(opts, "style")
            msgs.append(f"Customizing the {opts.style} preset: \u201c{data['text']}\u201d.")
        else:
            data.update(route="directed", why=why)
            data.pop("text", None)
            opts.direction = text
            if preset_named:
                msgs.append(f"That goes beyond the {opts.style} preset ({why}): the Director makes it, starting from "
                            f"{opts.style}.")
    elif not opts.direction.strip() and not data.get("text"):
        data["route"] = "quick"
    if merged:
        msgs.append("Settings: " + ", ".join(f"{k}={v if not isinstance(v, list) else '+'.join(v)}"
                                             for k, v in merged.items()) + ".")
    if merged or data.get("text"):
        _store(opts, data)
    else:
        opts.hints.pop(HINT, None)
    return opts, msgs


_EDGE_WORDS = {"lore", "bts", "process", "making-of", "makingof", "speedrun", "any%", "vertical", "portrait", "both",
               "horizontal", "landscape", "wide", "square", "16:9", "9:16", "1:1", "mute", "muted", "silent",
               "no-voice", "captions-only", "preview", "draft", "final", "quick", "standard", "max", "blender"}


def core_text(text: str, styles: set[str] | None = None) -> str:
    """The request without the option words at its edges (``pixel ... 60 vertical`` -> ``...``)."""
    words = str(text or "").split()
    skip = set(_EDGE_WORDS) | {s.lower() for s in (styles or set())}

    def opt(w: str) -> bool:
        k = w.strip(",.;:!?\"'()").lower()
        return k in skip or k.rstrip("s").isdigit() or k in ("seconds", "secs", "sec")
    while words and opt(words[0]):
        words.pop(0)
    while words and opt(words[-1]):
        words.pop()
    out = " ".join(words).strip(" ,.;:-")
    return out or str(text or "").strip()


# ------------------------------------------------------------------------------------------- slash command

def refine_command(cmd: Any, text: str, *, styles: set[str], base: Any, reparse: Any) -> Any:
    """``commands.parse`` hook: pull ``key=value`` knobs out, re-parse the rest, route preset + text.

    ``reparse(text)`` is ``commands.parse`` itself (its own call of this hook sees no knobs and only routes).
    """
    if getattr(cmd, "action", "render") != "render":
        return cmd
    ex = K.extract(text)
    if ex.knobs or ex.unknown or ex.force:
        cmd = reparse(ex.rest)
        if cmd.action != "render":
            return cmd
    opts = cmd.options
    free = opts.direction or (str(get(opts).get("text") or "") if ex.force else "")
    if ex.force == "directed":
        cmd.messages = [m for m in cmd.messages if not m.startswith("Customizing the ")]
    if ex.unknown:
        cmd.messages.append(K.unknown_message(ex.unknown))
    # "a preset named": a style or mode at the edges ("/showreel pixel ..."); a style word inside the sentence
    # ("for launch day", "in pixel art") stays a Director hint
    preset_named = bool({"style", "mode"} & set(opts.explicit))
    _opts, msgs = set_customize(opts, text=free, knobs=ex.knobs, preset_named=preset_named, force=ex.force,
                                styles=styles)
    cmd.messages += msgs
    return cmd


# ------------------------------------------------------------------------------------------- tool / CLI / API

def extend_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Add ``customize`` + ``knobs`` to the ``showreel_render`` tool schema (in place; idempotent)."""
    props = schema.setdefault("parameters", schema).setdefault("properties", {}) if "parameters" in schema \
        else schema.setdefault("properties", {})
    for k, v in TOOL_PROPS.items():
        props.setdefault(k, v)
    return schema


def from_tool_args(opts: Any, args: dict[str, Any]) -> Any:
    """``showreel_render`` args -> customization on ``opts`` (messages are logged by the job)."""
    knobs = args.get("knobs") if isinstance(args.get("knobs"), dict) else {}
    text = str(args.get("customize") or "")
    if not (knobs or text):
        return opts
    opts, msgs = set_customize(opts, text=text, knobs=knobs, preset_named=bool(args.get("style") or args.get("mode")
                                                                              or text))
    if msgs:
        opts.hints.setdefault(HINT, {})["messages"] = msgs[:6]
    return opts


def add_cli_args(parser: Any) -> None:
    """``hermes showreel render --customize TEXT --set KEY=VALUE ...``."""
    parser.add_argument("--customize", default="", help="free-text customization of the chosen preset (--style)")
    parser.add_argument("--set", dest="knobs", action="append", default=[], metavar="KEY=VALUE",
                        help="preset knob (repeatable): " + ", ".join(K.KNOBS))


def from_cli_args(opts: Any, args: Any) -> Any:
    raw: dict[str, Any] = {}
    for item in getattr(args, "knobs", None) or []:
        # One --set item is ONE knob: split at the first "=" and keep the whole value (spaces included),
        # so `--set "title=TEMPO QUEST"` keeps both words. Several space-separated knobs in one item still work
        # when the first value is a single word (`--set "accent=#f36 energy=high"`).
        s = str(item).strip()
        key, sep, value = s.partition("=")
        can = K.canonical(key) if sep else ""
        if sep and can and not K._TOKEN_RE.search(value):
            raw[can] = K._unquote(value)
            continue
        ex = K.extract(s)
        if not ex.knobs and not ex.unknown:
            print(f"--set expects key=value, got {s!r}. " + K.unknown_message([s.split("=")[0] or s]))
            continue
        raw.update(ex.knobs)
        for u in ex.unknown:
            print(K.unknown_message([u]))
    text = str(getattr(args, "customize", "") or "")
    if not (raw or text):
        return opts
    opts, msgs = set_customize(opts, text=text, knobs=raw, preset_named=True)
    for m in msgs:
        print(m)
    return opts


def from_request(options: dict[str, Any], customize: Any) -> tuple[dict[str, Any], list[str], int]:
    """Desktop ``POST /jobs`` body ``customize: {text, knobs}`` -> (options dict, messages, http status)."""
    from ..config import Options
    if not isinstance(customize, dict) or not (customize.get("text") or customize.get("knobs")):
        return options, [], 200
    knobs = customize.get("knobs") if isinstance(customize.get("knobs"), dict) else {}
    unknown = [k for k in knobs if not K.canonical(k)]
    if unknown:
        return options, [K.unknown_message(unknown)], 400
    opts = Options.from_dict(options)
    opts, msgs = set_customize(opts, text=str(customize.get("text") or ""), knobs=knobs, preset_named=True)
    return opts.to_dict(), msgs, 200


def summary(opts_or_job: Any) -> str:
    """One line for replies/UI: 'customized: pink and playful · accent=#FF5FA2'."""
    if isinstance(opts_or_job, dict):
        c = ((opts_or_job.get("options") or opts_or_job).get("hints") or {}).get(HINT) or {}
    else:
        c = get(opts_or_job)
    if not c:
        return ""
    bits = [f"\u201c{c['text']}\u201d"] if c.get("text") else []
    bits += [f"{k}={v}" for k, v in (c.get("knobs") or {}).items()]
    return "customized: " + " · ".join(bits) if bits else ""


def dumps(c: dict[str, Any]) -> str:
    return json.dumps(c, ensure_ascii=False, sort_keys=True)
