"""The deterministic (no-LLM) storyboard builder on synthetic sessions, all modes."""
import time

import pytest

from showreel_core.contracts import Product, SceneType
from showreel_core.story.facts import SessionFacts, image_of
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.options import StoryOptions
from showreel_core.story.rules import MAX_BUILD_SHARE
from showreel_core.story.schema import storyboard_to_json, validate_schema
from showreel_core.story.validate import scene_role, validate_storyboard

from story_synth import SESSIONS

T = SceneType
MODES = ("product", "making_of", "speedrun")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("seconds", (30, 60, 90))
def test_every_session_yields_a_clean_storyboard(session, mode, seconds):
    name, events, stats = session
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=seconds, mode=mode))
    assert sb.source == "heuristic" and sb.mode == mode
    assert validate_schema(storyboard_to_json(sb)) == []
    facts = SessionFacts(events, stats, timestamps=(mode == "speedrun"))
    res = validate_storyboard(sb, facts, seconds, mode)
    assert res.errors == [], [str(i) for i in res.errors]
    assert res.viable
    assert sb.scenes[-1].type == T.END
    for s in sb.scenes:
        assert all(facts.get(r) is not None for r in s.refs)
    if facts.visuals() or any(e.kind in ("terminal", "file_write", "file_patch") for e in events):
        assert sb.scenes[0].type == T.HOOK


@pytest.mark.parametrize("mode", MODES)
def test_deterministic(mode, coding):
    events, stats = coding
    a = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60, mode=mode))
    b = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60, mode=mode))
    assert storyboard_to_json(a) == storyboard_to_json(b)


def test_product_film_is_about_the_product():
    events, stats = SESSIONS["webapp"]()
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60))
    facts = SessionFacts(events, stats)
    assert sb.product.name == "Focusfox" and sb.title == "Focusfox"
    assert image_of(facts.by_id[sb.scenes[0].refs[0]]) is not None  # opens on the product
    roles = [scene_role(s, facts, sb.product) for s in sb.scenes]
    content = [r for r in roles if r != "frame"]
    assert content.count("build") / len(content) <= MAX_BUILD_SHARE
    features = [s.extra["feature"] for s in sb.scenes if s.type == T.FEATURE]
    assert features and set(features) <= set(sb.product.features)
    assert any(s.type == T.SCROLL for s in sb.scenes)  # the full-page capture scrolls
    assert sb.cta == "npx serve focusfox"


def test_cli_product_demos_real_commands(coding):
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60))
    assert sb.product.name == "Tally"
    assert sb.product.one_liner.startswith("Reads your bank's CSV exports")
    demos = [s.refs[0] for s in sb.scenes if s.type == T.TERMINAL]
    assert "e14" in demos  # the real `tally summary` output


def test_bugfix_product_is_the_fix():
    events, stats = SESSIONS["bugfix"]()
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=30))
    types = [s.type for s in sb.scenes]
    assert T.BEFORE_AFTER in types
    ba = next(s for s in sb.scenes if s.type == T.BEFORE_AFTER)
    assert ba.extra == {"before_ref": "e2", "after_ref": "e4"}


def test_tiny_chat_and_browsing():
    events, stats = SESSIONS["tiny"]()
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=30))
    assert {T.TITLE, T.END} <= {s.type for s in sb.scenes}
    assert any(s.type in (T.CALLOUT, T.PROBLEM) for s in sb.scenes)
    events, stats = SESSIONS["browsing"]()
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60))
    types = {s.type for s in sb.scenes}
    assert not types & {T.CODE, T.DIFF}
    assert T.SCREEN in types or T.FEATURE in types


def test_making_of_tells_the_struggle_in_order(coding):
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60, mode="making_of"))
    facts = SessionFacts(events, stats)
    body = [s for s in sb.scenes if s.refs and s.type not in (T.HOOK,)]
    order = [facts.order[s.refs[len(s.refs) // 2] if s.type == T.MONTAGE else s.refs[0]] for s in body]
    assert order == sorted(order)
    refs = [s.refs[0] for s in body]
    assert refs.index("e8") < refs.index("e9") < refs.index("e10")  # red, fix, green


@pytest.mark.parametrize("name", ("coding", "webapp", "huge"))
def test_speedrun_has_four_to_seven_ordered_splits(name):
    events, stats = SESSIONS[name]()
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60, mode="speedrun"))
    facts = SessionFacts(events, stats, timestamps=True)
    splits = [(facts.by_id[s.refs[0]].t, s.extra["split"]) for s in sb.scenes if s.extra.get("split")]
    assert 4 <= len(splits) <= 7
    assert [t for t, _ in splits] == sorted({t for t, _ in splits})
    assert sb.scenes[-1].vo.startswith("Final time")


def test_product_draft_is_respected(coding):
    events, stats = coding
    draft = Product(name="Tally CLI", one_liner="Budgets from bank exports", kind="cli",
                    features=["Monthly summary table"])
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=30), product=draft)
    assert sb.title == "Tally CLI" and sb.product.kind == "cli"


def test_huge_session_is_fast():
    events, stats = SESSIONS["huge"]()
    t0 = time.perf_counter()
    for mode in MODES:
        sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=90, mode=mode))
        assert len(sb.scenes) <= 22
        montage = [s for s in sb.scenes if s.type == T.MONTAGE]
        assert all(len(s.refs) <= 16 for s in montage)
    assert time.perf_counter() - t0 < 2.0
