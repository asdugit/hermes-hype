"""Small text helpers for storyboards: word counts, sentences, spoken numbers, syllables.

Everything here is pure stdlib and deterministic. Narration is written for a TTS voice,
so numbers are spelled the way they are spoken ("forty-two"), and validators need to
read spelled numbers back (``extract_numbers``) to check them against computed stats.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z0-9\u00C0-\u024F][A-Za-z0-9\u00C0-\u024F'’\-_.]*")
_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"dozen"}

_DIGIT_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")


def words(text: str) -> list[str]:
    """Split ``text`` into spoken-ish words (punctuation dropped, hyphenated kept whole)."""
    return _WORD_RE.findall(text or "")


def word_count(text: str) -> int:
    """Number of words in ``text`` (see :func:`words`)."""
    return len(words(text))


def sentences(text: str) -> list[str]:
    """Split text into sentences, keeping their terminal punctuation."""
    out = [m.group(0).strip() for m in _SENTENCE_RE.finditer((text or "").strip())]
    return [s for s in out if s and any(ch.isalnum() for ch in s)]


def normalize_ws(text: str) -> str:
    """Collapse whitespace runs to single spaces and strip."""
    return re.sub(r"\s+", " ", text or "").strip()


def trim_words(text: str, max_words: int) -> str:
    """Trim ``text`` to at most ``max_words`` words, preferring whole sentences.

    Keeps as many complete sentences as fit; if even the first sentence is too long it
    is cut at the last comma/semicolon that fits, else at the word limit, and closed
    with a period so TTS ends the phrase cleanly.
    """
    text = normalize_ws(text)
    if max_words <= 0:
        return ""
    if word_count(text) <= max_words:
        return text
    kept: list[str] = []
    for sent in sentences(text):
        if word_count(" ".join(kept + [sent])) <= max_words:
            kept.append(sent)
        else:
            break
    if kept:
        return " ".join(kept)
    first = sentences(text)[0] if sentences(text) else text
    tokens = first.split(" ")
    acc: list[str] = []
    best_clause = ""
    for tok in tokens:
        if word_count(" ".join(acc + [tok])) > max_words:
            break
        acc.append(tok)
        if tok.endswith((",", ";", ":")):
            best_clause = " ".join(acc)
    cut = best_clause if best_clause and word_count(best_clause) >= max(3, max_words // 2) else " ".join(acc)
    return cut.rstrip(",;:—- ") + "."


def trim_chars(text: str, max_chars: int) -> str:
    """Trim ``text`` to ``max_chars`` at a word boundary (no ellipsis added)."""
    text = normalize_ws(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars + 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    else:
        cut = cut[:max_chars]
    return cut.rstrip(",;:—-– ")


def trim_label(text: str, max_words: int = 6) -> str:
    """Trim an on-screen label to ``max_words`` words, no trailing period."""
    toks = normalize_ws(text).split(" ")
    out = " ".join(toks[:max_words]) if toks != [""] else ""
    return out.rstrip(".,;: ")


# ----------------------------------------------------------------------- numbers

_ONES_SPELL = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
               "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
               "seventeen", "eighteen", "nineteen"]
_TENS_SPELL = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def spell_number(n: int) -> str:
    """Spell a non-negative integer (< 1e9) the way a narrator says it: 1205 -> 'one thousand two hundred five'."""
    if n < 0:
        return "minus " + spell_number(-n)
    if n < 20:
        return _ONES_SPELL[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS_SPELL[tens] + ("-" + _ONES_SPELL[ones] if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return _ONES_SPELL[hundreds] + " hundred" + (" " + spell_number(rest) if rest else "")
    for scale, name in ((1_000_000, "million"), (1000, "thousand")):
        if n >= scale:
            major, rest = divmod(n, scale)
            return spell_number(major) + " " + name + (" " + spell_number(rest) if rest else "")
    return str(n)  # pragma: no cover - unreachable


@dataclass(frozen=True)
class NumberMention:
    """A number found in text: character span, numeric value and whether it was digits."""
    start: int
    end: int
    value: float
    digits: bool
    text: str


def _parse_word_run(tokens: list[str]) -> float | None:
    """Parse a run of number words ("forty-two", "one hundred and five") to a value."""
    total = 0.0
    current = 0.0
    seen = False
    for tok in tokens:
        tok = tok.lower()
        if tok in ("and", "a"):
            continue
        parts = tok.split("-")
        if all(p in _UNITS or p in _TENS for p in parts):
            for p in parts:
                current += _UNITS.get(p, _TENS.get(p, 0))
            seen = True
        elif tok in _SCALES:
            scale = _SCALES[tok]
            current = (current or 1) * scale
            if scale >= 1000:
                total += current
                current = 0
            seen = True
        elif tok == "dozen":
            current = (current or 1) * 12
            seen = True
        else:
            return None
    return total + current if seen else None


def extract_numbers(text: str) -> list[NumberMention]:
    """Find numbers written as digits or as English words in ``text``.

    Handles "42", "1,200", "3.5", "forty-two", "one hundred and five", "a dozen",
    "three point five". Ordinals ("first", "second") are not numbers here.
    """
    text = text or ""
    found: list[NumberMention] = []
    taken: list[tuple[int, int]] = []
    for m in _DIGIT_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        frac = m.group(2)
        value = float(raw + ("." + frac if frac else ""))
        found.append(NumberMention(m.start(), m.end(), value, True, m.group(0)))
        taken.append((m.start(), m.end()))
    token_re = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
    toks = [(m.start(), m.end(), m.group(0)) for m in token_re.finditer(text)]
    i = 0
    while i < len(toks):
        s, e, w = toks[i]
        lw = w.lower()
        is_num = lw in _NUMBER_WORDS or all(p in _UNITS or p in _TENS for p in lw.split("-"))
        if not is_num:
            i += 1
            continue
        j = i
        run = [w]
        while j + 1 < len(toks):
            nxt = toks[j + 1][2].lower()
            gap = text[toks[j][1]:toks[j + 1][0]]
            if gap.strip() not in ("",):
                break
            joins_and = (nxt == "and" and run[-1].lower() in ("hundred", "thousand")
                         and j + 2 < len(toks) and toks[j + 2][2].lower() in _NUMBER_WORDS)
            if nxt in _NUMBER_WORDS or joins_and or all(p in _UNITS or p in _TENS for p in nxt.split("-")):
                run.append(toks[j + 1][2])
                j += 1
            else:
                break
        # leading "a" as in "a hundred" / "a dozen"
        start = s
        if i > 0 and toks[i - 1][2].lower() == "a" and lw in ("hundred", "thousand", "dozen"):
            start = toks[i - 1][0]
        value = _parse_word_run(run)
        end = toks[j][1]
        # "three point five"
        if value is not None and j + 2 < len(toks) and toks[j + 1][2].lower() == "point" \
                and toks[j + 2][2].lower() in _UNITS:
            value = float(f"{int(value)}.{_UNITS[toks[j + 2][2].lower()]}")
            end = toks[j + 2][1]
            j += 2
        if value is not None and not any(a <= start < b for a, b in taken):
            found.append(NumberMention(start, end, value, False, text[start:end]))
        i = j + 1
    found.sort(key=lambda n: n.start)
    return found


def spell_digits(text: str, allowed: set[float] | None = None) -> str:
    """Replace standalone integer digits (< 10000) with spoken words.

    Decimals, versions (``3.11``), identifiers and numbers inside words are left alone.
    When ``allowed`` is given only those values are converted.
    """
    def repl(m: re.Match[str]) -> str:
        if m.group(2):
            return m.group(0)
        raw = m.group(1).replace(",", "")
        n = int(raw)
        if n >= 10000 or (allowed is not None and float(n) not in allowed):
            return m.group(0)
        return spell_number(n)
    return _DIGIT_RE.sub(repl, text)


# ----------------------------------------------------------------------- syllables

_VOWEL_GROUP = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    """Rough English syllable count (>= 1) for caption timing weights."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return max(1, len(word) // 3) if any(ch.isdigit() for ch in word) else 1
    count = len(_VOWEL_GROUP.findall(w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def phrases(text: str, max_words: int = 7) -> list[str]:
    """Split narration into caption phrases of <= ``max_words`` words at natural breaks."""
    out: list[str] = []
    for sent in sentences(text):
        parts = [p.strip() for p in re.split(r"(?<=[,;:—])\s+", sent) if p.strip()]
        buf: list[str] = []
        for part in parts:
            ptoks = part.split(" ")
            if buf and len(buf) + len(ptoks) > max_words:
                out.append(" ".join(buf))
                buf = []
            buf.extend(ptoks)
            while len(buf) > max_words:
                # split long runs evenly rather than leaving a one-word orphan
                n_chunks = -(-len(buf) // max_words)
                size = -(-len(buf) // n_chunks)
                out.append(" ".join(buf[:size]))
                buf = buf[size:]
        if buf:
            out.append(" ".join(buf))
    return out
