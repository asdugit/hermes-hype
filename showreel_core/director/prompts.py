"""Director prompts: treatment, film script, scene code, critic and revisions (+ their transport schemas).

Each builder returns ``(instructions, input_text)``. Instructions hold the role, doctrine, rules and output
format; the input holds the facts of this film (direction verbatim, product, assets, catalog, prior artefacts).
Schemas are deliberately loose (no patterns/limits) so every provider accepts them; the engine validates.
"""
from __future__ import annotations

import json
from typing import Any

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
   images, emotion and benefit language that implies no specific fact."""


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
    "requirements": _arr(_obj({"text": _S, "how": _S}, ["text", "how"])),
    "signature_moment": _S,
    "hook": _obj({"t": _N, "what": _S}, ["t", "what"]),
    "emotional_arc": _S,
    "acts": _arr(_obj({"name": _S, "world": _S, "style": _S, "duration": _N, "beats": _arr(_S),
                       "product_role": _S, "palette": _arr(_S)}, ["name", "world", "duration", "beats", "product_role"])),
    "transitions": _arr(_obj({"from_act": _S, "to_act": _S, "idea": _S, "motivation": _S})),
    "music_plan": _arr(_obj({"bed": _S, "from_s": _N, "to_s": _N, "why": _S})),
    "stings": _arr(_obj({"sting": _S, "t": _N, "why": _S})),
    "asset_plan": _arr(_obj({"asset": _S, "use": _S})),
    "payoff": _S, "cta": _S,
    "risks": _arr(_S),
}, ["logline", "selling_point", "requirements", "hook", "acts", "music_plan", "asset_plan", "payoff", "cta"])

_SHOT = _obj({"id": _S, "t0": _N, "t1": _N, "scene": _S, "res": {"type": ["array", "null"], "items": _N},
              "params": _FREE, "z": _N, "upscale": _S}, ["id", "t0", "t1", "scene", "params"])
FILM_DOC_SCHEMA = _obj({
    "version": _N, "fps": _N, "size": _arr(_N), "dur": _N, "seed": _N, "title": _S, "background": _S,
    "assets": _FREE,
    "shots": _arr(_SHOT),
    "transitions": _arr(_obj({"from": _S, "to": _S, "type": _S, "t": _N, "dur": _N, "params": _FREE},
                             ["from", "to", "type", "t", "dur"])),
    "overlays": _arr(_obj({"id": _S, "t0": _N, "t1": _N, "scene": _S, "params": _FREE}, ["id", "t0", "t1", "scene"])),
    "finish": _FREE,
    "cues": _arr(_obj({"t": _N, "sfx": _S, "gain_db": _N}, ["t", "sfx"])),
    "music": _arr(_obj({"bed": _S, "t0": _N, "t1": _N, "sting": _S, "t": _N})),
    "captions": _arr(_obj({"t0": _N, "t1": _N, "text": _S}, ["t0", "t1", "text"])),
}, ["dur", "shots", "music"])
PLAN_SCHEMA = _obj({
    "shots": _arr(_obj({"id": _S, "intent": _S, "product_visible": _B,
                        "beats": _arr(_obj({"t": _N, "what": _S}))}, ["id", "intent", "product_visible"])),
    "custom_scenes": _arr(_obj({"name": _S, "layer": _S, "describe": _S, "spec": _S, "params": _FREE,
                                "kits": _arr(_S), "fallback": _S}, ["name", "layer", "describe", "spec", "params"])),
})
FILM_SCHEMA = _obj({"film": FILM_DOC_SCHEMA, "plan": PLAN_SCHEMA}, ["film", "plan"])
REVISE_FILM_SCHEMA = _obj({"film": FILM_DOC_SCHEMA, "plan": PLAN_SCHEMA, "changes": _arr(_S),
                           "scene_notes": _arr(_obj({"name": _S, "notes": _S}, ["name", "notes"]))},
                          ["film", "plan", "changes"])
CRITIC_SCHEMA = _obj({
    "scores": _obj({k: _N for k in RUBRIC_KEYS}, list(RUBRIC_KEYS)),
    "frames": _arr(_obj({"cell": _N, "product_visible": _B, "note": _S}, ["cell", "product_visible"])),
    "requirements": _arr(_obj({"text": _S, "met": _B, "note": _S}, ["text", "met"])),
    "per_shot_issues": _arr(_obj({"shot": _S, "target": _S, "severity": _N, "issue": _S, "fix": _S},
                                 ["shot", "target", "severity", "issue", "fix"])),
    "strengths": _arr(_S),
    "verdict": _S,
}, ["scores", "frames", "per_shot_issues", "verdict"])


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
    if p.urls:
        lines.append("- urls: " + ", ".join(p.urls))
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
- Choose worlds the engine can make beautiful: prefer kits/library scenes listed in the catalog, and plan custom
  scenes only for the signature moments the kits cannot do.
- Plan the music: one bed per act (ids from the catalog only), with the turn landing on a bar line, plus stings.
- Plan every product asset's use. The product media is real footage/images: show it, frame it, light it; you may
  stylise it (pixelate, paint over, put it in a world) but it must stay recognisable.
- Name the risks (what could look cheap) and how to avoid them.
- Be specific and visual. "Epic battle" is useless; "the boss winds up for 0.6 s, a curved blade flies left, the
  knight is knocked back 12 px with a red flash and a floating -42" is useful.

Reply with one JSON object matching the schema."""
    parts = [_direction_block(brief), _product_text(brief), _film_frame(brief), catalog.overview(),
             _digest_block(brief)]
    return instructions, "\n\n".join(p for p in parts if p)


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
  CTA (e.g. a `kit:type/...` title overlay) for the last 3-5 s.
