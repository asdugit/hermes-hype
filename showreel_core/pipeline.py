"""Showreel pipeline: one job from session to delivered MP4s, with progress, cancel and fallbacks.

Stages (SPEC 3.8): ``reading -> storyboard -> voice -> layout -> render -> mix -> qa -> done``
(``failed`` / ``cancelled`` end a job early). Quick mode builds the film from a typed storyboard;
Directed mode (free-text direction) asks the Director engine for ``film.json`` and shares the back half
(page build, layout QA, render, audio, mux, QA, delivery). Every dependency has a fallback and every
fallback is logged in the job:

- LLM storyboard -> one repair -> heuristic storyboard (story stage, never fails)
- narration (``text_to_speech``) -> captions only
- requested style cannot be built or its page breaks -> ``launch``
- GPU render -> software render with one worker
- music bed -> no music; SFX -> none; mix -> no audio track; mux -> silent video
- video QA problems -> warnings (the film is still delivered)

``run_job`` never raises. Dev harness: ``python -m showreel_core.pipeline --session latest --style launch``.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import shutil
import threading
import time
import traceback
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .config import (
    ASPECT_SIZES,
    DEFAULT_STYLE,
    FINAL_FPS,
    PREVIEW_FPS,
    PREVIEW_SIZES,
    Options,
)
from .jobs import TERMINAL, JobStore
from .llm import Host

log = logging.getLogger(__name__)

#: Share of the whole job each stage stands for (progress bar); render dominates.
STAGE_WEIGHTS: dict[str, float] = {"reading": 0.04, "storyboard": 0.14, "voice": 0.08, "layout": 0.07,
                                   "render": 0.55, "mix": 0.07, "qa": 0.05}
ASSUMED_RENDER_FPS = 14.0       # e2e frames/s of a software render on a mid laptop (WP-A bench), for the ETA
TTS_WORKERS = 3
ASPECT_TAG = {"16:9": "16x9", "9:16": "9x16", "1:1": "1x1"}

_RENDER_LOCK = threading.Lock()                 # one heavy render per process (RAM)
_RUNNING: dict[str, CancelToken] = {}
_RUNNING_GUARD = threading.Lock()


class Cancelled(Exception):
    """Raised inside the pipeline when the user cancelled the job."""


class StageError(Exception):
    """A stage failed for good; ``code``/``hint`` end up in ``job.error``."""

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **({"hint": self.hint} if self.hint else {})}


# ------------------------------------------------------------------------- cancel token

class CancelToken:
    """Cancel state of one job: an in-process event plus the job's ``cancel`` flag file (other contexts)."""

    def __init__(self, store: JobStore, job_id: str) -> None:
        self.store, self.job_id = store, job_id
        self.event = threading.Event()
        self._last_poll = 0.0

    def set(self) -> None:
        self.event.set()

    def is_set(self) -> bool:
        if not self.event.is_set() and time.monotonic() - self._last_poll >= 0.5:
            self._last_poll = time.monotonic()
            if self.store.cancel_requested(self.job_id):
                self.event.set()
        return self.event.is_set()

    def check(self) -> None:
        if self.is_set():
            raise Cancelled()


def cancel_all(wait_s: float = 0.0) -> list[str]:
    """Cancel every job running in this process (plugin unload). Returns their ids."""
    with _RUNNING_GUARD:
        tokens = dict(_RUNNING)
    for tok in tokens.values():
        tok.set()
    deadline = time.monotonic() + wait_s
    while wait_s and time.monotonic() < deadline:
        with _RUNNING_GUARD:
            if not _RUNNING:
                break
        time.sleep(0.1)
    return list(tokens)


def running_ids() -> list[str]:
    with _RUNNING_GUARD:
        return list(_RUNNING)


# ----------------------------------------------------------------------------- progress

class Reporter:
    """Progress fan-out: ``job.json`` (throttled), the ``post_message`` handle, and plugin events."""

    def __init__(self, store: JobStore, job_id: str, host: Host, *, handle: Any = None,
                 write_every: float = 0.5, edit_every: float = 4.0) -> None:
        self.store, self.job_id, self.host, self.handle = store, job_id, host, handle
        self.write_every, self.edit_every = write_every, edit_every
        self.stage_name = "queued"
        self.done_weight = 0.0
        self._done: set[str] = set()
        self.t_stage = time.monotonic()
        self.t_job = time.monotonic()
        self.stage_times: dict[str, float] = {}
        self.render_estimate_s = 60.0
        self._last_write = self._last_edit = 0.0
        self._last_text = ""

    # stage bookkeeping
    def stage(self, name: str, note: str = "") -> None:
        now = time.monotonic()
        if self.stage_name in STAGE_WEIGHTS:
            self.stage_times[self.stage_name] = round(self.stage_times.get(self.stage_name, 0.0)
                                                      + now - self.t_stage, 2)
            if self.stage_name not in self._done and self.stage_name != name:
                self._done.add(self.stage_name)
                self.done_weight += STAGE_WEIGHTS[self.stage_name]
        self.stage_name, self.t_stage = name, now
        self.store.log(self.job_id, f"stage {name}" + (f": {note}" if note else ""))
        self.progress(0.0, note, force=True)

    def progress(self, frac: float, note: str | None = None, eta_s: float | None = None, *,
                 force: bool = False) -> None:
        frac = max(0.0, min(1.0, float(frac)))
        w = STAGE_WEIGHTS.get(self.stage_name, 0.0)
        pct = min(0.99, self.done_weight + w * frac)
        if eta_s is None:
            eta_s = self._estimate(frac)
        now = time.monotonic()
        if not force and now - self._last_write < self.write_every:
            return
        self._last_write = now
        fields: dict[str, Any] = {"stage": self.stage_name, "stage_pct": round(frac, 3), "pct": round(pct, 3),
                                  "eta_s": None if eta_s is None else round(max(0.0, eta_s), 1),
                                  "stages": self.stage_times}
        if note is not None:
            fields["note"] = note
        job = self.store.update(self.job_id, **fields) or {}
        self.host.emit("job.progress", {"id": self.job_id, "session_id": job.get("session_id", ""),
                                        "stage": self.stage_name, "pct": fields["pct"], "eta_s": fields["eta_s"],
                                        "note": job.get("note", "")})
        if self.handle is not None and (force or now - self._last_edit >= self.edit_every):
            self._last_edit = now
            from .deliver import progress_text
            self.edit(progress_text(job))

    def edit(self, text: str) -> None:
        """Update the posted status message in place (never raises)."""
        if self.handle is None or text == self._last_text:
            return
        self._last_text = text
        try:
            if getattr(self.handle, "ok", True) is not False:
                self.handle.edit(text)
        except Exception as exc:  # noqa: BLE001 - messages are best effort
            log.debug("showreel progress edit failed: %s", exc)

    def _estimate(self, frac: float) -> float | None:
        """Seconds left (estimate): remaining render time dominates; small constants for the rest."""
        order = list(STAGE_WEIGHTS)
        if self.stage_name not in order:
            return None
        rest = order[order.index(self.stage_name) + 1:]
        fixed = {"reading": 3.0, "storyboard": 25.0, "voice": 12.0, "layout": 8.0, "mix": 8.0, "qa": 5.0}
        left = sum(self.render_estimate_s if s == "render" else fixed[s] for s in rest)
        cur = self.render_estimate_s if self.stage_name == "render" else fixed.get(self.stage_name, 5.0)
        return left + cur * (1.0 - frac)

    def close_stage(self) -> None:
        if self.stage_name in STAGE_WEIGHTS:
            self.stage_times[self.stage_name] = round(self.stage_times.get(self.stage_name, 0.0)
                                                      + time.monotonic() - self.t_stage, 2)
            self.stage_name = "finishing"


# ------------------------------------------------------------------------------- built film

@dataclass
class Built:
    """A film ready to render: its page directory plus everything the back half needs."""
    aspect: str
    page_dir: Path
    page: str = "stage.html"
    w: int = 1920
    h: int = 1080
    fps: int = FINAL_FPS
    dur: float = 0.0
    out_size: tuple[int, int] | None = None
    post: str = "none"
    post_params: dict[str, Any] = field(default_factory=dict)
    film: dict[str, Any] = field(default_factory=dict)
    cues: list[dict[str, Any]] = field(default_factory=list)          # SFX cues (absolute seconds)
    voices: list[dict[str, Any]] = field(default_factory=list)        # [{path, start, duration}]
    scene_times: list[float] = field(default_factory=list)            # contact-sheet / QA sample times
    scene_labels: list[str] = field(default_factory=list)
    drop_time: float | None = None
    last_word_time: float | None = None
    style: str = DEFAULT_STYLE


# ------------------------------------------------------------------------------------ deps

def _d_read_session(session_id: str, *, assets_dir: Path, redact: bool) -> Any:
    from .session import analyze_session, resolve_session_ref
    sid = resolve_session_ref(session_id or "latest") or session_id      # full id, unique prefix or "latest"
    return analyze_session(sid, assets_dir=assets_dir, redact=redact)


def _d_capture(product: Any, events: list[Any], out_dir: Path, *, budget_s: float,
               progress: Callable[[int, int, str], None] | None, cancel: threading.Event | None) -> list[Any]:
    """Screenshots of the running product (local URLs / HTML files / media artifacts only; never starts servers)."""
    from .capture import capture_product
    return capture_product(product, events, out_dir, allow_network=False, budget_s=budget_s, progress=progress,
                           cancel=cancel)


