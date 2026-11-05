"""Director engine end to end with a scripted model and a scripted runtime."""
from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from director_fakes import (
    BUGGY_CODE,
    FILM,
    GOOD_CODE,
    LOW_ISSUES,
    RANDOM_CODE,
    TREATMENT,
    FakeLlm,
    FakeRenderer,
    critique,
    fenced,
    revised_film,
)

from showreel_core.director import EFFORTS, Budget, run
from showreel_core.director.engine import revise


def _run(env: dict[str, Any], llm: Any, renderer: Any = None, **kw: Any) -> Any:
    events: list[dict[str, Any]] = []

    def progress(**ev: Any) -> None:
        events.append(ev)
    kw.setdefault("effort", "standard")
    res = run(env["brief"], llm=llm, renderer=renderer or FakeRenderer(), progress=progress, job_dir=env["job"],
              library_dir=env["library"], catalog=env["catalog"], **kw)
    res.events = events  # type: ignore[attr-defined]
    return res


def _notes(res: Any) -> list[str]:
    return [e["note"] for e in res.events]


def test_full_loop_repair_critique_revise_pass(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM],
                   "scene": [fenced(BUGGY_CODE), fenced(GOOD_CODE), fenced(GOOD_CODE)],
                   "critic": [critique(6.0, LOW_ISSUES), critique(8.5)], "revise-film": [revised_film()]})
    rend = FakeRenderer()
    res = _run(env, llm, rend)
    assert res.ok and res.status == "done", res.error
    assert llm.purposes() == ["treatment", "film", "scene:boss-battle", "scene:boss-battle", "critic:r1",
                              "revise-film", "scene:boss-battle", "critic:r2"]
    assert [s.mean for s in res.scores] == [6.0, 8.5]
    assert res.passed_bar and res.version == 2
    assert res.scenes == {"boss-battle": "ok"}
    assert res.library_saved == ["lib:boss-battle"]
    lib = env["library"] / "boss-battle"
    assert "sr.defineScene('lib:boss-battle'" in (lib / "scene.js").read_text(encoding="utf-8")
    assert (lib / "thumb.jpg").is_file()
    meta = json.loads((lib / "meta.json").read_text(encoding="utf-8"))
    assert meta["describe"] and meta["params"]["boss_media"]["type"] == "asset"
    # artefacts
    job = Path(res.job_dir)
    film = json.loads((job / "film.json").read_text(encoding="utf-8"))
    assert film["captions"][0]["text"] == "Meet the boss."            # the revision won
    assert film["assets"] == {"car": {"type": "frames"}}
    assert (job / "director" / "treatment.json").is_file()
    assert (job / "director" / "v1" / "critique.json").is_file()
    assert (job / "director" / "v2" / "contact-1.jpg").is_file()
    assert len(list((job / "director" / "calls").glob("*.prompt.md"))) == 8
    assert (job / "page" / "scenes" / "boss-battle.js").read_text(encoding="utf-8") == GOOD_CODE
    # the critic saw images, the dry run repaired with the runtime error text
    critic = next(c for c in llm.calls if c["purpose"] == "critic:r1")
    assert critic["images"] == 1 and critic["schema"]
    repair = llm.calls[3]
    assert "TypeError: boss is undefined" in repair["text"]
    revise_scene = llm.calls[6]
    assert "boss too small" in revise_scene["text"] and "twice as big" in revise_scene["text"]
    notes = _notes(res)
    assert "Writing treatment" in notes and "Coding scene boss-battle" in notes
    assert any(n.startswith("Repairing scene boss-battle") for n in notes)
    assert any(n.startswith("Critic round 1: 6.0 -> fixing 2 issue(s)") for n in notes)
    assert res.usage["calls"] == 8 and res.usage["input_tokens"] == 8000
    assert res.events[-1]["frac"] == 1.0


def test_custom_scenes_are_coded_in_parallel(env: dict[str, Any]) -> None:
    film = json.loads(json.dumps(FILM))
    film["film"]["shots"][2].update(scene="custom:meadow", params={"car": "car"})
    film["plan"]["custom_scenes"].append({"name": "meadow", "layer": "2d", "describe": "cars over a meadow",
                                          "spec": "x" * 300, "params": {"car": {"type": "asset"}}, "kits": []})
    llm = FakeLlm({"treatment": [TREATMENT], "film": [film], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(9.0)]})
    res = _run(env, llm)
    assert res.ok and res.scenes == {"boss-battle": "ok", "meadow": "ok"}
    prompts = sorted(p.name for p in (Path(res.job_dir) / "director" / "calls").glob("*.prompt.md"))
    assert len(prompts) == 5 and len({p[:2] for p in prompts}) == 5          # unique call numbers
    assert (Path(res.job_dir) / "page" / "scenes" / "meadow.js").read_text(encoding="utf-8").count(
        "custom:meadow") == 1


