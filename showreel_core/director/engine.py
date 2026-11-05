"""The Director Engine: free-text direction -> treatment -> film.json -> custom scene code -> lint ->
build + dry run (repair / kit fallback) -> keyframes -> contact sheet -> vision critique -> surgical
revisions, until every rubric score reaches the bar or the effort budget is spent; the best-scoring
version becomes ``film.json``. Every artefact is persisted under ``<job>/director/``; the renderable
page is ``<job>/page/`` (the pipeline renders the final video from it).

Public API (never raises; returns :class:`DirectorResult`)::

    run(brief, *, llm, renderer=None, effort="standard", progress=None, cancel=None, job_dir=..., library_dir=...)
    revise(parent_job_dir, notes, *, llm, renderer=None, effort="standard", job_dir=None, ...)

``run`` also accepts the pipeline's keyword set (``direction``, ``product``, ``digest``, ``seconds``, ``aspect``,
``fps``, ``seed``, ``notes``, ``bundle``, ``options``, ``store``, ``job_id``, raw ``ctx.llm`` as ``llm``...).
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Product
from ..story.schema import parse_json_text
from . import prompts
from .backend import Preview, Renderer, RuntimeRenderer, ShotError
from .catalog import Catalog, build_catalog
from .checks import (
    check_film,
    check_treatment,
    extract_js,
    fallback_params,
    first_product_time,
    lint_scene,
    nearest_kit_scene,
    normalize_scene_code,
    product_share,
)
from .library import save_scene
from .llm import BudgetExceeded, CallLedger, Cancelled, DirectorLlm, Image, LlmReply, hermes_llm, is_cancelled
from .sheet import Frame, contact_sheets, plan_keyframes
from .types import (
    EFFORTS,
    PRODUCT_SHARE_BAR,
    RUBRIC_KEYS,
    SCORE_BAR,
    Brief,
    Budget,
    DirectorResult,
    MediaAsset,
    RoundScore,
    brief_from_dict,
)

log = logging.getLogger(__name__)

QUICK_STYLES = ("launch", "pixel", "terminal", "blueprint", "cinematic", "comic", "ink", "newspaper")
ProgressFn = Callable[..., Any]


# ------------------------------------------------------------------------------------ state

@dataclass
class Version:
    """One complete candidate film: script, plan, live scene code, fallbacks, its preview and its score."""
    n: int
    film: dict[str, Any]
    plan: dict[str, Any]
    scenes: dict[str, str] = field(default_factory=dict)        # custom scene name -> code
    fallbacks: dict[str, str] = field(default_factory=dict)     # custom scene name -> kit scene used instead
    tries: dict[str, int] = field(default_factory=dict)         # code attempts used per custom scene
    stable: dict[str, str] = field(default_factory=dict)        # code that passed the previous version's dry run
    frames: list[Frame] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    preview: Preview | None = None
    score: RoundScore | None = None
    critique: dict[str, Any] | None = None
    changes: list[str] = field(default_factory=list)

    @property
    def customs(self) -> dict[str, dict[str, Any]]:
        return {c["name"]: c for c in self.plan.get("custom_scenes") or []}

    def key(self) -> tuple[float, ...]:
        s = self.score
        return (1.0 if s and s.passed else 0.0, s.mean if s else 0.0, s.min if s else 0.0, -len(self.fallbacks),
                float(self.n))


class _Run:
    """Per-run context: brief, catalog, budget, ledger, dirs, progress, log."""

    def __init__(self, brief: Brief, catalog: Catalog, budget: Budget, llm: DirectorLlm, renderer: Renderer,
                 job_dir: Path, library_dir: Path | None, progress: ProgressFn | None, cancel: Any,
                 effort: str) -> None:
        self.brief, self.catalog, self.budget, self.renderer = brief, catalog, budget, renderer
        self.job_dir, self.library_dir, self.effort = job_dir, library_dir, effort
        self.ddir = job_dir / "director"
        self.page_dir = job_dir / "page"
        self.ddir.mkdir(parents=True, exist_ok=True)
        self.ledger = CallLedger(llm, self.ddir / "calls", max_calls=budget.max_calls, cancel=cancel)
        self.progress_cb, self.cancel = progress, cancel
        self.log: list[dict[str, Any]] = []
        self.t0 = time.monotonic()
        self.frac = 0.0
        self.versions: list[Version] = []
        self.treatment: dict[str, Any] = {}
        self.built_n = 0                                     # version currently built into page_dir

    # -------------------------------------------------------------- events
    def emit(self, step: str, msg: str, frac: float | None = None, level: str = "info", **extra: Any) -> None:
        if frac is not None:
            self.frac = max(self.frac, min(1.0, frac))
        entry = {"t": round(time.monotonic() - self.t0, 2), "step": step, "msg": msg, "level": level, **extra}
        self.log.append(entry)
        try:
            with (self.ddir / "log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
        if self.progress_cb is not None:
            try:
                self.progress_cb(stage=step, frac=self.frac, note=msg, level=level, **extra)
            except Exception as exc:
                if type(exc).__name__ == "Cancelled":
                    raise Cancelled("cancelled") from exc
                log.debug("progress callback failed: %s", exc)
        self.check_cancel()

    def warn(self, step: str, msg: str) -> None:
        self.emit(step, msg, level="warning")

    def check_cancel(self) -> None:
        if is_cancelled(self.cancel):
            raise Cancelled("cancelled")

    def save(self, rel: str, obj: Any) -> Path:
        p = self.ddir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False, default=str),
                     encoding="utf-8")
        return p

    def ask(self, purpose: str, instructions: str, text: str, *, schema: dict[str, Any] | None = None,
            schema_name: str | None = None, images: list[Image] | None = None, temperature: float = 0.7,
            max_tokens: int = 8000, timeout: float = 300.0) -> LlmReply:
        return self.ledger(purpose=purpose, instructions=instructions, text=text, images=images or [],
                           json_schema=schema, schema_name=schema_name, temperature=temperature,
                           max_tokens=max_tokens, timeout=timeout)


def _json_of(reply: LlmReply) -> Any:
    if reply.parsed is not None:
        return reply.parsed
    obj, _err = parse_json_text(reply.text)
    return obj


# ------------------------------------------------------------------------------------ public API

def run(brief: Brief | None = None, *, llm: Any = None, renderer: Renderer | None = None, effort: str = "standard",
        progress: ProgressFn | None = None, cancel: Any = None, job_dir: str | Path | None = None,
        library_dir: str | Path | None = None, catalog: Catalog | None = None, save_library: bool = True,
        budget: Budget | None = None, **kwargs: Any) -> DirectorResult:
    """Direct one film from a free-text brief. Never raises (see module docstring)."""
    t0 = time.monotonic()
    jd = Path(job_dir) if job_dir else Path.cwd() / "director-job"
    llm = kwargs.get("director_llm") or llm or getattr(kwargs.get("host"), "llm", None)
    try:
        brief = brief or brief_from_kwargs(kwargs, jd)
        opts = kwargs.get("options")
        effort = str(getattr(opts, "effort", "") or effort)
        parent = _parent_dir(kwargs)
        if brief.notes.strip() and parent and (parent / "director" / "state.json").is_file():
            return revise(parent, brief.notes, llm=llm, renderer=renderer, effort=effort, progress=progress,
                          cancel=cancel, job_dir=jd, library_dir=library_dir, catalog=catalog,
                          save_library=save_library, budget=budget)
        r = _setup(brief, llm, renderer, effort, progress, cancel, jd, library_dir, catalog, budget)
        return _finish(r, _produce(r), save_library, t0)
    except Cancelled:
        return DirectorResult(False, "cancelled", str(jd), error="cancelled", seconds=time.monotonic() - t0)
    except Exception as exc:
        if type(exc).__name__ == "Cancelled":
            return DirectorResult(False, "cancelled", str(jd), error="cancelled", seconds=time.monotonic() - t0)
        log.exception("director failed")
        return DirectorResult(False, "failed", str(jd), fallback="quick",
                              quick_style=guess_style(brief.direction if brief else ""),
                              error=f"{type(exc).__name__}: {exc}", seconds=time.monotonic() - t0)


def revise(parent_job_dir: str | Path, notes: str, *, llm: Any = None, renderer: Renderer | None = None,
           effort: str = "standard", progress: ProgressFn | None = None, cancel: Any = None,
           job_dir: str | Path | None = None, library_dir: str | Path | None = None, catalog: Catalog | None = None,
           save_library: bool = True, budget: Budget | None = None) -> DirectorResult:
    """``/showreel revise <notes>``: another pass on a finished Director film with the user's notes."""
    t0 = time.monotonic()
    parent = Path(parent_job_dir)
    jd = Path(job_dir) if job_dir else parent
    try:
        state = json.loads((parent / "director" / "state.json").read_text(encoding="utf-8"))
        brief = brief_from_dict(state["brief"])
        brief.notes = notes
        r = _setup(brief, llm, renderer, effort, progress, cancel, jd, library_dir, catalog, budget)
        r.treatment = state.get("treatment") or {}
        best_n = int(state.get("best") or 0)
        vdir = parent / "director" / f"v{best_n}"
        base = Version(0, json.loads((vdir / "film.json").read_text(encoding="utf-8")),
                       json.loads((vdir / "plan.json").read_text(encoding="utf-8")))
        base.scenes = {p.stem: p.read_text(encoding="utf-8") for p in sorted((vdir / "scenes").glob("*.js"))}
        fb = vdir / "fallbacks.json"
        base.fallbacks = json.loads(fb.read_text(encoding="utf-8")) if fb.is_file() else {}
        r.save("treatment.json", r.treatment)
        r.emit("revise", f"Revising {state.get('title') or 'the film'} with your notes", 0.05)
        return _finish(r, _produce(r, start=base), save_library, t0)
    except Cancelled:
        return DirectorResult(False, "cancelled", str(jd), error="cancelled", seconds=time.monotonic() - t0)
    except Exception as exc:
        if type(exc).__name__ == "Cancelled":
            return DirectorResult(False, "cancelled", str(jd), error="cancelled", seconds=time.monotonic() - t0)
        log.exception("director revise failed")
        return DirectorResult(False, "failed", str(jd), error=f"{type(exc).__name__}: {exc}",
                              seconds=time.monotonic() - t0)


