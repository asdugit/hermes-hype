"""Wave-3 listening previews (dev-only): new beds, the stings/SFX sampler, cue-sheet demos, README section.

    python -m tools.compose.previews_w3 --out ../previews/audio

Writes ``bed_<id>_30s.mp3`` / ``bed_<id>_full.mp3`` for the dream, pixel_boss, comic and ink beds,
``stings_sampler.mp3``, ``cuesheet_pixel_boss_to_dream_30s.mp3`` (the full film path: cue sheet + SFX +
edge-tts narration at speed 1.0 through ``render_film_audio``), ``cuesheet_comic_to_ink_20s.mp3`` (a
downbeat-crossfade join, music only) and a "Wave 3" block at the top of ``README.md``.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from showreel_core.audio.cuesheet import fit_cue_sheet
from showreel_core.audio.ffmpeg_io import find_ffmpeg, run
from showreel_core.audio.film_audio import render_film_audio
from showreel_core.audio.mix import MixSettings, VoicePlacement, mix, settings_for_families
from showreel_core.audio.music import fit_bed, load_beds
from showreel_core.audio.sfx import hero_times, load_kit, place_cues
from showreel_core.qa.audio import audio_report

from .beds import FAMILIES
from .encode import render_lock
from .previews import CUES, LINE, VOICE, say, to_mp3

NEW_SOUNDS = ("bloom_riser", "switch_whoosh", "petal_burst", "encounter", "buy", "cash", "sword_slash", "blade_spin",
              "damage", "footstep", "door_rumble", "chain_break", "menu_move", "menu_confirm", "level_up")
DEMO_LINE = "Every quest ends somewhere beautiful. Meet the car that makes the whole journey worth it."
DEMO = {  # 30 s: boss fight (music + SFX) -> BUY -> bloom riser -> dream with narration
    "dur": 30.0, "fps": 30,
    "music": [{"bed": "pixel_boss", "t0": 0.0, "t1": 14.0}, {"sting": "bloom_riser", "t": 13.4},
              {"bed": "dream", "t0": 14.0, "t1": 30.0}],
    "cues": [{"t": 2.0, "sfx": "footstep"}, {"t": 2.4, "sfx": "footstep"}, {"t": 2.8, "sfx": "footstep"},
             {"t": 4.0, "sfx": "blade_spin"}, {"t": 4.6, "sfx": "damage"}, {"t": 6.2, "sfx": "sword_slash"},
             {"t": 6.3, "sfx": "hit"}, {"t": 10.4, "sfx": "menu_move"}, {"t": 10.8, "sfx": "menu_move"},
             {"t": 11.2, "sfx": "menu_confirm"}, {"t": 11.32, "sfx": "buy"}, {"t": 13.4, "sfx": "bloom_riser"}],
}
VO_START = 15.6


def bed_previews(out: Path, work: Path, ffmpeg: str) -> list[dict[str, Any]]:
    rows = []
    for fam in FAMILIES:
        for bed in load_beds(fam):
            fm = fit_bed(bed, 30.0, work / f"{bed.id}_30s.wav", drop_time=12.0, ffmpeg=ffmpeg)
            to_mp3(fm.path, out / f"bed_{bed.id}_30s.mp3", ffmpeg)
            to_mp3(bed.path, out / f"bed_{bed.id}_full.mp3", ffmpeg)
            rows.append({"id": bed.id, "drop": fm.drop_time, "end": fm.end_time, "bars": fm.source_bars})
    return rows


def stings_sampler(out: Path, work: Path, ffmpeg: str) -> list[str]:
    """The wave-3 sounds (all variants), each announced by name (Aria, speed 1.0), separated by gaps."""
    kit = load_kit()
    assert kit is not None
    inputs: list[str] = []
    parts: list[str] = []
    order: list[str] = []
    t, k = 0.5, 0
    for name in NEW_SOUNDS:
        snd = kit.sounds[name]
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
            order.append(f"{v['file']} @ {t:.1f}s")
            t += v["dur"] + (0.25 if name == "footstep" else 0.5)
        t += 0.6
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(k)) + f"amix=inputs={k}:normalize=0[o]"
    run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
         "-map", "[o]", "-c:a", "libmp3lame", "-b:a", "192k", str(out / "stings_sampler.mp3")], timeout=600)
    return order


def cuesheet_demo(out: Path, work: Path, ffmpeg: str) -> dict[str, Any]:
    """The full film path on the 30 s pixel_boss -> bloom_riser -> dream demo, with narration at speed 1.0."""
    voice = say(DEMO_LINE, work / "demo_narration.wav", ffmpeg, VOICE)
    assert voice, "edge-tts narration failed"
    t0 = time.perf_counter()
    res = render_film_audio(DEMO, work / "demo_final.wav", voices=[VoicePlacement(voice.path, VO_START, voice.duration)],
                            style="pixel", seed=7, work_dir=work / "demo", ffmpeg=ffmpeg)
    secs = time.perf_counter() - t0
    assert res.ok and res.mix and res.music, res.error
    rep = audio_report(res.path, DEMO["dur"], voice_stem=res.mix.voice_stem, bed_stem=res.mix.bed_stem, ffmpeg=ffmpeg)
    name = "cuesheet_pixel_boss_to_dream_30s.mp3"
    to_mp3(res.path, out / name, ffmpeg)
    to_mp3(res.music.path, out / "cuesheet_pixel_boss_to_dream_30s_music_only.mp3", ffmpeg)
    mp3 = audio_report(out / name, DEMO["dur"], ffmpeg=ffmpeg)
    wpm = len(DEMO_LINE.split()) / voice.duration * 60.0
    return {"file": name, "seconds": round(secs, 2), "lufs": rep.get("lufs_i"), "tp_wav": rep.get("true_peak_db"),
            "tp_mp3": mp3.get("true_peak_db"), "snr": rep.get("snr_median_db"), "gap": rep.get("longest_gap_s"),
            "music_minus_voice": rep.get("music_minus_voice_lu"), "pass": rep.get("pass"), "mode": res.mix.norm_mode,
            "voice": {"provider": VOICE, "speed": 1.0, "duration": round(voice.duration, 2), "wpm": round(wpm),
                      "start": VO_START}, "music": res.music.to_dict(), "sfx": [p.name for p in res.sfx],
            "warnings": res.warnings}


def mock_mixes(out: Path, work: Path, ffmpeg: str) -> list[dict[str, Any]]:
    """Wave-1 style 25 s promo mock (voice from 2 s, five SFX roles, hero at the drop) for every new bed, with
    the runtime's per-family duck depth (``settings_for_families``)."""
    voice = say(LINE, work / "mock_narration.wav", ffmpeg, VOICE)
    assert voice, "edge-tts narration failed"
    kit = load_kit()
    assert kit is not None
    rows = []
    for fam in FAMILIES:
        for bed in load_beds(fam):
            dur, vo_t = 25.0, 2.0
            fm = fit_bed(bed, dur, work / f"m_{bed.id}.wav", drop_time=CUES["hero"], last_word_time=vo_t + voice.duration,
                         ffmpeg=ffmpeg)
            cues = [{"t": t, "sfx": role} for role, t in CUES.items()]
            cues[-1]["t"] = fm.drop_time or CUES["hero"]
            placed, _ = place_cues(cues, kit, dur, style=bed.style)
            s = settings_for_families([bed.family], MixSettings())
            res = mix(work / f"mix_{bed.id}.wav", dur, music=fm.path,
                      voices=[VoicePlacement(voice.path, vo_t, voice.duration)], sfx=placed,
                      hero_times=hero_times(placed), settings=s, work_dir=work / f"w_{bed.id}", ffmpeg=ffmpeg)
            rep = audio_report(res.path, dur, voice_stem=res.voice_stem, bed_stem=res.bed_stem, ffmpeg=ffmpeg)
            name = f"mix_{bed.id}_25s.mp3"
            to_mp3(res.path, out / name, ffmpeg)
            rows.append({"file": name, "bed": bed.id, "duck_mid_db": s.duck_mid_db, "lufs": rep.get("lufs_i"),
                         "tp": rep.get("true_peak_db"), "snr": rep.get("snr_median_db"),
                         "music_minus_voice": rep.get("music_minus_voice_lu"), "pass": rep.get("pass"),
                         "sfx": [p.name for p in placed]})
    return rows


