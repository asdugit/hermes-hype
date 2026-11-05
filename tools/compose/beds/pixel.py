"""Pixel beds: 2A03-style chiptune (two pulse channels with duty changes, stepped triangle bass,
LFSR noise drums, 30 Hz chord arpeggios, an echo channel) at 140-160 BPM."""
from __future__ import annotations

from typing import Any

from .. import instruments as I
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony, phrase

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=150, tonic="C", mode="major", label="C major", prog=[(1, "triad"), (5, "triad"), (6, "triad"), (4, "triad")],
              prog_b=[(4, "triad"), (5, "triad"), (3, "triad"), (6, "triad")], end=(1, "triad"),
              duty={"A": 0.25, "drop": 0.5, "B": 0.125}, title="Quest Start",
              notes="Bright overworld chiptune: lead pulse switches duty per section, 30 Hz arps, octave triangle bass."),
    "b": dict(bpm=144, tonic="A", mode="minor", label="A minor", prog=[(1, "triad"), (6, "triad"), (3, "triad"), (7, "triad")],
              prog_b=[(4, "triad"), (5, "triad"), (1, "triad"), (5, "triad")], end=(1, "triad"),
              duty={"A": 0.125, "drop": 0.25, "B": 0.5}, title="Boss Rush",
              notes="Driving minor chiptune: syncopated noise drums, echo lead, rising arps in the build."),
}

R_A = [[(0, 0.5, 0), (0.5, 0.5, 2), (1, 0.5, 4), (1.5, 1.0, 7), (2.5, 0.5, 4), (3, 1.0, 5)],
       [(0, 0.75, 4), (0.75, 0.75, 2), (1.5, 0.5, 0), (2, 2.0, -1)]]
R_DROP = [[(0, 0.25, 0), (0.25, 0.25, 4), (0.5, 0.5, 7), (1, 0.5, 12), (1.5, 0.5, 11), (2, 0.5, 7), (2.5, 0.5, 9), (3, 1, 7)],
          [(0, 0.5, 5), (0.5, 0.5, 4), (1, 0.5, 2), (1.5, 0.5, 4), (2, 1.5, 0), (3.5, 0.5, 2)]]
R_B = [[(0, 1.0, 7), (1, 0.5, 5), (1.5, 0.5, 4), (2, 1.0, 2), (3, 1.0, 4)],
       [(0, 1.5, 0), (1.5, 0.5, 2), (2, 0.5, 4), (2.5, 0.5, 5), (3, 1, 7)]]


