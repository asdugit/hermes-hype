"""The storyboard prompt: instructions + session input for one structured LLM call.

The model *chooses and orders* real session events, describes the product the session
built (grounded in evidence) and writes narration and short labels; Showreel resolves
every on-screen string from the referenced events and computes all numbers. The prompt
is parameterised by film mode (product trailer by default, making-of "lore", speedrun),
length, style tone and aspect.
"""
from __future__ import annotations

import json
import re

from ..contracts import SCENE_RULES, STAT_KEYS, Event, Product, SceneType
from .facts import (
    STAT_LABELS,
    SessionFacts,
    code_lines,
    data_get,
    diff_rows,
    duration_minutes,
    first_line,
    image_of,
    is_stub,
    terminal_ok,
)
from .options import StoryOptions
from .rules import VO_WORD_CAPS, film_mode, narration_budget, scene_count_range
from .text import normalize_ws, spell_number

T = SceneType

STYLE_TONES: dict[str, str] = {
    "launch": "confident, premium product-launch voice. Crisp declarative sentences, benefit first, "
              "restraint over hype. Labels read like keynote slide titles.",
    "pixel": "playful 16-bit quest. The request is the quest, the plan is the quest log, passing tests are "
             "battles won, the result is the item you get. Light game words in labels (\"Quest accepted\", "
             "\"Boss defeated\"); narration stays clear and factual.",
    "terminal": "terse hacker voice. Short, dry, technical sentences with no fluff. Labels look like log lines "
                "or shell comments (lowercase is fine).",
    "blueprint": "precise engineering voice: specification, measurement, tolerance. Labels read like drawing "
                 "annotations (\"Rev B: refund handling\").",
    "cinematic": "epic but restrained trailer voice. Fewer, weightier lines; leave room for silence; "
                 "the last line lands.",
    "comic": "punchy comic-book voice. Labels read like panel captions (\"Meanwhile, in the test suite\"); "
             "narration still uses full, clear sentences.",
    "ink": "friendly explainer, like a teacher sketching on paper. Plain words, cause and effect.",
    "newspaper": "headline voice. Labels are headlines, narration is a crisp news report.",
}

ASPECT_NOTES: dict[str, str] = {
    "16:9": "landscape 16:9. Code and diffs read well; screenshots fill the frame.",
    "9:16": "vertical 9:16 phone video. Favour product captures, terminal results and short code windows "
            "(focus 12 lines or fewer); keep labels to about 4 words.",
}

# ------------------------------------------------------------------------- modes

MODE_BRIEFS: dict[str, str] = {
    "product": """# This film: a launch trailer for the product this session built
The product is the hero. Spend about 70 % of the film on the product itself (the product in motion, its features, its real output) and about 30 % on one compact "built with Hermes" proof beat. Narration talks about the product and what it does for the person using it, never about the chat.
1. HOOK (2 s): the product doing its best thing. Use the best product_capture, screenshot or artifact; for a CLI or API, its most impressive real output; for a bug fix, the fixed state. A 2-5 word label, and at most five words of narration or none.
2. TITLE: the product's name with its one-liner.
3. Two to four product beats, one feature each: FEATURE (a capture or screenshot plus the feature name in extra.feature, optional bbox and click), SCROLL (a full-page capture) or SCREEN. No visual product? A CLI or API is demoed with TERMINAL scenes that run its real commands; a library with CODE of its usage or entry file plus a TERMINAL demo; a document or research result with SCROLL or SCREEN of its pages and a CALLOUT of its key line; a bug fix with BEFORE_AFTER (failing, then passing) and its DIFF.
4. Built with Hermes, about 30 % of the film: one or two of MONTAGE, DIFF or a passing TERMINAL test run, then STATS (for example tests_passed, files_created, duration_s). Name Hermes here, once or twice.
5. END: the product's call to action, its URL or install/run command from the session.
Voice: a launch film. Say what the product does for its user and show it ("Type in what is in your fridge and Pantry plans the week"). Second person is welcome.""",
    "making_of": """# This film: the making-of (lore)
The build story is the hero, told honestly and in the order it happened: problem, then plan, then the struggle (real failures from the session, shown as they happened), then the breakthrough (the fix that worked), then the result (the product working), then the stats. After HOOK and TITLE, scenes follow session time.
Voice: a candid documentary narrator. Hermes is the protagonist; say plainly what went wrong and what fixed it. No invented drama: every setback must be a real failing event.""",
    "speedrun": """# This film: the build as a speedrun
A fast, chronological time-lapse with a live split timer. Choose 4 to 7 milestone splits from real events (for example "First file", "First run", "First red", "Tests green", "Shipped"): put the label (18 characters max) in extra.split of the scene whose refs[0] is that milestone event. Splits must follow session time. Keep most scenes short, use MONTAGE as the time-lapse between splits, and make the last scene before END the "Shipped" milestone. END is the PB card: the title and the final time, which Showreel computes.
Voice: an energetic speedrun commentator in complete, short sentences ("The first test run catches a refund bug, and that costs a little time."). You may mention the minute mark an event happened at. Celebrate clean moves, own the mistakes, and close on the final time.""",
}

