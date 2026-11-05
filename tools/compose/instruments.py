"""Original synthesized instruments and drums for the composer.

Each function returns a mono (n,) or stereo (2, n) float array, peak roughly <= 1 at vel=1.
Tonal voices take MIDI note numbers; durations are in seconds.
"""
from __future__ import annotations

import numpy as np

from . import dsp as D
from .dsp import SR, mtof, ns


def _vib(f: float, n: int, depth: float = 0.0, rate: float = 5.5, delay: float = 0.25) -> np.ndarray:
    """Frequency curve with delayed vibrato (depth in semitones)."""
    if depth <= 0:
        return np.full(n, f)
    t = np.arange(n) / SR
    ramp_in = np.clip((t - delay) / 0.35, 0.0, 1.0)
    return f * 2.0 ** (depth * ramp_in * np.sin(2 * np.pi * rate * t) / 12.0)


def _bright_dark(x: np.ndarray, hi: float, lo: float, t_env: float) -> np.ndarray:
    """Cheap filter envelope: crossfade a bright copy into a dark copy over ``t_env`` seconds."""
    n = x.shape[-1]
    e = np.exp(-np.arange(n) / SR / max(t_env, 1e-3))
    return D.lp(x, hi) * e + D.lp(x, lo) * (1.0 - e)


# ------------------------------------------------------------------------------- drums

def kick(vel: float = 1.0, f_hi: float = 150.0, f_lo: float = 47.0, tau: float = 0.035, decay: float = 0.42,
         click: float = 0.35, knock: float = 0.25, drive: float = 1.6) -> np.ndarray:
    """Synth kick: swept sine body + noise click + a 180-220 Hz knock so phones hear it."""
    n = ns(decay + 0.05)
    t = np.arange(n) / SR
    f = f_lo + (f_hi - f_lo) * np.exp(-t / tau)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * D.perc(n, decay, 0.0008)
    k = D.sine(205.0, n) * D.perc(n, 0.07) * knock
    c = D.hp(D.noise(n, "kc"), 2500.0) * D.perc(n, 0.012) * click
    return D.drive(body + k + c, drive) * vel * 0.9


def snare(vel: float = 1.0, tone: float = 190.0, decay: float = 0.2, snappy: float = 0.8, seed: int = 0) -> np.ndarray:
    n = ns(decay + 0.1)
    t = np.arange(n) / SR
    body = (D.sine(tone * (1 + 0.5 * np.exp(-t / 0.01)), n) + 0.5 * D.sine(tone * 1.6, n)) * D.perc(n, 0.09)
    nz = D.bp(D.noise(n, ("sn", seed)), 1200.0, 9000.0) * D.perc(n, decay, 0.0005) * snappy * 2.2
    return D.drive(body * 0.7 + nz, 1.3) * vel * 0.8


def clap(vel: float = 1.0, seed: int = 0, tail: float = 0.18) -> np.ndarray:
    n = ns(tail + 0.08)
    base = D.bp(D.noise(n, ("cl", seed)), 900.0, 4200.0) * 2.5
    env = np.zeros(n)
    for k, off in enumerate((0.0, 0.009, 0.019, 0.028)):
        s = ns(off)
        m = n - s
        g = 1.0 if k < 3 else 0.9
        env[s:] = np.maximum(env[s:], g * D.perc(m, 0.03 if k < 3 else tail))
    return base * env * vel * 0.8


def hat(vel: float = 0.7, open_: bool = False, seed: int = 0, tone: float = 1.0) -> np.ndarray:
    """808-style metallic hat (six detuned squares + noise, high-passed)."""
    dur = 0.35 if open_ else 0.06
    n = ns(dur + 0.02)
    m = np.zeros(n)
    for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0):
        m += np.sign(D.sine(f * 1.7 * tone, n, phase0=(f * 13.0) % 1.0))
    x = D.hp(m * 0.15 + D.noise(n, ("hh", seed)) * 0.9, 7000.0, 4)
    return x * D.perc(n, dur, 0.0005) * vel


def shaker(vel: float = 0.5, seed: int = 0) -> np.ndarray:
    n = ns(0.09)
    x = D.bp(D.noise(n, ("sh", seed)), 4500.0, 12000.0)
    e = np.sin(np.linspace(0, np.pi, n)) ** 3
    return x * e * vel * 1.6


