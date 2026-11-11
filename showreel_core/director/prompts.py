"""Director prompts: treatment, film script, scene code, critic and revisions (+ their transport schemas).

Each builder returns ``(instructions, input_text)``. Instructions hold the role, doctrine, rules and output
format; the input holds the facts of this film (direction verbatim, product, assets, catalog, prior artefacts).
Schemas are deliberately loose (no patterns/limits) so every provider accepts them; the engine validates.
"""
from __future__ import annotations

import json
from typing import Any

from . import moods, recipes, repair
from .catalog import Catalog
from .types import RUBRIC_KEYS, SCORE_BAR, Brief

DOCTRINE = """\
DIRECTOR'S DOCTRINE (non-negotiable; the engine checks these and the critic scores them)
1. Sell the product. Every shot either makes the viewer want the product or sets up the payoff that does. The film
   ends on the product, its name and a call to action.
2. The product is visible and beautiful in at least 60 % of the frames. Treat the product media as the hero: large,
   well lit, framed with breathing room, moving with intent; never tiny, never hidden under text or UI.
3. Hook within 2 seconds: the first 2 s pose a question or show something striking (the product or an unmistakable
   tease of it).
4. One idea per shot: each shot is one clear action a viewer can read at a glance.
5. Contrast and payoff: set up, escalate, turn, pay off. The turn is the most memorable moment of the film.
6. Motivated transitions: every transition is caused by something on screen (a click, an impact, a burst, a camera
   move, a match of shape or colour), never decoration.
7. Music-led cutting: cuts, hits and the turn land on beats/bars of the chosen bed; one hero impact per film; a sting
   marks the turn.
8. Restraint in type: few words, large, high contrast; on-screen cards <= 6 words, captions <= 8 words; text never
   covers the product.
9. Honour the user's direction LITERALLY (every explicit requirement is visibly met) AND exceed it: add one signature
   idea they did not ask for that makes the film memorable.
10. Craft over quantity: fewer elements, better made. Real depth (layers, parallax, atmosphere, light), real animation
   (anticipation, follow-through, easing, secondary motion, readable holds), one coherent palette per world.
11. Truth: never invent product facts, specs, prices or numbers. Claims come only from the brief; otherwise sell with
   images, emotion and benefit language that implies no specific fact.
12. Kit first. Kit scenes are polished and production-tested; a first-draft custom scene looks like stock. Build the
   film from kit scenes and their proven recipes, tuned through params. Write a custom scene only for a genuine gap
   (no kit scene can show it), and compose it from kit building blocks (ctx.kit(...)) instead of drawing from scratch.
13. The product reads as the hero: in product shots it spans >= 35 % of the frame width at least once and is never a
   speck. The engine MEASURES the product's on-screen size in every keyframe and sends small or missing products
   back."""


# ------------------------------------------------------------------------------------ schemas

def _arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        d["required"] = required
    return d


_S = {"type": "string"}
_N = {"type": "number"}
_B = {"type": "boolean"}
_FREE = {"type": "object"}

TREATMENT_SCHEMA = _obj({
    "title": _S, "logline": _S, "audience": _S, "selling_point": _S,
    "recipe": _S,
    "requirements": _arr(_obj({"text": _S, "how": _S}, ["text", "how"])),
    "signature_moment": _S,
    "hook": _obj({"t": _N, "what": _S}, ["t", "what"]),
    "emotional_arc": _S,
    "acts": _arr(_obj({"name": _S, "world": _S, "style": _S, "duration": _N, "beats": _arr(_S),
                       "product_role": _S, "palette": _arr(_S)}, ["name", "world", "duration", "beats", "product_role"])),
    "transitions": _arr(_obj({"from_act": _S, "to_act": _S, "idea": _S, "motivation": _S})),
    "music_plan": _arr(_obj({"bed": _S, "from_s": _N, "to_s": _N, "why": _S})),
    "stings": _arr(_obj({"sting": _S, "t": _N, "why": _S})),
    "voice": _obj({"mode": _S, "tone": _S}),
    "asset_plan": _arr(_obj({"asset": _S, "use": _S})),
    "payoff": _S, "cta": _S,
    "risks": _arr(_S),
}, ["logline", "selling_point", "recipe", "requirements", "hook", "acts", "music_plan", "asset_plan", "payoff",
    "cta"])

_SHOT = _obj({"id": _S, "t0": _N, "t1": _N, "scene": _S, "res": {"type": ["array", "null"], "items": _N},
              "params": _FREE, "z": _N, "upscale": _S}, ["id", "t0", "t1", "scene", "params"])
