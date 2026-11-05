"""Semantic validation and safe auto-fixes."""
import copy

from showreel_core.contracts import Product, SceneType, Storyboard, StoryScene
from showreel_core.story.facts import SessionFacts
from showreel_core.story.validate import validate_storyboard

T = SceneType


def board(scenes, mode="product", **kw):
    product = kw.pop("product", Product(name="Tally", one_liner="Monthly budgets from bank exports", kind="cli",
                                        features=["Monthly summary table"]))
    return Storyboard(title=kw.pop("title", "Tally"), tagline=kw.pop("tagline", "Budgets from bank exports"),
                      scenes=scenes, cta=kw.pop("cta", "python -m tally summary"), mode=mode, product=product, **kw)


def base_scenes():
    return [StoryScene(T.HOOK, ["e21"], "", "Your spending, sorted"),
            StoryScene(T.TITLE, [], "Meet Tally, a tiny budget tool.", ""),
            StoryScene(T.TERMINAL, ["e14"], "Point it at your exports and every month comes back sorted.", "Monthly"),
            StoryScene(T.SCROLL, ["e20"], "", "The report"),
            StoryScene(T.FEATURE, ["e17"], "", "Monthly summary table", {"feature": "Monthly summary table"}),
            StoryScene(T.STATS, [], "", "Built with Hermes", {"stat_keys": ["tests_passed", "files_created"]}),
            StoryScene(T.END, [], "Tally is ready when you are.", "")]


def codes(res):
    return {i.code for i in res.issues}


def test_clean_board_has_no_issues(coding_facts):
    res = validate_storyboard(board(base_scenes()), coding_facts, 30)
    assert res.errors == [] and res.viable, [str(i) for i in res.issues]


def test_unknown_ref_and_kind_mismatch_drop_scenes(coding_facts):
    scenes = base_scenes()
    scenes.insert(3, StoryScene(T.CODE, ["e99"], "", "Ghost"))
    scenes.insert(4, StoryScene(T.TERMINAL, ["e5"], "", "Wrong kind"))
    res = validate_storyboard(board(scenes), coding_facts, 30)
    msgs = [str(i) for i in res.errors]
    assert "$.scenes[3].refs[0]: event 'e99' does not exist" in msgs
    assert any(m.startswith("$.scenes[4].refs: TERMINAL needs an event of kind terminal") for m in msgs)
    assert [s.label for s in res.storyboard.scenes].count("Ghost") == 0
    assert all(s.label != "Wrong kind" for s in res.storyboard.scenes)


def test_numbers_must_come_from_the_session(coding_facts):
    scenes = base_scenes()
    scenes[2].vo = "It wrote 2,000 lines in no time. All 14 tests pass."
    res = validate_storyboard(board(scenes), coding_facts, 30)
    assert "number_not_in_session" in codes(res)
    assert res.storyboard.scenes[2].vo == "All fourteen tests pass."


def test_ellipsis_markup_and_word_caps(coding_facts):
    scenes = base_scenes()
    scenes[1].vo = "Meet **Tally**... the budget tool that sorts every purchase you ever made into neat little piles."
    res = validate_storyboard(board(scenes), coding_facts, 30)
    vo = res.storyboard.scenes[1].vo
    assert "..." not in vo and "*" not in vo and " ," not in vo
    assert vo == "Meet Tally, the budget tool."  # cut at a clause boundary, never mid-phrase
    assert {"ellipsis", "markup", "vo_long"} <= codes(res)


def test_focus_lines_clamped(coding_facts):
    scenes = base_scenes()
    scenes.insert(3, StoryScene(T.CODE, ["e5"], "", "parser.py", {"focus_lines": [30, 500]}))
    res = validate_storyboard(board(scenes), coding_facts, 60)
    code = next(s for s in res.storyboard.scenes if s.type == T.CODE)
    n = len(coding_facts.by_id["e5"].data["lines"])
    assert code.extra["focus_lines"] == [30, min(n, 47)]


def test_structure_singletons_order_and_end(coding_facts):
    scenes = base_scenes()[:-1]  # no END
    scenes.append(StoryScene(T.HOOK, ["e17"], "", "Second hook"))
    scenes.insert(0, scenes.pop(1))  # TITLE before HOOK
    res = validate_storyboard(board(scenes), coding_facts, 30)
    types = [s.type for s in res.storyboard.scenes]
    assert types[0] == T.HOOK and types[1] == T.TITLE and types[-1] == T.END
    assert types.count(T.HOOK) == 1
    assert {"duplicate_singleton", "order", "missing_end"} <= codes(res)


def test_type_share_limit(coding_facts):
    scenes = base_scenes()[:2] + [StoryScene(T.TERMINAL, [r], "", "") for r in ("e3", "e10", "e14", "e15")] + \
        base_scenes()[-1:]
    res = validate_storyboard(board(scenes), coding_facts, 30)
    n = len(res.storyboard.scenes)
    assert sum(s.type == T.TERMINAL for s in res.storyboard.scenes) <= max(1, int(0.35 * n))
    assert "type_share" in codes(res)


