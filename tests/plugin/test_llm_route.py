"""The storyboard/Director model route sends the schema as prompt text in JSON mode (never provider-native
structured output: Anthropic answers our storyboard schema with HTTP 400 "Schema is too complex")."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from showreel_core.llm import Host, JsonModeLlm
from showreel_core.pipeline import director_llm


class RecordingLlm:
    def __init__(self, reply: Any, refuse_json: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reply = reply
        self.refuse_json = refuse_json
        self.extra = "kept"

    def complete_structured(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.refuse_json is not None and kwargs.get("json_mode"):
            raise self.refuse_json
        return self.reply


class BadRequestError(Exception):
    pass


ANTHROPIC_400 = BadRequestError("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                                "'message': \"output_config.format.schema: For 'object' type, 'additionalProperties' "
                                "must be explicitly set to false\"}}")


@pytest.fixture(autouse=True)
def _fresh_route(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(JsonModeLlm, "plain_only", False)
    monkeypatch.setattr(JsonModeLlm, "_disk_checked", False)
    monkeypatch.setenv("HYPE_DATA_DIR", str(tmp_path / "data"))   # the refusal memory file stays in the test


SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}


def test_json_mode_proxy_moves_the_schema_into_the_prompt() -> None:
    inner = RecordingLlm(SimpleNamespace(text='{"title": "Tempo"}', parsed={"title": "Tempo"}, content_type="json"))
    res = JsonModeLlm(inner).complete_structured(instructions="Write it.", input=[], json_schema=SCHEMA,
                                                 schema_name="sb", task="hype")
    call = inner.calls[0]
    assert "json_schema" not in call and call["json_mode"] is True and call["schema_name"] == "sb"
    assert call["instructions"].startswith("Write it.") and json.dumps(SCHEMA, sort_keys=True) in call["instructions"]
    assert res.parsed == {"title": "Tempo"}
    assert JsonModeLlm(inner).extra == "kept"                       # other attributes pass through


def test_json_mode_proxy_leaves_plain_calls_alone() -> None:
    inner = RecordingLlm(SimpleNamespace(text="hi", parsed=None, content_type="text"))
    JsonModeLlm(inner).complete_structured(instructions="Say hi.", input=[])
    assert inner.calls[0] == {"instructions": "Say hi.", "input": []}


def test_a_refused_json_mode_falls_back_to_plain_text_for_the_rest_of_the_process() -> None:
    reply = SimpleNamespace(text='```json\n{"title": "Tempo"}\n```', parsed=None, content_type="text",
                            provider="anthropic", model="m", usage=None)
    inner = RecordingLlm(reply, refuse_json=ANTHROPIC_400)
    call = Host(llm=inner).story_call()
    out = call(instructions="I", input_text="digest", json_schema=SCHEMA, schema_name="sb", temperature=0.4,
               max_tokens=100, timeout=10)
    assert not out.error and out.text.startswith("```json")       # story parses JSON out of the text itself
    assert [c.get("json_mode") for c in inner.calls] == [True, None] and JsonModeLlm.plain_only
    assert all("json_schema" not in c for c in inner.calls)
    call(instructions="I", input_text="again", json_schema=SCHEMA, schema_name="sb", temperature=0.4,
         max_tokens=100, timeout=10)
    assert inner.calls[-1].get("json_mode") is None and len(inner.calls) == 3   # no second refused call


def test_a_refusal_is_remembered_by_the_next_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """GAUNTLET #21: every `hermes hype render` (one process per film) paid a refused JSON-mode round trip first."""
    reply = SimpleNamespace(text='{"title": "Tempo"}', parsed=None, content_type="text")
    first = RecordingLlm(reply, refuse_json=ANTHROPIC_400)
    JsonModeLlm(first).complete_structured(instructions="I", input=[], json_schema=SCHEMA)
    assert [c.get("json_mode") for c in first.calls] == [True, None]
    monkeypatch.setattr(JsonModeLlm, "plain_only", False)          # a new process
    monkeypatch.setattr(JsonModeLlm, "_disk_checked", False)
    second = RecordingLlm(reply, refuse_json=ANTHROPIC_400)
    JsonModeLlm(second).complete_structured(instructions="I", input=[], json_schema=SCHEMA)
    assert [c.get("json_mode") for c in second.calls] == [None]    # straight to plain text, no wasted call


def test_other_errors_are_not_swallowed() -> None:
    inner = RecordingLlm(None, refuse_json=TimeoutError("read timed out"))
    with pytest.raises(TimeoutError):
        JsonModeLlm(inner).complete_structured(instructions="I", input=[], json_schema=SCHEMA)
    assert not JsonModeLlm.plain_only


def test_story_route_uses_json_mode_end_to_end() -> None:
    inner = RecordingLlm(SimpleNamespace(text='{"title": "Tempo"}', parsed={"title": "Tempo"}, content_type="json",
                                         provider="anthropic", model="m", usage=None))
    call = Host(llm=inner).story_call()
    reply = call(instructions="I", input_text="digest", json_schema=SCHEMA, schema_name="sb", temperature=0.4,
                 max_tokens=100, timeout=10)
    assert reply.parsed == {"title": "Tempo"} and not reply.error
    assert inner.calls and all("json_schema" not in c and c["json_mode"] for c in inner.calls)


def test_director_gets_the_json_mode_route() -> None:
    inner = RecordingLlm(None)
    wrapped = director_llm(Host(llm=inner))
    assert isinstance(wrapped, JsonModeLlm)
    assert director_llm(Host(llm=wrapped)) is wrapped                # never double-wrapped
    assert director_llm(Host()) is None
