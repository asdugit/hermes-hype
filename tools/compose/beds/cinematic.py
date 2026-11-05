"""Cinematic beds: ambient pads + drone, a bowed 150-400 Hz top line (phones carry it), a hybrid build
with a suck-out, ONE designed impact at the drop, then a low-string ostinato and taiko (70-80 BPM)."""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from ..song import Song
from ..theory import Key
from .common import Harmony, phrase

LAYOUT = [("intro", 2, 0.25), ("A", 4, 0.45), ("build", 2, 0.7), ("drop", 4, 1.0), ("B", 4, 0.75),
          ("outro", 2, 0.4), ("end", 1, 0.2)]

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=72, tonic="D", mode="minor", label="D minor",
              prog=[(1, "add9"), (6, "7"), (3, "triad"), (7, "sus2")], prog_b=[(6, "7"), (4, "7"), (1, "add9"), (5, "sus4")],
              end=(1, "add9"), title="Evidence", notes="Dark-to-bright trailer bed: drone, bowed top line, suck-out, one impact."),
    "b": dict(bpm=76, tonic="E", mode="major", label="E major",
              prog=[(1, "9"), (6, "7"), (4, "7"), (5, "add9")], prog_b=[(4, "7"), (1, "9"), (6, "7"), (5, "sus4")],
              end=(1, "9"), title="Horizon", notes="Warm ambient-product bed: glassy pads, felt piano, bowed line, one impact."),
}

TOP = [[(0, 2, 0), (2, 1, 3), (3, 1, 5)], [(0, 3, 7), (3, 1, 5)], [(0, 4, 3)], [(0, 2, 5), (2, 2, 0)]]
TOP_DROP = [[(0, 1.5, 7), (1.5, 0.5, 5), (2, 2, 3)], [(0, 2, 5), (2, 2, 8)], [(0, 3, 7), (3, 1, 10)], [(0, 4, 12)]]
PIANO = [(0.0, 1.5, 12), (1.5, 1.0, 7), (2.5, 1.5, 9)]


