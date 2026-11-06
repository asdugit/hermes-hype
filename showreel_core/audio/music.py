"""Bar-fit a composed music bed to an exact film duration (stdlib + ffmpeg).

The bed (``assets/audio/beds/<style>/<id>.ogg`` + ``bars.json``) is cut on whole bars:
intro -> A (looped) -> build -> drop (at the requested time) -> drop/B (looped) -> outro -> end hit,
so the final hit lands on a bar line and its ring-out carries past the last word. Splices are 30 ms
equal-power crossfades that finish 5 ms before each downbeat, so every downbeat transient is clean.
"""
from __future__ import annotations

import json
import math
import zlib
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ffmpeg_io import SR, AudioError, decode_f32, write_wav_f32

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "audio"
XFADE_S = 0.030
PRE_S = 0.005
MIN_RING_S = 1.2
#: styles without beds of their own -> the bed family that fits them (before the launch fallback)
STYLE_FALLBACK = {"nature": "dream", "newspaper": "ink"}


@dataclass
class Bed:
    """One composed bed and its bar map (from bars.json)."""
    id: str
    style: str
    path: Path
    bpm: float
    beats_per_bar: int
    bar_s: float
    sections: list[dict[str, Any]]
    drop_bar: int
    end_bar: int
    total_bars: int
    tail_s: float
    key: str = ""
    lufs: float = -16.0
    family: str = ""              # bed family (= style folder unless bars.json says otherwise), e.g. "dream"
    cadence_to: str = ""          # key the outro resolves into when another bed follows (e.g. "C major")
    title: str = ""

    def section(self, name: str) -> tuple[int, int]:
        """(start_bar, bars) of a named section (0, 0 if absent)."""
        for s in self.sections:
            if s["name"] == name:
                return int(s["start_bar"]), int(s["bars"])
        return 0, 0


@dataclass
class BarPlan:
    """Which source bar plays in each film bar (before the end hit at film bar ``n_bars``)."""
    source_bars: list[int]
    labels: list[str]
    n_bars: int
    drop_bar: int | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class FittedMusic:
    """Result of :func:`fit_bed` - the WAV plus the grid the timeline can snap cuts to."""
    path: Path
    bed_id: str
    duration: float
    bpm: float
    bar_s: float
    beats_per_bar: int
    downbeats: list[float]
    drop_time: float | None
    end_time: float
    sections: list[dict[str, Any]]
    source_bars: list[int]
    lufs: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["path"] = str(self.path)
        return d


# ---------------------------------------------------------------------------- beds

def load_beds(style: str, assets: Path | None = None) -> list[Bed]:
    """All beds for ``style`` (sorted by id); [] if the style has none."""
    root = (assets or ASSETS) / "beds" / style
    meta = root / "bars.json"
    if not meta.is_file():
        return []
    data = json.loads(meta.read_text(encoding="utf-8"))
    out = []
    for b in data.get("beds", []):
        out.append(Bed(id=b["id"], style=b.get("style", style), path=root / b["file"], bpm=float(b["bpm"]),
                       beats_per_bar=int(b.get("beats_per_bar", 4)), bar_s=float(b["bar_s"]), sections=b["sections"],
                       drop_bar=int(b["drop_bar"]), end_bar=int(b["end_bar"]), total_bars=int(b["total_bars"]),
                       tail_s=float(b.get("tail_s", 4.0)), key=b.get("key", ""), lufs=float(b.get("lufs") or -16.0),
                       family=str(b.get("family") or style), cadence_to=str(b.get("cadence_to") or ""),
                       title=str(b.get("title") or "")))
    return sorted(out, key=lambda b: b.id)


def all_beds(assets: Path | None = None) -> list[Bed]:
    """Every shipped bed across all ``beds/<folder>/bars.json`` (sorted by id)."""
    root = (assets or ASSETS) / "beds"
    if not root.is_dir():
        return []
    out: list[Bed] = []
    for meta in sorted(root.glob("*/bars.json")):
        try:
            out += load_beds(meta.parent.name, assets)
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda b: b.id)


def _same_key(a: str, b: str) -> bool:
    return bool(a) and a.strip().lower() == b.strip().lower()


def resolve_bed(ref: str, seed: int = 0, *, prefer_key: str | None = None, assets: Path | None = None) -> Bed | None:
    """A bed by exact id (``dream_a``), or by family/style name (``dream``, ``pixel_boss``, ``nature``).

    For a family, a variant in ``prefer_key`` wins (so a pixel_boss outro resolves into the dream bed in the key
    it cadences to); otherwise the choice is deterministic from ``seed``. ``None`` if nothing matches.
    """
    beds = all_beds(assets)
    ref = (ref or "").strip()
    for b in beds:
        if b.id == ref:
            return b
    fam = STYLE_FALLBACK.get(ref, ref)
    cands = [b for b in beds if b.family == fam or b.style == fam]
    if not cands:
        return None
    if prefer_key:
        keyed = [b for b in cands if _same_key(b.key, prefer_key)]
        if keyed:
            cands = keyed
    return cands[zlib.crc32(f"{fam}:{seed}".encode()) % len(cands)]


