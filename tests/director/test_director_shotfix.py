"""Engine shot fixes (model-free revision of the worst shots for weak / compose tiers)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from showreel_core.director import shotfix

FILM = {
    "title": "Tempo", "dur": 30.0,
    "shots": [
        {"id": "hook", "t0": 0, "t1": 4, "scene": "kit:cinematic/HOOK",
         "params": {"hero": {"kind": "image", "asset": "desktop"}, "label": "Every second leaves a trace"}},
        {"id": "feature1", "t0": 4, "t1": 10, "scene": "kit:cinematic/FEATURE",
         "params": {"image": {"asset": "timer"}, "feature": "A focus timer that remembers every session"}},
        {"id": "quote", "t0": 10, "t1": 14, "scene": "kit:type/title", "params": {"text": ""}},
        {"id": "end", "t0": 14, "t1": 30, "scene": "kit:cinematic/END", "params": {"title": "Tempo"}},
    ],
    "overlays": [{"id": "lt", "t0": 5, "t1": 9, "scene": "kit:type/lower-third",
                  "params": {"title": "Exhibit A: the clock that never sleeps", "sub": "Tempo", "scrim": 0.0}}],
}
PLAN = {"shots": [{"id": "hook", "product_visible": True}, {"id": "feature1", "product_visible": True},
                  {"id": "quote", "product_visible": False}, {"id": "end", "product_visible": False}]}


def test_small_product_shot_moves_to_the_large_base_frame_with_the_mood_theme():
    per = {"feature1": {"visible": 3, "max_width": 0.22}, "hook": {"visible": 3, "max_width": 0.5}}
    film, changes = shotfix.fix_worst(FILM, PLAN, critique=None, per_shot=per, product={"desktop", "timer"},
                                      theme="noir", name="Tempo")
    s = next(x for x in film["shots"] if x["id"] == "feature1")
    assert s["scene"] == "kit:base/FEATURE"
    assert s["params"]["image"] == {"asset": "timer"} and s["params"]["theme"] == "noir"
    assert len(s["params"]["feature"].split()) <= 5
    assert any("feature1" in c for c in changes)
    assert FILM["shots"][1]["scene"] == "kit:cinematic/FEATURE"          # the input film is untouched


def test_physical_products_and_non_product_shots_are_not_swapped():
    per = {"feature1": {"visible": 3, "max_width": 0.1}}
    film, changes = shotfix.fix_worst(FILM, PLAN, critique=None, per_shot=per, product={"timer"}, screen=False)
    assert film["shots"][1]["scene"] == "kit:cinematic/FEATURE"


def test_critic_text_issue_shortens_and_empty_type_card_gets_the_name():
    crit = {"shots": [{"id": "quote", "score": 3}, {"id": "hook", "score": 4}],
            "per_shot_issues": [{"shot": "hook", "severity": 2, "issue": "the caption text is tiny and hard to read",
                                 "fix": "bigger"}]}
    film, changes = shotfix.fix_worst(FILM, PLAN, critique=crit, per_shot={}, product={"desktop"}, name="Tempo")
    by = {s["id"]: s for s in film["shots"]}
    assert by["quote"]["params"]["text"] == "Tempo"
    assert len(by["hook"]["params"]["label"].split()) <= 4
    assert len(changes) == 2


def test_qa_flagged_overlay_gets_shorter_and_a_scrim():
    qa = [{"kind": "overlap", "shot": "lt", "msg": "x"}]
    film, changes = shotfix.fix_worst(FILM, PLAN, critique=None, per_shot={}, qa=qa, product=set())
    p = film["overlays"][0]["params"]
    assert len(p["title"].split()) <= 3 and p["scrim"] >= 0.45
    assert any(c.startswith("overlay lt") for c in changes)


def test_nothing_to_fix_returns_no_changes():
    good = {"shots": [{"id": "a", "t0": 0, "t1": 5, "scene": "kit:base/SCREEN", "params": {"image": {"asset": "d"}}}]}
    _film, changes = shotfix.fix_worst(good, {"shots": [{"id": "a", "product_visible": True}]}, critique=None,
                                       per_shot={"a": {"visible": 3, "max_width": 0.7}}, product={"d"})
    assert changes == []


def test_weak_tier_runs_one_engine_fix_round_and_best_of_keeps_the_better(tmp_path: Path, monkeypatch):
    import test_director_audit as T
    from director_fakes import FakeLlm

    from showreel_core.director import tiers
    from showreel_core.director.catalog import build_catalog
    from showreel_core.director.engine import run

    def fake_fix(film, plan, **kw):
        import copy
        f = copy.deepcopy(film)
        f["shots"][0]["params"]["engine_marker"] = 1
        return f, ["hook: test fix"]
    monkeypatch.setattr(shotfix, "fix_worst", fake_fix)
    b = T._screen_brief(tmp_path, "noir detective trailer")
    cat = build_catalog(assets=b.assets, capabilities=b.capabilities)
    llm = FakeLlm({"pick": [{"blueprint": "screen-cinematic", "voice": "none"}], "words": [{"text": {}}]})
    res = run(b, llm=llm, renderer=T.FakeRenderer(), effort="quick", budget=T.FREE_QUICK, job_dir=tmp_path / "job",
              library_dir=tmp_path / "lib", catalog=cat, tier=tiers.detect("deepseek-v4.1-flash"))
    assert res.ok, res.error
    msgs = [e["msg"] for e in res.log]
    assert any(m.startswith("Engine fix of the worst shot") for m in msgs), msgs[-12:]
    assert any(m.startswith("Engine fix v2") for m in msgs)
    assert not [c for c in llm.calls if c["purpose"].startswith(("critic", "revise"))]   # model-free, no vision
    assert dataclasses.is_dataclass(res) or res.version in (1, 2, 3)


def test_base_shot_that_runs_off_the_frame_becomes_a_whole_card():
    film = {"shots": [{"id": "feature1", "t0": 0, "t1": 6, "scene": "kit:base/FEATURE",
                       "params": {"image": {"asset": "timer"}, "feature": "Timer", "theme": "noir"}}]}
    plan = {"shots": [{"id": "feature1", "product_visible": True}]}
    crit = {"shots": [{"id": "feature1", "score": 4}],
            "per_shot_issues": [{"shot": "feature1", "severity": 3, "issue": "tight UI crop, frames run off the "
                                 "right/top edges", "fix": "keep it bounded"}]}
    out, changes = shotfix.fix_worst(film, plan, critique=crit, per_shot={}, product={"timer"})
    p = out["shots"][0]["params"]
    assert p["image"] == {"asset": "timer", "frame": "card"} and p["bbox"] == shotfix.WHOLE_BBOX
    assert p["theme"] == "noir" and changes
    # measured edge crops alone (no critic words) do it too
    out2, ch2 = shotfix.fix_worst(film, plan, critique=None, per_shot={}, product={"timer"}, cropped=["feature1"])
    assert out2["shots"][0]["params"]["image"]["frame"] == "card" and ch2
    # already a card: nothing more to do
    _o, ch3 = shotfix.fix_worst(out, plan, critique=crit, per_shot={}, product={"timer"})
    assert not any("ran off" in c for c in ch3)


def test_a_deliberate_push_in_is_not_undone_by_measured_edge_contact():
    """The content box pushes a game canvas to fill the frame; the measured edge contact that follows is the point,
    not a crop (a real run turned the pushed-in Brickfall canvas back into a small whole card)."""
    film = {"shots": [{"id": "exhibit", "t0": 0, "t1": 6, "scene": "kit:base/SCREEN",
                       "params": {"image": {"asset": "desk"}, "bbox": [0.22, 0.15, 0.56, 0.7]}}]}
    plan = {"shots": [{"id": "exhibit", "product_visible": True}]}
    out, ch = shotfix.fix_worst(film, plan, critique=None, per_shot={}, product={"desk"}, cropped=["exhibit"])
    assert out["shots"][0]["params"]["bbox"] == [0.22, 0.15, 0.56, 0.7] and not ch
