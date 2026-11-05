"""Scene lint: forbidden APIs are found with line numbers; comments, strings and allowed uses are not flagged."""
from __future__ import annotations

from pathlib import Path

from showreel_core.film.lint import lint_paths, lint_source, main, tokenize

OK_SCENE = """
import { sr } from '../runtime/showreel.js';
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
// Math.random() in a comment is fine; so is Date.now() here
/* performance.now() and setTimeout(f) in a block comment */
sr.defineScene('custom:ok', {
  layer: '2d',
  describe: 'mentions Math.random and fetch( in a string',
  render(ctx, t) {
    const r = ctx.rng(1);
    const s = `value ${ctx.lerp(0, 1, t)} and Date in text`;
    const re = /fetch\\(/g;
    const dpr = window.devicePixelRatio;
    const c = document.createElement('canvas');
    obj.fetch(1); obj.Date = 3; const o = { Date: 1 };
    ctx.root.style.transition = 'none';
    const ns = 'http://www.w3.org/2000/svg';
    return t / 2 / 3;
  },
});
"""


def rules(src: str, **kw) -> list[tuple[str, int]]:
    return [(i.rule, i.line) for i in lint_source(src, **kw) if i.severity == "error"]


def test_clean_scene_has_no_errors():
    assert rules(OK_SCENE) == []


def test_forbidden_apis_with_lines():
    src = "\n".join([
        "sr.defineScene('custom:x', { render(ctx, t) {",
        "  const a = Math.random();",                    # 2
        "  const b = Date.now(); const c = new Date();",  # 3 (twice)
        "  const d = performance.now();",                 # 4
        "  setTimeout(() => 0, 5); setInterval(f, 1);",   # 5
        "  requestAnimationFrame(f);",                    # 6
        "  fetch('x'); new XMLHttpRequest();",            # 7
        "  new WebSocket('ws://x'); new EventSource('y');",  # 8 (+ url)
        "  import('./x.js'); eval('1'); new Function('a');",  # 9
        "  document.body.appendChild(x); window.foo = 1;",  # 10
        "} });",
    ])
    got = rules(src)
    expect = {("math-random", 2), ("date", 3), ("performance-now", 4), ("settimeout", 5), ("setinterval", 5),
              ("requestanimationframe", 6), ("fetch", 7), ("xmlhttprequest", 7), ("websocket", 8),
              ("eventsource", 8), ("external-url", 8), ("dynamic-import", 9), ("eval", 9), ("new-function", 9),
              ("global-dom", 10)}
    assert expect <= set(got)
    assert sum(1 for r in got if r == ("date", 3)) == 2
    assert sum(1 for r in got if r[0] == "global-dom") == 2


def test_template_expressions_are_linted_as_code():
    src = "sr.defineScene('custom:x', { render() { const s = `a ${Math.random()} b ${`nested ${Date.now()}`}`; } });"
    assert {r for r, _ in rules(src)} == {"math-random", "date"}


def test_template_text_and_regex_are_not_code():
    src = "sr.defineScene('custom:x', { render() { const s = `Math.random() ${1}`; const r = /Date.now()/; } });"
    assert rules(src) == []


def test_css_wall_clock_animation_in_strings():
    src = ("sr.defineScene('custom:x', { setup(ctx) { ctx.css(`.a { transition: opacity .3s; }\n"
           "@keyframes spin { to { transform: rotate(1turn) } }`); }, render(ctx) { el.style.transition = 'all 1s'; } });")
    got = rules(src)
    assert ("css-animation", 1) in got and ("css-animation", 2) in got
    assert len([r for r in got if r[0] == "css-animation"]) == 3


def test_external_urls_and_imports():
    src = ("import x from 'https://cdn.example.com/lib.js';\nimport y from 'lodash';\n"
           "sr.defineScene('custom:x', { render(ctx) { ctx.loadImage('https://img.example/x.png'); } });")
    got = rules(src)
    assert ("external-import", 1) in got and ("external-import", 2) in got and ("external-url", 3) in got


def test_warnings_for_waapi_and_missing_define():
    issues = lint_source("el.animate([{opacity: 0}], 1000);")
    kinds = {(i.rule, i.severity) for i in issues}
    assert ("waapi", "warning") in kinds and ("no-define", "warning") in kinds
    assert not any(i.rule == "no-define" for i in lint_source("export const x = 1;", kind="module"))


def test_tokenizer_tracks_lines_through_comments_and_templates():
    toks = tokenize("/* a\nb */ x\n`t\n${y}`\nz")
    pos = {t.value: t.line for t in toks if t.kind == "ident"}
    assert pos == {"x": 2, "y": 4, "z": 5}


def test_issue_has_snippet_and_str():
    i = lint_source("sr.defineScene('custom:a', { render() { Math.random(); } });", filename="a.js")[0]
    assert i.snippet.startswith("sr.defineScene") and str(i).startswith("a.js:1:")


def test_paths_and_cli(tmp_path: Path, capsys):
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes" / "bad.js").write_text("sr.defineScene('custom:b', {render() { Date.now(); }});", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib.js").write_text("Math.random()", encoding="utf-8")
    res = lint_paths([tmp_path])
    assert list(res) == [str(tmp_path / "scenes" / "bad.js")]
    assert main([str(tmp_path)]) == 1
    assert "date" in capsys.readouterr().out


def test_repo_runtime_demo_kit_lints_clean_except_sloppy_fixture():
    root = Path(__file__).resolve().parents[2]
    res = lint_paths([root / "tests" / "film" / "fixtures" / "kits"])
    errs = [i for v in res.values() for i in v if i.severity == "error"]
    # the deliberately sloppy fixture scene uses Math.random/Date: exactly those, nothing else
    assert {i.rule for i in errs} == {"math-random", "date"}