def crossfade_demo(out: Path, work: Path, ffmpeg: str) -> dict[str, Any]:
    """Music only: comic -> ink at 9.0 s with a downbeat crossfade (no sting), 20 s."""
    sheet = [{"bed": "comic_a", "t0": 0.0, "t1": 9.0}, {"bed": "ink_a", "t0": 9.0, "t1": 20.0}]
    res = fit_cue_sheet(sheet, 20.0, work / "xfade.wav", seed=1, ffmpeg=ffmpeg)
    to_mp3(res.path, out / "cuesheet_comic_to_ink_20s.mp3", ffmpeg)
    return res.to_dict()


def _bars(fam: str) -> list[dict[str, Any]]:
    from showreel_core.audio.music import ASSETS
    f = ASSETS / "beds" / fam / "bars.json"
    return json.loads(f.read_text(encoding="utf-8"))["beds"] if f.is_file() else []


LISTEN = {
    "dream_a": "Does the chorus (from ~12 s in the 30 s cut) bloom - violins soaring over the royal-road "
               "progression - without turning sad? Felt-piano arpeggios + grand-piano tune before it.",
    "dream_b": "Brighter and moving: piano ostinato, canon-like bass walking down, violins + glockenspiel in the "
               "chorus. Is it 'beautiful field' or 'wedding video'?",
    "pixel_boss_a": "Boss tension: pedal-tone riff, chromatic bass run into the drop, Andalusian descent. The ending "
                    "bVI-bVII -> A major fanfare is the 'victory-ish cadence'.",
    "pixel_boss_b": "Faster gallop version; the drop theme climbs on the raised 7th. Too shrill on phone speakers?",
    "comic_a": "Cartoon funk: slap bass, clav, horn stabs, blues lick in the drop, slide whistle into it. Brass "
               "convincing or cheesy-synthetic?",
    "comic_b": "Caper/spy variant: quartal brass hits, bongos, dorian vamp, #9 build. Playful enough?",
    "ink_a": "Warm explainer: ukulele island strum, marimba hook, kalimba in B, snaps. Friendly, not childish?",
    "ink_b": "Pizzicato explainer: staccato strings, marimba + glockenspiel, brushes. Light on its feet?",
}


