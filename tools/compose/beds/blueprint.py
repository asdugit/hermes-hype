"""Blueprint beds: precise, minimal, mechanical (~108-112 BPM) - interlocking marimba patterns,
woody clock ticks, soft round kick, sine-triangle bass, glock top line."""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony, phrase

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=110, tonic="D", mode="major", label="D major",
              prog=[(1, "7"), (5, "triad"), (6, "7"), (4, "7")], prog_b=[(4, "7"), (5, "sus4"), (3, "7"), (6, "7")],
              end=(1, "7"), title="Drafting Table",
              notes="Explainer-tech bed: 3+3+2 marimba ostinato, clock ticks, glock hook; nothing wasted."),
    "b": dict(bpm=108, tonic="F", mode="lydian", label="F lydian",
              prog=[(1, "7"), (2, "triad"), (6, "7"), (1, "7")], prog_b=[(4, "7"), (5, "7"), (1, "7"), (2, "triad")],
              end=(1, "add9"), title="Precision",
              notes="Lydian mechanical bed: phased marimba pair, ratchet build, plucked chords."),
}

M1 = [0, 2, 1, 3, 2, 4, 1, 3]                     # pattern indices over chord tones (16ths)
M1_RHYTHM = [0, 0.75, 1.5, 2.0, 2.75, 3.5]        # 3+3+2 feel
HOOK = [[(0, 0.5, 0), (0.5, 0.5, 2), (1, 1.0, 4), (2.5, 0.5, 2), (3, 1, 7)], [(0, 1.5, 5), (1.5, 0.5, 4), (2, 2.0, 2)]]


