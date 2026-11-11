"""On-screen hygiene for films made from a stranger's session.

A judge runs ``/hype`` on their own session, so a Quick film must never print:

* a "run command" that is really a line of code: a real END card read ``from pathlib import Path`` (the first
  line of an ``execute_code`` script). The END command comes only from the product - its launch/install
  commands (:func:`launch_command`, :func:`install_command`) - and otherwise the END shows no command;
* a loopback / dev-server address (``Open it at localhost``, ``127.0.0.1:8765``): :func:`scrub_text`,
  :func:`scrub_film`;
* machine paths and shell noise (``cd ~/work/app && HYPE_X=1 ~/.venv/Scripts/python.exe ...``):
  :func:`display_cmd` / :func:`display_path` give the project-relative form.

Pure functions over strings and events; the story stage, the timeline and the Quick film all use them.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

try:  # one definition of "a loopback address" (the Director's END hygiene, 5d57c93)
    from ..director.repair import LOOPBACK
except Exception:  # noqa: BLE001 - a trimmed build without the Director still scrubs
    LOOPBACK = re.compile(r"(?:https?://)?(?:127(?:\.\d{1,3}){3}|localhost|0\.0\.0\.0|\[::1\])(?::\d{1,5})?"
                          r"(?:/[^\s\"']*)?", re.IGNORECASE)

#: one shell segment separator (``a && b``, ``a; b``, ``a || b``)
_SEG_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;)\s*")
#: leading ``VAR=value`` assignments (``FOO=1 BAR="x y" cmd``), also ``export``/``set`` forms
_ENV_PREFIX_RE = re.compile(r"^(?:(?:env\s+)?[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s;&|]*)\s+)+")
_ENV_ONLY_RE = re.compile(r"^(?:export\s+|set\s+)?[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S*)$")
#: segments that only set up the shell (they never belong on screen)
_NOISE_SEG_RE = re.compile(r"^(?:cd|pushd|popd|export|set|source|\.\s|conda\s+activate|nvm\s+use|clear|cls|"
                           r"sleep\s+\d|true$|:$)|activate(?:\.bat|\.ps1|\.fish)?[\"']?$", re.IGNORECASE)
_WRAPPER_RE = re.compile(r"^(?:(?:timeout|gtimeout)\s+(?:-\w+\s+)*\d+[smh]?\s+|sudo\s+|nohup\s+|time\s+|"
                         r"exec\s+|command\s+)+")
#: an interpreter given by path (``~/x/.venv-dev/Scripts/python.exe``, ``/usr/bin/python3``) -> its bare name
_INTERP_RE = re.compile(r"^[\"']?(?:[^\s\"']*[\\/])?(python3?(?:\.\d+)?|py|node|deno|bun|ruby|php|pythonw)"
                        r"(?:\.exe)?[\"']?$", re.IGNORECASE)
#: the first line of a program, not a command (``from pathlib import Path`` reached a real END card)
_CODE_RE = re.compile(r"^(?:from\s+[\w.]+\s+import\b|import\s+[\w.{*]|def\s|class\s|async\s|await\s|print\s*\(|"
                      r"const\s|let\s|var\s|function\b|return\b|if\s|for\s|while\s|with\s|try\s*:|#|//|/\*|@\w|"
                      r"[\w.\[\]'\"]+\s*[+\-*/]?=[^=])")
_BIND_ARG_RE = re.compile(r"\s+(?:--bind|--host|--hostname|-b|-H|--listen)(?:=|\s+)"
                          r"(?:127(?:\.\d{1,3}){3}|localhost|0\.0\.0\.0|::1?|\[::1?\])(?=\s|$)", re.IGNORECASE)
_REDIRECT_RE = re.compile(r"\s+(?:\d?>>?|&>)\s*\S+|\s+\d?>&\d|\s+&$")

#: commands that start/run the product (dev servers, CLIs, scripts, games, containers)
_RUN_SHAPE_RE = re.compile(r"""^(?:
    (?:npm|pnpm|yarn|bun)\s+(?:start|dev|serve|preview|run\s+[\w:.\-]+)\b
  | npx\s+(?:-y\s+|--yes\s+)?[@\w][\w@./\-]*
  | (?:uv\s+run\s+|poetry\s+run\s+|pipenv\s+run\s+)?(?:python3?|py)\s+(?:-m\s+[\w.]+|[\w./\-]+\.pyw?)(?=\s|$)
  | (?:uv|poetry|pipenv)\s+run\s+[\w.\-]+
  | (?:node|tsx|ts-node|deno\s+run(?:\s+-\S+)*|bun(?:\s+run)?)\s+[\w./\-]+\.(?:m?js|cjs|ts|tsx|jsx)(?=\s|$)
  | deno\s+task\s+[\w:.\-]+
  | cargo\s+run\b | go\s+run\b
  | make\s+(?:run|dev|serve|start|demo|play|up)\b
  | (?:flask|fastapi)\s+(?:run|dev)\b | streamlit\s+run\b | gradio\s+\S | (?:uvicorn|gunicorn|hypercorn)\s+\S
  | docker(?:-|\s+)compose\s+up\b | docker\s+run\b
  | php\s+-S\b | hugo\s+server\b | jekyll\s+serve\b | rails\s+s(?:erver)?\b | love\s+\.
  | (?:vite|next|astro|nuxt|remix|expo)(?:\s+(?:dev|start|preview|serve))?(?:\s|$)
  | \./[\w.\-]+
)""", re.IGNORECASE | re.VERBOSE)
_NOT_PRODUCT_NPM = {"test", "lint", "build", "format", "fmt", "typecheck", "type-check", "check", "clean",
                    "prettier", "eslint", "tsc", "coverage", "e2e", "storybook", "prepare", "release", "deploy"}
_NOT_PRODUCT_MODULE = {"pytest", "pip", "venv", "virtualenv", "unittest", "mypy", "ruff", "black", "flake8",
                       "pylint", "isort", "build", "twine", "compileall", "py_compile", "json.tool", "doctest",
                       "coverage", "playwright", "ensurepip", "pydoc", "timeit", "cprofile", "pdb", "site",
                       "tox", "nox", "pre_commit", "sphinx", "mkdocs", "setuptools", "wheel", "pipx", "uv"}
_TEST_PATH_RE = re.compile(r"(?i)(?:^|[\\/])(?:tests?|__tests__|specs?|fixtures?|e2e|testing|testdata|"
                           r"test[_-]?data|htmlcov|coverage|playwright-report|test-results|node_modules|"
                           r"site-packages|\.pytest_cache|\.tox|\.venv|venv)(?:[\\/]|$)"
                           r"|(?:^|[\\/])(?:test_[^\\/]*|[^\\/]*_test\.py|conftest\.py|[^\\/]*\.(?:test|spec)\.\w+)$")
#: install lines a README / an answer may give (the product's own, never a dependency)
INSTALL_RE = re.compile(r"((?:pip3?|pipx|uv pip|uv tool) install [\w.\-\[\]=<>]+|npm (?:i|install) -g [\w@/.\-]+"
                        r"|git clone \S+|cargo install [\w\-]+|brew install [\w\-/]+|go install \S+"
                        r"|hermes plugins install [\w/.\-]+)")
_INSTALL_NOT_PRODUCT = re.compile(r"(?i)install (?:-r|-e|--upgrade|-U|\.|pytest|pip|setuptools|wheel|"
                                  r"requirements)\b")
#: words that make a CTA read as a shell command (``$ ...``, ``python ...``, ``from x import y``)
_COMMANDISH_RE = re.compile(r"^(?:\$|>)\s|^(?:python3?|py|node|npm|npx|pnpm|yarn|bun|deno|pip3?|pipx|uv|cargo|"
                            r"go|make|docker|git|curl|wget|brew|cd|sudo|bash|sh|pwsh|powershell|hermes|flask|"
                            r"uvicorn|gunicorn|streamlit|vite|next|php|ruby|rails|java|mvn|gradle|dotnet|"
                            r"from|import|\./)(?:\s|$|\.exe)", re.IGNORECASE)
_PATH_TOKEN_RE = re.compile(r"(?<![\w:/.~\\\-])(?:~[\\/]|[A-Za-z]:[\\/]|/)[^\s\"'`|;&<>()]*")
ELLIPSIS = "\u2026"


# ------------------------------------------------------------------------------------------------ commands

def _clean_segment(seg: str) -> str:
    """One shell segment without wrappers, env assignments, redirections or interpreter paths."""
    s = seg.strip()
    if " | " in s:
        s = s.split(" | ", 1)[0].strip()
    s = _REDIRECT_RE.sub("", s).strip().rstrip("&").strip()
    for _ in range(3):
        before = s
        s = _WRAPPER_RE.sub("", s)
        s = _ENV_PREFIX_RE.sub("", s).strip()
        if s == before:
            break
    if not s or _ENV_ONLY_RE.match(s) or _NOISE_SEG_RE.search(s):
        return ""
    head, _, rest = s.partition(" ")
    m = _INTERP_RE.match(head)
    if m:
        name = m.group(1).lower()
        s = (("python" if name in ("pythonw",) else name) + (" " + rest if rest else "")).strip()
    return _BIND_ARG_RE.sub("", s).strip()


def _segments(cmd: str) -> list[str]:
    return [c for c in (_clean_segment(x) for x in _SEG_SPLIT_RE.split(cmd)) if c]


def _is_launch(seg: str, clis: Iterable[str] = ()) -> bool:
    from .facts import is_test_cmd
    if not seg or _CODE_RE.match(seg) or is_test_cmd(seg):
        return False
    if re.search(r"\s-(?:c|e|-eval|-command)(?:\s|$)", seg):     # inline code: a script, not a command
        return False
    if any(_TEST_PATH_RE.search(t) for t in seg.split()[1:3] if "/" in t or "\\" in t or t.endswith(".py")):
        return False
    if any(t.startswith(("~", "/")) or re.match(r"[A-Za-z]:[\\/]", t) for t in seg.split()):
        return False                                              # a machine path: not runnable elsewhere
    low = seg.lower()
    m = re.match(r"(?:npm|pnpm|yarn|bun)\s+run\s+([\w:.\-]+)", low)
    if m and (m.group(1).split(":")[0] in _NOT_PRODUCT_NPM):
        return False
    m = re.match(r"(?:uv\s+run\s+|poetry\s+run\s+|pipenv\s+run\s+)?(?:python3?|py)\s+-m\s+([\w.]+)", low)
    if m and m.group(1) in _NOT_PRODUCT_MODULE:
        return False
    m = re.match(r"npx\s+(?:-y\s+|--yes\s+)?([@\w][\w@./\-]*)", low)
    if m and m.group(1) in {"tsc", "eslint", "prettier", "jest", "vitest", "playwright", "mocha", "create-react-app"}:
        return False
    if _RUN_SHAPE_RE.match(seg):
        return True
    first = seg.split()[0]
    return any(first == c for c in clis if c)


def launch_command(cmd: str, *, shell: str = "", clis: Iterable[str] = ()) -> str:
    """The command a viewer would type to run the product, from a session/README command; "" when it is not one.

    Drops shell set-up (``cd X &&``, ``VAR=...``, venv activation), wrappers (``timeout 300``), redirections and
    loopback bind args; turns an interpreter path into its name. Code (an ``execute_code`` script, ``python -c``,
    a heredoc, ``from x import y``), tests, installs of tools and machine paths are never a launch command.
    ``clis``: the product's own CLI names (package.json bin / pyproject scripts)."""
    if shell == "python" or not cmd:
        return ""
    text = str(cmd).strip()
    if "\n" in text or "<<" in text:
        return ""
    best = ""
    for seg in _segments(text):
        if _is_launch(seg, clis):
            best = seg               # the last launch segment of `install && run` is the run
    return best


