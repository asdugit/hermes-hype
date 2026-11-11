"""Narration for Director films: the plan's voiceover lines -> TTS clips placed on the timeline.

The Director writes ``plan.voiceover = [{t, text}]`` (word budget checked against each line's window). After the
best version is chosen, each line is spoken through Hermes ``text_to_speech`` (``audio.tts.synthesize``) at the
pace of the film's narrating style (cinematic 1.13, everything else 1.0: the user's locked ear test; one pace
per film, see :func:`film_pace`), and
the clips become ``film["narration"] = [{path, start, duration, text}]``, which the pipeline mixes (ducking the
music). Lines are never cut or time-stretched: a clip that cannot fit before the film ends is dropped.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

GAP_S = 0.25            # minimum silence between two narration clips
RETRY_S = (1.5, 4.0)    # waits before a 2nd/3rd try: Edge's "NoAudioReceived" is transient (a real hushed-narrator
                        # documentary lost 2 of its 7 lines to it); no retries once TTS looks down (nothing spoke yet)
TAIL_S = 0.15           # clips end at least this long before the film ends
_STYLE_WORDS = ("cinematic", "pixel", "terminal", "blueprint", "comic", "ink", "launch")


def act_style_at(treatment: dict[str, Any], t: float) -> str:
    """The style id of the treatment act playing at ``t`` ('' when unknown)."""
    acc = 0.0
    for act in treatment.get("acts") or []:
        if not isinstance(act, dict):
            continue
        try:
            d = float(act.get("duration") or 0)
        except (TypeError, ValueError):
            d = 0.0
        if acc <= t < acc + d or d <= 0:
            words = re.findall(r"[a-z]+", f"{act.get('style', '')} {act.get('world', '')}".lower())
            return next((w for w in words if w in _STYLE_WORDS), "")
        acc += d
    return ""


def speed_for(treatment: dict[str, Any], t: float, override: Any = None) -> float:
    """Narration pace at film time ``t``: the act's style ``voice_speed`` (or the user's override)."""
    try:
        from ..config import voice_speed
        return float(voice_speed(act_style_at(treatment, t), override))
    except Exception:  # noqa: BLE001 - config is optional here; the locked default pace is 1.0
        return 1.0


def film_pace(treatment: dict[str, Any], lines: list[dict[str, Any]], override: Any = None) -> float:
    """ONE narrator pace for the whole film: the pace of the style that carries the most narrated words (ties: the
    style of the last line, the payoff). A single voice must not speed up and slow down between acts."""
    words: dict[str, int] = {}
    last = ""
    for ln in sorted(lines, key=lambda v: float(v.get("t", 0) or 0)):
        style = act_style_at(treatment, float(ln.get("t", 0) or 0))
        words[style] = words.get(style, 0) + len(str(ln.get("text") or "").split())
        last = style
    if not words:
        return 1.0
    top = max(words.values())
    style = last if words.get(last) == top else max(words, key=lambda k: words[k])
    try:
        from ..config import voice_speed
        return float(voice_speed(style, override))
    except Exception:  # noqa: BLE001 - config is optional here; the locked default pace is 1.0
        return 1.0


def synthesize(lines: list[dict[str, Any]], *, dispatch: Any, out_dir: Path, dur: float,
               pace: Callable[[float], float], tts: Callable[..., Any] | None = None,
               sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict[str, Any]], list[str]]:
    """Speak and place every line. Returns (narration entries, warnings). Never raises."""
    if tts is None:
        from ..audio.tts import synthesize as tts_synth

        def _default_tts(dispatch: Any, text: str, out: Path, speed: float | None = None) -> Any:
            return tts_synth(dispatch, text, out, speed=speed)
        tts = _default_tts
    out: list[dict[str, Any]] = []
    warnings: list[str] = []
    end_prev = 0.0
    spoke = failed = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, line in enumerate(sorted(lines, key=lambda v: float(v.get("t", 0)))):
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        speed = pace(float(line.get("t", 0)))
        clip, err = None, ""
        waits = (0.0, *RETRY_S) if spoke or not failed else (0.0,)
        for k, wait in enumerate(waits):
            if wait:
                sleep(wait)
            try:
                clip = tts(dispatch, text, out_dir / f"vo_{i:02d}.wav", None if abs(speed - 1.0) < 1e-6 else speed)
            except Exception as exc:  # noqa: BLE001 - a TTS backend error is a warning, never fatal
                clip, err = None, str(exc)
            if clip is not None:
                if k:
                    warnings.append(f"narration line {i + 1} spoke on try {k + 1}")
                break
        if clip is None and err:
            warnings.append(f"narration line {i + 1} failed: {err}")
        spoke, failed = spoke + (clip is not None), failed + (clip is None)
        if clip is None:
            warnings.append(f"narration line {i + 1} could not be spoken (TTS unavailable)")
            continue
        d = float(getattr(clip, "duration", 0.0) or 0.0)
        start = max(float(line.get("t", 0)), end_prev + GAP_S if out else 0.0)
        if start + d > dur - TAIL_S:
            warnings.append(f"narration line {i + 1} ({d:.1f} s) does not fit before the end; dropped: {text[:50]!r}")
            continue
        if start > float(line.get("t", 0)) + 0.05:
            warnings.append(f"narration line {i + 1} moved {start - float(line['t']):.1f} s later to avoid overlap")
        out.append({"path": str(getattr(clip, "path", out_dir / f"vo_{i:02d}.wav")), "start": round(start, 3),
                    "duration": round(d, 3), "text": text, "speed": speed})
        end_prev = start + d
    return out, warnings
