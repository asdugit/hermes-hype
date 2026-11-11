"""Mood -> world rules: a direction's mood picks the WORLD, not only the grade.

The grade (compose.MOODS -> render/post.py ``grade``) re-looks every frame, but it cannot fix a wrong world: a car
noir built from flower fields scored 4/10 (B&W meadow, pink flowers kept by the colour hold), an anime opening
ended in the same pastel meadow as the nature documentary. These rules are engine-level and apply on every path:

- ``rank_bonus``: the compose menu ranks the mood's own blueprints first and pushes blueprints built on worlds the
  mood forbids to the bottom (the engine's keyword default follows the same ranking);
- ``prompt_block``: the strong path's treatment/film prompts get the mood's world rule in plain words;
- ``enforce``: every film reply (free path, revisions, resumed scripts, composed films) is rewritten so forbidden
  worlds are swapped for the mood's world (car noir: meadow / flower-field shots -> the Blender studio at night),
  the mood's scene params are forced (studio env ``noir``, meadow ``dawn`` for documentaries, typewriter titles
  for noir), forbidden transitions become dips/cuts and the bed matches the mood.

Pure Python, no I/O.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MoodWorld:
    id: str
    words: tuple[str, ...]                         # direction words (substring match on the lowered direction)
    world: str                                     # the rule, in words, for the prompts
    prefer: tuple[str, ...] = ()                   # blueprint ids, best first
    avoid: tuple[str, ...] = ()                    # scene id prefixes this mood never uses (shots)
    avoid_transitions: tuple[str, ...] = ()        # transition type prefixes -> ``dip``
    dip: str = "dip-black"
    params: dict[str, dict[str, Any]] = field(default_factory=dict)   # scene prefix -> forced params
    swap: tuple[tuple[str, str], ...] = ()          # (avoided scene prefix, replacement scene) for physical products
    beds: tuple[str, ...] = ()                     # allowed bed id prefixes (others -> beds[0] + "_a" ...)
    bed: str = ""                                  # the replacement bed


WORLDS: tuple[MoodWorld, ...] = (
    MoodWorld(
        "noir", ("noir", "detective", "hard-boiled", "hardboiled", "crime", "gritty", "mystery", "thriller",
                 "private eye", "femme fatale"),
        world=("film noir = a rain-soaked NIGHT: black frame, ONE hard key light, smoke/haze, a wet mirror floor, "
               "venetian-blind light, black and white with only the product's own colour kept, typewriter titles. "
               "For a physical product with a 3D model use `blender:studio/product_hero` (env `noir`; moves "
               "orbit/dolly/macro/turntable) - NEVER a meadow, sky, flower field, daylight, pastel or a bright "
               "stage; for a screen product the dark `kit:cinematic/*` room."),
        prefer=("studio-noir", "screen-noir", "screen-cinematic"),
        avoid=("kit:nature/", "blender:meadow/", "kit:pixel/", "kit:launch/", "kit:ink/", "kit:comic/"),
        avoid_transitions=("kit:nature/", "kit:pixel/", "blender:transitions/petal", "kit:comic/", "kit:ink/"),
        params={"blender:studio/": {"env": "noir", "haze": 1.0},
                "kit:type/": {"theme": "noir"}, "kit:type/title": {"reveal": "type"}},
        swap=(("kit:nature/", "blender:studio/product_hero"), ("blender:meadow/", "blender:studio/product_hero")),
        beds=("cinematic_a", "terminal_"), bed="cinematic_a"),
    MoodWorld(
        "anime", ("anime", "shonen", "shounen", "manga", "mecha", "j-pop", "jpop", "90s opening", "tv opening"),
        world=("an anime TV OPENING, not a documentary: high-energy hard cuts every 1-3 s between dynamic camera "
               "moments (in the Blender meadow: several short `blender:meadow/oner` shots at different `t_offset`s "
               "- the crane, the swoop, the flight alongside, the hero pass - hard-cut, never one slow take), "
               "bold kinetic title cards in big display type (`kit:type/title`, one or two words, theme `anime`), "
               "a saturated sunset sky, an energetic bed; never the slow pastel golden-hour drift, never the "
               "dark glass room."),
        prefer=("anime-opening",),
        avoid=("kit:cinematic/", "kit:terminal/", "kit:blueprint/"),
        params={"blender:meadow/": {"time_of_day": "sunset"}, "kit:type/": {"theme": "anime"},
                "kit:nature/": {"time": "sunset"}},
        beds=("launch_", "pixel_boss", "comic_", "dream_b"), bed="launch_b"),
    MoodWorld(
        "documentary", ("documentary", "nature doc", "wildlife", "attenborough", "hushed", "national geographic",
                        "planet earth", "field study", "habitat"),
        world=("a nature documentary: the product observed like a rare animal in its habitat at DAWN - slow, "
               "observational camera, long takes and few cuts (crossfades), a hushed narrator, a species lower "
               "third; in the Blender meadow (`blender:meadow/oner`, `time_of_day` dawn) when Blender is "
               "available; never pop type, hard energetic cuts or neon."),
        prefer=("meadow-documentary", "nature-documentary"),
        avoid=("kit:pixel/", "kit:comic/", "kit:terminal/", "kit:launch/"),
        params={"blender:meadow/": {"time_of_day": "dawn"}, "kit:nature/": {"time": "dawn"}},
        beds=("dream_a", "cinematic_b"), bed="dream_a"),
    MoodWorld(
        "keynote", ("keynote", "apple", "unveil", "launch event", "wwdc", "steve jobs", "on stage"),
        world=("a product KEYNOTE: a black stage, one idea at a time in huge clean white type, the real product "
               "shown LARGE (a 3D laptop/phone reveal when Blender is available, else the full product screen "
               "pushing in), calm crossfades and dips, an upbeat bed; never pixel art, comic panels, a meadow or "
               "a phosphor terminal."),
        prefer=("device-reveal", "studio-reveal", "screen-keynote"),
        avoid=("kit:pixel/", "kit:comic/", "kit:ink/", "kit:nature/", "kit:terminal/", "blender:meadow/"),
        avoid_transitions=("kit:pixel/", "kit:comic/", "kit:ink/", "kit:nature/", "blender:transitions/petal"),
        dip="dip-black", beds=("launch_", "cinematic_", "dream_"), bed="launch_a"),
)


def detect(direction: str) -> list[MoodWorld]:
    """Mood worlds named by the direction, strongest first (word hits; ties keep table order)."""
    d = " " + re.sub(r"\s+", " ", (direction or "").lower()) + " "
    hits = []
    for i, m in enumerate(WORLDS):
        n = sum(1 for w in m.words if w in d)
        if n:
            hits.append((-n, i, m))
    hits.sort(key=lambda x: (x[0], x[1]))
    return [m for _, _, m in hits]


def dominant(direction: str) -> MoodWorld | None:
    ms = detect(direction)
    return ms[0] if ms else None


def _uses(scene: str, prefixes: tuple[str, ...]) -> bool:
    return any(scene.startswith(p) for p in prefixes)


def preferred(direction: str, eligible_ids: Any) -> str:
    """The dominant mood's own blueprint among ``eligible_ids`` ('' = no mood or none of its blueprints fits)."""
    m = dominant(direction)
    ids = set(eligible_ids or ())
    return next((b for b in m.prefer if b in ids), "") if m is not None else ""


