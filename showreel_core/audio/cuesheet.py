"""Multi-segment music for style-switching films: render a film.json ``music`` cue sheet (stdlib + ffmpeg).

    [{"bed": "pixel_boss", "t0": 0, "t1": 22.5}, {"sting": "bloom_riser", "t": 21.2}, {"bed": "dream", "t0": 22.5, "t1": 45}]

Every bed segment is bar-fitted to its own span with its own tempo; its first downbeat lands on the segment
start. Joins between segments are designed, never a blind crossfade:

* **sting join** - a sting whose impact is within ``STING_WINDOW_S`` of a switch: the outgoing bed fades out
  under the riser (a ~0.9 s suck-out ending ``STING_GAP_S`` before the impact), the impact lands exactly on
  the sting's ``t`` and the incoming bed starts on its downbeat at ``max(switch, impact)``; between an early
  impact and the switch only the sting's shimmer rings. The sting variant in the incoming bed's key wins.
* **downbeat crossfade** - no sting: the outgoing bed fades out over up to one beat, ending 5 ms before the
  switch (or on its own last bar line if that falls just before the switch), and the incoming bed starts on
  its downbeat at the switch.
* **gap** - a gap of >= 0.25 s between segments: the outgoing bed plays its own end hit before the gap and
  rings into it.

Outgoing segments end on their outro (pixel_boss's outro is the bVI-bVII 'victory approach', which is also
V of the relative major: with key pairing, ``dream`` resolves it). The final segment ends with its end hit
on a bar line after the last word (``plan_bars``) and rings to the end of the film.
Stings rendered here are part of the music track (they are returned in ``consumed`` so callers don't also
place them as SFX).
"""
from __future__ import annotations

import math
from array import array
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ffmpeg_io import SR, AudioError, decode_f32, write_wav_f32
from .music import MIN_RING_S, PRE_S, Bed, BarPlan, plan_bars, render_bars, resolve_bed
from .sfx import Kit, SfxSound, load_kit, sync_time

STING_WINDOW_S = 2.5        # a sting this close to a switch designs that join
STING_GAP_S = 0.12          # outgoing music is silent this long before a sting impact
STING_FADE_S = 0.9          # outgoing fade-out length under a riser
STING_OVER_BED_DB = 1.0     # sting short-term max vs the bed's integrated loudness
STING_DIP_DB = -3.0         # bed dip around a sting impact inside a segment
GAP_JOIN_S = 0.25           # gaps shorter than this are closed (the incoming bed wins)
MIN_SEGMENT_S = 0.5

Resolver = Callable[[str, int, "str | None"], "Bed | None"]


@dataclass
class StingCue:
    name: str
    t: float
    gain_db: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SegmentPlan:
    """One bed segment after join design (pure data; see :func:`plan_cue_sheet`)."""
    ref: str
    bed: Bed
    t0: float                 # requested span
    t1: float
    anchor: float             # first downbeat (audio starts here)
    end: float                # audio ends here (fade/ring included)
    join_in: str              # start | crossfade | sting | gap
    join_out: str             # final | crossfade | sting | gap
    closed: bool              # True: the bed's own end hit plays (final segment, gap join)
    fade_out_s: float = 0.0   # open segments: equal-power fade ending at ``end``
    plan: BarPlan | None = None
    sting: StingCue | None = None    # the sting designing this segment's outgoing join

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.anchor)


@dataclass
class CuePlan:
    segments: list[SegmentPlan]
    stings: list[StingCue]
    warnings: list[str] = field(default_factory=list)


