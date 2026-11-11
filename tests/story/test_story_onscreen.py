"""On-screen hygiene for strangers' sessions (W5 polish-2): the END command is the product's own launch/install
command or none, no loopback address and no machine path on screen, SCROLL only on the product's real long page.
All sessions here are synthetic."""
import pytest

from showreel_core.contracts import Event, Product, SceneType, Stats, Storyboard, StoryScene
from showreel_core.story.facts import SessionFacts
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.onscreen import (
    approved_cta,
    display_cmd,
    display_path,
    end_command,
    launch_command,
    looks_like_command,
    project_root,
    scrub_film,
)
from showreel_core.story.options import StoryOptions
from showreel_core.story.timing import solve_timeline
from showreel_core.story.validate import validate_storyboard

T = SceneType
ROOT = "~/work/tempo"


def _ev(i, kind, data, t=None, ok=True, title=""):
    return Event(f"e{i}", float(t if t is not None else i * 10), kind, "", title or kind, "", data, ok=ok)


def _term(i, cmd, out=("done",), shell=None, ok=True):
    d = {"cmd": cmd, "output_lines": list(out), "exit_code": 0 if ok else 1}
    if shell:
        d["shell"] = shell
    return _ev(i, "terminal", d, ok=ok)


def _cap(i, kind, size, url, title="Tempo", viewport=(1440, 900)):
    return _ev(i, "product_capture", {"path": f"D:/jobs/x/capture/web/{title.lower()}/{kind}_{i}.png", "url": url,
                                      "kind": kind, "size": list(size), "viewport": list(viewport), "dpr": 1.0,
                                      "full_page": kind in ("full", "mobile_full"), "page_title": title},
               title=f"{title} · {kind}")


def _write(i, path, lines):
    return _ev(i, "file_write", {"path": path, "lines": list(lines), "lang": "html"})


# ------------------------------------------------------------------------------------------- commands

@pytest.mark.parametrize("cmd,shell,want", [
    ("from pathlib import Path", "python", ""),                                   # an execute_code script
    ("from patchlib import patch", "", ""),                                       # a code line, any shell
    ("python -c \"import x; x.run()\"", "", ""),
    ("cd ~/work/tempo && HYPE_SLOTS=C:/x ~/work/.venv/Scripts/python.exe -m pytest tests/ -q", "", ""),
    ("python -m http.server 8765 --bind 127.0.0.1", "", "python -m http.server 8765"),
    ("cd app && npm install && npm run dev", "", "npm run dev"),
    ("timeout 300 python app.py --port 5000 > log.txt 2>&1 &", "", "python app.py --port 5000"),
    ("npm run build", "", ""),
    ("python ~/scratch/probe.py", "", ""),                                          # a machine path
    ("python tests/serve_fixture.py", "", ""),
    ("git status", "", ""),
    ("pip install -r requirements.txt", "", ""),
    ("npx serve focusfox", "", "npx serve focusfox"),
    ("python -m tally summary samples/", "", "python -m tally summary samples/"),
])
def test_launch_command_is_never_code_or_shell_noise(cmd, shell, want):
    assert launch_command(cmd, shell=shell) == want


def test_cta_word_lines_are_not_commands():
    assert looks_like_command("from patchlib import patch")
    assert looks_like_command("python -m http.server 8765")
    assert not looks_like_command("Read the code and run it locally")
    assert not looks_like_command("Open it at Tempo")


