"""Deterministic storyboard builder with no LLM (fallback and CI), for all three film modes.

* ``product`` (default): a launch trailer. The product is the hero: HOOK on its best
  visual or demo output, TITLE with name + one-liner, 2-6 product beats (FEATURE / SCROLL /
  SCREEN, or TERMINAL demos for CLIs, BEFORE_AFTER for bug fixes), then a short "built
  with Hermes" beat (tests, montage, STATS) and END with the product's call to action.
* ``making_of`` (lore): problem, plan, real struggle, breakthrough, result, stats, in order.
* ``speedrun``: chronological milestones with 4-7 splits, time-lapse montages, PB card.

Narration comes from templates that are always true for the chosen evidence; scenes
where a template would sound robotic get no narration (labels and captions carry them).
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Iterator

from ..contracts import SCENE_RULES, Event, Product, SceneType, Stats, Storyboard, StoryScene
from .facts import (SessionFacts, code_lines, data_get, diff_rows, image_of, is_demo_run, is_server_cmd, is_stub,
                    looks_like_failure, looks_like_test_pass, terminal_ok)
from .milestones import detect_milestones
from .options import StoryOptions
from .rules import (DROP_PRIORITY, MAX_BUILD_SHARE, NON_TOOL_KINDS, SPLITS_MAX, SPLITS_MIN, VO_WORD_CAPS, film_mode,
                    max_type_count, scene_count_range)
from .schema import CTA_CHARS, LABEL_WORDS, ONE_LINER_CHARS, TAGLINE_CHARS, TITLE_CHARS
from .text import normalize_ws, sentences, spell_number, trim_chars, trim_label, word_count
from .validate import chrono_key, default_stat_keys, scene_role

T = SceneType

_GENERIC_DIRS = {
    "src", "lib", "libs", "tests", "test", "docs", "doc", "app", "apps", "packages", "pkg", "internal", "cmd",
    "components", "utils", "util", "scripts", "public", "static", "assets", "home", "users", "user", "projects",
    "project", "code", "dev", "repos", "repo", "workspace", "tmp", "temp", "desktop", "documents", "downloads",
    "build", "dist", "out", "bin", "node_modules", "site-packages", "venv", ".venv", "~", "", ".", "..",
    "appdata", "local", "c:", "d:", "mnt", "var", "opt", "usr", "github", "git", "work", "styles", "templates",
    "samples", "data", "examples", "fixtures",
}
GENERIC_NAME = "Session Highlights"
#: Share of the scenes' summed max durations the solver can rely on (half-bar snapping eats the rest).
CAPACITY_MARGIN = 0.85
_GENERIC_STEMS = {"index", "main", "__init__", "init", "utils", "util", "app", "mod", "lib", "setup", "conftest",
                  "readme", "config", "settings", "__main__", "helpers", "common", "types", "style", "styles"}
_LOW_VALUE_EXT = {".md", ".txt", ".json", ".lock", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".gitignore",
                  ".csv", ".env", ".log"}
_ENTRY_NAMES = {"index.html", "main.py", "app.py", "server.py", "cli.py", "__main__.py", "main.js", "index.js",
                "server.js", "app.js", "main.ts", "index.ts", "main.rs", "main.go", "app.tsx", "main.tsx", "readme.md"}
_INSTALL_RE = re.compile(r"((?:pip|pipx|uv pip|uv tool) install [\w.\-\[\]=<>]+|npm (?:i|install) -g [\w@/.\-]+"
                         r"|git clone \S+|cargo install [\w\-]+|brew install [\w\-/]+"
                         r"|hermes plugins install [\w/.\-]+)")
_GITHUB_RE = re.compile(r"https://github\.com/[\w.\-]+/[\w.\-]+")
_LOCAL_RE = re.compile(r"^(?:https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])|file:)", re.I)
_CLI_HINT_RE = re.compile(r"\b(argparse|click|typer|clap|commander|yargs|cobra|sys\.argv|process\.argv)\b")
_ASK_CLAUSE_RE = re.compile(r"\b(?:that|which)\s+((?:[a-z]+s)\b[^.?!]*)", re.I)
_MAKE_ME_RE = re.compile(r"\b(?:make|build|create|write|code)\s+(?:me\s+|us\s+)?(an?\s+[^.?!]*)", re.I)
_TODO_SKIP_RE = re.compile(r"\b(tests?|testing|setup|set up|install|scaffold|refactor|lint|commit|readme|docs?|"
                           r"deploy|cleanup|clean up|investigate|research|plan)\b", re.I)


def build_heuristic_storyboard(events: list[Event], stats: Stats | None, options: StoryOptions | None = None,
                               digest: str = "", product: Product | None = None) -> Storyboard:
    """Build a good storyboard deterministically from events + stats (no LLM).

    ``product`` is an optional draft from the session stage; missing fields are inferred.
    """
    options = options or StoryOptions()
    mode = film_mode(options.mode)
    facts = SessionFacts(events, stats, digest, timestamps=(mode == "speedrun"))
    prod = infer_product(facts, product)
    builder = {"product": _ProductFilm, "making_of": _MakingOfFilm, "speedrun": _SpeedrunFilm}[mode]
    return builder(facts, options, prod).build()


# --------------------------------------------------------------------------- product

def infer_product(facts: SessionFacts, draft: Product | None = None) -> Product:
    """Infer the product the session built, keeping any non-empty fields of ``draft``."""
    d = draft or Product()
    kind = d.kind or _product_kind(facts)
    return Product(
        name=trim_chars(d.name or _product_name(facts), TITLE_CHARS),
        one_liner=trim_chars(d.one_liner or _one_liner(facts), ONE_LINER_CHARS),
        kind=kind,
        urls=list(d.urls) or _product_urls(facts),
        entry_files=list(d.entry_files) or sorted({p for p in facts.paths
                                                   if os.path.basename(p).lower() in _ENTRY_NAMES})[:6],
        run_commands=list(d.run_commands) or _run_commands(facts),
        features=[f for f in (list(d.features) or _features(facts)) if f][:6],
        hero_event_ids=list(d.hero_event_ids) or _hero_ids(facts, kind),
    )


def _product_name(facts: SessionFacts) -> str:
    paths = [str(data_get(e, "path") or e.title) for e in facts.events if e.kind in ("file_write", "file_patch")]
    for ev in facts.events:
        if ev.kind == "file_write" and os.path.basename(str(data_get(ev, "path", ""))).lower() == "readme.md":
            head = next((ln.lstrip("# ").strip() for ln in code_lines(ev) if ln.startswith("# ")), "")
            if head and len(head) <= TITLE_CHARS:
                return head
    dirs: Counter[str] = Counter()
    depth: dict[str, int] = {}
    for p in paths:
        parts = [x for x in re.split(r"[\\/]+", p) if x]
        for d, part in enumerate(parts[:-1]):
            if part.lower() in _GENERIC_DIRS or part.startswith(".") or len(part) > 32:
                continue
            dirs[part] += 1
            depth[part] = min(depth.get(part, 99), d)
    if dirs:
        best = max(dirs, key=lambda k: (dirs[k], -depth[k], k))
        return trim_chars(_prettify(best), TITLE_CHARS)
    for ev in facts.events:
        title = str(data_get(ev, "page_title") or "")
        if ev.kind == "product_capture" and title:
            return trim_chars(title, TITLE_CHARS)
    stems = Counter(os.path.splitext(os.path.basename(p))[0] for p in paths)
    for stem, _ in stems.most_common():
        if stem.lower() not in _GENERIC_STEMS and not stem.startswith("test"):
            return trim_chars(_prettify(stem), TITLE_CHARS)
    query = next((str(data_get(e, "query")) for e in facts.events if e.kind == "web_search" and data_get(e, "query")),
                 "")
    if query:
        return _titlecase(trim_chars(query, TITLE_CHARS))
    prompts = facts.of_kind("user_prompt")
    if prompts:
        first = sentences(str(data_get(prompts[0], "text", "")))
        if first and len(first[0]) <= TITLE_CHARS and word_count(first[0]) >= 2:
            return first[0].rstrip(".?! ")
    return GENERIC_NAME


def _one_liner(facts: SessionFacts) -> str:
    """'...a CLI that reads my bank's CSV exports and shows...' -> 'Reads your bank's CSV exports and shows...'."""
    for ev in facts.of_kind("user_prompt"):
        m = _ASK_CLAUSE_RE.search(str(data_get(ev, "text", "")))
        if m:
            clause = _second_person(m.group(1).strip().rstrip(",;"))
            return trim_chars(clause[0].upper() + clause[1:], ONE_LINER_CHARS)
    for ev in facts.of_kind("user_prompt"):
        m = _MAKE_ME_RE.search(str(data_get(ev, "text", "")))
        if m:
            desc = _second_person(re.sub(r"\s+(?:called|named)\s+[\"']?[\w.-]+[\"']?", "", m.group(1)).strip())
            if len(desc) > ONE_LINER_CHARS:
                cut = desc.rfind(", ", 0, ONE_LINER_CHARS)
                desc = desc[:cut] if cut > 20 else trim_chars(desc, ONE_LINER_CHARS)
            if word_count(desc) >= 3:
                return desc[0].upper() + desc[1:].rstrip(",;: ")
    return ""


def _second_person(text: str) -> str:
    swaps = {"my": "your", "me": "you", "i": "you", "mine": "yours", "myself": "yourself", "i'm": "you're"}
    return " ".join(swaps.get(w.lower(), w) for w in text.split())


def _product_kind(facts: SessionFacts) -> str:
    exts = Counter(os.path.splitext(p)[1].lower() for p in facts.paths)
    names = {os.path.basename(p).lower() for p in facts.paths}
    web_entry = (exts[".tsx"] + exts[".jsx"] + exts[".vue"] + exts[".svelte"] > 0 or "index.html" in names
                 or any(is_server_cmd(str(data_get(e, "cmd", ""))) for e in facts.of_kind("terminal")))
    if web_entry:
        return "web_app"
    code = "\n".join("\n".join(code_lines(e)) for e in facts.of_kind("file_write"))
    if _CLI_HINT_RE.search(code) or any(c.startswith(("python -m ", "node ", "./")) for c in _run_commands(facts)):
        return "cli"  # a CLI that also renders an HTML report is still a CLI
    if any(e.kind == "product_capture" for e in facts.events) or exts[".html"] > 0:
        return "web_app"
    if facts.of_kind("image_generated") or any(data_get(e, "kind") in ("image", "video", "audio")
                                               for e in facts.of_kind("artifact")):
        return "media"
    if any(data_get(e, "kind") in ("doc", "pdf") for e in facts.of_kind("artifact")):
        return "doc"
    if not facts.paths and facts.of_kind("web_search", "web_extract", "browser_nav"):
        return "doc"
    if exts[".py"] + exts[".ts"] + exts[".js"] + exts[".rs"] + exts[".go"] > 0:
        return "library"
    return "other"


def _product_urls(facts: SessionFacts) -> list[str]:
    urls: list[str] = []
    for ev in facts.events:
        img = image_of(ev)
        url = str(img["url"]) if img else ""
        if url and url not in urls and (ev.kind == "product_capture" or _LOCAL_RE.match(url)
                                        or data_get(ev, "product_shot")):
            urls.append(url)
    for u in facts.urls():
        if u not in urls and (_LOCAL_RE.match(u) or _GITHUB_RE.match(u)):
            urls.append(u)
    return urls[:5]


def _run_commands(facts: SessionFacts) -> list[str]:
    out: list[str] = []
    for ev in facts.of_kind("terminal"):
        cmd = normalize_ws(str(data_get(ev, "cmd", "")))
        runs = is_demo_run(ev) or (is_server_cmd(cmd) and (ev.ok or data_get(ev, "exit_code") is None))
        if runs and cmd not in out:
            out.append(cmd)
    return out[:4]


def _features(facts: SessionFacts) -> list[str]:
    feats: list[str] = []
    todos = facts.of_kind("todo")
    if todos:
        richest = max(todos, key=lambda e: len(data_get(e, "items") or []))
        for it in data_get(richest, "items") or []:
            text = normalize_ws(str(it.get("text", ""))) if isinstance(it, dict) else ""
            if text and not _TODO_SKIP_RE.search(text):
                feats.append(trim_label(text, LABEL_WORDS))
    return feats[:6]


def _hero_ids(facts: SessionFacts, kind: str) -> list[str]:
    visuals = sorted(facts.visuals(), key=lambda e: (-_visual_score(e), facts.order[e.id]))
    ids = [e.id for e in visuals[:4]]
    if len(ids) < 2:
        demos = sorted((e for e in facts.of_kind("terminal") if is_demo_run(e)), key=lambda e: -e.weight)
        ids += [e.id for e in demos[: 3 - len(ids)]]
    return ids


def _visual_score(ev: Event) -> float:
    img = image_of(ev) or {}
    score = ev.weight
    score += {"product_capture": 0.6, "artifact": 0.45, "screenshot": 0.3, "image_generated": 0.35}.get(ev.kind, 0)
    if data_get(ev, "product_shot"):
        score += 0.3
    if img.get("full_page"):
        score -= 0.15  # full pages scroll; heroes should be one frame
    return score


# ----------------------------------------------------------------------------- base

class _Film:
    """Shared scene builders; subclasses implement :meth:`body` for their mode."""

    mode = "product"

    def __init__(self, facts: SessionFacts, options: StoryOptions, product: Product) -> None:
        self.f = facts
        self.p = product
        self.secs = options.clamped_seconds()
        self.lo, self.hi = scene_count_range(self.secs, self.mode)
        self.used: set[str] = set()
        self.variant: Counter[str] = Counter()
        self.shown_features: set[str] = set()
        self.max_features = 3 if self.secs < 75 else 4
        self.max_screens = 2 if self.secs < 75 else 3
        self._beats: list[StoryScene] = []
        ev = facts.events
        self.prompts = [e for e in ev if e.kind == "user_prompt" and not is_stub(e) and data_get(e, "text")]
        self.todos = [e for e in ev if e.kind == "todo" and not is_stub(e) and data_get(e, "items")]
        self.writes = [e for e in ev if e.kind == "file_write" and not is_stub(e) and code_lines(e)]
        self.patches = [e for e in ev if e.kind == "file_patch" and not is_stub(e) and diff_rows(e)]
        self.terms = [e for e in ev if e.kind == "terminal" and not is_stub(e) and data_get(e, "cmd")]
        self.visuals = facts.visuals()
        self.answers = [e for e in ev if e.kind in ("final_answer", "assistant_note") and not is_stub(e)
                        and data_get(e, "text")]
        self.tests_green = [e for e in self.terms if looks_like_test_pass(e)]
        self.reds = [e for e in self.terms if looks_like_failure(e)]
        self.demos = [e for e in self.terms if is_demo_run(e)]

    # ------------------------------------------------------------------ assembly
    def build(self) -> Storyboard:
        scenes = self.body()
        scenes = self._fit_count(scenes)
        scenes = self._fill_capacity(scenes)
        cta, url = self._cta()
        return Storyboard(title=self.p.name or GENERIC_NAME, tagline=self._tagline(), scenes=scenes, cta=cta,
                          url=url, source="heuristic", mode=self.mode, product=self.p)  # type: ignore[arg-type]

    def body(self) -> list[StoryScene]:  # pragma: no cover - abstract
        raise NotImplementedError

    def extras(self) -> Iterator[StoryScene]:  # pragma: no cover - abstract
        """More true scenes, best first, used when the film is too thin to fill its length."""
        raise NotImplementedError

    def _fill_capacity(self, scenes: list[StoryScene]) -> list[StoryScene]:
        """Add extra scenes until the scenes' maximum durations can cover the target length."""
        def capacity() -> float:
            return CAPACITY_MARGIN * sum(SCENE_RULES[s.type][1] for s in scenes)

        self.max_features = self.max_screens = max_type_count(self.hi)
        pending = list(self.extras())  # materialised once: building a candidate marks its events used
        added = True
        while pending and added:  # several passes: the per-type cap grows as the film grows
            added = False
            for extra in list(pending):
                if capacity() >= self.secs or len(scenes) >= self.hi:
                    return scenes
                if sum(s.type == extra.type for s in scenes) + 1 > max_type_count(len(scenes) + 1):
                    continue
                if not self._accepts(extra, scenes):
                    continue
                self._insert(scenes, extra)
                pending.remove(extra)
                added = True
        return scenes

    def _accepts(self, extra: StoryScene, scenes: list[StoryScene]) -> bool:
        return True

    def _insert(self, scenes: list[StoryScene], extra: StoryScene) -> None:
        """Chronological films: keep HOOK/TITLE first, STATS/END last, the rest in session order."""
        head = [s for s in scenes if s.type in (T.HOOK, T.TITLE)]
        tail = [s for s in scenes if s.type in (T.STATS, T.END)]
        body = [s for s in scenes if s not in head and s not in tail] + [extra]
        body.sort(key=lambda s: chrono_key(s, self.f))
        scenes[:] = head + body + tail

    def _unused(self, events: list[Event]) -> list[Event]:
        return [e for e in events if e.id not in self.used]

    def _fit_count(self, scenes: list[StoryScene]) -> list[StoryScene]:
        prio = DROP_PRIORITY[self.mode]
        while len(scenes) > self.hi:
            protected = (T.END, T.HOOK, T.TITLE)
            cands = [(prio[s.type] + (10 if s.extra.get("split") else 0), -i, i) for i, s in enumerate(scenes)
                     if s.type not in protected]
            if not cands:
                break
            scenes.pop(min(cands)[2])
        return scenes

    def _tagline(self) -> str:
        line = self.p.one_liner.strip()
        if line and len(line) <= TAGLINE_CHARS:
            return line
        clause = re.split(r",\s|;\s|\s-\s|\.\s", line)[0].strip().rstrip(".") if line else ""
        if 3 <= len(clause.split()) and len(clause) <= TAGLINE_CHARS:
            return clause
        feats = [f for f in self.p.features if f]
        for n in (3, 2):
            if len(feats) >= n:
                rest = [f if f[1:2].isupper() else f[:1].lower() + f[1:] for f in feats[1:n]]
                head = ", ".join([feats[0]] + rest[:-1]) + " and " + rest[-1]
                if len(head) <= TAGLINE_CHARS:
                    return head
        st = self.f.stats
        if st.tests_passed and st.files_created:
            return trim_chars(f"{st.files_created} files, built and tested in one session", TAGLINE_CHARS)
        return "Built in one session with Hermes Agent"

    def _cta(self) -> tuple[str, str]:
        texts = [str(data_get(e, "text", "")) for e in self.answers] + [str(data_get(e, "cmd", "")) for e in self.terms
                                                                        if terminal_ok(e)]
        public = [u for u in self.p.urls + [x for x in self.f.urls() if _GITHUB_RE.match(x)]
                  if not _LOCAL_RE.match(u) and self.f.url_in_session(u)]
        url = next((u for u in public if _GITHUB_RE.match(u)), public[0] if public else "")
        for text in reversed(texts):
            m = _INSTALL_RE.search(text)
            if m and len(m.group(1)) <= CTA_CHARS:
                return m.group(1), url
        if url and _GITHUB_RE.match(url):
            return "Read the code on GitHub", url
        if url:
            return "Try it now", url
        run = next((c for c in self.p.run_commands if len(c) <= CTA_CHARS), "")
        return (run or "Built with Hermes Agent"), ""

    # ------------------------------------------------------------------ scenes
    def hook(self) -> StoryScene | None:
        ref = next((r for r in self.p.hero_event_ids if self.f.get(r) is not None
                    and image_of(self.f.by_id[r]) is not None), "")
        if not ref and self.visuals:
            ref = max(self.visuals, key=lambda e: (_visual_score(e), self.f.order[e.id])).id
        if not ref and self.demos:
            ref = max(self.demos, key=lambda e: (e.weight, self.f.order[e.id])).id
        if not ref and self.tests_green:
            ref = self.tests_green[-1].id
        if not ref:
            cands = self.patches + self.writes
            if cands:
                ref = max(cands, key=lambda e: (e.weight - (0.2 if _low_value(e) else 0), self.f.order[e.id])).id
        if not ref:
            return None
        ev = self.f.by_id[ref]
        self.used.add(ref)
        img = image_of(ev)
        if img is not None:
            title = normalize_ws(str(img["page_title"] or ""))
            label = trim_label(title, 5) if title and not _has_digits(title) else "The finished result"
        elif looks_like_test_pass(ev):
            label = "Every test passes"
        elif ev.kind == "terminal":
            label = "Real output, real run"
        elif ev.kind == "file_patch":
            label = "The fix, line by line"
        else:
            label = "Fresh code, written live"
        return StoryScene(T.HOOK, [ref], "", label)

    def title(self, vo: str) -> StoryScene:
        return StoryScene(T.TITLE, [], vo, "")

    def problem(self, vo: str) -> StoryScene | None:
        if not self.prompts:
            return None
        ev = self.prompts[0]
        self.used.add(ev.id)
        return StoryScene(T.PROBLEM, [ev.id], vo, "The ask")

    def plan(self, earliest: bool = False) -> StoryScene | None:
        if not self.todos:
            return None
        most = max(len(data_get(e, "items") or []) for e in self.todos)
        rich = [e for e in self.todos if len(data_get(e, "items") or []) == most]
        ev = rich[0] if earliest else max(rich, key=lambda e: (_done(e), self.f.order[e.id]))
        self.used.add(ev.id)
        return StoryScene(T.PLAN, [ev.id], "Hermes turns the request into a plan and works through it.", "The plan")

    def montage(self, label: str, lo_t: float = -1.0, hi_t: float = float("inf"), n_max: int = 12) -> StoryScene | None:
        pool = [e for e in self.f.events if e.kind not in NON_TOOL_KINDS and e.id not in self.used
                and lo_t < e.t < hi_t]
        if len(pool) < 6:
            return None
        n = min(n_max, len(pool))
        step = len(pool) / n
        refs = [pool[int(k * step)].id for k in range(n)]
        self.used.update(refs)
        return StoryScene(T.MONTAGE, refs, "", label, {"montage_refs": refs})

    def stats(self, label: str, vo: str = "") -> StoryScene | None:
        keys = default_stat_keys(self.f, 2 if self.secs <= 40 else 3)
        if not keys:
            return None
        return StoryScene(T.STATS, [], vo, label, {"stat_keys": keys})

    def stats_vo(self) -> str:
        st = self.f.stats
        if st.tests_passed and st.files_created:
            files = "file" if st.files_created == 1 else "files"
            spoken = (f"{spell_number(st.tests_passed).capitalize()} tests pass, across "
                      f"{spell_number(st.files_created)} new {files}.")
            if word_count(spoken) <= VO_WORD_CAPS[T.STATS]:
                return spoken
        return "And it all happens in a single session."

    def callout(self, sources: list[Event], want: int = 1) -> list[StoryScene]:
        out: list[StoryScene] = []
        for ev in sources:
            if ev.id in self.used:
                continue
            quotes = self.f.quotable_sentences(ev)
            if quotes:
                out.append(StoryScene(T.CALLOUT, [ev.id], "", "", {"quote_ref": ev.id, "quote": quotes[0]}))
                self.used.add(ev.id)
            if len(out) >= want:
                break
        return out

    def visual_scene(self, ev: Event, vo: str = "") -> StoryScene | None:
        """FEATURE (a feature this frame shows), SCROLL for a full page, else SCREEN; None over the type caps."""
        img = image_of(ev) or {}
        scene: StoryScene | None = None
        if img.get("full_page") and ev.kind in ("product_capture", "screenshot") and not self.variant["scroll"]:
            self.variant["scroll"] += 1
            scene = StoryScene(T.SCROLL, [ev.id], vo, trim_label(str(img.get("page_title") or "The whole page"), 5))
        feat = self._feature_shown_by(ev) if scene is None else ""
        if feat and self.variant["feature"] < self.max_features:
            self.variant["feature"] += 1
            self.shown_features.add(feat)
            scene = StoryScene(T.FEATURE, [ev.id], vo, feat, {"feature": feat})
        if scene is None and self.variant["screen"] < self.max_screens:
            self.variant["screen"] += 1
            title = str(img.get("page_title") or ev.title or "On screen")
            scene = StoryScene(T.SCREEN, [ev.id], vo, trim_label(title, 5) if not _has_digits(title) else "On screen")
        if scene is not None:
            self.used.add(ev.id)
        return scene

    def _feature_shown_by(self, ev: Event) -> str:
        """The first unused product feature whose words appear in this frame's title/summary/url."""
        img = image_of(ev) or {}
        seen = _content_words(" ".join(str(x) for x in (ev.title, ev.summary, img.get("page_title"), img.get("url"))))
        for feat in self.p.features:
            if feat not in self.shown_features and _content_words(feat) & seen:
                return feat
        return ""

    def code_scene(self, ev: Event, vo: str) -> StoryScene:
        self.used.add(ev.id)
        base = os.path.basename(str(data_get(ev, "path", ev.title)).replace("\\", "/")) or ev.title
        return StoryScene(T.CODE, [ev.id], vo, trim_label(base), {"focus_lines": _code_focus(code_lines(ev))})

    def diff_scene(self, ev: Event, vo: str) -> StoryScene:
        self.used.add(ev.id)
        base = os.path.basename(str(data_get(ev, "path", ev.title)).replace("\\", "/")) or ev.title
        return StoryScene(T.DIFF, [ev.id], vo, trim_label(base))

    def term_scene(self, ev: Event, vo: str, label: str = "") -> StoryScene:
        self.used.add(ev.id)
        return StoryScene(T.TERMINAL, [ev.id], vo, label or trim_label(str(data_get(ev, "cmd", "")), 3))

    def fix_pair(self) -> tuple[Event, Event] | None:
        """The first failing command that later passes with the same command line."""
        for i, fail in enumerate(self.terms):
            if not looks_like_failure(fail):
                continue
            cmd = normalize_ws(str(data_get(fail, "cmd", "")))
            fixed = next((e for e in self.terms[i + 1:] if terminal_ok(e) and not looks_like_failure(e)
                          and normalize_ws(str(data_get(e, "cmd", ""))) == cmd), None)
            if fixed is not None:
                return fail, fixed
        return None

    def best_write(self) -> Event | None:
        cands = [e for e in self.writes if e.id not in self.used]
        if not cands:
            return None
        return max(cands, key=lambda e: (e.weight + 0.15 * min(1.0, len(code_lines(e)) / 30.0)
                                         - (0.3 if _low_value(e) else 0), -self.f.order[e.id]))

    def n_beats(self, lo: int, hi: int) -> int:
        """Product beats for this length: 2 at 30 s, 5 at 60 s, 6 at 90 s."""
        return max(lo, min(hi, int((self.secs - 30) / 10.0) + lo))


