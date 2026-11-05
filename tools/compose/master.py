"""Mastering chain and dev-time QC metrics for composed beds and SFX."""
from __future__ import annotations

import numpy as np
from scipy import ndimage, signal

from .dsp import SR, bp, db, eq, hp, lp, lufs, ns, true_peak_db


def mono_below(x: np.ndarray, f: float = 120.0) -> np.ndarray:
    """Sum everything below ``f`` to mono (4th-order Linkwitz-Riley split keeps the sum flat)."""
    sos_lo = signal.butter(2, f / (SR / 2), "lowpass", output="sos")
    sos_hi = signal.butter(2, f / (SR / 2), "highpass", output="sos")
    lo = signal.sosfilt(sos_lo, signal.sosfilt(sos_lo, x, axis=-1), axis=-1)
    hi = signal.sosfilt(sos_hi, signal.sosfilt(sos_hi, x, axis=-1), axis=-1)
    m = lo.mean(axis=0)
    return hi + m[None, :]


def limiter(x: np.ndarray, ceiling_db: float = -1.8, lookahead: float = 0.005, release: float = 0.08) -> np.ndarray:
    """True-peak-aware look-ahead limiter (4x oversampled detection, block release recursion)."""
    up = signal.resample_poly(x, 4, 1, axis=-1)
    pk = np.abs(up).max(axis=0)
    n = x.shape[-1]
    pk = pk[: n * 4].reshape(-1, 4).max(axis=1) if pk.size >= n * 4 else np.pad(pk, (0, n * 4 - pk.size)).reshape(-1, 4).max(axis=1)
    ceil = db(ceiling_db)
    g = np.minimum(1.0, ceil / np.maximum(pk, 1e-12))
    if g.min() >= 1.0:
        return x
    blk = 32
    m = int(np.ceil(n / blk))
    gb = np.pad(g, (0, m * blk - n), constant_values=1.0).reshape(m, blk).min(axis=1)
    a = 1.0 - np.exp(-blk / (release * SR))
    env = np.empty(m)
    cur = 1.0
    for i in range(m):
        cur = min(gb[i], cur + (1.0 - cur) * a)
        env[i] = cur
    env = np.repeat(env, blk)[:n]
    L = ns(lookahead)
    env = ndimage.minimum_filter1d(env, 2 * L + 1)
    win = np.hanning(2 * L + 3)[1:-1]
    win /= win.sum()
    env = np.convolve(env, win, mode="same")
    return x * env[None, :]


def master(x: np.ndarray, target_lufs: float = -16.0, ceiling_dbtp: float = -1.5, fade_out: float = 0.0,
           phone_min: float = 0.5) -> tuple[np.ndarray, dict]:
    """HPF 28 Hz -> mono < 120 Hz -> phone-band guard -> 20 kHz FIR -> loudness -> TP limiter (verified)."""
    y = hp(x, 28.0)
    y = y - y.mean(axis=-1, keepdims=True)
    y = mono_below(y, 120.0)
    shelf = 0.0
    while phone_band_share(y) < phone_min + 0.02 and shelf > -6.0:
        y = eq(y, "lowshelf", 220.0, -1.0, 0.7)
        shelf -= 1.0
    fir = signal.firwin(255, 19500.0, fs=SR)
    y = signal.oaconvolve(y, fir[None, :], axes=-1)[:, 127:127 + y.shape[-1]]
    ceiling = ceiling_dbtp - 0.4
    z = y
    for _ in range(4):
        z = y * db(target_lufs - lufs(y))
        z = limiter(z, ceiling)
        z = z * db(target_lufs - lufs(z))
        z = limiter(z, ceiling)
        tp = true_peak_db(z)
        if tp <= ceiling_dbtp:
            break
        ceiling -= 0.3
    fi = ns(0.004)
    z[:, :fi] *= np.linspace(0, 1, fi)
    if fade_out > 0:
        fo = ns(fade_out)
        z[:, -fo:] *= np.linspace(1, 0, fo) ** 2
    return z, {"lufs": round(lufs(z), 2), "true_peak_db": round(true_peak_db(z), 2), "lowshelf_db": shelf,
               "phone_band": round(phone_band_share(z), 3), "lr_corr": round(lr_corr(z), 3)}


def phone_band_share(x: np.ndarray) -> float:
    """Energy share in 300 Hz-9 kHz (4th-order HP 300 + LP 9k) of the mono fold."""
    m = x.mean(axis=0) if x.ndim == 2 else x
    b = lp(hp(m, 300.0, 4), 9000.0, 4)
    return float(np.sum(b ** 2) / max(np.sum(m ** 2), 1e-20))


def lr_corr(x: np.ndarray) -> float:
    """Pearson correlation between L and R (1 = mono)."""
    if x.ndim == 1:
        return 1.0
    a, b = x[0] - x[0].mean(), x[1] - x[1].mean()
    return float(np.sum(a * b) / max(np.sqrt(np.sum(a * a) * np.sum(b * b)), 1e-20))


def mono_fold_db(x: np.ndarray) -> float:
    """Loudness change when folded to mono (>= -3 dB is healthy)."""
    m = x.mean(axis=0)
    return round(lufs(np.vstack([m, m])) - lufs(x), 2)


def band_shares(x: np.ndarray) -> dict[str, float]:
    m = x.mean(axis=0)
    tot = max(np.sum(m ** 2), 1e-20)
    sub = lp(m, 60.0, 4); bass = bp(m, 60.0, 250.0, 2); pres = bp(m, 4000.0, 8000.0, 2)
    return {"sub": round(float(np.sum(sub ** 2) / tot), 3), "bass": round(float(np.sum(bass ** 2) / tot), 3),
            "presence": round(float(np.sum(pres ** 2) / tot), 3)}



def section_loudness(x: np.ndarray, edges_s: list[tuple[str, float, float]]) -> dict[str, float]:
    """Integrated loudness per section (name, t0, t1)."""
    out = {}
    for name, a, b in edges_s:
        seg = x[:, ns(a):ns(b)]
        out[name] = round(lufs(seg), 1) if seg.shape[-1] > ns(0.5) else -70.0
    return out
