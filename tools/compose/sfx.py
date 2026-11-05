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
}

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
}


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


def build_kit(out: Path, progress: Callable[[str], None] | None = print) -> dict:
    """Render, normalise, encode every sound; write ``sfx.json``. Returns the metadata."""
    out.mkdir(parents=True, exist_ok=True)
    meta: dict = {"version": 1, "sr": SR, "lufs_target": LUFS_TARGET, "classes": {"hero": [-6.0, 0.0], "foley": [-18.0, -8.0]},
                  "styles": STYLE_MAP, "sounds": {}}
    for name, spec in KIT.items():
        variants = []
        for k in range(spec["n"]):
            x, st = _normalise(spec["fn"](k))
            pad = np.zeros((2, ns(0.02)))
            x = np.concatenate([x, pad], axis=1)
            f = f"{name}_{k + 1}.ogg"
            encode(x, out / f, "opus", "96k")
            dec = decode(out / f)
            sp = _sync_points(dec, spec["sync"])
            variants.append({"file": f, "dur": round(dec.shape[-1] / SR, 4), **sp, "st_lufs": round(st, 1)})
        meta["sounds"][name] = {"class": spec["cls"], "gain_db": spec["gain"], "sync": spec["sync"], "tags": spec["tags"],
                                "variants": variants}
        if progress:
            progress(f"sfx {name}: {len(variants)} variant(s)")
    (out / "sfx.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    return meta
