"""Narrative recipes: proven film structures the Director picks and adapts (kit-first shot templates).

A recipe is a structure, not a script: acts with runtime shares, a kit-scene shot template with the params
that make each shot sell, the turn, transitions, a music plan and a narration plan. The treatment names the
recipe it adapts (``treatment.recipe``); the film step gets that recipe's template laid out on the film's
real length, so the default film is built from polished kit scenes and custom scenes fill only real gaps.

Shot ``params`` use placeholders the engine fills: ``{product}`` (product asset name), ``{name}`` (product
name, upper-case for pixel worlds: ``{NAME}``), ``{cta}`` (call to action), ``{tagline}``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RecipeShot:
    """One templated shot: a share of the runtime, a kit scene and its selling params."""
    id: str
    share: tuple[float, float]           # (start, end) as fractions of the film
    scene: str                           # kit scene id (or "custom:<name>" when the recipe needs one)
    params: dict[str, Any] = field(default_factory=dict)
    res: tuple[int, int] | None = None
    product: bool = True                 # the product media is on screen in this shot
    beat: str = ""                       # what the viewer sees (one line)


@dataclass(frozen=True)
class Recipe:
    """A proven film structure."""
    id: str
    name: str
    fits: str                            # directions/products it suits
    arc: str                             # the structure in one line
    turn: float                          # where the turn lands (fraction of the film)
    shots: tuple[RecipeShot, ...]
    transitions: tuple[dict[str, Any], ...] = ()
    overlays: tuple[dict[str, Any], ...] = ()
    music: str = ""
    voice: str = "none"                  # none | sparse | narrated
    pacing: str = ""
    custom_gap: str = ""                 # the one custom scene this recipe may need, if any
    kits: tuple[str, ...] = ()


_END = {"id": "end", "share": (0.86, 1.0), "scene": "kit:type/end-lockup",
        "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}"}}

RECIPES: tuple[Recipe, ...] = (
    Recipe(
        id="boss-battle", name="Boss battle -> BUY -> bloom reveal",
        fits="games, pixel/retro asks, 'turn into another style', physical products, anything that can be a boss",
        arc="the product is the final boss of a 16-bit world; the party picks BUY instead of FIGHT; the pixels "
            "burst into petals and the product is revealed for real in an HD world",
        turn=0.46, kits=("pixel", "nature", "type"),
        shots=(
            RecipeShot("title", (0.0, 0.07), "kit:pixel/title-screen",
                       {"title": "{NAME}", "tagline": "{tagline}", "media": "{product}", "world": "night"},
                       (480, 270), True, "hook: the product on a podium under a gold logo, PRESS START blinks"),
            RecipeShot("walk", (0.07, 0.17), "kit:pixel/dungeon-walk", {"door_label": "LOCKED BOSS"},
                       (480, 270), False, "the party walks a torch-lit corridor to a chained boss door"),
            RecipeShot("boss", (0.17, 0.47), "kit:pixel/boss-battle",
                       {"boss_media": "{product}", "boss_name": "{NAME}", "boss_level": "99", "pick": "BUY",
                        "pick_text": "Make it yours."},
                       (480, 270), True, "the product IS the boss: it attacks, the menu opens, the cursor picks BUY"),
            RecipeShot("field", (0.47, 0.80), "kit:nature/flower-field",
                       {"product": "{product}", "time": "sunset", "camera": "drift", "count": 3},
                       None, True, "petals settle into an anime meadow; the product flies through it, close and big"),
            RecipeShot("hero", (0.80, 1.0), "kit:nature/product-hero",
                       {"product": "{product}", "time": "golden", "title": "top"},
                       None, True, "the product on a hilltop, sun behind it; name + CTA"),
        ),
        transitions=({"from": "title", "to": "walk", "type": "kit:pixel/iris"},
                     {"from": "walk", "to": "boss", "type": "kit:pixel/battle-swirl", "dur": 0.5},
                     {"from": "boss", "to": "field", "type": "kit:pixel/petal-bloom", "dur": 1.4,
                      "note": "start ~0.3 s after the boss shot's BUY click; params.origin = where BUY sits"},
                     {"from": "field", "to": "hero", "type": "crossfade", "dur": 0.8}),
        overlays=({"id": "end", "share": (0.86, 1.0), "scene": "kit:type/end-lockup",
                   "params": {"title": "{name}", "tagline": "{tagline}", "cta": "{cta}"}},),
        music="pixel bed (pixel_b driving / pixel_a bright) for the pixel act ending on a bar line at the BUY click; "
              "a riser sting into the bloom; a warm ambient bed (cinematic_b or a nature/dream bed) after the turn",
        voice="none (the battle dialog carries the words); at most one line on the reveal",
        pacing="hook 2-3 s; walk 4-5 s (cut before it drags); the battle is the longest shot (12-14 s at 45 s); "
               "hold the meadow 12-16 s; end on 6-8 s of hero + lockup",
    ),
    Recipe(
        id="item-get", name="Unboxing / ITEM GET",
        fits="unboxing, 'loot', reveals, collectibles, physical or digital products, short films",
        arc="a quest sets up a need; a chest shakes and bursts open; the product rises as a LEGENDARY item; "
            "the hero equips it and the world changes",
        turn=0.45, kits=("pixel", "nature", "type"),
        shots=(
            RecipeShot("title", (0.0, 0.10), "kit:pixel/title-screen",
                       {"title": "{NAME}", "tagline": "{tagline}", "media": "{product}", "world": "overworld"},
                       (480, 270), True, "hook: logo drops, the product glints on its podium"),
            RecipeShot("quest", (0.10, 0.25), "kit:pixel/quest-log",
                       {"title": "QUEST",
                        "items": [{"text": "<the need, verbatim from the brief>", "status": "active"}],
                        "world": "night"}, (480, 270), False, "the need, as a quest"),
            RecipeShot("chest", (0.25, 0.50), "kit:pixel/item-get",
                       {"media": "{product}", "name": "{NAME}", "desc": "{tagline}", "rarity": "LEGENDARY"},
                       (480, 270), True, "the chest bursts open, the product rises: ITEM GET!"),
            RecipeShot("shop", (0.50, 0.70), "kit:pixel/shop",
                       {"media": "{product}", "name": "{NAME}", "pick": "BUY"},
                       (480, 270), True, "the shopkeeper offers it; the cursor clicks BUY; coins fly"),
            RecipeShot("hero", (0.70, 1.0), "kit:nature/product-hero",
                       {"product": "{product}", "time": "golden", "title": "top"},
                       None, True, "out of the game: the product, real and lit"),
        ),
        transitions=({"from": "title", "to": "quest", "type": "kit:pixel/screen-slide"},
                     {"from": "quest", "to": "chest", "type": "kit:pixel/iris"},
                     {"from": "chest", "to": "shop", "type": "kit:pixel/screen-slide"},
                     {"from": "shop", "to": "hero", "type": "kit:pixel/petal-bloom", "dur": 1.4}),
        overlays=(_END,),
        music="pixel_a (bright) for the quest, a level_up/power_up sting on ITEM GET!, warm ambient after the bloom",
        voice="none or sparse", pacing="the chest burst is the hero impact; hold the ITEM GET! frame >= 2 s",
    ),
    Recipe(
        id="race-chase", name="Race / chase",
        fits="speed, cars, performance, 'faster than', competitive products",
        arc="the product lines up against rivals, falls behind, then overtakes everything on the final stretch "
            "and crosses the line first; podium reveal",
        turn=0.6, kits=("pixel", "nature", "type"),
        shots=(
            RecipeShot("hook", (0.0, 0.08), "custom:race", {"car": "{product}", "phase": "flyby"}, (480, 270), True,
                       "hook: the product blasts past the camera"),
            RecipeShot("grid", (0.08, 0.25), "custom:race", {"car": "{product}", "phase": "grid"}, (480, 270), True,
                       "the starting grid; lights go red, red, red, GO"),
            RecipeShot("chase", (0.25, 0.60), "custom:race", {"car": "{product}", "phase": "chase"}, (480, 270), True,
                       "behind, then side by side; one big overtake on the beat"),
            RecipeShot("finish", (0.60, 0.72), "custom:race", {"car": "{product}", "phase": "finish"}, (480, 270),
                       True, "the product crosses the line first: flag, burst, P1"),
            RecipeShot("hero", (0.72, 1.0), "kit:nature/product-hero",
                       {"product": "{product}", "time": "golden", "title": "top"}, None, True, "victory lap / podium"),
        ),
        transitions=({"from": "finish", "to": "hero", "type": "kit:pixel/petal-bloom", "dur": 1.2},),
        overlays=(_END,),
        music="driving bed (pixel_b or terminal_a/b) with the overtake on a downbeat; impact at the finish line",
        voice="none", pacing="cut on every bar during the chase; slow down only after the finish line",
        custom_gap="one custom `race` scene with a `phase` param, composed from ctx.kit('pixel') blocks "
                   "(worlds.* parallax, productSprite, motion, ui.ribbon) - no kit has a race",
    ),
    Recipe(
        id="heist", name="Heist",
        fits="playful premium products, 'steal the show', limited editions, night/neon moods",
        arc="the crew plans the job, sneaks past the guards, cracks the vault and the prize inside is the product; "
            "they get away with it into the night",
        turn=0.5, kits=("pixel", "nature", "type"),
        shots=(
            RecipeShot("plan", (0.0, 0.18), "kit:pixel/quest-log",
                       {"title": "THE JOB", "items": [{"text": "Get in", "status": "done"},
                                                      {"text": "Crack the vault", "status": "active"},
                                                      {"text": "Take the {NAME}", "status": "todo"}],
                        "world": "night"}, (480, 270), False, "the plan on a quest log"),
            RecipeShot("sneak", (0.18, 0.32), "kit:pixel/dungeon-walk",
                       {"door_label": "VAULT", "party": ["rogue", "mage", "knight"]}, (480, 270), False,
                       "the crew creeps to the vault door; the chains snap"),
            RecipeShot("vault", (0.32, 0.55), "kit:pixel/item-get",
                       {"media": "{product}", "name": "{NAME}", "rarity": "PRICELESS", "banner": "JACKPOT!"},
                       (480, 270), True, "the vault opens: the prize is the product"),
            RecipeShot("getaway", (0.55, 0.82), "kit:nature/flower-field",
                       {"product": "{product}", "time": "night", "camera": "push", "count": 2}, None, True,
                       "the getaway: the product streaks over a moonlit meadow"),
            RecipeShot("hero", (0.82, 1.0), "kit:nature/product-hero",
                       {"product": "{product}", "time": "dawn", "title": "top"}, None, True,
                       "dawn: they got away with it"),
        ),
        transitions=({"from": "sneak", "to": "vault", "type": "kit:pixel/iris"},
                     {"from": "vault", "to": "getaway", "type": "kit:pixel/petal-bloom", "dur": 1.4}),
        overlays=(_END,),
        music="tense minor chiptune (pixel_b) -> darksynth (terminal_a) for the getaway; impact on the vault opening",
        voice="none or one wry line", pacing="hold the vault reveal; the getaway is fast",
        custom_gap="the hook frame 0-2 s must tease the product (e.g. the plan's photo of the target)",
    ),
    Recipe(
        id="origin-story", name="Origin story (how it was built)",
        fits="software built in the session, 'tell the story', dev tools, making-of with a product payoff",
        arc="a real problem in the user's words; the plan; the build in the agent's real code and diffs; the red "
            "test turns green; the product, alive",
        turn=0.62, kits=("launch", "cinematic", "type"),
        shots=(
            RecipeShot("hook", (0.0, 0.10), "kit:launch/HOOK", {"hero": {"kind": "image", "asset": "{product}"}},
                       None, True, "the finished product, first"),
            RecipeShot("problem", (0.10, 0.22), "kit:launch/PROBLEM", {"text": "<the user's prompt, verbatim>"},
                       None, False, "the ask, typed"),
            RecipeShot("build", (0.22, 0.45), "kit:launch/DIFF", {"path": "<real file>", "hunks": "<real hunks>"},
                       None, False, "the real change lands"),
            RecipeShot("proof", (0.45, 0.62), "kit:launch/BEFORE_AFTER",
                       {"before": {"kind": "terminal"}, "after": {"kind": "terminal"}}, None, False,
                       "red tests turn green"),
            RecipeShot("feature", (0.62, 0.86), "kit:launch/FEATURE",
                       {"image": {"asset": "{product}"}, "feature": "<one real feature>"}, None, True,
                       "the product doing its best trick"),
            RecipeShot("end", (0.86, 1.0), "kit:launch/END", {"title": "{name}", "cta": "{cta}"}, None, True,
                       "lockup + CTA"),
        ),
        transitions=({"from": "proof", "to": "feature", "type": "zoom-through", "dur": 0.6},),
        music="launch_a/launch_b (or cinematic_a for a darker origin); the green test lands on a downbeat",
        voice="sparse: 3-5 short lines carry the story", pacing="evidence shots 3-5 s; the product shots longer",
    ),
    Recipe(
        id="day-in-the-life", name="Day in the life",
        fits="lifestyle, habits, productivity apps, everyday objects, calm moods",
        arc="dawn to night: the product is there at every moment of a day; the day ends better because of it",
        turn=0.5, kits=("nature", "launch", "cinematic", "type"),
        shots=(
            RecipeShot("dawn", (0.0, 0.18), "kit:nature/sky-reveal", {"product": "{product}", "time": "dawn"}, None,
                       True, "dawn sky tilts down to the world; the product is already there"),
            RecipeShot("morning", (0.18, 0.40), "kit:launch/FEATURE",
                       {"image": {"asset": "{product}"}, "feature": "<morning use>"}, None, True, "morning: first use"),
            RecipeShot("noon", (0.40, 0.62), "kit:nature/flower-field",
                       {"product": "{product}", "time": "pastel", "count": 2}, None, True, "midday: in its element"),
            RecipeShot("dusk", (0.62, 0.84), "kit:nature/product-hero",
                       {"product": "{product}", "time": "golden", "title": "top"}, None, True, "golden hour"),
            RecipeShot("night", (0.84, 1.0), "kit:nature/flower-field",
                       {"product": "{product}", "time": "night", "count": 1, "title": "center"}, None, True,
                       "night; name + CTA"),
        ),
        overlays=({"id": "end", "share": (0.86, 1.0), "scene": "kit:type/end-lockup",
                   "params": {"title": "{name}", "cta": "{cta}"}},),
        music="one warm ambient bed (cinematic_b) that blooms at the golden-hour turn",
        voice="sparse or narrated: one line per time of day", pacing="unhurried; every shot >= 5 s",
    ),
    Recipe(
        id="before-after", name="Before / after transformation",
        fits="'fix', 'upgrade', redesigns, performance wins, cleaning/tidying products",
        arc="the before world is grey, cramped and broken; one action flips it; the after world is vivid and "
            "the product is the reason",
        turn=0.45, kits=("launch", "nature", "pixel", "type"),
        shots=(
            RecipeShot("before", (0.0, 0.22), "kit:launch/PROBLEM", {"text": "<the pain, verbatim>"}, None, False,
                       "before: the pain"),
            RecipeShot("versus", (0.22, 0.45), "kit:launch/BEFORE_AFTER",
                       {"before": {"kind": "image"}, "after": {"kind": "image", "asset": "{product}"}}, None, True,
                       "side by side; the after lifts off"),
            RecipeShot("after", (0.45, 0.80), "kit:nature/flower-field",
                       {"product": "{product}", "time": "pastel", "count": 2}, None, True,
                       "after: the world in full colour, the product flying"),
            RecipeShot("hero", (0.80, 1.0), "kit:nature/product-hero", {"product": "{product}", "title": "top"},
                       None, True, "hero + CTA"),
        ),
        transitions=({"from": "versus", "to": "after", "type": "dip-white", "dur": 0.6},),
        overlays=(_END,),
        music="muted first half (cinematic_a intro), the bed opens up exactly at the flip; impact on the flip",
        voice="sparse", pacing="make the before short and ugly; the after long and beautiful",
    ),
    Recipe(
        id="speedrun", name="Speedrun",
        fits="'speedrun', 'how fast', built-in-minutes stories, competitive devs",
        arc="the timer starts; splits fly (plan, code, tests); a PB beats the clock; the product is the trophy",
        turn=0.7, kits=("pixel", "launch", "type"),
        shots=(
            RecipeShot("start", (0.0, 0.12), "kit:pixel/title-screen",
                       {"title": "{NAME}", "tagline": "ANY% SPEEDRUN", "media": "{product}", "press": "START RUN"},
                       (480, 270), True, "GO"),
            RecipeShot("splits", (0.12, 0.55), "kit:pixel/quest-log",
                       {"title": "SPLITS", "items": "<real plan items>"}, (480, 270), False, "splits tick"),
            RecipeShot("tests", (0.55, 0.72), "kit:pixel/TERMINAL", {"data": "<real test run>"}, (480, 270), False,
                       "PASS!"),
            RecipeShot("trophy", (0.72, 1.0), "kit:pixel/item-get",
                       {"media": "{product}", "name": "{NAME}", "banner": "NEW PB!"}, (480, 270), True,
                       "the product is the trophy"),
        ),
        overlays=({"id": "timer", "share": (0.0, 0.86), "scene": "kit:type/speedrun-timer", "params": {}}, _END),
        music="pixel_b, cut on every bar; level_up sting on the PB", voice="none", pacing="fast: 2-4 s per split",
    ),
    Recipe(
        id="nature-documentary", name="Nature documentary",
        fits="'nature documentary', 'Attenborough', 'wildlife', calm wonder, observational tone",
        arc="a hushed narrator observes the product as a rare creature in its habitat: first sighting, its "
            "behaviours (the features, verbatim), one dramatic moment, and the closing wide as the sun sets",
        turn=0.6, kits=("nature", "cinematic", "launch", "type"),
        shots=(
            RecipeShot("habitat", (0.0, 0.16), "kit:nature/sky-reveal", {"product": "{product}", "time": "dawn"},
                       None, True, "dawn over the meadow; the narrator sets the scene; a first glimpse"),
            RecipeShot("sighting", (0.16, 0.36), "kit:cinematic/screen-push",
                       {"image": "{product}", "kicker": "FIRST SIGHTING", "caption": "<species name>"}, None, True,
                       "the creature, close: the product itself, lit like rare footage"),
            RecipeShot("behaviour", (0.36, 0.60), "kit:launch/FEATURE",
                       {"image": {"asset": "{product}"}, "feature": "<observed behaviour = a real feature>"}, None,
                       True, "its behaviour, observed: one real feature in action"),
            RecipeShot("migration", (0.60, 0.84), "kit:nature/flower-field",
                       {"product": "{product}", "time": "golden", "camera": "drift", "count": 3}, None, True,
                       "the turn: the great migration across the meadow"),
            RecipeShot("closing", (0.84, 1.0), "kit:nature/product-hero",
                       {"product": "{product}", "time": "sunset", "title": "top"}, None, True,
                       "sunset; the narrator's last line; name + CTA"),
        ),
        transitions=({"from": "habitat", "to": "sighting", "type": "dip-black", "dur": 0.6},
                     {"from": "behaviour", "to": "migration", "type": "crossfade", "dur": 1.0}),
        overlays=({"id": "species", "share": (0.18, 0.30), "scene": "kit:type/lower-third",
                   "params": {"title": "{name}", "sub": "<a playful Latin-style species name>"}},
                  {"id": "end", "share": (0.88, 1.0), "scene": "kit:type/end-lockup",
                   "params": {"title": "{name}", "cta": "{cta}"}}),
        music="one warm ambient bed (cinematic_b), low under the narration; one swell at the migration",
        voice="narrated: 5-8 hushed, wry observational lines in the documentary register ('Here, in the long grass, "
              "something stirs.'), never over 8 words per second of window; leave silences",
        pacing="slow and patient; shots 6-10 s; let the narrator breathe",
    ),
    Recipe(
        id="launch-keynote", name="Launch keynote",
        fits="the default for software and web apps: 'launch video', 'promo', 'trailer'",
        arc="tease the best moment, name it, show 2-3 real features, prove it with real numbers, call to action",
        turn=0.3, kits=("launch", "cinematic", "type"),
        shots=(
            RecipeShot("hook", (0.0, 0.10), "kit:launch/HOOK", {"hero": {"kind": "image", "asset": "{product}"}},
                       None, True, "the scroll-stopper"),
            RecipeShot("title", (0.10, 0.25), "kit:launch/TITLE",
                       {"title": "{name}", "tagline": "{tagline}", "hero": {"kind": "image", "asset": "{product}"}},
                       None, True, "name + thesis"),
            RecipeShot("feature1", (0.25, 0.48), "kit:launch/FEATURE",
                       {"image": {"asset": "{product}"}, "feature": "<real feature>"}, None, True, "feature one"),
            RecipeShot("feature2", (0.48, 0.70), "kit:cinematic/screen-push",
                       {"image": "{product}", "caption": "<real feature>"}, None, True, "feature two, cinematic"),
            RecipeShot("proof", (0.70, 0.85), "kit:launch/STATS", {"stats": "<real session stats>"}, None, False,
                       "real numbers"),
            RecipeShot("end", (0.85, 1.0), "kit:launch/END", {"title": "{name}", "cta": "{cta}"}, None, True, "CTA"),
        ),
        music="launch_a or launch_b; the title lands on the first drop", voice="sparse",
        pacing="2-5 s per shot; one push per shot",
    ),
)


def get(recipe_id: str) -> Recipe | None:
    """The recipe with this id (or None)."""
    rid = str(recipe_id or "").strip().lower()
    return next((r for r in RECIPES if r.id == rid), None)


def suggest(direction: str, *, physical: bool) -> list[str]:
    """Recipe ids whose ``fits``/name words appear in the direction, best first (a hint, not a rule)."""
    words = set(re.findall(r"[a-z]{4,}", direction.lower()))
    scored = []
    for r in RECIPES:
        cand = set(re.findall(r"[a-z]{4,}", f"{r.id} {r.name} {r.fits}".lower()))
        score = len(words & cand) + (0.5 if r.id in direction.lower() else 0.0)
        if not physical and r.id in ("launch-keynote", "origin-story"):
            score += 0.3
        if physical and r.id == "boss-battle":
            score += 0.3
        scored.append((score, r.id))
    return [rid for s, rid in sorted(scored, key=lambda x: -x[0]) if s > 0][:3]


def overview(*, physical: bool | None = None) -> str:
    """One paragraph per recipe for the treatment step (recipes with a proven film for this product type marked)."""
    lines = ["## Narrative recipes (proven structures; pick the one that fits and ADAPT it, or say `custom`)"]
    proven = {e.recipe: e for e in exemplars() if physical is None or e.physical == physical}
    for r in RECIPES:
        scenes = ", ".join(dict.fromkeys(s.scene for s in r.shots))
        ex = proven.get(r.id)
        star = (f" **PROVEN FILM available ({ex.id}{f', critic {ex.critic:.1f}/10' if ex.critic else ''}): "
                f"choosing this recipe starts the film from a hand-polished, critic-tested film.**" if ex else "")
        lines.append(f"- `{r.id}` - **{r.name}**: {r.arc}. Fits: {r.fits}. Turn at {r.turn:.0%}. "
                     f"Voice: {r.voice.split(':')[0]}. Built from: {scenes}."
                     + (f" Needs: {r.custom_gap}." if r.custom_gap else "") + star)
    if proven:
        lines.append("A recipe with a PROVEN FILM gives the highest craft the kits reach today. When it fits the "
                     "direction, prefer it and make the film bespoke through its story, words, worlds and colours; "
                     "pick another structure only when the direction clearly asks for one. If you do, acts that use "
                     "the proven film's kits still reuse its shots.")
    return "\n".join(lines)


def _fill(obj: Any, values: dict[str, str]) -> Any:
    if isinstance(obj, str):
        out = obj
        for k, v in values.items():
            out = out.replace("{" + k + "}", v)
        return out
    if isinstance(obj, dict):
        return {k: _fill(v, values) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_fill(v, values) for v in obj]
    return obj


def template(recipe: Recipe, *, seconds: float, product: str, name: str, cta: str = "", tagline: str = "",
             available: set[str] | None = None) -> dict[str, Any]:
    """The recipe's shot list laid out on the real film length, placeholders filled (a starting film.json)."""
    values = {"product": product or "<product asset>", "name": name or "<product name>",
              "NAME": (name or "<PRODUCT NAME>").upper()[:14], "cta": cta or "<call to action>",
              "tagline": tagline or "<one-line benefit>"}
    shots = []
    for s in recipe.shots:
        shot: dict[str, Any] = {"id": s.id, "t0": round(s.share[0] * seconds, 2), "t1": round(s.share[1] * seconds, 2),
                                "scene": s.scene, "res": list(s.res) if s.res else None,
                                "params": _fill(s.params, values), "product_visible": s.product, "beat": s.beat}
        if available is not None and s.scene.startswith("kit:") and s.scene not in available:
            shot["note"] = "this kit scene is not installed: pick the closest catalog scene"
        shots.append(shot)
    by_id = {s["id"]: s for s in shots}
    trans = []
    for tr in recipe.transitions:
        a = by_id.get(tr["from"])
        if a is None or tr["to"] not in by_id:
            continue
        d = float(tr.get("dur", 0.6))
        trans.append({**{k: v for k, v in tr.items() if k != "note"}, "t": round(a["t1"] - d / 2, 2), "dur": d,
                      **({"note": tr["note"]} if tr.get("note") else {})})
    overlays = [{"id": o["id"], "t0": round(o["share"][0] * seconds, 2), "t1": round(o["share"][1] * seconds, 2),
                 "scene": o["scene"], "params": _fill(o["params"], values)} for o in recipe.overlays]
    return {"shots": shots, "transitions": trans, "overlays": overlays}


