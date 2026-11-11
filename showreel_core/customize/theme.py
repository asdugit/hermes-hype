"""The generic theme-override layer: semantic colours/fonts -> every kit's own tokens.

A resolved theme (``{"accent", "accent2", "accent3", "bg", "text", "font", "body_font"}``, any subset) becomes
the film.json ``theme`` block::

    "theme": {"tokens": {...semantic...},
              "vars": {"--sr-accent": "#FF2BD6", "--ph": "...", ...},      # CSS custom properties, page-wide
              "palette": {"comic": {"red": "#FF2BD6", ...}, "ink": {...}, "pixel": {"gold": "#..."}}}

The runtime injects ``vars`` with ``!important`` on every element of the stage (runtime/core/runtime.js), so the
DOM part of every kit re-skins without kit edits (the kits/base ``--sr-*`` tokens + the kit families ``--ph-*``
terminal, ``--sheet``/``--cyan`` blueprint, ``--cx-*`` comic, ``--ik-*`` ink). Kits that draw colours in JS read
``ctx.film.theme.palette[<kit>]`` (pixel palette words, comic/ink palette ``C``) and terminal takes a hex
``phosphor``; cinematic takes the per-shot ``accent`` param (set by customize/apply.py).
"""
from __future__ import annotations

from typing import Any

from . import vocab as V

SEMANTIC = ("accent", "accent2", "accent3", "bg", "text", "font", "body_font")


def resolve(knobs: dict[str, Any] | None, spec_theme: dict[str, Any] | None = None) -> dict[str, str]:
    """Semantic tokens from knobs (palette first, then explicit colours) and an LLM spec theme (knobs win)."""
    tokens: dict[str, str] = {}
    for src in (spec_theme or {}, knobs or {}):
        pal = src.get("palette")
        if isinstance(pal, str):
            pal = V.palette(pal)
        if isinstance(pal, dict):
            tokens.update({k: v for k, v in pal.items() if k in SEMANTIC and V.colour(v)})
        for k in ("accent", "accent2", "accent3", "bg", "text"):
            c = V.colour(src.get(k))
            if c:
                tokens[k] = c
        for k in ("font", "body_font"):
            f = V.font(src.get(k)) if src.get(k) else ""
            if f:
                tokens[k] = f
        if str(src.get("motion") or "") in ("bouncy", "smooth"):
            tokens["motion"] = str(src["motion"])
    if "bg" in tokens and "text" not in tokens:
        tokens["text"] = "#F4F3EF" if V.lum(tokens["bg"]) < 0.35 else "#16151A"
    return tokens


def _stage_bg(bg: str) -> str:
    lift = V.mix(bg, "#FFFFFF", 0.10) if V.lum(bg) < 0.35 else V.mix(bg, "#FFFFFF", 0.35)
    return f"radial-gradient(115% 90% at 50% 46%, {lift} 0%, {bg} 58%, {V.mix(bg, '#000000', 0.35)} 100%)"


def _accent_vars(a: str) -> dict[str, str]:
    return {"--sr-accent": a, "--sr-accent-ink": V.ink_on(a), "--sr-accent-hl": V.mix(a, "#FFFFFF", 0.55),
            "--sr-accent-glow": V.rgba(a, 0.38), "--sr-em-color": a, "--sr-tone": a}


def _font_stack(fam: str, generic: str = "sans-serif") -> str:
    return f'"{fam}", {generic}'


def css_vars(tokens: dict[str, str]) -> dict[str, str]:
    """CSS custom properties for every kit family from the semantic tokens."""
    v: dict[str, str] = {}
    a, a2, bg, tx = tokens.get("accent"), tokens.get("accent2"), tokens.get("bg"), tokens.get("text")
    if a:
        v.update(_accent_vars(a))
        # terminal: one phosphor hue drives the whole CRT palette
        v.update({"--ph": a, "--ph-hot": V.mix(a, "#FFFFFF", 0.72), "--ph-mid": V.mix(a, "#000000", 0.22),
                  "--ph-dim": V.mix(a, "#000000", 0.52), "--ph-faint": V.mix(a, "#000000", 0.78),
                  "--ph-rgb": ", ".join(str(c) for c in V.rgb(a))})
        # blueprint: the cyan accent family; comic: the red action colour; ink: terracotta hero accent
        v.update({"--cyan": a, "--cyan-dim": V.rgba(a, 0.45), "--cx-red": a, "--ik-terra": a,
                  "--ik-terra-d": V.mix(a, "#000000", 0.2)})
    if a2:
        v.update({"--cx-cyan": a2, "--cx-magenta": tokens.get("accent3") or V.mix(a2, a or a2, 0.5),
                  "--ik-teal": a2, "--ik-teal-d": V.mix(a2, "#000000", 0.24), "--sr-tone": a2})
    if tokens.get("accent3"):
        v.update({"--cx-yellow": tokens["accent3"], "--ik-mustard": tokens["accent3"]})
    if bg:
        dark = V.lum(bg) < 0.35
        v.update({"--sr-stage": bg, "--sr-stage-bg": _stage_bg(bg), "--sr-table": V.mix(bg, "#000000", 0.15),
                  "--sr-table-lit": V.mix(bg, "#FFFFFF", 0.14), "--sr-scrim-rgb": " ".join(str(c) for c in V.rgb(bg)),
                  "--glass": V.mix(bg, "#000000", 0.25), "--glass-lit": V.mix(bg, "#FFFFFF", 0.06),
                  "--sheet": bg, "--sheet-hi": V.mix(bg, "#FFFFFF", 0.08), "--sheet-lo": V.mix(bg, "#000000", 0.2),
                  "--cx-paper": bg, "--cx-paper-2": V.mix(bg, "#000000" if not dark else "#FFFFFF", 0.1),
                  "--ik-paper": bg, "--ik-paper-d": V.mix(bg, "#000000" if not dark else "#FFFFFF", 0.07),
                  "--sr-plate": V.rgba(V.mix(bg, "#000000", 0.2), 0.88)})
        v["--sr-grid"] = V.rgba(tx or ("#FFFFFF" if dark else "#000000"), 0.06)
    if tx:
        v.update({"--sr-fg": tx, "--sr-fg-2": V.mix(tx, bg or "#808080", 0.32), "--sr-fg-3": V.mix(tx, bg or "#808080", 0.55),
                  "--line": tx, "--line-2": V.rgba(tx, 0.74), "--line-3": V.rgba(tx, 0.46)})
    if tokens.get("font"):
        f = _font_stack(tokens["font"])
        v.update({"--sr-f-display": f, "--cx-display": f, "--ik-title": f, "--tm-fd": f})
    if tokens.get("body_font"):
        f = _font_stack(tokens["body_font"])
        v.update({"--sr-f-sans": f, "--cx-letter": f, "--ik-body": f, "--bp-f": f, "--tm-f": f})
    return v