def test_execute_code_session_ends_with_no_command():
    """The real bug: every 'run' was an execute_code script whose first line became the END command."""
    events = [
        _ev(0, "user_prompt", {"text": "build me a notes app called Orbit Notes"}),
        _write(1, "~/work/orbit/index.html", ["<!doctype html>", "<title>Orbit Notes</title>", "<h1>Orbit Notes</h1>"]),
        _term(2, "from pathlib import Path", ("wrote 3 files",), shell="python"),
        _term(3, "from pathlib import Path", ("ok",), shell="python"),
        _term(4, "cd ~/work/orbit && FOO=1 ~/work/.venv/Scripts/python.exe -m pytest -q", ("5 passed in 0.1s",)),
        _cap(5, "viewport", (1440, 900), "~/work/orbit/index.html", "Orbit Notes"),
    ]
    stats = Stats(duration_s=600, tests_passed=5, files_created=1)
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=30))
    assert "from" not in sb.cta and "import" not in sb.cta
    assert sb.product is not None and not any("import" in c for c in sb.product.run_commands)
    res = validate_storyboard(sb, SessionFacts(events, stats), 30, "product")
    assert res.storyboard.cta == ""                       # no product command: the END shows name + tagline
    sb2 = res.storyboard
    sb2.tagline = sb2.tagline or "Notes that stay in orbit"
    tl = solve_timeline(sb2, events, stats, {}, 120.0, 30, "16:9", 30, 1920, 1080, 1)
    end = next(s for s in tl.scenes if s.type == T.END)
    assert end.data["cta"] == "" and end.data["tagline"] == sb2.tagline


def _tempo_events():
    return [
        _ev(0, "user_prompt", {"text": "build a focus timer called Tempo"}),
        _write(1, f"{ROOT}/index.html", ["<!doctype html>", "<title>Tempo</title>"]),
        _write(2, f"{ROOT}/README.md", ["# Tempo", "", "A focus timer.", "", "```bash", "npm start", "```"]),
        _term(3, f"cd {ROOT} && python -m http.server 8765 --bind 127.0.0.1",
              ("Serving HTTP on 127.0.0.1 port 8765 (http://127.0.0.1:8765/) ...",)),
        _term(4, "from pathlib import Path", ("ok",), shell="python"),
        _cap(5, "viewport", (1440, 900), "http://127.0.0.1:8765/"),
        _cap(6, "full", (1440, 2400), "http://127.0.0.1:8765/"),
    ]


def test_model_cta_must_be_the_products_own_command():
    events = _tempo_events()
    facts = SessionFacts(events, Stats(duration_s=600))
    served = f"cd {ROOT} && python -m http.server 8765 --bind 127.0.0.1"
    product = Product(name="Tempo", kind="web_app", run_commands=[served])
    assert approved_cta("python -m http.server 8765", product, facts) == "python -m http.server 8765"
    assert approved_cta("$ python -m http.server 8765", product, facts) == "python -m http.server 8765"
    assert approved_cta("from patchlib import patch", product, facts) == ""
    assert approved_cta("npm run dev", product, facts) == ""          # never run, not in any product file
    assert approved_cta("npm start", product, facts, trusted=["npm start"]) == "npm start"   # README usage
    assert end_command(product, facts) == "python -m http.server 8765"

    def board(cta):
        return Storyboard(title="Tempo", tagline="A focus timer", cta=cta, mode="product", product=product,
                          scenes=[StoryScene(T.HOOK, ["e5"], "", "Tempo"),
                                  StoryScene(T.TITLE, [], "Meet Tempo. Open it at localhost and start.", ""),
                                  StoryScene(T.SCREEN, ["e5"], "", "Focus at localhost:8765"),
                                  StoryScene(T.END, [], "", "")], url="http://127.0.0.1:8765/")
    for bad in ("from patchlib import patch", "Open it at localhost", "Open it at http://localhost:8765/"):
        out = validate_storyboard(board(bad), facts, 30, "product").storyboard
        assert out.cta == "python -m http.server 8765", bad          # the session's own launch command
        assert out.url == ""
        assert "localhost" not in out.scenes[1].vo and out.scenes[1].vo.startswith("Meet Tempo")
        assert "localhost" not in out.scenes[2].label
    keep = validate_storyboard(board("Try Tempo today"), facts, 30, "product").storyboard
    assert keep.cta == "Try Tempo today"
    pathy = board("Try Tempo today")
    pathy.scenes[2].label = f"Open {ROOT}/index.html"
    assert validate_storyboard(pathy, facts, 30, "product").storyboard.scenes[2].label == "Open index.html"