@dataclass
class FittedSegment:
    """A rendered segment and its beat grid (film seconds)."""
    bed_id: str
    family: str
    key: str
    bpm: float
    bar_s: float
    beats_per_bar: int
    t0: float
    t1: float
    downbeats: list[float]
    sections: list[dict[str, Any]]
    source_bars: list[int]
    join_in: str
    join_out: str
    end_time: float | None = None    # final segment: the end hit

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PlacedSting:
    name: str
    file: str
    t: float                 # impact time (film seconds)
    start: float             # file start on the film timeline
    gain_db: float
    key: str = ""
    join: bool = False       # True: designs a switch

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class FittedCueSheet:
    """Result of :func:`fit_cue_sheet`: the music WAV plus per-segment downbeat grids."""
    path: Path
    duration: float
    segments: list[FittedSegment]
    stings: list[PlacedSting]
    consumed: list[dict[str, Any]]
    lufs: float = -16.0
    warnings: list[str] = field(default_factory=list)

    @property
    def downbeats(self) -> list[float]:
        return sorted(d for s in self.segments for d in s.downbeats)

    @property
    def bed_id(self) -> str:
        return "+".join(s.bed_id for s in self.segments)

    @property
    def bpm(self) -> float:
        return self.segments[0].bpm if self.segments else 0.0

    def segment_at(self, t: float) -> FittedSegment | None:
        """The segment whose audio is playing at film time ``t`` (the later one at a switch)."""
        hit = [s for s in self.segments if s.t0 - 1e-6 <= t < s.t1]
        return hit[-1] if hit else None

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "duration": self.duration, "bed_id": self.bed_id, "lufs": self.lufs,
                "segments": [s.to_dict() for s in self.segments], "stings": [s.to_dict() for s in self.stings],
                "consumed": self.consumed, "downbeats": self.downbeats, "warnings": self.warnings}


# ------------------------------------------------------------------------------- parsing

def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse_cue_sheet(cue_sheet: Sequence[Any], film_dur: float) -> tuple[list[tuple[str, float, float]],
                                                                          list[StingCue], list[str]]:
    """Split a film.json ``music`` list into bed spans and stings (clamped to the film, sorted)."""
    beds: list[tuple[str, float, float]] = []
    stings: list[StingCue] = []
    warns: list[str] = []
    for i, m in enumerate(cue_sheet or []):
        if not isinstance(m, Mapping):
            continue
        if m.get("bed"):
            t0 = max(0.0, _num(m.get("t0")) or 0.0)
            t1 = _num(m.get("t1"))
            t1 = film_dur if t1 is None else min(film_dur, t1)
            if t1 - t0 < MIN_SEGMENT_S:
                warns.append(f"music[{i}] bed '{m['bed']}' spans {t1 - t0:.2f} s: skipped")
                continue
            beds.append((str(m["bed"]), t0, t1))
        elif m.get("sting"):
            t = _num(m.get("t"))
            if t is None or not 0.0 <= t <= film_dur:
                warns.append(f"music[{i}] sting '{m['sting']}' has no time inside the film: skipped")
                continue
            stings.append(StingCue(str(m["sting"]), t, _num(m.get("gain_db", m.get("gain"))) or 0.0, dict(m)))
    beds.sort(key=lambda b: (b[1], b[2]))
    stings.sort(key=lambda s: s.t)
    return beds, stings, warns


# ------------------------------------------------------------------------------- planning

def _beat(bed: Bed) -> float:
    return bed.bar_s / max(bed.beats_per_bar, 1)


def plan_open(bed: Bed, length: float, drop_time: float | None = None) -> BarPlan:
    """Bars for a segment that hands over to another bed after ``length`` s: intro -> ... -> outro with no end
    hit; enough extra bars (repeats of the last one) to cover a partial final bar."""
    bar = bed.bar_s
    n_full = int(math.floor(length / bar + 1e-9))
    frac = length / bar - n_full
    n = max(1, n_full + (1 if frac > 0.5 else 0))
    base = plan_bars(bed, n * bar + MIN_RING_S + 1e-6, drop_time, None)
    src = list(base.source_bars)
    labels = list(base.labels)
    if not src:                                  # shorter than a bar: play from the drop
        d0 = bed.section("drop")[0]
        src, labels = [d0], ["drop"]
    cover = int(math.ceil(length / bar + 1e-9)) + 1
    while len(src) < cover:
        src.append(src[-1])
        labels.append(labels[-1])
    return BarPlan(src, labels, len(src), base.drop_bar, list(base.warnings))