def readme_block(res: dict[str, Any]) -> str:
    L = ["<!-- wave3 -->", "## Wave 3 (new) - listen to these first", "",
         "### W3.1 New beds - `bed_<id>_30s.mp3` (runtime bar-fit, drop at ~12 s) and `bed_<id>_full.mp3`", "",
         "| bed | title | BPM / key | what to listen for |", "|---|---|---|---|"]
    rows = [b for fam in FAMILIES for b in _bars(fam)]
    for b in rows:
        L.append(f"| `{b['id']}` | {b.get('title', '')} | {b['bpm']:g} / {b['key']} | {LISTEN.get(b['id'], b['notes'])} |")
    L += ["", "Measured (full mastered bed, dev meter):", "",
          "| bed | LUFS | TP dBTP | phone-band share (>= 0.50) | L/R corr (> 0.3) | mono fold dB "
          "| section LUFS intro / A / drop / B |",
          "|---|---|---|---|---|---|---|"]
    for b in rows:
        s = b.get("section_lufs") or {}
        L.append(f"| `{b['id']}` | {b['lufs']} | {b['true_peak_db']} | {b['phone_band']} | {b['lr_corr']} | "
                 f"{b.get('mono_fold_db')} | {s.get('intro')} / {s.get('A')} / {s.get('drop')} / {s.get('B')} |")
    d = res.get("demo") or {}
    m = d.get("music") or {}
    segs = m.get("segments") or []
    st = (m.get("stings") or [{}])[0]
    L += ["", "### W3.2 `cuesheet_pixel_boss_to_dream_30s.mp3` - the style-switch film path", "",
          "A 30 s film.json run through `render_film_audio` (cue sheet + SFX + narration, one mix): boss fight "
          "(footsteps, a thrown blade, damage, a slash + hit, menu cursor, confirm, **buy**) -> the **bloom_riser** "
          "swells into its soft impact -> the dream bed. Narration (edge-tts 7.3.1, "
          f"`{(d.get('voice') or {}).get('provider', VOICE)}`, **speed 1.0**) from {VO_START} s:", "",
          f"> {DEMO_LINE}", "",
          "Cue sheet: `[{bed: pixel_boss, t0: 0, t1: 14}, {sting: bloom_riser, t: 13.4}, {bed: dream, t0: 14, t1: 30}]`."]
    if segs:
        a, b = segs[0], segs[-1]
        L += ["", f"- Beds picked: `{a['bed_id']}` ({a['key']}, {a['bpm']:g} BPM) -> `{b['bed_id']}` ({b['key']}, "
              f"{b['bpm']:g} BPM): the boss outro's bVII is V of the dream key, so the switch is a real cadence.",
              f"- The boss bed fades out under the riser and stops at {a['t1']} s; the sting `{st.get('file')}` "
              f"(key {st.get('key')}) lands its impact at exactly {st.get('t')} s; only its shimmer rings until the "
              f"dream downbeat at {b['t0']} s; the dream's final hit is at {b.get('end_time')} s (after the last word "
              f"at {round(VO_START + (d.get('voice') or {}).get('duration', 0), 2)} s) and rings to 30 s.",
              "- Listen for: does the riser read as 'transformation' (not a trailer boom)? Is the shimmer gap "
              "before the dream too long or just right? Does the voice sit clearly over the dream bed?",
              "- `cuesheet_pixel_boss_to_dream_30s_music_only.mp3`: the same music track without SFX/voice."]
    L += ["", f"Measured: {d.get('lufs')} LUFS, TP {d.get('tp_wav')} dBTP (WAV) / {d.get('tp_mp3')} (MP3), speech-band "
          f"SNR median {d.get('snr')} dB, music - voice {d.get('music_minus_voice')} LU, longest gap "
          f"{d.get('gap')} s, gates {'pass' if d.get('pass') else 'FAIL'}; narration "
          f"{(d.get('voice') or {}).get('wpm')} wpm at speed 1.0; whole audio stage {d.get('seconds')} s.",
          "Narration pace: the user locked speed 1.13 for cinematic narration; this demo reads at speed 1.0 as "
          "asked for the comparison.",
          "", "### W3.3 `cuesheet_comic_to_ink_20s.mp3` - a join without a sting", "",
          "comic_a until 9.0 s, ink_a from 9.0 s: the comic bed fades over its last beat and stops just before the "
          "switch; ink starts on its downbeat at 9.0 s. Listen for whether the hand-off feels like an edit or a hole.",
          "", "### W3.4 `stings_sampler.mp3` - new stings and SFX (each announced by name)", "",
          "bloom_riser (x2: C major for dream_a, G major for dream_b - the cue sheet picks the incoming bed's key), "
          "switch_whoosh (x2), petal_burst (x2), encounter (battle-start swirl), buy (8-bit ka-ching), cash "
          "(non-chip purchase), sword_slash (x2: swish+shing / 8-bit), blade_spin (x2), damage (x2, 8-bit), "
          "footstep (x4), door_rumble, chain_break, menu_move, menu_confirm, level_up. Listen for anything harsh, "
          "cheap or too loud relative to the others (all are loudness-normalised to -18 LUFS short-term).",
          "", "### W3.5 Mock promo mixes for the new beds - `mix_<bed>_25s.mp3`", "",
          "Same 25 s mock as section 3 below (narration from 2.0 s, SFX roles cut/type/click/pass + the hero at the "
          "drop). Dream and pixel_boss mix with a 12 dB mid-band duck (their speech band is dense); the others "
          "with the default 9 dB.", "",
          "| file | duck dB | LUFS | TP | speech-band SNR (gate >= 10, aim 12-16) | music - voice LU | gates |",
          "|---|---|---|---|---|---|---|"]
    for r in res.get("mixes") or []:
        L.append(f"| `{r['file']}` | {r['duck_mid_db']:g} | {r['lufs']} | {r['tp']} | {r['snr']} | "
                 f"{r['music_minus_voice']} | {'pass' if r['pass'] else 'FAIL'} |")
    L += ["<!-- /wave3 -->", ""]
    return "\n".join(L)