TEMPLATES: dict[str, dict[int, str]] = {
    "product": {
        30: "HOOK (2 s) -> TITLE (3) -> FEATURE (5) -> FEATURE or SCROLL (5) -> SCREEN or TERMINAL demo (5) -> "
            "STATS (3) -> END (4). About 7 scenes; the build beat is just STATS.",
        60: "HOOK (2 s) -> TITLE (3) -> FEATURE (5) -> FEATURE (5) -> SCROLL (6) -> FEATURE or demo (5) -> "
            "BEFORE_AFTER if there was a real fix (5) -> TERMINAL tests green (4) -> MONTAGE (4) -> STATS (4) -> "
            "END (5). About 11 scenes.",
        90: "HOOK (2 s) -> TITLE (4) -> PROBLEM, the need in the user's words (4) -> 4-6 product beats (5-6 each) -> "
            "BEFORE_AFTER (5) -> DIFF (4) -> TERMINAL tests green (4) -> MONTAGE (5) -> STATS (4) -> CALLOUT (3) -> "
            "END (5). About 15 scenes.",
    },
    "making_of": {
        30: "HOOK (2 s) -> TITLE (3) -> PROBLEM (4) -> the struggle: a failing TERMINAL or BEFORE_AFTER (5) -> "
            "the breakthrough: DIFF or TERMINAL green (5) -> the result: SCREEN or FEATURE (4) -> STATS (3) -> END (4).",
        60: "HOOK (2 s) -> TITLE (3) -> PROBLEM (4) -> PLAN (4) -> CODE (6) -> TERMINAL red (4) -> DIFF fix (5) -> "
            "TERMINAL green (4) -> the result: SCREEN, FEATURE or SCROLL (6) -> MONTAGE (4) -> STATS (4) -> END (5).",
        90: "HOOK (2 s) -> TITLE (4) -> PROBLEM (5) -> PLAN (5) -> 2 CODE beats -> every real failure and its fix "
            "(TERMINAL red, DIFF, TERMINAL green) -> the result in 2 scenes -> MONTAGE (5) -> STATS (4) -> "
            "CALLOUT (3) -> END (5).",
    },
    "speedrun": {
        30: "HOOK (2 s) -> TITLE (2) -> CODE \"First file\" (4) -> TERMINAL \"First run\" or \"First red\" (4) -> "
            "TERMINAL \"Tests green\" (4) -> SCREEN \"Shipped\" (4) -> STATS (3) -> END PB card (4).",
        60: "HOOK (2 s) -> TITLE (2) -> PROBLEM, the run starts (3) -> CODE \"First file\" (4) -> MONTAGE time-lapse (4) "
            "-> TERMINAL \"First run\" (4) -> TERMINAL \"First red\" (4) -> DIFF (3) -> TERMINAL \"Tests green\" (4) -> "
            "MONTAGE (4) -> SCREEN or FEATURE \"Shipped\" (4) -> STATS (3) -> END PB card (5).",
        90: "Like 60 s with more splits (up to 7), two or three MONTAGE time-lapses, and every real red and green "
            "moment.",
    },
}