def test_film_is_normalised(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(9.0)]})
    res = _run(env, llm)
    assert res.ok
    f = res.film
    assert f["size"] == [1920, 1080] and f["fps"] == 30 and f["dur"] == 45.0 and f["version"] == 1
    assert [c["sfx"] for c in f["cues"]] == ["hit"]                    # unknown sfx dropped
    assert f["finish"]["vignette"] == 0.6                              # clamped
    assert all(m.get("bed") != "nope_bed" for m in f["music"])
    tr = f["transitions"][0]
    assert tr["t"] <= 20.0 <= tr["t"] + tr["dur"]
    assert llm.purposes().count("critic:r1") == 1 and "revise-film" not in llm.purposes()


def test_scene_that_keeps_throwing_falls_back_to_kit_scene(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(BUGGY_CODE)],
                   "critic": [critique(8.2)]})
    res = _run(env, llm)
    assert res.ok, res.error
    tries = EFFORTS["standard"].scene_tries
    assert llm.purposes().count("scene:boss-battle") == tries
    assert res.scenes == {"boss-battle": "fallback:kit:fake/walk"}
    boss = next(s for s in res.film["shots"] if s["id"] == "boss")
    assert boss["scene"] == "kit:fake/walk" and boss["params"] == {"media": "car"}
    assert res.library_saved == []
    assert any("fallback kit:fake/walk" in n for n in _notes(res))


def test_scene_that_fails_lint_falls_back_without_dry_run_errors(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(RANDOM_CODE)],
                   "critic": [critique(8.0)]})
    rend = FakeRenderer()
    res = _run(env, llm, rend)
    assert res.ok
    assert llm.purposes().count("scene:boss-battle") == EFFORTS["standard"].scene_tries
    assert "Math.random" in llm.calls[3]["text"]                       # the repair quoted the lint error
    assert res.scenes["boss-battle"].startswith("fallback:")
    assert len(rend.builds) == 1                                       # no repair builds were needed


def test_round_limit_quick_effort(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(5.0, LOW_ISSUES)], "revise-film": [revised_film()]})
    rend = FakeRenderer()
    res = _run(env, llm, rend, effort="quick")
    assert res.ok and not res.passed_bar
    assert len(res.scores) == 1 and "revise-film" not in llm.purposes()
    assert len(rend.previews[0]["capture"]) <= 3 + 1 + 1                 # 1 keyframe per shot + transition + hook


def test_best_version_wins_when_revision_scores_lower(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(7.0, LOW_ISSUES), critique(6.0, LOW_ISSUES)],
                   "revise-film": [revised_film()]})
    rend = FakeRenderer()
    res = _run(env, llm, rend)
    assert res.ok and res.version == 1 and [s.mean for s in res.scores] == [7.0, 6.0]
    assert res.film["captions"][0]["text"] == "Every hero has a boss."
    assert rend.builds[-1]["film"]["captions"][0]["text"] == "Every hero has a boss."   # page rebuilt from v1


def test_call_budget_keeps_best_scored_version(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(6.0, LOW_ISSUES)], "revise-film": [revised_film()]})
    budget = replace(EFFORTS["standard"], max_calls=5)
    res = _run(env, llm, budget=budget)
    assert res.ok and res.version == 1 and len(llm.calls) == 5
    assert any("budget" in n for n in _notes(res))


def test_call_budget_before_any_scored_version_fails_to_quick(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(BUGGY_CODE)]})
    res = _run(env, llm, budget=Budget(rounds=2, keyframes_per_shot=3, scene_tries=3, film_repairs=1, max_calls=3))
    assert not res.ok and res.status == "failed" and res.fallback == "quick" and res.quick_style == "pixel"


def test_cancel_during_scene_coding(env: dict[str, Any]) -> None:
    stop = threading.Event()
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(9.0)]})

    def progress(**ev: Any) -> None:
        if ev.get("stage") == "scenes":
            stop.set()
    res = run(env["brief"], llm=llm, renderer=FakeRenderer(), progress=progress, cancel=stop, job_dir=env["job"],
              library_dir=env["library"], catalog=env["catalog"])
    assert res.status == "cancelled" and not res.ok
    assert "critic:r1" not in llm.purposes()


