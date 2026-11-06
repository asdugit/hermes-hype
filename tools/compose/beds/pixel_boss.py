"""Pixel boss beds: driving minor-key 2A03 chiptune boss battle (150-170 BPM).

Tension builds through the A/build sections (pedal-tone riffs, a chromatic bass run into the drop, an
Andalusian descent in the drop, a Neapolitan/Phrygian twist in B); the outro is the Aeolian 'victory
approach' bVI -> bVII and the end bar resolves it to a Picardy major tonic with a fanfare.

In a multi-bed cue sheet the outro's bVII is also V of the relative major: pixel_boss_a (A minor) resolves
into dream_a (C major) and pixel_boss_b (E minor) into dream_b (G major) (``cadence_to`` in bars.json).
"""
from __future__ import annotations

from typing import Any

from .. import instruments as I
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony, chord_tones_near, nearest, phrase

Note = tuple  # (beat, dur_beats, scale degree[, alteration]); degree 8 = tonic an octave up (octave 4 base)

DROP_A: list[list[Note]] = [
    [(0, 1.5, 12), (1.5, 0.5, 11), (2, 0.5, 10), (2.5, 0.5, 11), (3, 1, 12)],
    [(0, 1.5, 11), (1.5, 0.5, 10), (2, 0.5, 9), (2.5, 0.5, 10), (3, 1, 11)],
    [(0, 1.5, 10), (1.5, 0.5, 9), (2, 0.5, 8), (2.5, 0.5, 9), (3, 1, 10)],
    [(0, 1.5, 9), (1.5, 0.5, 8), (2, 1, 7, 1), (3, 1, 5)],
    [(0, 1, 8), (1, 1, 12), (2, 1, 15), (3, 0.5, 14), (3.5, 0.5, 12)],
    [(0, 1.5, 14), (1.5, 0.5, 12), (2, 1, 11), (3, 1, 9)],
    [(0, 1, 10), (1, 1, 13), (2, 1, 15), (3, 1, 13)],
    [(0, 2, 12), (2, 1, 14, 1), (3, 1, 16)],
]
DROP_B: list[list[Note]] = [
    [(0, 1, 8), (1, 0.5, 9), (1.5, 0.5, 10), (2, 1.5, 12), (3.5, 0.5, 10)],
    [(0, 1, 11), (1, 0.5, 10), (1.5, 0.5, 9), (2, 2, 8)],
    [(0, 1, 9), (1, 0.5, 8), (1.5, 0.5, 7), (2, 1, 9), (3, 1, 11)],
    [(0, 3, 12), (3, 0.5, 11), (3.5, 0.5, 12)],
    [(0, 1, 10), (1, 1, 13), (2, 1.5, 15), (3.5, 0.5, 13)],
    [(0, 1.5, 15), (1.5, 0.5, 14), (2, 1, 13), (3, 1, 11)],
    [(0, 2, 12), (2, 1, 14, 1), (3, 1, 16)],
    [(0, 2, 16), (2, 1, 14, 1), (3, 1, 12)],
]
# pedal-tone riff (A section): upper notes on beats 1, 2, 3, 3.5 over a tonic/root pedal on the 8ths
RIFF_A: list[list[Note]] = [[(8,), (7,), (6,), (5,)], [(8,), (10,), (9,), (8,)], [(8,), (7,), (6,), (3,)],
                            [(9,), (8,), (7,), (4,)], [(8,), (7,), (6,), (5,)], [(8,), (10,), (9,), (8,)],
                            [(6,), (5,), (4,), (1,)], [(7, 1), (6,), (5,), (2,)]]
