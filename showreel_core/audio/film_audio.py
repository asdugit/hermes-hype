"""Complete audio for a film.json (Director / hero films): cue-sheet music + SFX cues + narration in one mix.

    res = render_film_audio(film, job / "audio.wav", voices=[VoicePlacement(...)], style="pixel", seed=7, fps=30)

* music: ``film["music"]`` through :func:`cuesheet.fit_film_music` (multi-bed, designed joins, stings inside
  the music track); a film without beds gets the style's bed for its whole length;
* SFX: ``cues`` (default ``film["cues"]``; pass the runtime's merged explicit + scene cues) minus the stings
  the music already rendered, placed with :func:`sfx.place_cues`;
* mix: :func:`mix.mix` (look-ahead mid-band duck, hero dips, -14 LUFS), retried without SFX and then without
  music before giving up. Never raises: failures come back as ``ok=False`` + ``error`` and warnings.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cuesheet import FittedCueSheet, film_music_plan, fit_film_music
from .ffmpeg_io import AudioError
from .mix import MixResult, MixSettings, VoicePlacement, mix, settings_for_families
from .sfx import PlacedSfx, hero_times, load_kit, place_cues


@dataclass
class FilmAudio:
    ok: bool
    path: Path | None
    mix: MixResult | None = None
    music: FittedCueSheet | None = None
    sfx: list[PlacedSfx] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": str(self.path) if self.path else None,
                "mix": self.mix.to_dict() if self.mix else None, "music": self.music.to_dict() if self.music else None,
                "sfx": [p.to_dict() for p in self.sfx], "warnings": self.warnings, "error": self.error}


def _is_consumed(cue: Mapping[str, Any], consumed: Sequence[Mapping[str, Any]]) -> bool:
    try:
        t, name = float(cue.get("t", -1)), str(cue.get("sfx", ""))
    except (TypeError, ValueError):
        return False
    return any(str(c.get("sting")) == name and abs(float(c.get("t", -99)) - t) < 2e-3 for c in consumed)


def render_film_audio(film: Mapping[str, Any], out_path: str | Path, *, voices: Sequence[VoicePlacement] = (),
                      style: str | None = None, seed: int = 0, fps: float | None = None,
                      cues: Sequence[Mapping[str, Any]] | None = None, last_word_time: float | None = None,
                      drop_times: Sequence[float] = (), work_dir: str | Path | None = None, ffmpeg: str | None = None,
                      settings: MixSettings | None = None, out_format: str = "wav") -> FilmAudio:
    """Music + SFX + narration for ``film`` mixed to ``out_path``. Never raises (see module doc)."""
    out = Path(out_path)
    work = Path(work_dir) if work_dir else out.parent / (out.stem + "_work")
    warns: list[str] = []
    try:
        dur = float(film.get("dur") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur <= 0.05:
        return FilmAudio(False, None, error="film has no duration")
    work.mkdir(parents=True, exist_ok=True)
    fps = float(fps or film.get("fps") or 30.0)
    if last_word_time is None and voices:
        last_word_time = max(v.start + v.duration for v in voices)
    # ---- music
    music: FittedCueSheet | None = None
    try:
        music = fit_film_music(film, work / "music.wav", style=style, seed=seed, last_word_time=last_word_time,
                               drop_times=drop_times, ffmpeg=ffmpeg)
        warns += [f"music: {w}" for w in music.warnings]
    except (AudioError, OSError, ValueError) as exc:
        warns.append(f"music failed ({exc}); mixing without music")
    # ---- SFX (stings the music rendered are not placed twice; if music failed they become SFX)
    raw = [dict(c) for c in (film.get("cues") or [] if cues is None else cues) if isinstance(c, Mapping)]
    consumed = music.consumed if music else []
    raw = [c for c in raw if not _is_consumed(c, consumed)]
    if music is None:
        for m in film_music_plan(film):
            if m.get("sting") and "t" in m and not any(c.get("sfx") == m["sting"] and c.get("t") == m["t"] for c in raw):
                raw.append({"t": m["t"], "sfx": m["sting"]})
    placed: list[PlacedSfx] = []
    kit = load_kit()
    if kit is None and raw:
        warns.append("SFX kit missing: no sound effects")
    elif kit is not None:
        try:
            placed, sw = place_cues(raw, kit, dur, style=style, fps=fps)
            warns += [f"sfx: {w}" for w in sw]
        except (KeyError, TypeError, ValueError) as exc:
            warns.append(f"SFX placement failed ({exc})")
    # ---- mix, degrading step by step (deeper mid-band duck when a dense bed plays under the narration)
    if music is not None and voices:
        spoken = [s.family for s in music.segments
                  if any(v.start < s.t1 and v.start + v.duration > s.t0 for v in voices)]
        settings = settings_for_families(spoken, settings)
    attempts = [(music, placed, "full mix"), (music, [], "mix without SFX"), (None, [], "narration only")]
    last_err = ""
    for k, (mus, sfx, label) in enumerate(attempts):
        if k and mus is attempts[k - 1][0] and sfx == attempts[k - 1][1]:
            continue
        try:
            res = mix(out, dur, music=mus.path if mus else None, voices=voices, sfx=sfx, hero_times=hero_times(sfx),
                      settings=settings, work_dir=work, ffmpeg=ffmpeg, out_format=out_format)
        except (AudioError, OSError) as exc:
            last_err = str(exc)
            warns.append(f"{label} failed ({exc})")
            continue
        if k:
            warns.append(f"delivered the {label}")
        return FilmAudio(True, res.path, res, mus, list(sfx), warns)
    return FilmAudio(False, None, None, music, placed, warns, last_err or "mix failed")