def plan_cue_sheet(cue_sheet: Sequence[Any], film_dur: float, resolve: Resolver, *, seed: int = 0,
                   last_word_time: float | None = None, drop_times: Sequence[float] = (),
                   fallback: str | None = None, sting_window: float = STING_WINDOW_S) -> CuePlan:
    """Design segments and joins for a cue sheet. Pure (``resolve(ref, seed, prefer_key) -> Bed``); unit-tested."""
    spans, stings, warns = parse_cue_sheet(cue_sheet, film_dur)
    segs: list[SegmentPlan] = []
    prev: Bed | None = None
    for i, (ref, t0, t1) in enumerate(spans):
        bed = resolve(ref, seed + i, prev.cadence_to if prev and prev.cadence_to else None)
        if bed is None:
            warns.append(f"unknown music bed '{ref}': skipped")
            continue
        segs.append(SegmentPlan(ref, bed, t0, t1, t0, t1, "crossfade", "crossfade", False))
        prev = bed
    if not segs:
        bed = resolve(fallback or "launch", seed, None) or resolve("launch", seed, None)
        if bed is None:
            return CuePlan([], stings, warns + ["no music bed could be resolved"])
        if spans:
            warns.append(f"no cue-sheet bed resolved; using '{bed.id}' for the whole film")
        segs = [SegmentPlan(bed.id, bed, 0.0, film_dur, 0.0, film_dur, "start", "final", True)]
    # ---- overlaps and tiny gaps: the incoming bed wins
    for a, b in zip(segs, segs[1:], strict=False):
        if a.t1 > b.t0 or b.t0 - a.t1 < GAP_JOIN_S:
            a.t1 = b.t0
    segs = [s for s in segs if s.t1 - s.t0 >= MIN_SEGMENT_S] or segs[:1]
    last = segs[-1]
    if film_dur - last.t1 > 0.5:
        warns.append(f"last bed '{last.ref}' extended from {last.t1:g} s to the end of the film")
    last.t1 = film_dur
    # ---- joins
    used: set[int] = set()
    segs[0].join_in = "start"
    segs[0].anchor = segs[0].t0
    for a, b in zip(segs, segs[1:], strict=False):
        switch = b.t0
        if switch - a.t1 >= GAP_JOIN_S:
            a.join_out, b.join_in, a.closed = "gap", "gap", True
            a.end, b.anchor = switch, switch
            continue
        near = [(abs(s.t - switch), k) for k, s in enumerate(stings) if k not in used and abs(s.t - switch) <= sting_window]
        if near:
            _d, k = min(near)
            used.add(k)
            st = stings[k]
            a.join_out, b.join_in, a.sting = "sting", "sting", st
            end = min(switch, st.t) - STING_GAP_S
            k_bar = math.floor((end - a.anchor) / a.bed.bar_s + 1e-9)
            bar_line = a.anchor + k_bar * a.bed.bar_s
            if k_bar >= 1 and 0.0 < end - bar_line < 0.35 * a.bed.bar_s:
                end = bar_line - PRE_S             # stop on a bar line: no stray downbeat before the impact
            a.end = max(a.anchor + 0.05, end)
            a.fade_out_s = min(STING_FADE_S, max(0.05, a.end - a.anchor))
            b.anchor = max(switch, st.t) if st.t < b.t1 - 1.0 else switch
            if b.anchor > switch + 1e-6:
                warns.append(f"'{b.bed.id}' starts on the sting impact at {st.t:g} s (cue sheet said {switch:g} s)")
        else:
            a.join_out, b.join_in = "crossfade", "crossfade"
            beat = _beat(a.bed)
            k_bar = math.floor((switch - a.anchor) / a.bed.bar_s + 1e-9)
            bar_line = a.anchor + k_bar * a.bed.bar_s
            end = switch - PRE_S
            if 0.0 < switch - bar_line < 0.3 * beat and k_bar >= 1:
                end = bar_line - PRE_S
            a.end = max(a.anchor + 0.05, end)
            a.fade_out_s = min(beat, 0.5, max(0.03, a.end - a.anchor))
            b.anchor = switch
    last.join_out, last.closed, last.end = "final", True, film_dur
    # ---- bar plans
    for s in segs:
        L = s.end - s.anchor
        drop = next((d - s.anchor for d in drop_times if s.anchor + s.bed.bar_s < d < s.end - s.bed.bar_s), None)
        if s is last:
            lw = None if last_word_time is None else last_word_time - s.anchor
            s.plan = plan_bars(s.bed, L, drop, lw if lw is None or lw > 0 else None)
        elif s.closed:
            ring = min(MIN_RING_S, max(0.3, s.end - s.t1))
            s.plan = plan_bars(s.bed, L, drop, None, min_ring=ring)
        else:
            s.plan = plan_open(s.bed, L, drop)
        warns += [f"{s.bed.id}: {w}" for w in s.plan.warnings]
    return CuePlan(segs, stings, warns)


# ------------------------------------------------------------------------------- rendering

def _choose_variant(snd: SfxSound, key: str, k: int) -> dict[str, Any]:
    if key:
        for v in snd.variants:
            if str(v.get("key", "")).lower() == key.lower():
                return v
    return snd.variants[k % len(snd.variants)]


