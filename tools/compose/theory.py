"""Tiny music-theory helpers: note names, scales, roman-numeral chords, voice-led voicings."""
from __future__ import annotations

NOTE = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7,
        "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}

MODES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
}


def midi(name: str) -> int:
    """'F#3' -> 54."""
    s = name.strip().upper()
    i = 2 if len(s) > 2 and s[1] in "#B" and not s[1:].lstrip("-").isdigit() else 1
    return NOTE[s[:i]] + 12 * (int(s[i:]) + 1)


class Key:
    """A tonal centre + mode; degrees are 1-based scale steps (can exceed 7 or go below 1)."""

    def __init__(self, tonic: str, mode: str = "major"):
        self.tonic = NOTE[tonic.upper()]
        self.mode = mode
        self.steps = MODES[mode]

    def degree(self, d: int, octave: int = 4, alter: int = 0) -> int:
        """MIDI note of scale degree ``d`` (1 = tonic) in ``octave``."""
        k = d - 1
        o, idx = divmod(k, 7)
        return 12 * (octave + 1 + o) + self.tonic + self.steps[idx] + alter

    def chord(self, root_degree: int, kind: str = "triad", octave: int = 3, alter: int = 0) -> list[int]:
        """Chord on a degree.

        Diatonic kinds (stacked from the scale): triad, 7, 9, add9, sus2, sus4, 6, 5.
        Fixed-quality kinds (semitones over the diatonic root, for borrowed/chromatic chords such as V in
        minor or bVII in major): maj, min, dim, aug, maj7, dom7, m7, m9, maj9, dom9, add9maj, 7sus4.
        """
        root = self.degree(root_degree, octave) + alter
        if kind in QUALITY:
            return [root + s for s in QUALITY[kind]]
        stacks = {"triad": [0, 2, 4], "7": [0, 2, 4, 6], "9": [0, 2, 4, 6, 8], "add9": [0, 2, 4, 8],
                  "sus2": [0, 1, 4], "sus4": [0, 3, 4], "6": [0, 2, 4, 5], "5": [0, 4]}[kind]
        base = self.degree(root_degree, octave)
        return [self.degree(root_degree + s, octave) - base + root for s in stacks]


QUALITY: dict[str, list[int]] = {
    "maj": [0, 4, 7], "min": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8], "m7b5": [0, 3, 6, 10],
    "maj7": [0, 4, 7, 11], "dom7": [0, 4, 7, 10], "m7": [0, 3, 7, 10], "m9": [0, 3, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14], "dom9": [0, 4, 7, 10, 14], "add9maj": [0, 4, 7, 14], "7sus4": [0, 5, 7, 10],
    "7#9": [0, 4, 7, 10, 15], "maj6": [0, 4, 7, 9], "69": [0, 4, 7, 9, 14], "m6": [0, 3, 7, 9],
}


def _stack(base: int, pcs: list[int]) -> list[int]:
    """Close voicing starting on ``base``, stacking the other pitch classes upward."""
    order = sorted(pcs, key=lambda pc: (pc - base) % 12)
    v = [base]
    for pc in order[1:]:
        v.append(v[-1] + ((pc - v[-1]) % 12 or 12))
    return v


def voice_lead(chords: list[list[int]], lo: int = 55, hi: int = 79) -> list[list[int]]:
    """Re-voice each chord into [lo, hi] choosing the inversion closest to the previous chord."""
    out: list[list[int]] = []
    prev: list[int] | None = None
    for ch in chords:
        pcs = sorted({n % 12 for n in ch})
        cands = [_stack(b, pcs) for b in range(lo, hi) if b % 12 in pcs]
        cands = [v for v in cands if v[-1] <= hi] or [sorted(ch)]
        if prev is None:
            mid = (lo + hi) / 2
            best = min(cands, key=lambda v: abs(sum(v) / len(v) - mid))
        else:
            pm = sum(prev) / len(prev)
            best = min(cands, key=lambda v: abs(sum(v) / len(v) - pm) + 0.1 * (v[-1] - v[0]))
        out.append(best)
        prev = best
    return out