EXAMPLES: dict[str, str] = {
    "product": """Good (60 s product trailer for Pantry, a meal-planning web app; STATS listed tests_passed and \
files_created; the session had product captures and a passing test run):
HOOK      refs [the week-plan capture]  label "Dinner, planned"  vo ""
TITLE     vo "Meet Pantry, the meal planner that starts with what is already in your fridge."
FEATURE   extra.feature "Plans from your fridge"  label "Plans from your fridge"  vo "Type in what you have, and Pantry turns it into a week of dinners."
FEATURE   extra.feature "Shopping list"  label "Only what is missing"  vo "The shopping list only holds what you still need, sorted by aisle."
SCROLL    refs [the full-page recipe capture]  label "Every recipe, step by step"  vo "Every recipe opens on one clean page, from prep to plate."
TERMINAL  refs [the passing test run]  label "Built with Hermes"  vo "Hermes built it in a single session, with every test passing."
STATS     stat_keys [tests_passed, files_created, duration_s]  vo ""
END       cta "npm run dev"  vo "Pantry is ready for tonight's dinner."
For a CLI the product beats are TERMINAL scenes of its real commands instead, each with a line about what that \
output gives the user.""",
    "making_of": """Good (making-of lines, in session order, for a different session):
PROBLEM   vo "It started with one request: plan my dinners from whatever is in the fridge."
PLAN      vo "Hermes breaks the job into five steps and starts with the recipe search."
TERMINAL  refs [the failing run]  label "The build breaks"  vo "The first build fails, because the date picker is imported from the wrong package."
DIFF      vo "Hermes finds the bad import and fixes it in two lines."
TERMINAL  refs [the passing run]  label "Green across the board"  vo "On the next run, every test passes."
SCREEN    vo "And there it is: a full week of dinners, planned from one fridge." """,
    "speedrun": """Good (speedrun lines, in session order, for a different session):
TITLE     vo "This is Pantry, any percent, starting from an empty folder."
CODE      extra.split "First file"  vo "The recipe search lands in the first minute, and the run is on."
TERMINAL  extra.split "First red"  vo "The first build breaks on a bad import, which costs a little time."
DIFF      vo "A two line patch, and the build is back."
TERMINAL  extra.split "Tests green"  vo "Green on the second try, and the pace is back."
SCREEN    extra.split "Shipped"  vo "The week plan renders in the browser, and that is the run."
END       vo "Final time, <the exact session time from STATS, spelled out>." """,
}

BAD_EXAMPLES = """Bad, and why:
- "Code. Tests. Done." -> fragment chain; the voice resets on every fragment.
- "Hermes thinks... and then... it builds." -> ellipses.
- "A revolutionary tool that seamlessly transforms your finances!" -> hype, and nothing on screen proves it.
- "In just 47 seconds it wrote 2,000 lines of code." -> invented numbers, written as digits.
- "Hermes calls write_file on src/pantry/search.py." -> narrates tool calls and file paths.
- "The music swells as hope returns." -> stage directions and mood words.
- A FEATURE named "AI-powered insights" when the session shows nothing like it -> ungrounded feature.
- A scene whose narration describes something its own refs do not show.
- Label "Code Changes" or "Step 3" -> generic; say what it does or what changed."""

_CATALOGUE_ROWS: list[tuple[SceneType, str, str, str]] = [
    (T.HOOK, "the hero asset with the label",
     "product_capture, artifact, screenshot, image_generated, file_patch, file_write or terminal", "-"),
    (T.TITLE, "title and tagline", "no refs needed", "-"),
    (T.FEATURE, "a product frame with one feature highlighted (and a cursor click)",
     "product_capture, screenshot, image_generated or artifact",
     "feature: one of product.features; bbox [x, y, w, h] and click [x, y] in 0..1, optional"),
    (T.SCROLL, "a smooth scroll through a full-page capture", "product_capture or screenshot",
     "scroll [from, to] in 0..1, optional"),
    (T.SCREEN, "a capture, screenshot or image with a push-in",
     "product_capture, artifact, screenshot or image_generated", "bbox [x, y, w, h] in 0..1, optional"),
    (T.PROBLEM, "the user's request in their own words", "user_prompt", "-"),
    (T.PLAN, "the todo list ticking off", "todo", "-"),
    (T.CODE, "an 18-line window of a written file", "file_write",
     "focus_lines [first, last]: 1-based lines to highlight (use the line hints in the index)"),
    (T.DIFF, "changed hunks (24 rows max) with +/- counts", "file_patch (or file_write for a new file)",
     "focus_lines optional: 1-based diff rows"),
    (T.TERMINAL, "the command, its last 12 output lines and exit status", "terminal", "-"),
    (T.MONTAGE, "6-16 tool calls flashing by on the beat", "any tool-call events",
     "montage_refs: 6-16 ids in time order"),
    (T.STATS, "1-3 numbers computed by Showreel", "no refs needed", "stat_keys: 1-3 keys listed under STATS"),
    (T.BEFORE_AFTER, "two states, wiped from before to after",
     ("two images (captures/screenshots), or two text events (file_patch/terminal) such as the failing run "
      "then the passing run"), "before_ref, after_ref"),
    (T.CALLOUT, "one line quoted from the session", "user_prompt, assistant_note, final_answer or terminal",
     "quote_ref + quote: copy 4-12 words exactly from that event"),
    (T.END, "title, cta, url and \"made with Hermes - Showreel\" (speedrun: the PB card)", "no refs needed", "-"),
]


