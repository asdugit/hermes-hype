"""Dream beds: the anime meadow moment - piano, warm strings, soft choir/air pad, glockenspiel and chimes,
major key, 72-90 BPM, swelling and uplifting (never sad). Phrases resolve on I or rest on an open fifth.

Keys are chosen to receive the pixel_boss cadences: pixel_boss_a (A minor) ends its outro on G (V of C) and
dream_a is in C; pixel_boss_b (E minor) ends on D (V of G) and dream_b is in G.
"""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from .. import orchestra as O
from ..song import Song
from ..theory import Key
from .common import Harmony

LAYOUT = [("intro", 2, 0.3), ("A", 4, 0.5), ("build", 2, 0.7), ("drop", 8, 1.0), ("B", 4, 0.75),
          ("outro", 2, 0.45), ("end", 1, 0.2)]

Mel = list[list[tuple[float, float, int]]]      # per bar: (beat, dur_beats, scale degree; 8 = tonic an octave up)

# dream_a (C major): royal-road chorus, singable 4-bar answers, phrase ends on the open fifth
A_A: Mel = [[(0, 1, 5), (1, 1, 8), (2, 1.5, 10), (3.5, 0.5, 9)], [(0, 2, 9), (2, 1, 7), (3, 1, 5)],
            [(0, 1, 8), (1, 1, 10), (2, 1.5, 12), (3.5, 0.5, 10)], [(0, 1.5, 13), (1.5, 0.5, 12), (2, 2, 10)]]
A_DROP: Mel = [[(0, 1, 6), (1, 1, 8), (2, 1.5, 10), (3.5, 0.5, 9)], [(0, 1.5, 9), (1.5, 0.5, 8), (2, 1, 9), (3, 1, 12)],
               [(0, 1.5, 12), (1.5, 0.5, 10), (2, 1, 9), (3, 1, 10)], [(0, 2, 10), (2, 0.5, 9), (2.5, 0.5, 8), (3, 1, 9)],
               [(0, 1, 8), (1, 1, 10), (2, 1.5, 13), (3.5, 0.5, 12)], [(0, 1.5, 12), (1.5, 0.5, 13), (2, 1, 14), (3, 1, 16)],
               [(0, 2.5, 15), (2.5, 0.5, 12), (3, 1, 10)], [(0, 1, 9), (1, 3, 12)]]
A_B: Mel = [[(0, 2, 10), (2, 1, 12), (3, 1, 13)], [(0, 1.5, 13), (1.5, 0.5, 12), (2, 2, 10)],
            [(0, 1, 12), (1, 1, 10), (2, 1, 9), (3, 1, 8)], [(0, 3, 9), (3, 1, 8)]]
A_OUTRO: Mel = [[(0, 2, 13), (2, 2, 12)], [(0, 4, 9)]]

# dream_b (G major): canon-like descending bass under a soaring violin line
B_A: Mel = [[(0, 1, 3), (1, 1, 5), (2, 1.5, 8), (3.5, 0.5, 7)], [(0, 2, 5), (2, 1, 3), (3, 1, 2)],
            [(0, 1, 3), (1, 1, 5), (2, 1.5, 6), (3.5, 0.5, 5)], [(0, 2, 7), (2, 1, 6), (3, 1, 5)]]
B_DROP: Mel = [[(0, 1.5, 10), (1.5, 0.5, 9), (2, 1, 8), (3, 1, 10)], [(0, 1.5, 9), (1.5, 0.5, 7), (2, 2, 5)],
               [(0, 1.5, 8), (1.5, 0.5, 9), (2, 1, 10), (3, 1, 12)], [(0, 2, 12), (2, 1, 10), (3, 1, 9)],
               [(0, 2, 13), (2, 1, 12), (3, 1, 10)], [(0, 1.5, 12), (1.5, 0.5, 10), (2, 2, 8)],
               [(0, 1, 13), (1, 1, 12), (2, 1, 10), (3, 1, 11)], [(0, 2, 9), (2, 1, 7), (3, 1, 9)]]
