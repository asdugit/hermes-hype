"""Launch beds: confident, premium synth-pop / house for a product-launch film (118-128 BPM)."""
from __future__ import annotations

from typing import Any

from .. import dsp as D
from .. import instruments as I
from ..song import Song
from ..theory import Key
from .common import GROOVE_LAYOUT, Harmony, phrase

VARIANTS: dict[str, dict[str, Any]] = {
    "a": dict(bpm=124, tonic="D", mode="major", label="D major",
              prog=[(6, "7"), (4, "7"), (1, "add9"), (5, "sus4")],
              prog_b=[(4, "7"), (5, "triad"), (6, "7"), (1, "add9")],
              end=(1, "add9"), stabs="saw", arp=[0, 1, 2, 3, 2, 1, 2, 3],
              title="Keynote", notes="Progressive-house launch bed: pumping pads, dotted-8th pluck arp, "
                                     "supersaw stabs and a pluck-lead hook in the drop."),
    "b": dict(bpm=120, tonic="E", mode="minor", label="E minor",
              prog=[(6, "7"), (7, "triad"), (1, "9"), (3, "add9")],
              prog_b=[(4, "7"), (6, "7"), (7, "sus4"), (1, "9")],
              end=(6, "7"), stabs="organ", arp=[0, 1, 2, 3, 0, 1, 2, 3],
              title="Release Day", notes="Synth-pop house bed: organ stabs, rolling bass, bell-pluck hook."),
}

LEAD_A = [(0, 0.75, 0), (0.75, 0.75, 3), (1.5, 1.0, 5), (2.5, 0.5, 3), (3.0, 1.0, 0)]
LEAD_B = [(0, 0.75, -2), (0.75, 0.75, 0), (1.5, 2.5, -4)]
LEAD_A2 = [(0, 0.5, 0), (0.5, 0.5, 2), (1.0, 0.5, 4), (1.5, 1.0, 7), (2.5, 1.5, 5)]
LEAD_B2 = [(0, 1.0, 4), (1.0, 1.0, 2), (2.0, 2.0, 0)]
BELL = [(0, 1.5, 7), (1.5, 1.0, 4), (3.0, 1.0, 2)]