#: pixel "Dusk 32" tokens per semantic role (dark -> light ramps get shades of the new colour).
PIXEL_ROLES = {"accent": ["amber", "gold", "cream"], "accent2": ["tealdk", "teal", "ice"],
               "accent3": ["maroon", "red", "coral"], "bg": ["ink", "night", "navy"], "text": ["white"]}


def _ramp(c: str, n: int) -> list[str]:
    if n == 1:
        return [c]
    if n == 3:
        return [V.mix(c, "#000000", 0.42), c, V.mix(c, "#FFFFFF", 0.55)]
    return [V.mix(c, "#000000", 0.4 * (1 - i / (n - 1))) for i in range(n)]


def kit_palettes(tokens: dict[str, str]) -> dict[str, dict[str, str]]:
    """JS palette overrides for kits that draw colours in code (pixel words, comic/ink ``C``)."""
    out: dict[str, dict[str, str]] = {}
    pix: dict[str, str] = {}
    for role, names in PIXEL_ROLES.items():
        c = tokens.get(role)
        if not c:
            continue
        if role == "bg":
            shades = [V.mix(c, "#000000", 0.35), c, V.mix(c, "#FFFFFF", 0.12)]
        else:
            shades = _ramp(c, len(names))
        pix.update(dict(zip(names, shades)))
    if pix:
        out["pixel"] = pix
    a, a2, a3, bg, tx = (tokens.get(k) for k in ("accent", "accent2", "accent3", "bg", "text"))
    comic: dict[str, str] = {}
    if a:
        comic.update({"red": a, "orange": V.mix(a, "#FFD23A", 0.35)})
    if a2:
        comic.update({"cyan": a2, "blue": V.mix(a2, "#000000", 0.3), "magenta": a3 or V.mix(a2, a or a2, 0.5)})
    if a3:
        comic.update({"yellow": a3, "green": V.mix(a3, a2 or a3, 0.5)})
    if bg:
        comic.update({"paper": bg, "paper2": V.mix(bg, "#000000" if V.lum(bg) > 0.35 else "#FFFFFF", 0.1)})
    if comic:
        out["comic"] = comic
    ink: dict[str, str] = {}
    if a:
        ink.update({"terra": a, "terraD": V.mix(a, "#000000", 0.2)})
    if a2:
        ink.update({"teal": a2, "tealD": V.mix(a2, "#000000", 0.24)})
    if a3:
        ink["mustard"] = a3
    if bg:
        ink.update({"paper": bg, "paperD": V.mix(bg, "#000000", 0.07)})
    if ink:
        out["ink"] = ink
    _ = tx
    return out


def theme_block(tokens: dict[str, str]) -> dict[str, Any]:
    """The film.json ``theme`` block (``{}`` when nothing is overridden)."""
    if not tokens:
        return {}
    block: dict[str, Any] = {"tokens": dict(tokens), "vars": css_vars(tokens)}
    if tokens.get("motion"):
        block["motion"] = tokens["motion"]          # kits/base motion.js: type entrances spring (bouncy)
    pal = kit_palettes(tokens)
    if pal:
        block["palette"] = pal
    return block


def font_faces(tokens: dict[str, str]) -> list[dict[str, Any]]:
    """film.json ``fonts`` entries for the theme fonts (repo-relative ``kits/<kit>/fonts/...`` srcs)."""
    out: list[dict[str, Any]] = []
    table = V.fonts()
    for k in ("font", "body_font"):
        fam = tokens.get(k)
        row = table.get(str(fam or "").lower())
        if row:
            out += [dict(f) for f in row["files"] if f not in out]
    return out


def terminal_phosphor(tokens: dict[str, str]) -> str:
    """terminal kit ``phosphor``: p1 (green) / p3 (amber) when the accent is close to them, else the hex itself."""
    a = tokens.get("accent")
    if not a:
        return ""
    h = V.hue(a)
    r, g, b = V.rgb(a)
    sat = (max(r, g, b) - min(r, g, b)) / 255
    if sat > 0.45 and 110 <= h <= 160:
        return "p1"
    if sat > 0.45 and 28 <= h <= 48:
        return "p3"
    return a
