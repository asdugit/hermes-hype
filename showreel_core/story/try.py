"""Dev harness: ``python -m showreel_core.story.try --fixture FILE [--seconds 60] [--style launch]
[--mode product|lore|speedrun] [--llm none|hermes]``.

Prints the storyboard (with its source, fixes and issues) and the solved timeline.

Inputs: ``--fixture`` takes ``{"events": [...], "stats": {...}, "product"?: {...}, "digest"?: "..."}``
(the format of ``tests/story/fixtures/*.json`` and of ``python -m showreel_core.session.inspect --json``);
``--session ID|latest`` analyses a real Hermes session through the session stage instead.

``--llm hermes`` calls the user's configured model through Hermes's real plugin LLM facade
(``agent.plugin_llm`` -> ``agent.auxiliary_client.call_llm``) without touching any config. It must run
under the Hermes venv, e.g.::

    %LOCALAPPDATA%/hermes/hermes-agent/venv/Scripts/python.exe -m showreel_core.story.try \\
        --fixture tests/story/fixtures/coding_session.json --llm hermes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from ..contracts import Event, Product, Stats, Storyboard, Timeline
from .generate import generate_storyboard_report, hermes_llm
from .options import KNOWN_STYLES, StoryOptions
from .prompt import build_input, build_instructions
from .facts import SessionFacts
from .heuristic import infer_product
from .rules import TTS_WORDS_PER_SECOND
from .schema import storyboard_to_json
from .text import word_count
from .timing import solve_timeline

DEFAULT_BPM = 120.0
SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


def _out(text: str = "") -> None:
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(enc, "replace").decode(enc) + "\n")


# ------------------------------------------------------------------------- inputs

def load_fixture(path: str | Path) -> tuple[list[Event], Stats, Product | None, str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    events = [Event(**{k: v for k, v in e.items() if k in Event.__dataclass_fields__}) for e in raw["events"]]
    stats = Stats(**{k: v for k, v in (raw.get("stats") or {}).items() if k in Stats.__dataclass_fields__})
    prod = raw.get("product")
    product = Product(**{k: v for k, v in prod.items() if k in Product.__dataclass_fields__}) if prod else None
    return events, stats, product, str(raw.get("digest") or "")


def load_session(ref: str) -> tuple[list[Event], Stats, Product | None, str]:
    from ..session import analyze_session, resolve_session_ref  # optional: the session stage
    sid = resolve_session_ref(ref)
    if not sid:
        raise SystemExit(f"no session matches {ref!r}")
    b = analyze_session(sid)
    return b.events, b.stats, (b.product if getattr(b, "product_detected", True) else None), b.digest


def style_bpm(style: str) -> float:
    try:
        from ..audio.music import load_beds  # optional: the audio stage's beds carry the real tempo
        beds = load_beds(style)
        if beds:
            return beds[0].bpm
    except Exception:  # noqa: BLE001 - dev harness: any failure means "use the default tempo"
        pass
    return DEFAULT_BPM


def hermes_adapter(root: str | None) -> Any:
    """ctx.llm-equivalent built from Hermes's own plugin LLM facade (dev only; no config changes)."""
    root = root or os.environ.get("HERMES_AGENT_ROOT") or str(
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "hermes-agent")
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from agent.plugin_llm import _TrustPolicy, make_plugin_llm_for_test
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(f"--llm hermes needs the Hermes venv and agent code at {root}: {exc}") from exc
    plugin_llm = make_plugin_llm_for_test(plugin_id="showreel-dev", policy=_TrustPolicy(plugin_id="showreel-dev"))
    return hermes_llm(plugin_llm, task=None)


# ------------------------------------------------------------------------- printing

def print_storyboard(sb: Storyboard) -> None:
    p = sb.product
    _out(f"STORYBOARD  source={sb.source}  mode={sb.mode}  scenes={len(sb.scenes)}")
    _out(f"  title   {sb.title!r}\n  tagline {sb.tagline!r}\n  cta     {sb.cta!r}  url={sb.url!r}")
    if p is not None:
        _out(f"  product {p.name!r} ({p.kind}) - {p.one_liner!r}")
        _out(f"          features={p.features} run={p.run_commands} urls={p.urls} heroes={p.hero_event_ids}")
    words = 0
    for i, s in enumerate(sb.scenes):
        words += word_count(s.vo)
        extra = f"  {json.dumps(s.extra, ensure_ascii=False)}" if s.extra else ""
        _out(f"  [{i:2d}] {s.type.value:12s} refs={','.join(s.refs) or '-':18s} label={s.label!r}{extra}")
        if s.vo:
            _out(f"       vo: {s.vo}")
    _out(f"  narration: {words} words")