- Do not set `assets`, `size`, `fps`, `seed`, `version`: the engine fills them.

PLAN RULES
- plan.shots: one entry per shot: `intent` (what the viewer must see and feel, one sentence), `product_visible`
  (true only if the product media is clearly on screen for most of the shot), `beats` (shot-local times).
  At least 60 % of the runtime must be product-visible shots, and the product must appear by 2 s or be teased then.
- plan.custom_scenes: for each custom scene: `name` (slug), `layer` ('2d' for pixel art and painterly 2D, 'three'
  only when real 3D is essential), `describe` (one line), `params` (name -> {{type, default, doc}}; asset params have
  type 'asset'), `kits` (kit building blocks it should reuse, by kit name), `fallback` (the closest kit scene id, used
  if the code fails), and `spec`: a precise, self-contained animation brief: surface size, palette hexes, layers
  back to front, where the product sits in frame and how big, every beat with shot-local start/end times and easing,
  exact on-screen text strings, sound cue times, and the quality bar (what would make it look cheap and must be
  avoided). The animator has not read the treatment: put everything they need in the spec.

Reply with one JSON object: {{"film": {{...}}, "plan": {{...}}}}."""
    parts = [_direction_block(brief), _product_text(brief), _film_frame(brief),
             "## Approved treatment\n" + _json(treatment), _bar_hint(catalog), catalog.full(),
             "## Scene SDK reference\n" + catalog.sdk]
    return instructions, "\n\n".join(p for p in parts if p)


# ------------------------------------------------------------------------------------ scene code

_SCENE_SELF_CHECK = """\
SELF-CHECK BEFORE ANSWERING
- The file starts with `import { sr } from '../runtime/showreel.js';` and calls `sr.defineScene('<id>', {...})` with the
  exact id given, `layer`, `describe`, `params` (every param with type/default/doc) and `render`.
- render(ctx, t, p) is a pure function of t: nothing is mutated in render, no state carried between frames.
- None of the forbidden APIs appear (Math.random, Date, performance.now, timers, rAF, fetch/XHR/WebSocket, dynamic
  import, eval, new Function, document./window. access, external URLs).