def template_for(seconds: float, mode: str = "product") -> str:
    """The structural template closest to ``seconds`` (30/60/90) for ``mode``."""
    key = 30 if seconds <= 40 else (60 if seconds <= 75 else 90)
    return TEMPLATES[film_mode(mode)][key]


def _catalogue() -> str:
    lines = ["type | shows (resolved by Showreel from refs) | refs[0] must be | extra | seconds | narration words"]
    for st, shows, refs, extra in _CATALOGUE_ROWS:
        lo, hi, _ = SCENE_RULES[st]
        cap = VO_WORD_CAPS[st]
        words = "0 (music only)" if cap == 0 else f"0-{cap}"
        lines.append(f"{st.value} | {shows} | {refs} | {extra} | {lo:g}-{hi:g} | {words}")
    return "\n".join(lines)


def build_instructions(options: StoryOptions) -> str:
    """The instruction block: role, mode brief, rules, scene catalogue, template and examples."""
    secs = options.clamped_seconds()
    mode = film_mode(options.mode)
    style = options.style if options.style in STYLE_TONES else "launch"
    aspect = options.aspect if options.aspect in ASPECT_NOTES else "16:9"
    lo, hi = scene_count_range(secs, mode)
    budget = narration_budget(secs, mode)
    voice_note = "" if options.voice else (
        "\nThis film has no voice: narration becomes burned-in captions, so keep lines short and readable.")
    split_rule = " Speedrun splits: 4-7 scenes carry extra.split, in session order." if mode == "speedrun" else ""
    return f"""You are the editor of a {secs:g}-second film made from one Hermes Agent session (Hermes is an AI agent). Showreel renders your storyboard with the session's REAL evidence: the verbatim code, diffs, terminal output, screenshots, product captures and plans of the events you reference, plus numbers that Showreel computed itself. You describe the product the session built, choose and order events, write the narration a voice will read, and write short on-screen labels. You never type code, commands, output or statistics; you point at events and Showreel shows them.
Make the strongest honest film this session allows, one the user is proud to post.

# The film
- Length {secs:g} s, {ASPECT_NOTES[aspect]}
- Style "{style}": {STYLE_TONES[style]}
- Aim for {lo}-{hi} scenes. Showreel times every scene to the music within the ranges below.
- Narration budget: about {budget} words in total. The voice speaks about 2.4 words per second, and the montage and end-card hold are music-only. Leave room to breathe; shorter is better than crammed.{voice_note}

{MODE_BRIEFS[mode]}

# Structure for {secs:g} s
{template_for(secs, mode)}
Adapt it to the session: leave out scene types the session has no evidence for instead of forcing them. A short chat without tools becomes TITLE, PROBLEM, one or two CALLOUT quotes from the answer, STATS if any, and END.

# The product (always fill "product", in every mode)
- name: its real name (README title, package or repo name, page title); 40 characters max. Never name it after a tool, a Showreel stage or a capture label ("product capture", "screenshot", "write_file"): the film is about the thing the session built, not about how it was filmed.
- one_liner: what it does for its user, 90 characters max, using only what the session shows.
- kind: web_app, site, cli, library, api, game, doc, media, data or other.
- features: up to 6 names of 6 words or fewer, each visible in the evidence (a capture, a todo item, a README line, a command, a code identifier). Never invent a feature.
- urls, entry_files, run_commands: copied exactly from the session; hero_event_ids: the best evidence of the product.
A PRODUCT DRAFT inferred by Showreel may be in the input; correct it where the evidence disagrees. When the draft says "name (fixed)", keep that name (you may drop a descriptive suffix, as in "Tempo" for "Tempo — focus timer").

# Picking evidence
Prefer high-weight events and product captures. Prefer the final, working state over intermediate attempts, except in BEFORE_AFTER and in making-of or speedrun films, where real failures are part of the story. Skip trivial events (file reads, ls, cat) outside MONTAGE. Each scene shows one thing; never show the same event in two scenes except the HOOK.

# Scene catalogue
{_catalogue()}

# Narration (read aloud by a text-to-speech voice)
- Write for the ear: complete, connected sentences that flow from one scene to the next as one script. Vary the length; 8 to 20 words per line works best.
- No fragment chains ("Fast. Simple. Done."), no ellipses, no three-word sentences, no lists of nouns, no exclamation marks, no emoji, no markdown, no code in quotes.
- Present tense, plain words, active verbs.
- Say what things do, not what they are called: "the parser" or "the refund check", never file paths, identifiers with underscores, or tool names like write_file.
- Numbers: only numbers listed under STATS or quoted in the session, spelled as spoken ("fourteen tests", "nine files"). Leave most numbers to the STATS scene. Never estimate or invent amounts ("dozens", "hundreds of lines").
- No mood words or stage directions ("calmly", "dramatic pause", "music swells") and no hype ("revolutionary", "game-changing", "seamless", "effortless", "cutting-edge", "supercharge", "unleash", "magic").
- Each scene's narration is about what that scene's refs show. Empty narration ("") is right for MONTAGE and often for HOOK and CALLOUT.
- The last narration line is upbeat, confident and simple.

# Labels (on screen, 6 words max)
Specific and concrete: "Refunds stop double counting", "Every test passes", "Reports for every month". Not "Code changes", "Step 3" or "Amazing results". No trailing period. Numbers follow the narration rule.

# Title, tagline, CTA, URL
- title: the product's name (or, for a session with no product, a short descriptive name); 40 characters max. No "Hermes" or "Showreel" in it unless the product is about them.
- tagline: one line, 60 characters max: what it does, for whom.
- cta: 40 characters max, a concrete next step from the session (the install or run command, or "Read the code on GitHub").
- url: only a public URL that appears verbatim in the session (repo, deployed page); otherwise omit it.
- accent_hint: omit unless the product's own code defines a clear brand colour (#RRGGBB).

# Examples
{EXAMPLES[mode]}

{BAD_EXAMPLES}

# Output
Return one JSON object and nothing else:
{{"mode": "{mode}", "product": {{"name": "...", "one_liner": "...", "kind": "...", "urls": [], "entry_files": [], "run_commands": [], "features": [], "hero_event_ids": []}}, "title": "...", "tagline": "...", "cta": "...", "scenes": [{{"type": "HOOK", "refs": ["e41"], "vo": "", "label": "...", "extra": {{}}}}, ...]}}
Rules the checker enforces: every ref is an id from the REFERENCE INDEX and refs[0] has a kind the scene accepts; HOOK opens the film when any visual or proof exists; TITLE follows it; END is last; at most one HOOK, TITLE and END; no scene type fills more than a third of the scenes; narration and labels stay within the word limits; quotes are copied exactly; features and numbers are grounded in the session.{split_rule}"""


