"""Screenshot harness for the Desktop pane (dev-only; not a test and not shipped to users).

``SR_SNAPSHOT_DIR=<snap> node render_check.mjs`` writes the markup of key screens. This script wraps each one
in a page with an approximate Hermes theme (dark or light: the ``--ui-*`` / ``--dt-*`` variables the plugin
reads, plus look-alike styles for the stub SDK components) and screenshots it with Hype's own headless
Chromium (``showreel_core.render.workers.capture_stills``). Icons are blank (no codicon font) and the core
video player is a grey box: the real app is the reference; this is for layout and theme checks.

    python tests/desktop/snapshot.py <snap dir> <out dir> [dark|light]

On a machine shared by several render agents set HYPE_RENDER_SLOT_DIR to the folder holding the
``render.slot1..3`` files; one slot is held while Chromium runs.
"""
from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

THEMES = {
    "dark": {"--dt-background": "#121417", "--ui-text-primary": "#e9e9ec", "--ui-text-secondary": "#b6b8be",
             "--ui-text-tertiary": "#8b8e95", "--ui-text-quaternary": "#6a6d73", "--ui-stroke-primary": "#3b3e44",
             "--ui-stroke-secondary": "#30333a", "--ui-stroke-tertiary": "#262930", "--ui-accent": "#8aa4ff",
             "--ui-bg-card": "#181a1f", "--ui-bg-quaternary": "#1d2026", "--ui-red": "#f07070", "--ui-green": "#62d38f",
             "--ui-yellow": "#e9c35e"},
    "light": {"--dt-background": "#fbfbfa", "--ui-text-primary": "#1d1f23", "--ui-text-secondary": "#4a4d55",
              "--ui-text-tertiary": "#73767e", "--ui-text-quaternary": "#9a9ca2", "--ui-stroke-primary": "#c9cbd0",
              "--ui-stroke-secondary": "#dcdde1", "--ui-stroke-tertiary": "#e6e7ea", "--ui-accent": "#3f63e0",
              "--ui-bg-card": "#ffffff", "--ui-bg-quaternary": "#f0f1f3", "--ui-red": "#d84a4a", "--ui-green": "#2e9e5e",
              "--ui-yellow": "#c99a1c"},
}
SIZES = {"pane": (int(os.environ.get("SR_PANE_WIDTH") or 400), 1100), "page": (1280, 1000), "bar": (420, 40), "card": (660, 460)}
STUB_CSS = """
html,body{margin:0;background:var(--dt-background);color:var(--ui-text-primary);font:13px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif}
.frame{box-sizing:border-box;height:100vh;overflow:hidden}
*{box-sizing:border-box}
button[data-variant]{display:inline-flex;align-items:center;gap:6px;font:500 12px/16px inherit;font-family:inherit;padding:6px 12px;border:0;border-radius:3px;cursor:pointer;
 background:var(--ui-bg-quaternary);color:var(--ui-text-primary)}
button[data-variant=default]{background:var(--ui-accent);color:var(--dt-background)}
button[data-variant=outline]{background:transparent;box-shadow:inset 0 0 0 1px var(--ui-stroke-secondary)}
button[data-variant=ghost]{background:transparent;color:var(--ui-text-secondary)}
button[data-variant]:disabled{opacity:.5}
[data-seg]{display:inline-flex;gap:2px;padding:2px;border-radius:4px;background:var(--ui-bg-quaternary)}
[data-seg] button{border:0;background:transparent;color:var(--ui-text-secondary);font:inherit;font-size:12px;padding:3px 9px;border-radius:3px}
[data-seg] button[aria-pressed=true]{background:var(--ui-bg-card);color:var(--ui-text-primary);box-shadow:0 0 0 1px var(--ui-stroke-secondary)}
button[role=switch]{width:30px;height:16px;border-radius:9px;border:0;background:var(--ui-stroke-primary);position:relative}
button[role=switch][aria-checked=true]{background:var(--ui-accent)}
button[role=switch]::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--ui-text-primary)}
button[role=switch][aria-checked=true]::after{left:16px;background:var(--dt-background)}
textarea,input{font:inherit;color:inherit;background:transparent;border:0;box-shadow:inset 0 0 0 1px var(--ui-stroke-secondary);border-radius:4px;padding:6px 8px;width:100%;resize:vertical}
[data-media]{aspect-ratio:16/9;border-radius:8px;background:repeating-linear-gradient(135deg,var(--ui-bg-quaternary) 0 12px,var(--ui-bg-card) 12px 24px);display:grid;place-items:center}
[data-media]::after{content:"core video player";color:var(--ui-text-tertiary);font-size:12px}
.codicon{display:inline-block;width:12px;height:12px;border-radius:2px;background:currentColor;opacity:.35;vertical-align:-1px}
video[data-fallback]{display:block;width:100%;aspect-ratio:16/9;background:var(--ui-bg-quaternary)}
"""


@contextlib.contextmanager
def render_slot() -> Iterator[None]:
    """Hold one ``render.slotN`` file under $HYPE_RENDER_SLOT_DIR while Chromium runs (no-op when unset)."""
    folder = os.environ.get("HYPE_RENDER_SLOT_DIR", "")
    if not folder:
        yield
        return
    held = None
    while held is None:
        for k in (1, 2, 3):
            p = Path(folder) / f"render.slot{k}"
            with contextlib.suppress(OSError):
                if p.exists() and time.time() - p.stat().st_mtime >= 900:
                    p.unlink()
            try:
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            os.write(fd, f"w3-desktop-snapshot {os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}".encode())
            os.close(fd)
            held = p
            break
        if held is None:
            time.sleep(5)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            held.unlink()


def build_pages(snap: Path, theme: str) -> list[tuple[str, str, tuple[int, int]]]:
    """Wrap every ``<variant>-<name>.html`` snapshot into a themed page; returns (stem, page file, size)."""
    vars_css = ":root{" + ";".join(f"{k}:{v}" for k, v in THEMES[theme].items()) + ";color-scheme:" + theme + "}"
    pages = []
    for f in sorted(snap.glob("*.html")):
        if f.name.startswith("_"):
            continue
        variant = f.stem.split("-", 1)[0]
        w, h = SIZES.get(variant, (400, 900))
        body = f.read_text(encoding="utf-8")
        html = ("<!doctype html><html><head><meta charset='utf-8'><style>" + vars_css + STUB_CSS + "</style>"
                "<script>window.__sr={ready:Promise.resolve(),dur:1,fps:1,seek:async()=>{}}</script></head>"
                f"<body><div class='frame' style='width:{w}px;height:{h}px'>{body}</div></body></html>")
        out = snap / f"_{theme}-{f.name}"
        out.write_text(html, encoding="utf-8")
        pages.append((f.stem, out.name, (w, h)))
    return pages


def main(argv: list[str]) -> int:
    snap, out = Path(argv[0]), Path(argv[1])
    theme = argv[2] if len(argv) > 2 else "dark"
    out.mkdir(parents=True, exist_ok=True)
    from showreel_core.render.workers import capture_stills
    with render_slot():
        for stem, page, (w, h) in build_pages(snap, theme):
            res = capture_stills(snap, page, [1.2], w=w, h=h, fmt="png")
            if not res.ok:
                print(f"{stem}: FAILED {res.error}")
                continue
            target = out / f"{theme}-{stem}.png"
            target.write_bytes(res.images[0])
            print(f"{stem}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