def compose(v: str) -> Song:
    """Build the Cinematic bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"cinematic_{v}", "cinematic", P["bpm"], P["label"], LAYOUT, tail_s=7.0, title=P["title"], notes=P["notes"])
    key = Key(P["tonic"], P["mode"])
    h = Harmony(s, key, {"B": P["prog_b"], "outro": P["prog_b"]}, P["prog"], pad_range=(52, 74), bass_octave=2,
                end_chord=P["end"])
    T, t, B = s.track, s.t, s.beat
    bld = s.sec("build")
    drop_t = t(s.sec("drop").start_bar)
    suck = 0.8
    drone = T("drone", gain_db=-14.0, gain=[(0, -6.0), (t(2), 0.0), (drop_t - suck - 0.05, 0.0), (drop_t - suck + 0.25, -30.0),
                                             (drop_t, -30.0), (drop_t + 0.02, 0.0)])
    pad = T("pad", gain_db=-9.0, reverb=0.5, width=1.4)
    top = T("topline", gain_db=-6.0, reverb=0.35, pan=-0.05)
    pno = T("piano", gain_db=-9.0, reverb=0.55, delay=0.2, pan=0.15)
    ost = T("ostinato", gain_db=-10.0, reverb=0.2, pump=0.25, width=1.2)
    perc = T("perc", gain_db=-8.0, reverb=0.3)
    fx = T("fx", gain_db=-5.0)
    bell = T("bell", gain_db=-16.0, reverb=0.6, delay=0.25, pan=-0.2)
    s.reverb_ir = D.reverb_ir(4.2, 0.03, 0.5, seed=s.id)
    center = key.degree(1, 3) + 7          # A3 / B3: the 150-400 Hz band
    tonic2 = key.degree(1, 2)

    # drone: one long tone per section group (tonic + fifth), slow swell
    total = t(s.sec("end").start_bar)
    dr = I.saw_pad([tonic2 - 12, tonic2 - 5, tonic2], total, 0.55, attack=4.0, release=3.0, cutoff=380.0, detune=0.08,
                   voices=3, seed=7)
    drone.add(dr, 0.0)

    for bar, sec, i in s.bars():
        name = sec.name
        ch = h.voiced[bar]
        if name == "end":
            continue
        last_build = name == "build" and i == bld.bars - 1
        dur = s.bar - (suck + 0.1 if last_build else 0.0)
        cut = {"intro": 900.0, "A": 1400.0, "build": 2000.0 + 600 * i, "drop": 3400.0, "B": 2400.0, "outro": 1300.0}[name]
        pv = {"intro": 0.55, "A": 0.55, "build": 0.6, "drop": 0.62, "B": 0.55, "outro": 0.5}[name]
        pad.add(I.saw_pad(ch, dur, pv, attack=1.2 if i == 0 else 0.25, release=1.0 if last_build else 1.8,
                          cutoff=cut, seed=bar), t(bar))
        if name in ("drop", "B"):
            pad.add(I.saw_pad([m + 12 for m in ch[1:]], dur, 0.25, attack=0.5, release=2.0, cutoff=4200.0, seed=bar + 50), t(bar))
        # top line (bowed) in A, drop, B
        if name in ("A", "drop", "B"):
            bank = TOP_DROP if name == "drop" else TOP
            for bt, d, m in phrase(h, bar, bank[i % 4], center, span=8, strong=(0.0,)):
                top.add(I.cello(m, d * B * 0.98, 0.85 if name == "drop" else 0.7, attack=0.3), t(bar, bt))
                if name == "drop":
                    top.add(I.cello(m + 12, d * B * 0.98, 0.35, attack=0.4), t(bar, bt))
                    bell.add(I.bell(m + 24, 0.5, 3.0), t(bar, bt))
        # felt piano: intro / B / outro, sparse
        if name in ("intro", "B", "outro") or (name == "A" and i % 2 == 1):
            for bt, d, m in phrase(h, bar, PIANO, key.degree(1, 4) + 7, span=7):
                pno.add(I.felt_piano(m, d * B, 0.55), t(bar, bt))
        # heartbeat / ostinato
        if name in ("A", "B", "outro"):
            for k in range(8):
                if name == "outro" and i == 1 and k >= 4:
                    break
                vel = 0.55 if k % 2 == 0 else 0.35
                ost.add(I.pluck(h.roots[bar] + 12, B * 0.4, vel, bright=0.35, decay=0.5), t(bar, k * 0.5))
        elif name == "build":
            n16 = 16 if not last_build else 12
            for k in range(n16):
                if t(bar, k * 0.25) > drop_t - suck:
                    break
                ost.add(I.bass(h.roots[bar] + 12, B * 0.2, 0.45 + 0.03 * k, cutoff=500.0 + 60 * k, drive=1.2), t(bar, k * 0.25))
        elif name == "drop":
            for k in range(16):
                acc = 0.9 if k % 4 == 0 else 0.6
                ost.add(I.bass(h.roots[bar] + 12 + (7 if k % 8 == 6 else 0), B * 0.2, acc, cutoff=900.0, drive=1.6),
                        t(bar, k * 0.25))
        # percussion
        if name == "build":
            step = 1.0 if i == 0 else 0.5
            bt = 0.0
            while t(bar, bt) < drop_t - suck - 0.05 and bt < 4:
                perc.add(I.taiko(0.45 + 0.12 * i + 0.05 * bt, 80.0), t(bar, bt))
                bt += step
        if name == "drop":
            for bt, vel in ((0, 1.0), (1.5, 0.7), (2, 0.85), (3, 0.6), (3.5, 0.6)):
                if i == 0 and bt == 0:
                    continue
                s.kick_at(perc, t(bar, bt), I.taiko(vel, 68.0))
        if name == "B":
            for bt in (0, 2.5):
                perc.add(I.taiko(0.45, 70.0), t(bar, bt))
    # build riser + reverse swell + the impact
    fx.add(I.riser(bld.bars * s.bar - suck * 0.5, seed=3, tonal=tonic2 + 12), t(bld.start_bar), -3.0)
    fx.add(I.reverse_swell(2.2, seed=5), drop_t - 2.2, -2.0)
    fx.add(I.impact(1.0, seed=11, sub_f=50.0, tail=3.5), drop_t, 0.0)
    s.kicks.append(drop_t)
    # ending: final chord rings
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    pad.add(I.saw_pad(ch, s.bar * 0.5, 0.6, attack=0.3, release=5.5, cutoff=1800.0, seed=99), t(eb))
    top.add(I.cello(key.degree(1, 3), s.bar * 0.8, 0.7, attack=0.25), t(eb))
    for k, m in enumerate(sorted(ch)[:4]):
        pno.add(I.felt_piano(m + 12, 3.0, 0.5), t(eb) + 0.03 * k)
    bell.add(I.bell(key.degree(1, 6), 0.5, 5.0), t(eb), 3.0)
    perc.add(I.taiko(0.5, 60.0), t(eb))
    return s
