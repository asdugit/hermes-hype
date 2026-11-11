"""Listening previews for the user (dev-only): bed excerpts, SFX sampler, mock promo mixes, benchmark.

    python -m tools.compose.previews --out ../previews/audio          # everything
    python -m tools.compose.previews --out ../previews/audio --bench  # 75 s runtime mix benchmark only

Narration comes from edge-tts (dev venv) through the SAME runtime path the plugin uses
(``showreel_core.audio.tts.synthesize`` with a dispatch that mimics Hermes ``text_to_speech``).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from showreel_core.audio.captions import phrase_timing
from showreel_core.audio.ffmpeg_io import find_ffmpeg, run
from showreel_core.audio.mix import MixSettings, VoicePlacement, mix
from showreel_core.audio.music import fit_bed, load_beds
from showreel_core.audio.sfx import hero_times, load_kit, place_cues
from showreel_core.audio.tts import VoiceClip, synthesize
from showreel_core.qa.audio import audio_report

from .beds import STYLES
from .encode import render_lock

LINE = ("Your agent just built something real. Auteur turns that session into a film: "
        "the code, the diffs, the moment the tests passed.")
VOICE = "en-US-AndrewMultilingualNeural"


def edge_dispatch(voice: str = VOICE):
    """A stand-in for ``ctx.dispatch_tool`` that speaks with edge-tts and returns Hermes' envelope."""
    import edge_tts

    def dispatch(name: str, args: dict[str, Any], **_kw: Any) -> str:
        assert name == "text_to_speech"
        out = args["output_path"]
        asyncio.run(edge_tts.Communicate(args["text"], voice).save(out))
        return json.dumps({"success": True, "file_path": out, "file_paths": [out], "provider": f"edge:{voice}"})

    return dispatch


def to_mp3(src: Path, dst: Path, ffmpeg: str, extra: list[str] | None = None) -> Path:
    run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), *(extra or []),
         "-c:a", "libmp3lame", "-b:a", "192k", str(dst)])
    return dst


def say(text: str, path: Path, ffmpeg: str, voice: str = VOICE) -> VoiceClip | None:
    return synthesize(edge_dispatch(voice), text, path, ffmpeg=ffmpeg)


def bed_previews(out: Path, work: Path, ffmpeg: str) -> list[dict]:
    rows = []
    for style in STYLES:
        for bed in load_beds(style):
            fm = fit_bed(bed, 30.0, work / f"{bed.id}_30s.wav", drop_time=12.0, ffmpeg=ffmpeg)
            to_mp3(fm.path, out / f"bed_{bed.id}_30s.mp3", ffmpeg)
            to_mp3(bed.path, out / f"bed_{bed.id}_full.mp3", ffmpeg)
            rows.append({"id": bed.id, "title": "", "bpm": bed.bpm, "key": bed.key, "drop": fm.drop_time,
                         "end": fm.end_time, "bars": fm.source_bars})
    return rows


def sfx_sampler(out: Path, work: Path, ffmpeg: str) -> Path:
    """Every sound (all variants), each announced by name, separated by gaps."""
    kit = load_kit()
    assert kit is not None
    inputs: list[str] = []
    parts: list[str] = []
    t = 0.5
    k = 0
    for name, snd in kit.sounds.items():
        clip = say(name.replace("_", " "), work / f"say_{name}.wav", ffmpeg, "en-US-AriaNeural")
        if clip:
            inputs += ["-i", str(clip.path)]
            parts.append(f"[{k}:a]aformat=channel_layouts=stereo,volume=-6dB,adelay={int(t * 1000)}:all=1[a{k}]")
            k += 1
            t += clip.duration + 0.35
        for v in snd.variants:
            inputs += ["-i", str(kit.root / v["file"])]
            parts.append(f"[{k}:a]aformat=channel_layouts=stereo,adelay={int(t * 1000)}:all=1[a{k}]")
            k += 1
            t += v["dur"] + 0.45
        t += 0.6
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(k)) + f"amix=inputs={k}:normalize=0[o]"
    dst = out / "sfx_sampler.mp3"
    run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
         "-map", "[o]", "-c:a", "libmp3lame", "-b:a", "192k", str(dst)], timeout=600)
    return dst