_LISTS = {
    "transitions": _arr(_obj({"from": _S, "to": _S, "type": _S, "t": _N, "dur": _N, "params": _FREE},
                             ["from", "to", "type", "t", "dur"])),
    "overlays": _arr(_obj({"id": _S, "t0": _N, "t1": _N, "scene": _S, "params": _FREE}, ["id", "t0", "t1", "scene"])),
    "cues": _arr(_obj({"t": _N, "sfx": _S, "gain_db": _N}, ["t", "sfx"])),
    "music": _arr(_obj({"bed": _S, "t0": _N, "t1": _N, "sting": _S, "t": _N})),
    "captions": _arr(_obj({"t0": _N, "t1": _N, "text": _S}, ["t0", "t1", "text"])),
}
FILM_DOC_SCHEMA = _obj({
    "version": _N, "fps": _N, "size": _arr(_N), "dur": _N, "seed": _N, "title": _S, "background": _S,
    "assets": _FREE,
    "shots": _arr(_SHOT),
    **_LISTS,
    "finish": _FREE,
}, ["dur", "shots", "music"])
_PLAN_SHOT = _obj({"id": _S, "intent": _S, "product_visible": _B, "beats": _arr(_obj({"t": _N, "what": _S}))},
                  ["id", "intent", "product_visible"])
_CUSTOM = _obj({"name": _S, "layer": _S, "describe": _S, "spec": _S, "params": _FREE, "kits": _arr(_S),
                "fallback": _S}, ["name", "layer", "describe", "spec", "params"])
_VOICE = _arr(_obj({"t": _N, "text": _S}, ["t", "text"]))
PLAN_SCHEMA = _obj({"shots": _arr(_PLAN_SHOT), "custom_scenes": _arr(_CUSTOM), "voiceover": _VOICE})
FILM_SCHEMA = _obj({"film": FILM_DOC_SCHEMA, "plan": PLAN_SCHEMA}, ["film", "plan"])
REVISE_PATCH_SCHEMA = _obj({
    "changes": _arr(_S),
    "shots": _arr(_obj({"id": _S, "t0": _N, "t1": _N, "scene": _S, "res": {"type": ["array", "null"], "items": _N},
                        "params": _FREE, "params_replace": _FREE, "remove": _B}, ["id"])),
    **_LISTS,
    "finish": _FREE, "title": _S,
    "plan_shots": _arr(_PLAN_SHOT), "custom_scenes": _arr(_CUSTOM), "voiceover": _VOICE,
    "scene_notes": _arr(_obj({"name": _S, "notes": _S}, ["name", "notes"])),
}, ["changes"])
CRITIC_SCHEMA = _obj({
    "scores": _obj({k: _N for k in RUBRIC_KEYS}, list(RUBRIC_KEYS)),
    "shots": _arr(_obj({"id": _S, "score": _N, "note": _S}, ["id", "score"])),
    "frames": _arr(_obj({"cell": _N, "product_visible": _B, "product_size": _N, "note": _S},
                        ["cell", "product_visible", "product_size"])),
    "requirements": _arr(_obj({"text": _S, "met": _B, "note": _S}, ["text", "met"])),
    "per_shot_issues": _arr(_obj({"shot": _S, "target": _S, "severity": _N, "issue": _S, "fix": _S},
                                 ["shot", "target", "severity", "issue", "fix"])),
    "strengths": _arr(_S),
    "verdict": _S,
}, ["scores", "shots", "per_shot_issues", "verdict"])


# ------------------------------------------------------------------------------------ helpers

def _product_text(brief: Brief) -> str:
    p = brief.product
    if not p:
        return "## Product\n(no product record: infer the product only from the direction and the media)"
    lines = ["## Product (facts you may state; nothing else)", f"- name: {p.name or '(unnamed)'}"]
    if p.one_liner:
        lines.append(f"- one-liner: {p.one_liner}")
    if p.kind:
        lines.append(f"- kind: {p.kind}")
    if p.features:
        lines.append("- features: " + "; ".join(p.features))
    public = [u for u in p.urls if u and not repair.LOOPBACK.search(u)]   # never offer a dev-server address
    if public:
        lines.append("- urls: " + ", ".join(public))
    return "\n".join(lines)


def _film_frame(brief: Brief) -> str:
    w, h = brief.size
    return (f"## Film\n- length: {brief.seconds:g} s (exactly)\n- aspect: {brief.aspect} ({w}x{h}), {brief.fps} fps\n"
            f"- seed: {brief.seed}")


def _direction_block(brief: Brief) -> str:
    out = f"## The user's direction (verbatim)\n\"\"\"{brief.direction.strip()}\"\"\""
    if brief.notes.strip():
        out += f"\n\n## Additional notes from the user (verbatim)\n\"\"\"{brief.notes.strip()}\"\"\""
    return out


def _digest_block(brief: Brief, budget: int = 6000) -> str:
    d = brief.digest.strip()
    if not d:
        return ""
    if len(d) > budget:
        d = d[:budget].rsplit("\n", 1)[0] + "\n[... digest truncated]"
    return f"## Session digest (what was built; redacted)\n{d}"


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _bar_hint(catalog: Catalog) -> str:
    rows = [f"- `{b.id}`: {b.bpm:g} BPM, beat {60.0 / b.bpm:.3f} s, bar {b.bar_s:.3f} s" for b in catalog.beds]
    return "## Beat grid per bed (place cuts, hits and the turn on these)\n" + ("\n".join(rows) or "(no beds)")


# ------------------------------------------------------------------------------------ treatment

