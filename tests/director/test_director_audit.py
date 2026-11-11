"""Pre-submission audit regressions (story area): tier detection through the plugin route, on-screen text."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from test_director_anymodel import FREE_QUICK, _screen_brief

from showreel_core.director import tiers
from showreel_core.director.catalog import build_catalog
from showreel_core.director.engine import run
from showreel_core.director.tiers import host_model as real_host_model

from director_fakes import FakeRenderer  # noqa: I001


class _Res:
    def __init__(self, obj: Any) -> None:
        self.text, self.parsed, self.content_type = json.dumps(obj), obj, "json"
        self.provider, self.model, self.usage = "fake", "", None


class _CtxLlm:
    """``ctx.llm``-shaped object: like Hermes' PluginLlm it has no model attribute."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies, self.purposes = replies, []

    def complete_structured(self, **kw: Any) -> _Res:
        purpose = str(kw["purpose"]).removeprefix("hype.")
        self.purposes.append(purpose)
        key = next((k for k in self.replies if purpose.startswith(k)), None)
        if key is None:
            raise RuntimeError(f"offline ({purpose})")
        return _Res(self.replies[key])


def test_plugin_route_picks_the_tier_from_the_hosts_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ctx.llm has no model id, so every model took the strong free path inside the plugin (README: small models
    take the compose path). The host's configured main model decides the tier now."""
    monkeypatch.setattr(tiers, "host_model", lambda: "claude-haiku-4-5")
    b = _screen_brief(tmp_path, "noir detective trailer")
    llm = _CtxLlm({"pick": {"blueprint": "screen-cinematic", "voice": "none"}, "words": {"text": {}, "voiceover": []}})
    res = run(b, llm=llm, renderer=FakeRenderer(), effort="quick", budget=FREE_QUICK, job_dir=tmp_path / "job",
              library_dir=tmp_path / "lib", catalog=build_catalog(assets=b.assets, capabilities=b.capabilities))
    assert res.ok, res.error
    assert res.tier["name"] == "weak" and res.tier["model"] == "claude-haiku-4-5" and res.tier["path"] == "compose"
    assert llm.purposes[:2] == ["pick", "words"] and "treatment" not in llm.purposes


def test_host_model_reads_the_hermes_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg: dict[str, Any] = {}
    mod = types.ModuleType("hermes_cli.config")
    mod.load_config_readonly = lambda: cfg  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    cfg["model"] = {"default": " claude-haiku-4-5 ", "provider": "anthropic"}
    assert real_host_model() == "claude-haiku-4-5"
    cfg["model"] = "gpt-5-mini"
    assert real_host_model() == "gpt-5-mini"
    cfg["model"] = {"default": "my-preset", "provider": "moa"}           # a MoA preset name is not a model id
    assert real_host_model() == ""
    cfg["model"] = {"default": 5}
    assert real_host_model() == ""
    mod.load_config_readonly = lambda: (_ for _ in ()).throw(OSError("unreadable"))  # type: ignore[attr-defined]
    assert real_host_model() == ""


def test_gemini_pro_is_not_a_small_model() -> None:
    """'gemini-' contains 'mini' followed by a word boundary: every Gemini Pro was routed to the weak path."""
    for m in ("gemini-2.5-pro", "gemini-3-pro-preview", "google/gemini-3.1-pro"):
        assert tiers.detect(m).name == "strong", m
    assert tiers.detect("gemini-2.5-flash").name == "weak"
    assert tiers.detect("gpt-5-mini").name == "weak" and tiers.detect("o4-mini").name == "weak"


def test_text_only_models_get_the_measured_review() -> None:
    for m in ("nousresearch/hermes-4-405b", "Hermes-3-Llama-3.1-70B", "openai/gpt-oss-120b", "moonshotai/kimi-k2"):
        assert not tiers.detect(m).vision, m
    assert tiers.detect("claude-haiku-4-5").vision and tiers.detect("hermes chat (default model)").vision


def test_template_slots_and_filler_never_reach_a_directed_film(env: dict[str, Any]) -> None:
    """The film prompt's starting template carries ``<call to action>`` / ``<one-line benefit>`` slots and
    ``{name}``-style placeholders; a model that echoed them (or wrote Lorem ipsum / TODO) put them on screen."""
    import copy

    from director_fakes import FILM, TREATMENT, FakeLlm, critique
    from test_director_anymodel import _GOOD
    bad = copy.deepcopy(FILM)
    bad["film"]["captions"] = [{"t0": 1, "t1": 3, "text": "<one-line benefit>"},
                               {"t0": 3, "t1": 5, "text": "TODO: tagline"},
                               {"t0": 5, "t1": 7, "text": "Lorem ipsum dolor"},
                               {"t0": 7, "t1": 9, "text": "Meet {product}."}]
    bad["film"]["overlays"][0]["params"].update(text="{NAME}", sub="<call to action>")
    bad["plan"]["voiceover"] = [{"t": 1.0, "text": "Meet {product}, the fastest car alive."}]
    llm = FakeLlm({"treatment": [TREATMENT], "film": [bad], "scene": ["```js\n" + _GOOD + "```"],
                   "critic": [critique(9.0)]})
    res = run(env["brief"], llm=llm, renderer=FakeRenderer(), effort="quick", job_dir=env["job"],
              library_dir=env["library"], catalog=env["catalog"], tier=tiers.detect("claude-opus-5-5"),
              budget=FREE_QUICK)
    assert res.ok, res.error
    shown = json.dumps([res.film.get("captions"), res.film.get("overlays"), res.film.get("shots")])
    for junk in ("<one-line", "<call to", "{NAME}", "{product}", "TODO:", "Lorem"):
        assert junk not in shown, junk
    texts = [c["text"] for c in res.film["captions"]]
    assert texts == ["A red car.", "Meet Red Car."]                  # filler-only captions are dropped, not blank
    assert res.film["overlays"][0]["params"]["text"] == "RED CAR"