R_B = [[(0, 1.0, 7), (1, 0.5, 5), (1.5, 0.5, 4), (2, 1.0, 2), (3, 1.0, 4)],
       [(0, 1.5, 0), (1.5, 0.5, 2), (2, 0.5, 4), (2.5, 0.5, 5), (3, 1, 7)]]

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=160, tonic="A", label="A minor", title="Final Phase", cadence_to="C major", pairs_with="dream_a",
              prog={"intro": [(1, "min"), (1, "min"), (6, "maj"), (5, "maj")],
                    "A": [(1, "min"), (1, "min"), (6, "maj"), (7, "maj"), (1, "min"), (1, "min"), (4, "min"), (5, "maj")],
                    "build": [(6, "maj"), (7, "maj"), (5, "maj"), (5, "maj")],
                    "drop": [(1, "min"), (7, "maj"), (6, "maj"), (5, "maj")],
                    "B": [(4, "min"), (1, "min"), (6, "maj"), (3, "maj"), (4, "min"), (1, "min"), (2, "maj", -1), (5, "maj")],
                    "outro": [(6, "maj"), (7, "maj")]},
              drop=DROP_A, gallop=False, drop_oct=-12,
              notes="Boss battle chiptune: pedal-tone riff, Andalusian-descent drop theme, Neapolitan twist, "
                    "chromatic bass run into the drop, bVI-bVII victory cadence to a Picardy A major fanfare."),
    "b": dict(bpm=168, tonic="E", label="E minor", title="Last Stand", cadence_to="G major", pairs_with="dream_b",
              prog={"intro": [(1, "min"), (6, "maj"), (4, "min"), (5, "maj")],
                    "A": [(1, "min"), (6, "maj"), (3, "maj"), (7, "maj")],
                    "build": [(4, "min"), (5, "maj"), (6, "maj"), (5, "maj")],
                    "drop": [(1, "min"), (4, "min"), (7, "maj"), (3, "maj"), (6, "maj"), (4, "min"), (5, "maj"), (5, "maj")],
                    "B": [(6, "maj"), (7, "maj"), (1, "min"), (1, "min"), (6, "maj"), (7, "maj"), (5, "maj"), (5, "maj")],
                    "outro": [(6, "maj"), (7, "maj")]},
              drop=DROP_B, gallop=True, drop_oct=0,
              notes="Galloping last-boss chiptune: heroic-minor loop, triplet-feel gallop bass, soaring drop theme "
                    "with a raised-seventh climb, bVI-bVII victory cadence to a Picardy E major fanfare."),
}


