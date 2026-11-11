"""The any-model path and the engine floor: small schema-constrained steps, the engine assembles the film.

A frontier model can write a treatment and a whole film.json from a 140 KB catalog. A small or cheap model
cannot - it invents kit names, breaks the JSON, forgets the timeline. So for weaker models the Director asks for
much less and the ENGINE does the film-making:

1. PICK  (one call, ~3k tokens, enum-constrained): which blueprint (a proven structure on polished kit scenes, in
   the style the direction asks for), the world/time of day, the accent colour, the voice, title/tagline/CTA.
2. WORDS (one call, ~2k tokens): only the words: each shot's on-screen text slots and the narration lines, with
   word budgets per slot.
3. ASSEMBLE (no model): the blueprint is laid out on the film length, placeholders filled with the product facts
   and the words, music cue sheet, stings, transitions, overlays and narration timing from the blueprint; then
   the same validators, measurements and repairs as every other film.

Each step validates and repairs (lenient JSON, type coercion, enum snapping, word budgets); anything still missing
falls back to the engine's defaults, so the ENGINE FLOOR - ``floor()`` - makes a complete, good film from the
product facts and the direction words alone, with no model at all.

Blueprints come from three places: the narrative recipes (+ their proven films), one "product film" per 2D style
kit (each kit's own transitions, bed, finish and post chain from its kit.json), and Blender blueprints (3D studio
reveal, device reveal, meadow documentary) when Blender is available.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import moods
from . import recipes as rc
from . import repair
from .repair import coerce, fit_words, is_hex, loads_lenient, snap
from .types import Brief

PLACEHOLDER = re.compile(r"<([^<>]{3,120})>")
EVIDENCE = re.compile(r"\breal (hunks|file|session|test|plan|code|diff|stats)|verbatim prompt|the user's prompt",
                      re.IGNORECASE)
TIMES = ("dawn", "golden", "sunset", "night", "pastel")
VOICES = ("none", "sparse", "narrated")
STYLE_KITS = ("launch", "cinematic", "comic", "ink", "terminal", "blueprint", "pixel")
ONER_LENGTH = 25.4                                # blender:meadow/oner's designed move (its `length` default)


@dataclass(frozen=True)
class Blueprint:
    """A complete, engine-assemblable film structure."""
    id: str
    name: str
    fits: str                                   # one line for the pick menu: directions it suits
    look: str                                   # one line: what it looks and sounds like
    kind: str                                   # physical | screen | any
    shots: tuple[dict[str, Any], ...]           # {id, share, scene, params, res?, product, beat}
    transitions: tuple[dict[str, Any], ...] = ()
    overlays: tuple[dict[str, Any], ...] = ()
    music: tuple[dict[str, Any], ...] = ()      # {bed, share} | {sting, at}
    voice: str = "none"
    finish: dict[str, Any] = field(default_factory=dict)
    render: dict[str, Any] = field(default_factory=dict)
    background: str = "#000"
    blender: bool = False
    recipe: str = ""                            # the narrative recipe it implements
    seconds: tuple[float, float] = (20.0, 60.0)  # lengths it supports well
    keywords: tuple[str, ...] = ()
    exemplar: str = ""


# ------------------------------------------------------------------------------------ blueprint library

_RECIPE_MUSIC: dict[str, tuple[dict[str, Any], ...]] = {
    "boss-battle": ({"bed": "pixel_boss_b", "share": (0.0, 0.47)}, {"sting": "bloom_riser", "at": 0.46},
                    {"bed": "dream_b", "share": (0.47, 1.0)}),
    "item-get": ({"bed": "pixel_a", "share": (0.0, 0.70)}, {"sting": "level_up", "at": 0.30},
                 {"bed": "dream_a", "share": (0.70, 1.0)}),
    "heist": ({"bed": "pixel_b", "share": (0.0, 0.55)}, {"sting": "impact", "at": 0.33},
              {"bed": "terminal_a", "share": (0.55, 1.0)}),
    "day-in-the-life": ({"bed": "cinematic_b", "share": (0.0, 1.0)},),
    "before-after": ({"bed": "cinematic_a", "share": (0.0, 0.45)}, {"sting": "impact", "at": 0.45},
                     {"bed": "dream_b", "share": (0.45, 1.0)}),
    "nature-documentary": ({"bed": "cinematic_b", "share": (0.0, 1.0)},),
    "launch-keynote": ({"bed": "launch_a", "share": (0.0, 1.0)},),
    "origin-story": ({"bed": "launch_b", "share": (0.0, 1.0)},),
    "speedrun": ({"bed": "pixel_b", "share": (0.0, 1.0)}, {"sting": "level_up", "at": 0.72}),
}
_RECIPE_KEYWORDS = {
    "boss-battle": ("pixel", "boss", "game", "battle", "rpg", "16-bit", "8-bit", "retro game", "transform", "style"),
    "item-get": ("unbox", "loot", "chest", "item", "reveal", "collect"),
    "heist": ("heist", "steal", "vault", "night", "crew", "neon"),
    "day-in-the-life": ("day", "life", "everyday", "routine", "morning", "calm"),
    "before-after": ("before", "after", "fix", "upgrade", "transform"),
    "nature-documentary": ("nature", "documentary", "attenborough", "wildlife", "narrat", "hushed"),
    "launch-keynote": ("launch", "promo", "keynote", "product"),
    "origin-story": ("story", "built", "origin", "making"),
    "speedrun": ("speedrun", "fast", "timer"),
}
_STYLE_WORDS = {
    "terminal": ("vhs", "80s", "1980", "eighties", "infomercial", "crt", "retro tv", "tv", "terminal", "hacker",
                 "phosphor", "late-night", "late night", "tape", "analog"),
    "cinematic": ("noir", "detective", "trailer", "cinematic", "dark", "moody", "thriller", "mystery", "film",
                  "movie", "epic", "dramatic"),
    "comic": ("comic", "manga", "anime", "superhero", "pop art", "cartoon", "opening credits", "opening", "action"),
    "ink": ("hand-drawn", "hand drawn", "sketch", "doodle", "explainer", "illustrat", "whiteboard", "storybook",
            "notebook"),
    "blueprint": ("blueprint", "engineering", "technical", "schematic", "architect", "precision", "spec"),
    "pixel": ("pixel", "8-bit", "16-bit", "arcade", "game", "nintendo", "rpg", "retro game", "chiptune"),
    "launch": ("launch", "promo", "startup", "saas", "clean", "modern", "minimal", "product hunt"),
}
_STYLE_LOOK = {
    "terminal": "a phosphor CRT tube: amber/green glyphs, ASCII-to-dither-to-real captures, channel-switch cuts, "
                "darksynth bed",
    "cinematic": "a dark room of glowing glass cards, heavy camera, rack focus, 2.39 letterbox, amber accent, serif "
                 "titles, a slow ominous bed",
    "comic": "a motion-comic issue: ink-bordered panels on newsprint, halftone, sunbursts, speech balloons, "
             "onomatopoeia slams, punchy bed",
    "ink": "a warm hand-drawn explainer: ink strokes on paper, a cartoon user and robot, sticky notes, ink-bleed "
           "transitions, light acoustic bed",
    "blueprint": "a cyanotype engineering drawing: plotter-drawn lines, dimensions, DETAIL zooms, calm camera, "
                 "precise electronic bed",
    "pixel": "a 16-bit game: pixel art, chunky UI boxes, iris and screen-slide transitions, chiptune",
    "launch": "a premium launch film: paper UI panels on a lit graphite table, look-at camera pushes, one lime "
              "accent, upbeat bed",
}


def _recipe_blueprints() -> list[Blueprint]:
    out = []
    for r in rc.RECIPES:
        if any(s.scene.startswith("custom:") for s in r.shots) or r.id not in _RECIPE_MUSIC:
            continue
        physical = {"boss-battle", "item-get", "heist", "race-chase", "day-in-the-life", "before-after",
                    "nature-documentary"}          # nature-world flyers: screenshots read as ghost cards
        screen = {"launch-keynote", "origin-story", "speedrun"}
        kind = "physical" if r.id in physical else "screen" if r.id in screen else "any"
        shots = tuple({"id": s.id, "share": s.share, "scene": s.scene, "params": copy.deepcopy(s.params),
                       "res": list(s.res) if s.res else None, "product": s.product, "beat": s.beat} for s in r.shots)
        out.append(Blueprint(
            id=r.id, name=r.name, fits=r.fits, look=f"{r.arc} (kits: {', '.join(r.kits)})", kind=kind,
            shots=shots, transitions=tuple(copy.deepcopy(list(r.transitions))),
            overlays=tuple({**o, "share": tuple(o["share"])} for o in r.overlays), music=_RECIPE_MUSIC[r.id],
            voice=next((w for w in re.findall(r"[a-z]+", r.voice.lower())[:1] if w in VOICES), "sparse"),
            recipe=r.id, keywords=_RECIPE_KEYWORDS.get(r.id, ()),
            exemplar=(ex.id if (ex := rc.exemplar_for(r.id)) else "")))
    return out


def _kit_json(kits_root: Path, kit: str) -> dict[str, Any]:
    try:
        return json.loads((kits_root / kit / "kit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _style_blueprint(kit: str, kits_root: Path) -> Blueprint:
    """The kit authors' "product film (web app)" recipe in one 2D style kit: HOOK -> TITLE -> FEATURE x2 ->
    SCREEN -> CALLOUT -> END, with that kit's own transitions, bed, finish and post chain."""
    kj = _kit_json(kits_root, kit)
    tr = kj.get("transitions") or {}
    act = (tr.get("push") or tr.get("wipe") or ["crossfade", 0.6])
    inner = (tr.get("match") or tr.get("cut") or ["cut", 0.2])
    beds = list(((kj.get("style") or {}).get("music")) or [f"{kit}_a"])
    k = f"kit:{kit}"
    shots = (
        {"id": "hook", "share": (0.0, 0.12), "scene": f"{k}/HOOK", "product": True,
         "params": {"hero": {"kind": "image", "asset": "{asset1}"}, "label": "<hook: a 3-6 word line that stops "
                    "the scroll, in the direction's voice>"}, "beat": "the product, first, with a hook line"},
        {"id": "title", "share": (0.12, 0.27), "scene": f"{k}/TITLE", "product": True,
         "params": {"title": "{name}", "tagline": "{tagline}", "product": "{name}", "one_liner": "{one_liner}",
                    "hero": {"kind": "image", "asset": "{asset1}"}}, "beat": "name + thesis"},
        {"id": "feature1", "share": (0.27, 0.44), "scene": f"{k}/FEATURE", "product": True,
         "params": {"image": {"asset": "{asset2}"}, "feature": "{feature1}"}, "beat": "feature one, clicked"},
        {"id": "feature2", "share": (0.44, 0.61), "scene": f"{k}/FEATURE", "product": True,
         "params": {"image": {"asset": "{asset3}"}, "feature": "{feature2}"}, "beat": "feature two"},
        {"id": "screen", "share": (0.61, 0.79), "scene": f"{k}/SCREEN", "product": True,
         "params": {"image": {"asset": "{asset1}"}, "bbox": [0.2, 0.22, 0.6, 0.42]},
         "beat": "the product, pushed in on its headline"},
        {"id": "quote", "share": (0.79, 0.87), "scene": f"{k}/CALLOUT", "product": False,
         "params": {"text": "<one short line a delighted user would say; no numbers, no claims>",
                    "who": "first look"},
         "beat": "the reaction"},
        {"id": "end", "share": (0.87, 1.0), "scene": f"{k}/END", "product": False,
         "params": {"title": "{name}", "cta": "{cta}", "url": "{url}"}, "beat": "lockup + CTA"},
    )
    # act changes get the kit's signature transition; inside the feature act one match cut and hard cuts on the
    # beat (three identical dips in a row read as slide changes - critic, noir trial)
    trans = ({"from": "hook", "to": "title", "type": act[0], "dur": float(act[1])},
             {"from": "feature1", "to": "feature2", "type": inner[0], "dur": float(inner[1])},
             {"from": "screen", "to": "quote", "type": act[0], "dur": float(act[1])},
             {"from": "quote", "to": "end", "type": act[0], "dur": float(act[1])})
    music: tuple[dict[str, Any], ...] = ({"bed": beds[0], "share": (0.0, 1.0)},)
    return Blueprint(
        id=f"screen-{kit}", name=f"Product film, {kit} style", kind="screen",
        fits=f"software / web apps; directions that ask for: {', '.join(_STYLE_WORDS.get(kit, ())[:9])}",
        look=_STYLE_LOOK.get(kit, kit), shots=shots, transitions=trans, music=music, voice="sparse",
        finish=dict(kj.get("finish") or {}), render=dict(kj.get("render") or {}),
        background=str(kj.get("background") or "#000"), recipe="launch-keynote", keywords=_STYLE_WORDS.get(kit, ()),
        seconds=(20.0, 50.0))


