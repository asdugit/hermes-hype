"""The Director Engine: free-text direction -> treatment (a narrative recipe adapted) -> film.json (kit-first)
-> custom scene code only for real gaps -> lint -> build + dry run (repair / kit fallback) -> keyframes ->
MEASURED product prominence (repaired before any critique) -> contact sheet -> vision critique with per-shot
scores -> PATCH revisions of only what the review names -> per-shot best-of merge across versions -> narration.

Every artefact is persisted under ``<job>/director/``; the renderable page is ``<job>/page/`` (the pipeline
renders the final video from it, mixing ``film["music"]``, ``film["cues"]`` and ``film["narration"]``).

Public API (never raises; returns :class:`DirectorResult`)::

    run(brief, *, llm, renderer=None, effort="standard", progress=None, cancel=None, job_dir=..., library_dir=...)
    revise(parent_job_dir, notes, *, llm, renderer=None, effort="standard", job_dir=None, ...)

``run`` also accepts the pipeline's keyword set (``direction``, ``product``, ``digest``, ``seconds``, ``aspect``,
``fps``, ``seed``, ``notes``, ``bundle``, ``options``, ``store``, ``job_id``, ``dispatch``, raw ``ctx.llm``...).
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Product
from ..story.schema import parse_json_text
from . import compose, measured, prompts, repair, tiers
from . import prominence as pm
from .backend import Preview, Renderer, RuntimeRenderer, ShotError
from .catalog import Catalog, build_catalog
from .checks import (
    MAX_SCENE_BYTES,
    check_film,
    check_treatment,
    extract_js,
    fallback_params,
    first_product_time,
    lint_scene,
    nearest_kit_scene,
    normalize_scene_code,
    product_share,
    references,
)
from .library import save_scene
from .llm import (
    BudgetExceeded,
    CallLedger,
    Cancelled,
    DirectorLlm,
    Image,
    LlmReply,
    hermes_llm,
    is_cancelled,
)
from .patches import apply_blocks, apply_film_patch, parse_blocks, shot_diff
from .sheet import Frame, contact_sheets, plan_keyframes
from .types import (
    EFFORTS,
    PRODUCT_HERO_BAR,
    PRODUCT_HERO_SIZE,
    PRODUCT_SHARE_BAR,
    RUBRIC_KEYS,
    SCORE_BAR,
    Brief,
    Budget,
    Capabilities,
    DirectorResult,
    MediaAsset,
    RoundScore,
    brief_from_dict,
)

log = logging.getLogger(__name__)

QUICK_STYLES = ("launch", "pixel", "terminal", "blueprint", "cinematic", "comic", "ink", "newspaper")
SCENE_PARALLEL = 3              # custom scenes coded concurrently (independent model calls)
# Output budgets measured on real runs: scene modules 16-39 KB (5-12k tokens), film/revision JSON up to 40 KB.
SCENE_MAX_TOKENS = 32000
FILM_MAX_TOKENS = 32000
PATCH_MAX_TOKENS = 12000
MERGE_MARGIN = 0.5              # a donor shot must beat the base shot by this much to be merged in
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
    mask_images: list[bytes] = field(default_factory=list)
    preview: Preview | None = None
    score: RoundScore | None = None
    critique: dict[str, Any] | None = None
    changes: list[str] = field(default_factory=list)
    sheets: list[Path] = field(default_factory=list)            # contact sheets the critic saw
    review: dict[str, Any] = field(default_factory=dict)        # what the previous version's review showed
    measures: list[pm.Measure] = field(default_factory=list)
    prom: pm.Prominence | None = None
    origin: str = "script"                                      # script | revision | notes | merge
    prom_repaired: int = 0

    @property
    def customs(self) -> dict[str, dict[str, Any]]:
        return {c["name"]: c for c in self.plan.get("custom_scenes") or []}

    def shot_scores(self) -> dict[str, float]:
        """Per-shot critic scores (shot id -> 1..10)."""
        out: dict[str, float] = {}
        for s in (self.critique or {}).get("shots") or []:
            if isinstance(s, dict) and s.get("id") is not None:
                try:
                    out[str(s["id"])] = max(1.0, min(10.0, float(s.get("score"))))
                except (TypeError, ValueError):
                    continue
        return out

    def key(self) -> tuple[float, ...]:
        """Ranking: passed, mean, min, then the user's requirements met and how well the product sells."""
        s = self.score
        reqs = [q for q in (self.critique or {}).get("requirements") or [] if isinstance(q, dict)]
        met = sum(1 for q in reqs if q.get("met") is True)
        return (1.0 if s and s.passed else 0.0, s.mean if s else 0.0, s.min if s else 0.0, float(met),
                s.scores.get("product_clarity", 0.0) if s else 0.0, (s.product_hero or 0.0) if s else 0.0,
                -len(self.fallbacks), float(self.n))


class _Run:
    """Per-run context: brief, catalog, budget, ledger, dirs, progress, log, keyframe cache."""

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
        self._lock = threading.Lock()                        # log/progress from parallel scene coding
        self.product = {a.name for a in brief.assets if a.product}
        self.frame_cache: dict[str, tuple[bytes, bytes | None]] = {}   # frame fingerprint -> (image, mask image)
        self.shot_ok: set[str] = set()                       # shot fingerprints that dry-ran clean
        self.dispatch: Any = None                            # Hermes dispatch_tool (narration TTS)
        self.voice_speed: Any = None                         # the user's narration_speed override
        self.parent_prom: pm.Prominence | None = None        # measurements of the film being revised
        self.tier: tiers.Tier = tiers.Tier("strong")         # what the model is trusted with (see tiers.py)
        self.path = ""                                       # free | compose | floor: how v1 was made

    # -------------------------------------------------------------- events
    def emit(self, step: str, msg: str, frac: float | None = None, level: str = "info", **extra: Any) -> None:
        if frac is not None:
            self.frac = max(self.frac, min(1.0, frac))
        entry = {"t": round(time.monotonic() - self.t0, 2), "step": step, "msg": msg, "level": level, **extra}
        with self._lock:
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
        if isinstance(obj, bytes):
            p.write_bytes(obj)
        else:
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
                          save_library=save_library, budget=budget, dispatch=kwargs.get("dispatch"),
                          voice_speed=getattr(opts, "voice_speed", None))
        if renderer is None and kwargs.get("blender"):
            renderer = RuntimeRenderer(gpu=brief.capabilities.gpu, blender=kwargs.get("blender"), job_dir=jd)
        tier = kwargs.get("tier") if isinstance(kwargs.get("tier"), tiers.Tier) else tiers.detect(
            str(kwargs.get("model") or tiers.model_of(llm)),
            configured=str(kwargs.get("director_tier") or getattr(opts, "director_tier", "") or ""),
            vision=kwargs.get("director_vision", getattr(opts, "director_vision", None)))
        r = _setup(brief, llm, renderer, effort, progress, cancel, jd, library_dir, catalog, budget, tier=tier)
        r.dispatch = kwargs.get("dispatch")
        r.voice_speed = getattr(opts, "voice_speed", None)
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
           save_library: bool = True, budget: Budget | None = None, dispatch: Any = None,
           voice_speed: Any = None) -> DirectorResult:
    """``/showreel revise <notes>``: another pass on a finished Director film with the user's notes."""
    t0 = time.monotonic()
    parent = Path(parent_job_dir)
    jd = Path(job_dir) if job_dir else parent
    try:
        state = json.loads((parent / "director" / "state.json").read_text(encoding="utf-8"))
        brief = brief_from_dict(state["brief"])
        brief.notes = notes
        r = _setup(brief, llm, renderer, effort, progress, cancel, jd, library_dir, catalog, budget)
        r.dispatch, r.voice_speed = dispatch, voice_speed
        r.treatment = state.get("treatment") or {}
        best_n = int(state.get("best") or 0)
        vdir = parent / "director" / f"v{best_n}"
        base = Version(0, json.loads((vdir / "film.json").read_text(encoding="utf-8")),
                       json.loads((vdir / "plan.json").read_text(encoding="utf-8")))
        base.scenes = {p.stem: p.read_text(encoding="utf-8") for p in sorted((vdir / "scenes").glob("*.js"))}
        fb = vdir / "fallbacks.json"
        base.fallbacks = json.loads(fb.read_text(encoding="utf-8")) if fb.is_file() else {}
        _load_parent_frames(r, vdir)
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
    blender = bool(kw.get("blender"))
    model = str(getattr(product, "model", "") or "") if product is not None else ""
    if blender and model and Path(model).is_file() and not any(a.type == "model" for a in assets):
        assets.append(MediaAsset(name="model3d", type="model", path=str(Path(model).resolve()),
                                 description="the product's 3D model (Blender scenes only)"))
    return Brief(
        direction=str(kw.get("direction") or getattr(opts, "direction", "") or ""),
        product=product if isinstance(product, Product) else None,
        digest=str(kw.get("digest") or getattr(bundle, "digest", "") or ""),
        assets=assets,
        seconds=float(kw.get("seconds") or getattr(opts, "seconds", 45) or 45),
        aspect=aspect, fps=int(kw.get("fps") or 30), seed=int(kw.get("seed") or 7),
        capabilities=Capabilities(gpu=bool(kw.get("gpu")), blender=blender),
        notes=str(kw.get("notes") or getattr(opts, "notes", "") or ""),
    )


