"""Small text helpers shared by the session pipeline (stdlib only)."""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"      # OSC ... BEL / ST
    r"|\x1b\[[0-?]*[ -/]*[@-~]"               # CSI
    r"|\x1b[PX^_][^\x1b]*\x1b\\"              # DCS/SOS/PM/APC
    r"|\x1b[@-Z\\-_]"                         # other 2-byte escapes
    r"|\x9b[0-?]*[ -/]*[@-~]"                 # 8-bit CSI
)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_LINE_CHARS = 240

_LANGS = {
    "py": "python", "pyi": "python", "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "jsx": "jsx", "ts": "typescript", "tsx": "tsx", "json": "json", "jsonc": "json", "md": "markdown",
    "markdown": "markdown", "html": "html", "htm": "html", "css": "css", "scss": "scss", "sh": "bash",
    "bash": "bash", "zsh": "bash", "ps1": "powershell", "bat": "batch", "cmd": "batch", "lua": "lua",
    "luau": "lua", "rs": "rust", "go": "go", "java": "java", "kt": "kotlin", "c": "c", "h": "c",
    "cc": "cpp", "cpp": "cpp", "hpp": "cpp", "cs": "csharp", "rb": "ruby", "php": "php",
    "yaml": "yaml", "yml": "yaml", "toml": "toml", "ini": "ini", "cfg": "ini", "sql": "sql",
    "swift": "swift", "vue": "vue", "svelte": "svelte", "xml": "xml", "svg": "xml", "glsl": "glsl",
    "frag": "glsl", "vert": "glsl", "txt": "text", "csv": "csv", "r": "r", "dart": "dart",
    "scala": "scala", "zig": "zig", "nix": "nix", "tf": "hcl", "gd": "gdscript", "ex": "elixir",
}
_NAMED_LANGS = {"dockerfile": "dockerfile", "makefile": "makefile", "cmakelists.txt": "cmake"}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def strip_ansi(text: str) -> str:
    """Remove ANSI/VT escape sequences."""
    return _ANSI_RE.sub("", text)


def clean_text(text: str) -> str:
    """ANSI-strip, normalise newlines, resolve carriage-return overwrites, drop control chars."""
    text = strip_ansi(text).replace("\r\n", "\n")
    if "\r" in text:
        text = "\n".join(line.rsplit("\r", 1)[-1] if "\r" in line.rstrip("\r") else line.rstrip("\r")
                         for line in text.split("\n"))
    text = text.replace("\t", "    ")
    return _CTRL_RE.sub("", text)


def _is_binary_line(line: str) -> bool:
    if not line or ("\ufffd" not in line and line.isascii()):
        return False
    bad = sum(1 for ch in line if ch == "\ufffd" or (0xD800 <= ord(ch) <= 0xDFFF))
    return bad / len(line) > 0.3


def clip(text: str, n: int) -> str:
    """Single-line clip to ``n`` chars with an ellipsis."""
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: max(0, n - 1)].rstrip() + "…"


def clip_line(line: str, n: int = MAX_LINE_CHARS) -> str:
    return line if len(line) <= n else line[: n - 1] + "…"


def output_lines(text: str, max_lines: int = 40, head: int = 12) -> tuple[list[str], int, int | None]:
    """Cleaned output as (lines, total_lines, gap_index).

    Keeps the first ``head`` and the last ``max_lines - head`` lines when longer; ``gap_index`` is the
    position in ``lines`` where lines were omitted (renderers draw their own separator), else None.
    Binary-looking lines are dropped. Lines longer than ``MAX_LINE_CHARS`` are clipped.
    """
    lines = [clip_line(l.rstrip()) for l in clean_text(text or "").split("\n")]
    lines = [l for l in lines if not _is_binary_line(l)]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    total = len(lines)
    if total <= max_lines:
        return lines, total, None
    tail = max_lines - head
    return lines[:head] + lines[-tail:], total, head


def lang_for(path: str) -> str:
    """Language id for syntax highlighting from a file name ("" if unknown)."""
    name = basename(path).lower()
    if name in _NAMED_LANGS:
        return _NAMED_LANGS[name]
    if "." not in name:
        return ""
    return _LANGS.get(name.rsplit(".", 1)[-1], "")


def basename(path: str) -> str:
    return PureWindowsPath(path).name if "\\" in path else PurePosixPath(path).name


_HOME_PREFIX_RE = re.compile(r"^(?:[A-Za-z]:|/mnt/[a-z]|/[a-z](?=/users/))?/+(?:users|home)/[^/]+", re.I)


def short_path(path: str, parts: int = 3) -> str:
    """Last ``parts`` components with forward slashes; a home-dir prefix becomes ``~`` so user names
    never leak into labels (``C:/Users/alice/proj/a.py`` → ``~/proj/a.py``)."""
    p = str(path).replace("\\", "/").rstrip("/")
    while "//" in p:
        p = p.replace("//", "/")
    p = _HOME_PREFIX_RE.sub("~", p)
    comps = [c for c in p.split("/") if c]
    return "/".join(comps[-parts:]) if comps else p


def norm_path(path: str) -> str:
    """Comparison key for paths across Windows/POSIX spellings."""
    p = str(path).strip().replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    if re.match(r"^[A-Za-z]:/", p) or re.match(r"^/[a-z]/", p):
        p = p.lower()
        if re.match(r"^/[a-z]/", p):
            p = p[1] + ":" + p[2:]
    return p


def is_local_path(s: str) -> bool:
    s = s.strip()
    return bool(re.match(r"^(?:[A-Za-z]:[\\/]|/|~[\\/]|\\\\)", s)) and not s.startswith("//")


def first_comment_or_line(code: str) -> tuple[str, str]:
    """(step label from a leading ``# comment``, first meaningful code line)."""
    label = ""
    first = ""
    for raw in (code or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") and not label and not first:
            label = line.lstrip("#").strip()
            continue
        if not line.startswith("#"):
            first = line
            break
    return label, first
