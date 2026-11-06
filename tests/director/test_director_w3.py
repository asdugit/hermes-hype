"""Wave-3 Director features: recipes, measured product prominence, patch revisions, keyframe reuse, per-shot
best-of, narration."""
from __future__ import annotations

import copy
import io
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from director_fakes import (
    FILM,
    GOOD_CODE,
    LOW_ISSUES,
    TREATMENT,
    FakeLlm,
    FakeRenderer,
    boxed,
    critique,
    fenced,
    png,
)

from showreel_core.director import prominence as pm
from showreel_core.director import recipes, run
from showreel_core.director.checks import check_film, check_voiceover
from showreel_core.director.engine import Version, merge_versions, revise, shot_groups
from showreel_core.director.patches import apply_blocks, apply_film_patch, parse_blocks
from showreel_core.director.types import RoundScore


def _run(env: dict[str, Any], llm: Any, renderer: Any = None, **kw: Any) -> Any:
    kw.setdefault("effort", "standard")
    return run(env["brief"], llm=llm, renderer=renderer or FakeRenderer(), job_dir=env["job"],
               library_dir=env["library"], catalog=env["catalog"], **kw)


def _scores(shots: dict[str, float], mean: float = 6.0, issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    c = critique(mean, issues if issues is not None else LOW_ISSUES)
    c["shots"] = [{"id": k, "score": v} for k, v in shots.items()]
    return c


# ------------------------------------------------------------------------------------ recipes

def test_recipes_are_kit_first_and_lay_out_on_the_film() -> None:
    ids = [r.id for r in recipes.RECIPES]
    assert {"boss-battle", "race-chase", "item-get", "heist", "origin-story", "day-in-the-life", "before-after",
            "speedrun", "nature-documentary"} <= set(ids)
    for r in recipes.RECIPES:
        shares = [s.share for s in r.shots]
        assert shares[0][0] == 0.0 and shares[-1][1] == 1.0, r.id
        assert all(a[1] == b[0] for a, b in itertools.pairwise(shares)), r.id        # back to back
        customs = [s for s in r.shots if s.scene.startswith("custom:")]
        assert not customs or r.custom_gap, f"{r.id}: custom scenes only for a named gap"
    tpl = recipes.template(recipes.get("boss-battle"), seconds=45, product="car", name="Red Car", cta="Buy")
    boss = next(s for s in tpl["shots"] if s["id"] == "boss")
    assert boss["params"]["boss_media"] == "car" and boss["params"]["boss_name"] == "RED CAR"
    assert tpl["shots"][-1]["t1"] == 45.0
    assert any(t["type"] == "kit:pixel/petal-bloom" for t in tpl["transitions"])
    assert recipes.suggest("make it feel like a nature documentary", physical=False)[0] == "nature-documentary"


def test_treatment_and_film_prompts_carry_recipes(env: dict[str, Any]) -> None:
    from showreel_core.director import prompts
    _instr, text = prompts.treatment_prompt(env["brief"], env["catalog"])
    assert "Narrative recipes" in text and "`boss-battle`" in text
    _instr, text = prompts.film_prompt(env["brief"], env["catalog"], dict(TREATMENT, recipe="boss-battle"),
                                       max_custom=2)
    assert "Chosen recipe: `boss-battle`" in text and '"boss_media": "car"' in text
    assert "PRODUCT SIZE" in _instr


# ------------------------------------------------------------------------------------ patches

def test_film_patch_touches_only_named_shots() -> None:
    film, plan = copy.deepcopy(FILM["film"]), copy.deepcopy(FILM["plan"])
    patch = {"shots": [{"id": "field", "params": {"time": "pastel", "flyers": [{"media": "car", "path": "hero"}]}},
                       {"id": "walk", "params": {"media": None}}],
             "captions": [{"t0": 1, "t1": 3, "text": "Meet the boss."}], "changes": ["pinker"]}
    f2, _p2, errors, touched = apply_film_patch(film, plan, patch)
    assert not errors and set(touched) == {"field", "walk"}
    field = next(s for s in f2["shots"] if s["id"] == "field")
    assert field["params"] == {"time": "pastel", "flyers": [{"media": "car", "path": "hero"}]}
    walk = next(s for s in f2["shots"] if s["id"] == "walk")
    assert "media" not in walk["params"] and walk["params"]["party"] == ["knight", "mage"]
    assert next(s for s in f2["shots"] if s["id"] == "boss") == next(s for s in film["shots"] if s["id"] == "boss")
    assert f2["captions"][0]["text"] == "Meet the boss." and f2["transitions"] == film["transitions"]
    _f3, _p3, errors, _ = apply_film_patch(film, plan, {"shots": [{"id": "new"}]})
    assert errors and "needs" in errors[0]


def test_search_replace_blocks_apply_exactly_or_report() -> None:
    reply = ("Bigger boss.\n<<<<<<< SEARCH\n  render(ctx, t, p) { const g = ctx.g;\n=======\n"
             "  render(ctx, t, p) { const g = ctx.g; /*BIG*/\n>>>>>>> REPLACE\n")
    blocks = parse_blocks(reply)
    assert len(blocks) == 1
    code, failures = apply_blocks(GOOD_CODE, blocks)
    assert not failures and "/*BIG*/" in code and code.replace(" /*BIG*/", "") == GOOD_CODE
    # indentation drift still applies; a missing anchor is reported, nothing changes
    code2, failures = apply_blocks(GOOD_CODE, [("render(ctx, t, p) { const g = ctx.g;", "X")])
    assert not failures and "X" in code2
    code3, failures = apply_blocks(GOOD_CODE, [("no such line", "X")])
    assert failures and code3 == GOOD_CODE


# ------------------------------------------------------------------------------------ measurement

def test_measure_finds_the_product_box() -> None:
    base = png((40, 60, 90), (960, 540))
    vis, w, _h, _area, bbox, regions = pm.measure(base, boxed(base, 0.4))
    assert vis and abs(w - 0.4) < 0.02 and regions == 1 and bbox is not None
    vis, w, *_ = pm.measure(base, base)
    assert not vis and w == 0.0


def test_flip_and_mirror_never_touch_the_real_page(tmp_path: Path) -> None:
    from PIL import Image
    page = tmp_path / "page"
    (page / "assets" / "car" / "cutout").mkdir(parents=True)
    (page / "stage.html").write_text("x", encoding="utf-8")
    Image.new("RGB", (8, 8), (200, 30, 30)).save(page / "assets" / "car" / "000001.jpg")
    Image.new("RGBA", (8, 8), (200, 30, 30, 0)).save(page / "assets" / "car" / "cutout" / "000001.png")
    flipped = pm.flipped_assets(page, ["car"], tmp_path / "cache")
    mask = pm.mirror_page(page, tmp_path / "mask", flipped)
    real = Image.open(page / "assets" / "car" / "000001.jpg").convert("RGB").getpixel((4, 4))
    flip = Image.open(mask / "assets" / "car" / "000001.jpg").convert("RGB").getpixel((4, 4))
    assert abs(real[0] - 200) < 8 and abs(flip[0] - (200 ^ 0x80)) < 8
    assert Image.open(mask / "assets" / "car" / "cutout" / "000001.png").getpixel((4, 4))[3] == 0   # alpha kept
    assert (mask / "stage.html").read_text(encoding="utf-8") == "x"


def test_static_check_and_bump_for_nature_flyers() -> None:
    shot = {"id": "field", "t0": 0, "t1": 10, "scene": "kit:nature/flower-field",
            "params": {"product": "car", "count": 4}}
    est = pm.estimate_width(shot, "16:9")
    assert est is not None and 0.2 < est < 0.3                         # the descend flyer is the largest
    shot["params"] = {"flyers": [{"media": "car", "path": "rise"}, {"media": "car", "path": "arc"}]}
    assert pm.estimate_width(shot, "16:9") < 0.1
    what = pm.bump(shot, 3.0)
    assert "flyer sizes" in what and pm.estimate_width(shot, "16:9") > 0.18
    plan = {"shots": [{"id": "field", "product_visible": True}]}
    film = {"shots": [{"id": "field", "scene": "kit:nature/flower-field", "params": {"time": "sunset"}}]}
    errors, _ = pm.static_check(film, plan, {"car"}, "16:9")
    assert errors and "never reference the product" in errors[0]
    s2 = {"id": "x", "scene": "kit:any/thing", "params": {"product_scale": 1.0}}
    assert pm.bump(s2, 1.5, ["product_scale"]) and s2["params"]["product_scale"] == 1.5


def test_measured_small_product_is_repaired_before_the_critic(env: dict[str, Any]) -> None:
    """The boss (custom scene) draws the car at 8 %: the engine patches the scene before any critique."""
    def width(shot: dict[str, Any], page: Path) -> float:
        if shot["id"] != "boss":
            return 0.45
        return 0.5 if "/*BIG*/" in (page / "scenes" / "boss-battle.js").read_text(encoding="utf-8") else 0.08
    patch = ("<<<<<<< SEARCH\n  render(ctx, t, p) { const g = ctx.g;\n=======\n"
             "  render(ctx, t, p) { const g = ctx.g; /*BIG*/\n>>>>>>> REPLACE")
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE), patch],
                   "critic": [critique(9.0)]})
    rend = FakeRenderer(product_width=width)
    res = _run(env, llm, rend)
    assert res.ok and res.passed_bar
    purposes = llm.purposes()
    assert purposes == ["treatment", "film", "scene:boss-battle", "scene:boss-battle", "critic:r1"]
    fix = llm.calls[3]
    assert "MEASURED: the product spans only 8%" in fix["text"] and "SEARCH" in fix["instructions"]
    assert "/*BIG*/" in (Path(res.job_dir) / "page" / "scenes" / "boss-battle.js").read_text(encoding="utf-8")
    assert res.measured["per_shot"]["boss"]["max_width"] >= 0.45
    critic = next(c for c in llm.calls if c["purpose"] == "critic:r1")
    assert "MEASURED (pixel-exact)" in critic["text"]
    # only the boss keyframes were rendered again
    second = rend.previews[1]
    assert second["capture"] and all(6 <= t < 20 or 19 <= t <= 21 for t in second["capture"])


