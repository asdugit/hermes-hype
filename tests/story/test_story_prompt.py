"""Prompt construction: modes, budgets, catalogue, bounded input."""
import pytest

from showreel_core.contracts import Product, SceneType
from showreel_core.story.facts import SessionFacts
from showreel_core.story.options import StoryOptions
from showreel_core.story.prompt import (INDEX_MAX_CHARS, build_input, build_instructions, build_repair_input)
from showreel_core.story.rules import narration_budget

from story_synth import SESSIONS


@pytest.mark.parametrize("mode,marker", [("product", "launch trailer"), ("making_of", "making-of (lore)"),
                                         ("speedrun", "build as a speedrun"), ("lore", "making-of (lore)")])
def test_instructions_follow_the_mode(mode, marker):
    text = build_instructions(StoryOptions(seconds=60, mode=mode, style="pixel"))
    assert marker in text
    assert "16-bit quest" in text
    assert f"about {narration_budget(60, 'making_of' if mode == 'lore' else mode)} words" in text
    for st in SceneType:
        assert f"\n{st.value} | " in text
    assert "Never invent a feature" in text


def test_lengths_pick_templates():
    assert "About 7 scenes" in build_instructions(StoryOptions(seconds=30))
    assert "About 15 scenes" in build_instructions(StoryOptions(seconds=90))
    assert "burned-in captions" in build_instructions(StoryOptions(voice=False))


def test_input_has_stats_index_and_product_draft(coding):
    events, stats = coding
    facts = SessionFacts(events, stats)
    draft = Product(name="Tally", one_liner="Budgets from bank exports", kind="cli", features=["Monthly summary"])
    text = build_input("", facts, StoryOptions(seconds=60), draft)
    assert 'tests_passed = 14 tests passing  (say "fourteen")' in text
    assert "e14 | 6:40 | terminal" in text
    assert "e20 | 7:32 | product_capture" in text and "full page" in text
    assert "name: Tally" in text and '"Monthly summary"' in text
    assert "lines: L12 class Transaction:; L19 def parse_amount" in text  # line hints for focus_lines


def test_huge_session_input_is_bounded():
    events, stats = SESSIONS["huge"]()
    text = build_input("", SessionFacts(events, stats), StoryOptions(seconds=90))
    index = text.split("# REFERENCE INDEX")[1].split("# SESSION DIGEST")[0]
    assert len(index) <= INDEX_MAX_CHARS + 400
    assert len(text) < 60000


def test_repair_input_quotes_problems():
    text = build_repair_input("ORIGINAL", {"title": "x"}, ["$.scenes[2].refs[0]: event 'e99' does not exist"])
    assert text.startswith("ORIGINAL")
    assert '"title": "x"' in text and "- $.scenes[2].refs[0]: event 'e99' does not exist" in text