def crash(vel: float = 0.8, decay: float = 2.2, seed: int = 0) -> np.ndarray:
    """Crash cymbal -> stereo."""
    n = ns(decay + 0.2)
    out = []
    for c in range(2):
        m = np.zeros(n)
        for f in (311.0, 437.0, 593.0, 711.0, 829.0, 1063.0):
            m += np.sign(D.sine(f * (1.0 + 0.013 * c), n, phase0=0.37 * c))
        x = D.hp(m * 0.08 + D.noise(n, ("cr", seed, c)), 3500.0, 2)
        out.append(x * D.perc(n, decay, 0.001) * (0.6 + 0.4 * D.perc(n, 0.25)))
    return np.vstack(out) * vel * 0.55


def tom(freq: float = 110.0, vel: float = 0.9, decay: float = 0.5) -> np.ndarray:
    n = ns(decay + 0.05)
    t = np.arange(n) / SR
    f = freq * (1.0 + 0.6 * np.exp(-t / 0.03))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * D.perc(n, decay)
    x += D.bp(D.noise(n, ("tom", freq)), 300.0, 3000.0) * D.perc(n, 0.03) * 0.5
    return D.drive(x, 1.4) * vel


def taiko(vel: float = 1.0, freq: float = 72.0) -> np.ndarray:
    """Big hand drum: tom body + a skin slap in the mid band (reads on phones)."""
    x = D.mix((tom(freq, 1.0, 0.9), 1.0), (tom(freq * 2.4, 0.4, 0.18), 1.0))
    n = x.size
    x += D.bp(D.noise(n, "slap"), 600.0, 2500.0) * D.perc(n, 0.05) * 0.8
    return x * vel * 0.8


def rim(vel: float = 0.7, freq: float = 1750.0) -> np.ndarray:
    """Woody rim / clock tick (resonant ping + click)."""
    n = ns(0.08)
    x = D.sine(freq, n) * D.perc(n, 0.035) + D.sine(freq * 2.71, n) * D.perc(n, 0.012) * 0.5
    x += D.hp(D.noise(n, ("rim", freq)), 3000.0) * D.perc(n, 0.004) * 0.8
    return x * vel


def boom(vel: float = 1.0, f0: float = 62.0, decay: float = 2.2) -> np.ndarray:
    """Sub boom with a downward glide."""
    n = ns(decay + 0.1)
    t = np.arange(n) / SR
    f = f0 * (0.55 + 0.45 * np.exp(-t / 0.4)) * (1 + 1.2 * np.exp(-t / 0.015))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * D.perc(n, decay, 0.002) * vel


# ---------------------------------------------------------------------------- tonal

def pluck(m: float, dur: float = 0.4, vel: float = 0.8, bright: float = 1.0, decay: float = 0.6,
          shape: str = "saw", seed: int = 0) -> np.ndarray:
    """Additive pluck: harmonics whose decay shortens with order (a natural filter envelope)."""
    f = float(mtof(m))
    n = ns(dur + decay * 0.6)
    parts = []
    for k in range(1, 40):
        if f * k > 16000:
            break
        if shape == "square" and k % 2 == 0:
            continue
        amp = 1.0 / k
        t60 = decay / (1.0 + 0.35 * k / max(bright, 0.05))
        parts.append((k, amp, t60))
    x = D.additive(f, n, parts, phase_seed=seed)
    x *= D.adsr(n, 0.002, 0.1, 1.0, 0.05, gate=dur)
    return x * vel * 0.7


def marimba(m: float, vel: float = 0.8, decay: float = 0.9, seed: int = 0) -> np.ndarray:
    """Modal marimba bar (1 : 3.93 : 9.2) with a mallet click."""
    f = float(mtof(m))
    n = ns(decay * 1.1)
    x = D.additive(f, n, [(1.0, 1.0, decay), (3.93, 0.32 * vel, decay * 0.28), (9.2, 0.12 * vel, decay * 0.08),
                          (2.0, 0.05, decay * 0.4)], phase_seed=seed)
    x += D.bp(D.noise(n, ("mal", seed)), 1500.0, 6000.0) * D.perc(n, 0.006) * 0.25 * vel
    return x * D.perc(n, decay * 1.1, 0.0015) ** 0.25 * vel * 0.8