def detail(recipe: Recipe, *, seconds: float, product: str, name: str, cta: str = "", tagline: str = "",
           available: set[str] | None = None) -> str:
    """Prompt text for the film step: the chosen recipe as a concrete starting film."""
    tpl = template(recipe, seconds=seconds, product=product, name=name, cta=cta, tagline=tagline,
                   available=available)
    return (f"## Chosen recipe: `{recipe.id}` ({recipe.name})\n{recipe.arc}.\n"
            f"- Turn at ~{recipe.turn * seconds:.1f} s. Pacing: {recipe.pacing}\n- Music: {recipe.music}\n"
            f"- Voice: {recipe.voice}\n" + (f"- Custom scene allowed for: {recipe.custom_gap}\n" if recipe.custom_gap
                                             else "- Every shot below is a polished kit scene: no custom scene is "
                                                  "needed unless the treatment's signature moment demands one.\n")
            + "Starting film (laid out on this film's length; keep its kit scenes and selling params, adapt timing,"
              " text and params to the treatment, fill every <...>):\n```json\n"
            + json.dumps(tpl, indent=1, ensure_ascii=False) + "\n```")


# ------------------------------------------------------------------------------------ proven films (exemplars)
#
# A recipe tells the model the STRUCTURE; an exemplar is a whole film.json that was polished by hand over several
# preview rounds and scored by the same vision critic. It is the highest craft the kits reach today: the film step
# adapts it (names, text, worlds) instead of inventing camera moves, flyer depths and lockup layouts from scratch.

