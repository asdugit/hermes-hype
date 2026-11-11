"""Semantic storyboard checks beyond the JSON schema, with safe auto-fixes.

:func:`validate_storyboard` never mutates its input. It returns the issues found (with
JSONPath-style locations into the *input* storyboard, so the repair prompt can quote
them) and a fixed copy. ``error`` issues mean the fix had to drop or blank something
the model wrote (worth one repair call); ``warning`` issues were fixed losslessly
(trims, reordering, spelling digits, filling defaults).

Mode rules: product films keep the build story to <= 45 % of content scenes and open
on the product; making-of and speedrun films run chronologically; speedruns carry
4-7 milestone splits that strictly increase in session time.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from ..contracts import Event, Product, SceneType, Storyboard, StoryScene
from .facts import (
    SessionFacts,
    code_lines,
    diff_rows,
    image_of,
    is_demo_run,
    is_stub,
    is_test_cmd,
)
from .identity import replace_name, same_product, toolish_words
from .milestones import split_label
from .rules import (
    BUILD_TYPES,
    DROP_PRIORITY,
    MAX_BUILD_SHARE,
    NON_TOOL_KINDS,
    PRODUCT_KINDS,
    REFLESS,
    SINGLETONS,
    SPLIT_CHARS,
    SPLITS_MAX,
    SPLITS_MIN,
    VO_WORD_CAPS,
    accepted_kinds,
    film_mode,
    max_type_count,
    narration_budget,
)
from .onscreen import (
    approved_cta,
    display_text_paths,
    end_command,
    has_loopback,
    is_long_page,
    is_test_page,
    looks_like_command,
    scrub_text,
)
from .schema import (
    CTA_CHARS,
    LABEL_WORDS,
    ONE_LINER_CHARS,
    QUOTE_WORDS,
    TAGLINE_CHARS,
    TITLE_CHARS,
    TRANSITIONS,
)
from .text import (
    extract_numbers,
    normalize_ws,
    sentences,
    spell_digits,
    trim_chars,
    trim_label,
    trim_words,
    word_count,
)

T = SceneType
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MARKUP_RE = re.compile(r"[*_`~<>\[\]{}|\\]|\s--\s")
_ELLIPSIS_RE = re.compile(r"\s*(\.\s*\.\s*\.|\u2026)\s*")
_EXTRA_KEYS: dict[SceneType, tuple[str, ...]] = {
    T.CODE: ("focus_lines",), T.DIFF: ("focus_lines",), T.STATS: ("stat_keys",),
    T.BEFORE_AFTER: ("before_ref", "after_ref"), T.CALLOUT: ("quote_ref", "quote"),
    T.SCREEN: ("bbox",), T.MONTAGE: ("montage_refs",), T.FEATURE: ("feature", "bbox", "click"),
    T.SCROLL: ("scroll",),
}
MAX_CODE_FOCUS = 18
MIN_MONTAGE = 4
MAX_MONTAGE = 16
#: no product command found: the END shows the product name + tagline, no command (never a line of code)
DEFAULT_CTA = ""


@dataclass(frozen=True)
class Issue:
    """One semantic problem: machine code, input location, message, severity."""
    code: str
    path: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class ValidationResult:
    """Fixed storyboard plus what was wrong with the input and what was changed."""
    storyboard: Storyboard
    issues: list[Issue] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        """Issues whose fix lost content the model intended."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def viable(self) -> bool:
        """True when the fixed storyboard can be rendered as a real film."""
        scenes = self.storyboard.scenes
        content = [s for s in scenes if s.type not in (T.TITLE, T.END)]
        return len(scenes) >= 3 and bool(content) and scenes[-1].type == T.END and bool(self.storyboard.title)


class _Ctx:
    def __init__(self, facts: SessionFacts, mode: str, draft: Product | None = None, lock_name: bool = False) -> None:
        self.facts = facts
        self.mode = mode
        self.issues: list[Issue] = []
        self.fixes: list[str] = []
        self.product = Product()
        self.draft = draft if draft is not None and normalize_ws(draft.name) else None
        self.lock_name = lock_name
        self.renamed_from = ""      # the model's product name when it was replaced by the session's
        self.used_pictures: set[str] = set()   # picture refs already on screen (a swap never repeats one)
        self.all_refs: set[str] = set()        # every scene's first ref (a swap never steals a later scene's)
        self.picture_keys: set[str] = set()    # identity keys of the pictures on screen (see _picture_keys)

    def issue(self, code: str, path: str, message: str, severity: str = "error", fix: str = "") -> None:
        self.issues.append(Issue(code, path, message, severity))
        if fix:
            self.fixes.append(f"{path}: {fix}")


def validate_storyboard(sb: Storyboard, facts: SessionFacts, target_seconds: float = 60.0,
                        mode: str | None = None, draft: Product | None = None,
                        lock_name: bool = False) -> ValidationResult:
    """Check ``sb`` against the session and film rules; return issues and a fixed copy.

    ``mode`` overrides ``sb.mode`` (the user's choice is authoritative). ``draft`` is the product the session
    stage detected (or the brief named); with ``lock_name`` (a strong name: brief, README, package, page title)
    the film keeps that product's name - the model may only shorten or tidy it. Without the lock the model may
    correct a weak draft name, but never to a tool, stage or capture label ("Hype Product Capture").
    """
    ctx = _Ctx(facts, film_mode(mode or getattr(sb, "mode", None)), draft, lock_name)
    out = copy.deepcopy(sb)
    out.mode = ctx.mode  # type: ignore[assignment]
    ctx.all_refs = {sc.refs[0] for sc in out.scenes if sc.refs}
    _check_product(out, ctx)
    _check_top(out, ctx)
    _check_identity_mentions(out, ctx)
    kept: list[tuple[int, StoryScene]] = []
    for i, scene in enumerate(out.scenes):
        fixed = _check_scene(scene, i, ctx)
        if fixed is not None:
            kept.append((i, fixed))
    kept = _check_structure(kept, ctx)
    if ctx.mode == "product":
        kept = _check_product_film(kept, ctx)
        kept = _enrich_pictures(kept, ctx, target_seconds)
    else:
        kept = _check_chronology(kept, ctx)
    if ctx.mode == "speedrun":
        _check_splits(kept, ctx)
    out.scenes = [s for _, s in kept]
    _check_budget(out, ctx, target_seconds)
    if len(out.scenes) < 3:
        ctx.issue("too_few_scenes", "$.scenes", f"only {len(out.scenes)} usable scene(s); need at least 3")
    return ValidationResult(out, ctx.issues, ctx.fixes)


# -------------------------------------------------------------------------- product

