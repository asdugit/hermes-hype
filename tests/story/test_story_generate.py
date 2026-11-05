"""LLM generate -> repair -> heuristic flow with fake models, and the ctx.llm adapter."""
import copy
import json
from types import SimpleNamespace

import pytest

from showreel_core.contracts import SceneType
from showreel_core.story.generate import (
    LlmReply,
    generate_storyboard,
    generate_storyboard_report,
    hermes_llm,
)
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.options import StoryOptions
from showreel_core.story.schema import storyboard_to_json

T = SceneType


class FakeLlm:
    """Scripted model: returns the queued replies in order and records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def good_json(coding):
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60))
    obj = storyboard_to_json(sb)
    obj["scenes"][1]["vo"] = "Meet Tally, the budget tool that reads your bank exports."
    return obj


def test_good_json_is_accepted_in_one_call(coding, good_json):
    events, stats = coding
    llm = FakeLlm(LlmReply(text=json.dumps(good_json)))
    report = generate_storyboard_report(llm, "", events, stats, StoryOptions(seconds=60))
    assert report.storyboard.source == "llm"
    assert len(llm.calls) == 1
    assert report.storyboard.scenes[1].vo.startswith("Meet Tally")
    call = llm.calls[0]
    assert call["schema_name"] == "showreel.storyboard"
    assert "REFERENCE INDEX" in call["input_text"] and "launch trailer" in call["instructions"]


def test_parsed_reply_is_used_directly(coding, good_json):
    events, stats = coding
    llm = FakeLlm(LlmReply(text="(ignored)", parsed=good_json))
    assert generate_storyboard(llm, "", events, stats, StoryOptions(seconds=60)).source == "llm"


def test_invalid_json_is_repaired(coding, good_json):
    events, stats = coding
    llm = FakeLlm(LlmReply(text='{"title": "Tally", "scenes": ['), LlmReply(text=json.dumps(good_json)))
    report = generate_storyboard_report(llm, "", events, stats, StoryOptions(seconds=60))
    assert report.storyboard.source == "repaired"
    assert len(llm.calls) == 2
    repair_input = llm.calls[1]["input_text"]
    assert "invalid JSON" in repair_input and "Your previous answer (rejected)" in repair_input
    assert [a.kind for a in report.attempts] == ["initial", "repair"]
    assert report.attempts[1].accepted


def test_wrong_refs_trigger_a_repair_with_precise_paths(coding, good_json):
    events, stats = coding
    bad = copy.deepcopy(good_json)
    bad["scenes"][2]["refs"] = ["e99"]
    llm = FakeLlm(LlmReply(parsed=bad), LlmReply(parsed=good_json))
    sb = generate_storyboard(llm, "", events, stats, StoryOptions(seconds=60))
    assert sb.source == "repaired"
    assert "$.scenes[2].refs[0]: event 'e99' does not exist" in llm.calls[1]["input_text"]


def test_schema_errors_are_quoted_back(coding, good_json):
    events, stats = coding
    bad = copy.deepcopy(good_json)
    bad["scenes"][0]["type"] = "INTRO"
    llm = FakeLlm(LlmReply(parsed=bad), LlmReply(parsed=good_json))
    generate_storyboard(llm, "", events, stats, StoryOptions(seconds=60))
    assert "$.scenes[0].type: 'INTRO' is not one of" in llm.calls[1]["input_text"]


def test_two_failures_fall_back_to_the_heuristic(coding):
    events, stats = coding
    llm = FakeLlm(LlmReply(text="I cannot do that."), LlmReply(text="Still no JSON."))
    report = generate_storyboard_report(llm, "", events, stats, StoryOptions(seconds=60, mode="speedrun"))
    assert report.storyboard.source == "heuristic" and report.storyboard.mode == "speedrun"
    assert len(llm.calls) == 2
    assert report.storyboard.scenes[-1].type == T.END


def test_exceptions_never_escape(coding):
    events, stats = coding
    llm = FakeLlm(RuntimeError("provider down"), TimeoutError("slow"))
    report = generate_storyboard_report(llm, "", events, stats)
    assert report.storyboard.source == "heuristic"
    assert "RuntimeError: provider down" in report.attempts[0].problems[0]


def test_viable_but_flawed_first_answer_beats_a_broken_repair(coding, good_json):
    events, stats = coding
    flawed = copy.deepcopy(good_json)
    flawed["scenes"][3]["vo"] = "It sorted 4,812 receipts."  # number not in the session -> error, auto-fixable
    llm = FakeLlm(LlmReply(parsed=flawed), LlmReply(text="not json"))
    sb = generate_storyboard(llm, "", events, stats, StoryOptions(seconds=60))
    assert sb.source == "llm"
    assert "4,812" not in json.dumps(storyboard_to_json(sb))


def test_no_llm_means_heuristic(coding):
    events, stats = coding
    assert generate_storyboard(None, "", events, stats, StoryOptions(mode="lore")).mode == "making_of"


def test_garbage_events_do_not_crash():
    from showreel_core.contracts import Event, Stats
    events = [Event(id="e0", t=0, kind="terminal", tool="terminal", title="", summary="", data={"cmd": None}),
              Event(id="e1", t=1, kind="file_patch", tool="patch", title="x", summary="", data={"hunks": "nope"})]
    sb = generate_storyboard(None, "", events, Stats())
    assert sb.scenes and sb.scenes[-1].type == T.END


# ---------------------------------------------------------------- ctx.llm adapter

class PluginLlmTrustError(PermissionError):
    pass


class FakeCtxLlm:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def complete_structured(self, **kw):
        self.calls.append(kw)
        return self.behaviour(kw)


def _result(text, parsed=None):
    usage = SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30, cost_usd=None)
    return SimpleNamespace(text=text, parsed=parsed, content_type="json" if parsed is not None else "text",
                           provider="fake", model="fake-1", usage=usage)


def _call(adapter):
    return adapter(instructions="i", input_text="x", json_schema={"type": "object"}, schema_name="s",
                   temperature=0.4, max_tokens=100, timeout=5)


def test_adapter_passes_structured_kwargs():
    ctx = FakeCtxLlm(lambda kw: _result('{"a": 1}', {"a": 1}))
    reply = _call(hermes_llm(ctx))
    assert reply.parsed == {"a": 1} and reply.model == "fake-1" and reply.usage["total_tokens"] == 30
    kw = ctx.calls[0]
    assert kw["task"] == "showreel" and kw["json_schema"] == {"type": "object"}
    assert kw["input"] == [{"type": "text", "text": "x"}] and kw["purpose"] == "showreel.storyboard"


def test_adapter_falls_back_to_main_model_when_task_is_refused():
    def behaviour(kw):
        if kw["task"]:
            raise PluginLlmTrustError("task not registered")
        return _result("plain text")
    ctx = FakeCtxLlm(behaviour)
    reply = _call(hermes_llm(ctx))
    assert [c["task"] for c in ctx.calls] == ["showreel", None]
    assert reply.text == "plain text" and reply.parsed is None


def test_adapter_turns_errors_into_replies():
    def boom(kw):
        raise ValueError("Plugin LLM structured output did not match schema: 'x' is required")
    reply = _call(hermes_llm(FakeCtxLlm(boom)))
    assert reply.error.startswith("ValueError: Plugin LLM structured output")