def _parent_dir(kw: dict[str, Any]) -> Path | None:
    if kw.get("parent_job_dir"):
        return Path(kw["parent_job_dir"])
    store, job_id = kw.get("store"), kw.get("job_id")
    try:
        parent = (store.load(job_id) or {}).get("parent") if store is not None and job_id else ""
        return Path(store.job_dir(parent)) if parent else None
    except Exception:
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
           budget: Budget | None = None, tier: tiers.Tier | None = None) -> _Run:
    effort = effort if effort in EFFORTS else "standard"
    lib = Path(library_dir) if library_dir else None
    if lib is None:
        try:
            from .library import default_library_dir
            lib = default_library_dir()
        except Exception:
            lib = None
    cat = catalog or build_catalog(library_dir=lib, assets=brief.assets, capabilities=brief.capabilities)
    if not cat.assets:
        cat.assets = list(brief.assets)
    tier = tier or tiers.Tier("strong")
    if not tier.vision:
        brief.capabilities.vision = False
    bud = budget or EFFORTS[effort]
    if bud.path == "compose" and tier.path != "compose":
        tier = dataclasses.replace(tier, path="compose", custom_scenes=0,
                                   reason=(tier.reason + "; " if tier.reason else "") + f"{effort} effort: kit-first, "
                                   "engine-assembled from blueprints")
    if tier.custom_scenes < bud.max_custom:
        bud = dataclasses.replace(bud, max_custom=tier.custom_scenes)
    if not tier.vision or tier.path == "compose":
        # no critic to iterate with -> one measured review; a weak model's free-form revision patch regressed the
        # composed film in trials (5.7 -> 4.7, best-of kept v1): critique once, keep the engine's repairs only
        bud = dataclasses.replace(bud, rounds=1)
    r = _Run(brief, cat, bud, _as_director_llm(llm),
             renderer or RuntimeRenderer(gpu=brief.capabilities.gpu), job_dir, lib, progress, cancel, effort)
    r.tier = tier
    if hasattr(r.renderer, "job_dir") and getattr(r.renderer, "job_dir", None) is None:
        r.renderer.job_dir = job_dir
    r.save("brief.json", brief.to_dict())
    r.save("catalog.md", cat.full())
    r.save("tier.json", tier.to_dict())
    r.emit("setup", f"Director ready ({effort}: {r.budget.rounds} critique round(s), "
                    f"{len(cat.scenes())} kit/library scenes, {len(brief.assets)} media; model tier {tier.name}"
                    f"{'' if tier.vision else ', no vision: measured review'}"
                    f"{', compose path' if tier.path == 'compose' else ''})", 0.01, tier=tier.to_dict())
    return r


# ------------------------------------------------------------------------------------ the loop

def _produce(r: _Run, start: Version | None = None, first: Version | None = None) -> Version | None:
    """Treatment -> film -> realise -> critique/revise rounds -> per-shot best-of. Returns the best version.

    ``start`` = a finished version to revise with the user's notes; ``first`` = an already scripted v1
    (dev resume: skips the treatment and film calls).
    """
    try:
        if first is not None:
            v = first
            _static_bumps(r, v)
            if not _realise(r, v, code=list(v.customs)):
                return None
        elif start is None:
            v = _first_version(r)
            if v is None:
                return None
        else:
            v = _apply_notes(r, start)
            if v is None:
                return None
        rounds = r.budget.rounds
        for rnd in range(1, rounds + 1):
            _prominence_pass(r, v)
            r.versions.append(v)
            _save_version(r, v)
            late = _late(r, 0.7)
            if late:
                r.warn("critic", f"{late}: measured review instead of the vision critic")
            score = _critique(r, v, rnd, measured_only=bool(late))
            span = 0.45 + 0.45 * rnd / rounds
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
            late = _late(r, 0.5)
            if late:
                r.emit("critic", f"Critic round {rnd}: {score.mean:.1f} (min {score.min:g}) - {late}, no revision", span)
                _save_version(r, v)
                break
            r.emit("critic", f"Critic round {rnd}: {score.mean:.1f} -> fixing {n_issues} issue(s)", span - 0.2 / rounds)
            _save_version(r, v)
            nxt = _revise_version(r, v)
            if nxt is None:
                r.warn("revise", "Revision failed; keeping the best version so far")
                break
            v = nxt
        merged = _merge_best(r)
        if merged is not None:
            r.versions.append(merged)
            _save_version(r, merged)
    except BudgetExceeded as exc:
        r.warn("budget", f"{exc}; keeping the best version so far")
    scored = [x for x in r.versions if x.preview is not None and x.preview.ok]
    if not scored:
        return None
    return max(scored, key=Version.key)


# ------------------------------------------------------------------------------------ steps

def _first_version(r: _Run) -> Version | None:
    """v1 by the path the model's tier allows, falling down the floor on failure:
    free (treatment -> film -> custom code) -> compose (pick -> words -> engine film) -> engine floor (no model)."""
    if r.tier.path == "free":
        v = _free_version(r)
        if v is not None:
            return v
        r.warn("floor", "Composing from a blueprint instead")
    v = _compose(r, use_model=r.ledger.remaining >= 2)
    if v is not None and _realise(r, v, code=[]):
        return v
    if r.path != "floor":
        r.warn("floor", "The composed film did not render; using the engine floor film")
        v = _compose(r, use_model=False)
        if v is not None and _realise(r, v, code=[]):
            return v
    if r.budget.path == "compose" and r.tier.name != "weak" and r.ledger.remaining >= 2:
        # the effort chose compose for speed, but no blueprint fits/renders here: the model writes the film itself
        r.warn("floor", "No blueprint film rendered; the model writes the film (kit scenes only)")
        return _free_version(r)
    return None


def _free_version(r: _Run) -> Version | None:
    """The free path: treatment -> film script (+ custom code within the budget). None when it does not come
    together (the caller falls down to compose / the floor)."""
    try:
        r.emit("treatment", "Writing treatment", 0.03)
        r.treatment = _treatment(r)
        v = None
        if r.treatment:
            r.emit("film", "Writing film script", 0.10)
            v = _film(r)
        if v is not None:
            recipe = r.treatment.get("recipe")
            r.emit("scenes", f"Film script: {len(v.film['shots'])} shots, {len(v.customs)} custom scene(s)"
                             + (f" (recipe {recipe})" if recipe else ""), 0.18)
            if _realise(r, v, code=list(v.customs)):
                r.path = "free"
                return v
        r.warn("floor", "The free-form film did not come together")
    except BudgetExceeded:
        raise
    except Cancelled:
        raise
    except Exception as exc:
        if type(exc).__name__ == "Cancelled":
            raise
        log.exception("free path failed")
        r.warn("floor", f"The free-form path failed ({type(exc).__name__})")
    return None