# ------------------------------------------------------------------------------------ setup

def brief_from_kwargs(kw: dict[str, Any], job_dir: Path) -> Brief:
    """Build a :class:`Brief` from the pipeline's keyword set."""
    opts = kw.get("options")
    product = kw.get("product")
    bundle = kw.get("bundle")
    if product is None and bundle is not None:
        product = getattr(bundle, "product", None)
    size = kw.get("size")
    aspect = str(kw.get("aspect") or (getattr(opts, "aspects", None) or ["16:9"])[0])
    if isinstance(size, (list, tuple)) and len(size) == 2 and int(size[1]) > int(size[0]):
        aspect = "9:16"
    assets = []
    for a in kw.get("assets") or []:
        if isinstance(a, MediaAsset):
            assets.append(a)
        elif isinstance(a, dict):
            assets.append(MediaAsset(**{k: v for k, v in a.items() if k in MediaAsset.__dataclass_fields__}))
        elif isinstance(a, (str, Path)):
            from .media import probe_asset
            assets.append(probe_asset(a, out_dir=job_dir / "director" / "media"))
    if not assets and bundle is not None:
        from .media import assets_from_bundle
        assets = assets_from_bundle(bundle, job_dir / "director" / "media")
    return Brief(
        direction=str(kw.get("direction") or getattr(opts, "direction", "") or ""),
        product=product if isinstance(product, Product) else None,
        digest=str(kw.get("digest") or getattr(bundle, "digest", "") or ""),
        assets=assets,
        seconds=float(kw.get("seconds") or getattr(opts, "seconds", 45) or 45),
        aspect=aspect, fps=int(kw.get("fps") or 30), seed=int(kw.get("seed") or 7),
        notes=str(kw.get("notes") or getattr(opts, "notes", "") or ""),
    )