def _d_digest(bundle: Any) -> str:
    """Rebuild the storyboard digest after product captures were added to the events."""
    from .session.digest import build_digest
    from .session.product import ProductReport
    report = ProductReport(bundle.product, bool(getattr(bundle, "product_detected", False)),
                           float(getattr(bundle, "product_confidence", 0.0) or 0.0),
                           dict(getattr(bundle, "product_evidence", None) or {}))
    return build_digest(bundle.events, bundle.stats, getattr(bundle, "meta", None) or {}, product=report)


def _d_storyboard(llm_call: Any, bundle: Any, story_opts: Any, product: Any) -> Any:
    from .story import generate_storyboard_report
    return generate_storyboard_report(llm_call, bundle.digest, bundle.events, bundle.stats, story_opts, product)


def _d_tts(dispatch: Any, text: str, out_path: Path, speed: float | None = None) -> Any:
    from .audio.tts import synthesize
    return synthesize(dispatch, text, out_path, speed=speed)


def _d_speed_check(speed: float) -> str | None:
    from .llm import tts_speed_conflict
    return tts_speed_conflict(speed)


def _d_pick_bed(style: str, seed: int, bed_id: str | None = None) -> Any:
    from .audio.music import pick_bed
    return pick_bed(style, seed, bed_id)


def _d_solve(sb: Any, bundle: Any, voice_durations: dict[int, float], bpm: float, seconds: float, aspect: str,
             fps: int, w: int, h: int, seed: int, style: str) -> Any:
    from .story import solve_timeline
    return solve_timeline(sb, bundle.events, bundle.stats, voice_durations, bpm, seconds, aspect, fps, w, h, seed,
                          style=style)


def _d_quick_film(timeline: Any, *, job_dir: Path, page_dir: Path, style: str, aspect: str, preview: bool,
                  storyboard: Any, bundle: Any, blender: bool = False) -> dict[str, Any]:
    """Timeline -> ``{"film": film.json, "assets": {...}, "scenes": {...}}`` via ``film/quick.py`` (WP-D).

    A bare film dict is accepted too (no extra assets or scenes).
    """
    try:
        from .film import quick
    except ImportError as exc:
        raise StageError("film_runtime_missing", f"the Quick film adapter is not in this build ({exc})") from exc
    res = _call_flexible(quick, ("film_from_timeline", "timeline_to_film", "quick_film", "build_film"),
                         timeline=timeline, style=style, aspect=aspect, preview=preview, job_dir=job_dir,
                         page_dir=page_dir, storyboard=storyboard, events=bundle.events, stats=bundle.stats,
                         product=getattr(storyboard, "product", None), blender=blender,
                         product_model=str(getattr(getattr(bundle, "product", None), "model", "") or
                                           getattr(getattr(storyboard, "product", None), "model", "") or ""))
    if hasattr(res, "to_dict") and not isinstance(res, dict):
        res = res.to_dict()
    if isinstance(res, dict) and "film" in res and "shots" not in res:
        return {"film": dict(res["film"]), "assets": dict(res.get("assets") or {}),
                "scenes": dict(res.get("scenes") or {})}
    return {"film": dict(res), "assets": {}, "scenes": {}}


def _d_build_page(film: dict[str, Any], *, page_dir: Path, job_dir: Path, assets: dict[str, Any] | None = None,
                  scenes: dict[str, Any] | None = None) -> str:
    """film.json -> a servable job dir via ``film.page.build_job``; returns the entry page name."""
    try:
        from .film.page import JobError, build_job
    except ImportError as exc:
        raise StageError("film_runtime_missing", f"the film page builder is not in this build ({exc})") from exc
    try:
        build_job(film, page_dir, assets=assets or {}, scenes=scenes or {})
    except JobError as exc:
        raise StageError("film_invalid", f"the film could not be built: {exc}") from exc
    return "stage.html"


def _d_blender_locate(config_path: str | None) -> Any:
    """The user's Blender (``BlenderFound``) or ``BlenderMissing`` with a user-facing message."""
    from .blender.locate import locate
    return locate(config_path)


def _d_blender_pass(film: dict[str, Any], job_dir: Path, **kw: Any) -> Any:
    """Blender pass of a film (``showreel_core.blender.film.render_film_shots``; never raises)."""
    from .blender.film import render_film_shots
    return render_film_shots(film, job_dir, **kw)


def _d_layout_qa(built: Built, times: list[float], thumbs_dir: Path | None) -> dict[str, Any]:
    """Seek the page at ``times``: layout issues, page cues, errors and (optionally) JPEG thumbnails."""
    from .render.errors import RenderError
    from .render.workers import _run_sync, page_session

    async def go() -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        thumbs: list[str] = []
        async with page_session(built.page_dir, built.page, w=built.w, h=built.h) as p:
            cues = await p.evaluate("(window.__sr && window.__sr.cues) || []")
            for k, t in enumerate(times):
                await p.seek(t)
                found = await p.evaluate(f"(window.__sr.qa ? window.__sr.qa({t!r}) : [])")
                for it in found or []:
                    if isinstance(it, dict):
                        issues.append({**it, "t": t})
                if thumbs_dir is not None:
                    thumbs_dir.mkdir(parents=True, exist_ok=True)
                    out = thumbs_dir / f"{ASPECT_TAG.get(built.aspect, 'x')}_{k:02d}.jpg"
                    out.write_bytes(await p.capture("jpeg", quality=80))
                    thumbs.append(str(out))
            errors = list(p.errors)
        return {"issues": issues, "cues": cues if isinstance(cues, list) else [], "errors": errors, "thumbs": thumbs}

    try:
        return _run_sync(go)
    except RenderError as e:
        return {"fatal": e.to_dict()}


def _d_render(spec: Any, progress: Callable[[int, int, float | None], None], cancel: threading.Event) -> Any:
    from .render.workers import render_video
    return render_video(spec, progress=progress, cancel=cancel)


def _d_fit_music(bed: Any, duration: float, out_path: Path, drop_time: float | None,
                 last_word_time: float | None) -> Any:
    from .audio.music import fit_bed
    return fit_bed(bed, duration, out_path, drop_time=drop_time, last_word_time=last_word_time)


def _d_fit_cue_sheet(music: list[dict[str, Any]], duration: float, out_path: Path, *, style: str, seed: int,
                     drop_time: float | None, last_word_time: float | None) -> Any:
    """The designed multi-bed fit (``audio.cuesheet``): each bed bar-fitted to its span, stings rendered into
    the music with their impact on ``t`` (returned in ``.consumed``), riser/downbeat joins."""
    from .audio.cuesheet import fit_cue_sheet
    return fit_cue_sheet(music, duration, out_path, style=style, seed=seed, last_word_time=last_word_time,
                         drop_times=[drop_time] if drop_time is not None else [])