# ------------------------------------------------------------------------------------ revisions

def test_patch_revision_rerenders_only_changed_shots(env: dict[str, Any]) -> None:
    patch = {"changes": ["field pinker"], "shots": [{"id": "field", "params": {"time": "pastel"}}]}
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [critique(6.0, [{"shot": "field", "target": "film", "severity": 2,
                                              "issue": "too orange", "fix": "time pastel"}]), critique(8.5)],
                   "revise-film": [patch]})
    rend = FakeRenderer()
    res = _run(env, llm, rend)
    assert res.ok and res.version == 2
    assert llm.purposes() == ["treatment", "film", "scene:boss-battle", "critic:r1", "revise-film", "critic:r2"]
    rev = next(c for c in llm.calls if c["purpose"] == "revise-film")
    assert "ANSWER WITH A PATCH" in rev["instructions"]
    v1 = json.loads((Path(res.job_dir) / "director" / "v1" / "film.json").read_text(encoding="utf-8"))
    v2 = json.loads((Path(res.job_dir) / "director" / "v2" / "film.json").read_text(encoding="utf-8"))
    changed = [a["id"] for a, b in zip(v1["shots"], v2["shots"], strict=False) if a != b]
    assert changed == ["field"] and v2["shots"][2]["params"]["time"] == "pastel"
    last = rend.previews[-1]
    assert last["capture"] and all(t >= 19.0 for t in last["capture"])     # field (+ its transition) only
    assert all(t >= 19.0 for t in last["probe"])


