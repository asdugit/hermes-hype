"""Film-grammar constants shared by prompt, validator, heuristic and timing solver.

Durations and accepted ref kinds come from :data:`contracts.SCENE_RULES`; everything here
is derived policy: narration caps, budgets, scene counts and the per-mode drop/grow/shrink
priorities (product trailer, making-of "lore", speedrun).
"""
from __future__ import annotations

import math

from ..contracts import MODE_ALIASES, SCENE_RULES, SceneType

T = SceneType

#: Narration pace used for budgets (words per second, ~145 wpm: leaves room for pauses).
WORDS_PER_SECOND = 2.4
#: Pace assumed when we must guess a clip length before TTS has run (~155 wpm).
TTS_WORDS_PER_SECOND = 2.6
#: Captions-only reading pace (SPEC 5: ~3 words/s + 0.3 s per phrase).
CAPTION_WORDS_PER_SECOND = 3.0
CAPTION_PHRASE_PAD = 0.3

FILM_MODES = ("product", "making_of", "speedrun")
PRODUCT_KINDS = ("web_app", "site", "cli", "library", "api", "game", "doc", "media", "data", "other")
#: Event kinds that show the product itself as a picture.
PRODUCT_VISUAL_KINDS = ("product_capture", "artifact", "screenshot", "image_generated")

#: Scenes that show the product (a product film spends ~70 % of its content here).
PRODUCT_TYPES = frozenset({T.HOOK, T.FEATURE, T.SCROLL, T.SCREEN, T.BEFORE_AFTER})
#: Scenes that tell the build story (the "built with Hermes" beat in a product film).
BUILD_TYPES = frozenset({T.PROBLEM, T.PLAN, T.CODE, T.DIFF, T.MONTAGE, T.STATS})
#: Scenes that must appear at most once.
SINGLETONS = (T.HOOK, T.TITLE, T.END)
#: Scenes that need no event refs.
REFLESS = frozenset({T.TITLE, T.STATS, T.END})
#: Event kinds that count as "tool calls" for MONTAGE.
NON_TOOL_KINDS = frozenset({"user_prompt", "assistant_note", "final_answer", "product_capture"})
#: Max share of content scenes that may tell the build story in a product film.
MAX_BUILD_SHARE = 0.45
#: Speedrun split count and label length.
SPLITS_MIN, SPLITS_MAX, SPLIT_CHARS = 4, 7, 18

MAX_TYPE_SHARE = 0.35


def _cap(scene: SceneType) -> int:
    lo, hi, _ = SCENE_RULES[scene]
    return int(math.floor((hi - 0.8) * 2.5))


#: Narration word cap per scene type, so a clip fits inside the scene's max duration.
VO_WORD_CAPS: dict[SceneType, int] = {t: _cap(t) for t in SceneType}
VO_WORD_CAPS[T.MONTAGE] = 0  # montage is music-only

#: Drop order when a film is too long (lower = dropped first). END is never dropped.
DROP_PRIORITY: dict[str, dict[SceneType, float]] = {
    "product": {
        T.PROBLEM: 1, T.PLAN: 1.5, T.CODE: 2, T.CALLOUT: 2.5, T.MONTAGE: 3, T.DIFF: 3.5, T.TERMINAL: 4,
        T.BEFORE_AFTER: 6, T.SCREEN: 6.5, T.SCROLL: 7, T.FEATURE: 7.5, T.STATS: 8.5, T.TITLE: 10, T.HOOK: 11,
        T.END: 99,
    },
    "making_of": {
        T.MONTAGE: 1, T.CALLOUT: 2, T.SCROLL: 2.5, T.FEATURE: 3, T.PLAN: 3.5, T.CODE: 5, T.DIFF: 5.5,
        T.SCREEN: 6, T.BEFORE_AFTER: 6.5, T.TERMINAL: 6.5, T.PROBLEM: 7, T.STATS: 9, T.TITLE: 10, T.HOOK: 11,
        T.END: 99,
    },
    "speedrun": {
        T.CALLOUT: 1, T.PLAN: 1.5, T.SCROLL: 2, T.FEATURE: 2.5, T.CODE: 3, T.SCREEN: 4, T.DIFF: 4.5,
        T.BEFORE_AFTER: 5, T.TERMINAL: 5.5, T.MONTAGE: 6, T.PROBLEM: 7, T.STATS: 8, T.TITLE: 10, T.HOOK: 11,
        T.END: 99,
    },
}

