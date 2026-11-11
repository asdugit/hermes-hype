"""Pipeline hook: one call (``install(run)``, in ``pipeline._run`` before the Quick front half) wires a job's
customization into the stages by wrapping ``run.deps`` (no other pipeline edits):

* before narration: knobs + the request's words (keyword reader, no model) set the narration pace (energy,
  voice style, ``voice_speed``), language and the storyboard brief; ``deps.tts`` gets the voice style
  (Hermes ``text_to_speech`` ``instructions``; the Edge dev route also honours ``voice``/``pitch``/``volume``).
* ``deps.quick_film``: builds the plain preset film, asks the model for the customization spec once per job
  (``customize.json``, reused by the second aspect and by re-renders/revisions of the job), applies the
  structural edits to the Timeline (so narration/captions/cues follow) and the look to the film.
* ``deps.pick_bed``: the chosen bed (or none).
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from . import apply as A
from . import command as C
from . import knobs as K
from . import spec as S
from . import vocab as V
from .llm import customize_spec

log = logging.getLogger(__name__)
SPEC_FILE = "customize.json"


def settings_knobs() -> dict[str, Any]:
    """Knob defaults from the plugin setting ``customize`` (``plugins.entries.auteur.settings.customize``)."""
    try:
        import yaml  # Hermes core dependency
        from hermes_constants import get_hermes_home  # public, lazy
        raw = yaml.safe_load((Path(get_hermes_home()) / "config.yaml").read_text(encoding="utf-8")) or {}
        entry = ((raw.get("plugins") or {}).get("entries") or {}).get("auteur") or {}
        values = entry.get("settings") or entry.get("config") or {}
        return K.from_settings(values.get("customize")) if isinstance(values, dict) else {}
    except Exception:  # noqa: BLE001 - outside Hermes / unreadable config: no defaults
        return {}


def _info(run: Any, msg: str, **extra: Any) -> None:
    try:
        run.info(msg, **extra)
    except Exception:  # noqa: BLE001
        log.info("auteur customize: %s", msg)


def resolve(run: Any) -> dict[str, Any] | None:
    """The job's customization: ``{"knobs": normalised, "text", "preset", "floor": keyword spec}`` or None."""
    c = C.get(run.opts)
    defaults = settings_knobs()
    if not c and not defaults:
        return None
    dclean, _ = K.normalise(defaults, style=run.opts.style)
    knobs = {**dclean, **(c.get("knobs") or {})}
    text = str(c.get("text") or "")
    if c.get("route") == "directed" and run.opts.directed:
        return None                    # the Director has them as hints; Quick fallback re-enters here undirected
    if not knobs and not text:
        return None
    floor = S.keywords(text, None, style=run.opts.style) if text else {}
    return {"knobs": knobs, "text": text, "preset": run.opts.style, "floor": floor, "defaults": bool(dclean)}


def _voice_plan(run: Any, cz: dict[str, Any]) -> dict[str, Any]:
    from ..config import voice_speed
    knobs, floor = cz["knobs"], cz["floor"]
    style = str(knobs.get("voice") or (floor.get("voice") or {}).get("style") or "")
    plan: dict[str, Any] = {}
    if style in V.VOICE_STYLES:
        plan.update(V.VOICE_STYLES[style])
        plan["style"] = style
    elif style:
        plan["voice"] = style                       # an Edge voice name (dev route; Hermes uses its tts config)
    lang = str(knobs.get("language") or "")
    if lang and lang != "en":
        plan["voice"] = plan.get("voice") or V.LANGUAGES[lang][2]
        plan["language"] = lang
    energy = str(knobs.get("energy") or floor.get("energy") or "")
    if run.opts.voice_speed is None and "voice_speed" not in knobs:
        mult = V.ENERGY_VOICE.get(energy, 1.0) * float(plan.get("speed") or 1.0)
        if abs(mult - 1.0) > 1e-3:
            run.opts.voice_speed = round(voice_speed(run.opts.style, None) * mult, 3)
    plan["energy"] = energy
    return plan