def test_readme_usage_block_is_a_launch_source():
    from showreel_core.session.product import product_runs
    assert product_runs("readme.md", ["# Tempo", "```bash", "pip install -r requirements.txt", "npm start",
                                      "```", "from tempo import run"]) == ["npm start"]
    assert product_runs("package.json", ['{"name": "tempo", "scripts": {"start": "serve .", "test": "jest"}}']) \
        == ["npm start"]
    assert product_runs("pyproject.toml", ['[project]', 'name = "tally"', '[project.scripts]',
                                           'tally = "tally.cli:main"']) == ["tally"]
    assert product_runs("makefile", ["build:", "\tcc x.c", "run:", "\t./x"]) == ["make run"]
    facts = SessionFacts([_ev(0, "user_prompt", {"text": "x"})], Stats())
    assert end_command(Product(name="Tally", run_commands=["tally"]), facts) == "tally"


# ------------------------------------------------------------------------------------------ paths

def test_project_root_and_display_forms():
    paths = ["~/work/hermes-app/app/main.py", "~/work/hermes-app/tests/test_main.py", "~/work/hermes-app/README.md",
             "~/AppData/Local/hermes/cache/scratch/probe.py"]
    root = project_root(paths, ["cd ~/work/hermes-app && pytest -q"])
    assert root == "~/work/hermes-app"
    assert display_path("~/work/hermes-app/app/main.py", root) == "app/main.py"
    assert display_path("~/AppData/Local/hermes/cache/scratch/probe.py", root) == "\u2026/scratch/probe.py"
    cmd = ("cd ~/work/hermes-app && HYPE_RENDER_SLOTS_DIR=C:/Users/x/slots ~/work/.venv-dev/Scripts/python.exe "
           "-m pytest ~/work/hermes-app/tests/test_main.py -q --durations=10 --maxfail=3 -p no:cacheprovider")
    shown = display_cmd(cmd, root, 64)
    assert shown.startswith("python -m pytest tests/test_main.py -q")
    assert len(shown) <= 64 and shown.endswith("\u2026") and "~" not in shown and "HYPE" not in shown
    assert display_cmd("curl -s http://127.0.0.1:8765/api/stats", root) == "curl -s \u2026/api/stats"
    # the rest of the command stays verbatim (';' and pipes keep their meaning); one ellipsis, even for a script
    long = ("cd /d/work/app && node --test < /dev/null 2>&1 | grep -E '^# (tests|pass)'; echo \"--- curl\"; "
            "curl -sI http://127.0.0.1:8765/ | tr -d '\\r'")
    shown = display_cmd(long, "/d/work/app", 64)
    assert shown.startswith("node --test < /dev/null 2>&1 | grep -E") and " && " not in shown
    assert shown.count("\u2026") == 1 and len(shown) <= 64
    script = display_cmd("cd ~/work/hermes-app && ~/.venv/Scripts/python.exe - <<'EOF'\nfrom x import y\nEOF", root, 64)
    assert script == "python - <<'EOF' \u2026"
    assert display_path("/usr/bin/bash", root) == "/usr/bin/bash"          # system paths are not machine-specific
    # Git-Bash / WSL spellings of a Windows project folder are the same folder (a real panel printed /d/...)
    win = "D:/work/app"
    assert display_cmd("mkdir -p /d/work/app && cd /d/work/app && ls -la", win) == "mkdir -p app && cd app && ls -la"
    assert display_path("/mnt/d/work/app/src/x.js", win) == "src/x.js"
    assert display_path("d:\\work\\app\\index.html", win) == "index.html"


