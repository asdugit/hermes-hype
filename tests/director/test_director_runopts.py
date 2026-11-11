"""Director run options: narration off unless asked (E15), a no-model flag on the result (E8), and the wall-clock /
soft spend caps that degrade to the best film so far / the engine floor (story audit open P2s)."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from showreel_core.director import tiers
from showreel_core.director.catalog import build_catalog
from showreel_core.director.engine import run, wants_narration
from showreel_core.director.llm import CallLedger, LlmReply

T = pytest.importorskip("test_director_audit")


def _run(tmp_path: Path, llm, direction="a noir detective trailer", budget=None, **kw):
    b = T._screen_brief(tmp_path, direction)
    cat = build_catalog(assets=b.assets, capabilities=b.capabilities)
    return run(b, llm=llm, renderer=T.FakeRenderer(), effort="quick", budget=budget or T.FREE_QUICK,
               job_dir=tmp_path / "job", library_dir=tmp_path / "lib", catalog=cat,
               tier=tiers.detect("deepseek-v4.1-flash"), **kw)


def test_wants_narration_follows_the_option_then_the_words():
    assert wants_narration({}, SimpleNamespace(voice=False), "with narration") is False   # the option decides
    assert wants_narration({}, SimpleNamespace(voice=True), "") is True
    assert wants_narration({"narration": True}, SimpleNamespace(voice=False), "") is True
    assert wants_narration({}, None, "a noir trailer") is False                         # music only by default
    assert wants_narration({}, None, "a noir trailer with narration") is True


def test_music_only_film_plans_and_speaks_no_narration(tmp_path: Path):
    from director_fakes import FakeLlm
    spoken = []

    def dispatch(name, args, **_k):
        spoken.append(args)
        return '{"success": false, "error": "should not be called"}'
    llm = FakeLlm({"pick": [{"blueprint": "screen-noir", "voice": "narrated"}],
                   "words": [{"text": {}, "voiceover": [{"id": "x", "text": "Tempo awaits."}]}]})
    res = _run(tmp_path, llm, options=SimpleNamespace(voice=False, effort="quick"), dispatch=dispatch)
    assert res.ok and res.narration == [] and spoken == []
    words = next(c for c in llm.calls if c["purpose"] == "words")
    assert "Narration windows: none" in words["text"]


def test_all_model_calls_failing_is_flagged_not_silent(tmp_path: Path):
    from director_fakes import FakeLlm
    llm = FakeLlm({"pick": [LlmReply(error="401 invalid api key")], "words": [LlmReply(error="401 invalid api key")],
                   "critic": [LlmReply(error="401 invalid api key")]})
    res = _run(tmp_path, llm)
    assert res.ok and res.no_model and res.notes and "401" in res.notes[0]
    assert res.to_dict()["no_model"] is True


def test_a_working_model_is_not_flagged(tmp_path: Path):
    from director_fakes import FakeLlm
    res = _run(tmp_path, FakeLlm({"pick": [{"blueprint": "screen-noir", "voice": "none"}], "words": [{"text": {}}]}))
    assert res.ok and not res.no_model and res.notes == []


def test_soft_spend_cap_stops_further_calls_and_keeps_a_film(tmp_path: Path):
    from director_fakes import FakeLlm
    llm = FakeLlm({"pick": [{"blueprint": "screen-noir", "voice": "none"}], "words": [{"text": {}}]})
    res = _run(tmp_path, llm, budget=dataclasses.replace(T.FREE_QUICK, max_usd=0.005))   # each fake call $0.01
    assert res.ok
    assert llm.purposes() == ["pick"]                                    # the cap held after the first call
    assert any("spend cap" in e["msg"] for e in res.log)


def test_wall_clock_limit_degrades_to_the_engine_floor(tmp_path: Path, monkeypatch):
    import itertools

    from director_fakes import FakeLlm

    from showreel_core.director import engine
    tick = itertools.count(1000.0, 5.0)              # Windows' monotonic clock ticks every ~16 ms: step it
    monkeypatch.setattr(engine.time, "monotonic", lambda: next(tick))
    llm = FakeLlm({"pick": [{"blueprint": "screen-noir", "voice": "none"}], "words": [{"text": {}}]})
    res = _run(tmp_path, llm, budget=dataclasses.replace(T.FREE_QUICK, call_wall_s=1.0))
    assert res.ok and llm.calls == [] and res.no_model
    assert "limit for model work" in res.notes[0]


def test_ledger_guard_and_estimated_spend():
    calls = []
    led = CallLedger(lambda **kw: calls.append(1) or LlmReply(text="{}", usage={"input_tokens": 200_000,
                                                                                   "output_tokens": 20_000}),
                     None, max_calls=5)
    led(purpose="pick", instructions="", text="")
    assert led.spent_usd() == pytest.approx(1.5)                          # $5/M in + $25/M out, estimated
    led.guard = lambda: "over"
    from showreel_core.director.llm import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        led(purpose="words", instructions="", text="")
    assert len(calls) == 1
