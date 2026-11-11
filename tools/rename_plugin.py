#!/usr/bin/env python3
"""Rename the plugin's user-facing identity in one go (catalog name conflict, ISSUES #44).

    python tools/rename_plugin.py --name auteur --title Auteur --dry-run     # list every change
    python tools/rename_plugin.py --name auteur --title Auteur               # apply to this tree
    python tools/rename_plugin.py --name auteur --title Auteur --catalog ../catalog

What changes (all text files of the tree, plus file and folder names):

* the brand ``Showreel`` -> ``<Title>`` (README, docs, CHANGELOG, kit end-card credits, Desktop labels, palette
  entries, status chip, messages; ``a Showreel`` becomes ``an <Title>`` when the title starts with a vowel);
* every identifier ``showreel`` -> ``<name>``: manifest name, ``/showreel``, ``showreel_render`` /
  ``showreel_status``, ``hermes showreel``, the toolset and auxiliary task, ``plugins.entries.showreel``,
  ``plugin-data/showreel``, the dashboard route prefix, ``plugin.showreel.*`` events, the Desktop plugin id and
  route, the bundled skill (``skills/showreel/`` is moved to ``skills/<name>/``) and the test expectations;
* ``SHOWREEL_*`` environment variables -> ``<NAME>_*``;
* the common noun ("a showreel is already rendering", "your showreel") -> "film", because the noun reads wrong as
  a brand name.

What stays (internal, not user-facing): the Python package ``showreel_core``, the runtime module
``runtime/showreel.js``, the GitHub repo slug ``hermes-showreel`` (``--repo-slug`` renames it), developer paths
(``showreel-work``, ``showreel-scratch``, ``showreel-e2e``), the other catalog plugin ``Duffey234/hermes-showreel``,
and the trigger phrases an agent should still react to ("demo reel or showreel", ``demo reel, "showreel"``).
This tool and its tests are never rewritten.

``--catalog DIR`` also rewrites the catalog drafts (``showreel-studio`` / ``Showreel Studio`` become the new key and
title, ``*.yaml`` and ``*.md`` files named after the plugin are renamed) and deletes the lines and blocks that only
exist because of the name conflict: yaml lines ending in ``# naming:conflict`` and Markdown between
``<!-- naming:conflict -->`` and ``<!-- /naming:conflict -->``. ``NAMING.md`` itself is never touched.

The rewrite is idempotent: a second run with the same name finds nothing to do. Binary files (NUL bytes or not
UTF-8), ``.git``, ``node_modules``, ``__pycache__`` and vendored libraries are skipped. Line endings are preserved.
Exit code 0 on success (or nothing to do), 2 on bad arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

OLD = "showreel"
OLD_TITLE = "Showreel"
OLD_UPPER = "SHOWREEL"
OLD_CATALOG_KEY = "showreel-studio"
OLD_CATALOG_TITLE = "Showreel Studio"

#: Kept verbatim (internal names, other people's plugin, dev paths, generic trigger phrases), as regexes.
PROTECTED = (
    r"Duffey234/hermes-showreel",
    r"demo reel or showreel",
    r'demo reel, "showreel"',
    r"showreel_core",
    r"showreel\.js\b",
    r"showreel-(?:work|scratch|e2e)\b",
)
REPO_RE = r"hermes-showreel"

#: Skipped folders, and files with these names (a worktree's ``.git`` is a file pointing at the main repo).
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv",
             "venv", "vendor", "out", "renders", "jobs"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".ico", ".mp4", ".webm", ".mov", ".ogg",
                 ".mp3", ".wav", ".flac", ".woff", ".woff2", ".ttf", ".otf", ".glb", ".gltf", ".blend", ".zip",
                 ".gz", ".pyc", ".pyo", ".db", ".pdf"}
#: Never rewritten: the decision doc and this tool + its tests (they must keep saying "showreel").
KEEP_FILES = {"NAMING.md", "rename_plugin.py", "test_rename_plugin.py"}
NAME_RE = re.compile(r"^[a-z][a-z0-9]{2,30}$")
#: The common noun: "a showreel", "your showreel", "no showreel yet" -> "film" (not followed by an identifier
#: character, so "the showreel_render tool" and "a showreel plugin" are left to the identifier rules).
NOUN_RE = re.compile(r"\b(a|A|an|An|the|The|your|Your|my|My|no|No|this|This|one|One) showreel(s?)\b(?![_\-/:]|\.\w)")
CONFLICT_LINE = re.compile(r"#\s*naming:conflict\s*$")
CONFLICT_BLOCK = re.compile(r"[ \t]*<!-- naming:conflict -->.*?<!-- /naming:conflict -->[ \t]*\r?\n?", re.S)


@dataclass
class Change:
    path: str
    kind: str                      # "edit" | "move" | "drop"
    detail: str = ""
    count: int = 0
    samples: list[str] = field(default_factory=list)


def _hide(text: str, patterns: tuple[str, ...]) -> tuple[str, list[str]]:
    """Swap protected spans for NUL-delimited placeholders (restored by :func:`_show`)."""
    kept: list[str] = []

    def keep(m: re.Match) -> str:
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"
    for pat in patterns:
        text = re.sub(pat, keep, text)
    return text, kept


def _show(text: str, kept: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)


def rewrite(text: str, name: str, title: str, *, repo_slug: str = "", catalog: bool = False) -> str:
    """The renamed text (pure function; idempotent for a fixed ``name``/``title``)."""
    if catalog:
        text = CONFLICT_BLOCK.sub("", text)
        text = "".join(ln for ln in text.splitlines(keepends=True) if not CONFLICT_LINE.search(ln.rstrip("\r\n")))
        text = text.replace(OLD_CATALOG_KEY, name).replace(OLD_CATALOG_TITLE, title)
    text, kept = _hide(text, PROTECTED + (() if repo_slug else (REPO_RE,)))
    if repo_slug:
        text = re.sub(REPO_RE, repo_slug, text)
    text = re.sub(r"\b([Tt]he|[Aa]) showreel plugin\b", lambda m: f"{m.group(1)} {name} plugin", text)
    text = NOUN_RE.sub(lambda m: f"{ {'an': 'a', 'An': 'A'}.get(m.group(1), m.group(1))} film{m.group(2)}", text)
    text = text.replace(OLD_UPPER, name.upper()).replace(OLD_TITLE, title).replace(OLD, name)
    if title[:1].lower() in "aeiou":
        text = re.sub(rf"\b([Aa]) {re.escape(title)}\b", lambda m: f"{m.group(1)}n {title}", text)
    return _show(text, kept)


def new_path(rel: str, name: str, *, catalog: bool = False) -> str:
    """A path with the plugin's name in it, renamed (internal module paths stay)."""
    parts = rel.replace("\\", "/").split("/")
    out = []
    for part in parts:
        if part in ("showreel_core", "showreel.js") or part in KEEP_FILES:
            out.append(part)
        elif catalog and part.startswith(OLD_CATALOG_KEY):
            out.append(name + part[len(OLD_CATALOG_KEY):])
        else:
            out.append(re.sub(r"(?<![a-z])showreel(?![a-z_])", name, part))
    return "/".join(out)


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix.lower() in SKIP_SUFFIXES or fn in KEEP_FILES or fn in SKIP_DIRS or p.is_symlink():
                continue
            yield p