EXEMPLAR_DIR = Path(__file__).with_name("exemplars")
_TIME_KEYS = ("t", "t0", "t1")


@dataclass(frozen=True)
class Exemplar:
    id: str
    recipe: str
    aspect: str
    seconds: float
    source: str
    fits: str
    why: tuple[str, ...]
    film: dict[str, Any]
    plan: dict[str, Any]
    critic: float | None = None          # mean rubric score the Director's critic gave it (None = not measured)
    physical: bool = True                # made for a physical product video/cutout

    def kits(self) -> set[str]:
        return {str(s.get("scene", "")).split("/")[0].removeprefix("kit:") for s in self.film.get("shots") or []
                if str(s.get("scene", "")).startswith("kit:")}


def exemplars() -> list[Exemplar]:
    out = []
    for p in sorted(EXEMPLAR_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append(Exemplar(d["id"], d["recipe"], d.get("aspect", "16:9"), float(d["seconds"]),
                                d.get("source", ""), d.get("fits", ""), tuple(d.get("why") or ()), d["film"],
                                d.get("plan") or {}, d.get("critic"), bool(d.get("physical", True))))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def exemplar_for(recipe_id: str, *, aspect: str = "16:9", physical: bool = True) -> Exemplar | None:
    """The proven film for a recipe (same aspect preferred; physical/screen products must match)."""
    cands = [e for e in exemplars() if e.recipe == recipe_id and e.physical == physical]
    cands.sort(key=lambda e: (e.aspect != aspect, -(e.critic or 0)))
    return cands[0] if cands else None


def _scale_times(obj: Any, k: float, key: str = "") -> Any:
    if isinstance(obj, dict):
        out = {}
        for kk, v in obj.items():
            if kk in _TIME_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[kk] = round(v * k, 2)
            elif kk == "timings" and isinstance(v, dict):
                out[kk] = {a: round(b * k, 2) if isinstance(b, (int, float)) else b for a, b in v.items()}
            else:
                out[kk] = _scale_times(v, k, kk)
        return out
    if isinstance(obj, list):
        if key == "rack":
            return [[round(x[0] * k, 2), *x[1:]] if isinstance(x, list) and x else x for x in obj]
        return [_scale_times(v, k) for v in obj]
    return obj


def adapt(ex: Exemplar, *, seconds: float, product: str, name: str, cta: str = "", tagline: str = "",
          aspect: str = "") -> dict[str, Any]:
    """The exemplar's film + plan on this film's length with this product (placeholders filled)."""
    values = {"product": product or "<product asset>", "name": name or "<product name>",
              "NAME": (name or "<PRODUCT NAME>").upper()[:14], "cta": cta or "<call to action>",
              "tagline": tagline or "<one-line benefit>"}
    film = _fill(ex.film, values)
    k = seconds / ex.seconds if ex.seconds else 1.0
    if abs(k - 1.0) > 0.02:
        film = _scale_times(film, k)
    film["dur"] = round(seconds, 2)
    if aspect and aspect != ex.aspect:                  # shot render sizes belong to the exemplar's aspect
        for s in film.get("shots") or []:
            s.pop("res", None)
    return {"film": film, "plan": _fill(ex.plan, values)}


def exemplar_text(ex: Exemplar, *, seconds: float, product: str, name: str, cta: str = "", tagline: str = "",
                  whole: bool = True, aspect: str = "") -> str:
    """Prompt block: the proven film to adapt (``whole``) or to borrow proven shots from."""
    fitted = adapt(ex, seconds=seconds, product=product, name=name, cta=cta, tagline=tagline, aspect=aspect)
    score = f"the critic scored it {ex.critic:.1f}/10 - " if ex.critic else ""
    head = (f"## PROVEN FILM `{ex.id}` ({score}{ex.source})\n"
            + ("ADAPT THIS FILM. It is the highest craft the kits reach: its camera moves, flyer depths/sizes/paths, "
               "timings, transitions, lockup layout and music cue sheet were tuned by eye over many preview rounds. "
               "Keep its shots, kit scenes and params unless the treatment explicitly needs something else; change "
               "names, on-screen text, colours/time of day and the acts the treatment rewrites. Every change you make "
               "must be an improvement you can name. Do not add custom scenes unless the treatment's signature moment "
               "cannot be told with these shots.\n" if whole else
               "BORROW FROM THIS FILM: for every act of your film that uses the same kit, start from its shots "
               "(scene + params, verbatim where they fit) instead of inventing params - they are proven on screen.\n")
            + "Why it works:\n" + "\n".join(f"- {w}" for w in ex.why))
    return head + "\n```json\n" + json.dumps(fitted, indent=1, ensure_ascii=False) + "\n```"
