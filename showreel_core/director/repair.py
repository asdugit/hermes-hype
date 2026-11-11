"""Auto-repair for model output: lenient JSON, schema-driven type coercion, id snapping, word budgets.

Weaker models break structured output in predictable ways: prose around the JSON, code fences, trailing commas,
comments, single quotes, Python literals, a reply cut off mid-object, numbers as strings ("3.5 s"), a single
object where a list is expected, enum values in the wrong case or slightly misspelt, and invented ids for kit
scenes, transitions, beds and sound effects. Every function here repairs instead of rejecting and reports what it
changed (the fixes go to the job log), so a weak reply still becomes a usable step and no extra model call is spent.

    obj, fixes = loads_lenient(text)
    obj, fixes = coerce(obj, schema)
    name = snap("kit:natur/flower_field", catalog_ids)     # -> "kit:nature/flower-field"
    fixes = snap_film_ids(obj, catalog, asset_names)       # in place, before check_film
    line = fit_words("A long sentence, with a clause.", 4)  # sentence/comma/conjunction cut, never mid-phrase
"""
from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON|js|javascript)?\s*\n(.*?)(?:```|\Z)", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_LINE_COMMENT = re.compile(r"(^|[^:\"'\\])//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_NUM_PREFIX = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?|[-+]?\.\d+)")


# ------------------------------------------------------------------------------------ lenient JSON

def _strip_outside_strings(text: str, pattern: re.Pattern[str], repl: str) -> str:
    """Apply ``pattern`` only to the parts of ``text`` outside double-quoted strings."""
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            out.append(pattern.sub(repl, "".join(buf)))
            buf = []
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        buf.append(c)
        i += 1
    out.append(pattern.sub(repl, "".join(buf)))
    return "".join(out)


def _single_to_double(text: str) -> str:
    """'key': 'value' -> "key": "value" (only when the text has no double-quoted strings at all)."""
    if '"' in text:
        return text
    return re.sub(r"'((?:\\.|[^'\\])*)'", lambda m: json.dumps(m.group(1)), text)


def _close_truncated(text: str) -> str:
    """Close an object cut off mid-reply: drop the dangling tail, then close open strings/brackets."""
    stack: list[str] = []
    in_str = esc = False
    last_safe = 0
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
                last_safe = i + 1
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
            last_safe = i + 1
        elif c in ",":
            last_safe = i
        elif not c.isspace():
            last_safe = i + 1
    if not stack and not in_str:
        return text
    body = text[:last_safe].rstrip()
    body = re.sub(r",\s*$", "", body)
    body = re.sub(r'[,{]\s*"[^"]*"\s*:?\s*$', lambda m: "{" if m.group(0).lstrip().startswith("{") else "", body)
    # recompute the open brackets of what is left
    stack = []
    in_str = esc = False
    for c in body:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]" and stack:
            stack.pop()
    if in_str:
        body += '"'
    body = re.sub(r",\s*$", "", body.rstrip())
    if body.endswith(":"):
        body += " null"
    return body + "".join(reversed(stack))


def _candidates(text: str) -> list[str]:
    out = []
    m = _FENCE.search(text)
    if m:
        out.append(m.group(1).strip())
    s = text.strip()
    out.append(s)
    first = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=-1)
    if first >= 0:
        last = max(s.rfind("}"), s.rfind("]"))
        if last > first:
            out.append(s[first:last + 1])
        out.append(s[first:])                     # maybe cut off: no closing bracket at all
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def loads_lenient(text: str) -> tuple[Any, list[str]]:
    """Parse a model reply into JSON, repairing common breakage. Returns ``(obj | None, fixes)``."""
    if not isinstance(text, str) or not text.strip():
        return None, ["empty reply"]
    for cand in _candidates(text):
        try:
            return json.loads(cand), ([] if cand == text.strip() else ["extracted the JSON from the reply"])
        except ValueError:
            pass
    for cand in _candidates(text):
        fixes = ["extracted the JSON from the reply"]
        t = _BLOCK_COMMENT.sub("", cand)
        t = _strip_outside_strings(t, _LINE_COMMENT, r"\1")
        t2 = _strip_outside_strings(t, re.compile(r"\bTrue\b"), "true")
        t2 = _strip_outside_strings(t2, re.compile(r"\bFalse\b"), "false")
        t2 = _strip_outside_strings(t2, re.compile(r"\bNone\b"), "null")
        if t2 != t:
            fixes.append("Python literals -> JSON")
        t = _single_to_double(t2)
        t = _strip_outside_strings(t, _TRAILING_COMMA, r"\1")
        for attempt in (t, _close_truncated(t)):
            try:
                obj = json.loads(attempt)
            except ValueError:
                continue
            if attempt is not t:
                fixes.append("closed a reply that was cut off")
            return obj, fixes + ["removed comments / trailing commas / single quotes"]
    return None, ["the reply is not JSON"]


# ------------------------------------------------------------------------------------ schema coercion

def _types(schema: dict[str, Any]) -> list[str]:
    t = schema.get("type")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def to_number(x: Any) -> float | None:
    """3 / "3.5" / "3.5 s" / "~2" -> float; anything else -> None (booleans are not numbers)."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        m = _NUM_PREFIX.match(x.replace("~", "").replace(",", "."))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def to_bool(x: Any) -> bool | None:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        v = x.strip().lower()
        if v in ("true", "yes", "y", "1", "on", "visible"):
            return True
        if v in ("false", "no", "n", "0", "off", "none", "hidden", ""):
            return False
    return None


def coerce(obj: Any, schema: dict[str, Any], path: str = "$") -> tuple[Any, list[str]]:
    """Coerce ``obj`` towards ``schema`` (JSON-schema subset: type, properties, required, items, enum, default).

    Never raises; returns the repaired value and the list of fixes. Unknown properties are kept (the engine's
    own validators decide); missing required properties with a ``default`` are filled.
    """
    fixes: list[str] = []
    if not isinstance(schema, dict) or not schema:
        return obj, fixes
    types = _types(schema)
    if "enum" in schema and obj is not None:
        choices = [str(c) for c in schema["enum"]]
        if str(obj) not in choices:
            hit = snap(str(obj), choices)
            if hit is not None:
                fixes.append(f"{path}: {obj!r} -> {hit!r}")
                return hit, fixes
            if "default" in schema:
                fixes.append(f"{path}: unknown {obj!r} -> default {schema['default']!r}")
                return schema["default"], fixes
        return obj, fixes
    if obj is None:
        if "default" in schema:
            return schema["default"], fixes
        return obj, fixes
    if "null" in types and obj is None:
        return obj, fixes
    if "object" in types:
        if isinstance(obj, str):
            parsed, _ = loads_lenient(obj)
            if isinstance(parsed, dict):
                fixes.append(f"{path}: parsed a JSON string")
                obj = parsed
        if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], dict):
            fixes.append(f"{path}: unwrapped a one-item list")
            obj = obj[0]
        if not isinstance(obj, dict):
            if "array" in types:
                pass
            else:
                return obj, fixes
        if isinstance(obj, dict):
            props = schema.get("properties") or {}
            out = dict(obj)
            lower = {str(k).lower().replace("-", "_").replace(" ", "_"): k for k in obj}
            for key, sub in props.items():
                if key not in out:
                    alt = lower.get(key.lower())
                    if alt is not None and alt != key:
                        out[key] = out.pop(alt)
                        fixes.append(f"{path}: key {alt!r} -> {key!r}")
                if key in out:
                    out[key], f = coerce(out[key], sub, f"{path}.{key}")
                    fixes += f
            for key in schema.get("required") or []:
                sub = props.get(key) or {}
                if key not in out and "default" in sub:
                    out[key] = sub["default"]
                    fixes.append(f"{path}.{key}: missing -> default")
            return out, fixes
    if "array" in types:
        items = schema.get("items") or {}
        if isinstance(obj, str) and _types(items) and _types(items) != ["string"]:
            parsed, _ = loads_lenient(obj)
            if isinstance(parsed, (list, dict)):
                obj = parsed
                fixes.append(f"{path}: parsed a JSON string")
        if isinstance(obj, dict):
            if items and "object" in _types(items) and not all(isinstance(v, dict) for v in obj.values()):
                obj = [obj]
                fixes.append(f"{path}: wrapped one object into a list")
            else:
                obj = list(obj.values()) if obj and all(isinstance(v, dict) for v in obj.values()) else [obj]
                fixes.append(f"{path}: object -> list")
        elif isinstance(obj, str):
            parts = [p.strip() for p in re.split(r"\n|;|\s\|\s", obj) if p.strip()]
            obj = parts or [obj]
            fixes.append(f"{path}: string -> list")
        elif not isinstance(obj, list):
            obj = [obj]
            fixes.append(f"{path}: value -> one-item list")
        out_list = []
        for i, it in enumerate(obj):
            v, f = coerce(it, items, f"{path}[{i}]")
            fixes += f
            out_list.append(v)
        return out_list, fixes
    if "number" in types or "integer" in types:
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            return (round(obj) if types == ["integer"] else obj), fixes
        n = to_number(obj)
        if n is not None:
            fixes.append(f"{path}: {obj!r} -> {n:g}")
            return (round(n) if "number" not in types else n), fixes
        if "default" in schema:
            return schema["default"], fixes + [f"{path}: {obj!r} is not a number -> default"]
        return obj, fixes
    if "boolean" in types:
        b = to_bool(obj)
        if b is not None and b is not obj:
            fixes.append(f"{path}: {obj!r} -> {b}")
            return b, fixes
        return obj, fixes
    if "string" in types:
        if isinstance(obj, str):
            return obj, fixes
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            return f"{obj:g}" if isinstance(obj, float) else str(obj), fixes + [f"{path}: number -> string"]
        if isinstance(obj, list) and all(isinstance(x, (str, int, float)) for x in obj):
            return " ".join(str(x) for x in obj), fixes + [f"{path}: list -> string"]
        if isinstance(obj, dict):
            for k in ("text", "value", "name", "id"):
                if isinstance(obj.get(k), str):
                    return obj[k], fixes + [f"{path}: object -> its {k!r}"]
        return str(obj), fixes + [f"{path}: -> string"]
    return obj, fixes


# ------------------------------------------------------------------------------------ id snapping

def _norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9:/]+", "", s.lower().replace("_", "-"))


def snap(name: str, choices: Iterable[str], *, cutoff: float = 0.6) -> str | None:
    """The catalog id a (possibly hallucinated / misspelt / mis-cased) ``name`` most likely means, or None."""
    pool = [c for c in choices if c]
    if not pool or not isinstance(name, str) or not name.strip():
        return None
    raw = name.strip()
    if raw in pool:
        return raw
    by_norm: dict[str, str] = {}
    for c in pool:
        by_norm.setdefault(_norm_id(c), c)
    n = _norm_id(raw)
    if n in by_norm:
        return by_norm[n]
    for pre in ("kit:", "lib:", "blender:"):          # missing / doubled prefix
        if pre + n in by_norm:
            return by_norm[pre + n]
        if n.startswith(pre) and n[len(pre):] in by_norm:
            return by_norm[n[len(pre):]]
    tails = {}
    for c in pool:                                    # "flower-field" alone, or the right scene in the wrong kit
        tails.setdefault(_norm_id(c.split("/")[-1]), []).append(c)
    t = _norm_id(raw.split("/")[-1])
    if t in tails:
        same_kit = [c for c in tails[t] if raw.split("/")[0].lower() in c.lower()]
        return (same_kit or tails[t])[0]
    hit = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=cutoff)
    if hit:
        return by_norm[hit[0]]
    hit = difflib.get_close_matches(t, list(tails), n=1, cutoff=max(cutoff, 0.72))
    if hit:
        return tails[hit[0]][0]
    return None


def snap_scene(name: str, scenes: Iterable[str]) -> str | None:
    """Stricter :func:`snap` for scene ids: a misspelt scene inside a real kit, a real scene under the wrong
    kit or prefix; never a random scene for a made-up kit."""
    pool = list(scenes)
    hit = snap(name, pool, cutoff=0.95)
    if hit:
        return hit
    raw = str(name).strip()
    kit, _, tail = raw.rpartition("/")
    kit_n = _norm_id(kit).removeprefix("kit:").removeprefix("blender:")
    same = [c for c in pool if _norm_id(c.rpartition("/")[0]).removeprefix("kit:").removeprefix("blender:") == kit_n]
    if same:
        tails = {_norm_id(c.rpartition("/")[2]): c for c in same}
        m = difflib.get_close_matches(_norm_id(tail), list(tails), n=1, cutoff=0.6)
        if m:
            return tails[m[0]]
    by_tail: dict[str, list[str]] = {}
    for c in pool:
        by_tail.setdefault(_norm_id(c.rpartition("/")[2]), []).append(c)
    if _norm_id(tail) in by_tail and len(_norm_id(tail)) >= 4:
        return by_tail[_norm_id(tail)][0]
    m = difflib.get_close_matches(_norm_id(raw), [_norm_id(c) for c in pool], n=1, cutoff=0.88)
    if m:
        return next(c for c in pool if _norm_id(c) == m[0])
    return None


def snap_film_ids(obj: Any, catalog: Any, asset_names: Iterable[str] = (), *,
                  extra_scenes: Iterable[str] = ()) -> list[str]:
    """Fix invented ids in a ``{"film": ..., "plan": ...}`` reply IN PLACE before validation.

    Scene ids (shots, overlays), transition types, music beds/stings, SFX cues and asset references in shot
    params are snapped to the nearest catalog entry; ids that match nothing are left for the validator to report.
    """
    fixes: list[str] = []
    if not isinstance(obj, dict) or not isinstance(obj.get("film"), dict):
        return fixes
    film = obj["film"]
    scenes = set(catalog.scenes()) | set(extra_scenes)
    customs = {str(c.get("name")) for c in (obj.get("plan") or {}).get("custom_scenes") or []
               if isinstance(c, dict) and c.get("name")}
    for key in ("shots", "overlays"):
        for s in film.get(key) or []:
            if not isinstance(s, dict):
                continue
            sc = str(s.get("scene") or "")
            if not sc or sc in scenes or sc.startswith("custom:") or sc.startswith("lib:") and sc in scenes:
                continue
            if sc.split(":", 1)[-1] in customs and not sc.startswith("kit:"):
                s["scene"] = "custom:" + sc.split(":", 1)[-1]
                fixes.append(f"{key} {s.get('id')}: scene {sc!r} -> {s['scene']!r}")
                continue
            hit = snap_scene(sc, scenes)
            if hit and hit != sc:
                s["scene"] = hit
                fixes.append(f"{key} {s.get('id')}: scene {sc!r} -> {hit!r}")
    trans = set(catalog.transitions())
    for tr in film.get("transitions") or []:
        if isinstance(tr, dict) and tr.get("type") and tr["type"] not in trans:
            hit = snap(str(tr["type"]), trans, cutoff=0.7)
            if hit:
                fixes.append(f"transition {tr['type']!r} -> {hit!r}")
                tr["type"] = hit
    beds = [b.id for b in getattr(catalog, "beds", [])]
    sfx = list(getattr(catalog, "sfx", {}) or {})
    for m in film.get("music") or []:
        if not isinstance(m, dict):
            continue
        if m.get("bed") and m["bed"] not in beds:
            hit = snap(str(m["bed"]), beds, cutoff=0.5) or (beds[0] if beds else None)
            if hit:
                fixes.append(f"music bed {m['bed']!r} -> {hit!r}")
                m["bed"] = hit
        if m.get("sting") and sfx and m["sting"] not in sfx:
            hit = snap(str(m["sting"]), sfx, cutoff=0.5)
            if hit:
                fixes.append(f"sting {m['sting']!r} -> {hit!r}")
                m["sting"] = hit
    for c in film.get("cues") or []:
        if isinstance(c, dict) and c.get("sfx") and sfx and c["sfx"] not in sfx:
            hit = snap(str(c["sfx"]), sfx, cutoff=0.5)
            if hit:
                fixes.append(f"sfx {c['sfx']!r} -> {hit!r}")
                c["sfx"] = hit
    names = [a for a in asset_names if a]
    if names:
        for s in film.get("shots") or []:
            if isinstance(s, dict) and isinstance(s.get("params"), dict):
                fixes += _snap_assets(s["params"], names, f"shot {s.get('id')}")
    return fixes


_ASSET_KEYS = ("product", "media", "boss_media", "image", "asset", "model", "car", "hero")


def _snap_assets(params: dict[str, Any], names: list[str], where: str) -> list[str]:
    fixes = []
    for k, v in list(params.items()):
        if isinstance(v, dict):
            fixes += _snap_assets(v, names, where)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    fixes += _snap_assets(it, names, where)
        elif k in _ASSET_KEYS and isinstance(v, str) and v and v not in names and not v.startswith(("#", "http")):
            hit = snap(v, names, cutoff=0.5)
            if hit is None and len(names) == 1 and k in ("product", "media", "boss_media", "asset", "model"):
                hit = names[0]
            if hit:
                params[k] = hit
                fixes.append(f"{where}: asset {v!r} -> {hit!r}")
    return fixes


# ------------------------------------------------------------------------------------ word budgets

_CONJ = re.compile(r"\s+(?:and|but|or|so|while|because|then|with|as)\s+", re.IGNORECASE)


def fit_words(text: Any, max_words: int) -> str:
    """Trim to ``max_words`` without cutting a phrase: whole sentences first, then before a comma, then before a
    conjunction; otherwise '' (a line is never cut mid-phrase - the caller keeps its default). The words must also
    fit ``max_words`` slots in width (~9 columns each, CJK counted double): a 300-character run without spaces (a
    Chinese or Japanese line, a URL) counts as one word."""
    # nothing past ~40 characters a word can survive the fit: a degenerate reply (a weak model repeating a
    # token up to max_tokens) is cut first, so the sentence regexes never scan it (they backtrack quadratically)
    out = _fit_word_count(str(text or "")[: max(0, max_words) * 40 + 40], max_words)
    room = max_words * 9 + 10
    if _width(out) <= room:
        return out
    for pattern in (r".+?(?:[.!?](?=\s|$)|[\u3002\uff01\uff1f])", r"[^,;\uff0c\u3001\uff1b]+[,;\uff0c\u3001\uff1b]?"):
        acc = ""
        for part in re.findall(pattern, out):
            if _width(acc + part) > room:
                break
            acc += part
        acc = acc.strip().rstrip(",;\uff0c\u3001\uff1b")
        if acc and any(ch.isalnum() for ch in acc):
            return acc
    return ""


def _width(s: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _fit_word_count(text: Any, max_words: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip().strip('"').strip()
    if not s or max_words <= 0:
        return ""
    if len(s.split()) <= max_words:
        return s
    sentences = re.findall(r".+?[.!?]+(?=\s|$)", s)        # 'orbit.app' is not a sentence end
    acc = ""
    for sen in sentences:
        cand = (acc + " " + sen.strip()).strip()
        if len(cand.split()) > max_words:
            break
        acc = cand
    if acc:
        return acc
    first = sentences[0].strip() if sentences else s
    for splitter in (r",\s*", None):
        if splitter:
            parts = re.split(splitter, first)
            acc = ""
            for p in parts:
                cand = (acc + (", " if acc else "") + p).strip()
                if len(cand.split()) > max_words:
                    break
                acc = cand
            if acc and acc != first:
                return acc.rstrip(",;:") + ("." if first.endswith(".") else "")
        else:
            m = _CONJ.split(first)
            if m and len(m[0].split()) <= max_words and m[0] != first:
                return m[0].rstrip(",;:") + "."
    return ""


def is_hex(s: Any) -> bool:
    return isinstance(s, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", s.strip()) is not None


# ------------------------------------------------------------------------------------ on-screen hygiene

LOOPBACK = re.compile(r"(?:https?://)?(?:127(?:\.\d{1,3}){3}|localhost|0\.0\.0\.0|\[::1\])(?::\d{1,5})?(?:/[^\s\"']*)?",
                      re.IGNORECASE)
_URL_KEYS = ("url", "href", "link", "domain")


def public_url(urls: Iterable[str] | None) -> str:
    """The first URL that is not a loopback/dev-server address ('' when none)."""
    return next((u for u in (urls or []) if u and not LOOPBACK.search(u)), "")


def scrub_loopback(film: dict[str, Any], *, name: str, url: str = "") -> list[str]:
    """Never print a dev-server address on screen (a real END read '127.0.0.1:8765'): IN PLACE, url-like params
    become the public URL (or ''), and the address inside any other text becomes the public URL or the product
    name. Covers shots, overlays and captions."""
    fixes: list[str] = []

    def walk(o: Any, key: str, path: str) -> Any:
        if isinstance(o, str):
            if not LOOPBACK.search(o):
                return o
            new = url if key.lower() in _URL_KEYS else re.sub(r"\s{2,}", " ", LOOPBACK.sub(url or name, o)).strip()
            fixes.append(f"{path}: loopback address -> {new!r}")
            return new
        if isinstance(o, dict):
            return {k: walk(v, str(k), f"{path}.{k}") for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v, key, f"{path}[{i}]") for i, v in enumerate(o)]
        return o
    for sect in ("shots", "overlays", "captions"):
        if isinstance(film.get(sect), list):
            film[sect] = walk(film[sect], "", sect)
    return fixes


_CMD_PARAM_KEYS = {"cta", "cmd", "command", "install", "run"}
_TEXT_PARAM_KEYS = {"title", "tagline", "text", "sub", "label", "eyebrow", "caption", "headline", "feature", "quote",
                    "who", "words", "line", "credit", "name", "one_liner", "species", "heading", "subtitle"}
_MACHINE_PATH = re.compile(r"^(?:file:|~[\\/]|[A-Za-z]:[\\/]|/)")


def onscreen(film: dict[str, Any], plan: dict[str, Any] | None = None, *, product: Any = None, name: str = "",
             url: str = "") -> list[str]:
    """IN PLACE: the Director's on-screen text through the same helpers as Quick mode (``story/onscreen.py``):
    no loopback address anywhere (narration drops the sentence, commands elide it, URL fields become the public
    URL or ''); a CTA / command param that reads as a command or a line of code must be the product's own
    launch or install command (``approved_cta``) or it goes (the END then shows name + tagline); URL fields
    never carry a machine path; machine paths inside titles, taglines and labels are shortened like Quick's.
    Returns what changed."""
    from types import SimpleNamespace

    from ..story import onscreen as so
    fixes = so.scrub_film(film, name=name, url=url)
    nofacts = SimpleNamespace(events=[])          # a Directed film has no session events: only the product's
    trusted = list(getattr(product, "run_commands", None) or [])   # detected commands are trusted
    one = str(getattr(product, "one_liner", "") or "")
    slots = {"name": name or str(getattr(product, "name", "") or ""), "tagline": one if len(one) <= 60 else "",
             "cta": ""}                           # echoed template slots ({name}, <call to action>) never show

    def walk(o: Any, key: str, path: str) -> Any:
        if isinstance(o, dict):
            return {k: walk(v, str(k), f"{path}.{k}") for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v, key, f"{path}[{i}]") for i, v in enumerate(o)]
        if not isinstance(o, str) or not o.strip():
            return o
        k = key.lower()
        new = so.unplaceholder(o, **slots) if k in _TEXT_PARAM_KEYS or k in _CMD_PARAM_KEYS else o
        if k in _CMD_PARAM_KEYS:
            if new and (so.looks_like_command(new) or _MACHINE_PATH.match(new.strip())):
                new = so.approved_cta(new, product, nofacts, trusted)
        elif k in _URL_KEYS or k == "address":
            if _MACHINE_PATH.match(o.strip()):
                new = url if url and not _MACHINE_PATH.match(url) else ""
        elif k in _TEXT_PARAM_KEYS:
            new = so.display_text_paths(new)
        if new != o:
            fixes.append(f"{path}: {o[:60]!r} -> {new[:60]!r}")
        return new
    for sect in ("shots", "overlays", "captions"):
        if isinstance(film.get(sect), list):
            film[sect] = walk(film[sect], "", sect)
    if isinstance(film.get("captions"), list):         # a caption that was only filler goes (empty text is invalid)
        kept = [c for c in film["captions"] if not (isinstance(c, dict) and isinstance(c.get("text"), str)
                                                     and not c["text"].strip())]
        if len(kept) != len(film["captions"]):
            fixes.append(f"captions: {len(film['captions']) - len(kept)} empty caption(s) dropped")
            film["captions"] = kept
    for i, line in enumerate((plan or {}).get("voiceover") or []):
        if isinstance(line, dict) and isinstance(line.get("text"), str) and so.has_loopback(line["text"]):
            line["text"] = so.scrub_sentences(line["text"])
            fixes.append(f"plan.voiceover[{i}]: loopback sentence dropped")
        if isinstance(line, dict) and isinstance(line.get("text"), str):
            spoken = so.unplaceholder(line["text"], **slots)
            if spoken != line["text"]:
                line["text"] = spoken
                fixes.append(f"plan.voiceover[{i}]: template placeholder removed")
    return fixes


def _mentions_assets(o: Any, names: set[str]) -> bool:
    if isinstance(o, str):
        return o in names
    if isinstance(o, dict):
        return any(_mentions_assets(v, names) for v in o.values())
    if isinstance(o, list):
        return any(_mentions_assets(v, names) for v in o)
    return False


def lockup_end(obj: dict[str, Any], catalog: Any, product_assets: Iterable[str], *, name: str, tagline: str = "",
               cta: str = "", url: str = "") -> list[str]:
    """A custom-code final shot that puts the product behind the closing type is swapped for a kit lockup, IN PLACE
    on a ``{"film", "plan"}`` object (a real END laid "Tempo / Focus, beautifully." across the app's timer ring and
    its CTA pill over the app's own text). Kit END lockups keep the name off the product's UI by construction."""
    film = obj.get("film") if isinstance(obj.get("film"), dict) else obj
    shots = film.get("shots") or []
    if not shots or not isinstance(shots[-1], dict):
        return []
    last = shots[-1]
    scene = str(last.get("scene", ""))
    if not scene.startswith("custom:") or not _mentions_assets(last.get("params") or {}, set(product_assets)):
        return []
    known = set(catalog.scenes()) if catalog is not None else set()
    kits: dict[str, float] = {}
    for sh in shots:
        sc = str(sh.get("scene", ""))
        if sc.startswith("kit:"):
            k = sc.split(":", 1)[1].split("/")[0]
            kits[k] = kits.get(k, 0.0) + float(sh.get("t1", 0) or 0) - float(sh.get("t0", 0) or 0)
    cands = [f"kit:{k}/END" for k in sorted(kits, key=lambda k: -kits[k]) if k not in ("type", "frames")]
    target = next((c for c in [*cands, "kit:type/end-lockup"] if c in known), "")
    if not target:
        return []
    params: dict[str, Any] = {"title": name, "cta": cta, "url": url}
    if target == "kit:type/end-lockup":
        params = {"title": name, "tagline": tagline, "cta": cta, "url": url, "scrim": 0.0}
    last["scene"], last["params"] = target, {k: v for k, v in params.items() if v != ""}
    plan = obj.get("plan") if isinstance(obj.get("plan"), dict) else None
    old = scene.split(":", 1)[1]
    if plan is not None and not any(str(sh.get("scene", "")) == scene for sh in shots[:-1]):
        plan["custom_scenes"] = [c for c in plan.get("custom_scenes") or []
                                 if not (isinstance(c, dict) and c.get("name") == old)]
    return [f"shot `{last.get('id')}`: custom end {scene} put the title over the product; now {target}"]