def _d_join_music(parts: list[Path], xfade: float, out_path: Path) -> Path:
    """Concatenate fitted bed segments with equal-power-ish triangular crossfades (ffmpeg ``acrossfade``)."""
    import subprocess

    from .render.ffmpeg import resolve_ffmpeg
    if len(parts) == 1:
        shutil.copy2(parts[0], out_path)
        return out_path
    cmd = [resolve_ffmpeg().path, "-y", "-v", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    chain, last = [], "[0:a]"
    for k in range(1, len(parts)):
        chain.append(f"{last}[{k}:a]acrossfade=d={xfade:.3f}:c1=tri:c2=tri[x{k}]")
        last = f"[x{k}]"
    cmd += ["-filter_complex", ";".join(chain), "-map", last, "-c:a", "pcm_f32le", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    return out_path


def _d_gpu_ok(cache: Path) -> bool | None:
    """The cached GPU probe decision for the first usable browser (``None`` when it cannot be probed)."""
    from .render.chromium import browser_candidates
    from .render.probe import probe_gpu
    cands = browser_candidates()
    return bool(probe_gpu(cands[0], cache_path=cache).use_gpu) if cands else None


#: Legacy cue names (story timing before wave 3, older saved timelines / Director films) -> SFX kit roles.
#: The story timing now emits role names directly (cut, build, appear, type, ...).
SFX_ALIASES = {"whoosh": "cut", "tick": "type", "split": "appear", "riser": "build"}


def sfx_for_style(name: str, style: str, roles: dict[str, dict[str, str]], sounds: set[str]) -> str:
    """The sound a cue name plays in ``style``: a style ROLE wins over a same-named sound (``hit``/``click``
    are both, and pixel's ``hit`` role is ``coin``), then a sound name, then a legacy alias, then the Launch
    role table (styles without their own SFX map). Unknown names are returned unchanged."""
    table = roles.get(style) or {}
    if name in table:
        return table[name]
    if name in sounds:
        return name
    alias = SFX_ALIASES.get(name)
    if alias:
        return table.get(alias) or (roles.get("launch") or {}).get(alias) or alias
    return (roles.get("launch") or {}).get(name, name)


def _d_place_sfx(cues: list[Any], duration: float, style: str, fps: int) -> tuple[list[Any], list[str]]:
    from .audio.sfx import load_kit, place_cues
    kit = load_kit()
    if kit is None:
        return [], ["SFX kit missing; no sound effects"]
    sounds = set(kit.sounds)
    mapped = []
    for c in cues:
        c = dict(c) if isinstance(c, dict) else {"t": c.t, "sfx": c.sfx, "gain_db": c.gain_db, "align": c.align}
        c["sfx"] = sfx_for_style(str(c.get("sfx") or ""), style, kit.styles, sounds)
        mapped.append(c)
    return place_cues(mapped, kit, duration, style=style, fps=fps)


def _d_mix(out_path: Path, duration: float, *, music: Path | None, voices: list[dict[str, Any]],
           sfx: list[Any], work_dir: Path) -> Any:
    from .audio.mix import VoicePlacement, mix
    from .audio.sfx import hero_times
    vp = [VoicePlacement(Path(v["path"]), float(v["start"]), float(v["duration"])) for v in voices]
    return mix(out_path, duration, music=music, voices=vp, sfx=sfx, hero_times=hero_times(sfx), work_dir=work_dir,
               out_format="wav")


def _d_audio_report(final: Path, duration: float, mix_result: Any, captions_only: bool) -> dict[str, Any]:
    from .qa.audio import audio_report
    return audio_report(final, duration, voice_stem=getattr(mix_result, "voice_stem", None),
                        bed_stem=getattr(mix_result, "bed_stem", None), captions_only=captions_only)


def _d_mux(video: Path, audio: Path, out_path: Path, duration_s: float) -> Path:
    from .render.ffmpeg import mux, resolve_ffmpeg
    return mux(resolve_ffmpeg().path, video, audio, out_path, duration_s=duration_s)


def _d_check_video(path: Path, *, frames: int, dur: float, fps: int, times: list[float], labels: list[str],
                   contact_sheet: Path) -> dict[str, Any]:
    from .qa.video import check_video
    return check_video(path, expected_frames=frames, expected_duration_s=dur, fps=fps, scene_times=times,
                       scene_labels=labels, contact_sheet=contact_sheet).to_dict()


def _d_deliver(master: Path, *, title: str, job_id: str, aspect: str) -> Path:
    from .deliver import deliver
    return deliver(master, title=title, job_id=job_id, aspect=aspect)


def _d_director() -> Any:
    """The Director entry point (``showreel_core.director.run``) or ``None`` when not in this build."""
    try:
        from . import director
    except ImportError:
        return None
    fn = getattr(director, "run", None)
    return fn if callable(fn) else None


@dataclass
class Deps:
    """Stage implementations (swap any of them in tests)."""
    read_session: Callable[..., Any] = _d_read_session
    capture: Callable[..., Any] | None = _d_capture
    digest: Callable[[Any], str] | None = _d_digest
    storyboard: Callable[..., Any] = _d_storyboard
    tts: Callable[..., Any] = _d_tts
    speed_check: Callable[[float], str | None] | None = _d_speed_check
    pick_bed: Callable[..., Any] = _d_pick_bed
    solve: Callable[..., Any] = _d_solve
    quick_film: Callable[..., Any] = _d_quick_film
    build_page: Callable[..., Any] = _d_build_page
    layout_qa: Callable[..., Any] | None = _d_layout_qa
    render: Callable[..., Any] = _d_render
    fit_music: Callable[..., Any] = _d_fit_music
    join_music: Callable[..., Any] = _d_join_music
    fit_cue_sheet: Callable[..., Any] | None = _d_fit_cue_sheet    # None: per-bed fit + crossfades (stand-in)
    gpu_ok: Callable[[Path], bool | None] | None = _d_gpu_ok
    place_sfx: Callable[..., Any] = _d_place_sfx
    mix: Callable[..., Any] = _d_mix
    audio_report: Callable[..., Any] | None = _d_audio_report
    mux: Callable[..., Any] = _d_mux
    check_video: Callable[..., Any] | None = _d_check_video
    deliver: Callable[..., Any] = _d_deliver
    director: Callable[[], Any] = _d_director
    blender_locate: Callable[[str | None], Any] = _d_blender_locate
    blender_pass: Callable[..., Any] = _d_blender_pass


def _call_flexible(module: Any, names: tuple[str, ...], **kwargs: Any) -> Any:
    """Call the first function of ``names`` in ``module`` with the keyword arguments it declares."""
    import inspect
    for name in names:
        fn = getattr(module, name, None)
        if not callable(fn):
            continue
        params = inspect.signature(fn).parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return fn(**kwargs)
        accepted = {k: v for k, v in kwargs.items() if k in params}
        first = next(iter(params.values()), None)
        if first is not None and first.name not in accepted and first.kind in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            lead = next((kwargs[k] for k in ("timeline", "film") if k in kwargs), None)
            return fn(lead, **{k: v for k, v in accepted.items() if k != first.name})
        return fn(**accepted)
    raise StageError("film_api", f"{module.__name__} has none of {', '.join(names)}")


# ------------------------------------------------------------------------------------- run

@dataclass
class _Run:
    """Everything one job run carries between stages."""
    job_id: str
    job: dict[str, Any]
    opts: Options
    host: Host
    store: JobStore
    deps: Deps
    rep: Reporter
    cancel: CancelToken
    job_dir: Path
    seed: int = 0
    bundle: Any = None
    storyboard: Any = None
    clips: dict[int, Any] = field(default_factory=dict)       # storyboard index -> VoiceClip
    built: list[Built] = field(default_factory=list)
    title: str = ""
    blender: Any = None                                       # BlenderFound once located ("" = looked, none)

    def warn(self, msg: str) -> None:
        log.info("showreel %s: %s", self.job_id, msg)
        self.store.log(self.job_id, msg, "warn")

    def info(self, msg: str, **extra: Any) -> None:
        self.store.log(self.job_id, msg, **extra)


def job_seed(session_id: str, style: str, mode: str) -> int:
    """Deterministic film seed (crc32, never ``hash()``)."""
    return zlib.crc32(f"{session_id}|{style}|{mode}".encode()) & 0x7FFFFFFF


def run_job(job_id: str, host: Host | None = None, *, store: JobStore | None = None, deps: Deps | None = None,
            handle: Any = None) -> dict[str, Any]:
    """Run one persisted job to the end and return its final record. Never raises.

    ``handle`` is a ``ctx.post_message`` handle to edit with progress (optional).
    """
    store = store or JobStore()
    host = host or Host()
    deps = deps or Deps()
    job = store.load(job_id)
    if job is None:
        return {"id": job_id, "stage": "failed", "error": {"code": "no_job", "message": "job not found"}}
    token = CancelToken(store, job_id)
    with _RUNNING_GUARD:
        _RUNNING[job_id] = token
    rep = Reporter(store, job_id, host, handle=handle)
    opts = Options.from_dict(job.get("options"))
    run = _Run(job_id, job, opts, host, store, deps, rep, token, store.job_dir(job_id),
               seed=job_seed(job.get("session_id", ""), opts.style, opts.mode))
    store.update(job_id, pid=os.getpid(), started=time.time())
    t0 = time.monotonic()
    try:
        _run(run)
        rep.close_stage()
        final = store.update(job_id, stage="done", pct=1.0, stage_pct=1.0, eta_s=0, finished=time.time(),
                             note="", stages=rep.stage_times, wall_s=round(time.monotonic() - t0, 2))
    except Cancelled:
        rep.close_stage()
        final = store.update(job_id, stage="cancelled", finished=time.time(), eta_s=None, note="",
                             stages=rep.stage_times, wall_s=round(time.monotonic() - t0, 2))
        store.log(job_id, "cancelled by the user")
    except StageError as e:
        rep.close_stage()
        store.log(job_id, f"failed: {e.message}", "error", code=e.code)
        final = store.update(job_id, stage="failed", error=e.to_dict(), finished=time.time(), eta_s=None,
                             stages=rep.stage_times, wall_s=round(time.monotonic() - t0, 2))
    except Exception as e:  # noqa: BLE001 - last line of defence: a job never dies silently
        rep.close_stage()
        store.log(job_id, "internal error: " + "".join(traceback.format_exception_only(type(e), e)).strip(),
                  "error", trace=traceback.format_exc()[-4000:])
        final = store.update(job_id, stage="failed", finished=time.time(), eta_s=None, stages=rep.stage_times,
                             error={"code": "internal", "message": f"{type(e).__name__}: {e}"},
                             wall_s=round(time.monotonic() - t0, 2))
    finally:
        with _RUNNING_GUARD:
            _RUNNING.pop(job_id, None)
    final = final or store.load(job_id) or job
    host.emit("job.progress", {"id": job_id, "session_id": final.get("session_id", ""), "stage": final.get("stage"),
                               "pct": final.get("pct"), "eta_s": None, "note": ""})
    _final_message(rep, final)
    if final.get("stage") in TERMINAL:
        with contextlib.suppress(Exception):
            store.prune_work(job_id)
            store.prune()
    return final


def _final_message(rep: Reporter, job: dict[str, Any]) -> None:
    from .deliver import done_text, failed_text, progress_text
    stage = job.get("stage")
    text = done_text(job, media=False) if stage == "done" else failed_text(job) if stage == "failed" \
        else progress_text(job)
    rep.edit(text)


def start_background(job_id: str, host: Host, *, store: JobStore | None = None, deps: Deps | None = None,
                     handle: Any = None, on_done: Callable[[dict[str, Any]], Any] | None = None) -> threading.Thread:
    """Run a job on a daemon thread that inherits the caller's context (keeps ``post_message`` bound)."""
    ctx = contextvars.copy_context()

    def target() -> None:
        final = run_job(job_id, host, store=store, deps=deps, handle=handle)
        if on_done is not None:
            try:
                on_done(final)
            except Exception as exc:  # noqa: BLE001
                log.warning("showreel on_done callback failed: %s", exc)

    th = threading.Thread(target=ctx.run, args=(target,), daemon=True, name=f"showreel-{job_id}")
    th.start()
    return th


# --------------------------------------------------------------------------------- stages

def _run(run: _Run) -> None:
    run.cancel.check()
    run.rep.stage("reading", "reading the session")
    _read(run)
    run.cancel.check()
    built = None
    if run.opts.directed:
        built = _directed(run)
    if built is None:
        _quick_front(run)
    run.cancel.check()
    _back_half(run)


@dataclass
class SavedSession:
    """A session bundle restored from a job's ``session.json`` (re-renders reuse the parent's evidence)."""
    session_id: str = ""
    events: list[Any] = field(default_factory=list)
    stats: Any = None
    digest: str = ""
    product: Any = None
    product_detected: bool = False
    warnings: list[str] = field(default_factory=list)


def save_session(bundle: Any, path: Path) -> None:
    """Persist the evidence a re-render needs (already redacted; stays in the local job dir)."""
    from dataclasses import asdict
    data = {"session_id": getattr(bundle, "session_id", ""), "digest": getattr(bundle, "digest", ""),
            "events": [e.to_dict() if hasattr(e, "to_dict") else asdict(e) for e in bundle.events],
            "stats": bundle.stats.to_dict() if hasattr(bundle.stats, "to_dict") else {},
            "product": _product_dict(getattr(bundle, "product", None)),
            "product_detected": bool(getattr(bundle, "product_detected", False))}
    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")


def load_session(path: Path) -> SavedSession | None:
    """Inverse of :func:`save_session` (``None`` if missing or unreadable)."""
    from .contracts import Event, Product, Stats
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        events = [Event(**{k: v for k, v in e.items() if k in Event.__dataclass_fields__}) for e in raw["events"]]
        stats = Stats(**{k: v for k, v in (raw.get("stats") or {}).items() if k in Stats.__dataclass_fields__})
        prod = Product(**{k: v for k, v in (raw.get("product") or {}).items() if k in Product.__dataclass_fields__})
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return SavedSession(str(raw.get("session_id") or ""), events, stats, str(raw.get("digest") or ""), prod,
                        bool(raw.get("product_detected")))


def _read(run: _Run) -> None:
    sid = run.job.get("session_id") or ""
    bundle = None
    parent = str(run.job.get("parent") or "")
    if parent and run.job.get("reuse_storyboard"):
        with contextlib.suppress(ValueError):
            bundle = load_session(run.store.job_dir(parent) / "session.json")
        if bundle is not None:
            run.info(f"re-render: reusing the evidence of job {parent}")
    if bundle is None:
        bundle = run.deps.read_session(sid, assets_dir=run.job_dir / "assets", redact=run.opts.redact)
        fresh = True
    else:
        fresh = False
    for w in (getattr(bundle, "warnings", None) or [])[:8]:
        run.info(f"session: {w}")
    brief = run.opts.brief
    if not getattr(bundle, "events", None) and not brief.get("name"):
        raise StageError("empty_session", "This session has nothing to film yet.",
                         "Build something first (or pass a product brief to showreel_render), then try again.")
    if brief:
        _merge_brief(bundle, brief)
    run.bundle = bundle
    if fresh:
        _capture(run)
    with contextlib.suppress(Exception):
        save_session(bundle, run.job_dir / "session.json")
    run.store.update(run.job_id, session_id=getattr(bundle, "session_id", sid) or sid,
                     product=_product_dict(getattr(bundle, "product", None)))
    run.rep.progress(1.0, f"{len(bundle.events)} events")


CAPTURE_BUDGET_S = 45.0


def _capture(run: _Run) -> None:
    """Product capture: own screenshots of the product (local only), appended as ``product_capture`` events.

    Skipped when no product was detected. Failures and an empty result only log; the film then uses the
    session's own screenshots. New events go to the front of ``product.hero_event_ids`` and the digest is
    rebuilt so the storyboard can cite them.
    """
    b = run.bundle
    prod = getattr(b, "product", None)
    if run.deps.capture is None or prod is None or not (getattr(b, "product_detected", False) or run.opts.brief):
        return
    run.rep.progress(0.3, "capturing the product")
    t0 = time.monotonic()

    def progress(done: int, total: int, label: str = "") -> None:
        run.rep.progress(0.3 + 0.7 * done / max(1, total), f"capturing the product: {label}"[:120])

    try:
        new = list(run.deps.capture(prod, b.events, run.job_dir / "capture", budget_s=CAPTURE_BUDGET_S,
                                    progress=progress, cancel=run.cancel.event) or [])
    except Exception as exc:  # noqa: BLE001 - capture is optional
        run.warn(f"product capture failed ({type(exc).__name__}: {exc}); using the session's screenshots")
        return
    run.cancel.check()
    new = [e for e in new if getattr(e, "kind", "") == "product_capture"]
    run.info(f"product capture: {len(new)} shot(s) in {time.monotonic() - t0:.1f}s",
             kinds=sorted({str((e.data or {}).get("kind", "")) for e in new}))
    if not new:
        return
    b.events.extend(new)
    ids = [e.id for e in sorted(new, key=lambda e: -float(getattr(e, "weight", 0.0) or 0.0))]
    with contextlib.suppress(AttributeError):
        prod.hero_event_ids = list(dict.fromkeys(ids[:4] + list(prod.hero_event_ids or [])))[:8]
    if run.deps.digest is not None:
        try:
            b.digest = run.deps.digest(b)
        except Exception as exc:  # noqa: BLE001
            run.info(f"digest rebuild after capture failed: {exc}", level="warn")


def _merge_brief(bundle: Any, brief: dict[str, Any]) -> None:
    """An agent-supplied product brief overrides the inferred product draft."""
    prod = getattr(bundle, "product", None)
    if prod is None:
        return
    for key in ("name", "one_liner", "kind"):
        if brief.get(key):
            setattr(prod, key, str(brief[key])[:120])
    for key, attr in (("url", "urls"), ("urls", "urls"), ("features", "features"), ("run_commands", "run_commands")):
        val = brief.get(key)
        items = [val] if isinstance(val, str) else list(val or [])
        cur = list(getattr(prod, attr) or [])
        setattr(prod, attr, list(dict.fromkeys([str(v) for v in items if v] + cur))[:6 if attr == "features" else 8])
    with contextlib.suppress(AttributeError):
        bundle.product_detected = True


def _product_dict(prod: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass
    return asdict(prod) if is_dataclass(prod) and not isinstance(prod, type) else {}


def _story_options(run: _Run) -> Any:
    from .story import StoryOptions
    brief_bits = []
    b = run.opts.brief
    if b:
        brief_bits.append("Product brief from the agent: " + json.dumps(b, ensure_ascii=False)[:800])
    if run.opts.notes:
        brief_bits.append("User notes for this version: " + run.opts.notes[:600])
    if run.opts.direction:
        brief_bits.append("User direction: " + run.opts.direction[:600])
    return StoryOptions(seconds=run.opts.seconds, style=run.opts.style, aspect=run.opts.aspects[0],
                        mode=run.opts.mode, voice=run.opts.voice, brief="\n".join(brief_bits))


def _quick_front(run: _Run) -> None:
    """Storyboard -> narration -> timing -> film.json + page per aspect."""
    run.rep.stage("storyboard", "writing the storyboard")
    run.storyboard = _storyboard(run)
    run.cancel.check()
    run.rep.stage("voice", "recording narration" if run.opts.voice else "captions only")
    _voice(run)
    run.cancel.check()
    run.rep.stage("layout", "building the film")
    _build_quick(run)


def _storyboard(run: _Run) -> Any:
    from .story import storyboard_from_json, storyboard_to_json
    reuse = run.job.get("reuse_storyboard") or {}
    sb = None
    source = "llm"
    if isinstance(reuse, dict) and reuse.get("scenes"):
        try:
            from .story import validate_storyboard
            from .story.facts import SessionFacts
            sb = storyboard_from_json(reuse, source="llm", mode=run.opts.mode)
            facts = SessionFacts(run.bundle.events, run.bundle.stats, run.bundle.digest,
                                 timestamps=(run.opts.mode == "speedrun"))
            checked = validate_storyboard(sb, facts, run.opts.seconds, run.opts.mode)
            sb = checked.storyboard
            for fix in checked.fixes[:12]:
                run.info(f"edited storyboard fix: {fix}")
            run.info("storyboard reused (no model call)")
            source = "reused"
        except Exception as exc:  # noqa: BLE001 - a broken edit falls back to a fresh storyboard
            run.warn(f"saved storyboard could not be used ({exc}); writing a new one")
            sb = None
    if sb is None:
        story_opts = _story_options(run)
        llm_call = run.host.story_call()
        if llm_call is None:
            run.warn("no model available; storyboard built by the heuristic")
        rep = run.deps.storyboard(llm_call, run.bundle, story_opts,
                                  run.bundle.product if getattr(run.bundle, "product_detected", True) else None)
        sb = rep.storyboard
        source = getattr(sb, "source", "llm")
        for a in getattr(rep, "attempts", []) or []:
            run.info(f"storyboard attempt {a.kind}: {'accepted' if a.accepted else 'rejected'}",
                     problems=(a.problems or [])[:6], seconds=round(getattr(a, "seconds", 0.0), 1))
        for fix in (getattr(rep, "fixes", None) or [])[:12]:
            run.info(f"storyboard fix: {fix}")
        if source == "heuristic" and llm_call is not None:
            run.warn("the model's storyboard was unusable; used the heuristic storyboard")
    run.title = sb.title or getattr(getattr(sb, "product", None), "name", "") or "Showreel"
    data = storyboard_to_json(sb)
    (run.job_dir / "storyboard.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    run.store.update(run.job_id, storyboard=data, storyboard_source=source, title=run.title)
    run.rep.progress(1.0, f"{len(sb.scenes)} scenes ({source})")
    return sb


def words_per_minute(text: str, seconds: float) -> float | None:
    """Spoken pace of a clip (words / duration), ``None`` for an empty or zero-length clip."""
    words = len(str(text or "").split())
    return round(words * 60.0 / seconds, 1) if words and seconds > 0 else None


def _voice(run: _Run) -> None:
    """One TTS call per narrated scene (parallel, max 3); failures leave that scene captions-only.

    The pace comes from the style's ``voice_speed`` (or the ``narration_speed`` setting) and is passed to
    ``text_to_speech`` as ``speed``; audio is never time-stretched afterwards. A clip that fails with a
    speed is retried once at the provider's normal pace.
    """
    run.clips = {}
    if not run.opts.voice:
        return
    if run.host.dispatch is None:
        run.warn("text_to_speech is unavailable; captions only")
        return
    lines = [(i, s.vo) for i, s in enumerate(run.storyboard.scenes) if (s.vo or "").strip()]
    if not lines:
        return
    from .config import voice_speed
    vdir = run.job_dir / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    speed = voice_speed(run.opts.style, run.opts.voice_speed)
    tts_speed = None if abs(speed - 1.0) < 1e-6 else speed
    source = "narration_speed setting" if run.opts.voice_speed is not None else f"style {run.opts.style}"
    run.info(f"narration pace x{speed:g} ({source})", voice_speed=speed)
    if tts_speed is not None and run.deps.speed_check is not None:
        conflict = run.deps.speed_check(tts_speed)
        if conflict:
            run.warn(f"narration pace: {conflict}")
    done = 0
    failures = 0
    unpaced = 0
    lock = threading.Lock()

    def one(item: tuple[int, str]) -> tuple[int, Any]:
        nonlocal unpaced
        i, text = item
        if run.cancel.is_set():
            return i, None
        clip = run.deps.tts(run.host.dispatch, text, vdir / f"vo_{i:02d}.wav", tts_speed)
        if clip is None and tts_speed is not None and not run.cancel.is_set():
            clip = run.deps.tts(run.host.dispatch, text, vdir / f"vo_{i:02d}.wav", None)
            if clip is not None:
                with lock:
                    unpaced += 1
        return i, clip

    with ThreadPoolExecutor(max_workers=TTS_WORKERS, thread_name_prefix=f"showreel-tts-{run.job_id[-4:]}") as pool:
        futures = [pool.submit(contextvars.copy_context().run, one, item) for item in lines]
        for fut in futures:
            try:
                i, clip = fut.result()
            except Exception as exc:  # noqa: BLE001
                i, clip = -1, None
                run.info(f"narration error: {exc}")
            with lock:
                done += 1
                if clip is None:
                    failures += 1
                else:
                    run.clips[i] = clip
            run.rep.progress(done / len(lines), f"narration {done}/{len(lines)}")
    run.cancel.check()
    if failures == len(lines):
        run.warn("narration failed for every line (TTS provider unavailable?); captions only")
    elif failures:
        run.warn(f"narration failed for {failures} of {len(lines)} lines; those scenes are captions only")
    if unpaced:
        run.warn(f"the TTS provider refused speed x{speed:g} for {unpaced} line(s); those use its normal pace")
    manifest: dict[str, Any] = {}
    for i in sorted(run.clips):
        c = run.clips[i]
        wpm = words_per_minute(c.text, float(c.duration))
        manifest[str(i)] = {"path": str(c.path), "duration": c.duration, "text": c.text, "wpm": wpm,
                            "speed": tts_speed or 1.0, "provider": getattr(c, "provider", "")}
        run.info(f"narration scene {i}: {len(c.text.split())} words in {float(c.duration):.2f}s = {wpm} wpm",
                 wpm=wpm, scene=i)
    rates = [m["wpm"] for m in manifest.values() if m["wpm"]]
    if rates:
        total_w = sum(len(m["text"].split()) for m in manifest.values())
        total_s = sum(float(m["duration"]) for m in manifest.values())
        overall = round(total_w * 60.0 / total_s, 1) if total_s > 0 else None
        run.info(f"narration pace overall {overall} wpm (clips {min(rates)}-{max(rates)} wpm, speed x{speed:g})")
        run.store.update(run.job_id, narration={"speed": speed, "wpm": overall, "clips": len(rates)})
    (vdir / "voice.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def _build_quick(run: _Run) -> None:
    """Timing + film + page for every aspect, with the launch style as the fallback build."""
    styles_to_try = [run.opts.style] + ([DEFAULT_STYLE] if run.opts.style != DEFAULT_STYLE else [])
    last_err: StageError | None = None
    for k, style in enumerate(styles_to_try):
        try:
            run.built = [_build_aspect(run, aspect, style) for aspect in run.opts.aspects]
            if k:
                run.warn(f"style '{run.opts.style}' could not be built; used '{style}' instead")
            run.store.update(run.job_id, style_used=style)
            return
        except Cancelled:
            raise
        except StageError as e:
            last_err = e
            if e.code == "film_runtime_missing":
                break
            run.info(f"film build with style {style} failed: {e.message}", level="warn")
        except Exception as e:  # noqa: BLE001
            last_err = StageError("film_build", f"{type(e).__name__}: {e}")
            run.info(f"film build with style {style} failed: {last_err.message}",
                     trace=traceback.format_exc()[-3000:])
    raise last_err or StageError("film_build", "the film could not be built")


def _sizes(opts: Options, aspect: str) -> tuple[int, int, int]:
    w, h = (PREVIEW_SIZES if opts.preview else ASPECT_SIZES).get(aspect, ASPECT_SIZES["16:9"])
    return w, h, PREVIEW_FPS if opts.preview else FINAL_FPS


def _build_aspect(run: _Run, aspect: str, style: str) -> Built:
    tag = ASPECT_TAG.get(aspect, "x")
    w, h, fps = _sizes(run.opts, aspect)
    bed = run.deps.pick_bed(style, run.seed)
    bpm = float(getattr(bed, "bpm", 0) or 120.0)
    durations = {i: float(c.duration) for i, c in run.clips.items()}
    tl = run.deps.solve(run.storyboard, run.bundle, durations, bpm, run.opts.seconds, aspect, fps, w, h, run.seed,
                        style)
    for sc in tl.scenes:
        clip = run.clips.get(int(sc.data.get("story_index", -1)))
        if clip is not None:
            sc.vo_path = str(clip.path)
    tl_path = run.job_dir / f"timeline_{tag}.json"
    tl_path.write_text(json.dumps(tl.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    paths = dict((run.store.load(run.job_id) or {}).get("timeline_paths") or {})
    paths[aspect] = str(tl_path)
    run.store.update(run.job_id, timeline_paths=paths, duration_s=tl.dur)
    page_dir = run.job_dir / f"page_{tag}"
    if page_dir.exists():
        shutil.rmtree(page_dir, ignore_errors=True)
    page_dir.mkdir(parents=True, exist_ok=True)
    found = blender_engine(run)
    qkw = {"blender": True} if found else {}
    made = run.deps.quick_film(tl, job_dir=run.job_dir, page_dir=page_dir, style=style, aspect=aspect,
                               preview=run.opts.preview, storyboard=run.storyboard, bundle=run.bundle, **qkw)
    film = made["film"]
    assets = made.get("assets")
    if found and (film.get("meta") or {}).get("blender_shots"):
        from .film.quick import revert_blender
        film, assets = blender_pass(run, film, assets, page_dir, tag, found, revert=revert_blender)
    page = run.deps.build_page(film, page_dir=page_dir, job_dir=run.job_dir, assets=assets,
                               scenes=made.get("scenes"))
    voices = [{"path": str(run.clips[int(sc.data["story_index"])].path), "start": float(sc.vo_t0),
               "duration": float(run.clips[int(sc.data["story_index"])].duration)}
              for sc in tl.scenes if int(sc.data.get("story_index", -1)) in run.clips]
    last_word = max((v["start"] + v["duration"] for v in voices), default=None)
    drop = next((float(sc.t0) for sc in tl.scenes if getattr(sc.type, "value", sc.type) == "STATS"), None)
    page, post, post_params = post_plan(film, page)
    return Built(aspect=aspect, page_dir=page_dir, page=page, w=w, h=h, fps=fps, dur=float(tl.dur),
                 out_size=_out_size(film, w, h), post=post, post_params=post_params, film=film,
                 cues=[{"t": c.t, "sfx": c.sfx, "gain_db": c.gain_db, "align": c.align} for c in tl.cues],
                 voices=voices, scene_times=[round((sc.t0 + sc.t1) / 2, 3) for sc in tl.scenes],
                 scene_labels=[getattr(sc.type, "value", str(sc.type)) for sc in tl.scenes],
                 drop_time=drop, last_word_time=last_word, style=style)


def post_plan(film: dict[str, Any], page: str = "stage.html") -> tuple[str, str, dict[str, Any]]:
    """(page, post chain, post_params) for a final render: the film's ``finish`` (grain/vignette/bloom) moves to
    ffmpeg post (``?finish=post``; in-page grain costs +40-60 % per frame in software mode) and is appended to a
    style's own ``film.render.post`` chain (e.g. terminal's ``crt``)."""
    from .film.render import post_for_finish
    render = film.get("render") if isinstance(film.get("render"), dict) else {}
    chains = [c for c in str(render.get("post") or "none").split("+") if c and c != "none"]
    params = dict(render.get("post_params") or {})
    fin_chain, fin_params = post_for_finish(film.get("finish"))
    for c in (x for x in fin_chain.split("+") if x and x != "none"):
        if c not in chains:
            chains.append(c)
            params.setdefault(c, fin_params.get(c, {}))
    base = page.split("?", 1)[0]
    return f"{base}?finish=post", ("+".join(chains) or "none"), params


def _out_size(film: dict[str, Any], w: int, h: int) -> tuple[int, int] | None:
    size = film.get("size") if isinstance(film, dict) else None
    if isinstance(size, (list, tuple)) and len(size) == 2 and (int(size[0]), int(size[1])) != (w, h):
        return (w, h)
    return None


def _gpu_ok(run: _Run) -> bool | None:
    """GPU decision from the (cached) render probe, for the Director's keyframe previews. Never raises."""
    if run.deps.gpu_ok is None:
        return None
    try:
        return run.deps.gpu_ok(run.store.root / "gpu_probe.json")
    except Exception as exc:  # noqa: BLE001
        run.info(f"GPU probe for previews failed: {exc}")
        return None


def _directed(run: _Run) -> list[Built] | None:
    """Directed mode: the Director writes film.json; ``None`` means fall back to Quick mode."""
    director = run.deps.director()
    if director is None:
        run.warn("Directed mode isn't in this build yet; made a Quick film with your options instead")
        return None
    run.rep.stage("storyboard", "the Director is planning the film")
    aspect = run.opts.aspects[0]
    if len(run.opts.aspects) > 1:
        run.warn(f"Directed films render one aspect per run; made {aspect}")
    w, h, fps = _sizes(run.opts, aspect)

    def progress(stage: str = "", frac: float = 0.0, note: str = "", **_: Any) -> None:
        run.cancel.check()
        run.rep.progress(frac, note or stage)

    import inspect
    offered = {"direction": run.opts.direction, "options": run.opts, "job_dir": run.job_dir, "job_id": run.job_id,
               "host": run.host, "llm": run.host.llm, "dispatch": run.host.dispatch, "effort": run.opts.effort,
               "progress": progress, "cancel": run.cancel, "store": run.store, "bundle": run.bundle,
               "session_id": run.job.get("session_id", ""), "digest": getattr(run.bundle, "digest", ""),
               "product": getattr(run.bundle, "product", None), "seconds": run.opts.seconds, "aspect": aspect,
               "fps": fps, "size": (w, h), "seed": run.seed, "notes": run.opts.notes, "style": run.opts.style,
               "hints": run.opts.hints, "voice_speed": run.opts.voice_speed,
               "engine_3d": run.opts.engine_3d}
    found = blender_engine(run)
    offered["blender"] = found.to_dict() if found else None   # the Director may write blender: shots when set
    try:
        params = inspect.signature(director).parameters
        takes_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        if takes_all or "gpu" in params:
            offered["gpu"] = _gpu_ok(run)        # previews on the GPU like the final render (ISSUES #17)
        kwargs = offered if takes_all else {k: v for k, v in offered.items() if k in params}
        result = director(**kwargs)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        run.warn(f"the Director failed ({type(exc).__name__}: {exc}); made a Quick film instead")
        return None
    res = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
    if res.get("status") == "cancelled":
        raise Cancelled()
    film_path = res.get("film_path") or ""
    film = res.get("film") or (json.loads(Path(film_path).read_text(encoding="utf-8")) if film_path else None)
    if not res.get("ok") or not film:
        if res.get("quick_style"):
            run.opts = replace(run.opts, style=str(res["quick_style"]))
        run.warn(f"the Director could not finish ({res.get('error') or res.get('fallback') or 'no film'}); "
                 "made a Quick film instead")
        return None
    run.title = str(film.get("title") or "Showreel")
    run.store.update(run.job_id, title=run.title, director={k: v for k, v in res.items() if k not in ("film", "log")})
    run.rep.stage("layout", "building the film")
    director_dir = Path(res.get("job_dir") or run.job_dir)
    built_dir = next((Path(d) for d in (res.get("page_dir"), director_dir) if d and (Path(d) / "stage.html").is_file()
                      and (Path(d) / "film.json").is_file()), None)
    from .blender.film import blender_shots
    if blender_shots(film):
        if not found:
            run.warn("the Director's film has Blender shots but Blender is not available; made a Quick film instead")
            return None
        page_dir = run.job_dir / "page"
        page_dir.mkdir(parents=True, exist_ok=True)
        scenes = ({str(k): Path(v) for k, v in (res.get("scene_files") or {}).items()}
                  or {f"custom:{p.stem}": p for p in sorted((director_dir / "scenes").glob("*.js"))})
        film, assets = blender_pass(run, film, dict(res.get("assets") or {}), page_dir, "directed", found,
                                    revert=None, scenes=scenes)
        page = run.deps.build_page(film, page_dir=page_dir, job_dir=run.job_dir, assets=assets, scenes=scenes)
    elif built_dir is not None:
        page_dir, page = built_dir, "stage.html"          # the Director built (and dry-ran) its final page
    else:
        page_dir = run.job_dir / "page"
        page_dir.mkdir(parents=True, exist_ok=True)
        scenes = ({str(k): Path(v) for k, v in (res.get("scene_files") or {}).items()}
                  or {f"custom:{p.stem}": p for p in sorted((director_dir / "scenes").glob("*.js"))})
        page = run.deps.build_page(film, page_dir=page_dir, job_dir=run.job_dir, assets=res.get("assets") or {},
                                   scenes=scenes)
    dur = float(film.get("dur") or run.opts.seconds)
    shots = film.get("shots") or []
    cues = [c for c in film.get("cues") or [] if isinstance(c, dict)]
    cues += [{"t": m["t"], "sfx": m["sting"]} for m in film.get("music") or [] if isinstance(m, dict) and "sting" in m]
    voices = [v for v in film.get("narration") or [] if isinstance(v, dict) and v.get("path")]
    page, post, post_params = post_plan(film, page)
    last_word = max((float(v.get("start", 0)) + float(v.get("duration", 0)) for v in voices), default=None)
    drop = next((float(c["t"]) for c in cues if str(c.get("sfx")) in ("hit", "hero", "impact")), None)
    run.built = [Built(aspect=aspect, page_dir=page_dir, page=page, w=w, h=h, fps=fps, dur=dur, film=film,
                       post=post, post_params=post_params, last_word_time=last_word, drop_time=drop,
                       cues=cues, voices=voices, style=run.opts.style,
                       scene_times=[round((float(s.get("t0", 0)) + float(s.get("t1", 0))) / 2, 3) for s in shots],
                       scene_labels=[str(s.get("id", "")) for s in shots])]
    run.store.update(run.job_id, duration_s=dur)
    return run.built


def blender_engine(run: _Run) -> Any:
    """The user's Blender when this film should use it (``engine_3d`` blender/auto), else None. Located once per
    run; when the user asked for Blender and it is missing, the job log says so and 3D stays in the browser."""
    eng = str(getattr(run.opts, "engine_3d", "browser") or "browser")
    if eng == "browser":
        return None
    if run.blender is not None:
        return run.blender or None
    found = run.deps.blender_locate(getattr(run.opts, "blender_path", "") or None)
    if getattr(found, "ok", False):
        run.blender = found
        run.info(f"3D engine: Blender {found.version_string} ({found.path})")
        return found
    run.blender = ""
    msg = getattr(found, "message", "Blender was not found.")
    if eng == "blender":
        run.warn(f"{msg} Made the 3D shots in the browser (three.js) instead.")
    else:
        run.info(f"3D engine: browser (engine_3d auto, no Blender: {msg})")
    return None


def blender_pass(run: _Run, film: dict[str, Any], assets: dict[str, Any] | None, page_dir: Path, tag: str,
                 found: Any, *, revert: Callable[[dict[str, Any]], dict[str, Any]] | None,
                 scenes: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Render the film's ``blender:`` shots into ``page_dir`` (cache under ``job_dir/blender/<tag>``) and return
    ``(film, assets)`` for ``build_page``. On failure: ``revert(film)`` (Quick: browser originals) with a warning,
    or StageError when there is no fallback (Directed). Progress: "Blender: shot k/n, frame f/N, ETA ..."."""
    tier = "preview" if run.opts.preview else "final"

    def progress(ev: dict[str, Any]) -> None:
        frames, frame = int(ev.get("frames") or 0), int(ev.get("frame") or 0)
        if ev.get("phase") == "eta" and ev.get("eta_s") is not None:
            run.info(str(ev.get("message")))           # "Blender shots: ~9 min on your GPU" in the job log
        run.rep.progress(frame / frames if frames else 0.0, str(ev.get("message") or "Blender"),
                         eta_s=ev.get("eta_s"))

    n_shots = sum(1 for s in film.get("shots") or [] if str(s.get("scene", "")).startswith("blender:"))
    run.info(f"Blender pass ({tier}): {n_shots} shot(s)")
    bp = run.deps.blender_pass(film, page_dir, blender=found, tier=tier, assets=dict(assets or {}), scenes=scenes,
                               progress=progress, cancel=lambda: run.cancel.is_set(),
                               cache_dir=run.job_dir / "blender" / tag)
    run.store.update(run.job_id, blender=bp.to_dict() if hasattr(bp, "to_dict") else {})
    if getattr(bp, "cancelled", False):
        raise Cancelled()
    if bp.ok:
        run.info(bp.message)
        for w in bp.warnings[:6]:
            run.warn(f"Blender: {w}")
        return bp.film, {**bp.browser_assets, **bp.manifest}
    if revert is None:
        raise StageError("blender", f"the Blender shots failed: {bp.message}")
    run.warn(f"Blender could not render the 3D shots ({bp.message}); made them in the browser instead")
    film = revert(film)
    keep = {n: a for n, a in (assets or {}).items() if n in (film.get("assets") or {})}
    return film, keep


def _back_half(run: _Run) -> None:
    """Layout QA -> render -> audio -> mux -> QA -> delivery, per aspect."""
    if not _RENDER_LOCK.acquire(blocking=False):
        run.rep.progress(0.0, "waiting for another showreel to finish", force=True)
        while not _RENDER_LOCK.acquire(timeout=1.0):
            run.cancel.check()
    try:
        _layout(run)
        run.cancel.check()
        run.rep.stage("render", "rendering")
        videos = _render_all(run)
        run.cancel.check()
        run.rep.stage("mix", "mixing music, narration and sound")
        finals = _audio_all(run, videos)
    finally:
        _RENDER_LOCK.release()
    run.cancel.check()
    run.rep.stage("qa", "checking the video")
    _qa_and_deliver(run, finals)


def _layout(run: _Run) -> None:
    if run.deps.layout_qa is None:
        return
    report: dict[str, Any] = {}
    thumbs: list[str] = []
    for k, b in enumerate(run.built):
        run.cancel.check()
        res = run.deps.layout_qa(b, b.scene_times[:24], run.job_dir / "thumbs" if k == 0 else None)
        if res.get("fatal"):
            raise StageError("page_broken", f"the film page failed to load: {res['fatal'].get('message')}",
                             res["fatal"].get("hint", ""))
        issues = res.get("issues") or []
        report[b.aspect] = {"issues": issues[:200], "errors": (res.get("errors") or [])[:50]}
        page_cues = [c for c in res.get("cues") or [] if isinstance(c, dict) and "t" in c and "sfx" in c]
        known = {(round(float(c["t"]), 2), c["sfx"]) for c in b.cues}
        b.cues += [c for c in page_cues if (round(float(c["t"]), 2), c["sfx"]) not in known]
        thumbs += res.get("thumbs") or []
        if issues:
            run.warn(f"layout QA {b.aspect}: {len(issues)} issue(s), e.g. {issues[0].get('msg', '')}"[:300])
        run.rep.progress((k + 1) / len(run.built))
    (run.job_dir / "layout_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    run.store.update(run.job_id, thumbs=thumbs)


def _render_spec(run: _Run, b: Built, *, gpu: str, workers: int | None) -> Any:
    from .render.workers import RenderSpec
    tag = ASPECT_TAG.get(b.aspect, "x")
    w, h = b.w, b.h
    if b.out_size:
        size = b.film.get("size") or [w, h]
        w, h = int(size[0]), int(size[1])
    return RenderSpec(page_dir=b.page_dir, out_path=run.job_dir / f"video_{tag}.mp4", w=w, h=h, fps=float(b.fps),
                      page=b.page, duration_s=b.dur, out_size=b.out_size, post=b.post, post_params=b.post_params,
                      seed=run.seed, workers=workers, gpu=gpu, work_dir=run.job_dir / f"chunks_{tag}",
                      gpu_cache=run.store.root / "gpu_probe.json")


def _render_all(run: _Run) -> dict[str, Path]:
    total_frames = sum(max(1, round(b.dur * b.fps)) for b in run.built)
    run.rep.render_estimate_s = total_frames / ASSUMED_RENDER_FPS
    done_before = 0
    videos: dict[str, Path] = {}
    for b in run.built:
        frames_b = max(1, round(b.dur * b.fps))

        def progress(done: int, total: int, eta: float | None, _base: int = done_before, b: Built = b) -> None:
            frac = (_base + done) / max(1, total_frames)
            rest_eta = None if eta is None else eta + (total_frames - _base - total) / ASSUMED_RENDER_FPS
            if rest_eta is not None:
                rest_eta += 20.0
            run.rep.progress(frac, f"rendering {b.aspect} {done}/{total} frames", eta_s=rest_eta)
            run.cancel.is_set()     # polls the cancel flag file; the event stops the renderer

        res = None
        for attempt, (gpu, workers) in enumerate((("auto", run.opts.workers), ("off", 1))):
            res = run.deps.render(_render_spec(run, b, gpu=gpu, workers=workers), progress, run.cancel.event)
            err = getattr(res, "error", None) or {}
            if getattr(res, "ok", False) or err.get("code") == "cancelled" or err.get("code") in (
                    "no_browser", "no_ffmpeg", "bad_env_browser", "bad_env_ffmpeg", "page_contract"):
                break
            if attempt == 0:
                run.warn(f"render failed ({err.get('code')}: {err.get('message')}); retrying in software mode")
        err = getattr(res, "error", None) or {}
        if run.cancel.is_set() or err.get("code") == "cancelled":
            raise Cancelled()
        if res is None or not getattr(res, "ok", False):
            raise StageError(str(err.get("code") or "render"), str(err.get("message") or "render failed"),
                             str(err.get("hint") or ""))
        rd = res.to_dict() if hasattr(res, "to_dict") else {}
        run.info(f"rendered {b.aspect}", render={k: rd.get(k) for k in (
            "frames", "wall_s", "render_fps", "workers", "gpu", "encoder", "restarts", "warnings", "page_errors",
            "blocked_urls")})
        for w in (rd.get("warnings") or [])[:5]:
            run.warn(f"render {b.aspect}: {w}")
        videos[b.aspect] = Path(res.out_path)
        done_before += frames_b
    return videos


def _audio_all(run: _Run, videos: dict[str, Path]) -> dict[str, Path]:
    """Music + narration + SFX per aspect, muxed onto the video. Every failure degrades, none is fatal."""
    finals: dict[str, Path] = {}
    mixes: dict[tuple[Any, ...], tuple[Path | None, Any]] = {}
    report: dict[str, Any] = {}
    for k, b in enumerate(run.built):
        run.cancel.check()
        tag = ASPECT_TAG.get(b.aspect, "x")
        key = (round(b.dur, 3), json.dumps(b.cues, sort_keys=True, default=str),
               json.dumps(b.voices, sort_keys=True, default=str))
        if key not in mixes:
            mixes[key] = _mix_one(run, b, tag)
        audio, mres = mixes[key]
        final = run.job_dir / f"showreel_{tag}.mp4"
        if audio is not None:
            try:
                run.deps.mux(videos[b.aspect], audio, final, b.dur)
            except Exception as exc:  # noqa: BLE001
                run.warn(f"muxing audio failed ({exc}); delivering the video without sound")
                audio = None
        if audio is None:
            shutil.copy2(videos[b.aspect], final)
        elif run.deps.audio_report is not None:
            try:
                report[b.aspect] = run.deps.audio_report(audio, b.dur, mres, not b.voices)
            except Exception as exc:  # noqa: BLE001
                report[b.aspect] = {"error": str(exc)}
        finals[b.aspect] = final
        run.rep.progress((k + 1) / len(run.built))
    if report:
        (run.job_dir / "audio_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return finals


MUSIC_XFADE_S = 0.6


def _cue_sheet(run: _Run, b: Built, plan: list[dict[str, Any]], out: Path) -> Path:
    """Multi-bed music (``film.music = [{bed, t0, t1}, ...]``, beds of any style): each bed is bar-fitted to its
    segment (the drop / last word land in the segment that holds them) and the segments are joined with
    ``MUSIC_XFADE_S`` crossfades; the total length equals the film. Raises on any failure (caller falls back)."""
    segs = sorted(plan, key=lambda m: float(m.get("t0", 0)))
    bounds = [max(0.0, float(m.get("t0", 0))) for m in segs] + [b.dur]
    bounds[0] = 0.0
    parts: list[Path] = []
    ids = []
    for i, m in enumerate(segs):
        t0, t1 = bounds[i], min(b.dur, bounds[i + 1])
        if t1 - t0 < 1.0:
            continue
        bed = run.deps.pick_bed(b.style, run.seed, str(m["bed"]))
        if bed is None:
            raise RuntimeError(f"bed {m['bed']!r} not found")
        seg = t1 - t0 + (MUSIC_XFADE_S if i < len(segs) - 1 else 0.0)
        drop = b.drop_time - t0 if b.drop_time is not None and t0 <= b.drop_time < t1 else None
        last = b.last_word_time - t0 if b.last_word_time is not None and i == len(segs) - 1 and b.last_word_time > t0 else None
        fitted = run.deps.fit_music(bed, seg, out.parent / f"music_{i}.wav", drop, last)
        parts.append(Path(getattr(fitted, "path", out.parent / f"music_{i}.wav")))
        ids.append(getattr(bed, "id", str(m["bed"])))
    if not parts:
        raise RuntimeError("no usable music segment")
    run.deps.join_music(parts, MUSIC_XFADE_S, out)
    run.info(f"music cue sheet: {' -> '.join(ids)} ({len(parts)} segment(s), {MUSIC_XFADE_S}s crossfades)")
    return out


def _designed_cue_sheet(run: _Run, b: Built, out: Path) -> tuple[Path, list[dict[str, Any]]]:
    """``film.music`` through ``deps.fit_cue_sheet``: the music track and the stings it already contains."""
    music = [m for m in (b.film.get("music") or []) if isinstance(m, dict)]
    res = run.deps.fit_cue_sheet(music, b.dur, out, style=b.style, seed=run.seed, drop_time=b.drop_time,
                                 last_word_time=b.last_word_time)
    for w in (getattr(res, "warnings", None) or [])[:3]:
        run.info(f"music: {w}")
    segs = getattr(res, "segments", None) or []
    joins = [str(getattr(s, "bed_id", "?")) + (f" -{s.join_out}->" if getattr(s, "join_out", "final") != "final" else "")
             for s in segs]
    run.info(f"music cue sheet: {' '.join(joins)} ({len(segs)} segment(s), designed joins)")
    return Path(getattr(res, "path", out)), list(getattr(res, "consumed", None) or [])


def _music_track(run: _Run, b: Built, out: Path) -> tuple[Path | None, list[dict[str, Any]]]:
    """Fit the film's bed(s) to its length -> (music, stings rendered into it); music ``None`` (with a warning)
    when none can be made."""
    plan = [m for m in (b.film.get("music") or []) if isinstance(m, dict) and m.get("bed")]
    bed_id = str(plan[0]["bed"]) if len(plan) >= 1 else None
    if len(plan) > 1 and run.deps.fit_cue_sheet is not None:
        try:
            return _designed_cue_sheet(run, b, out)
        except Exception as exc:  # noqa: BLE001 - fall back to per-bed fits + crossfades
            run.info(f"designed cue sheet failed ({exc}); crossfading per-bed fits", level="warn")
    if len(plan) > 1:
        try:
            return _cue_sheet(run, b, plan, out), []
        except Exception as exc:  # noqa: BLE001 - fall back to one bed for the whole film
            run.warn(f"multi-bed music failed ({exc}); the first bed plays the whole film")
    bed = None
    if bed_id:
        with contextlib.suppress(Exception):
            bed = run.deps.pick_bed(b.style, run.seed, bed_id)
    bed = bed or run.deps.pick_bed(b.style, run.seed)
    if bed is None:
        run.warn("no music bed for this style; the film has no music")
        return None, []
    try:
        fitted = run.deps.fit_music(bed, b.dur, out, b.drop_time, b.last_word_time)
    except Exception as exc:  # noqa: BLE001
        run.warn(f"music could not be fitted ({exc}); the film has no music")
        return None, []
    for w in (getattr(fitted, "warnings", None) or [])[:3]:
        run.info(f"music: {w}")
    run.info(f"music bed {getattr(fitted, 'bed_id', '?')} at {getattr(fitted, 'bpm', '?')} bpm")
    return Path(getattr(fitted, "path", out)), []


def _mix_one(run: _Run, b: Built, tag: str) -> tuple[Path | None, Any]:
    mdir = run.job_dir / f"mix_{tag}"
    mdir.mkdir(parents=True, exist_ok=True)
    music, in_music = _music_track(run, b, mdir / "music.wav")
    cues = [c for c in b.cues if not (isinstance(c, dict) and any(
        str(c.get("sfx")) == str(m.get("sting")) and abs(float(c.get("t", -1)) - float(m.get("t", -9))) < 2e-3
        for m in in_music))]
    try:
        sfx, warns = run.deps.place_sfx(cues, b.dur, b.style, b.fps)
    except Exception as exc:  # noqa: BLE001
        sfx, warns = [], [f"SFX placement failed: {exc}"]
    for w in warns[:4]:
        run.info(f"sfx: {w}")
    attempts = [(music, b.voices, sfx, "full mix"), (music, b.voices, [], "mix without SFX"),
                (None, b.voices, [], "mix without music"), (music, [], [], "music only")]
    for music_i, voices_i, sfx_i, label in attempts:
        if label != "full mix" and not (music_i or voices_i):
            continue
        try:
            res = run.deps.mix(mdir / "mix.wav", b.dur, music=music_i, voices=voices_i, sfx=sfx_i, work_dir=mdir)
            if label != "full mix":
                run.warn(f"audio fallback: {label}")
            return Path(getattr(res, "path", mdir / "mix.wav")), res
        except Exception as exc:  # noqa: BLE001
            run.info(f"{label} failed: {exc}", level="warn")
    run.warn("audio could not be mixed; the film is silent")
    return None, None


def _qa_and_deliver(run: _Run, finals: dict[str, Path]) -> None:
    qa: dict[str, Any] = {}
    delivered: dict[str, str] = {}
    contact = ""
    for k, b in enumerate(run.built):
        run.cancel.check()
        final = finals[b.aspect]
        tag = ASPECT_TAG.get(b.aspect, "x")
        if run.deps.check_video is not None:
            try:
                rep = run.deps.check_video(final, frames=max(1, round(b.dur * b.fps)), dur=b.dur, fps=b.fps,
                                           times=b.scene_times, labels=b.scene_labels,
                                           contact_sheet=run.job_dir / f"contact_{tag}.png")
            except Exception as exc:  # noqa: BLE001
                rep = {"ok": False, "error": {"message": str(exc)}}
            qa[b.aspect] = rep
            for issue in (rep.get("issues") or [])[:5]:
                run.warn(f"video QA {b.aspect}: {issue.get('msg')}")
            if rep.get("contact_sheet") and not contact:
                contact = str(rep["contact_sheet"])
        try:
            delivered[b.aspect] = str(run.deps.deliver(final, title=run.title or "showreel", job_id=run.job_id,
                                                       aspect=b.aspect))
        except Exception as exc:  # noqa: BLE001
            run.warn(f"could not copy the film to Hermes' video folder ({exc}); use the job copy")
            delivered[b.aspect] = str(final)
        run.rep.progress((k + 1) / len(run.built))
    (run.job_dir / "qa_report.json").write_text(json.dumps(qa, indent=1, default=str), encoding="utf-8")
    run.store.update(run.job_id, outputs={a: str(p) for a, p in finals.items()}, delivered=delivered, qa=qa,
                     contact_sheet=contact, title=run.title)


# ------------------------------------------------------------------------------ dev harness

def _dev_main(argv: list[str] | None = None) -> int:
    """``python -m showreel_core.pipeline --session latest --style launch --seconds 30``: one job, outside Hermes."""
    import argparse

    from .commands import describe
    from .llm import edge_tts_dispatch, hermes_cli_story_llm

    ap = argparse.ArgumentParser(prog="python -m showreel_core.pipeline", description=_dev_main.__doc__)
    ap.add_argument("--session", default="latest")
    ap.add_argument("--style", default=DEFAULT_STYLE)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--aspect", default="16:9", help="16:9 | 9:16 | both | 1:1")
    ap.add_argument("--mode", default="product")
    ap.add_argument("--direction", default="")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--llm", default="none", choices=("none", "hermes-cli"))
    ap.add_argument("--tts", default="none", choices=("none", "edge"))
    ap.add_argument("--data-dir", default="", help="job store root (default: plugin data dir)")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    opts = Options(style=args.style, seconds=args.seconds, aspects=[args.aspect], mode=args.mode,
                   voice=args.tts != "none", preview=args.preview, direction=args.direction,
                   workers=args.workers or None).normalised()
    store = JobStore(Path(args.data_dir)) if args.data_dir else JobStore()
    host = Host(story_llm=hermes_cli_story_llm() if args.llm == "hermes-cli" else None,
                dispatch=edge_tts_dispatch() if args.tts == "edge" else None, label="dev")
    job = store.create(args.session, opts.to_dict(), kind="directed" if opts.directed else "quick", surface="dev")
    print(f"job {job['id']} in {store.job_dir(job['id'])}: {describe(opts)}", flush=True)

    class _Echo:
        ok = True

        def edit(self, text: str) -> None:
            print(text, flush=True)

    t0 = time.monotonic()
    final = run_job(job["id"], host, store=store, handle=_Echo())
    print(json.dumps({k: final.get(k) for k in ("stage", "error", "title", "duration_s", "storyboard_source",
                                                 "stages", "wall_s", "outputs", "delivered", "contact_sheet",
                                                 "warnings")}, indent=1, default=str))
    print(f"wall {time.monotonic() - t0:.1f}s")
    return 0 if final.get("stage") == "done" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_dev_main())