def test_user_revise_keeps_the_parent_runs_model_tier(tmp_path: Path) -> None:
    """``/hype revise`` re-ran setup without a tier: a text-only weak model got the strong path again (vision critic
    with contact sheets, a full critique/revision budget)."""
    from director_fakes import FakeLlm

    from showreel_core.director.engine import revise
    b = _screen_brief(tmp_path, "noir detective trailer")
    cat = build_catalog(assets=b.assets, capabilities=b.capabilities)
    first = FakeLlm({"pick": [{"blueprint": "screen-cinematic", "voice": "none"}], "words": [{"text": {}}]})
    res1 = run(b, llm=first, renderer=FakeRenderer(), effort="quick", budget=FREE_QUICK, job_dir=tmp_path / "job",
               library_dir=tmp_path / "lib", catalog=cat, tier=tiers.detect("deepseek-v4.1-flash"))
    assert res1.ok and not res1.tier["vision"]
    second = FakeLlm({"revise-notes": [{"changes": ["warmer"], "shots": []}]})
    res2 = revise(tmp_path / "job", "warmer light", llm=second, renderer=FakeRenderer(), job_dir=tmp_path / "job2",
                  library_dir=tmp_path / "lib", catalog=cat, budget=FREE_QUICK)
    assert res2.tier["name"] == "weak" and not res2.tier["vision"], res2.tier
    assert not [c for c in second.calls if c["purpose"].startswith("critic")]   # measured review, no picture critic


def test_call_budget_spent_on_the_free_path_still_gives_the_floor_film(tmp_path: Path) -> None:
    """BudgetExceeded inside the free path skipped the engine floor (which needs no model) and ended the whole
    Directed film in a Quick fallback."""
    import dataclasses

    from director_fakes import FakeLlm
    b = _screen_brief(tmp_path, "an Apple keynote reveal")
    llm = FakeLlm({"treatment": ["I am not JSON"]})
    res = run(b, llm=llm, renderer=FakeRenderer(), effort="quick", job_dir=tmp_path / "job",
              library_dir=tmp_path / "lib", catalog=build_catalog(assets=b.assets, capabilities=b.capabilities),
              tier=tiers.detect("claude-opus-5-5"), budget=dataclasses.replace(FREE_QUICK, max_calls=1))
    assert res.ok, res.error
    assert llm.purposes() == ["treatment"] and res.tier["path"] == "floor"


def test_fit_words_bounds_width_and_time() -> None:
    """Word limits alone let a CJK line or a run without spaces (one 'word') overflow its slot; a degenerate reply
    (one token repeated up to max_tokens) made the sentence regex backtrack for seconds; 'orbit.app' was split."""
    import time

    from showreel_core.director.repair import fit_words
    cjk = "预算工具，读取您的银行导出并自动分类每一笔交易。然后生成漂亮的月度报告给你的家人看。"
    assert fit_words(cjk, 8) == "预算工具，读取您的银行导出并自动分类每一笔交易。"
    assert fit_words("A" * 100_000, 8) == "" and fit_words("https://example.com/" + "x" * 200, 5) == ""
    t0 = time.monotonic()
    assert fit_words("word " * 40_000, 8) == ""
    assert time.monotonic() - t0 < 0.5
    assert fit_words("Visit orbit.app today. It is fast.", 4) == "Visit orbit.app today."
    assert fit_words("Orbit Notes", 4) == "Orbit Notes"
    assert fit_words("Die schnellsten Offline-Notizen mit Synchronisierung für alle Geräte", 8).startswith("Die")


def test_failed_vision_critic_falls_back_to_the_measured_review(env: dict[str, Any]) -> None:
    """A model that rejects the contact sheets (an unknown text-only model) left the round without any review;
    it now gets the measured review, and later rounds stop sending pictures."""
    import dataclasses

    from director_fakes import FILM, TREATMENT, FakeLlm
    from test_director_anymodel import _GOOD

    from showreel_core.director.llm import LlmReply
    llm = FakeLlm({"treatment": [TREATMENT], "film": [FILM], "scene": ["```js\n" + _GOOD + "```"],
                   "critic": [LlmReply(error="BadRequestError: 400 this model does not support image input")]})
    res = run(env["brief"], llm=llm, renderer=FakeRenderer(), effort="quick", job_dir=env["job"],
              library_dir=env["library"], catalog=env["catalog"], tier=tiers.detect("claude-opus-5-5"),
              budget=dataclasses.replace(FREE_QUICK, rounds=2))
    assert res.ok, res.error
    assert res.scores and "measured" in res.scores[0].verdict
    assert [p for p in llm.purposes() if p.startswith("critic")] == ["critic:r1", "critic:r1"]   # never again
    assert res.tier["vision"] is False