# ---------------------------------------------------------------------------- input

INDEX_MAX_ENTRIES = 140
INDEX_MAX_CHARS = 14000
DIGEST_MAX_CHARS = 16000
_DEF_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|func|interface|type|struct|impl)\s+\w+"
                     r"|^\s*(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s*)?\(")


def _clip(text: str, limit: int) -> str:
    text = normalize_ws(text)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _mmss(t: float) -> str:
    t = max(0, round(t))
    return f"{t // 60}:{t % 60:02d}"


def describe_event(ev: Event) -> str:
    """One compact index line describing what an event would show on screen."""
    head = f"{ev.id} | {_mmss(ev.t)} | {ev.kind} | w={ev.weight:.2f}"
    if is_stub(ev):
        return f"{head} | (compacted, no content) {_clip(ev.summary, 100)}"
    data = ev.data or {}
    img = image_of(ev)
    if img is not None:
        size = f"{img['w']}x{img['h']}" if img["w"] and img["h"] else "image"
        bits = [size]
        if img["full_page"]:
            bits.append("full page")
        if img["page_title"]:
            bits.append(f"\"{_clip(str(img['page_title']), 60)}\"")
        if img["url"]:
            bits.append(str(img["url"]))
        if ev.kind == "artifact":
            bits.append(f"artifact {data.get('kind', '')} {data.get('path', '')}".strip())
        return f"{head} | {' | '.join(bits)} | {_clip(ev.summary or ev.title, 90)}"
    if ev.kind == "file_write":
        lines = code_lines(ev)
        defs = [f"L{i + 1} {line.strip()[:48]}" for i, line in enumerate(lines) if _DEF_RE.match(line)][:6]
        new = "new file" if data.get("new_file", True) else "rewrite"
        hint = f" | lines: {'; '.join(defs)}" if defs else ""
        return f"{head} | {data.get('path', ev.title)} | {data.get('lang', '')} {len(lines)} lines, {new}{hint}"
    if ev.kind == "file_patch":
        rows = diff_rows(ev)
        n_h = len(data.get("hunks") or [])
        return (f"{head} | {data.get('path', ev.title)} | +{data.get('adds', 0)} -{data.get('dels', 0)}, "
                f"{n_h} hunk(s), {len(rows)} rows")
    if ev.kind == "terminal":
        out = [str(x) for x in data.get("output_lines") or [] if str(x).strip()]
        tail = " / ".join(_clip(x, 70) for x in out[-2:])
        status = "exit 0" if terminal_ok(ev) else f"exit {data.get('exit_code', '?')}"
        return f"{head} | $ {_clip(str(data.get('cmd', ev.title)), 90)} | {status} | {tail}"
    if ev.kind == "todo":
        items = [it for it in data.get("items") or [] if isinstance(it, dict)]
        done = sum(1 for it in items if it.get("status") in ("completed", "done"))
        first = "; ".join(_clip(str(it.get("text", "")), 40) for it in items[:6])
        return f"{head} | {len(items)} items ({done} done): {first}"
    if ev.kind in ("user_prompt", "assistant_note", "final_answer"):
        return f"{head} | \"{_clip(str(data.get('text', ev.summary)), 320)}\""
    if ev.kind == "artifact":
        return f"{head} | {data.get('kind', '')} {data.get('path', ev.title)} (no preview)"
    return f"{head} | {ev.tool or ev.kind} | {_clip(ev.title or ev.summary, 90)}"