def treatment_prompt(brief: Brief, catalog: Catalog) -> tuple[str, str]:
    """Treatment step: the creative plan (no code, no timings below the act level)."""
    instructions = f"""\
You are the Director of Showreel Studio: a senior commercial director and motion designer who makes short product
films that people watch twice. You are writing the TREATMENT for one film: the creative plan that a film script and
custom animation code will be written from. You will not write code here.

{DOCTRINE}

HOW TO WORK
- First extract every explicit requirement from the user's direction into `requirements` (one entry each, in their
  words) and say exactly how the film meets it. Their words are a contract: if they name a style, a structure (e.g.
  "transition into a different style mid way through"), a goal ("sell the product"), the film must visibly do it.
- Then decide the one idea that exceeds the direction: `signature_moment`.
- Build the film in acts. Each act is a world with a style, a palette (3-8 hex colours), 3-6 beats (concrete visible
  actions, not adjectives) and the product's role in it. Act durations must add up to the film length.
- Choose worlds the engine can make beautiful. Kit scenes are polished, production-tested and look better than a
  first-draft custom scene: when a kit scene (or a library scene) expresses an idea of yours, build that part of
  the film from it and tune it through its params. Spend custom scenes on what only this film needs (the
  signature moment, a world no kit offers), at most 1-2 of them, and only where no kit scene fits.
- Pick the narrative recipe that fits the direction best (`recipe`: its id, or `custom` when none fits) and adapt
  it: recipes are proven structures (pacing, turn, music, product role per act) laid out on kit scenes. Adapting
  means changing worlds, words, timing and params to this direction, not throwing the structure away.
- Plan the music: one bed per act (ids from the catalog only), with the turn landing on a bar line, plus stings.
- Plan the voice (`voice.mode`: `none` | `sparse` (2-4 short lines) | `narrated` (a narrator carries the film);
  `voice.tone`: who speaks and how). Narrate when the direction implies a narrator (documentary, story, explainer);
  stay silent when the pictures and in-world text carry it (games, music-video energy).
- Plan every product asset's use. The product media is real footage/images: show it, frame it, light it; you may
  stylise it (pixelate, paint over, put it in a world) but it must stay recognisable and LARGE.
- Name the risks (what could look cheap) and how to avoid them.
- Be specific and visual. "Epic battle" is useless; "the boss winds up for 0.6 s, a curved blade flies left, the
  knight is knocked back 12 px with a red flash and a floating -42" is useful.

Reply with one JSON object matching the schema."""
    parts = [_direction_block(brief), _product_text(brief), _film_frame(brief), blender_rule(brief),
             moods.prompt_block(brief.direction),
             recipes.overview(physical=_physical(brief)), _recipe_hint(brief), catalog.overview(),
             catalog.recipes_text(budget=6000), _digest_block(brief)]
    return instructions, "\n\n".join(p for p in parts if p)


def blender_rule(brief: Brief) -> str:
    """When Blender is available the user wants 3D Blender worlds; the three.js nature kit is only the fallback."""
    if not brief.capabilities.blender:
        return ""
    model = next((a.name for a in brief.assets if a.type == "model"), "")
    return ("## 3D (Blender is available: USE IT)\n"
            "The user decided that 3D worlds are made in Blender: `blender:<kit>/<scene>` shots render the product as "
            "a real 3D model with smooth spline cameras and look far better than the browser kits' 3D. The browser "
            "`kit:nature/*` meadow is ONLY the fallback when Blender is missing - do not use it here.\n"
            "- meadow / field / nature / anime-sky / dreamy worlds -> `blender:meadow/oner` (one continuous 25.4 s "
            "camera move; split it into shots with `t_offset`, `time_of_day` sunset|golden|dawn; keep "
            "t_offset + shot duration <= `length`)\n"
            "- product reveals, keynotes, studio, luxury -> `blender:studio/product_hero` (move orbit|dolly|turntable, "
            "env studio|light|sunset|accent, `paint` = the product's real colour as hex) and "
            "`blender:studio/product_float`\n"
            "- app screens -> `blender:device/device_hero|device_feature|device_scroll|device_trio|device_end`\n"
            + (f"- the product's 3D model asset is `{model}` (Blender scenes use it by default)\n" if model else "")
            + "Words go on top as `kit:type/*` overlays (lower-third, title, end-lockup); 2D style kits remain fine "
              "for acts that are not 3D worlds (pixel, comic, terminal...).")


def _physical(brief: Brief) -> bool:
    """A physical product (video clip / cut-out) rather than a screen product (screenshots, captures)."""
    return any(a.type == "video" or a.cutout for a in brief.assets if a.product)


def _recipe_hint(brief: Brief) -> str:
    ids = recipes.suggest(brief.direction, physical=_physical(brief))
    return f"Recipes whose words match this direction: {', '.join(ids)}" if ids else ""


# ------------------------------------------------------------------------------------ film

