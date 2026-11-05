"""Storyboard JSON Schema (for ``ctx.llm`` structured output) and a strict hand-written validator.

``jsonschema`` is not a Hermes core dependency, so :func:`validate_schema` implements the
subset of JSON Schema we use and returns precise JSONPath-style error locations
(``$.scenes[3].extra.focus_lines``) that the repair prompt can quote back to the model.

Two schemas:

* :data:`STORYBOARD_SCHEMA` - the full contract (lengths, counts, ranges, word limits via
  the custom ``x-maxWords`` keyword). Used by our validator.
* :func:`transport_schema` - a portable subset sent to providers for constrained
  decoding (Anthropic/OpenAI structured outputs reject length/range keywords and need
  ``additionalProperties: false`` on every object). Limits move into descriptions.
  The host validates replies against this one when ``jsonschema`` happens to be
  installed, so keeping it loose means a near-miss reply still reaches our repair step.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

from ..contracts import STAT_KEYS, Product, SceneType, Storyboard, StoryScene
from .rules import FILM_MODES, PRODUCT_KINDS, SPLIT_CHARS, film_mode
from .text import normalize_ws, word_count

SCENE_TYPES: tuple[str, ...] = tuple(t.value for t in SceneType)
TRANSITIONS: tuple[str, ...] = ("cut", "match", "push", "wipe")

TITLE_CHARS = 40
TAGLINE_CHARS = 60
ONE_LINER_CHARS = 90
CTA_CHARS = 40
URL_CHARS = 200
VO_WORDS = 28
LABEL_WORDS = 6
QUOTE_WORDS = 12
MIN_SCENES = 3
MAX_SCENES = 24
MAX_REFS = 16
SCHEMA_NAME = "showreel.storyboard"

_REF = {"type": "string", "minLength": 1, "maxLength": 32, "description": "event id from the reference index, e.g. e17"}

SCENE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "refs", "vo", "label"],
    "properties": {
        "type": {"type": "string", "enum": list(SCENE_TYPES)},
        "refs": {"type": "array", "items": _REF, "maxItems": MAX_REFS,
                 "description": "event ids this scene shows; first id is the primary content"},
        "vo": {"type": "string", "maxLength": 240, "x-maxWords": VO_WORDS,
               "description": f"narration read aloud for this scene, <= {VO_WORDS} words, or empty"},
        "label": {"type": "string", "maxLength": 48, "x-maxWords": LABEL_WORDS,
                  "description": f"on-screen label, <= {LABEL_WORDS} words"},
        "extra": {
            "type": "object",
            "additionalProperties": False,
            "description": "type-specific fields",
            "properties": {
                "focus_lines": {"type": "array", "items": {"type": "integer", "minimum": 1},
                                "minItems": 2, "maxItems": 2,
                                "description": "CODE/DIFF: [first, last] 1-based line numbers to highlight"},
                "stat_keys": {"type": "array", "items": {"type": "string", "enum": list(STAT_KEYS)},
                              "minItems": 1, "maxItems": 3, "uniqueItems": True,
                              "description": "STATS: 1-3 computed stat keys to show"},
                "before_ref": {**_REF, "description": "BEFORE_AFTER: event id of the before state"},
                "after_ref": {**_REF, "description": "BEFORE_AFTER: event id of the after state"},
                "quote_ref": {**_REF, "description": "CALLOUT: event id the quote is copied from"},
                "quote": {"type": "string", "maxLength": 120, "x-maxWords": QUOTE_WORDS,
                          "description": f"CALLOUT: exact words copied from quote_ref, <= {QUOTE_WORDS} words"},
                "bbox": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
                         "minItems": 4, "maxItems": 4,
                         "description": "SCREEN: focus box [x, y, w, h] as fractions of the image"},
                "montage_refs": {"type": "array", "items": _REF, "minItems": 1, "maxItems": MAX_REFS,
                                 "description": "MONTAGE: 6-16 tool-call event ids in time order"},
                "transition": {"type": "string", "enum": list(TRANSITIONS),
                               "description": "optional transition into this scene"},
                "feature": {"type": "string", "maxLength": 48, "x-maxWords": LABEL_WORDS,
                            "description": "FEATURE: the product feature this scene shows (one of product.features)"},
                "click": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
                          "minItems": 2, "maxItems": 2,
                          "description": "FEATURE: optional cursor click point [x, y] as fractions of the image"},
                "scroll": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
                           "minItems": 2, "maxItems": 2,
                           "description": "SCROLL: optional [from, to] scroll positions as fractions of the page"},
                "split": {"type": "string", "minLength": 1, "maxLength": SPLIT_CHARS,
                          "description": f"speedrun: milestone split label shown on the timer, <= {SPLIT_CHARS} "
                                         "characters; the scene's first ref is the milestone event"},
            },
        },
    },
}

PRODUCT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "one_liner", "kind", "features"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": TITLE_CHARS,
                 "description": "the product's real name from the session (repo, package, page title)"},
        "one_liner": {"type": "string", "maxLength": ONE_LINER_CHARS,
                      "description": f"what it does for its user, <= {ONE_LINER_CHARS} characters"},
        "kind": {"type": "string", "enum": list(PRODUCT_KINDS)},
        "urls": {"type": "array", "items": {"type": "string", "maxLength": URL_CHARS}, "maxItems": 5,
                 "description": "URLs of the product seen in the session (deployed or local)"},
        "entry_files": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 6,
                        "description": "main files of the product (index.html, cli.py, README.md ...)"},
        "run_commands": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 6,
                         "description": "commands the session used to run or demo the product, copied exactly"},
        "features": {"type": "array", "maxItems": 6,
                     "items": {"type": "string", "minLength": 1, "maxLength": 48, "x-maxWords": LABEL_WORDS},
                     "description": f"up to 6 feature names, <= {LABEL_WORDS} words each, each visible in the "
                                    "session evidence"},
        "hero_event_ids": {"type": "array", "items": _REF, "maxItems": 6,
                           "description": "event ids of the best evidence of the product (captures, screenshots, "
                                          "demo runs)"},
    },
}

STORYBOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "tagline", "cta", "product", "scenes"],
    "properties": {
        "mode": {"type": "string", "enum": list(FILM_MODES),
                 "description": "film mode; Showreel sets it from the user's choice"},
        "product": PRODUCT_SCHEMA,
        "title": {"type": "string", "minLength": 1, "maxLength": TITLE_CHARS,
                  "description": f"project name or film title, <= {TITLE_CHARS} characters"},
        "tagline": {"type": "string", "maxLength": TAGLINE_CHARS,
                    "description": f"one-line thesis, <= {TAGLINE_CHARS} characters"},
        "cta": {"type": "string", "maxLength": CTA_CHARS,
                "description": f"end-card call to action, <= {CTA_CHARS} characters"},
        "url": {"type": "string", "maxLength": URL_CHARS,
                "description": "optional URL for the end card; must appear verbatim in the session"},
        "accent_hint": {"type": "string", "pattern": "^(#[0-9A-Fa-f]{6})?$",
                        "description": "optional #RRGGBB accent colour taken from the project"},
        "scenes": {"type": "array", "items": SCENE_SCHEMA, "minItems": MIN_SCENES, "maxItems": MAX_SCENES},
    },
}

# Keywords providers' structured-output decoders commonly reject.
_TRANSPORT_DROP = ("minLength", "maxLength", "pattern", "minimum", "maximum", "maxItems", "uniqueItems")


def transport_schema() -> dict[str, Any]:
    """Portable copy of :data:`STORYBOARD_SCHEMA` for provider-side constrained decoding.

    Removes length/range/count keywords and ``x-*`` extensions (keeping ``minItems``
    only when it is 0 or 1) so Anthropic and OpenAI accept it; the stripped limits are
    already stated in each property's description and in the prompt.
    """
    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in _TRANSPORT_DROP or k.startswith("x-"):
                    continue
                if k == "minItems" and isinstance(v, int) and v > 1:
                    continue
                out[k] = strip(v)
            return out
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node
    return strip(copy.deepcopy(STORYBOARD_SCHEMA))


# ------------------------------------------------------------------------ validator

@dataclass(frozen=True)
class SchemaError:
    """One schema violation at a JSONPath-like location."""
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


_TYPE_NAMES = {dict: "object", list: "array", str: "string", bool: "boolean", type(None): "null"}


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return _TYPE_NAMES.get(type(value), type(value).__name__)


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_schema(value: Any, schema: dict[str, Any] = STORYBOARD_SCHEMA, path: str = "$") -> list[SchemaError]:
    """Validate ``value`` against the JSON Schema subset used by Showreel.

    Supports: type, enum, required, properties, additionalProperties (bool), items,
    minItems, maxItems, uniqueItems, minLength, maxLength, pattern, minimum, maximum and
    the custom ``x-maxWords``. Returns every violation found (empty list = valid).
    """
    errors: list[SchemaError] = []
    expected = schema.get("type")
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, t) for t in options):
            errors.append(SchemaError(path, f"expected {' or '.join(options)}, got {_type_name(value)}"))
            return errors
    if "enum" in schema and value not in schema["enum"]:
        shown = ", ".join(map(str, schema["enum"]))
        errors.append(SchemaError(path, f"{value!r} is not one of: {shown}"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(SchemaError(path, f"must have at least {schema['minLength']} character(s)"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(SchemaError(path, f"is {len(value)} characters; max {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(SchemaError(path, f"{value!r} does not match {schema['pattern']}"))
        if "x-maxWords" in schema and word_count(value) > schema["x-maxWords"]:
            errors.append(SchemaError(path, f"is {word_count(value)} words; max {schema['x-maxWords']}"))
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(SchemaError(path, f"{value} is below minimum {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(SchemaError(path, f"{value} is above maximum {schema['maximum']}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(SchemaError(path, f"has {len(value)} item(s); needs at least {schema['minItems']}"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(SchemaError(path, f"has {len(value)} items; max {schema['maxItems']}"))
        if schema.get("uniqueItems"):
            seen: list[str] = []
            for item in value:
                key = json.dumps(item, sort_keys=True)
                if key in seen:
                    errors.append(SchemaError(path, f"duplicate item {item!r}"))
                    break
                seen.append(key)
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(SchemaError(f"{path}.{key}", "is required"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(SchemaError(f"{path}.{key}", "is not an allowed property"))
        for key, sub in props.items():
            if key in value:
                errors.extend(validate_schema(value[key], sub, f"{path}.{key}"))
    return errors


# ---------------------------------------------------------------------- conversions

_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)


def parse_json_text(text: str) -> tuple[Any, str]:
    """Parse model output into JSON: strips code fences and surrounding prose.

    Returns ``(obj, "")`` on success or ``(None, error message)``.
    """
    if not text or not text.strip():
        return None, "empty response"
    candidates = []
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    candidates.append(text.strip())
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first:last + 1])
    error = ""
    for cand in candidates:
        try:
            return json.loads(cand), ""
        except (json.JSONDecodeError, ValueError) as exc:
            error = f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}" \
                if isinstance(exc, json.JSONDecodeError) else f"invalid JSON: {exc}"
    return None, error


def product_from_json(obj: Any) -> Product:
    """Convert a product JSON object (possibly partial) into a :class:`Product`."""
    obj = obj if isinstance(obj, dict) else {}

    def strings(key: str) -> list[str]:
        raw = obj.get(key) or []
        return [normalize_ws(str(x)) for x in raw if str(x).strip()] if isinstance(raw, list) else []

    return Product(name=normalize_ws(str(obj.get("name", ""))), one_liner=normalize_ws(str(obj.get("one_liner", ""))),
                   kind=str(obj.get("kind", "") or ""), urls=strings("urls"), entry_files=strings("entry_files"),
                   run_commands=strings("run_commands"), features=strings("features"),
                   hero_event_ids=strings("hero_event_ids"))


def product_to_json(product: Product | None) -> dict[str, Any]:
    """Inverse of :func:`product_from_json`."""
    p = product or Product()
    return {"name": p.name, "one_liner": p.one_liner, "kind": p.kind or "other", "urls": list(p.urls),
            "entry_files": list(p.entry_files), "run_commands": list(p.run_commands), "features": list(p.features),
            "hero_event_ids": list(p.hero_event_ids)}


def storyboard_from_json(obj: dict[str, Any], source: str = "llm", mode: str | None = None) -> Storyboard:
    """Convert schema-valid storyboard JSON into a :class:`Storyboard` (text whitespace-normalised).

    ``mode`` (the user's choice) wins over the JSON's own ``mode`` field.
    """
    scenes = []
    for raw in obj.get("scenes", []):
        scenes.append(StoryScene(
            type=SceneType(raw["type"]),
            refs=[str(r) for r in raw.get("refs", [])],
            vo=normalize_ws(raw.get("vo", "")),
            label=normalize_ws(raw.get("label", "")),
            extra=copy.deepcopy(raw.get("extra", {}) or {}),
        ))
    return Storyboard(
        title=normalize_ws(obj.get("title", "")),
        tagline=normalize_ws(obj.get("tagline", "")),
        scenes=scenes,
        cta=normalize_ws(obj.get("cta", "")),
        url=(obj.get("url") or "").strip(),
        accent_hint=(obj.get("accent_hint") or "").strip(),
        source=source,  # type: ignore[arg-type]
        mode=film_mode(mode or obj.get("mode")),  # type: ignore[arg-type]
        product=product_from_json(obj.get("product")),
    )


def storyboard_to_json(sb: Storyboard) -> dict[str, Any]:
    """Inverse of :func:`storyboard_from_json` (``source`` is not part of the schema)."""
    out: dict[str, Any] = {"mode": film_mode(sb.mode), "product": product_to_json(sb.product), "title": sb.title,
                           "tagline": sb.tagline, "cta": sb.cta, "scenes": []}
    if sb.url:
        out["url"] = sb.url
    if sb.accent_hint:
        out["accent_hint"] = sb.accent_hint
    for sc in sb.scenes:
        item: dict[str, Any] = {"type": SceneType(sc.type).value, "refs": list(sc.refs), "vo": sc.vo,
                                "label": sc.label}
        if sc.extra:
            item["extra"] = copy.deepcopy(sc.extra)
        out["scenes"].append(item)
    return out
