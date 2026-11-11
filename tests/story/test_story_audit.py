"""Pre-submission audit regressions (story area): malformed model output and template/filler text on screen."""
import copy
import json
import re

import pytest

from showreel_core.story.generate import LlmReply, generate_storyboard_report
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.onscreen import unplaceholder
from showreel_core.story.options import StoryOptions
from showreel_core.story.schema import storyboard_to_json

_JUNK = re.compile(r"[{}<>]|lorem|patchlib|TODO:", re.IGNORECASE)


class _Fake:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def __call__(self, **kw):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def good(coding):
    events, stats = coding
    return storyboard_to_json(build_heuristic_storyboard(events, stats, StoryOptions(seconds=30)))


def _texts(sb):
    out = [sb.title, sb.tagline, sb.cta]
    for s in sb.scenes:
        out += [s.label, s.vo]
    return [t for t in out if t]


def test_malformed_replies_always_give_a_valid_film_in_at_most_two_calls(coding, good):
    events, stats = coding
    txt = json.dumps(good)
    replies = [LlmReply(text="```json\n" + txt + "\n```"), LlmReply(text="Sure! " + txt + " Enjoy."),
               LlmReply(text=txt[: len(txt) // 2]), LlmReply(text="I'm sorry, I can't help with that."),
               LlmReply(error="RateLimitError: 429"), LlmReply(error="TimeoutError: timed out"),
               LlmReply(parsed=[1, 2]), LlmReply(parsed="hello"), LlmReply(parsed=dict(good, scenes={"a": 1})),
               LlmReply(parsed=dict(good, title=5)), LlmReply(parsed={"title": "X"}),
               LlmReply(text=json.dumps(dict(good, tagline="A" * 200_000))), RuntimeError("boom"), None,
               LlmReply(parsed=dict(good, tagline="预算工具，读取您的银行导出"))]
    for reply in replies:
        llm = _Fake(reply)
        sb = generate_storyboard_report(llm, "", events, stats, StoryOptions(seconds=30)).storyboard
        assert llm.calls <= 2 and len(sb.scenes) >= 3, reply
        assert sb.title and all(len(t) <= 300 for t in _texts(sb)), reply


def test_template_slots_and_filler_never_reach_the_screen(coding, good):
    """A model that echoes template slots ({product}, <call to action>) or filler ('Lorem ipsum', 'TODO:',
    'from patchlib import patch') used to put them on screen as labels, tagline, CTA and narration."""
    events, stats = coding
    obj = copy.deepcopy(good)
    obj["tagline"], obj["cta"] = "{product} for {audience}", "<call to action>"
    junk = ["Meet {product}", "Lorem ipsum dolor", "TODO: label", "from patchlib import patch", "<one real feature>"]
    for i, s in enumerate(obj["scenes"]):
        s["label"] = junk[i % len(junk)]
        if s["vo"]:
            s["vo"] = "Meet {product}, your new budget tool."
    sb = generate_storyboard_report(_Fake(LlmReply(parsed=obj)), "", events, stats,
                                    StoryOptions(seconds=30)).storyboard
    name = sb.product.name if sb.product else ""
    assert not [t for t in _texts(sb) if _JUNK.search(t)], _texts(sb)
    assert sb.scenes[0].label in ("", f"Meet {name}")
    assert any(f"Meet {name}" in s.vo for s in sb.scenes if s.vo) or not any(s.vo for s in sb.scenes)


def test_unplaceholder_keeps_real_copy():
    kw = {"name": "Orbit Notes", "tagline": "Fast offline notes."}
    assert unplaceholder("Try <PRODUCT NAME> today", **kw) == "Try ORBIT NOTES today"
    assert unplaceholder("{{name}} for {audience}", **kw) == "Orbit Notes"
    assert unplaceholder("<one-line benefit>", **kw) == "Fast offline notes."
    for real in ("TODO list, done.", "Your todo app", "List<String> parse()", "Import your bank CSV", "x < y > z",
                 "with friends", "const {x} = y", "预算工具", "Class notes, sorted"):
        assert unplaceholder(real, **kw) == real
    for junk in ("TODO: tagline", "TBD", "Lorem ipsum dolor", "from patchlib import patch", "import os",
                 "<call to action>", "<one real feature>"):
        assert unplaceholder(junk, **kw) == "", junk