# -------------------------------------------------------------------------- product

class _ProductFilm(_Film):
    mode = "product"

    def body(self) -> list[StoryScene]:
        p = self.p
        scenes: list[StoryScene] = []
        hook = self.hook()
        if hook:
            scenes.append(hook)
        name_ok = 0 < word_count(p.name) <= 4 and p.name != GENERIC_NAME
        scenes.append(self.title(f"Meet {p.name}." if name_ok else ""))
        beats = self._product_beats(exclude={hook.refs[0]} if hook else set())
        self._beats = beats
        if beats and p.one_liner and not beats[0].vo:
            line = p.one_liner.rstrip(".") + "."
            line = "It " + line[0].lower() + line[1:] if _starts_with_verb(line) else line
            if word_count(line) <= VO_WORD_CAPS[SceneType(beats[0].type)]:
                beats[0].vo = line
        scenes += beats
        scenes += self._build_beat()
        scenes.append(StoryScene(T.END, [], f"{p.name} is ready when you are." if name_ok else
                                 "And it is ready when you are.", ""))
        return scenes

    def _product_beats(self, exclude: set[str]) -> list[StoryScene]:
        n = self.n_beats(2, 6)
        beats: list[StoryScene] = []
        visuals = sorted((e for e in self.visuals if e.id not in exclude),
                         key=lambda e: (-_visual_score(e), self.f.order[e.id]))[:n]
        visuals.sort(key=lambda e: self.f.order[e.id])
        for ev in visuals:
            scene = self.visual_scene(ev)
            if scene is not None:
                beats.append(scene)
        demos = sorted((e for e in self.demos if e.id not in exclude), key=lambda e: -e.weight)
        for k, ev in enumerate(demos[: max(0, n - len(beats))]):
            vo = "One command, and the answer is right there in your terminal." if k == 0 else ""
            beats.append(self.term_scene(ev, vo, trim_label(str(data_get(ev, "cmd", "")), 4)))
        if len(beats) < 2:
            pair = self.fix_pair()
            if pair:
                fail, fixed = pair
                self.used.update({fail.id, fixed.id})
                beats.append(StoryScene(T.BEFORE_AFTER, [fail.id, fixed.id], "The same check that failed before now passes.",
                                        "Broken, then fixed", {"before_ref": fail.id, "after_ref": fixed.id}))
                patch = next((e for e in self.patches if fail.t < e.t < fixed.t and e.id not in self.used), None)
                if patch is not None:
                    beats.append(self.diff_scene(patch, "Here is the change that fixed it, line by line."))
        if self.p.kind in ("doc", "other") or len(beats) < 2:
            only_words = not beats
            beats += self.callout(list(reversed([e for e in self.answers if e.kind == "final_answer"])))
            if only_words:
                prob = self.problem("It starts with one question, asked in plain words.")
                if prob is not None:
                    beats.insert(0, prob)
        if not beats:
            ev = self.best_write()
            if ev is not None:
                beats.append(self.code_scene(ev, ""))
        return beats

    def extras(self) -> Iterator[StoryScene]:
        for ev in sorted(self._unused(self.visuals), key=lambda e: (-_visual_score(e), self.f.order[e.id])):
            scene = self.visual_scene(ev)
            if scene is not None:
                yield scene
        for ev in sorted(self._unused(self.demos), key=lambda e: -e.weight):
            yield self.term_scene(ev, "", trim_label(str(data_get(ev, "cmd", "")), 4))
        yield from self.callout(list(reversed([e for e in self.answers if e.kind == "final_answer"])))
        pair = self.fix_pair()
        if pair and not {pair[0].id, pair[1].id} & self.used:
            self.used.update({pair[0].id, pair[1].id})
            yield StoryScene(T.BEFORE_AFTER, [pair[0].id, pair[1].id], "", "Broken, then fixed",
                             {"before_ref": pair[0].id, "after_ref": pair[1].id})
        mont = self.montage("How it was built")
        if mont:
            yield mont
        for ev in sorted(self._unused(self.writes), key=lambda e: -e.weight)[:2]:
            yield self.code_scene(ev, "")
        for ev in sorted(self._unused(self.patches), key=lambda e: -e.weight)[:2]:
            yield self.diff_scene(ev, "")

    def _accepts(self, extra: StoryScene, scenes: list[StoryScene]) -> bool:
        if scene_role(extra, self.f, self.p) != "build":
            return True
        roles = [scene_role(s, self.f, self.p) for s in scenes + [extra]]
        content = [r for r in roles if r != "frame"]
        return content.count("build") / max(1, len(content)) <= MAX_BUILD_SHARE

    def _insert(self, scenes: list[StoryScene], extra: StoryScene) -> None:
        """Product beats go before the build beat; build scenes go just before STATS/END."""
        start = next((k for k, s in enumerate(scenes) if s.type not in (T.HOOK, T.TITLE)), len(scenes))
        if scene_role(extra, self.f, self.p) == "build":
            at = next((k for k, s in enumerate(scenes) if s.type in (T.STATS, T.END)), len(scenes))
        else:
            at = next((k for k in range(start, len(scenes)) if scenes[k].type in (T.STATS, T.END, T.MONTAGE)
                       or scene_role(scenes[k], self.f, self.p) == "build"), len(scenes))
        scenes.insert(at, extra)

    def _build_beat(self) -> list[StoryScene]:
        out: list[StoryScene] = []
        n_product = sum(1 for s in self._beats if s.type != T.CALLOUT) + 1  # + the hook
        room = max(1, int(n_product * MAX_BUILD_SHARE / (1 - MAX_BUILD_SHARE)))  # build scenes incl. STATS
        if self.secs >= 50 and self.tests_green and room >= 2:
            ev = self.tests_green[-1]
            if ev.id not in self.used:
                out.append(self.term_scene(ev, "Hermes built it in a single session, with tests that all pass.",
                                           "Every test passes"))
        if self.secs >= 80:
            pair = self.fix_pair()
            if pair and pair[0].id not in self.used and pair[1].id not in self.used:
                self.used.update({pair[0].id, pair[1].id})
                out.insert(0, StoryScene(T.BEFORE_AFTER, [pair[0].id, pair[1].id], "", "Broken, then fixed",
                                         {"before_ref": pair[0].id, "after_ref": pair[1].id}))
        if self.secs >= 50 and room - sum(1 for s in out if s.type != T.BEFORE_AFTER) >= 2:
            mont = self.montage("How it was built")
            if mont:
                out.append(mont)
        vo = "" if out else "Hermes built it in a single session."
        stats = self.stats("Built with Hermes", vo)
        if stats:
            out.append(stats)
        return out


