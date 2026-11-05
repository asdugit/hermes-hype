"""Final audio mix in ONE ffmpeg filtergraph + two-pass loudness normalisation (stdlib + ffmpeg).

Graph (look-ahead by delaying the program, not the detector):
  music -> gain -> hero dips -> delay L -> 3-band split (<=250 / 250-5k / >=5k)
        -> ONLY the mid band is sidechain-compressed by the undelayed narration (ratio ~3.5, 80/450 ms)
        -> recombine
  narration clips -> placed -> voice bus -> (detector) + (program, delayed L)
  SFX -> placed (delayed L) -> -4 dB while narration speaks
  sum -> trim L -> premix (+ voice / bed stems for SNR QA)
then loudnorm analysis -> linear loudnorm to -14 LUFS / -1.5 dBTP (or linear gain + TP-safe limiter when a
linear loudnorm can't meet the peak target) -> WAV (24-bit) or AAC.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Sequence

from ..qa.audio import measure_loudness
from .ffmpeg_io import SR, AudioError, require_ffmpeg, run
from .sfx import PlacedSfx


@dataclass
class VoicePlacement:
    """A normalised narration clip placed at ``start`` seconds on the film timeline."""
    path: Path
    start: float
    duration: float
    gain_db: float = 0.0


@dataclass
class MixSettings:
    target_lufs: float = -14.0
    true_peak: float = -1.5
    music_vs_voice_lu: float = -11.0      # presence target (pre-duck): music ~ voice - 11 LU
    lookahead_s: float = 0.12
    duck_ratio: float = 3.5
    duck_attack_ms: float = 80.0
    duck_release_ms: float = 450.0
    duck_mid_db: float = 9.0               # aimed gain reduction of the 250 Hz-5 kHz band under speech
    sfx_under_speech_db: float = -4.0
    hero_dip_db: float = -6.0
    hero_hold_s: float = 0.3
    hero_release_s: float = 0.25
    voice_rms_db: float = -20.0            # level the TTS clips were normalised to
    captions_only_music_lu: float = -0.5   # music alone sits this far under the target before loudnorm


@dataclass
class MixResult:
    path: Path
    premix: Path
    voice_stem: Path | None
    bed_stem: Path | None
    duration: float
    music_gain_db: float
    voice_gain_db: float
    duck_threshold_db: float | None
    loudnorm: dict[str, Any]
    norm_mode: str
    graph: str
    seconds: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        for k in ("path", "premix", "voice_stem", "bed_stem"):
            d[k] = str(d[k]) if d[k] else None
        return d


# ------------------------------------------------------------------ expressions

def _f(x: float) -> str:
    """Compact decimal for filter args (4 dp, no trailing zeros)."""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def trapezoid_gain_expr(intervals: Sequence[tuple[float, float]], depth_db: float, attack: float, release: float) -> str:
    """ffmpeg expression: 1 outside the intervals, 10^(depth/20) inside, linear ramps of attack/release.

    Overlapping intervals take the max weight. Returns "1" when there is nothing to dip.
    """
    if not intervals or depth_db >= 0:
        return "1"
    g = 10 ** (depth_db / 20.0)
    ws = [f"clip(min((t-({_f(a - attack)}))/{_f(attack)},(({_f(b + release)})-t)/{_f(release)}),0,1)"
          for a, b in intervals]
    w = ws[0]
    for x in ws[1:]:
        w = f"max({w},{x})"
    return f"1-{_f(1 - g)}*{w}"


def merge_intervals(iv: Sequence[tuple[float, float]], gap: float = 0.25) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(iv):
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def duck_threshold_db(det_rms_db: float, gr_db: float, ratio: float) -> float:
    """Threshold so a detector at ``det_rms_db`` produces ``gr_db`` of gain reduction at ``ratio``."""
    return det_rms_db - gr_db / (1.0 - 1.0 / ratio)


# ------------------------------------------------------------------------ graph

@dataclass
class GraphSpec:
    inputs: list[list[str]]      # ffmpeg args per input
    graph: str
    outputs: list[str]           # output pad labels in order: premix, stemvo?, stembed?


def build_graph(duration: float, music: Path | None, voices: Sequence[VoicePlacement], sfx: Sequence[PlacedSfx],
                music_gain_db: float, voice_gain_db: float, s: MixSettings,
                hero_times: Sequence[float] = (), duck_thr_db: float | None = None) -> GraphSpec:
    """Build the single mix filtergraph. Pure function (unit-tested)."""
    L = s.lookahead_s
    Lms = int(round(L * 1000))
    TOT = duration + L
    fmt = f"aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo"
    inputs: list[list[str]] = []
    parts: list[str] = []
    # music (or silence) ----------------------------------------------------------
    if music is not None:
        inputs.append(["-i", str(music)])
    else:
        inputs.append(["-f", "lavfi", "-t", _f(duration), "-i", f"anullsrc=r={SR}:cl=stereo"])
    dips = [(t, t + s.hero_hold_s) for t in hero_times]
    hero = trapezoid_gain_expr(dips, s.hero_dip_db, 0.03, s.hero_release_s)
    m = f"[0:a]{fmt},volume={_f(music_gain_db)}dB"
    if hero != "1":
        m += f",asetnsamples=n=480,volume='{hero}':eval=frame"
    m += f",apad=whole_dur={_f(duration)},atrim=end={_f(duration)},adelay={Lms}:all=1[mus]"
    parts.append(m)
    # voice bus -------------------------------------------------------------------
    has_voice = bool(voices)
    if has_voice:
        vl = []
        for v in voices:
            k = len(inputs)
            inputs.append(["-i", str(v.path)])
            parts.append(f"[{k}:a]{fmt},volume={_f(voice_gain_db + v.gain_db)}dB,"
                         f"adelay={int(round(v.start * 1000))}:all=1[v{k}]")
            vl.append(f"[v{k}]")
        head = f"{''.join(vl)}amix=inputs={len(vl)}:normalize=0:duration=longest," if len(vl) > 1 else vl[0]
        parts.append(f"{head}apad=whole_dur={_f(TOT)},atrim=end={_f(TOT)}[vbus]")
        parts.append("[vbus]asplit=2[vdet][vp0]")
        parts.append(f"[vp0]adelay={Lms}:all=1,atrim=end={_f(TOT)}[vprog]")
        thr = 10 ** ((duck_thr_db if duck_thr_db is not None else -32.0) / 20.0)
        thr = min(1.0, max(0.000976563, thr))
        parts.append("[mus]acrossover=split=250 5000:order=4th[mlo][mmid][mhi]")
        parts.append(f"[mmid][vdet]sidechaincompress=threshold={thr:.6f}:ratio={_f(s.duck_ratio)}:"
                     f"attack={_f(s.duck_attack_ms)}:release={_f(s.duck_release_ms)}:makeup=1:knee=2.5:"
                     f"detection=rms:link=average[mmidd]")
        parts.append("[mlo][mmidd][mhi]amix=inputs=3:normalize=0[mbus]")
    else:
        parts.append("[mus]anull[mbus]")
    # sfx bus ------------------------------------------------------------------------
    if sfx:
        sl = []
        for p in sfx:
            k = len(inputs)
            inputs.append(["-i", str(p.file)])
            trim = f"atrim=start={_f(p.skip)},asetpts=PTS-STARTPTS," if p.skip > 0 else ""
            parts.append(f"[{k}:a]{fmt},{trim}volume={_f(p.gain_db)}dB,adelay={int(round((p.start + L) * 1000))}:all=1[s{k}]")
            sl.append(f"[s{k}]")
        head = f"{''.join(sl)}amix=inputs={len(sl)}:normalize=0:duration=longest," if len(sl) > 1 else f"{sl[0]}"
        speech = merge_intervals([(v.start + L, v.start + v.duration + L) for v in voices])
        sexpr = trapezoid_gain_expr(speech, s.sfx_under_speech_db, 0.05, 0.15)
        tail = f"asetnsamples=n=480,volume='{sexpr}':eval=frame" if sexpr != "1" else "anull"
        parts.append(f"{head}{tail}[sfxb]")
        parts.append("[mbus][sfxb]amix=inputs=2:normalize=0:duration=first[bed]")
    else:
        parts.append("[mbus]anull[bed]")
    trim = f"atrim=start={_f(L)}:end={_f(TOT)},asetpts=PTS-STARTPTS"
    outs = ["premix"]
    if has_voice:
        parts.append("[bed]asplit=2[bed1][bed2]")
        parts.append("[vprog]asplit=2[vp1][vp2]")
        parts.append(f"[bed1][vp1]amix=inputs=2:normalize=0:duration=first,{trim}[premix]")
        parts.append(f"[vp2]{trim}[stemvo]")
        parts.append(f"[bed2]{trim}[stembed]")
        outs += ["stemvo", "stembed"]
    else:
        parts.append(f"[bed]{trim}[premix]")
    return GraphSpec(inputs, ";".join(parts), outs)


# -------------------------------------------------------------------------- run

_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def _loudnorm_stats(stderr: str) -> dict[str, Any]:
    m = _JSON.search(stderr)
    if not m:
        raise AudioError("loudnorm analysis produced no stats")
    return json.loads(m.group(0))


def _voice_lufs(voices: Sequence[VoicePlacement], exe: str) -> float:
    """Integrated loudness of the narration clips played back to back."""
    args = [exe, "-hide_banner", "-nostdin", "-nostats"]
    for v in voices:
        args += ["-i", str(v.path)]
    n = len(voices)
    args += ["-filter_complex", "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1,ebur128=framelog=quiet",
             "-f", "null", "-"]
    from ..qa.audio import parse_ebur128

    return parse_ebur128(run(args).stderr.decode("utf-8", "replace"))["lufs_i"]


def mix(out_path: str | Path, duration: float, *, music: Path | None, voices: Sequence[VoicePlacement] = (),
        sfx: Sequence[PlacedSfx] = (), hero_times: Sequence[float] = (), settings: MixSettings | None = None,
        work_dir: str | Path | None = None, ffmpeg: str | None = None, out_format: str = "wav") -> MixResult:
    """Mix music + narration + SFX to ``out_path`` (``wav`` 24-bit or ``m4a`` AAC 256k). Raises AudioError."""
    s = settings or MixSettings()
    exe = require_ffmpeg(ffmpeg)
    out = Path(out_path)
    work = Path(work_dir) if work_dir else out.parent
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    # pass 0: levels ----------------------------------------------------------------
    music_lufs = measure_loudness(music, exe)["lufs_i"] if music is not None else -99.0
    if voices:
        v_lufs = _voice_lufs(voices, exe)
        voice_gain = (s.target_lufs - 1.0) - v_lufs
        music_gain = (v_lufs + voice_gain + s.music_vs_voice_lu) - music_lufs if music_lufs > -70 else 0.0
        det = s.voice_rms_db + voice_gain
        thr = duck_threshold_db(det, s.duck_mid_db, s.duck_ratio)
    else:
        voice_gain, thr = 0.0, None
        music_gain = (s.target_lufs + s.captions_only_music_lu) - music_lufs if music_lufs > -70 else 0.0
    t1 = time.perf_counter()
    # pass 1: the graph -> premix + stems -----------------------------------------------
    g = build_graph(duration, music, voices, sfx, music_gain, voice_gain, s, hero_times, thr)
    premix = work / "mix_premix.wav"
    stems = {"premix": premix, "stemvo": work / "mix_stem_voice.wav", "stembed": work / "mix_stem_bed.wav"}
    args = [exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    for a in g.inputs:
        args += a
    args += ["-filter_complex", g.graph]
    for lab in g.outputs:
        args += ["-map", f"[{lab}]", "-c:a", "pcm_f32le", "-ar", str(SR), str(stems[lab])]
    run(args, timeout=600)
    t2 = time.perf_counter()
    # pass 2: loudnorm analysis --------------------------------------------------------
    ln = f"loudnorm=I={_f(s.target_lufs)}:TP={_f(s.true_peak)}:LRA=20"
    cp = run([exe, "-hide_banner", "-nostdin", "-nostats", "-i", str(premix), "-af", ln + ":print_format=json",
              "-f", "null", "-"])
    st = _loudnorm_stats(cp.stderr.decode("utf-8", "replace"))
    mi, mtp = float(st["input_i"]), float(st["input_tp"])
    gain = s.target_lufs - mi
    if mtp + gain <= s.true_peak - 0.1 and float(st["input_lra"]) <= 20.0:
        mode = "loudnorm-linear"
        chain = (f"{ln}:measured_I={st['input_i']}:measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}:"
                 f"measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true,aresample={SR}")
    else:
        mode = "gain+limiter"
        lim = 10 ** ((s.true_peak - 0.7) / 20.0)
        chain = (f"volume={_f(gain)}dB,aresample=192000,alimiter=limit={lim:.5f}:attack=1.5:release=60:level=0:"
                 f"latency=1,aresample={SR}")
    # pass 3: apply -----------------------------------------------------------------
    codec = ["-c:a", "pcm_s24le"] if out_format == "wav" else ["-c:a", "aac", "-b:a", "256k"]
    out.parent.mkdir(parents=True, exist_ok=True)

    def apply(ch: str) -> None:
        run([exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(premix), "-af", ch,
             "-ar", str(SR), *codec, "-t", _f(duration), str(out)], timeout=600)

    apply(chain)
    if mode == "gain+limiter":
        # the limiter shaves loudness off peaky material: re-measure and correct (at most 3 passes)
        for _ in range(3):
            got = measure_loudness(out, exe)["lufs_i"]
            if abs(got - s.target_lufs) <= 0.1 or got <= -70:
                break
            gain += s.target_lufs - got
            chain = re.sub(r"^volume=[^,]+", f"volume={_f(gain)}dB", chain)
            apply(chain)
    t3 = time.perf_counter()
    return MixResult(path=out, premix=premix, voice_stem=stems["stemvo"] if voices else None,
                     bed_stem=stems["stembed"] if voices else None, duration=duration,
                     music_gain_db=round(music_gain, 2), voice_gain_db=round(voice_gain, 2),
                     duck_threshold_db=None if thr is None else round(thr, 2), loudnorm=st, norm_mode=mode,
                     graph=g.graph, seconds={"levels": round(t1 - t0, 2), "graph": round(t2 - t1, 2),
                                             "normalise": round(t3 - t2, 2), "total": round(t3 - t0, 2)})

