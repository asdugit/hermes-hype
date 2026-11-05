"""Phrase-level caption timing (stdlib only).

Narration is split into phrases of at most 6 words at the most natural break (sentence end > clause
punctuation > before a conjunction/preposition, nearest the middle). With a measured voice clip the
phrases are spread over the clip by syllable weight plus pause weight for punctuation; without one
(captions-only mode) they run at ~3 words/s + 0.3 s per phrase.
"""
from __future__ import annotations

import re

from ..contracts import Caption

MAX_WORDS = 6
LEAD_S = 0.066           # captions appear 2 frames before the first word
_BREAK_BEFORE = {"and", "but", "or", "so", "because", "while", "when", "then", "that", "which", "with", "into",
                 "for", "to", "from", "in", "on", "of", "the", "until", "after", "before", "as"}
_PAUSE_UNITS = {".": 1.6, "!": 1.6, "?": 1.6, ":": 1.1, ";": 1.1, ",": 0.7, "\u2014": 0.9, "-": 0.5}
_WORD = re.compile(r"\S+")


def syllables(word: str) -> int:
    """English syllable estimate (vowel groups with common corrections); digits count per spoken digit."""
    w = word.lower()
    digits = re.sub(r"[^0-9]", "", w)
    if digits:
        return max(1, int(len(digits) * 1.4))
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith(("ed",)) and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1
    return max(1, n)


def _trail(word: str) -> str:
    m = re.search(r"([.!?:;,\u2014-]+)[\"')\]]*$", word)
    return m.group(1)[-1] if m else ""


def _best_split(words: list[str]) -> int:
    """Index to split ``words`` into two non-empty halves (prefers punctuation, then function words, near middle)."""
    n = len(words)
    best, best_score = n // 2, -1e9
    for i in range(1, n):
        p = _trail(words[i - 1])
        score = {".": 6.0, "!": 6.0, "?": 6.0, ":": 4.5, ";": 4.5, "\u2014": 4.0, ",": 3.5, "-": 1.0}.get(p, 0.0)
        if not p and words[i].lower().strip("\"'(") in _BREAK_BEFORE:
            score += 1.5
        score -= abs(i - n / 2) * 0.8
        if min(i, n - i) == 1:
            score -= 2.5            # avoid one-word orphans
        if score > best_score:
            best, best_score = i, score
    return best


def split_phrases(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """Split narration into caption phrases of <= ``max_words`` words."""
    words = _WORD.findall(text.strip())
    if not words:
        return []
    # hard sentence boundaries first
    sents: list[list[str]] = [[]]
    for w in words:
        sents[-1].append(w)
        if _trail(w) in (".", "!", "?"):
            sents.append([])
    out: list[str] = []

    def rec(ws: list[str]) -> None:
        if len(ws) <= max_words:
            out.append(" ".join(ws))
            return
        i = _best_split(ws)
        rec(ws[:i])
        rec(ws[i:])

    for s in sents:
        if s:
            rec(s)
    return out


def _units(phrase: str) -> tuple[float, float]:
    """(speech units, trailing pause units) for a phrase."""
    words = phrase.split()
    sp = sum(syllables(w) for w in words)
    inner = sum(_PAUSE_UNITS.get(_trail(w), 0.0) for w in words[:-1])
    return sp + inner, _PAUSE_UNITS.get(_trail(words[-1]), 0.0) if words else 0.0


def phrase_timing(text: str, duration: float, offset: float = 0.0, max_words: int = MAX_WORDS,
                  hold: float = 0.3) -> list[Caption]:
    """Caption phrases spread over a measured clip of ``duration`` s starting at ``offset``.

    Phrases chain with no gap (each holds until the next appears); the last one holds ``hold`` s past the clip.
    """
    phrases = split_phrases(text, max_words)
    if not phrases or duration <= 0:
        return []
    units = [_units(p) for p in phrases]
    total = sum(a for a, _ in units) + sum(b for _, b in units[:-1])
    if total <= 0:
        return []
    k = duration / total
    caps: list[Caption] = []
    t = 0.0
    starts = []
    for (sp, pause) in units:
        starts.append(t)
        t += (sp + pause) * k
    for i, p in enumerate(phrases):
        t0 = max(0.0, starts[i] - LEAD_S) + offset
        t1 = (max(0.0, starts[i + 1] - LEAD_S) + offset) if i + 1 < len(phrases) else offset + duration + hold
        caps.append(Caption(round(t0, 3), round(t1, 3), p))
    return caps


def fallback_timing(text: str, start: float = 0.0, words_per_s: float = 3.0, per_phrase_s: float = 0.3,
                    max_words: int = MAX_WORDS) -> list[Caption]:
    """Captions-only mode: ~3 words/s + 0.3 s per phrase, back to back from ``start``."""
    caps: list[Caption] = []
    t = start
    for p in split_phrases(text, max_words):
        d = len(p.split()) / words_per_s + per_phrase_s
        caps.append(Caption(round(t, 3), round(t + d, 3), p))
        t += d
    return caps


def fallback_duration(text: str, words_per_s: float = 3.0, per_phrase_s: float = 0.3) -> float:
    """Reading time the captions-only timeline should budget for ``text``."""
    caps = fallback_timing(text, 0.0, words_per_s, per_phrase_s)
    return caps[-1].t1 if caps else 0.0