def pick_bed(style: str, seed: int, bed_id: str | None = None, assets: Path | None = None) -> Bed | None:
    """Deterministic bed choice for a style (explicit ``bed_id`` wins, searched across every bed family;
    styles without beds use :data:`STYLE_FALLBACK`, then the launch beds)."""
    if bed_id:
        found = next((b for b in load_beds(style, assets) if b.id == bed_id), None) or resolve_bed(bed_id, seed,
                                                                                                    assets=assets)
        if found:
            return found
    beds = load_beds(style, assets)
    if not beds and style in STYLE_FALLBACK:
        beds = load_beds(STYLE_FALLBACK[style], assets)
    beds = beds or load_beds("launch", assets)
    if not beds:
        return None
    return beds[zlib.crc32(f"{style}:{seed}".encode()) % len(beds)]


# ---------------------------------------------------------------------------- plan

def _tail_cycle(bars: list[int], count: int) -> list[int]:
    """The last ``count`` bars of ``bars`` repeated as a loop (so the run ends on the section's last bar)."""
    if count <= 0 or not bars:
        return []
    reps = math.ceil(count / len(bars))
    return (bars * reps)[-count:]


def plan_bars(bed: Bed, duration: float, drop_time: float | None = None, last_word_time: float | None = None,
              min_ring: float = MIN_RING_S) -> BarPlan:
    """Choose the source bar for every film bar. Pure function (unit-tested).

    The end hit lands on film bar ``n_bars`` (time n_bars * bar), at least ``min_ring`` before the end and,
    if possible, after ``last_word_time``. The drop starts on the film bar nearest ``drop_time``.
    """
    bar = bed.bar_s
    warn: list[str] = []
    n = int(math.floor((duration - min_ring) / bar + 1e-9))
    if last_word_time is not None and n * bar < last_word_time:
        n2 = int(math.floor((duration - 0.6) / bar + 1e-9))
        if n2 * bar >= last_word_time:
            n = n2
        else:
            warn.append("end hit lands before the last word (film too tight for a whole bar)")
    n = max(0, n)

    def sec(name: str) -> list[int]:
        s, c = bed.section(name)
        return list(range(s, s + c))

    intro, a_bars, build, drop, b_bars, outro = (sec(x) for x in ("intro", "A", "build", "drop", "B", "outro"))
    if n == 0:
        return BarPlan([], [], 0, None, warn + ["film shorter than one bar: end hit only"])
    if n == 1:
        return BarPlan([drop[0] if drop else 0], ["drop"], 1, 0, warn)
    if drop_time is None:
        kd = round(n * 0.45)
    else:
        kd = round(drop_time / bar)
    kd = max(1, min(n - 1, kd))
    # ---- before the drop: intro tail -> A loop -> build tail
    pre = kd
    nb = min(len(build), pre, max(1, pre // 2), 2 if pre < 8 else 4)    # short spans keep an intro before the build
    rest = pre - nb
    ni = min(len(intro), rest, 2 if rest < 8 else len(intro))
    na = rest - ni
    if na % 2 == 1 and ni > 1 and a_bars:
        ni, na = ni - 1, na + 1
    if not a_bars:
        ni, na = rest, 0
    seq = [(b, "intro") for b in _tail_cycle(intro, ni)]
    seq += [(b, "A") for b in _tail_cycle(a_bars, na)]
    seq += [(b, "build") for b in _tail_cycle(build, nb)]
    # ---- from the drop: drop -> (B, drop) loop -> outro tail
    post = n - kd
    no = min(len(outro), post - 1, len(outro) if post >= 6 else 1) if post >= 3 else 0   # short spans: more drop
    mid = post - no
    cyc = [(b, "drop") for b in drop] + [(b, "B") for b in b_bars] + [(b, "drop") for b in drop] + [(b, "B") for b in b_bars]
    while len(cyc) < mid:
        cyc += cyc
    seq += cyc[:mid]
    seq += [(b, "outro") for b in _tail_cycle(outro, no)]
    return BarPlan([b for b, _ in seq], [lab for _, lab in seq], n, kd, warn)


# ---------------------------------------------------------------------------- render

def _runs(source_bars: list[int]) -> list[tuple[int, int, int]]:
    """Group film bars into (film_start_bar, source_start_bar, length) runs of consecutive source bars."""
    runs: list[tuple[int, int, int]] = []
    for f, s in enumerate(source_bars):
        if runs and runs[-1][1] + runs[-1][2] == s:
            fs, ss, ln = runs[-1]
            runs[-1] = (fs, ss, ln + 1)
        else:
            runs.append((f, s, 1))
    return runs


def render_plan(src: array, bed: Bed, plan: BarPlan, duration: float) -> array:
    """Assemble interleaved stereo float32 for ``duration`` seconds from the planned bars (pure Python)."""
    return render_bars(src, bed.bar_s, plan.source_bars, int(round(duration * SR)), end_bar=bed.end_bar,
                       n_bars=plan.n_bars)


def render_bars(src: array, bar_s: float, source_bars: list[int], n_out: int, *, end_bar: int | None = None,
                n_bars: int | None = None) -> array:
    """Splice whole source bars into ``n_out`` stereo frames (pure Python).

    Closed mode (``end_bar`` given): the end bar plays at film bar ``n_bars`` (default ``len(source_bars)``) and
    rings to the end, with a quarter-sine fade if it is still sounding. Open mode (``end_bar=None``): only
    ``source_bars`` play; the caller supplies enough bars to cover ``n_out`` and shapes the ending itself.
    """
    ch = 2
    out = array("f", bytes(4 * ch * n_out))
    n_src = len(src) // ch
    bar = bar_s
    xf, pre = int(round(XFADE_S * SR)), int(round(PRE_S * SR))
    runs = _runs(source_bars)
    nb = len(source_bars) if n_bars is None else n_bars
    if end_bar is not None:
        if runs and runs[-1][1] + runs[-1][2] == end_bar:
            runs[-1] = (runs[-1][0], runs[-1][1], 10 ** 6)      # outro flows straight into the end hit: no splice
        else:
            runs.append((nb, end_bar, 10 ** 6))
    if not runs:
        return out

    def put(o0: int, o1: int, s0: int, gain_fn=None, add: bool = False) -> None:  # noqa: ANN001
        o0, o1 = max(o0, 0), min(o1, n_out)
        if o1 <= o0:
            return
        if gain_fn is None and not add:
            a = max(s0, 0)
            b = min(s0 + (o1 - o0), n_src)
            lead = a - s0
            if b > a:
                out[(o0 + lead) * ch:(o0 + lead + b - a) * ch] = src[a * ch:b * ch]
            return
        for k in range(o1 - o0):
            si = s0 + k
            if 0 <= si < n_src:
                g = gain_fn(k) if gain_fn else 1.0
                j, q = (o0 + k) * ch, si * ch
                if add:
                    out[j] += src[q] * g
                    out[j + 1] += src[q + 1] * g
                else:
                    out[j] = src[q] * g
                    out[j + 1] = src[q + 1] * g

    for idx, (fb, sb, ln) in enumerate(runs):
        film_d = int(round(fb * bar * SR))
        src_d = int(round(sb * bar * SR))
        last = idx == len(runs) - 1
        start = 0 if idx == 0 else film_d - pre - xf
        end = n_out if last else int(round((fb + ln) * bar * SR)) - pre
        off = src_d - film_d                      # source sample = film sample + off
        if idx > 0:
            put(start, start + xf, start + off, lambda k: math.sin(0.5 * math.pi * (k + 0.5) / xf), add=True)
            body0 = start + xf
        else:
            body0 = start
        body1 = end if last else end - xf
        put(body0, body1, body0 + off)
        if not last:
            put(end - xf, end, end - xf + off, lambda k: math.cos(0.5 * math.pi * (k + 0.5) / xf))
    # first-sample fade-in (5 ms) and a quarter-sine fade-out if the ring is still sounding at the end
    fi = int(0.005 * SR)
    for k in range(min(fi, n_out)):
        g = k / fi
        out[k * ch] *= g
        out[k * ch + 1] *= g
    if end_bar is None:
        return out
    end_src = int(round(end_bar * bar * SR)) + (n_out - int(round(nb * bar * SR)))
    if end_src < n_src - int(0.05 * SR):
        fo = min(int(0.6 * SR), n_out)
        for k in range(fo):
            g = math.cos(0.5 * math.pi * (k + 1) / fo)
            j = (n_out - fo + k) * ch
            out[j] *= g
            out[j + 1] *= g
    return out


def fit_bed(bed: Bed, duration: float, out_path: str | Path, drop_time: float | None = None,
            last_word_time: float | None = None, ffmpeg: str | None = None) -> FittedMusic:
    """Fit ``bed`` to exactly ``duration`` s and write a 48 kHz float WAV. Raises AudioError on failure."""
    if duration <= 0.05:
        raise AudioError("duration must be positive")
    if not bed.path.is_file():
        raise AudioError(f"music bed missing: {bed.path}")
    plan = plan_bars(bed, duration, drop_time, last_word_time)
    src = decode_f32(bed.path, 2, ffmpeg)
    out = render_plan(src, bed, plan, duration)
    path = write_wav_f32(out_path, out, 2)
    bar = bed.bar_s
    secs: list[dict[str, Any]] = []
    for k, lab in enumerate(plan.labels + ["end"]):
        t0 = k * bar
        if secs and secs[-1]["name"] == lab:
            continue
        if secs:
            secs[-1]["t1"] = round(t0, 4)
        secs.append({"name": lab, "t0": round(t0, 4), "t1": round(duration, 4)})
    return FittedMusic(path=path, bed_id=bed.id, duration=duration, bpm=bed.bpm, bar_s=bar,
                       beats_per_bar=bed.beats_per_bar,
                       downbeats=[round(k * bar, 4) for k in range(plan.n_bars + 1)],
                       drop_time=None if plan.drop_bar is None else round(plan.drop_bar * bar, 4),
                       end_time=round(plan.n_bars * bar, 4), sections=secs, source_bars=plan.source_bars,
                       lufs=bed.lufs, warnings=plan.warnings)