def _compose(r: _Run, *, use_model: bool) -> Version | None:
    """The any-model path: PICK (enum-constrained) -> WORDS (slot texts) -> the engine assembles the film from the
    blueprint. Every reply is repaired; anything missing comes from the engine floor (``use_model=False`` = floor)."""
    bps = compose.blueprints(catalog=r.catalog, blender=r.brief.capabilities.blender)
    if not bps:
        r.emit("compose", "No blueprints are installed", level="error")
        return None
    brief = r.brief
    pick = compose.default_pick(bps, brief)
    texts: dict[str, str] = {}
    voice: list[dict[str, Any]] = []
    answered = 0                                   # model replies that were usable at all
    if use_model:
        r.emit("compose", "Choosing the film's blueprint", 0.05)
        instr, text = compose.pick_prompt(brief, bps)
        try:
            reply = r.ask("pick", instr, text, schema=compose.PICK_SCHEMA, schema_name="showreel.pick",
                          temperature=0.5, max_tokens=1500, timeout=180.0)
            raw = reply.parsed if reply.parsed is not None else reply.text
            answered += int(bool(reply.text.strip()) and not (reply.error and not reply.parsed))
            pick, fixes = compose.check_pick(raw, bps, brief)
            for f in fixes:
                r.emit("compose", f"pick repaired: {f}", level="debug")
            if reply.error and not reply.text:
                r.warn("compose", f"Pick call failed ({reply.error[:120]}); engine default blueprint")
        except BudgetExceeded:
            r.warn("compose", "No model calls left; engine default blueprint")
    bp = next(b for b in bps if b.id == pick["blueprint"])
    r.emit("compose", f"Blueprint {bp.id} ({bp.name}); voice {pick.get('voice')}; time {pick.get('time')}"
                      + (f": {pick.get('why')[:160]}" if pick.get("why") else ""), 0.08, blueprint=bp.id)
    if use_model and r.ledger.remaining >= 1:
        instr, text = compose.words_prompt(brief, bp, pick, float(brief.seconds))
        try:
            reply = r.ask("words", instr, text, schema=compose.WORDS_SCHEMA, schema_name="showreel.words",
                          temperature=0.7, max_tokens=2500, timeout=180.0)
            answered += int(bool(reply.text.strip()) and not (reply.error and not reply.parsed))
            texts, voice, fixes = compose.check_words(reply.parsed if reply.parsed is not None else reply.text,
                                                      bp, brief, pick, float(brief.seconds))
            for f in fixes:
                r.emit("compose", f"words repaired: {f}", level="debug")
        except BudgetExceeded:
            r.warn("compose", "No model calls left; the engine writes the words")
    if not voice and pick.get("voice") == "narrated" and not use_model:
        voice = []
    obj = compose.assemble(brief, bp, pick, texts, voice)
    if not r.treatment:
        r.treatment = compose.treatment_of(bp, pick, brief)
        r.save("treatment.json", r.treatment)
    value, errors, warnings = _validate(r, obj)
    for w in warnings:
        r.emit("compose", w, level="debug")
    if value is None and (texts or voice):
        r.warn("compose", f"Composed film rejected ({'; '.join(errors)[:240]}); retrying without the model's words")
        value, errors, _w = _validate(r, compose.assemble(brief, bp, pick))
    if value is None:
        r.emit("compose", f"Blueprint {bp.id} did not validate: {'; '.join(errors)[:300]}", level="error")
        ranked = compose.rank(bps, brief.direction, brief)
        top = ranked[0][0] if ranked else 0.0
        # only alternatives that still match the direction (a documentary must not become a boss battle)
        alt = [b for s, b in ranked if b.id != bp.id and not b.blender and (s >= 0.5 * top or top <= 0.6)]
        for b in alt[:2]:
            value, errors, _w = _validate(r, compose.assemble(brief, b, compose.default_pick([b], brief)))
            if value is not None:
                bp = b
                break
    if value is None:
        return None
    film, plan = value
    r.path = "compose" if use_model and answered else "floor"
    v = Version(1, film, plan, origin=r.path)
    _static_bumps(r, v)
    r.save("v1/compose.json", {"blueprint": bp.id, "pick": pick, "texts": texts, "voiceover": voice,
                               "path": r.path})
    r.emit("scenes", f"Composed film: {len(film['shots'])} shots on blueprint {bp.id} ({r.path})", 0.18)
    return v


def _treatment(r: _Run) -> dict[str, Any]:
    instr, text = prompts.treatment_prompt(r.brief, r.catalog)
    images = _product_images(r)
    extra, last_usable = "", None
    for attempt in range(1 + r.budget.film_repairs):
        reply = r.ask("treatment", instr, text + extra, schema=prompts.TREATMENT_SCHEMA,
                      schema_name="showreel.treatment", images=images, temperature=0.8, max_tokens=12000)
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
                   acts=[a.get("name") for a in chk.value.get("acts") or []], recipe=chk.value.get("recipe"))
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
    v = Version(1, film, plan)
    _static_bumps(r, v)
    return v


def _validate(r: _Run, obj: Any) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, list[str], list[str]]:
    """Director checks + static prominence + runtime schema for a {film, plan} object."""
    if isinstance(obj, dict) and isinstance(obj.get("film"), dict):
        obj, fixes = repair.coerce(obj, prompts.FILM_SCHEMA)
        fixes += repair.snap_film_ids(obj, r.catalog, [a.name for a in r.brief.assets])
        if fixes:
            r.emit("repair", f"Repaired {len(fixes)} field(s) of the film reply: {'; '.join(fixes[:6])[:300]}",
                   level="debug")
    chk = check_film(obj, r.brief, r.catalog, max_custom=r.budget.max_custom)
    errors = list(chk.errors)
    if chk.value is not None and not errors:
        film, plan = chk.value
        perr, notes = pm.static_check(film, plan, r.product, r.brief.aspect)
        errors += perr
        chk.warnings.extend(notes)
        if not errors:
            errors += [f"runtime schema: {e}" for e in r.renderer.validate_film(film)]
    return (chk.value if not errors else None), errors, chk.warnings