def test_user_notes_revise_as_patch_with_before_measurements(env: dict[str, Any]) -> None:
    first = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                     "critic": [critique(8.5)]})
    res1 = _run(env, first, FakeRenderer(product_width=lambda s, p: 0.2 if s["id"] == "field" else 0.45))
    assert res1.ok
    patch = {"changes": ["bigger cars"], "shots": [{"id": "field", "params": {"flyers": [
        {"media": "car", "path": "hero", "size": 10}]}}]}
    second = FakeLlm({"revise-notes": [patch], "critic": [critique(8.8)]})
    rend = FakeRenderer(product_width=lambda s, p: 0.5 if s["id"] == "field" else 0.45)
    res2 = revise(env["job"], "make the field pinker and the cars bigger", llm=second, renderer=rend,
                  job_dir=env["tmp"] / "job2", library_dir=env["library"], catalog=env["catalog"])
    assert res2.ok, res2.error
    assert second.purposes() == ["revise-notes", "critic:r1"]                # no scene code was touched
    crit = second.calls[1]["text"]
    assert "MEASURED before the user's notes" in crit and "field 20%" in crit and "field 50%" in crit
    assert all(t >= 19.0 for t in rend.previews[0]["capture"])            # parent keyframes were reused


# ------------------------------------------------------------------------------------ per-shot best-of