#: Grow order when a film is too short (index 0 absorbs time first; HOOK never grows).
GROW_ORDER: dict[str, tuple[SceneType, ...]] = {
    "product": (T.END, T.FEATURE, T.SCROLL, T.SCREEN, T.BEFORE_AFTER, T.TERMINAL, T.TITLE, T.MONTAGE, T.STATS,
                T.CODE, T.DIFF, T.CALLOUT, T.PLAN, T.PROBLEM),
    "making_of": (T.END, T.MONTAGE, T.SCREEN, T.BEFORE_AFTER, T.CODE, T.TERMINAL, T.DIFF, T.FEATURE, T.SCROLL,
                  T.STATS, T.PLAN, T.PROBLEM, T.CALLOUT, T.TITLE),
    "speedrun": (T.END, T.MONTAGE, T.TERMINAL, T.BEFORE_AFTER, T.SCREEN, T.DIFF, T.CODE, T.STATS, T.FEATURE,
                 T.SCROLL, T.PROBLEM, T.PLAN, T.CALLOUT, T.TITLE),
}
#: Shrink order when a film is too long (index 0 gives time back first).
SHRINK_ORDER: dict[str, tuple[SceneType, ...]] = {
    "product": (T.MONTAGE, T.PROBLEM, T.PLAN, T.CODE, T.DIFF, T.CALLOUT, T.END, T.TERMINAL, T.STATS, T.TITLE,
                T.BEFORE_AFTER, T.SCREEN, T.SCROLL, T.FEATURE, T.HOOK),
    "making_of": (T.MONTAGE, T.END, T.CALLOUT, T.PLAN, T.SCROLL, T.FEATURE, T.SCREEN, T.CODE, T.PROBLEM,
                  T.BEFORE_AFTER, T.TERMINAL, T.DIFF, T.TITLE, T.STATS, T.HOOK),
    "speedrun": (T.CALLOUT, T.PLAN, T.CODE, T.SCROLL, T.FEATURE, T.SCREEN, T.DIFF, T.PROBLEM, T.TERMINAL,
                 T.BEFORE_AFTER, T.TITLE, T.MONTAGE, T.STATS, T.END, T.HOOK),
}


def film_mode(mode: str | None) -> str:
    """Normalise a film mode or command alias ("lore" -> "making_of"); default "product"."""
    key = (mode or "").strip().lower()
    if key in FILM_MODES:
        return key
    return MODE_ALIASES.get(key, "product")


def accepted_kinds(scene: SceneType) -> tuple[str, ...]:
    """Event kinds a scene's primary ref may have (``("*",)`` = any tool call)."""
    return SCENE_RULES[scene][2]


def narration_budget(seconds: float, mode: str = "product") -> int:
    """Total narration words for a film: ~2.4 words/s minus music-only montage and holds.

    Speedruns talk less (time-lapse stretches run on music and the split timer).
    """
    montage = 0.0 if seconds <= 35 else (4.0 if seconds <= 70 else 5.0)
    holds = 5.0  # hook flash + end-card hold
    words = WORDS_PER_SECOND * max(0.0, seconds - montage - holds)
    if film_mode(mode) == "speedrun":
        words *= 0.75
    return max(20, int(round(words)))


def scene_count_range(seconds: float, mode: str = "product") -> tuple[int, int]:
    """Sensible scene count for a film length (average 4-6 s per scene; speedruns cut faster)."""
    per = 0.85 if film_mode(mode) == "speedrun" else 1.0
    lo = max(4, int(round(seconds / (6.0 * per))))
    hi = max(lo + 1, int(round(seconds / (4.2 * per))))
    return lo, min(hi, 22)


def max_type_count(n_scenes: int) -> int:
    """Max scenes of one type so no type exceeds 35 % of the film (at least 1)."""
    return max(1, int(math.floor(MAX_TYPE_SHARE * n_scenes)))
