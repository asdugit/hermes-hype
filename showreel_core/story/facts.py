"""Read-only view over a session's events + stats for the story stage.

Centralises defensive access to ``Event.data`` (stubs and missing keys are normal),
the set of numbers narration may mention, quote lookup that returns verbatim spans,
showable images (screenshots, product captures, artifact previews), command
classification and stat display values. Used by the prompt builder, validator,
heuristic and timing solver.
"""
from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from functools import cached_property
from typing import Any

from ..contracts import STAT_KEYS, Event, Stats
from .text import extract_numbers, normalize_ws, sentences, word_count

#: On-screen labels for stat keys (values are always computed by us).
STAT_LABELS: dict[str, str] = {
    "duration_s": "minutes", "tool_calls": "tool calls", "files_created": "files created",
    "files_modified": "files modified", "lines_added": "lines added", "lines_removed": "lines removed",
    "commands_run": "commands run", "tests_passed": "tests passing", "screenshots": "screenshots",
    "subagents": "subagents",
}

MESSAGE_KINDS = ("user_prompt", "assistant_note", "final_answer")
#: Kinds that can be shown as a picture (artifacts only when they have an image to show).
VISUAL_KINDS = ("product_capture", "screenshot", "image_generated", "artifact")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp")
_URL_RE = re.compile(r"https?://[^\s'\"<>()\[\]{}]+")
_QUOTE_MAP = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2014": "-", "\u2013": "-"})
_TEST_CMD_RE = re.compile(r"\b(pytest|jest|vitest|mocha|unittest|npm (?:run )?test|pnpm test|yarn test|cargo test|"
                          r"go test|tox|nox|rspec|phpunit|ctest|deno test|bun test)\b")
_SETUP_CMD_RE = re.compile(r"^\s*(?:sudo\s+)?(?:pip3?|pipx|uv|npm|pnpm|yarn|bun|cargo|brew|apt(?:-get)?|choco|"
                           r"winget|conda|poetry)\s+(?:install|add|i|sync|init|update|upgrade|pip install)\b"
                           r"|^\s*(?:git|mkdir|cd|ls|dir|cat|pwd|echo|which|where|type|head|tail|wc|touch|rm|cp|mv|"
                           r"chmod|clear|true|python3? -m venv|python3? --version|node --version)\b")
_TEST_PASS_RE = re.compile(r"\b(\d+)\s+(passed|passing|tests? passed|ok)\b", re.IGNORECASE)
_FAIL_COUNT_RE = re.compile(r"\b([1-9]\d*)\s+(failed|failing|errors?)\b", re.IGNORECASE)


def duration_minutes(seconds: float) -> int:
    """Whole minutes shown/spoken for a session duration (at least 1)."""
    return max(1, round(seconds / 60.0))


