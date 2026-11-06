"""Ink beds: warm acoustic explainer (100-115 BPM) - ukulele strums, marimba and pizzicato, kalimba and
glockenspiel colour, light percussion (shaker, finger snaps, rim, soft kick, claps in the chorus)."""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from .. import orchestra as O
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony, phrase

Mel = list[list[tuple[float, float, int]]]     # per bar: (beat, dur_beats, scale degree; 8 = tonic an octave up)

DROP_A: Mel = [[(0, 0.5, 10), (0.5, 0.5, 9), (1, 0.5, 8), (1.5, 0.5, 9), (2, 1, 10), (3, 1, 12)],
               [(0, 0.5, 13), (0.5, 0.5, 12), (1, 1, 11), (2, 1.5, 8), (3.5, 0.5, 9)],
               [(0, 1, 10), (1, 0.5, 8), (1.5, 0.5, 6), (2, 1, 8), (3, 1, 10)],
               [(0, 1.5, 9), (1.5, 0.5, 7), (2, 2, 5)],
               [(0, 0.5, 10), (0.5, 0.5, 9), (1, 0.5, 8), (1.5, 0.5, 9), (2, 1, 10), (3, 1, 12)],
               [(0, 0.5, 13), (0.5, 0.5, 12), (1, 1, 11), (2, 1, 13), (3, 1, 15)],
               [(0, 1.5, 14), (1.5, 0.5, 13), (2, 1, 12), (3, 1, 9)],
               [(0, 1, 10), (1, 3, 8)]]
# contour rhythms (beat, dur, semitone contour) mapped onto the harmony by ``phrase``
R_A = [[(0, 0.5, 0), (0.5, 0.5, 2), (1, 1, 4), (2, 0.5, 2), (2.5, 0.5, 0), (3, 1, -1)],
       [(0, 1.5, 0), (1.5, 0.5, -3), (2, 2, -5)]]
R_DROP_B = [[(0, 0.5, 0), (0.5, 0.25, 2), (0.75, 0.25, 4), (1, 1, 7), (2, 0.5, 4), (2.5, 0.5, 5), (3, 1, 4)],
            [(0, 0.5, 2), (0.5, 0.5, 0), (1, 1, -1), (2, 1.5, 0), (3.5, 0.5, 2)],
            [(0, 0.5, 4), (0.5, 0.25, 5), (0.75, 0.25, 7), (1, 1, 9), (2, 0.5, 7), (2.5, 0.5, 5), (3, 1, 4)],
            [(0, 1, 2), (1, 1, 4), (2, 2, 0)]]
R_B = [[(0, 1, 0), (1, 0.5, 2), (1.5, 0.5, 4), (2, 2, 5)], [(0, 1.5, 4), (1.5, 0.5, 2), (2, 2, 0)]]
STRUM = [(0.0, True), (1.0, True), (1.5, False), (2.5, False), (3.0, True), (3.5, False)]

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=104, tonic="G", label="G major", title="Sketchbook",
              prog={"intro": [(1, "triad"), (4, "maj7"), (1, "triad"), (5, "triad")],
                    "A": [(1, "triad"), (5, "triad"), (6, "7"), (4, "triad"), (1, "triad"), (5, "triad"), (4, "triad"), (5, "triad")],
                    "build": [(2, "7"), (4, "triad"), (2, "7"), (5, "7sus4")],
                    "drop": [(1, "triad"), (4, "triad"), (6, "triad"), (5, "triad"), (1, "triad"), (4, "triad"), (5, "triad"), (1, "triad")],
                    "B": [(6, "7"), (4, "maj7"), (1, "triad"), (5, "triad"), (6, "7"), (4, "maj7"), (2, "7"), (5, "triad")],
                    "outro": [(4, "triad"), (5, "triad")]},
              end=(1, "69"), lead="marimba", bmel="kalimba", texture="ukulele",
              notes="Warm explainer bed: island-strum ukulele, marimba hook, pizzicato bass, kalimba in B, shaker, "
                    "snaps and soft claps; friendly and unhurried."),
    "b": dict(bpm=112, tonic="D", label="D major", title="Margin Notes",
              prog={"intro": [(1, "triad"), (3, "7"), (4, "triad"), (5, "triad")],
                    "A": [(1, "triad"), (6, "7"), (2, "7"), (5, "triad"), (1, "triad"), (6, "7"), (4, "triad"), (5, "triad")],
                    "build": [(4, "triad"), (5, "triad"), (4, "triad"), (5, "7sus4")],
                    "drop": [(1, "triad"), (5, "triad"), (6, "triad"), (4, "triad"), (1, "triad"), (5, "triad"), (4, "triad"), (5, "triad")],
                    "B": [(2, "7"), (5, "triad"), (3, "7"), (6, "7"), (2, "7"), (5, "triad"), (4, "triad"), (5, "triad")],
                    "outro": [(4, "triad"), (5, "triad")]},
              end=(1, "69"), lead="marimba", bmel="glock", texture="pizz",
              notes="Playful pizzicato explainer: staccato string ostinato, marimba tune, glockenspiel and kalimba "
                    "sparkle, brushes, woodblock and claps; light on its feet."),
}