def _fade_out(buf: array, n0: int, n1: int) -> None:
    """Equal-power (cos) fade over frames [n0, n1) and silence after (interleaved stereo, in place)."""
    n = max(1, n1 - n0)
    for k in range(max(0, n0), min(n1, len(buf) // 2)):
        g = math.cos(0.5 * math.pi * (k - n0 + 1) / n)
        buf[2 * k] *= g
        buf[2 * k + 1] *= g
    z = max(0, n1)
    if z < len(buf) // 2:
        buf[2 * z:] = array("f", bytes(4 * (len(buf) - 2 * z)))


def _dip(buf: array, t: float, depth_db: float, hold: float = 0.3, attack: float = 0.05, release: float = 0.3) -> None:
    """Trapezoid gain dip around ``t`` (in place)."""
    g = 10 ** (depth_db / 20.0)
    a0, a1 = t - attack, t + hold + release
    n_frames = len(buf) // 2
    for k in range(max(0, int(a0 * SR)), min(n_frames, int(a1 * SR) + 1)):
        tt = k / SR
        w = min(1.0, (tt - a0) / attack if tt < t else 1.0, (a1 - tt) / release if tt > t + hold else 1.0)
        w = max(0.0, w)
        m = 1.0 - (1.0 - g) * w
        buf[2 * k] *= m
        buf[2 * k + 1] *= m


def _sections(seg: SegmentPlan) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bar = seg.bed.bar_s
    plan = seg.plan
    labels = list(plan.labels[: plan.n_bars] if plan else []) + (["end"] if seg.closed else [])
    for k, lab in enumerate(labels):
        t = seg.anchor + k * bar
        if t >= seg.end:
            break
        if out and out[-1]["name"] == lab:
            continue
        if out:
            out[-1]["t1"] = round(t, 4)
        out.append({"name": lab, "t0": round(t, 4), "t1": round(seg.end, 4)})
    return out


def fit_cue_sheet(cue_sheet: Sequence[Any], film_dur: float, out_path: str | Path, *, style: str | None = None,
                  seed: int = 0, last_word_time: float | None = None, drop_times: Sequence[float] = (),
                  ffmpeg: str | None = None, kit: Kit | None = None, assets: Path | None = None,
                  stings_in_music: bool = True) -> FittedCueSheet:
    """Render a film.json ``music`` cue sheet to a 48 kHz float WAV of exactly ``film_dur`` s.

    Beds resolve by id or family (``resolve_bed``; a family follows the previous bed's ``cadence_to`` key),
    unknown beds are skipped with a warning (falling back to the style's bed), stings land with their impact
    exactly on ``t``. Raises :class:`AudioError` when nothing can be rendered.
    """
    if film_dur <= 0.05:
        raise AudioError("duration must be positive")

    def resolve(ref: str, s: int, key: str | None) -> Bed | None:
        return resolve_bed(ref, s, prefer_key=key, assets=assets)

    cp = plan_cue_sheet(cue_sheet, film_dur, resolve, seed=seed, last_word_time=last_word_time,
                        drop_times=drop_times, fallback=style or "launch")
    if not cp.segments:
        raise AudioError("; ".join(cp.warnings) or "empty cue sheet")
    warns = list(cp.warnings)
    n_film = int(round(film_dur * SR))
    out = array("f", bytes(4 * 2 * n_film))
    decoded: dict[Path, array] = {}
    fitted: list[FittedSegment] = []
    for seg in cp.segments:
        bed, plan = seg.bed, seg.plan
        assert plan is not None
        if not bed.path.is_file():
            raise AudioError(f"music bed missing: {bed.path}")
        src = decoded.get(bed.path) or decode_f32(bed.path, 2, ffmpeg)
        decoded[bed.path] = src
        n_local = int(round(seg.length * SR))
        if seg.closed:
            buf = render_bars(src, bed.bar_s, plan.source_bars, n_local, end_bar=bed.end_bar, n_bars=plan.n_bars)
        else:
            buf = render_bars(src, bed.bar_s, plan.source_bars, n_local)
            fo = int(round(seg.fade_out_s * SR))
            _fade_out(buf, n_local - fo, n_local)
        if seg.join_out == "gap":
            _fade_out(buf, n_local - int(0.05 * SR), n_local)
        a0 = int(round(seg.anchor * SR))
        m = min(n_local, n_film - a0)
        if m > 0:
            out[2 * a0:2 * (a0 + m)] = buf[: 2 * m]
        bar = bed.bar_s
        nb = plan.n_bars if seg.closed else int(math.floor(seg.length / bar + 1e-9))
        downs = [round(seg.anchor + k * bar, 4) for k in range(nb + 1) if seg.anchor + k * bar < seg.end - 1e-6]
        fitted.append(FittedSegment(bed.id, bed.family, bed.key, bed.bpm, bar, bed.beats_per_bar, round(seg.anchor, 4),
                                    round(seg.end, 4), downs, _sections(seg), plan.source_bars[: max(nb, 0)],
                                    seg.join_in, seg.join_out,
                                    round(seg.anchor + plan.n_bars * bar, 4) if seg.join_out == "final" else None))
    # ---- stings: in the music track, impact exactly on t
    placed: list[PlacedSting] = []
    consumed: list[dict[str, Any]] = []
    if cp.stings and stings_in_music:
        kit = kit or load_kit(assets)
        if kit is None:
            warns.append("SFX kit missing: stings skipped")
        else:
            rr: dict[str, int] = {}
            join_of = {id(s.sting): s for s in cp.segments if s.sting is not None}
            ref_lufs = sum(s.bed.lufs for s in cp.segments) / len(cp.segments)
            for st in cp.stings:
                snd = kit.resolve(st.name, style)
                if snd is None:
                    warns.append(f"unknown sting '{st.name}' at {st.t:g} s skipped")
                    continue
                incoming = join_of.get(id(st))
                if incoming is not None:
                    key_bed = cp.segments[cp.segments.index(incoming) + 1].bed
                else:
                    playing = [s for s in cp.segments if s.anchor <= st.t + 1e-6]
                    key_bed = (playing[-1] if playing else cp.segments[0]).bed
                k = rr.get(snd.name, 0)
                rr[snd.name] = k + 1
                var = _choose_variant(snd, key_bed.key, k)
                sync = sync_time(snd, var)
                gain = ref_lufs + STING_OVER_BED_DB - float(var.get("st_lufs", -18.0)) + st.gain_db
                if incoming is None:
                    _dip(out, st.t, STING_DIP_DB)
                _add_file(out, kit.root / var["file"], st.t - sync, gain, ffmpeg)
                placed.append(PlacedSting(snd.name, var["file"], round(st.t, 4), round(st.t - sync, 4),
                                          round(gain, 2), str(var.get("key", "")), incoming is not None))
                consumed.append(st.raw or {"sting": st.name, "t": st.t})
    path = write_wav_f32(out_path, out, 2)
    return FittedCueSheet(path, film_dur, fitted, placed, consumed,
                          round(sum(s.bed.lufs for s in cp.segments) / len(cp.segments), 2), warns)


def _add_file(out: array, path: Path, start: float, gain_db: float, ffmpeg: str | None) -> None:
    """Mix an audio file into ``out`` at ``start`` s (head-trimmed before 0, tail-trimmed at the end)."""
    src = decode_f32(path, 2, ffmpeg)
    g = 10 ** (gain_db / 20.0)
    n_out, n_src = len(out) // 2, len(src) // 2
    s0 = int(round(start * SR))
    k0 = max(0, -s0)
    k1 = min(n_src, n_out - s0)
    for k in range(k0, k1):
        j = 2 * (s0 + k)
        out[j] += src[2 * k] * g
        out[j + 1] += src[2 * k + 1] * g


# ------------------------------------------------------------------------------- film helper

def film_music_plan(film: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The film's ``music`` entries that this module renders (beds and stings)."""
    return [dict(m) for m in film.get("music") or [] if isinstance(m, Mapping) and (m.get("bed") or m.get("sting"))]


def fit_film_music(film: Mapping[str, Any], out_path: str | Path, *, style: str | None = None, seed: int = 0,
                   last_word_time: float | None = None, drop_times: Sequence[float] = (),
                   ffmpeg: str | None = None, assets: Path | None = None) -> FittedCueSheet:
    """Music for a whole film.json: its cue sheet, or the style's bed over the full length when it has none."""
    dur = float(film.get("dur") or 0.0)
    plan = film_music_plan(film)
    if not any(m.get("bed") for m in plan):
        plan = [{"bed": style or "launch", "t0": 0.0, "t1": dur}] + plan
    return fit_cue_sheet(plan, dur, out_path, style=style, seed=seed, last_word_time=last_word_time,
                         drop_times=drop_times, ffmpeg=ffmpeg, assets=assets)