def _parent_dir(kw: dict[str, Any]) -> Path | None:
    if kw.get("parent_job_dir"):
        return Path(kw["parent_job_dir"])
    store, job_id = kw.get("store"), kw.get("job_id")
    try:
        parent = (store.load(job_id) or {}).get("parent") if store is not None and job_id else ""
        return Path(store.job_dir(parent)) if parent else None
    except Exception:  # noqa: BLE001
        return None


def _as_director_llm(llm: Any) -> DirectorLlm:
    if llm is None:
        raise ValueError("the Director needs a model (ctx.llm)")
    if hasattr(llm, "complete_structured"):
        return hermes_llm(llm)
    host_llm = getattr(llm, "llm", None)
    if host_llm is not None and hasattr(host_llm, "complete_structured"):
        return hermes_llm(host_llm)
    if callable(llm):
        return llm  # type: ignore[no-any-return]
    raise ValueError(f"unsupported llm object {type(llm).__name__}")


def _setup(brief: Brief, llm: Any, renderer: Renderer | None, effort: str, progress: ProgressFn | None,
           cancel: Any, job_dir: Path, library_dir: str | Path | None, catalog: Catalog | None,
           budget: Budget | None = None) -> _Run:
    effort = effort if effort in EFFORTS else "standard"
    lib = Path(library_dir) if library_dir else None
    if lib is None:
        try:
            from .library import default_library_dir
            lib = default_library_dir()
        except Exception:  # noqa: BLE001
            lib = None
    cat = catalog or build_catalog(library_dir=lib, assets=brief.assets, capabilities=brief.capabilities)
    if not cat.assets:
        cat.assets = list(brief.assets)
    r = _Run(brief, cat, budget or EFFORTS[effort], _as_director_llm(llm), renderer or RuntimeRenderer(), job_dir, lib,
             progress, cancel, effort)
    r.save("brief.json", brief.to_dict())
    r.save("catalog.md", cat.full())
    r.emit("setup", f"Director ready ({effort}: {r.budget.rounds} critique round(s), "
                    f"{len(cat.scenes())} kit/library scenes, {len(brief.assets)} media)", 0.01)
    return r


# ------------------------------------------------------------------------------------ the loop

def _produce(r: _Run, start: Version | None = None, first: Version | None = None) -> Version | None:
    """Treatment -> film -> realise -> critique/revise rounds. Returns the best version (or None).

    ``start`` = a finished version to revise with the user's notes; ``first`` = an already scripted v1
    (dev resume: skips the treatment and film calls).
    """
    try:
        if first is not None:
            v = first
            if not _realise(r, v, code=list(v.customs)):
                return None
        elif start is None:
            r.emit("treatment", "Writing treatment", 0.03)
            r.treatment = _treatment(r)
            if not r.treatment:
                return None
            r.emit("film", "Writing film script", 0.10)
            v = _film(r)
            if v is None:
                return None
            r.emit("scenes", f"Film script: {len(v.film['shots'])} shots, {len(v.customs)} custom scene(s)", 0.18)
            if not _realise(r, v, code=list(v.customs)):
                return None
        else:
            v = _apply_notes(r, start)
            if v is None:
                return None
        rounds = r.budget.rounds
        for rnd in range(1, rounds + 1):
            r.versions.append(v)
            _save_version(r, v)
            score = _critique(r, v, rnd)
            span = 0.45 + 0.5 * rnd / rounds
            if score is None:
                r.warn("critic", f"Critic round {rnd}: no usable critique")
                break
            n_issues = len((v.critique or {}).get("per_shot_issues") or [])
            if score.passed:
                r.emit("critic", f"Critic round {rnd}: {score.mean:.1f} (min {score.min:g}) - passes the bar", span)
                _save_version(r, v)
                break
            if rnd == rounds:
                r.emit("critic", f"Critic round {rnd}: {score.mean:.1f} (min {score.min:g}) - round budget spent", span)
                _save_version(r, v)
                break
            r.emit("critic", f"Critic round {rnd}: {score.mean:.1f} -> fixing {n_issues} issue(s)", span - 0.2 / rounds)
            _save_version(r, v)
            nxt = _revise_version(r, v)
            if nxt is None:
                r.warn("revise", "Revision failed; keeping the best version so far")
                break
            v = nxt
    except BudgetExceeded as exc:
        r.warn("budget", f"{exc}; keeping the best version so far")
    scored = [x for x in r.versions if x.preview is not None and x.preview.ok]
    if not scored:
        return None
    return max(scored, key=Version.key)