def _blender_blueprints() -> list[Blueprint]:
    studio = Blueprint(
        id="studio-reveal", name="3D studio reveal (keynote)", kind="physical", blender=True,
        fits="premium physical products; 'keynote', 'Apple', 'reveal', 'luxury', 'commercial', 'unveil'",
        look="a real 3D model in a dark premium studio: rims draw the silhouette from darkness, a strip light "
             "sweeps the body, slow orbits, a macro detail pass, a hover on a pooled-colour cyc; minimal type",
        shots=(
            {"id": "tease", "share": (0.0, 0.10), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-4 word keynote teaser shown on black before the reveal>", "sub": ""},
             "beat": "black stage, one line of type: the keynote tease"},
            {"id": "reveal", "share": (0.10, 0.38), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "orbit", "env": "studio", "reveal": True, "yaw": 145, "orbit_deg": 34, "fill": 0.74,
                        "wheel_rps": 0.0, "paint": "{paint}"},
             "beat": "out of darkness, rims draw the silhouette; a light sweep; the front three-quarter"},
            {"id": "detail", "share": (0.38, 0.56), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "dolly", "env": "studio", "reveal": False, "yaw": 105, "pitch": 4, "orbit_deg": 16,
                        "fill": 0.82, "paint": "{paint}"}, "beat": "a low side dolly along the body: the craft, close"},
            {"id": "float", "share": (0.56, 0.80), "scene": "blender:studio/product_float", "product": True,
             "params": {"env": "accent", "accent": "{accent}", "turn_deg": 60, "fill": 0.68, "wheel_rps": 0.8,
                        "yaw": 150, "paint": "{paint}"},
             "beat": "it lifts off the floor and turns, pooled in the accent colour"},
            {"id": "hero", "share": (0.80, 0.90), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "turntable", "env": "studio", "reveal": False, "turn_deg": 40, "fill": 0.66,
                        "yaw": 160, "pitch": 8, "paint": "{paint}"}, "beat": "the hero turntable, front on"},
            {"id": "endcard", "share": (0.90, 1.0), "scene": "kit:type/end-lockup", "product": False,
             "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.0},
             "beat": "the name on black, keynote style"},
        ),
        # same-car shots never crossfade (two translucent cars read as an error): dips on act changes, cuts inside
        transitions=({"from": "tease", "to": "reveal", "type": "dip-black", "dur": 0.6},
                     {"from": "detail", "to": "float", "type": "dip-black", "dur": 0.5},
                     {"from": "hero", "to": "endcard", "type": "dip-black", "dur": 0.6}),
        overlays=({"id": "name", "share": (0.20, 0.35), "scene": "kit:type/lower-third",
                   "params": {"title": "{name}", "sub": "{tagline}"}},
                  {"id": "line", "share": (0.60, 0.76), "scene": "kit:type/lower-third",
                   "params": {"title": "<a 2-4 word benefit, no numbers>", "sub": "<a 4-8 word line, no claims>"}}),
        music=({"bed": "cinematic_a", "share": (0.0, 0.56)}, {"sting": "riser", "at": 0.54},
               {"bed": "launch_b", "share": (0.56, 1.0)}),
        voice="sparse", finish={"grain": 0.015, "vignette": 0.18}, recipe="launch-keynote",
        keywords=("keynote", "apple", "reveal", "unveil", "premium", "luxury", "studio", "commercial", "elegant",
                  "minimal", "3d", "showroom"), seconds=(16.0, 45.0))
    device = Blueprint(
        id="device-reveal", name="3D device reveal (keynote)", kind="screen", blender=True,
        fits="software / web apps; 'keynote', 'Apple', 'reveal', 'premium', 'launch event'",
        look="a real 3D laptop opens out of darkness with the product's live UI, eased pushes onto each feature, "
             "a laptop + phone family shot, a calm lockup; keynote type",
        shots=(
            {"id": "open", "share": (0.0, 0.24), "scene": "blender:device/device_hero", "product": True,
             "params": {"media": "{asset1}", "env": "studio", "reveal": True, "space": "none"},
             "beat": "the lid opens; the screen lights with the real UI"},
            {"id": "feature1", "share": (0.24, 0.44), "scene": "blender:device/device_feature", "product": True,
             "params": {"image": "{asset2}", "feature": "{feature1}", "fill": 0.6}, "beat": "push onto feature one"},
            {"id": "feature2", "share": (0.44, 0.63), "scene": "blender:device/device_feature", "product": True,
             "params": {"image": "{asset3}", "feature": "{feature2}", "fill": 0.6, "side": "right"},
             "beat": "push onto feature two"},
            {"id": "family", "share": (0.63, 0.81), "scene": "blender:device/device_trio", "product": True,
             "params": {"media": "{asset1}", "env": "studio"}, "beat": "laptop + phone: everywhere"},
            {"id": "end", "share": (0.81, 1.0), "scene": "blender:device/device_end", "product": True,
             "params": {"media": "{asset1}", "space": "left", "dim_bg": 0.3}, "beat": "calm lockup"},
        ),
        transitions=({"from": "open", "to": "feature1", "type": "crossfade", "dur": 0.5},
                     {"from": "feature1", "to": "feature2", "type": "crossfade", "dur": 0.5},
                     {"from": "feature2", "to": "family", "type": "dip-black", "dur": 0.6},
                     {"from": "family", "to": "end", "type": "crossfade", "dur": 0.6}),
        overlays=({"id": "name", "share": (0.12, 0.23), "scene": "kit:type/title",
                   "params": {"text": "{name}", "sub": "{tagline}"}},
                  {"id": "f1", "share": (0.30, 0.43), "scene": "kit:type/lower-third",
                   "params": {"title": "{feature1}", "sub": "<one benefit line for feature one, <= 8 words>"}},
                  {"id": "f2", "share": (0.50, 0.62), "scene": "kit:type/lower-third",
                   "params": {"title": "{feature2}", "sub": "<one benefit line for feature two, <= 8 words>"}},
                  {"id": "endcard", "share": (0.84, 1.0), "scene": "kit:type/end-lockup",
                   "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "url": "{url}"}}),
        music=({"bed": "launch_a", "share": (0.0, 1.0)},), voice="sparse", finish={"grain": 0.015, "vignette": 0.15},
        recipe="launch-keynote", keywords=("keynote", "apple", "reveal", "premium", "launch event", "3d", "device",
                                           "laptop", "elegant", "minimal"), seconds=(16.0, 45.0))
    meadow = Blueprint(
        id="meadow-documentary", name="3D anime meadow documentary", kind="physical", blender=True,
        fits="'nature documentary', 'Attenborough', 'wildlife', 'dreamy', 'anime field', calm wonder, narrated",
        look="one continuous Blender camera move through an anime flower meadow at dawn/golden hour; the product "
             "flies, dives and drives past a lone figure; a hushed narrator observes it like a rare creature",
        shots=({"id": "meadow", "share": (0.0, 1.0), "scene": "blender:meadow/oner", "product": True,
                "params": {"time_of_day": "{time}", "t_offset": 0.0, "density": 1.0, "figure": True, "petals": 1.0},
                "beat": "the habitat; sightings; the creature's behaviours; the close pass; the hero"},),
        overlays=({"id": "species", "share": (0.20, 0.34), "scene": "kit:type/lower-third",
                   "params": {"title": "{name}", "sub": "<a playful Latin-style species name, 2-4 words>"}},
                  {"id": "end", "share": (0.84, 1.0), "scene": "kit:type/end-lockup",
                   "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.3}}),
        music=({"bed": "dream_a", "share": (0.0, 1.0)},), voice="narrated", finish={"grain": 0.02, "vignette": 0.14},
        recipe="nature-documentary", keywords=("nature", "documentary", "attenborough", "wildlife", "narrat",
                                               "hushed", "meadow", "field", "dreamy", "calm", "dawn"),
        seconds=(18.0, 25.4))
    noir = Blueprint(
        id="studio-noir", name="3D film noir at night (studio)", kind="physical", blender=True,
        fits="'noir', 'detective', 'crime', 'mystery', 'thriller', 'hard-boiled', rain, night, black and white",
        look="the real 3D product alone on a wet black stage at night: one hard spot key, smoke, venetian-blind "
             "light across the wall and the body, rain; black and white except the product's own colour; "
             "typewriter title cards; a hard-boiled narrator",
        shots=(
            {"id": "open", "share": (0.0, 0.11), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-5 word hard-boiled opening line, typed on black (no product name)>", "sub": "",
                        "theme": "noir", "reveal": "type", "scrim": 0.0},
             "beat": "black frame, rain, a typewriter line: the case opens"},
            {"id": "suspect", "share": (0.11, 0.40), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "orbit", "env": "noir", "reveal": True, "yaw": 145, "orbit_deg": 30, "fill": 0.86,
                        "pitch": 7, "wheel_rps": 0.0, "paint": "{paint}"},
             "beat": "the suspect steps out of the dark: rim first, then the hard key; blinds across the wall"},
            {"id": "clues", "share": (0.40, 0.56), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "orbit", "env": "noir", "reveal": False, "yaw": 70, "pitch": 2, "orbit_deg": 22,
                        "fill": 0.95, "paint": "{paint}"},
             "beat": "the clues, close: a low side profile sliding past, light catching the edges"},
            {"id": "tail", "share": (0.56, 0.80), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "dolly", "env": "noir", "reveal": False, "yaw": -40, "pitch": 3, "orbit_deg": 24,
                        "fill": 0.8, "wheel_rps": 0.0, "paint": "{paint}"},
             "beat": "a low dolly in on the wet floor: the reflection, the rain, the colour that will not go grey"},
            {"id": "reveal", "share": (0.80, 0.91), "scene": "blender:studio/product_hero", "product": True,
             "params": {"move": "turntable", "env": "noir", "reveal": False, "yaw": 160, "pitch": 8,
                        "turn_deg": 35, "fill": 0.7, "paint": "{paint}"}, "beat": "the confession: front on"},
            {"id": "end", "share": (0.91, 1.0), "scene": "kit:type/end-lockup", "product": False,
             "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.0, "theme": "noir"},
             "beat": "the name on black, typewriter type"},
        ),
        transitions=({"from": "open", "to": "suspect", "type": "dip-black", "dur": 0.6},
                     {"from": "suspect", "to": "clues", "type": "dip-black", "dur": 0.5},
                     {"from": "tail", "to": "reveal", "type": "dip-black", "dur": 0.5},
                     {"from": "reveal", "to": "end", "type": "dip-black", "dur": 0.6}),
        overlays=({"id": "case", "share": (0.43, 0.54), "scene": "kit:type/lower-third",
                   "params": {"title": "<a 2-4 word case-file heading, e.g. EXHIBIT A>",
                              "sub": "<a 4-8 word hard-boiled line about the product, no numbers>", "theme": "noir"}},
                  {"id": "line", "share": (0.62, 0.76), "scene": "kit:type/title",
                   "params": {"text": "<a 3-6 word typed line: the detective's verdict>", "band": "bottom",
                              "theme": "noir", "reveal": "type", "scrim": 0.3}}),
        music=({"bed": "cinematic_a", "share": (0.0, 1.0)},), voice="narrated",
        finish={"grain": 0.08, "vignette": 0.5}, recipe="launch-keynote",
        keywords=("noir", "detective", "crime", "mystery", "thriller", "hard-boiled", "night", "rain", "gritty",
                  "black and white", "private eye"), seconds=(18.0, 40.0))
    anime = Blueprint(
        id="anime-opening", name="3D anime TV opening (meadow, fast cuts)", kind="physical", blender=True,
        fits="'anime', 'anime opening', 'shonen', 'manga', 'opening credits', high energy, J-pop, hype",
        look="a 90s anime TV opening: hard cuts every 2-3 s between dynamic moments of the Blender meadow (crane "
             "into a sky full of the product, low swoop, flight alongside, the hero pass) under huge kinetic title "
             "cards; saturated sunset sky; an energetic bed",
        shots=(
            {"id": "sky", "share": (0.0, 0.15), "scene": "blender:meadow/oner", "product": True,
             "params": {"time_of_day": "sunset", "t_offset": 1.6, "figure": True, "petals": 1.4, "crowd": 1.0},
             "beat": "crane up: the sky full of the product"},
            {"id": "swoop", "share": (0.15, 0.27), "scene": "blender:meadow/oner", "product": True,
             "params": {"time_of_day": "sunset", "t_offset": 6.0, "figure": True, "petals": 1.4, "crowd": 1.0},
             "beat": "swoop low under a pass"},
            {"id": "wing", "share": (0.27, 0.44), "scene": "blender:meadow/oner", "product": True,
             "params": {"time_of_day": "sunset", "t_offset": 9.6, "figure": True, "petals": 1.2, "crowd": 1.0},
             "beat": "flying alongside the product"},
            {"id": "wave", "share": (0.44, 0.58), "scene": "blender:meadow/oner", "product": True,
             "params": {"time_of_day": "sunset", "t_offset": 14.6, "figure": True, "petals": 1.4, "crowd": 1.0},
             "beat": "she waves; the product pulls up"},
            {"id": "hero", "share": (0.58, 0.86), "scene": "blender:meadow/oner", "product": True,
             "params": {"time_of_day": "sunset", "t_offset": 18.6, "figure": True, "petals": 1.6, "crowd": 1.0},
             "beat": "the hero close-up, light sweeping the paint"},
            {"id": "end", "share": (0.86, 1.0), "scene": "kit:type/end-lockup", "product": False,
             "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.45, "theme": "anime"},
             "beat": "the title card"},
        ),
        transitions=({"from": "sky", "to": "swoop", "type": "cut", "dur": 0.2},
                     {"from": "swoop", "to": "wing", "type": "cut", "dur": 0.2},
                     {"from": "wing", "to": "wave", "type": "cut", "dur": 0.2},
                     {"from": "wave", "to": "hero", "type": "cut", "dur": 0.2},
                     {"from": "hero", "to": "end", "type": "crossfade", "dur": 0.4}),
        overlays=({"id": "shout", "share": (0.02, 0.13), "scene": "kit:type/title",
                   "params": {"text": "<a 1-3 word shout, like an anime opening's first card>", "theme": "anime",
                              "scrim": 0.25}},
                  {"id": "name", "share": (0.26, 0.40), "scene": "kit:type/title",
                   "params": {"text": "{NAME}", "sub": "<a 2-5 word hype line>", "theme": "anime", "scrim": 0.3}},
                  {"id": "cry", "share": (0.44, 0.55), "scene": "kit:type/title",
                   "params": {"text": "<a 1-3 word battle cry>", "theme": "anime", "band": "bottom", "scrim": 0.2}}),
        music=({"bed": "launch_b", "share": (0.0, 1.0)},), voice="sparse",
        finish={"grain": 0.02, "vignette": 0.12, "bloom": 0.2}, recipe="boss-battle",
        keywords=("anime", "opening", "shonen", "manga", "hype", "j-pop", "energetic", "op"),
        seconds=(18.0, 32.0))
    return [studio, device, meadow, noir, anime]