CUES = {  # role -> time (s) in the 25 s mock promo; the narration starts at 2.0 s
    "cut": 1.6, "type": 6.3, "click": 8.2, "pass": 10.9, "hero": 12.6,
}


def mock_mix(bed, voice: VoiceClip, out: Path, work: Path, ffmpeg: str, *, music_lu: float = -11.0,
             captions_only: bool = False, tag: str = "") -> dict:
    dur, vo_t = 25.0, 2.0
    fm = fit_bed(bed, dur, work / f"m_{bed.id}{tag}.wav", drop_time=CUES["hero"],
                 last_word_time=vo_t + voice.duration, ffmpeg=ffmpeg)
    kit = load_kit()
    assert kit is not None
    cues = [{"t": t, "sfx": role} for role, t in CUES.items()]
    cues[-1]["t"] = fm.drop_time or CUES["hero"]
    placed, warns = place_cues(cues, kit, dur, style=bed.style)
    voices = [] if captions_only else [VoicePlacement(voice.path, vo_t, voice.duration)]
    s = MixSettings(music_vs_voice_lu=music_lu)
    t0 = time.perf_counter()
    res = mix(work / f"mix_{bed.id}{tag}.wav", dur, music=fm.path, voices=voices, sfx=placed,
              hero_times=hero_times(placed), settings=s, work_dir=work / f"w_{bed.id}{tag}", ffmpeg=ffmpeg)
    secs = time.perf_counter() - t0
    rep = audio_report(res.path, dur, voice_stem=res.voice_stem, bed_stem=res.bed_stem, ffmpeg=ffmpeg,
                       captions_only=captions_only)
    name = f"mix_{bed.id}_25s{tag}.mp3"
    to_mp3(res.path, out / name, ffmpeg)
    mp3 = audio_report(out / name, dur, ffmpeg=ffmpeg)
    return {"file": name, "bed": bed.id, "lufs": rep.get("lufs_i"), "tp_wav": rep.get("true_peak_db"),
            "tp_mp3": mp3.get("true_peak_db"), "snr": rep.get("snr_median_db"), "snr_p5": rep.get("snr_p5_db"),
            "music_minus_voice": rep.get("music_minus_voice_lu"), "gap": rep.get("longest_gap_s"),
            "pass": rep.get("pass"), "gates": rep.get("gates"), "mode": res.norm_mode, "mix_s": round(secs, 2),
            "sfx": [p.name for p in placed], "warnings": warns}


def bench_75s(work: Path, ffmpeg: str, voice: VoiceClip) -> dict:
    """Runtime audio for a 75 s film: bar-fit + 8 narration clips + 20 SFX cues + mix + QA."""
    bed = next(b for b in load_beds("launch") if b.id == "launch_a")
    kit = load_kit()
    assert kit is not None
    dur = 75.0
    t0 = time.perf_counter()
    fm = fit_bed(bed, dur, work / "bench_music.wav", drop_time=40.0, ffmpeg=ffmpeg)
    t1 = time.perf_counter()
    voices = [VoicePlacement(voice.path, 1.5 + 9.0 * k, voice.duration) for k in range(8)]
    roles = ["cut", "click", "type", "appear", "cut", "pass"]
    cues = [{"t": 1.0 + 3.4 * k, "sfx": roles[k % len(roles)]} for k in range(19)] + [{"t": fm.drop_time, "sfx": "hero"}]
    placed, _ = place_cues(cues, kit, dur, style="launch")
    t2 = time.perf_counter()
    res = mix(work / "bench_final.wav", dur, music=fm.path, voices=voices, sfx=placed, hero_times=hero_times(placed),
              work_dir=work / "bench", ffmpeg=ffmpeg)
    t3 = time.perf_counter()
    rep = audio_report(res.path, dur, voice_stem=res.voice_stem, bed_stem=res.bed_stem, ffmpeg=ffmpeg)
    t4 = time.perf_counter()
    return {"bar_fit_s": round(t1 - t0, 2), "sfx_place_s": round(t2 - t1, 3), "mix_s": round(t3 - t2, 2),
            "mix_breakdown": res.seconds, "qa_s": round(t4 - t3, 2), "total_s": round(t4 - t0, 2),
            "lufs": rep.get("lufs_i"), "tp": rep.get("true_peak_db"), "snr": rep.get("snr_median_db"),
            "music_minus_voice": rep.get("music_minus_voice_lu"), "pass": rep.get("pass"), "mode": res.norm_mode,
            "n_sfx": len(placed)}