# ------------------------------------------------------------------------ making-of

class _MakingOfFilm(_Film):
    mode = "making_of"

    def extras(self) -> Iterator[StoryScene]:
        for ev in sorted(self._unused(self.writes), key=lambda e: -e.weight)[:3]:
            noun = _noun_for(str(data_get(ev, "path", "")))
            yield self.code_scene(ev, f"Then it writes {noun}." if noun else "")
        for ev in sorted(self._unused(self.patches), key=lambda e: -e.weight)[:3]:
            yield self.diff_scene(ev, "")
        for ev in self._unused(self.reds)[:2] + self._unused(self.tests_green)[-2:] + self._unused(self.demos)[:2]:
            yield self.term_scene(ev, "", "Still red" if looks_like_failure(ev) else "")
        for ev in self._unused(self.visuals):
            scene = self.visual_scene(ev)
            if scene is not None:
                yield scene
        plan = self.plan(earliest=True) if self.todos and not any(t.id in self.used for t in self.todos) else None
        if plan is not None:
            yield plan
        yield from self.callout(list(reversed(self.answers)))

    def body(self) -> list[StoryScene]:
        p = self.p
        scenes: list[StoryScene] = []
        hook = self.hook()
        if hook:
            scenes.append(hook)
        scenes.append(self.title(f"This is how {p.name} got built." if 0 < word_count(p.name) <= 3 and p.name != GENERIC_NAME else
                                 "This is how it got built."))
        body: list[StoryScene] = []
        prob = self.problem("It all starts with one request, typed straight into Hermes.")
        if prob:
            body.append(prob)
        if self.secs >= 45:
            plan = self.plan(earliest=True)
            if plan:
                body.append(plan)
        first_write = self.best_write()
        if first_write is not None:
            noun = _noun_for(str(data_get(first_write, "path", "")))
            body.append(self.code_scene(first_write, f"Hermes starts by writing {noun}." if noun else ""))
        pair = self.fix_pair()
        if pair:
            fail, fixed = pair
            body.append(self.term_scene(fail, "The first run fails, so Hermes goes looking for the cause.",
                                        "First run fails"))
            patch = next((e for e in self.patches if fail.t < e.t < fixed.t and e.id not in self.used), None)
            if patch is not None:
                noun = _noun_for(str(data_get(patch, "path", "")))
                body.append(self.diff_scene(patch, f"It finds the problem and patches {noun}." if noun else
                                            "It finds the problem and patches it."))
            body.append(self.term_scene(fixed, "On the next run, everything passes.",
                                        "Every test passes" if looks_like_test_pass(fixed) else "Fixed"))
        elif self.tests_green and self.tests_green[-1].id not in self.used:
            body.append(self.term_scene(self.tests_green[-1], "Then the tests run, and every one of them passes.",
                                        "Every test passes"))
        result = [e for e in self.visuals if e.id not in self.used and (not hook or e.id != hook.refs[0])]
        shown = self.visual_scene(result[-1], "And here is the result, working for real.") if result else None
        if shown is not None:
            body.append(shown)
        elif self.demos and self.demos[-1].id not in self.used:
            body.append(self.term_scene(self.demos[-1], "And here is the result, working for real."))
        if self.secs >= 45:
            mont = self.montage("Everything in between")
            if mont:
                body.append(mont)
        body.sort(key=lambda s: chrono_key(s, self.f))
        scenes += body
        stats = self.stats("By the numbers", self.stats_vo())
        if stats:
            scenes.append(stats)
        if self.secs >= 80 or len(self.f.events) <= 6:
            scenes += self.callout(list(reversed(self.answers)), want=2 if len(self.f.events) <= 6 else 1)
        scenes.append(StoryScene(T.END, [], f"{p.name} is ready to go." if 0 < word_count(p.name) <= 4 else
                                 "And that is the whole story, start to finish.", ""))
        return scenes