def _mood_blueprints() -> list[Blueprint]:
    """Screen-product films whose WORLD is the mood (any model, no Blender): big mood type cards interleaved with the
    real product shown large (kit:base SCREEN/FEATURE: a 1560 px browser frame pushing in), so a noir ask reads as a
    case file and a keynote ask reads as a keynote stage - not as the same launch film with other words."""
    theme_n = {"theme": "noir"}
    # a feature capture is already the feature: show it whole (the default 0.8 focus box pushed a timer ring and a
    # task list half out of the frame in a real Tempo film)
    WHOLE = {"bbox": [0.03, 0.03, 0.94, 0.94], "click": [0.5, 0.5]}  # noqa: N806
    noir = Blueprint(
        id="screen-noir", name="Noir case file (software)", kind="screen",
        fits="software / web apps; 'noir', 'detective', 'crime', 'mystery', 'thriller', 'hard-boiled', rain, night",
        look="typewriter title cards typed on black, the real product shown large as the evidence (pushing in), "
             "case-file lower thirds, black and white with rain, a red accent, a serif-typewriter end lockup",
        shots=(
            {"id": "open", "share": (0.0, 0.09), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-5 word hard-boiled opening line, typed on black (no product name)>",
                        "sub": "", "reveal": "type", "scrim": 0.0, **theme_n},
             "beat": "black frame, rain, a typewriter line: the case opens"},
            {"id": "exhibit", "share": (0.09, 0.34), "scene": "kit:base/SCREEN", "product": True,
             "params": {"image": {"asset": "{asset1}"}, "bbox": [0.08, 0.06, 0.6, 0.6], **theme_n},
             "beat": "the evidence: the real product, large, the camera pushing in"},
            {"id": "clue", "share": (0.34, 0.41), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 3-6 word typed line: the detective's first clue about the product>",
                        "reveal": "type", "scrim": 0.0, **theme_n}, "beat": "a typed clue on black"},
            {"id": "feature1", "share": (0.41, 0.60), "scene": "kit:base/FEATURE", "product": True,
             "params": {"image": {"asset": "{asset2}", "frame": "card"}, "feature": "{feature1}", **WHOLE, **theme_n},
             "beat": "exhibit B: feature one, close"},
            {"id": "feature2", "share": (0.60, 0.80), "scene": "kit:base/FEATURE", "product": True,
             "params": {"image": {"asset": "{asset3}", "frame": "card"}, "feature": "{feature2}", **WHOLE, **theme_n},
             "beat": "exhibit C: feature two, close"},
            {"id": "verdict", "share": (0.80, 0.88), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-5 word typed verdict that names no numbers>", "reveal": "type", "scrim": 0.0,
                        **theme_n}, "beat": "the verdict, typed"},
            {"id": "end", "share": (0.88, 1.0), "scene": "kit:type/end-lockup", "product": False,
             "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.0, **theme_n},
             "beat": "the name on black, typewriter type"},
        ),
        transitions=({"from": "open", "to": "exhibit", "type": "dip-black", "dur": 0.5},
                     {"from": "exhibit", "to": "clue", "type": "dip-black", "dur": 0.4},
                     {"from": "clue", "to": "feature1", "type": "dip-black", "dur": 0.4},
                     {"from": "feature1", "to": "feature2", "type": "cut", "dur": 0.2},
                     {"from": "feature2", "to": "verdict", "type": "dip-black", "dur": 0.4},
                     {"from": "verdict", "to": "end", "type": "dip-black", "dur": 0.5}),
        overlays=({"id": "case", "share": (0.13, 0.30), "scene": "kit:type/lower-third",
                   "params": {"title": "<a 2-4 word case-file heading, e.g. EXHIBIT A>",
                              "sub": "{name}", **theme_n}},),
        music=({"bed": "cinematic_a", "share": (0.0, 1.0)}, {"sting": "impact", "at": 0.09}),
        voice="sparse", finish={"grain": 0.08, "vignette": 0.4}, background="#000", recipe="launch-keynote",
        keywords=("noir", "detective", "crime", "mystery", "thriller", "hard-boiled", "night", "rain", "gritty",
                  "black and white", "private eye", "case", "trailer"), seconds=(18.0, 50.0))
    keynote = Blueprint(
        id="screen-keynote", name="Keynote stage (software)", kind="screen",
        fits="software / web apps; 'keynote', 'Apple', 'unveil', 'launch event', 'premium', 'minimal', 'clean'",
        look="a black keynote stage: huge white type cards one idea at a time, the real product shown large and "
             "pushing in on its best parts, calm crossfades, a clean end lockup",
        shots=(
            {"id": "tease", "share": (0.0, 0.08), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-4 word keynote teaser shown on black, no product name>", "scrim": 0.0},
             "beat": "black stage, one line of type: the keynote tease"},
            {"id": "reveal", "share": (0.08, 0.32), "scene": "kit:base/SCREEN", "product": True,
             "params": {"image": {"asset": "{asset1}"}, "bbox": [0.1, 0.08, 0.62, 0.62]},
             "beat": "the product revealed large, the camera easing in"},
            {"id": "name", "share": (0.32, 0.40), "scene": "kit:type/title", "product": False,
             "params": {"text": "{name}", "sub": "{tagline}", "scrim": 0.0}, "beat": "the name, huge, on black"},
            {"id": "feature1", "share": (0.40, 0.59), "scene": "kit:base/FEATURE", "product": True,
             "params": {"image": {"asset": "{asset2}", "frame": "card"}, "feature": "{feature1}", **WHOLE}, "beat": "feature one, close"},
            {"id": "feature2", "share": (0.59, 0.80), "scene": "kit:base/FEATURE", "product": True,
             "params": {"image": {"asset": "{asset3}", "frame": "card"}, "feature": "{feature2}", **WHOLE}, "beat": "feature two, close"},
            {"id": "statement", "share": (0.80, 0.88), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-5 word keynote statement in two beats, e.g. 'Less noise. More focus.'>",
                        "scrim": 0.0}, "beat": "the one-line promise"},
            {"id": "end", "share": (0.88, 1.0), "scene": "kit:type/end-lockup", "product": False,
             "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.0},
             "beat": "the clean lockup"},
        ),
        transitions=({"from": "tease", "to": "reveal", "type": "dip-black", "dur": 0.6},
                     {"from": "reveal", "to": "name", "type": "dip-black", "dur": 0.5},
                     {"from": "name", "to": "feature1", "type": "dip-black", "dur": 0.5},
                     {"from": "feature1", "to": "feature2", "type": "crossfade", "dur": 0.5},
                     {"from": "feature2", "to": "statement", "type": "dip-black", "dur": 0.5},
                     {"from": "statement", "to": "end", "type": "crossfade", "dur": 0.5}),
        music=({"bed": "launch_a", "share": (0.0, 1.0)}, {"sting": "riser", "at": 0.07}),
        voice="sparse", finish={"grain": 0.01, "vignette": 0.12}, background="#000", recipe="launch-keynote",
        keywords=("keynote", "apple", "unveil", "launch event", "premium", "minimal", "clean", "elegant", "wwdc",
                  "stage", "announcement"), seconds=(18.0, 50.0))
    doc = Blueprint(
        id="screen-documentary", name="Nature documentary (software)", kind="screen",
        fits="software / web apps; 'nature documentary', 'Attenborough', 'wildlife', 'hushed narrator', calm, slow",
        look="a hushed nature film about the product: slow observational pushes over the real product shown "
             "large, a Latin species lower third, quiet title cards, long crossfades, warm film stock",
        shots=(
            {"id": "open", "share": (0.0, 0.10), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 2-5 word hushed opening line, like the first words of a nature film>",
                        "scrim": 0.0}, "beat": "dawn, silence, one quiet line"},
            {"id": "habitat", "share": (0.10, 0.36), "scene": "kit:base/SCREEN", "product": True,
             "params": {"image": {"asset": "{asset1}"}, "bbox": [0.05, 0.04, 0.8, 0.8]},
             "beat": "the creature in its habitat: the whole product, observed, the camera drifting closer"},
            {"id": "feature1", "share": (0.36, 0.58), "scene": "kit:base/FEATURE", "product": True,
             "params": {"image": {"asset": "{asset2}", "frame": "card"}, "feature": "{feature1}", **WHOLE},
             "beat": "a behaviour, observed close"},
            {"id": "observe", "share": (0.58, 0.66), "scene": "kit:type/title", "product": False,
             "params": {"text": "<a 3-7 word hushed observation about how it behaves, no numbers>", "scrim": 0.0},
             "beat": "the narrator's quiet aside"},
            {"id": "feature2", "share": (0.66, 0.88), "scene": "kit:base/FEATURE", "product": True,
             "params": {"image": {"asset": "{asset3}", "frame": "card"}, "feature": "{feature2}", **WHOLE},
             "beat": "a second behaviour"},
            {"id": "end", "share": (0.88, 1.0), "scene": "kit:type/end-lockup", "product": False,
             "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}", "scrim": 0.0},
             "beat": "the name, quietly"},
        ),
        transitions=({"from": "open", "to": "habitat", "type": "crossfade", "dur": 0.9},
                     {"from": "habitat", "to": "feature1", "type": "crossfade", "dur": 0.8},
                     {"from": "feature1", "to": "observe", "type": "crossfade", "dur": 0.8},
                     {"from": "observe", "to": "feature2", "type": "crossfade", "dur": 0.8},
                     {"from": "feature2", "to": "end", "type": "crossfade", "dur": 0.9}),
        overlays=({"id": "species", "share": (0.14, 0.31), "scene": "kit:type/lower-third",
                   "params": {"title": "{name}", "sub": "<a playful Latin-style species name, 2-4 words>"}},),
        music=({"bed": "dream_a", "share": (0.0, 1.0)},), voice="narrated",
        finish={"grain": 0.035, "vignette": 0.2}, background="#000", recipe="nature-documentary",
        keywords=("nature", "documentary", "attenborough", "wildlife", "narrat", "hushed", "observ", "habitat",
                  "national geographic", "planet earth"), seconds=(18.0, 50.0))
    return [noir, keynote, doc]