def test_terminal_and_montage_show_project_relative_paths():
    root = "~/work/tempo"
    events = [_ev(0, "user_prompt", {"text": f"Build a focus timer called Tempo in the current folder ({root})."})]
    for i, f in enumerate(["index.html", "app.js", "style.css", "README.md", "src/components/ring/progress-ring.js"]):
        events.append(_write(i + 1, f"{root}/{f}", ["// " + f, "export const x = 1;"]))
    events.append(_term(9, f"cd {root} && NODE_ENV=test ~/tools/node/node.exe {root}/scripts/check.js --all",
                        (f"checked {root}/src/components/ring/progress-ring.js", "  Local: http://localhost:5173/",
                         "all good")))
    stats = Stats(duration_s=600, files_created=5)
    sb = Storyboard(title="Tempo", tagline="A focus timer", cta="", mode="making_of",
                    product=Product(name="Tempo", kind="web_app"),
                    scenes=[StoryScene(T.HOOK, ["e9"], "", "Tempo"),
                            StoryScene(T.PROBLEM, ["e0"], "", "The ask"),
                            StoryScene(T.MONTAGE, ["e1", "e2", "e3", "e4", "e5"], "", "Files",
                                       {"montage_refs": ["e1", "e2", "e3", "e4", "e5"]}),
                            StoryScene(T.TERMINAL, ["e9"], "", "Check"),
                            StoryScene(T.END, [], "", "")])
    tl = solve_timeline(sb, events, stats, {}, 120.0, 30, "16:9", 30, 1920, 1080, 1)
    ask = next(s for s in tl.scenes if s.type == T.PROBLEM).data
    assert ask["text"] == "Build a focus timer called Tempo in the current folder (tempo)."
    term = next(s for s in tl.scenes if s.type == T.TERMINAL).data
    assert term["cmd"] == "node scripts/check.js --all"
    assert term["output"] == ["checked src/components/ring/progress-ring.js", "all good"]
    items = next(s for s in tl.scenes if s.type == T.MONTAGE).data["items"]
    args = [it["arg"] for it in items]
    assert "src/components/ring/progress-ring.js" in args and "index.html" in args
    assert all("~" not in a and len(a) <= 40 for a in args)


# ------------------------------------------------------------------------------------------ film

def test_scrub_film_covers_quick_and_customize_text():
    film = {"shots": [{"id": "s01", "scene": "kit:launch/SCREEN",
                       "params": {"image": {"asset": "m0", "url": "http://127.0.0.1:8765/", "w": 1, "h": 1}}},
                      {"id": "s02", "scene": "kit:launch/END", "params": {"cta": "Open it at localhost",
                                                                         "title": "Tempo"}}],
            "overlays": [{"id": "o", "scene": "kit:type/end-lockup", "params": {"url": "localhost:5173"}}],
            "captions": [{"t0": 0, "t1": 1, "text": "Open it at localhost:8765 today."}]}
    fixes = scrub_film(film, name="Tempo")
    assert fixes and "localhost" not in str(film) and "127.0.0.1" not in str(film)
    assert film["shots"][0]["params"]["image"]["url"] == ""
    assert film["shots"][0]["params"]["image"]["asset"] == "m0"
    assert film["shots"][1]["params"]["cta"] == "Open it at Tempo"


# ------------------------------------------------------------------------------------------ scroll

def test_scroll_needs_the_products_real_long_page():
    url = "http://127.0.0.1:8765/"
    shell = "~/work/tempo/tests/fixtures/shell.html"
    events = [_ev(0, "user_prompt", {"text": "build a focus timer called Tempo"}),
              _cap(1, "viewport", (1440, 900), url),
              _cap(2, "full", (1440, 900), url),                       # a 'full page' one screen tall
              _cap(3, "viewport", (1440, 900), shell, "Dashboard"),
              _cap(4, "full", (1440, 2800), shell, "Dashboard"),        # long, but a test fixture page
              _cap(5, "full", (1440, 2400), url)]
    facts = SessionFacts(events, Stats(duration_s=600))
    prod = Product(name="Tempo", kind="web_app")

    def check(ref):
        sb = Storyboard(title="Tempo", tagline="A focus timer", cta="", mode="product", product=prod,
                        scenes=[StoryScene(T.HOOK, ["e1"], "", "Tempo"), StoryScene(T.TITLE, [], "", ""),
                                StoryScene(T.SCROLL, [ref], "", "The page", {"scroll": [0, 1]}),
                                StoryScene(T.END, [], "", "")])
        return validate_storyboard(sb, facts, 30, "product").storyboard.scenes[2]
    short = check("e2")
    assert short.type == T.SCREEN and short.refs == ["e1"] and "scroll" not in short.extra
    fixture = check("e4")
    assert fixture.type == T.SCREEN and fixture.refs == ["e1"]
    real = check("e5")
    assert real.type == T.SCROLL and real.refs == ["e5"]