def update_readme(out: Path, res: dict[str, Any]) -> Path:
    p = out / "README.md"
    text = p.read_text(encoding="utf-8") if p.is_file() else "# Showreel audio previews\n\n"
    text = re.sub(r"<!-- wave3 -->.*?<!-- /wave3 -->\n?", "", text, flags=re.S)
    block = readme_block(res)
    m = re.search(r"^## ", text, flags=re.M)
    head, tail = (text[:m.start()], text[m.start():]) if m else (text, "")
    text = head.rstrip("\n") + "\n\n" + block + "\n" + tail
    p.write_text(text, encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.compose.previews_w3")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--readme-only", action="store_true")
    a = ap.parse_args(argv)
    work = a.out / "_work" / "w3"
    work.mkdir(parents=True, exist_ok=True)
    if a.readme_only:
        res = json.loads((work / "previews_w3.json").read_text(encoding="utf-8"))
        print(update_readme(a.out, res))
        return 0
    ffmpeg = find_ffmpeg()
    assert ffmpeg, "ffmpeg required"
    res: dict[str, Any] = {}
    with render_lock("wp-c-audio w3 previews"):
        res["beds"] = bed_previews(a.out, work, ffmpeg)
        res["sampler"] = stings_sampler(a.out, work, ffmpeg)
        res["demo"] = cuesheet_demo(a.out, work, ffmpeg)
        res["crossfade"] = crossfade_demo(a.out, work, ffmpeg)
        res["mixes"] = mock_mixes(a.out, work, ffmpeg)
    (work / "previews_w3.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    update_readme(a.out, res)
    d = res["demo"]
    print(json.dumps({k: d[k] for k in ("lufs", "tp_wav", "tp_mp3", "snr", "music_minus_voice", "gap", "pass", "seconds",
                                        "voice", "sfx", "warnings")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