def _check_product(sb: Storyboard, ctx: _Ctx) -> None:
    facts = ctx.facts
    p = copy.deepcopy(sb.product) if sb.product is not None else Product()
    path = "$.product"
    if sb.product is None:
        ctx.issue("product_missing", path, "storyboard has no product", fix="derived from title")
    p.name = normalize_ws(p.name) or normalize_ws(sb.title)
    if len(p.name) > TITLE_CHARS:
        p.name = trim_chars(p.name, TITLE_CHARS)
        ctx.issue("product_name_long", f"{path}.name", f"longer than {TITLE_CHARS} characters", "warning", "trimmed")
    p.one_liner = normalize_ws(p.one_liner)
    if len(p.one_liner) > ONE_LINER_CHARS:
        p.one_liner = trim_chars(p.one_liner, ONE_LINER_CHARS)
        ctx.issue("one_liner_long", f"{path}.one_liner", f"longer than {ONE_LINER_CHARS} characters", "warning",
                  "trimmed")
    if _bad_numbers(p.one_liner, facts):
        ctx.issue("number_not_in_session", f"{path}.one_liner", "mentions a number that is not a session number",
                  fix="cleared")
        p.one_liner = ""
    if p.kind not in PRODUCT_KINDS:
        if p.kind:
            ctx.issue("product_kind", f"{path}.kind", f"{p.kind!r} is not a known kind", "warning", "set to other")
        p.kind = "other"
    p.urls = _keep(p.urls, facts.url_in_session, f"{path}.urls", "does not appear in the session", ctx)[:5]
    p.entry_files = _keep(p.entry_files, facts.path_in_session, f"{path}.entry_files",
                          "is not a file the session touched", ctx)[:6]
    trusted = set(ctx.draft.run_commands) if ctx.draft is not None else set()   # README / package.json / ...
    p.run_commands = _keep(p.run_commands, lambda c: facts.command_in_session(c) or c in trusted,
                           f"{path}.run_commands", "is not a command the session ran", ctx)[:6]
    features: list[str] = []
    for j, feat in enumerate(p.features):
        feat = trim_label(normalize_ws(feat), LABEL_WORDS)
        if not feat or feat.lower() in (f.lower() for f in features):
            continue
        if _bad_numbers(feat, facts) or not facts.grounded(feat):
            ctx.issue("feature_ungrounded", f"{path}.features[{j}]",
                      f"{feat!r} is not backed by anything in the session", fix="removed")
            continue
        features.append(feat)
    p.features = features[:6]
    p.hero_event_ids = [r for r in dict.fromkeys(p.hero_event_ids)
                        if facts.get(r) is not None and (image_of(facts.by_id[r]) is not None
                                                         or facts.by_id[r].kind == "terminal")][:6]
    _check_identity(p, ctx)
    ctx.product = p
    sb.product = p


def _check_identity(p: Product, ctx: _Ctx) -> None:
    """Keep the session's product name (see :mod:`.identity`); the model may only shorten or tidy it."""
    draft = ctx.draft
    path = "$.product.name"
    if draft is None:
        bad = toolish_words(p.name)
        if bad and p.name:
            ctx.issue("product_name_toolish", path, f"{p.name!r} names Hype/Hermes machinery "
                      f"({', '.join(bad)}), not the product the session built", "warning")
        return
    want = trim_chars(normalize_ws(draft.name), TITLE_CHARS)
    if not p.name:
        p.name = want
        ctx.fixes.append(f"{path}: set to the session's product {want!r}")
        return
    if same_product(p.name, want):
        bad = toolish_words(p.name, want)
        if not bad:
            return                      # the same product, tidied ("Tempo" for "Tempo — focus timer")
    else:
        bad = toolish_words(p.name, want)
        if not ctx.lock_name and not bad:
            return                      # a weak draft name (project directory) corrected by the model
    why = (f"it names Hype/Hermes machinery ({', '.join(bad)})" if bad
           else "the session's product has another name")
    ctx.issue("product_renamed", path,
              f"the product this session built is {want!r} (from its README/package/page title or the brief); "
              f"{p.name!r} is not its name: {why}. Use {want!r} in the product, title, narration and labels",
              fix=f"set to {want!r}")
    ctx.renamed_from = p.name
    p.name = want
    if draft.one_liner:
        p.one_liner = trim_chars(normalize_ws(draft.one_liner), ONE_LINER_CHARS)
    if draft.features:
        p.features = list(dict.fromkeys([*draft.features, *p.features]))[:6]
    if draft.kind in PRODUCT_KINDS:
        p.kind = draft.kind


def _check_identity_mentions(sb: Storyboard, ctx: _Ctx) -> None:
    """After a rename, say the product's real name wherever the model wrote the wrong one."""
    wrong, right = ctx.renamed_from, ctx.product.name
    if not wrong or not right:
        return
    changed = 0
    for attr in ("tagline", "cta"):
        new = replace_name(getattr(sb, attr), wrong, right)
        if new != getattr(sb, attr):
            setattr(sb, attr, new)
            changed += 1
        elif attr == "tagline" and new:
            # a tagline that never names the product describes the wrong one: the product's own line or none
            one = ctx.product.one_liner
            sb.tagline = one if one and len(one) <= TAGLINE_CHARS else ""
            changed += 1
    for scene in sb.scenes:
        for attr in ("vo", "label"):
            new = replace_name(getattr(scene, attr) or "", wrong, right)
            if new != (getattr(scene, attr) or ""):
                setattr(scene, attr, new)
                changed += 1
        feat = scene.extra.get("feature") if isinstance(scene.extra, dict) else None
        if isinstance(feat, str) and replace_name(feat, wrong, right) != feat:
            scene.extra["feature"] = replace_name(feat, wrong, right)
            changed += 1
    if changed:
        ctx.fixes.append(f"$: {changed} mention(s) of {wrong!r} now say {right!r}")


def _keep(items: list[str], ok: object, path: str, why: str, ctx: _Ctx) -> list[str]:
    out: list[str] = []
    for j, item in enumerate(items):
        if ok(item):  # type: ignore[operator]
            if item not in out:
                out.append(item)
        else:
            ctx.issue("product_unbacked", f"{path}[{j}]", f"{item!r} {why}", "warning", "removed")
    return out


# ------------------------------------------------------------------------ top level