def blueprints(*, kits_root: Path | None = None, catalog: Any = None, blender: bool = False) -> list[Blueprint]:
    """Every blueprint usable on this machine (kit scenes installed, Blender present for 3D ones)."""
    root = kits_root or Path(__file__).resolve().parents[2] / "kits"
    out = _recipe_blueprints() + [_style_blueprint(k, root) for k in STYLE_KITS if (root / k / "kit.json").is_file()]
    out += _mood_blueprints()
    if blender:
        out += _blender_blueprints()
    if catalog is not None:
        known = set(catalog.scenes())
        out = [b for b in out if all(s["scene"] in known or s["scene"].startswith("blender:") for s in b.shots)]
    return out


# ------------------------------------------------------------------------------------ facts

def physical(brief: Brief) -> bool:
    return any(a.type in ("video", "model") or a.cutout for a in brief.assets if a.product)


def _product_assets(brief: Brief) -> list[Any]:
    return [a for a in brief.assets if a.product and a.type != "model"]


def _model_asset(brief: Brief) -> str:
    return next((a.name for a in brief.assets if a.product and a.type == "model"), "")


def _strip(a: Any) -> bool:
    """A capture too thin to carry a shot: a header row or a footer sentence cropped by a text match (a real
    keynote film opened on a 2096x136 footer strip because it out-ranked the 1920x1080 desktop capture)."""
    return bool(a.w and a.h and (a.h < 160 or a.w / a.h > 6.0))


