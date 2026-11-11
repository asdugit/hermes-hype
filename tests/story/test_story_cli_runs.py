"""UI-less products and honest type: CLI films show real runs, END names the command the session ran, product runs
read from the top, and the agent's verdict on its own work is never a pull-quote (synthetic events only)."""
from __future__ import annotations

from showreel_core.contracts import Event, Product, SceneType as T, Stats, Storyboard, StoryScene
from showreel_core.story.facts import SessionFacts
from showreel_core.story.onscreen import end_command
from showreel_core.story.timing import _terminal
from showreel_core.story.validate import _SELF_PRAISE, validate_storyboard

BARS = [f"{name:<10} {'#' * n} {n}" for name, n in (("alice", 30), ("bob", 22), ("carol", 15), ("dan", 9),
                                                        ("erin", 7), ("frank", 5), ("gina", 4), ("hal", 3),
                                                        ("ivy", 2), ("jo", 2), ("kim", 1), ("lee", 1), ("max", 1),
                                                        ("ned", 1), ("oz", 1), ("pat", 1))]


def _run(i: int, t: float, cmd: str, out: list[str], ok: bool = True) -> Event:
    return Event(f"e{i}", t, "terminal", "terminal", cmd[:60], "", {"cmd": cmd, "output_lines": out,
                                                                     "exit_code": 0 if ok else 1}, ok=ok)


def _cli_facts() -> SessionFacts:
    evs = [
        Event("e0", 0.0, "user_prompt", "", "build a git history CLI", "", {"text": "Build gitpulse, a git history CLI"}),
        Event("e1", 10.0, "file_write", "write_file", "gitpulse.py", "", {"path": "gitpulse.py", "lines": ["import sys"]}),
        _run(2, 20.0, "python gitpulse.py ./sample-repo", ["gitpulse - sample-repo (677 commits)", *BARS]),
        _run(3, 30.0, "python gitpulse.py ./sample-repo --heatmap", ["commits by hour", "Mon ..##..", "Tue .###.."]),
        _run(4, 40.0, "python -m pytest -q", ["12 passed in 0.4s"]),
        _run(5, 50.0, "python gitpulse.py ./sample-repo", ["gitpulse - sample-repo (677 commits)", *BARS]),
        Event("e6", 60.0, "final_answer", "", "done", "", {"text": "Output looks great and correct."}),
    ]
    return SessionFacts(evs, Stats(duration_s=180, files_created=2))


def test_self_praise_is_recognised() -> None:
    for bad in ("Output looks great and correct.", "no build step, no CDN.", "Everything works as expected.",
                "All green.", "The heatmap is now correct."):
        assert _SELF_PRAISE.search(bad), bad
    for ok in ("Refunds now net out", "Every alibi, minute by minute", "make it sparkle", "Build gitpulse"):
        assert not _SELF_PRAISE.search(ok), ok