def bell(m: float, vel: float = 0.6, decay: float = 2.2, seed: int = 0) -> np.ndarray:
    """Glass/glock bell: inharmonic partials, long ring."""
    f = float(mtof(m))
    n = ns(decay * 1.05)
    x = D.additive(f, n, [(1.0, 1.0, decay), (2.0, 0.35, decay * 0.6), (2.76, 0.42, decay * 0.45),
                          (5.4, 0.2, decay * 0.25), (8.93, 0.1, decay * 0.12)], phase_seed=seed)
    return x * vel * 0.6


def felt_piano(m: float, dur: float = 1.5, vel: float = 0.6, seed: int = 0) -> np.ndarray:
    """Soft felt-piano tone: slightly stretched partials, gentle hammer, damped release."""
    f = float(mtof(m))
    n = ns(dur + 0.8)
    B = 0.0004
    parts = [(k * np.sqrt(1 + B * k * k), (0.9 ** k) / k ** 0.6, 2.8 / (1 + 0.45 * k)) for k in range(1, 18)]
    x = D.additive(f, n, parts, phase_seed=seed)
    x = D.lp(x, 2600.0 + 2500.0 * vel)
    x *= D.adsr(n, 0.004, 0.6, 1.0, 0.35, gate=dur, curve=3.0)
    return x * vel * 0.5


def organ(m: float, dur: float = 0.25, vel: float = 0.8) -> np.ndarray:
    """Percussive house organ stab (drawbar-ish sines + key click)."""
    f = float(mtof(m))
    n = ns(dur + 0.12)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * f * t) + 0.7 * np.sin(4 * np.pi * f * t) + 0.45 * np.sin(6 * np.pi * f * t)
         + 0.3 * np.sin(8 * np.pi * f * t) * np.exp(-t / 0.08))
    x *= D.adsr(n, 0.002, 0.12, 0.55, 0.08, gate=dur)
    x[: ns(0.003)] += D.noise(ns(0.003), ("click", m)) * 0.3
    return x * vel * 0.35


def saw_pad(chord: list[int], dur: float, vel: float = 0.5, attack: float = 0.6, release: float = 1.2,
            cutoff: float = 2400.0, detune: float = 0.16, voices: int = 5, seed: int = 0) -> np.ndarray:
    """Wide detuned-saw pad for a chord (stereo)."""
    n = ns(dur + release)
    out = np.zeros((2, n))
    for i, m in enumerate(chord):
        out += D.supersaw(float(mtof(m)), n, voices=voices, detune=detune, seed=seed * 31 + i, spread=0.6)
    out = D.lp(out, cutoff, 2)
    out *= D.adsr(n, attack, 0.8, 0.85, release, gate=dur, curve=3.0)[None, :]
    return out * vel / np.sqrt(len(chord)) * 0.6


def stab(chord: list[int], dur: float = 0.2, vel: float = 0.8, bright: float = 3800.0, seed: int = 0) -> np.ndarray:
    """Short supersaw chord stab with a quick filter envelope (stereo)."""
    n = ns(dur + 0.18)
    out = np.zeros((2, n))
    for i, m in enumerate(chord):
        out += D.supersaw(float(mtof(m)), n, voices=5, detune=0.14, seed=seed * 17 + i, spread=0.5)
    out = _bright_dark(out, bright, bright * 0.35, 0.06)
    out *= D.adsr(n, 0.003, 0.15, 0.5, 0.1, gate=dur)[None, :]
    return out * vel / np.sqrt(len(chord)) * 0.55


def bass(m: float, dur: float, vel: float = 0.9, cutoff: float = 700.0, sub: float = 0.7, drive: float = 1.5,
         env_t: float = 0.08, kind: str = "saw") -> np.ndarray:
    """Synth bass: saw (or square) + sine sub, enveloped low-pass, gentle drive."""
    f = float(mtof(m))
    n = ns(dur + 0.04)
    osc = D.saw(f, n) if kind == "saw" else D.pulse(f, n, 0.5)
    x = _bright_dark(osc, cutoff * 2.5, cutoff, env_t)
    x = x * 0.7 + D.sine(f, n) * sub
    x *= D.adsr(n, 0.003, 0.2, 0.8, 0.03, gate=dur)
    return D.drive(x, drive) * vel * 0.6


