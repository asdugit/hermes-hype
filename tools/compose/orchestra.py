"""Acoustic-style and band instruments for the wave-3 beds (dream, pixel_boss, comic, ink).

Same conventions as ``instruments.py``: mono (n,) or stereo (2, n) float arrays, peak roughly <= 1 at vel=1,
MIDI note numbers, durations in seconds. Everything is additive/subtractive synthesis (no samples).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from . import dsp as D
from . import instruments as I
from .dsp import SR, mtof, ns

# ------------------------------------------------------------------------------- helpers

VOWELS: dict[str, list[tuple[float, float, float]]] = {    # (formant Hz, gain dB, Q) - soft mixed choir
    "ah": [(780.0, 0.0, 6.0), (1180.0, -5.0, 7.0), (2750.0, -14.0, 9.0), (3600.0, -20.0, 10.0)],
    "oh": [(470.0, 0.0, 6.0), (820.0, -6.0, 7.0), (2800.0, -18.0, 9.0), (3500.0, -24.0, 10.0)],
    "oo": [(340.0, 0.0, 6.0), (700.0, -10.0, 7.0), (2650.0, -22.0, 9.0), (3400.0, -28.0, 10.0)],
    "ee": [(320.0, 0.0, 6.0), (2300.0, -9.0, 9.0), (2950.0, -12.0, 9.0), (3700.0, -18.0, 10.0)],
}


def _drift(n: int, seed: object, rate: float = 3.0, cents: float = 6.0) -> np.ndarray:
    """Slow random pitch drift (semitones) - low-passed noise, so sustained voices never sound frozen."""
    w = D.lp(D.rng("drift", seed).standard_normal(n), rate, 2)
    s = np.std(w)
    return w / (s if s > 1e-9 else 1.0) * cents / 100.0


def _vibrato(n: int, rate: float, depth: float, delay: float, seed: object) -> np.ndarray:
    """Delayed vibrato curve in semitones with a random phase."""
    t = np.arange(n) / SR
    ph = D.rng("vib", seed).random() * 2 * np.pi
    ramp = np.clip((t - delay) / 0.4, 0.0, 1.0)
    return depth * ramp * np.sin(2 * np.pi * rate * t + ph)


def _crossfade_env(x: np.ndarray, lo: float, hi: float, env: np.ndarray) -> np.ndarray:
    """Filter-envelope stand-in: blend a dark (``lo`` Hz) and a bright (``hi`` Hz) low-passed copy by ``env``."""
    return D.lp(x, lo) * (1.0 - env) + D.lp(x, hi) * env


# ------------------------------------------------------------------------------- keys

def grand_piano(m: float, dur: float = 1.5, vel: float = 0.6, seed: int = 0, pedal: float = 0.0) -> np.ndarray:
    """Grand piano: stretched partials (inharmonicity), two-string unison beating, hammer-position comb,
    pitch-dependent two-stage decay, velocity-dependent brightness, felt-hammer knock. ``pedal`` adds ring
    (seconds) after the key is released."""
    f = float(mtof(m))
    t_base = float(np.clip(10.0 * 2.0 ** (-(m - 45) / 20.0), 1.4, 14.0))
    n = ns(min(dur + 0.6 + pedal, dur + t_base * 0.7))
    B = 0.00015 + 0.00045 * max(0.0, (m - 60) / 36.0) + 0.0004 * max(0.0, (40 - m) / 20.0)
    tilt = 1.85 - 0.75 * vel
    parts = []
    for k in range(1, 40):
        fk = k * np.sqrt(1.0 + B * k * k)
        if f * fk > 9000.0:
            break
        a = (1.0 / k ** tilt) * (0.25 + 0.75 * abs(np.sin(np.pi * k / 7.6)))
        t60 = t_base / (1.0 + 0.32 * (k - 1)) * (1.0 + 0.4 * (k == 1))
        parts.append((fk, a * 0.62, t60))
        parts.append((fk * (1.0 + 0.00045 + 0.0002 * (k % 3)), a * 0.38, t60 * 1.15))   # second string
    x = D.additive(f, n, parts, phase_seed=seed)
    # prompt sound -> aftersound: a fast early drop of ~5 dB, then the slow tail
    t = np.arange(n) / SR
    x *= 0.55 + 0.45 * np.exp(-t / 0.35)
    knock = D.lp(D.noise(n, ("hammer", m, seed)), 900.0 + 1800.0 * vel) * D.perc(n, 0.018, 0.0005) * 0.22 * vel
    x = x + knock
    gate = dur + pedal
    rel = np.ones(n)
    g0 = ns(gate)
    if g0 < n:
        rel[g0:] = np.exp(-(np.arange(n - g0) / SR) / 0.09)
    x *= rel
    x[: ns(0.002)] *= np.linspace(0, 1, ns(0.002))
    return x * vel * 0.32


# --------------------------------------------------------------------------- strings

def strings(chord: list[int], dur: float, vel: float = 0.5, attack: float = 0.6, release: float = 1.0,
            bright: float = 2600.0, voices: int = 3, seed: int = 0, swell: float = 0.0) -> np.ndarray:
    """Warm string-section pad (stereo): per note ``voices`` detuned saws with independent vibrato and drift,
    gentle body EQ, slow bow attack. ``swell`` > 0 adds a crescendo across the note (0..1)."""
    n = ns(dur + release)
    out = np.zeros((2, n))
    for i, m in enumerate(chord):
        for v in range(voices):
            key = (seed, i, v, m)
            off = (v - (voices - 1) / 2) * 0.07
            semi = m + off + _vibrato(n, 4.9 + 0.5 * D.rng("vr", key).random(), 0.11, 0.3, key) + _drift(n, key)
            osc = D.saw(mtof(semi), n, D.rng("ph", key).random())
            pan = ((v / max(voices - 1, 1)) * 2 - 1) * 0.65 * (1 if i % 2 else -1)
            out += D.stereo(osc, pan) * (0.8 if v == voices // 2 else 0.65)
    out = D.lp(out, bright, 2)
    out = D.eq(out, "peak", 420.0, 2.5, 1.0)
    out = D.eq(out, "peak", 1250.0, -2.0, 1.2)
    out = D.eq(out, "peak", 2900.0, 1.5, 1.4)
    env = D.adsr(n, attack, 0.6, 0.9, release, gate=dur, curve=3.0)
    if swell > 0:
        t = np.arange(n) / SR
        env *= 1.0 - swell + swell * np.clip(t / max(dur, 1e-3), 0, 1) ** 1.5
    return out * env[None, :] * vel / np.sqrt(len(chord) * voices) * 0.55


def violin_line(m: float, dur: float, vel: float = 0.6, attack: float = 0.12, seed: int = 0) -> np.ndarray:
    """Unison violin section for melodies (stereo): five drifting saws, expressive mid-note swell."""
    n = ns(dur + 0.45)
    t = np.arange(n) / SR
    out = np.zeros((2, n))
    for v in range(5):
        key = (seed, v, m)
        semi = (m + (v - 2) * 0.05 + _vibrato(n, 5.4 + 0.4 * D.rng("vr", key).random(), 0.16, 0.18, key)
                + _drift(n, key, 4.0, 5.0))
        out += D.stereo(D.saw(mtof(semi), n, D.rng("ph", key).random()), (v - 2) * 0.25)
    out = D.lp(out, 3800.0, 2)
    out = D.eq(out, "peak", 520.0, 2.0, 1.0)
    out = D.eq(out, "peak", 3100.0, 2.0, 1.5)
    env = D.adsr(n, attack, 0.4, 0.85, 0.35, gate=dur, curve=3.0)
    env *= 0.85 + 0.15 * np.sin(np.pi * np.clip(t / max(dur, 1e-3), 0, 1))
    return out * env[None, :] * vel * 0.16


# ----------------------------------------------------------------------------- choir

def choir(chord: list[int], dur: float, vel: float = 0.5, vowel: str = "ah", attack: float = 0.9,
          release: float = 1.4, breath: float = 0.25, seed: int = 0) -> np.ndarray:
    """Soft choir / air pad (stereo): drifting saw+pulse voices through a parallel formant bank, plus breath
    noise through the same formants."""
    n = ns(dur + release)
    src = np.zeros((2, n))
    for i, m in enumerate(chord):
        for v in range(4):
            key = (seed, i, v, m, "ch")
            semi = m + (v - 1.5) * 0.09 + _vibrato(n, 5.1, 0.13, 0.35, key) + _drift(n, key, 2.5, 7.0)
            fr = mtof(semi)
            osc = D.saw(fr, n, D.rng("ph", key).random()) * 0.7 + D.pulse(fr, n, 0.3, D.rng("pp", key).random()) * 0.3
            src += D.stereo(osc, ((v % 2) * 2 - 1) * 0.55)
    nz = np.vstack([D.noise(n, ("breath", seed, c)) for c in range(2)]) * breath * np.sqrt(len(chord))
    src = src + nz
    out = np.zeros_like(src)
    for fq, g, q in VOWELS[vowel]:
        out += signal.sosfilt(D._rbj("bp", fq, q), src, axis=-1) * D.db(g)
    out = D.hp(out, 140.0)
    env = D.adsr(n, attack, 0.8, 0.9, release, gate=dur, curve=3.0)
    return out * env[None, :] * vel / np.sqrt(len(chord) * 4) * 1.6


# ----------------------------------------------------------------------- mallets/bells

def glock(m: float, vel: float = 0.6, decay: float = 1.8, seed: int = 0) -> np.ndarray:
    """Glockenspiel bar (free-free bar partials 1 : 2.76 : 5.40 : 8.93) with a hard-mallet tick."""
    f = float(mtof(m))
    n = ns(decay * 1.05)
    x = D.additive(f, n, [(1.0, 1.0, decay), (2.76, 0.28 * vel, decay * 0.35), (5.40, 0.12 * vel, decay * 0.14),
                          (8.93, 0.05 * vel, decay * 0.06)], phase_seed=seed)
    x += D.bp(D.noise(n, ("glk", seed, m)), 2500.0, 9000.0) * D.perc(n, 0.004) * 0.35 * vel
    return x * vel * 0.55


def celesta(m: float, vel: float = 0.6, decay: float = 1.4, seed: int = 0) -> np.ndarray:
    """Celesta: near-harmonic, sweet, soft attack."""
    f = float(mtof(m))
    n = ns(decay * 1.05)
    x = D.additive(f, n, [(1.0, 1.0, decay), (2.0, 0.22, decay * 0.5), (3.0, 0.08, decay * 0.25),
                          (4.02, 0.05, decay * 0.15)], phase_seed=seed)
    x *= np.clip(np.arange(n) / ns(0.004), 0, 1)
    return x * vel * 0.6


def chime_tree(dur: float = 1.2, notes: list[int] | None = None, up: bool = False, seed: int = 0) -> np.ndarray:
    """Wind-chime / mark-tree run (stereo): many tiny bells across ``dur`` (descending by default)."""
    notes = notes or [96, 94, 91, 89, 86, 84, 82, 79, 77, 74]
    seq = list(reversed(notes)) if up else notes
    out = np.zeros((2, ns(dur + 2.2)))
    r = D.rng("tree", seed)
    for k, m in enumerate(seq):
        tt = dur * (k / max(len(seq) - 1, 1)) ** 1.15 + r.random() * 0.012
        b = D.additive(float(mtof(m)), ns(2.0), [(1.0, 1.0, 1.8), (2.76, 0.3, 0.6), (5.4, 0.1, 0.25)], phase_seed=k)
        pan = np.sin(k * 1.7) * 0.7
        D.place(out, D.stereo(b * (0.35 + 0.25 * r.random()), pan), ns(tt))
    return out * 0.6


def harp(m: float, vel: float = 0.6, decay: float | None = None, seed: int = 0) -> np.ndarray:
    """Concert-harp pluck (gut string): plucked-near-centre partials, round attack."""
    f = float(mtof(m))
    dec = decay or float(np.clip(3.2 * 2.0 ** (-(m - 55) / 24.0), 0.8, 4.0))
    n = ns(dec * 1.1)
    parts = [(k, (1.0 / k ** 1.4) * (0.3 + 0.7 * abs(np.sin(np.pi * k * 0.42))), dec / (1.0 + 0.6 * (k - 1)))
             for k in range(1, 16) if f * k < 9000.0]
    x = D.additive(f, n, parts, phase_seed=seed)
    x *= np.clip(np.arange(n) / ns(0.003), 0, 1)
    x += D.bp(D.noise(n, ("harp", m, seed)), 800.0, 4000.0) * D.perc(n, 0.006) * 0.08
    return x * vel * 0.55


def cymbal_swell(dur: float, seed: int = 0) -> np.ndarray:
    """Suspended-cymbal roll crescendo that peaks at ``dur`` and rings briefly (stereo)."""
    n = ns(dur + 0.9)
    t = np.arange(n) / SR
    rise = np.clip(t / dur, 0, 1) ** 2.4
    tail = np.where(t > dur, np.exp(-(t - dur) / 0.35), 1.0)
    out = []
    for c in range(2):
        m = np.zeros(n)
        for fq in (342.0, 467.0, 631.0, 789.0, 1011.0, 1373.0):
            m += np.sign(D.sine(fq * (1 + 0.01 * c), n, phase0=0.21 * c + fq / 997.0))
        x = D.hp(m * 0.05 + D.noise(n, ("cswell", seed, c)), 3200.0, 2)
        x = D.lp(x, 11000.0)
        out.append(x * rise * tail)
    return np.vstack(out) * 0.5


def soft_timp(freq: float = 65.0, vel: float = 0.6) -> np.ndarray:
    """Soft timpani / low floor tom with a felt mallet (round, phone-audible 2nd mode)."""
    n = ns(1.4)
    t = np.arange(n) / SR
    f = freq * (1.0 + 0.05 * np.exp(-t / 0.08))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * D.perc(n, 1.2, 0.004)
    x += np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * D.perc(n, 0.6, 0.004) * 0.35
    x += np.sin(2 * np.pi * np.cumsum(f * 2.0) / SR) * D.perc(n, 0.4, 0.004) * 0.2
    x += D.lp(D.noise(n, ("timp", freq)), 600.0) * D.perc(n, 0.03) * 0.3
    return x * vel * 0.7


# ------------------------------------------------------------------------------- brass

def brass(chord: list[int], dur: float, vel: float = 0.8, bright: float = 3400.0, scoop: float = 0.6,
          fall: float = 0.0, seed: int = 0, attack: float = 0.018) -> np.ndarray:
    """Synth brass section (stereo): detuned saws with a pitch scoop, a filter 'blat' that opens on the attack,
    brass formant EQ and optional cartoon fall-off (``fall`` semitones over the last 0.18 s)."""
    n = ns(dur + 0.14)
    t = np.arange(n) / SR
    out = np.zeros((2, n))
    for i, m in enumerate(chord):
        for v in range(3):
            key = (seed, i, v, m, "br")
            semi = m + (v - 1) * 0.06 - scoop * np.exp(-t / 0.035) + _drift(n, key, 3.0, 4.0)
            if dur > 0.45:
                semi = semi + _vibrato(n, 5.6, 0.12, 0.25, key)
            if fall:
                semi = semi - fall * np.clip((t - (dur - 0.18)) / 0.18, 0, 1) ** 2
            osc = D.saw(mtof(semi), n, D.rng("ph", key).random())
            out += D.stereo(osc, (v - 1) * 0.35 + (0.15 if i % 2 else -0.15))
    lo_c = float(mtof(min(chord))) * 1.6
    blat = np.clip(t / 0.03, 0, 1) * (0.55 + 0.45 * np.exp(-np.maximum(t - 0.03, 0) / 0.12))
    out = _crossfade_env(out, lo_c, bright * (0.6 + 0.4 * vel), blat[None, :] * vel ** 0.5)
    out = D.eq(out, "peak", 1150.0, 4.0, 1.1)
    out = D.eq(out, "peak", 2600.0, 2.0, 1.6)
    out = D.drive(out * 0.9, 1.4)
    env = D.adsr(n, attack, 0.18, 0.78, 0.07, gate=dur, curve=3.0)
    if fall:
        env *= np.clip((dur + 0.02 - t) / 0.2, 0, 1) ** 0.7
    return out * env[None, :] * vel / np.sqrt(len(chord) * 3) * 0.7


def slap_bass(m: float, dur: float, vel: float = 0.9, kind: str = "thumb", seed: int = 0) -> np.ndarray:
    """Slap bass: ``thumb`` (bright slap transient + round body), ``pop`` (snappy pulled string, higher),
    ``ghost`` (muted dead note: percussive thump only)."""
    n = ns(dur + 0.06)
    if kind == "ghost":
        x = D.lp(D.noise(n, ("ghost", seed, m)), 700.0) * D.perc(n, 0.035, 0.001) * 1.2
        x += D.bp(D.noise(n, ("gk", seed)), 1500.0, 5000.0) * D.perc(n, 0.006) * 0.4
        return x * vel * 0.45
    f = float(mtof(m))
    snap = 0.03 if kind == "thumb" else 0.022
    parts = []
    for k in range(1, 30):
        if f * k > 7000.0:
            break
        a = 1.0 / k ** (0.85 if kind == "thumb" else 0.7)
        parts.append((k * (1 + 0.0002 * k * k), a, 0.9 / (1.0 + 0.45 * k)))
        parts.append((k * (1 + 0.0002 * k * k), a * (1.4 if kind == "pop" else 1.0) * (k > 3), snap))
    x = D.additive(f, n, parts, phase_seed=seed)
    x += D.sine(f, n) * 0.5 * D.perc(n, 1.2, 0.003)
    click = D.bp(D.noise(n, ("slap", seed, m, kind)), 2000.0, 7000.0) * D.perc(n, 0.004, 0.0003)
    x += click * (0.5 if kind == "thumb" else 0.8)
    x *= D.adsr(n, 0.001, 0.25, 0.75, 0.035, gate=dur)
    return D.drive(x * 0.8, 1.6) * vel * 0.55


def clav(m: float, dur: float, vel: float = 0.7, seed: int = 0) -> np.ndarray:
    """Funk clavinet: narrow pulse, bright pluck envelope, quick damp."""
    f = float(mtof(m))
    n = ns(dur + 0.05)
    t = np.arange(n) / SR
    x = D.pulse(f, n, 0.22) * 0.7 + D.saw(f * 1.002, n, 0.3) * 0.3
    env_b = np.exp(-t / 0.05)
    x = _crossfade_env(x, 1400.0, 6500.0, env_b)
    x = D.hp(x, 180.0)
    x = D.eq(x, "peak", 1800.0, 4.0, 2.0)
    x *= D.adsr(n, 0.001, 0.12, 0.45, 0.02, gate=dur)
    return x * vel * 0.28


# ------------------------------------------------------------------------- plucked

def ukulele(m: float, vel: float = 0.6, decay: float = 1.1, seed: int = 0) -> np.ndarray:
    """Nylon-string ukulele pluck: plucked-at-1/5 partials, body resonances, soft finger transient."""
    f = float(mtof(m))
    n = ns(decay * 1.1)
    parts = [(k * (1 + 0.00008 * k * k), (1.0 / k ** 1.05) * (0.2 + 0.8 * abs(np.sin(np.pi * k * 0.19))),
              decay / (1.0 + 0.42 * (k - 1))) for k in range(1, 22) if f * k < 9500.0]
    x = D.additive(f, n, parts, phase_seed=seed)
    x = D.eq(x, "peak", 430.0, 3.5, 1.4)
    x = D.eq(x, "peak", 2300.0, 2.0, 1.8)
    x += D.bp(D.noise(n, ("uke", seed, m)), 1500.0, 6000.0) * D.perc(n, 0.004, 0.0003) * 0.18
    x *= np.clip(np.arange(n) / ns(0.0015), 0, 1)
    return x * vel * 0.42


def strum(chord: list[int], vel: float = 0.6, down: bool = True, spread: float = 0.012, decay: float = 1.0,
          mute: float = 0.0, seed: int = 0) -> np.ndarray:
    """Strummed chord (stereo): strings staggered by ``spread`` s (down = low->high); ``mute`` s damps it."""
    notes = sorted(chord) if down else sorted(chord, reverse=True)
    n = ns(decay * 1.1 + spread * len(notes))
    out = np.zeros(n)
    for k, mm in enumerate(notes):
        v = vel * (1.0 - 0.06 * k if down else 0.8 + 0.05 * k)
        D.place(out, ukulele(mm, v, decay, seed=seed * 7 + k), ns(k * spread))
    if mute > 0:
        g0 = ns(mute)
        if g0 < n:
            out[g0:] *= np.exp(-np.arange(n - g0) / SR / 0.03)
    return D.stereo(out, 0.12 if down else -0.12) * 0.75


def pizz(m: float, vel: float = 0.6, decay: float | None = None, seed: int = 0) -> np.ndarray:
    """Pizzicato string: short, round pluck with body resonances and a tiny upward pitch flick on the attack."""
    f = float(mtof(m))
    dec = decay or float(np.clip(0.75 * 2.0 ** (-(m - 50) / 30.0), 0.25, 0.9))
    n = ns(dec * 1.2)
    t = np.arange(n) / SR
    fc = f * (1.0 + 0.012 * np.exp(-t / 0.02))
    ph = np.cumsum(fc) / SR
    x = np.zeros(n)
    for k in range(1, 14):
        if f * k > 7000.0:
            break
        x += (1.0 / k ** 1.25) * np.sin(2 * np.pi * k * ph + k) * np.exp(-6.91 * t / (dec / (1 + 0.55 * (k - 1))))
    x = D.eq(x, "peak", 290.0, 3.0, 1.2)
    x = D.eq(x, "peak", 1050.0, 2.0, 1.5)
    x += D.lp(D.noise(n, ("pz", seed, m)), 1500.0) * D.perc(n, 0.008) * 0.12
    x *= np.clip(t / 0.002, 0, 1)
    return x * vel * 0.6


def kalimba(m: float, vel: float = 0.6, decay: float = 1.6, seed: int = 0) -> np.ndarray:
    """Kalimba tine: fundamental + inharmonic overtone near 5.9x, gentle thumb attack."""
    f = float(mtof(m))
    n = ns(decay * 1.05)
    x = D.additive(f, n, [(1.0, 1.0, decay), (5.93, 0.22 * vel, decay * 0.18), (2.0, 0.06, decay * 0.4)],
                   phase_seed=seed)
    x += D.bp(D.noise(n, ("kal", seed, m)), 600.0, 3000.0) * D.perc(n, 0.005) * 0.15
    x *= np.clip(np.arange(n) / ns(0.002), 0, 1)
    return x * vel * 0.55


# --------------------------------------------------------------------------- percussion

def tambourine(vel: float = 0.6, seed: int = 0, long: bool = False) -> np.ndarray:
    """Tambourine hit: jingle partials + bright noise, shaken envelope."""
    dur = 0.32 if long else 0.14
    n = ns(dur)
    m = np.zeros(n)
    for fq in (5150.0, 6420.0, 7330.0, 8710.0, 9890.0):
        m += D.sine(fq * (1 + 0.004 * seed), n, phase0=fq / 3000.0)
    x = m * 0.2 + D.hp(D.noise(n, ("tamb", seed)), 6000.0) * 0.9
    env = D.perc(n, dur, 0.002) * (1.0 + 0.4 * np.sin(np.linspace(0, 9 * np.pi, n)) * long)
    return x * env * vel * 0.5


def snap(vel: float = 0.7, seed: int = 0) -> np.ndarray:
    """Finger snap: sharp band-passed burst with a short 2.2 kHz ring."""
    n = ns(0.09)
    x = D.bp(D.noise(n, ("snap", seed)), 1400.0, 5200.0) * D.perc(n, 0.018, 0.0003) * 2.2
    x += D.sine(2200.0 + 90 * (seed % 3), n) * D.perc(n, 0.025) * 0.25
    return x * vel * 0.7


def woodblock(freq: float = 900.0, vel: float = 0.6) -> np.ndarray:
    n = ns(0.12)
    x = D.sine(freq, n) * D.perc(n, 0.06) + D.sine(freq * 2.43, n) * D.perc(n, 0.02) * 0.4
    x += D.hp(D.noise(n, ("wb", freq)), 3000.0) * D.perc(n, 0.003) * 0.4
    return x * vel * 0.6


def conga(freq: float = 220.0, vel: float = 0.6, slap_: bool = False, seed: int = 0) -> np.ndarray:
    """Hand drum (conga/bongo): pitched skin + palm slap noise."""
    n = ns(0.35)
    t = np.arange(n) / SR
    f = freq * (1.0 + 0.12 * np.exp(-t / 0.015))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * D.perc(n, 0.22 if not slap_ else 0.1, 0.001)
    x += D.bp(D.noise(n, ("conga", seed, freq)), 900.0, 4500.0) * D.perc(n, 0.02 if not slap_ else 0.05) * (0.3 + 0.6 * slap_)
    return x * vel * 0.7


def brush(vel: float = 0.5, seed: int = 0, sweep: bool = False) -> np.ndarray:
    """Brush on snare: a short tap or a longer sweep (filtered noise)."""
    dur = 0.32 if sweep else 0.12
    n = ns(dur)
    t = np.arange(n) / SR
    x = D.bp(D.noise(n, ("brush", seed)), 2200.0, 9000.0)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** (2.0 if sweep else 0.5) if sweep else D.perc(n, 0.1, 0.004)
    x += D.sine(190.0, n) * D.perc(n, 0.05) * (0 if sweep else 0.3)
    return x * env * vel * 0.8


def soft_kick(vel: float = 0.8) -> np.ndarray:
    """Felt/acoustic kick for gentle beds: round body, knock for phones, little click."""
    return I.kick(vel, f_hi=110.0, f_lo=50.0, tau=0.03, decay=0.35, click=0.08, knock=0.3, drive=1.2)


def slide_whistle(m0: float, m1: float, dur: float, vel: float = 0.5) -> np.ndarray:
    """Slide whistle glide (cartoon): sine with breath noise, exponential glide m0 -> m1."""
    n = ns(dur + 0.05)
    t = np.arange(n) / SR
    p = np.clip(t / dur, 0, 1)
    semi = m0 + (m1 - m0) * (1 - (1 - p) ** 2) + 0.15 * np.sin(2 * np.pi * 6.0 * t)
    x = D.sine(mtof(semi), n) + D.bp(D.noise(n, ("whistle", m0)), 1500.0, 6000.0) * 0.05
    x *= np.clip(t / 0.03, 0, 1) * np.clip((dur + 0.05 - t) / 0.06, 0, 1)
    return x * vel * 0.4
