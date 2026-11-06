"""Original procedural SFX kit: ~24 sounds (+ variants), loudness-normalised, each with sync points.

Writes ``assets/audio/sfx/<name>_<k>.ogg`` and ``sfx.json``:
  {"sounds": {name: {"class", "gain_db", "sync", "tags", "variants": [{"file","dur","onset","peak","end"}]}}}
``sync`` is the natural alignment of the sound: onset (transient), peak (whoosh pass-by) or end (risers).
"""
from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable

import numpy as np

from . import dsp as D
from . import instruments as I
from . import orchestra as O
from .dsp import SR, ns
from .encode import decode, encode

LUFS_TARGET = -18.0
PEAK_MAX_DB = -1.5


# ------------------------------------------------------------------------------- designs

def whoosh(dur: float, seed: int, bright: float = 1.0) -> np.ndarray:
    """Doppler pass-by: band-passed noise whose centre falls as it passes, panned L->R, peak at ~58 %."""
    n = ns(dur)
    t = np.arange(n) / SR
    tp, w = dur * 0.58, dur * 0.16
    x = (t - tp) / w
    env = 1.0 / (1.0 + x * x) ** 0.9
    env *= np.clip(t / 0.02, 0, 1) * np.clip((dur - t) / 0.03, 0, 1)
    fc = 1400.0 * bright * (1.0 + 0.35 * np.tanh(-x))            # approaching high, receding low
    out = []
    for c in range(2):
        nz = D.noise(n, ("wh", seed, c))
        out.append(D.sweep(nz, fc, q=1.4, kind="bp", block=128) * 0.6 + D.sweep(nz, fc * 2.2, q=2.0, kind="bp", block=128) * 0.25)
    y = np.vstack(out)
    pan = np.tanh(x * 0.8) * 0.6
    a = (pan + 1.0) * np.pi / 4.0
    m = y.mean(axis=0)
    y = np.vstack([m * np.cos(a), m * np.sin(a)]) * np.sqrt(2) * 0.8 + y * 0.2
    return y * env[None, :]


def soft_click(seed: int) -> np.ndarray:
    f = (2300.0, 1900.0, 2700.0)[seed % 3]
    n = ns(0.05)
    x = D.sine(f, n) * D.perc(n, 0.012) + D.hp(D.noise(n, ("ck", seed)), 2000.0) * D.perc(n, 0.004) * 0.6
    x += D.sine(f * 0.25, n) * D.perc(n, 0.02) * 0.3
    return D.lp(x, 9000.0)


def key_tick(seed: int) -> np.ndarray:
    r = D.rng("key", seed)
    n = ns(0.06)
    x = D.bp(D.noise(n, ("kt", seed)), 1800.0 + 900 * r.random(), 7000.0) * D.perc(n, 0.009 + 0.004 * r.random())
    x += D.sine(260.0 + 80 * r.random(), n) * D.perc(n, 0.018) * 0.35
    x[ns(0.012):] += D.bp(D.noise(n - ns(0.012), ("kt2", seed)), 2500.0, 6000.0) * D.perc(n - ns(0.012), 0.005) * 0.3
    return x


def pop(seed: int) -> np.ndarray:
    n = ns(0.12)
    t = np.arange(n) / SR
    f0 = (380.0, 470.0)[seed % 2]
    f = f0 * (1 + 1.6 * (1 - np.exp(-t / 0.025)))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * D.perc(n, 0.08, 0.001)
    x += D.hp(D.noise(n, ("pop", seed)), 3000.0) * D.perc(n, 0.003) * 0.3
    return x


def chime() -> np.ndarray:
    a = I.bell(88, 0.7, 1.6)            # E6
    b = I.bell(95, 0.8, 2.2)            # B6
    return D.mix((a, 1.0), (np.concatenate([np.zeros(ns(0.11)), b]), 1.0))


def error_buzz() -> np.ndarray:
    n = ns(0.36)
    x = np.zeros(n)
    for k in range(2):
        s = ns(0.17 * k)
        m = ns(0.13)
        y = D.lp(D.pulse(155.0, m, 0.5) + D.saw(157.5, m), 1400.0) * D.adsr(m, 0.004, 0.05, 0.8, 0.03)
        x[s:s + m] += y
    return x


def hit(seed: int) -> np.ndarray:
    """Mid-size hit: tom body + mid-band crack (phones) + small room."""
    body = I.tom(92.0, 1.0, 0.45)
    n = body.size + ns(0.3)
    crack = D.bp(D.noise(n, ("hit", seed)), 800.0, 3200.0) * D.perc(n, 0.06, 0.0005) * 1.3
    x = D.mix((body, 1.0), (crack, 1.0))
    wet = D.convolve(x * 0.4, D.reverb_ir(0.9, 0.008, 0.6, seed="hit"))
    return D.stereo(D.drive(x, 1.3)) + wet * 0.35