def compose(v: str) -> Song:
    """Build the Launch bed variant ``v`` ('a' or 'b')."""
    P = VARIANTS[v]
    s = Song(f"launch_{v}", "launch", P["bpm"], P["label"], GROOVE_LAYOUT, tail_s=4.5,
             title=P["title"], notes=P["notes"])
    key = Key(P["tonic"], P["mode"])
    h = Harmony(s, key, {"B": P["prog_b"]}, P["prog"], end_chord=P["end"])
    r = D.rng("launch", v)
    T, t, B = s.track, s.t, s.beat
    kick = T("kick", gain_db=-6.5)
    clap = T("clap", gain_db=-10.0, reverb=0.22)
    hat = T("hat", gain_db=-19.0, pan=0.18)
    ohat = T("ohat", gain_db=-19.0, pan=-0.15)
    shk = T("shaker", gain_db=-23.0, pan=0.3)
    bass = T("bass", gain_db=-12.0, pump=0.3, hp=35.0)
    pad = T("pad", gain_db=-11.0, pump=0.5, reverb=0.35, width=1.45,
            sweep=[(0, 1100.0), (t(4), 3200.0), (t(12), 3200.0), (t(15.8), 12000.0), (t(40), 12000.0)])
    stb = T("stab", gain_db=-10.0, pump=0.35, reverb=0.22, delay=0.12, width=1.3)
    arp = T("arp", gain_db=-10.0, pump=0.2, delay=0.32, reverb=0.25, hp=200.0, width=1.3)
    led = T("lead", gain_db=-8.0, delay=0.22, reverb=0.3)
    bel = T("bell", gain_db=-14.0, reverb=0.45, delay=0.15, pan=0.2)
    fx = T("fx", gain_db=-8.0)

    def roll(bar: int, start: float, end: float, step: float, v0: float, v1: float) -> None:
        k, bt = 0, start
        while bt < end - 1e-6:
            frac = (bt - start) / max(end - start, 1e-6)
            clap.add(I.snare(v0 + (v1 - v0) * frac, 200.0, 0.12, seed=k), t(bar, bt), -3.0)
            bt += step; k += 1

    for bar, sec, i in s.bars():
        ch = h.voiced[bar]
        root = h.roots[bar]
        name = sec.name
        # ------------------------------------------------------------- pads
        if name != "end":
            pv = {"intro": 0.5, "A": 0.42, "build": 0.5, "drop": 0.45, "B": 0.42, "outro": 0.45}[name]
            cut = {"intro": 1600.0, "A": 2200.0, "build": 2600.0, "drop": 3600.0, "B": 2600.0, "outro": 1800.0}[name]
            pad.add(I.saw_pad(ch, s.bar, pv, attack=0.35 if bar == 0 else 0.04, release=0.5, cutoff=cut, seed=bar), t(bar))
        # ------------------------------------------------------------ drums
        if name in ("A", "build", "drop", "B") or (name == "outro" and i == 0):
            last_build = name == "build" and i == 3
            for b in range(4):
                if last_build:
                    break
                s.kick_at(kick, t(bar, b), I.kick(0.95 if name in ("drop", "B") else 0.85))
            if name in ("drop", "B") or (name == "A" and i >= 4):
                for b in (1, 3):
                    clap.add(I.clap(0.9, seed=bar * 4 + b), t(bar, b))
            if name in ("A", "B", "build", "outro"):
                for k in range(16):
                    acc = (0.9, 0.35, 0.6, 0.35)[k % 4]
                    hat.add(I.hat(acc * (0.8 + 0.2 * r.random()), seed=k % 5), t(bar, k / 4) + (r.random() - 0.5) * 0.004)
            if name in ("drop", "B"):
                for b in range(4):
                    ohat.add(I.hat(0.75, open_=True, seed=b), t(bar, b + 0.5))
                for k in range(16):
                    shk.add(I.shaker((0.7, 0.3, 0.5, 0.3)[k % 4], seed=k % 7), t(bar, k / 4) + (r.random() - 0.5) * 0.005)
        if name == "intro" and i >= 2:
            for k in range(8):
                shk.add(I.shaker(0.25 + 0.1 * (k % 2), seed=k), t(bar, k / 2))
        # ------------------------------------------------------------- bass
        if name == "A":
            bass.add(I.bass(root, 2 * B - 0.05, 0.75, cutoff=380.0), t(bar))
            bass.add(I.bass(root, 2 * B - 0.05, 0.7, cutoff=380.0), t(bar, 2))
        elif name == "build":
            stop = 3.5 if i == 3 else 4.0
            bt = 0.0
            while bt < stop:
                bass.add(I.bass(root, B * 0.45, 0.8, cutoff=420.0 + 160 * i), t(bar, bt))
                bt += 0.5
        elif name in ("drop", "B") or (name == "outro" and i == 0):
            if P["stabs"] == "saw":
                pat = [(0.5, 0), (1.5, 0), (2.5, 0), (3.25, 12), (3.5, 0)]
            else:
                pat = [(0.0, 0), (0.5, 0), (1.0, 12), (1.5, 0), (2.0, 0), (2.5, 0), (3.0, 12), (3.5, 0)]
            for bt, oc in pat:
                bass.add(I.bass(root + oc, B * 0.42, 0.9, cutoff=650.0 if oc else 520.0, env_t=0.05), t(bar, bt))
        # ------------------------------------------------------------ stabs
        if name in ("drop", "B"):
            stab_ch = [m + 12 for m in ch] if P["stabs"] == "saw" else ch
            pat = [(0.0, 0.35), (0.75, 0.25), (1.5, 0.35), (2.5, 0.25), (3.0, 0.4)] if name == "drop" else \
                  [(0.75, 0.25), (1.5, 0.3), (2.5, 0.25), (3.5, 0.25)]
            for bt, d in pat:
                if P["stabs"] == "saw":
                    stb.add(I.stab(stab_ch, d * B * 1.6, 0.8, seed=bar), t(bar, bt))
                else:
                    for m in stab_ch:
                        stb.add(I.organ(m + 12, d * B * 1.6, 0.8), t(bar, bt))
        # -------------------------------------------------------------- arp
        if name in ("intro", "A", "build", "B", "outro") and not (name == "intro" and i < 1):
            tones = sorted(ch)[:4] + [sorted(ch)[0] + 12]
            tones = [m + 12 for m in tones]
            bright = {"intro": 0.5, "A": 0.9, "build": 0.9 + 0.5 * i, "B": 1.4, "outro": 0.8}[name]
            vel0 = {"intro": 0.4 + 0.08 * i, "outro": 0.5}.get(name, 0.7)
            steps = 14 if name == "build" and i == 3 else 16
            for k in range(steps):
                m = tones[P["arp"][k % 8] % len(tones)]
                acc = 1.0 if k % 4 == 0 else (0.8 if k % 2 == 0 else 0.65)
                arp.add(I.pluck(m, B * 0.22, vel0 * acc, bright=bright, decay=0.35, seed=k), t(bar, k / 4))
        # ------------------------------------------------------------- lead
        center = key.degree(3, 5) if P["mode"] == "major" else key.degree(5, 4)
        if name == "drop" or (name == "B" and i >= 4):
            j = i % 8 if name == "drop" else i - 4
            rh = [LEAD_A, LEAD_B, LEAD_A, LEAD_B, LEAD_A, LEAD_B, LEAD_A2, LEAD_B2][j if name == "drop" else j + 4]
            for bt, d, m in phrase(h, bar, rh, center - (12 if name == "B" and P["mode"] == "major" else 0)):
                led.add(D.mix((I.pluck(m, d * B, 0.85, bright=1.6, decay=1.3, seed=bar), 1.0),
                              (I.lead(m, d * B * 0.95, 0.6, cutoff=2600.0, vib=0.12), 0.45)), t(bar, bt))
        if (name == "A" and i >= 4) or (name == "B" and i < 4):
            for bt, _d, m in phrase(h, bar, BELL, center + 12, span=7):
                bel.add(I.bell(m, 0.5, 1.6, seed=bar), t(bar, bt))
        # --------------------------------------------------------- transitions
        if name == "build" and i == 0:
            fx.add(I.riser(4 * s.bar, seed=1, tonal=key.degree(1, 3)), t(bar), -2.0)
        if name == "build":
            if i < 2:
                roll(bar, 0.0, 4.0, 1.0, 0.25 + 0.1 * i, 0.4)
            elif i == 2:
                roll(bar, 0.0, 4.0, 0.5, 0.35, 0.6)
            else:
                roll(bar, 0.0, 2.0, 0.25, 0.5, 0.75)
                roll(bar, 2.0, 3.5, 0.125, 0.75, 1.0)
        if name in ("A", "drop", "outro", "end") and i == 0:
            fx.add(I.crash(0.8 if name == "drop" else 0.5, 2.4, seed=bar), t(bar), -2.0)
        if name == "drop" and i == 0:
            fx.add(I.boom(0.9, 55.0, 1.6), t(bar), -3.0)
        if name in ("A", "outro") and i == 0:
            fx.add(I.reverse_swell(s.bar * 0.75, seed=bar), t(bar) - s.bar * 0.75, -6.0)
        if name == "B" and i == 7:
            roll(bar, 2.0, 4.0, 0.25, 0.35, 0.7)
    # ---------------------------------------------------------------- ending
    eb = s.sec("end").start_bar
    ch = h.voiced[eb]
    pad.add(I.saw_pad(ch, s.bar * 0.6, 0.55, attack=0.01, release=3.2, cutoff=2600.0, seed=99), t(eb))
    for k, m in enumerate(sorted(ch)):
        arp.add(I.pluck(m + 12, 0.6, 0.6, bright=1.2, decay=2.4, seed=k), t(eb) + k * 0.012)
    bel.add(I.bell(key.degree(1, 6), 0.6, 3.5), t(eb), 2.0)
    bass.add(I.bass(h.roots[eb], 1.6, 0.7, cutoff=300.0), t(eb))
    s.kick_at(kick, t(eb), I.kick(0.8))
    return s