def test_cli_film_shows_real_runs_and_no_self_praise() -> None:
    facts = _cli_facts()
    product = Product(name="gitpulse", one_liner="Your git history at a glance", kind="cli")
    sb = Storyboard(title="gitpulse", tagline="Your git history at a glance", cta="", mode="product", product=product,
                    scenes=[StoryScene(T.HOOK, ["e2"], "", "Who wrote this repo?"),
                            StoryScene(T.TITLE, [], "", "gitpulse"),
                            StoryScene(T.CALLOUT, ["e6"], "", "", {"quote_ref": "e6", "quote": "Output looks great and correct."}),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    types = [s.type for s in res.storyboard.scenes]
    assert T.CALLOUT not in types                              # the agent grading its own output
    runs = [s.refs[0] for s in res.storyboard.scenes if s.type == T.TERMINAL]
    assert runs and "e4" not in runs                           # a real run of the CLI, never the test run
    assert types.index(T.TERMINAL) == types.index(T.TITLE) + 1   # the demo right after the title
    assert "e2" not in runs                                    # the HOOK's own event is not repeated
    assert len({facts.by_id[r].data["cmd"] for r in runs}) == len(runs) == 2   # distinct commands, the full output


def test_end_names_the_command_the_session_ran() -> None:
    facts = _cli_facts()
    assert end_command(Product(name="gitpulse", kind="cli"), facts) == "python gitpulse.py ./sample-repo"


def test_product_run_reads_from_the_top_tests_from_the_tail() -> None:
    facts = _cli_facts()
    head = _terminal(facts.by_id["e2"], 8)
    assert head["output"][0].startswith("gitpulse - sample-repo") and not head["truncated_top"]
    many = _run(9, 70.0, "python -m pytest -q", [f"test_{i} PASSED" for i in range(20)] + ["20 passed in 1.0s"])
    tail = _terminal(many, 8)
    assert tail["output"][-1] == "20 passed in 1.0s" and tail["truncated_top"]


def test_a_server_start_is_not_a_product_beat() -> None:
    evs = [Event("e0", 0.0, "user_prompt", "", "habit tracker", "", {"text": "Build Streaks, a habit tracker"}),
           _run(1, 5.0, "python -m http.server 8743", ["Background process started"]),
           _run(2, 9.0, "python gitpulse.py ./sample-repo", ["gitpulse - sample-repo (677 commits)", *BARS])]
    facts = SessionFacts(evs, Stats(duration_s=60))
    sb = Storyboard(title="Streaks", tagline="Habits", cta="", mode="product",
                    product=Product(name="Streaks", kind="web_app"),
                    scenes=[StoryScene(T.TITLE, [], "", "Streaks"),
                            StoryScene(T.TERMINAL, ["e1"], "", "One command to launch"),
                            StoryScene(T.TERMINAL, ["e2"], "", "Real output"),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    assert [s.refs for s in res.storyboard.scenes if s.type == T.TERMINAL] == [["e2"]]


def test_install_terminal_is_not_a_product_beat() -> None:
    evs = [Event("e0", 0.0, "user_prompt", "", "retry lib", "", {"text": "Build patience, a retry library"}),
           _run(1, 5.0, "uv pip install -e .", ["warning: Failed to hardlink files", "Installed 3 packages"]),
           _run(2, 9.0, "python gitpulse.py ./sample-repo", ["gitpulse - sample-repo (677 commits)", *BARS])]
    sb = Storyboard(title="patience", tagline="Retries", cta="", mode="product",
                    product=Product(name="patience", kind="library"),
                    scenes=[StoryScene(T.TITLE, [], "", "patience"), StoryScene(T.TERMINAL, ["e1"], "", "Install"),
                            StoryScene(T.TERMINAL, ["e2"], "", "Run"), StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, SessionFacts(evs, Stats(duration_s=60)), 30, "product")
    assert [s.refs for s in res.storyboard.scenes if s.type == T.TERMINAL] == [["e2"]]


def test_browser_game_pictures_are_cards_and_montage_never_prints_asset_paths() -> None:
    from showreel_core.story.facts import picture_frame
    from showreel_core.story.timing import _verbatim_arg
    shot = Event("e3", 4.0, "screenshot", "browser_exec", "shot.png", "",
                 {"src": "~/.config/browser-harness/tmp/shot.png", "url": "http://example.com/game.html",
                  "path": "/data/hype/jobs/j1/assets/e3_shot.png", "asset": True})
    assert picture_frame(shot) == "browser"
    shot.data["frame_hint"] = "card"                 # solve_timeline sets it for kind == game
    assert picture_frame(shot) == "card"
    arg, _ = _verbatim_arg(shot)
    assert arg == "shot.png" and "assets" not in arg


def test_library_film_shows_the_readme_usage_block() -> None:
    from showreel_core.story.timing import _code_window
    readme = ["# patience", "", "Retries with backoff.", "", "```bash", "pip install patience", "```", "",
              "```python", "from patience import retry", "", "@retry(attempts=3, backoff=2.0)", "def fetch():",
              "    return get('/x')", "```"]
    evs = [Event("e0", 0.0, "user_prompt", "", "retry lib", "", {"text": "Build patience, a retry library"}),
           Event("e1", 5.0, "file_write", "write_file", "src/patience/core.py", "",
                 {"path": "src/patience/core.py", "lines": ["def retry(attempts=3):", '    """Args: ..."""', "    pass"]}),
           Event("e2", 9.0, "file_write", "write_file", "README.md", "", {"path": "README.md", "lines": readme})]
    facts = SessionFacts(evs, Stats(duration_s=60))
    sb = Storyboard(title="patience", tagline="Retries", cta="", mode="product",
                    product=Product(name="patience", kind="library"),
                    scenes=[StoryScene(T.TITLE, [], "", "patience"), StoryScene(T.CODE, ["e1"], "", "The decorator"),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    codes = [s for s in res.storyboard.scenes if s.type == T.CODE]
    assert codes[0].refs == ["e2"] and codes[0].extra["focus_lines"] == [10, 14]   # the python block, not bash
    win = _code_window(facts.by_id["e2"], [10, 14], 12)
    assert win["lang"] == "python" and "@retry(attempts=3, backoff=2.0)" in win["lines"]


def test_overlong_strings_are_trimmed_not_rejected() -> None:
    """E18: a 43-char CTA (the session's real run command) threw away a working haiku storyboard twice."""
    from showreel_core.story.generate import trim_overlong
    from showreel_core.story.schema import validate_schema
    obj = {"mode": "product", "title": "Tempo", "tagline": "Focus", "cta": "python -m http.server 8765 --bind 127.0.0.1",
           "product": {"name": "Tempo", "one_liner": "A focus timer " * 12, "kind": "web_app", "urls": [],
                       "entry_files": [], "run_commands": [], "features": [], "hero_event_ids": []},
           "scenes": [{"type": "TITLE", "refs": [], "vo": "", "label": ""}, {"type": "END", "refs": [], "vo": "", "label": ""}]}
    done = trim_overlong(obj)
    assert len(done) == 2 and not [e for e in validate_schema(obj) if "characters" in e.message]
    assert len(obj["cta"]) <= 40 and not obj["cta"].endswith(" ")


def test_readme_code_beats_show_only_a_code_block() -> None:
    """#14: `# Shortly`, `## Features` and backticks were shown as a CODE beat."""
    from showreel_core.story.timing import _code_window
    prose = Event("e1", 1.0, "file_write", "write_file", "README.md", "",
                  {"path": "README.md", "lines": ["# Shortly", "", "## Features", "- short links", "- stats"]})
    usage = Event("e2", 2.0, "file_write", "write_file", "docs/USAGE.md", "",
                  {"path": "docs/USAGE.md", "lines": ["# Usage", "", "```python", "from shortly import shorten",
                                                      "print(shorten('https://example.com'))", "```", "", "More text."]})
    evs = [Event("e0", 0.0, "user_prompt", "", "x", "", {"text": "Build Shortly"}), prose, usage]
    facts = SessionFacts(evs, Stats(duration_s=60))
    sb = Storyboard(title="Shortly", tagline="Links", cta="", mode="product", product=Product(name="Shortly", kind="api"),
                    scenes=[StoryScene(T.TITLE, [], "", "Shortly"), StoryScene(T.CODE, ["e1"], "", "Docs"),
                            StoryScene(T.CODE, ["e2"], "", "Usage", {"focus_lines": [1, 2]}),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    codes = [s for s in res.storyboard.scenes if s.type == T.CODE]
    assert [c.refs for c in codes] == [["e2"]] and codes[0].extra["focus_lines"] == [4, 5]
    win = _code_window(usage, [4, 5], 12)
    assert win["lines"] == ["from shortly import shorten", "print(shorten('https://example.com'))"]
    assert win["lang"] == "python" and win["start"] == 4