def compose(v: str) -> Song:
    """Build the Pixel boss bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"pixel_boss_{v}", "pixel_boss", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=3.0, title=P["title"],
             notes=P["notes"])
    s.meta = {"family": "pixel_boss", "mood": "tense", "cadence_to": P["cadence_to"], "pairs_with": P["pairs_with"]}
    key = Key(P["tonic"], "minor")
    h = Harmony(s, key, P["prog"], P["prog"]["A"], pad_range=(62, 81), bass_octave=2, end_chord=(1, "maj"))
    T, t, B = s.track, s.t, s.beat
    p1 = T("pulse1", gain_db=-6.0, pan=-0.25, delay=0.22, reverb=0.07)
    p2 = T("pulse2", gain_db=-12.0, pan=0.3, reverb=0.05)
    echo = T("echo", gain_db=-17.0, pan=0.45, reverb=0.1)
    tri = T("triangle", gain_db=-3.5)
    nz = T("noise", gain_db=-7.5, reverb=0.04)
    s.delay_time = B * 0.75

    def note(n: Note, octave: int = 4) -> int:
        """MIDI note of a timed note (beat, dur, degree[, alteration])."""
        return key.degree(int(n[2]), octave) + (int(n[3]) if len(n) > 3 else 0)

    def riff(n: Note, octave: int = 4) -> int:
        """MIDI note of a riff entry (degree[, alteration])."""
        return key.degree(int(n[0]), octave) + (int(n[1]) if len(n) > 1 else 0)

    def pedal(bar: int) -> int:
        return (h.roots[bar] - 57) % 12 + 57

    eb = s.sec("end").start_bar
    for bar, sec, i in s.bars():
        name = sec.name
        if name == "end":
            continue
        ch = h.voiced[bar]
        root = h.roots[bar] + 12
        offs = tuple(m - ch[0] for m in ch) + (12,)
        # ---- pulse 2: 16th chord arps (intro: tremolo pulses), rising slide in the build
        if name == "intro":
            for k in range(4 if i < 2 else 8):
                step = 1.0 if i < 2 else 0.5
                p2.add(I.chip_pulse(ch[0], B * step * 0.8, 0.125, 6 + 2 * i, "decay", arp=offs, arp_hz=30.0), t(bar, k * step))
        else:
            hits = [k * 0.25 for k in range(16)] if name in ("drop", "build") else [k * 0.5 for k in range(8)]
            for k, bt in enumerate(hits):
                vol = 9 if k % 4 == 0 else 7
                slide = 3.0 * i if name == "build" else 0.0
                p2.add(I.chip_pulse(ch[k % len(ch)] + (12 if name == "drop" and k % 8 >= 4 else 0),
                                    B * (0.22 if name in ("drop", "build") else 0.42), 0.25, vol, "pluck",
                                    slide=slide), t(bar, bt))
        # ---- triangle bass: driving 8ths (octaves) / gallop (b); chromatic run into the drop
        last_build = name == "build" and i == 3
        if name == "intro" and i >= 2:
            for k in range(8):
                tri.add(I.chip_tri(root, B * 0.45), t(bar, k * 0.5))
        elif name in ("A", "B", "drop", "outro") or (name == "build" and not last_build):
            if P["gallop"] and name in ("A", "B", "drop"):
                for k in range(4):
                    for bt, d in ((0.0, 0.45), (0.5, 0.2), (0.75, 0.2)):
                        tri.add(I.chip_tri(root + (12 if (k % 2 and bt == 0.0) else 0), B * d), t(bar, k + bt))
            else:
                for k in range(8):
                    tri.add(I.chip_tri(root + (12 if k % 2 else 0), B * 0.45), t(bar, k * 0.5))
        elif last_build:
            target = key.degree(1, 3)                 # tonic, where the drop lands
            run = [target - 8 + k for k in range(8)]  # chromatic climb ending a semitone under the tonic
            for k, m in enumerate(run):
                tri.add(I.chip_tri(m, B * 0.45), t(bar, k * 0.5))
        # ---- noise drums
        if name in ("A", "drop", "B") or (name == "outro" and i == 0) or (name == "build" and i < 2):
            kicks = [0, 1.5, 2.5] if name == "drop" else [0, 2.5] if not P["gallop"] else [0, 0.75, 2, 2.75]
            for bt in kicks:
                s.kick_at(nz, t(bar, bt), I.chip_kick(1.0))
            for bt in (1, 3):
                nz.add(I.chip_snare(1.0), t(bar, bt))
            for k in range(16 if name == "drop" else 8):
                step = 0.25 if name == "drop" else 0.5
                nz.add(I.chip_hat(0.7 if k % 2 == 0 else 0.4), t(bar, k * step))
            if name in ("A", "B") and i == 7:
                for k in range(8):
                    nz.add(I.chip_snare(0.5 + 0.06 * k), t(bar, 2 + k * 0.25))
        elif name == "build":
            step = 0.5 if i == 2 else 0.25
            stop = 3.5 if last_build else 4.0
            bt = 0.0
            while bt < stop - 1e-6:
                nz.add(I.chip_snare(0.55 + 0.1 * (i - 2) + 0.03 * bt), t(bar, bt))
                bt += step
        elif name == "intro" and i >= 2:
            s.kick_at(nz, t(bar), I.chip_kick(0.9))
            for k in range(8):
                nz.add(I.chip_hat(0.45 if k % 2 == 0 else 0.25), t(bar, k * 0.5))
        if i == 0 and name in ("A", "drop", "B", "outro"):
            nz.add(I.chip_crash(0.9), t(bar))
        # ---- pulse 1: lead
        if name == "A":
            if not P["gallop"]:
                ups = RIFF_A[i % len(RIFF_A)]
                pd = pedal(bar)
                for k in range(8):
                    bt = k * 0.5
                    up = {2: 0, 4: 1, 6: 2, 7: 3}.get(k)
                    if up is None:
                        p1.add(I.chip_pulse(pd, B * 0.4, 0.25, 11, "pluck"), t(bar, bt))
                    else:
                        p1.add(I.chip_pulse(riff(ups[up], 4), B * 0.45, 0.5, 14, "pluck"), t(bar, bt))
            else:
                for bt, d, m in phrase(h, bar, R_B[i % 2], key.degree(1, 5)):
                    p1.add(I.chip_pulse(m, d * B * 0.9, 0.25, 12, "sustain", vib=0.25 if d >= 1 else 0.0), t(bar, bt))
        elif name == "drop":
            for n in P["drop"][i % len(P["drop"])]:
                bt, d = n[0], n[1]
                m = note(n, 4) + P["drop_oct"]
                p1.add(I.chip_pulse(m, d * B * 0.92, 0.5, 13, "sustain", vib=0.3 if d >= 1 else 0.0), t(bar, bt))
                echo.add(I.chip_pulse(m + 12, d * B * 0.9, 0.125, 9, "sustain"), t(bar, bt) + B * 0.75)
        elif name == "B":
            for bt, d, m in phrase(h, bar, R_B[i % 2], key.degree(1, 5) if P["gallop"] else key.degree(5, 4)):
                p1.add(I.chip_pulse(m, d * B * 0.9, 0.125, 12, "sustain", vib=0.25 if d >= 1 else 0.0), t(bar, bt))
        elif name == "build":
            # long rising notes with vibrato: tension
            top = nearest(key.degree(1, 5) + (0, 2, 4, 7)[i], chord_tones_near(h, bar, 70, 92))
            p1.add(I.chip_pulse(top, B * (3.9 if not last_build else 3.4), 0.5, 11 + i, "sustain", vib=0.35), t(bar))
        elif name == "outro":
            # victory approach: bVI -> bVII held, rising
            top = nearest(key.degree(1, 5) + 2 * i, chord_tones_near(h, bar, 70, 92))
            last = i == s.sec("outro").bars - 1
            p1.add(I.chip_pulse(top, B * (1.9 if last else 3.6), 0.5, 12, "sustain", vib=0.3), t(bar))
            echo.add(I.chip_pulse(top + 12, B * (1.5 if last else 3.2), 0.125, 8, "sustain"), t(bar) + B * 0.75)
            if last:
                # bVII arpeggio climbing a step under the tonic (also V of the relative major in a cue sheet)
                tones = sorted(ch)
                run = (tones + [m + 12 for m in tones])[:6]
                for k, m in enumerate(run):
                    p1.add(I.chip_pulse(m, B * 0.22, 0.25, 12, "pluck"), t(bar, 2 + k * 0.25))
    # ---- ending: Picardy major fanfare (rising tonic arpeggio, held chord, crash)
    ch = h.voiced[eb]
    tonic = key.degree(1, 4)
    for k, m in enumerate((tonic + 12, tonic + 16, tonic + 19)):
        p1.add(I.chip_pulse(m, B * 0.24, 0.25, 12, "pluck"), t(eb, k * 0.25))
    p1.add(I.chip_pulse(tonic + 24, B * 3.0, 0.5, 13, "decay", vib=0.3), t(eb, 0.75))
    p2.add(I.chip_pulse(ch[0] + 12, B * 3.5, 0.25, 10, "decay", arp=tuple(m - ch[0] for m in ch), arp_hz=30.0), t(eb))
    tri.add(I.chip_tri(h.roots[eb] + 12, B * 2.5), t(eb))
    s.kick_at(nz, t(eb), I.chip_kick(1.0))
    nz.add(I.chip_crash(1.0), t(eb))
    return s