def plan(root: Path, name: str, title: str, *, repo_slug: str = "", catalog: bool = False) -> list[Change]:
    changes: list[Change] = []
    for p in iter_files(root):
        rel = p.relative_to(root).as_posix()
        data = p.read_bytes()
        if _is_text(data):
            before = data.decode("utf-8")
            after = rewrite(before, name, title, repo_slug=repo_slug, catalog=catalog)
            if after != before:
                b_lines, a_lines = before.splitlines(), after.splitlines()
                samples = [f"- {b.strip()[:110]}\n  + {a.strip()[:110]}" for b, a in zip(b_lines, a_lines)
                           if a != b][:3]
                n = sum(1 for b, a in zip(b_lines, a_lines) if a != b) + abs(len(b_lines) - len(a_lines))
                changes.append(Change(rel, "edit", count=n, samples=samples))
        target = new_path(rel, name, catalog=catalog)
        if target != rel:
            changes.append(Change(rel, "move", detail=target))
    return changes


def apply(root: Path, changes: list[Change], name: str, title: str, *, repo_slug: str = "",
          catalog: bool = False) -> None:
    for c in changes:
        if c.kind == "edit":
            p = root / c.path
            text = p.read_bytes().decode("utf-8")
            p.write_bytes(rewrite(text, name, title, repo_slug=repo_slug, catalog=catalog).encode("utf-8"))
    for c in changes:
        if c.kind == "move":
            src, dst = root / c.path, root / c.detail
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
    for c in changes:                       # remove folders left empty by the moves (skills/showreel/)
        if c.kind == "move":
            d = (root / c.path).parent
            while d != root and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent


