"""Core DSP for the dev-time composer (numpy/scipy; never imported by the plugin at runtime).

All signals are float64 numpy arrays at 48 kHz. Mono = shape (n,), stereo = shape (2, n).
Everything is vectorised; the only Python loops run per block (filter sweeps) or per note.
"""
from __future__ import annotations

import functools
import zlib

import numpy as np
from scipy import signal

SR = 48000


# ----------------------------------------------------------------------------- basics

def ns(seconds: float) -> int:
    """Seconds -> whole samples (never negative)."""
    return max(0, int(round(seconds * SR)))


def rng(*key: object) -> np.random.Generator:
    """Deterministic RNG from any key (crc32 of its repr, never ``hash()``)."""
    return np.random.default_rng(zlib.crc32(repr(key).encode("utf-8")))


def db(x: float) -> float:
    """dB -> linear gain."""
    return float(10.0 ** (x / 20.0))


def mtof(m: float | np.ndarray) -> float | np.ndarray:
    """MIDI note -> Hz."""
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0)


def stereo(x: np.ndarray, pan: float = 0.0) -> np.ndarray:
    """Mono -> stereo with a constant-power pan (-1 left .. +1 right); stereo passes through."""
    if x.ndim == 2:
        return x
    a = (pan + 1.0) * np.pi / 4.0
    return np.vstack([x * np.cos(a), x * np.sin(a)]) * np.sqrt(2.0)


def width(x: np.ndarray, w: float) -> np.ndarray:
    """M/S width (1 = unchanged, 0 = mono, >1 wider). Mono-safe: never a Haas delay."""
    m = (x[0] + x[1]) * 0.5
    s = (x[0] - x[1]) * 0.5 * w
    return np.vstack([m + s, m - s])


def fade(x: np.ndarray, fin: float = 0.003, fout: float = 0.01) -> np.ndarray:
    """Short linear fades at both ends to avoid clicks (in place on a copy)."""
    y = np.array(x, dtype=float, copy=True)
    n = y.shape[-1]
    a, b = min(ns(fin), n), min(ns(fout), n)
    if a:
        y[..., :a] *= np.linspace(0.0, 1.0, a)
    if b:
        y[..., n - b:] *= np.linspace(1.0, 0.0, b)
    return y


def mix(*parts: tuple[np.ndarray, float]) -> np.ndarray:
    """Sum (signal, linear gain) pairs of different lengths (mono or stereo) into one buffer."""
    n = max(p[0].shape[-1] for p in parts)
    two = any(p[0].ndim == 2 for p in parts)
    out = np.zeros((2, n) if two else n)
    for x, g in parts:
        xs = stereo(x) if two and x.ndim == 1 else x
        out[..., : xs.shape[-1]] += xs * g
    return out


def place(buf: np.ndarray, x: np.ndarray, start: int, gain: float = 1.0) -> None:
    """Add ``x`` into ``buf`` at sample ``start`` (clipped to the buffer)."""
    n = buf.shape[-1]
    if start >= n or x.shape[-1] == 0:
        return
    s0 = max(0, start)
    off = s0 - start
    m = min(x.shape[-1] - off, n - s0)
    if m <= 0:
        return
    if buf.ndim == 2 and x.ndim == 1:
        buf[:, s0:s0 + m] += gain * x[off:off + m]
    else:
        buf[..., s0:s0 + m] += gain * x[..., off:off + m]


# ------------------------------------------------------------------------ oscillators