- Every beat of the spec happens at its time; the shot works for the whole duration (no dead tail, no blank frames).
- The product media is drawn from ctx.asset(<param value>) and is the hero when the spec says so.
- All readable text goes through ctx.text inside ctx.safe; every pixel is painted every frame.
- Params with defaults make the scene render sensibly even if a param is missing."""


def scene_prompt(brief: Brief, catalog: Catalog, spec: dict[str, Any], shots: list[dict[str, Any]],
                 plan_shots: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Scene-code step: one custom scene module against the SDK (+ kit building blocks)."""
    sid = f"custom:{spec.get('name')}"
    instructions = f"""\
You are a senior creative coder and motion designer (demoscene precision, feature-animation taste). Write ONE scene
module for Showreel's runtime, exactly to the spec. The scene is rendered frame by frame, out of order, at the shot's
surface size, then composited into the film. It must look finished: this is a commercial, not a prototype.

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
                        issues: list[dict[str, Any]], notes: str = "") -> tuple[str, str]:
    """Apply the critic's visual fixes to one scene, surgically."""
    sid = f"custom:{spec.get('name')}"
    instructions = f"""\
You are a senior creative coder revising a Showreel scene module (`{sid}`) after a creative director reviewed
rendered keyframes. Apply each fix below precisely and visibly; keep everything the review did not criticise.
Improve craft where the fix asks for it (depth, light, motion, composition, legibility); do not add clutter.

{catalog.craft}

{_SCENE_SELF_CHECK}

Reply with the complete revised JavaScript file in ONE ```js fenced block and nothing else."""
    parts = ["## Review: issues and fixes for this scene\n" + _json(issues)]
    if notes.strip():
        parts.append("## Director's notes for this scene\n" + notes.strip())
    parts += ["## Current code\n```js\n" + code + "\n```", "## Scene spec\n" + _json(spec), catalog.assets_text(),
              "## Kit building blocks\n" + catalog.kit_docs([str(k) for k in spec.get("kits") or []], budget=8000),
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
- frames: for every cell say whether the product (the real product media, recognisable) is visible.
- requirements: check every requirement of the user's direction (listed below) against the frames.
- per_shot_issues: at most 8, most important first. Each names the shot id, a `target` ("scene" if fixing it needs
  the custom scene's drawing code changed, "film" if it is timing, params, captions, overlays, transitions, music or
  scene choice), a `severity` (3 = ruins the film, 2 = clearly hurts, 1 = polish), the `issue` as seen, and a
  concrete `fix` an animator can implement (positions, sizes, colours, timings, what to add or remove).
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
    if checks:
        parts.append("## Engine measurements (facts)\n" + "\n".join(f"- {c}" for c in checks))
    return instructions, "\n\n".join(parts)


# ------------------------------------------------------------------------------------ revisions

def revise_film_prompt(brief: Brief, catalog: Catalog, treatment: dict[str, Any], film: dict[str, Any],
                       plan: dict[str, Any], issues: list[dict[str, Any]], notes: str, *,
                       max_custom: int) -> tuple[str, str]:
    """Apply review fixes to the film script surgically (scene code is revised separately)."""
    instructions = f"""\
You are the Director of Showreel Studio revising your film script after review. Apply every fix below that can be
made in film.json or the plan (timing, params, scene choice, transitions, music, cues, captions, overlays). Change
ONLY what the fixes require: keep shot ids, keep shots and settings nobody criticised, keep the custom scenes'
names. Fixes that need a custom scene's drawing code changed are applied by an animator: pass them on, sharpened,
in `scene_notes` (by custom scene name) and update that scene's `spec` if the plan changes. You may replace a
weak custom scene with a kit scene, or add one custom scene (max {max_custom} in total) only when an issue demands it.

{DOCTRINE}

The same FILM.JSON and PLAN rules as before apply (back-to-back shots covering 0..dur, ids from the catalog,
music on bar lines, >= 60 % product-visible runtime). List what you changed in `changes`.

Reply with one JSON object: {{"film": {{...}}, "plan": {{...}}, "changes": [...], "scene_notes": [...]}}."""
    parts = [_direction_block(brief)]
    if issues:
        parts.append("## Review issues and fixes\n" + _json(issues))
    if notes.strip():
        parts.append("## The user's revision notes (highest priority, verbatim)\n" + notes.strip())
    parts += ["## Current film.json\n" + _json(film), "## Current plan\n" + _json(plan),
              "## Treatment\n" + _json(treatment), _bar_hint(catalog), catalog.full(kit_budget=5000)]
    return instructions, "\n\n".join(parts)


def repair_text(previous: Any, errors: list[str]) -> str:
    """Input appendix for a re-ask after validation failed."""
    prev = previous if isinstance(previous, str) else _json(previous)
    if len(prev) > 24000:
        prev = prev[:24000] + "\n[... truncated]"
    return ("\n\n## Your previous answer was REJECTED by the engine\n" + prev +
            "\n\n## Fix exactly these problems and answer again (complete JSON)\n" +
            "\n".join(f"- {e}" for e in errors))
