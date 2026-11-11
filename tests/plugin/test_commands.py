"""``/hype`` argument parsing: free word order, actions, Directed free text and hints."""
from __future__ import annotations

import pytest

from showreel_core.commands import HELP, describe, parse, styles_text
from showreel_core.config import Options, StyleInfo

STYLES = ["launch", "pixel", "terminal", "blueprint", "cinematic"]


def p(raw: str, **kw):
    return parse(raw, styles=STYLES, **kw)


def test_users_example_is_directed_with_style_pixel() -> None:
    raw = "pixel but transition into a different style mid way through, goal is to sell the product"
    cmd = p(raw)
    o = cmd.options
    assert cmd.action == "render" and cmd.directed
    assert o.direction == raw                      # the Director gets the user's words verbatim
    assert o.style == "pixel" and "style" in o.explicit
    assert o.mode == "product" and "mode" not in o.explicit   # "...the product" is prose, not a mode word


def test_empty_is_the_default_product_trailer() -> None:
    cmd = p("")
    assert cmd.action == "render" and not cmd.directed
    assert (cmd.options.mode, cmd.options.style, cmd.options.seconds, cmd.options.aspects) == \
        ("product", "launch", 60, ["16:9"])


@pytest.mark.parametrize(("raw", "mode"), [
    ("lore", "making_of"), ("bts", "making_of"), ("process", "making_of"), ("making-of", "making_of"),
    ("speedrun", "speedrun"), ("any%", "speedrun"), ("trailer", "product"), ("LORE", "making_of"),
])
def test_mode_aliases(raw: str, mode: str) -> None:
    cmd = p(raw)
    assert cmd.options.mode == mode and not cmd.directed


def test_full_grammar_in_any_order() -> None:
    for raw in ("speedrun pixel 60 vertical", "vertical 60 pixel speedrun", "60 vertical speedrun pixel"):
        o = p(raw).options
        assert (o.mode, o.style, o.seconds, o.aspects, o.directed) == ("speedrun", "pixel", 60, ["9:16"], False)


@pytest.mark.parametrize(("raw", "secs"), [
    ("30", 30), ("90", 90), ("45s", 45), ("45sec", 45), ("60 seconds", 60), ("--seconds 75", 75),
    ("--seconds=40", 40), ("seconds=50", 50), ("2m", 120), ("1min", 60), ("--length 90", 90),
])
def test_lengths(raw: str, secs: int) -> None:
    cmd = p(raw)
    assert cmd.options.seconds == secs and not cmd.directed


def test_out_of_range_numbers_are_text() -> None:
    cmd = p("5")
    assert cmd.directed and cmd.options.seconds == 60


@pytest.mark.parametrize(("raw", "secs"), [
    ("--seconds 5", 15), ("--seconds=999", 180), ("seconds=5", 15), ("pixel 10s vertical", 15), ("500 seconds", 180),
    ("4m", 180), ("--length 0", 15),
])
def test_explicit_lengths_out_of_range_are_clamped_with_a_note(raw: str, secs: int) -> None:
    """An explicit length (flag, key=, unit) outside 15-180 s is clamped and said, never a Directed film whose
    direction is the flag itself."""
    cmd = p(raw)
    assert not cmd.directed and cmd.options.seconds == secs
    assert any("15-180" in m for m in cmd.messages)


@pytest.mark.parametrize("raw", ["--seconds", "--seconds abc", "seconds=abc", "--style", "--style=", "pixel --style",
                                 "mode=xyz", "--effort ultra", "engine=gpu"])
def test_option_words_with_bad_values_are_ignored_with_a_note(raw: str) -> None:
    cmd = p(raw)
    assert cmd.action == "render" and not cmd.directed and cmd.options.direction == ""
    assert any("ignored" in m for m in cmd.messages)


def test_out_of_range_length_inside_prose_is_not_a_hint() -> None:
    o = p("in 5 seconds it builds, make it pop").options
    assert o.directed and o.seconds == 60


@pytest.mark.parametrize("raw", ['""', "...", "\u200b", "\ufeff \u2060"])
def test_quotes_punctuation_or_invisible_characters_alone_are_the_default_film(raw: str) -> None:
    cmd = p(raw)
    assert not cmd.directed and cmd.options.direction == ""
    assert p("\u200bpixel").options.style == "pixel"
    assert p("\U0001F468\u200d\U0001F4BB hacker vibe").options.direction == "\U0001F468\u200d\U0001F4BB hacker vibe"


