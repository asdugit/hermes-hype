"""Song framework: a bar grid with named sections, tracks with sends/pump/automation, and the final render.

A composition (see ``beds/``) builds a :class:`Song`, adds notes to tracks with instrument functions,
then calls :meth:`Song.render` which mixes the tracks through shared reverb/delay buses and masters the
result. The bar layout is exported as ``bars.json`` so the runtime can cut the bed on whole bars.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

import numpy as np

from . import dsp as D
from .dsp import SR, ns
from .master import band_shares, lr_corr, master, mono_fold_db, phone_band_share, section_loudness


@dataclass
class Section:
    name: str
    start_bar: int
    bars: int
    energy: float


@dataclass
class Track:
    """One instrument bus. ``buf`` is stereo float32; effects are applied at render time."""
    name: str
    n: int
    gain_db: float = 0.0
    pan: float = 0.0
    reverb: float = 0.0            # send level (linear)
    delay: float = 0.0             # send level (linear)
    pump: float = 0.0              # sidechain depth 0..1 keyed from Song.kicks
    hp: float | None = None
    lp: float | None = None
    width: float = 1.0
    sweep: list[tuple[float, float]] = field(default_factory=list)   # (time_s, cutoff_hz) low-pass automation
    gain: list[tuple[float, float]] = field(default_factory=list)    # (time_s, dB) automation
    buf: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.buf = np.zeros((2, self.n), dtype=np.float32)

    def add(self, x: np.ndarray, t: float, gain_db: float = 0.0, pan: float | None = None) -> None:
        """Mix a mono/stereo buffer in at time ``t`` (s)."""
        s = D.stereo(x, self.pan if pan is None else pan) if x.ndim == 1 else x
        D.place(self.buf, s.astype(np.float32), ns(t), D.db(gain_db))


class Song:
    """Bar grid + tracks for one bed."""

    def __init__(self, bed_id: str, style: str, bpm: float, key_label: str,
                 layout: list[tuple[str, int, float]], tail_s: float = 4.0, beats_per_bar: int = 4,
                 title: str = "", notes: str = ""):
        self.id, self.style, self.bpm, self.key_label = bed_id, style, float(bpm), key_label
        self.beats_per_bar = beats_per_bar
        self.beat = 60.0 / self.bpm
        self.bar = self.beat * beats_per_bar
        self.sections: list[Section] = []
        b = 0
        for name, bars, energy in layout:
            self.sections.append(Section(name, b, bars, energy))
            b += bars
        self.total_bars = b
        self.tail_s = tail_s
        self.n = ns(self.total_bars * self.bar + tail_s)
        self.tracks: dict[str, Track] = {}
        self.kicks: list[float] = []
        self.title, self.notes = title, notes
        self.reverb_ir = D.reverb_ir(2.4, 0.018, 0.55, seed=bed_id)
        self.delay_time = self.beat * 0.75

    # ------------------------------------------------------------------ grid helpers
    def t(self, bar: float, beat: float = 0.0) -> float:
        """Seconds at ``bar`` (0-based, may be fractional) + ``beat`` beats."""
        return bar * self.bar + beat * self.beat

    def sec(self, name: str) -> Section:
        return next(s for s in self.sections if s.name == name)

    def bars(self, *names: str) -> list[tuple[int, Section, int]]:
        """[(absolute bar, section, bar index within section)] for the named sections (all if none)."""
        out = []
        for s in self.sections:
            if names and s.name not in names:
                continue
            out += [(s.start_bar + i, s, i) for i in range(s.bars)]
        return out

    def track(self, name: str, **kw: object) -> Track:
        if name not in self.tracks:
            self.tracks[name] = Track(name, self.n, **kw)  # type: ignore[arg-type]
        return self.tracks[name]

    def kick_at(self, tr: Track, t: float, x: np.ndarray, gain_db: float = 0.0) -> None:
        """Add a kick and register it as a sidechain key."""
        tr.add(x, t, gain_db)
        self.kicks.append(t)

    # ------------------------------------------------------------------------ render
    def _process(self, tr: Track) -> tuple[np.ndarray, np.ndarray]:
        x = tr.buf.astype(np.float64)
        if tr.hp:
            x = D.hp(x, tr.hp)
        if tr.lp:
            x = D.lp(x, tr.lp)
        if tr.sweep:
            cut = D.ramp(self.n, tr.sweep)
            x = D.sweep(x, cut, q=0.9, block=256)
        if tr.width != 1.0:
            x = D.width(x, tr.width)
        if tr.pump > 0 and self.kicks:
            x *= D.pump(self.n, self.kicks, tr.pump, release=self.beat * 0.55)[None, :]
        g = np.full(self.n, D.db(tr.gain_db))
        if tr.gain:
            g *= 10 ** (D.ramp(self.n, tr.gain) / 20.0)
        x *= g[None, :]
        return x, x

    def render(self, target_lufs: float = -16.0, progress: Callable[[str], None] | None = None) -> tuple[np.ndarray, dict]:
        """Mix all tracks (+ reverb/delay buses) and master. Returns (stereo, report)."""
        dry = np.zeros((2, self.n))
        rev = np.zeros((2, self.n))
        dly = np.zeros((2, self.n))
        for tr in self.tracks.values():
            if progress:
                progress(tr.name)
            x, _ = self._process(tr)
            dry += x
            if tr.reverb:
                rev += x * tr.reverb
            if tr.delay:
                dly += x * tr.delay
            tr.buf = np.zeros((2, 1), dtype=np.float32)   # free memory early
        if np.any(dly):
            dry += D.delay(dly, self.delay_time, 0.38, 6, 4500.0, 0.25)
            rev += D.delay(dly, self.delay_time, 0.38, 6, 4500.0, 0.25) * 0.3
        if np.any(rev):
            dry += D.convolve(D.hp(rev, 180.0), self.reverb_ir) * 0.9
        lift = self._lift_quiet_sections(dry)
        y, rep = master(dry, target_lufs, -1.5)
        rep["section_lift_db"] = lift
        edges = [(s.name, s.start_bar * self.bar, (s.start_bar + s.bars) * self.bar) for s in self.sections]
        rep.update({"mono_fold_db": mono_fold_db(y), "bands": band_shares(y), "section_lufs": section_loudness(y, edges)})
        return y, rep

    def _lift_quiet_sections(self, x: np.ndarray, max_gap: float = 3.5) -> dict[str, float]:
        """Raise intro/outro so they sit no more than ``max_gap`` LU under A/B (beds must stay audible
        under narration from the first bar); ramps finish on the section boundaries."""
        lifts: dict[str, float] = {}
        names = {s.name for s in self.sections}
        g = np.zeros(self.n)
        for sec, ref in (("intro", "A"), ("outro", "B")):
            if sec not in names or ref not in names:
                continue
            a, r = self.sec(sec), self.sec(ref)
            la = D.lufs(x[:, ns(self.t(a.start_bar)):ns(self.t(a.start_bar + a.bars))])
            lr = D.lufs(x[:, ns(self.t(r.start_bar)):ns(self.t(r.start_bar + r.bars))])
            lift = float(np.clip(lr - max_gap - la, 0.0, 6.0))
            if lift <= 0.05:
                continue
            lifts[sec] = round(lift, 2)
            t0, t1 = self.t(a.start_bar), self.t(a.start_bar + a.bars)
            ramp = 0.3
            pts = [(0.0, 0.0), (max(t0 - ramp, 0.0), 0.0), (t0, lift), (t1 - ramp, lift), (t1, 0.0), (self.n / SR, 0.0)]
            if t0 <= 0.0:
                pts = [(0.0, lift), (t1 - ramp, lift), (t1, 0.0), (self.n / SR, 0.0)]
            g += D.ramp(self.n, pts)
        if lifts:
            x *= (10 ** (g / 20.0))[None, :]
        return lifts

    def bars_json(self, file: str, report: dict) -> dict:
        """Metadata the runtime bar-fitter needs (``assets/audio/beds/<style>/bars.json`` entry)."""
        drop = self.sec("drop").start_bar
        return {
            "id": self.id, "style": self.style, "title": self.title, "file": file, "sr": SR,
            "bpm": self.bpm, "beats_per_bar": self.beats_per_bar, "bar_s": round(self.bar, 6),
            "key": self.key_label, "total_bars": self.total_bars, "tail_s": self.tail_s,
            "duration_s": round(self.n / SR, 3), "drop_bar": drop, "end_bar": self.sec("end").start_bar,
            "sections": [{"name": s.name, "start_bar": s.start_bar, "bars": s.bars, "energy": s.energy}
                         for s in self.sections],
            "loop_unit_bars": 2, "lufs": report.get("lufs"), "true_peak_db": report.get("true_peak_db"),
            "phone_band": report.get("phone_band"), "lr_corr": report.get("lr_corr"), "notes": self.notes,
        }


__all__ = ["Song", "Track", "Section", "phone_band_share", "lr_corr"]