def install_command(text: str, product_words: Iterable[str] = ()) -> str:
    """The product's own install line in ``text`` (README, an answer), else "" (dependency installs are not)."""
    for m in INSTALL_RE.finditer(text or ""):
        line = m.group(1)
        if _INSTALL_NOT_PRODUCT.search(line):
            continue
        words = [w.lower() for w in product_words if w and len(w) >= 3]
        if words and not any(w in line.lower() for w in words):
            continue
        return line
    return ""


def looks_like_command(text: str) -> bool:
    """True when a CTA reads as something to type (a command or a line of code), not as words."""
    s = (text or "").strip().strip("`")
    if not s:
        return False
    return bool(_COMMANDISH_RE.match(s) or _CODE_RE.match(s) or re.search(r"\s--?\w|[=(){};|]|&&|\w\.\w+\(", s))


def command_key(cmd: str) -> str:
    """Comparable form of a command (cleaned, whitespace-normalised, lower case)."""
    return " ".join(" ".join(_segments(str(cmd or ""))).split()).lower()


def product_words(product: Any) -> list[str]:
    """Words of the product's name (an install line must name the product: ``pip install tempo-timer``)."""
    name = str(getattr(product, "name", "") or "")
    return [w for w in re.findall(r"[A-Za-z0-9]+", name.lower()) if len(w) >= 3]