def film_prompt(brief: Brief, catalog: Catalog, treatment: dict[str, Any], *, max_custom: int) -> tuple[str, str]:
    """Film step: treatment -> film.json (SDK section 2) + a plan with shot intents and custom scene specs."""
    instructions = f"""\
You are the Director of Showreel Studio. Turn the approved TREATMENT into the FILM SCRIPT: a film.json the runtime
renders frame by frame, plus a PLAN that tells the engine what each shot must show and specifies every custom scene
precisely enough that a separate animator (who sees only your spec, the SDK and the kit docs) can code it.

{DOCTRINE}

FILM.JSON RULES (validated by code; violations are sent back to you)
- Shots are back to back and cover 0..dur exactly (shot[i].t1 == shot[i+1].t0, first t0 = 0, last t1 = dur).
  Shot ids are short slugs. One idea per shot: most shots last 2-8 s; a single continuous action may run longer.
- `scene`: a kit scene id from the catalog (`kit:<kit>/<name>`), a library id (`lib:<name>`), or `custom:<name>` for a
  scene you specify in plan.custom_scenes. Use kits wherever they fit; at most {max_custom} custom scene(s). One custom
  scene may serve several shots through different params (e.g. a `phase` param).
- `params`: only params the scene declares (kits: see the catalog; custom: the params you declare in its spec). Refer
  to product media by asset name (e.g. "car"); the engine counts a shot as showing the product when its params
  reference a product asset.
- `res`: [480, 270] (or [320, 180]) for pixel-art worlds, null for HD worlds.
- Transitions: one per act change at least, motivated by the action at the cut; the window [t, t+dur] contains
  the cut. Use a kit transition id from the catalog or a built-in name.
- Music: `music` lists beds ({{bed, t0, t1}}) that cover the film, and stings ({{sting, t}}). Ids from the catalog only.
  Put the turn and the main cuts on bar lines of the active bed (see the beat grid).
- Cues: sound effects on visible actions only (hits, clicks, bursts, whooshes), ids from the SFX list; one hero
  impact per film.
- Captions: optional, few, <= 8 words, 1.5-3.5 s each, never two at once. Overlays: end on the product name and the
  CTA (e.g. a `kit:type/...` title overlay) for the last 3-5 s; never put an end card over the product itself
  (use the scene's `title` param / reserved area, or a lockup with a scrim).
- Do not set `assets`, `size`, `fps`, `seed`, `version`: the engine fills them.

PRODUCT SIZE (the engine measures it in every keyframe; < 25 % of the frame width = too small, the target is 35 %+)
- Pass the product asset to every product shot's media param (`product`, `boss_media`, `media`, `image`, `hero`...).
- Nature flyers are sized in metres at a depth in metres; the camera sees ~1.09 x depth metres across (16:9). A
  flyer reads as the hero only near the camera: e.g. `{{"path": "hero"}}` (6.4 m at 16 m = 37 %), `descend` 5.4 m at
  20 m = 25 %, `float` 6 m at 36 m = 15 %, `rise`/`arc` at 70-90 m = specks. In a product shot give the lead flyer
  `size` >= 9 at d <= 24 (or path `hero`), keep 1-2 smaller ones behind it for depth; never 4+ default specks.
- If a kit scene declares `product_scale`, use >= 1.2 in product shots.
- SCREEN products (UI screenshots) in nature scenes fly as cards with `key: false` (auto-key ghosts light UI), at
  most ~60 % of the width. The nature `product-hero` cannot un-key a screenshot (a ghost): show UI close-ups with
  `kit:cinematic/screen-push` or `kit:launch/SCREEN|FEATURE` and let the meadow carry the mood around them.

PLAN RULES
- plan.shots: one entry per shot: `intent` (what the viewer must see and feel, one sentence), `product_visible`
  (true only if the product media is clearly on screen for most of the shot), `beats` (shot-local times).
  At least 60 % of the runtime must be product-visible shots, and the product must appear by 2 s or be teased then.
- plan.voiceover (only when the treatment's voice mode is not `none`): narration lines [{{t, text}}] at absolute
  seconds, in the treatment's tone. Budget: <= 2.4 words per second of the gap until the next line (or the end);
  never two lines at once; leave >= 0.4 s of air between lines; the first line not before 0.5 s. Each line is a
  complete sentence (lines are never cut). Narration and on-screen text must not say the same thing.
- plan.custom_scenes (only for genuine gaps): for each custom scene: `name` (slug), `layer` ('2d' for pixel art and
  painterly 2D, 'three' only when real 3D is essential), `describe` (one line), `params` (name -> {{type, default,
  doc}}; asset params have type 'asset'), `kits` (kit building blocks it MUST reuse, by kit name), `fallback` (the
  closest kit scene id, used if the code fails), and `spec`: a precise, self-contained animation brief: surface size,
  palette hexes, layers back to front (name the kit blocks that draw them), where the product sits in frame and how
  big, every beat with shot-local start/end times and easing, exact on-screen text strings, sound cue times, and the
  quality bar (what would make it look cheap and must be avoided). The animator has not read the treatment: put
  everything they need in the spec.

Reply with one JSON object: {{"film": {{...}}, "plan": {{...}}}}."""
    parts = [_direction_block(brief), _product_text(brief), _film_frame(brief), blender_rule(brief),
             moods.prompt_block(brief.direction),
             "## Approved treatment\n" + _json(treatment), recipe_block(brief, catalog, treatment),
             _bar_hint(catalog), catalog.full(), catalog.recipes_text(), "## Scene SDK reference\n" + catalog.sdk]
    return instructions, "\n\n".join(p for p in parts if p)