def compose(v: str) -> Song:
    """Build the Ink bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"ink_{v}", "ink", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=3.5, title=P["title"], notes=P["notes"])
    s.meta = {"family": "ink", "mood": "warm"}
    key = Key(P["tonic"], "major")
    h = Harmony(s, key, P["prog"], P["prog"]["A"], pad_range=(60, 76), bass_octave=2, end_chord=P["end"])
    r = D.rng("ink", v)
    T, t, B = s.track, s.t, s.beat
    s.reverb_ir = D.reverb_ir(1.9, 0.015, 0.55, seed=s.id)
    kick = T("kick", gain_db=-10.0)
    snap_ = T("snap", gain_db=-6.0, reverb=0.25, pan=0.15)
    shk = T("shaker", gain_db=-21.0, pan=0.3)
    rim = T("rim", gain_db=-11.0, pan=-0.25, reverb=0.15)
    bass = T("bass", gain_db=-6.5, hp=35.0)
    tex = T("texture", gain_db=-5.0 if P["texture"] == "ukulele" else -8.0, reverb=0.22, width=1.3)
    lead = T("lead", gain_db=-5.0, reverb=0.3, delay=0.12, pan=0.1)
    col = T("colour", gain_db=-12.0, reverb=0.4, delay=0.18, pan=-0.2)
    fx = T("fx", gain_db=-12.0, reverb=0.25)
    s.delay_time = B * 0.75
    uke_range = (60, 72)

    def deg(d: int, octave: int = 4) -> int:
        return key.degree(d, octave)

    for bar, sec, i in s.bars():
        name = sec.name
        if name == "end":
            continue
        ch = h.voiced[bar]
        root = (h.roots[bar] - 38) % 12 + 38                 # D2..C#3 bass register
        pcs = sorted({m % 12 for m in ch})
        lo = uke_range[0]
        uke = sorted({lo + (p - lo) % 12 for p in pcs} | {lo + (h.roots[bar] - lo) % 12 + 12})
        energy = sec.energy
        groove = name in ("A", "drop", "B") or (name == "outro" and i == 0)
        # ---- texture: ukulele island strum (a) / pizzicato ostinato (b)
        if name != "build" or i < 3:
            if P["texture"] == "ukulele":
                pat = STRUM if name != "intro" or i >= 2 else [(0.0, True), (2.0, True)]
                for bt, down in pat:
                    vel = (0.6 if down else 0.42) * (0.8 + 0.3 * energy)
                    tex.add(O.strum(uke, vel, down, 0.011, 0.9, mute=B * 0.95, seed=bar * 8 + int(bt * 2)),
                            t(bar, bt) + (r.random() - 0.5) * 0.006)
            else:
                tones = sorted(ch)
                ost = [root + 12, root + 19, tones[-1], root + 19, tones[1] if len(tones) > 1 else tones[0], root + 19,
                       tones[-1], root + 19]
                steps = range(8) if name != "intro" or i >= 2 else range(0, 8, 2)
                for k in steps:
                    tex.add(O.pizz(ost[k], 0.55 + 0.1 * (k % 2 == 0), seed=bar * 8 + k), t(bar, k * 0.5),
                            pan=-0.3 + 0.08 * k)
        else:
            for k, bt in enumerate((0.0, 0.5, 1.0, 1.5, 2.0, 2.5)):        # last build bar: rising hits then air
                m = sorted(uke)[k % len(uke)] + 12 * (k // len(uke))
                tex.add(O.pizz(m + 12, 0.5 + 0.06 * k, seed=k) if P["texture"] == "pizz"
                        else O.strum(uke, 0.5 + 0.05 * k, True, 0.008, 0.5, mute=B * 0.4, seed=k), t(bar, bt))
        # ---- pizzicato bass: root/fifth on 1 and 3, walking 8ths into the next chord in the drop
        if name != "intro" or i >= 1:
            if name == "drop":
                nxt = (h.roots[bar + 1] - 38) % 12 + 38 if bar + 1 < s.total_bars else root
                walk = [root, root + 7, root + 12, root + 7, root, root + 4 if 4 in [(m - root) % 12 for m in ch] else root + 3,
                        root + 7, nxt - 1 if nxt > root else nxt + 1]
                for k, m in enumerate(walk):
                    bass.add(O.pizz(m, 0.75 if k % 2 == 0 else 0.55, seed=bar * 8 + k), t(bar, k * 0.5))
            elif not (name == "build" and i == 3):
                for bt, m in ((0, root), (2, root + 7)):
                    bass.add(O.pizz(m, 0.8, seed=bar * 2 + bt), t(bar, bt))
                if name in ("A", "B"):
                    bass.add(O.pizz(root + 12, 0.45, seed=bar), t(bar, 3.5))
        # ---- percussion
        if groove:
            for bt in (0, 2) if name != "drop" else (0, 1.5, 2):
                s.kick_at(kick, t(bar, bt), O.soft_kick(0.8 if bt == 0 else 0.65))
            for bt in (1, 3):
                if name == "drop":
                    snap_.add(D.mix((I.clap(0.7, seed=bar + bt), 1.0), (O.snap(0.6, seed=bt), 0.6)), t(bar, bt))
                else:
                    snap_.add(O.snap(0.75, seed=bar + bt) if v == "a" else O.brush(0.7, seed=bar + bt), t(bar, bt))
            for k in range(16):
                shk.add(I.shaker((0.75, 0.3, 0.5, 0.3)[k % 4], seed=k % 7), t(bar, k / 4) + (r.random() - 0.5) * 0.006)
            for bt in (1.75, 3.25):
                rim.add(I.rim(0.5, 1650.0), t(bar, bt))
        elif name == "intro" and i >= 2:
            for k in range(8):
                shk.add(I.shaker(0.4 if k % 2 == 0 else 0.25, seed=k), t(bar, k / 2))
        elif name == "build":
            for k in range(4 if i < 2 else 8 if i == 2 else 6):
                step = 1.0 if i < 2 else 0.5
                rim.add(I.rim(0.4 + 0.1 * i, 1650.0 if k % 2 else 1900.0), t(bar, k * step))
            if i == 3:
                fx.add(O.chime_tree(B * 1.0, up=True, seed=bar), t(bar, 3.0), -2.0)
        if name in ("A", "B") and i % 4 == 3:
            for bt, fq in ((3.0, 950.0), (3.5, 1200.0)):
                fx.add(O.woodblock(fq, 0.55), t(bar, bt))
        # ---- melody
        if name == "drop":
            if v == "a":
                notes = [(bt, d, deg(dg, 4)) for bt, d, dg in DROP_A[i % len(DROP_A)]]
            else:
                notes = phrase(h, bar, R_DROP_B[i % 4], deg(1, 5), span=10)
            for bt, d, m in notes:
                lead.add(I.marimba(m, 0.85, decay=min(1.2, d * B + 0.4), seed=bar), t(bar, bt))
                if bt % 1 == 0:
                    col.add(O.glock(m + 12, 0.35, seed=bar), t(bar, bt))
        elif name == "A":
            for bt, d, m in phrase(h, bar, R_A[i % 2], deg(5, 4)):
                lead.add(I.marimba(m, 0.7, decay=min(1.0, d * B + 0.3), seed=bar), t(bar, bt))
        elif name == "B":
            for bt, _d, m in phrase(h, bar, R_B[i % 2], deg(1, 5)):
                if P["bmel"] == "kalimba":
                    col.add(O.kalimba(m, 0.8, seed=bar), t(bar, bt), 5.0)
                else:
                    col.add(O.glock(m + 12, 0.6, seed=bar), t(bar, bt), 2.0)
                    lead.add(I.marimba(m, 0.55, seed=bar), t(bar, bt), -3.0)
        elif name == "outro":
            for bt, _d, m in phrase(h, bar, R_B[i % 2], deg(1, 5)):
                lead.add(I.marimba(m, 0.6, seed=bar), t(bar, bt))
        if i == 0 and name in ("drop", "B"):
            fx.add(I.crash(0.3, 2.0, seed=bar), t(bar), -10.0)
    # ---- ending: strum + marimba roll on the tonic, glock, soft kick
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    pcs = sorted({m % 12 for m in ch})
    uke = sorted({60 + (p - 60) % 12 for p in pcs})
    if P["texture"] == "ukulele":
        tex.add(O.strum(uke, 0.65, True, 0.03, 2.0, seed=99), t(eb))
    else:
        for k, m in enumerate(sorted(ch)):
            tex.add(O.pizz(m, 0.6, decay=0.9, seed=k), t(eb) + 0.03 * k)
    tonic = deg(1, 2)
    bass.add(O.pizz((tonic - 38) % 12 + 38, 0.9, decay=1.2), t(eb))
    for k, m in enumerate(sorted(ch)):
        lead.add(I.marimba(m + 12, 0.6, decay=1.6, seed=k), t(eb) + 0.06 * k)
    col.add(O.glock(deg(8, 5), 0.6, decay=2.4), t(eb, 0.5))
    s.kick_at(kick, t(eb), O.soft_kick(0.6))
    return s

