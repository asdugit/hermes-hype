"""Dev-only balance inspector: per-track loudness, brightness and noisiness of a composed bed.

    python -m tools.compose.balance dream_a [--sections]

Nobody here can listen, so the arrangement is balanced by numbers: each track's integrated loudness after
its gain (relative to the loudest track), spectral centroid (brightness) and median spectral flatness
(0 = tonal, 1 = white noise; sustained flatness > ~0.3 on a pad means audible hiss).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from scipy import signal

from . import beds
from . import dsp as D
from .dsp import SR, ns


def track_stats(x: np.ndarray) -> dict[str, float]:
    """LUFS, peak, spectral centroid and median flatness of a stereo buffer."""
    m = x.mean(axis=0)
    f, _t, S = signal.stft(m, SR, nperseg=4096, noverlap=2048)
    P = np.abs(S) ** 2
    e = P.sum(axis=0)
    act = e > e.max() * 1e-4
    cen = float((f[:, None] * P).sum(axis=0)[act].sum() / max(e[act].sum(), 1e-20)) if act.any() else 0.0
    band = (f > 200) & (f < 12000)
    Pb = P[band][:, act] + 1e-20
    flat = np.exp(np.mean(np.log(Pb), axis=0)) / np.mean(Pb, axis=0) if Pb.size else np.zeros(1)
    return {"lufs": round(D.lufs(x), 1), "peak_db": round(20 * np.log10(max(np.abs(x).max(), 1e-12)), 1),
            "centroid_hz": round(cen), "flatness": round(float(np.median(flat)), 3)}


def inspect(bed_id: str, sections: bool = False) -> None:
    style, v = bed_id.rsplit("_", 1)
    song = beds.module(style).compose(v)
    rows = []
    for tr in list(song.tracks.values()):
        x, _ = song._process(tr)
        st = track_stats(x)
        if sections:
            st["sections"] = {s.name: round(D.lufs(x[:, ns(song.t(s.start_bar)):ns(song.t(s.start_bar + s.bars))]), 1)
                              for s in song.sections}
        rows.append((tr.name, st, tr.reverb, tr.delay))
    top = max(r[1]["lufs"] for r in rows)
    print(f"{bed_id}: {song.bpm:g} BPM, bar {song.bar:.3f} s, {song.total_bars} bars")
    for name, st, rv, dl in sorted(rows, key=lambda r: -r[1]["lufs"]):
        extra = f"  {st['sections']}" if sections else ""
        print(f"  {name:<12} {st['lufs'] - top:6.1f} LU  peak {st['peak_db']:6.1f}  centroid {st['centroid_hz']:5d} Hz  "
              f"flat {st['flatness']:.3f}  rev {rv:.2f} dly {dl:.2f}{extra}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.compose.balance")
    ap.add_argument("beds", nargs="+")
    ap.add_argument("--sections", action="store_true")
    a = ap.parse_args(argv)
    for b in a.beds:
        inspect(b, a.sections)
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    sys.exit(main())
