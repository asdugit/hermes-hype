"""Static lint for scene and kit JavaScript (SDK.md §7): forbidden APIs, wall-clock CSS, external URLs/imports.

Token-aware: comments are skipped, string/template text is only checked for URLs and CSS animation rules, and
``${...}`` expressions inside template literals are linted as code. Reports 1-based line/column numbers.

    python -m showreel_core.film.lint FILE_OR_DIR... [--json]       # exit 1 if any error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

REGEX_PREV_KEYWORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield",
    "await",
})
REGEX_PREV_PUNCT = frozenset("(,=:[!&|?{};+-*%<>~^")
BANNED_IDENTS = {
    "setTimeout": "timers run on wall-clock time; derive everything from t",
    "setInterval": "timers run on wall-clock time; derive everything from t",
    "requestAnimationFrame": "the runtime drives frames; render(ctx, t, p) is called per frame",
    "XMLHttpRequest": "no network access in scenes",
    "WebSocket": "no network access in scenes",
    "EventSource": "no network access in scenes",
    "fetch": "no network access in scenes (use ctx.asset / ctx.loadImage)",
    "eval": "eval is forbidden",
    "Date": "Date is wall-clock; use t (shot-local seconds)",
}
WARN_IDENTS = {
    "localStorage": "storage is not available to scenes", "sessionStorage": "storage is not available to scenes",
    "indexedDB": "storage is not available to scenes", "navigator": "navigator differs between machines",
    "Worker": "workers are not synchronised with the frame clock",
}
DOC_OK = frozenset({"createElement", "createElementNS", "createTextNode", "createDocumentFragment", "createRange",
                    "fonts"})   # building offscreen nodes/canvases and reading font status touch nothing on the page
URL_RE = re.compile(r"\b(?:https?|wss?|ftp)://[^\s'\"`)]+|(?<![:\w])//(?:cdn|unpkg|fonts\.|ajax)\S*", re.IGNORECASE)
URL_OK = re.compile(r"^https?://www\.w3\.org/", re.IGNORECASE)
CSS_ANIM_RE = re.compile(r"(?<![\w-])(transition|animation(?:-name)?)\s*:\s*(?!\s*(?:none|unset|initial)\b)[^;'\"`]+|@keyframes\b", re.IGNORECASE)


@dataclass(frozen=True)
class LintIssue:
    """One finding; ``severity`` is "error" (blocks the scene) or "warning"."""
    rule: str
    severity: str
    line: int
    col: int
    msg: str
    file: str = ""
    snippet: str = ""

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}: {self.severity} [{self.rule}] {self.msg}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Tok:
    kind: str      # ident | punct | string | template | regex | number
    value: str
    line: int
    col: int


def tokenize(src: str) -> list[Tok]:
    """Tokenize JavaScript well enough for linting. Template literal text is emitted as 'template' tokens and the
    ``${}`` expressions inside them as ordinary tokens."""
    toks: list[Tok] = []
    i, n = 0, len(src)
    line, line_start = 1, 0
    # stack of brace depths at which a template literal resumes after '}'
    tmpl_stack: list[int] = []
    depth = 0

    def pos(k: int) -> tuple[int, int]:
        return line, k - line_start + 1

    def prev_sig() -> Tok | None:
        return toks[-1] if toks else None

    def regex_allowed() -> bool:
        p = prev_sig()
        if p is None:
            return True
        if p.kind == "punct":
            return p.value in REGEX_PREV_PUNCT or p.value in ("=>", "&&", "||", "??", "==", "===", "!=", "!==",
                                                              "+=", "-=", "*=", "/=", "<=", ">=", "...")
        return p.kind == "ident" and p.value in REGEX_PREV_KEYWORDS

    def read_template(k: int) -> int:
        """Read template text from k (just after ` or }) to the closing ` or ${; returns the new index."""
        nonlocal line, line_start
        start = k
        ln, cl = pos(k)
        while k < n:
            c = src[k]
            if c == "\\":
                k += 2
                continue
            if c == "\n":
                line += 1
                line_start = k + 1
            if c == "`":
                toks.append(Tok("template", src[start:k], ln, cl))
                return k + 1
            if c == "$" and k + 1 < n and src[k + 1] == "{":
                toks.append(Tok("template", src[start:k], ln, cl))
                tmpl_stack.append(depth)
                return k + 2
            k += 1
        toks.append(Tok("template", src[start:k], ln, cl))
        return k

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue
        if c in " \t\r\f\v\ufeff":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            seg = src[i:j]
            nl = seg.count("\n")
            if nl:
                line += nl
                line_start = i + seg.rfind("\n") + 1
            i = j
            continue
        if c in "'\"":
            ln, cl = pos(i)
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            toks.append(Tok("string", src[i + 1:j], ln, cl))
            i = j + 1
            continue
        if c == "`":
            i = read_template(i + 1)
            continue
        if c == "}" and tmpl_stack and tmpl_stack[-1] == depth:
            tmpl_stack.pop()
            i = read_template(i + 1)
            continue
        if c.isalpha() or c in "_$" or ord(c) > 127:
            ln, cl = pos(i)
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_$" or ord(src[j]) > 127):
                j += 1
            toks.append(Tok("ident", src[i:j], ln, cl))
            i = j
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            ln, cl = pos(i)
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            toks.append(Tok("number", src[i:j], ln, cl))
            i = j
            continue
        if c == "/" and regex_allowed():
            ln, cl = pos(i)
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            toks.append(Tok("regex", src[i:j], ln, cl))
            i = j
            continue
        ln, cl = pos(i)
        for op in ("===", "!==", "...", "=>", "==", "!=", "&&", "||", "??", "+=", "-=", "*=", "/=", "<=", ">=", "?."):
            if src.startswith(op, i):
                toks.append(Tok("punct", op, ln, cl))
                i += len(op)
                break
        else:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            toks.append(Tok("punct", c, ln, cl))
            i += 1
    return toks


def lint_source(src: str, *, filename: str = "<scene>", kind: str = "scene") -> list[LintIssue]:
    """Lint one JS source. ``kind`` = "scene" (expects sr.defineScene/defineTransition/defineKit) or "module"."""
    lines = src.splitlines()
    out: list[LintIssue] = []

    def add(rule: str, sev: str, t: Tok | tuple[int, int], msg: str) -> None:
        ln, cl = (t.line, t.col) if isinstance(t, Tok) else t
        snip = lines[ln - 1].strip()[:160] if 0 < ln <= len(lines) else ""
        out.append(LintIssue(rule, sev, ln, cl, msg, filename, snip))

    toks = tokenize(src)
    code = [t for t in toks if t.kind in ("ident", "punct", "number")]
    defined = False
    for k, t in enumerate(code):
        prev = code[k - 1] if k else None
        nxt = code[k + 1] if k + 1 < len(code) else None
        nxt2 = code[k + 2] if k + 2 < len(code) else None
        after_dot = prev is not None and prev.kind == "punct" and prev.value in (".", "?.")
        if t.kind != "ident":
            continue
        v = t.value
        member = nxt2.value if nxt is not None and nxt.value in (".", "?.") and nxt2 is not None else None
        if v == "Math" and member == "random" and not after_dot:
            add("math-random", "error", t, "Math.random is forbidden; use ctx.rng(seed)")
        elif v == "performance" and member == "now" and not after_dot:
            add("performance-now", "error", t, "performance.now is wall-clock; use t")
        elif v in ("document", "window", "globalThis", "self", "top", "parent") and member is not None and not after_dot:
            ok = (v == "window" and member == "devicePixelRatio") or (v == "document" and member in DOC_OK)
            if not ok and v not in ("self", "top", "parent"):
                add("global-dom", "error", t, f"{v}.{member}: no access outside ctx.root/ctx surfaces")
        elif v == "import" and nxt is not None and nxt.value == "(" and not after_dot:
            add("dynamic-import", "error", t, "dynamic import() is forbidden; use static imports")
        elif v == "Function" and not after_dot and ((prev and prev.value == "new") or (nxt and nxt.value == "(")):
            add("new-function", "error", t, "Function constructor is forbidden")
        elif v in BANNED_IDENTS and not after_dot:
            if v == "Date" and nxt is not None and nxt.value == ":":
                continue
            add(v.lower(), "error", t, f"{v}: {BANNED_IDENTS[v]}")
        elif v in WARN_IDENTS and not after_dot:
            add(v.lower(), "warning", t, f"{v}: {WARN_IDENTS[v]}")
        elif after_dot and v in ("transition", "animation", "animationName", "webkitAnimation") and nxt is not None and nxt.value == "=":
            val = code[k + 2] if k + 2 < len(code) else None
            raw = next((x for x in toks if x.line == t.line and x.kind in ("string", "template") and x.col > t.col), None)
            if not (raw and raw.value.strip() in ("none", "")) and not (val and val.value == "none"):
                add("css-animation", "error", t, f"style.{v} runs on wall-clock time; compute styles from t")
        elif after_dot and v == "animate" and nxt is not None and nxt.value == "(":
            add("waapi", "warning", t, "WAAPI: call .pause() and set currentTime from t (never let it play)")
        elif v in ("defineScene", "defineTransition", "defineKit") and after_dot:
            defined = True
    # static imports / re-exports
    for k, t in enumerate(toks):
        if t.kind == "ident" and t.value in ("import", "from") and k + 1 < len(toks) and toks[k + 1].kind == "string":
            spec = toks[k + 1].value
            if t.value == "import" and k > 0 and toks[k - 1].kind == "punct" and toks[k - 1].value == ".":
                continue
            if not (spec.startswith(("./", "../", "three/addons/")) or spec == "three"):
                add("external-import", "error", toks[k + 1], f"import {spec!r}: only relative paths, 'three' and 'three/addons/...'")
    # text content: URLs and wall-clock CSS
    for t in toks:
        if t.kind not in ("string", "template"):
            continue
        for m in URL_RE.finditer(t.value):
            if URL_OK.match(m.group(0)):
                continue
            ln = t.line + t.value[:m.start()].count("\n")
            add("external-url", "error", (ln, t.col), f"external URL {m.group(0)[:80]!r}: pages have no network; ship the file in the kit")
        for m in CSS_ANIM_RE.finditer(t.value):
            ln = t.line + t.value[:m.start()].count("\n")
            add("css-animation", "error", (ln, t.col), f"CSS {m.group(0).strip()[:60]!r} runs on wall-clock time; compute styles from t (or WAAPI paused + currentTime)")
    if kind == "scene" and not defined:
        add("no-define", "warning", (1, 1), "no sr.defineScene / defineTransition / defineKit call found")
    return sorted(out, key=lambda x: (x.line, x.col, x.rule))


def lint_file(path: Path, *, kind: str | None = None) -> list[LintIssue]:
    """Lint a .js file (kit sub-modules are linted as kind 'module')."""
    p = Path(path)
    src = p.read_text(encoding="utf-8", errors="replace")
    k = kind or ("scene" if p.name == "kit.js" or p.parent.name == "scenes" else "module")
    return lint_source(src, filename=str(p), kind=k)


def _files(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(x for x in p.rglob("*.js") if "vendor" not in x.parts and "node_modules" not in x.parts)
        elif p.suffix in (".js", ".mjs"):
            out.append(p)
    return out


def lint_paths(paths: Iterable[Path]) -> dict[str, list[LintIssue]]:
    """Lint files and folders (recursively, skipping vendor/); maps file -> issues."""
    return {str(f): lint_file(f) for f in _files(paths)}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.film.lint", description="Lint Showreel scene/kit JS.")
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = lint_paths(a.paths)
    errors = sum(1 for v in res.values() for i in v if i.severity == "error")
    if a.json:
        print(json.dumps({k: [i.to_dict() for i in v] for k, v in res.items()}, indent=1))
    else:
        for issues in res.values():
            for i in issues:
                print(i)
        print(f"{len(res)} files, {errors} errors, {sum(len(v) for v in res.values()) - errors} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
