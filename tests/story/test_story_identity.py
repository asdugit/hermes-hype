"""Product identity (ISSUES #40): the film names the product the session built, from session facts.

Real E2E: a customized comic film of an Orbit Notes session named the product "Hype Product Capture"
(the capture stage that photographed it) and wrote "Meet Hype's product capture" in the narration.
"""
import json

from story_synth import SESSIONS

from showreel_core.contracts import Product
from showreel_core.pipeline import product_name_locked
from showreel_core.story.facts import SessionFacts
from showreel_core.story.generate import LlmReply, generate_storyboard_report
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.identity import replace_name, same_product, toolish_words
from showreel_core.story.options import StoryOptions
from showreel_core.story.schema import storyboard_from_json, storyboard_to_json
from showreel_core.story.validate import validate_storyboard


class FakeLlm:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)


def _webapp():
    events, stats = SESSIONS["webapp"]()
    return events, stats, Product(name="Focusfox", one_liner="A pomodoro timer with tasks and dark mode.",
                                  kind="web_app", features=["Task list", "Dark mode toggle"])


def _renamed(events, stats, draft, name="Hype Product Capture"):
    """A storyboard JSON that is right except that it calls the product after Hype's capture stage."""
    obj = storyboard_to_json(build_heuristic_storyboard(events, stats, StoryOptions(seconds=30), "", draft))
    obj["product"]["name"] = name
    obj["product"]["one_liner"] = "Captures a product's web pages as product_capture events."
    obj["title"] = name
    obj["tagline"] = f"{name}: your app, photographed"
    obj["scenes"][1]["vo"] = "Meet Hype's product capture, your app's camera crew."
    return obj


def test_identity_helpers():
    assert same_product("Tempo", "Tempo — focus timer")
    assert same_product("orbit-notes", "Orbit Notes")
    assert not same_product("Hype Product Capture", "Orbit Notes")
    assert not same_product("Tempo", "Tempora")
    assert toolish_words("Hype Product Capture", "Orbit Notes") == ["hype", "capture", "product capture"]
    assert toolish_words("Hype", "Hype") == []          # a session that built Hype itself
    assert toolish_words("WEBPRODUCT") == ["webproduct"]
    assert replace_name("Meet Hype's product capture, your crew.", "Hype Product Capture",
                        "Orbit Notes") == "Meet Orbit Notes, your crew."


def test_locked_name_survives_a_model_that_renames_the_product():
    events, stats, draft = _webapp()
    bad = _renamed(events, stats, draft)
    llm = FakeLlm(LlmReply(parsed=bad), LlmReply(parsed=bad))          # the repair repeats the mistake
    opts = StoryOptions(seconds=30, product_name_locked=True)
    rep = generate_storyboard_report(llm, "", events, stats, opts, draft)
    sb = rep.storyboard
    assert sb.product.name == "Focusfox" and sb.title == "Focusfox"
    assert sb.product.one_liner == draft.one_liner
    assert "Hype" not in sb.tagline and "Focusfox" in sb.tagline
    assert sb.scenes[1].vo == "Meet Focusfox, your app's camera crew."
    assert not any("hype" in (s.vo + s.label).lower() for s in sb.scenes)
    # the rename is an error: the model was asked to repair it, with the right name in the problem list
    assert len(llm.calls) == 2
    assert "'Focusfox'" in llm.calls[1]["input_text"] and "product_renamed" not in llm.calls[1]["input_text"]
    assert "name (fixed): Focusfox" in llm.calls[0]["input_text"]


def test_toolish_name_is_replaced_even_without_the_lock():
    events, stats, draft = _webapp()
    sb = storyboard_from_json(_renamed(events, stats, draft, "WEBPRODUCT"), source="llm", mode="product")
    res = validate_storyboard(sb, SessionFacts(events, stats), 30, "product", draft=draft, lock_name=False)
    assert res.storyboard.product.name == "Focusfox" and res.storyboard.title == "Focusfox"
    assert any(i.code == "product_renamed" for i in res.errors)


def test_the_model_may_tidy_or_correct_a_weak_name():
    events, stats, draft = _webapp()
    facts = SessionFacts(events, stats)
    obj = _renamed(events, stats, draft, "Focusfox")
    long_draft = Product(name="Focusfox — pomodoro timer", kind="web_app")
    res = validate_storyboard(storyboard_from_json(obj, source="llm", mode="product"), facts, 30, "product",
                              draft=long_draft, lock_name=True)
    assert res.storyboard.product.name == "Focusfox" and not res.errors     # shortened, same product
    weak = Product(name="focusfox-app", kind="web_app")                    # a directory name
    obj2 = _renamed(events, stats, draft, "Pomodoro Fox")
    res2 = validate_storyboard(storyboard_from_json(obj2, source="llm", mode="product"), facts, 30, "product",
                               draft=weak, lock_name=False)
    assert res2.storyboard.product.name == "Pomodoro Fox"


def test_no_draft_keeps_the_model_name_with_a_warning():
    events, stats, draft = _webapp()
    sb = storyboard_from_json(_renamed(events, stats, draft), source="llm", mode="product")
    res = validate_storyboard(sb, SessionFacts(events, stats), 30, "product")
    assert res.storyboard.product.name == "Hype Product Capture"
    assert any(i.code == "product_name_toolish" and i.severity == "warning" for i in res.issues)


def test_pipeline_locks_strong_names_only():
    class B:
        def __init__(self):
            self.product = Product(name="Orbit Notes")
            self.product_evidence = {"names": [{"name": "Orbit Notes", "source": "<title> of app/index.html",
                                                "score": 0.7}]}
    b = B()
    assert product_name_locked(b)
    b.product_evidence = {"names": [{"name": "Orbit Notes", "source": "project directory", "score": 0.45}]}
    assert not product_name_locked(b)
    assert product_name_locked(b, {"name": "Orbit Notes"})            # the brief names it
    b.product = Product(name="")
    assert not product_name_locked(b, {"name": "x"})


def test_title_brand_part_names_the_product():
    from showreel_core.contracts import Event
    from showreel_core.session.product import infer_product
    html = ["<!doctype html>", "<html><head><title>Tempo — focus timer</title></head>", "<body></body></html>"]
    events = [Event(id="e0", t=1.0, kind="file_write", tool="write_file", title="app/index.html", summary="",
                    data={"path": "app/index.html", "lines": html, "lang": "html", "new_file": True})]
    rep = infer_product(events, {})
    assert rep.product.name == "Tempo"
    assert [n["name"] for n in rep.evidence["names"]][:2] == ["Tempo", "Tempo — focus timer"]
    assert json.dumps(rep.evidence["names"][0])