B_B: Mel = [[(0, 2, 10), (2, 1, 8), (3, 1, 9)], [(0, 2, 9), (2, 2, 7)], [(0, 1, 6), (1, 1, 8), (2, 2, 10)],
            [(0, 3, 9), (3, 1, 12)]]
B_OUTRO: Mel = [[(0, 2, 10), (2, 2, 9)], [(0, 4, 9)]]

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=80, tonic="C", label="C major", title="Meadow Light",
              prog={"intro": [(4, "maj7"), (5, "sus4")], "A": [(1, "add9"), (5, "triad"), (6, "7"), (4, "maj7")],
                    "build": [(2, "7"), (5, "sus4")],
                    "drop": [(4, "maj7"), (5, "triad"), (3, "7"), (6, "triad"), (4, "maj7"), (5, "triad"),
                             (1, "add9"), (1, "add9")],
                    "B": [(6, "7"), (4, "maj7"), (1, "add9"), (5, "sus4")], "outro": [(4, "maj7"), (5, "sus4")]},
              bass={"A": [1, 7, 6, 4]}, end=(1, "add9"), mel={"A": A_A, "drop": A_DROP, "B": A_B, "outro": A_OUTRO},
              arp_piano="felt", mel_piano="grand", sparkle="glock",
              notes="Anime meadow bed: felt-piano arpeggios, grand-piano tune, warm strings, soft choir, glockenspiel; "
                    "the chorus blooms with soaring violins on the royal-road progression."),
    "b": dict(bpm=88, tonic="G", label="G major", title="Paper Sky",
              prog={"intro": [(1, "add9"), (4, "maj7")], "A": [(1, "triad"), (3, "7"), (4, "maj7"), (5, "triad")],
                    "build": [(2, "7"), (5, "7sus4")],
                    "drop": [(1, "add9"), (5, "triad"), (6, "7"), (3, "7"), (4, "maj7"), (1, "triad"),
                             (4, "maj7"), (5, "triad")],
                    "B": [(6, "7"), (5, "triad"), (4, "maj7"), (5, "triad")], "outro": [(4, "maj7"), (5, "sus4")]},
              bass={"drop": [1, 7, 6, 5, 4, 3, 4, 5]}, end=(1, "add9"),
              mel={"A": B_A, "drop": B_DROP, "B": B_B, "outro": B_OUTRO},
              arp_piano="grand", mel_piano="grand", sparkle="celesta",
              notes="Bright flowing dream bed: grand-piano ostinato, celesta, canon-like bass walking down under a "
                    "soaring violin line, choir 'ah' in the chorus, harp glissandi."),
}

ARP = [0, 1, 2, 3, 4, 3, 2, 1]