def _check_top(sb: Storyboard, ctx: _Ctx) -> None:
    sb.title = normalize_ws(sb.title)
    name = ctx.product.name
    if sb.title and name and not same_product(sb.title, name) and (
            (ctx.renamed_from and same_product(sb.title, ctx.renamed_from)) or toolish_words(sb.title, name)):
        ctx.issue("title_not_product", "$.title", f"{sb.title!r} is not the product's name ({name!r})",
                  fix=f"set to {name!r}")
        sb.title = ""
    if not sb.title:
        if ctx.product.name:
            sb.title = ctx.product.name
            ctx.fixes.append("$.title: set to the product name")
        else:
            ctx.issue("title_empty", "$.title", "title is empty")
    elif len(sb.title) > TITLE_CHARS:
        sb.title = trim_chars(sb.title, TITLE_CHARS)
        ctx.issue("title_long", "$.title", f"longer than {TITLE_CHARS} characters", "warning", "trimmed")
    for attr, limit, path in (("tagline", TAGLINE_CHARS, "$.tagline"), ("cta", CTA_CHARS, "$.cta")):
        value = normalize_ws(getattr(sb, attr))
        if has_loopback(value):   # 'Open it at localhost' reached a real END card
            new = "" if attr == "cta" else scrub_text(value, ctx.product.name)
            ctx.issue("loopback_on_screen", path, f"{value!r} names a loopback/dev-server address", "warning",
                      f"now {new!r}")
            value = new
        if attr == "cta" and value and looks_like_command(value):
            ok = approved_cta(value, ctx.product, ctx.facts,
                              ctx.draft.run_commands if ctx.draft is not None else ())
            if ok != value:
                ctx.issue("cta_not_product_command", path,
                          f"{value!r} is not the product's own launch or install command", "warning",
                          f"now {ok!r}" if ok else "cleared")
            value = ok
        if len(value) > limit:
            value = trim_chars(value, limit)
            ctx.issue(f"{attr}_long", path, f"longer than {limit} characters", "warning", "trimmed")
        bad = _bad_numbers(value, ctx.facts)
        if bad:
            ctx.issue("number_not_in_session", path, f"mentions {', '.join(bad)}, which is not a session number",
                      fix="cleared")
            value = ""
        setattr(sb, attr, value)
    if not sb.tagline and ctx.product.one_liner and len(ctx.product.one_liner) <= TAGLINE_CHARS:
        sb.tagline = ctx.product.one_liner
    if not sb.cta:
        sb.cta = end_command(ctx.product, ctx.facts, CTA_CHARS) or DEFAULT_CTA
        ctx.fixes.append(f"$.cta: defaulted to {sb.cta!r}")
    if sb.url and (has_loopback(sb.url) or re.match(r"(?i)(?:file:|~|/|\\|[a-z]:[\\/])", sb.url.strip())):
        ctx.issue("url_not_public", "$.url", f"{sb.url!r} is a dev-server address or a local path", "warning",
                  "cleared")
        sb.url = ""
    if sb.url and not ctx.facts.url_in_session(sb.url):
        ctx.issue("url_not_in_session", "$.url", f"{sb.url!r} does not appear in the session", "warning", "cleared")
        sb.url = ""
    if sb.accent_hint and not _HEX_RE.match(sb.accent_hint):
        ctx.issue("accent_invalid", "$.accent_hint", f"{sb.accent_hint!r} is not #RRGGBB", "warning", "cleared")
        sb.accent_hint = ""


# ---------------------------------------------------------------------------- scene

def _check_scene(scene: StoryScene, i: int, ctx: _Ctx) -> StoryScene | None:
    """Validate one scene; return the fixed scene or None to drop it."""
    path = f"$.scenes[{i}]"
    facts = ctx.facts
    st = SceneType(scene.type)
    scene.type = st
    extra = dict(scene.extra or {})
    refs: list[str] = []
    for j, ref in enumerate(scene.refs):
        if facts.get(ref) is None:
            ctx.issue("unknown_ref", f"{path}.refs[{j}]", f"event {ref!r} does not exist", fix="removed")
        elif ref not in refs:
            refs.append(ref)
    scene.refs = refs
    scene.extra = {k: v for k, v in extra.items() if k in _EXTRA_KEYS.get(st, ())}
    if extra.get("transition") in TRANSITIONS:
        scene.extra["transition"] = extra["transition"]
    if ctx.mode == "speedrun" and isinstance(extra.get("split"), str) and extra["split"].strip():
        scene.extra["split"] = extra["split"].strip()
    handler = _SCENE_HANDLERS.get(st, _check_primary)
    if not handler(scene, path, ctx):
        return None
    _check_vo(scene, path, ctx)
    _check_label(scene, path, ctx)
    return scene


def _primary_usable(ev_kind: str | None, st: SceneType) -> bool:
    kinds = accepted_kinds(st)
    return ev_kind is not None and ("*" in kinds or ev_kind in kinds)


def _has_content(scene_type: SceneType, ref: str, facts: SessionFacts) -> bool:
    ev = facts.get(ref)
    if ev is None or is_stub(ev):
        return False
    data = ev.data or {}
    if ev.kind in ("product_capture", "screenshot", "image_generated", "artifact"):
        return image_of(ev) is not None
    if ev.kind == "file_write":
        return bool(code_lines(ev))
    if ev.kind == "file_patch":
        return bool(diff_rows(ev))
    if ev.kind == "terminal":
        return bool(data.get("cmd"))
    if ev.kind == "todo":
        return bool(data.get("items"))
    if ev.kind in ("user_prompt", "assistant_note", "final_answer"):
        return bool(str(data.get("text") or "").strip())
    return scene_type == T.MONTAGE


def _set_aside(ev: Event | None) -> bool:
    """True for a picture the session ranking set aside (session.mediarank: contact sheet, debug render)."""
    return bool(ev is not None and ((ev.data or {}).get("media_rank") or {}).get("junk"))


def _shown_before(ref: str, ctx: _Ctx) -> bool:
    """True when this picture (or a copy of it) is already on screen in an earlier scene."""
    ev = ctx.facts.get(ref)
    return ref in ctx.used_pictures or (ev is not None and bool(_picture_keys(ev) & ctx.picture_keys))


def _best_unused_picture(st: SceneType, ctx: _Ctx) -> str:
    """The best-ranked showable picture no scene uses yet ('' when none is left: the scene is then dropped and
    the film runs on fewer pictures rather than padding with junk)."""
    facts = ctx.facts
    kinds = accepted_kinds(st)
    used = ctx.used_pictures | ctx.all_refs
    best, score = "", -1.0
    for ev in facts.events:
        if ev.id in used or ev.kind not in kinds or image_of(ev) is None or _picture_keys(ev) & ctx.picture_keys:
            continue
        rank = (ev.data or {}).get("media_rank") or {}
        if not rank and st != T.HOOK:
            continue                       # only ranked session pictures (web captures keep the model's choice)
        img = image_of(ev) or {}
        try:
            aspect = float(img.get("w") or 0) / float(img.get("h") or 1)
        except (TypeError, ValueError):
            aspect = 0.0
        s = float(rank.get("score", 0.5)) + 0.3 * float(ev.weight or 0) + (0.12 if 1.3 <= aspect <= 2.4 else 0.0)
        if s > score:
            best, score = ev.id, s
    return best