def glitch(seed: int) -> np.ndarray:
    r = D.rng("glitch", seed)
    n = ns(0.36)
    x = np.zeros(n)
    pos = 0
    while pos < n - ns(0.02):
        seg = ns(0.012 + 0.03 * r.random())
        kind = r.integers(0, 3)
        if kind == 0:
            y = D.pulse(200 + 1800 * r.random(), seg, 0.5)
        elif kind == 1:
            y = np.repeat(D.noise(seg // 24 + 1, ("g", seed, pos)), 24)[:seg] * 1.6
        else:
            y = D.sine(3000 * r.random() + 400, seg) * np.sign(D.sine(60 + 200 * r.random(), seg))
        reps = int(r.integers(1, 4))
        for _ in range(reps):
            m = min(seg, n - pos)
            if m <= 0:
                break
            x[pos:pos + m] += y[:m] * (0.4 + 0.6 * r.random())
            pos += m
        pos += ns(0.004 * r.random())
    x = np.round(x * 8) / 8
    return D.stereo(D.fade(x, 0.001, 0.01)) * 0.6


def blip(seed: int) -> np.ndarray:
    n = ns(0.07)
    f = np.where(np.arange(n) < ns(0.03), 1200.0 + 200 * seed, 1800.0 + 200 * seed)
    return D.pulse(f, n, 0.25) * D.perc(n, 0.07, 0.001) * 0.6


def coin() -> np.ndarray:
    a = D.pulse(987.8, ns(0.07), 0.5)
    m = ns(0.45)
    b = D.pulse(1318.5, m, 0.5) * np.round(D.perc(m, 0.45) * 15) / 15
    return np.concatenate([a, b]) * 0.5


def power_up() -> np.ndarray:
    n = ns(0.7)
    t = np.arange(n) / SR
    semi = 60 + 24 * t / 0.7 + np.asarray([0, 4, 7, 12])[(t * 40).astype(int) % 4]
    x = D.pulse(D.mtof(semi), n, 0.25) * np.clip(1.2 - t / 0.7, 0, 1)
    return x * 0.5


def level_up() -> np.ndarray:
    notes = [72, 76, 79, 84, 88, 91]
    parts = []
    for m in notes:
        parts.append(I.chip_pulse(m, 0.075, 0.25, 13, "pluck"))
    run = np.concatenate(parts)
    held = D.mix((I.chip_pulse(96, 0.9, 0.5, 13, "decay", vib=0.3), 1.0),
                 (I.chip_pulse(84, 0.9, 0.25, 10, "decay", arp=(0, 4, 7), arp_hz=30.0), 0.6),
                 (I.chip_tri(60, 0.6), 0.8))
    return np.concatenate([run, held])


def relay() -> np.ndarray:
    n = ns(0.16)
    x = np.zeros(n)
    for k, (off, g) in enumerate(((0.0, 1.0), (0.018, 0.6), (0.075, 0.45))):
        s = ns(off)
        m = n - s
        y = (D.sine(2450.0 + 300 * k, m) * D.perc(m, 0.02) + D.sine(4100.0, m) * D.perc(m, 0.008) * 0.6
             + D.bp(D.noise(m, ("rl", k)), 1500.0, 8000.0) * D.perc(m, 0.004) + D.sine(180.0, m) * D.perc(m, 0.03) * 0.4)
        x[s:] += y * g
    return x


def beep(seed: int) -> np.ndarray:
    n = ns(0.13)
    f = (1000.0, 1500.0)[seed % 2]
    x = (D.sine(f, n) * 0.8 + D.pulse(f, n, 0.5) * 0.12) * D.adsr(n, 0.004, 0.05, 0.9, 0.01, gate=0.115)
    return D.lp(x, 6000.0)


def plotter() -> np.ndarray:
    n = ns(0.9)
    t = np.arange(n) / SR
    stroke = 0.5 + 0.5 * np.sin(2 * np.pi * 3.2 * t) ** 2
    scratch = D.bp(D.noise(n, "pen"), 2200.0, 7000.0) * stroke * 0.5
    steps = 620.0 + 260.0 * (np.floor(t * 8) % 3)
    motor = D.lp(D.pulse(steps, n, 0.5), 2500.0) * 0.08
    env = np.clip(t / 0.03, 0, 1) * np.clip((0.9 - t) / 0.06, 0, 1)
    return (scratch + motor) * env


def paper_swipe(seed: int) -> np.ndarray:
    n = ns(0.38)
    t = np.arange(n) / SR
    fc = 1500.0 * (1 + 2.0 * t / 0.38)
    x = D.sweep(D.noise(n, ("paper", seed)), fc, q=0.9, kind="bp", block=128)
    x += D.hp(D.noise(n, ("grain", seed)), 5000.0) * (D.noise(n, ("g2", seed)) > 0.6) * 0.3
    env = np.sin(np.pi * np.clip(t / 0.38, 0, 1)) ** 1.5
    return D.stereo(x * env, -0.2)


def shutter() -> np.ndarray:
    n = ns(0.22)
    x = np.zeros(n)
    for off, g, f in ((0.0, 1.0, 3200.0), (0.065, 0.8, 2700.0)):
        s = ns(off)
        m = n - s
        x[s:] += (D.bp(D.noise(m, ("sh", off)), 1500.0, 9000.0) * D.perc(m, 0.012) + D.sine(f, m) * D.perc(m, 0.01) * 0.4) * g
    x += D.sine(140.0, n) * D.perc(n, 0.05) * 0.3
    return x


def sub_drop() -> np.ndarray:
    b = I.boom(1.0, 58.0, 1.6)
    n = b.size
    mid = D.bp(D.noise(n, "subhit"), 900.0, 3000.0) * D.perc(n, 0.05, 0.0005) * 0.9
    return D.drive(b + mid, 1.2)


def stamp() -> np.ndarray:
    """Blueprint revision stamp: rubber thud + paper slap."""
    body = I.tom(140.0, 0.8, 0.12)
    n = body.size
    slap = D.bp(D.noise(n, "stamp"), 600.0, 4000.0) * D.perc(n, 0.025) * 0.8
    return body + slap


# ------------------------------------------------------------------- wave 3: stings + kit sounds

BLOOM_SWELL = 1.7          # seconds from file start to the bloom_riser impact (its ``hit`` sync point)


def bloom_riser(tonic: int, seed: int, swell: float = BLOOM_SWELL) -> np.ndarray:
    """Style-switch sting: an airy 1.7 s swell (rising band-passed air, a reversed bell chord sucking in, a soft
    rising sine pair) into a SOFT shimmering impact (felt thump with a phone-band knock, bell chord in the
    key of the incoming bed, descending chime tree, air burst, quiet cymbal) with a long reverb tail."""
    tail = 3.4
    n = ns(swell + tail)
    hit = ns(swell)
    t = np.arange(n) / SR
    p = np.clip(t / swell, 0.0, 1.0)
    pre = (t < swell).astype(float)
    out = np.zeros((2, n))
    cut = 500.0 * (14.0 ** (p ** 1.5))
    for c in range(2):
        air = D.sweep(D.noise(n, ("bloom", seed, c)), cut, q=1.3, kind="bp", block=256)
        out[c] += air * (p ** 1.8) * pre * 0.55
    chord = [tonic + 24, tonic + 31, tonic + 36, tonic + 38, tonic + 40]       # 1 5 8 9 10: open add9
    fw = np.zeros(ns(swell))
    for k, m in enumerate(chord):
        b = O.glock(m, 0.6, decay=2.2, seed=k)[: fw.size]
        fw[: b.size] += b
    rev = fw[::-1] * np.linspace(0.3, 1.0, fw.size) ** 2
    out[:, hit - rev.size:hit] += D.stereo(rev) * 0.55
    gl = np.zeros(n)
    for m, g in ((tonic + 12, 1.0), (tonic + 19, 0.6)):
        semi = m + 12.0 * p ** 1.8
        gl += D.sine(D.mtof(semi), n) * g
    out += D.stereo(gl * (p ** 3.0) * pre * 0.12)
    # ---- the soft impact
    imp = np.zeros((2, n - hit))
    m_ = imp.shape[1]
    thump = O.soft_timp(float(D.mtof(tonic - 12)), 0.9)[:m_]
    knock = D.sine(205.0, m_) * D.perc(m_, 0.08) * 0.35
    imp[:, : thump.size] += D.stereo(thump * 1.1)
    imp += D.stereo(knock)
    for k, m in enumerate(chord):
        b = O.glock(m, 0.55, decay=3.0, seed=10 + k)[:m_]
        imp[:, : b.size] += D.stereo(b, (k - 2) * 0.3) * 0.85
    ct = O.chime_tree(1.1, seed=seed)[:, :m_]
    imp[:, : ct.shape[1]] += ct * 1.1
    burst = D.hp(np.vstack([D.noise(m_, ("burst", seed, c)) for c in range(2)]), 4000.0) * D.perc(m_, 1.2, 0.004)
    imp += burst * 0.35
    cr = I.crash(0.25, 2.4, seed=seed)[:, :m_]
    imp[:, : cr.shape[1]] += cr
    wet = D.convolve(imp * 0.6, D.reverb_ir(3.4, 0.02, 0.45, seed=f"bloom{seed}"))
    gap = ns(0.045)                       # a 45 ms breath before the hit so the impact reads
    out[:, hit - gap:hit] *= np.linspace(1.0, 0.25, gap) ** 2
    out[:, hit:] += imp + wet * 0.55
    return out


def chip_buy() -> np.ndarray:
    """8-bit 'ka-ching': LFSR noise 'ka' + quick rising pulse arp into a held chord with a metallic ching."""
    ka = D.lfsr_noise(ns(0.05), 12) * I._frame_steps(np.array([1.0, 0.7, 0.3]), ns(0.05)) * 0.35
    a = I.chip_pulse(83, 0.055, 0.5, 13, "pluck")
    b = I.chip_pulse(88, 0.055, 0.5, 13, "pluck")
    held = D.mix((I.chip_pulse(95, 0.6, 0.25, 14, "decay", vib=0.25), 1.0),
                 (I.chip_pulse(88, 0.6, 0.5, 11, "decay", arp=(0, 4, 7, 12), arp_hz=30.0), 0.55))
    n = held.size
    ching = D.additive(2637.0, n, [(1.0, 1.0, 0.7), (1.51, 0.6, 0.5), (2.02, 0.4, 0.35), (2.71, 0.25, 0.25)]) * 0.08
    return np.concatenate([ka, a, b, held + ching])


def cash() -> np.ndarray:
    """Glossy (non-chip) purchase: drawer 'ka-chunk' then a bright bell 'ching' with a few coin pings."""
    n = ns(1.5)
    x = np.zeros(n)
    thunk = D.bp(D.noise(ns(0.07), "drawer"), 300.0, 2200.0) * D.perc(ns(0.07), 0.05, 0.001)
    x[: thunk.size] += thunk * 0.9
    x[: ns(0.004)] += D.hp(D.noise(ns(0.004), "clk"), 3000.0) * 0.6
    s0 = ns(0.075)
    bell = D.additive(2093.0, n - s0, [(1.0, 1.0, 1.1), (1.26, 0.7, 0.9), (1.5, 0.6, 0.8), (2.0, 0.45, 0.6),
                                       (2.76, 0.2, 0.3), (3.4, 0.12, 0.2)])
    x[s0:] += bell * 0.5
    r = D.rng("coins")
    for k in range(5):
        st = s0 + ns(0.05 + 0.09 * k + 0.02 * r.random())
        m = ns(0.12)
        if st + m < n:
            x[st:st + m] += D.sine(3400.0 + 900.0 * r.random(), m) * D.perc(m, 0.06) * 0.18
    return D.stereo(x)


def sword_slash(seed: int) -> np.ndarray:
    """Blade swish (fast high-to-low band-pass sweep) + metallic 'shing'; variant 2 is 8-bit (LFSR sweep + ping)."""
    if seed % 2 == 1:
        n = ns(0.34)
        t = np.arange(n) / SR
        per = np.clip(2 + (t / 0.16) * 40, 2, 64).astype(int)
        nz = np.zeros(n)
        for pv in sorted(set(per.tolist())):
            msk = per == pv
            nz[msk] = D.lfsr_noise(n, int(pv))[msk]
        env = np.clip(t / 0.015, 0, 1) * np.exp(-np.maximum(t - 0.02, 0) / 0.07)
        ping = D.pulse(1760.0 * np.exp(-t / 0.25), n, 0.25) * D.perc(n, 0.25, 0.002) * 0.25
        return D.stereo(nz * env * 0.5 + ping)
    n = ns(0.5)
    t = np.arange(n) / SR
    fc = 6500.0 * np.exp(-t / 0.07) + 900.0
    sw = D.sweep(D.noise(n, ("slash", seed)), fc, q=1.6, kind="bp", block=64)
    env = np.clip(t / 0.03, 0, 1) * np.exp(-np.maximum(t - 0.04, 0) / 0.05)
    s0 = ns(0.035)
    shing = np.zeros(n)
    shing[s0:] = D.additive(2830.0, n - s0, [(1.0, 1.0, 0.35), (1.386, 0.7, 0.3), (1.848, 0.5, 0.22), (2.35, 0.35, 0.15)],
                            phase_seed=seed) * 0.16
    x = sw * env * 1.4 + shing
    pan = np.clip((t - 0.03) / 0.1, 0, 1) * 1.2 - 0.6
    a = (pan + 1.0) * np.pi / 4.0
    return np.vstack([x * np.cos(a), x * np.sin(a)]) * np.sqrt(2)


def blade_spin(seed: int) -> np.ndarray:
    """Spinning thrown blade: rotor-modulated air with a doppler pass-by and a metallic whirr, peak at ~55 %."""
    dur = 0.95
    n = ns(dur)
    t = np.arange(n) / SR
    tp, w = dur * 0.55, dur * 0.2
    xx = (t - tp) / w
    env = (1.0 / (1.0 + xx * xx)) * np.clip(t / 0.03, 0, 1) * np.clip((dur - t) / 0.05, 0, 1)
    rot = np.abs(np.sin(np.pi * (13.0 + 3.0 * seed) * t)) ** 3
    fc = 2200.0 * (1.0 + 0.3 * np.tanh(-xx))
    air = D.sweep(D.noise(n, ("spin", seed)), fc, q=1.8, kind="bp", block=128)
    whirr = D.saw(780.0 * (1.0 + 0.06 * np.tanh(-xx)), n) * 0.05 * rot
    x = (air * (0.35 + 0.65 * rot) + whirr) * env
    pan = np.tanh(xx * 0.9) * 0.7
    a = (pan + 1.0) * np.pi / 4.0
    return np.vstack([x * np.cos(a), x * np.sin(a)]) * np.sqrt(2) * 1.4


def damage(seed: int) -> np.ndarray:
    """8-bit 'hurt': falling pulse + crunchy LFSR noise with a 30 Hz flicker (NES damage blink)."""
    n = ns(0.3)
    t = np.arange(n) / SR
    f0 = (880.0, 660.0)[seed % 2]
    tone = D.pulse(f0 * np.exp(-t / 0.07) + 70.0, n, 0.5) * 0.5
    crunch = D.lfsr_noise(n, 24 + 16 * seed) * 0.35
    lv = np.clip(np.linspace(15, 0, 18), 0, 15).round() / 15.0
    env = I._frame_steps(lv, n)
    flick = np.where((t * 30).astype(int) % 2 == 0, 1.0, 0.45)
    return D.stereo((tone + crunch) * env * flick * 0.6)


def footstep(seed: int) -> np.ndarray:
    """Dungeon footstep: short 8-bit noise tick + a soft low thud (4 variants, different pitch)."""
    n = ns(0.11)
    per = (96, 128, 80, 112)[seed % 4]
    tick = D.lfsr_noise(n, per, seed=seed + 3) * I._frame_steps(np.array([0.9, 0.45, 0.15, 0.0]), n) * 0.35
    thud = D.sine(85.0 + 12 * seed, n) * D.perc(n, 0.05, 0.002) * 0.5
    thud += D.lp(D.noise(n, ("step", seed)), 600.0) * D.perc(n, 0.03, 0.001) * 0.4
    return D.stereo(tick + thud, (-0.15, 0.15)[seed % 2])


def door_rumble() -> np.ndarray:
    """Heavy stone door grinding open: sub rumble, stick-slip grind in the mid band (phones), a few knocks."""
    dur = 1.9
    n = ns(dur)
    t = np.arange(n) / SR
    am_raw = D.lp(D.rng("am").standard_normal(n), 6.0)
    am = np.clip(0.6 + 0.4 * am_raw / (np.max(np.abs(am_raw)) + 1e-12), 0.2, 1.0)
    rumble = D.lp(D.noise(n, "rumble"), 140.0, 4) * 3.0 * am
    slip = np.clip(D.lp(D.rng("slip").standard_normal(n), 22.0) * 40.0, 0, None)
    grind = D.bp(D.noise(n, "grind"), 260.0, 1400.0) * (0.3 + slip / (np.max(slip) + 1e-9)) * 0.9
    x = rumble + grind
    for k, tt in enumerate((0.05, 0.62, 1.31)):
        kn = I.tom(70.0 + 15 * k, 0.6, 0.25)
        D.place(x, kn, ns(tt))
    env = np.clip(t / 0.12, 0, 1) * np.clip((dur - t) / 0.45, 0, 1)
    return D.stereo(x * env) * 0.8


def chain_break() -> np.ndarray:
    """Chain snapping: a crack + clank, then links rattling down with decreasing bounces."""
    n = ns(1.0)
    x = np.zeros(n)
    crack = D.bp(D.noise(ns(0.03), "crack"), 1000.0, 6000.0) * D.perc(ns(0.03), 0.02, 0.0003) * 1.4
    x[: crack.size] += crack
    clank = D.additive(1230.0, ns(0.25), [(1.0, 1.0, 0.18), (1.71, 0.7, 0.14), (2.32, 0.6, 0.1), (2.93, 0.4, 0.07)])
    x[: clank.size] += clank * 0.5
    r = D.rng("links")
    tt, gap, g = 0.09, 0.075, 0.55
    for k in range(14):
        m = ns(0.07)
        st = ns(tt)
        if st + m >= n:
            break
        f = 2200.0 + 3500.0 * r.random()
        ping = D.additive(f, m, [(1.0, 1.0, 0.05), (1.53, 0.6, 0.035), (2.11, 0.4, 0.025)], phase_seed=k)
        x[st:st + m] += ping * g * (0.7 + 0.3 * r.random())
        tt += gap * (0.6 + 0.8 * r.random())
        gap *= 0.88
        g *= 0.86
    return D.stereo(x)


def menu_move() -> np.ndarray:
    """Soft 8-bit cursor tick (lower and shorter than blip)."""
    n = ns(0.045)
    return D.pulse(1046.5, n, 0.25) * I._frame_steps(np.array([0.8, 0.4, 0.0]), n) * 0.5


def menu_confirm() -> np.ndarray:
    """8-bit confirm: two rising notes (B5 -> E6) with a short octave echo."""
    a = I.chip_pulse(83, 0.05, 0.5, 13, "pluck")
    b = I.chip_pulse(88, 0.17, 0.5, 13, "decay")
    echo = I.chip_pulse(100, 0.12, 0.125, 6, "decay")
    return np.concatenate([a, D.mix((b, 1.0), (np.concatenate([np.zeros(ns(0.05)), echo]), 1.0))])


def petal_burst(seed: int) -> np.ndarray:
    """Airy swirl of petals: circling band-passed air with a rotating pan and a few tiny high sparkles."""
    dur = 1.25
    n = ns(dur)
    t = np.arange(n) / SR
    tp = 0.38
    env = np.where(t < tp, (t / tp) ** 1.6, np.exp(-(t - tp) / 0.33))
    env *= np.clip((dur - t) / 0.05, 0, 1)
    lfo = 2.6 + 0.6 * seed
    fc1 = 2400.0 + 1300.0 * np.sin(2 * np.pi * lfo * t)
    fc2 = 4200.0 + 1600.0 * np.cos(2 * np.pi * lfo * 1.3 * t)
    nz = D.noise(n, ("petal", seed))
    air = D.sweep(nz, fc1, q=2.2, kind="bp", block=128) + 0.6 * D.sweep(nz, fc2, q=2.6, kind="bp", block=128)
    ang = 2 * np.pi * 1.2 * t + seed
    pan = np.sin(ang) * 0.75
    a = (pan + 1.0) * np.pi / 4.0
    out = np.vstack([air * np.cos(a), air * np.sin(a)]) * np.sqrt(2) * env * 0.9
    r = D.rng("petal_sparkle", seed)
    for _ in range(7):
        m = int(r.choice([91, 93, 96, 98, 100, 103]))
        st = ns(0.12 + 0.75 * r.random())
        b = O.celesta(m, 0.35 + 0.2 * r.random(), decay=0.7, seed=m)
        D.place(out, D.stereo(b, r.random() * 1.4 - 0.7) * 0.25, st)
    return out


def encounter() -> np.ndarray:
    """JRPG battle-start swirl (8-bit): a spiralling pulse arpeggio that falls two octaves with fast vibrato over
    a rising LFSR-noise swell, then a bright 'shatter' (noise + high pulse burst) as the screen breaks."""
    dur = 0.85
    n = ns(dur)
    t = np.arange(n) / SR
    p = t / dur
    semi = 96.0 - 24.0 * p + np.asarray([0, 7, 12, 19])[(t * 40).astype(int) % 4] + 0.5 * np.sin(2 * np.pi * 18 * t)
    swirl = D.pulse(D.mtof(semi), n, 0.25) * (0.55 + 0.45 * np.sin(np.pi * p)) * 0.4
    per = np.clip(64 - 56 * p, 4, 64).astype(int)
    nz = np.zeros(n)
    for pv in sorted(set(per.tolist())):
        msk = per == pv
        nz[msk] = D.lfsr_noise(n, int(pv))[msk]
    swell = nz * p ** 1.5 * 0.3
    m = ns(0.35)
    shatter = (D.lfsr_noise(m, 6) * 0.45 + D.pulse(2093.0, m, 0.125) * 0.25) * I._frame_steps(
        np.clip(np.linspace(15, 0, 21), 0, 15).round() / 15.0, m)
    out = np.concatenate([swirl + swell, shatter])
    return D.stereo(out)


def switch_whoosh(seed: int) -> np.ndarray:
    """Style-switch whoosh: a big airy pass-by with low-mid body, reverse-swell lead-in, peak at ~60 %."""
    dur = 1.2
    w = whoosh(dur, 40 + seed, 0.9)
    n = w.shape[1]
    t = np.arange(n) / SR
    tp = dur * 0.58
    body = D.bp(D.noise(n, ("body", seed)), 180.0, 900.0) * (1.0 / (1.0 + ((t - tp) / (dur * 0.18)) ** 2))
    rs = I.reverse_swell(tp, seed=50 + seed)
    out = w * 1.1 + D.stereo(body * 0.8)
    out[:, : rs.shape[1]] += rs * 0.35
    return out


KIT: dict[str, dict] = {
    "whoosh_short": dict(fn=lambda k: whoosh(0.5, k, 1.0 + 0.15 * k), n=2, cls="foley", gain=-10.0, sync="peak", tags=["transition", "camera"]),
    "whoosh_long": dict(fn=lambda k: whoosh(1.15, 10 + k, 0.8), n=2, cls="foley", gain=-9.0, sync="peak", tags=["transition", "camera"]),
    "click": dict(fn=soft_click, n=3, cls="foley", gain=-14.0, sync="onset", tags=["ui"]),
    "key": dict(fn=key_tick, n=4, cls="foley", gain=-17.0, sync="onset", tags=["typing"]),
    "pop": dict(fn=pop, n=2, cls="foley", gain=-12.0, sync="onset", tags=["ui", "appear"]),
    "chime": dict(fn=lambda k: chime(), n=1, cls="hero", gain=-6.0, sync="onset", tags=["success"]),
    "error": dict(fn=lambda k: error_buzz(), n=1, cls="foley", gain=-14.0, sync="onset", tags=["fail"]),
    "hit": dict(fn=hit, n=2, cls="hero", gain=-6.0, sync="onset", tags=["reveal", "stat"]),
    "impact": dict(fn=lambda k: I.impact(1.0, seed=40 + k, sub_f=48.0, tail=2.6), n=1, cls="hero", gain=-3.0, sync="onset",
                   tags=["hero"]),
    "riser": dict(fn=lambda k: I.riser(2.4, seed=60 + k, tonal=50), n=1, cls="hero", gain=-6.0, sync="end", tags=["build"]),
    "reverse": dict(fn=lambda k: I.reverse_swell(1.4, seed=70 + k), n=1, cls="hero", gain=-6.0, sync="end", tags=["build"]),
    "glitch": dict(fn=glitch, n=2, cls="foley", gain=-12.0, sync="onset", tags=["transition", "terminal"]),
    "blip": dict(fn=blip, n=2, cls="foley", gain=-14.0, sync="onset", tags=["ui", "pixel"]),
    "coin": dict(fn=lambda k: coin(), n=1, cls="foley", gain=-12.0, sync="onset", tags=["pixel", "stat"]),
    "power_up": dict(fn=lambda k: power_up(), n=1, cls="foley", gain=-12.0, sync="onset", tags=["pixel"]),
    "level_up": dict(fn=lambda k: level_up(), n=1, cls="hero", gain=-6.0, sync="onset", tags=["pixel", "success"]),
    "relay": dict(fn=lambda k: relay(), n=1, cls="foley", gain=-13.0, sync="onset", tags=["terminal"]),
    "beep": dict(fn=beep, n=2, cls="foley", gain=-15.0, sync="onset", tags=["terminal"]),
    "plotter": dict(fn=lambda k: plotter(), n=1, cls="foley", gain=-13.0, sync="onset", tags=["blueprint", "draw"]),
    "paper": dict(fn=paper_swipe, n=2, cls="foley", gain=-12.0, sync="peak", tags=["blueprint", "transition"]),
    "stamp": dict(fn=lambda k: stamp(), n=1, cls="foley", gain=-10.0, sync="onset", tags=["blueprint", "reveal"]),
    "shutter": dict(fn=lambda k: shutter(), n=1, cls="foley", gain=-12.0, sync="onset", tags=["screenshot"]),
    "sub_drop": dict(fn=lambda k: sub_drop(), n=1, cls="hero", gain=-4.0, sync="onset", tags=["hero"]),
    # ---- wave 3 (stings + the pixel/nature kit requests in ISSUES.md #6)
    "bloom_riser": dict(fn=lambda k: bloom_riser((60, 55)[k], seed=k), n=2, cls="hero", gain=-4.0, sync="hit",
                        hit_s=BLOOM_SWELL, keys=["C major", "G major"], tags=["sting", "build", "transition", "dream"]),
    "switch_whoosh": dict(fn=switch_whoosh, n=2, cls="foley", gain=-8.0, sync="peak", tags=["transition", "sting"]),
    "petal_burst": dict(fn=petal_burst, n=2, cls="foley", gain=-10.0, sync="peak", tags=["transition", "dream"]),
    "buy": dict(fn=lambda k: chip_buy(), n=1, cls="hero", gain=-6.0, sync="onset", tags=["pixel", "success", "buy"]),
    "cash": dict(fn=lambda k: cash(), n=1, cls="hero", gain=-6.0, sync="onset", tags=["success", "buy"]),
    "sword_slash": dict(fn=sword_slash, n=2, cls="foley", gain=-9.0, sync="peak", tags=["pixel", "combat"]),
    "blade_spin": dict(fn=blade_spin, n=2, cls="foley", gain=-10.0, sync="peak", tags=["pixel", "combat"]),
    "damage": dict(fn=damage, n=2, cls="foley", gain=-9.0, sync="onset", tags=["pixel", "combat"]),
    "footstep": dict(fn=footstep, n=4, cls="foley", gain=-16.0, sync="onset", tags=["pixel", "foley"]),
    "door_rumble": dict(fn=lambda k: door_rumble(), n=1, cls="foley", gain=-8.0, sync="onset", tags=["pixel", "reveal"]),
    "chain_break": dict(fn=lambda k: chain_break(), n=1, cls="foley", gain=-9.0, sync="onset", tags=["pixel", "reveal"]),
    "menu_move": dict(fn=lambda k: menu_move(), n=1, cls="foley", gain=-15.0, sync="onset", tags=["pixel", "ui"]),
    "menu_confirm": dict(fn=lambda k: menu_confirm(), n=1, cls="foley", gain=-12.0, sync="onset", tags=["pixel", "ui"]),
    "encounter": dict(fn=lambda k: encounter(), n=1, cls="foley", gain=-9.0, sync="onset",
                      tags=["pixel", "transition", "sting"]),
}

#: Other names kits and the story timing use -> a sound, or ``@role`` (resolved per style via ``styles``).
ALIASES = {
    "whoosh": "@cut", "tick": "@type", "split": "@appear", "transition": "@cut", "success": "@pass",
    "slash": "sword_slash", "sword": "sword_slash", "throw": "blade_spin", "chains": "chain_break",
    "hurt": "damage", "step": "footstep", "door": "door_rumble", "menu_select": "menu_confirm",
    "confirm": "menu_confirm", "cursor": "menu_move", "purchase": "@buy", "petals": "petal_burst",
    "bloom": "bloom_riser", "style_switch": "@switch", "item_get": "level_up", "press_start": "power_up",
    "boss_appear": "impact", "door_open": "whoosh_long", "menu_open": "pop", "emote": "blip",
    "bloom_whoosh": "switch_whoosh", "battle_start": "encounter",
}

_PIXEL = {"cut": "blip", "move": "power_up", "click": "menu_move", "type": "blip", "appear": "coin", "pass": "level_up",
          "fail": "damage", "hit": "coin", "hero": "level_up", "build": "power_up", "shot": "coin", "buy": "buy",
          "switch": "bloom_riser"}
_INK = {"cut": "paper", "move": "paper", "click": "click", "type": "plotter", "appear": "pop", "pass": "chime",
        "fail": "error", "hit": "stamp", "hero": "hit", "build": "reverse", "shot": "shutter", "buy": "cash",
        "switch": "switch_whoosh"}
_DREAM = {"cut": "petal_burst", "move": "whoosh_long", "click": "click", "type": "key", "appear": "chime",
          "pass": "chime", "fail": "error", "hit": "hit", "hero": "bloom_riser", "build": "reverse", "shot": "shutter",
          "buy": "cash", "switch": "bloom_riser"}
STYLE_MAP = {
    "launch": {"cut": "whoosh_short", "move": "whoosh_long", "click": "click", "type": "key", "appear": "pop",
               "pass": "chime", "fail": "error", "hit": "hit", "hero": "impact", "build": "riser", "shot": "shutter"},
    "pixel": {"cut": "blip", "move": "power_up", "click": "blip", "type": "blip", "appear": "coin", "pass": "level_up",
              "fail": "error", "hit": "coin", "hero": "level_up", "build": "power_up", "shot": "coin"},
    "terminal": {"cut": "glitch", "move": "glitch", "click": "relay", "type": "key", "appear": "beep", "pass": "beep",
                 "fail": "error", "hit": "relay", "hero": "sub_drop", "build": "riser", "shot": "shutter"},
    "blueprint": {"cut": "paper", "move": "paper", "click": "click", "type": "plotter", "appear": "stamp",
                  "pass": "chime", "fail": "error", "hit": "stamp", "hero": "hit", "build": "reverse", "shot": "shutter"},
    "cinematic": {"cut": "whoosh_long", "move": "whoosh_long", "click": "click", "type": "key", "appear": "reverse",
                  "pass": "chime", "fail": "error", "hit": "hit", "hero": "impact", "build": "riser", "shot": "shutter"},
    "pixel_boss": _PIXEL,
    "comic": {"cut": "whoosh_short", "move": "whoosh_long", "click": "pop", "type": "key", "appear": "pop",
              "pass": "chime", "fail": "error", "hit": "hit", "hero": "impact", "build": "riser", "shot": "shutter",
              "buy": "cash", "switch": "switch_whoosh"},
    "ink": _INK,
    "newspaper": {**_INK, "appear": "stamp", "type": "key"},
    "dream": _DREAM,
    "nature": _DREAM,
}
for _m in STYLE_MAP.values():               # every style knows the wave-3 roles
    _m.setdefault("buy", "cash")
    _m.setdefault("switch", "switch_whoosh")
STYLE_MAP["pixel"].update({"buy": "buy", "switch": "bloom_riser"})


def _normalise(x: np.ndarray) -> tuple[np.ndarray, float]:
    xs = D.stereo(x) if x.ndim == 1 else x
    xs = D.hp(xs, 30.0)
    st = D.short_term_max(xs)
    g = LUFS_TARGET - st
    y = xs * D.db(g)
    tp = D.true_peak_db(y)
    if tp > PEAK_MAX_DB:
        y *= D.db(PEAK_MAX_DB - tp)
    return D.fade(y, 0.0005, 0.008), D.short_term_max(y)


def _hit_point(x: np.ndarray, designed_s: float, window_s: float = 0.03) -> float:
    """The impact transient nearest the designed hit time (largest rise of the 2 ms envelope in the window)."""
    m = np.abs(x).max(axis=0)
    env = np.convolve(m, np.ones(ns(0.002)) / ns(0.002), mode="same")
    a, b = ns(max(designed_s - window_s, 0.0)), min(ns(designed_s + window_s), env.size - 1)
    rise = np.diff(env[a:b + 1])
    return round((a + int(np.argmax(rise))) / SR, 4) if rise.size else round(designed_s, 4)


def _sync_points(x: np.ndarray, sync: str) -> dict[str, float]:
    m = np.abs(x).max(axis=0)
    env = np.convolve(m, np.ones(ns(0.005)) / ns(0.005), mode="same")
    pk = float(env.max())
    onset = int(np.argmax(env > pk * 0.1))
    peak = int(np.argmax(env))
    above = np.nonzero(env > pk * 0.01)[0]
    end = int(above[-1]) if above.size else x.shape[-1]
    if sync == "end":
        end = int(above[-1])
    return {"onset": round(onset / SR, 4), "peak": round(peak / SR, 4), "end": round(end / SR, 4)}


def _encode_if_changed(x: np.ndarray, path: Path) -> None:
    """Encode to Opus, but keep an existing file whose decoded audio is identical (Ogg stream serials are
    random, so re-encoding unchanged sounds would churn binary files in git)."""
    if not path.is_file():
        encode(x, path, "opus", "96k")
        return
    tmp = path.with_name(path.stem + ".tmp.ogg")
    try:
        encode(x, tmp, "opus", "96k")
        old, new = decode(path), decode(tmp)
        if old.shape != new.shape or float(np.abs(old - new).max()) > 0.0:
            tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def build_kit(out: Path, progress: Callable[[str], None] | None = print) -> dict:
    """Render, normalise, encode every sound; write ``sfx.json``. Returns the metadata."""
    out.mkdir(parents=True, exist_ok=True)
    meta: dict = {"version": 1, "sr": SR, "lufs_target": LUFS_TARGET, "classes": {"hero": [-6.0, 0.0], "foley": [-18.0, -8.0]},
                  "styles": STYLE_MAP, "aliases": ALIASES, "sounds": {}}
    for name, spec in KIT.items():
        variants = []
        for k in range(spec["n"]):
            x, st = _normalise(spec["fn"](k))
            pad = np.zeros((2, ns(0.02)))
            x = np.concatenate([x, pad], axis=1)
            f = f"{name}_{k + 1}.ogg"
            _encode_if_changed(x, out / f)
            dec = decode(out / f)
            sp = _sync_points(dec, spec["sync"])
            var = {"file": f, "dur": round(dec.shape[-1] / SR, 4), **sp, "st_lufs": round(st, 1)}
            if "hit_s" in spec:
                var["hit"] = round(float(spec["hit_s"]), 4)          # designed impact sample (decode is sample-exact)
                var["hit_measured"] = _hit_point(dec, spec["hit_s"])  # QA: steepest envelope rise near it
            if "keys" in spec:
                var["key"] = spec["keys"][k]
            variants.append(var)
        meta["sounds"][name] = {"class": spec["cls"], "gain_db": spec["gain"], "sync": spec["sync"], "tags": spec["tags"],
                                "variants": variants}
        if progress:
            progress(f"sfx {name}: {len(variants)} variant(s)")
    (out / "sfx.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    return meta
