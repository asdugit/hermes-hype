"""Helpers shared by the bed compositions: harmony per bar, melody shaping, groove patterns."""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..song import Song
from ..theory import Key, voice_lead

ChordSpec = tuple[int, str]          # (scale degree, chord kind) e.g. (6, "7")
GROOVE_LAYOUT = [("intro", 4, 0.3), ("A", 8, 0.55), ("build", 4, 0.75), ("drop", 8, 1.0),
                 ("B", 8, 0.8), ("outro", 2, 0.45), ("end", 1, 0.2)]


class Harmony:
    """Chord per absolute bar, voice-led for pads (``voiced``), plus bass roots."""

    def __init__(self, song: Song, key: Key, progs: dict[str, list[ChordSpec]], default: list[ChordSpec],
                 pad_range: tuple[int, int] = (57, 76), bass_octave: int = 2, end_chord: ChordSpec = (1, "add9")):
        self.key = key
        raw, roots, specs = [], [], []
        for _bar, sec, i in song.bars():
            prog = progs.get(sec.name, default)
            d, kind = end_chord if sec.name == "end" else prog[i % len(prog)]
            specs.append((d, kind))
            raw.append(key.chord(d, kind, 3))
            roots.append(key.degree(d, bass_octave))
        self.specs = specs
        self.voiced = voice_lead(raw, *pad_range)
        self.roots = roots

    def tones(self, bar: int) -> list[int]:
        """Pitch classes of the chord at ``bar``."""
        return sorted({n % 12 for n in self.voiced[bar]})


def nearest(target: float, candidates: Iterable[int]) -> int:
    return min(candidates, key=lambda m: (abs(m - target), m))


def chord_tones_near(h: Harmony, bar: int, lo: int, hi: int) -> list[int]:
    pcs = h.tones(bar)
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def scale_tones_near(key: Key, lo: int, hi: int) -> list[int]:
    pcs = {(key.tonic + s) % 12 for s in key.steps}
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def phrase(h: Harmony, bar: int, rhythm: Sequence[tuple[float, float, float]], center: int, span: int = 9,
           strong: tuple[float, ...] = (0.0, 2.0)) -> list[tuple[float, float, int]]:
    """Map a contour rhythm [(beat, dur_beats, contour_semitones)] onto bar ``bar``'s harmony.

    Notes on strong beats snap to chord tones, others to the scale, so the same shape sequences
    naturally over each chord (memorable, never out of key).
    """
    out = []
    ct = chord_tones_near(h, bar, center - span, center + span + 4)
    st = scale_tones_near(h.key, center - span, center + span + 4)
    for beat, dur, c in rhythm:
        pool = ct if (beat % 4.0) in strong or dur >= 1.0 else st
        out.append((beat, dur, nearest(center + c, pool)))
    return out