def _check_primary(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    """Generic rule: the first ref must be a usable event of an accepted kind."""
    st = SceneType(scene.type)
    if st in REFLESS:
        return True
    facts = ctx.facts
    usable = [r for r in scene.refs if _primary_usable(facts.kind(r), st) and _has_content(st, r, facts)]
    if not usable and st in (T.HOOK, T.SCREEN, T.FEATURE) and any(_set_aside(facts.get(r)) for r in scene.refs):
        swap = _best_unused_picture(st, ctx)
        if swap:
            ctx.issue("debug_media", f"{path}.refs", "the picture is a working/debug artefact (contact sheet, test "
                      "render or older retry)", "warning", f"swapped for {swap}")
            scene.refs = [swap]
            scene.extra.pop("bbox", None)
            scene.extra.pop("click", None)
            usable = [swap]
    if usable and st in (T.SCREEN, T.FEATURE) and _shown_before(usable[0], ctx):
        swap = _best_unused_picture(st, ctx)       # the same picture twice reads as padding: show another real one
        if swap:
            ctx.issue("repeated_picture", f"{path}.refs", f"{usable[0]} is already on screen", "warning",
                      f"swapped for {swap}")
            scene.refs = [swap] + [r for r in scene.refs if r != usable[0]]
            scene.extra.pop("bbox", None)
            scene.extra.pop("click", None)
            usable = [swap]
    if usable and st in (T.HOOK, T.SCREEN, T.FEATURE, T.SCROLL):
        ctx.used_pictures.add(usable[0])
        ev0 = facts.get(usable[0])
        if ev0 is not None:
            ctx.picture_keys |= _picture_keys(ev0)
    if not usable:
        if scene.refs:
            kinds = ", ".join(sorted({facts.kind(r) or "?" for r in scene.refs}))
            ctx.issue("kind_mismatch", f"{path}.refs",
                      f"{st.value} needs an event of kind {'/'.join(accepted_kinds(st))} with content; got {kinds}",
                      fix="scene dropped")
        else:
            ctx.issue("missing_ref", f"{path}.refs", f"{st.value} needs at least one event ref", fix="scene dropped")
        return False
    if scene.refs[0] != usable[0]:
        scene.refs = [usable[0]] + [r for r in scene.refs if r != usable[0]]
        ctx.issue("primary_order", f"{path}.refs", f"first ref must be the {st.value} content", "warning",
                  f"moved {usable[0]} first")
    return True


def _check_code(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    if not _check_primary(scene, path, ctx):
        return False
    ev = ctx.facts.by_id[scene.refs[0]]
    n = len(code_lines(ev)) if ev.kind == "file_write" else len(diff_rows(ev))
    focus = scene.extra.get("focus_lines")
    if focus is None:
        return True
    try:
        a, b = int(focus[0]), int(focus[1])
    except (TypeError, ValueError, IndexError):
        ctx.issue("focus_invalid", f"{path}.extra.focus_lines", "must be [first, last] line numbers", "warning",
                  "removed")
        scene.extra.pop("focus_lines", None)
        return True
    fa, fb = sorted((a, b))
    fa, fb = max(1, min(fa, n)), max(1, min(fb, n))
    cap = MAX_CODE_FOCUS if SceneType(scene.type) == T.CODE else 24
    if fb - fa + 1 > cap:
        fb = fa + cap - 1
    if [fa, fb] != [a, b]:
        ctx.issue("focus_out_of_range", f"{path}.extra.focus_lines",
                  f"[{a}, {b}] outside 1..{n} or longer than {cap} lines", "warning", f"clamped to [{fa}, {fb}]")
        scene.extra["focus_lines"] = [fa, fb]
    return True


_STAT_PREFERENCE = ("tests_passed", "files_created", "duration_s", "lines_added", "tool_calls", "files_modified",
                    "commands_run", "screenshots", "subagents", "lines_removed")


def default_stat_keys(facts: SessionFacts, n: int = 3) -> list[str]:
    """The most telling computed stats for this session (tests, files, time first)."""
    usable = set(facts.usable_stat_keys())
    return [k for k in _STAT_PREFERENCE if k in usable][:n]


def _check_stats(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    usable = ctx.facts.usable_stat_keys()
    keys = list(scene.extra.get("stat_keys") or [])
    good = [k for k in keys if k in usable][:3]
    for k in keys:
        if k not in usable:
            ctx.issue("stat_unavailable", f"{path}.extra.stat_keys",
                      f"{k!r} has no computed value in this session", fix="removed")
    if not good:
        good = default_stat_keys(ctx.facts)
        if not good:
            ctx.issue("no_stats", f"{path}", "session has no usable stats", fix="scene dropped")
            return False
        ctx.fixes.append(f"{path}.extra.stat_keys: chose {good}")
    scene.extra["stat_keys"] = good
    return True


def _check_before_after(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    facts = ctx.facts
    before = scene.extra.get("before_ref") or (scene.refs[0] if scene.refs else "")
    after = scene.extra.get("after_ref") or (scene.refs[1] if len(scene.refs) > 1 else "")
    problems = []
    for name, ref in (("before_ref", before), ("after_ref", after)):
        if not ref or facts.get(ref) is None:
            problems.append(f"{name} {ref!r} does not exist")
        elif not _primary_usable(facts.kind(ref), T.BEFORE_AFTER) or not _has_content(T.BEFORE_AFTER, ref, facts):
            problems.append(f"{name} {ref!r} is a {facts.kind(ref)} event without showable content")
    if not problems and before == after:
        problems.append("before_ref and after_ref are the same event")
    if not problems:
        fam = {image_of(facts.by_id[r]) is not None for r in (before, after)}
        if len(fam) > 1:
            problems.append("before and after must both be images or both be text (diff/terminal)")
    if problems:
        ctx.issue("before_after_invalid", f"{path}.extra", "; ".join(problems), fix="scene dropped")
        return False
    scene.extra.update(before_ref=before, after_ref=after)
    scene.refs = [before, after] + [r for r in scene.refs if r not in (before, after)]
    return True


def _check_callout(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    facts = ctx.facts
    ref = scene.extra.get("quote_ref") or (scene.refs[0] if scene.refs else "")
    if not ref or not _primary_usable(facts.kind(ref), T.CALLOUT) or not _has_content(T.CALLOUT, ref, facts):
        ctx.issue("quote_ref_invalid", f"{path}.extra.quote_ref",
                  f"CALLOUT needs quote_ref to a user_prompt/assistant_note/final_answer/terminal event; got {ref!r}",
                  fix="scene dropped")
        return False
    quote = str(scene.extra.get("quote") or "")
    span = facts.find_quote(ref, quote) if quote else None
    if span and word_count(span) > QUOTE_WORDS:
        shorter = [s for s in sentences(span) if word_count(s) <= QUOTE_WORDS]
        span = facts.find_quote(ref, shorter[0]) if shorter else None
    if not span:
        candidates = facts.quotable_sentences(facts.by_id[ref])
        if not candidates:
            ctx.issue("quote_not_found", f"{path}.extra.quote",
                      f"quote is not a verbatim span of {ref} (<= {QUOTE_WORDS} words)", fix="scene dropped")
            return False
        span = candidates[0]
        if quote:
            ctx.issue("quote_not_found", f"{path}.extra.quote",
                      f"{quote!r} is not a verbatim span of {ref} (<= {QUOTE_WORDS} words)",
                      fix=f"replaced with {span!r}")
    scene.extra.update(quote_ref=ref, quote=span)
    scene.refs = [ref] + [r for r in scene.refs if r != ref]
    return True


def _check_montage(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    facts = ctx.facts
    raw = list(scene.extra.get("montage_refs") or []) or list(scene.refs)
    refs: list[str] = []
    for j, ref in enumerate(raw):
        ev = facts.get(ref)
        if ev is None:
            if ref not in scene.refs:
                ctx.issue("unknown_ref", f"{path}.extra.montage_refs[{j}]", f"event {ref!r} does not exist",
                          fix="removed")
            continue
        if ev.kind not in NON_TOOL_KINDS and ref not in refs:
            refs.append(ref)
    refs.sort(key=lambda r: facts.order.get(r, 0))
    if len(refs) > MAX_MONTAGE:
        step = len(refs) / MAX_MONTAGE
        refs = [refs[int(k * step)] for k in range(MAX_MONTAGE)]
        ctx.fixes.append(f"{path}.extra.montage_refs: thinned to {MAX_MONTAGE}")
    if len(refs) < MIN_MONTAGE:
        ctx.issue("montage_small", f"{path}.extra.montage_refs",
                  f"MONTAGE needs {MIN_MONTAGE}-{MAX_MONTAGE} tool-call events; got {len(refs)}", fix="scene dropped")
        return False
    scene.extra["montage_refs"] = refs
    scene.refs = refs
    return True


def _clamp_box(scene: StoryScene, key: str, path: str, ctx: _Ctx) -> None:
    box = scene.extra.get(key)
    if box is None:
        return
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        scene.extra.pop(key, None)
        ctx.issue("bbox_invalid", f"{path}.extra.{key}", "must be [x, y, w, h]", "warning", "removed")
        return
    fx, fy = min(max(x, 0.0), 0.9), min(max(y, 0.0), 0.9)
    fw, fh = min(max(w, 0.1), 1.0 - fx), min(max(h, 0.1), 1.0 - fy)
    fixed = [round(v, 4) for v in (fx, fy, fw, fh)]
    if fixed != [round(v, 4) for v in (x, y, w, h)]:
        ctx.issue("bbox_out_of_range", f"{path}.extra.{key}", "box must lie inside the image", "warning",
                  f"clamped to {fixed}")
    scene.extra[key] = fixed


def _clamp_pair(scene: StoryScene, key: str, path: str, ctx: _Ctx) -> None:
    pair = scene.extra.get(key)
    if pair is None:
        return
    try:
        a, b = (min(1.0, max(0.0, float(v))) for v in pair)
    except (TypeError, ValueError):
        scene.extra.pop(key, None)
        ctx.issue("pair_invalid", f"{path}.extra.{key}", "must be two numbers in 0..1", "warning", "removed")
        return
    scene.extra[key] = [round(a, 4), round(b, 4)]


def _check_screen(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    if not _check_primary(scene, path, ctx):
        return False
    _clamp_box(scene, "bbox", path, ctx)
    return True


def _check_feature(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    if not _check_primary(scene, path, ctx):
        return False
    _clamp_box(scene, "bbox", path, ctx)
    _clamp_pair(scene, "click", path, ctx)
    feat = trim_label(normalize_ws(str(scene.extra.get("feature") or scene.label or "")), LABEL_WORDS)
    known = {f.lower(): f for f in ctx.product.features}
    if feat.lower() in known:
        feat = known[feat.lower()]
    elif feat and (_bad_numbers(feat, ctx.facts) or not ctx.facts.grounded(feat)):
        ctx.issue("feature_ungrounded", f"{path}.extra.feature", f"{feat!r} is not backed by the session",
                  fix="feature name removed")
        feat = ""
    if feat:
        scene.extra["feature"] = feat
        if not scene.label:
            scene.label = feat
    else:
        scene.extra.pop("feature", None)
    return True


def _check_scroll(scene: StoryScene, path: str, ctx: _Ctx) -> bool:
    if not _check_primary(scene, path, ctx):
        return False
    ev = ctx.facts.get(scene.refs[0]) if scene.refs else None
    if ev is not None and image_of(ev) is not None:
        why = ""
        if not is_long_page(ev):
            why = "the picture is not a long page"
        elif is_test_page(ev) and any(not is_test_page(e) for e in ctx.facts.visuals() if e.kind == "product_capture"):
            why = "the page is a test fixture, not the product"
        if why:
            # SCROLL must scroll the product's real long page (a 9:16 film scrolled a test page of colour blocks);
            # otherwise it is a still SCREEN of the product's own page
            ctx.issue("scroll_not_product_page", path, why, "warning", "now a SCREEN")
            alt = _scroll_fallback(ev, ctx)
            scene.type = T.SCREEN
            scene.refs = [alt.id] if alt is not None else scene.refs
            scene.extra = {k: v for k, v in (scene.extra or {}).items() if k in _EXTRA_KEYS[T.SCREEN]}
            return _check_screen(scene, path, ctx)
    _clamp_pair(scene, "scroll", path, ctx)
    return True


def _scroll_fallback(ev: Event, ctx: _Ctx) -> Event | None:
    """The viewport capture of the same page (or of the product's main page when ``ev`` is a test page)."""
    caps = [e for e in ctx.facts.visuals() if e.kind == "product_capture" and (e.data or {}).get("kind") == "viewport"]
    url = str((ev.data or {}).get("url") or "").rstrip("/")
    if not is_test_page(ev) or not any(not is_test_page(e) for e in caps):
        same = [e for e in caps if str((e.data or {}).get("url") or "").rstrip("/") == url]
        if same:
            return same[0]
    real = [e for e in caps if not is_test_page(e)]
    return real[0] if real else None


_SCENE_HANDLERS = {
    T.CODE: _check_code, T.DIFF: _check_code, T.STATS: _check_stats, T.BEFORE_AFTER: _check_before_after,
    T.CALLOUT: _check_callout, T.MONTAGE: _check_montage, T.SCREEN: _check_screen, T.FEATURE: _check_feature,
    T.SCROLL: _check_scroll,
}


# ------------------------------------------------------------------------- text

def _bad_numbers(text: str, facts: SessionFacts) -> list[str]:
    return [n.text for n in extract_numbers(text) if not facts.number_allowed(n.value)]


def _check_vo(scene: StoryScene, path: str, ctx: _Ctx) -> None:
    st = SceneType(scene.type)
    vo = normalize_ws(scene.vo)
    if not vo:
        scene.vo = ""
        return
    if _ELLIPSIS_RE.search(vo):
        vo = _ELLIPSIS_RE.sub(", ", vo).strip(" ,")
        vo = re.sub(r",\s*([.!?])", r"\1", vo)
        ctx.issue("ellipsis", f"{path}.vo", "ellipses break TTS phrasing", "warning", "replaced with commas")
    if _MARKUP_RE.search(vo):
        vo = normalize_ws(_MARKUP_RE.sub(" ", vo))
        vo = re.sub(r"\s+([,.;:!?])", r"\1", vo)
        ctx.issue("markup", f"{path}.vo", "narration contains markup characters", "warning", "stripped")
    kept: list[str] = []
    for sent in sentences(vo):
        if has_loopback(sent):     # a voice never reads a dev-server address ('open it at localhost')
            ctx.issue("loopback_on_screen", f"{path}.vo", "names a loopback/dev-server address", "warning",
                      "sentence removed")
            continue
        bad = _bad_numbers(sent, ctx.facts)
        if bad:
            ctx.issue("number_not_in_session", f"{path}.vo",
                      f"mentions {', '.join(bad)}, which is not in the stats or the session", fix="sentence removed")
            continue
        kept.append(sent)
    vo = " ".join(kept)
    spelled = spell_digits(vo)
    if spelled != vo:
        ctx.issue("digits", f"{path}.vo", "numbers must be spelled as spoken", "warning", "spelled out")
        vo = spelled
    cap = VO_WORD_CAPS[st]
    soft = cap + max(2, cap // 5)  # a slightly long line is better than a cut one; the scene just runs longer
    if word_count(vo) > (soft if cap else 0):
        if cap == 0:
            ctx.issue("vo_not_allowed", f"{path}.vo", f"{st.value} is music-only (no narration)", "warning",
                      "removed")
            vo = ""
        else:
            ctx.issue("vo_long", f"{path}.vo", f"{word_count(vo)} words; {st.value} allows {cap}", "warning",
                      "trimmed")
            vo = trim_words(vo, soft)
    if vo and vo[-1] not in ".!?":
        vo += "."
    scene.vo = vo


def _check_label(scene: StoryScene, path: str, ctx: _Ctx) -> None:
    label = normalize_ws(scene.label).rstrip(".")
    if has_loopback(label):
        label = scrub_text(label, ctx.product.name)
        ctx.issue("loopback_on_screen", f"{path}.label", "names a loopback/dev-server address", "warning",
                  f"now {label!r}")
    if "/" in label or "\\" in label:      # 'Scrolling ~/work/app/index.html': project-relative on screen
        label = display_text_paths(label, ctx.facts.project_root)
    feat = (scene.extra or {}).get("feature")
    if isinstance(feat, str) and has_loopback(feat):
        scene.extra["feature"] = scrub_text(feat, ctx.product.name)
    if _bad_numbers(label, ctx.facts):
        ctx.issue("number_not_in_session", f"{path}.label", "label mentions a number that is not a session number",
                  fix="cleared")
        label = ""
    if word_count(label) > LABEL_WORDS:
        ctx.issue("label_long", f"{path}.label", f"more than {LABEL_WORDS} words", "warning", "trimmed")
        label = trim_label(label, LABEL_WORDS)
    scene.label = label


# ----------------------------------------------------------------------- structure

def _check_structure(kept: list[tuple[int, StoryScene]], ctx: _Ctx) -> list[tuple[int, StoryScene]]:
    for st in SINGLETONS:
        idx = [k for k, (_, s) in enumerate(kept) if s.type == st]
        if len(idx) > 1:
            keep = idx[-1] if st == T.END else idx[0]
            for k in idx:
                if k != keep:
                    ctx.issue("duplicate_singleton", f"$.scenes[{kept[k][0]}]", f"only one {st.value} allowed",
                              fix="scene dropped")
            kept = [item for k, item in enumerate(kept) if k == keep or k not in idx]
    seen: dict[str, int] = {}
    deduped: list[tuple[int, StoryScene]] = []
    for oi, s in kept:
        primary = s.refs[0] if s.refs and s.type not in (T.HOOK, T.MONTAGE, T.TITLE, T.STATS, T.END) else None
        if primary is not None and s.type == T.CALLOUT:
            primary = f"{primary}:{s.extra.get('quote', '')}"  # two different quotes from one answer are fine
        if primary is not None and primary in seen:
            ctx.issue("duplicate_content", f"$.scenes[{oi}]", f"shows {primary} again (already scene {seen[primary]})",
                      fix="scene dropped")
            continue
        if primary is not None:
            seen[primary] = oi
        deduped.append((oi, s))
    kept = deduped
    order = {T.HOOK: 0, T.TITLE: 1}
    head = sorted([item for item in kept if item[1].type in order], key=lambda it: order[it[1].type])
    ends = [item for item in kept if item[1].type == T.END]
    body = [item for item in kept if item[1].type not in order and item[1].type != T.END]
    new = head + body + ends
    if [id(s) for _, s in new] != [id(s) for _, s in kept]:
        ctx.issue("order", "$.scenes", "HOOK must open, TITLE must follow it, END must close", "warning",
                  "reordered")
    if not ends:
        new.append((-1, StoryScene(type=T.END, refs=[], vo="", label="")))
        ctx.issue("missing_end", "$.scenes", "storyboard has no END scene", "warning", "appended END")
    while True:
        n = len(new)
        limit = max_type_count(n)
        counts: dict[SceneType, list[int]] = {}
        for k, (_, s) in enumerate(new):
            counts.setdefault(SceneType(s.type), []).append(k)
        over = [(st, ks) for st, ks in counts.items() if len(ks) > limit and st not in SINGLETONS]
        if not over or n <= 3:
            break
        st, ks = max(over, key=lambda it: len(it[1]))
        drop = ks[-1]
        ctx.issue("type_share", f"$.scenes[{new[drop][0]}]",
                  f"too many {st.value} scenes ({len(ks)} of {n}; max {limit})", fix="scene dropped")
        new.pop(drop)
    return new


def scene_role(scene: StoryScene, facts: SessionFacts, product: Product | None) -> str:
    """'product' (shows the product), 'build' (tells how it was made) or 'frame' (title/end/quote)."""
    st = SceneType(scene.type)
    if st in (T.TITLE, T.END, T.CALLOUT):
        return "frame"
    if st in (T.HOOK, T.FEATURE, T.SCROLL, T.SCREEN):
        return "product"
    no_product_shots = not facts.visuals() and not any(is_demo_run(e) for e in facts.events)
    if st == T.BEFORE_AFTER:
        # two product states (images), or a bug fix whose fix is the deliverable; a red-then-green test run
        # next to a real product is build proof
        shots = any(e is not None and image_of(e) is not None for e in (facts.get(r) for r in scene.refs))
        return "product" if shots or no_product_shots else "build"
    ev = facts.get(scene.refs[0]) if scene.refs else None
    if st == T.TERMINAL and ev is not None:
        cmd = str((ev.data or {}).get("cmd") or "")
        runs = {normalize_ws(c) for c in (product.run_commands if product else [])}
        if normalize_ws(cmd) in runs or (is_demo_run(ev) and not is_test_cmd(cmd)):
            return "product"
        return "build"
    if st == T.CODE and ev is not None and product is not None and product.kind in ("library", "api"):
        path = str((ev.data or {}).get("path", ""))
        if any(path.endswith(f) or f.endswith(path) for f in product.entry_files) or "example" in path.lower() \
                or path.lower().endswith("readme.md"):
            return "product"
    if st == T.DIFF and no_product_shots:
        return "product"  # a bug fix: the change itself is the deliverable
    return "build" if st in BUILD_TYPES or st in (T.TERMINAL, T.CODE) else "frame"


def _product_evidence(scene: StoryScene, facts: SessionFacts, product: Product) -> bool:
    if not scene.refs:
        return False
    ev = facts.get(scene.refs[0])
    if ev is None:
        return False
    return image_of(ev) is not None or (ev.kind == "terminal" and scene_role(
        StoryScene(T.TERMINAL, [ev.id]), facts, product) == "product")


def _check_product_film(kept: list[tuple[int, StoryScene]], ctx: _Ctx) -> list[tuple[int, StoryScene]]:
    facts, product = ctx.facts, ctx.product
    # HOOK should show the product when the session has product evidence
    hooks = [s for _, s in kept if s.type == T.HOOK]
    best = _best_product_ref(facts, product)
    if hooks and best and not _product_evidence(hooks[0], facts, product):
        ctx.issue("hook_not_product", "$.scenes[0]", "a product film opens on the product doing its best thing",
                  "warning", f"hook now shows {best}")
        hooks[0].refs = [best]
    # build story <= 45 % of content scenes
    while True:
        content = [(k, s) for k, (_, s) in enumerate(kept) if scene_role(s, facts, product) != "frame"]
        build = [(k, s) for k, s in content if scene_role(s, facts, product) == "build"]
        n_product = len(content) - len(build)
        if not content or n_product == 0 or len(build) / len(content) <= MAX_BUILD_SHARE or len(build) <= 1:
            break
        prio = DROP_PRIORITY["product"]
        k, s = min(build, key=lambda ks: (prio[SceneType(ks[1].type)], -ks[0]))
        ctx.issue("build_heavy", f"$.scenes[{kept[k][0]}]",
                  f"product films keep the build story short ({len(build)} of {len(content)} content scenes)",
                  fix=f"{SceneType(s.type).value} dropped")
        kept.pop(k)
    return kept


def _picture_keys(ev: Event) -> set[str]:
    """Identity keys of a picture: its file stem without the ``e123_`` asset prefix, its source file, its hash."""
    import re as _re
    d = ev.data or {}
    keys: set[str] = set()
    for raw in (d.get("path"), d.get("preview_path"), d.get("src"), d.get("page_title"),
                d.get("url") if ev.kind == "product_capture" and d.get("target_kind") == "image" else None):
        if raw:
            stem = _re.sub(r"^e\d+_", "", str(raw).replace("\\", "/").rsplit("/", 1)[-1]).rsplit(".", 1)[0].lower()
            if stem and stem not in ("image", "poster", "frame"):
                keys.add("n:" + stem)
    h = ((d.get("media_rank") or {}).get("hash"))
    if h:
        keys.add("h:" + str(h))
    return keys


#: picture shots a product film aims for: one per ~10 s, at most 6 (a gallery, not a slideshow)
PICTURES_PER_S = 1 / 10
MAX_PICTURES = 6


def _enrich_pictures(kept: list[tuple[int, StoryScene]], ctx: _Ctx, target_seconds: float) -> list[tuple[int, StoryScene]]:
    """A product film with real pictures shows them: when the storyboard uses fewer picture shots than the film
    has room for and the session has ranked, unused real shots (session.mediarank), add silent SCREEN beats of
    the best ones right after the last picture shot (they cross-dissolve; no padding: never a set-aside picture,
    never a repeat). Without such pictures nothing is added and type/stat beats carry the film."""
    facts = ctx.facts
    if not any((e.data or {}).get("media_rank") for e in facts.events):
        return kept                      # an unranked session (older saved jobs, fixtures): unchanged
    pic_types = (T.HOOK, T.SCREEN, T.FEATURE, T.SCROLL)
    shown = [sc.refs[0] for _, sc in kept if sc.type in pic_types and sc.refs]
    want = min(MAX_PICTURES, max(2, round(float(target_seconds or 30) * PICTURES_PER_S)))
    if len(shown) >= want:
        return kept
    used = set(shown)
    seen: set[str] = set()                # one picture = one shot: its captured copies and the file it came from
    for r in shown:
        ev = facts.by_id.get(r)
        if ev is not None:
            seen |= _picture_keys(ev)
            used |= {str(x) for x in (ev.data or {}).get("source_ids") or []}
    cands = []
    for ev in facts.events:
        rank = (ev.data or {}).get("media_rank") or {}
        img = image_of(ev)
        if not rank or img is None or ev.id in used or ev.kind not in accepted_kinds(T.SCREEN):
            continue
        cands.append((float(rank.get("score", 0.5)), ev.t, ev.id, ev))
    cands.sort(key=lambda c: (-c[0], -c[1]))
    adds: list[StoryScene] = []
    for _, _, eid, ev in cands:
        if len(shown) + len(adds) >= want:
            break
        keys = _picture_keys(ev)
        if keys & seen:
            continue
        seen |= keys
        adds.append(StoryScene(T.SCREEN, [eid], "", "", {}))
    if not adds:
        return kept
    last = max((k for k, (_, sc) in enumerate(kept) if sc.type in pic_types), default=None)
    if last is None:
        last = next((k for k, (_, sc) in enumerate(kept) if sc.type == T.TITLE), 0)
    at = last + 1
    idx = kept[last][0] if kept else 0
    ctx.issue("pictures_added", "$.scenes", f"{len(adds)} more of the session's best pictures shown", "warning",
              "added " + ", ".join(sc.refs[0] for sc in adds))
    return kept[:at] + [(idx, sc) for sc in adds] + kept[at:]


def _best_product_ref(facts: SessionFacts, product: Product) -> str:
    for ref in product.hero_event_ids:
        ev = facts.get(ref)
        if ev is not None and image_of(ev) is not None:
            return ref
    visuals = facts.visuals()
    if visuals:
        return max(visuals, key=lambda e: (e.kind == "product_capture", e.weight, facts.order[e.id])).id
    return ""


def chrono_key(scene: StoryScene, facts: SessionFacts) -> float:
    """Session-order position of what a scene shows (montages by their middle event)."""
    refs = [r for r in scene.refs if facts.get(r) is not None]
    if not refs:
        return float("inf")
    if SceneType(scene.type) == T.MONTAGE:
        return facts.order[refs[len(refs) // 2]]
    if SceneType(scene.type) == T.BEFORE_AFTER:
        return facts.order[refs[-1]]
    return facts.order[refs[0]]


def _check_chronology(kept: list[tuple[int, StoryScene]], ctx: _Ctx) -> list[tuple[int, StoryScene]]:
    head = [it for it in kept if it[1].type in (T.HOOK, T.TITLE)]
    tail = [it for it in kept if it[1].type == T.END]
    body = [it for it in kept if it[1].type not in (T.HOOK, T.TITLE, T.END)]
    ordered = sorted(body, key=lambda it: (chrono_key(it[1], ctx.facts), 0 if it[1].type != T.STATS else 1))
    if [id(s) for _, s in ordered] != [id(s) for _, s in body]:
        ctx.issue("chronology", "$.scenes", f"{ctx.mode} films tell the session in the order it happened",
                  "warning", "reordered by event time")
    return head + ordered + tail


def _check_splits(kept: list[tuple[int, StoryScene]], ctx: _Ctx) -> None:
    facts = ctx.facts
    last_t = -1.0
    labelled: list[StoryScene] = []
    for oi, s in kept:
        label = s.extra.get("split")
        if not label:
            continue
        ev = facts.get(s.refs[0]) if s.refs else None
        if ev is None or ev.t <= last_t:
            ctx.issue("split_order", f"$.scenes[{oi}].extra.split",
                      "splits need a milestone event later than the previous split", "warning", "removed")
            s.extra.pop("split", None)
            continue
        if len(label) > SPLIT_CHARS:
            s.extra["split"] = label[:SPLIT_CHARS].rstrip()
            ctx.issue("split_long", f"$.scenes[{oi}].extra.split", f"longer than {SPLIT_CHARS} characters",
                      "warning", "trimmed")
        last_t = ev.t
        labelled.append(s)
    if len(labelled) > SPLITS_MAX:
        keep = {id(labelled[0]), id(labelled[-1])} | {id(x) for x in labelled[1:SPLITS_MAX - 1]}
        for s in labelled:
            if id(s) not in keep:
                s.extra.pop("split", None)
        ctx.issue("splits_many", "$.scenes", f"more than {SPLITS_MAX} splits", "warning", "kept the first and last")
        labelled = [s for s in labelled if id(s) in keep]
    if len(labelled) < SPLITS_MIN:
        _assign_splits(kept, ctx)


def _assign_splits(kept: list[tuple[int, StoryScene]], ctx: _Ctx) -> None:
    """Give unlabelled chronological scenes milestone splits until there are 4-7."""
    facts = ctx.facts
    seen = {s.extra["split"] for _, s in kept if s.extra.get("split")}
    candidates = [s for _, s in kept if s.refs and s.type not in (T.HOOK, T.TITLE, T.END, T.MONTAGE, T.STATS,
                                                                    T.PROBLEM)
                  and facts.get(s.refs[0]) is not None and facts.by_id[s.refs[0]].t > 0]
    for s in candidates:
        if sum(1 for _, x in kept if x.extra.get("split")) >= SPLITS_MAX:
            break
        if s.extra.get("split"):
            continue
        t = facts.by_id[s.refs[0]].t
        times = sorted(facts.by_id[x.refs[0]].t for _, x in kept if x.extra.get("split") and x.refs)
        if t in times:
            continue
        s.extra["split"] = split_label(facts.by_id[s.refs[0]], seen)
    n = sum(1 for _, x in kept if x.extra.get("split"))
    ctx.issue("splits_assigned", "$.scenes", f"speedruns need {SPLITS_MIN}-{SPLITS_MAX} milestone splits",
              "warning", f"now {n} split(s)")
    # keep strictly increasing order after assignment
    last_t = -1.0
    for _, s in kept:
        if s.extra.get("split"):
            t = facts.by_id[s.refs[0]].t
            if t <= last_t:
                s.extra.pop("split", None)
            else:
                last_t = t


def _check_budget(sb: Storyboard, ctx: _Ctx, target_seconds: float) -> None:
    """Over budget by more than a quarter: drop whole trailing sentences from the longest multi-sentence
    lines, then silence the least important narrated scenes. Never cuts a sentence mid-way."""
    budget = narration_budget(target_seconds, ctx.mode)
    total = sum(word_count(s.vo) for s in sb.scenes)
    if total <= int(budget * 1.25):
        return
    ctx.issue("vo_budget", "$.scenes", f"narration is {total} words; budget for {target_seconds:g} s is {budget}",
              "warning", "dropped trailing sentences / silenced minor scenes")
    while total > budget:
        multi = [s for s in sb.scenes if len(sentences(s.vo)) > 1]
        if multi:
            longest = max(multi, key=lambda s: word_count(s.vo))
            longest.vo = " ".join(sentences(longest.vo)[:-1])
        else:
            prio = DROP_PRIORITY[ctx.mode]
            voiced = [(prio[s.type], -i, s) for i, s in enumerate(sb.scenes)
                      if s.vo and s.type not in (T.TITLE, T.END, T.HOOK)]
            if not voiced:
                break
            min(voiced, key=lambda x: (x[0], x[1]))[2].vo = ""
        total = sum(word_count(s.vo) for s in sb.scenes)