def _readme_texts(facts: Any) -> list[str]:
    out = []
    for ev in getattr(facts, "events", []):
        d = ev.data or {}
        path = str(d.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if ev.kind in ("file_write", "file_read") and path.startswith("readme"):
            lines = d.get("lines") or d.get("content_lines") or []
            out.append("\n".join(str(x) for x in lines) if isinstance(lines, list) else "")
    return out


def _clean_install(line: str) -> str:
    if has_loopback(line) or any(t.startswith(("~", "/")) or re.match(r"[A-Za-z]:[\\/]", t) for t in line.split()[2:]):
        return ""
    return line


def end_command(product: Any, facts: Any, limit: int = 40) -> str:
    """The END card's command: the product's own install line (said in an answer, the README or run in the
    terminal), else its launch command (session run / README / package.json / pyproject / Makefile), else ""
    - an END with no command shows the name and tagline, never a line of code."""
    from .facts import data_get
    texts = [str(data_get(e, "text", "")) for e in getattr(facts, "events", [])
             if e.kind in ("final_answer", "assistant_note")]
    texts += _readme_texts(facts)
    texts += [str(data_get(e, "cmd", "")) for e in getattr(facts, "events", [])
              if e.kind == "terminal" and e.ok and str(data_get(e, "shell", "")) != "python"]
    words = product_words(product)
    for text in reversed(texts):
        line = _clean_install(install_command(text, words))
        if line and len(line) <= limit:
            return line
    for c in list(getattr(product, "run_commands", None) or []):
        lc = launch_command(c) or bare_cli(c)
        if lc and len(lc) <= limit:
            return lc
    return ""


_NOT_CLI = {"python", "python3", "py", "node", "npm", "npx", "pip", "pip3", "uv", "make", "bash", "sh", "zsh",
            "pwsh", "powershell", "cmd", "start", "open", "exit", "help", "echo", "env", "sudo", "code", "vim",
            "nano", "less", "more", "curl", "wget", "ssh", "docker", "deno", "bun", "cargo", "go", "hermes"}


def bare_cli(cmd: str) -> str:
    """A product CLI named on its own (a pyproject ``[project.scripts]`` entry such as ``tally``), else ""."""
    from .facts import is_setup_cmd, is_test_cmd
    s = (cmd or "").strip()
    if (re.fullmatch(r"[A-Za-z][\w\-]{2,30}", s) and s.lower() not in _NOT_CLI and not is_setup_cmd(s)
            and not is_test_cmd(s)):
        return s
    return ""


def approved_cta(cta: str, product: Any, facts: Any, trusted: Iterable[str] = ()) -> str:
    """A command-like CTA as the film may print it (cleaned), or "" when it is not the product's own launch or
    install command: it must be a launch/install shape AND the session ran it, a README/answer gives it, or the
    session's product detection found it (``trusted``)."""
    from .facts import data_get
    s = re.sub(r"^(?:\$|>)\s+", "", (cta or "").strip().strip("`")).strip()
    if not s or has_loopback(s) and not launch_command(s):
        return ""
    inst = _clean_install(install_command(s, product_words(product)))
    if inst and inst == s:
        texts = [str(data_get(e, "text", "")) for e in facts.events if e.kind in ("final_answer", "assistant_note")]
        texts += _readme_texts(facts) + [str(data_get(e, "cmd", "")) for e in facts.events if e.kind == "terminal"]
        return inst if any(inst in t for t in texts) else ""
    lc = launch_command(s)
    if not lc:
        return ""
    key = command_key(lc)
    known = [launch_command(str(data_get(e, "cmd", "")), shell=str(data_get(e, "shell", "") or ""))
             for e in facts.events if e.kind == "terminal"]
    known += [launch_command(c) for c in list(getattr(product, "run_commands", None) or []) + list(trusted)]
    for k in known:
        kk = command_key(k)
        if kk and (kk == key or kk.startswith(key + " ")):
            return lc
    return ""


# ------------------------------------------------------------------------------------------ pages

def is_test_path(path: str) -> bool:
    """A file under a test/fixture/report/vendor folder (``tests/capture/fixture_site/shell.html``,
    ``htmlcov/index.html``, ``node_modules/...``): never the product's page when the product has its own."""
    return bool(path) and bool(_TEST_PATH_RE.search(str(path).replace("\\", "/")))


def is_test_page(ev: Any) -> bool:
    """A captured/screenshotted page that lives under a test/fixture/report folder."""
    d = getattr(ev, "data", None) or {}
    return any(is_test_path(str(d.get(k) or "")) for k in ("url", "source", "page_path")
               if str(d.get(k) or "").startswith(("~", "/", "file:")) or re.match(r"[A-Za-z]:[\\/]", str(d.get(k) or "")))


def is_long_page(ev: Any) -> bool:
    """True for a picture of a page at least 1.5 screens tall (worth a SCROLL); a viewport-high 'full page' (a
    page that scrolls inside an inner panel) is not."""
    d = getattr(ev, "data", None) or {}
    vp, size = d.get("viewport"), d.get("size")
    try:
        if vp and size:
            dpr = float(d.get("dpr") or 1.0) or 1.0
            return float(size[1]) / dpr >= 1.5 * float(vp[1])
    except (TypeError, ValueError, IndexError):
        pass
    from .facts import image_of
    img = image_of(ev) or {}
    w, h = float(img.get("w") or 0), float(img.get("h") or 0)
    return bool(w and h >= 1.4 * w)


# ------------------------------------------------------------------------------------------ placeholders

#: template slots a model echoes back: ``{product}``, ``{{name}}``, ``{NAME}`` (prompt templates) and the engine's
#: own ``<call to action>`` / ``<one real feature>`` hints (letters and spaces only, so ``List<String>`` or HTML stay)
_SLOT_RE = re.compile(r"\{\{?\s*(product|product[ _]?name|name|title|brand|app|tagline|one[ _]?liner|benefit|cta|url|"
                      r"feature|features|audience)\s*\}?\}|<([A-Za-z][A-Za-z' -]{0,60}\s[A-Za-z' -]{1,60})>",
                      re.IGNORECASE)
#: filler that is never real copy: Lorem ipsum anywhere, or a text that IS a to-do marker ('TODO', 'TBD: tagline')
_FILLER_RE = re.compile(r"(?i)\blorem ipsum\b|\bdolor sit amet\b|^\W*(?:todo\s*[:\-–—]|"
                        r"(?:tbd|fixme|placeholder|xxx+)\b\s*(?:[:\-–—]|$))")
#: a line of program code as a caption/label ('from patchlib import patch' reached a real END card)
_CODE_LINE_RE = re.compile(r"^\W*(?:from\s+[\w.]+\s+import\s+\S|import\s+[\w.]+(?:\s+as\s+\w+)?\s*;?\s*$|"
                           r"def\s+\w+\s*\(|class\s+\w+\s*[(:]|(?:const|let|var)\s+\w+\s*=|print\s*\(|"
                           r"console\.log\s*\(|#include\s*<|require\s*\(['\"])")


def is_filler(text: Any) -> bool:
    """True for placeholder copy that must never be on screen (Lorem ipsum, a bare TODO, a line of code)."""
    return isinstance(text, str) and bool(_FILLER_RE.search(text) or _CODE_LINE_RE.match(text))


def unplaceholder(text: str, *, name: str = "", tagline: str = "", cta: str = "") -> str:
    """``text`` without template junk: a ``{name}`` / ``<product name>`` slot becomes the fact it stands for
    (product name, tagline, CTA) or goes; filler ('Lorem ipsum', a bare 'TODO:', a line of code) clears the text.
    Plain text comes back unchanged."""
    if not isinstance(text, str) or not text.strip():
        return text
    if is_filler(text):
        return ""
    if "{" not in text and "<" not in text:
        return text

    def fill(m: re.Match[str]) -> str:
        key = re.sub(r"[^a-z]", "", (m.group(1) or m.group(2) or "").lower())
        if "tagline" in key or "benefit" in key or "liner" in key:
            return tagline
        if "calltoaction" in key or key == "cta":
            return cta
        if key in ("product", "productname", "name", "title", "brand", "app") or key.endswith("productname"):
            raw = (m.group(1) or m.group(2) or "").strip()
            return name.upper() if name and raw == raw.upper() else name
        return ""
    out = _SLOT_RE.sub(fill, text)
    if out == text:
        return text
    out = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s{2,}", " ", out)).strip(" -–—:,;")
    out = re.sub(r"\s+\b(?:at|on|to|via|from|for|with|and|by|in)\s*([.!?]?)$", r"\1", out).strip()
    return out if any(ch.isalnum() for ch in out) else ""


# --------------------------------------------------------------------------------------------- loopback

def has_loopback(text: Any) -> bool:
    return isinstance(text, str) and bool(LOOPBACK.search(text))


def scrub_text(text: str, name: str = "", url: str = "") -> str:
    """``text`` with any loopback address replaced by the public URL or the product name (or dropped)."""
    if not has_loopback(text):
        return text
    repl = url or name
    out = LOOPBACK.sub(repl, text) if repl else LOOPBACK.sub("", text)
    out = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s{2,}", " ", out)).strip()
    if not repl:
        out = re.sub(r"\b(?:at|on|to|via|from)\s*([.!?]?)$", r"\1", out).strip()
    return out


def scrub_sentences(text: str) -> str:
    """Narration without the sentences that name a loopback address (a voice never reads 'localhost')."""
    if not has_loopback(text):
        return text
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(p for p in parts if not has_loopback(p)).strip()


def scrub_cmd(cmd: str) -> str:
    """A displayed command with a loopback origin elided (``curl http://127.0.0.1:8765/api`` -> ``curl …/api``)."""
    if not has_loopback(cmd):
        return cmd
    cmd = _BIND_ARG_RE.sub("", cmd)

    def repl(m: re.Match[str]) -> str:
        path = re.sub(r"^(?:https?://)?[^/]+", "", m.group(0))
        return ELLIPSIS + path if path not in ("", "/") else ELLIPSIS
    return LOOPBACK.sub(repl, cmd)


_URL_KEYS = {"url", "href", "link", "domain", "address"}
_LINE_KEYS = {"output", "lines", "output_lines"}
_CMD_KEYS = {"cmd", "command"}
_VO_KEYS = {"vo", "narration", "voiceover"}
_SKIP_KEYS = {"asset", "src", "path", "id", "scene", "font", "fonts", "kits", "assets"}


def scrub_value(o: Any, *, name: str, url: str = "", key: str = "", path: str = "$",
                fixes: list[str] | None = None) -> Any:
    """Deep copy of ``o`` with no loopback address in any on-screen string (key-aware: URL fields become the
    public URL or '', terminal output lines naming one are dropped, commands elide it, narration drops the
    sentence, other text says the product name)."""
    k = key.lower()
    if isinstance(o, str):
        if k in _SKIP_KEYS or not has_loopback(o):
            return o
        if k in _URL_KEYS:
            new = url if url and not has_loopback(url) else ""
        elif k in _CMD_KEYS:
            new = scrub_cmd(o)
        elif k in _VO_KEYS:
            new = scrub_sentences(o)
        else:
            new = scrub_text(o, name, url)
        if fixes is not None:
            fixes.append(f"{path}: loopback address -> {new!r}")
        return new
    if isinstance(o, dict):
        return {kk: scrub_value(v, name=name, url=url, key=str(kk), path=f"{path}.{kk}", fixes=fixes)
                for kk, v in o.items()}
    if isinstance(o, list):
        if k in _LINE_KEYS and all(isinstance(x, str) for x in o):
            kept = [x for x in o if not has_loopback(x)]
            if fixes is not None and len(kept) != len(o):
                fixes.append(f"{path}: {len(o) - len(kept)} line(s) naming a loopback address dropped")
            return kept
        return [scrub_value(v, name=name, url=url, key=key, path=f"{path}[{i}]", fixes=fixes)
                for i, v in enumerate(o)]
    return o


def scrub_film(film: dict[str, Any], *, name: str, url: str = "") -> list[str]:
    """IN PLACE: no loopback address in a film's shots, overlays or captions (Quick + customize)."""
    fixes: list[str] = []
    for sect in ("shots", "overlays", "captions"):
        if isinstance(film.get(sect), list):
            film[sect] = scrub_value(film[sect], name=name, url=url, path=sect, fixes=fixes)
    return fixes


# ------------------------------------------------------------------------------------------- paths

def _norm(p: str) -> str:
    """Forward slashes, no trailing slash; MSYS / WSL / Cygwin drive forms (``/d/x``, ``/mnt/d/x``) as ``D:/x``."""
    s = str(p or "").replace("\\", "/").rstrip("/")
    m = re.match(r"^/(?:mnt/|cygdrive/)?([A-Za-z])(?=/)", s)
    if m:
        s = m.group(1).upper() + ":" + s[m.end():]
    elif re.match(r"^[a-z]:/", s):
        s = s[0].upper() + s[1:]
    return s


def _ancestors(path: str) -> list[str]:
    parts = _norm(path).split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def _too_shallow(d: str) -> bool:
    parts = [x for x in d.split("/") if x]
    if not parts:
        return True
    if parts[0] == "~" or re.fullmatch(r"[A-Za-z]:", parts[0]):
        return len(parts) < 2
    return parts[0] in ("home", "Users", "users", "mnt") and len(parts) < 3


_MANIFESTS = {"readme.md", "readme", "readme.rst", "package.json", "pyproject.toml", "cargo.toml", "go.mod",
              "setup.py", "plugin.yaml", "manifest.json", "index.html"}
_CD_RE = re.compile(r"(?:^|&&|;)\s*cd\s+(?:/d\s+)?(\"[^\"]+\"|'[^']+'|[^\s&;|]+)")


def project_root(paths: Iterable[str], commands: Iterable[str] = ()) -> str:
    """The project's root folder (``~/work/tempo``), from the files the session wrote and the folders it ``cd``ed
    into; "" when the session has no clear project folder. Machine-specific prefixes stay out of film text by
    cutting everything up to and including this folder (:func:`display_path`)."""
    files = [_norm(p) for p in paths if p and ("/" in str(p) or "\\" in str(p))]
    files = [f for f in files if f.startswith(("~", "/")) or re.match(r"[A-Za-z]:/", f)]
    if not files:
        return ""
    support: Counter[str] = Counter()
    for f in files:
        for a in _ancestors(f):
            if not _too_shallow(a):
                support[a] += 1
    if not support:
        return ""
    n = len(files)
    cds = Counter(_norm(m.group(1).strip("\"'")) for c in commands for m in _CD_RE.finditer(str(c or "")))
    manifest_dirs = {f.rsplit("/", 1)[0] for f in files if f.rsplit("/", 1)[-1].lower() in _MANIFESTS}

    def score(d: str) -> tuple[float, int, int]:
        share = support[d] / n
        bonus = 0.35 if d in cds else 0.0
        bonus += 0.25 if d in manifest_dirs else 0.0
        return (share + bonus, support[d], len(d))
    cands = [d for d in support if support[d] / n >= 0.34 or d in cds]
    if not cands:
        return ""
    best = max(cands, key=score)
    # a deeper folder that holds (nearly) every file of the chosen one is the real project (src/ layouts aside)
    deeper = [d for d in cands if d.startswith(best + "/") and support[d] >= max(2, int(support[best] * 0.9))
              and d.rsplit("/", 1)[-1].lower() not in ("src", "app", "lib", "source", "web", "public")]
    if deeper:
        best = max(deeper, key=lambda d: (support[d], len(d)))
    return best


def display_path(path: str, root: str = "", parts: int = 2) -> str:
    """Project-relative path for the screen: ``~/work/tempo/src/app.js`` -> ``src/app.js`` (root = ``~/work/tempo``);
    a path outside the project keeps its last ``parts`` components (``…/scratch/run.py``)."""
    p = _norm(path)
    if not p:
        return str(path or "")
    r = _norm(root)
    if r:
        if p == r:
            return r.rsplit("/", 1)[-1]
        if p.lower().startswith(r.lower() + "/"):
            return p[len(r) + 1:]
        if p.lower() == r.lower():
            return r.rsplit("/", 1)[-1]
    if p.startswith("/") and not re.match(r"(?i)/(?:home|users)/", p):
        return p                    # a system path (/usr/bin/bash, /tmp/x) says nothing about this machine
    if p.startswith(("~/", "/")) or re.match(r"[A-Za-z]:/", p):
        comps = [c for c in p.split("/") if c and c != "~" and not re.fullmatch(r"[A-Za-z]:", c)]
        if len(comps) > parts:
            return ELLIPSIS + "/" + "/".join(comps[-parts:])
        if p.startswith("/"):
            return p                # a short system path (/tmp, /usr/bin) says nothing about the machine
        return "/".join(comps) if comps else p
    return p


def display_text_paths(text: str, root: str = "") -> str:
    """``text`` with every machine path in it shortened by :func:`display_path`."""
    if not text or not ("/" in text or "\\" in text):
        return text
    return _PATH_TOKEN_RE.sub(lambda m: display_path(m.group(0), root), text)


def ellipsize(text: str, limit: int) -> str:
    """``text`` cut at a word boundary to at most ``limit`` characters, with an ellipsis."""
    t = " ".join(str(text or "").split())
    if limit <= 0 or len(t) <= limit:
        return t
    cut = t[:max(1, limit - 1)]
    sp = cut.rfind(" ")
    if sp >= limit * 0.5:
        cut = cut[:sp]
    return cut.rstrip(" ,;&|") + ELLIPSIS


_LEAD_NOISE_RES = (
    re.compile(r"^(?:cd|pushd)\s+(?:/d\s+)?(?:\"[^\"]+\"|'[^']+'|\S+)\s*(?:&&|;)\s*"),
    re.compile(r"^(?:export\s+|set\s+)?[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s;&|]*)\s*(?:&&|;)\s*"),
    re.compile(r"^(?:source\s+|\.\s+)?\S*activate(?:\.bat|\.ps1|\.fish)?\s*(?:&&|;)\s*"),
)
_INTERP_PATH_RE = re.compile(r"(?<![\w\-])(?:\"[^\"\s]*[\\/]|'[^'\s]*[\\/]|[^\s\"';&|]*[\\/])"
                             r"(python3?(?:\.\d+)?|pythonw|py|node|deno|bun|ruby|php)(?:\.exe)?[\"']?(?=\s|$)",
                             re.IGNORECASE)


def display_cmd(cmd: str, root: str = "", limit: int = 0) -> str:
    """A session command as a film shows it: first line only; the leading shell set-up (``cd X &&``, ``VAR=...``,
    venv activation, ``timeout N``) dropped; interpreter paths as their names; home/drive/project paths
    project-relative; a loopback origin elided; ellipsized at a word boundary to ``limit`` characters (0 = no
    limit). Everything else stays verbatim (pipes, ``;``, quoting), so the command keeps its real meaning."""
    lines = str(cmd or "").strip().splitlines()
    s = lines[0].strip() if lines else ""
    more = len(lines) > 1
    for _ in range(8):
        before = s
        for rx in _LEAD_NOISE_RES:
            s = rx.sub("", s, count=1)
        s = _ENV_PREFIX_RE.sub("", _WRAPPER_RE.sub("", s)).strip()
        if s == before:
            break
    s = s or (lines[0].strip() if lines else "")
    s = _INTERP_PATH_RE.sub(lambda m: m.group(1).lower().replace("pythonw", "python"), s)
    s = scrub_cmd(display_text_paths(s, root))
    if limit:
        s = ellipsize(s, limit - (2 if more else 0))
    if more and not s.endswith(ELLIPSIS):
        s = s.rstrip() + " " + ELLIPSIS
    return s