def _structured_film(r: _Run, purpose: str, instr: str, text: str, schema: dict[str, Any],
                     schema_name: str, images: list[Image] | None = None,
                     ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Ask for {film, plan, ...}, validate (director checks + runtime schema) and repair."""
    extra = ""
    for attempt in range(1 + r.budget.film_repairs):
        reply = r.ask(purpose, instr, text + extra, schema=schema, schema_name=schema_name, temperature=0.6,
                      images=images if attempt == 0 else None, max_tokens=FILM_MAX_TOKENS, timeout=600.0)
        obj = _json_of(reply)
        if obj is None:
            errs = [reply.error or "the reply was not valid JSON (or was cut off: keep specs tighter)"]
            r.warn(purpose, f"Film attempt {attempt + 1}: {errs[0][:160]}")
            extra = prompts.repair_text(reply.text[:8000], errs)
            continue
        value, errors, warnings = _validate(r, obj)
        for w in warnings:
            r.emit(purpose, w, level="debug")
        if value is not None:
            film, plan = value
            return film, plan, obj
        r.warn(purpose, f"Film attempt {attempt + 1} rejected: {'; '.join(errors)[:400]}")
        extra = prompts.repair_text(obj, errors)
    r.emit(purpose, "The film script did not pass validation", level="error")
    return None


def _structured_patch(r: _Run, purpose: str, instr: str, text: str, base: Version,
                      images: list[Image] | None = None,
                      ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Ask for a revision PATCH, apply it to ``base``, validate the result; re-ask with the errors."""
    extra = ""
    for attempt in range(1 + r.budget.film_repairs):
        reply = r.ask(purpose, instr, text + extra, schema=prompts.REVISE_PATCH_SCHEMA, schema_name="showreel.patch",
                      temperature=0.5, images=images if attempt == 0 else None, max_tokens=PATCH_MAX_TOKENS,
                      timeout=600.0)
        obj = _json_of(reply)
        if not isinstance(obj, dict):
            errs = [reply.error or "the reply was not a JSON object"]
            r.warn(purpose, f"Patch attempt {attempt + 1}: {errs[0][:160]}")
            extra = prompts.repair_text(reply.text[:6000], errs)
            continue
        if isinstance(obj.get("film"), dict) and obj["film"].get("shots"):      # a whole film came back
            film, plan, perr = obj["film"], obj.get("plan") or base.plan, []
        else:
            film, plan, perr, _touched = apply_film_patch(base.film, base.plan, obj)
        value, errors, warnings = _validate(r, {"film": film, "plan": plan})
        errors = perr + errors
        for w in warnings:
            r.emit(purpose, w, level="debug")
        if value is not None and not perr:
            return value[0], value[1], obj
        r.warn(purpose, f"Patch attempt {attempt + 1} rejected: {'; '.join(errors)[:400]}")
        extra = prompts.repair_text(obj, [*errors, "(the current film above is unchanged; send a corrected patch)"])
    r.emit(purpose, "The revision patch did not pass validation", level="error")
    return None


def _static_bumps(r: _Run, v: Version) -> None:
    """Before any render: product flyers that would be specks in product shots are enlarged; screenshots flying
    in nature scenes are never chroma-keyed (the kit's auto-key eats light UI backgrounds -> a ghosted card)."""
    if not r.product:
        return
    screens = {a.name for a in r.brief.assets if a.product and a.type == "image" and not a.cutout}
    for s in v.film["shots"]:
        scene = str(s.get("scene", ""))
        if screens and scene in pm.NATURE_FLYER_SCENES + pm.NATURE_HERO_SCENES:
            for f in (s.get("params") or {}).get("flyers") or []:
                if isinstance(f, dict) and f.get("media") in screens:
                    f.setdefault("key", False)
                    if "facing" not in f and pm.flyer_direction(f) < 0:
                        f["facing"] = "left"        # the kit mirrors left-moving cards: UI text would read backwards
    intents = {p["id"]: p for p in v.plan.get("shots") or []}
    for s in v.film["shots"]:
        if not references(s.get("params") or {}, r.product) or not (intents.get(s["id"]) or {}).get("product_visible"):
            continue
        est = pm.estimate_width(s, r.brief.aspect)
        if est is not None and est < 0.18:
            what = pm.bump(s, 0.30 / max(est, 0.06), _declared(r, s))
            if what:
                v.changes.append(f"engine: {s['id']} product too small before render (~{est:.0%}): {what}")
                r.emit("prominence", f"Shot {s['id']}: product would read ~{est:.0%} wide; {what}")


def _declared(r: _Run, shot: dict[str, Any]) -> list[str]:
    info = r.catalog.scenes().get(str(shot.get("scene", "")))
    return list(info.params) if info else []


def _code_scene(r: _Run, v: Version, name: str, *, issues: list[dict[str, Any]] | None = None, notes: str = "",
                errors: list[str] | None = None) -> bool:
    """Write (or patch / repair) one custom scene until it lints clean.

    New scenes are written whole. Revisions and repairs of existing code are SEARCH/REPLACE patches (untouched
    lines stay byte-identical); a patch that does not apply is retried once with the failures, then the scene is
    rewritten whole. Returns False when its tries ran out; a revision that never lints clean keeps the previous
    working code (``v.stable``).
    """
    spec = v.customs[name]
    sid = f"custom:{name}"
    shots = [s for s in v.film["shots"] if s["scene"] == sid]
    plan_shots = {p["id"]: p for p in v.plan.get("shots") or []}
    prev = v.scenes.get(name, "")
    errs = list(errors or [])
    failures: list[str] = []
    whole = False                                   # patching failed twice: rewrite the file
    while v.tries.get(name, 0) < r.budget.scene_tries:
        see: list[Image] = []
        v.tries[name] = v.tries.get(name, 0) + 1
        attempt = v.tries[name]
        patch_mode = bool(prev) and not whole and bool(errs or issues or notes)
        if patch_mode:
            cells = (v.review.get("cells") or {}).get(name) or []
            see = list(v.review.get("images") or []) if cells and not errs else []
            r.emit("scenes", f"{'Repairing' if errs else 'Revising'} scene {name} (patch, try {attempt})"
                             + (f": {errs[0][:120]}" if errs else ""))
            instr, text = prompts.scene_patch_prompt(r.brief, r.catalog, spec, prev, issues=None if errs else issues,
                                                     errors=errs or None, notes="" if errs else notes,
                                                     keep=v.review.get("keep"), cells=cells if see else None,
                                                     failures=failures or None)
        elif errs and prev:
            r.emit("scenes", f"Repairing scene {name} (try {attempt}): {errs[0][:120]}")
            instr, text = prompts.scene_repair_prompt(r.brief, r.catalog, spec, prev, errs)
        elif prev and (issues or notes):
            r.emit("scenes", f"Revising scene {name} (whole file)")
            cells = (v.review.get("cells") or {}).get(name) or []
            see = list(v.review.get("images") or []) if cells else []
            instr, text = prompts.scene_revise_prompt(r.brief, r.catalog, spec, prev, issues or [], notes,
                                                      keep=v.review.get("keep"), cells=cells if see else None)
        else:
            r.emit("scenes", f"Coding scene {name}")
            instr, text = prompts.scene_prompt(r.brief, r.catalog, spec, shots, plan_shots)
        reply = r.ask(f"scene:{name}", instr, text, images=see, temperature=0.5,
                      max_tokens=PATCH_MAX_TOKENS if patch_mode else SCENE_MAX_TOKENS, timeout=600.0)
        if reply.error and not reply.text.strip() and re.search(r"timed? ?out|timeout", reply.error, re.IGNORECASE):
            # a scene call that times out (a slow model: > 30 min in trials) will time out again: stop paying
            # for retries and let the kit fallback / previous code stand in
            r.warn("scenes", f"Scene {name}: the model timed out writing it; using the kit fallback")
            v.tries[name] = r.budget.scene_tries
            break
        blocks = parse_blocks(reply.text) if patch_mode else []
        if blocks:
            code, failures = apply_blocks(prev, blocks)
            if failures:
                r.warn("scenes", f"Scene {name} patch did not apply: {failures[0][:160]}")
                whole = whole or attempt >= 2
                continue
        else:
            code = extract_js(reply.text)
            if not code or reply.text.count("```") % 2:
                if patch_mode and not code:
                    failures = ["no edit blocks found: answer with <<<<<<< SEARCH / ======= / >>>>>>> REPLACE blocks"]
                    r.warn("scenes", f"Scene {name} try {attempt}: no edit blocks in the reply")
                    whole = whole or attempt >= 2
                    continue
                errs = [reply.error or ("the reply was cut off before the end of the ```js block: the module is too "
                                        f"long; rewrite it more compactly (under {MAX_SCENE_BYTES // 1000} KB)" if code
                                        else "no ```js code block in the reply")]
                r.warn("scenes", f"Scene {name} try {attempt}: {errs[0][:160]}")
                if not prev:
                    prev = code
                whole = True
                continue
        failures = []
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
    """Code the listed custom scenes (in parallel), then build + dry-run with repairs/fallbacks; captures keyframes."""
    issues, notes = issues or {}, notes or {}
    names = [n for n in code if n in v.customs]
    if names:
        r.frac = max(r.frac, 0.2)

        def one(name: str) -> bool:
            return _code_scene(r, v, name, issues=issues.get(name), notes=notes.get(name, ""))
        workers = max(1, min(len(names), SCENE_PARALLEL))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="showreel-scene") as pool:
                results = dict(zip(names, pool.map(one, names), strict=True))
        else:
            results = {n: one(n) for n in names}
        for name in names:
            if not results[name] and not _fallback(r, v, name, "code did not pass lint"):
                return False
    return _dry_run(r, v)


# ------------------------------------------------------------------------------------ fingerprints

def _code_of(v: Version, scene: str) -> str:
    if scene.startswith("custom:"):
        return hashlib.sha1(v.scenes.get(scene.split(":", 1)[1], "").encode("utf-8")).hexdigest()
    return ""