@pytest.mark.parametrize(("raw", "aspects"), [
    ("vertical", ["9:16"]), ("9:16", ["9:16"]), ("both", ["16:9", "9:16"]), ("--both", ["16:9", "9:16"]),
    ("--vertical", ["9:16"]), ("square", ["1:1"]), ("landscape", ["16:9"]), ("16:9 vertical", ["16:9", "9:16"]),
])
def test_aspects(raw: str, aspects: list[str]) -> None:
    assert p(raw).options.aspects == aspects


@pytest.mark.parametrize("raw", ["mute", "no-voice", "--no-voice", "silent", "captions"])
def test_voice_off(raw: str) -> None:
    o = p(raw).options
    assert o.voice is False and not o.directed


def test_effort_preview_and_flags() -> None:
    o = p("max lore cinematic preview").options
    assert (o.effort, o.mode, o.style, o.preview) == ("max", "making_of", "cinematic", True)
    o = p("--style terminal --mode speedrun --effort quick --preview").options
    assert (o.style, o.mode, o.effort, o.preview) == ("terminal", "speedrun", "quick", True)


def test_decades_and_inner_numbers_stay_prose() -> None:
    o = p("make it feel like the 90s, 60 seconds, vertical").options
    assert o.directed and o.seconds == 60 and o.aspects == ["9:16"]
    o = p("sell 100 units of it").options
    assert o.directed and o.seconds == 60


def test_inner_style_words_are_hints_and_style_nouns_win() -> None:
    o = p("show the terminal output in cinematic style").options
    assert o.directed and o.style == "cinematic"
    assert o.hints["styles"] == ["cinematic", "terminal"]
    assert "style" not in o.explicit


def test_inner_weak_aspect_words_do_not_change_aspect() -> None:
    o = p("zoom in on the square logo then the wide dashboard").options
    assert o.directed and o.aspects == ["16:9"] and "aspects" not in o.hints


def test_suffix_options_after_free_text() -> None:
    o = p("make it pop for launch day 30 vertical mute").options
    assert o.directed and (o.seconds, o.aspects, o.voice) == (30, ["9:16"], False)


def test_typo_style_is_corrected_with_a_message() -> None:
    cmd = p("pixle")
    assert not cmd.directed and cmd.options.style == "pixel"
    assert cmd.messages and "pixel" in cmd.messages[0]


def test_single_unknown_word_is_a_direction() -> None:
    cmd = p("neon")
    assert cmd.directed and cmd.options.direction == "neon"


def test_second_style_is_kept_as_hint() -> None:
    cmd = p("pixel terminal")
    assert cmd.options.style == "pixel" and cmd.options.hints["styles"] == ["terminal"] and cmd.messages


@pytest.mark.parametrize(("raw", "action", "ref"), [
    ("styles", "styles", ""), ("status", "status", ""), ("status 20261106-120000-ab12", "status", "20261106-120000-ab12"),
    ("cancel", "cancel", ""), ("cancel ab12", "cancel", "ab12"), ("help", "help", ""), ("?", "help", ""),
])
def test_actions(raw: str, action: str, ref: str) -> None:
    cmd = p(raw)
    assert cmd.action == action and cmd.job_ref == ref


def test_action_words_inside_text_are_directions() -> None:
    assert p("help me sell it").action == "render"
    assert p("styles that pop").directed
    assert p("cancel culture explained in pixel art please").directed


def test_revise_keeps_notes_verbatim() -> None:
    cmd = p("revise slower start, more product shots")
    assert cmd.action == "revise" and cmd.options.notes == "slower start, more product shots"
    assert p("revise").messages


def test_base_options_are_defaults_not_explicit() -> None:
    base = Options(style="terminal", seconds=90, aspects=["9:16"], voice=False)
    o = p("lore", base=base).options
    assert (o.style, o.seconds, o.aspects, o.voice, o.mode) == ("terminal", 90, ["9:16"], False, "making_of")
    assert o.explicit == ["mode"]


def test_never_raises_on_garbage() -> None:
    for raw in (None, "   ", "--seconds", "--style", "=", "--seconds=abc", "\u2603 \u00e9t\u00e9 9:16", "a" * 5000):
        cmd = parse(raw, styles=STYLES)
        assert cmd.action in ("render", "help")


def test_texts() -> None:
    assert "/hype" in HELP
    o = Options(style="pixel", mode="speedrun", seconds=60, aspects=["16:9", "9:16"], voice=False).normalised()
    assert describe(o) == "pixel speedrun · 60s · 16:9 + 9:16 · music only"
    txt = styles_text({"launch": StyleInfo("launch", blurb="Premium", ready=True),
                       "pixel": StyleInfo("pixel", ready=False)})
    assert "launch" in txt and "falls back to launch): pixel" in txt