class SessionFacts:
    """Indexed, defensive access to events, stats and digest text.

    ``timestamps=True`` (speedrun films) also allows narration to mention the minute
    marks at which events happened ("tests go green at the four minute mark").
    """

    def __init__(self, events: Iterable[Event], stats: Stats | None = None, digest: str = "",
                 timestamps: bool = False) -> None:
        self.events: list[Event] = list(events)
        self.by_id: dict[str, Event] = {e.id: e for e in self.events}
        self.order: dict[str, int] = {e.id: i for i, e in enumerate(self.events)}
        self.stats: Stats = stats or Stats()
        self.digest: str = digest or ""
        self.timestamps = timestamps

    # ------------------------------------------------------------------ events
    def get(self, ref: str) -> Event | None:
        """Event by id or None."""
        return self.by_id.get(ref)

    def kind(self, ref: str) -> str | None:
        """Kind of event ``ref`` or None when unknown."""
        ev = self.by_id.get(ref)
        return ev.kind if ev else None

    def of_kind(self, *kinds: str) -> list[Event]:
        """Non-stub events of the given kinds, in session order."""
        return [e for e in self.events if e.kind in kinds and not is_stub(e)]

    def visuals(self) -> list[Event]:
        """Events with a showable image, in session order."""
        return [e for e in self.events if image_of(e) is not None]

    # ------------------------------------------------------------------ text
    @staticmethod
    def text_of(ev: Event) -> str:
        """The quotable text of an event (message text or terminal output)."""
        data = ev.data or {}
        if ev.kind in MESSAGE_KINDS:
            return str(data.get("text") or "")
        if ev.kind == "terminal":
            return "\n".join(str(x) for x in data.get("output_lines") or [])
        return ""

    def find_quote(self, ref: str, quote: str) -> str | None:
        """Verbatim span of event ``ref`` matching ``quote`` (case/whitespace/quote-mark tolerant)."""
        ev = self.by_id.get(ref)
        if ev is None or not quote.strip():
            return None
        return find_span(self.text_of(ev), quote)

    def quotable_sentences(self, ev: Event, min_words: int = 4, max_words: int = 12) -> list[str]:
        """Verbatim sentences/lines of ``ev`` that fit a CALLOUT (``min..max`` words).

        Whole sentences come first; long sentences contribute their longest leading run of
        clauses (cut at a comma) that fits.
        """
        source = self.text_of(ev)
        whole: list[str] = []
        clauses: list[str] = []
        for line in source.splitlines():
            for sent in sentences(line):
                sent = sent.strip(" -*#>`")
                if "`" in sent or "http" in sent:
                    continue
                if min_words <= word_count(sent) <= max_words:
                    if find_span(source, sent):
                        whole.append(sent)
                    continue
                parts = sent.split(", ")
                for k in range(1, len(parts)):
                    head = ", ".join(parts[:k])
                    if 3 <= word_count(head) <= max_words and find_span(source, head):
                        clauses.append(head)
                        break
        return whole + clauses

    @cached_property
    def corpus(self) -> str:
        """Session text used for URL/number/feature provenance (digest, titles, messages, outputs)."""
        parts = [self.digest]
        for ev in self.events:
            parts.append(ev.title)
            parts.append(ev.summary)
            parts.append(self.text_of(ev))
            data = ev.data or {}
            for key in ("url", "query", "cmd", "path", "page_title", "title"):
                if data.get(key):
                    parts.append(str(data[key]))
            for title in data.get("titles") or []:
                parts.append(str(title))
            if ev.kind == "todo":
                parts.extend(str(it.get("text", "")) for it in data.get("items") or [] if isinstance(it, dict))
            if ev.kind == "file_write" and os.path.basename(str(data.get("path", ""))).lower().startswith("readme"):
                parts.extend(str(x) for x in data.get("lines") or [])
        return "\n".join(p for p in parts if p)

    @cached_property
    def corpus_words(self) -> set[str]:
        """Lower-cased word set of the corpus plus identifier parts (for feature grounding)."""
        words: set[str] = set()
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9]+", self.corpus):
            words.add(tok.lower())
            for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", tok):
                words.add(part.lower())
        return words

    def urls(self) -> list[str]:
        """URLs that appear anywhere in the session corpus, in first-seen order."""
        seen: dict[str, None] = {}
        for m in _URL_RE.finditer(self.corpus):
            seen.setdefault(m.group(0).rstrip(".,;:"), None)
        return list(seen)

    def url_in_session(self, url: str) -> bool:
        """True when ``url`` (modulo a trailing slash) appears verbatim in the session."""
        url = (url or "").strip()
        if not url:
            return False
        return url in self.corpus or url.rstrip("/") in self.corpus

    @cached_property
    def paths(self) -> set[str]:
        """File paths the session touched (normalised to forward slashes)."""
        out: set[str] = set()
        for ev in self.events:
            p = (ev.data or {}).get("path")
            if p:
                out.add(str(p).replace("\\", "/"))
        return out

    @cached_property
    def project_root(self) -> str:
        """The project folder (``~/work/tempo``): film text shows paths relative to it (``src/app.js``)."""
        from .onscreen import project_root
        written = [str((e.data or {}).get("path") or "") for e in self.events
                   if e.kind in ("file_write", "file_patch", "artifact")]
        return project_root(written or self.paths, self.commands)

    def path_in_session(self, path: str) -> bool:
        """True when ``path`` equals or ends a path the session touched."""
        p = (path or "").replace("\\", "/").strip()
        if not p:
            return False
        return any(q == p or q.endswith("/" + p.lstrip("./")) for q in self.paths)

    @cached_property
    def commands(self) -> list[str]:
        """Terminal commands of the session, in order."""
        return [str(data_get(e, "cmd")) for e in self.events if e.kind == "terminal" and data_get(e, "cmd")]

    def command_in_session(self, cmd: str) -> bool:
        """True when ``cmd`` (whitespace-normalised) is, or starts, a command the session ran."""
        c = normalize_ws(cmd)
        return bool(c) and any(normalize_ws(x) == c or normalize_ws(x).startswith(c + " ") for x in self.commands)

    def grounded(self, phrase: str) -> bool:
        """True when a short phrase shares a content word (4+ letters) with the session text."""
        toks = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", phrase or "")]
        content = [t for t in toks if t not in _STOP]
        if not content:
            return False
        vocab = self.corpus_words
        return any(t in vocab or t.rstrip("s") in vocab or (len(t) > 5 and any(v.startswith(t[:5]) for v in vocab))
                   for t in content)

    # ------------------------------------------------------------------ numbers
    @cached_property
    def allowed_numbers(self) -> set[float]:
        """Numbers narration may mention: computed stats + numbers present in the session text."""
        allowed: set[float] = {1.0}
        for value in self.stats.to_dict().values():
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                allowed.add(float(value))
            elif isinstance(value, dict):
                allowed.update(float(v) for v in value.values() if isinstance(v, (int, float)))
        dur = float(self.stats.duration_s or 0)
        if dur > 0:
            mins = dur / 60.0
            allowed.update({float(duration_minutes(dur)), float(math.floor(mins)), float(math.ceil(mins)),
                            float(round(dur)), float(round(dur) % 60)})
            if dur >= 3600:
                allowed.update({float(round(dur / 3600.0)), float(int(dur) // 3600), float((int(dur) % 3600) // 60)})
        allowed.add(float(self.stats.files_created + self.stats.files_modified))
        for ev in self.events:
            data = ev.data or {}
            for key in ("adds", "dels"):
                if isinstance(data.get(key), int):
                    allowed.add(float(data[key]))
            if ev.kind == "todo" and isinstance(data.get("items"), list):
                allowed.add(float(len(data["items"])))
            if self.timestamps:
                allowed.update({float(math.floor(ev.t / 60.0)), float(round(ev.t / 60.0)), float(round(ev.t))})
        for n in extract_numbers(self.corpus):
            allowed.add(n.value)
        return allowed

    def number_allowed(self, value: float) -> bool:
        """True when ``value`` is a stat or appears in the session text."""
        return any(abs(value - a) < 1e-6 for a in self.allowed_numbers)

    # ------------------------------------------------------------------ stats
    def stat_value(self, key: str) -> float | None:
        """Display value for a stat key (duration in minutes), or None if absent/zero."""
        if key not in STAT_KEYS:
            return None
        raw = getattr(self.stats, key, None)
        if raw is None or isinstance(raw, bool):
            return None
        if key == "duration_s":
            return float(duration_minutes(raw)) if raw and raw > 0 else None
        return float(raw) if raw and raw > 0 else None

    def usable_stat_keys(self) -> list[str]:
        """Stat keys with a positive value, in :data:`STAT_KEYS` order."""
        return [k for k in STAT_KEYS if self.stat_value(k) is not None]


_STOP = {"with", "that", "this", "from", "your", "into", "over", "under", "each", "every", "them", "they", "their",
         "what", "when", "then", "than", "also", "just", "more", "most", "less", "make", "makes", "made", "using",
         "built", "build", "feature", "features", "support", "supports", "easy", "fast", "simple", "smart", "real",
         "live", "full", "page", "view", "tool", "able"}


# ---------------------------------------------------------------------- helpers

def is_stub(ev: Event) -> bool:
    """True for compaction stubs (only ``summary`` is reliable)."""
    return bool((ev.data or {}).get("stub"))


def image_of(ev: Event) -> dict[str, Any] | None:
    """The showable picture of an event, or None.

    Screenshots / generated images / product captures use ``data.path``; artifacts use
    ``preview_path`` or their own path when it is an image file. Returns verbatim fields:
    ``{path, w, h, url, full_page, page_title, source_kind}``.
    """
    if is_stub(ev) or ev.kind not in VISUAL_KINDS:
        return None
    data = ev.data or {}
    if (data.get("media_rank") or {}).get("junk"):
        return None             # a contact sheet / debug render / older retry (session.mediarank): never on screen
    path = ""
    if ev.kind == "artifact":
        if data.get("preview_path"):
            path = str(data["preview_path"])
        elif str(data.get("path", "")).lower().endswith(IMAGE_EXTS) or data.get("kind") == "image":
            path = str(data.get("path", ""))
    else:
        path = str(data.get("path") or "")
    if not path:
        return None
    # the picture's own pixel size first: an element crop's viewport (1440x900) is not its shape (2096x626)
    size = data.get("size") if isinstance(data.get("size"), (list, tuple)) and len(data["size"]) == 2 else None
    viewport = data.get("viewport") if isinstance(data.get("viewport"), (list, tuple)) else None
    w = data.get("w") or (size[0] if size else None) or (viewport[0] if viewport and len(viewport) == 2 else None)
    h = data.get("h") or (size[1] if size else None) or (viewport[1] if viewport and len(viewport) == 2 else None)
    return {"path": path, "w": w, "h": h, "url": data.get("url") or "", "full_page": bool(data.get("full_page")),
            "page_title": data.get("page_title") or "", "source_kind": ev.kind, "frame": picture_frame(ev)}


#: capture target kinds that are real web pages (DOM rects, an address bar that means something)
WEB_TARGETS = ("url", "html")


def picture_frame(ev: Event) -> str:
    """How a picture is presented: ``"browser"`` (address-bar window, cursor, focus ring) ONLY for a real web
    page capture or a session screenshot of an http(s) page; ``"card"`` (borderless, soft shadow, slow
    Ken-Burns move across the whole picture) for everything else: game/app/desktop screenshots, renders,
    generated images, captured image files, PDF pages."""
    data = ev.data or {}
    if data.get("frame_hint") in ("card", "browser"):       # set from the product kind (a game is never a web page)
        return str(data["frame_hint"])
    url = str(data.get("url") or "")
    if ev.kind == "product_capture":
        tk = str(data.get("target_kind") or "")
        if tk:
            return "browser" if tk in WEB_TARGETS else "card"
        return "browser" if re.match(r"(?:https?|file)://", url, re.I) and data.get("kind") not in (
            "image", "video") and not url.lower().split("?")[0].endswith(IMAGE_EXTS) else "card"
    if ev.kind == "screenshot" and re.match(r"https?://", url, re.I) and not url.lower().split("?")[0].endswith(
            IMAGE_EXTS):
        return "browser"
    return "card"


#: desktop capture kind -> its phone twin (the capture stage shoots both of every page)
_PORTRAIT_TWIN = {"viewport": "mobile", "full": "mobile_full"}


def portrait_twin(ev: Event, events: list[Event]) -> Event | None:
    """The phone capture of the same page as a landscape desktop picture ``ev`` (for 9:16 films), or None.

    Real E2E: a 9:16 film showed 1440x900 desktop captures tiny in the tall frame while a 390x844 capture
    of the same page existed. Element crops and pictures that are already upright keep their own picture.
    """
    data = ev.data or {}
    url = str(data.get("url") or "").rstrip("/")
    img = image_of(ev)
    if not url or img is None:
        return None
    w, h = img.get("w") or 0, img.get("h") or 0
    if ev.kind == "product_capture":
        want = _PORTRAIT_TWIN.get(str(data.get("kind") or ""))
    elif ev.kind == "screenshot" and w and h and w > h * 1.2:
        want = "mobile"
    else:
        want = None
    if want is None:
        return None
    for other in events:
        od = other.data or {}
        if (other.kind == "product_capture" and other.ok and od.get("kind") == want
                and str(od.get("url") or "").rstrip("/") == url and image_of(other) is not None):
            return other
    return None


def code_lines(ev: Event) -> list[str]:
    """Lines of a file_write event (empty for stubs/missing)."""
    lines = (ev.data or {}).get("lines") or []
    return [str(x) for x in lines] if isinstance(lines, list) else []


def diff_rows(ev: Event) -> list[tuple[int, str, str]]:
    """Flattened diff rows ``(hunk_index, op, text)`` of a file_patch (op in '+', '-', ' ', '@')."""
    rows: list[tuple[int, str, str]] = []
    for hi, hunk in enumerate((ev.data or {}).get("hunks") or []):
        if not isinstance(hunk, dict):
            continue
        for line in hunk.get("lines") or []:
            if isinstance(line, (list, tuple)) and len(line) == 2:
                rows.append((hi, str(line[0])[:1] or " ", str(line[1])))
    return rows


def terminal_ok(ev: Event) -> bool:
    """True for a terminal event that exited 0 (or ok without an exit code)."""
    code = (ev.data or {}).get("exit_code")
    return (code == 0) if code is not None else bool(ev.ok)


def is_test_cmd(cmd: str) -> bool:
    """True for test-runner commands (pytest, jest, cargo test, ...)."""
    return bool(_TEST_CMD_RE.search(cmd or ""))


_SERVER_CMD_RE = re.compile(
    r"\b(npx (?:-y )?(?:serve|http-server|live-server|vite)|python3? -m http\.server|(?:npm|pnpm|yarn) (?:run )?"
    r"(?:dev|start|serve|preview)\b|vite(?: dev| preview)?$|next (?:dev|start)|flask run|uvicorn|gunicorn|"
    r"rails s(?:erver)?|php -S|hugo server|jekyll serve)", re.IGNORECASE)


def is_server_cmd(cmd: str) -> bool:
    """True for commands that only start a dev/static server (they belong in the CTA, not in a demo)."""
    return bool(_SERVER_CMD_RE.search(cmd or ""))


def is_setup_cmd(cmd: str) -> bool:
    """True for install/housekeeping commands that demo nothing (pip install, git, ls, ...)."""
    return bool(_SETUP_CMD_RE.search(cmd or ""))


def looks_like_test_pass(ev: Event) -> bool:
    """A terminal run that exited cleanly and reports passing tests (and no failures)."""
    if ev.kind != "terminal" or not terminal_ok(ev):
        return False
    text = SessionFacts.text_of(ev)
    if _FAIL_COUNT_RE.search(text):
        return False
    return bool(_TEST_PASS_RE.search(text)) or is_test_cmd(str((ev.data or {}).get("cmd") or ""))


def looks_like_failure(ev: Event) -> bool:
    """A terminal run that failed (non-zero exit or reported failures)."""
    if ev.kind != "terminal":
        return False
    return not terminal_ok(ev) or bool(_FAIL_COUNT_RE.search(SessionFacts.text_of(ev)))


def is_demo_run(ev: Event) -> bool:
    """A successful terminal run that exercises the product (not a test, install or housekeeping)."""
    cmd = str((ev.data or {}).get("cmd") or "")
    out = [x for x in (ev.data or {}).get("output_lines") or [] if str(x).strip()]
    return (ev.kind == "terminal" and terminal_ok(ev) and bool(out) and not is_test_cmd(cmd)
            and not is_setup_cmd(cmd) and not is_server_cmd(cmd))


def find_span(source: str, needle: str) -> str | None:
    """Find ``needle`` in ``source`` ignoring case, whitespace runs and curly quotes; return the verbatim span."""
    if not source or not needle:
        return None
    norm_chars: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(source):
        c = ch.translate(_QUOTE_MAP).lower()
        if c.isspace():
            if prev_space:
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        norm_chars.append(c)
        index.append(i)
    norm = "".join(norm_chars)
    target = normalize_ws(needle.translate(_QUOTE_MAP).lower()).strip(" \"'")
    target = target.rstrip(".,;:!?") or target
    if not target:
        return None
    pos = norm.find(target)
    if pos < 0:
        return None
    start = index[pos]
    end = index[pos + len(target) - 1] + 1
    while end < len(source) and source[end] in ".!?":
        end += 1
    return source[start:end]


def short_arg(ev: Event, limit: int = 40) -> str:
    """Short human argument for montage cards: path, command, URL or query."""
    data = ev.data or {}
    for key in ("path", "cmd", "url", "query"):
        if data.get(key):
            return clip(str(data[key]), limit)
    return clip(ev.title or ev.summary or ev.tool or ev.kind, limit)


def clip(text: str, limit: int) -> str:
    """Whitespace-normalised ``text`` cut to ``limit`` chars with an ellipsis (display only)."""
    text = normalize_ws(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def first_line(text: str) -> str:
    """First non-empty line of ``text``."""
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def data_get(ev: Event, key: str, default: Any = None) -> Any:
    """``ev.data[key]`` with a default (data may be empty for stubs)."""
    return (ev.data or {}).get(key, default)