def shot_fingerprint(v: Version, shot: dict[str, Any]) -> str:
    """Identity of one shot's pixels-to-be: its definition + its scene code."""
    blob = json.dumps({"shot": shot, "code": _code_of(v, str(shot.get("scene", "")))}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def frame_fingerprint(v: Version, t: float) -> str:
    """Identity of the frame at film time ``t``: everything that can draw on it (shots active or blending in a
    transition, overlays, captions, finish) with their code. Equal fingerprints render equal pixels."""
    film = v.film
    trans = [tr for tr in film.get("transitions") or []
             if float(tr["t"]) - 1e-6 <= t <= float(tr["t"]) + float(tr["dur"])]
    ids = {tr["from"] for tr in trans} | {tr["to"] for tr in trans}
    shots = [s for s in film.get("shots") or [] if float(s["t0"]) <= t < float(s["t1"]) or s["id"] in ids]
    overlays = [o for o in film.get("overlays") or [] if float(o["t0"]) <= t < float(o["t1"])]
    caps = [c for c in film.get("captions") or [] if float(c["t0"]) <= t < float(c["t1"])]
    blob = json.dumps({"t": round(t, 3), "shots": shots, "codes": [_code_of(v, s["scene"]) for s in shots],
                       "trans": trans, "overlays": overlays, "ocodes": [_code_of(v, o["scene"]) for o in overlays],
                       "caps": caps, "finish": film.get("finish"), "bg": film.get("background"),
                       "size": film.get("size"), "fonts": film.get("fonts"), "safe": film.get("safe")},
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------ dry run + keyframes

def _mask_page(r: _Run, film: dict[str, Any]) -> Path | None:
    """The product-flipped mirror of the built page (None when the film shows no product media)."""
    names = [n for n in (film.get("assets") or {}) if n in r.product]
    if not names:
        return None
    try:
        flipped = pm.flipped_assets(r.page_dir, names, r.ddir / "flipcache")
        if not flipped:
            return None
        return pm.mirror_page(r.page_dir, r.ddir / "maskpage", flipped)
    except Exception as exc:
        r.warn("prominence", f"Could not prepare the measurement page: {exc}")
        return None


def _dry_run(r: _Run, v: Version) -> bool:
    """Build the page and render probe frames for CHANGED shots only; repair scenes that throw, fall back when
    tries run out. Keyframes whose fingerprint is unchanged come from the cache (no re-render)."""
    v.frames = plan_keyframes(v.film, r.budget.keyframes_per_shot)
    stalls = 0
    for loop in range(r.budget.scene_tries + 4):
        r.check_cancel()
        if hasattr(r.renderer, "blender_times"):
            r.renderer.blender_times = _blender_times(v)
        errs = r.renderer.build(v.film, r.page_dir, scenes=v.scenes, assets=r.brief.assets,
                                library_dir=r.library_dir)
        r.built_n = v.n
        if errs:
            r.emit("dryrun", f"Page build failed: {'; '.join(errs)[:300]}", level="error")
            return False
        sfp = {s["id"]: shot_fingerprint(v, s) for s in v.film["shots"]}
        changed = {sid for sid, fp in sfp.items() if fp not in r.shot_ok}
        probe, det = _probe_times(v.film, only=changed)
        ffp = [frame_fingerprint(v, f.t) for f in v.frames]
        need = [i for i, fp in enumerate(ffp) if fp not in r.frame_cache]
        mask = _mask_page(r, v.film) if need and r.product else None
        r.emit("dryrun", f"Dry run v{v.n}{f' (pass {loop + 1})' if loop else ''}: {len(probe)} probe frames for "
                         f"{len(changed)} changed shot(s), {len(need)}/{len(v.frames)} keyframes to render",
               0.42 if v.n == 1 else None)
        if not probe and not need and not det:          # nothing changed since a clean dry run: no browser
            pv = Preview(ok=True)
        else:
            pv = r.renderer.preview(r.page_dir, probe_times=probe, capture_times=[v.frames[i].t for i in need],
                                    size=r.brief.preview_size, film_size=r.brief.size, shots=v.film["shots"],
                                    determinism_times=det, mask_page=mask)
        v.preview = pv
        r.save(f"v{v.n}/dryrun-{loop + 1}.json", {"ok": pv.ok, "load_error": pv.load_error, "seconds": pv.seconds,
                                                  "changed": sorted(changed), "rendered_keyframes": len(need),
                                                  "errors": [str(e) for e in pv.errors[:60]], "qa": pv.qa[:80]})
        by_scene = _errors_by_scene(v, pv)
        kit_errors = by_scene.pop("", [])
        if pv.ok and not by_scene:
            if kit_errors:
                r.warn("dryrun", f"{len(kit_errors)} runtime error(s) in kit shots: {kit_errors[0][:160]}")
            if len(pv.images) != len(need):                    # renderer captured something else: use it as is
                v.images, v.mask_images = list(pv.images), list(pv.mask_images)
            else:
                masks: list[bytes | None] = (list(pv.mask_images) if len(pv.mask_images) == len(need)
                                             else [None] * len(need))
                for i, img, m in zip(need, pv.images, masks, strict=True):
                    r.frame_cache[ffp[i]] = (img, m)
                v.images = [r.frame_cache[fp][0] for fp in ffp]
                ms = [r.frame_cache[fp][1] for fp in ffp]
                v.mask_images = [m for m in ms if m is not None] if all(m is not None for m in ms) else []
            r.shot_ok.update(sfp.values())
            return True
        if not by_scene:
            if stalls < 2 and re.search(r"timed out|stall|crash|disconnect|closed", pv.load_error or "", re.IGNORECASE):
                stalls += 1             # an intermittent browser stall: retry with a fresh browser, not a new film
                r.warn("dryrun", f"Browser stalled ({pv.load_error[:120]}); retrying with a fresh browser")
                continue
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


def _blender_shot_ids(film: dict[str, Any]) -> set[str]:
    return {str(s["id"]) for s in film.get("shots") or [] if str(s.get("scene", "")).startswith("blender:")}


def _blender_times(v: Version) -> list[float]:
    """Film times the browser will show inside Blender shots (keyframes + probe frames): only these frames are
    rendered by the Blender preview pass."""
    ids = _blender_shot_ids(v.film)
    if not ids:
        return []
    probe, _det = _probe_times(v.film, only=ids)
    return sorted({round(f.t, 3) for f in v.frames} | set(probe))


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


def _probe_times(film: dict[str, Any], only: set[str] | None = None) -> tuple[list[float], list[float]]:
    """Dry-run times: start/middle/end of every (changed) shot, every 0.5 s inside custom shots; determinism."""
    times: set[float] = set()
    det: list[float] = []
    for s in film["shots"]:
        if only is not None and s["id"] not in only:
            continue
        t0, t1 = float(s["t0"]), float(s["t1"])
        times.update({round(t0 + 0.04, 3), round((t0 + t1) / 2, 3), round(t1 - 0.04, 3)})
        if str(s["scene"]).startswith("custom:"):
            t = t0 + 0.25
            while t < t1:
                times.add(round(t, 3))
                t += 0.5
            det += [round(t0 + 0.37 * (t1 - t0), 3), round(t0 + 0.81 * (t1 - t0), 3)]
    return sorted(times), det


# ------------------------------------------------------------------------------------ prominence

def _measure(r: _Run, v: Version) -> None:
    if not r.product or not v.mask_images or len(v.mask_images) != len(v.images):
        v.measures, v.prom = [], None
        return
    v.measures = pm.measure_frames(v.frames, v.images, v.mask_images)
    b_ids = _blender_shot_ids(v.film)
    if b_ids:          # Blender frames are not drawn from the flipped media: the mirror cannot measure them
        v.measures = [m for m in v.measures if m.shot not in b_ids]
        if not v.measures:
            v.prom = None
            return
    v.prom = pm.summarise(v.measures)
    pm.save(r.ddir / f"v{v.n}" / "prominence.json", v.measures, v.prom)


def _prominence_failures(r: _Run, v: Version) -> list[tuple[dict[str, Any], float]]:
    """(shot, measured largest width) for product shots that read too small or not at all."""
    if v.prom is None:
        return []
    intents = {p["id"]: p for p in v.plan.get("shots") or []}
    film_ok = v.prom.visible_share >= PRODUCT_SHARE_BAR and v.prom.hero_share >= PRODUCT_HERO_BAR
    out = []
    for s in v.film["shots"]:
        d = v.prom.per_shot.get(s["id"])
        if d is None:
            continue
        wanted = bool((intents.get(s["id"]) or {}).get("product_visible"))
        refs = bool(references(s.get("params") or {}, r.product))
        ghost = 0 < float(d.get("clarity", 1.0)) < pm.FAINT and _fragmented(v, s["id"])
        if wanted and d["visible"] == 0:
            out.append((s, 0.0))
        elif refs and d["max_width"] < PRODUCT_HERO_SIZE and (not film_ok or wanted) and not ghost:
            out.append((s, d["max_width"]))     # a ghosted, fragmented product measures narrow: never grow it blind
    return out


def _fragmented(v: Version, shot: str) -> bool:
    """The product breaks into several regions in most of the shot's keyframes (keyed/ghosted UI cards)."""
    ms = [m for m in v.measures if m.shot == shot and m.visible]
    return bool(ms) and sum(m.regions >= 3 for m in ms) * 2 >= len(ms)


def _prominence_pass(r: _Run, v: Version) -> None:
    """Measure the product in every keyframe; when product shots read too small, enlarge them (kit params) or
    patch their custom scene, re-render only those shots and measure again - all before the critic looks."""
    _measure(r, v)
    if v.prom is None:
        return
    r.emit("prominence", f"Measured v{v.n}: product visible in {v.prom.visible_share:.0%} of keyframes, hero-sized "
                         f"in {v.prom.hero_share:.0%}", measured=v.prom.to_dict())
    while v.prom_repaired < r.budget.prominence_repairs:
        bad = _prominence_failures(r, v)
        if not bad:
            return
        v.prom_repaired += 1
        bumped: list[str] = []
        scene_issues: dict[str, list[dict[str, Any]]] = {}
        for s, w in bad:
            scene = str(s["scene"])
            if scene.startswith("custom:") and scene.split(":", 1)[1] in v.scenes:
                scene_issues.setdefault(scene.split(":", 1)[1], []).append({
                    "shot": s["id"], "target": "scene", "severity": 3,
                    "issue": (f"MEASURED: the product media is not drawn in shot {s['id']}" if w == 0 else
                              f"MEASURED: the product spans only {w:.0%} of the frame width in shot {s['id']}"),
                    "fix": f"draw ctx.asset(<the product param>) as the hero: >= {pm.TARGET_WIDTH:.0%} of the frame "
                           "width at its key moment (scale it up / move the camera closer); keep the composition"})
                continue
            what = pm.bump(s, pm.TARGET_WIDTH / max(w, 0.08), _declared(r, s))
            if what:
                bumped.append(f"{s['id']}: {what}")
        if not bumped and not scene_issues:
            return
        msg = "; ".join(bumped + [f"{n}: patching the scene" for n in scene_issues])
        v.changes.append(f"engine prominence repair: {msg}")
        r.emit("prominence", f"Product too small in {len(bad)} shot(s) - {msg[:240]}")
        if scene_issues:
            v.stable = {**v.scenes, **v.stable}
            for n in scene_issues:
                v.tries[n] = 0
        if not _realise(r, v, code=list(scene_issues), issues=scene_issues):
            r.warn("prominence", "The prominence repair did not render; keeping the measured version")
            return
        _measure(r, v)
        if v.prom is not None:
            r.emit("prominence", f"Re-measured v{v.n}: visible {v.prom.visible_share:.0%}, hero-sized "
                                 f"{v.prom.hero_share:.0%}", measured=v.prom.to_dict())


# ------------------------------------------------------------------------------------ critic

def _late(r: _Run, frac: float) -> str:
    """A reason string when the run has used more than ``frac`` of its effort's wall-clock target, else ""."""
    dl = float(getattr(r.budget, "deadline_s", 0.0) or 0.0)
    spent = time.monotonic() - r.t0
    return f"{spent / 60:.0f} of the {r.effort} effort's {dl / 60:.0f} min used" if dl and spent > frac * dl else ""


def _critique(r: _Run, v: Version, rnd: int, *, measured_only: bool = False) -> RoundScore | None:
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
    _save_frames(r, v)
    sheets = contact_sheets(v.images, v.frames, vdir, prefix="contact")
    v.sheets = list(sheets)
    r.emit("critic", f"Critic round {rnd}: reviewing {len(v.frames)} keyframes on {len(sheets)} sheet(s)",
           sheets=[str(s) for s in sheets])
    if not r.tier.vision or measured_only:
        return _measured_critique(r, v, rnd)
    product = r.product
    share, missing = product_share(v.film, product) if product else (1.0, [])
    checks = [f"product media referenced in {share:.0%} of the runtime" + (f" (not in {missing})" if missing else "")]
    first = first_product_time(v.film, product) if product else None
    if first is not None:
        checks.append(f"product first appears at {first:g} s")
    if v.prom is not None:
        checks += pm.facts(v.prom, v.film, v.measures)
        if r.parent_prom is not None and r.brief.notes.strip():
            checks.append("MEASURED before the user's notes (largest product width per shot): " + ", ".join(
                f"{sid} {d['max_width']:.0%}" for sid, d in r.parent_prom.per_shot.items()))
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
        note = {"text": f"User revision notes: {r.brief.notes.strip()}", "how": "must be visibly addressed"}
        treat["requirements"] = [*list(treat.get("requirements") or []), note]
    instr, text = prompts.critic_prompt(r.brief, treat, v.film, v.plan, [f.to_dict() for f in v.frames], checks)
    images = [Image(s.read_bytes(), "image/jpeg", str(s), f"contact sheet {i + 1}") for i, s in enumerate(sheets)]
    crit = None
    for attempt in range(2):
        reply = r.ask(f"critic:r{rnd}", instr, text, schema=prompts.CRITIC_SCHEMA, schema_name="showreel.critique",
                      images=images, temperature=0.2, max_tokens=10000)
        crit = _normalise_critique(_json_of(reply), v)
        if crit is not None:
            break
        r.warn("critic", f"Critique attempt {attempt + 1} unusable: {(reply.error or reply.text)[:160]}")
    if crit is None:
        return None
    scores = crit["scores"]
    vals = [scores[k] for k in RUBRIC_KEYS]
    if v.prom is not None:                   # measured beats estimated
        vshare, hshare = v.prom.visible_share, v.prom.hero_share
    else:
        frames = [f for f in crit.get("frames") or [] if isinstance(f, dict) and "product_visible" in f]
        vis = [bool(f.get("product_visible")) for f in frames]
        vshare = (sum(vis) / len(vis)) if vis else None
        hero = [_num(f.get("product_size")) >= PRODUCT_HERO_SIZE for f in frames if f.get("product_visible")]
        hshare = (sum(hero) / len(frames)) if frames else None
    sev3 = any(i["severity"] >= 3 for i in crit["per_shot_issues"])
    passed = (min(vals) >= SCORE_BAR and not sev3 and (vshare is None or not product or vshare >= PRODUCT_SHARE_BAR)
              and (hshare is None or not product or hshare >= PRODUCT_HERO_BAR))
    v.critique = crit
    v.score = RoundScore(rnd, v.n, scores, round(sum(vals) / len(vals), 2), min(vals), vshare, passed,
                         len(crit["per_shot_issues"]), str(crit.get("verdict", "")), hshare)
    r.save(f"v{v.n}/critique.json", crit)
    shots_txt = ", ".join(f"{k} {s:g}" for k, s in v.shot_scores().items())
    r.emit("critic", f"Scores v{v.n}: " + ", ".join(f"{k} {scores[k]:g}" for k in RUBRIC_KEYS)
           + (f"; product visible in {vshare:.0%} of keyframes" if vshare is not None else "")
           + (f", framed as the hero in {hshare:.0%}" if hshare is not None and product else "")
           + (f"; shots: {shots_txt}" if shots_txt else ""),
           scores=scores, product_share=vshare, shot_scores=v.shot_scores())
    return v.score


def _measured_critique(r: _Run, v: Version, rnd: int) -> RoundScore:
    """No vision: score the version from measurements (keyframes, prominence, layout QA, film structure)."""
    crit = measured.review(v.film, v.plan, v.frames, v.images, prom=v.prom, measures=v.measures,
                           qa=(v.preview.qa if v.preview else []), fallbacks=v.fallbacks, product=bool(r.product))
    crit = _normalise_critique(crit, v) or crit
    crit["measured"] = True
    scores = crit["scores"]
    vals = [scores[k] for k in RUBRIC_KEYS]
    vshare = v.prom.visible_share if v.prom is not None else None
    hshare = v.prom.hero_share if v.prom is not None else None
    v.critique = crit
    v.score = RoundScore(rnd, v.n, scores, round(sum(vals) / len(vals), 2), min(vals), vshare, False,
                         len(crit["per_shot_issues"]), str(crit.get("verdict", "")), hshare)
    r.save(f"v{v.n}/critique.json", crit)
    r.emit("critic", f"Measured review v{v.n} (no vision): " + ", ".join(f"{k} {scores[k]:g}" for k in RUBRIC_KEYS),
           scores=scores, measured=True)
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
    shots = [s for s in obj.get("shots") or [] if isinstance(s, dict) and str(s.get("id")) in ids]
    return dict(obj, scores=scores, per_shot_issues=issues[:10], shots=shots)


# ------------------------------------------------------------------------------------ revisions

def _revise_version(r: _Run, v: Version) -> Version | None:
    """Apply the critique as patches: a film-level patch (only if film issues exist) + scene patches for the custom
    scenes the review names. Everything else stays identical (and is not re-rendered)."""
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
    for name, qa_items in _qa_by_scene(v).items():
        if name in scene_issues:                 # only scenes that are being revised anyway
            scene_issues[name] += qa_items
    extras = [{"shot": "film", "target": "film", "severity": 3, "issue": f"requirement not met: {q.get('text')}",
               "fix": str(q.get("note") or "make it visibly happen")} for q in unmet]
    if v.score and v.score.product_share is not None and v.score.product_share < PRODUCT_SHARE_BAR:
        extras.append({"shot": "film", "target": "film", "severity": 3,
                       "issue": f"the product is visible in only {v.score.product_share:.0%} of keyframes (measured)",
                       "fix": "put the product on screen (large, lit) in more shots or shorten shots without it"})
    small = _small_product_shots(v)
    faint = _faint_product_shots(v)
    if faint:
        extras.append({"shot": "film", "target": "film", "severity": 3,
                       "issue": "MEASURED: the product reads faint/ghosted (its own pixels barely reach the "
                                "screen) in: " + ", ".join(f"{s} (clarity {c:.0%})" for s, c in faint),
                       "fix": "make the product solid and crisp there: for a screenshot/UI card in a nature scene set "
                              "`key: false` on its flyer (auto-key eats light UI backgrounds) and bring it closer "
                              "(less haze); move titles/lockups/scrims off the product; lower bloom/mist over it"})
    if small and v.score and v.score.product_hero is not None and v.score.product_hero < PRODUCT_HERO_BAR:
        extras.append({"shot": "film", "target": "film", "severity": 3,
                       "issue": f"the product is framed as the hero (>= {PRODUCT_HERO_SIZE:.0%} of the frame width) in "
                                f"only {v.score.product_hero:.0%} of keyframes; too small in: "
                                + ", ".join(f"{s} ({w:.0%})" for s, w in small),
                       "fix": "scale the product up (scene params / camera / framing) so it reads as the hero; "
                              "aim for >= 35 % of the width in most shots"})
    film_issues += extras
    keep = [str(x) for x in crit.get("strengths") or []][:6]
    cells = _cells_by_scene(v)
    images = [Image(p.read_bytes(), "image/jpeg", str(p), f"contact sheet {i + 1} (current render)")
              for i, p in enumerate(v.sheets) if p.is_file()]
    nv = Version(v.n + 1, copy.deepcopy(v.film), copy.deepcopy(v.plan), dict(v.scenes), dict(v.fallbacks),
                 stable=dict(v.scenes), origin="revision")
    notes: dict[str, str] = {}
    recode: list[str] = list(scene_issues)
    if film_issues:
        r.emit("revise", f"Revising the film script ({len(film_issues)} film-level issue(s), as a patch)")
        facts = pm.facts(v.prom, v.film, v.measures) if v.prom is not None else None
        instr, text = prompts.revise_patch_prompt(r.brief, r.catalog, r.treatment, v.film, v.plan, issues + extras, "",
                                                  max_custom=r.budget.max_custom, keep=keep, seen=bool(images),
                                                  facts=facts)
        res = _structured_patch(r, "revise-film", instr, text, v, images=images)
        if res is not None:
            _adopt(r, v, nv, res, recode)
            notes = {str(n.get("name")): str(n.get("notes")) for n in res[2].get("scene_notes") or []
                     if isinstance(n, dict) and n.get("name")}
            recode += [n for n in notes if n in nv.customs and n not in recode]
        else:
            r.warn("revise", "Film revision rejected; applying scene fixes only")
    recode = [n for n in recode if n in nv.customs]
    if not recode and nv.film == v.film and nv.plan == v.plan:
        r.warn("revise", "Nothing actionable in the critique")
        return None
    nv.tries = {}
    nv.review = {"keep": keep, "cells": cells, "images": images}
    r.emit("revise", f"Revision v{nv.n}: shots changed {shot_diff(v.film, nv.film) or 'none'}; "
                     f"scenes patched {recode or 'none'}")
    if not _realise(r, nv, code=recode, issues=scene_issues, notes=notes):
        return None
    return nv


def _adopt(r: _Run, old: Version, nv: Version, res: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
           recode: list[str]) -> None:
    """Take a validated revised film/plan into ``nv``; custom scenes that are new or re-specified get coded."""
    film, plan, obj = res
    nv.film, nv.plan = film, plan
    nv.changes = [str(c) for c in obj.get("changes") or []]
    old_specs = old.customs
    for name, spec in nv.customs.items():
        if name not in old_specs or name not in nv.scenes:
            nv.scenes.pop(name, None)
            nv.tries.pop(name, None)
            if name not in recode:
                recode.append(name)
        elif spec.get("spec") != old_specs[name].get("spec") and name not in recode:
            recode.append(name)
    for name in list(nv.scenes):
        if name not in nv.customs:
            nv.scenes.pop(name)
    _static_bumps(r, nv)
    if nv.changes:
        r.emit("revise", "Changes: " + "; ".join(nv.changes)[:300])


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _faint_product_shots(v: Version) -> list[tuple[str, float]]:
    """(shot, best clarity) for shots whose sizeable product never reads solid (measured, see prominence.clarity)."""
    if v.prom is None:
        return []
    return [(s, float(d.get("clarity", 1.0))) for s, d in v.prom.per_shot.items()
            if d["visible"] > 0 and d["max_width"] >= 0.08 and 0 < float(d.get("clarity", 1.0)) < pm.FAINT]


def _small_product_shots(v: Version) -> list[tuple[str, float]]:
    """(shot, largest product width seen) for product shots whose keyframes never frame it as the hero."""
    if v.prom is not None:
        return [(s, d["max_width"]) for s, d in v.prom.per_shot.items()
                if d["max_width"] < PRODUCT_HERO_SIZE and d["visible"] > 0]
    by_cell = {f.cell: f.shot for f in v.frames}
    best: dict[str, float] = {}
    for f in (v.critique or {}).get("frames") or []:
        if not isinstance(f, dict):
            continue
        shot = by_cell.get(int(_num(f.get("cell"))))
        if shot:
            best[shot] = max(best.get(shot, 0.0), _num(f.get("product_size")) if f.get("product_visible") else 0.0)
    return [(s, w) for s, w in best.items() if w < PRODUCT_HERO_SIZE]


def _cells_by_scene(v: Version) -> dict[str, list[str]]:
    """custom scene name -> contact-sheet cell labels showing it (for revisions that look at the render)."""
    scene_of = {s["id"]: s["scene"] for s in v.film["shots"]}
    out: dict[str, list[str]] = {}
    for f in v.frames:
        sc = scene_of.get(f.shot, "")
        if sc.startswith("custom:"):
            out.setdefault(sc.split(":", 1)[1], []).append(f"{f.cell} ({f.shot} {f.t:.1f}s)")
    return out


def _qa_by_scene(v: Version, per_scene: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Runtime layout-QA findings (clipped/overlapping/unsafe/small text) grouped by custom scene, deduplicated."""
    scene_of = {s["id"]: s["scene"] for s in v.film["shots"]}
    out: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for q in (v.preview.qa if v.preview else []):
        scene = scene_of.get(str(q.get("shot", "")), "")
        if not scene.startswith("custom:"):
            continue
        name = scene.split(":", 1)[1]
        key = (name, f"{q.get('kind')}:{q.get('msg')}")
        if key in seen or len(out.get(name, [])) >= per_scene:
            continue
        seen.add(key)
        fix = {"overlap": "draw a drop shadow with ctx.text's `shadow` option instead of drawing the text twice; "
                          "otherwise move one of the texts",
               "safe": "keep readable text inside ctx.safe", "clip": "keep the text box inside the surface",
               "small_text": "make the text larger (>= 22 px at 1080p; pixel fonts at integer scales)"}
        out.setdefault(name, []).append({"shot": q.get("shot"), "target": "scene", "severity": 1,
                                         "issue": f"layout QA at {q.get('t')}s: {q.get('msg')}",
                                         "fix": fix.get(str(q.get("kind")), "fix the text layout")})
    return out


def _apply_notes(r: _Run, base: Version) -> Version | None:
    """User revision notes -> a film patch (+ scene patches) -> realise."""
    base.n = 0
    r.emit("revise", "Applying your notes to the film (as a patch)", 0.1)
    facts = pm.facts(r.parent_prom, base.film) if r.parent_prom is not None else None
    instr, text = prompts.revise_patch_prompt(r.brief, r.catalog, r.treatment, base.film, base.plan, [],
                                              r.brief.notes, max_custom=r.budget.max_custom, facts=facts)
    res = _structured_patch(r, "revise-notes", instr, text, base)
    if res is None:
        return None
    v = Version(1, copy.deepcopy(base.film), copy.deepcopy(base.plan), dict(base.scenes), dict(base.fallbacks),
                stable=dict(base.scenes), origin="notes")
    recode: list[str] = []
    _adopt(r, base, v, res, recode)
    notes = {str(n.get("name")): str(n.get("notes")) for n in res[2].get("scene_notes") or []
             if isinstance(n, dict) and n.get("name")}
    recode += [n for n in notes if n in v.customs and n not in recode]
    if not _realise(r, v, code=recode, issues={n: [{"shot": "film", "target": "scene", "severity": 2,
                                                     "issue": "user notes", "fix": r.brief.notes}] for n in recode},
                    notes=notes):
        return None
    return v


# ------------------------------------------------------------------------------------ per-shot best-of

def _timeline(film: dict[str, Any]) -> list[tuple[str, float, float]]:
    return [(s["id"], round(float(s["t0"]), 3), round(float(s["t1"]), 3)) for s in film.get("shots") or []]


def shot_groups(versions: list[Version]) -> list[set[str]]:
    """Shot ids that must move together: shots sharing a custom scene (in any version) form one group."""
    ids = [s["id"] for s in versions[0].film["shots"]]
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for v in versions:
        by_scene: dict[str, list[str]] = {}
        for s in v.film["shots"]:
            if str(s["scene"]).startswith("custom:") and s["id"] in parent:
                by_scene.setdefault(s["scene"], []).append(s["id"])
        for members in by_scene.values():
            for m in members[1:]:
                parent[find(m)] = find(members[0])
    groups: dict[str, set[str]] = {}
    for i in ids:
        groups.setdefault(find(i), set()).add(i)
    return list(groups.values())


def merge_versions(versions: list[Version], n: int) -> tuple[Version, list[str]] | None:
    """Per-shot best-of: start from the best whole version and take every shot group from the version whose
    critic scored that group highest (by >= MERGE_MARGIN). Only versions with the same timeline merge.
    Returns (merged version, what was taken) or None when the best version is already the best everywhere."""
    scored = [v for v in versions if v.score is not None and v.shot_scores()]
    if len(scored) < 2:
        return None
    base = max(scored, key=Version.key)
    same = [v for v in scored if _timeline(v.film) == _timeline(base.film)]
    if len(same) < 2:
        return None
    groups = shot_groups(same)
    film, plan = copy.deepcopy(base.film), copy.deepcopy(base.plan)
    scenes, fallbacks = dict(base.scenes), dict(base.fallbacks)
    specs = {c["name"]: c for c in plan.get("custom_scenes") or []}
    taken: list[str] = []
    for g in groups:
        def gscore(v: Version, g: set[str] = g) -> float | None:
            sc = v.shot_scores()
            vals = [sc[s] for s in g if s in sc]
            return sum(vals) / len(vals) if vals else None
        b = gscore(base)
        best_v, best_s = base, b
        for v in same:
            s = gscore(v)
            if v is base or s is None or b is None:
                continue
            if s >= b + MERGE_MARGIN and (best_s is None or s > best_s):
                best_v, best_s = v, s
        if best_v is base or best_s is None or b is None:
            continue
        donor = {s["id"]: s for s in best_v.film["shots"]}
        dplan = {p["id"]: p for p in best_v.plan.get("shots") or []}
        for i, s in enumerate(film["shots"]):
            if s["id"] in g:
                film["shots"][i] = copy.deepcopy(donor[s["id"]])
        plan["shots"] = [copy.deepcopy(dplan[p["id"]]) if p["id"] in g and p["id"] in dplan else p
                         for p in plan.get("shots") or []]
        for s in film["shots"]:
            if s["id"] in g and str(s["scene"]).startswith("custom:"):
                name = s["scene"].split(":", 1)[1]
                if name in best_v.scenes:
                    scenes[name] = best_v.scenes[name]
                if name in best_v.customs:
                    specs[name] = copy.deepcopy(best_v.customs[name])
        taken.append(f"{'/'.join(sorted(g))} from v{best_v.n} ({best_s:.1f} vs {b:.1f})")
    if not taken:
        return None
    used = {s["scene"].split(":", 1)[1] for s in film["shots"] if str(s["scene"]).startswith("custom:")}
    used |= {o["scene"].split(":", 1)[1] for o in film.get("overlays") or [] if str(o["scene"]).startswith("custom:")}
    plan["custom_scenes"] = [specs[nm] for nm in specs if nm in used]
    scenes = {k: c for k, c in scenes.items() if k in used}
    fallbacks = {k: f for k, f in fallbacks.items() if k not in used}
    if any(v.film == film and v.scenes == scenes for v in versions):
        return None
    mv = Version(n, film, plan, scenes, fallbacks, stable=dict(scenes), origin="merge")
    mv.changes = [f"per-shot best-of: {t}" for t in taken]
    return mv, taken


def _merge_best(r: _Run) -> Version | None:
    """Assemble the best version of every shot, render what changed and verify it with one critic pass."""
    best = max((v for v in r.versions if v.score), key=Version.key, default=None)
    if best is None or (best.score and best.score.passed):
        return None
    res = merge_versions(r.versions, max(v.n for v in r.versions) + 1)
    if res is None:
        return None
    mv, taken = res
    r.emit("merge", f"Per-shot best-of v{mv.n}: " + "; ".join(taken)[:240])
    if r.ledger.remaining < 1:
        r.warn("merge", "No model calls left to verify the merged version; keeping the best whole version")
        return None
    if not _dry_run(r, mv):
        r.warn("merge", "The merged version did not render; keeping the best whole version")
        return None
    _measure(r, mv)
    score = _critique(r, mv, len(r.versions) + 1)
    if score is None:
        return None
    r.emit("merge", f"Merged v{mv.n}: {score.mean:.1f} (min {score.min:g}) vs best whole v{best.n} "
                    f"{best.score.mean if best.score else 0:.1f}")
    return mv


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


def _save_frames(r: _Run, v: Version) -> None:
    """Keyframe index with fingerprints (+ the measurement captures) so a later revise reuses unchanged frames."""
    rows = []
    mdir = r.ddir / f"v{v.n}" / "keyframes-mask"
    masks = v.mask_images if len(v.mask_images) == len(v.frames) else []
    for i, f in enumerate(v.frames):
        row = {**f.to_dict(), "fp": frame_fingerprint(v, f.t)}
        if masks:
            mdir.mkdir(parents=True, exist_ok=True)
            mp = mdir / f"{f.cell:02d}-{f.shot}.png"
            mp.write_bytes(masks[i])
            row["mask"] = str(mp)
        rows.append(row)
    r.save(f"v{v.n}/frames.json", rows)


def _load_parent_frames(r: _Run, vdir: Path) -> None:
    """Seed the keyframe cache (and the 'before' measurement) from the film being revised."""
    try:
        rows = json.loads((vdir / "frames.json").read_text(encoding="utf-8"))
        for row in rows:
            img = Path(row.get("path") or "")
            mask = Path(row["mask"]) if row.get("mask") else None
            if img.is_file():
                r.frame_cache[row["fp"]] = (img.read_bytes(), mask.read_bytes() if mask and mask.is_file() else None)
    except (OSError, ValueError, KeyError):
        pass
    try:
        data = json.loads((vdir / "prominence.json").read_text(encoding="utf-8"))
        s = data["summary"]
        r.parent_prom = pm.Prominence(float(s["visible_share"]), float(s["hero_share"]), dict(s["per_shot"]),
                                      s.get("hook_visible"))
    except (OSError, ValueError, KeyError, TypeError):
        r.parent_prom = None


def _narrate(r: _Run, best: Version) -> list[dict[str, Any]]:
    """Speak the best version's voiceover lines (when Hermes TTS is available) into ``film["narration"]``."""
    lines = [v for v in best.plan.get("voiceover") or [] if isinstance(v, dict)]
    if not lines:
        return []
    if r.dispatch is None:
        r.warn("voice", f"{len(lines)} narration line(s) planned but no text_to_speech tool: no voice")
        return []
    from .voice import film_pace, synthesize
    speed = film_pace(r.treatment, lines, r.voice_speed)
    r.emit("voice", f"Recording {len(lines)} narration line(s) at pace x{speed:g}")
    out, warns = synthesize(lines, dispatch=r.dispatch, out_dir=r.ddir / "voice", dur=float(best.film["dur"]),
                            pace=lambda _t: speed)
    for w in warns:
        r.warn("voice", w)
    return out


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
    narration = _narrate(r, best)
    film = dict(best.film)
    if narration:
        film["narration"] = narration
    look = style_render(film)
    if look and not (film.get("render") or {}).get("post"):
        film["render"] = look                 # e.g. terminal's CRT: Quick films get it from kit.json, so do these
        r.emit("final", f"Style post chain from the film's main kit: {look.get('post')}")
    film_path = r.job_dir / "film.json"
    film_path.write_text(json.dumps(film, indent=1, ensure_ascii=False), encoding="utf-8")
    saved = _save_library(r, best) if save_library and r.library_dir else []
    _save_state(r, best)
    scores = [v.score for v in r.versions if v.score]
    passed = bool(best.score and best.score.passed)
    scenes = {n: "ok" for n in best.scenes}
    scenes.update({n: f"fallback:{k}" for n, k in best.fallbacks.items()})
    msg = (f"Final: v{best.n}" + (f" ({best.origin})" if best.origin != "script" else "")
           + (f", score {best.score.mean:.1f} (min {best.score.min:g})" if best.score else ", not critiqued")
           + (" - passes the bar" if passed else ""))
    r.emit("done", msg, 1.0)
    files = {f"custom:{n}": str(r.ddir / f"v{best.n}" / "scenes" / f"{n}.js") for n in best.scenes}
    res = DirectorResult(True, "done", str(r.job_dir), film=film, film_path=str(film_path),
                         page_dir=str(r.page_dir), scene_files=files, treatment=r.treatment, version=best.n,
                         scores=scores, passed_bar=passed, scenes=scenes, library_saved=saved,
                         usage=r.ledger.totals(), seconds=round(time.monotonic() - t0, 1), log=r.log,
                         measured=best.prom.to_dict() if best.prom else {}, narration=narration,
                         tier={**r.tier.to_dict(), "path": r.path})
    r.save("result.json", {k: v for k, v in res.to_dict().items() if k != "log"})
    return res


def style_render(film: dict[str, Any], kits_root: Path | None = None) -> dict[str, Any]:
    """The `render` block (post chain) of the kit that fills most of the film's runtime, if that kit has one."""
    root = kits_root or Path(__file__).resolve().parents[2] / "kits"
    secs: dict[str, float] = {}
    for s in film.get("shots") or []:
        sc = str(s.get("scene", ""))
        if sc.startswith("kit:"):
            k = sc.split(":", 1)[1].split("/")[0]
            secs[k] = secs.get(k, 0.0) + float(s["t1"]) - float(s["t0"])
    if not secs:
        return {}
    kit, t = max(secs.items(), key=lambda x: x[1])
    if t < 0.6 * float(film.get("dur") or 1.0):
        return {}
    try:
        kj = json.loads((root / kit / "kit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rend = kj.get("render") if isinstance(kj.get("render"), dict) else {}
    return copy.deepcopy(rend) if rend.get("post") else {}


def _save_state(r: _Run, best: Version) -> None:
    r.save("state.json", {"brief": r.brief.to_dict(), "treatment": r.treatment, "best": best.n,
                          "tier": {**r.tier.to_dict(), "path": r.path},
                          "title": best.film.get("title", ""),
                          "versions": [{"n": v.n, "origin": v.origin, "score": v.score.to_dict() if v.score else None,
                                        "shots": v.shot_scores(), "measured": v.prom.to_dict() if v.prom else None,
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