def _v(n: int, film: dict[str, Any], shots: dict[str, float], mean: float) -> Version:
    v = Version(n, copy.deepcopy(film), copy.deepcopy(FILM["plan"]), {"boss-battle": f"code{n}"})
    v.critique = _scores(shots, mean)
    v.score = RoundScore(n, n, {k: mean for k in ("a",)}, mean, mean, 1.0, False, 2, "", 1.0)
    return v


def test_merge_takes_each_shot_from_its_best_version() -> None:
    f1 = copy.deepcopy(FILM["film"])
    f2 = copy.deepcopy(FILM["film"])
    f2["shots"][2]["params"]["time"] = "pastel"                          # field changed in v2 ...
    f2["shots"][1]["params"]["pick"] = "RUN"                             # ... and the boss regressed
    v1 = _v(1, f1, {"walk": 6, "boss": 8, "field": 4}, 6.0)
    v2 = _v(2, f2, {"walk": 6, "boss": 5, "field": 7}, 6.2)
    mv, taken = merge_versions([v1, v2], 3)
    assert mv.origin == "merge" and len(taken) == 1 and "boss from v1" in taken[0]
    shots = {s["id"]: s for s in mv.film["shots"]}
    assert shots["field"]["params"]["time"] == "pastel" and shots["boss"]["params"]["pick"] == "BUY"
    assert mv.scenes == {"boss-battle": "code1"}                        # the boss scene's code came with it
    assert merge_versions([v1], 3) is None


def test_shot_groups_join_shots_sharing_a_custom_scene() -> None:
    f = copy.deepcopy(FILM["film"])
    f["shots"][2]["scene"] = "custom:boss-battle"
    groups = shot_groups([Version(1, f, {}), Version(2, copy.deepcopy(FILM["film"]), {})])
    assert {"boss", "field"} in groups and {"walk"} in groups


def test_engine_merges_and_verifies_best_of(env: dict[str, Any]) -> None:
    patch = {"changes": ["field pastel, boss pick RUN"],
             "shots": [{"id": "field", "params": {"time": "pastel"}}, {"id": "walk", "params": {"party": ["rogue"]}}]}
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": [fenced(GOOD_CODE)],
                   "critic": [_scores({"walk": 7, "boss": 7, "field": 4}, 6.0),
                              _scores({"walk": 4, "boss": 7, "field": 8}, 6.1),
                              _scores({"walk": 7, "boss": 7, "field": 8}, 7.4, [])],
                   "revise-film": [patch]})
    rend = FakeRenderer()
    res = _run(env, llm, rend)
    assert res.ok and res.version == 3, [s.mean for s in res.scores]
    assert llm.purposes()[-1] == "critic:r3"
    shots = {s["id"]: s for s in res.film["shots"]}
    assert shots["walk"]["params"]["party"] == ["knight", "mage"] and shots["field"]["params"]["time"] == "pastel"
    # the boss never changed: its keyframes were rendered once (v1) and reused by v2 and the merge
    assert not [t for p in rend.previews[1:] for t in p["capture"] if 6.0 <= t < 19.0]


