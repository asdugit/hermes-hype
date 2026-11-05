"""Terminal beds: darksynth (~105-115 BPM) - distorted rolling saw bass, gated big snare, square arps,
detuned saw lead with delay, phrygian tension."""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony, phrase

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=110, tonic="D", mode="phrygian", label="D phrygian",
              prog=[(1, "triad"), (2, "triad"), (1, "triad"), (7, "triad")],
              prog_b=[(6, "triad"), (7, "triad"), (1, "triad"), (2, "triad")], end=(1, "5"),
              title="Root Shell", notes="Darksynth: rolling distorted bass, gated snare, square arp, saw lead."),
    "b": dict(bpm=114, tonic="C", mode="minor", label="C minor",
              prog=[(1, "triad"), (6, "triad"), (3, "triad"), (7, "triad")],
              prog_b=[(4, "triad"), (6, "triad"), (5, "triad"), (5, "triad")], end=(1, "5"),
              title="Night Build", notes="Retro-dark synthwave: four-on-floor, octave bass, wide pad, echo lead."),
}

LEAD = [[(0, 1.5, 0), (1.5, 0.5, 1), (2, 1.0, 3), (3, 1.0, 1)], [(0, 2.0, 0), (2, 1.0, -2), (3, 1.0, -4)],
        [(0, 1.5, 7), (1.5, 0.5, 5), (2, 1.0, 3), (3, 1.0, 5)], [(0, 3.0, 0), (3, 0.5, 1), (3.5, 0.5, 3)]]