def _data_brief(sc: Any) -> str:
    d = sc.data
    if "lines" in d and "start" in d:
        return f"{d.get('path', '')} L{d['start']}-{d['start'] + len(d['lines']) - 1} focus={d.get('focus')}"
    if "hunks" in d:
        return f"{d.get('path', '')} {len(d['hunks'])} hunks / {sum(len(h['lines']) for h in d['hunks'])} lines"
    if "output" in d:
        return f"$ {d.get('cmd', '')[:60]}  ({len(d['output'])} lines)"
    if "stats" in d:
        return ", ".join(f"{r['label']}={r['display']}" for r in d["stats"])
    if "image" in d:
        return f"{Path(str(d['image'].get('path', ''))).name} bbox={d.get('bbox')}"
    if "items" in d:
        return f"{len(d['items'])} items"
    if "text" in d:
        return repr(str(d["text"])[:70])
    return ", ".join(sorted(k for k in d if k != "story_index"))


def print_timeline(tl: Timeline) -> None:
    _out(f"TIMELINE  {tl.dur:.2f}s  bpm={tl.bpm:g}  mode={tl.mode}  {tl.w}x{tl.h}@{tl.fps}  scenes={len(tl.scenes)}")
    for sc in tl.scenes:
        vo = f" vo@{sc.vo_t0:.2f}" if sc.captions else ""
        _out(f"  {sc.t0:6.2f}-{sc.t1:6.2f} {sc.type.value:12s} {sc.transition_in:5s}{vo:10s} {_data_brief(sc)}")
    if tl.splits:
        _out("  splits: " + "  ".join(f"{s.label}@{s.film_t:.2f}s(real {s.session_t:.0f}s)" for s in tl.splits))
    _out("  cues:   " + "  ".join(f"{c.sfx}@{c.t:.2f}" for c in tl.cues))


# ------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m showreel_core.story.try", description=(__doc__ or "").splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fixture", help="events/stats JSON file")
    src.add_argument("--session", help="Hermes session id, prefix or 'latest' (needs the session stage)")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--style", default="launch", choices=sorted(KNOWN_STYLES))
    ap.add_argument("--mode", default="product", help="product | making_of (lore, bts, process) | speedrun")
    ap.add_argument("--aspect", default="16:9", choices=sorted(SIZES))
    ap.add_argument("--bpm", type=float, help="music tempo (default: the style's bed, else 120)")
    ap.add_argument("--llm", default="none", choices=("none", "hermes"))
    ap.add_argument("--hermes-root", help="hermes-agent checkout (default: %%LOCALAPPDATA%%/hermes/hermes-agent)")
    ap.add_argument("--no-voice", action="store_true", help="captions only")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--brief", default="", help="extra direction from the user")
    ap.add_argument("--prompt", action="store_true", help="print the prompt and exit")
    ap.add_argument("--json", help="write {storyboard, timeline, report} to this file")
    args = ap.parse_args(argv)

    events, stats, product, digest = load_fixture(args.fixture) if args.fixture else load_session(args.session)
    opts = StoryOptions(seconds=args.seconds, style=args.style, aspect=args.aspect, mode=args.mode,
                        voice=not args.no_voice, brief=args.brief)
    if args.prompt:
        facts = SessionFacts(events, stats, digest)
        _out(build_instructions(opts))
        _out("=" * 72)
        _out(build_input(digest, facts, opts, product or infer_product(facts)))
        return 0

    llm = hermes_adapter(args.hermes_root) if args.llm == "hermes" else None
    t0 = time.perf_counter()
    report = generate_storyboard_report(llm, digest, events, stats, opts, product)
    gen_s = time.perf_counter() - t0
    sb = report.storyboard
    for a in report.attempts:
        _out(f"attempt {a.kind}: accepted={a.accepted} {a.seconds:.1f}s {a.model} "
             f"tokens={a.usage.get('total_tokens', '?')}")
        for prob in a.problems[:12]:
            _out(f"   - {prob}")
    for fix in report.fixes:
        _out(f"fix: {fix}")
    _out(f"generated in {gen_s:.2f}s")
    print_storyboard(sb)

    bpm = args.bpm or style_bpm(args.style)
    voice = {} if args.no_voice else {
        i: round(word_count(s.vo) / TTS_WORDS_PER_SECOND, 3) for i, s in enumerate(sb.scenes) if s.vo}
    w, h = SIZES[args.aspect]
    tl = solve_timeline(sb, events, stats, voice, bpm, opts.clamped_seconds(), args.aspect, 30, w, h, args.seed,
                        style=args.style)
    print_timeline(tl)
    if args.json:
        out = {"storyboard": storyboard_to_json(sb), "source": sb.source, "timeline": tl.to_dict(),
               "attempts": [vars(a) for a in report.attempts], "fixes": report.fixes, "issues": report.issues}
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n",
                                   encoding="utf-8", newline="\n")
        _out(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