# ------------------------------------------------------------------------------------ narration

def test_voiceover_budget_is_checked() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    lines = check_voiceover([{"t": 1.0, "text": "Dawn."}, {"t": 2.0, "text": " ".join(["word"] * 30)},
                             {"t": 6.0, "text": "Short and sweet line here."}], 20.0, errors, warnings)
    assert len(lines) == 3 and errors and "30 words" in errors[0]


def test_film_accepts_voiceover_in_plan(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["film"]["voiceover"] = [{"t": 21.0, "text": "Here, in the long grass, something stirs."}]
    chk = check_film(obj, env["brief"], env["catalog"], max_custom=2)
    assert chk.ok, chk.errors
    film, plan = chk.value
    assert "voiceover" not in film and plan["voiceover"][0]["t"] == 21.0


def test_narration_is_spoken_at_the_style_pace(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["plan"]["voiceover"] = [{"t": 2.0, "text": "Every hero has a boss."},
                                {"t": 25.0, "text": "This one, you can own."}]
    treatment = dict(TREATMENT)
    treatment["acts"] = [dict(TREATMENT["acts"][0], style="pixel"), dict(TREATMENT["acts"][1], style="cinematic")]
    calls: list[dict[str, Any]] = []

    def dispatch(name: str, args: dict[str, Any], **_: Any) -> str:
        calls.append(args)
        out = Path(args["output_path"])
        out.write_bytes(b"ID3")
        return json.dumps({"success": True, "file_path": str(out)})

    class Clip:
        def __init__(self, path: Path, duration: float) -> None:
            self.path, self.duration = path, duration

    from showreel_core.director import voice
    lines, warns = voice.synthesize(obj["plan"]["voiceover"], dispatch=dispatch, out_dir=env["tmp"] / "vo", dur=45.0,
                                    pace=lambda t: voice.speed_for(treatment, t),
                                    tts=lambda d, text, out, speed=None: (d("text_to_speech", {
                                        "text": text, "output_path": str(out), **({"speed": speed} if speed else {})}),
                                        Clip(out, 1.8))[1])
    assert not warns and [ln["start"] for ln in lines] == [2.0, 25.0]
    assert "speed" not in calls[0] and calls[1]["speed"] == pytest.approx(1.13)
    llm = FakeLlm({"treatment": [treatment], "film": [obj], "scene": [fenced(GOOD_CODE)], "critic": [critique(9.0)]})
    res = run(env["brief"], llm=llm, renderer=FakeRenderer(), job_dir=env["job"], library_dir=env["library"],
              catalog=env["catalog"], dispatch=None)
    assert res.ok and res.narration == [] and "narration" not in res.film


def test_contact_sheet_sizes_survive_fake_captures() -> None:
    from PIL import Image
    data = png((10, 10, 10), (960, 540))
    assert Image.open(io.BytesIO(data)).size == (960, 540)


def test_product_hero_bump_grows_the_one_hilltop_product() -> None:
    shot = {"id": "end", "scene": "kit:nature/product-hero", "params": {"product": "car", "title": "top"}}
    est = pm.estimate_width(shot, "16:9")
    assert est is not None and 0.2 < est < 0.3                        # 5 m at 19 m
    what = pm.bump(shot, 1.6)
    assert what.startswith("hero size") and "flyers" not in shot["params"] and shot["params"]["size"] == 8.0
    assert pm.estimate_width(shot, "16:9") > 0.35


def test_cropped_product_is_reported() -> None:
    ms = [pm.Measure(1, "hero", 1.0, True, 0.4, 0.3, 0.1, (0.3, 0.0, 0.7, 0.3), 1),
          pm.Measure(2, "ui", 2.0, True, 0.5, 0.5, 0.2, (0.2, 0.2, 0.7, 0.7), 1)]
    lines = pm.facts(pm.summarise(ms), {"shots": [{"id": "hero"}, {"id": "ui"}]}, ms)
    assert any("off the frame edge in hero (top, 1 frame(s))" in ln for ln in lines)
    assert not any("ui (" in ln for ln in lines)