def compose(v: str) -> Song:
    """Build the Dream bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"dream_{v}", "dream", P["bpm"], P["label"], LAYOUT, tail_s=7.0, title=P["title"], notes=P["notes"])
    s.meta = {"family": "dream", "mood": "uplifting"}
    key = Key(P["tonic"], "major")
    h = Harmony(s, key, P["prog"], P["prog"]["A"], pad_range=(55, 74), bass_octave=2, end_chord=P["end"])
    T, t, B = s.track, s.t, s.beat
    s.reverb_ir = D.reverb_ir(3.4, 0.025, 0.5, seed=s.id)
    s.delay_time = B * 0.75
    arp = T("piano_arp", gain_db=-9.5, reverb=0.45, width=1.25)
    mel = T("piano_mel", gain_db=1.5, reverb=0.42, delay=0.08)
    vln = T("violins", gain_db=-8.0, reverb=0.5)
    pad = T("strings", gain_db=-10.0, reverb=0.4, width=1.35)
    low = T("low_strings", gain_db=-11.0, reverb=0.25)
    cho = T("choir", gain_db=-11.0, reverb=0.6, width=1.4)
    spk = T("sparkle", gain_db=-9.0, reverb=0.55, delay=0.22, pan=0.2)
    hrp = T("harp", gain_db=-13.5, reverb=0.5, width=1.2)
    kick = T("kick", gain_db=-11.0, reverb=0.08)
    snr = T("snare", gain_db=-6.0, reverb=0.3)
    shk = T("shaker", gain_db=-18.0, pan=0.25)
    fx = T("fx", gain_db=-12.0, reverb=0.3)

    def deg(d: int, octave: int = 4) -> int:
        return key.degree(d, octave)

    def bass_note(bar: int, sec_name: str, i: int) -> int:
        line = P["bass"].get(sec_name)
        return deg(line[i % len(line)], 2) if line else h.roots[bar]

    piano = O.grand_piano if P["arp_piano"] == "grand" else (lambda m, d, vel, seed=0: I.felt_piano(m, d, vel, seed))
    sparkle = O.glock if P["sparkle"] == "glock" else O.celesta
    drop0 = s.sec("drop").start_bar
    for bar, sec, i in s.bars():
        name = sec.name
        if name == "end":
            continue
        ch = h.voiced[bar]
        root = bass_note(bar, name, i)
        energy = sec.energy
        # ---- piano arpeggio (8ths; open voicing from the bass up)
        tones = sorted({root + 12} | {m for m in ch + [c + 12 for c in ch] if m > root + 12})[:5]
        for k in range(8 if name != "outro" or i == 0 else 4):
            if name == "intro" and i == 0 and k % 2:
                continue
            idx = ARP[k] if v == "a" else (0, 2, 1, 3, 2, 4, 3, 2)[k]
            vel = (0.42 + 0.12 * energy) * (1.0 if k % 2 == 0 else 0.82)
            arp.add(piano(tones[idx], B * (1.6 if v == "a" else 0.9), vel, seed=bar * 8 + k), t(bar, k * 0.5),
                    pan=-0.35 + 0.15 * idx)
        # ---- low strings (bass) + string pad
        if name != "intro" or i == 1:
            low.add(O.strings([root, root + 12], s.bar * 0.98, 0.5 + 0.25 * energy, attack=0.5, release=0.9,
                              bright=900.0, voices=2, seed=bar), t(bar))
        pad_vel = {"intro": 0.32, "A": 0.42, "build": 0.55, "drop": 0.62, "B": 0.5, "outro": 0.42}[name]
        swell = 0.55 if name == "build" else (0.25 if name in ("A", "B") else 0.0)
        pad.add(O.strings(ch, s.bar * 0.98, pad_vel, attack=0.9 if i == 0 else 0.35, release=1.2,
                          bright=1900.0 + 1600.0 * energy, swell=swell, seed=bar), t(bar))
        if name == "drop":
            pad.add(O.strings([m + 12 for m in ch[1:]], s.bar * 0.98, 0.3, attack=0.5, release=1.4, bright=4200.0,
                              voices=2, seed=bar + 40), t(bar))
        # ---- choir / air pad
        if name in ("intro", "A", "B", "outro"):
            cho.add(O.choir(ch[-3:], s.bar, 0.35 + 0.15 * energy, "oo", attack=1.4, release=1.6, breath=0.4,
                            seed=bar), t(bar))
        elif name in ("build", "drop"):
            cho.add(O.choir(ch[-3:], s.bar, 0.55 if name == "drop" else 0.45 + 0.15 * i, "ah", attack=0.8,
                            release=1.6, breath=0.25, seed=bar), t(bar))
        # ---- melody
        bank = P["mel"].get(name)
        if bank:
            for bt, d, dg in bank[i % len(bank)]:
                m = deg(dg, 4)
                if name == "drop":
                    vln.add(O.violin_line(m, d * B * 0.97, 0.75, attack=0.1, seed=bar), t(bar, bt))
                    vln.add(O.violin_line(m - 12, d * B * 0.97, 0.35, attack=0.14, seed=bar + 9), t(bar, bt))
                    if v == "b" and bt % 2 == 0:
                        spk.add(sparkle(m + 12, 0.5, seed=bar), t(bar, bt))
                else:
                    mv = 0.55 if name == "A" else 0.5
                    mel.add(O.grand_piano(m, d * B, mv, seed=bar * 13 + int(bt * 4)), t(bar, bt), pan=0.1)
                    if name == "B":
                        vln.add(O.violin_line(m, d * B * 0.97, 0.4, attack=0.18, seed=bar), t(bar, bt))
            last = bank[i % len(bank)][-1]
            if name in ("A", "B") and i % 2 == 1:
                spk.add(sparkle(deg(last[2], 5), 0.55, seed=bar), t(bar, last[0]))
        # ---- sparkle countermelody in the chorus (a), chord tones every 2 beats
        if name == "drop" and v == "a":
            top = sorted(m % 12 for m in ch)
            for k, bt in enumerate((0.5, 2.5)):
                pcs = [p for p in top if p != (root % 12)] or top
                m = 84 + (pcs[(bar + k) % len(pcs)] - 84) % 12
                spk.add(sparkle(m, 0.45, seed=bar * 2 + k), t(bar, bt))
        # ---- harp: arpeggios in B, glissandi into sections
        if name == "B" or (v == "b" and name == "A" and i % 2 == 1):
            for k in range(4):
                hrp.add(O.harp(tones[(k * 2) % 5] + 12, 0.45, seed=bar * 4 + k), t(bar, 0.5 + k))
        # ---- drums (only from the chorus on; soft ballad groove)
        if name == "drop" or (name == "B" and v == "b"):
            ks = (0.0, 2.5) if v == "a" else (0.0, 2.0)
            for bt in ks:
                s.kick_at(kick, t(bar, bt), O.soft_kick(0.85 if bt == 0 else 0.65))
            for bt in (1.0, 3.0):
                snr.add(D.mix((O.brush(0.6, seed=bar * 2 + int(bt)), 1.0), (I.clap(0.35, seed=bar), 0.5)), t(bar, bt))
            for k in range(8 if v == "a" else 16):
                step = 0.5 if v == "a" else 0.25
                shk.add(I.shaker((0.6, 0.35)[k % 2], seed=k % 5), t(bar, k * step))
        elif name == "B":
            s.kick_at(kick, t(bar), O.soft_kick(0.55))
        # ---- transitions
        if name == "build":
            if i == 0:
                fx.add(O.cymbal_swell(2 * s.bar - 0.05, seed=bar), t(bar), -2.0)
            for k in range(16 if i == 1 else 4):
                step = 0.25 if i == 1 else 1.0
                fx.add(O.soft_timp(float(D.mtof(deg(1, 2))), 0.25 + 0.04 * k), t(bar, k * step))
            if i == 1:
                for k, m in enumerate(sorted({deg(dd, 4) for dd in range(1, 16)})):
                    hrp.add(O.harp(m, 0.35 + 0.02 * k, seed=k), t(bar, 3.0) + k * B / 16)
        if bar == drop0 or (name == "B" and i == 0):
            fx.add(O.chime_tree(1.0, up=bar == drop0, seed=bar), t(bar), -4.0)
            fx.add(I.crash(0.35, 2.5, seed=bar), t(bar), -10.0)
            fx.add(O.soft_timp(float(D.mtof(deg(1, 2))), 0.8), t(bar))
    # ---- ending: rolled tonic chord, harp gliss, chimes, glock on the tonic
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    root = h.roots[eb]
    pad.add(O.strings(ch, s.bar * 0.6, 0.5, attack=0.2, release=4.5, bright=2600.0, seed=99), t(eb))
    low.add(O.strings([root, root + 12], s.bar * 0.6, 0.5, attack=0.2, release=4.0, bright=900.0, voices=2, seed=98), t(eb))
    cho.add(O.choir(ch[-3:], s.bar * 0.7, 0.45, "ah", attack=0.4, release=4.0, seed=97), t(eb))
    for k, m in enumerate(sorted({root + 12, root + 19} | set(ch))):
        mel.add(O.grand_piano(m, 4.0, 0.5, seed=200 + k, pedal=1.0), t(eb) + 0.035 * k)
    for k, m in enumerate(sorted({deg(dd, 4) for dd in range(1, 15)})):
        hrp.add(O.harp(m, 0.3 + 0.015 * k, seed=300 + k), t(eb) - B + k * B / 14)
    spk.add(sparkle(deg(8, 5), 0.6, decay=3.0, seed=1), t(eb))
    fx.add(O.chime_tree(1.4, seed=7), t(eb) + 0.1, -5.0)
    s.kick_at(kick, t(eb), O.soft_kick(0.6))
    return s