# ------------------------------------------------------------------------------------ steps

def _treatment(r: _Run) -> dict[str, Any]:
    instr, text = prompts.treatment_prompt(r.brief, r.catalog)
    images = _product_images(r)
    extra, last_usable = "", None
    for attempt in range(1 + r.budget.film_repairs):
        reply = r.ask("treatment", instr, text + extra, schema=prompts.TREATMENT_SCHEMA,
                      schema_name="showreel.treatment", images=images, temperature=0.8, max_tokens=6000)
        obj = _json_of(reply)
        if obj is None:
            errs = [reply.error or "the reply was not valid JSON"]
            extra = prompts.repair_text(reply.text[:6000], errs)
            r.warn("treatment", f"Treatment attempt {attempt + 1}: {errs[0][:160]}")
            continue
        chk = check_treatment(obj, r.brief, r.catalog)
        for w in chk.warnings:
            r.emit("treatment", w, level="debug")
        if chk.ok:
            r.save("treatment.json", chk.value)
            r.emit("treatment", f"Treatment: {str(chk.value.get('logline', ''))[:140]}",
                   acts=[a.get("name") for a in chk.value.get("acts") or []])
            return chk.value
        if isinstance(chk.value, dict) and chk.value.get("acts"):
            last_usable = chk.value
        r.warn("treatment", f"Treatment attempt {attempt + 1} rejected: {'; '.join(chk.errors)[:300]}")
        extra = prompts.repair_text(obj, chk.errors)
    if last_usable:
        r.warn("treatment", "Using the last treatment despite open issues (the film step re-checks)")
        r.save("treatment.json", last_usable)
        return last_usable
    r.emit("treatment", "The Director could not write a usable treatment", level="error")
    return {}


def _film(r: _Run) -> Version | None:
    instr, text = prompts.film_prompt(r.brief, r.catalog, r.treatment, max_custom=r.budget.max_custom)
    res = _structured_film(r, "film", instr, text, prompts.FILM_SCHEMA, "showreel.film")
    if res is None:
        return None
    film, plan, _obj = res
    return Version(1, film, plan)