def select_index_events(facts: SessionFacts, limit: int = INDEX_MAX_ENTRIES) -> list[Event]:
    """Pick the events worth listing: asks, answers, plans, product visuals, then the highest-weight rest."""
    evs = facts.events
    must: list[Event] = []
    must += [e for e in evs if e.kind == "user_prompt"][:6]
    must += [e for e in evs if e.kind == "final_answer"][-2:]
    todos = sorted((e for e in evs if e.kind == "todo"), key=lambda e: -len(data_get(e, "items", []) or []))
    must += todos[:2]
    must += sorted(facts.visuals(), key=lambda e: (-(e.kind == "product_capture"), -e.weight))[:16]
    chosen = {e.id for e in must}
    rest = sorted((e for e in evs if e.id not in chosen), key=lambda e: (-e.weight, facts.order[e.id]))
    for e in rest:
        if len(chosen) >= limit:
            break
        chosen.add(e.id)
    return [e for e in evs if e.id in chosen]


def build_reference_index(facts: SessionFacts) -> str:
    """The REFERENCE INDEX block, bounded in entries and characters."""
    lines: list[str] = []
    size = 0
    for ev in select_index_events(facts):
        line = describe_event(ev)
        if size + len(line) > INDEX_MAX_CHARS:
            lines.append(f"... ({len(facts.events) - len(lines)} more events not listed)")
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines) if lines else "(no events)"


def build_stats_block(facts: SessionFacts) -> str:
    """STATS block: computed values with their spoken forms (the only numbers narration may use)."""
    st = facts.stats
    lines = []
    for key in STAT_KEYS:
        value = facts.stat_value(key)
        if value is None:
            continue
        n = int(value)
        if key == "duration_s":
            lines.append(f"duration_s = {n} minute(s)  (say \"{spell_number(n)} minute{'s' if n != 1 else ''}\"; "
                         f"exact session time {_mmss(st.duration_s)})")
        else:
            lines.append(f"{key} = {n} {STAT_LABELS[key]}  (say \"{spell_number(n)}\")")
    if st.turns:
        lines.append(f"(context, not a STATS key) turns = {st.turns}")
    if st.commands_failed_then_fixed:
        lines.append(f"(context, not a STATS key) commands_failed_then_fixed = {st.commands_failed_then_fixed}")
    return "\n".join(lines) if lines else "(no computed stats; do not use a STATS scene)"


