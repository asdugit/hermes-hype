"""Caption phrase splitting and timing."""
from __future__ import annotations

import pytest

from showreel_core.audio.captions import (LEAD_S, fallback_duration, fallback_timing, phrase_timing, split_phrases,
                                          syllables)

LINE = ("Your agent just built something real. Auteur turns that session into a film: "
        "the code, the diffs, the moment the tests passed.")


@pytest.mark.parametrize("word,n", [("agent", 2), ("real", 1), ("Auteur", 2), ("session", 2), ("the", 1),
                                    ("passed", 1), ("film", 1), ("moment", 2), ("1,247", 5)])
def test_syllables(word, n):
    assert syllables(word) == n


def test_split_respects_max_words_and_sentences():
    ph = split_phrases(LINE)
    assert all(1 <= len(p.split()) <= 6 for p in ph)
    assert " ".join(ph) == " ".join(LINE.split())
    assert ph[0] == "Your agent just built something real."
    assert any(p.endswith("film:") for p in ph)          # clause punctuation is a preferred break


def test_split_avoids_orphans_when_possible():
    ph = split_phrases("We shipped the parser, the renderer and the tests in one afternoon today")
    assert min(len(p.split()) for p in ph) >= 2


def test_phrase_timing_is_chained_and_covers_clip():
    caps = phrase_timing(LINE, 7.5, offset=10.0)
    assert caps[0].t0 == pytest.approx(10.0, abs=1e-6)
    for a, b in zip(caps, caps[1:], strict=False):
        assert a.t1 == pytest.approx(b.t0)               # no blank frame between phrases
        assert b.t0 > a.t0
    assert caps[-1].t1 == pytest.approx(10.0 + 7.5 + 0.3)
    # later phrases start at most LEAD_S before their syllable-weighted position
    assert caps[1].t0 > 10.0 + 7.5 * 0.2 - LEAD_S


def test_fallback_timing_three_words_per_second():
    caps = fallback_timing("one two three four five six seven", start=2.0)
    total = sum(len(c.text.split()) for c in caps) / 3.0 + 0.3 * len(caps)
    assert caps[0].t0 == 2.0
    assert caps[-1].t1 == pytest.approx(2.0 + total, abs=1e-3)
    assert fallback_duration("one two three") == pytest.approx(1.3)


def test_empty_text():
    assert split_phrases("   ") == []
    assert phrase_timing("", 3.0) == []
    assert fallback_timing("") == []
