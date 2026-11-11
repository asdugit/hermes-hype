"""Product films carry no tool-call MONTAGE, terminal beats drop tool chatter, and a session that FIXED an existing
project is told as a fix (never 'Introducing ...') (synthetic events only)."""
from __future__ import annotations

from showreel_core.contracts import Event, Product, SceneType as T, Stats, Storyboard, StoryScene
from showreel_core.story.facts import SessionFacts, is_fix_session, is_noise_line
from showreel_core.story.prompt import build_input
from showreel_core.story.timing import _terminal, resolve_scene_data
from showreel_core.story.validate import validate_storyboard


def _run(i: int, t: float, cmd: str, out: list[str], ok: bool = True) -> Event:
    return Event(f"e{i}", t, "terminal", "terminal", cmd[:60], "", {"cmd": cmd, "output_lines": out,
                                                                     "exit_code": 0 if ok else 1}, ok=ok)


def _fix_facts() -> SessionFacts:
    evs = [
        Event("e0", 0.0, "user_prompt", "", "fix tests", "", {"text": "The test suite is failing. Please fix it."}),
        _run(1, 5.0, "python -m pytest -q", ["FAILED tests/test_invoice.py::test_discount", "5 failed, 2 passed"],
             ok=False),
        Event("e2", 10.0, "file_read", "read_file", "invoice.py", "", {"path": "invoicely/invoice.py"}),
        Event("e3", 20.0, "file_patch", "patch", "invoice.py", "", {"path": "invoicely/invoice.py",
                                                                    "action": "update"}),
        _run(4, 30.0, "python -m pytest -q", ["7 passed in 0.01s"]),
        _run(5, 35.0, "git add -A && git commit -m 'Fix discount'",
             ["warning: in the working copy of 'invoicely/invoice.py', LF will be replaced by CRLF the next time Git "
              "touches it", "[main 1a2b3c] Fix discount", " 1 file changed, 3 insertions(+)"]),
        Event("e6", 40.0, "final_answer", "", "done", "", {"text": "Root cause: discount was a percent."}),
    ]
    return SessionFacts(evs, Stats(duration_s=60, files_created=0))


def test_fix_session_is_recognised_and_a_build_is_not() -> None:
    assert is_fix_session(_fix_facts())
    build = [
        Event("e0", 0.0, "user_prompt", "", "lib", "", {"text": "Build patience, a retry library"}),
        Event("e1", 5.0, "file_write", "write_file", "a.py", "", {"path": "src/a.py", "lines": ["x = 1"]}),
        Event("e2", 6.0, "file_write", "write_file", "b.py", "", {"path": "src/b.py", "lines": ["y = 1"]}),
        _run(3, 10.0, "python -m pytest -q", ["1 failed, 3 passed"], ok=False),
        Event("e4", 12.0, "file_patch", "patch", "a.py", "", {"path": "src/a.py", "action": "update"}),
        _run(5, 15.0, "python -m pytest -q", ["4 passed in 0.1s"]),
    ]
    assert not is_fix_session(SessionFacts(build, Stats(duration_s=60, files_created=2)))


def test_fix_film_title_is_not_an_introduction_and_the_model_hears_it() -> None:
    facts = _fix_facts()
    product = Product(name="invoicely", one_liner="Invoice math", kind="library")
    sb = Storyboard(title="invoicely", tagline="Invoice math, finally correct", cta="", mode="product",
                    product=product, scenes=[StoryScene(T.TITLE, [], "", "invoicely")])
    data = resolve_scene_data(sb.scenes[0], sb, facts)
    assert data["eyebrow"] == "Fixed"
    from showreel_core.story.options import StoryOptions
    text = build_input("", facts, StoryOptions(seconds=30))
    assert "FIXED AN EXISTING PROJECT" in text


def test_tool_chatter_is_not_shown_in_a_terminal_beat() -> None:
    assert is_noise_line("warning: in the working copy of 'a.py', LF will be replaced by CRLF the next time")
    assert is_noise_line("warning: Failed to hardlink files; falling back to full copy.")
    assert not is_noise_line("warning: 3 habits have no colour")      # the product's own warning stays
    shown = _terminal(_fix_facts().by_id["e5"], 8)
    assert not any("CRLF" in ln for ln in shown["output"])