def compose(v: str) -> Song:
    """Build the Terminal bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"terminal_{v}", "terminal", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=4.0, title=P["title"], notes=P["notes"])
    key = Key(P["tonic"], P["mode"])
    h = Harmony(s, key, {"B": P["prog_b"]}, P["prog"], pad_range=(55, 74), bass_octave=2, end_chord=P["end"])
    T, t, B = s.track, s.t, s.beat
    r = D.rng("terminal", v)
    kick = T("kick", gain_db=-9.0)
    snr = T("snare", gain_db=-8.0, reverb=0.45)
    hat = T("hat", gain_db=-20.0, pan=0.2)
    bass = T("bass", gain_db=-14.0, pump=0.45, hp=45.0)
    pad = T("pad", gain_db=-11.0, pump=0.5, reverb=0.4, width=1.4,
            sweep=[(0, 700.0), (t(4), 2200.0), (t(12), 2200.0), (t(15.8), 7000.0), (t(40), 7000.0)])
    arp = T("arp", gain_db=-11.0, delay=0.3, reverb=0.2, hp=250.0, width=1.25,
            sweep=[(0, 900.0), (t(4), 2600.0), (t(12), 2600.0), (t(16), 8000.0), (t(24), 5000.0), (t(40), 5000.0)])
    led = T("lead", gain_db=-7.5, delay=0.32, reverb=0.35)
    fx = T("fx", gain_db=-8.0)
    s.delay_time = B * 0.75
    four = v == "b"
    for bar, sec, i in s.bars():
        name = sec.name
        ch = h.voiced[bar]
        root = h.roots[bar]
        if name == "end":
            continue
        pad.add(I.saw_pad(ch, s.bar, 0.5, attack=0.4 if bar == 0 else 0.05, release=0.6, cutoff=1800.0, seed=bar), t(bar))
        # arp: square 16ths through the swept filter
        if name != "drop" or four:
            tones = sorted(ch) + [sorted(ch)[0] + 12]
            pat = [0, 2, 1, 3, 2, 0, 3, 1] if not four else [0, 1, 2, 3, 3, 2, 1, 0]
            steps = 14 if name == "build" and i == 3 else 16
            for k in range(steps):
                m = tones[pat[k % 8] % len(tones)] + 12
                arp.add(I.pluck(m, B * 0.2, 0.75 if k % 4 == 0 else 0.55, bright=1.2, decay=0.25, shape="square", seed=k),
                        t(bar, k / 4))
        # bass: rolling 16ths (phrygian) or octave 8ths
        if name in ("A", "build", "drop", "B") or (name == "outro" and i == 0):
            stop = 3.5 if name == "build" and i == 3 else 4.0
            if not four:
                k = 0
                while k / 4 < stop:
                    acc = 1.0 if k % 4 == 0 else 0.7
                    bass.add(I.bass(root, B * 0.2, acc, cutoff=650.0 + (250 if name == "drop" else 0), drive=2.6,
                                    env_t=0.04), t(bar, k / 4))
                    k += 1
            else:
                k = 0
                while k / 2 < stop:
                    bass.add(I.bass(root + (12 if k % 2 else 0), B * 0.42, 0.95, cutoff=760.0, drive=2.2, env_t=0.05),
                             t(bar, k / 2))
                    k += 1
        elif name == "intro" and i >= 2:
            bass.add(I.bass(root, s.bar * 0.95, 0.6, cutoff=260.0, drive=1.5), t(bar))
        # drums
        if name in ("A", "drop", "B") or (name == "outro" and i == 0) or (name == "build" and i < 3):
            kb = [0, 1, 2, 3] if (name == "drop" or four) else [0, 2.5] if name == "A" else [0, 1.75, 2.5]
            for bt in kb:
                s.kick_at(kick, t(bar, bt), I.kick(1.0, f_hi=170.0, f_lo=45.0, decay=0.5, drive=2.2))
            if name != "build":
                for bt in (1, 3):
                    sn = I.snare(1.0, 175.0, 0.28, 0.9, seed=bar)
                    snr.add(sn, t(bar, bt))
            for k in range(8):
                hat.add(I.hat(0.8 if k % 2 else 0.5, seed=k, tone=0.9), t(bar, k / 2) + (r.random() - 0.5) * 0.003)
        if name == "build":
            step = 1.0 if i < 2 else 0.5 if i == 2 else 0.25
            bt = 0.0
            while bt < (3.5 if i == 3 else 4.0) - 1e-6:
                snr.add(I.snare(0.35 + 0.15 * i + 0.04 * bt, 180.0, 0.15, seed=int(bt * 4)), t(bar, bt), -4.0)
                bt += step
            if i == 0:
                fx.add(I.riser(4 * s.bar, seed=9, tonal=key.degree(1, 3)), t(bar), -2.0)
        if i == 0 and name in ("A", "drop", "outro"):
            fx.add(I.crash(0.7, 2.5, seed=bar), t(bar), -3.0)
        if name == "drop" and i == 0:
            fx.add(I.boom(0.8, 50.0, 1.4), t(bar), -4.0)
        # lead
        if name == "drop" or (name == "B" and i >= 4):
            for bt, d, m in phrase(h, bar, LEAD[i % 4], key.degree(1, 5) - (12 if name == "B" else 0), strong=(0.0,)):
                led.add(I.lead(m, d * B * 0.95, 0.75, cutoff=2200.0, vib=0.2, detune=0.12), t(bar, bt))
        if name == "B" and i < 4:
            for bt, d, m in phrase(h, bar, [(0, 0.5, 7), (0.75, 0.5, 5), (1.5, 2.0, 3)], key.degree(1, 5), strong=(0.0,)):
                led.add(I.pluck(m, d * B, 0.6, bright=0.9, decay=0.9, shape="square"), t(bar, bt), -3.0)
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    pad.add(I.saw_pad(ch, s.bar * 0.5, 0.6, attack=0.01, release=3.5, cutoff=2200.0, seed=77), t(eb))
    bass.add(I.bass(h.roots[eb], 1.5, 0.8, cutoff=260.0, drive=1.8), t(eb))
    led.add(I.lead(key.degree(1, 5), s.bar * 0.6, 0.6, cutoff=1800.0, vib=0.25), t(eb))
    s.kick_at(kick, t(eb), I.kick(1.0, f_hi=170.0, f_lo=45.0, decay=0.6, drive=2.2))
    snr.add(I.snare(0.8, 175.0, 0.4, seed=3), t(eb))
    fx.add(I.crash(0.6, 3.0, seed=eb), t(eb), -4.0)
    return s