def recipe_block(brief: Brief, catalog: Catalog, treatment: dict[str, Any]) -> str:
    """The treatment's recipe laid out on this film: its proven film when one exists (adapt it), else the recipe
    template, plus a proven film of another recipe to borrow shots from when the acts share its kits."""
    rec = recipes.get(str(treatment.get("recipe") or ""))
    product = next((a.name for a in brief.assets if a.product), "")
    name = (brief.product.name if brief.product and brief.product.name else str(treatment.get("title") or ""))
    tagline = brief.product.one_liner if brief.product and brief.product.one_liner else ""
    cta = str(treatment.get("cta") or "")
    physical = _physical(brief)
    ex = recipes.exemplar_for(rec.id, aspect=brief.aspect, physical=physical) if rec is not None else None
    if ex is not None and rec is not None and product:
        head = f"## Chosen recipe: `{rec.id}` ({rec.name})\n{rec.arc}.\n- Voice: {rec.voice}\n"
        return head + "\n" + recipes.exemplar_text(ex, seconds=brief.seconds, product=product, name=name, cta=cta,
                                                   tagline=tagline, whole=True, aspect=brief.aspect)
    blocks = []
    if rec is not None:
        blocks.append(recipes.detail(rec, seconds=brief.seconds, product=product, name=name, cta=cta,
                                     tagline=tagline, available=set(catalog.scenes()) | catalog.transitions()))
    styles = {str(a.get("style") or "") for a in treatment.get("acts") or [] if isinstance(a, dict)}
    for other in recipes.exemplars():
        if product and other.physical == physical and other.kits() & styles and (rec is None or other.recipe != rec.id):
            blocks.append(recipes.exemplar_text(other, seconds=brief.seconds, product=product, name=name, cta=cta,
                                                tagline=tagline, whole=False, aspect=brief.aspect))
            break
    return "\n\n".join(blocks)


# ------------------------------------------------------------------------------------ scene code

_SCENE_SELF_CHECK = """\
SELF-CHECK BEFORE ANSWERING
- The file starts with `import { sr } from '../runtime/showreel.js';` and calls `sr.defineScene('<id>', {...})` with the
  exact id given, `layer`, `describe`, `params` (every param with type/default/doc) and `render`.
- render(ctx, t, p) is a pure function of t: nothing is mutated in render, no state carried between frames.
- None of the forbidden APIs appear (Math.random, Date, performance.now, timers, rAF, fetch/XHR/WebSocket, dynamic
  import, eval, new Function, document./window. access, external URLs).
- Every beat of the spec happens at its time; the shot works for the whole duration (no dead tail, no blank frames).
- The product media is drawn from ctx.asset(<param value>) and is the hero when the spec says so: it spans >= 35 % of
  the frame width at its key moment (the engine MEASURES this in every keyframe and sends small products back), and
  nothing (title, scrim, haze, particles) covers it.
- All readable text goes through ctx.text inside ctx.safe; every pixel is painted every frame. `ctx.w`/`ctx.h` are
  the surface size on every layer; DOM scenes build elements with `ctx.el(tag, props, ...kids)`; text painted into
  WebGL is registered with `ctx.qaText([x, y, w, h], size, text)`; purely decorative DOM text gets `data-qa="off"`.
- Params with defaults make the scene render sensibly even if a param is missing."""


