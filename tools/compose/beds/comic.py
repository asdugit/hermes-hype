"""Comic beds: punchy, playful, brassy funk (110-125 BPM) - synth-brass section stabs and licks, slap bass,
clavinet comping, tight funk kit with ghost notes, tambourine, cartoon touches (slide whistle, woodblock).
"""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from .. import orchestra as O
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony

# slap pattern per bar: (beat, kind T/P/G, semitones over the chord root, dur beats)
SLAP_1 = [(0, "T", 0, 0.4), (0.5, "G", 0, 0.1), (0.75, "P", 12, 0.2), (1.25, "T", 0, 0.2), (1.5, "T", 10, 0.3),
          (1.75, "P", 12, 0.2), (2.5, "T", 7, 0.3), (2.75, "G", 0, 0.1), (3, "P", 12, 0.2), (3.5, "T", 10, 0.2),
          (3.75, "T", 0, 0.2)]
SLAP_2 = [(0, "T", 0, 0.4), (0.5, "P", 12, 0.2), (0.75, "G", 0, 0.1), (1, "T", 0, 0.2), (1.5, "P", 10, 0.2),
          (2, "T", 7, 0.3), (2.5, "G", 0, 0.1), (2.75, "P", 12, 0.2), (3.25, "T", 5, 0.2), (3.5, "T", 7, 0.3)]
LICK = [(0, 0.25, 0), (0.25, 0.25, 3), (0.5, 0.5, 4), (1.0, 0.5, 7), (1.5, 0.75, 10), (2.25, 0.25, 7), (2.5, 1.0, 4)]
STABS = [(0, 0.25), (0.75, 0.25), (1.5, 0.5), (2.75, 0.25), (3.5, 0.4)]
STABS_A = [(2.75, 0.25), (3.5, 0.35)]

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=116, tonic="F", mode="mixolydian", label="F mixolydian", title="Splash Page",
              prog={"intro": [(1, "dom7"), (1, "dom7"), (4, "dom7"), (5, "dom7")],
                    "A": [(1, "dom7"), (1, "dom7"), (4, "dom7"), (4, "dom7"), (1, "dom7"), (1, "dom7"), (2, "m7"), (5, "dom7")],
                    "build": [(2, "m7"), (5, "dom7"), (2, "m7"), (5, "7#9")],
                    "drop": [(1, "dom7"), (4, "dom7"), (1, "dom7"), (5, "dom7"), (1, "dom7"), (4, "dom7"), (7, "dom7"), (5, "dom7")],
                    "B": [(6, "m7"), (2, "m7"), (5, "dom7"), (1, "dom7"), (6, "m7"), (2, "m7"), (4, "dom7"), (5, "dom7")],
                    "outro": [(4, "dom7"), (5, "dom7")]},
              end=(1, "69"), quartal=False, perc="tambourine",
              notes="Brassy cartoon funk: slap bass, clav 16ths, horn-section stabs and a blues lick in the drop, "
                    "slide whistle into the drop, big brass button ending."),
    "b": dict(bpm=122, tonic="D", mode="dorian", label="D dorian", title="Kapow!",
              prog={"intro": [(1, "m7"), (1, "m7"), (4, "dom7"), (4, "dom7")],
                    "A": [(1, "m7"), (4, "dom7"), (1, "m7"), (4, "dom7"), (6, "maj7", -1), (5, "dom7"), (1, "m7"), (5, "dom7")],
                    "build": [(6, "maj7", -1), (7, "dom7"), (6, "maj7", -1), (5, "7#9")],
                    "drop": [(1, "m7"), (4, "dom7"), (1, "m7"), (4, "dom7"), (6, "maj7", -1), (7, "dom7"), (5, "dom7"), (5, "7#9")],
                    "B": [(4, "m7"), (7, "dom7"), (3, "maj7"), (6, "maj7", -1), (2, "m7b5"), (5, "dom7"), (1, "m7"), (5, "dom7")],
                    "outro": [(6, "maj7", -1), (5, "dom7")]},
              end=(1, "m9"), quartal=True, perc="bongo",
              notes="Caper funk: quartal brass hits, popping slap bass, bongos and woodblock, dorian vamp with a "
                    "#9 build, sly brass licks and a final 'kapow' stab.")
}


def _quartal(top: int) -> list[int]:
    """Three-note stack of fourths under ``top`` (the 'So What' brass colour)."""
    return [top - 10, top - 5, top]