def _phase(freq: float | np.ndarray, n: int, phase0: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    f = np.broadcast_to(np.asarray(freq, dtype=float), (n,))
    inc = f / SR
    ph = (phase0 + np.cumsum(inc) - inc) % 1.0
    return ph, np.maximum(inc, 1e-9)


def _blep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """PolyBLEP residual for a unit step at phase 0 (t = phase in [0,1), dt = increment)."""
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt[m]
    out[m] = x * x + x + x + 1.0
    return out


def saw(freq: float | np.ndarray, n: int, phase0: float = 0.0) -> np.ndarray:
    """Band-limited (PolyBLEP) sawtooth in [-1, 1]."""
    ph, dt = _phase(freq, n, phase0)
    return 2.0 * ph - 1.0 - _blep(ph, dt)


def pulse(freq: float | np.ndarray, n: int, duty: float | np.ndarray = 0.5, phase0: float = 0.0) -> np.ndarray:
    """Band-limited (PolyBLEP) pulse with variable duty; DC removed."""
    ph, dt = _phase(freq, n, phase0)
    d = np.broadcast_to(np.asarray(duty, dtype=float), (n,))
    y = np.where(ph < d, 1.0, -1.0)
    y += _blep(ph, dt)
    y -= _blep((ph - d) % 1.0, dt)
    return y - (2.0 * d - 1.0)


def sine(freq: float | np.ndarray, n: int, phase0: float = 0.0) -> np.ndarray:
    ph, _ = _phase(freq, n, phase0)
    return np.sin(2.0 * np.pi * ph)


def tri(freq: float | np.ndarray, n: int, phase0: float = 0.0, steps: int = 0) -> np.ndarray:
    """Triangle; ``steps`` > 0 quantises it (16 = NES 4-bit stepped triangle)."""
    ph, _ = _phase(freq, n, phase0)
    y = 1.0 - 4.0 * np.abs(ph - 0.5)
    if steps:
        y = np.round((y + 1.0) * (steps - 1) / 2.0) / ((steps - 1) / 2.0) - 1.0
    return y


def supersaw(freq: float | np.ndarray, n: int, voices: int = 7, detune: float = 0.18,
             seed: int = 0, spread: float = 0.8) -> np.ndarray:
    """Detuned saw stack -> stereo. ``detune`` in semitones across the stack."""
    r = np.random.default_rng(seed)
    out = np.zeros((2, n))
    offs = np.linspace(-1.0, 1.0, voices)
    for i, o in enumerate(offs):
        f = np.asarray(freq, dtype=float) * 2.0 ** (o * detune / 12.0)
        v = saw(f, n, r.random())
        pan = o * spread
        g = 1.0 if i == voices // 2 else 0.75
        out += stereo(v * g, pan)
    return out / np.sqrt(voices)


def additive(freq: float, n: int, partials: list[tuple[float, float, float]], phase_seed: int = 0) -> np.ndarray:
    """Sum of decaying sines: partials = [(ratio, amp, t60_seconds)]. Skips anything above 19 kHz."""
    t = np.arange(n) / SR
    r = np.random.default_rng(phase_seed)
    y = np.zeros(n)
    for ratio, amp, t60 in partials:
        f = freq * ratio
        if f >= 19000.0 or amp == 0.0:
            continue
        y += amp * np.sin(2 * np.pi * f * t + r.random() * 2 * np.pi) * np.exp(-6.91 * t / max(t60, 1e-4))
    return y


def noise(n: int, seed: object = 0) -> np.ndarray:
    return rng("noise", seed).standard_normal(n) * 0.5


@functools.lru_cache(maxsize=8)
def _lfsr_bits(short: bool, seed: int) -> np.ndarray:
    reg = seed & 0x7FFF or 1
    tap = 6 if short else 1
    bits = np.empty(93 if short else 32767, dtype=np.float64)
    for i in range(bits.size):
        fb = (reg & 1) ^ ((reg >> tap) & 1)
        reg = (reg >> 1) | (fb << 14)
        bits[i] = 1.0 if reg & 1 else -1.0
    return bits


def lfsr_noise(n: int, period: int = 4, short: bool = False, seed: int = 1) -> np.ndarray:
    """NES-style 15-bit LFSR noise. ``period`` = CPU cycles per shift (bigger = lower pitch)."""
    rate = 1789773.0 / period
    bits = _lfsr_bits(short, seed)
    idx = (np.arange(n) * rate / SR).astype(np.int64) % bits.size
    return bits[idx]


# -------------------------------------------------------------------------- envelopes

def adsr(n: int, a: float, d: float, s: float, r: float, gate: float | None = None, curve: float = 4.0) -> np.ndarray:
    """ADSR with exponential decay/release. ``gate`` = seconds held (default: n - release)."""
    t = np.arange(n) / SR
    g = (n / SR - r) if gate is None else gate
    g = max(g, 1e-4)
    env = np.empty(n)
    att = t < a
    env[att] = t[att] / max(a, 1e-5)
    dec = (~att) & (t < g)
    env[dec] = s + (1.0 - s) * np.exp(-curve * (t[dec] - a) / max(d, 1e-5))
    lvl_g = s + (1.0 - s) * np.exp(-curve * max(g - a, 0.0) / max(d, 1e-5)) if g > a else min(g / max(a, 1e-5), 1.0)
    rel = t >= g
    env[rel] = lvl_g * np.exp(-curve * (t[rel] - g) / max(r, 1e-5))
    return env


def perc(n: int, t60: float, attack: float = 0.001) -> np.ndarray:
    """Percussive envelope: linear attack then exponential decay to -60 dB at t60."""
    t = np.arange(n) / SR
    e = np.exp(-6.91 * t / max(t60, 1e-4))
    a = ns(attack)
    if a > 0:
        e[:a] *= np.linspace(0.0, 1.0, a)
    return e


def ramp(n: int, points: list[tuple[float, float]]) -> np.ndarray:
    """Piecewise-linear curve from (time_s, value) points over n samples."""
    t = np.arange(n) / SR
    xs, ys = zip(*points, strict=False)
    return np.interp(t, xs, ys)


# ----------------------------------------------------------------------------- filters

def _sos(kind: str, f: float | tuple[float, float], order: int = 2) -> np.ndarray:
    nyq = SR / 2.0
    if isinstance(f, tuple):
        wn = (max(f[0], 5.0) / nyq, min(f[1], nyq * 0.98) / nyq)
    else:
        wn = min(max(f, 5.0), nyq * 0.98) / nyq
    return signal.butter(order, wn, btype=kind, output="sos")


def lp(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("lowpass", f, order), x, axis=-1)


def hp(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("highpass", f, order), x, axis=-1)


def bp(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("bandpass", (lo, hi), order), x, axis=-1)


def _rbj(kind: str, f0: float, q: float = 0.707, gain_db: float = 0.0) -> np.ndarray:
    """RBJ cookbook biquad as one SOS row."""
    a_ = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * min(max(f0, 10.0), SR * 0.49) / SR
    cw, sw = np.cos(w0), np.sin(w0)
    al = sw / (2 * q)
    if kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + al, -2 * cw, 1 - al]
    elif kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + al, -2 * cw, 1 - al]
    elif kind == "bp":
        b = [al, 0.0, -al]; a = [1 + al, -2 * cw, 1 - al]
    elif kind == "peak":
        b = [1 + al * a_, -2 * cw, 1 - al * a_]; a = [1 + al / a_, -2 * cw, 1 - al / a_]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * np.sqrt(a_) * al
        if kind == "lowshelf":
            b = [a_ * ((a_ + 1) - (a_ - 1) * cw + sq), 2 * a_ * ((a_ - 1) - (a_ + 1) * cw), a_ * ((a_ + 1) - (a_ - 1) * cw - sq)]
            a = [(a_ + 1) + (a_ - 1) * cw + sq, -2 * ((a_ - 1) + (a_ + 1) * cw), (a_ + 1) + (a_ - 1) * cw - sq]
        else:
            b = [a_ * ((a_ + 1) + (a_ - 1) * cw + sq), -2 * a_ * ((a_ - 1) + (a_ + 1) * cw), a_ * ((a_ + 1) + (a_ - 1) * cw - sq)]
            a = [(a_ + 1) - (a_ - 1) * cw + sq, 2 * ((a_ - 1) - (a_ + 1) * cw), (a_ + 1) - (a_ - 1) * cw - sq]
    else:
        raise ValueError(kind)
    b = np.asarray(b) / a[0]
    a = np.asarray(a) / a[0]
    return np.concatenate([b, a])[None, :]