def scene_prompt(brief: Brief, catalog: Catalog, spec: dict[str, Any], shots: list[dict[str, Any]],
                 plan_shots: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Scene-code step: one custom scene module against the SDK (+ kit building blocks)."""
    sid = f"custom:{spec.get('name')}"
    instructions = f"""\
You are a senior creative coder and motion designer (demoscene precision, feature-animation taste). Write ONE scene
module for Showreel's runtime, exactly to the spec. The scene is rendered frame by frame, out of order, at the shot's
surface size, then composited into the film. It must look finished: this is a commercial, not a prototype.

Compose it from the kit building blocks listed below (ctx.kit('<kit>').<block>): worlds, skies, sprites, product
presentation, UI, type and motion helpers there are polished and production-tested, and they keep this shot in the
same visual language as the kit shots around it. Draw by hand only what no block provides.

Scene id: `{sid}`

{catalog.craft}

{_SCENE_SELF_CHECK}

Reply with the complete JavaScript file in ONE ```js fenced block and nothing else."""
    uses = []
    for s in shots:
        ps = plan_shots.get(str(s.get("id")), {})
        uses.append({"shot": s.get("id"), "dur": round(float(s.get("t1", 0)) - float(s.get("t0", 0)), 3),
                     "res": s.get("res") or list(brief.size), "params": s.get("params") or {},
                     "intent": ps.get("intent", ""), "beats": ps.get("beats", [])})
    parts = [
        "## Scene spec\n" + _json(spec),
        "## Shots that use this scene (shot-local time starts at 0 in each)\n" + _json(uses),
        f"## Film\n{brief.size[0]}x{brief.size[1]} @ {brief.fps} fps (the scene draws at its shot's `res`)",
        catalog.assets_text(),
        "## Kit building blocks you may call through ctx.kit(name)\n"
        + catalog.kit_docs([str(k) for k in spec.get("kits") or []]),
        "## Scene SDK reference\n" + catalog.sdk,
    ]
    return instructions, "\n\n".join(parts)


def scene_repair_prompt(brief: Brief, catalog: Catalog, spec: dict[str, Any], code: str,
                        errors: list[str]) -> tuple[str, str]:
    """Fix a scene that failed lint or the dry run; keep everything that works."""
    sid = f"custom:{spec.get('name')}"
    instructions = f"""\
You are a senior creative coder fixing a Showreel scene module (`{sid}`) that failed the engine's checks. Fix every
error below at its root cause. Keep the look, timing and structure that are not involved in the errors. Do not
simplify the scene to make errors go away unless the error cannot be fixed otherwise.

{_SCENE_SELF_CHECK}

Reply with the complete corrected JavaScript file in ONE ```js fenced block and nothing else."""
    parts = ["## Errors (from lint and from rendering the scene at several times)\n" + "\n".join(f"- {e}" for e in errors),
             "## Current code\n```js\n" + code + "\n```", "## Scene spec\n" + _json(spec), catalog.assets_text(),
             "## Kit building blocks\n" + catalog.kit_docs([str(k) for k in spec.get("kits") or []], budget=8000),
             "## Scene SDK reference\n" + catalog.sdk]
    return instructions, "\n\n".join(parts)


def scene_revise_prompt(brief: Brief, catalog: Catalog, spec: dict[str, Any], code: str,
                        issues: list[dict[str, Any]], notes: str = "", *, keep: list[str] | None = None,
                        cells: list[str] | None = None) -> tuple[str, str]:
    """Apply the critic's visual fixes to one scene, surgically."""
    sid = f"custom:{spec.get('name')}"
    seen = ("" if not cells else
            "\nThe attached contact sheet(s) show what your current code renders; this scene is in cells "
            + ", ".join(cells) + ". Look at them before changing anything.")
    instructions = f"""\
You are a senior creative coder revising a Showreel scene module (`{sid}`) after a creative director reviewed
rendered keyframes.{seen} Apply each fix below precisely and visibly; keep everything the review did not criticise
(do not rewrite working parts: regressions are worse than an unfixed polish issue). Improve craft where the fix
asks for it (depth, light, motion, composition, legibility); do not add clutter.

{catalog.craft}

{_SCENE_SELF_CHECK}

Reply with the complete revised JavaScript file in ONE ```js fenced block and nothing else."""
    parts = ["## Review: issues and fixes for this scene\n" + _json(issues)]
    if keep:
        parts.append("## What already works (keep it)\n" + "\n".join(f"- {k}" for k in keep))
    if notes.strip():
        parts.append("## Director's notes for this scene\n" + notes.strip())
    parts += ["## Current code\n```js\n" + code + "\n```", "## Scene spec\n" + _json(spec), catalog.assets_text(),
              "## Kit building blocks\n" + catalog.kit_docs([str(k) for k in spec.get("kits") or []], budget=8000),
              "## Scene SDK reference\n" + catalog.sdk]
    return instructions, "\n\n".join(parts)


PATCH_FORMAT = """\
OUTPUT FORMAT: edit blocks only (no full file). Each block replaces one exact, unique run of lines:
<<<<<<< SEARCH
(lines copied EXACTLY from the current code: enough lines to be unique, usually 2-12)
=======
(the new lines)
>>>>>>> REPLACE
Use as many blocks as the fixes need, in file order. Change nothing else: every line you do not touch stays
byte-identical (that is the point: no regressions). A one-line sentence before the blocks may say what you changed."""


def scene_patch_prompt(brief: Brief, catalog: Catalog, spec: dict[str, Any], code: str, *,
                       issues: list[dict[str, Any]] | None = None, errors: list[str] | None = None, notes: str = "",
                       keep: list[str] | None = None, cells: list[str] | None = None,
                       failures: list[str] | None = None) -> tuple[str, str]:
    """Targeted scene edits (search/replace blocks) for review fixes or runtime/lint errors."""
    sid = f"custom:{spec.get('name')}"
    seen = ("" if not cells else
            " The attached contact sheet(s) show what the current code renders; this scene is in cells "
            + ", ".join(cells) + ". Look at them before changing anything.")
    job = ("fix the errors below at their root cause" if errors else
           "apply each review fix below precisely and visibly")
    instructions = f"""\
You are a senior creative coder making SURGICAL edits to a Showreel scene module (`{sid}`):{' ' + job}.{seen}
Keep everything the review did not criticise; regressions are worse than an unfixed polish issue. Prefer kit
building blocks (ctx.kit(...)) over hand-drawn code when a fix needs new drawing.

{_SCENE_SELF_CHECK}

{PATCH_FORMAT}"""
    parts = []
    if errors:
        parts.append("## Errors (from lint and from rendering the scene)\n" + "\n".join(f"- {e}" for e in errors))
    if issues:
        parts.append("## Review: issues and fixes for this scene\n" + _json(issues))
    if keep:
        parts.append("## What already works (keep it)\n" + "\n".join(f"- {k}" for k in keep))
    if notes.strip():
        parts.append("## Director's notes for this scene\n" + notes.strip())
    if failures:
        parts.append("## Your previous edit blocks did NOT apply (nothing was changed); fix them\n"
                     + "\n".join(f"- {f}" for f in failures))
    parts += ["## Current code\n```js\n" + code + "\n```", "## Scene spec\n" + _json(spec), catalog.assets_text(),
              "## Kit building blocks\n" + catalog.kit_docs([str(k) for k in spec.get("kits") or []], budget=6000),
              "## Scene SDK reference\n" + catalog.sdk]
    return instructions, "\n\n".join(parts)


# ------------------------------------------------------------------------------------ critic

RUBRIC_TEXT = """\
RUBRIC (score each 1-10; 10 = would air in a top-tier brand spot, 8 = professional and clean with nothing that
looks cheap, 6 = competent but generic or visibly flawed, 4 = amateur, obvious problems, 2 = broken)
- product_clarity: the product is recognisable, large enough, well lit and the hero where it should be; a viewer
  could name what is being sold.
- composition: framing, balance, focal point, negative space, safe areas, nothing awkwardly cropped or colliding.
- beauty_craft: rendering quality, palette, light, depth, texture, detail density, polish of motion implied by the
  frames (smears, poses, particles), pixel-art discipline where pixel art is used.
- story_clarity: the sequence of frames reads as the planned story; the turn and the payoff are clear.
- legibility: every word on screen is readable at a glance (size, contrast, placement) and there is not too much.
- style_coherence: each world is internally consistent; the style change (if any) feels designed, not accidental.
- transition_quality: transitions are motivated, well timed and look good mid-transition."""


def critic_prompt(brief: Brief, treatment: dict[str, Any], film: dict[str, Any], plan: dict[str, Any],
                  frame_index: list[dict[str, Any]], checks: list[str]) -> tuple[str, str]:
    """Vision critique of keyframe contact sheet(s) against the treatment and per-shot intent."""
    instructions = f"""\
You are a demanding creative director reviewing an animatic: contact sheet(s) of keyframes rendered from a product
film. Each cell is numbered (top-left label) and listed in the frame index with its shot, time and intent. Judge
what is actually visible in the frames, not what the plan promises. Compare against the best commercial motion
design you know. Be specific, be harsh where it is deserved, and never praise to be polite.

{RUBRIC_TEXT}

ALSO
- shots: one entry per shot id with `score` (1-10: how well THAT shot is crafted and sells, judged on its cells;
  the engine keeps the best version of every shot across revisions, so score shots independently and honestly).
- frames (optional): notes on single cells. The product's visibility and on-screen width are MEASURED by the engine
  (pixel-exact, see the engine measurements); trust those numbers over your impression.
- requirements: check every requirement of the user's direction (listed below) against the frames.
- per_shot_issues: at most 8, most important first. Each names the shot id, a `target` ("scene" if fixing it needs
  the custom scene's drawing code changed, "film" if it is timing, params, captions, overlays, transitions, music or
  scene choice), a `severity` (3 = ruins the film, 2 = clearly hurts, 1 = polish), the `issue` as seen, and a
  concrete `fix` an animator can implement (positions, sizes, colours, timings, params, what to add or remove).
  Kit scenes are fixed through their params (see each shot's params), never by asking for new drawing code.
- verdict: "pass" only if every score is >= {SCORE_BAR:g} and nothing has severity 3; otherwise "revise".

Reply with one JSON object matching the schema."""
    shots = [{"id": s.get("id"), "t0": s.get("t0"), "t1": s.get("t1"), "scene": s.get("scene"),
              "params": s.get("params")} for s in film.get("shots") or []]
    parts = [
        _direction_block(brief),
        "## Requirements to verify\n" + _json(treatment.get("requirements") or []),
        "## Treatment (summary)\n" + _json({k: treatment.get(k) for k in
                                            ("logline", "selling_point", "signature_moment", "hook", "acts",
                                             "transitions", "payoff", "cta") if k in treatment}),
        "## Shots\n" + _json(shots),
        "## Shot intents\n" + _json(plan.get("shots") or []),
        "## Transitions / overlays / captions\n" + _json({k: film.get(k) for k in ("transitions", "overlays",
                                                                                   "captions")}),
        "## Frame index (cell -> shot, time)\n" + "\n".join(
            f"- cell {f['cell']}: shot `{f['shot']}` at {f['t']:.2f}s (shot-local {f['local']:.2f}s of {f['dur']:.2f}s)"
            f"{' [transition ' + f['transition'] + ']' if f.get('transition') else ''}" for f in frame_index),
    ]
    if plan.get("voiceover"):
        parts.append("## Narration (spoken over the film, not on screen)\n" + "\n".join(
            f"- {v.get('t')}s: {v.get('text')}" for v in plan["voiceover"] if isinstance(v, dict)))
    if checks:
        parts.append("## Engine measurements (facts)\n" + "\n".join(f"- {c}" for c in checks))
    return instructions, "\n\n".join(parts)


# ------------------------------------------------------------------------------------ revisions

def revise_patch_prompt(brief: Brief, catalog: Catalog, treatment: dict[str, Any], film: dict[str, Any],
                        plan: dict[str, Any], issues: list[dict[str, Any]], notes: str, *, max_custom: int,
                        keep: list[str] | None = None, seen: bool = False, facts: list[str] | None = None
                        ) -> tuple[str, str]:
    """Film-level revision as a PATCH: only the shots/lists that change come back (untouched shots stay exact)."""
    instructions = f"""\
You are the Director of Showreel Studio revising your film after review. Fix what the review (and the user's
notes, if any: they come first) asks for that can be fixed in film.json or the plan: timing, kit-scene params,
scene choice, transitions, music, cues, captions, overlays, narration.{" The attached contact sheet(s) show the "
"current render (cells are listed in the review)." if seen else ""}

ANSWER WITH A PATCH, NOT A FILM. Return only what changes:
- `shots`: one entry per shot you change, by `id`: `params` is DEEP-MERGED into the shot's params (a key set to
  null is removed; lists are replaced whole), `params_replace` replaces them entirely, `t0`/`t1`/`scene`/`res`
  overwrite; `{{"id": ..., "remove": true}}` deletes a shot; a new id with t0, t1, scene, params adds one. Shots stay
  back to back and cover 0..dur: when you retime one shot, retime its neighbour too.
- `transitions` | `overlays` | `captions` | `cues` | `music`: the FULL new list, only when that list changes.
- `plan_shots` (changed intents), `custom_scenes` (changed/new specs, max {max_custom} custom scenes in the film),
  `voiceover` (the full new narration list, only when it changes).
- `scene_notes`: fixes that need a custom scene's drawing code changed, sharpened for the animator, by scene name.
- `changes`: one line per change.
Everything you do not mention stays exactly as it is: keep what works (regressions are worse than an unfixed polish
issue). Kit scenes are fixed through their params (see the catalog); when the product reads small, raise its size
params (see PRODUCT SIZE). Prefer replacing a weak custom scene by a kit scene over rewriting it.
SCOPE: fix every severity-3 issue and at most the 4 most damaging others - a few precise changes beat many. Keep the
TIMELINE (every shot's id, t0, t1) unless an issue is about pacing or the user's notes ask for it: the engine keeps
the best version of each shot across revisions, and that needs the same shots at the same times.

{DOCTRINE}

Reply with one JSON object matching the schema."""
    parts = [_direction_block(brief)]
    if notes.strip():
        parts.append("## The user's revision notes (highest priority, verbatim)\n" + notes.strip())
    if issues:
        parts.append("## Review issues and fixes\n" + _json(issues))
    if facts:
        parts.append("## Engine measurements (facts)\n" + "\n".join(f"- {f}" for f in facts))
    if keep:
        parts.append("## What already works (keep it)\n" + "\n".join(f"- {k}" for k in keep))
    parts += ["## Current film.json\n" + _json(film), "## Current plan\n" + _json(plan),
              "## Treatment\n" + _json(treatment), PRODUCT_SIZE_NOTE, _bar_hint(catalog),
              catalog.full(kit_budget=5000)]
    return instructions, "\n\n".join(parts)


PRODUCT_SIZE_NOTE = """\
## PRODUCT SIZE (measured by the engine; < 25 % of the frame width = too small, target 35 %+)
- Nature flyers: metres at a depth in metres; the camera sees ~1.09 x depth metres across (16:9). `hero` path 6.4 m
  at 16 m = 37 %; `descend` 5.4 m at 20 m = 25 %; `float` 6 m at 36 m = 15 %; `rise`/`arc` = specks. Make the lead
  flyer `size` >= 9 at d <= 24 (or path `hero`); 1-2 smaller ones behind it for depth.
- Kit scenes that declare `product_scale`: >= 1.2 in product shots.
- SCREEN products (UI screenshots) in nature scenes fly as cards: give every such flyer `key: false` (the kit's
  auto-key ghosts light UI) and keep it within ~60 % of the width (it is a 16:10 card: taller than a car). The
  nature `product-hero` cannot un-key a screenshot (it reads as a ghost): show the UI close and crisp with
  `kit:cinematic/screen-push` or `kit:launch/SCREEN|FEATURE` instead, and let the meadow carry the mood."""


def repair_text(previous: Any, errors: list[str]) -> str:
    """Input appendix for a re-ask after validation failed."""
    prev = previous if isinstance(previous, str) else _json(previous)
    if len(prev) > 24000:
        prev = prev[:24000] + "\n[... truncated]"
    return ("\n\n## Your previous answer was REJECTED by the engine\n" + prev +
            "\n\n## Fix exactly these problems and answer again (complete JSON)\n" +
            "\n".join(f"- {e}" for e in errors))