def lead(m: float, dur: float, vel: float = 0.7, cutoff: float = 3200.0, vib: float = 0.18,
         glide_from: float | None = None, detune: float = 0.08, attack: float = 0.008) -> np.ndarray:
    """Two-saw lead with delayed vibrato and optional glide (stereo-safe mono)."""
    n = ns(dur + 0.12)
    f = float(mtof(m))
    fc = _vib(f, n, vib, 5.6, 0.18)
    if glide_from is not None:
        t = np.arange(n) / SR
        fc = fc * 2.0 ** ((glide_from - m) * np.exp(-t / 0.045) / 12.0)
    x = D.saw(fc * 2 ** (detune / 12), n) + D.saw(fc * 2 ** (-detune / 12), n, 0.31) + 0.4 * D.pulse(fc / 2, n, 0.3)
    x = _bright_dark(x, cutoff * 1.6, cutoff, 0.12)
    x *= D.adsr(n, attack, 0.3, 0.75, 0.1, gate=dur)
    return x * vel * 0.35


def cello(m: float, dur: float, vel: float = 0.7, attack: float = 0.25) -> np.ndarray:
    """Bowed low-string top line: saw + body resonances, slow attack, vibrato (150-400 Hz register)."""
    n = ns(dur + 0.6)
    f = float(mtof(m))
    fc = _vib(f, n, 0.12, 5.0, 0.35)
    x = D.saw(fc, n) + 0.5 * D.saw(fc * 1.003, n, 0.5)
    x = D.lp(x, 2400.0, 2)
    x = D.eq(x, "peak", 300.0, 4.0, 1.2)
    x = D.eq(x, "peak", 1100.0, 2.5, 1.5)
    x += D.bp(D.noise(n, ("bow", m)), 1500.0, 5000.0) * 0.015
    x *= D.adsr(n, attack, 0.6, 0.9, 0.5, gate=dur, curve=3.0)
    return x * vel * 0.4


# ----------------------------------------------------------------------------- chip

FRAME = 1.0 / 60.0


def _frame_steps(levels: np.ndarray, n: int) -> np.ndarray:
    idx = np.minimum((np.arange(n) / SR / FRAME).astype(int), len(levels) - 1)
    return levels[idx]


def chip_env(dur: float, kind: str = "decay", vol: int = 15, frames: int = 14) -> np.ndarray:
    """4-bit volume per 60 Hz frame."""
    nf = max(1, int(np.ceil(dur / FRAME)))
    f = np.arange(nf)
    if kind == "decay":
        v = vol * np.clip(1 - f / max(frames, 1), 0, 1)
    elif kind == "pluck":
        v = np.maximum(vol * np.clip(1 - f / 6, 0, 1), vol * 0.45)
        v[-2:] = v[-2:] * 0.5
    else:  # sustain with a short tail
        v = np.where(f < 2, vol, vol * 0.8)
        v[-2:] = vol * 0.3
    return np.round(v) / 15.0


def chip_pulse(m: float, dur: float, duty: float = 0.25, vol: int = 12, env: str = "sustain",
               vib: float = 0.0, arp: tuple[int, ...] = (), arp_hz: float = 30.0, slide: float = 0.0) -> np.ndarray:
    """NES-like pulse note (band-limited) with optional 60 Hz-style arpeggio, vibrato and slide (semitones/s)."""
    n = ns(dur)
    t = np.arange(n) / SR
    semi = np.full(n, float(m))
    if arp:
        k = (t * arp_hz).astype(int) % len(arp)
        semi = semi + np.asarray(arp, dtype=float)[k]
    if vib:
        semi = semi + vib * np.clip((t - 0.15) / 0.2, 0, 1) * np.sin(2 * np.pi * 6.0 * t)
    if slide:
        semi = semi + slide * t
    x = D.pulse(mtof(semi), n, duty)
    lv = chip_env(dur, env, vol)
    return x * _frame_steps(lv, n) * 0.3


def chip_tri(m: float, dur: float, vol: float = 1.0, slide: float = 0.0) -> np.ndarray:
    """4-bit stepped triangle (no volume control on the real chip: gate only)."""
    n = ns(dur)
    t = np.arange(n) / SR
    f = mtof(m + slide * t) if slide else float(mtof(m))
    x = D.tri(f, n, steps=16)
    g = np.ones(n)
    g[-ns(0.004):] = np.linspace(1, 0, ns(0.004))
    return x * g * vol * 0.42