def test_quotes_are_verbatim(coding_facts):
    scenes = base_scenes()
    scenes.insert(5, StoryScene(T.CALLOUT, ["e19"], "", "", {"quote_ref": "e19", "quote": "refunds NOW net out"}))
    scenes.insert(6, StoryScene(T.CALLOUT, ["e0"], "", "", {"quote_ref": "e0", "quote": "make it sparkle"}))
    res = validate_storyboard(board(scenes), coding_facts, 60)
    quotes = [s.extra["quote"] for s in res.storyboard.scenes if s.type == T.CALLOUT]
    assert quotes[0] == "Refunds now net out"
    source = coding_facts.by_id["e0"].data["text"]
    assert quotes[1] in source  # replaced with a real span of the same event
    assert "quote_not_found" in codes(res)


def test_product_grounding(coding_facts):
    product = Product(name="Tally", one_liner="Sorts 9000 receipts a second", kind="cli",
                      urls=["https://tally.example.com"], run_commands=["python -m tally summary samples/", "rm -rf /"],
                      features=["Monthly summary table", "AI-powered insights", "Blockchain sync"])
    res = validate_storyboard(board(base_scenes(), product=product), coding_facts, 30)
    p = res.storyboard.product
    assert p.features == ["Monthly summary table"]
    assert p.run_commands == ["python -m tally summary samples/"]
    assert p.urls == [] and p.one_liner == ""
    assert {"feature_ungrounded", "product_unbacked", "number_not_in_session"} <= codes(res)


def test_product_film_keeps_build_story_short_and_opens_on_product(coding_facts):
    scenes = [StoryScene(T.HOOK, ["e5"], "", "Code"), StoryScene(T.TITLE, [], "", ""),
              StoryScene(T.PROBLEM, ["e0"], "", "The ask"), StoryScene(T.PLAN, ["e2"], "", "Plan"),
              StoryScene(T.CODE, ["e6"], "", "categorize.py"), StoryScene(T.DIFF, ["e9"], "", "fix"),
              StoryScene(T.FEATURE, ["e17"], "", "Monthly summary table"),
              StoryScene(T.STATS, [], "", "", {"stat_keys": ["tests_passed"]}), StoryScene(T.END, [], "", "")]
    res = validate_storyboard(board(scenes), coding_facts, 60)
    assert res.storyboard.scenes[0].refs[0] in ("e21", "e20", "e17")  # swapped to a product visual
    assert "build_heavy" in codes(res) and "hook_not_product" in codes(res)


def test_making_of_runs_chronologically(coding_facts):
    scenes = [StoryScene(T.TITLE, [], "", ""), StoryScene(T.TERMINAL, ["e10"], "", "green"),
              StoryScene(T.PROBLEM, ["e0"], "", "ask"), StoryScene(T.TERMINAL, ["e8"], "", "red"),
              StoryScene(T.STATS, [], "", "", {"stat_keys": ["tests_passed"]}), StoryScene(T.END, [], "", "")]
    res = validate_storyboard(board(scenes, mode="making_of"), coding_facts, 30)
    refs = [s.refs[0] for s in res.storyboard.scenes if s.refs]
    assert refs == ["e0", "e8", "e10"]
    assert "chronology" in codes(res)


def test_speedrun_splits(coding):
    events, stats = coding
    facts = SessionFacts(events, stats, timestamps=True)
    scenes = [StoryScene(T.TITLE, [], "", ""),
              StoryScene(T.CODE, ["e5"], "", "", {"split": "First file"}),
              StoryScene(T.TERMINAL, ["e8"], "", "", {"split": "A very long split label indeed"}),
              StoryScene(T.TERMINAL, ["e10"], "Tests go green at the four minute mark.", ""),
              StoryScene(T.SCREEN, ["e17"], "", ""),
              StoryScene(T.END, [], "Final time, seven minutes and thirty-two seconds.", "")]
    res = validate_storyboard(board(scenes, mode="speedrun"), facts, 30)
    splits = [(s.refs[0], s.extra["split"]) for s in res.storyboard.scenes if s.extra.get("split")]
    assert 4 <= len(splits) <= 7
    assert all(len(label) <= 18 for _, label in splits)
    times = [facts.by_id[r].t for r, _ in splits]
    assert times == sorted(times) and len(set(times)) == len(times)
    assert res.errors == []  # minute marks and the final time are allowed numbers in a speedrun


def test_url_accent_and_input_not_mutated(coding_facts):
    sb = board(base_scenes(), url="https://not-in-session.example", accent_hint="lime")
    before = copy.deepcopy(sb)
    res = validate_storyboard(sb, coding_facts, 30)
    assert res.storyboard.url == "" and res.storyboard.accent_hint == ""
    assert sb == before