def rank_bonus(bp: Any, direction: str) -> float:
    """Score added to a blueprint by the direction's dominant mood: its own blueprints first, forbidden worlds last."""
    m = dominant(direction)
    if m is None:
        return 0.0
    s = 0.0
    if bp.id in m.prefer:
        s += 4.0 - 0.5 * m.prefer.index(bp.id)
    if any(_uses(str(sh.get("scene", "")), m.avoid) for sh in bp.shots):
        s -= 6.0
    return s


def prompt_block(direction: str) -> str:
    m = dominant(direction)
    if m is None:
        return ""
    return (f"## World rule for this direction ({m.id}; engine-enforced)\n{m.world}\n"
            f"Shots in {', '.join(f'`{a}*`' for a in m.avoid)} are swapped out by the engine under this mood, so "
            "do not plan them.")


def _forced(m: MoodWorld, scene: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pre in sorted(m.params, key=len):          # general prefixes first, exact scenes win
        if scene.startswith(pre):
            out.update(m.params[pre])
    return out


_STUDIO_MOVES = (("orbit", 145.0, 6.0), ("macro", -30.0, 4.0), ("dolly", -40.0, 3.0), ("turntable", 160.0, 8.0))


def enforce(film: dict[str, Any], direction: str, *, scenes: Any = (), model: str = "", paint: str = "",
            product: str = "") -> list[str]:
    """Rewrite ``film`` in place to obey the dominant mood's world; returns what changed (for the log).

    ``scenes``: the catalog's scene ids (a swap only happens to a scene that exists); ``model``: the product's 3D
    model asset ('' = no Blender product: no swap into Blender); ``paint``: the product colour for Blender paint;
    ``product``: the product media asset (kit stand-ins)."""
    m = dominant(direction)
    if m is None or not isinstance(film, dict):
        return []
    known = set(scenes or ())
    fixes: list[str] = []
    shots = [s for s in film.get("shots") or [] if isinstance(s, dict)]
    k = 0
    for s in shots:
        scene = str(s.get("scene", ""))
        if _uses(scene, m.avoid):
            to = next((t for pre, t in m.swap if scene.startswith(pre)), "")
            ok = bool(to) and (to in known or not known) and (not to.startswith("blender:") or bool(model))
            if ok:
                mv, yaw, pitch = _STUDIO_MOVES[k % len(_STUDIO_MOVES)]
                k += 1
                s["scene"] = to
                s["params"] = {"model": model, "move": mv, "yaw": yaw, "pitch": pitch, "fill": 0.72,
                               "reveal": k == 1, "wheel_rps": 0.0, **({"paint": paint} if paint else {})}
                s.pop("res", None)
                fixes.append(f"{s.get('id')}: {scene} -> {to} ({m.id} world)")
        f = _forced(m, str(s.get("scene", "")))
        if f:
            p = s.setdefault("params", {})
            ch = {kk: v for kk, v in f.items() if p.get(kk) != v}
            if ch:
                p.update(copy.deepcopy(ch))
                fixes.append(f"{s.get('id')}: {', '.join(f'{a}={b}' for a, b in ch.items())} ({m.id})")
    for o in film.get("overlays") or []:
        if not isinstance(o, dict):
            continue
        f = _forced(m, str(o.get("scene", "")))
        p = o.setdefault("params", {})
        ch = {kk: v for kk, v in f.items() if p.get(kk) != v}
        if ch:
            p.update(copy.deepcopy(ch))
            fixes.append(f"overlay {o.get('id')}: {', '.join(f'{a}={b}' for a, b in ch.items())} ({m.id})")
    for tr in film.get("transitions") or []:
        if isinstance(tr, dict) and _uses(str(tr.get("type", "")), m.avoid_transitions):
            fixes.append(f"transition {tr.get('from')}->{tr.get('to')}: {tr.get('type')} -> {m.dip} ({m.id})")
            tr["type"] = m.dip
            tr["params"] = {}
    if m.beds and m.bed:
        for mu in film.get("music") or []:
            if isinstance(mu, dict) and mu.get("bed") and not _uses(str(mu["bed"]), m.beds):
                fixes.append(f"bed {mu['bed']} -> {m.bed} ({m.id})")
                mu["bed"] = m.bed
    return fixes