def test_product_film_has_no_tool_call_montage() -> None:
    evs = [Event("e0", 0.0, "user_prompt", "", "app", "", {"text": "Build Streaks"})]
    evs += [Event(f"e{i}", float(i), "file_patch", "patch", "styles.css", "", {"path": "styles.css",
                                                                              "action": "update"})
            for i in range(1, 7)]
    facts = SessionFacts(evs, Stats(duration_s=60, files_created=1))
    sb = Storyboard(title="Streaks", tagline="Habits", cta="", mode="product", product=Product(name="Streaks"),
                    scenes=[StoryScene(T.TITLE, [], "", "Streaks"),
                            StoryScene(T.MONTAGE, ["e1", "e2", "e3", "e4"], "", "How it was built",
                                       {"montage_refs": ["e1", "e2", "e3", "e4", "e5"]}),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    assert T.MONTAGE not in [s.type for s in res.storyboard.scenes]
    lore = validate_storyboard(sb, facts, 30, "making_of")
    assert T.MONTAGE in [s.type for s in lore.storyboard.scenes]


def test_a_game_never_shows_a_full_page_capture() -> None:
    def cap(i: int, name: str, vp: list[int], full: bool) -> Event:
        return Event(f"e{i}", float(i), "product_capture", "hype_capture", name, "",
                     {"path": f"capture/web/{name}", "viewport": vp, "full_page": full, "target_kind": "html",
                      "url": "index.html", "page_title": "Brickfall", "label": name}, weight=0.8)
    evs = [Event("e0", 0.0, "user_prompt", "", "game", "", {"text": "Build Brickfall, a breakout game"}),
           cap(1, "desktop_1920x1080.png", [1920, 1080], False), cap(2, "mobile_390x844.png", [390, 844], False),
           cap(3, "mobile_full_390.jpg", [390, 844], True)]
    facts = SessionFacts(evs, Stats(duration_s=60, files_created=1))
    sb = Storyboard(title="Brickfall", tagline="Breakout in neon", cta="", mode="product",
                    product=Product(name="Brickfall", kind="game"),
                    scenes=[StoryScene(T.HOOK, ["e1"], "", "Breakout, reborn"), StoryScene(T.TITLE, [], "", "Brickfall"),
                            StoryScene(T.SCREEN, ["e3"], "", "Pulsing neon title screen"),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    shown = [s.refs[0] for s in res.storyboard.scenes if s.refs]
    assert "e3" not in shown
    web = Storyboard(title="Streaks", tagline="Habits", cta="", mode="product", product=Product(name="Streaks",
                     kind="web_app"), scenes=[StoryScene(T.TITLE, [], "", "Streaks"),
                                              StoryScene(T.SCREEN, ["e3"], "", "The whole page"),
                                              StoryScene(T.END, [], "", "")])
    assert "e3" in [s.refs[0] for s in validate_storyboard(web, facts, 30, "product").storyboard.scenes if s.refs]


def test_agent_working_notes_are_not_pull_quotes() -> None:
    from showreel_core.story.validate import _agent_fragment
    for bad in ("let me remove those from the repo.", "scored 90, saved as new high score", "all three data-flow bugs",
                "Let me look at the tests.", "I'll fix the CSS now."):
        assert _agent_fragment(bad), bad
    for ok in ("flipper-mass correlation r=0.871 overall", "produced 27505.0 instead of 275.05.",
               "Every alibi checks out, minute by minute.", "Discounts were applied as whole numbers."):
        assert not _agent_fragment(ok), ok


def test_process_housekeeping_and_http_headers_are_not_product_beats() -> None:
    from showreel_core.story.facts import is_setup_cmd
    for cmd in ("netstat -ano | grep ':8000'", "taskkill //F //PID 12336", "kill %1", "sleep 2", "ps aux"):
        assert is_setup_cmd(cmd), cmd
    assert not is_setup_cmd("curl -s -X POST localhost/links")
    run = _run(1, 1.0, "curl -i -X POST /links", ["HTTP/1.1 201 Created", "date: Wed, 11 Nov 2026 17:17:26 GMT",
                                                  "server: uvicorn", "content-length: 64",
                                                  "content-type: application/json", '{"code":"aB3x9"}'])
    shown = _terminal(run, 8)["output"]
    assert shown == ["HTTP/1.1 201 Created", "content-type: application/json", '{"code":"aB3x9"}']


def test_escape_code_output_is_never_a_terminal_beat() -> None:
    from showreel_core.story.facts import is_garbled
    garbage = _run(2, 2.0, "python -c 'import gitpulse' | cat -v",
                   ["^[[2mM-bM-^TM-^AM-bM-^TM-^A^[[0m ^[[1m^[[96mCommits per author^[[0m",
                    "  David Lord    ^[[96mM-bM-^VM-^HM-bM-^VM-^H", "  Armin  ^[[93mM-bM-^VM-^H", "^M"])
    clean = _run(3, 3.0, "python gitpulse.py ./sample-repo", ["gitpulse - sample-repo (677 commits)",
                                                               "David Lord   ######## 120", "Armin        ##### 80"])
    assert is_garbled(garbage) and not is_garbled(clean)
    evs = [Event("e0", 0.0, "user_prompt", "", "cli", "", {"text": "Build gitpulse, a git history CLI"}),
           Event("e1", 1.0, "file_write", "write_file", "gitpulse.py", "", {"path": "gitpulse.py", "lines": ["x"]}),
           garbage, clean]
    facts = SessionFacts(evs, Stats(duration_s=60, files_created=1))
    sb = Storyboard(title="gitpulse", tagline="History", cta="", mode="product",
                    product=Product(name="gitpulse", kind="cli"),
                    scenes=[StoryScene(T.TITLE, [], "", "gitpulse"), StoryScene(T.TERMINAL, ["e2"], "", "Colour on"),
                            StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    assert "e2" not in [r for s in res.storyboard.scenes for r in s.refs[:1]]


def test_a_prompt_card_shows_long_urls_short() -> None:
    from showreel_core.story.timing import short_urls
    txt = ("Download the dataset from https://raw.githubusercontent.com/mwaskom/seaborn-data/master/penguins.csv into "
           "this folder, see https://example.com/a.")
    assert short_urls(txt) == ("Download the dataset from raw.githubusercontent.com/\u2026/penguins.csv into this folder, "
                               "see https://example.com/a.")


def test_a_product_without_pictures_shows_its_tests_and_code() -> None:
    code = [f"line {i}" for i in range(3)] + ["def standup(args):", "    entries = load()", "    return fmt(entries)",
                                              "", "def register(ctx):", "    ctx.register_command('standup', standup)"]
    evs = [Event("e0", 0.0, "user_prompt", "", "plugin", "", {"text": "Build a Hermes plugin called standup"}),
           Event("e1", 1.0, "file_write", "write_file", "commands.py", "", {"path": "plugin/commands.py", "lines": code}),
           Event("e2", 2.0, "file_write", "write_file", "test_x.py", "", {"path": "plugin/tests/test_x.py",
                                                                         "lines": code * 3}),
           _run(3, 3.0, "python -m pytest", ["21 passed in 0.3s"]),
           _run(4, 4.0, "hermes plugins validate .", ["ok manifest", "ok isolation"])]
    facts = SessionFacts(evs, Stats(duration_s=60, files_created=2))
    sb = Storyboard(title="standup", tagline="Standups", cta="", mode="product",
                    product=Product(name="standup", kind="other"),
                    scenes=[StoryScene(T.HOOK, ["e4"], "", "Validation passed"), StoryScene(T.TITLE, [], "", "standup"),
                            StoryScene(T.STATS, [], "", "", {"stat_keys": ["files_created"]}), StoryScene(T.END, [], "", "")])
    res = validate_storyboard(sb, facts, 30, "product")
    types = [(s.type, s.refs[:1]) for s in res.storyboard.scenes]
    assert (T.TERMINAL, ["e3"]) in types and (T.CODE, ["e1"]) in types
    assert [t for t, _ in types].index(T.TERMINAL) == [t for t, _ in types].index(T.TITLE) + 1
