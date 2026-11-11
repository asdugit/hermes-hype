"""The storyboard/Director model route sends the schema as prompt text in JSON mode (never provider-native
structured output: Anthropic answers our storyboard schema with HTTP 400 "Schema is too complex")."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from showreel_core.llm import Host, JsonModeLlm
from showreel_core.pipeline import director_llm


class RecordingLlm:
    def __init__(self, reply: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reply = reply
        self.extra = "kept"

    def complete_structured(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.reply


SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}


def test_json_mode_proxy_moves_the_schema_into_the_prompt() -> None:
    inner = RecordingLlm(SimpleNamespace(text='{"title": "Tempo"}', parsed={"title": "Tempo"}, content_type="json"))
    res = JsonModeLlm(inner).complete_structured(instructions="Write it.", input=[], json_schema=SCHEMA,
                                                 schema_name="sb", task="showreel")
    call = inner.calls[0]
    assert "json_schema" not in call and call["json_mode"] is True and call["schema_name"] == "sb"
    assert call["instructions"].startswith("Write it.") and json.dumps(SCHEMA, sort_keys=True) in call["instructions"]
    assert res.parsed == {"title": "Tempo"}
    assert JsonModeLlm(inner).extra == "kept"                       # other attributes pass through


def test_json_mode_proxy_leaves_plain_calls_alone() -> None:
    inner = RecordingLlm(SimpleNamespace(text="hi", parsed=None, content_type="text"))
    JsonModeLlm(inner).complete_structured(instructions="Say hi.", input=[])
    assert inner.calls[0] == {"instructions": "Say hi.", "input": []}


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
