"""Shared contracts between Showreel stages (see SPEC.md section 3).

Owned by the orchestrator. Work packages import from here; propose changes in your
report instead of editing this file. Everything is plain dataclasses + JSON-able dicts
so stages can persist their outputs in the job directory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

# --------------------------------------------------------------------------- events

EventKind = Literal[
    "user_prompt", "assistant_note", "final_answer",
    "file_write", "file_patch", "file_read",
    "terminal", "browser_nav", "screenshot", "image_generated",
    "web_search", "web_extract", "todo", "delegate", "skill", "clarify", "tool_other",
    # product-first additions (2026-11-06):
    "artifact",          # a deliverable the session produced: {path, kind: web|image|video|audio|pdf|doc|data|code|other, preview_path?}
    "product_capture",   # captured by Showreel itself from the running product: {path, url, viewport:[w,h], full_page: bool, page_title}
]

# What the film is about (user-facing command words in parentheses):
#   "product"   (/showreel)          launch trailer for what was built; the session supplies proof. DEFAULT.
#   "making_of" (/showreel lore)     the build story is the hero (aliases: bts, process, making-of).
#   "speedrun"  (/showreel speedrun) the build story as a speedrun: live split timer, milestone splits, time-lapse pacing.
FilmMode = Literal["product", "making_of", "speedrun"]
MODE_ALIASES: dict[str, str] = {
    "trailer": "product", "product": "product", "launch": "product",
    "lore": "making_of", "bts": "making_of", "process": "making_of", "making-of": "making_of", "makingof": "making_of",
    "speedrun": "speedrun", "any%": "speedrun",
}


@dataclass
class Split:
    """A speedrun split (mode "speedrun"): a milestone and when it happened."""
    label: str            # "First file", "Tests green", "Shipped" ... (<= 18 chars)
    event_id: str
    session_t: float      # seconds since session start (real time, shown on the timer)
    film_t: float = 0.0   # when it appears in the film (set by the timing solver)


@dataclass
class Product:
    """The thing that was built, inferred from the session (+ optional agent-supplied brief)."""
    name: str = ""
    one_liner: str = ""                 # what it does, <= 90 chars, from session evidence
    kind: str = ""                      # web_app | site | cli | library | api | game | doc | media | data | other
    urls: list[str] = field(default_factory=list)          # localhost / deployed URLs seen in the session
    entry_files: list[str] = field(default_factory=list)   # index.html, main.py, README.md ...
    run_commands: list[str] = field(default_factory=list)  # commands the session used to run/demo it
    features: list[str] = field(default_factory=list)      # <= 6 short feature names grounded in the session
    hero_event_ids: list[str] = field(default_factory=list)  # best visual evidence (captures/screenshots/artifacts)


@dataclass
class Event:
    """One meaningful thing that happened in the session (SPEC 3.1).

    ``data`` holds kind-specific VERBATIM content (already redacted):
      file_write: {path, lang, lines: [str], new_file: bool}
      file_patch: {path, lang, hunks: [{header, lines: [[op, text]]}], adds, dels}
      terminal:   {cmd, output_lines: [str], exit_code: int|None, elapsed_s: float|None}
      screenshot / image_generated: {path (copied into job assets), w, h, url?}
      todo:       {items: [{text, status}]}
      user_prompt / assistant_note / final_answer: {text}
      web_search / web_extract / browser_nav: {query|url, titles?: [str]}
      delegate:   {goals: [str], count}
    A compaction stub sets data["stub"] = True and only ``summary`` is reliable.
    """
    id: str                 # "e0", "e1", ... stable within a job
    t: float                # seconds since session start
    kind: EventKind
    tool: str               # tool name, or "" for messages
    title: str              # short human label, e.g. a file path or command
    summary: str            # <= 160 chars, plain text
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    weight: float = 0.0     # interestingness 0..1 (digest + heuristic storyboard)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Stats:
    """Numbers computed from the session. Never produced by the LLM (SPEC 3.2)."""
    duration_s: float = 0.0          # active time (gaps > 10 min ignored)
    wall_s: float = 0.0              # first to last event, wall clock
    turns: int = 0
    tool_calls: int = 0
    tool_kinds: dict[str, int] = field(default_factory=dict)
    files_created: int = 0
    files_modified: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    commands_run: int = 0
    commands_failed_then_fixed: int = 0
    tests_passed: int | None = None
    screenshots: int = 0
    subagents: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------- scene types

class SceneType(str, Enum):
    HOOK = "HOOK"
    TITLE = "TITLE"
    PROBLEM = "PROBLEM"
    PLAN = "PLAN"
    CODE = "CODE"
    DIFF = "DIFF"
    TERMINAL = "TERMINAL"
    MONTAGE = "MONTAGE"
    SCREEN = "SCREEN"
    STATS = "STATS"
    BEFORE_AFTER = "BEFORE_AFTER"
    CALLOUT = "CALLOUT"
    END = "END"
    FEATURE = "FEATURE"   # product frame + highlighted region + feature name (+ cursor click)
    SCROLL = "SCROLL"     # smooth scroll through a full-page product capture


# (min_s, max_s, accepted ref kinds) — SPEC 3.4
SCENE_RULES: dict[SceneType, tuple[float, float, tuple[str, ...]]] = {
    SceneType.HOOK: (1.5, 3.0, ("product_capture", "artifact", "screenshot", "image_generated", "file_patch", "file_write", "terminal")),
    SceneType.TITLE: (2.0, 4.0, ()),
    SceneType.PROBLEM: (3.0, 6.0, ("user_prompt",)),
    SceneType.PLAN: (3.0, 6.0, ("todo",)),
    SceneType.CODE: (4.0, 8.0, ("file_write",)),
    SceneType.DIFF: (3.0, 6.0, ("file_patch", "file_write")),
    SceneType.TERMINAL: (3.0, 7.0, ("terminal",)),
    SceneType.MONTAGE: (3.0, 6.0, ("*",)),
    SceneType.SCREEN: (4.0, 7.0, ("product_capture", "artifact", "screenshot", "image_generated")),
    SceneType.STATS: (2.0, 4.0, ()),
    SceneType.BEFORE_AFTER: (3.0, 6.0, ("product_capture", "screenshot", "image_generated", "file_patch", "terminal")),
    SceneType.CALLOUT: (2.0, 4.0, ("user_prompt", "assistant_note", "final_answer", "terminal")),
    SceneType.END: (3.0, 5.0, ()),
    SceneType.FEATURE: (3.0, 6.0, ("product_capture", "screenshot", "image_generated", "artifact")),
    SceneType.SCROLL: (4.0, 8.0, ("product_capture", "screenshot")),
}

STAT_KEYS = (
    "duration_s", "tool_calls", "files_created", "files_modified", "lines_added",
    "lines_removed", "commands_run", "tests_passed", "screenshots", "subagents",
)

# ----------------------------------------------------------------------- storyboard

@dataclass
class StoryScene:
    type: SceneType
    refs: list[str] = field(default_factory=list)   # event ids
    vo: str = ""                                     # narration, <= 28 words, spoken English
    label: str = ""                                  # <= 6 words on-screen label
    extra: dict[str, Any] = field(default_factory=dict)  # focus_lines, stat_keys, before_ref, after_ref, bbox, quote...


@dataclass
class Storyboard:
    title: str
    tagline: str
    scenes: list[StoryScene]
    cta: str = ""
    url: str = ""
    accent_hint: str = ""
    source: Literal["llm", "repaired", "heuristic"] = "llm"
    mode: FilmMode = "product"
    product: Product | None = None


# ------------------------------------------------------------------------- timeline

Aspect = Literal["16:9", "9:16"]
ASPECT_SIZES: dict[str, tuple[int, int]] = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
PREVIEW_SIZES: dict[str, tuple[int, int]] = {"16:9": (960, 540), "9:16": (540, 960)}


@dataclass
class Caption:
    t0: float
    t1: float
    text: str


@dataclass
class TimelineScene:
    i: int
    type: SceneType
    t0: float
    t1: float
    data: dict[str, Any]          # resolved verbatim content for the template
    label: str = ""
    vo_path: str = ""             # narration clip (wav) or ""
    vo_t0: float = 0.0            # narration start (absolute seconds)
    captions: list[Caption] = field(default_factory=list)
    transition_in: Literal["cut", "match", "push", "wipe"] = "cut"


@dataclass
class Cue:
    t: float
    sfx: str
    gain_db: float = 0.0
    align: Literal["auto", "onset", "peak", "end"] = "auto"


@dataclass
class Timeline:
    style: str
    aspect: Aspect
    fps: int
    w: int
    h: int
    dur: float
    bpm: float
    seed: int
    scenes: list[TimelineScene]
    cues: list[Cue] = field(default_factory=list)
    title: str = ""
    accent: str = ""
    mode: FilmMode = "product"
    splits: list[Split] = field(default_factory=list)   # speedrun overlay; empty otherwise

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for s in d["scenes"]:
            s["type"] = s["type"].value if isinstance(s["type"], SceneType) else s["type"]
        return d


# ------------------------------------------------------------------- page contract
# The rendered page (runtime + style pack + timeline) must expose window.__sr:
#   __sr.ready: Promise<void>          fonts loaded (document.fonts.check) + images decoded
#   __sr.dur, __sr.fps, __sr.w, __sr.h
#   __sr.seek(t: number): Promise<void>  pure function of t; resolves after layout+paint (1 rAF)
#   __sr.cues: Array<{t, sfx, gain_db, align}>   template-emitted SFX cues
#   __sr.qa(t: number): Array<{kind, msg, rect}> DOM checks (clip/overlap/safe-area/min glyph)
# Templates must not use Math.random, Date, performance.now, setTimeout or CSS transitions.
PAGE_GLOBAL = "__sr"