def compose(v: str) -> Song:
    """Build the Blueprint bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"blueprint_{v}", "blueprint", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=4.0, title=P["title"], notes=P["notes"])
    key = Key(P["tonic"], P["mode"])
    h = Harmony(s, key, {"B": P["prog_b"]}, P["prog"], pad_range=(57, 76), bass_octave=2, end_chord=P["end"])
    T, t, B = s.track, s.t, s.beat
    r = D.rng("blueprint", v)
    mar = T("marimba", gain_db=-5.0, reverb=0.25, pan=-0.2, width=1.2)
    mar2 = T("marimba2", gain_db=-9.0, reverb=0.25, pan=0.3)
    tick = T("tick", gain_db=-17.0, pan=0.25)
    kick = T("kick", gain_db=-8.0)
    rimt = T("rim", gain_db=-12.0, reverb=0.2, pan=-0.1)
    bass = T("bass", gain_db=-10.0, pump=0.2, hp=35.0)
    chd = T("chords", gain_db=-12.0, reverb=0.35, delay=0.15, width=1.3)
    glk = T("glock", gain_db=-11.0, reverb=0.4, delay=0.22, pan=0.15)
    fx = T("fx", gain_db=-9.0)
    s.delay_time = B * 0.75
    for bar, sec, i in s.bars():
        name = sec.name
        ch = h.voiced[bar]
        root = h.roots[bar]
        if name == "end":
            continue
        tones = sorted(ch) + [sorted(ch)[0] + 12, sorted(ch)[1] + 12]
        # marimba ostinato (always; it IS the piece)
        dens = M1_RHYTHM if name in ("intro", "outro") else [k / 4 for k in range(16)]
        if name == "build" and i == 3:
            dens = [k / 4 for k in range(14)]
        for j, bt in enumerate(dens):
            m = tones[M1[j % 8] % len(tones)] + 12
            vel = 0.85 if bt in M1_RHYTHM else 0.45
            if name == "build":
                m += 12 if i >= 2 and j % 4 == 3 else 0
            mar.add(I.marimba(m, vel, 0.7, seed=j), t(bar, bt))
        # second marimba, offset by a dotted 8th (phasing feel) from A on
        if name in ("A", "drop", "B") and not (name == "A" and i < 4):
            for j, bt in enumerate(M1_RHYTHM):
                m = tones[(M1[j % 8] + 2) % len(tones)]
                mar2.add(I.marimba(m, 0.6, 0.9, seed=j + 9), t(bar, (bt + 0.75) % 4))
        # clock ticks (16ths, accent on beats), alternate pitch
        if name != "intro" or i >= 2:
            for k in range(16):
                if name == "build" and i == 3 and k >= 14:
                    break
                tick.add(I.rim(0.8 if k % 4 == 0 else 0.4, 2600.0 if k % 2 else 3100.0), t(bar, k / 4) + (r.random() - .5) * 0.002)
        # kick + rim
        if name in ("A", "drop", "B") or (name == "build" and i < 3) or (name == "outro" and i == 0):
            kb = [0, 1, 2, 3] if name == "drop" else [0, 2] if name != "build" else [0, 1, 2, 3]
            for bt in kb:
                s.kick_at(kick, t(bar, bt), I.kick(0.85, f_hi=120.0, f_lo=50.0, decay=0.32, click=0.15, drive=1.2))
            if name != "build":
                for bt in (1, 3):
                    rimt.add(I.rim(0.9, 1750.0), t(bar, bt))
                    if name == "drop":
                        rimt.add(I.clap(0.5, seed=bar), t(bar, bt), -6.0)
        if name == "build":
            # ratchet: accelerating mechanical clicks into the drop
            step = [0.5, 0.25, 0.25, 0.125][i]
            bt = 0.0
            while bt < (3.5 if i == 3 else 4.0) - 1e-6:
                rimt.add(I.rim(0.4 + 0.15 * i, 1200.0 + 200 * i), t(bar, bt))
                bt += step
            if i == 0:
                fx.add(I.riser(4 * s.bar, seed=21), t(bar), -6.0)
        # bass: sine/triangle, quarter notes (drop: 8ths)
        if name in ("A", "drop", "B") or (name == "build"):
            pat = [k * 0.5 for k in range(8)] if name == "drop" else [0, 1.5, 2, 3]
            for bt in pat:
                if name == "build" and i == 3 and bt >= 3.5:
                    continue
                n = D.ns(B * 0.45)
                x = (D.sine(float(D.mtof(root)), n) * 0.8 + D.tri(float(D.mtof(root)), n) * 0.35) * D.adsr(n, 0.004, 0.15, 0.7, 0.04)
                x = x + I.pluck(root + 12, B * 0.3, 0.25, bright=0.3, decay=0.3)[: n]
                bass.add(x, t(bar, bt))
        # plucked chords on the "and" of 2 and 4 (A second half, drop, B)
        if (name == "A" and i >= 4) or name in ("drop", "B"):
            for bt in (1.5, 3.5):
                for k, m in enumerate(ch):
                    chd.add(I.pluck(m, B * 0.6, 0.55, bright=0.6, decay=0.9, seed=k), t(bar, bt) + 0.008 * k)
        # glock hook
        if name == "drop" or (name == "B" and i >= 4):
            for bt, _d, m in phrase(h, bar, HOOK[i % 2], key.degree(3, 5)):
                glk.add(I.bell(m, 0.6, 1.4, seed=bar), t(bar, bt))
        if i == 0 and name in ("drop",):
            fx.add(I.crash(0.45, 2.0, seed=bar), t(bar), -6.0)
            fx.add(I.boom(0.7, 55.0, 1.0), t(bar), -6.0)
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    for k, m in enumerate(sorted(ch)):
        mar.add(I.marimba(m + 12, 0.8, 2.2, seed=k), t(eb) + 0.02 * k)
        chd.add(I.pluck(m, 1.2, 0.5, bright=0.6, decay=2.4, seed=k), t(eb))
    glk.add(I.bell(key.degree(1, 6), 0.6, 3.5), t(eb), 1.0)
    s.kick_at(kick, t(eb), I.kick(0.8, f_hi=120.0, f_lo=50.0, decay=0.4, click=0.15, drive=1.2))
    return s