def test_cancel_raised_by_pipeline_progress_is_reported_as_cancelled(env: dict[str, Any]) -> None:
    class Cancelled(Exception):
        pass

    def progress(**ev: Any) -> None:
        if ev.get("stage") == "film":
            raise Cancelled()
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM]})
    res = run(env["brief"], llm=llm, renderer=FakeRenderer(), progress=progress, job_dir=env["job"],
              library_dir=env["library"], catalog=env["catalog"])
    assert res.status == "cancelled"


def test_bad_treatment_falls_back_to_quick_mode(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": ["I would love to help! Here's my idea: a dungeon..."]})
    res = _run(env, llm)
    assert not res.ok and res.fallback == "quick" and res.quick_style == "pixel"
    assert llm.purposes() == ["treatment"] * (1 + EFFORTS["standard"].film_repairs)
    assert "REJECTED" in llm.calls[1]["text"]


def test_film_validation_errors_are_repaired(env: dict[str, Any]) -> None:
    bad = json.loads(json.dumps(FILM))
    bad["film"]["shots"][2]["scene"] = "kit:fake/does-not-exist"
    bad["film"]["shots"][0]["params"].pop("media")
    llm = FakeLlm({"treatment": [TREATMENT], "film": [bad, FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(9.0)]})
    res = _run(env, llm)
    assert res.ok
    repair = llm.calls[2]
    assert "unknown scene `kit:fake/does-not-exist`" in repair["text"]


def test_page_that_never_loads_fails_cleanly(env: dict[str, Any]) -> None:
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)]})
    res = _run(env, llm, FakeRenderer(load_error="window.__sr never appeared"))
    assert not res.ok and res.fallback == "quick"


def test_user_revise_with_notes(env: dict[str, Any]) -> None:
    first = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                     "critic": [critique(8.5)]})
    res1 = _run(env, first)
    assert res1.ok
    second = FakeLlm({"revise-notes": [revised_film()], "scene": [fenced(GOOD_CODE)], "critic": [critique(8.8)]})
    job2 = env["tmp"] / "job2"
    res2 = revise(env["job"], "slower start, bigger boss", llm=second, renderer=FakeRenderer(), job_dir=job2,
                  library_dir=env["library"], catalog=env["catalog"])
    assert res2.ok, res2.error
    assert second.purposes() == ["revise-notes", "scene:boss-battle", "critic:r1"]
    assert "slower start, bigger boss" in second.calls[0]["text"]
    assert "slower start, bigger boss" in second.calls[2]["text"]           # critic checks the notes
    assert (job2 / "film.json").is_file()
    assert res2.library_saved == []                                         # identical code: not saved twice


def test_pipeline_keyword_entry_with_ctx_llm(env: dict[str, Any]) -> None:
    """The orchestrator calls run(direction=..., llm=<ctx.llm>, options=..., ...)."""
    replies = {"showreel.treatment": TREATMENT, "showreel.film": FILM, "showreel.critic:r1": critique(9.0)}

    class Res:
        def __init__(self, text: str, parsed: Any) -> None:
            self.text, self.parsed = text, parsed
            self.content_type = "json" if parsed is not None else "text"
            self.provider, self.model = "fake", "fake-model"
            self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001})()

    class CtxLlm:
        def __init__(self) -> None:
            self.kwargs: list[dict[str, Any]] = []

        def complete_structured(self, **kw: Any) -> Res:
            self.kwargs.append(kw)
            purpose = kw["purpose"]
            if purpose.startswith("showreel.scene"):
                return Res(fenced(GOOD_CODE), None)
            obj = replies[purpose]
            return Res(json.dumps(obj), obj)

    class Opts:
        effort = "quick"
        direction = env["brief"].direction
        seconds = 45
        aspects = ("16:9",)
        notes = ""

    ctx_llm = CtxLlm()
    res = run(direction=env["brief"].direction, llm=ctx_llm, options=Opts(), renderer=FakeRenderer(),
              job_dir=env["job"], library_dir=env["library"], catalog=env["catalog"], seconds=45, aspect="16:9",
              fps=30, size=(1920, 1080), seed=3, product=env["brief"].product, assets=[env["car"]],
              progress=lambda stage="", frac=0.0, note="", **_: None)
    assert res.ok, res.error
    assert res.film["seed"] == 3
    critic = next(k for k in ctx_llm.kwargs if k["purpose"] == "showreel.critic:r1")
    assert critic["task"] == "showreel" and critic["input"][1]["type"] == "image"
    assert critic["input"][1]["mime_type"] == "image/jpeg" and isinstance(critic["input"][1]["data"], bytes)
    scene = next(k for k in ctx_llm.kwargs if k["purpose"].startswith("showreel.scene"))
    assert "json_schema" not in scene
    assert res.usage["cost_usd"] == round(0.001 * len(ctx_llm.kwargs), 4)