def _wrap_dispatch(dispatch: Any, plan: dict[str, Any]) -> Any:
    extra: dict[str, Any] = {}
    if plan.get("instructions"):
        extra["instructions"] = plan["instructions"]
    if plan.get("voice"):
        extra["voice"] = plan["voice"]
    for k, v in (plan.get("edge") or {}).items():
        extra[k] = v
    if not extra or dispatch is None:
        return dispatch

    def call(name: str, args: dict[str, Any], **kw: Any) -> Any:
        if name == "text_to_speech":
            args = {**extra, **args}
        return dispatch(name, args, **kw)
    return call


def install(run: Any) -> dict[str, Any] | None:
    """Wire the job's customization into ``run`` (deps wrappers + options). Never raises; returns the plan."""
    try:
        return _install(run)
    except Exception as exc:  # noqa: BLE001 - a broken customization must never cost the film
        log.exception("auteur customize install failed")
        try:
            run.warn(f"customization could not be applied ({type(exc).__name__}: {exc}); made the plain preset")
        except Exception:  # noqa: BLE001
            pass
        return None


def _install(run: Any) -> dict[str, Any] | None:
    cz = resolve(run)
    if cz is None:
        return None
    knobs = cz["knobs"]
    if cz["defaults"]:
        C.apply_knobs(run.opts, {k: v for k, v in knobs.items() if k not in (C.get(run.opts).get("knobs") or {})})
    # storyboard: the request and the language reach the writer (tone/wording; facts stay facts)
    notes = []
    if cz["text"]:
        notes.append(f"Customization of the {run.opts.style} preset requested by the user (apply it to the tone and "
                     f"wording of narration and on-screen words; keep every fact): {cz['text'][:400]}")
    for k in ("title", "tagline", "cta"):
        if knobs.get(k):
            notes.append(f"Use exactly this {k}: {knobs[k]!r}.")
    if knobs.get("language") and knobs["language"] != "en":
        name = V.LANGUAGES[knobs["language"]][1]
        notes.append(f"Write every narration line and every on-screen word in {name}.")
    if str(knobs.get("energy") or cz["floor"].get("energy") or "") == "high":
        # high energy = more, faster cuts and SHORTER lines; the voice is never sped up (stays <= ~185 wpm)
        notes.append("High energy: keep every narration line short and punchy (about 5-9 words); never longer lines.")
    if notes:
        run.opts.notes = " ".join([run.opts.notes] + notes).strip() if run.opts.notes else " ".join(notes)
    plan = _voice_plan(run, cz)
    deps = copy.copy(run.deps)
    orig_tts, orig_quick, orig_bed = deps.tts, deps.quick_film, deps.pick_bed
    if plan.get("instructions") or plan.get("voice") or plan.get("edge"):
        def tts(dispatch: Any, text: str, out_path: Path, speed: float | None = None) -> Any:
            return orig_tts(_wrap_dispatch(dispatch, plan), text, out_path, speed)
        deps.tts = tts
    state: dict[str, Any] = {"spec": None}

    def chosen_bed() -> str:
        sp = state["spec"] or cz["floor"]
        return str(knobs.get("music") or sp.get("music") or "")

    def pick_bed(style: str, seed: int, bed_id: str | None = None) -> Any:
        bed = chosen_bed()
        if bed == "none":
            return None
        return orig_bed(style, seed, bed_id or bed or None)
    deps.pick_bed = pick_bed

    def quick_film(tl: Any, **kw: Any) -> dict[str, Any]:
        style = str(kw.get("style") or run.opts.style)
        if state["spec"] is None:
            state["spec"] = _spec_for(run, cz, tl, orig_quick, kw, style)
        sp = state["spec"]
        energy = str(knobs.get("energy") or sp.get("energy") or "")
        tnotes, idmap = A.apply_timeline(tl, sp, energy=energy)
        for n in tnotes:
            _info(run, f"customize: {n}")
        sp = A.remap(sp, idmap)
        if tnotes:                    # the pipeline wrote the timeline + duration before this hook trimmed/moved shots
            try:
                from ..pipeline import ASPECT_TAG
                tag = ASPECT_TAG.get(str(kw.get("aspect") or ""), "x")
                (Path(run.job_dir) / f"timeline_{tag}.json").write_text(
                    json.dumps(tl.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                run.store.update(run.job_id, duration_s=tl.dur)
            except Exception:  # noqa: BLE001 - bookkeeping only
                pass
        made = orig_quick(tl, **kw)
        film = made["film"]
        from ..film.quick import kit_meta
        kit = kit_meta(style)
        assets = made.setdefault("assets", {})
        notes = A.apply_film(film, assets, style=style, knobs=knobs, spec=sp, wrapped=kit.get("params") == "wrapped",
                             kit=kit)
        for n in notes:
            _info(run, f"customize: {n}")
        return made
    deps.quick_film = quick_film
    run.deps = deps
    _info(run, "customizing the preset: " + (C.summary(run.opts) or "settings defaults"), customize=C.get(run.opts))
    return {"plan": plan, "knobs": knobs, "text": cz["text"]}


def _parent_spec(run: Any, text: str) -> dict[str, Any] | None:
    parent = str((run.job or {}).get("parent") or "")
    if not parent:
        return None
    try:
        data = json.loads((run.store.job_dir(parent) / SPEC_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return data.get("spec") if data.get("text") == text and isinstance(data.get("spec"), dict) else None


def _spec_for(run: Any, cz: dict[str, Any], tl: Any, orig_quick: Any, kw: dict[str, Any], style: str) -> dict[str, Any]:
    """The customization spec for this job (model call once; cached in customize.json)."""
    path = Path(run.job_dir) / SPEC_FILE
    text = cz["text"]
    if not text:
        spec = {}
        record = {"text": "", "spec": spec, "source": "knobs"}
    else:
        reused = _parent_spec(run, text)
        if reused is not None:
            spec, record = reused, {"text": text, "spec": reused, "source": "reused"}
            _info(run, "customization reused from the parent job (no model call)")
        else:
            plain = orig_quick(copy.deepcopy(tl), **kw)
            from ..film.quick import kit_meta
            wrapped = kit_meta(style).get("params") == "wrapped"
            llm_call = None
            try:
                llm_call = run.host.story_call()
            except Exception:  # noqa: BLE001
                llm_call = None
            try:
                run.rep.progress(0.2, "customizing the preset" + (" (model)" if llm_call else ""))
            except Exception:  # noqa: BLE001
                pass
            res = customize_spec(text, plain["film"], style=style, llm_call=llm_call, wrapped=wrapped,
                                 log=lambda m: _info(run, m))
            spec = res["spec"]
            record = {"text": text, **{k: v for k, v in res.items() if k != "raw"}, "raw": res.get("raw")}
            if res.get("error"):
                run.warn(f"customization model reply unusable ({res['error']}); used the request's words")
            if spec.get("restructure"):
                run.warn("this request goes beyond the preset; for a different film run it without naming a preset "
                         "(or add 'directed') and the Director makes it")
            _info(run, f"customization ({res['source']}, {res['seconds']}s): {S.describe(spec)}",
                  customize_source=res["source"])
    record["knobs"] = cz["knobs"]
    try:
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        knob_bits = ", ".join(f"{k}={v}" for k, v in cz["knobs"].items())
        summary = "; ".join(x for x in ((f"knobs {knob_bits}" if knob_bits else ""),
                                        (S.describe(spec) if spec else "")) if x) or "no changes"
        run.store.update(run.job_id, customize={"summary": summary, "source": record.get("source"),
                                                "text": text, "knobs": cz["knobs"]})
    except Exception:  # noqa: BLE001
        pass
    return spec