def chip_kick(vol: float = 1.0) -> np.ndarray:
    """Triangle pitch-drop kick + a short noise tick."""
    n = ns(0.12)
    t = np.arange(n) / SR
    f = 55.0 + 260.0 * np.exp(-t / 0.018)
    x = D.tri(f, n, steps=16) * (t < 0.1) * 0.6
    x += D.lfsr_noise(n, 64) * _frame_steps(np.array([1.0, 0.5, 0.0]), n) * 0.18
    return x * vol


def chip_snare(vol: float = 1.0) -> np.ndarray:
    n = ns(0.16)
    lv = np.array([15, 12, 9, 6, 4, 2, 1, 0]) / 15.0
    x = D.lfsr_noise(n, 160) * _frame_steps(lv, n) * 0.32
    x += D.tri(180.0 * np.exp(-np.arange(n) / SR / 0.05), n, steps=16) * _frame_steps(np.array([1, .6, .2, 0.0]), n) * 0.3
    return x * vol


def chip_hat(vol: float = 0.6, open_: bool = False) -> np.ndarray:
    n = ns(0.2 if open_ else 0.05)
    lv = (np.array([10, 7, 5, 4, 3, 2, 2, 1, 1, 0]) if open_ else np.array([9, 4, 1, 0])) / 15.0
    return D.lfsr_noise(n, 8) * _frame_steps(lv, n) * 0.22 * vol


def chip_crash(vol: float = 0.8) -> np.ndarray:
    n = ns(0.9)
    lv = np.clip(np.linspace(13, 0, 54), 0, 15).round() / 15.0
    return D.lfsr_noise(n, 32) * _frame_steps(lv, n) * 0.25 * vol


# ------------------------------------------------------------------------ transitions

def riser(dur: float, seed: int = 0, tonal: float | None = None) -> np.ndarray:
    """Noise riser (band-pass sweeping up) + optional rising saw; crescendo ends at ``dur`` (stereo)."""
    n = ns(dur)
    t = np.arange(n) / SR
    p = t / dur
    cut = 300.0 * (40.0 ** (p ** 1.6))
    out = []
    for c in range(2):
        x = D.sweep(D.noise(n, ("rise", seed, c)), cut, q=2.5, kind="bp", block=256)
        out.append(x)
    y = np.vstack(out) * (p ** 2.2)[None, :] * 1.6
    if tonal is not None:
        f = float(mtof(tonal)) * 2.0 ** (p * 12.0 / 12.0)
        s = D.lp(D.saw(f, n) + D.saw(f * 1.006, n, 0.4), 4000.0) * (p ** 2.5) * 0.18
        y += D.stereo(s)
    end = ns(0.015)
    y[:, -end:] *= np.linspace(1, 0, end)
    return y


def reverse_swell(dur: float, seed: int = 0) -> np.ndarray:
    """Reverse cymbal: a reversed crash tail that ends abruptly at ``dur`` (stereo)."""
    c = crash(1.0, decay=dur * 1.1, seed=seed)
    c = c[:, : ns(dur)]
    return c[:, ::-1] * 1.4


def impact(vel: float = 1.0, seed: int = 0, sub_f: float = 52.0, tail: float = 3.0) -> np.ndarray:
    """Designed trailer impact: sub boom + mid-band crack (phones) + metallic body + long tail (stereo)."""
    b = boom(1.0, sub_f, tail)
    n = b.size
    crack = D.bp(D.noise(n, ("crack", seed)), 700.0, 3500.0) * D.perc(n, 0.09, 0.0005) * 1.6
    metal = np.zeros(n)
    for f in (233.0, 351.0, 527.0, 781.0, 1033.0):
        metal += D.sine(f, n, phase0=f / 1000.0) * D.perc(n, 0.9 * 400.0 / f)
    body = D.bp(D.noise(n, ("body", seed)), 120.0, 900.0) * D.perc(n, 0.35) * 0.9
    mono = D.drive(b * 1.1 + crack + metal * 0.12 + body, 1.3)
    ir = D.reverb_ir(2.8, 0.02, 0.5, seed="impact")
    wet = D.convolve(mono * 0.5, ir)
    return (D.stereo(mono) + wet * 0.45) * vel * 0.7