def _structured_film(r: _Run, purpose: str, instr: str, text: str, schema: dict[str, Any],
                     schema_name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Ask for {film, plan, ...}, validate (director checks + runtime schema) and repair."""
    extra = ""
    for attempt in range(1 + r.budget.film_repairs):
        reply = r.ask(purpose, instr, text + extra, schema=schema, schema_name=schema_name, temperature=0.6,
                      max_tokens=16000, timeout=420.0)
        obj = _json_of(reply)
        if obj is None:
            errs = [reply.error or "the reply was not valid JSON (or was cut off: keep specs tighter)"]
            r.warn(purpose, f"Film attempt {attempt + 1}: {errs[0][:160]}")
            extra = prompts.repair_text(reply.text[:8000], errs)
            continue
        chk = check_film(obj, r.brief, r.catalog, max_custom=r.budget.max_custom)
        errors = list(chk.errors)
        if chk.value is not None and not errors:
            errors += [f"runtime schema: {e}" for e in r.renderer.validate_film(chk.value[0])]
        for w in chk.warnings:
            r.emit(purpose, w, level="debug")
        if not errors and chk.value is not None:
            film, plan = chk.value
            return film, plan, obj
        r.warn(purpose, f"Film attempt {attempt + 1} rejected: {'; '.join(errors)[:400]}")
        extra = prompts.repair_text(obj, errors)
    r.emit(purpose, "The film script did not pass validation", level="error")
    return None


def _code_scene(r: _Run, v: Version, name: str, *, issues: list[dict[str, Any]] | None = None, notes: str = "",
                errors: list[str] | None = None) -> bool:
    """Write (or revise / repair) one custom scene until it lints clean.

    Returns False when its tries ran out. A revision that never lints clean keeps the previous working code
    (``v.stable``) instead of failing the scene.
    """
    spec = v.customs[name]
    sid = f"custom:{name}"
    shots = [s for s in v.film["shots"] if s["scene"] == sid]
    plan_shots = {p["id"]: p for p in v.plan.get("shots") or []}
    prev = v.scenes.get(name, "")
    errs = list(errors or [])
    while v.tries.get(name, 0) < r.budget.scene_tries:
        v.tries[name] = v.tries.get(name, 0) + 1
        attempt = v.tries[name]
        if errs and prev:
            r.emit("scenes", f"Repairing scene {name} (try {attempt}): {errs[0][:120]}")
            instr, text = prompts.scene_repair_prompt(r.brief, r.catalog, spec, prev, errs)
        elif prev and (issues or notes):
            r.emit("scenes", f"Revising scene {name}")
            instr, text = prompts.scene_revise_prompt(r.brief, r.catalog, spec, prev, issues or [], notes)
        else:
            r.emit("scenes", f"Coding scene {name}")
            instr, text = prompts.scene_prompt(r.brief, r.catalog, spec, shots, plan_shots)
        reply = r.ask(f"scene:{name}", instr, text, temperature=0.5, max_tokens=16000, timeout=420.0)
        code = extract_js(reply.text)
        if not code:
            errs = [reply.error or "no ```js code block in the reply"]
            r.warn("scenes", f"Scene {name} try {attempt}: {errs[0][:160]}")
            continue
        code = normalize_scene_code(code, sid)
        found, warns = lint_scene(code, sid)
        found += r.renderer.lint_scene(code, sid)
        for w in warns:
            r.emit("scenes", f"{name}: {w}", level="debug")
        prev = code
        r.save(f"v{v.n}/tries/{name}.try{attempt}.js", code)
        if not found:
            v.scenes[name] = code
            return True
        errs = found
        r.warn("scenes", f"Scene {name} failed lint: {'; '.join(found)[:200]}")
    if name in v.stable:
        r.warn("scenes", f"Scene {name}: keeping the previous working code")
        v.scenes[name] = v.stable[name]
        return True
    return False


def _fallback(r: _Run, v: Version, name: str, why: str) -> bool:
    """Replace custom scene ``name`` by the nearest kit scene in every shot; False when no kit scene exists."""
    spec = v.customs.get(name, {"name": name})
    target = nearest_kit_scene(spec, r.catalog)
    if target is None:
        r.emit("scenes", f"Scene {name} failed ({why}) and no kit scene can stand in", level="error")
        return False
    names = r.catalog.asset_names()
    for s in v.film["shots"]:
        if s["scene"] == f"custom:{name}":
            s["params"] = fallback_params(spec, s.get("params") or {}, target, names)
            s["scene"] = target.id
    for o in v.film.get("overlays") or []:
        if o["scene"] == f"custom:{name}":
            o["scene"] = target.id
    v.scenes.pop(name, None)
    v.fallbacks[name] = target.id
    v.plan["custom_scenes"] = [c for c in v.plan.get("custom_scenes") or [] if c.get("name") != name]
    r.warn("scenes", f"Scene {name} -> fallback {target.id} ({why[:160]})")
    return True


def _realise(r: _Run, v: Version, *, code: list[str], issues: dict[str, list[dict[str, Any]]] | None = None,
             notes: dict[str, str] | None = None) -> bool:
    """Code the listed custom scenes, then build + dry-run with repairs/fallbacks; captures keyframes."""
    issues, notes = issues or {}, notes or {}
    total = max(1, len(code))
    for i, name in enumerate(code):
        if name not in v.customs:
            continue
        r.frac = max(r.frac, 0.18 + 0.22 * i / total)
        if not _code_scene(r, v, name, issues=issues.get(name), notes=notes.get(name, "")) and                 not _fallback(r, v, name, "code did not pass lint"):
            return False
    return _dry_run(r, v)


def _dry_run(r: _Run, v: Version) -> bool:
    """Build the page and render probe frames; repair scenes that throw, fall back when tries run out."""
    v.frames = plan_keyframes(v.film, r.budget.keyframes_per_shot)
    for loop in range(r.budget.scene_tries + 2):
        r.check_cancel()
        errs = r.renderer.build(v.film, r.page_dir, scenes=v.scenes, assets=r.brief.assets,
                                library_dir=r.library_dir)
        r.built_n = v.n
        if errs:
            r.emit("dryrun", f"Page build failed: {'; '.join(errs)[:300]}", level="error")
            return False
        probe, det = _probe_times(v.film)
        r.emit("dryrun", f"Dry run v{v.n}{f' (pass {loop + 1})' if loop else ''}: {len(probe)} probe frames, "
                         f"{len(v.frames)} keyframes", 0.42 if v.n == 1 else None)
        pv = r.renderer.preview(r.page_dir, probe_times=probe, capture_times=[f.t for f in v.frames],
                                size=r.brief.preview_size, film_size=r.brief.size, shots=v.film["shots"],
                                determinism_times=det)
        v.preview = pv
        r.save(f"v{v.n}/dryrun-{loop + 1}.json", {"ok": pv.ok, "load_error": pv.load_error, "seconds": pv.seconds,
                                                  "errors": [str(e) for e in pv.errors[:60]], "qa": pv.qa[:80]})
        by_scene = _errors_by_scene(v, pv)
        kit_errors = by_scene.pop("", [])
        if pv.ok and not by_scene:
            if kit_errors:
                r.warn("dryrun", f"{len(kit_errors)} runtime error(s) in kit shots: {kit_errors[0][:160]}")
            v.images = pv.images
            return True
        if not by_scene:
            r.emit("dryrun", f"The page does not load and no custom scene is to blame: {pv.load_error[:300]}",
                   level="error")
            return False
        for name, msgs in by_scene.items():
            if name in v.fallbacks or name not in v.customs:
                continue
            ok = v.tries.get(name, 0) < r.budget.scene_tries and _code_scene(r, v, name, errors=msgs[:12])
            if ok:
                continue
            if name in v.stable and v.scenes.get(name) != v.stable[name]:
                r.warn("dryrun", f"Scene {name}: the revision keeps failing; restoring the previous working code")
                v.scenes[name] = v.stable[name]
                v.tries[name] = r.budget.scene_tries
                continue
            if not _fallback(r, v, name, msgs[0] if msgs else "runtime errors"):
                return False
    r.emit("dryrun", "Dry run still failing after repairs", level="error")
    return False


def _errors_by_scene(v: Version, pv: Preview) -> dict[str, list[str]]:
    """Group dry-run errors by custom scene name ('' = kit shots / unattributed but harmless)."""
    scene_of = {s["id"]: s["scene"] for s in v.film["shots"]}
    out: dict[str, list[str]] = {}
    unattributed: list[ShotError] = []
    for e in pv.errors:
        scene = scene_of.get(e.shot, "")
        if scene.startswith("custom:"):
            out.setdefault(scene.split(":", 1)[1], []).append(str(e))
        elif not e.shot:
            unattributed.append(e)
        else:
            out.setdefault("", []).append(str(e))
    if not pv.ok:
        msg = f"the page failed to load: {pv.load_error}"
        named = [n for n in v.scenes if n in pv.load_error]
        targets = named or (list(v.scenes) if not out else [])
        for n in targets:
            out.setdefault(n, []).append(msg)
        for e in unattributed:
            for n in targets:
                out[n].append(str(e))
    return out


def _probe_times(film: dict[str, Any]) -> tuple[list[float], list[float]]:
    """Dry-run times: start/middle/end of every shot, every 0.5 s inside custom shots; determinism probes."""
    times: set[float] = set()
    det: list[float] = []
    for s in film["shots"]:
        t0, t1 = float(s["t0"]), float(s["t1"])
        times.update({round(t0 + 0.04, 3), round((t0 + t1) / 2, 3), round(t1 - 0.04, 3)})
        if str(s["scene"]).startswith("custom:"):
            t = t0 + 0.25
            while t < t1:
                times.add(round(t, 3))
                t += 0.5
            det += [round(t0 + 0.37 * (t1 - t0), 3), round(t0 + 0.81 * (t1 - t0), 3)]
    return sorted(times), det


def _critique(r: _Run, v: Version, rnd: int) -> RoundScore | None:
    """Contact sheet(s) -> vision critic -> rubric; stores the score on the version."""
    if not v.images:
        return None
    vdir = r.ddir / f"v{v.n}"
    kdir = vdir / "keyframes"
    kdir.mkdir(parents=True, exist_ok=True)
    for f, img in zip(v.frames, v.images, strict=False):
        p = kdir / f"{f.cell:02d}-{f.shot}.png"
        p.write_bytes(img)
        f.path = str(p)
    sheets = contact_sheets(v.images, v.frames, vdir, prefix="contact")
    r.emit("critic", f"Critic round {rnd}: reviewing {len(v.frames)} keyframes on {len(sheets)} sheet(s)",
           sheets=[str(s) for s in sheets])
    product = {a.name for a in r.brief.assets if a.product}
    share, missing = product_share(v.film, product) if product else (1.0, [])
    checks = [f"product media referenced in {share:.0%} of the runtime" + (f" (not in {missing})" if missing else "")]
    first = first_product_time(v.film, product) if product else None
    if first is not None:
        checks.append(f"product first appears at {first:g} s")
    if v.fallbacks:
        checks.append(f"custom scenes replaced by kit scenes after failing: {v.fallbacks}")
    qa = (v.preview.qa if v.preview else [])
    if qa:
        kinds: dict[str, int] = {}
        for q in qa:
            kinds[str(q.get("kind"))] = kinds.get(str(q.get("kind")), 0) + 1
        checks.append(f"layout QA issues: {kinds}")
    treat = dict(r.treatment)
    if r.brief.notes.strip():
        treat["requirements"] = list(treat.get("requirements") or []) + [
            {"text": f"User revision notes: {r.brief.notes.strip()}", "how": "must be visibly addressed"}]
    instr, text = prompts.critic_prompt(r.brief, treat, v.film, v.plan, [f.to_dict() for f in v.frames], checks)
    images = [Image(s.read_bytes(), "image/jpeg", str(s), f"contact sheet {i + 1}") for i, s in enumerate(sheets)]
    crit = None
    for attempt in range(2):
        reply = r.ask(f"critic:r{rnd}", instr, text, schema=prompts.CRITIC_SCHEMA, schema_name="showreel.critique",
                      images=images, temperature=0.2, max_tokens=5000)
        crit = _normalise_critique(_json_of(reply), v)
        if crit is not None:
            break
        r.warn("critic", f"Critique attempt {attempt + 1} unusable: {(reply.error or reply.text)[:160]}")
    if crit is None:
        return None
    scores = crit["scores"]
    vals = [scores[k] for k in RUBRIC_KEYS]
    frames = [f for f in crit.get("frames") or [] if isinstance(f, dict)]
    vis = [bool(f.get("product_visible")) for f in frames]
    vshare = (sum(vis) / len(vis)) if vis else None
    sev3 = any(i["severity"] >= 3 for i in crit["per_shot_issues"])
    passed = min(vals) >= SCORE_BAR and not sev3 and (vshare is None or not product or vshare >= PRODUCT_SHARE_BAR)
    v.critique = crit
    v.score = RoundScore(rnd, v.n, scores, round(sum(vals) / len(vals), 2), min(vals), vshare, passed,
                         len(crit["per_shot_issues"]), str(crit.get("verdict", "")))
    r.save(f"v{v.n}/critique.json", crit)
    r.emit("critic", f"Scores v{v.n}: " + ", ".join(f"{k} {scores[k]:g}" for k in RUBRIC_KEYS)
           + (f"; product visible in {vshare:.0%} of keyframes" if vshare is not None else ""),
           scores=scores, product_share=vshare)
    return v.score


def _normalise_critique(obj: Any, v: Version) -> dict[str, Any] | None:
    if not isinstance(obj, dict) or not isinstance(obj.get("scores"), dict):
        return None
    scores = {}
    for k in RUBRIC_KEYS:
        try:
            scores[k] = max(1.0, min(10.0, float(obj["scores"][k])))
        except (KeyError, TypeError, ValueError):
            return None
    ids = {s["id"] for s in v.film["shots"]}
    issues = []
    for it in obj.get("per_shot_issues") or []:
        if not isinstance(it, dict) or not str(it.get("issue") or "").strip():
            continue
        shot = str(it.get("shot") or "")
        try:
            sev = round(float(it.get("severity") or 2))
        except (TypeError, ValueError):
            sev = 2
        issues.append({"shot": shot if shot in ids else "film", "target": "scene" if it.get("target") == "scene"
                       else "film", "severity": max(1, min(3, sev)), "issue": str(it["issue"]),
                       "fix": str(it.get("fix") or "")})
    out = dict(obj, scores=scores, per_shot_issues=issues[:10])
    return out


def _revise_version(r: _Run, v: Version) -> Version | None:
    """Apply the critique: film-level revision (if needed) + scene revisions, then realise."""
    crit = v.critique or {}
    issues = crit.get("per_shot_issues") or []
    unmet = [q for q in crit.get("requirements") or [] if isinstance(q, dict) and q.get("met") is False]
    scene_of = {s["id"]: s["scene"] for s in v.film["shots"]}
    scene_issues: dict[str, list[dict[str, Any]]] = {}
    film_issues = []
    for it in issues:
        scene = scene_of.get(it["shot"], "")
        if it["target"] == "scene" and scene.startswith("custom:") and scene.split(":", 1)[1] in v.scenes:
            scene_issues.setdefault(scene.split(":", 1)[1], []).append(it)
        else:
            film_issues.append(it)
    extras = [{"shot": "film", "target": "film", "severity": 3, "issue": f"requirement not met: {q.get('text')}",
               "fix": str(q.get("note") or "make it visibly happen")} for q in unmet]
    if v.score and v.score.product_share is not None and v.score.product_share < PRODUCT_SHARE_BAR:
        extras.append({"shot": "film", "target": "film", "severity": 3,
                       "issue": f"the product is visible in only {v.score.product_share:.0%} of keyframes",
                       "fix": "put the product on screen (large, lit) in more shots or shorten shots without it"})
    film_issues += extras
    nv = Version(v.n + 1, copy.deepcopy(v.film), copy.deepcopy(v.plan), dict(v.scenes), dict(v.fallbacks),
                 stable=dict(v.scenes))
    notes: dict[str, str] = {}
    recode: list[str] = list(scene_issues)
    if film_issues:
        r.emit("revise", f"Revising the film script ({len(film_issues)} film-level issue(s))")
        instr, text = prompts.revise_film_prompt(r.brief, r.catalog, r.treatment, v.film, v.plan, issues + extras, "",
                                                 max_custom=r.budget.max_custom)
        res = _structured_film(r, "revise-film", instr, text, prompts.REVISE_FILM_SCHEMA, "showreel.revision")
        if res is not None:
            film, plan, obj = res
            nv.film, nv.plan = film, plan
            nv.changes = [str(c) for c in obj.get("changes") or []]
            notes = {str(n.get("name")): str(n.get("notes")) for n in obj.get("scene_notes") or []
                     if isinstance(n, dict) and n.get("name")}
            old_specs = v.customs
            for name, spec in nv.customs.items():
                if name not in old_specs or name not in nv.scenes:
                    nv.scenes.pop(name, None)
                    nv.tries.pop(name, None)
                    if name not in recode:
                        recode.append(name)
                elif (spec.get("spec") != old_specs[name].get("spec") or name in notes) and name not in recode:
                    recode.append(name)
            for name in list(nv.scenes):
                if name not in nv.customs:
                    nv.scenes.pop(name)
            if nv.changes:
                r.emit("revise", "Changes: " + "; ".join(nv.changes)[:300])
        else:
            r.warn("revise", "Film revision rejected; applying scene fixes only")
    recode = [n for n in recode if n in nv.customs]
    if not recode and not film_issues:
        r.warn("revise", "Nothing actionable in the critique")
        return None
    nv.tries = {}
    if not _realise(r, nv, code=recode, issues=scene_issues, notes=notes):
        return None
    return nv


def _apply_notes(r: _Run, base: Version) -> Version | None:
    """User revision notes -> revised film (+ scenes) -> realise."""
    base.n = 0
    r.emit("revise", "Applying your notes to the film script", 0.1)
    instr, text = prompts.revise_film_prompt(r.brief, r.catalog, r.treatment, base.film, base.plan, [],
                                             r.brief.notes, max_custom=r.budget.max_custom)
    res = _structured_film(r, "revise-notes", instr, text, prompts.REVISE_FILM_SCHEMA, "showreel.revision")
    if res is None:
        return None
    film, plan, obj = res
    v = Version(1, film, plan, dict(base.scenes), dict(base.fallbacks), stable=dict(base.scenes))
    v.changes = [str(c) for c in obj.get("changes") or []]
    notes = {str(n.get("name")): str(n.get("notes")) for n in obj.get("scene_notes") or []
             if isinstance(n, dict) and n.get("name")}
    old = base.customs
    recode = []
    for name, spec in v.customs.items():
        if name not in v.scenes or name not in old:
            v.scenes.pop(name, None)
            recode.append(name)
        elif name in notes or spec.get("spec") != old[name].get("spec"):
            recode.append(name)
    for name in list(v.scenes):
        if name not in v.customs:
            v.scenes.pop(name)
    if not _realise(r, v, code=recode, issues={n: [{"shot": "film", "target": "scene", "severity": 2,
                                                     "issue": "user notes", "fix": r.brief.notes}] for n in recode},
                    notes=notes):
        return None
    return v


# ------------------------------------------------------------------------------------ finish

def _save_version(r: _Run, v: Version) -> None:
    vdir = f"v{v.n}"
    r.save(f"{vdir}/film.json", v.film)
    r.save(f"{vdir}/plan.json", v.plan)
    r.save(f"{vdir}/fallbacks.json", v.fallbacks)
    for name, code in v.scenes.items():
        r.save(f"{vdir}/scenes/{name}.js", code)
    if v.changes:
        r.save(f"{vdir}/changes.json", v.changes)


def _finish(r: _Run, best: Version | None, save_library: bool, t0: float) -> DirectorResult:
    usage = r.ledger.totals()
    if best is None:
        r.emit("done", "The Director could not finish; falling back to Quick mode", 1.0, level="error")
        res = DirectorResult(False, "failed", str(r.job_dir), treatment=r.treatment or None,
                             scores=[v.score for v in r.versions if v.score], fallback="quick",
                             quick_style=guess_style(r.brief.direction), error="director_failed", usage=usage,
                             seconds=round(time.monotonic() - t0, 1), log=r.log)
        r.save("result.json", res.to_dict())
        return res
    if r.built_n != best.n:
        r.emit("final", f"Rebuilding the page from the best version (v{best.n})")
        errs = r.renderer.build(best.film, r.page_dir, scenes=best.scenes, assets=r.brief.assets,
                                library_dir=r.library_dir)
        if errs:
            r.warn("final", f"Rebuild failed: {'; '.join(errs)[:200]}")
    film_path = r.job_dir / "film.json"
    film_path.write_text(json.dumps(best.film, indent=1, ensure_ascii=False), encoding="utf-8")
    saved = _save_library(r, best) if save_library and r.library_dir else []
    _save_state(r, best)
    scores = [v.score for v in r.versions if v.score]
    passed = bool(best.score and best.score.passed)
    scenes = {n: "ok" for n in best.scenes}
    scenes.update({n: f"fallback:{k}" for n, k in best.fallbacks.items()})
    msg = (f"Final: v{best.n}" + (f", score {best.score.mean:.1f} (min {best.score.min:g})" if best.score else
                                  ", not critiqued") + (" - passes the bar" if passed else ""))
    r.emit("done", msg, 1.0)
    files = {f"custom:{n}": str(r.ddir / f"v{best.n}" / "scenes" / f"{n}.js") for n in best.scenes}
    res = DirectorResult(True, "done", str(r.job_dir), film=best.film, film_path=str(film_path),
                         page_dir=str(r.page_dir), scene_files=files, treatment=r.treatment, version=best.n, scores=scores, passed_bar=passed, scenes=scenes,
                         library_saved=saved, usage=r.ledger.totals(), seconds=round(time.monotonic() - t0, 1),
                         log=r.log)
    r.save("result.json", {k: v for k, v in res.to_dict().items() if k != "log"})
    return res


def _save_state(r: _Run, best: Version) -> None:
    r.save("state.json", {"brief": r.brief.to_dict(), "treatment": r.treatment, "best": best.n,
                          "title": best.film.get("title", ""),
                          "versions": [{"n": v.n, "score": v.score.to_dict() if v.score else None,
                                        "fallbacks": v.fallbacks} for v in r.versions]})


def _save_library(r: _Run, best: Version) -> list[str]:
    """Save every custom scene of the final film that rendered cleanly (not severity-3 criticised)."""
    assert r.library_dir is not None
    crit_issues = (best.critique or {}).get("per_shot_issues") or []
    scene_of = {s["id"]: s["scene"] for s in best.film["shots"]}
    bad = {scene_of.get(i["shot"], "") for i in crit_issues if i.get("severity", 0) >= 3}
    saved = []
    for name, code in best.scenes.items():
        sid = f"custom:{name}"
        if sid in bad:
            continue
        spec = best.customs.get(name, {})
        thumb = None
        for f, img in zip(best.frames, best.images, strict=False):
            if scene_of.get(f.shot) == sid and not f.transition:
                thumb = img
                if f.local >= 0.4 * f.dur:
                    break
        meta = {"describe": spec.get("describe", ""), "layer": spec.get("layer", ""), "params": spec.get("params", {}),
                "kits": spec.get("kits", []), "tags": _tags(spec), "created_job": r.job_dir.name,
                "direction": r.brief.direction[:300], "spec": spec.get("spec", ""),
                "scores": best.score.scores if best.score else None,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            lib_id = save_scene(r.library_dir, name, code, meta, thumb)
        except OSError as exc:
            r.warn("library", f"Could not save {name}: {exc}")
            continue
        if lib_id:
            saved.append(lib_id)
    if saved:
        r.emit("library", f"Saved {len(saved)} scene(s) to your library: {', '.join(saved)}")
    return saved


def _tags(spec: dict[str, Any]) -> list[str]:
    words = re.findall(r"[a-z]{4,}", f"{spec.get('name', '')} {spec.get('describe', '')}".lower())
    stop = {"with", "that", "this", "from", "into", "then", "where", "scene", "while", "their", "over"}
    out: list[str] = []
    for w in words:
        if w not in stop and w not in out:
            out.append(w)
    return out[:8]


def _product_images(r: _Run, limit: int = 2) -> list[Image]:
    out = []
    for a in r.brief.assets:
        if not a.product or not a.thumbnail or not Path(a.thumbnail).is_file():
            continue
        data = Path(a.thumbnail).read_bytes()
        mime = "image/jpeg" if a.thumbnail.lower().endswith((".jpg", ".jpeg")) else "image/png"
        out.append(Image(data, mime, a.thumbnail, f"product media `{a.name}` ({a.type})"))
        if len(out) >= limit:
            break
    return out


def guess_style(direction: str) -> str:
    """A Quick-mode style named in the direction (for the fallback), or ''."""
    words = re.findall(r"[a-z]+", direction.lower())
    return next((w for w in words if w in QUICK_STYLES), "")