def compose(v: str) -> Song:
    """Build the Comic bed variant ``v``."""
    P = VARIANTS[v]
    s = Song(f"comic_{v}", "comic", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=3.5, title=P["title"], notes=P["notes"])
    s.meta = {"family": "comic", "mood": "playful"}
    key = Key(P["tonic"], P["mode"])
    h = Harmony(s, key, P["prog"], P["prog"]["A"], pad_range=(62, 79), bass_octave=1, end_chord=P["end"])
    r = D.rng("comic", v)
    T, t, B = s.track, s.t, s.beat
    s.reverb_ir = D.reverb_ir(1.6, 0.012, 0.6, seed=s.id)
    kick = T("kick", gain_db=-9.5)
    snr = T("snare", gain_db=-9.5, reverb=0.18)
    hat = T("hat", gain_db=-18.0, pan=0.2)
    ohat = T("ohat", gain_db=-19.0, pan=-0.2)
    perc = T("perc", gain_db=-12.0, pan=0.35, reverb=0.1)
    bass = T("slap", gain_db=-10.0, hp=40.0)
    clv = T("clav", gain_db=-7.0, pan=-0.3, reverb=0.08)
    brs = T("brass", gain_db=-6.0, reverb=0.22, width=1.3)
    pad = T("brass_pad", gain_db=-14.0, reverb=0.35, width=1.4)
    fx = T("fx", gain_db=-10.0, reverb=0.2)

    def brass_chord(bar: int, oct_up: bool = False) -> list[int]:
        ch = sorted(h.voiced[bar])[-3:]
        if P["quartal"]:
            ch = _quartal(max(ch))
        return [m + 12 for m in ch] if oct_up else ch

    for bar, sec, i in s.bars():
        name = sec.name
        if name == "end":
            continue
        root = (h.roots[bar] - 40) % 12 + 40       # slap register: E2..D#3 (pops an octave up)
        ch = h.voiced[bar]
        groove = name in ("A", "drop", "B") or (name == "outro" and i == 0)
        # ---- drums
        if groove or (name == "intro" and i >= 1) or (name == "build" and i < 3):
            kp = [0, 0.75, 2.5] if (bar % 2 == 0) else [0, 1.75, 2.5, 3.25]
            if name == "intro" and i < 2:
                kp = [0, 2.5]
            for bt in kp:
                s.kick_at(kick, t(bar, bt), I.kick(0.9, f_hi=170.0, f_lo=52.0, decay=0.28, click=0.45, knock=0.3))
            for bt in (1, 3):
                snr.add(I.snare(0.95, 210.0, 0.16, seed=bar * 2 + bt), t(bar, bt))
            if name != "intro":
                for bt in (1.75, 2.25, 3.75):
                    if r.random() < 0.7:
                        snr.add(I.snare(0.22, 230.0, 0.06, snappy=0.5, seed=bar * 7 + int(bt * 4)), t(bar, bt), -6.0)
            for k in range(16):
                acc = (0.85, 0.35, 0.6, 0.4)[k % 4]
                if name == "drop" and k in (6, 14):
                    ohat.add(I.hat(0.7, open_=True, seed=k), t(bar, k / 4))
                    continue
                hat.add(I.hat(acc * (0.85 + 0.15 * r.random()), seed=k % 5, tone=1.1), t(bar, k / 4) + (r.random() - 0.5) * 0.004)
        elif name == "intro" and i == 0:
            for k in range(4):
                perc.add(O.snap(0.6, seed=k) if v == "a" else O.conga(330.0, 0.5, seed=k), t(bar, k + 0.5))
        if name == "build":
            step = 0.5 if i < 2 else 0.25
            stop = 3.0 if i == 3 else 4.0
            bt = 0.0 if i >= 2 else 2.0
            while bt < stop - 1e-6:
                snr.add(I.snare(0.35 + 0.15 * i + 0.04 * bt, 220.0, 0.1, seed=int(bt * 8) + bar), t(bar, bt), -2.0)
                bt += step
        # ---- percussion colour
        if groove:
            if P["perc"] == "tambourine":
                for k in range(8):
                    perc.add(O.tambourine(0.7 if k % 2 else 0.4, seed=k % 3, long=k in (3, 7)), t(bar, k * 0.5))
            else:
                for bt, fq, sl in ((0, 260.0, False), (0.75, 340.0, False), (1.5, 340.0, True), (2.5, 260.0, False),
                                   (3.0, 340.0, False), (3.5, 340.0, True)):
                    perc.add(O.conga(fq, 0.6, slap_=sl, seed=bar), t(bar, bt))
            if name == "drop":
                for bt in (1, 3):
                    snr.add(I.clap(0.7, seed=bar + int(bt)), t(bar, bt), -3.0)
        if name in ("A", "B") and i % 4 == 3:
            for bt, fq in ((3.0, 900.0), (3.25, 1150.0), (3.5, 900.0), (3.75, 1350.0)):
                fx.add(O.woodblock(fq, 0.6), t(bar, bt), -2.0)
        # ---- slap bass
        if groove or name == "intro" or (name == "build" and i < 3):
            pat = SLAP_1 if (bar % 2 == 0) else SLAP_2
            if name == "intro" and i == 0:
                pat = [p for p in pat if p[0] in (0, 1.5, 2.5, 3.5)]
            for bt, kind, iv, d in pat:
                kk = {"T": "thumb", "P": "pop", "G": "ghost"}[kind]
                bass.add(O.slap_bass(root + iv, d * B, 0.9 if bt == 0 else 0.75, kk, seed=bar * 16 + int(bt * 4)), t(bar, bt))
        elif name == "build" and i == 3:
            for k, iv in enumerate((0, 2, 4, 5, 7, 9)):
                bass.add(O.slap_bass(root + iv, B * 0.4, 0.8, "pop" if k % 2 else "thumb", seed=k), t(bar, k * 0.5))
        # ---- clav comping (16ths with rests)
        if name in ("A", "B", "drop", "build") or (name == "intro" and i >= 2):
            comp = [0.25, 0.75, 1.0, 1.75, 2.25, 2.5, 3.25, 3.75] if bar % 2 == 0 else [0.5, 0.75, 1.5, 2.25, 2.75, 3.25, 3.5]
            voic = sorted(ch)[:3]
            for bt in comp:
                for m in voic:
                    clv.add(O.clav(m, B * 0.18, 0.65 + 0.2 * (bt % 1 == 0.0), seed=bar), t(bar, bt))
        # ---- brass
        if name == "A":
            for bt, d in STABS_A:
                brs.add(O.brass(brass_chord(bar), d * B, 0.75, seed=bar), t(bar, bt))
        elif name == "drop":
            if i % 2 == 0 and i < 6:
                for bt, d, iv in LICK:
                    m = root + 24 + iv
                    m = m - 12 if m > 84 else m
                    fall = 4.0 if (bt, d) == (2.5, 1.0) else 0.0
                    brs.add(O.brass([m - 12, m], d * B * 0.95, 0.9, fall=fall, seed=bar), t(bar, bt))
            else:
                for bt, d in STABS:
                    brs.add(O.brass(brass_chord(bar, oct_up=i == 7 and bt > 3), d * B, 0.95, seed=bar,
                                    fall=5.0 if (i == 7 and bt == 3.5) else 0.0), t(bar, bt))
        elif name == "B":
            pad.add(O.brass(brass_chord(bar), B * 3.8, 0.5, bright=1800.0, scoop=0.3, attack=0.25, seed=bar), t(bar))
            if i % 2 == 1:
                for bt, d in STABS_A:
                    brs.add(O.brass(brass_chord(bar), d * B, 0.7, seed=bar), t(bar, bt))
        elif name == "build":
            pad.add(O.brass(brass_chord(bar), B * 3.6, 0.45 + 0.15 * i, bright=1600.0 + 700.0 * i, scoop=0.4,
                            attack=0.6, seed=bar), t(bar))
            if i == 3:
                fx.add(O.slide_whistle(74, 98, B * 1.1, 0.7), t(bar, 2.75))
        elif name == "outro":
            brs.add(O.brass(brass_chord(bar), B * 0.3, 0.9, seed=bar), t(bar, 0))
            brs.add(O.brass(brass_chord(bar), B * 0.3, 0.8, seed=bar + 1), t(bar, 1.5))
            if i == 1:
                for bt in (2.5, 3.0, 3.5):
                    brs.add(O.brass(brass_chord(bar), B * 0.2, 0.85, seed=int(bt * 2)), t(bar, bt))
        # ---- section marks
        if i == 0 and name in ("A", "drop", "B"):
            fx.add(I.crash(0.6 if name == "drop" else 0.4, 2.0, seed=bar), t(bar), -4.0)
    # ---- button ending: big brass stab with a fall, kick + crash, bass root
    eb = s.sec("end").start_bar
    top = brass_chord(eb, oct_up=True)
    brs.add(O.brass(sorted(h.voiced[eb])[-4:], B * 1.2, 1.0, fall=0.0, seed=99), t(eb))
    brs.add(O.brass(top, B * 1.6, 0.9, fall=6.0, seed=98), t(eb))
    bass.add(O.slap_bass((h.roots[eb] - 40) % 12 + 40, B * 1.5, 1.0, "thumb"), t(eb))
    s.kick_at(kick, t(eb), I.kick(1.0, f_hi=170.0, f_lo=50.0, decay=0.4))
    snr.add(I.snare(1.0, 200.0, 0.2, seed=5), t(eb))
    fx.add(I.crash(0.8, 2.6, seed=eb), t(eb), -2.0)
    return s