def leftovers(root: Path) -> list[str]:
    """``file:line: text`` for every remaining 'showreel' outside the protected names (should be empty)."""
    out = []
    for p in iter_files(root):
        data = p.read_bytes()
        if not _is_text(data):
            continue
        for i, line in enumerate(data.decode("utf-8").splitlines(), 1):
            hidden, _ = _hide(line, PROTECTED + (REPO_RE,))
            if re.search("showreel", hidden, re.I):
                out.append(f"{p.relative_to(root).as_posix()}:{i}: {line.strip()[:140]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--name", required=True, help="new plugin id: lowercase letters/digits, e.g. auteur")
    ap.add_argument("--title", default="", help="new brand title (default: Name capitalised)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="plugin tree (default: repo)")
    ap.add_argument("--repo-slug", default="", help="also rename the GitHub repo slug hermes-showreel to this")
    ap.add_argument("--catalog", default="", help="also rewrite the catalog drafts in this folder")
    ap.add_argument("--dry-run", action="store_true", help="list every change, write nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable plan")
    args = ap.parse_args(argv)

    name, title = args.name.strip(), (args.title.strip() or args.name.strip().capitalize())
    if not NAME_RE.match(name) or name == OLD:
        print(f"--name must match {NAME_RE.pattern} and differ from {OLD!r}", file=sys.stderr)
        return 2
    if not re.match(r"^[A-Z][A-Za-z0-9 ]{1,40}$", title):
        print("--title must start with a capital letter (letters, digits, spaces)", file=sys.stderr)
        return 2
    if args.repo_slug and not re.match(r"^[A-Za-z0-9._-]{1,100}$", args.repo_slug):
        print("--repo-slug is not a valid GitHub repository name", file=sys.stderr)
        return 2
    trees = [(Path(args.root).resolve(), False)]
    if args.catalog:
        trees.append((Path(args.catalog).resolve(), True))
    report: dict[str, list[dict]] = {}
    for root, is_cat in trees:
        if not root.is_dir():
            print(f"not a folder: {root}", file=sys.stderr)
            return 2
        changes = plan(root, name, title, repo_slug=args.repo_slug, catalog=is_cat)
        report[str(root)] = [c.__dict__ for c in changes]
        if not args.json:
            edits = [c for c in changes if c.kind == "edit"]
            moves = [c for c in changes if c.kind == "move"]
            print(f"{root}: {len(edits)} file(s) to edit ({sum(c.count for c in edits)} lines), "
                  f"{len(moves)} to move" + (" [dry run]" if args.dry_run else ""))
            for c in changes:
                if c.kind == "move":
                    print(f"  move  {c.path} -> {c.detail}")
                else:
                    print(f"  edit  {c.path} ({c.count} line(s))")
                    for s in c.samples if args.dry_run else []:
                        print("        " + s.replace("\n", "\n        "))
        if not args.dry_run:
            apply(root, changes, name, title, repo_slug=args.repo_slug, catalog=is_cat)
            rest = leftovers(root)
            if rest and not args.json:
                print(f"  {len(rest)} line(s) still say 'showreel' (protected names excluded):")
                for line in rest[:40]:
                    print("    " + line)
    if args.json:
        print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