def write_readme(out: Path, results: dict[str, Any]) -> Path:
    """README.md for the user: every file, what to listen for, measured numbers."""
    beds = {b["id"]: b for st in STYLES for b in _bars(st)}
    L: list[str] = ["# Auteur audio previews (WP-C)", "",
                    "Nobody on the build machine can listen: these numbers are measurements, not ear checks. "
                    "Please listen on **phone speakers and headphones** and tell us what to change.", "",
                    "All music and SFX are original, generated by `tools/compose` (procedural synthesis, no samples). "
                    f"Narration test line (edge-tts `{VOICE}`, the same path the plugin uses via Hermes "
                    "`text_to_speech`):", "", f"> {LINE}", "",
                    "## 1. Beds — `bed_<id>_30s.mp3` (runtime bar-fit to 30 s, drop at ~12 s) and `bed_<id>_full.mp3`", "",
                    "| bed | title | BPM / key | what to listen for |", "|---|---|---|---|"]
    for bid, b in beds.items():
        L.append(f"| `{bid}` | {b.get('title', '')} | {b['bpm']:g} / {b['key']} | {b.get('notes', '')} |")
    L += ["", "The 30 s versions are cut by the runtime (`showreel_core/audio/music.py`): intro tail -> A -> build -> "
          "drop -> outro -> final hit on a bar line, with 30 ms splices that finish before each downbeat. Listen for "
          "audible seams (there should be none), whether the drop lands, and whether the ending rings out naturally.",
          "", "Mastered bed numbers (full composition, dev meter):", "",
          "| bed | LUFS | TP dBTP | phone-band share (>= 0.50) | L/R corr (> 0.3) |", "|---|---|---|---|---|"]
    for bid, b in beds.items():
        L.append(f"| `{bid}` | {b.get('lufs')} | {b.get('true_peak_db')} | {b.get('phone_band')} | {b.get('lr_corr')} |")
    L += ["", "## 2. `sfx_sampler.mp3`", "",
          "Every SFX in the kit (all variants), each announced by name (Aria voice) and separated by gaps: whooshes "
          "(doppler pass-by), clicks, key ticks, pops, success chime, error buzz, hits, the hero impact, riser, "
          "reverse swell, glitch, blip, coin, power-up, level-up jingle, relay, beep, plotter, paper, stamp, shutter, "
          "sub drop. Listen for anything harsh, cheap or 'CapCut'. In films they are used sparingly: only on "
          "visible actions, one hero impact per film.", "",
          "## 3. Mock promo mixes — `mix_<bed>_25s.mp3`", "",
          "25 s: music intro, narration from 2.0 s, SFX on a cut (1.6 s), typing (6.3 s), a click (8.2 s), a success "
          "sound when the line says 'the tests passed' (10.9 s) and the one hero impact at the drop (~12.6 s), then "
          "music alone to the final hit. Music sits at voice - 11 LU and only its 250 Hz-5 kHz band ducks under "
          "speech (120 ms look-ahead), so the groove keeps going under the voice. Final: -14 LUFS, <= -1.5 dBTP.", "",
          "| file | LUFS | TP (wav / mp3) | speech-band SNR median (gate >= 10, aim 12-16) | music - voice LU | "
          "longest gap s | gates |", "|---|---|---|---|---|---|---|"]
    for m in results.get("mixes", []):
        L.append(f"| `{m['file']}` | {m['lufs']} | {m['tp_wav']} / {m['tp_mp3']} | {m['snr']} | "
                 f"{m['music_minus_voice']} | {m['gap']} | {'pass' if m['pass'] else 'FAIL'} |")
    L += ["", "- `mix_launch_a_25s_music-3dB.mp3` / `_music+3dB.mp3`: the same mix with the music 3 dB quieter / "
          "louder (presence -14 / -8 LU). **Tell us which of the three levels you prefer.**",
          "- `mix_launch_a_25s_captions-only.mp3`: what a reel sounds like when no TTS is available "
          "(music at full presence + SFX).", "",
          "## 4. Voices", "", f"- `voice_andrew.mp3`: `{VOICE}` (used in the mixes).",
          "- `voice_aria_hermes_default.mp3`: `en-US-AriaNeural`, the Hermes default Edge voice - what most users "
          "will hear unless they configure another TTS provider.", ""]
    b = results.get("bench_75s")
    if b:
        L += ["## 5. Runtime benchmark (75 s film, this PC)", "",
              f"bar-fit {b['bar_fit_s']} s, SFX placement {b['sfx_place_s']} s, mix {b['mix_s']} s "
              f"({b['mix_breakdown']}), QA {b['qa_s']} s -> total {b['total_s']} s. "
              f"Result: {b['lufs']} LUFS, {b['tp']} dBTP, SNR {b['snr']} dB, pass={b['pass']}.", ""]
    p = out / "README.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _bars(style: str) -> list[dict]:
    from showreel_core.audio.music import ASSETS

    f = ASSETS / "beds" / style / "bars.json"
    return json.loads(f.read_text(encoding="utf-8"))["beds"] if f.is_file() else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.compose.previews")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--readme-only", action="store_true")
    a = ap.parse_args(argv)
    if a.readme_only:
        res = json.loads((a.out / "_work" / "previews.json").read_text(encoding="utf-8"))
        print(write_readme(a.out, res))
        return 0
    ffmpeg = find_ffmpeg()
    assert ffmpeg, "ffmpeg required"
    out = a.out
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    with render_lock("wp-c-audio previews"):
        voice = say(LINE, work / "narration_andrew.wav", ffmpeg)
        assert voice, "edge-tts narration failed"
        results["voice"] = voice.to_dict()
        results["captions"] = [c.__dict__ for c in phrase_timing(LINE, voice.duration, 2.0)]
        if not a.bench:
            aria = say(LINE, work / "narration_aria.wav", ffmpeg, "en-US-AriaNeural")
            to_mp3(voice.path, out / "voice_andrew.mp3", ffmpeg)
            if aria:
                to_mp3(aria.path, out / "voice_aria_hermes_default.mp3", ffmpeg)
            results["beds"] = bed_previews(out, work, ffmpeg)
            results["sfx_sampler"] = str(sfx_sampler(out, work, ffmpeg))
            mixes = []
            for style in STYLES:
                for bed in load_beds(style):
                    mixes.append(mock_mix(bed, voice, out, work, ffmpeg))
            la = next(b for b in load_beds("launch") if b.id == "launch_a")
            for lu, tag in ((-14.0, "_music-3dB"), (-8.0, "_music+3dB")):
                mixes.append(mock_mix(la, voice, out, work, ffmpeg, music_lu=lu, tag=tag))
            mixes.append(mock_mix(la, voice, out, work, ffmpeg, captions_only=True, tag="_captions-only"))
            results["mixes"] = mixes
        results["bench_75s"] = bench_75s(work, ffmpeg, voice)
    (work / "previews.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    if not a.bench:
        write_readme(out, results)
    print(json.dumps(results.get("bench_75s"), indent=1))
    for m in results.get("mixes", []):
        print(f"{m['file']:<44} LUFS {m['lufs']}  TP {m['tp_wav']}/{m['tp_mp3']}  SNR {m['snr']}  "
              f"M-V {m['music_minus_voice']}  gap {m['gap']}  pass {m['pass']}  {m['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