def eq(x: np.ndarray, kind: str, f0: float, gain_db: float = 0.0, q: float = 0.707) -> np.ndarray:
    """Static RBJ biquad (lp/hp/bp/peak/lowshelf/highshelf)."""
    return signal.sosfilt(_rbj(kind, f0, q, gain_db), x, axis=-1)


def sweep(x: np.ndarray, cutoff: np.ndarray, q: float = 0.8, kind: str = "lp", block: int = 128) -> np.ndarray:
    """Time-varying resonant biquad; ``cutoff`` is per-sample Hz (evaluated per block, state carried)."""
    mono = x.ndim == 1
    xs = x[None, :] if mono else x
    n = xs.shape[-1]
    y = np.empty_like(xs)
    zi = np.zeros((xs.shape[0], 1, 2))
    for s in range(0, n, block):
        e = min(s + block, n)
        sos = _rbj(kind, float(cutoff[min(s + block // 2, n - 1)]), q)
        for c in range(xs.shape[0]):
            y[c, s:e], zi[c] = signal.sosfilt(sos, xs[c, s:e], zi=zi[c])
    return y[0] if mono else y


# ------------------------------------------------------------------------------ effects

def drive(x: np.ndarray, amount: float = 2.0) -> np.ndarray:
    """tanh saturation normalised to unity small-signal gain."""
    return np.tanh(x * amount) / np.tanh(amount)


def reverb_ir(seconds: float, predelay: float = 0.012, damp: float = 0.55, seed: str = "ir",
              early: int = 10) -> np.ndarray:
    """Synthetic stereo room/plate impulse response (decorrelated decaying noise, frequency-dependent decay)."""
    n = ns(seconds * 1.15 + predelay)
    t = np.arange(n) / SR
    r = rng("ir", seed)
    ir = np.zeros((2, n))
    pd = ns(predelay)
    for c in range(2):
        w = r.standard_normal(n)
        lo = lp(w, 700.0); hi = hp(w, 4000.0); mid = w - lo - hi
        tail = (lo * np.exp(-6.91 * t / (seconds * 1.15)) + mid * np.exp(-6.91 * t / seconds)
                + hi * np.exp(-6.91 * t / max(seconds * (1.0 - damp), 0.08)))
        tail[:pd] = 0.0
        ir[c] = tail
        for _ in range(early):
            k = pd + int(r.random() * ns(0.06))
            if k < n:
                ir[c, k] += (r.random() * 2 - 1) * 2.5
    # Keep the two channels partially correlated so a mono fold doesn't hollow out (corr > 0.3 target).
    m = (ir[0] + ir[1]) * 0.5
    ir = np.vstack([0.55 * ir[0] + 0.45 * m, 0.55 * ir[1] + 0.45 * m])
    ir /= np.sqrt(np.sum(ir ** 2) / 2.0)
    return ir


def convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """FFT convolution (stereo IR). Output keeps the length of x (tail beyond is dropped)."""
    xs = stereo(x)
    n = xs.shape[-1]
    out = np.vstack([signal.oaconvolve(xs[c], ir[c])[:n] for c in range(2)])
    return out


def delay(x: np.ndarray, seconds: float, feedback: float = 0.35, taps: int = 6, lowpass: float = 5000.0,
          pingpong: float = 0.3) -> np.ndarray:
    """Feedback delay built from summed taps (wet only, stereo). ``pingpong`` alternates pan."""
    xs = stereo(x)
    n = xs.shape[-1]
    d = ns(seconds)
    out = np.zeros_like(xs)
    src = lp(xs, lowpass)
    for k in range(1, taps + 1):
        g = feedback ** (k - 1)
        sh = d * k
        if sh >= n:
            break
        p = pingpong if k % 2 else -pingpong
        seg = src[:, : n - sh] * g
        out[0, sh:] += seg[0] * (1 - p)
        out[1, sh:] += seg[1] * (1 + p)
        if k % 2 == 0:
            src = lp(src, lowpass * 0.85)
    return out


def pump(n: int, hits: list[float], depth: float = 0.5, release: float = 0.22, attack: float = 0.004) -> np.ndarray:
    """Sidechain 'pump' gain curve: dips by ``depth`` at each hit time (s) and recovers over ``release``."""
    t = np.arange(n) / SR
    g = np.ones(n)
    hits = sorted(hits)
    for i, h in enumerate(hits):
        s0 = ns(h)
        if s0 >= n:
            break
        s1 = ns(hits[i + 1]) if i + 1 < len(hits) else n
        s1 = min(s1, n)
        tt = t[s0:s1] - h
        shape = np.where(tt < attack, tt / attack, 1.0) * np.exp(-((np.maximum(tt - attack, 0.0)) / release) ** 2 * 2.5)
        g[s0:s1] = np.minimum(g[s0:s1], 1.0 - depth * shape)
    return g


# ------------------------------------------------------------------- loudness & peaks

_K1 = (np.array([1.53512485958697, -2.69169618940638, 1.19839281085285]),
       np.array([1.0, -1.69065929318241, 0.73248077421585]))
_K2 = (np.array([1.0, -2.0, 1.0]), np.array([1.0, -1.99004745483398, 0.99007225036621]))


def lufs(x: np.ndarray) -> float:
    """ITU-R BS.1770-4 integrated loudness (48 kHz, mono or stereo)."""
    xs = stereo(x) if x.ndim == 1 else x
    if x.ndim == 1:
        xs = np.vstack([x, np.zeros_like(x)])
    y = signal.lfilter(*_K2, signal.lfilter(*_K1, xs, axis=-1), axis=-1)
    blk, hop = ns(0.4), ns(0.1)
    if y.shape[-1] < blk:
        return -70.0
    p = y ** 2
    cs = np.concatenate([np.zeros((2, 1)), np.cumsum(p, axis=-1)], axis=-1)
    starts = np.arange(0, y.shape[-1] - blk + 1, hop)
    z = (cs[:, starts + blk] - cs[:, starts]) / blk
    zz = z.sum(axis=0)
    lk = -0.691 + 10 * np.log10(np.maximum(zz, 1e-20))
    g = zz[lk > -70.0]
    if g.size == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(g.mean()) - 10.0
    g2 = zz[(lk > -70.0) & (lk > rel)]
    return float(-0.691 + 10 * np.log10(g2.mean())) if g2.size else -70.0


def true_peak_db(x: np.ndarray) -> float:
    """4x-oversampled peak in dBTP."""
    up = signal.resample_poly(np.atleast_2d(x), 4, 1, axis=-1)
    return float(20 * np.log10(max(np.max(np.abs(up)), 1e-12)))


def short_term_max(x: np.ndarray) -> float:
    """Max 3 s short-term loudness (LUFS) - used to normalise SFX."""
    xs = np.vstack([x, x]) / np.sqrt(2) if x.ndim == 1 else x
    y = signal.lfilter(*_K2, signal.lfilter(*_K1, xs, axis=-1), axis=-1)
    w = min(ns(3.0), y.shape[-1])
    w = max(w, ns(0.4)) if y.shape[-1] >= ns(0.4) else y.shape[-1]
    p = (y ** 2).sum(axis=0)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    if w <= 0:
        return -70.0
    vals = (cs[w:] - cs[:-w]) / w
    return float(-0.691 + 10 * np.log10(max(vals.max(), 1e-20)))
