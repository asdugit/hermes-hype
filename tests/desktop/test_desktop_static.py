"""Static checks on desktop/plugin.js: the SDK surface rules no render test can see.

- imports: only ``@hermes/plugin-sdk`` (as a namespace, so optional exports are feature-detected), ``react``
  and ``react/jsx-runtime``;
- catalog rule 8 (the ``hermes plugins validate`` "desktop surface" lint): no eval / new Function, no import()
  outside the SDK, no URL imports, no script injection, no reach into the app's markup or the preview guest;
  the same patterns are checked here, and the upstream lint itself runs when a Hermes checkout is around;
- theme: no hard-coded colour (hex, rgb()/hsl(), named colours) in the plugin's CSS or inline styles;
- lifecycle: no bare timers or global listeners (ctx.setInterval / ctx.setTimeout / ctx.onDispose instead),
  no fetch / WebSocket / localStorage / raw bridge;
- the module parses as ESM (``node --check``) when node is installed.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "desktop" / "plugin.js"
ALLOWED = {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}

# Same rules (and the same comment stripping) as hermes_cli/plugin_validate_desktop.py on Hermes main @5d12e89.
_FORBIDDEN = (
    ("dynamic code evaluation", re.compile(r"(?<![\w$.])eval\(|\bnew\s+Function\(")),
    ("dynamic import outside the SDK", re.compile(r"\bimport\(\s*(?!['\"](?:@hermes/plugin-sdk|react)(?:/[\w/-]*)?['\"]\s*\))")),
    ("remote import outside the SDK", re.compile(r"\bimport\s+(?:[^;'\"]*?\bfrom\s*)?['\"][a-zA-Z][\w+.-]*:")),
    ("script injection", re.compile(r"createElement\(\s*['\"]script['\"]\s*\)|<script\b")),
    ("app DOM reach", re.compile(r"\bdocument\.(?:querySelector(?:All)?|getElementsBy\w+|getElementById)\(\s*[`'\"][^`'\"]*"
                                 r"\[data-(?:slot|tour|sidebar|testid)\b")),
    ("app DOM reach", re.compile(r"\.observe\(\s*document\.body\s*,\s*\{[^}]*\b(?:childList|subtree)\b")),
    ("preview guest reach", re.compile(r"\b(?:querySelector(?:All)?|closest|getElementsByTagName|createElement)\(\s*[`'\"]webview\b")),
)
_REVIEW = (
    ("raw bridge window.hermesDesktop", re.compile(r"\b(?:window|globalThis|self)\s*(?:\?\.|\.)\s*hermesDesktop\b")),
    ("app markup selector", re.compile(r"\[data-(?:slot|tour|sidebar|testid|tree-[\w-]+|pane-host|titlebar-cluster)\b")),
)
_COMMENT = re.compile(
    r"(\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)"
    r"|/\*.*?\*/|(?<![:\w])//[^\n]*",
    re.DOTALL,
)
# Stricter house rules on top of rule 8.
_HOUSE = (
    ("bare timer (use ctx.setTimeout / ctx.setInterval)", re.compile(r"(?<![\w$.])(?:window\.)?set(?:Interval|Timeout)\(")),
    ("global listener (use ctx.addEventListener)", re.compile(r"\b(?:window|document|globalThis)\.addEventListener\(")),
    ("DOM query (render it yourself)", re.compile(r"\bdocument\.(?:querySelector|getElementBy|getElementsBy)")),
    ("MutationObserver", re.compile(r"\bMutationObserver\b")),
    ("network outside ctx.rest", re.compile(r"(?<![\w$.])fetch\(|\bXMLHttpRequest\b|\bnew\s+WebSocket\(")),
    ("localStorage (use ctx.storage)", re.compile(r"\b(?:local|session)Storage\b")),
    ("innerHTML", re.compile(r"\binnerHTML\b|dangerouslySetInnerHTML")),
)
_CSS_COLOUR = (
    ("hex colour", re.compile(r"(?<![\w&])#[0-9a-fA-F]{3,8}\b")),
    ("rgb()/hsl() colour", re.compile(r"\b(?:rgba?|hsla?)\(")),
    ("named colour", re.compile(r"(?<![\w-])(?:black|white|gr[ae]y|red|green|blue|yellow|orange|purple|pink|silver)(?![\w-])")),
)


def _source() -> str:
    return JS.read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    return _COMMENT.sub(lambda m: m.group(1) or "\n" * m.group(0).count("\n"), source)


def _hits(rules: tuple[tuple[str, re.Pattern[str]], ...], text: str) -> list[str]:
    return [f"{rule} (line {text.count(chr(10), 0, m.start()) + 1}: {m.group(0)[:40]!r})"
            for rule, pat in rules for m in pat.finditer(text)]


def _css_blocks(source: str) -> list[str]:
    """The template literals assigned to CSS constants plus every inline ``style: {...}`` object."""
    blocks = re.findall(r"const\s+\w*CSS\s*=\s*`([^`]*)`", source)
    blocks += re.findall(r"style:\s*\{[^{}]*\}", source)
    return blocks


def test_plugin_js_exists_and_is_lf() -> None:
    raw = JS.read_bytes()
    assert raw and b"\r\n" not in raw


def test_only_allowed_import_specifiers() -> None:
    src = _strip_comments(_source())
    specs = re.findall(r"^\s*(?:import|export)\b[^'\"`;]*?\bfrom\s*['\"]([^'\"]+)['\"]", src, re.M)
    specs += re.findall(r"^\s*import\s*['\"]([^'\"]+)['\"]", src, re.M)
    assert specs, "no imports found"
    assert set(specs) <= ALLOWED, set(specs) - ALLOWED
    assert "import(" not in src


def test_sdk_is_a_namespace_import() -> None:
    src = _source()
    assert re.search(r"^import \* as sdk from '@hermes/plugin-sdk'$", src, re.M)
    assert not re.search(r"^import\s*\{[^}]*\}\s*from\s*'@hermes/plugin-sdk'", src, re.M), \
        "named SDK imports fail the module link on hosts that lack an export"
    # an optional area is only ever used behind a typeof check
    for m in re.finditer(r"sdk\.TOOL_MEDIA_RENDERER_AREA", src):
        line = src[src.rfind("\n", 0, m.start()) + 1: src.find("\n", m.end())]
        if "area:" in line:
            continue
        assert "typeof" in line, line


def test_rule_8_desktop_surface_patterns() -> None:
    stripped = _strip_comments(_source())
    assert _hits(_FORBIDDEN, stripped) == []
    assert _hits(_REVIEW, stripped) == []


def test_house_rules() -> None:
    stripped = _strip_comments(_source())
    assert _hits(_HOUSE, stripped) == []
    src = _source()
    assert "ctx.onDispose(" in src and ".setInterval(" in src and "ctx.onEvent(" in src


def test_theme_variables_only() -> None:
    problems = []
    for block in _css_blocks(_source()):
        problems += _hits(_CSS_COLOUR, block)
    assert problems == []
    css = "\n".join(re.findall(r"const\s+\w*CSS\s*=\s*`([^`]*)`", _source()))
    assert "var(--ui-accent)" in css and "var(--ui-text-primary)" in css


def test_one_default_export_with_the_plugin_id() -> None:
    src = _source()
    assert src.count("export default") == 1
    assert re.search(r"^const ID = 'auteur'$", src, re.M) and "id: ID," in src


def _upstream_validator() -> object | None:
    candidates = [os.environ.get("HERMES_AGENT_DIR", "")]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates += [str(Path(local) / "hermes" / "hermes-agent"),
                       str(Path(local) / "hermes" / "cache" / "scratch" / "sr" / "ha")]
    candidates.append(str(Path.home() / ".hermes" / "hermes-agent"))
    for base in candidates:
        path = Path(base) / "hermes_cli" / "plugin_validate_desktop.py" if base else None
        if path and path.is_file():
            spec = importlib.util.spec_from_file_location("_upstream_desktop_lint", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules["_upstream_desktop_lint"] = mod
                spec.loader.exec_module(mod)
                return mod
    return None


def test_upstream_desktop_surface_lint_when_available() -> None:
    mod = _upstream_validator()
    if mod is None:
        pytest.skip("no Hermes checkout found (set HERMES_AGENT_DIR)")
    assert mod.desktop_surface_hits(ROOT) == []                       # type: ignore[attr-defined]
    if hasattr(mod, "desktop_review_findings"):
        assert mod.desktop_surface_hits(ROOT, mod.desktop_review_findings) == []   # type: ignore[attr-defined]


def test_parses_as_an_es_module(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    assert node is not None
    copy = tmp_path / "plugin.mjs"
    copy.write_bytes(JS.read_bytes())
    r = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_energy_knob_takes_a_whole_row():
    """W5-ship2: the 4-option Energy control clipped "High" in a 150 px knob column (pane 360-480 px, page 1280)."""
    src = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert "className: 'srl-knob srl-knob-wide', children: [jsx('span', { children: 'Energy' })" in src
    assert ".srl-knob-wide{grid-column:1/-1}" in src and "grid-auto-flow:row dense" in src