def build_product_block(product: Product | None, name_locked: bool = False) -> str:
    """The PRODUCT DRAFT block (Showreel's own inference), or a note that there is none."""
    if product is None or not (product.name or product.features or product.hero_event_ids):
        return "(no draft: infer the product from the evidence)"
    p = product
    key = "name (fixed)" if name_locked and p.name else "name"
    rows = [f"{key}: {p.name}", f"one_liner: {p.one_liner}", f"kind: {p.kind}"]
    for key in ("urls", "entry_files", "run_commands", "features", "hero_event_ids"):
        values = getattr(p, key)
        if values:
            rows.append(f"{key}: {json.dumps(values, ensure_ascii=False)}")
    return "\n".join(rows)


def fallback_digest(facts: SessionFacts, max_chars: int = DIGEST_MAX_CHARS) -> str:
    """A chronological event digest for when the session stage supplied none."""
    lines = []
    for ev in facts.events:
        body = ev.summary or ev.title
        if ev.kind in ("user_prompt", "final_answer", "assistant_note"):
            body = _clip(str(data_get(ev, "text", body)), 400)
        elif ev.kind == "terminal":
            out = [str(x) for x in data_get(ev, "output_lines", []) or [] if str(x).strip()]
            body = f"$ {_clip(str(data_get(ev, 'cmd', ev.title)), 100)} -> {_clip(first_line(chr(10).join(out[-3:])), 120)}"
        lines.append(f"[{ev.id} {_mmss(ev.t)} {ev.kind}{'' if ev.ok else ' FAILED'}] {_clip(body, 400)}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2:]
    return head[: head.rfind("\n")] + "\n... (middle of the session omitted) ...\n" + tail[tail.find("\n") + 1:]


def build_input(digest: str, facts: SessionFacts, options: StoryOptions, product: Product | None = None,
                name_locked: bool = False) -> str:
    """The user-content block: film settings, stats, product draft, reference index and digest."""
    secs = options.clamped_seconds()
    mode = film_mode(options.mode)
    lo, hi = scene_count_range(secs, mode)
    digest_text = (digest or "").strip() or fallback_digest(facts)
    if len(digest_text) > DIGEST_MAX_CHARS * 2:
        digest_text = digest_text[: DIGEST_MAX_CHARS * 2] + "\n... (digest truncated)"
    minutes = duration_minutes(facts.stats.duration_s) if facts.stats.duration_s else 0
    brief = f"\n\n# BRIEF FROM THE USER\n{normalize_ws(options.brief)}" if options.brief.strip() else ""
    return f"""# Film settings
mode {mode} | target {secs:g} s | style {options.style} | aspect {options.aspect} | narration budget about {narration_budget(secs, mode)} words | {lo}-{hi} scenes | narration {'spoken' if options.voice else 'captions only'}{brief}

# STATS (computed by Showreel: the only numbers narration may use besides numbers quoted in the session)
{build_stats_block(facts)}

# PRODUCT DRAFT
{build_product_block(product, name_locked)}

# REFERENCE INDEX (id | session time m:ss | kind | weight 0-1 | what it shows). Only these ids are valid refs.
{build_reference_index(facts)}

# SESSION DIGEST ({len(facts.events)} events{f', about {minutes} min' if minutes else ''})
{digest_text}"""


def build_repair_input(original_input: str, previous: object, problems: list[str]) -> str:
    """Input for the single repair call: the original input, the rejected answer and its problems."""
    if isinstance(previous, (dict, list)):
        prev_text = json.dumps(previous, ensure_ascii=False, indent=1)
    else:
        prev_text = str(previous or "(no usable answer)")
    if len(prev_text) > 12000:
        prev_text = prev_text[:12000] + "\n... (truncated)"
    listed = "\n".join(f"- {p}" for p in problems[:40]) or "- (unknown problem)"
    return f"""{original_input}

# Your previous answer (rejected)
{prev_text}

# Problems to fix
{listed}

Return the complete corrected storyboard as one JSON object. Keep everything that was fine, fix exactly the problems listed, and use only ids from the REFERENCE INDEX."""
