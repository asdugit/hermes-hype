"""``/showreel`` argument parsing (free word order) and the human replies of the non-render actions.

Grammar (any order): ``[lore|bts|process|making-of|speedrun|any%] [<style>] [30|60|90|45s|"60 seconds"]
[vertical|9:16|both|square] [mute|no-voice] [quick|standard|max] [preview]`` plus the flags of the spec
(``--seconds N``, ``--style X``, ``--vertical``, ``--both``, ``--no-voice``, ``--preview``...).
First-word actions: ``styles``, ``status [job]``, ``cancel [job]``, ``revise <notes>``, ``help``.

Anything that is not an option makes the film **Directed**: the whole text goes to the Director as
the user's direction, and options recognised at the start or end of it still apply
(``/showreel pixel but transition into a different style mid way through`` -> directed, style pixel).
Option words inside the free text are only *hints* (a style named mid-sentence, ``60 seconds``,
``vertical``), so ordinary words such as "the 90s" or "the product" never change settings.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .config import EFFORTS, MAX_SECONDS, MIN_SECONDS, Options, norm_aspects
from .contracts import MODE_ALIASES

ACTIONS = {"styles": "styles", "status": "status", "cancel": "cancel", "revise": "revise",
           "help": "help", "-h": "help", "--help": "help", "?": "help"}
#: Most words an action may take before the text counts as a direction ("/showreel help me sell it").
_ACTION_MAX_WORDS = {"styles": 1, "help": 1, "status": 2, "cancel": 2, "revise": 10_000}
_VOICE_OFF = {"mute", "muted", "silent", "no-voice", "novoice", "no-vo", "captions", "captions-only", "no-narration",
              "--no-voice", "--mute", "--captions"}
_VOICE_ON = {"voice", "narrated", "--voice"}
_ASPECT_WORDS = {"vertical", "portrait", "9:16", "both", "horizontal", "landscape", "16:9", "wide", "square", "1:1"}
_STRONG_ASPECTS = {"vertical", "9:16", "16:9", "1:1"}
_PREVIEW = {"preview", "draft", "--preview"}
_FINAL = {"final", "--final"}
#: Mode words strong enough to count when they appear inside free text.
_DISTINCT_MODES = {"lore", "bts", "making-of", "makingof", "speedrun", "any%"}
_UNITS = {"s", "sec", "secs", "second", "seconds"}
#: "the 90s", "like the 80s": a decade, not a length.
_DECADE_LEAD = {"the", "like", "in", "of", "from", "early", "late", "mid", "those", "these"}
#: "cinematic style", "pixel look": the style the user really means when several are named.
_STYLE_NOUNS = {"style", "look", "vibe", "vibes", "aesthetic", "theme", "feel", "styled"}
_LEN_RE = re.compile(r"^(\d{1,3})(s|sec|secs|seconds?)?$")
_MIN_RE = re.compile(r"^(\d)(m|min|mins|minutes?)$")
_STRIP = ",.;!?\"'()[]{}"
_VALUE_FLAGS = {"--seconds": "seconds", "--length": "seconds", "--duration": "seconds", "--style": "style",
                "--mode": "mode", "--effort": "effort", "--aspect": "aspect"}

HELP = (
    "Usage: /showreel [lore|speedrun] [style] [30|60|90] [vertical|both] [mute] [quick|standard|max]\n"
    "  /showreel                      product trailer of what this session built (default)\n"
    "  /showreel lore                 the making-of story · /showreel speedrun  the build as a speedrun\n"
    "  /showreel pixel 60 vertical    style + length + 9:16 · add 'mute' for captions only\n"
    "  /showreel <any direction>      Directed film, e.g. /showreel pixel, then bloom into anime, sell it\n"
    "  /showreel revise <notes>       another pass on the last film with your notes\n"
    "  /showreel styles | status | cancel"
)


@dataclass
class Command:
    """A parsed ``/showreel`` invocation."""
    action: str = "render"            # render | styles | status | cancel | revise | help
    options: Options = field(default_factory=Options)
    job_ref: str = ""                 # status/cancel target (job id or prefix)
    messages: list[str] = field(default_factory=list)   # things to tell the user (typos, ignored words...)

    @property
    def directed(self) -> bool:
        return self.options.directed


@dataclass
class _Tok:
    raw: str
    kind: str = "text"                # text | mode | style | seconds | aspect | voice | effort | preview | final | flag
    value: Any = None
    strong: bool = True               # counts inside free text (as a hint)
    pref: bool = False                # a style followed by "style"/"look": preferred hint


def _length(tok: str) -> int | None:
    m = _LEN_RE.match(tok)
    if m:
        n = int(m.group(1))
        return n if MIN_SECONDS <= n <= MAX_SECONDS else None
    m = _MIN_RE.match(tok)
    if m and 1 <= int(m.group(1)) <= 3:
        return min(MAX_SECONDS, 60 * int(m.group(1)))
    return None


def _classify(raw: str, styles: set[str]) -> _Tok:
    tok = raw.strip(_STRIP).lower()
    if not tok:
        return _Tok(raw)
    if tok.startswith("--") and "=" in tok:
        key, _, val = tok.partition("=")
        if key in _VALUE_FLAGS:
            return _value(raw, _VALUE_FLAGS[key], val, styles)
    if "=" in tok and not tok.startswith("-"):
        key, _, val = tok.partition("=")
        if key in {"seconds", "length", "style", "mode", "effort", "aspect"}:
            return _value(raw, {"length": "seconds"}.get(key, key), val, styles)
    if tok in _VALUE_FLAGS:
        return _Tok(raw, "flag", _VALUE_FLAGS[tok])
    if tok in styles:
        return _Tok(raw, "style", tok)
    if tok in MODE_ALIASES:
        return _Tok(raw, "mode", MODE_ALIASES[tok], strong=tok in _DISTINCT_MODES)
    if tok in _ASPECT_WORDS or tok in {"--vertical", "--both", "--horizontal", "--square"}:
        return _Tok(raw, "aspect", norm_aspects(tok.lstrip("-")), strong=tok in _STRONG_ASPECTS)
    if tok in _VOICE_OFF:
        return _Tok(raw, "voice", False, strong=False)
    if tok in _VOICE_ON:
        return _Tok(raw, "voice", True, strong=False)
    if tok in EFFORTS or tok in {"--quick", "--standard", "--max", "maximum"}:
        return _Tok(raw, "effort", {"maximum": "max"}.get(tok, tok.lstrip("-")), strong=False)
    if tok in _PREVIEW:
        return _Tok(raw, "preview", True, strong=False)
    if tok in _FINAL:
        return _Tok(raw, "final", False, strong=False)
    n = _length(tok)
    if n is not None:
        # "45s" / "60" are lengths at the edges; inside text only "<n> seconds" counts (see _merge)
        return _Tok(raw, "seconds", n, strong=False)
    return _Tok(raw)


def _value(raw: str, kind: str, val: str, styles: set[str]) -> _Tok:
    val = val.strip(_STRIP).lower()
    if kind == "seconds":
        n = _length(val)
        return _Tok(raw, "seconds", n) if n else _Tok(raw)
    if kind == "style":
        return _Tok(raw, "style", val) if val else _Tok(raw)
    if kind == "mode":
        return _Tok(raw, "mode", MODE_ALIASES.get(val, "product"))
    if kind == "effort":
        return _Tok(raw, "effort", val if val in EFFORTS else "standard")
    return _Tok(raw, "aspect", norm_aspects(val))


def _merge(toks: list[_Tok], styles: set[str]) -> list[_Tok]:
    """Join two-token forms: ``--seconds 45``, ``--style pixel``, ``60 seconds``."""
    out: list[_Tok] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        prev = toks[i - 1].raw.strip(_STRIP).lower() if i else ""
        if t.kind == "seconds" and prev in _DECADE_LEAD and t.raw.strip(_STRIP).lower().endswith("s"):
            out.append(_Tok(t.raw))
            i += 1
            continue
        if t.kind == "style" and nxt is not None and nxt.raw.strip(_STRIP).lower() in _STYLE_NOUNS:
            t.pref = True
        if t.kind == "flag" and nxt is not None:
            merged = _value(f"{t.raw} {nxt.raw}", t.value, nxt.raw, styles)
            if merged.kind != "text":
                out.append(merged)
                i += 2
                continue
        if nxt is not None and nxt.raw.strip(_STRIP).lower() in _UNITS:
            n = _length(t.raw.strip(_STRIP).lower())
            if n is not None:
                out.append(_Tok(f"{t.raw} {nxt.raw}", "seconds", n, strong=True))
                i += 2
                continue
        out.append(_Tok(t.raw) if t.kind == "flag" else t)
        i += 1
    return out


def _apply(opts: Options, t: _Tok, messages: list[str]) -> None:
    """Set one explicit option (the first value of a kind wins; repeats are noted)."""
    name = {"aspect": "aspects", "preview": "preview", "final": "preview"}.get(t.kind, t.kind)
    if name in opts.explicit and t.kind not in ("aspect",):
        if t.kind == "style" and t.value != opts.style:
            opts.hints.setdefault("styles", []).append(t.value)
            messages.append(f"Using style '{opts.style}' ('{t.value}' kept as a hint).")
        return
    if t.kind == "aspect":
        merged = [a for a in opts.aspects if "aspects" in opts.explicit] + [a for a in t.value]
        opts.aspects = list(dict.fromkeys(merged))
    elif t.kind in ("final", "preview"):
        opts.preview = bool(t.value)
    else:
        setattr(opts, t.kind, t.value)
    if name not in opts.explicit:
        opts.explicit.append(name)


def _apply_hint(opts: Options, t: _Tok) -> None:
    """Option words found inside free text: recorded for the Director, applied only if not set explicitly."""
    key = {"style": "styles", "mode": "modes", "aspect": "aspects", "seconds": "seconds"}.get(t.kind)
    if key is None:
        return
    if key == "seconds":
        opts.hints["seconds"] = t.value
    else:
        bucket = opts.hints.setdefault(key, [])
        for v in t.value if isinstance(t.value, list) else [t.value]:
            if v not in bucket:
                bucket.append(v)
    name = {"aspect": "aspects"}.get(t.kind, t.kind)
    if name in opts.explicit or name in opts.hints.get("_applied", []):
        return
    if t.kind == "aspect":
        opts.aspects = list(t.value)
    else:
        setattr(opts, t.kind, t.value)
    opts.hints.setdefault("_applied", []).append(name)


def parse(raw: str | None, *, styles: Iterable[str] = (), base: Options | None = None) -> Command:
    """Parse ``/showreel`` arguments into a :class:`Command`. Never raises.

    ``styles`` are the accepted style ids (``config.style_ids()``); ``base`` carries the user's
    settings defaults. Any free text makes the film Directed (``options.direction`` = the full text).
    """
    text = " ".join(str(raw or "").split())
    opts = (base or Options()).normalised()
    opts.explicit, opts.hints, opts.direction = [], {}, ""
    cmd = Command(options=opts)
    words = text.split(" ") if text else []
    if words:
        action = ACTIONS.get(words[0].lower()) or ACTIONS.get(words[0].lower().strip(_STRIP))
        if action and len(words) <= _ACTION_MAX_WORDS[action]:
            cmd.action = action
            rest = " ".join(words[1:]).strip()
            if action == "revise":
                opts.notes = rest
                if not rest:
                    cmd.messages.append("Add your notes after 'revise', e.g. /showreel revise slower start, more product.")
            elif action in ("status", "cancel"):
                cmd.job_ref = rest.split(" ")[0] if rest else ""
            return cmd
    style_set = {s.lower() for s in styles}
    toks = _merge([_classify(w, style_set) for w in words], style_set)
    lead = 0
    while lead < len(toks) and toks[lead].kind != "text":
        lead += 1
    tail = len(toks)
    while tail > lead and toks[tail - 1].kind != "text":
        tail -= 1
    edges = toks[:lead] + toks[tail:]
    if lead < tail:      # free text exists: weak mode words at its edges ("...sell the product") are prose
        edges = [t for t in edges if not (t.kind == "mode" and not t.strong)]
    for t in edges:
        _apply(opts, t, cmd.messages)
    middle = toks[lead:tail]
    if middle:
        words_mid = [t.raw.strip(_STRIP) for t in middle if t.kind == "text" and t.raw.strip(_STRIP)]
        guess = _typo_style(words_mid, style_set) if len(middle) == 1 else None
        if guess:
            cmd.messages.append(f"Read '{words_mid[0]}' as the {guess} style.")
            _apply(opts, _Tok(words_mid[0], "style", guess), cmd.messages)
        else:
            opts.direction = text
            for t in sorted((t for t in middle if t.kind != "text" and t.strong), key=lambda t: not t.pref):
                _apply_hint(opts, t)
    opts.hints.pop("_applied", None)
    return cmd


def _typo_style(words: list[str], styles: set[str]) -> str | None:
    """A lone unknown word that is a near-miss of a style id (``pixle`` -> ``pixel``)."""
    if len(words) != 1 or not styles:
        return None
    hit = difflib.get_close_matches(words[0].lower(), sorted(styles), n=1, cutoff=0.8)
    return hit[0] if hit else None


# ----------------------------------------------------------------------- replies

def describe(opts: Options) -> str:
    """One-line human summary of the options (used in replies and progress messages)."""
    mode = {"product": "trailer", "making_of": "making-of", "speedrun": "speedrun"}.get(opts.mode, opts.mode)
    parts = [f"{opts.style} {mode}", f"{opts.seconds}s", " + ".join(opts.aspects)]
    if not opts.voice:
        parts.append("captions only")
    if opts.preview:
        parts.append("preview")
    if opts.directed:
        parts.append(f"directed ({opts.effort})")
    return " · ".join(parts)


def styles_text(styles: dict[str, Any]) -> str:
    """Reply for ``/showreel styles``: ready styles first, then names this build cannot render yet."""
    ready = [s for s in styles.values() if getattr(s, "ready", False)]
    later = [s for s in styles.values() if not getattr(s, "ready", False)]
    lines = ["Showreel styles:"]
    for s in sorted(ready, key=lambda s: s.id):
        lines.append(f"  {s.id:<10} {s.blurb}".rstrip())
    if later:
        lines.append("Not in this build yet (falls back to launch): " + ", ".join(sorted(s.id for s in later)))
    lines.append("Use: /showreel <style> [30|60|90] [vertical|both] [mute], or describe any look you want.")
    return "\n".join(lines)