def _rank_screens(brief: Brief) -> list[str]:
    """Product screenshots, hero first: desktop captures, then wide screens, feature crops, mobile, strips last."""
    imgs = [a for a in _product_assets(brief) if a.type == "image"]

    def key(a: Any) -> tuple[int, int]:
        n = a.name.lower()
        if _strip(a):
            return (4, 0)
        if "mobile" in n or (a.h and a.w and a.h > a.w * 1.3):
            return (3, 0)
        if "desktop" in n or "1920" in n:
            return (0, -a.w)
        if a.w >= 1400 and a.h and 1.3 <= a.w / a.h <= 2.4:
            return (1, -a.w)
        return (2, 0)
    return [a.name for a in sorted(imgs, key=key)]


def product_color(brief: Brief) -> str:
    """The product's dominant saturated colour (hex) from its poster frame, '' when it has none (grey/white UI).
    Blender scenes repaint a neutral 3D model with it, so the 3D product matches the real one."""
    for a in brief.assets:
        if not a.product or a.type == "model" or not a.thumbnail or not Path(a.thumbnail).is_file():
            continue
        try:
            from PIL import Image
            im = Image.open(a.thumbnail).convert("RGB").resize((96, 54))
            hsv = im.convert("HSV")
        except Exception:  # noqa: BLE001 - optional (PIL), never fatal
            return ""
        bins: dict[int, list[tuple[int, tuple[int, int, int]]]] = {}
        for (h, s, v), rgb in zip(hsv.getdata(), im.getdata(), strict=False):
            if s >= 120 and v >= 70:
                bins.setdefault(h // 12, []).append((s, rgb))
        if not bins:
            return ""
        best = max(bins.values(), key=len)
        if len(best) < 0.03 * 96 * 54:
            return ""
        best.sort(key=lambda x: -x[0])                     # the most saturated half: the paint, not its highlights
        top = [rgb for _, rgb in best[: max(1, len(best) // 2)]]
        r, g, b = (sorted(c[i] for c in top)[len(top) // 2] for i in range(3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return ""


def _paint_tone(hex_color: str) -> str:
    """A sunlit poster colour -> the paint base a 3D studio should use (deeper, more saturated; same hue)."""
    if not is_hex(hex_color):
        return ""
    import colorsys
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.85), min(v, 0.72))
    return "#" + "".join(f"{round(c * 255):02x}" for c in (r, g, b))


def facts(brief: Brief, pick: dict[str, Any] | None = None) -> dict[str, str]:
    """Placeholder values: product, name, tagline, CTA, features, assets, accent, time."""
    p = brief.product
    pick = pick or {}
    name = (p.name if p and p.name else "") or str(pick.get("title") or "") or "The Product"
    one = (p.one_liner if p and p.one_liner else "")
    feats = [f for f in (p.features if p else []) if f and f.lower() not in ("features", "pricing", "see it")]
    prods = _product_assets(brief)
    main = next((a.name for a in prods if a.type == "video"), "") or (prods[0].name if prods else "")
    screens = _rank_screens(brief)
    strips = {a.name for a in _product_assets(brief) if a.type == "image" and _strip(a)}
    good = [s for s in screens if s not in strips] or screens

    def feat_asset(i: int) -> str:
        if not good:
            return main
        f = (feats[i] if i < len(feats) else "").lower()
        words = [w for w in re.findall(r"[a-z]{4,}", f)]
        for s in good:
            if words and any(w[:6] in s.lower() for w in words):
                return s
        rest = [s for s in good[1:] if "mobile" not in s.lower()] or good
        return rest[min(i, len(rest) - 1)]
    tagline = str(pick.get("tagline") or "") or (fit_words(one, 8) if one else "") or "Made to be wanted."
    paint = _paint_tone(product_color(brief)) if _model_asset(brief) else ""
    url = repair.public_url(p.urls if p else [])
    return {
        "product": main, "name": name, "NAME": name.upper()[:14], "tagline": tagline,
        "one_liner": one or tagline, "cta": str(pick.get("cta") or "") or ("Try it today" if screens else "Make it yours"),
        # no known feature -> no label (filler like "Built to delight" read as placeholder text on real films)
        "feature1": fit_words(feats[0], 5) if feats else "",
        "feature2": fit_words(feats[1], 5) if len(feats) > 1 else "",
        "asset1": screens[0] if screens else main, "asset2": feat_asset(0), "asset3": feat_asset(1),
        "url": url, "accent": str(pick.get("accent") or paint or "#E8384A"),
        "time": str(pick.get("time") or "golden"), "model": _model_asset(brief), "paint": paint,
    }


# ------------------------------------------------------------------------------------ choosing (no model)

def eligible(bps: list[Blueprint], brief: Brief) -> list[Blueprint]:
    phys = physical(brief)
    has_model = bool(_model_asset(brief))
    out = []
    for b in bps:
        if b.kind == "physical" and not phys or b.kind == "screen" and phys and not _rank_screens(brief):
            continue
        if b.blender and b.kind == "physical" and not has_model:
            continue
        if b.id.startswith("screen-") and not _rank_screens(brief):
            continue
        out.append(b)
    return out or bps


def rank(bps: list[Blueprint], direction: str, brief: Brief) -> list[tuple[float, Blueprint]]:
    """Blueprints scored against the direction words (keywords, fits, look), best first."""
    d = " " + re.sub(r"\s+", " ", direction.lower()) + " "
    wants_blender = bool(re.search(r"\b(blender|3d|three-d)\b", d))
    scored = []
    for b in eligible(bps, brief):
        s = 0.0
        for kw in b.keywords:
            if kw in d:
                s += 1.0 + 0.15 * len(kw.split())
        words = set(re.findall(r"[a-z]{4,}", f"{b.fits} {b.look} {b.name}".lower()))
        s += 0.25 * len(words & set(re.findall(r"[a-z]{4,}", d)))
        if b.blender:
            s += 0.6 if wants_blender else 0.2       # 3D looks best when the machine has Blender
        if b.exemplar:
            s += 0.3                                  # a proven film behind it
        s += moods.rank_bonus(b, direction)           # the mood's own world first, forbidden worlds last
        scored.append((s, b))
    scored.sort(key=lambda x: -x[0])
    return scored


def default_pick(bps: list[Blueprint], brief: Brief) -> dict[str, Any]:
    """The engine's own choice (no model): best keyword match, else the house default for the product kind."""
    ranked = rank(bps, brief.direction, brief)
    best = ranked[0][1] if ranked and ranked[0][0] > 0.6 else None
    if best is None:
        ok = [(sc, b) for sc, b in ranked if sc >= 0]      # a mood ranks its forbidden worlds below zero
        ids = [b.id for _, b in ok]
        for want in (("studio-reveal", "boss-battle") if physical(brief) else ("device-reveal", "screen-launch")):
            if want in ids:
                best = next(b for _, b in ok if b.id == want)
                break
        best = best or (ok[0][1] if ok else ranked[0][1] if ranked else bps[0])
    d = brief.direction.lower()
    time = next((t for t in TIMES if t in d), "night" if "night" in d or "noir" in d else "golden")
    return {"blueprint": best.id, "time": time, "accent": "#E8384A", "voice": best.voice, "title": "",
            "tagline": "", "cta": "", "why": "engine default (keyword match)"}


# ------------------------------------------------------------------------------------ PICK step

PICK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "blueprint": {"type": "string"}, "time": {"type": "string", "enum": list(TIMES), "default": "golden"},
        "accent": {"type": "string"}, "voice": {"type": "string", "enum": list(VOICES), "default": "sparse"},
        "title": {"type": "string"}, "tagline": {"type": "string"}, "cta": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["blueprint", "time", "voice", "tagline", "cta"],
}


def pick_prompt(brief: Brief, bps: list[Blueprint]) -> tuple[str, str]:
    menu = "\n".join(f"- `{b.id}`: {b.name}. Fits: {b.fits}. Looks like: {b.look}. Voice: {b.voice}."
                     for _, b in rank(bps, brief.direction, brief))
    instr = ("You are the creative director of a short product film. Choose ONE blueprint from the menu that best "
             "matches the user's direction (style, mood, structure), and fill the few choices below. Reply with ONE "
             "JSON object only, no prose:\n"
             '{"blueprint": "<id from the menu>", "time": "dawn|golden|sunset|night|pastel", "accent": "#RRGGBB", '
             '"voice": "none|sparse|narrated", "title": "<product name>", "tagline": "<= 8 words", '
             '"cta": "<= 5 words", "why": "<one sentence>"}\n'
             "Rules: the blueprint id must be copied exactly from the menu. Never invent product facts, numbers or "
             "prices. Narrate (voice `narrated`) when the direction implies a narrator; `none` when it implies "
             "silence or in-world text.")
    p = brief.product
    facts_txt = (f"name: {p.name}\none-liner: {p.one_liner}\nfeatures: {', '.join(p.features)}" if p
                 else "(no product record)")
    media = ", ".join(f"{a.name} ({a.type})" for a in brief.assets if a.product) or "(none)"
    direction = brief.direction.strip() or "(none: make the best film for this product)"
    text = (f"## The user's direction (verbatim)\n\"\"\"{direction}\"\"\"\n\n## Product\n{facts_txt}\n"
            f"media: {media}\n\n## Blueprint menu (best keyword matches first)\n{menu}")
    return instr, text


def check_pick(obj: Any, bps: list[Blueprint], brief: Brief) -> tuple[dict[str, Any], list[str]]:
    """Repair a PICK reply into a complete pick (never fails: missing parts come from the engine default)."""
    base = default_pick(bps, brief)
    fixes: list[str] = []
    if isinstance(obj, str):
        obj, f = loads_lenient(obj)
        fixes += f
    if not isinstance(obj, dict):
        return base, fixes + ["no usable pick: engine default"]
    obj, f = coerce(obj, PICK_SCHEMA)
    fixes += f
    elig = {b.id: b for b in eligible(bps, brief)}
    bid = str(obj.get("blueprint") or "")
    if bid not in elig:
        hit = snap(bid, list(elig), cutoff=0.5)
        if hit is None:
            for b in elig.values():          # "the nature one" / a recipe name / a kit name
                if bid and (bid.lower() in b.name.lower() or bid.lower() in b.id or b.recipe == bid.lower()):
                    hit = b.id
                    break
        fixes.append(f"blueprint {bid!r} -> {hit or base['blueprint']!r}")
        bid = hit or base["blueprint"]
    mood_bp = moods.preferred(brief.direction, elig)
    m = moods.dominant(brief.direction)
    if mood_bp and m is not None and bid not in m.prefer:
        # the direction's mood owns the world: a weak model that picks the generic launch/cinematic film for
        # "noir" or "keynote" gets the mood's own film (the direction must visibly change the film)
        fixes.append(f"blueprint {bid!r} -> {mood_bp!r} ({m.id} world)")
        bid = mood_bp
    pick = dict(base, blueprint=bid)
    pick["voice"] = obj.get("voice") if obj.get("voice") in VOICES else elig[bid].voice
    pick["time"] = obj.get("time") if obj.get("time") in TIMES else base["time"]
    pick["accent"] = obj["accent"].strip() if is_hex(obj.get("accent")) else base["accent"]
    for key, n in (("title", 4), ("tagline", 8), ("cta", 5)):
        v = fit_words(obj.get(key), n)
        if v:
            pick[key] = v.rstrip(".") if key != "tagline" else v
        elif obj.get(key):
            fixes.append(f"{key} too long: kept the default")
    pick["why"] = str(obj.get("why") or "")[:300]
    return pick, fixes


# ------------------------------------------------------------------------------------ WORDS step

def _slots_of(obj: Any, path: str = "") -> list[tuple[str, str]]:
    out = []
    if isinstance(obj, str):
        for m in PLACEHOLDER.finditer(obj):
            out.append((path, m.group(1)))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _slots_of(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _slots_of(v, f"{path}[{i}]")
    return out


def _max_words(meaning: str) -> int:
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*word|<=\s*(\d+)\s*word|(\d+)\s*words?", meaning)
    if m:
        nums = [int(x) for x in m.groups() if x]
        return max(nums)
    return 8


def slots(bp: Blueprint, brief: Brief) -> dict[str, dict[str, Any]]:
    """Every text slot of a blueprint: key -> {meaning, max_words, where}."""
    out: dict[str, dict[str, Any]] = {}
    for kind, items in (("shot", bp.shots), ("overlay", bp.overlays)):
        for it in items:
            if kind == "shot" and _drop_shot(it, brief):
                continue
            for path, meaning in _slots_of(it.get("params") or {}):
                if EVIDENCE.search(meaning):
                    continue
                out[f"{it['id']}.{path}"] = {"meaning": meaning, "max_words": _max_words(meaning),
                                             "where": f"{kind} `{it['id']}` ({it.get('beat') or it['scene']})"}
    return out


def _drop_shot(shot: dict[str, Any], brief: Brief) -> bool:
    """Shots that need real session evidence (diffs, test runs, stats) are dropped when there is none."""
    if brief.digest.strip():
        return False
    return any(EVIDENCE.search(m) for _, m in _slots_of(shot.get("params") or {}))


def voice_windows(bp: Blueprint, seconds: float, voice: str) -> list[dict[str, Any]]:
    """Narration windows per shot (absolute seconds) with a word budget each."""
    if voice == "none":
        return []
    lay = _layout_shots(bp, seconds)
    wins = []
    if len(lay) == 1 and voice == "narrated":           # a oner: split the move into ~5 s windows
        n = max(3, min(6, int(seconds // 5)))
        step = seconds / n
        lay = [{"id": f"w{i + 1}", "t0": round(i * step, 2), "t1": round((i + 1) * step, 2)} for i in range(n)]
    for i, s in enumerate(lay):
        if voice == "sparse" and i not in (0, len(lay) // 2, len(lay) - 2):
            continue
        t0 = max(0.5, float(s["t0"]) + 0.35)
        t1 = float(s["t1"]) - 0.45
        if t1 - t0 < 1.4:
            continue
        wins.append({"id": s["id"], "t": round(t0, 2), "max_words": max(3, int((t1 - t0) * 2.3))})
    return wins


WORDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "object"}, "voiceover": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}}},
    "required": ["text"],
}


def words_prompt(brief: Brief, bp: Blueprint, pick: dict[str, Any], seconds: float) -> tuple[str, str]:
    sl = slots(bp, brief)
    wins = voice_windows(bp, seconds, pick.get("voice") or bp.voice)
    instr = ("You write the WORDS of a short product film whose pictures are already designed. Fill every text slot "
             "and every narration window in the direction's voice. Reply with ONE JSON object only:\n"
             '{"text": {"<slot key>": "<words>", ...}, "voiceover": [{"id": "<window id>", "text": "<one complete '
             'sentence>"}, ...]}\n'
             "Rules: stay within each max_words; complete phrases only; never invent product facts, specs, numbers "
             "or prices; the narration must not repeat the on-screen words; make it specific to THIS direction.")
    p = brief.product
    text = (f"## Direction (verbatim)\n\"\"\"{brief.direction.strip() or '(none)'}\"\"\"\n\n## Product\nname: "
            f"{pick.get('title') or (p.name if p else '')}\ntagline: {pick.get('tagline')}\n"
            f"one-liner: {p.one_liner if p else ''}\nfeatures: {', '.join(p.features) if p else ''}\n\n"
            f"## Film: {bp.name} - {bp.look}\n\n## Text slots\n"
            + ("\n".join(f"- `{k}` (max {v['max_words']} words) in {v['where']}: {v['meaning']}"
                         for k, v in sl.items()) or "(none)")
            + "\n\n## Narration windows" + (f" ({pick.get('voice')})\n" if wins else ": none (voice off)\n")
            + "\n".join(f"- `{w['id']}` at {w['t']:g} s (max {w['max_words']} words)" for w in wins))
    return instr, text


def check_words(obj: Any, bp: Blueprint, brief: Brief, pick: dict[str, Any], seconds: float
                ) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    """Repair a WORDS reply: (slot texts, voiceover lines [{t, text}], fixes). Missing slots stay unfilled
    (assemble() uses safe defaults)."""
    fixes: list[str] = []
    if isinstance(obj, str):
        obj, f = loads_lenient(obj)
        fixes += f
    obj, f = coerce(obj if isinstance(obj, dict) else {}, WORDS_SCHEMA)
    fixes += f
    sl = slots(bp, brief)
    raw = obj.get("text") if isinstance(obj.get("text"), dict) else {}
    if not raw:                                 # some models answer flat: {"hook.label": "..."}
        raw = {k: v for k, v in obj.items() if k in sl}
    texts: dict[str, str] = {}
    for k, v in raw.items():
        key = k if k in sl else snap(str(k), list(sl), cutoff=0.6)
        if key is None:
            fixes.append(f"dropped unknown slot {k!r}")
            continue
        if isinstance(v, list):
            v = " ".join(str(x) for x in v if isinstance(x, (str, int, float)))
        val = fit_words(v if isinstance(v, str) else (v.get("text") if isinstance(v, dict) else v),
                        sl[key]["max_words"])
        if val:
            texts[key] = val
        else:
            fixes.append(f"slot {key}: too long or empty")
    wins = {w["id"]: w for w in voice_windows(bp, seconds, pick.get("voice") or bp.voice)}
    lines = []
    vo = obj.get("voiceover") or []
    for i, it in enumerate(vo if isinstance(vo, list) else []):
        if isinstance(it, str):
            it = {"id": list(wins)[i] if i < len(wins) else "", "text": it}
        if not isinstance(it, dict):
            continue
        wid = str(it.get("id") or "")
        if wid not in wins:
            wid = snap(wid, list(wins), cutoff=0.5) or (list(wins)[i] if i < len(wins) else "")
        if wid not in wins or any(ln["id"] == wid for ln in lines):
            continue
        txt = fit_words(it.get("text"), wins[wid]["max_words"])
        if txt:
            lines.append({"id": wid, "t": wins[wid]["t"], "text": txt})
        else:
            fixes.append(f"voice {wid}: too long for its window")
    lines.sort(key=lambda x: x["t"])
    return texts, [{"t": ln["t"], "text": ln["text"]} for ln in lines], fixes


# ------------------------------------------------------------------------------------ ASSEMBLE (no model)

def _fill(obj: Any, values: dict[str, str]) -> Any:
    if isinstance(obj, str):
        if re.fullmatch(r"\{[A-Za-z0-9_]+\}", obj) and obj[1:-1] in values:
            return values[obj[1:-1]]
        out = obj
        for k, v in values.items():
            out = out.replace("{" + k + "}", v)
        return out
    if isinstance(obj, dict):
        return {k: _fill(v, values) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_fill(v, values) for v in obj]
    return obj


def _put_slots(obj: Any, texts: dict[str, str], prefix: str) -> Any:
    """Replace each `<...>` placeholder string with its slot text (or drop the param when unfilled)."""
    def walk(o: Any, path: str) -> Any:
        if isinstance(o, str):
            if PLACEHOLDER.search(o):
                return texts.get(f"{prefix}.{path}", None)
            return o
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                nv = walk(v, f"{path}.{k}" if path else k)
                if nv is not None:
                    out[k] = nv
            return out
        if isinstance(o, list):
            vals = [walk(v, f"{path}[{i}]") for i, v in enumerate(o)]
            return [v for v in vals if v is not None]
        return o
    return walk(obj, "")


def _layout_shots(bp: Blueprint, seconds: float, brief: Brief | None = None) -> list[dict[str, Any]]:
    """Blueprint shots on the film length; dropped shots' time goes to their neighbours (shares renormalised)."""
    keep = [s for s in bp.shots if brief is None or not _drop_shot(s, brief)] or list(bp.shots[:1])
    total = sum(s["share"][1] - s["share"][0] for s in keep)
    t, out = 0.0, []
    for i, s in enumerate(keep):
        d = (s["share"][1] - s["share"][0]) / total * seconds
        t1 = seconds if i == len(keep) - 1 else round(t + d, 2)
        out.append({**s, "t0": round(t, 2), "t1": round(t1, 2)})
        t = t1
    return out


def _frame_cards(params: dict[str, Any], cards: set[str]) -> dict[str, Any]:
    """Image params that name a picture (game/app screenshot, element crop) get ``frame: card``: shown whole on a
    card, never inside a fake browser window cropped by a push-in."""
    for v in params.values():
        if isinstance(v, dict) and v.get("asset") in cards and not v.get("frame"):
            v["frame"] = "card"
    return params


def assemble(brief: Brief, bp: Blueprint, pick: dict[str, Any], texts: dict[str, str] | None = None,
             voiceover: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The blueprint + pick + words -> ``{"film": ..., "plan": ...}`` (ready for ``check_film``)."""
    texts = texts or {}
    seconds = float(brief.seconds)
    vals = facts(brief, pick)
    if bp.exemplar and not bp.blender:
        ex = next((e for e in rc.exemplars() if e.id == bp.exemplar), None)
        if ex is not None and (physical(brief) == ex.physical):
            fitted = rc.adapt(ex, seconds=seconds, product=vals["product"], name=vals["name"], cta=vals["cta"],
                              tagline=vals["tagline"], aspect=brief.aspect)
            film, plan = fitted["film"], fitted["plan"]
            film["title"] = vals["name"]
            plan["voiceover"] = list(voiceover or [])
            return {"film": film, "plan": plan}
    shots, plan_shots = [], []
    cards = {a.name for a in brief.assets if getattr(a, "frame", "") == "card"}
    for s in _layout_shots(bp, seconds, brief):
        params = _frame_cards(_put_slots(_fill(copy.deepcopy(s.get("params") or {}), vals), texts, s["id"]), cards)
        params = {k: v for k, v in params.items() if not (k in ("paint", "accent", "feature") and not v)}
        if s["scene"] == "kit:type/title" and not params.get("text"):
            params["text"] = vals["name"]          # an unfilled teaser still says something: the name
        if s["scene"].startswith("blender:") and vals["model"] and s["scene"].startswith("blender:studio/"):
            params.setdefault("model", vals["model"])
        if s["scene"] == "blender:meadow/oner":
            params["time_of_day"] = vals["time"] if vals["time"] in ("sunset", "golden", "dawn") else "golden"
            dur = float(s["t1"]) - float(s["t0"])          # never run past the designed move (the camera spline
            ln = float(params.get("length") or ONER_LENGTH)  # extrapolates beyond it)
            params["t_offset"] = round(max(0.0, min(float(params.get("t_offset") or 0.0), ln - dur)), 2)
        shot = {"id": s["id"], "t0": s["t0"], "t1": s["t1"], "scene": s["scene"], "res": s.get("res"),
                "params": params}
        shots.append(shot)
        plan_shots.append({"id": s["id"], "intent": s.get("beat") or "", "product_visible": bool(s.get("product")),
                           "beats": []})
    by_id = {s["id"]: s for s in shots}
    trans = []
    for tr in bp.transitions:
        a, b = by_id.get(tr["from"]), by_id.get(tr["to"])
        if a is None or b is None:
            continue
        d = float(tr.get("dur", 0.6))
        trans.append({"from": a["id"], "to": b["id"], "type": tr["type"], "t": round(a["t1"] - d / 2, 2), "dur": d,
                      "params": dict(tr.get("params") or {})})
    overlays = []
    for o in bp.overlays:
        params = _put_slots(_fill(copy.deepcopy(o.get("params") or {}), vals), texts, o["id"])
        if not any(isinstance(v, str) and v.strip() for v in params.values()):
            continue
        overlays.append({"id": o["id"], "t0": round(o["share"][0] * seconds, 2),
                         "t1": round(o["share"][1] * seconds, 2), "scene": o["scene"], "params": params})
    music: list[dict[str, Any]] = []
    for m in bp.music:
        if "bed" in m:
            music.append({"bed": m["bed"], "t0": round(m["share"][0] * seconds, 2),
                          "t1": round(m["share"][1] * seconds, 2)})
        elif "sting" in m:
            music.append({"sting": m["sting"], "t": round(m["at"] * seconds, 2)})
    film = {"title": vals["name"], "background": bp.background, "shots": shots, "transitions": trans,
            "overlays": overlays, "music": music, "cues": [], "finish": dict(bp.finish)}
    if bp.render:
        film["render"] = copy.deepcopy(bp.render)
    moods.enforce(film, brief.direction, model=vals["model"], paint=vals["paint"], product=vals["product"])
    mood_look(film, brief.direction, hold=product_color(brief) if physical(brief) else "")
    plan = {"shots": plan_shots, "custom_scenes": [], "voiceover": list(voiceover or []),
            "blueprint": bp.id}
    repair.onscreen(film, plan, product=brief.product, name=vals["name"], url=vals["url"])
    return {"film": film, "plan": plan}


MOODS: tuple[tuple[tuple[str, ...], dict[str, Any], dict[str, Any], dict[str, Any]], ...] = (
    # (direction words, finish, render post, mood grade) - the engine's look levers on top of any blueprint or
    # script. The grade (render/post.py `grade`) runs over every frame, so it re-looks the product media and the kit
    # scenes alike: a direction changes the WHOLE look while the product stays recognisable.
    (("vhs", "1980", "80s", "eighties", "infomercial", "tape", "camcorder", "late-night", "public access"),
     {"grain": 0.07, "vignette": 0.35}, {"post": "crt", "post_params": {"crt": {"glow": 0.45, "scanline": 0.32,
                                                                               "curvature": 0.05, "vignette": 0.4}}},
     {"mono": 0.15, "tint": "#ffd9a0", "tint_amount": 0.25, "shift": 7, "wobble": 4, "smear": 1.6, "band": 1.0,
      "contrast": 0.92, "min_scanline": 0.3}),
    (("noir", "detective", "thriller", "crime", "gritty", "mystery"), {"grain": 0.10, "vignette": 0.6}, {},
     {"mono": 1.0, "hold": "{product}", "contrast": 1.25, "rain": 0.9}),     # 1.4 crushed dark worlds to black
    (("anime", "shonen", "shounen", "manga", "mecha"), {"bloom": 0.16, "grain": 0.015, "vignette": 0.12}, {},
     {"saturation": 1.28, "contrast": 1.1}),
    (("dream", "soft", "nostalgic", "pastel", "fairy"), {"bloom": 0.22, "grain": 0.02, "vignette": 0.15}, {},
     {}),
    (("documentary", "nature", "film stock", "35mm", "wildlife"), {"grain": 0.035, "vignette": 0.22}, {},
     {"tint": "#ffe0b0", "tint_amount": 0.10, "contrast": 1.05}),
    (("keynote", "apple", "minimal", "clean", "unveil"), {"max_grain": 0.012}, {}, {"contrast": 1.06}),
)


def merge_render(film: dict[str, Any], render: dict[str, Any]) -> None:
    """Union a post chain block into ``film.render`` (chains + params; existing params win)."""
    if not render or not render.get("post"):
        return
    cur = film.get("render") if isinstance(film.get("render"), dict) else {}
    chains = [c for c in str(cur.get("post") or "").split("+") if c and c != "none"]
    for c in str(render["post"]).split("+"):
        if c and c != "none" and c not in chains:
            chains.append(c)
    params = dict(cur.get("post_params") or {})
    for k, v in (render.get("post_params") or {}).items():
        params.setdefault(k, copy.deepcopy(v))
    film["render"] = {**cur, "post": "+".join(chains), "post_params": params}


def mood_look(film: dict[str, Any], direction: str, *, hold: str = "") -> list[str]:
    """Mood words in the direction -> finish (grain / vignette / bloom), post chain (CRT for VHS asks) and the mood
    grade (noir: black and white with the product's own colour held, hard contrast, rain; VHS: chroma bleed,
    tracking wobble, warm tape tint; keynote: clean). Idempotent; never drops a style kit's own post chain.
    ``hold``: the product's colour (hex) for noir's one colour, '' = pure black and white."""
    d = direction.lower()
    done: list[str] = []
    grade: dict[str, Any] = {}
    for words, finish, render, mood in MOODS:
        if not any(w in d for w in words):
            continue
        fin = film.setdefault("finish", {})
        for k, v in finish.items():
            if k == "max_grain":
                fin["grain"] = min(float(fin.get("grain") or 0.0), float(v))
            else:
                fin[k] = max(float(fin.get(k) or 0.0), float(v))
        merge_render(film, copy.deepcopy(render))
        grade.update(mood)
        done.append(words[0])
    floor = float(grade.pop("min_scanline", 0.0) or 0.0)       # VHS: a kit CRT without scanlines gets them
    if floor and "crt" in str((film.get("render") or {}).get("post", "")).split("+"):
        crt = film["render"].setdefault("post_params", {}).setdefault("crt", {})
        crt["scanline"] = max(float(crt.get("scanline") or 0.0), floor)
    if grade.get("hold") == "{product}":
        if is_hex(hold):
            grade["hold"] = hold
        else:
            grade.pop("hold")
    prev = ((film.get("render") or {}).get("post_params") or {}).get("grade") if isinstance(film.get("render"),
                                                                                           dict) else None
    if grade and isinstance(prev, dict) and prev.get("levels") is not None:
        grade["levels"] = prev["levels"]          # the look guard's measured exposure survives a re-look
    if grade:
        merge_render(film, {"post": "grade", "post_params": {}})
        film["render"]["post_params"]["grade"] = grade
    return done


def treatment_of(bp: Blueprint, pick: dict[str, Any], brief: Brief) -> dict[str, Any]:
    """A minimal treatment record for the critic/revisions (the compose path writes no treatment)."""
    req = [{"text": brief.direction.strip(), "how": f"blueprint {bp.id}: {bp.look}"}] if brief.direction.strip() \
        else []
    return {"title": pick.get("title") or "", "logline": f"{bp.name}: {bp.look}", "recipe": bp.recipe or "custom",
            "blueprint": bp.id, "selling_point": pick.get("tagline") or "", "requirements": req,
            "voice": {"mode": pick.get("voice") or bp.voice, "tone": "in the direction's voice"},
            "acts": [{"name": s["id"], "world": s["scene"], "duration": 0, "beats": [s.get("beat") or ""],
                      "product_role": "hero" if s.get("product") else "setup"} for s in bp.shots],
            "cta": pick.get("cta") or "", "payoff": "the product, name and CTA", "composed": True,
            "pick": {k: v for k, v in pick.items() if k != "why"}}


def floor(brief: Brief, bps: list[Blueprint]) -> tuple[Blueprint, dict[str, Any], dict[str, Any]]:
    """The engine floor: a whole film from the product facts and the direction words, no model call."""
    pick = default_pick(bps, brief)
    bp = next(b for b in bps if b.id == pick["blueprint"])
    return bp, pick, assemble(brief, bp, pick)


def preferred_seconds(bp: Blueprint, seconds: float) -> float:
    lo, hi = bp.seconds
    return max(lo, min(hi, seconds))