# -------------------------------------------------------------------------- speedrun

_SPLIT_VO = {
    "First file": "The first file lands, and the run is on.",
    "First run": "First run, and it works on the first try.",
    "First red": "The first test run comes back red, which costs a little time.",
    "Tests green": "Tests go green, and the pace is back.",
    "First screen": "The first screen comes up, and the finish is close.",
    "Shipped": "And that is the run, done and shipped.",
}


class _SpeedrunFilm(_Film):
    mode = "speedrun"

    def extras(self) -> Iterator[StoryScene]:
        for _ in range(2):
            mont = self.montage("Time-lapse", n_max=10)
            if mont:
                yield mont
        for ev in self._unused(self.terms)[:4]:
            yield self.term_scene(ev, "")
        for ev in sorted(self._unused(self.writes), key=lambda e: -e.weight)[:2]:
            yield self.code_scene(ev, "")
        for ev in self._unused(self.patches)[:2]:
            yield self.diff_scene(ev, "")
        for ev in self._unused(self.visuals):
            scene = self.visual_scene(ev)
            if scene is not None:
                yield scene

    def body(self) -> list[StoryScene]:
        p = self.p
        scenes: list[StoryScene] = []
        hook = self.hook()
        if hook:
            scenes.append(hook)
        name_ok = 0 < word_count(p.name) <= 3 and p.name != GENERIC_NAME
        scenes.append(self.title(f"An any percent run of {p.name}." if name_ok else
                                 "This is an any percent run, start to finish."))
        prob = self.problem("The timer starts the moment the request lands.")
        body: list[StoryScene] = [prob] if prob else []
        milestones = self._pick_milestones(detect_milestones(self.f))
        prev_t = self.f.by_id[prob.refs[0]].t if prob else 0.0
        n_montage = 0 if self.secs < 45 else (1 if self.secs < 75 else 2)
        for k, (label, ev) in enumerate(milestones):
            if n_montage and k in (1, 3):
                mont = self.montage("Time-lapse", prev_t, ev.t, n_max=10)
                if mont:
                    body.append(mont)
                    n_montage -= 1
            scene = self._milestone_scene(ev, label)
            if scene is not None:
                scene.extra["split"] = label
                body.append(scene)
                prev_t = ev.t
        scenes += body
        stats = self.stats("Run stats")
        if stats:
            scenes.append(stats)
        scenes.append(StoryScene(T.END, [], self._final_time_vo(), "Personal best"))
        return scenes

    def _pick_milestones(self, found: list[tuple[str, Event]]) -> list[tuple[str, Event]]:
        """Keep the most telling milestones that fit the scene budget and the 35 % type cap."""
        budget = max(SPLITS_MIN, min(SPLITS_MAX, self.hi - 4))
        cap = max_type_count(self.hi)
        rank = {"Shipped": 0, "Tests green": 1, "First red": 2, "First file": 3, "First screen": 4, "First run": 5}
        kinds: Counter[str] = Counter()
        keep: list[tuple[str, Event]] = []
        for label, ev in sorted(found, key=lambda m: rank.get(m[0], 9)):
            kind = "visual" if image_of(ev) is not None else ev.kind
            if len(keep) >= budget or kinds[kind] >= cap:
                continue
            kinds[kind] += 1
            keep.append((label, ev))
        return sorted(keep, key=lambda m: (m[1].t, self.f.order[m[1].id]))

    def _milestone_scene(self, ev: Event, label: str) -> StoryScene | None:
        vo = _SPLIT_VO.get(label, "")
        if ev.id in self.used:
            return None
        if ev.kind == "file_write":
            return self.code_scene(ev, vo)
        if ev.kind == "file_patch":
            return self.diff_scene(ev, vo)
        if ev.kind == "terminal":
            if label == "First run" and not terminal_ok(ev):
                vo = ""
            return self.term_scene(ev, vo, label)
        if image_of(ev) is not None:
            self.used.add(ev.id)
            return StoryScene(T.SCREEN, [ev.id], vo, label)
        if ev.kind == "final_answer":
            quotes = self.f.quotable_sentences(ev)
            if quotes:
                self.used.add(ev.id)
                return StoryScene(T.CALLOUT, [ev.id], vo, "", {"quote_ref": ev.id, "quote": quotes[0]})
        return None

    def _final_time_vo(self) -> str:
        total = int(round(self.f.stats.duration_s or 0))
        if total <= 0:
            return "And that is the run."
        m, s = divmod(total, 60)
        if m == 0:
            return f"Final time, {spell_number(s)} seconds."
        if m >= 60:
            h, mm = divmod(m, 60)
            hours = f"{spell_number(h)} hour{'s' if h != 1 else ''}"
            return f"Final time, {hours} flat." if mm == 0 else \
                f"Final time, {hours} and {spell_number(mm)} minute{'s' if mm != 1 else ''}."
        mins = f"{spell_number(m)} minute{'s' if m != 1 else ''}"
        return f"Final time, {mins} flat." if s == 0 else f"Final time, {mins} and {spell_number(s)} seconds."


