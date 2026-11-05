"""Text helpers: spoken numbers, trimming, phrases, verbatim spans."""
from showreel_core.story.facts import find_span
from showreel_core.story.text import (extract_numbers, phrases, spell_digits, spell_number, trim_label, trim_words,
                                      word_count)


def values(text):
    return [n.value for n in extract_numbers(text)]


def test_extract_numbers_digits_and_words():
    assert values("It ran forty-two tests and one hundred and five checks") == [42, 105]
    assert values("in 3.5 seconds, 1,200 lines") == [3.5, 1200]
    assert values("a dozen files and a hundred ways") == [12, 100]
    assert values("three point five stars") == [3.5]
    assert values("two and three") == [2, 3]


def test_extract_numbers_ignores_identifiers_and_words_containing_numbers():
    assert values("e17 v1 someone none") == []


def test_spell_number():
    assert spell_number(0) == "zero"
    assert spell_number(42) == "forty-two"
    assert spell_number(1205) == "one thousand two hundred five"
    assert spell_number(2_000_000) == "two million"


def test_spell_digits_keeps_versions():
    assert spell_digits("It wrote 14 tests in Python 3.11.") == "It wrote fourteen tests in Python 3.11."


def test_trim_words_prefers_whole_sentences():
    assert trim_words("This is the first sentence. And here is a much longer second one.", 7) == \
        "This is the first sentence."
    out = trim_words("One very long sentence, with a clause, that keeps going and going forever", 8)
    assert word_count(out) <= 8 and out.endswith(".")


def test_trim_label():
    assert trim_label("One two three four five six seven.", 6) == "One two three four five six"


def test_phrases_are_short_and_cover_all_words():
    text = "Hermes reads the codebase, writes a plan, and gets straight to work on the exporter. Then the tests pass."
    chunks = phrases(text)
    assert all(word_count(c) <= 7 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_find_span_returns_verbatim_source():
    source = "All  14 tests \u201cpass\u201d now.\nDone."
    assert find_span(source, 'all 14 tests "pass" now') == "All  14 tests \u201cpass\u201d now."
    assert find_span(source, "missing words") is None