def compose(v: str) -> Song:
    """Build the Pixel bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"pixel_{v}", "pixel", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=3.0, title=P["title"], notes=P["notes"])
    key = Key(P["tonic"], P["mode"])
    h = Harmony(s, key, {"B": P["prog_b"]}, P["prog"], pad_range=(60, 79), bass_octave=2, end_chord=P["end"])
    T, t, B = s.track, s.t, s.beat
    p1 = T("pulse1", gain_db=-6.0, pan=-0.3, delay=0.28, reverb=0.08)
    p2 = T("pulse2", gain_db=-11.0, pan=0.35, reverb=0.06)
    tri = T("triangle", gain_db=-4.0)
    nz = T("noise", gain_db=-7.0, reverb=0.04)
    s.delay_time = B * 0.75
    syn = v == "b"
    center = key.degree(1, 5)
    for bar, sec, i in s.bars():
        name = sec.name
        ch = h.voiced[bar]
        root = h.roots[bar] + 12
        if name == "end":
            continue
        # ---- pulse 2: chord arps, staccato 8ths (intro: half notes)
        offs = tuple(m - ch[0] for m in ch) + (12,)
        if name == "intro":
            for bt in (0, 2):
                p2.add(I.chip_pulse(ch[0], B * 1.8, 0.125, 8 + 2 * i, "decay", arp=offs, arp_hz=30.0), t(bar, bt))
        elif name in ("A", "drop", "B", "outro", "build"):
            hits = [0, 0.5, 1.5, 2, 2.5, 3.5] if name != "build" else [k * 0.5 for k in range(8)]
            for bt in hits:
                slide = 2.0 * i if name == "build" else 0.0
                p2.add(I.chip_pulse(ch[0] + (i if name == "build" else 0), B * 0.42, 0.25 if name == "drop" else 0.125,
                                    10, "pluck", arp=offs, arp_hz=30.0, slide=slide), t(bar, bt))
        # ---- triangle bass
        if name == "intro" and i >= 2:
            p = [(0, 1.8)] if not syn else [(0, 0.9), (1.5, 0.4), (2, 1.8)]
            for bt, d in p:
                tri.add(I.chip_tri(root, d * B), t(bar, bt))
        elif name in ("A", "B", "outro"):
            for k in range(8):
                m = root + (7 if (k == 6 and name == "B") else 0) + (12 if (syn and k % 4 == 3) else 0)
                tri.add(I.chip_tri(m, B * 0.45), t(bar, k * 0.5))
        elif name == "drop":
            for k in range(8):
                tri.add(I.chip_tri(root + (12 if k % 2 else 0), B * 0.45), t(bar, k * 0.5))
        elif name == "build":
            stop = 7 if i == 3 else 8
            for k in range(stop):
                tri.add(I.chip_tri(root + k % 2 * 12, B * 0.45, slide=0.0), t(bar, k * 0.5))
        # ---- noise drums
        if name in ("A", "drop", "B") or (name == "outro" and i == 0):
            kicks = [0, 2] + ([1.5] if name == "drop" else []) + ([2.75] if syn else [])
            for bt in kicks:
                s.kick_at(nz, t(bar, bt), I.chip_kick(1.0))
            for bt in (1, 3):
                nz.add(I.chip_snare(1.0), t(bar, bt))
            for k in range(8):
                if name == "drop" and k % 2 == 1:
                    nz.add(I.chip_hat(0.8, open_=True), t(bar, k * 0.5))
                else:
                    nz.add(I.chip_hat(0.7 if k % 2 == 0 else 0.45), t(bar, k * 0.5))
            if name == "B" and i == 7:
                for k in range(8):
                    nz.add(I.chip_snare(0.5 + 0.06 * k), t(bar, 2 + k * 0.25))
        elif name == "intro" and i >= 2:
            for k in range(8):
                nz.add(I.chip_hat(0.5 if k % 2 == 0 else 0.3), t(bar, k * 0.5))
        elif name == "build":
            step = 1.0 if i == 0 else 0.5 if i < 3 else 0.25
            stop = 3.5 if i == 3 else 4.0
            bt = 0.0
            while bt < stop - 1e-6:
                nz.add(I.chip_snare(0.5 + 0.12 * i), t(bar, bt))
                bt += step
            if i < 3:
                s.kick_at(nz, t(bar, 0), I.chip_kick(1.0))
                s.kick_at(nz, t(bar, 2), I.chip_kick(1.0))
        if i == 0 and name in ("A", "drop", "outro"):
            nz.add(I.chip_crash(0.9), t(bar))
        # ---- pulse 1: lead melody
        if name in ("A", "drop", "B"):
            if name == "A" and i < 4 and not syn:
                continue
            bank = {"A": R_A, "drop": R_DROP, "B": R_B}[name]
            rh = bank[i % 2]
            duty = P["duty"][name]
            for bt, d, m in phrase(h, bar, rh, center + (12 if name == "drop" else 0)):
                p1.add(I.chip_pulse(m, d * B * 0.92, duty, 12, "sustain", vib=0.25 if d >= 1 else 0.0), t(bar, bt))
        elif name == "build":
            for k in range(4 if i < 3 else 3):
                m = center + 12 + [0, 4, 7, 12][(k + i) % 4] - 12 * (i < 2)
                p1.add(I.chip_pulse(m, B * 0.9, 0.5, 10 + i, "sustain"), t(bar, k))
    # ---- ending jingle: rising tonic arpeggio, then a held chord
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    run = [ch[0], ch[1], ch[2], ch[0] + 12, ch[1] + 12, ch[2] + 12]
    for k, m in enumerate(run):
        p1.add(I.chip_pulse(m, B * 0.2, 0.25, 12, "pluck"), t(eb - 1, 2 + k * 0.25))
    p1.add(I.chip_pulse(ch[0] + 24, B * 3.5, 0.5, 13, "decay", vib=0.3), t(eb))
    p2.add(I.chip_pulse(ch[0] + 12, B * 3.5, 0.25, 10, "decay", arp=tuple(m - ch[0] for m in ch), arp_hz=30.0), t(eb))
    tri.add(I.chip_tri(h.roots[eb], B * 2.5), t(eb))
    s.kick_at(nz, t(eb), I.chip_kick(1.0))
    nz.add(I.chip_crash(1.0), t(eb))
    return s