# ---------------------------------------------------------------------- helpers

def _has_digits(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


_STOPWORDS = {"with", "when", "that", "this", "from", "your", "into", "page", "full", "view", "showreel", "capture"}


def _content_words(text: str) -> set[str]:
    return {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z]{4,}", text or "") if w.lower() not in _STOPWORDS}


def _done(ev: Event) -> int:
    return sum(1 for it in data_get(ev, "items") or [] if isinstance(it, dict)
               and it.get("status") in ("completed", "done"))


def _low_value(ev: Event) -> bool:
    path = str(data_get(ev, "path", ev.title))
    return os.path.splitext(path)[1].lower() in _LOW_VALUE_EXT


def _starts_with_verb(sentence: str) -> bool:
    first = sentence.split(" ", 1)[0].lower()
    return first.endswith("s") and first.isalpha() and first not in ("this", "is", "was", "has", "its")


def _prettify(name: str) -> str:
    """'invoice_exporter' -> 'Invoice Exporter'; keeps names that already have capitals."""
    words = [w for w in re.split(r"[_\-\s]+", name) if w]
    if any(ch.isupper() for ch in name):
        return " ".join(words) if len(words) > 1 else name
    return " ".join(w.capitalize() for w in words)


_SMALL = {"a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "vs", "with"}


def _titlecase(text: str) -> str:
    words = text.split()
    return " ".join(w if any(c.isupper() for c in w) or (i and w in _SMALL) else w.capitalize()
                    for i, w in enumerate(words))


def _noun_for(path: str) -> str:
    """Spoken noun for a file: 'src/tally/parser.py' -> 'the parser'; '' when it would sound odd."""
    stem = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0]
    if not stem or stem.lower() in _GENERIC_STEMS:
        return ""
    if stem.lower().startswith("test"):
        return "the tests"
    words = [w for w in re.split(r"[_\-\s.]+|(?<=[a-z])(?=[A-Z])", stem) if w]
    if not words or len(words) > 3 or not all(w.isalpha() for w in words):
        return ""
    return "the " + " ".join(w.lower() for w in words)


_DEF_LINE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|func|struct|impl|interface)\b")


def _code_focus(lines: list[str], span: int = 12) -> list[int]:
    """1-based [first, last] focus: the first definition after the imports, else the top."""
    n = len(lines)
    start = next((i for i, line in enumerate(lines) if _DEF_LINE.match(line)), 0)
    end = min(n, start + span)
    return [start + 1, max(start + 1, end)]

